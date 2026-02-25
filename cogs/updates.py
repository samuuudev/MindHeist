import discord
from discord.ext import commands
import datetime
import os
import asyncio

class UpdatesCog(commands.Cog):
    """Cog que envía actualizaciones desde un archivo al iniciar el bot."""

    def __init__(self, bot: commands.Bot, update_file="updates.txt"):
        self.bot = bot
        self.update_file = update_file
        self.update_channel_id = None  # Cambiar luego con set_update_channel
        # Ejecutar check al iniciar
        self.bot.loop.create_task(self.check_updates_on_startup())

    async def check_updates_on_startup(self):
        await self.bot.wait_until_ready()  # espera que el bot esté listo

        if not self.update_channel_id or not os.path.exists(self.update_file):
            return

        # Leer mensajes
        async with asyncio.Lock():
            with open(self.update_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

            if not lines:
                return

            channel = self.bot.get_channel(self.update_channel_id)
            if not channel:
                print("No se encontró el canal de actualizaciones.")
                return

            for message in lines:
                message = message.strip()
                if message:
                    embed = discord.Embed(
                        title="📢 Nueva actualización",
                        description=message,
                        color=discord.Color.blue(),
                        timestamp=datetime.datetime.utcnow()
                    )
                    embed.set_footer(text="Enviado desde VPS al iniciar el bot")
                    await channel.send(embed=embed)
                    print(f"Actualización enviada: {message}")

            # Borrar contenido del archivo
            open(self.update_file, "w").close()
            print("Archivo de actualizaciones limpiado.")

    @commands.command(name="set_update_channel")
    async def set_update_channel_cmd(self, ctx, channel: discord.TextChannel):
        """Comando para definir el canal de actualizaciones"""
        self.update_channel_id = channel.id
        await ctx.send(f"Canal de actualizaciones configurado: {channel.mention}")

async def setup(bot: commands.Bot):
    await bot.add_cog(UpdatesCog(bot))