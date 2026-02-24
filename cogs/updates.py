import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import datetime

class UpdatesCog(commands.Cog):
    """Cog para notificaciones de actualizaciones desde VPS."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.update_channel_id = None  # Canal donde se publicarán las actualizaciones

    @app_commands.command(
        name="set_update_channel",
        description="Define el canal donde se enviarán las actualizaciones"
    )
    async def set_update_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        self.update_channel_id = channel.id
        await interaction.response.send_message(
            f"Canal de actualizaciones configurado: {channel.mention}", ephemeral=True
        )

    @app_commands.command(
        name="update",
        description="Envía una actualización desde el VPS"
    )
    @app_commands.describe(message="Mensaje de actualización")
    async def update(self, interaction: discord.Interaction, message: str):
        if not self.update_channel_id:
            await interaction.response.send_message(
                "No se ha configurado un canal de actualizaciones.", ephemeral=True
            )
            return

        channel = self.bot.get_channel(self.update_channel_id)
        if not channel:
            await interaction.response.send_message(
                "No se encontró el canal de actualizaciones.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="📢 Nueva actualización",
            description=message,
            color=discord.Color.blue(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_footer(text=f"Enviado por {interaction.user.display_name}")

        await channel.send(embed=embed)
        await interaction.response.send_message("Actualización enviada correctamente.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(UpdatesCog(bot))