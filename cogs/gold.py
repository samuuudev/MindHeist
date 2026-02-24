"""
Cog Pregunta de Oro — Evento global aleatorio
Aparece aleatoriamente, todos compiten, solo el primero gana.
Sistema de jackpot acumulativo si nadie acierta.
"""

import random
import asyncio
import json
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks
import logging

log = logging.getLogger("bot.gold")


# ── Vista global (cualquiera puede responder) ─────────────────
class GoldQuestionView(discord.ui.View):
    """Botones para la Pregunta de Oro. Primer acierto gana."""

    EMOJI_LETTERS = ["🇦", "🇧", "🇨", "🇩"]

    def __init__(self, question_data: dict, timeout_seconds: int = 60):
        super().__init__(timeout=timeout_seconds)
        self.question_data = question_data
        self.winner_id: int | None = None
        self.winner_name: str | None = None
        self.response_time: float = 0.0
        self._start_time = datetime.utcnow()
        self._answered_users: set[int] = set()  # Usuarios que ya intentaron
        self._lock = asyncio.Lock()
        self.finished = False

        for i, option in enumerate(question_data["options"]):
            button = discord.ui.Button(
                label=option,
                emoji=self.EMOJI_LETTERS[i],
                style=discord.ButtonStyle.secondary,
                custom_id=f"gold_option_{i}",
                row=i // 2,
            )
            button.callback = self._make_callback(i)
            self.add_item(button)

    def _make_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            async with self._lock:
                # Ya hay ganador
                if self.finished:
                    await interaction.response.send_message(
                        "⚡ ¡Alguien ya acertó! Llegas tarde.",
                        ephemeral=True,
                    )
                    return

                # Ya intentó este usuario
                if interaction.user.id in self._answered_users:
                    await interaction.response.send_message(
                        "❌ Ya usaste tu intento en esta Pregunta de Oro.",
                        ephemeral=True,
                    )
                    return

                # Registrar intento
                self._answered_users.add(interaction.user.id)

                is_correct = index == self.question_data["correct_index"]

                if is_correct:
                    # ¡GANADOR!
                    self.finished = True
                    self.winner_id = interaction.user.id
                    self.winner_name = interaction.user.display_name
                    self.response_time = (
                        datetime.utcnow() - self._start_time
                    ).total_seconds()

                    # Actualizar botones
                    for i, child in enumerate(self.children):
                        if isinstance(child, discord.ui.Button):
                            child.disabled = True
                            if i == self.question_data["correct_index"]:
                                child.style = discord.ButtonStyle.success

                    await interaction.response.edit_message(view=self)
                    self.stop()

                else:
                    # Fallo — puede que otros sigan intentando
                    await interaction.response.send_message(
                        f"❌ Respuesta incorrecta. No tienes más intentos en esta pregunta.",
                        ephemeral=True,
                    )

        return callback

    async def on_timeout(self):
        """Nadie acertó — jackpot se acumula."""
        self.finished = True
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
                idx = int(child.custom_id.split("_")[-1])
                if idx == self.question_data["correct_index"]:
                    child.style = discord.ButtonStyle.success
        self.stop()


