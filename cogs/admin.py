"""
Cog de Administración — /config, /setup, /reset
Configuración del servidor, gestión de canales, roles y parámetros del bot.
"""

import json
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands
import logging

log = logging.getLogger("bot.admin")


# ── Cog principal ──────────────────────────────────────────────
class AdminCog(commands.Cog):
    """Configuración y administración del bot por servidor."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ════════════════════════════════════════════════════════════
    # /setup — Configuración inicial rápida
    # ════════════════════════════════════════════════════════════
    @app_commands.command(
        name="setup",
        description="⚙️ [Admin] Configuración inicial del bot en el servidor",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        quiz_channel="Canal donde se envían los quizzes",
        gold_channel="Canal donde se anuncian las Preguntas de Oro",
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
            # Crear config si no existe
            await conn.execute(
                "INSERT INTO guild_config (guild_id) VALUES ($1) ON CONFLICT DO NOTHING;",
                guild_id,
            )

            # Construir updates dinámicamente
            updates = []
            values = [guild_id]
            param_idx = 2

            if quiz_channel:
                updates.append(f"quiz_channel_id = ${param_idx}")
                values.append(quiz_channel.id)
                param_idx += 1

            if gold_channel:
                updates.append(f"gold_channel_id = ${param_idx}")
                values.append(gold_channel.id)
                param_idx += 1

            if log_channel:
                updates.append(f"log_channel_id = ${param_idx}")
                values.append(log_channel.id)
                param_idx += 1

            # Roles del top
            top_roles = []
            if top1_role:
                top_roles.append(top1_role.id)
            if top2_role:
                top_roles.append(top2_role.id)
            if top3_role:
                top_roles.append(top3_role.id)

            if top_roles:
                updates.append(f"top_role_ids = ${param_idx}::jsonb")
                values.append(json.dumps(top_roles))
                param_idx += 1

            if updates:
                updates.append("updated_at = NOW()")
                query = f"UPDATE guild_config SET {', '.join(updates)} WHERE guild_id = $1;"
                await conn.execute(query, *values)

        # Embed de confirmación
        embed = discord.Embed(
            title="⚙️ Configuración actualizada",
            color=discord.Color.green(),
        )

        if quiz_channel:
            embed.add_field(name="🧠 Canal Quiz", value=quiz_channel.mention, inline=True)
        if gold_channel:
            embed.add_field(name="✨ Canal Oro", value=gold_channel.mention, inline=True)
        if log_channel:
            embed.add_field(name="📋 Canal Logs", value=log_channel.mention, inline=True)
        if top_roles:
            roles_text = ""
            labels = ["👑 Top 1", "🥈 Top 2", "🥉 Top 3"]
            for i, role in enumerate([top1_role, top2_role, top3_role]):
                if role:
                    roles_text += f"{labels[i]}: {role.mention}\n"
            embed.add_field(name="🏆 Roles del Top", value=roles_text, inline=False)

        if not any([quiz_channel, gold_channel, log_channel, top_roles]):
            embed.description = (
                "No se modificó nada. Usa los parámetros para configurar:\n"
                "`/setup quiz_channel:#canal gold_channel:#canal ...`"
            )

        embed.set_footer(text="Usa /config para ver la configuración completa")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ════════════════════════════════════════════════════════════
    # /config — Ver configuración actual
    # ═══════════════════════════════════════════════════��════════
    @app_commands.command(
        name="config",
        description="⚙️ [Admin] Ver la configuración actual del bot",
    )
    @app_commands.default_permissions(administrator=True)
    async def config(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id

        async with self.bot.db.acquire() as conn:
            cfg = await conn.fetchrow(
                "SELECT * FROM guild_config WHERE guild_id = $1", guild_id
            )

        if not cfg:
            await interaction.response.send_message(
                "⚠️ No hay configuración para este servidor. Usa `/setup` primero.",
                ephemeral=True,
            )
            return

        guild = interaction.guild

        # Resolver canales
        def channel_mention(channel_id):
            if not channel_id:
                return "❌ No configurado"
            ch = guild.get_channel(channel_id)
            return ch.mention if ch else f"⚠️ Canal no encontrado ({channel_id})"

        # Resolver roles
        top_roles = cfg["top_role_ids"] if cfg["top_role_ids"] else []
        if isinstance(top_roles, str):
            top_roles = json.loads(top_roles)

        roles_text = ""
        labels = ["👑 Top 1", "🥈 Top 2", "🥉 Top 3"]
        for i, role_id in enumerate(top_roles[:3]):
            role = guild.get_role(role_id)
            roles_text += f"{labels[i]}: {role.mention if role else '⚠️ No encontrado'}\n"
        if not roles_text:
            roles_text = "❌ No configurados"

        embed = discord.Embed(
            title=f"⚙️ Configuración — {guild.name}",
            color=discord.Color.blurple(),
        )

        # Canales
        embed.add_field(
            name="📺 Canales",
            value=(
                f"🧠 Quiz: {channel_mention(cfg['quiz_channel_id'])}\n"
                f"✨ Oro: {channel_mention(cfg['gold_channel_id'])}\n"
                f"📋 Logs: {channel_mention(cfg['log_channel_id'])}"
            ),
            inline=False,
        )

        # Puntos
        embed.add_field(
            name="🏆 Puntos",
            value=(
                f"📅 Daily: **{cfg['daily_points']}** pts\n"
                f"🧠 Quiz: **{cfg['quiz_points']}** pts\n"
                f"✨ Oro: **{cfg['gold_min_points']}-{cfg['gold_max_points']}** pts"
            ),
            inline=True,
        )

        # Cooldowns
        embed.add_field(
            name="⏱️ Cooldowns",
            value=(
                f"📅 Daily: **{cfg['daily_cooldown_hours']}h**\n"
                f"🧠 Quiz: **{cfg['quiz_cooldown_min']}** min\n"
                f"🗡️ Robo: **{cfg['robbery_cooldown_min']}** min"
            ),
            inline=True,
        )

        # Robos
        embed.add_field(
            name="🗡️ Robos",
            value=(
                f"Robo éxito: **{int(cfg['robbery_min_pct']*100)}-{int(cfg['robbery_max_pct']*100)}%**\n"
                f"Robo fallo: **-{int(cfg['robbery_fail_pct']*100)}%**\n"
                f"Máx diarios: **{cfg['max_robberies_daily']}**\n"
                f"Dinero mín víctima: **{cfg['min_money_to_rob']}** 💰"
            ),
            inline=True,
        )

        # Pregunta de Oro
        embed.add_field(
            name="✨ Pregunta de Oro",
            value=(
                f"Intervalo: **{cfg['gold_interval_min']}-{cfg['gold_interval_max']}** min\n"
                f"Chance en /quiz: **{int(cfg['gold_quiz_chance']*100)}%**"
            ),
            inline=True,
        )

        # Roles
        embed.add_field(
            name="🏅 Roles del Top",
            value=roles_text,
            inline=True,
        )

        embed.set_footer(text="Usa /set para modificar valores individuales")
        embed.timestamp = datetime.utcnow()

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ════════════════════════════════════════════════════════════
    # /set — Modificar parámetros individuales
    # ════════════════════════════════════════════════════════════
    @app_commands.command(
        name="set",
        description="⚙️ [Admin] Modificar un parámetro de configuración",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        parameter="Parámetro a modificar",
        value="Nuevo valor",
    )
    @app_commands.choices(
        parameter=[
            app_commands.Choice(name="📅 Puntos Daily", value="daily_points"),
            app_commands.Choice(name="🧠 Puntos Quiz", value="quiz_points"),
            app_commands.Choice(name="✨ Oro mínimo", value="gold_min_points"),
            app_commands.Choice(name="✨ Oro máximo", value="gold_max_points"),
            app_commands.Choice(name="⏱️ Cooldown Quiz (min)", value="quiz_cooldown_min"),
            app_commands.Choice(name="⏱️ Cooldown Daily (horas)", value="daily_cooldown_hours"),
            app_commands.Choice(name="⏱️ Cooldown Robo (min)", value="robbery_cooldown_min"),
            app_commands.Choice(name="🗡️ Máx robos diarios", value="max_robberies_daily"),
            app_commands.Choice(name="🗡️ Dinero mín para robar", value="min_money_to_rob"),
            app_commands.Choice(name="✨ Intervalo Oro mín (min)", value="gold_interval_min"),
            app_commands.Choice(name="✨ Intervalo Oro máx (min)", value="gold_interval_max"),
            app_commands.Choice(name="✨ Chance Oro en Quiz (%)", value="gold_quiz_chance"),
        ],
    )
    async def set_param(
        self,
        interaction: discord.Interaction,
        parameter: str,
        value: str,
    ):
        guild_id = interaction.guild_id

        # Validar que el valor sea numérico
        try:
            if parameter == "gold_quiz_chance":
                # Convertir porcentaje a decimal
                num_value = float(value) / 100.0
                if not (0 <= num_value <= 1):
                    raise ValueError("El porcentaje debe estar entre 0 y 100")
                display_value = f"{value}%"
            elif parameter in ("daily_cooldown_hours",):
                num_value = int(value)
                if num_value < 1 or num_value > 168:
                    raise ValueError("Debe estar entre 1 y 168 horas")
                display_value = f"{num_value} horas"
            elif "cooldown" in parameter or "interval" in parameter:
                num_value = int(value)
                if num_value < 1 or num_value > 1440:
                    raise ValueError("Debe estar entre 1 y 1440 minutos")
                display_value = f"{num_value} minutos"
            elif "points" in parameter or "money" in parameter or "min_money" in parameter:
                num_value = int(value)
                if num_value < 0 or num_value > 10000:
                    raise ValueError("Debe estar entre 0 y 10000")
                display_value = f"{num_value} pts"
            elif "robberies" in parameter:
                num_value = int(value)
                if num_value < 0 or num_value > 50:
                    raise ValueError("Debe estar entre 0 y 50")
                display_value = str(num_value)
            else:
                num_value = int(value)
                display_value = str(num_value)

        except ValueError as e:
            await interaction.response.send_message(
                f"❌ Valor inválido: {e}",
                ephemeral=True,
            )
            return

        # Actualizar en DB
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO guild_config (guild_id) VALUES ($1) ON CONFLICT DO NOTHING;",
                guild_id,
            )
            await conn.execute(
                f"UPDATE guild_config SET {parameter} = $2, updated_at = NOW() WHERE guild_id = $1;",
                guild_id, num_value,
            )

        embed = discord.Embed(
            title="✅ Parámetro actualizado",
            description=f"**{parameter}** = `{display_value}`",
            color=discord.Color.green(),
        )
        embed.set_footer(text="Usa /config para ver toda la configuración")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ════════════════════════════════════════════════════════════
    # /give — Dar puntos/dinero a un usuario (admin)
    # ════════════════════════════════════════════════════════════
    @app_commands.command(
        name="give",
        description="⚙️ [Admin] Dar puntos o dinero a un usuario",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        member="Usuario al que dar puntos/dinero",
        amount="Cantidad (puede ser negativa para quitar)",
        currency="Tipo de moneda",
    )
    @app_commands.choices(
        currency=[
            app_commands.Choice(name="⭐ Puntos", value="points"),
            app_commands.Choice(name="💰 Dinero", value="money"),
            app_commands.Choice(name="⭐💰 Ambos", value="both"),
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
            # Verificar que el usuario existe
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id = $1 AND guild_id = $2",
                member.id, guild_id,
            )

            if not user:
                await conn.execute("""
                    INSERT INTO users (user_id, guild_id, username)
                    VALUES ($1, $2, $3);
                """, member.id, guild_id, member.display_name)

            # Aplicar cambios
            if currency == "points":
                await conn.execute("""
                    UPDATE users SET points = GREATEST(0, points + $3), updated_at = NOW()
                    WHERE user_id = $1 AND guild_id = $2;
                """, member.id, guild_id, amount)
                points_delta = amount
                money_delta = 0
            elif currency == "money":
                await conn.execute("""
                    UPDATE users SET money = GREATEST(0, money + $3), updated_at = NOW()
                    WHERE user_id = $1 AND guild_id = $2;
                """, member.id, guild_id, amount)
                points_delta = 0
                money_delta = amount
            else:  # both
                await conn.execute("""
                    UPDATE users
                    SET points = GREATEST(0, points + $3),
                        money = GREATEST(0, money + $3),
                        updated_at = NOW()
                    WHERE user_id = $1 AND guild_id = $2;
                """, member.id, guild_id, amount)
                points_delta = amount
                money_delta = amount

            # Registrar transacción
            await conn.execute("""
                INSERT INTO transactions
                    (user_id, guild_id, tx_type, points_delta, money_delta, description)
                VALUES ($1, $2, 'admin', $3, $4, $5);
            """, member.id, guild_id, points_delta, money_delta,
                f"Admin: {interaction.user.display_name}",
            )

        action = "Dados" if amount >= 0 else "Quitados"
        embed = discord.Embed(
            title=f"{'➕' if amount >= 0 else '➖'} {action} por admin",
            description=(
                f"**{member.display_name}**\n"
                + (f"⭐ Puntos: **{'+' if amount >= 0 else ''}{points_delta}**\n" if points_delta != 0 else "")
                + (f"💰 Dinero: **{'+' if amount >= 0 else ''}{money_delta}**\n" if money_delta != 0 else "")
            ),
            color=discord.Color.green() if amount >= 0 else discord.Color.red(),
        )
        embed.set_footer(text=f"Por {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ════════════════════════════════════════════════════════════
    # /reset — Resetear datos
    # ════════════════════════════════════════════════════════════
    @app_commands.command(
        name="reset",
        description="⚙️ [Admin] Resetear datos de un usuario o del servidor",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        target="Qué resetear",
        member="Usuario específico (solo para 'usuario')",
    )
    @app_commands.choices(
        target=[
            app_commands.Choice(name="👤 Un usuario", value="user"),
            app_commands.Choice(name="🏆 Ranking completo", value="ranking"),
            app_commands.Choice(name="💎 Jackpot de Oro", value="jackpot"),
            app_commands.Choice(name="⏱️ Cooldowns de todos", value="cooldowns"),
            app_commands.Choice(name="☢️ TODO el servidor", value="all"),
        ],
    )
    async def reset(
        self,
        interaction: discord.Interaction,
        target: str,
        member: discord.Member | None = None,
    ):
        guild_id = interaction.guild_id

        if target == "user":
            if not member:
                await interaction.response.send_message(
                    "❌ Debes especificar un usuario con `member:`",
                    ephemeral=True,
                )
                return
            # Confirmación
            view = ConfirmView(interaction.user.id)
            await interaction.response.send_message(
                f"⚠️ ¿Seguro que quieres resetear TODOS los datos de **{member.display_name}**?",
                view=view,
                ephemeral=True,
            )
            await view.wait()
            if not view.confirmed:
                return

            async with self.bot.db.acquire() as conn:
                await conn.execute(
                    "DELETE FROM answer_history WHERE user_id = $1 AND guild_id = $2;",
                    member.id, guild_id,
                )
                await conn.execute(
                    "DELETE FROM transactions WHERE user_id = $1 AND guild_id = $2;",
                    member.id, guild_id,
                )
                await conn.execute(
                    "DELETE FROM robberies WHERE (attacker_id = $1 OR victim_id = $1) AND guild_id = $2;",
                    member.id, guild_id,
                )
                await conn.execute(
                    "DELETE FROM temp_roles WHERE user_id = $1 AND guild_id = $2;",
                    member.id, guild_id,
                )
                await conn.execute("""
                    UPDATE users SET
                        points = 0, money = 0, elo = 1000,
                        daily_streak = 0, last_daily = NULL,
                        gold_wins = 0, total_quizzes = 0,
                        correct_answers = 0, robberies_today = 0,
                        last_robbery = NULL, shield_until = NULL,
                        updated_at = NOW()
                    WHERE user_id = $1 AND guild_id = $2;
                """, member.id, guild_id)

            await interaction.followup.send(
                f"✅ Datos de **{member.display_name}** reseteados.",
                ephemeral=True,
            )

        elif target == "ranking":
            view = ConfirmView(interaction.user.id)
            await interaction.response.send_message(
                "⚠️ ¿Seguro que quieres resetear **puntos y dinero de TODOS** los usuarios?",
                view=view,
                ephemeral=True,
            )
            await view.wait()
            if not view.confirmed:
                return

            async with self.bot.db.acquire() as conn:
                await conn.execute("""
                    UPDATE users SET
                        points = 0, money = 0, elo = 1000,
                        daily_streak = 0, gold_wins = 0,
                        updated_at = NOW()
                    WHERE guild_id = $1;
                """, guild_id)

            await interaction.followup.send(
                "✅ Ranking del servidor reseteado.", ephemeral=True
            )

        elif target == "jackpot":
            async with self.bot.db.acquire() as conn:
                await conn.execute("""
                    UPDATE gold_events SET jackpot = 0
                    WHERE guild_id = $1 AND winner_id IS NULL;
                """, guild_id)

            await interaction.response.send_message(
                "✅ Jackpot de Pregunta de Oro reseteado a 0.", ephemeral=True
            )

        elif target == "cooldowns":
            async with self.bot.db.acquire() as conn:
                await conn.execute("""
                    UPDATE users SET
                        last_daily = NULL,
                        last_robbery = NULL,
                        robberies_today = 0,
                        updated_at = NOW()
                    WHERE guild_id = $1;
                """, guild_id)

            # Limpiar cooldowns en memoria del QuizCog
            quiz_cog = self.bot.get_cog("QuizCog")
            if quiz_cog:
                quiz_cog._cooldowns.clear()

            await interaction.response.send_message(
                "✅ Todos los cooldowns reseteados.", ephemeral=True
            )

        elif target == "all":
            view = ConfirmView(interaction.user.id)
            await interaction.response.send_message(
                "☢️ **¿ESTÁS SEGURO?** Esto borrará TODOS los datos del servidor:\n"
                "- Usuarios\n- Historial\n- Robos\n- Transacciones\n- Eventos de Oro\n- Roles temporales\n\n"
                "**Esta acción es irreversible.**",
                view=view,
                ephemeral=True,
            )
            await view.wait()
            if not view.confirmed:
                return

            async with self.bot.db.acquire() as conn:
                await conn.execute("DELETE FROM answer_history WHERE guild_id = $1;", guild_id)
                await conn.execute("DELETE FROM transactions WHERE guild_id = $1;", guild_id)
                await conn.execute("DELETE FROM robberies WHERE guild_id = $1;", guild_id)
                await conn.execute("DELETE FROM temp_roles WHERE guild_id = $1;", guild_id)
                await conn.execute("DELETE FROM gold_events WHERE guild_id = $1;", guild_id)
                await conn.execute("DELETE FROM users WHERE guild_id = $1;", guild_id)

            # Limpiar cooldowns en memoria
            quiz_cog = self.bot.get_cog("QuizCog")
            if quiz_cog:
                quiz_cog._cooldowns.clear()

            await interaction.followup.send(
                "☢️ **Todos los datos del servidor han sido eliminados.**",
                ephemeral=True,
            )

    # ════════════��═══════════════════════════════════════════════
    # /sync — Sincronizar comandos slash (owner)
    # ══════════════════════════════════��═════════════════════════
    @app_commands.command(
        name="sync",
        description="⚙️ [Admin] Sincronizar comandos slash del bot",
    )
    @app_commands.default_permissions(administrator=True)
    async def sync_commands(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            synced = await self.bot.tree.sync()
            await interaction.followup.send(
                f"✅ **{len(synced)} comandos** sincronizados correctamente.",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Error sincronizando: {e}",
                ephemeral=True,
            )

    # ════════════════════════════════════════════════════════════
    # /status — Estado del bot
    # ════════════════════════════════════════════════════════════
    @app_commands.command(
        name="status",
        description="📊 Ver el estado actual del bot y estadísticas del servidor",
    )
    @app_commands.default_permissions(administrator=True)
    async def status(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id

        async with self.bot.db.acquire() as conn:
            # Stats generales
            total_users = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE guild_id = $1;", guild_id
            )
            active_users = await conn.fetchval("""
                SELECT COUNT(*) FROM users
                WHERE guild_id = $1 AND updated_at > NOW() - INTERVAL '7 days';
            """, guild_id)
            total_quizzes = await conn.fetchval("""
                SELECT COUNT(*) FROM answer_history
                WHERE guild_id = $1;
            """, guild_id)
            total_quizzes_today = await conn.fetchval("""
                SELECT COUNT(*) FROM answer_history
                WHERE guild_id = $1 AND answered_at > NOW() - INTERVAL '1 day';
            """, guild_id)
            total_robberies = await conn.fetchval(
                "SELECT COUNT(*) FROM robberies WHERE guild_id = $1;", guild_id
            )
            total_gold = await conn.fetchval(
                "SELECT COUNT(*) FROM gold_events WHERE guild_id = $1;", guild_id
            )
            jackpot = await conn.fetchval("""
                SELECT COALESCE(SUM(jackpot), 0) FROM gold_events
                WHERE guild_id = $1 AND winner_id IS NULL AND is_active = FALSE;
            """, guild_id)
            total_questions = await conn.fetchval(
                "SELECT COUNT(*) FROM questions;"
            )
            temp_roles_active = await conn.fetchval("""
                SELECT COUNT(*) FROM temp_roles
                WHERE guild_id = $1 AND removed = FALSE AND expires_at > NOW();
            """, guild_id)

        # Cogs cargados
        cogs_loaded = list(self.bot.cogs.keys())

        # Uptime
        import time
        uptime_seconds = time.time() - self.bot._uptime if hasattr(self.bot, "_uptime") else 0

        embed = discord.Embed(
            title=f"📊 Estado del Bot — {interaction.guild.name}",
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="👥 Usuarios",
            value=(
                f"Total: **{total_users}**\n"
                f"Activos (7d): **{active_users}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="🧠 Partidas",
            value=(
                f"Total: **{total_quizzes}**\n"
                f"Hoy: **{total_quizzes_today}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="⚔️ Robos / Oro",
            value=(
                f"Robos: **{total_robberies}**\n"
                f"Eventos Oro: **{total_gold}**\n"
                f"Jackpot: **{jackpot}** 💎"
            ),
            inline=True,
        )
        embed.add_field(
            name="🗄️ Base de datos",
            value=(
                f"Preguntas cacheadas: **{total_questions}**\n"
                f"Roles temporales activos: **{temp_roles_active}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="🤖 Bot",
            value=(
                f"Servidores: **{len(self.bot.guilds)}**\n"
                f"Cogs: **{len(cogs_loaded)}** ({', '.join(cogs_loaded)})\n"
                f"Latencia: **{self.bot.latency*1000:.0f}ms**"
            ),
            inline=False,
        )

        embed.timestamp = datetime.utcnow()
        embed.set_footer(text="Bot Competitivo de Trivia")

        await interaction.response.send_message(embed=embed, ephemeral=True)


# ── Vista de confirmación ──────────────────────────────────────
class ConfirmView(discord.ui.View):
    """Botones de confirmación para acciones destructivas."""

    def __init__(self, admin_id: int):
        super().__init__(timeout=30)
        self.admin_id = admin_id
        self.confirmed = False

    @discord.ui.button(label="✅ Confirmar", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.admin_id:
            await interaction.response.send_message("❌ Solo el admin puede confirmar.", ephemeral=True)
            return
        self.confirmed = True
        button.disabled = True
        self.children[1].disabled = True
        await interaction.response.edit_message(content="✅ Confirmado. Procesando...", view=self)
        self.stop()

    @discord.ui.button(label="❌ Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.admin_id:
            await interaction.response.send_message("❌ Solo el admin puede cancelar.", ephemeral=True)
            return
        self.confirmed = False
        button.disabled = True
        self.children[0].disabled = True
        await interaction.response.edit_message(content="❌ Cancelado.", view=self)
        self.stop()

    async def on_timeout(self):
        self.confirmed = False
        self.stop()


# ── Setup ──────────────────────────────────────────────────────
async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))