import os
import logging

import discord
from discord.ext import commands

from keep_alive import start_keep_alive


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

logger = logging.getLogger("welcome_bot")


class WelcomeBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        await self.load_extension("cogs.welcome")

        try:
            synced = await self.tree.sync()
            logger.info("Synced %s slash commands.", len(synced))
        except Exception:
            logger.exception("Failed to sync slash commands.")

    async def on_ready(self):
        logger.info(
            "Logged in as %s (ID: %s)",
            self.user,
            self.user.id
        )


def main():
    token = os.getenv("DISCORD_TOKEN")

    if not token:
        raise RuntimeError(
            "DISCORD_TOKEN environment variable is not set."
        )

    start_keep_alive()

    bot = WelcomeBot()

    try:
        bot.run(token)
    except Exception:
        logger.exception("Bot stopped unexpectedly.")


if __name__ == "__main__":
    main()
