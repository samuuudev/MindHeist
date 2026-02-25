"""
Bot Competitivo de Trivia — Archivo principal
Gestiona la conexión a Discord, base de datos y carga de módulos.
"""

import os
import sys
import time
import asyncio
import logging
from pathlib import Path

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import asyncpg

# ── Configuración de entorno ───────────────────────────────────
load_dotenv(override=False)

TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not TOKEN:
    print("[ERROR] DISCORD_TOKEN no está configurado.")
    sys.exit(1)

if not DATABASE_URL:
    print("[ERROR] DATABASE_URL no está configurado.")
    sys.exit(1)

# ── Logging ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("bot")

# Silenciar logs excesivos de discord.py
logging.getLogger("discord.http").setLevel(logging.WARNING)
logging.getLogger("discord.gateway").setLevel(logging.WARNING)

# ── Lista de módulos (cogs) ────────────────────────────────────
COGS = [
    "cogs.logger",
    "cogs.quiz",
    "cogs.daily",
    "cogs.ranking",
    "cogs.gold",
    "cogs.robbery",
    "cogs.admin",
    "cogs.updates",
]


# ── Bot principal ──────────────────────────────────────────────
class TriviaBot(commands.Bot):
    """Bot principal con conexión a PostgreSQL y carga de cogs."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Iniciando...",
            ),
        )
        self.db: asyncpg.Pool | None = None
        self._uptime: float = time.time()

    async def setup_hook(self):
        """Se ejecuta antes de conectar a Discord. Inicializa DB y cogs."""

        print("DATABASE_URL usada:", DATABASE_URL)
        # Conexión a PostgreSQL
        log.info("Conectando a PostgreSQL...")
        try:
            self.db = await asyncpg.create_pool(
                DATABASE_URL,
                min_size=2,
                max_size=10,
                command_timeout=30,
            )
            log.info("Pool de PostgreSQL creado correctamente.")
        except Exception as e:
            log.critical(f"No se pudo conectar a PostgreSQL: {e}")
            sys.exit(1)

        # Inicializar schema
        await self._init_database()

        # Cargar cogs
        for cog in COGS:
            try:
                await self.load_extension(cog)
                log.info(f"  Cog cargado: {cog}")
            except Exception as e:
                log.error(f"  Error cargando {cog}: {e}")

        print("Comandos registrados en tree:")
        for cmd in self.tree.get_commands():
            print("-", cmd.name)

    async def _init_database(self):
        """Ejecuta schema.sql para crear tablas si no existen."""
        schema_path = Path(__file__).parent / "schema.sql"

        if not schema_path.exists():
            log.warning("schema.sql no encontrado. Saltando inicialización de DB.")
            return

        log.info("Inicializando base de datos con schema.sql...")
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                schema = f.read()
            async with self.db.acquire() as conn:
                await conn.execute(schema)
            log.info("Base de datos inicializada correctamente.")
        except Exception as e:
            log.error(f"Error inicializando base de datos: {e}")

    async def on_ready(self):
        """Se ejecuta cuando el bot se conecta a Discord."""
        log.info(f"Conectado como {self.user} (ID: {self.user.id})")
        log.info(f"Servidores: {len(self.guilds)}")

        # Señal para Pterodactyl (marca el servidor como Online)
        print(f"{self.user.name} está online!")

        # Sincronizar comandos slash
        try:
            synced = await self.tree.sync()
            log.info(f"Comandos sincronizados: {len(synced)}")
        except Exception as e:
            log.error(f"Error sincronizando comandos: {e}")

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.competing,
                name="/quiz · /daily · /rank",
            )
        )
    async def on_guild_join(self, guild: discord.Guild):
        """Se ejecuta cuando el bot se une a un nuevo servidor."""
        log.info(f"Nuevo servidor unido: {guild.name} (ID: {guild.id})")
        print(f"[NUEVO SERVIDOR] {guild.name}")

    async def close(self):
        """Limpieza al cerrar el bot."""
        log.info("Cerrando bot...")
        if self.db:
            await self.db.close()
            log.info("Pool de PostgreSQL cerrado.")
        await super().close()


# ── Punto de entrada ───────────────────────────────────────────
def main():
    bot = TriviaBot()
    bot.run(TOKEN, log_handler=None)


if __name__ == "__main__":
    print("Iniciando bot...")
    main()