"""
Cog Admin — /setup, /config, /set, /give, /reset, /sync, /status
Configuración del servidor, gestión de economía y herramientas de administración.
"""

import json
import time
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands
import logging

log = logging.getLogger("bot.admin")


# ── Vista de confirmación ──────────────────────────────────────

class ConfirmView(discord.ui.View):
    """Botones de confirmación para acciones destructivas."""

    def __init__(self, admin_id: int):
        super().__init__(timeout=30)
        self.admin_id = admin_id
        self.confirmed = False

    @discord.ui.button(label="Confirmar", style=discord.ButtonStyle.danger)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button,
    ):
        if interaction.user.id != self.admin_id:
            await interaction.response.send_message(
                "Solo el administrador puede confirmar.", ephemeral=True,
            )
            return
        self.confirmed = True
        button.disabled = True
        self.children[1].disabled = True
        await interaction.response.edit_message(
            content="Confirmado. Procesando...", view=self,
        )
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button,
    ):
        if interaction.user.id != self.admin_id:
            await interaction.response.send_message(
                "Solo el administrador puede cancelar.", ephemeral=True,
            )
            return
        self.confirmed = False
        button.disabled = True
        self.children[0].disabled = True
        await interaction.response.edit_message(
            content="Cancelado.", view=self,
        )
        self.stop()

    async def on_timeout(self):
        self.confirmed = False
        self.stop()


# ── Validación de parámetros ───────────────────────────────────

PARAM_RULES = {
    "daily_points":        {"type": int, "min": 0,  "max": 10000, "unit": "pts"},
    "quiz_points":         {"type": int, "min": 0,  "max": 10000, "unit": "pts"},
    "gold_min_points":     {"type": int, "min": 0,  "max": 10000, "unit": "pts"},
    "gold_max_points":     {"type": int, "min": 0,  "max": 10000, "unit": "pts"},
    "quiz_cooldown_min":   {"type": int, "min": 1,  "max": 1440,  "unit": "min"},
    "daily_cooldown_hours": {"type": int, "min": 1, "max": 168,   "unit": "horas"},
    "robbery_cooldown_min": {"type": int, "min": 1, "max": 1440,  "unit": "min"},
    "max_robberies_daily": {"type": int, "min": 0,  "max": 50,    "unit": ""},
    "min_money_to_rob":    {"type": int, "min": 0,  "max": 10000, "unit": ""},
    "gold_interval_min":   {"type": int, "min": 1,  "max": 1440,  "unit": "min"},
    "gold_interval_max":   {"type": int, "min": 1,  "max": 1440,  "unit": "min"},
    "gold_quiz_chance":    {"type": float, "min": 0, "max": 100,  "unit": "%"},
}


def validate_param(parameter: str, value: str) -> tuple[float | int, str]:
    """
    Valida y convierte un valor para un parámetro.
    Devuelve (valor_convertido, texto_para_mostrar).
    Lanza ValueError si no es válido.
    """
    rules = PARAM_RULES.get(parameter)
    if not rules:
        raise ValueError(f"Parámetro desconocido: {parameter}")

    if parameter == "gold_quiz_chance":
        num = float(value)
        if not (rules["min"] <= num <= rules["max"]):
            raise ValueError(
                f"Debe estar entre {rules['min']} y {rules['max']}",
            )
        display = f"{num}%"
        return num / 100.0, display

    num = int(value)
    if not (rules["min"] <= num <= rules["max"]):
        raise ValueError(
            f"Debe estar entre {rules['min']} y {rules['max']}",
        )
    unit = f" {rules['unit']}" if rules["unit"] else ""
    return num, f"{num}{unit}"


# ── Cog principal ──────────────────────────────────────────────

