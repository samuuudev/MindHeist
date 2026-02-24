"""
Cog Quiz — /quiz
Preguntas de trivia con cooldown, dificultad variable y generación por IA.
"""

import html
import json
import os
import random
from datetime import datetime

import aiohttp
import discord
import openai
from discord import app_commands
from discord.ext import commands
import logging

log = logging.getLogger("bot.quiz")


# ── Generador de preguntas ─────────────────────────────────────

class QuestionGenerator:
    """Genera preguntas desde OpenAI (primario) u Open Trivia DB (fallback)."""

    OPENAI_PROMPT = """Genera una pregunta de trivia en español.
Categoría: {category}
Dificultad: {difficulty}

Responde SOLO con un JSON válido, sin texto adicional, con este formato exacto:
{{
    "question": "texto de la pregunta",
    "options": ["opción A", "opción B", "opción C", "opción D"],
    "correct_index": 0,
    "category": "{category}"
}}

Reglas:
- La pregunta debe ser interesante y no obvia
- Las 4 opciones deben ser plausibles
- correct_index es el índice (0-3) de la respuesta correcta
- No repitas preguntas típicas de trivia
- Varía los temas dentro de la categoría
- Adaptate a la difucultad solicitada (easy: básica, medium: intermedia, hard: desafiante)
- No incluyas explicaciones ni texto fuera del JSON
- Trata de no generar preguntas con respuestas extremadamente comunes o muy fáciles de adivinar si la difultad es distinta de facil
- Trata de no generar preguntas similares a las antes generadas recientemente para evitar repetición (aunque no es un requisito estricto)
"""

    CATEGORIES = [
        "general", "science", "history", "geography",
        "entertainment", "sports", "logic", "videogames",
        "literature", "art",
    ]

    OPENTDB_CATEGORIES = {
        "general": 9, "science": 17, "history": 23,
        "geography": 22, "entertainment": 11, "sports": 21,
    }

    OPENTDB_DIFFICULTY = {"easy": "easy", "medium": "medium", "hard": "hard"}

    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        self.openai_client = openai.AsyncOpenAI(api_key=api_key) if api_key else None

    async def generate(
        self, difficulty: str = "medium", category: str | None = None,
    ) -> dict | None:
        """Genera una pregunta. Intenta OpenAI primero, fallback a OpenTDB."""
        cat = category or random.choice(self.CATEGORIES)

        if self.openai_client:
            result = await self._from_openai(difficulty, cat)
            if result:
                result["source"] = "openai"
                return result

        result = await self._from_opentdb(difficulty, cat)
        if result:
            result["source"] = "opentdb"
            return result

        return None

    async def _from_openai(self, difficulty: str, category: str) -> dict | None:
        """Genera una pregunta con GPT-4o-mini."""
        try:
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Eres un generador de preguntas de trivia. "
                            "Responde SOLO con JSON válido."
                        ),
                    },
                    {
                        "role": "user",
                        "content": self.OPENAI_PROMPT.format(
                            category=category, difficulty=difficulty,
                        ),
                    },
                ],
                temperature=1.0,
                max_tokens=300,
            )
            content = response.choices[0].message.content.strip()

            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                content = content.rsplit("```", 1)[0]

            data = json.loads(content)

            if (
                "question" in data
                and "options" in data
                and "correct_index" in data
                and len(data["options"]) == 4
                and 0 <= data["correct_index"] <= 3
            ):
                data["category"] = category
                data["difficulty"] = difficulty
                return data

        except Exception as e:
            log.warning(f"Error generando pregunta con OpenAI: {e}")

        return None

    async def _from_opentdb(self, difficulty: str, category: str) -> dict | None:
        """Genera una pregunta desde Open Trivia Database."""
        try:
            cat_id = self.OPENTDB_CATEGORIES.get(category, 9)
            diff = self.OPENTDB_DIFFICULTY.get(difficulty, "medium")
            url = (
                f"https://opentdb.com/api.php?amount=1"
                f"&category={cat_id}&difficulty={diff}&type=multiple"
            )

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()

            if data["response_code"] != 0 or not data["results"]:
                return None

            q = data["results"][0]
            question_text = html.unescape(q["question"])
            correct = html.unescape(q["correct_answer"])
            incorrect = [html.unescape(a) for a in q["incorrect_answers"]]

            options = incorrect + [correct]
            random.shuffle(options)

            return {
                "question": question_text,
                "options": options,
                "correct_index": options.index(correct),
                "category": category,
                "difficulty": difficulty,
            }

        except Exception as e:
            log.warning(f"Error con Open Trivia DB: {e}")

        return None


