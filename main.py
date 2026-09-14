import os
import logging

import discord
from discord.ext import commands

from keep_alive import start_keep_alive


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

logger = logging.getLogger("discord_bot")


class DiscordBot(commands.Bot):

    def __init__(self):
        intents = discord.Intents.default()

        # メンバー参加・退出
        intents.members = True

        # メッセージ内容を読む
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):

        # =========================
        # Cogs
        # =========================

        await self.load_extension("cogs.welcome")
        logger.info("Loaded cogs.welcome")

        await self.load_extension("cogs.leave")
        logger.info("Loaded cogs.leave")

        await self.load_extension("cogs.mcid")
        logger.info("Loaded cogs.mcid")

        # =========================
        # Slash Commands
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


def main():

    token = os.getenv("DISCORD_TOKEN")

    if not token:
        raise RuntimeError(
            "DISCORD_TOKEN environment variable is not set."
        )

    # Render用
    start_keep_alive()

    bot = DiscordBot()

    try:
        bot.run(token)

    except Exception:
        logger.exception(
            "Bot stopped unexpectedly."
        )


if __name__ == "__main__":
    main()
