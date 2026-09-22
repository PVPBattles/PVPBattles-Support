import os
import logging

import discord
from discord.ext import commands

from keep_alive import start_keep_alive


# =========================================================
# Logging
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

logger = logging.getLogger("discord_bot")


# =========================================================
# Bot
# =========================================================

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

    # =====================================================
    # Setup Hook
    # =====================================================

    async def setup_hook(self):

        # -------------------------------------------------
        # Cog読み込み
        # -------------------------------------------------

        extensions = [
            "cogs.welcome",
            "cogs.leave",
            "cogs.mcid",
            "cogs.rule",
            "cogs.ticket",
            "cogs.youtube",
            "cogs.role",
            "cogs.embed",
        ]

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

        # -------------------------------------------------
        # Persistent Views
        # -------------------------------------------------

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

        # -------------------------------------------------
        # Slash Command Sync
        # -------------------------------------------------

        guild_id = os.getenv("GUILD_ID")

        if not guild_id:
            logger.error(
                "GUILD_ID is not set."
            )

            logger.error(
                "Slash commands will NOT be registered globally."
            )

            return

        try:
            guild_id_int = int(guild_id)

        except ValueError:
            logger.error(
                "GUILD_ID is invalid: %s",
                guild_id
            )
            return

        guild = discord.Object(
            id=guild_id_int
        )

        try:
            # =============================================
            # 現在Cogから登録されているコマンドを取得
            # =============================================

            commands_to_register = list(
                self.tree.get_commands()
            )

            logger.info(
                "Found %s local slash commands.",
                len(commands_to_register)
            )

            for command in commands_to_register:
                logger.info(
                    "Found command: /%s",
                    command.name
                )

            # =============================================
            # IMPORTANT
            #
            # Global commandを完全に削除
            # =============================================

            self.tree.clear_commands()

            await self.tree.sync()

            logger.info(
                "Global slash commands cleared."
            )

            # =============================================
            # Guild側の古いコマンドを完全削除
            # =============================================

            self.tree.clear_commands(
                guild=guild
            )

            await self.tree.sync(
                guild=guild
            )

            logger.info(
                "Old guild slash commands cleared."
            )

            # =============================================
            # コマンドをGuild専用として直接登録
            #
            # copy_global_to() は使用しない
            # =============================================

            for command in commands_to_register:

                self.tree.add_command(
                    command,
                    guild=guild
                )

            logger.info(
                "Registered %s commands directly to guild %s.",
                len(commands_to_register),
                guild_id
            )

            # =============================================
            # Guildへ同期
            # =============================================

            synced = await self.tree.sync(
                guild=guild
            )

            logger.info(
                "Successfully synced %s slash commands to guild %s.",
                len(synced),
                guild_id
            )

            # =============================================
            # 同期されたコマンド一覧
            # =============================================

            for command in synced:
                logger.info(
                    "Guild command: /%s",
                    command.name
                )

        except Exception:
            logger.exception(
                "Failed to sync slash commands."
            )


    # =====================================================
    # Ready
    # =====================================================

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


# =========================================================
# Main
# =========================================================

def main():

    token = os.getenv(
        "DISCORD_TOKEN"
    )

    if not token:
        raise RuntimeError(
            "DISCORD_TOKEN environment variable is not set."
        )

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


# =========================================================
# Entry Point
# =========================================================

if __name__ == "__main__":
    main()
