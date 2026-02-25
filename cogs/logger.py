"""
Cog Logger — Sistema centralizado de logs en canal de Discord.
Registra acciones de quiz, daily, oro, robos y administración.
"""

from datetime import datetime
from enum import Enum

import discord
from discord.ext import commands
import logging

log = logging.getLogger("bot.logger")


class LogType(Enum):
    """Tipos de eventos registrables."""
    QUIZ = "quiz"
    DAILY = "daily"
    GOLD = "gold"
    ROBBERY = "robbery"
    ADMIN = "admin"
    SYSTEM = "system"
    ECONOMY = "economy"


LOG_CONFIG = {
    LogType.QUIZ:    {"color": 0x3498DB, "prefix": "QUIZ"},
    LogType.DAILY:   {"color": 0xF1C40F, "prefix": "DAILY"},
    LogType.GOLD:    {"color": 0xFFD700, "prefix": "ORO"},
    LogType.ROBBERY: {"color": 0xE74C3C, "prefix": "ROBO"},
    LogType.ADMIN:   {"color": 0x9B59B6, "prefix": "ADMIN"},
    LogType.SYSTEM:  {"color": 0x95A5A6, "prefix": "SISTEMA"},
    LogType.ECONOMY: {"color": 0x2ECC71, "prefix": "ECONOMIA"},
}


class LoggerCog(commands.Cog):
    """Envía registros de actividad al canal de logs configurado."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _get_log_channel(self, guild_id: int) -> discord.TextChannel | None:
        async with self.bot.db.acquire() as conn:
            channel_id = await conn.fetchval("SELECT log_channel_id FROM guild_config WHERE guild_id = $1", guild_id)

        if not channel_id:
            return None

        guild = self.bot.get_guild(guild_id)
        if not guild:
            return None

        channel = guild.get_channel(channel_id)
        if not channel:
            log.warning(f"Canal de logs {channel_id} no encontrado en {guild.name}")

        return channel

    async def send_log(self, guild_id: int, log_type: LogType, title: str, description: str, fields: list[dict] | None = None, user: discord.User | discord.Member | None = None, target: discord.User | discord.Member | None = None):
        channel = await self._get_log_channel(guild_id)
        if not channel:
            return

        config = LOG_CONFIG.get(log_type, LOG_CONFIG[LogType.SYSTEM])

        embed = discord.Embed(title=f"[{config['prefix']}] {title}", description=description, color=config["color"], timestamp=datetime.utcnow())

        if user:
            embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)

        if target:
            embed.add_field(name="Objetivo", value=f"{target.mention} ({target.id})", inline=True)

        if fields:
            for field in fields:
                embed.add_field(name=field["name"], value=field["value"], inline=field.get("inline", True))

        if user:
            embed.set_footer(text=f"User ID: {user.id}")

        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            log.warning(f"Sin permisos para enviar logs en #{channel.name}")
        except Exception as e:
            log.error(f"Error enviando log: {e}")

    # Métodos por tipo de evento (resúmenes)
    async def log_quiz(self, guild_id: int, user: discord.Member, correct: bool, points: int, difficulty: str, category: str, response_time: float):
        result = "Correcto" if correct else "Incorrecto"
        await self.send_log(guild_id=guild_id, log_type=LogType.QUIZ, title=f"Quiz completado — {result}", description=f"{user.mention} respondió un quiz.", fields=[
            {"name": "Resultado", "value": result},
            {"name": "Puntos", "value": f"+{points}" if correct else "0"},
            {"name": "Dificultad", "value": difficulty},
            {"name": "Categoría", "value": category},
            {"name": "Tiempo", "value": f"{response_time:.1f}s"},
        ], user=user)

    async def log_daily(self, guild_id: int, user: discord.Member, correct: bool, points: int, streak: int):
        title = (f"Daily completado — Racha: {streak} días" if correct else "Daily fallado — Racha perdida")
        await self.send_log(guild_id=guild_id, log_type=LogType.DAILY, title=title, description=f"{user.mention} completó su pregunta diaria.", fields=[
            {"name": "Resultado", "value": "Correcto" if correct else "Incorrecto"},
            {"name": "Puntos", "value": f"+{points}" if correct else "0"},
            {"name": "Racha", "value": f"{streak} días"},
        ], user=user)

    async def log_gold(self, guild_id: int, winner: discord.Member | None, reward: int, participants: int, jackpot_accumulated: int):
        if winner:
            title = "Pregunta de Oro ganada"
            desc = f"{winner.mention} acertó la Pregunta de Oro."
        else:
            title = "Pregunta de Oro sin ganador"
            desc = "Nadie acertó. El jackpot se acumula."

        fields = [
            {"name": "Recompensa", "value": f"{reward} pts"},
            {"name": "Participantes", "value": str(participants)},
        ]
        if not winner:
            fields.append({"name": "Jackpot acumulado", "value": f"{jackpot_accumulated} pts"})

        await self.send_log(guild_id=guild_id, log_type=LogType.GOLD, title=title, description=desc, fields=fields, user=winner)

    async def log_robbery(self, guild_id: int, attacker: discord.Member, victim: discord.Member, success: bool, amount: int):
        if success:
            title = "Robo exitoso"
            desc = f"{attacker.mention} robó **{amount}** monedas a {victim.mention}."
        else:
            title = "Robo fallido"
            desc = f"{attacker.mention} intentó robar a {victim.mention} y perdió **{amount}** monedas."

        await self.send_log(guild_id=guild_id, log_type=LogType.ROBBERY, title=title, description=desc, fields=[
            {"name": "Resultado", "value": "Exitoso" if success else "Fallido"},
            {"name": "Cantidad", "value": f"{amount} monedas"},
        ], user=attacker, target=victim)

    async def log_shield(self, guild_id: int, user: discord.Member, duration: str, cost: int):
        await self.send_log(guild_id=guild_id, log_type=LogType.ECONOMY, title="Escudo comprado", description=f"{user.mention} compró un escudo de **{duration}**.", fields=[
            {"name": "Duración", "value": duration},
            {"name": "Coste", "value": f"{cost} monedas"},
        ], user=user)

    async def log_admin_give(self, guild_id: int, admin: discord.Member, target: discord.Member, points: int, money: int):
        await self.send_log(guild_id=guild_id, log_type=LogType.ADMIN, title="Modificación manual de economía", description=f"{admin.mention} modificó los recursos de {target.mention}.", fields=[
            {"name": "Puntos", "value": f"{'+' if points >= 0 else ''}{points}"},
            {"name": "Dinero", "value": f"{'+' if money >= 0 else ''}{money}"},
        ], user=admin, target=target)

    async def log_admin_reset(self, guild_id: int, admin: discord.Member, target_type: str, member: discord.Member | None = None):
        desc = f"{admin.mention} ejecutó un reset: **{target_type}**."
        if member:
            desc += f"\nUsuario afectado: {member.mention}"
        await self.send_log(guild_id=guild_id, log_type=LogType.ADMIN, title=f"Reset — {target_type}", description=desc, user=admin, target=member)

    async def log_system(self, guild_id: int, title: str, description: str):
        await self.send_log(guild_id=guild_id, log_type=LogType.SYSTEM, title=title, description=description)

    async def log_role_change(self, guild_id: int, member: discord.Member, role: discord.Role, action: str, reason: str):
        await self.send_log(guild_id=guild_id, log_type=LogType.SYSTEM, title=f"Rol {action}", description=(f"Rol **{role.name}** {action} a {member.mention}.\nRazón: {reason}"), user=member)


async def setup(bot: commands.Bot):
    await bot.add_cog(LoggerCog(bot))