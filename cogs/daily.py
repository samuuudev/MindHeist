"""
Cog Daily — /daily, /streak
Pregunta diaria con sistema de rachas y bonus acumulativo.
"""

import json
import random
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands
import logging

log = logging.getLogger("bot.daily")


# ── Vista de respuesta ─────────────────────────────────────────

class DailyView(discord.ui.View):
    """Botones de respuesta para la pregunta diaria."""

    EMOJIS = ["🇦", "🇧", "🇨", "🇩"]

    def __init__(self, question_data: dict, user_id: int):
        super().__init__(timeout=60)
        self.question_data = question_data
        self.user_id = user_id
        self.answered = False
        self.selected_index: int | None = None
        self.is_correct: bool = False
        self.response_time: float = 0.0
        self._start_time = datetime.utcnow()

        for i, option in enumerate(question_data["options"]):
            button = discord.ui.Button(
                label=option,
                emoji=self.EMOJIS[i],
                style=discord.ButtonStyle.secondary,
                custom_id=f"daily_option_{i}",
                row=i // 2,
            )
            button.callback = self._make_callback(i)
            self.add_item(button)

    def _make_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message(
                    "Esta pregunta diaria no es para ti.",
                    ephemeral=True,
                )
                return

            if self.answered:
                await interaction.response.send_message(
                    "Ya has respondido.", ephemeral=True,
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


# ── Helpers de racha ───────────────────────────────────────────

STREAK_TIERS = [
    (30, "MAX"),
    (14, "|||"),
    (7,  "||"),
    (3,  "|"),
    (1,  "."),
    (0,  "-"),
]

STREAK_MESSAGES = {
    1:  "Primer día. Empieza la racha.",
    2:  "2 días seguidos. Sigue así.",
    3:  "3 días. La constancia paga.",
    5:  "5 días. Imparable.",
    7:  "Una semana entera.",
    10: "10 días. Pocos llegan aquí.",
    14: "2 semanas. Leyenda del servidor.",
    21: "3 semanas consecutivas.",
    30: "Un mes completo. Respeto absoluto.",
}

MAX_STREAK_BONUS = 20  # Máximo bonus de racha (+2 por día, cap en día 11)


def get_streak_tier(streak: int) -> str:
    """Devuelve un indicador visual de la racha."""
    for threshold, label in STREAK_TIERS:
        if streak >= threshold:
            return label
    return "-"


def get_streak_message(streak: int) -> str:
    """Devuelve un mensaje según el hito de racha alcanzado."""
    for days in sorted(STREAK_MESSAGES.keys(), reverse=True):
        if streak >= days:
            return STREAK_MESSAGES[days]
    return ""


def calculate_streak_bonus(streak: int) -> int:
    """Calcula el bonus de puntos por racha (máximo +20)."""
    return min((streak - 1) * 2, MAX_STREAK_BONUS)


# ── Cog principal ──────────────────────────────────────────────

class DailyCog(commands.Cog):
    """Sistema de pregunta diaria con rachas acumulativas."""

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

    # ── /daily ─────────────────────────────────────────────────

    @app_commands.command(
        name="daily",
        description="Responde tu pregunta diaria y mantén tu racha",
    )
    async def daily(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        guild_id = interaction.guild_id

        user = await self._ensure_user(
            user_id, guild_id, interaction.user.display_name,
        )

        # Cooldown
        config = await self._get_config(guild_id)
        cooldown_hours = config["daily_cooldown_hours"] if config else 24
        base_points = config["daily_points"] if config else 10

        if user["last_daily"]:
            elapsed = datetime.utcnow() - user["last_daily"]
            remaining = timedelta(hours=cooldown_hours) - elapsed

            if remaining.total_seconds() > 0:
                hours = int(remaining.total_seconds() // 3600)
                mins = int((remaining.total_seconds() % 3600) // 60)

                embed = discord.Embed(
                    title="Ya usaste tu daily hoy",
                    description=(
                        f"Vuelve en **{hours}h {mins}m**\n\n"
                        f"Racha actual: **{user['daily_streak']} días**\n"
                        f"Puntos totales: **{user['points']}**"
                    ),
                    color=discord.Color.orange(),
                )
                await interaction.response.send_message(
                    embed=embed, ephemeral=True,
                )
                return

        # Calcular racha
        current_streak = user["daily_streak"]

        if user["last_daily"]:
            hours_since = (
                datetime.utcnow() - user["last_daily"]
            ).total_seconds() / 3600
            new_streak = current_streak + 1 if hours_since <= 48 else 1
        else:
            new_streak = 1

        # Puntos
        streak_bonus = calculate_streak_bonus(new_streak)
        multiplier = await self._get_multiplier(user_id, guild_id)
        total_points = int((base_points + streak_bonus) * multiplier)

        # Generar pregunta
        await interaction.response.defer(thinking=True)
        question_data = await self.generator.generate(
            difficulty="medium", category=None,
        )

        if not question_data:
            await interaction.followup.send(
                "No se pudo generar una pregunta. Inténtalo de nuevo.",
                ephemeral=True,
            )
            return

        question_id = await self._save_question(question_data)

        # Embed
        reward_text = f"{base_points} base + {streak_bonus} racha"
        if multiplier > 1:
            reward_text += f" (x{multiplier})"
        reward_text += f" = **{total_points} pts**"

        embed = discord.Embed(
            title="Pregunta Diaria",
            description=f"**{question_data['question']}**",
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="Racha",
            value=f"[{get_streak_tier(new_streak)}] **{new_streak} días**",
            inline=True,
        )
        embed.add_field(name="Recompensa", value=reward_text, inline=True)
        embed.add_field(name="Tiempo", value="60 segundos", inline=True)
        embed.set_footer(text=f"Pregunta para {interaction.user.display_name}")

        # Enviar y esperar
        view = DailyView(question_data, user_id)
        await interaction.followup.send(embed=embed, view=view)
        timed_out = await view.wait()

        # Timeout
        if timed_out or not view.answered:
            await self._update_daily(user_id, guild_id, streak=0)

            correct_answer = question_data["options"][question_data["correct_index"]]
            timeout_embed = discord.Embed(
                title="Tiempo agotado",
                description=(
                    f"La respuesta era: **{correct_answer}**\n\n"
                    f"**Racha perdida.** Volviste a 0 días."
                ),
                color=discord.Color.dark_red(),
            )
            await interaction.followup.send(embed=timeout_embed)

            await self._save_answer(
                user_id, guild_id, question_id,
                answered_index=-1, is_correct=False,
                points_earned=0, context="daily", response_time=60.0,
            )

            logger = self.bot.get_cog("LoggerCog")
            if logger:
                await logger.log_daily(
                    guild_id=guild_id, user=interaction.user,
                    correct=False, points=0, streak=0,
                )
            return

        # Acierto
        if view.is_correct:
            await self._update_daily(user_id, guild_id, streak=new_streak)
            await self._update_user_points(user_id, guild_id, total_points)

            streak_msg = get_streak_message(new_streak)
            desc = (
                f"**+{total_points} puntos**\n"
                f"Respondiste en **{view.response_time:.1f}s**\n\n"
                f"Racha: **{new_streak} días** [{get_streak_tier(new_streak)}]"
            )
            if streak_msg:
                desc += f"\n{streak_msg}"

            result_embed = discord.Embed(
                title="Correcto",
                description=desc,
                color=discord.Color.green(),
            )
            await interaction.followup.send(embed=result_embed)

            await self._save_answer(
                user_id, guild_id, question_id,
                answered_index=view.selected_index, is_correct=True,
                points_earned=total_points, context="daily",
                response_time=view.response_time,
            )

        # Fallo
        else:
            await self._update_daily(user_id, guild_id, streak=0)

            correct_answer = question_data["options"][question_data["correct_index"]]
            result_embed = discord.Embed(
                title="Incorrecto",
                description=(
                    f"La respuesta correcta era: **{correct_answer}**\n"
                    f"Respondiste en **{view.response_time:.1f}s**\n\n"
                    f"**Racha de {current_streak} días perdida.** "
                    f"Mañana empiezas de nuevo."
                ),
                color=discord.Color.red(),
            )
            await interaction.followup.send(embed=result_embed)

            await self._save_answer(
                user_id, guild_id, question_id,
                answered_index=view.selected_index, is_correct=False,
                points_earned=0, context="daily",
                response_time=view.response_time,
            )

        # Log
        logger = self.bot.get_cog("LoggerCog")
        if logger:
            if view.is_correct:
                await logger.log_daily(
                    guild_id=guild_id, user=interaction.user,
                    correct=True, points=total_points, streak=new_streak,
                )
            else:
                await logger.log_daily(
                    guild_id=guild_id, user=interaction.user,
                    correct=False, points=0, streak=0,
                )

    # ── /streak ────────────────────────────────────────────────

    @app_commands.command(
        name="streak",
        description="Consulta tu racha diaria actual",
    )
    async def streak(self, interaction: discord.Interaction):
        user = await self._ensure_user(
            interaction.user.id,
            interaction.guild_id,
            interaction.user.display_name,
        )

        streak = user["daily_streak"]
        bonus = calculate_streak_bonus(streak + 1)  # Bonus del próximo día

        # Próximo daily
        next_daily = "Disponible ahora"
        if user["last_daily"]:
            config = await self._get_config(interaction.guild_id)
            cooldown_hours = config["daily_cooldown_hours"] if config else 24
            elapsed = datetime.utcnow() - user["last_daily"]
            remaining = timedelta(hours=cooldown_hours) - elapsed

            if remaining.total_seconds() > 0:
                hours = int(remaining.total_seconds() // 3600)
                mins = int((remaining.total_seconds() % 3600) // 60)
                next_daily = f"En **{hours}h {mins}m**"

                hours_since = elapsed.total_seconds() / 3600
                if hours_since > 36:
                    next_daily += "\n*Cuidado: tu racha expira pronto.*"

        embed = discord.Embed(
            title=f"Racha de {interaction.user.display_name}",
            color=discord.Color.orange(),
        )
        embed.add_field(
            name="Racha actual",
            value=f"[{get_streak_tier(streak)}] **{streak} días**",
            inline=True,
        )
        embed.add_field(
            name="Bonus activo",
            value=f"+{bonus} puntos extra",
            inline=True,
        )
        embed.add_field(name="Próximo /daily", value=next_daily, inline=False)

        progression = (
            "```\n"
            "Día   Bonus   Total\n"
            "───────────────────\n"
            " 1     +0     10 pts\n"
            " 2     +2     12 pts\n"
            " 3     +4     14 pts\n"
            " 5     +8     18 pts\n"
            " 7    +12     22 pts\n"
            "10    +18     28 pts\n"
            "11+   +20     30 pts (máx)\n"
            "```"
        )
        embed.add_field(name="Progresión", value=progression, inline=False)

        await interaction.response.send_message(embed=embed)

    # ── Base de datos ──────────────────────────────────────────

    async def _get_config(self, guild_id: int) -> dict | None:
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM guild_config WHERE guild_id = $1", guild_id,
            )
            return dict(row) if row else None

    async def _ensure_user(self, user_id: int, guild_id: int, username: str):
        async with self.bot.db.acquire() as conn:
            # Hacemos un upsert para evitar race conditions que provoquen UniqueViolation
            await conn.execute(
                """
                INSERT INTO users (user_id, guild_id, username)
                VALUES ($1, $2, $3) ON CONFLICT (user_id) DO
                UPDATE
                    SET username = EXCLUDED.username, updated_at = NOW();
                """,
                user_id, guild_id, username,
            )

            # Recuperamos la fila ya existente/actualizada para devolverla
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id = $1 AND guild_id = $2",
                user_id, guild_id,
            )
            return user

    async def _update_daily(self, user_id: int, guild_id: int, streak: int):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE users
                SET last_daily = NOW(), daily_streak = $3, updated_at = NOW()
                WHERE user_id = $1 AND guild_id = $2;
                """,
                user_id, guild_id, streak,
            )

    async def _save_question(self, data: dict) -> int:
        async with self.bot.db.acquire() as conn:
            return await conn.fetchval(
                """
                INSERT INTO questions
                    (content, options, correct_index, difficulty, category, source)
                VALUES ($1, $2::jsonb, $3, $4::question_difficulty,
                        $5::question_category, $6::question_source)
                RETURNING question_id;
                """,
                data["question"],
                json.dumps(data["options"]),
                data["correct_index"],
                data.get("difficulty", "medium"),
                data.get("category", "general"),
                data.get("source", "openai"),
            )

    async def _save_answer(
        self, user_id, guild_id, question_id,
        answered_index, is_correct, points_earned,
        context, response_time,
    ):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO answer_history
                    (user_id, guild_id, question_id, answered_index,
                     is_correct, points_earned, context, response_time)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8);
                """,
                user_id, guild_id, question_id, answered_index,
                is_correct, points_earned, context, response_time,
            )
            await conn.execute(
                """
                UPDATE users
                SET total_quizzes = total_quizzes + 1,
                    correct_answers = correct_answers
                        + CASE WHEN $2 THEN 1 ELSE 0 END,
                    updated_at = NOW()
                WHERE user_id = $1;
                """,
                user_id, is_correct,
            )
            await conn.execute(
                """
                UPDATE questions
                SET times_used = times_used + 1,
                    times_correct = times_correct
                        + CASE WHEN $2 THEN 1 ELSE 0 END
                WHERE question_id = $1;
                """,
                question_id, is_correct,
            )

    async def _update_user_points(self, user_id: int, guild_id: int, points: int):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """
                UPDATE users
                SET points = points + $3, money = money + $3, updated_at = NOW()
                WHERE user_id = $1 AND guild_id = $2;
                """,
                user_id, guild_id, points,
            )
            await conn.execute(
                """
                INSERT INTO transactions
                    (user_id, guild_id, tx_type, points_delta,
                     money_delta, description)
                VALUES ($1, $2, 'daily', $3, $3, 'Pregunta diaria completada');
                """,
                user_id, guild_id, points,
            )

    async def _get_multiplier(self, user_id: int, guild_id: int) -> float:
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT multiplier FROM temp_roles
                WHERE user_id = $1 AND guild_id = $2
                  AND role_type = 'multiplier'
                  AND removed = FALSE
                  AND expires_at > NOW()
                ORDER BY multiplier DESC
                LIMIT 1;
                """,
                user_id, guild_id,
            )
            return row["multiplier"] if row else 1.0


async def setup(bot: commands.Bot):
    await bot.add_cog(DailyCog(bot))