"""
Cog de Ranking — /rank, /top, /stats
Sistema de clasificación, leaderboard y estadísticas personales.
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import logging

log = logging.getLogger("bot.ranking")


# ── Constantes visuales ───────────────────────────────────────
PODIUM_EMOJIS = ["👑", "🥈", "🥉"]
RANK_COLORS = [0xFFD700, 0xC0C0C0, 0xCD7F32]  # Oro, Plata, Bronce
BAR_FULL = "█"
BAR_EMPTY = "░"


# ── Cog principal ──────────────────────────────────────────────
class RankingCog(commands.Cog):
    """Sistema de ranking, leaderboard y estadísticas."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.update_top_roles.start()

    def cog_unload(self):
        self.update_top_roles.cancel()

    # ════════════════════════════════════════════════════════════
    # /rank — Tu posición personal en el ranking
    # ════════════════════════════════════════════════════════════
    @app_commands.command(
        name="rank",
        description="📊 Mira tu posición en el ranking del servidor",
    )
    @app_commands.describe(member="Usuario del que quieres ver el ranking")
    async def rank(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ):
        target = member or interaction.user
        guild_id = interaction.guild_id

        async with self.bot.db.acquire() as conn:
            # Obtener datos del usuario
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id = $1 AND guild_id = $2",
                target.id, guild_id,
            )

            if not user:
                await interaction.response.send_message(
                    f"❌ {'Ese usuario' if member else 'Tú'} aún no ha jugado ninguna partida.",
                    ephemeral=True,
                )
                return

            # Calcular posición en ranking
            position = await conn.fetchval("""
                SELECT COUNT(*) + 1 FROM users
                WHERE guild_id = $1 AND points > $2;
            """, guild_id, user["points"])

            total_users = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE guild_id = $1;",
                guild_id,
            )

            # Obtener stats recientes (últimos 7 días)
            recent = await conn.fetchrow("""
                SELECT
                    COUNT(*) AS total_7d,
                    SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) AS correct_7d,
                    SUM(points_earned) AS points_7d
                FROM answer_history
                WHERE user_id = $1 AND guild_id = $2
                  AND answered_at > NOW() - INTERVAL '7 days';
            """, target.id, guild_id)

        # ── Construir embed ────────────────────────────────────
        # Color según posición
        if position <= 3:
            color = RANK_COLORS[position - 1]
        else:
            color = discord.Color.blurple()

        # Barra de progreso (precisión de respuestas)
        accuracy = 0
        if user["total_quizzes"] > 0:
            accuracy = (user["correct_answers"] / user["total_quizzes"]) * 100
        bar = self._progress_bar(accuracy)

        # Emoji de posición
        if position <= 3:
            pos_display = f"{PODIUM_EMOJIS[position - 1]} #{position}"
        else:
            pos_display = f"#{position}"

        embed = discord.Embed(
            title=f"📊 Ranking de {target.display_name}",
            color=color,
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        embed.add_field(
            name="🏆 Posición",
            value=f"**{pos_display}** de {total_users}",
            inline=True,
        )
        embed.add_field(
            name="⭐ Puntos",
            value=f"**{user['points']:,}**",
            inline=True,
        )
        embed.add_field(
            name="💰 Dinero",
            value=f"**{user['money']:,}**",
            inline=True,
        )
        embed.add_field(
            name="🔥 Racha daily",
            value=f"**{user['daily_streak']}** días",
            inline=True,
        )
        embed.add_field(
            name="🥇 Oros ganados",
            value=f"**{user['gold_wins']}**",
            inline=True,
        )
        embed.add_field(
            name="📈 ELO",
            value=f"**{user['elo']}**",
            inline=True,
        )

        # Precisión
        embed.add_field(
            name=f"🎯 Precisión ({user['correct_answers']}/{user['total_quizzes']})",
            value=f"{bar} **{accuracy:.1f}%**",
            inline=False,
        )

        # Stats últimos 7 días
        if recent and recent["total_7d"] and recent["total_7d"] > 0:
            acc_7d = (recent["correct_7d"] / recent["total_7d"]) * 100
            embed.add_field(
                name="📅 Últimos 7 días",
                value=(
                    f"Partidas: **{recent['total_7d']}** · "
                    f"Aciertos: **{recent['correct_7d']}** · "
                    f"Precisión: **{acc_7d:.0f}%** · "
                    f"Puntos: **+{recent['points_7d'] or 0}**"
                ),
                inline=False,
            )

        embed.set_footer(text=f"Servidor: {interaction.guild.name}")
        embed.timestamp = datetime.utcnow()

        await interaction.response.send_message(embed=embed)

    # ═══════════════════════════════════════��════════════════════
    # /top — Leaderboard del servidor
    # ════════════════════════════════════════════════════════════
    @app_commands.command(
        name="top",
        description="🏅 Mira el top de jugadores del servidor",
    )
    @app_commands.describe(
        category="Tipo de ranking a mostrar",
        page="Página del ranking (10 por página)",
    )
    @app_commands.choices(
        category=[
            app_commands.Choice(name="⭐ Puntos", value="points"),
            app_commands.Choice(name="💰 Dinero", value="money"),
            app_commands.Choice(name="📈 ELO", value="elo"),
            app_commands.Choice(name="🔥 Racha Daily", value="streak"),
            app_commands.Choice(name="🥇 Victorias de Oro", value="gold"),
            app_commands.Choice(name="🎯 Precisión", value="accuracy"),
        ],
    )
    async def top(
        self,
        interaction: discord.Interaction,
        category: str = "points",
        page: int = 1,
    ):
        guild_id = interaction.guild_id
        page = max(1, page)
        per_page = 10
        offset = (page - 1) * per_page

        # ── Query según categoría ────────────────────────────���─
        queries = {
            "points": {
                "order": "points DESC",
                "title": "⭐ Top por Puntos",
                "field": "points",
                "format": lambda v: f"**{v:,}** pts",
            },
            "money": {
                "order": "money DESC",
                "title": "💰 Top por Dinero",
                "field": "money",
                "format": lambda v: f"**{v:,}** 💰",
            },
            "elo": {
                "order": "elo DESC",
                "title": "📈 Top por ELO",
                "field": "elo",
                "format": lambda v: f"**{v}** ELO",
            },
            "streak": {
                "order": "daily_streak DESC",
                "title": "🔥 Top por Racha Daily",
                "field": "daily_streak",
                "format": lambda v: f"**{v}** días 🔥",
            },
            "gold": {
                "order": "gold_wins DESC",
                "title": "🥇 Top por Victorias de Oro",
                "field": "gold_wins",
                "format": lambda v: f"**{v}** victorias",
            },
            "accuracy": {
                "order": "CASE WHEN total_quizzes > 0 THEN correct_answers::float / total_quizzes ELSE 0 END DESC",
                "title": "🎯 Top por Precisión",
                "field": None,  # Campo calculado
                "format": None,
            },
        }

        q = queries[category]

        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT user_id, username, points, money, elo,
                       daily_streak, gold_wins, total_quizzes, correct_answers
                FROM users
                WHERE guild_id = $1 AND total_quizzes > 0
                ORDER BY {q['order']}
                LIMIT $2 OFFSET $3;
            """, guild_id, per_page, offset)

            total_count = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE guild_id = $1 AND total_quizzes > 0;",
                guild_id,
            )

        if not rows:
            await interaction.response.send_message(
                "❌ No hay jugadores en el ranking aún. ¡Usa `/quiz` o `/daily` para empezar!",
                ephemeral=True,
            )
            return

        # ── Construir leaderboard ──────────────────────────────
        total_pages = max(1, (total_count + per_page - 1) // per_page)
        page = min(page, total_pages)

        embed = discord.Embed(
            title=q["title"],
            color=discord.Color.gold(),
        )

        leaderboard = ""
        for i, row in enumerate(rows):
            position = offset + i + 1

            # Emoji de posición
            if position == 1:
                pos_str = "👑"
            elif position == 2:
                pos_str = "🥈"
            elif position == 3:
                pos_str = "🥉"
            else:
                pos_str = f"`{position}.`"

            # Nombre (resaltar si es el que ejecuta el comando)
            name = row["username"]
            if row["user_id"] == interaction.user.id:
                name = f"**► {name} ◄**"

            # Valor según categoría
            if category == "accuracy":
                if row["total_quizzes"] > 0:
                    acc = (row["correct_answers"] / row["total_quizzes"]) * 100
                    value = f"**{acc:.1f}%** ({row['correct_answers']}/{row['total_quizzes']})"
                else:
                    value = "Sin datos"
            else:
                value = q["format"](row[q["field"]])

            leaderboard += f"{pos_str} {name} — {value}\n"

        embed.description = leaderboard

        # Footer con paginación
        embed.set_footer(
            text=f"Página {page}/{total_pages} · {total_count} jugadores · {interaction.guild.name}"
        )
        embed.timestamp = datetime.utcnow()

        # ── Botones de paginación ──────────────────────────────
        view = TopPaginationView(
            cog=self,
            interaction=interaction,
            category=category,
            current_page=page,
            total_pages=total_pages,
        )

        await interaction.response.send_message(embed=embed, view=view)

    # ════════════════════════════════════════════════════════════
    # /stats — Estadísticas detalladas
    # ════════════════════════════════════════════════════════════
    @app_commands.command(
        name="stats",
        description="📈 Estadísticas detalladas de un jugador",
    )
    @app_commands.describe(member="Usuario del que quieres ver las estadísticas")
    async def stats(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ):
        target = member or interaction.user
        guild_id = interaction.guild_id

        async with self.bot.db.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id = $1 AND guild_id = $2",
                target.id, guild_id,
            )

            if not user:
                await interaction.response.send_message(
                    f"❌ {'Ese usuario' if member else 'Tú'} aún no ha jugado.",
                    ephemeral=True,
                )
                return

            # Stats por contexto
            context_stats = await conn.fetch("""
                SELECT
                    context,
                    COUNT(*) AS total,
                    SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) AS correct,
                    SUM(points_earned) AS points,
                    AVG(response_time) FILTER (WHERE response_time > 0) AS avg_time
                FROM answer_history
                WHERE user_id = $1 AND guild_id = $2
                GROUP BY context
                ORDER BY total DESC;
            """, target.id, guild_id)

            # Robos (como atacante)
            rob_stats = await conn.fetchrow("""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN success THEN 1 ELSE 0 END) AS wins,
                    SUM(money_stolen) AS total_money
                FROM robberies
                WHERE attacker_id = $1 AND guild_id = $2;
            """, target.id, guild_id)

            # Robos (como víctima)
            robbed_stats = await conn.fetchrow("""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN success THEN money_stolen ELSE 0 END) AS total_lost
                FROM robberies
                WHERE victim_id = $1 AND guild_id = $2;
            """, target.id, guild_id)

            # Mejor racha histórica (aproximación desde transacciones)
            best_streak = await conn.fetchval("""
                SELECT MAX(daily_streak) FROM users
                WHERE user_id = $1 AND guild_id = $2;
            """, target.id, guild_id) or user["daily_streak"]

        # ── Construir embed ────────────────────────────────────
        accuracy = 0
        if user["total_quizzes"] > 0:
            accuracy = (user["correct_answers"] / user["total_quizzes"]) * 100

        embed = discord.Embed(
            title=f"📈 Estadísticas de {target.display_name}",
            color=discord.Color.purple(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        # General
        embed.add_field(
            name="📋 General",
            value=(
                f"⭐ Puntos: **{user['points']:,}**\n"
                f"💰 Dinero: **{user['money']:,}**\n"
                f"📈 ELO: **{user['elo']}**\n"
                f"🔥 Racha: **{user['daily_streak']}** días\n"
                f"🥇 Oros: **{user['gold_wins']}**"
            ),
            inline=True,
        )

        # Precisión
        embed.add_field(
            name="🎯 Precisión",
            value=(
                f"Partidas: **{user['total_quizzes']}**\n"
                f"Aciertos: **{user['correct_answers']}**\n"
                f"Ratio: **{accuracy:.1f}%**\n"
                f"{self._progress_bar(accuracy)}"
            ),
            inline=True,
        )

        # Desglose por contexto
        if context_stats:
            context_display = {
                "quiz": "🧠 Quiz",
                "daily": "📅 Daily",
                "gold": "✨ Oro",
                "robbery": "🗡️ Robo",
            }
            ctx_text = ""
            for row in context_stats:
                name = context_display.get(row["context"], row["context"])
                ctx_acc = 0
                if row["total"] > 0:
                    ctx_acc = (row["correct"] / row["total"]) * 100
                avg = row["avg_time"] or 0
                ctx_text += (
                    f"{name}: **{row['correct']}/{row['total']}** "
                    f"({ctx_acc:.0f}%) · ⏱️{avg:.1f}s\n"
                )
            embed.add_field(
                name="📊 Desglose por tipo",
                value=ctx_text,
                inline=False,
            )

        # Robos
        if rob_stats and rob_stats["total"] and rob_stats["total"] > 0:
            rob_ratio = (rob_stats["wins"] / rob_stats["total"]) * 100
            robbed_total = robbed_stats["total"] if robbed_stats and robbed_stats["total"] else 0
            robbed_lost = robbed_stats["total_lost"] if robbed_stats and robbed_stats["total_lost"] else 0

            embed.add_field(
                name="🗡️ Robos",
                value=(
                    f"**Atacante:**\n"
                    f"Intentos: **{rob_stats['total']}** · "
                    f"Éxitos: **{rob_stats['wins']}** ({rob_ratio:.0f}%)\n"
                    f"Dinero robado: **{rob_stats['total_money'] or 0:,}** 💰\n\n"
                    f"**Víctima:**\n"
                    f"Veces robado: **{robbed_total}** · "
                    f"Dinero perdido: **{robbed_lost:,}** 💰"
                ),
                inline=False,
            )

        embed.set_footer(
            text=f"Jugando desde {user['created_at'].strftime('%d/%m/%Y')}"
        )
        embed.timestamp = datetime.utcnow()

        await interaction.response.send_message(embed=embed)

    # ════════════════════════════════════════════════════════════
    # Tarea: Actualizar roles del top 3
    # ════════════════════════════════════════════════════════════
    @tasks.loop(minutes=5)
    async def update_top_roles(self):
        """Asigna/remueve roles automáticos del top 3."""
        if not self.bot.db:
            return

        async with self.bot.db.acquire() as conn:
            configs = await conn.fetch(
                "SELECT guild_id, top_role_ids FROM guild_config WHERE top_role_ids != '[]'::jsonb;"
            )

        for config in configs:
            guild = self.bot.get_guild(config["guild_id"])
            if not guild:
                continue

            import json
            role_ids = json.loads(config["top_role_ids"]) if isinstance(config["top_role_ids"], str) else config["top_role_ids"]

            if not role_ids or len(role_ids) == 0:
                continue

            async with self.bot.db.acquire() as conn:
                # Top 3 por puntos
                top_users = await conn.fetch("""
                    SELECT user_id FROM users
                    WHERE guild_id = $1
                    ORDER BY points DESC, gold_wins DESC
                    LIMIT 3;
                """, guild.id)

            top_user_ids = [row["user_id"] for row in top_users]

            for i, role_id in enumerate(role_ids[:3]):
                role = guild.get_role(role_id)
                if not role:
                    continue

                try:
                    # Remover rol de todos los que lo tengan
                    for m in role.members:
                        if i < len(top_user_ids) and m.id != top_user_ids[i]:
                            await m.remove_roles(role, reason="Ya no está en el top")
                            log.info(f"Rol {role.name} removido de {m.display_name}")
                        elif i >= len(top_user_ids):
                            await m.remove_roles(role, reason="No hay suficientes jugadores en el top")

                    # Asignar al que corresponde
                    if i < len(top_user_ids):
                        member = guild.get_member(top_user_ids[i])
                        if member and role not in member.roles:
                            await member.add_roles(role, reason=f"Top {i + 1} del servidor")
                            log.info(f"Rol {role.name} asignado a {member.display_name} (Top {i + 1})")

                except discord.Forbidden:
                    log.warning(f"Sin permisos para gestionar rol {role.name} en {guild.name}")
                except Exception as e:
                    log.error(f"Error actualizando roles top en {guild.name}: {e}")

    @update_top_roles.before_loop
    async def before_update_top_roles(self):
        await self.bot.wait_until_ready()

    # ── Helpers ────────────────────────────────────────────────
    @staticmethod
    def _progress_bar(percentage: float, length: int = 10) -> str:
        filled = int(length * percentage / 100)
        empty = length - filled
        return f"`{BAR_FULL * filled}{BAR_EMPTY * empty}`"


# ── Vista de paginación para /top ──────────────────────────────
class TopPaginationView(discord.ui.View):
    """Botones de paginación para el leaderboard."""

    def __init__(
        self,
        cog: RankingCog,
        interaction: discord.Interaction,
        category: str,
        current_page: int,
        total_pages: int,
    ):
        super().__init__(timeout=120)
        self.cog = cog
        self.original_interaction = interaction
        self.category = category
        self.current_page = current_page
        self.total_pages = total_pages
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.current_page <= 1
        self.next_btn.disabled = self.current_page >= self.total_pages
        self.page_indicator.label = f"{self.current_page}/{self.total_pages}"

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_interaction.user.id:
            await interaction.response.send_message("❌ Solo quien usó /top puede navegar.", ephemeral=True)
            return
        self.current_page -= 1
        await self._update_leaderboard(interaction)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.primary, disabled=True)
    async def page_indicator(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.original_interaction.user.id:
            await interaction.response.send_message("❌ Solo quien usó /top puede navegar.", ephemeral=True)
            return
        self.current_page += 1
        await self._update_leaderboard(interaction)

    async def _update_leaderboard(self, interaction: discord.Interaction):
        """Regenera el embed con la nueva página."""
        guild_id = self.original_interaction.guild_id
        per_page = 10
        offset = (self.current_page - 1) * per_page

        queries = {
            "points": ("points DESC", "⭐ Top por Puntos", "points", lambda v: f"**{v:,}** pts"),
            "money": ("money DESC", "💰 Top por Dinero", "money", lambda v: f"**{v:,}** 💰"),
            "elo": ("elo DESC", "📈 Top por ELO", "elo", lambda v: f"**{v}** ELO"),
            "streak": ("daily_streak DESC", "🔥 Top por Racha Daily", "daily_streak", lambda v: f"**{v}** días 🔥"),
            "gold": ("gold_wins DESC", "🥇 Top por Victorias de Oro", "gold_wins", lambda v: f"**{v}** victorias"),
            "accuracy": (
                "CASE WHEN total_quizzes > 0 THEN correct_answers::float / total_quizzes ELSE 0 END DESC",
                "🎯 Top por Precisión", None, None,
            ),
        }

        order, title, field, fmt = queries[self.category]

        async with self.cog.bot.db.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT user_id, username, points, money, elo,
                       daily_streak, gold_wins, total_quizzes, correct_answers
                FROM users
                WHERE guild_id = $1 AND total_quizzes > 0
                ORDER BY {order}
                LIMIT $2 OFFSET $3;
            """, guild_id, per_page, offset)

            total_count = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE guild_id = $1 AND total_quizzes > 0;",
                guild_id,
            )

        embed = discord.Embed(title=title, color=discord.Color.gold())

        leaderboard = ""
        for i, row in enumerate(rows):
            position = offset + i + 1
            if position == 1:
                pos_str = "👑"
            elif position == 2:
                pos_str = "🥈"
            elif position == 3:
                pos_str = "🥉"
            else:
                pos_str = f"`{position}.`"

            name = row["username"]
            if row["user_id"] == interaction.user.id:
                name = f"**► {name} ◄**"

            if self.category == "accuracy":
                if row["total_quizzes"] > 0:
                    acc = (row["correct_answers"] / row["total_quizzes"]) * 100
                    value = f"**{acc:.1f}%** ({row['correct_answers']}/{row['total_quizzes']})"
                else:
                    value = "Sin datos"
            else:
                value = fmt(row[field])

            leaderboard += f"{pos_str} {name} — {value}\n"

        embed.description = leaderboard
        self.total_pages = max(1, (total_count + per_page - 1) // per_page)
        embed.set_footer(
            text=f"Página {self.current_page}/{self.total_pages} · {total_count} jugadores"
        )
        embed.timestamp = datetime.utcnow()

        self._update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.original_interaction.edit_original_response(view=self)
        except Exception:
            pass


# ── Setup ──────────────────────────────────────────────────────
async def setup(bot: commands.Bot):
    await bot.add_cog(RankingCog(bot))