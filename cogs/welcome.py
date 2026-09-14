import discord
from discord import app_commands
from discord.ext import commands

from storage import get_guild_config, set_guild_value


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def get_channel(self, guild: discord.Guild):
        config = get_guild_config(guild.id)
        channel_id = config.get("welcome_channel_id")

        if not channel_id:
            return None

        return guild.get_channel(channel_id)

    @app_commands.command(
        name="welcome-setup",
        description="Set the welcome notification channel."
    )
    @app_commands.describe(
        channel="The channel for welcome notifications."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def welcome_setup(
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
            "welcome_channel_id",
            channel.id
        )

        await interaction.response.send_message(
            f"✅ Welcome notifications will be sent to "
            f"{channel.mention}.",
            ephemeral=True
        )

    @app_commands.command(
        name="welcome-disable",
        description="Disable welcome notifications."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def welcome_disable(
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
            "welcome_channel_id",
            None
        )

        await interaction.response.send_message(
            "✅ Welcome notifications have been disabled.",
            ephemeral=True
        )

    @app_commands.command(
        name="welcome-test",
        description="Send a test welcome notification."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def welcome_test(
        self,
        interaction: discord.Interaction
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ This command can only be used in a server.",
                ephemeral=True
            )
            return

        channel = self.get_channel(interaction.guild)

        if channel is None:
            await interaction.response.send_message(
                "❌ Welcome channel is not configured.\n"
                "Use `/welcome-setup` first.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🧪 Welcome Test",
            description=(
                f"Welcome to **{interaction.guild.name}**, "
                f"{interaction.user.mention}!\n\n"
                "This is a test welcome notification."
            ),
            color=discord.Color.blurple()
        )

        embed.set_thumbnail(
            url=interaction.user.display_avatar.url
        )

        embed.add_field(
            name="👤 Member",
            value=interaction.user.mention,
            inline=True
        )

        embed.add_field(
            name="👥 Members",
            value=str(interaction.guild.member_count),
            inline=True
        )

        embed.set_footer(
            text=f"{interaction.guild.name} • Welcome"
        )

        try:
            await channel.send(
                content=interaction.user.mention,
                embed=embed
            )

            await interaction.response.send_message(
                f"✅ Test notification sent to {channel.mention}.",
                ephemeral=True
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to send messages "
                "in that channel.",
                ephemeral=True
            )

        except discord.HTTPException:
            await interaction.response.send_message(
                "❌ Failed to send the notification.",
                ephemeral=True
            )

    @commands.Cog.listener()
    async def on_member_join(
        self,
        member: discord.Member
    ):
        channel = self.get_channel(member.guild)

        if channel is None:
            return

        embed = discord.Embed(
            title="👋 Welcome!",
            description=(
                f"Welcome to **{member.guild.name}**, "
                f"{member.mention}!\n\n"
                "We're glad to have you here!"
            ),
            color=discord.Color.blurple()
        )

        embed.set_thumbnail(
            url=member.display_avatar.url
        )

        embed.add_field(
            name="👤 Member",
            value=member.mention,
            inline=True
        )

        embed.add_field(
            name="👥 Members",
            value=str(member.guild.member_count),
            inline=True
        )

        embed.set_footer(
            text=f"{member.guild.name} • Welcome"
        )

        try:
            await channel.send(
                content=member.mention,
                embed=embed
            )

        except (
            discord.Forbidden,
            discord.HTTPException
        ):
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
