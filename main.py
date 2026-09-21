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

        intents.members = True
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):

        extensions = [
            "cogs.welcome",
            "cogs.leave",
            "cogs.mcid",
            "cogs.rule",
            "cogs.ticket",
            "cogs.youtube",
        ]

        # =========================
        # Cog読み込み
        # =========================

        for extension in extensions:
            try:
                await self.load_extension(extension)

                logger.info(
                    "Loaded %s",
                    extension
                )

            except Exception:
                logger.exception(
                    "Failed to load %s",
                    extension
                )

        # =========================
        # Rule Persistent View
        # =========================

        try:
            from cogs.rule import VerifyView

            self.add_view(
                VerifyView()
            )

            logger.info(
                "Registered persistent VerifyView."
            )

        except Exception:
            logger.exception(
                "Failed to register VerifyView."
            )

        # =========================
        # Ticket Persistent Views
        # =========================

        try:
            from cogs.ticket import (
                TicketPanelView,
                TicketCloseView
            )

            self.add_view(
                TicketPanelView()
            )

            self.add_view(
                TicketCloseView()
            )

            logger.info(
                "Registered persistent Ticket views."
            )

        except Exception:
            logger.exception(
                "Failed to register Ticket views."
            )

        # =========================
        # Slash Command Sync
        # =========================

        guild_id = os.getenv(
            "GUILD_ID"
        )

        try:

            if guild_id:

                guild = discord.Object(
                    id=int(guild_id)
                )

                # ギルド用にグローバルコマンドをコピー
                self.tree.copy_global_to(
                    guild=guild
                )

                synced = await self.tree.sync(
                    guild=guild
                )

                logger.info(
                    "Synced %s slash commands to guild %s.",
                    len(synced),
                    guild_id
                )

                for command in synced:

                    logger.info(
                        "Guild command: /%s",
                        command.name
                    )

            else:

                synced = await self.tree.sync()

                logger.info(
                    "Synced %s global slash commands.",
                    len(synced)
                )

                for command in synced:

                    logger.info(
                        "Global command: /%s",
                        command.name
                    )

        except Exception:

            logger.exception(
                "Failed to sync slash commands."
            )

    # =========================
    # Bot Ready
    # =========================

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

    token = os.getenv(
        "DISCORD_TOKEN"
    )

    if not token:

        raise RuntimeError(
            "DISCORD_TOKEN environment variable is not set."
        )

    # Render用Keep Alive
    start_keep_alive()

    bot = DiscordBot()

    try:

        bot.run(
            token
        )

    except Exception:

        logger.exception(
            "Bot stopped unexpectedly."
        )


if __name__ == "__main__":
    main()
