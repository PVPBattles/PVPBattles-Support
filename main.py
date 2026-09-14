import os
import logging

import discord
from discord.ext import commands

from keep_alive import start_keep_alive


# =========================
# Logging
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

logger = logging.getLogger("mcid_bot")


# =========================
# Bot
# =========================

class MCIDBot(commands.Bot):

    def __init__(self):
        intents = discord.Intents.default()

        # メンバー情報
        intents.members = True

        # メッセージ内容を読むために必要
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):

        # MCID機能
        await self.load_extension("cogs.mcid")

        logger.info("Loaded cogs.mcid")

        # =========================
        # Slash Commands Sync
        # =========================

        try:
            synced = await self.tree.sync()

            logger.info(
                "Synced %s slash commands.",
                len(synced)
            )

            for command in synced:
                logger.info(
                    "Registered command: /%s",
                    command.name
                )

        except Exception:
            logger.exception(
                "Failed to sync slash commands."
            )

    async def on_ready(self):

        logger.info(
            "Logged in as %s (ID: %s)",
            self.user,
            self.user.id
        )

        logger.info(
            "Connected to %s server(s).",
            len(self.guilds)
        )


# =========================
# Main
# =========================

def main():

    token = os.getenv("DISCORD_TOKEN")

    if not token:
        raise RuntimeError(
            "DISCORD_TOKEN environment variable is not set."
        )

    # Render用
    start_keep_alive()

    bot = MCIDBot()

    try:
        bot.run(token)

    except Exception:
        logger.exception(
            "Bot stopped unexpectedly."
        )


if __name__ == "__main__":
    main()
