"""
Discord Competitive Bot — Main Entry Point
Desarrollado con discord.py + PostgreSQL
"""

import os
import asyncio
import logging
from datetime import datetime

import discord
from discord.ext import commands, tasks
import asyncpg
from dotenv import load_dotenv

# ── Configuración ──────────────────────────────────────────────
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")  # postgresql://user:pass@host:port/dbname
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# ── Logging ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("bot")

# ── Intents ────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True


# ── Clase principal del Bot ────────────────────────────────────
class CompetitiveBot(commands.Bot):
    """Bot principal con pool de conexión a PostgreSQL."""

    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
            description="Bot competitivo de trivia y economía",
        )
        self.db: asyncpg.Pool | None = None

    # ── Conexión a la base de datos ────────────────────────────
    async def setup_hook(self):
        """Se ejecuta antes de que el bot se conecte a Discord."""
        log.info("Conectando a PostgreSQL...")
        self.db = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        log.info("✅ Pool de PostgreSQL creado correctamente.")

        # Inicializar schema si es necesario
        await self._init_database()

        # Cargar cogs (módulos del bot)
        await self._load_cogs()

        # Iniciar tareas en segundo plano
        self.check_temp_roles.start()
        self.reset_daily_counters.start()

        # Sincronizar comandos slash
        log.info("Sincronizando comandos slash...")
        await self.tree.sync()
        log.info("✅ Comandos sincronizados.")

    async def _init_database(self):
        """Ejecuta el schema SQL si las tablas no existen."""
        async with self.db.acquire() as conn:
            # Verificar si la tabla 'users' existe
            exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'users'
                );
            """)
            if not exists:
                log.info("Inicializando base de datos con schema.sql...")
                schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
                with open(schema_path, "r", encoding="utf-8") as f:
                    schema = f.read()
                await conn.execute(schema)
                log.info("✅ Schema aplicado correctamente.")
            else:
                log.info("Base de datos ya inicializada.")

    async def _load_cogs(self):
        """Carga todos los cogs desde la carpeta cogs/."""
        cogs_dir = os.path.join(os.path.dirname(__file__), "cogs")
        if not os.path.exists(cogs_dir):
            os.makedirs(cogs_dir)
            log.warning("Carpeta cogs/ creada. Añade tus módulos ahí.")
            return

        for filename in sorted(os.listdir(cogs_dir)):
            if filename.endswith(".py") and not filename.startswith("_"):
                cog_name = f"cogs.{filename[:-3]}"
                try:
                    await self.load_extension(cog_name)
                    log.info(f"  ✅ Cog cargado: {cog_name}")
                except Exception as e:
                    log.error(f"  ❌ Error cargando {cog_name}: {e}")

    # ── Eventos ──────────────────────���─────────────────────────
    async def on_ready(self):
        log.info(f"Bot conectado como {self.user} (ID: {self.user.id})")
        log.info(f"Servidores: {len(self.guilds)}")

        print(f"✅ {self.user.name} está online!")

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.competing,
                name="🧠 /quiz · /daily · /rank",
            )
        )

    async def on_guild_join(self, guild: discord.Guild):
        """Registrar configuración por defecto al unirse a un servidor."""
        log.info(f"Unido al servidor: {guild.name} ({guild.id})")
        async with self.db.acquire() as conn:
            await conn.execute("""
                INSERT INTO guild_config (guild_id)
                VALUES ($1)
                ON CONFLICT (guild_id) DO NOTHING;
            """, guild.id)

    # ── Tareas en segundo plano ────────────────────────────────
    @tasks.loop(minutes=1)
    async def check_temp_roles(self):
        """Revisa y elimina roles temporales expirados."""
        if not self.db:
            return

        async with self.db.acquire() as conn:
            expired = await conn.fetch("""
                SELECT temp_role_id, user_id, guild_id, role_id
                FROM temp_roles
                WHERE removed = FALSE AND expires_at < NOW();
            """)

            for row in expired:
                try:
                    guild = self.get_guild(row["guild_id"])
                    if not guild:
                        continue
                    member = guild.get_member(row["user_id"])
                    if not member:
                        continue
                    role = guild.get_role(row["role_id"])
                    if role and role in member.roles:
                        await member.remove_roles(role, reason="Rol temporal expirado")
                        log.info(
                            f"Rol temporal {role.name} removido de {member.display_name}"
                        )
                except discord.Forbidden:
                    log.warning(
                        f"Sin permisos para remover rol {row['role_id']} "
                        f"en guild {row['guild_id']}"
                    )
                except Exception as e:
                    log.error(f"Error removiendo rol temporal: {e}")

                # Marcar como removido en la DB
                await conn.execute("""
                    UPDATE temp_roles SET removed = TRUE
                    WHERE temp_role_id = $1;
                """, row["temp_role_id"])

    @check_temp_roles.before_loop
    async def before_check_temp_roles(self):
        await self.wait_until_ready()

    @tasks.loop(hours=24)
    async def reset_daily_counters(self):
        """Resetea contadores diarios (robos, etc.)."""
        if not self.db:
            return
        async with self.db.acquire() as conn:
            await conn.execute("SELECT reset_daily_counters();")
            log.info("✅ Contadores diarios reseteados.")

    @reset_daily_counters.before_loop
    async def before_reset_daily(self):
        await self.wait_until_ready()
        # Esperar hasta medianoche para empezar el loop
        now = datetime.utcnow()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if now > midnight:
            from datetime import timedelta
            midnight += timedelta(days=1)
        delta = (midnight - now).total_seconds()
        log.info(f"Reset diario programado en {delta:.0f} segundos.")
        await asyncio.sleep(delta)

    # ── Cierre limpio ──────────────────────────────────────────
    async def close(self):
        log.info("Cerrando bot...")
        if self.db:
            await self.db.close()
            log.info("Pool de PostgreSQL cerrado.")
        await super().close()


# ── Helper para acceder a la DB desde los cogs ────────────────
async def get_or_create_user(
    db: asyncpg.Pool, user_id: int, guild_id: int, username: str
) -> asyncpg.Record:
    """Obtiene un usuario o lo crea si no existe."""
    async with db.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT * FROM users WHERE user_id = $1 AND guild_id = $2",
            user_id,
            guild_id,
        )
        if not user:
            user = await conn.fetchrow("""
                INSERT INTO users (user_id, guild_id, username)
                VALUES ($1, $2, $3)
                RETURNING *;
            """, user_id, guild_id, username)
        return user


async def log_transaction(
    db: asyncpg.Pool,
    user_id: int,
    guild_id: int,
    tx_type: str,
    points_delta: int = 0,
    money_delta: int = 0,
    description: str = "",
):
    """Registra una transacción económica."""
    async with db.acquire() as conn:
        await conn.execute("""
            INSERT INTO transactions (user_id, guild_id, tx_type, points_delta, money_delta, description)
            VALUES ($1, $2, $3, $4, $5, $6);
        """, user_id, guild_id, tx_type, points_delta, money_delta, description)


# ── Entry Point ────────────────────────────────────────────────
def main():
    if not TOKEN:
        log.error("❌ DISCORD_TOKEN no configurado en .env")
        return
    if not DATABASE_URL:
        log.error("❌ DATABASE_URL no configurado en .env")
        return

    bot = CompetitiveBot()
    bot.run(TOKEN, log_handler=None)


if __name__ == "__main__":
    main()