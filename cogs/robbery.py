"""
Cog Robo PvP — /robar, /escudo, /estado_escudo, /robos, /debug_set_escudo
Re-estructurado para:
- Escudos por puntos (por defecto la compra sin args pone 24h).
- Comandos: estado_escudo, debug_set_escudo, robar, robos.
- Robos con pregunta difícil: si aciertas robas puntos del objetivo; si fallas pierdes el 10% de tus puntos.
- Facilidades de testing: debug_set_escudo permite añadir/quitar escudos sin permisos admin (controlado por DEV_USER_IDS o flag en guild_config).
"""

import os
import json
import random
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands
import logging

log = logging.getLogger("bot.robbery")


# ── Vista de respuesta para robos ──────────────────────────────

class RobberyView(discord.ui.View):
    """Vista de botones para responder la pregunta del robo. Solo el atacante puede usarla."""

    EMOJIS = ["🇦", "🇧", "🇨", "🇩"]

    def __init__(self, question_data: dict, attacker_id: int, timeout_seconds: int = 20):
        super().__init__(timeout=timeout_seconds)
        self.question_data = question_data
        self.attacker_id = attacker_id
        self.answered = False
        self.selected_index: int | None = None
        self.is_correct: bool = False
        self.response_time: float = 0.0
        self._start_time = datetime.utcnow()

        for i, option in enumerate(question_data["options"]):
            btn = discord.ui.Button(
                label=option,
                emoji=self.EMOJIS[i],
                style=discord.ButtonStyle.secondary,
                custom_id=f"rob_option_{i}",
                row=i // 2,
            )
            btn.callback = self._make_callback(i)
            self.add_item(btn)

    def _make_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            # Sólo el atacante
            if interaction.user.id != self.attacker_id:
                await interaction.response.send_message("Solo el atacante puede responder.", ephemeral=True)
                return

            if self.answered:
                await interaction.response.send_message("Ya has respondido.", ephemeral=True)
                return

            self.answered = True
            self.selected_index = index
            self.is_correct = index == self.question_data["correct_index"]
            self.response_time = (datetime.utcnow() - self._start_time).total_seconds()

            # Desactivar botones y marcar resultado
            for i, child in enumerate(self.children):
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
                    if i == self.question_data["correct_index"]:
                        child.style = discord.ButtonStyle.success
                    elif i == index and not self.is_correct:
                        child.style = discord.ButtonStyle.danger

            # Intentar editar el mensaje (puede fallar en algunos casos; no es crítico)
            try:
                await interaction.response.edit_message(view=self)
            except Exception:
                # fallback: ack with a followup
                try:
                    await interaction.followup.send("Respuesta registrada.", ephemeral=True)
                except Exception:
                    pass

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


# ── Configuración de escudos y comportamiento ─────────────────

# Opciones "nominales" por si quieres ofrecer presets. Los costes serán recalculados
PRESET_SHIELDS = {
    "1h": {"hours": 1, "name": "1 hora"},
    "6h": {"hours": 6, "name": "6 horas"},
    "24h": {"hours": 24, "name": "24 horas"},
}

# Coste base en puntos por hora (ajusta a gusto)
COST_POINTS_PER_HOUR = 5

# Robos: porcentajes por defecto para calcular cuánto se puede robar del objetivo
DEFAULT_ROBBERY_MIN_PCT = 0.05
DEFAULT_ROBBERY_MAX_PCT = 0.20

# Penalización por fallo: 10% de puntos del atacante
FAIL_PENALTY_PCT = 0.10


