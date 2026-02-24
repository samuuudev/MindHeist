"""
Cog de Robo PvP — /robar @usuario
Sistema de robos con preguntas, riesgo/recompensa y protecciones.
"""

import random
import asyncio
import json
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands
import logging

log = logging.getLogger("bot.robbery")


# ── Vista de robo (solo el atacante puede responder) ───────────
class RobberyView(discord.ui.View):
    """Botones para la pregunta del robo. Solo el atacante responde."""

    EMOJI_LETTERS = ["🅰️", "🅱️", "🅲", "🅳"]

    def __init__(self, question_data: dict, attacker_id: int):
        super().__init__(timeout=20)  # 20 segundos para robo
        self.question_data = question_data
        self.attacker_id = attacker_id
        self.answered = False
        self.selected_index: int | None = None
        self.is_correct: bool = False
        self.response_time: float = 0.0
        self._start_time = datetime.utcnow()

        for i, option in enumerate(question_data["options"]):
            button = discord.ui.Button(
                label=option,
                emoji=self.EMOJI_LETTERS[i],
                style=discord.ButtonStyle.secondary,
                custom_id=f"rob_option_{i}",
                row=i // 2,
            )
            button.callback = self._make_callback(i)
            self.add_item(button)

    def _make_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.attacker_id:
                await interaction.response.send_message(
                    "❌ Este robo no es tuyo. Solo el ladrón puede responder.",
                    ephemeral=True,
                )
                return

            if self.answered:
                await interaction.response.send_message(
                    "Ya has respondido.", ephemeral=True
                )
                return

            self.answered = True
            self.selected_index = index
            self.is_correct = index == self.question_data["correct_index"]
            self.response_time = (
                datetime.utcnow() - self._start_time
            ).total_seconds()

            for i, child in enumerate(self.children):
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
                    if i == self.question_data["correct_index"]:
                        child.style = discord.ButtonStyle.success
                    elif i == index and not self.is_correct:
                        child.style = discord.ButtonStyle.danger

            await interaction.response.edit_message(view=self)
            self.stop()

        return callback

    async def on_timeout(self):
        self.answered = False
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
                idx = int(child.custom_id.split("_")[-1])
                if idx == self.question_data["correct_index"]:
                    child.style = discord.ButtonStyle.success
        self.stop()


