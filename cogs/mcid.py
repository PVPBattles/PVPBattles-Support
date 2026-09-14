import re

import discord
from discord import app_commands
from discord.ext import commands

from storage import get_guild_config, set_guild_value


# 英字・数字・アンダーバーのみ
MCID_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")

# Discordのニックネーム上限
MAX_NICKNAME_LENGTH = 32


class MCID(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def get_channel(self, guild: discord.Guild):
        config = get_guild_config(guild.id)

        channel_id = config.get("mcid_channel_id")

        if not channel_id:
            return None

        return guild.get_channel(channel_id)

    # =========================
    # /mcid-setup
    # =========================

    @app_commands.command(
        name="mcid-setup",
        description="Set the channel for MCID registration."
    )
    @app_commands.describe(
        channel="The channel where users register their MCID."
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def mcid_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ This command can only be used in a server.",
                ephemeral=True
            )
            return

        set_guild_value(
            interaction.guild.id,
            "mcid_channel_id",
            channel.id
        )

        await interaction.response.send_message(
            f"✅ MCID registration channel has been set to "
            f"{channel.mention}.",
            ephemeral=True
        )

    # =========================
    # /mcid-disable
    # =========================

    @app_commands.command(
        name="mcid-disable",
        description="Disable MCID registration."
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def mcid_disable(
        self,
        interaction: discord.Interaction
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ This command can only be used in a server.",
                ephemeral=True
            )
            return

        set_guild_value(
            interaction.guild.id,
            "mcid_channel_id",
            None
        )

        await interaction.response.send_message(
            "✅ MCID registration has been disabled.",
            ephemeral=True
        )

    # =========================
    # MCID Registration
    # =========================

    @commands.Cog.listener()
    async def on_message(
        self,
        message: discord.Message
    ):
        # Bot自身・他のBotは無視
        if message.author.bot:
            return

        # DMは無視
        if message.guild is None:
            return

        channel = self.get_channel(message.guild)

        # MCID登録チャンネルではない
        if channel is None:
            return

        if message.channel.id != channel.id:
            return

        mcid = message.content.strip()

        # 空文字
        if not mcid:
            await self.add_reaction(
                message,
                "❌"
            )
            return

        # 英字・数字・アンダーバー以外を禁止
        if not MCID_PATTERN.fullmatch(mcid):
            await self.add_reaction(
                message,
                "❌"
            )

            await message.reply(
                "❌ Your MCID can only contain "
                "English letters, numbers, and `_`.",
                mention_author=False,
                delete_after=5
            )

            return

        # Discordのニックネーム上限
        if len(mcid) > MAX_NICKNAME_LENGTH:
            await self.add_reaction(
                message,
                "❌"
            )

            await message.reply(
                "❌ Your MCID is too long. "
                "The maximum length is 32 characters.",
                mention_author=False,
                delete_after=5
            )

            return

        member = message.author

        if not isinstance(member, discord.Member):
            await self.add_reaction(
                message,
                "❌"
            )
            return

        # =========================
        # ニックネーム変更
        # =========================

        try:
            await member.edit(
                nick=mcid,
                reason="MCID registration"
            )

        except discord.Forbidden:
            await self.add_reaction(
                message,
                "❌"
            )

            await message.reply(
                "❌ I don't have permission to change "
                "your nickname.",
                mention_author=False,
                delete_after=5
            )

            return

        except discord.HTTPException:
            await self.add_reaction(
                message,
                "❌"
            )

            await message.reply(
                "❌ Failed to register your MCID.",
                mention_author=False,
                delete_after=5
            )

            return

        # =========================
        # 成功
        # =========================

        await self.add_reaction(
            message,
            "✅"
        )

    # =========================
    # Reaction Helper
    # =========================

    async def add_reaction(
        self,
        message: discord.Message,
        emoji: str
    ):
        try:
            await message.add_reaction(emoji)

        except (
            discord.Forbidden,
            discord.HTTPException
        ):
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(MCID(bot))