class RobberyCog(commands.Cog):
    """Cog reestructurado para robos y escudos (PvP)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Dev IDs desde ENV para testing del debug_set_escudo
        dev_ids = os.getenv("DEV_USER_IDS", "")
        self.dev_user_ids = {int(x) for x in dev_ids.split(",") if x.strip().isdigit()}

        self._generator = None  # se resuelve con QuizCog si está cargado

    # ---------------- utilities ----------------

    async def _safe_defer(self, interaction: discord.Interaction, *, thinking: bool = True) -> bool:
        """
        Intenta defer la interacción. Devuelve True si defer se realizó OK.
        Si ya está respondida / expirada devuelve False.
        """
        try:
            if interaction.response.is_done():
                return False
            await interaction.response.defer(thinking=thinking)
            return True
        except Exception:
            return False

    @property
    def generator(self):
        """Reutiliza el generador de preguntas del QuizCog si existe."""
        if self._generator is None:
            quiz_cog = self.bot.get_cog("QuizCog")
            if quiz_cog:
                self._generator = quiz_cog.generator
            else:
                # Fallback mínimo que devuelve None (evita crashes)
                class _Stub:
                    async def generate(self, *args, **kwargs):
                        return None
                self._generator = _Stub()
        return self._generator

    def _is_dev_or_allowed(self, interaction: discord.Interaction, guild_config: dict | None) -> bool:
        """Permitir debug a devs o si guild_config.allow_test_shields está activado."""
        if interaction.user.id in self.dev_user_ids:
            return True
        if getattr(self.bot, "owner_id", None) and interaction.user.id == self.bot.owner_id:
            return True
        if guild_config and guild_config.get("allow_test_shields"):
            return True
        return False

    # ---------------- comandos públicos ----------------

    @app_commands.command(name="estado_escudo", description="Muestra quién tiene escudo activo o el estado de un miembro.")
    @app_commands.describe(member="Miembro (opcional). Si no se indica, lista los escudos activos.")
    async def estado_escudo(self, interaction: discord.Interaction, member: discord.Member | None = None):
        did_defer = await self._safe_defer(interaction)

        guild_id = interaction.guild_id
        async with self.bot.db.acquire() as conn:
            if member:
                row = await conn.fetchrow(
                    "SELECT user_id, username, shield_until FROM users WHERE user_id = $1 AND guild_id = $2",
                    member.id, guild_id,
                )
                if not row or not row["shield_until"] or row["shield_until"] <= datetime.utcnow():
                    if did_defer:
                        await interaction.followup.send(f"{member.display_name} no tiene escudo activo.", ephemeral=True)
                    else:
                        await interaction.response.send_message(f"{member.display_name} no tiene escudo activo.", ephemeral=True)
                    return
                expires = row["shield_until"]
                text = f"{member.display_name} tiene escudo activo hasta <t:{int(expires.timestamp())}:R>."
                if did_defer:
                    await interaction.followup.send(text, ephemeral=True)
                else:
                    await interaction.response.send_message(text, ephemeral=True)
                return

            rows = await conn.fetch(
                "SELECT user_id, username, shield_until FROM users WHERE guild_id = $1 AND shield_until > NOW() ORDER BY shield_until DESC LIMIT 50",
                guild_id,
            )

        if not rows:
            if did_defer:
                await interaction.followup.send("No hay usuarios con escudo activo en este servidor.", ephemeral=True)
            else:
                await interaction.response.send_message("No hay usuarios con escudo activo en este servidor.", ephemeral=True)
            return

        lines = [f"{r['username']} — expira <t:{int(r['shield_until'].timestamp())}:R>" for r in rows]
        embed = discord.Embed(title="Escudos activos", description="\n".join(lines), color=discord.Color.blue())

        if did_defer:
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="escudo", description="Compra un escudo temporal contra robos. Si no indicas duración, se aplica 24h.")
    @app_commands.describe(duration="1h, 6h, 24h (por defecto 24h)")
    @app_commands.choices(duration=[
        app_commands.Choice(name="1 hora", value="1h"),
        app_commands.Choice(name="6 horas", value="6h"),
        app_commands.Choice(name="24 horas", value="24h"),
    ])
    async def escudo(self, interaction: discord.Interaction, duration: str | None = "24h"):
        did_defer = await self._safe_defer(interaction)

        user_id = interaction.user.id
        guild_id = interaction.guild_id

        # elegir preset (default 24h)
        preset_key = duration or "24h"
        preset = PRESET_SHIELDS.get(preset_key, PRESET_SHIELDS["24h"])
        hours = preset["hours"]
        name = preset["name"]

        cost = max(1, int(COST_POINTS_PER_HOUR * hours))  # coste en puntos

        async with self.bot.db.acquire() as conn:
            user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1 AND guild_id = $2", user_id, guild_id)

            if not user:
                # crear fila básica si no existe
                await conn.execute(
                    "INSERT INTO users (user_id, guild_id, username, created_at, points) VALUES ($1,$2,$3,NOW(),0) ON CONFLICT DO NOTHING",
                    user_id, guild_id, interaction.user.display_name
                )
                user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1 AND guild_id = $2", user_id, guild_id)

            # si ya tiene escudo activo, no comprar (simplifica)
            if user.get("shield_until") and user["shield_until"] > datetime.utcnow():
                remaining = user["shield_until"] - datetime.utcnow()
                hours_r = int(remaining.total_seconds() // 3600)
                mins_r = int((remaining.total_seconds() % 3600) // 60)
                text = f"Ya tienes un escudo activo. Expira en **{hours_r}h {mins_r}m**."
                if did_defer:
                    await interaction.followup.send(text, ephemeral=True)
                else:
                    await interaction.response.send_message(text, ephemeral=True)
                return

            points = user.get("points", 0) or 0
            if points < cost:
                text = f"No tienes suficientes puntos ({points}) para comprar un escudo de {name} (coste: {cost} puntos)."
                if did_defer:
                    await interaction.followup.send(text, ephemeral=True)
                else:
                    await interaction.response.send_message(text, ephemeral=True)
                return

            expires = datetime.utcnow() + timedelta(hours=hours)
            await conn.execute(
                "UPDATE users SET points = points - $3, shield_until = $4, updated_at = NOW() WHERE user_id = $1 AND guild_id = $2",
                user_id, guild_id, cost, expires
            )
            await conn.execute(
                "INSERT INTO transactions (user_id, guild_id, tx_type, points_delta, money_delta, description) VALUES ($1,$2,$3,$4,$5,$6)",
                user_id, guild_id, "shield_buy", -cost, 0, f"Compra escudo {name}"
            )

        embed = discord.Embed(
            title="Escudo activado",
            description=(f"Protección contra robos durante **{name}**.\n\nCoste: **{cost}** puntos\nExpira: <t:{int(expires.timestamp())}:R>"),
            color=discord.Color.blue(),
        )

        if did_defer:
            await interaction.followup.send(embed=embed)
        else:
            await interaction.response.send_message(embed=embed)

        logger = self.bot.get_cog("LoggerCog")
        if logger:
            await logger.log_shield(guild_id=guild_id, user=interaction.user, duration=name, cost=cost)

    @app_commands.command(
        name="debug_set_escudo",
        description="(DEBUG) Forzar o quitar escudo a un usuario — usar solo para testing"
    )
    @app_commands.describe(member="Miembro", duration="1h|6h|24h o 'clear' para quitar")
    @app_commands.choices(duration=[
        app_commands.Choice(name="1 hora", value="1h"),
        app_commands.Choice(name="6 horas", value="6h"),
        app_commands.Choice(name="24 horas", value="24h"),
        app_commands.Choice(name="Quitar escudo", value="clear"),
    ])
    async def debug_set_escudo(self, interaction: discord.Interaction, member: discord.Member, duration: str):
        did_defer = await self._safe_defer(interaction)

        guild_id = interaction.guild_id
        config = await self._get_config(guild_id)

        if not self._is_dev_or_allowed(interaction, config):
            msg = "No tienes permiso para usar este comando de debug."
            if did_defer:
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return

        if duration == "clear":
            async with self.bot.db.acquire() as conn:
                await conn.execute("UPDATE users SET shield_until = NULL, updated_at = NOW() WHERE user_id = $1 AND guild_id = $2", member.id, guild_id)
                await conn.execute("INSERT INTO transactions (user_id, guild_id, tx_type, points_delta, money_delta, description) VALUES ($1,$2,$3,$4,$5,$6)",
                                   interaction.user.id, guild_id, "shield_debug", 0, 0, f"Debug quitó escudo a {member.display_name}")
            text = f"Escudo de {member.display_name} eliminado (modo debug)."
            if did_defer:
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
            return

        preset = PRESET_SHIELDS.get(duration)
        if not preset:
            text = "Duración no válida."
            if did_defer:
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
            return

        expires = datetime.utcnow() + timedelta(hours=preset["hours"])
        async with self.bot.db.acquire() as conn:
            # Asegurar que existe el usuario
            await conn.execute(
                "INSERT INTO users (user_id, guild_id, username, created_at, points) VALUES ($1,$2,$3,NOW(),0) ON CONFLICT (user_id, guild_id) DO UPDATE SET username = EXCLUDED.username, updated_at = NOW()",
                member.id, guild_id, member.display_name
            )
            await conn.execute("UPDATE users SET shield_until = $3, updated_at = NOW() WHERE user_id = $1 AND guild_id = $2", member.id, guild_id, expires)
            await conn.execute("INSERT INTO transactions (user_id, guild_id, tx_type, points_delta, money_delta, description) VALUES ($1,$2,$3,$4,$5,$6)",
                               interaction.user.id, guild_id, "shield_debug", 0, 0, f"Debug puso escudo a {member.display_name} por {preset['name']}")

        text = f"Escudo activado para {member.display_name} hasta <t:{int(expires.timestamp())}:R> (modo debug)."
        if did_defer:
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="robar", description="Intenta robar puntos a otro jugador respondiendo una pregunta difícil.")
    @app_commands.describe(victim="El jugador al que quieres robar")
    async def robar(self, interaction: discord.Interaction, victim: discord.Member):
        did_defer = await self._safe_defer(interaction)

        attacker = interaction.user
        guild_id = interaction.guild_id

        # validaciones
        if victim.id == attacker.id:
            txt = "No puedes robarte a ti mismo."
            if did_defer:
                await interaction.followup.send(txt, ephemeral=True)
            else:
                await interaction.response.send_message(txt, ephemeral=True)
            return

        if victim.bot:
            txt = "No puedes robar a un bot."
            if did_defer:
                await interaction.followup.send(txt, ephemeral=True)
            else:
                await interaction.response.send_message(txt, ephemeral=True)
            return

        # asegurar config y usuarios
        config = await self._get_config(guild_id)
        async with self.bot.db.acquire() as conn:
            if not config:
                await conn.execute("INSERT INTO guild_config (guild_id) VALUES ($1) ON CONFLICT DO NOTHING", guild_id)
                config = await self._get_config(guild_id)

            attacker_row = await self._ensure_user_row(attacker.id, guild_id, attacker.display_name)
            victim_row = await self._ensure_user_row(victim.id, guild_id, victim.display_name)

        # protección por creación reciente (24h)
        if victim_row["created_at"] > datetime.utcnow() - timedelta(hours=24):
            txt = f"**{victim.display_name}** es nuevo y tiene protección de 24h."
            if did_defer:
                await interaction.followup.send(txt, ephemeral=True)
            else:
                await interaction.response.send_message(txt, ephemeral=True)
            return

        # protección por escudo
        if victim_row.get("shield_until") and victim_row["shield_until"] > datetime.utcnow():
            remaining = victim_row["shield_until"] - datetime.utcnow()
            mins = int(remaining.total_seconds() // 60)
            txt = f"**{victim.display_name}** tiene un escudo activo. Expira en **{mins} minutos**."
            if did_defer:
                await interaction.followup.send(txt, ephemeral=True)
            else:
                await interaction.response.send_message(txt, ephemeral=True)
            return

        # cooldown sencillo: usar last_robbery en minutos
        cooldown_min = config.get("robbery_cooldown_min", 5)
        if attacker_row.get("last_robbery"):
            elapsed = (datetime.utcnow() - attacker_row["last_robbery"]).total_seconds()
            remaining = (cooldown_min * 60) - elapsed
            if remaining > 0:
                mins, secs = int(remaining // 60), int(remaining % 60)
                txt = f"Espera **{mins}m {secs}s** antes de intentar otro robo."
                if did_defer:
                    await interaction.followup.send(txt, ephemeral=True)
                else:
                    await interaction.response.send_message(txt, ephemeral=True)
                return

        # límite diario simple
        max_daily = config.get("max_robberies_daily", 5)
        if attacker_row.get("robberies_today", 0) >= max_daily:
            txt = f"Has alcanzado el límite diario de **{max_daily}** robos."
            if did_defer:
                await interaction.followup.send(txt, ephemeral=True)
            else:
                await interaction.response.send_message(txt, ephemeral=True)
            return

        # Generar pregunta difícil
        # enviamos un followup ephemeral indicando generación si defer ya hecho
        if did_defer:
            await interaction.followup.send("Generando pregunta difícil...", ephemeral=True)

        question_data = await self.generator.generate(difficulty="hard", category=None, recent_questions=None)
        if not question_data:
            txt = "No se pudo generar una pregunta. Inténtalo de nuevo más tarde."
            if did_defer:
                await interaction.followup.send(txt, ephemeral=True)
            else:
                await interaction.response.send_message(txt, ephemeral=True)
            return

        # registrar pregunta en DB
        qid = await self._save_question(question_data)

        # calcular cuánto se puede robar: porcentaje aleatorio de puntos de la víctima
        min_pct = config.get("robbery_min_pct", DEFAULT_ROBBERY_MIN_PCT)
        max_pct = config.get("robbery_max_pct", DEFAULT_ROBBERY_MAX_PCT)
        steal_pct = random.uniform(min_pct, max_pct)

        victim_points = victim_row.get("points", 0) or 0
        attacker_points = attacker_row.get("points", 0) or 0

        potential_steal = max(1, int(victim_points * steal_pct))
        fail_loss = max(1, int(attacker_points * FAIL_PENALTY_PCT))

        # mensaje principal con vista
        embed = discord.Embed(
            title="Intento de robo",
            description=f"**{attacker.display_name}** intenta robar a **{victim.display_name}**.\n\n**{question_data['question']}**",
            color=discord.Color.dark_red()
        )
        embed.add_field(name="Si aciertas", value=f"Robas **{potential_steal}** puntos (se restarán a la víctima).", inline=False)
        embed.add_field(name="Si fallas", value=f"Pierdes **{fail_loss}** puntos (10% de tus puntos).", inline=False)
        embed.set_footer(text=f"Solo {attacker.display_name} puede responder · Tiempo: 20s")

        # Enviar embed + vista. Si defer fue hecho, usar followup.send
        if did_defer:
            sent = await interaction.followup.send(content=f"{victim.mention} — Están intentando robarte.", embed=embed, view=RobberyView(question_data, attacker.id))
        else:
            # no deferido, enviar respuesta normal
            await interaction.response.send_message(content=f"{victim.mention} — Están intentando robarte.", embed=embed, view=RobberyView(question_data, attacker.id))
            # message object not captured in this branch, view.wait still works

        # actualizar cooldown y contador de intentos
        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE users SET last_robbery = NOW(), robberies_today = robberies_today + 1, updated_at = NOW() WHERE user_id = $1 AND guild_id = $2", attacker.id, guild_id)

        # esperar resultado en la vista: buscar la vista en el mensaje no es necesario; RobberyView.stop() liberará wait()
        # Para simplificar, reconstruimos la view localmente to wait on it: (we already passed one to send; here we wait on a new one won't work)
        # Instead, rely on ephemeral "followup" we already sent above; but to detect answer we need to capture the view instance passed to send.
        # To keep things simple and reliable, re-fetch the message the bot just sent and get its components isn't straightforward.
        # A practical approach: embed the view we created and hold reference by creating it first and passing it to send while retaining ref.

        # Re-send with retained view reference if we didn't keep it
        # (Better approach: create view before sending and keep it)
        view = RobberyView(question_data, attacker.id, timeout_seconds=20)
        # If we deferred and used followup earlier, delete the ephemeral "generating..." message isn't necessary

        # Send a separate message that contains the view and embed (non-ephemeral) so we can wait reliably
        msg = await interaction.channel.send(content=f"{victim.mention} — Intento de robo (respuesta del atacante):", embed=embed, view=view)

        # Wait for the view
        timed_out = await view.wait()

        # Resultado -> aplicar efectos
        if timed_out or not view.answered:
            # timeout -> tratar como fallo
            await self._apply_rob_failure(attacker, victim, guild_id, qid, fail_loss, view_response_time=20.0, answered_index=-1, reason="timeout")
            return

        if view.is_correct:
            await self._apply_rob_success(attacker, victim, guild_id, qid, potential_steal, view.response_time, view.selected_index)
        else:
            await self._apply_rob_failure(attacker, victim, guild_id, qid, fail_loss, view.response_time, view.selected_index, reason="wrong")

    @app_commands.command(name="robos", description="Mira tu historial de robos recientes")
    async def robos(self, interaction: discord.Interaction):
        did_defer = await self._safe_defer(interaction)
        user_id = interaction.user.id
        guild_id = interaction.guild_id

        async with self.bot.db.acquire() as conn:
            history = await conn.fetch(
                """
                SELECT r.*, a.username AS attacker_name, v.username AS victim_name
                FROM robberies r
                LEFT JOIN users a ON r.attacker_id = a.user_id AND r.guild_id = a.guild_id
                LEFT JOIN users v ON r.victim_id = v.user_id AND r.guild_id = v.guild_id
                WHERE r.guild_id = $1 AND (r.attacker_id = $2 OR r.victim_id = $2)
                ORDER BY r.created_at DESC LIMIT 15
                """,
                guild_id, user_id
            )

        if not history:
            if did_defer:
                await interaction.followup.send("No hay historial de robos para ti.", ephemeral=True)
            else:
                await interaction.response.send_message("No hay historial de robos para ti.", ephemeral=True)
            return

        lines = []
        for row in history:
            t = f"<t:{int(row['created_at'].timestamp())}:R>"
            if row["attacker_id"] == user_id:
                if row["success"]:
                    lines.append(f"Robaste **{row['points_changed']}** a {row['victim_name']} · {t}")
                else:
                    lines.append(f"Fallo al robar a {row['victim_name']} · Perdiste **{abs(row['points_changed'])}** · {t}")
            else:
                if row["success"]:
                    lines.append(f"{row['attacker_name']} te robó **{row['points_changed']}** · {t}")
                else:
                    lines.append(f"{row['attacker_name']} intentó robarte y falló · {t}")

        embed = discord.Embed(title=f"Historial de robos — {interaction.user.display_name}", description="\n".join(lines), color=discord.Color.dark_red())
        if did_defer:
            await interaction.followup.send(embed=embed)
        else:
            await interaction.response.send_message(embed=embed)

    # ---------------- efectos de éxito/fallo ----------------

    async def _apply_rob_success(self, attacker: discord.User, victim: discord.Member, guild_id: int, question_id: int, stolen_points: int, view_response_time: float, answered_index: int):
        async with self.bot.db.acquire() as conn:
            # Bloquear fila de la víctima para evitar condiciones de carrera
            victim_points = await conn.fetchval("SELECT points FROM users WHERE user_id = $1 AND guild_id = $2 FOR UPDATE", victim.id, guild_id)
            actual_stolen = min(stolen_points, victim_points or 0)
            if actual_stolen <= 0:
                # víctima no tiene puntos
                channel = self._get_channel_for_user(attacker, victim)
                embed = discord.Embed(title="Robo vacío", description=f"**{victim.display_name}** no tiene puntos para robar.", color=discord.Color.greyple())
                await channel.send(embed=embed)
                return

            await conn.execute("UPDATE users SET points = points - $3, updated_at = NOW() WHERE user_id = $1 AND guild_id = $2", victim.id, guild_id, actual_stolen)
            await conn.execute("UPDATE users SET points = points + $3, updated_at = NOW() WHERE user_id = $1 AND guild_id = $2", attacker.id, guild_id, actual_stolen)

            # registrar en robberies (points_changed positivo para éxito)
            await conn.execute(
                "INSERT INTO robberies (attacker_id, victim_id, guild_id, question_id, success, points_changed, created_at) VALUES ($1,$2,$3,$4,TRUE,$5,NOW())",
                attacker.id, victim.id, guild_id, question_id, actual_stolen
            )

            await conn.execute(
                "INSERT INTO transactions (user_id, guild_id, tx_type, points_delta, money_delta, description) VALUES ($1,$2,$3,$4,$5,$6)",
                attacker.id, guild_id, "rob_win", actual_stolen, 0, f"Robo exitoso a {victim.display_name}"
            )
            await conn.execute(
                "INSERT INTO transactions (user_id, guild_id, tx_type, points_delta, money_delta, description) VALUES ($1,$2,$3,$4,$5,$6)",
                victim.id, guild_id, "rob_lose", -actual_stolen, 0, f"Robado por {attacker.display_name}"
            )

        # Notificar en canal público (canal: usar el último channel donde se ejecutó, simplificamos enviando al primer texto channel accessible)
        channel = self._get_channel_for_user(attacker, victim)
        embed = discord.Embed(
            title="Robo exitoso",
            description=(f"**{attacker.display_name}** ha robado a **{victim.display_name}**.\n\n"
                         f"Puntos robados: **+{actual_stolen}**\n"
                         f"Tiempo de respuesta: **{view_response_time:.1f}s**"),
            color=discord.Color.dark_red()
        )
        await channel.send(embed=embed)

        logger = self.bot.get_cog("LoggerCog")
        if logger:
            await logger.log_robbery(guild_id=guild_id, attacker=attacker, victim=victim, success=True, amount=actual_stolen)

    async def _apply_rob_failure(self, attacker: discord.User, victim: discord.Member, guild_id: int, question_id: int, loss_points: int, view_response_time: float, answered_index: int, reason: str = "wrong"):
        async with self.bot.db.acquire() as conn:
            # Bloquear fila del atacante
            attacker_points = await conn.fetchval("SELECT points FROM users WHERE user_id = $1 AND guild_id = $2 FOR UPDATE", attacker.id, guild_id)
            actual_loss = min(loss_points, max(0, attacker_points or 0))
            await conn.execute("UPDATE users SET points = GREATEST(0, points - $3), updated_at = NOW() WHERE user_id = $1 AND guild_id = $2", attacker.id, guild_id, actual_loss)

            # registrar robbery con points_changed negativo
            await conn.execute("INSERT INTO robberies (attacker_id, victim_id, guild_id, question_id, success, points_changed, created_at) VALUES ($1,$2,$3,$4,FALSE,$5,NOW())",
                               attacker.id, victim.id, guild_id, question_id, -actual_loss)

            await conn.execute("INSERT INTO transactions (user_id, guild_id, tx_type, points_delta, money_delta, description) VALUES ($1,$2,$3,$4,$5,$6)",
                               attacker.id, guild_id, -actual_loss, 0, f"Robo fallido contra {victim.display_name}")

        channel = self._get_channel_for_user(attacker, victim)
        correct = None
        # obtener pregunta correcta para mostrar (si fue guardada)
        try:
            async with self.bot.db.acquire() as conn:
                row = await conn.fetchrow("SELECT content, options, correct_index FROM questions WHERE question_id = $1", question_id)
                if row:
                    opts = json.loads(row["options"])
                    correct = opts[row["correct_index"]]
        except Exception:
            correct = None

        if reason == "timeout":
            title = "Robo fallido — Tiempo agotado"
            detail = "No respondiste a tiempo."
        else:
            title = "Robo fallido"
            detail = "Respuesta incorrecta."

        desc = f"**{attacker.display_name}** intentó robar a **{victim.display_name}** y fracasó.\n\n{detail}\n"
        if correct:
            desc += f"La respuesta correcta era: **{correct}**\n\n"
        desc += f"Puntos perdidos: **-{actual_loss}**"

        embed = discord.Embed(title=title, description=desc, color=discord.Color.orange())
        await channel.send(embed=embed)

        logger = self.bot.get_cog("LoggerCog")
        if logger:
            await logger.log_robbery(guild_id=guild_id, attacker=attacker, victim=victim, success=False, amount=actual_loss)

    # ---------------- helpers DB y misc ----------------

    async def _get_config(self, guild_id: int) -> dict | None:
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM guild_config WHERE guild_id = $1", guild_id)
            return dict(row) if row else None

    async def _ensure_user_row(self, user_id: int, guild_id: int, username: str) -> dict:
        """
        Asegura que exista la fila users y devuelve la fila actualizada.
        Campos relevantes esperados: points, shield_until, created_at, last_robbery, robberies_today
        """
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO users (user_id, guild_id, username, created_at, points)
                VALUES ($1, $2, $3, NOW(), COALESCE((SELECT default_points FROM guild_config WHERE guild_id = $2), 0))
                ON CONFLICT (user_id, guild_id) DO UPDATE
                    SET username = EXCLUDED.username, updated_at = NOW();
                """,
                user_id, guild_id, username
            )
            row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1 AND guild_id = $2", user_id, guild_id)
            return dict(row) if row else {}

    async def _save_question(self, data: dict) -> int | None:
        """Guarda pregunta en tabla questions si existe y retorna question_id (o None)."""
        try:
            async with self.bot.db.acquire() as conn:
                qid = await conn.fetchval(
                    """
                    INSERT INTO questions (content, options, correct_index, difficulty, category, source, created_at)
                    VALUES ($1, $2::jsonb, $3, $4::question_difficulty, $5::question_category, $6::question_source, NOW())
                    RETURNING question_id
                    """,
                    data["question"], json.dumps(data["options"]), data["correct_index"],
                    data.get("difficulty", "medium"), data.get("category", "general"), data.get("source", "openai")
                )
                return qid
        except Exception as e:
            log.warning("Error guardando pregunta: %s", e)
            return None

    def _get_channel_for_user(self, *users) -> discord.abc.Messageable:
        """
        Heurística para elegir un canal donde avisar (usa el canal de la primera guild text channel encontrado).
        Si no puede, retorna el propio bot.user (para evitar crash).
        """
        # Preferir el channel of last context isn't tracked; safe fallback to first guild text channel accessible
        try:
            for g in self.bot.guilds:
                for ch in g.text_channels:
                    # escoger primer canal donde el bot pueda enviar mensajes
                    if ch.permissions_for(g.me).send_messages:
                        return ch
        except Exception:
            pass
        return self.bot.user  # fallback, send will fail silently

async def setup(bot: commands.Bot):
    await bot.add_cog(RobberyCog(bot))