# ── Vista con botones de respuesta ─────────────────────────────

class QuizView(discord.ui.View):
    """Botones de respuesta para el quiz. Solo el invocador puede responder."""

    LABELS = ["A", "B", "C", "D"]
    EMOJIS = ["🇦", "🇧", "🇨", "🇩"]

    def __init__(self, question_data: dict, user_id: int, timeout_seconds: int = 30):
        super().__init__(timeout=timeout_seconds)
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
                custom_id=f"quiz_option_{i}",
                row=i // 2,
            )
            button.callback = self._make_callback(i)
            self.add_item(button)

    def _make_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message(
                    "Esta pregunta no es para ti. Usa `/quiz` para la tuya.",
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


# ── Cog principal ──────────────────────────────────────────────

DIFFICULTY_DISPLAY = {
    "easy":   {"emoji": "🟢", "name": "Fácil"},
    "medium": {"emoji": "🟡", "name": "Media"},
    "hard":   {"emoji": "🔴", "name": "Difícil"},
}


class QuizCog(commands.Cog):
    """Sistema de quiz con preguntas de trivia."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.generator = QuestionGenerator()
        self._cooldowns: dict[int, datetime] = {}

    # ── /quiz ──────────────────────────────────────────────────

    @app_commands.command(
        name="quiz",
        description="Responde una pregunta de trivia y gana puntos",
    )
    @app_commands.describe(
        difficulty="Dificultad de la pregunta",
        category="Categoría de la pregunta",
    )
    @app_commands.choices(
        difficulty=[
            app_commands.Choice(name="Fácil", value="easy"),
            app_commands.Choice(name="Media", value="medium"),
            app_commands.Choice(name="Difícil", value="hard"),
        ],
        category=[
            app_commands.Choice(name="General", value="general"),
            app_commands.Choice(name="Ciencia", value="science"),
            app_commands.Choice(name="Historia", value="history"),
            app_commands.Choice(name="Geografía", value="geography"),
            app_commands.Choice(name="Entretenimiento", value="entertainment"),
            app_commands.Choice(name="Deportes", value="sports"),
            app_commands.Choice(name="Lógica", value="logic"),
            app_commands.Choice(name="Videojuegos", value="videogames"),
            app_commands.Choice(name="Literatura", value="literature"),
            app_commands.Choice(name="Arte", value="art"),
        ],
    )
    async def quiz(
        self,
        interaction: discord.Interaction,
        difficulty: str = "medium",
        category: str | None = None,
    ):
        user_id = interaction.user.id
        guild_id = interaction.guild_id

        # Cooldown
        config = await self._get_config(guild_id)
        cooldown_min = config["quiz_cooldown_min"] if config else 15

        if user_id in self._cooldowns:
            elapsed = (datetime.utcnow() - self._cooldowns[user_id]).total_seconds()
            remaining = (cooldown_min * 60) - elapsed
            if remaining > 0:
                mins, secs = int(remaining // 60), int(remaining % 60)
                await interaction.response.send_message(
                    f"Cooldown activo. Puedes usar `/quiz` en **{mins}m {secs}s**.",
                    ephemeral=True,
                )
                return

        # Generar pregunta
        await interaction.response.defer(thinking=True)
        question_data = await self.generator.generate(difficulty, category)

        if not question_data:
            await interaction.followup.send(
                "No se pudo generar una pregunta. Inténtalo de nuevo.",
                ephemeral=True,
            )
            return

        question_id = await self._save_question(question_data)
        await self._ensure_user(user_id, guild_id, interaction.user.display_name)

        # Embed
        points = config["quiz_points"] if config else 5
        diff = DIFFICULTY_DISPLAY.get(difficulty, DIFFICULTY_DISPLAY["medium"])

        embed = discord.Embed(
            title="Quiz de Trivia",
            description=f"**{question_data['question']}**",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Dificultad", value=f"{diff['emoji']} {diff['name']}", inline=True)
        embed.add_field(name="Recompensa", value=f"{points} puntos", inline=True)
        embed.add_field(name="Tiempo", value="30 segundos", inline=True)
        embed.set_footer(
            text=f"Pregunta para {interaction.user.display_name} · "
                 f"Fuente: {question_data.get('source', 'desconocida')}",
        )

        # Enviar y esperar
        view = QuizView(question_data, user_id, timeout_seconds=30)
        await interaction.followup.send(embed=embed, view=view)
        self._cooldowns[user_id] = datetime.utcnow()

        timed_out = await view.wait()

        # Timeout
        if timed_out or not view.answered:
            correct_answer = question_data["options"][question_data["correct_index"]]
            timeout_embed = discord.Embed(
                title="Tiempo agotado",
                description=f"La respuesta correcta era: **{correct_answer}**",
                color=discord.Color.orange(),
            )
            await interaction.followup.send(embed=timeout_embed)
            await self._save_answer(
                user_id, guild_id, question_id,
                answered_index=-1, is_correct=False,
                points_earned=0, context="quiz", response_time=30.0,
            )

            logger = self.bot.get_cog("LoggerCog")
            if logger:
                await logger.log_quiz(
                    guild_id=guild_id, user=interaction.user,
                    correct=False, points=0, difficulty=difficulty,
                    category=category or "aleatoria", response_time=30.0,
                )
            return

        # Resultado
        final_points = 0

        if view.is_correct:
            multiplier = await self._get_multiplier(user_id, guild_id)
            final_points = int(points * multiplier)
            await self._update_user_points(user_id, guild_id, final_points)

            desc = f"**+{final_points} puntos**\nRespondiste en **{view.response_time:.1f}s**"
            if multiplier > 1:
                desc += f"\nMultiplicador activo: x{multiplier}"

            result_embed = discord.Embed(
                title="Correcto",
                description=desc,
                color=discord.Color.green(),
            )
            await interaction.followup.send(embed=result_embed)

            await self._save_answer(
                user_id, guild_id, question_id,
                answered_index=view.selected_index, is_correct=True,
                points_earned=final_points, context="quiz",
                response_time=view.response_time,
            )

        else:
            correct_answer = question_data["options"][question_data["correct_index"]]
            result_embed = discord.Embed(
                title="Incorrecto",
                description=(
                    f"La respuesta correcta era: **{correct_answer}**\n"
                    f"Respondiste en **{view.response_time:.1f}s**"
                ),
                color=discord.Color.red(),
            )
            await interaction.followup.send(embed=result_embed)

            await self._save_answer(
                user_id, guild_id, question_id,
                answered_index=view.selected_index, is_correct=False,
                points_earned=0, context="quiz",
                response_time=view.response_time,
            )

        # Log
        logger = self.bot.get_cog("LoggerCog")
        if logger:
            await logger.log_quiz(
                guild_id=guild_id, user=interaction.user,
                correct=view.is_correct, points=final_points,
                difficulty=difficulty, category=category or "aleatoria",
                response_time=view.response_time,
            )

        # Trigger Pregunta de Oro (probabilidad configurable)
        gold_cog = self.bot.get_cog("GoldCog")
        if gold_cog:
            await gold_cog.try_trigger_from_quiz(interaction.guild)

    # ── Base de datos ──────────────────────────────────────────

    async def _get_config(self, guild_id: int) -> dict | None:
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM guild_config WHERE guild_id = $1", guild_id,
            )
            return dict(row) if row else None

    async def _ensure_user(self, user_id: int, guild_id: int, username: str):
        async with self.bot.db.acquire() as conn:
            # Upsert para evitar UniqueViolation en inserciones concurrentes
            await conn.execute(
                """
                INSERT INTO users (user_id, guild_id, username)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id, guild_id) DO UPDATE
                    SET username = EXCLUDED.username, updated_at = NOW();
                """,
                user_id, guild_id, username,
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
                        + CASE WHEN $3 THEN 1 ELSE 0 END,
                    updated_at = NOW()
                WHERE user_id = $1 AND guild_id = $2;
                """,
                user_id, guild_id, is_correct,
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
                VALUES ($1, $2, 'quiz', $3, $3, 'Quiz completado');
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
    cog = QuizCog(bot)
    await bot.add_cog(cog)