# ── Cog principal ──────────────────────────────────────────────
class GoldCog(commands.Cog):
    """Sistema de Pregunta de Oro global con jackpot acumulativo."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._generator = None
        self._active_events: dict[int, bool] = {}  # guild_id -> activo
        self.gold_scheduler.start()

    def cog_unload(self):
        self.gold_scheduler.cancel()

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
    # Scheduler — Lanza Preguntas de Oro aleatoriamente
    # ════════════════════════════════════════════════════════════
    @tasks.loop(minutes=1)
    async def gold_scheduler(self):
        """Cada minuto verifica si toca lanzar una Pregunta de Oro."""
        if not self.bot.db:
            return

        async with self.bot.db.acquire() as conn:
            configs = await conn.fetch(
                "SELECT * FROM guild_config;"
            )

        for config in configs:
            guild_id = config["guild_id"]

            # No lanzar si ya hay uno activo
            if self._active_events.get(guild_id, False):
                continue

            # Verificar cuándo fue el último evento
            async with self.bot.db.acquire() as conn:
                last_event = await conn.fetchrow("""
                    SELECT ended_at FROM gold_events
                    WHERE guild_id = $1
                    ORDER BY created_at DESC
                    LIMIT 1;
                """, guild_id)

            min_interval = config["gold_interval_min"]  # minutos
            max_interval = config["gold_interval_max"]  # minutos

            if last_event and last_event["ended_at"]:
                elapsed = (datetime.utcnow() - last_event["ended_at"]).total_seconds() / 60

                if elapsed < min_interval:
                    # Aún no ha pasado el mínimo
                    continue

                # Probabilidad creciente: 0% en min_interval → 100% en max_interval
                probability = min(1.0, (elapsed - min_interval) / (max_interval - min_interval))
                if random.random() > probability:
                    continue
            else:
                # Primer evento: esperar al menos min_interval desde el arranque
                # Lanzar con 10% de probabilidad cada minuto después de min_interval
                if random.random() > 0.10:
                    continue

            # ¡Lanzar evento!
            guild = self.bot.get_guild(guild_id)
            if guild:
                self.bot.loop.create_task(self._launch_gold_event(guild, config))

    @gold_scheduler.before_loop
    async def before_gold_scheduler(self):
        await self.bot.wait_until_ready()
        # Espera inicial para no lanzar nada justo al arrancar
        await asyncio.sleep(60)

    # ════════════════════════════════════════════════════════════
    # Lanzar Pregunta de Oro
    # ════════════════════════════════════════════════════════════
    async def _launch_gold_event(self, guild: discord.Guild, config: dict):
        """Ejecuta una Pregunta de Oro completa."""
        guild_id = guild.id

        # Marcar como activo
        self._active_events[guild_id] = True

        try:
            # ── Determinar canal ───────────────────────────────
            channel = None
            if config["gold_channel_id"]:
                channel = guild.get_channel(config["gold_channel_id"])
            if not channel:
                log.warning(f"No se encontró canal para Pregunta de Oro en {guild.name}")
                return

            # ── Obtener jackpot acumulado ──────────────────────
            async with self.bot.db.acquire() as conn:
                jackpot_row = await conn.fetchrow("""
                    SELECT COALESCE(SUM(jackpot), 0) AS total_jackpot
                    FROM gold_events
                    WHERE guild_id = $1 AND winner_id IS NULL AND is_active = FALSE;
                """, guild_id)

            accumulated_jackpot = jackpot_row["total_jackpot"] if jackpot_row else 0

            # Calcular recompensa
            base_reward = random.randint(
                config["gold_min_points"],
                config["gold_max_points"],
            )
            total_reward = base_reward + accumulated_jackpot

            # ── Generar pregunta (más difícil) ─────────────────
            question_data = await self.generator.generate(
                difficulty=random.choice(["medium", "hard"]),
                category=None,
            )

            if not question_data:
                log.error(f"No se pudo generar pregunta de oro para {guild.name}")
                return

            # ── Guardar en DB ──────────────────────────────────
            async with self.bot.db.acquire() as conn:
                question_id = await conn.fetchval("""
                    INSERT INTO questions (content, options, correct_index, difficulty, category, source)
                    VALUES ($1, $2::jsonb, $3, $4::question_difficulty, $5::question_category, $6::question_source)
                    RETURNING question_id;
                """,
                    question_data["question"],
                    json.dumps(question_data["options"]),
                    question_data["correct_index"],
                    question_data.get("difficulty", "medium"),
                    question_data.get("category", "general"),
                    question_data.get("source", "openai"),
                )

                event_id = await conn.fetchval("""
                    INSERT INTO gold_events
                        (guild_id, question_id, reward_points, jackpot, is_active, started_at)
                    VALUES ($1, $2, $3, $4, TRUE, NOW())
                    RETURNING event_id;
                """, guild_id, question_id, total_reward, base_reward)

            # ── Anuncio previo (5 segundos de hype) ────────────
            hype_embed = discord.Embed(
                title="⚡✨ ¡PREGUNTA DE ORO INMINENTE! ✨⚡",
                description=(
                    "**¡Prepárense!** En **5 segundos** aparecerá una Pregunta de Oro.\n\n"
                    f"🏆 Recompensa: **{total_reward} puntos**"
                    + (f"\n💎 ¡Incluye jackpot acumulado de **{accumulated_jackpot}** puntos!" if accumulated_jackpot > 0 else "")
                    + "\n\n⚠️ **Solo el primero en acertar gana.**"
                    + "\n⚠️ **Solo tienes UN intento.**"
                ),
                color=discord.Color.gold(),
            )
            hype_embed.set_thumbnail(
                url="https://em-content.zobj.net/source/twitter/376/star_2b50.png"
            )

            hype_msg = await channel.send(
                content="@everyone",
                embed=hype_embed,
            )

            await asyncio.sleep(5)

            # ── Pregunta de Oro ─────────────────────────────────
            gold_embed = discord.Embed(
                title="✨🏆 PREGUNTA DE ORO 🏆✨",
                description=f"**{question_data['question']}**",
                color=discord.Color.gold(),
            )
            gold_embed.add_field(
                name="🏆 Recompensa",
                value=f"**{total_reward} puntos**",
                inline=True,
            )
            gold_embed.add_field(
                name="⏱️ Tiempo",
                value="**60 segundos**",
                inline=True,
            )
            gold_embed.add_field(
                name="⚠️ Reglas",
                value="Solo 1 intento por persona\nPrimer acierto gana",
                inline=True,
            )

            if accumulated_jackpot > 0:
                gold_embed.add_field(
                    name="💎 Jackpot acumulado",
                    value=f"**+{accumulated_jackpot}** puntos extra incluidos",
                    inline=False,
                )

            view = GoldQuestionView(question_data, timeout_seconds=60)
            gold_msg = await channel.send(embed=gold_embed, view=view)

            # ── Esperar resultado ──────────────────────────────
            await view.wait()

            # Borrar mensaje de hype
            try:
                await hype_msg.delete()
            except Exception:
                pass

            if view.winner_id:
                # ══ ALGUIEN GANÓ ═══════════════════════════════
                # Registrar usuario si es nuevo
                async with self.bot.db.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO users (user_id, guild_id, username)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (user_id) DO UPDATE SET username = $3, updated_at = NOW();
                    """, view.winner_id, guild_id, view.winner_name)

                    # Dar puntos con lock transaccional
                    await conn.execute("""
                        UPDATE users
                        SET points = points + $3,
                            money = money + $3,
                            gold_wins = gold_wins + 1,
                            updated_at = NOW()
                        WHERE user_id = $1 AND guild_id = $2;
                    """, view.winner_id, guild_id, total_reward)

                    # Registrar transacción
                    await conn.execute("""
                        INSERT INTO transactions
                            (user_id, guild_id, tx_type, points_delta, money_delta, description)
                        VALUES ($1, $2, 'gold', $3, $3, $4);
                    """,
                        view.winner_id, guild_id, total_reward,
                        f"Pregunta de Oro #{event_id} ganada",
                    )

                    # Registrar en historial
                    await conn.execute("""
                        INSERT INTO answer_history
                            (user_id, guild_id, question_id, answered_index, is_correct,
                             points_earned, context, response_time)
                        VALUES ($1, $2, $3, $4, TRUE, $5, 'gold', $6);
                    """,
                        view.winner_id, guild_id, question_id,
                        question_data["correct_index"],
                        total_reward, view.response_time,
                    )

                    # Cerrar evento como ganado
                    await conn.execute("""
                        UPDATE gold_events
                        SET winner_id = $1, is_active = FALSE, ended_at = NOW(), jackpot = 0
                        WHERE event_id = $2;
                    """, view.winner_id, event_id)

                    # Limpiar jackpots anteriores acumulados
                    await conn.execute("""
                        UPDATE gold_events
                        SET jackpot = 0
                        WHERE guild_id = $1 AND winner_id IS NULL AND is_active = FALSE;
                    """, guild_id)

                # Embed de victoria
                participants = len(view._answered_users)
                winner_embed = discord.Embed(
                    title="🏆✨ ¡PREGUNTA DE ORO GANADA! ✨🏆",
                    description=(
                        f"**{view.winner_name}** ha acertado la Pregunta de Oro!\n\n"
                        f"🏆 **+{total_reward} puntos**\n"
                        f"⏱️ Respondió en **{view.response_time:.1f}s**\n"
                        f"👥 Participantes: **{participants}**"
                    ),
                    color=discord.Color.gold(),
                )
                winner_embed.set_thumbnail(
                    url="https://em-content.zobj.net/source/twitter/376/trophy_1f3c6.png"
                )

                await channel.send(embed=winner_embed)

            else:
                # ══ NADIE ACERTÓ — JACKPOT ACUMULA ═════════════
                async with self.bot.db.acquire() as conn:
                    await conn.execute("""
                        UPDATE gold_events
                        SET is_active = FALSE, ended_at = NOW()
                        WHERE event_id = $1;
                    """, event_id)

                new_jackpot = accumulated_jackpot + base_reward
                participants = len(view._answered_users)

                correct_answer = question_data["options"][question_data["correct_index"]]

                jackpot_embed = discord.Embed(
                    title="💔 Nadie acertó la Pregunta de Oro",
                    description=(
                        f"La respuesta correcta era: **{correct_answer}**\n\n"
                        f"👥 Participantes: **{participants}**\n\n"
                        f"💎 **¡El jackpot se acumula!**\n"
                        f"Jackpot actual: **{new_jackpot} puntos**\n\n"
                        f"La próxima Pregunta de Oro tendrá ese premio extra."
                    ),
                    color=discord.Color.dark_gold(),
                )
                jackpot_embed.set_thumbnail(
                    url="https://em-content.zobj.net/source/twitter/376/gem-stone_1f48e.png"
                )

                await channel.send(embed=jackpot_embed)

            log.info(
                f"Pregunta de Oro #{event_id} en {guild.name} — "
                f"{'Ganada por ' + view.winner_name if view.winner_id else 'Sin ganador'}"
            )

        except Exception as e:
            log.error(f"Error en Pregunta de Oro para {guild.name}: {e}")

        finally:
            self._active_events[guild_id] = False

    # ══��═════════════════════════════════════════════════════════
    # Trigger desde /quiz (5% de probabilidad)
    # ════════════════════════════════════════════════════════════
    async def try_trigger_from_quiz(self, guild: discord.Guild):
        """Llamado desde QuizCog al completar un /quiz. 5% de probabilidad."""
        guild_id = guild.id

        if self._active_events.get(guild_id, False):
            return

        async with self.bot.db.acquire() as conn:
            config = await conn.fetchrow(
                "SELECT * FROM guild_config WHERE guild_id = $1", guild_id
            )

        if not config:
            return

        chance = config["gold_quiz_chance"]  # 0.05 = 5%
        if random.random() < chance:
            log.info(f"¡Pregunta de Oro activada por /quiz en {guild.name}!")
            self.bot.loop.create_task(self._launch_gold_event(guild, dict(config)))

    # ════════════════════════════════════════════════════════════
    # /gold — Info sobre el sistema de oro
    # ════════════════════════��═══════════════════════════════════
    @app_commands.command(
        name="gold",
        description="✨ Info sobre las Preguntas de Oro y el jackpot actual",
    )
    async def gold_info(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id

        async with self.bot.db.acquire() as conn:
            # Jackpot acumulado actual
            jackpot_row = await conn.fetchrow("""
                SELECT COALESCE(SUM(jackpot), 0) AS total_jackpot
                FROM gold_events
                WHERE guild_id = $1 AND winner_id IS NULL AND is_active = FALSE;
            """, guild_id)

            # Último evento
            last_event = await conn.fetchrow("""
                SELECT * FROM gold_events
                WHERE guild_id = $1
                ORDER BY created_at DESC
                LIMIT 1;
            """, guild_id)

            # Estadísticas globales
            stats = await conn.fetchrow("""
                SELECT
                    COUNT(*) AS total_events,
                    COUNT(winner_id) AS won_events,
                    COUNT(*) - COUNT(winner_id) AS no_winner
                FROM gold_events
                WHERE guild_id = $1 AND is_active = FALSE;
            """, guild_id)

            # Top ganadores de oro
            top_gold = await conn.fetch("""
                SELECT username, gold_wins
                FROM users
                WHERE guild_id = $1 AND gold_wins > 0
                ORDER BY gold_wins DESC
                LIMIT 5;
            """, guild_id)

            # Config
            config = await conn.fetchrow(
                "SELECT * FROM guild_config WHERE guild_id = $1", guild_id
            )

        jackpot = jackpot_row["total_jackpot"] if jackpot_row else 0
        min_pts = config["gold_min_points"] if config else 25
        max_pts = config["gold_max_points"] if config else 40

        embed = discord.Embed(
            title="✨ Pregunta de Oro — Info",
            color=discord.Color.gold(),
        )

        # Jackpot
        if jackpot > 0:
            embed.add_field(
                name="💎 Jackpot acumulado",
                value=f"**{jackpot} puntos**\nSe sumará a la próxima Pregunta de Oro",
                inline=False,
            )
        else:
            embed.add_field(
                name="💎 Jackpot",
                value="Sin jackpot acumulado",
                inline=False,
            )

        # Último evento
        if last_event:
            if last_event["winner_id"]:
                last_info = f"✅ Ganada · **{last_event['reward_points']} pts**"
            else:
                last_info = f"💔 Sin ganador · Jackpot acumulado"

            time_ago = datetime.utcnow() - last_event["created_at"]
            mins_ago = int(time_ago.total_seconds() / 60)
            if mins_ago < 60:
                time_str = f"Hace {mins_ago} min"
            else:
                hours_ago = mins_ago // 60
                time_str = f"Hace {hours_ago}h {mins_ago % 60}m"

            embed.add_field(
                name="🕐 Última Pregunta de Oro",
                value=f"{last_info}\n{time_str}",
                inline=True,
            )

        # Stats
        if stats and stats["total_events"] > 0:
            win_rate = (stats["won_events"] / stats["total_events"]) * 100
            embed.add_field(
                name="📊 Estadísticas",
                value=(
                    f"Total: **{stats['total_events']}**\n"
                    f"Ganadas: **{stats['won_events']}** ({win_rate:.0f}%)\n"
                    f"Sin ganador: **{stats['no_winner']}**"
                ),
                inline=True,
            )

        # Top ganadores
        if top_gold:
            medals = ["🥇", "🥈", "🥉", "4.", "5."]
            top_text = ""
            for i, row in enumerate(top_gold):
                top_text += f"{medals[i]} {row['username']} — **{row['gold_wins']}** victorias\n"
            embed.add_field(
                name="👑 Top cazadores de Oro",
                value=top_text,
                inline=False,
            )

        # Cómo funciona
        embed.add_field(
            name="❓ ¿Cómo funciona?",
            value=(
                f"• Aparece **aleatoriamente** cada {config['gold_interval_min']}-{config['gold_interval_max']} min\n"
                f"• **5%** de probabilidad al usar `/quiz`\n"
                f"• Recompensa: **{min_pts}-{max_pts}** puntos + jackpot\n"
                f"• Solo tienes **1 intento**\n"
                f"• **Primer acierto** gana\n"
                f"• Si nadie acierta → **jackpot acumula**"
            ),
            inline=False,
        )

        embed.set_thumbnail(
            url="https://em-content.zobj.net/source/twitter/376/star_2b50.png"
        )
        embed.timestamp = datetime.utcnow()

        await interaction.response.send_message(embed=embed)

    # ═════════════════════��══════════════════════════════════════
    # /forcegold — Admin: forzar Pregunta de Oro (para testing)
    # ════════════════════════════════════════════════════════════
    @app_commands.command(
        name="forcegold",
        description="⚙️ [Admin] Forzar una Pregunta de Oro ahora",
    )
    @app_commands.default_permissions(administrator=True)
    async def force_gold(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id

        if self._active_events.get(guild_id, False):
            await interaction.response.send_message(
                "⚠️ Ya hay una Pregunta de Oro activa en este servidor.",
                ephemeral=True,
            )
            return

        async with self.bot.db.acquire() as conn:
            config = await conn.fetchrow(
                "SELECT * FROM guild_config WHERE guild_id = $1", guild_id
            )

        if not config:
            # Crear config por defecto
            async with self.bot.db.acquire() as conn:
                await conn.execute(
                    "INSERT INTO guild_config (guild_id) VALUES ($1) ON CONFLICT DO NOTHING;",
                    guild_id,
                )
                config = await conn.fetchrow(
                    "SELECT * FROM guild_config WHERE guild_id = $1", guild_id
                )

        await interaction.response.send_message(
            "✅ ¡Pregunta de Oro forzada! Aparecerá en unos segundos...",
            ephemeral=True,
        )

        await self._launch_gold_event(interaction.guild, dict(config))


# ── Setup ──────────────────────────────────────────────────────
async def setup(bot: commands.Bot):
    await bot.add_cog(GoldCog(bot))