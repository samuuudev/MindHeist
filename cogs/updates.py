"""
Cog Updates — Sistema de novedades del bot.
Lee updates.txt al iniciar y las envía a los canales de logs configurados.
"""

import os
import datetime
import logging

import discord
from discord.ext import commands

log = logging.getLogger("bot.updates")

UPDATE_FILE = "updates.txt"


class UpdatesCog(commands.Cog):
    """Envía actualizaciones pendientes a los canales de logs al iniciar el bot."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.loop.create_task(self._send_pending_updates())

    # ── Al iniciar: leer updates.txt y enviar a todos los servidores ──

    async def _send_pending_updates(self):
        await self.bot.wait_until_ready()

        if not os.path.exists(UPDATE_FILE):
            return

        with open(UPDATE_FILE, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]

        if not lines:
            return

        content = "\n".join(f"• {line}" for line in lines)

        embed = discord.Embed(
            title="📢 Novedades del bot",
            description=content,
            color=discord.Color.blue(),
            timestamp=datetime.datetime.utcnow(),
        )
        embed.set_footer(text="Actualización automática al iniciar")

        sent_count = 0
        for guild in self.bot.guilds:
            channel = await self._get_log_channel(guild.id)
            if not channel:
                log.info(f"  Sin canal de logs en {guild.name}, saltando update.")
                continue
            try:
                await channel.send(embed=embed)
                sent_count += 1
                log.info(f"  Update enviada a {guild.name} (#{channel.name})")
            except discord.Forbidden:
                log.warning(f"  Sin permisos para enviar en #{channel.name} ({guild.name})")
            except Exception as e:
                log.warning(f"  Error enviando update a {guild.name}: {e}")

        # Limpiar el archivo solo si se envió al menos a un servidor
        if sent_count > 0:
            open(UPDATE_FILE, "w").close()
            log.info(f"Updates enviadas a {sent_count} servidor(es). Archivo limpiado.")
        else:
            log.warning("No se envió a ningún servidor. El archivo NO se limpia.")


    # ── Helper: obtener canal de logs de un servidor ──

    async def _get_log_channel(self, guild_id: int) -> discord.TextChannel | None:
        try:
            async with self.bot.db.acquire() as conn:
                channel_id = await conn.fetchval(
                    "SELECT log_channel_id FROM guild_config WHERE guild_id = $1",
                    guild_id,
                )
        except Exception:
            return None

        if not channel_id:
            return None

        guild = self.bot.get_guild(guild_id)
        if not guild:
            return None

        return guild.get_channel(channel_id)


async def setup(bot: commands.Bot):
    await bot.add_cog(UpdatesCog(bot))