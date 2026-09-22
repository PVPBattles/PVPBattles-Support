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

        # =============================================
        # Cog読み込み
        # =============================================

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
                logger.info("Loaded %s", extension)

            except Exception:
                logger.exception(
                    "Failed to load %s",
                    extension
                )

        # =============================================
        # Persistent Views
        # =============================================

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

        # =============================================
        # Slash Command Sync
        # =============================================

        guild_id = os.getenv("GUILD_ID")

        try:

            # -----------------------------------------
            # GUILD_IDが設定されている場合
            # -----------------------------------------

            if guild_id:

                guild = discord.Object(
                    id=int(guild_id)
                )

                # -------------------------------------
                # 現在のコマンドを保存
                # -------------------------------------

                current_commands = list(
                    self.tree.get_commands()
                )

                logger.info(
                    "Current local commands: %s",
                    len(current_commands)
                )

                # -------------------------------------
                # 古いグローバルコマンドを削除
                # -------------------------------------
                #
                # 過去に登録されたコマンドがDiscord側の
                # Global Commandとして残っている場合、
                # Guild Commandと二重に表示されることがある。
                #
                # 一度Global Commandを空にして同期する。
                # -------------------------------------

                self.tree.clear_commands()

                await self.tree.sync()

                logger.info(
                    "Cleared old global slash commands."
                )

                # -------------------------------------
                # 現在のコマンドをTreeへ戻す
                # -------------------------------------

                for command in current_commands:
                    self.tree.add_command(
                        command
                    )

                # -------------------------------------
                # Guild用に現在のコマンドだけコピー
                # -------------------------------------

                self.tree.clear_commands(
                    guild=guild
                )

                self.tree.copy_global_to(
                    guild=guild
                )

                # -------------------------------------
                # Guildへ同期
                # -------------------------------------

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

            # -----------------------------------------
            # GUILD_IDがない場合
            # -----------------------------------------

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