class AdminCog(commands.Cog):
    """Configuración y administración del bot por servidor."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /setup ─────────────────────────────────────────────────

    @app_commands.command(
        name="setup",
        description="[Admin] Configuración inicial del bot",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        quiz_channel="Canal para quizzes",
        gold_channel="Canal para Preguntas de Oro",
        log_channel="Canal de logs del bot",
        top1_role="Rol para el Top 1",
        top2_role="Rol para el Top 2",
        top3_role="Rol para el Top 3",
    )
    async def setup(
        self,
        interaction: discord.Interaction,
        quiz_channel: discord.TextChannel | None = None,
        gold_channel: discord.TextChannel | None = None,
        log_channel: discord.TextChannel | None = None,
        top1_role: discord.Role | None = None,
        top2_role: discord.Role | None = None,
        top3_role: discord.Role | None = None,
    ):
        guild_id = interaction.guild_id

        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO guild_config (guild_id) VALUES ($1) "
                "ON CONFLICT DO NOTHING;",
                guild_id,
            )

            updates = []
            values = [guild_id]
            idx = 2

            if quiz_channel:
                updates.append(f"quiz_channel_id = ${idx}")
                values.append(quiz_channel.id)
                idx += 1

            if gold_channel:
                updates.append(f"gold_channel_id = ${idx}")
                values.append(gold_channel.id)
                idx += 1

            if log_channel:
                updates.append(f"log_channel_id = ${idx}")
                values.append(log_channel.id)
                idx += 1

            top_roles = []
            for role in [top1_role, top2_role, top3_role]:
                if role:
                    top_roles.append(role.id)

            if top_roles:
                updates.append(f"top_role_ids = ${idx}::jsonb")
                values.append(json.dumps(top_roles))
                idx += 1

            if updates:
                updates.append("updated_at = NOW()")
                query = (
                    f"UPDATE guild_config SET {', '.join(updates)} "
                    f"WHERE guild_id = $1;"
                )
                await conn.execute(query, *values)

        # Embed de confirmación
        embed = discord.Embed(
            title="Configuración actualizada",
            color=discord.Color.green(),
        )

        if quiz_channel:
            embed.add_field(
                name="Canal Quiz", value=quiz_channel.mention, inline=True,
            )
        if gold_channel:
            embed.add_field(
                name="Canal Oro", value=gold_channel.mention, inline=True,
            )
        if log_channel:
            embed.add_field(
                name="Canal Logs", value=log_channel.mention, inline=True,
            )

        if top_roles:
            labels = ["Top 1", "Top 2", "Top 3"]
            roles_text = ""
            for i, role in enumerate([top1_role, top2_role, top3_role]):
                if role:
                    roles_text += f"{labels[i]}: {role.mention}\n"
            embed.add_field(name="Roles del Top", value=roles_text, inline=False)

        if not any([quiz_channel, gold_channel, log_channel, top_roles]):
            embed.description = (
                "No se modificó nada. Especifica al menos un parámetro.\n"
                "Ejemplo: `/setup gold_channel:#canal`"
            )

        embed.set_footer(text="Usa /config para ver la configuración completa")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /config ────────────────────────────────────────────────

    @app_commands.command(
        name="config",
        description="[Admin] Ver la configuración actual del bot",
    )
    @app_commands.default_permissions(administrator=True)
    async def config(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id

        async with self.bot.db.acquire() as conn:
            cfg = await conn.fetchrow(
                "SELECT * FROM guild_config WHERE guild_id = $1",
                guild_id,
            )

        if not cfg:
            await interaction.response.send_message(
                "No hay configuración para este servidor. Usa `/setup`.",
                ephemeral=True,
            )
            return

        guild = interaction.guild

        def ch_mention(channel_id):
            if not channel_id:
                return "No configurado"
            ch = guild.get_channel(channel_id)
            return ch.mention if ch else f"No encontrado ({channel_id})"

        top_roles = cfg["top_role_ids"] if cfg["top_role_ids"] else []
        if isinstance(top_roles, str):
            top_roles = json.loads(top_roles)

        roles_text = ""
        labels = ["Top 1", "Top 2", "Top 3"]
        for i, role_id in enumerate(top_roles[:3]):
            role = guild.get_role(role_id)
            roles_text += (
                f"{labels[i]}: {role.mention if role else 'No encontrado'}\n"
            )
        if not roles_text:
            roles_text = "No configurados"

        embed = discord.Embed(
            title=f"Configuración — {guild.name}",
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="Canales",
            value=(
                f"Quiz: {ch_mention(cfg['quiz_channel_id'])}\n"
                f"Oro: {ch_mention(cfg['gold_channel_id'])}\n"
                f"Logs: {ch_mention(cfg['log_channel_id'])}"
            ),
            inline=False,
        )

        embed.add_field(
            name="Puntos",
            value=(
                f"Daily: **{cfg['daily_points']}** pts\n"
                f"Quiz: **{cfg['quiz_points']}** pts\n"
                f"Oro: **{cfg['gold_min_points']}-{cfg['gold_max_points']}** pts"
            ),
            inline=True,
        )

        embed.add_field(
            name="Cooldowns",
            value=(
                f"Daily: **{cfg['daily_cooldown_hours']}h**\n"
                f"Quiz: **{cfg['quiz_cooldown_min']}** min\n"
                f"Robo: **{cfg['robbery_cooldown_min']}** min"
            ),
            inline=True,
        )

        embed.add_field(
            name="Robos",
            value=(
                f"Éxito: **{int(cfg['robbery_min_pct'] * 100)}-"
                f"{int(cfg['robbery_max_pct'] * 100)}%** del dinero\n"
                f"Fallo: **-{int(cfg['robbery_fail_pct'] * 100)}%** propio\n"
                f"Máx diarios: **{cfg['max_robberies_daily']}**\n"
                f"Dinero mín víctima: **{cfg['min_money_to_rob']}**"
            ),
            inline=True,
        )

        embed.add_field(
            name="Pregunta de Oro",
            value=(
                f"Intervalo: **{cfg['gold_interval_min']}-"
                f"{cfg['gold_interval_max']}** min.\n"
                f"Chance en /quiz: **{int(cfg['gold_quiz_chance'] * 100)}%**"
            ),
            inline=True,
        )

        embed.add_field(name="Roles del Top", value=roles_text, inline=True)

        embed.set_footer(text="Usa /set para modificar valores individuales")
        embed.timestamp = datetime.utcnow()

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /set ───────────────────────────────────────────────────

    @app_commands.command(
        name="set",
        description="[Admin] Modificar un parámetro de configuración",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        parameter="Parámetro a modificar",
        value="Nuevo valor",
    )
    @app_commands.choices(
        parameter=[
            app_commands.Choice(name="Puntos Daily", value="daily_points"),
            app_commands.Choice(name="Puntos Quiz", value="quiz_points"),
            app_commands.Choice(name="Oro mínimo", value="gold_min_points"),
            app_commands.Choice(name="Oro máximo", value="gold_max_points"),
            app_commands.Choice(name="Cooldown Quiz (min)", value="quiz_cooldown_min"),
            app_commands.Choice(name="Cooldown Daily (horas)", value="daily_cooldown_hours"),
            app_commands.Choice(name="Cooldown Robo (min)", value="robbery_cooldown_min"),
            app_commands.Choice(name="Máx robos diarios", value="max_robberies_daily"),
            app_commands.Choice(name="Dinero mín para robar", value="min_money_to_rob"),
            app_commands.Choice(name="Intervalo Oro mín (min)", value="gold_interval_min"),
            app_commands.Choice(name="Intervalo Oro máx (min)", value="gold_interval_max"),
            app_commands.Choice(name="Chance Oro en Quiz (%)", value="gold_quiz_chance"),
        ],
    )
    async def set_param(
        self,
        interaction: discord.Interaction,
        parameter: str,
        value: str,
    ):
        guild_id = interaction.guild_id

        try:
            num_value, display_value = validate_param(parameter, value)
        except ValueError as e:
            await interaction.response.send_message(
                f"Valor inválido: {e}", ephemeral=True,
            )
            return

        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO guild_config (guild_id) VALUES ($1) "
                "ON CONFLICT DO NOTHING;",
                guild_id,
            )
            await conn.execute(
                f"UPDATE guild_config SET {parameter} = $2, "
                f"updated_at = NOW() WHERE guild_id = $1;",
                guild_id, num_value,
            )

        embed = discord.Embed(
            title="Parámetro actualizado",
            description=f"**{parameter}** = `{display_value}`",
            color=discord.Color.green(),
        )
        embed.set_footer(text="Usa /config para ver toda la configuración")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /give ──────────────────────────────────────────────────

    @app_commands.command(
        name="give",
        description="[Admin] Dar o quitar puntos/dinero a un usuario",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        member="Usuario objetivo",
        amount="Cantidad (negativa para quitar)",
        currency="Tipo de moneda",
    )
    @app_commands.choices(
        currency=[
            app_commands.Choice(name="Puntos", value="points"),
            app_commands.Choice(name="Dinero", value="money"),
            app_commands.Choice(name="Ambos", value="both"),
        ],
    )
    async def give(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: int,
        currency: str = "both",
    ):
        guild_id = interaction.guild_id

        async with self.bot.db.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id = $1 AND guild_id = $2",
                member.id, guild_id,
            )

            if not user:
                # Usar upsert para evitar race condition si otra tarea inserta el usuario
                await conn.execute(
                    """
                    INSERT INTO users (user_id, guild_id, username)
                    VALUES ($1, $2, $3) ON CONFLICT (user_id, guild_id) DO
                    UPDATE
                        SET username = EXCLUDED.username, updated_at = NOW();
                    """,
                    member.id, guild_id, member.display_name,
                )

            if currency == "points":
                await conn.execute(
                    """
                    UPDATE users
                    SET points = GREATEST(0, points + $3), updated_at = NOW()
                    WHERE user_id = $1 AND guild_id = $2;
                    """,
                    member.id, guild_id, amount,
                )
                points_delta, money_delta = amount, 0

            elif currency == "money":
                await conn.execute(
                    """
                    UPDATE users
                    SET money = GREATEST(0, money + $3), updated_at = NOW()
                    WHERE user_id = $1 AND guild_id = $2;
                    """,
                    member.id, guild_id, amount,
                )
                points_delta, money_delta = 0, amount

            else:
                await conn.execute(
                    """
                    UPDATE users
                    SET points = GREATEST(0, points + $3),
                        money = GREATEST(0, money + $3),
                        updated_at = NOW()
                    WHERE user_id = $1 AND guild_id = $2;
                    """,
                    member.id, guild_id, amount,
                )
                points_delta, money_delta = amount, amount

            await conn.execute(
                """
                INSERT INTO transactions
                    (user_id, guild_id, tx_type, points_delta,
                     money_delta, description)
                VALUES ($1, $2, 'admin', $3, $4, $5);
                """,
                member.id, guild_id, points_delta, money_delta,
                f"Admin: {interaction.user.display_name}",
            )

        sign = "+" if amount >= 0 else ""
        action = "Dados" if amount >= 0 else "Quitados"
        desc = f"**{member.display_name}**\n"
        if points_delta != 0:
            desc += f"Puntos: **{sign}{points_delta}**\n"
        if money_delta != 0:
            desc += f"Dinero: **{sign}{money_delta}**\n"

        embed = discord.Embed(
            title=f"{action} por administrador",
            description=desc,
            color=discord.Color.green() if amount >= 0 else discord.Color.red(),
        )
        embed.set_footer(text=f"Por {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed, ephemeral=True)

        logger = self.bot.get_cog("LoggerCog")
        if logger:
            await logger.log_admin_give(
                guild_id=guild_id, admin=interaction.user,
                target=member, points=points_delta, money=money_delta,
            )

    # ── /reset ─────────────────────────────────────────────────

    @app_commands.command(
        name="reset",
        description="[Admin] Resetear datos del servidor",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        target="Qué resetear",
        member="Usuario específico (solo para 'Un usuario')",
    )
    @app_commands.choices(
        target=[
            app_commands.Choice(name="Un usuario", value="user"),
            app_commands.Choice(name="Ranking completo", value="ranking"),
            app_commands.Choice(name="Jackpot de Oro", value="jackpot"),
            app_commands.Choice(name="Cooldowns de todos", value="cooldowns"),
            app_commands.Choice(name="TODO el servidor", value="all"),
        ],
    )
    async def reset(
        self,
        interaction: discord.Interaction,
        target: str,
        member: discord.Member | None = None,
    ):
        guild_id = interaction.guild_id
        logger = self.bot.get_cog("LoggerCog")

        # ── Reset de usuario ──────────────────────────────────
        if target == "user":
            if not member:
                await interaction.response.send_message(
                    "Especifica un usuario con `member:`.",
                    ephemeral=True,
                )
                return

            view = ConfirmView(interaction.user.id)
            await interaction.response.send_message(
                f"¿Resetear TODOS los datos de **{member.display_name}**?",
                view=view, ephemeral=True,
            )
            await view.wait()
            if not view.confirmed:
                return

            async with self.bot.db.acquire() as conn:
                await conn.execute(
                    "DELETE FROM answer_history "
                    "WHERE user_id = $1 AND guild_id = $2;",
                    member.id, guild_id,
                )
                await conn.execute(
                    "DELETE FROM transactions "
                    "WHERE user_id = $1 AND guild_id = $2;",
                    member.id, guild_id,
                )
                await conn.execute(
                    "DELETE FROM robberies "
                    "WHERE (attacker_id = $1 OR victim_id = $1) "
                    "AND guild_id = $2;",
                    member.id, guild_id,
                )
                await conn.execute(
                    "DELETE FROM temp_roles "
                    "WHERE user_id = $1 AND guild_id = $2;",
                    member.id, guild_id,
                )
                await conn.execute(
                    """
                    UPDATE users SET
                        points = 0, money = 0, elo = 1000,
                        daily_streak = 0, last_daily = NULL,
                        gold_wins = 0, total_quizzes = 0,
                        correct_answers = 0, robberies_today = 0,
                        last_robbery = NULL, shield_until = NULL,
                        updated_at = NOW()
                    WHERE user_id = $1 AND guild_id = $2;
                    """,
                    member.id, guild_id,
                )

            await interaction.followup.send(
                f"Datos de **{member.display_name}** reseteados.",
                ephemeral=True,
            )

            if logger:
                await logger.log_admin_reset(
                    guild_id, interaction.user, "Usuario", member,
                )

        # ── Reset de ranking ──────────────────────────────────
        elif target == "ranking":
            view = ConfirmView(interaction.user.id)
            await interaction.response.send_message(
                "¿Resetear puntos, dinero y ELO de **TODOS** los usuarios?",
                view=view, ephemeral=True,
            )
            await view.wait()
            if not view.confirmed:
                return

            async with self.bot.db.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE users SET
                        points = 0, money = 0, elo = 1000,
                        daily_streak = 0, gold_wins = 0,
                        updated_at = NOW()
                    WHERE guild_id = $1;
                    """,
                    guild_id,
                )

            await interaction.followup.send(
                "Ranking del servidor reseteado.", ephemeral=True,
            )

            if logger:
                await logger.log_admin_reset(
                    guild_id, interaction.user, "Ranking completo",
                )

        # ── Reset de jackpot ──────────────────────────────────
        elif target == "jackpot":
            async with self.bot.db.acquire() as conn:
                await conn.execute(
                    "UPDATE gold_events SET jackpot = 0 "
                    "WHERE guild_id = $1 AND winner_id IS NULL;",
                    guild_id,
                )

            await interaction.response.send_message(
                "Jackpot de Pregunta de Oro reseteado a 0.",
                ephemeral=True,
            )

            if logger:
                await logger.log_admin_reset(
                    guild_id, interaction.user, "Jackpot de Oro",
                )

        # ── Reset de cooldowns ────────────────────────────────
        elif target == "cooldowns":
            async with self.bot.db.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE users SET
                        last_daily = NULL,
                        last_robbery = NULL,
                        robberies_today = 0,
                        updated_at = NOW()
                    WHERE guild_id = $1;
                    """,
                    guild_id,
                )

            quiz_cog = self.bot.get_cog("QuizCog")
            if quiz_cog:
                quiz_cog._cooldowns.clear()

            await interaction.response.send_message(
                "Todos los cooldowns reseteados.", ephemeral=True,
            )

            if logger:
                await logger.log_admin_reset(
                    guild_id, interaction.user, "Cooldowns",
                )

        # ── Reset total ───────────────────────────────────────
        elif target == "all":
            view = ConfirmView(interaction.user.id)
            await interaction.response.send_message(
                "**ATENCIÓN:** Esto borrará todos los datos del servidor:\n"
                "Usuarios, historial, robos, transacciones, eventos de Oro "
                "y roles temporales.\n\n"
                "**Esta acción es irreversible.**",
                view=view, ephemeral=True,
            )
            await view.wait()
            if not view.confirmed:
                return

            async with self.bot.db.acquire() as conn:
                for table in [
                    "answer_history", "transactions", "robberies",
                    "temp_roles", "gold_events", "users",
                ]:
                    await conn.execute(
                        f"DELETE FROM {table} WHERE guild_id = $1;",
                        guild_id,
                    )

            quiz_cog = self.bot.get_cog("QuizCog")
            if quiz_cog:
                quiz_cog._cooldowns.clear()

            await interaction.followup.send(
                "**Todos los datos del servidor han sido eliminados.**",
                ephemeral=True,
            )

            if logger:
                await logger.log_admin_reset(
                    guild_id, interaction.user, "TODO el servidor",
                )

    # ── /sync ──────────────────────────────────────────────────

    @app_commands.command(
        name="sync",
        description="[Admin] Sincronizar comandos slash del bot",
    )
    @app_commands.default_permissions(administrator=True)
    async def sync_commands(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            synced = await self.bot.tree.sync()
            await interaction.followup.send(
                f"**{len(synced)} comandos** sincronizados.",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f"Error sincronizando: {e}", ephemeral=True,
            )

    # ── /status ──────────────────────────────────────────────────

    @app_commands.command(
        name="status",
        description="[Admin] Estado del bot y estadísticas del servidor",
    )
    @app_commands.default_permissions(administrator=True)
    async def status(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id

        async with self.bot.db.acquire() as conn:
            total_users = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE guild_id = $1;",
                guild_id,
            )
            active_users = await conn.fetchval(
                """
                SELECT COUNT(*) FROM users
                WHERE guild_id = $1
                  AND updated_at > NOW() - INTERVAL '7 days';
                """,
                guild_id,
            )
            total_quizzes = await conn.fetchval(
                "SELECT COUNT(*) FROM answer_history WHERE guild_id = $1;",
                guild_id,
            )
            quizzes_today = await conn.fetchval(
                """
                SELECT COUNT(*) FROM answer_history
                WHERE guild_id = $1
                  AND answered_at > NOW() - INTERVAL '1 day';
                """,
                guild_id,
            )
            total_robberies = await conn.fetchval(
                "SELECT COUNT(*) FROM robberies WHERE guild_id = $1;",
                guild_id,
            )
            total_gold = await conn.fetchval(
                "SELECT COUNT(*) FROM gold_events WHERE guild_id = $1;",
                guild_id,
            )
            jackpot = await conn.fetchval(
                """
                SELECT COALESCE(SUM(jackpot), 0) FROM gold_events
                WHERE guild_id = $1 AND winner_id IS NULL
                  AND is_active = FALSE;
                """,
                guild_id,
            )
            total_questions = await conn.fetchval(
                "SELECT COUNT(*) FROM questions;",
            )
            active_temp_roles = await conn.fetchval(
                """
                SELECT COUNT(*) FROM temp_roles
                WHERE guild_id = $1 AND removed = FALSE
                  AND expires_at > NOW();
                """,
                guild_id,
            )

        cogs_loaded = list(self.bot.cogs.keys())
        uptime_seconds = time.time() - self.bot._uptime
        hours = int(uptime_seconds // 3600)
        mins = int((uptime_seconds % 3600) // 60)

        embed = discord.Embed(
            title=f"Estado del Bot — {interaction.guild.name}",
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="Usuarios",
            value=(
                f"Total: **{total_users}**\n"
                f"Activos (7d): **{active_users}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="Partidas",
            value=(
                f"Total: **{total_quizzes}**\n"
                f"Hoy: **{quizzes_today}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="Robos / Oro",
            value=(
                f"Robos: **{total_robberies}**\n"
                f"Eventos Oro: **{total_gold}**\n"
                f"Jackpot: **{jackpot}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="Base de datos",
            value=(
                f"Preguntas cacheadas: **{total_questions}**\n"
                f"Roles temporales activos: **{active_temp_roles}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="Bot",
            value=(
                f"Servidores: **{len(self.bot.guilds)}**\n"
                f"Cogs: **{len(cogs_loaded)}** "
                f"({', '.join(cogs_loaded)})\n"
                f"Latencia: **{self.bot.latency * 1000:.0f}ms**\n"
                f"Uptime: **{hours}h {mins}m**"
            ),
            inline=False,
        )

        embed.timestamp = datetime.utcnow()
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))