# ── Cog principal ──────────────────────────────────────────────
class RobberyCog(commands.Cog):
    """Sistema de robo PvP con preguntas."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._generator = None

    @property
    def generator(self):
        if self._generator is None:
            quiz_cog = self.bot.get_cog("QuizCog")
            if quiz_cog:
                self._generator = quiz_cog.generator
            else:
                from cogs.quiz import QuestionGenerator
                self._generator = QuestionGenerator()
        return self._generator

    # ════════════════════════════════════════════════════════════
    # /robar @usuario
    # ════════════════════════════════════════════════════════════
    @app_commands.command(
        name="robar",
        description="🗡️ Intenta robar puntos a otro jugador respondiendo una pregunta",
    )
    @app_commands.describe(victim="El jugador al que quieres robar")
    async def rob(
        self,
        interaction: discord.Interaction,
        victim: discord.Member,
    ):
        attacker = interaction.user
        guild_id = interaction.guild_id

        # ══════════════════════════════════════════════════════
        # VALIDACIONES
        # ══════════════════════════════════════════════════════

        # No robarte a ti mismo
        if victim.id == attacker.id:
            await interaction.response.send_message(
                "❌ No puedes robarte a ti mismo... ¿o sí? 🤔",
                ephemeral=True,
            )
            return

        # No robar a bots
        if victim.bot:
            await interaction.response.send_message(
                "❌ Los bots no tienen dinero. Buen intento.",
                ephemeral=True,
            )
            return

        # Obtener configuración
        config = await self._get_config(guild_id)
        if not config:
            async with self.bot.db.acquire() as conn:
                await conn.execute(
                    "INSERT INTO guild_config (guild_id) VALUES ($1) ON CONFLICT DO NOTHING;",
                    guild_id,
                )
                config = await self._get_config(guild_id)

        # Obtener/crear usuarios
        attacker_data = await self._ensure_user(attacker.id, guild_id, attacker.display_name)
        victim_data = await self._ensure_user(victim.id, guild_id, victim.display_name)

        # ── Protección: usuario nuevo (menos de 24h) ───────────
        if victim_data["created_at"] > datetime.utcnow() - timedelta(hours=24):
            await interaction.response.send_message(
                f"🛡️ **{victim.display_name}** es un jugador nuevo y tiene protección de 24h.",
                ephemeral=True,
            )
            return

        # ── Protección: víctima tiene escudo activo ────────────
        if victim_data["shield_until"] and victim_data["shield_until"] > datetime.utcnow():
            remaining = victim_data["shield_until"] - datetime.utcnow()
            mins = int(remaining.total_seconds() / 60)
            await interaction.response.send_message(
                f"🛡️ **{victim.display_name}** tiene un escudo activo. "
                f"Expira en **{mins} minutos**.",
                ephemeral=True,
            )
            return

        # ── Protección: víctima no tiene suficiente dinero ─────
        min_money = config["min_money_to_rob"]
        if victim_data["money"] < min_money:
            await interaction.response.send_message(
                f"💸 **{victim.display_name}** tiene menos de **{min_money}** monedas. "
                f"No vale la pena robarlo.",
                ephemeral=True,
            )
            return

        # ── Cooldown de robo ───────────────────────────────────
        cooldown_min = config["robbery_cooldown_min"]
        if attacker_data["last_robbery"]:
            elapsed = (datetime.utcnow() - attacker_data["last_robbery"]).total_seconds()
            remaining = (cooldown_min * 60) - elapsed
            if remaining > 0:
                mins = int(remaining // 60)
                secs = int(remaining % 60)
                await interaction.response.send_message(
                    f"⏳ Debes esperar **{mins}m {secs}s** antes de intentar otro robo.",
                    ephemeral=True,
                )
                return

        # ── Límite diario de robos ─────────────────────────────
        max_daily = config["max_robberies_daily"]
        if attacker_data["robberies_today"] >= max_daily:
            await interaction.response.send_message(
                f"🚫 Ya usaste tus **{max_daily} robos** de hoy. Vuelve mañana.",
                ephemeral=True,
            )
            return

        # ══════════════════════════════════════════════════════
        # ROBO EN CURSO
        # ══════════════════════════════════════════════════════
        await interaction.response.defer(thinking=True)

        # Generar pregunta
        question_data = await self.generator.generate(
            difficulty=random.choice(["medium", "hard"]),
            category=None,
        )

        if not question_data:
            await interaction.followup.send(
                "❌ No se pudo generar una pregunta. Inténtalo de nuevo.",
                ephemeral=True,
            )
            return

        # Guardar pregunta
        question_id = await self._save_question(question_data)

        # Calcular cuánto se puede robar
        rob_min_pct = config["robbery_min_pct"]  # 0.10
        rob_max_pct = config["robbery_max_pct"]  # 0.20
        rob_fail_pct = config["robbery_fail_pct"]  # 0.05

        steal_pct = random.uniform(rob_min_pct, rob_max_pct)
        potential_steal = max(1, int(victim_data["money"] * steal_pct))
        potential_loss = max(1, int(attacker_data["money"] * rob_fail_pct))

        # Embed de la pregunta
        embed = discord.Embed(
            title="🗡️ ¡Intento de robo!",
            description=(
                f"**{attacker.display_name}** intenta robar a **{victim.display_name}**!\n\n"
                f"Responde correctamente para completar el robo:\n\n"
                f"**{question_data['question']}**"
            ),
            color=discord.Color.dark_red(),
        )
        embed.add_field(
            name="💰 Si aciertas",
            value=f"Robas **{potential_steal}** monedas + **5 pts**",
            inline=True,
        )
        embed.add_field(
            name="💸 Si fallas",
            value=f"Pierdes **{potential_loss}** monedas + **3 pts**",
            inline=True,
        )
        embed.add_field(
            name="⏱️ Tiempo",
            value="**20 segundos**",
            inline=True,
        )
        embed.set_footer(text=f"Solo {attacker.display_name} puede responder")

        # Enviar con botones
        view = RobberyView(question_data, attacker.id)
        await interaction.followup.send(
            content=f"{victim.mention} ¡Están intentando robarte! 👀",
            embed=embed,
            view=view,
        )

        # Actualizar cooldown y contador
        async with self.bot.db.acquire() as conn:
            await conn.execute("""
                UPDATE users
                SET last_robbery = NOW(),
                    robberies_today = robberies_today + 1,
                    updated_at = NOW()
                WHERE user_id = $1 AND guild_id = $2;
            """, attacker.id, guild_id)

        # Esperar respuesta
        timed_out = await view.wait()

        # ══════════════════════════════════════════════════════
        # RESULTADO
        # ══════════════════════════════════════════════════════

        if timed_out or not view.answered:
            # ── Timeout = fallo ────────────────────────────────
            await self._process_robbery_fail(
                interaction, attacker, victim, guild_id,
                question_id, question_data, potential_loss, config,
                response_time=20.0, answered_index=-1,
                reason="timeout",
            )
            return

        if view.is_correct:
            # ── Robo exitoso ───────────────────────────────────
            await self._process_robbery_success(
                interaction, attacker, victim, guild_id,
                question_id, question_data, potential_steal, config,
                view.response_time, view.selected_index,
            )
        else:
            # ── Robo fallido ───────────────────────────────────
            await self._process_robbery_fail(
                interaction, attacker, victim, guild_id,
                question_id, question_data, potential_loss, config,
                view.response_time, view.selected_index,
                reason="wrong",
            )

    # ════════════════════════════════════════════════════════════
    # Procesar robo exitoso
    # ════════════════════════════════════════════════════════════
    async def _process_robbery_success(
        self, interaction, attacker, victim, guild_id,
        question_id, question_data, stolen_amount, config,
        response_time, answered_index,
    ):
        """Robo exitoso: transfiere dinero, da puntos, registra todo."""
        points_gained = 5

        async with self.bot.db.acquire() as conn:
            # Re-verificar dinero de la víctima (lock transaccional)
            victim_money = await conn.fetchval(
                "SELECT money FROM users WHERE user_id = $1 AND guild_id = $2 FOR UPDATE;",
                victim.id, guild_id,
            )

            # Ajustar si la víctima tiene menos de lo calculado
            actual_stolen = min(stolen_amount, victim_money)
            if actual_stolen <= 0:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="😅 Robo vacío",
                        description=f"**{victim.display_name}** ya no tiene dinero. Mala suerte.",
                        color=discord.Color.greyple(),
                    )
                )
                return

            # Quitar dinero a la víctima
            await conn.execute("""
                UPDATE users
                SET money = money - $3, updated_at = NOW()
                WHERE user_id = $1 AND guild_id = $2;
            """, victim.id, guild_id, actual_stolen)

            # Dar dinero y puntos al atacante
            await conn.execute("""
                UPDATE users
                SET money = money + $3,
                    points = points + $4,
                    updated_at = NOW()
                WHERE user_id = $1 AND guild_id = $2;
            """, attacker.id, guild_id, actual_stolen, points_gained)

            # Registrar robo
            await conn.execute("""
                INSERT INTO robberies
                    (attacker_id, victim_id, guild_id, question_id, success, money_stolen, points_change)
                VALUES ($1, $2, $3, $4, TRUE, $5, $6);
            """, attacker.id, victim.id, guild_id, question_id, actual_stolen, points_gained)

            # Transacción del atacante
            await conn.execute("""
                INSERT INTO transactions
                    (user_id, guild_id, tx_type, points_delta, money_delta, description)
                VALUES ($1, $2, 'rob_win', $3, $4, $5);
            """, attacker.id, guild_id, points_gained, actual_stolen,
                f"Robo exitoso a {victim.display_name}",
            )

            # Transacción de la víctima
            await conn.execute("""
                INSERT INTO transactions
                    (user_id, guild_id, tx_type, points_delta, money_delta, description)
                VALUES ($1, $2, 'rob_lose', 0, $3, $4);
            """, victim.id, guild_id, -actual_stolen,
                f"Robado por {attacker.display_name}",
            )

            # Historial de respuesta
            await conn.execute("""
                INSERT INTO answer_history
                    (user_id, guild_id, question_id, answered_index, is_correct,
                     points_earned, context, response_time)
                VALUES ($1, $2, $3, $4, TRUE, $5, 'robbery', $6);
            """, attacker.id, guild_id, question_id, answered_index,
                points_gained, response_time,
            )

        # Embed de éxito
        embed = discord.Embed(
            title="🗡️💰 ¡Robo exitoso!",
            description=(
                f"**{attacker.display_name}** ha robado a **{victim.display_name}**!\n\n"
                f"💰 Monedas robadas: **+{actual_stolen}**\n"
                f"🏆 Puntos ganados: **+{points_gained}**\n"
                f"⏱️ Tiempo de respuesta: **{response_time:.1f}s**"
            ),
            color=discord.Color.dark_red(),
        )
        embed.set_thumbnail(
            url="https://em-content.zobj.net/source/twitter/376/money-bag_1f4b0.png"
        )

        await interaction.followup.send(embed=embed)

    # ════════════════════════════════════════════════════════════
    # Procesar robo fallido
    # ════════════════════════════════════════════════════════════
    async def _process_robbery_fail(
        self, interaction, attacker, victim, guild_id,
        question_id, question_data, loss_amount, config,
        response_time, answered_index, reason="wrong",
    ):
        """Robo fallido: pierde dinero y puntos."""
        points_lost = 3

        async with self.bot.db.acquire() as conn:
            # Verificar dinero actual del atacante
            attacker_money = await conn.fetchval(
                "SELECT money FROM users WHERE user_id = $1 AND guild_id = $2 FOR UPDATE;",
                attacker.id, guild_id,
            )

            actual_loss = min(loss_amount, max(0, attacker_money))

            # Quitar dinero y puntos al atacante
            await conn.execute("""
                UPDATE users
                SET money = GREATEST(0, money - $3),
                    points = GREATEST(0, points - $4),
                    updated_at = NOW()
                WHERE user_id = $1 AND guild_id = $2;
            """, attacker.id, guild_id, actual_loss, points_lost)

            # Registrar robo fallido
            await conn.execute("""
                INSERT INTO robberies
                    (attacker_id, victim_id, guild_id, question_id, success, money_stolen, points_change)
                VALUES ($1, $2, $3, $4, FALSE, $5, $6);
            """, attacker.id, victim.id, guild_id, question_id, -actual_loss, -points_lost)

            # Transacción
            await conn.execute("""
                INSERT INTO transactions
                    (user_id, guild_id, tx_type, points_delta, money_delta, description)
                VALUES ($1, $2, 'rob_fail', $3, $4, $5);
            """, attacker.id, guild_id, -points_lost, -actual_loss,
                f"Robo fallido contra {victim.display_name}",
            )

            # Historial de respuesta
            await conn.execute("""
                INSERT INTO answer_history
                    (user_id, guild_id, question_id, answered_index, is_correct,
                     points_earned, context, response_time)
                VALUES ($1, $2, $3, $4, FALSE, $5, 'robbery', $6);
            """, attacker.id, guild_id, question_id, answered_index,
                -points_lost, response_time,
            )

        # Embed de fallo
        correct_answer = question_data["options"][question_data["correct_index"]]

        if reason == "timeout":
            title = "⏰🗡️ ¡Robo fallido — Tiempo agotado!"
            extra = "No respondiste a tiempo."
        else:
            title = "❌🗡️ ¡Robo fallido!"
            extra = f"Respuesta incorrecta."

        embed = discord.Embed(
            title=title,
            description=(
                f"**{attacker.display_name}** intentó robar a **{victim.display_name}** "
                f"y **fracasó**.\n\n"
                f"{extra}\n"
                f"La respuesta correcta era: **{correct_answer}**\n\n"
                f"💸 Monedas perdidas: **-{actual_loss}**\n"
                f"📉 Puntos perdidos: **-{points_lost}**"
            ),
            color=discord.Color.orange(),
        )
        embed.set_thumbnail(
            url="https://em-content.zobj.net/source/twitter/376/police-officer_1f46e.png"
        )

        await interaction.followup.send(embed=embed)

    # ════════════════════════════════════════════════════════════
    # /escudo — Comprar protección contra robos
    # ════════════════════════════════════════════════════════════
    @app_commands.command(
        name="escudo",
        description="🛡️ Compra un escudo temporal contra robos",
    )
    @app_commands.describe(
        duration="Duración del escudo",
    )
    @app_commands.choices(
        duration=[
            app_commands.Choice(name="🛡️ 1 hora — 50 monedas", value="1h"),
            app_commands.Choice(name="🛡️ 6 horas — 200 monedas", value="6h"),
            app_commands.Choice(name="🛡️ 24 horas — 500 monedas", value="24h"),
        ],
    )
    async def shield(
        self,
        interaction: discord.Interaction,
        duration: str = "1h",
    ):
        user_id = interaction.user.id
        guild_id = interaction.guild_id

        # Precios y duración
        shield_options = {
            "1h":  {"hours": 1,  "cost": 50,  "name": "1 hora"},
            "6h":  {"hours": 6,  "cost": 200, "name": "6 horas"},
            "24h": {"hours": 24, "cost": 500, "name": "24 horas"},
        }

        option = shield_options[duration]

        async with self.bot.db.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id = $1 AND guild_id = $2",
                user_id, guild_id,
            )

            if not user:
                await interaction.response.send_message(
                    "❌ Aún no has jugado ninguna partida. Usa `/quiz` o `/daily` primero.",
                    ephemeral=True,
                )
                return

            # Ya tiene escudo activo
            if user["shield_until"] and user["shield_until"] > datetime.utcnow():
                remaining = user["shield_until"] - datetime.utcnow()
                hours = int(remaining.total_seconds() / 3600)
                mins = int((remaining.total_seconds() % 3600) / 60)
                await interaction.response.send_message(
                    f"🛡️ Ya tienes un escudo activo. Expira en **{hours}h {mins}m**.",
                    ephemeral=True,
                )
                return

            # Verificar dinero
            if user["money"] < option["cost"]:
                await interaction.response.send_message(
                    f"💸 No tienes suficiente dinero. "
                    f"Necesitas **{option['cost']}** monedas, tienes **{user['money']}**.",
                    ephemeral=True,
                )
                return

            # Comprar escudo
            expires = datetime.utcnow() + timedelta(hours=option["hours"])

            await conn.execute("""
                UPDATE users
                SET money = money - $3,
                    shield_until = $4,
                    updated_at = NOW()
                WHERE user_id = $1 AND guild_id = $2;
            """, user_id, guild_id, option["cost"], expires)

            await conn.execute("""
                INSERT INTO transactions
                    (user_id, guild_id, tx_type, points_delta, money_delta, description)
                VALUES ($1, $2, 'shield', 0, $3, $4);
            """, user_id, guild_id, -option["cost"],
                f"Escudo de {option['name']} comprado",
            )

        embed = discord.Embed(
            title="🛡️ ¡Escudo activado!",
            description=(
                f"Estás protegido contra robos durante **{option['name']}**.\n\n"
                f"💸 Coste: **{option['cost']}** monedas\n"
                f"⏰ Expira: <t:{int(expires.timestamp())}:R>"
            ),
            color=discord.Color.blue(),
        )

        await interaction.response.send_message(embed=embed)

    # ════════════════════════════════════════════════════════════
    # /robos — Historial de robos
    # ════════════════════════════════════════════════════════════
    @app_commands.command(
        name="robos",
        description="📜 Mira tu historial de robos recientes",
    )
    async def robbery_history(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        guild_id = interaction.guild_id

        async with self.bot.db.acquire() as conn:
            # Últimos 10 robos (como atacante o víctima)
            history = await conn.fetch("""
                SELECT r.*, 
                    a.username AS attacker_name,
                    v.username AS victim_name
                FROM robberies r
                JOIN users a ON r.attacker_id = a.user_id
                JOIN users v ON r.victim_id = v.user_id
                WHERE r.guild_id = $1 
                  AND (r.attacker_id = $2 OR r.victim_id = $2)
                ORDER BY r.created_at DESC
                LIMIT 10;
            """, guild_id, user_id)

            # Stats generales
            stats = await conn.fetchrow("""
                SELECT
                    COUNT(*) FILTER (WHERE attacker_id = $1) AS attacks,
                    COUNT(*) FILTER (WHERE attacker_id = $1 AND success) AS attack_wins,
                    COUNT(*) FILTER (WHERE victim_id = $1) AS times_robbed,
                    COUNT(*) FILTER (WHERE victim_id = $1 AND success) AS times_lost,
                    COALESCE(SUM(money_stolen) FILTER (WHERE attacker_id = $1 AND success), 0) AS total_stolen,
                    COALESCE(SUM(money_stolen) FILTER (WHERE victim_id = $1 AND success), 0) AS total_lost_to
                FROM robberies
                WHERE guild_id = $2 AND (attacker_id = $1 OR victim_id = $1);
            """, user_id, guild_id)

            # Robos restantes hoy
            user = await conn.fetchrow(
                "SELECT robberies_today FROM users WHERE user_id = $1 AND guild_id = $2",
                user_id, guild_id,
            )

        config = await self._get_config(guild_id)
        max_daily = config["max_robberies_daily"] if config else 3
        remaining_today = max_daily - (user["robberies_today"] if user else 0)

        embed = discord.Embed(
            title=f"📜 Historial de robos — {interaction.user.display_name}",
            color=discord.Color.dark_red(),
        )

        # Stats
        if stats and stats["attacks"] > 0:
            attack_rate = (stats["attack_wins"] / stats["attacks"]) * 100 if stats["attacks"] > 0 else 0
            embed.add_field(
                name="⚔️ Como atacante",
                value=(
                    f"Intentos: **{stats['attacks']}**\n"
                    f"Éxitos: **{stats['attack_wins']}** ({attack_rate:.0f}%)\n"
                    f"Dinero robado: **{stats['total_stolen']:,}** 💰"
                ),
                inline=True,
            )

        if stats and stats["times_robbed"] > 0:
            embed.add_field(
                name="🛡️ Como víctima",
                value=(
                    f"Veces atacado: **{stats['times_robbed']}**\n"
                    f"Veces robado: **{stats['times_lost']}**\n"
                    f"Dinero perdido: **{stats['total_lost_to']:,}** 💰"
                ),
                inline=True,
            )

        embed.add_field(
            name="📅 Robos hoy",
            value=f"**{remaining_today}/{max_daily}** restantes",
            inline=True,
        )

        # Historial
        if history:
            history_text = ""
            for row in history:
                time_str = f"<t:{int(row['created_at'].timestamp())}:R>"
                if row["attacker_id"] == user_id:
                    if row["success"]:
                        history_text += f"✅ Robaste **{row['money_stolen']}** 💰 a {row['victim_name']} · {time_str}\n"
                    else:
                        history_text += f"❌ Fallo al robar a {row['victim_name']} · perdiste **{abs(row['money_stolen'])}** 💰 · {time_str}\n"
                else:
                    if row["success"]:
                        history_text += f"🗡️ {row['attacker_name']} te robó **{row['money_stolen']}** 💰 · {time_str}\n"
                    else:
                        history_text += f"🛡️ {row['attacker_name']} intentó robarte y falló · {time_str}\n"

            embed.add_field(
                name="📋 Últimos robos",
                value=history_text or "Sin robos aún",
                inline=False,
            )
        else:
            embed.add_field(
                name="📋 Historial",
                value="Sin robos aún. ¡Usa `/robar @usuario` para empezar!",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)

    # ── Métodos auxiliares de base de datos ─────────────────────
    async def _get_config(self, guild_id: int) -> dict | None:
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM guild_config WHERE guild_id = $1", guild_id
            )
            return dict(row) if row else None

    async def _ensure_user(self, user_id: int, guild_id: int, username: str):
        async with self.bot.db.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id = $1 AND guild_id = $2",
                user_id, guild_id,
            )
            if not user:
                user = await conn.fetchrow("""
                    INSERT INTO users (user_id, guild_id, username)
                    VALUES ($1, $2, $3)
                    RETURNING *;
                """, user_id, guild_id, username)
            return user

    async def _save_question(self, data: dict) -> int:
        async with self.bot.db.acquire() as conn:
            return await conn.fetchval("""
                INSERT INTO questions (content, options, correct_index, difficulty, category, source)
                VALUES ($1, $2::jsonb, $3, $4::question_difficulty, $5::question_category, $6::question_source)
                RETURNING question_id;
            """,
                data["question"],
                json.dumps(data["options"]),
                data["correct_index"],
                data.get("difficulty", "medium"),
                data.get("category", "general"),
                data.get("source", "openai"),
            )


# ── Setup ──────────────────────────────────────────────────────
async def setup(bot: commands.Bot):
    await bot.add_cog(RobberyCog(bot))