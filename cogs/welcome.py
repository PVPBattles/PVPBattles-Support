import discord
from discord import app_commands
from discord.ext import commands

from storage import get_guild_config, set_guild_value


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def get_welcome_channel_id(self, guild_id: int):
        config = get_guild_config(guild_id)
        return config.get("welcome_channel_id")

    def create_welcome_embed(
        self,
        member: discord.Member
    ) -> discord.Embed:
        guild = member.guild

        embed = discord.Embed(
            title="👋 Welcome!",
            description=(
                f"Welcome to **{guild.name}**, {member.mention}!\n\n"
                "We're glad to have you here!"
            ),
            color=discord.Color.blurple()
        )

        embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(
            name="👤 Member",
            value=member.mention,
            inline=True
        )

        embed.add_field(
            name="👥 Members",
            value=str(guild.member_count),
            inline=True
        )

        embed.set_footer(
            text=f"{guild.name} • Welcome"
        )

        return embed

    @app_commands.command(
        name="welcome-setup",
        description="Set the channel for welcome messages."
    )
    @app_commands.describe(
        channel="The channel where welcome messages will be sent."
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

        embed = discord.Embed(
            title="✅ Welcome Setup Complete",
            description=(
                f"Welcome messages will now be sent to {channel.mention}."
            ),
            color=discord.Color.green()
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

    @app_commands.command(
        name="welcome-disable",
        description="Disable welcome messages."
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

        embed = discord.Embed(
            title="✅ Welcome Disabled",
            description="Welcome messages have been disabled.",
            color=discord.Color.red()
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

    @app_commands.command(
        name="welcome-test",
        description="Send a test welcome message."
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

        channel_id = self.get_welcome_channel_id(
            interaction.guild.id
        )

        if not channel_id:
            await interaction.response.send_message(
                "❌ Welcome messages are not configured yet.\n"
                "Use `/welcome-setup` first.",
                ephemeral=True
            )
            return

        channel = interaction.guild.get_channel(channel_id)

        if channel is None:
            await interaction.response.send_message(
                "❌ The configured welcome channel no longer exists.\n"
                "Please use `/welcome-setup` again.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="👋 Welcome Test",
            description=(
                f"This is a test welcome message from "
                f"**{interaction.guild.name}**!"
            ),
            color=discord.Color.blurple()
        )

        embed.set_thumbnail(
            url=interaction.user.display_avatar.url
        )

        embed.add_field(
            name="👤 User",
            value=interaction.user.mention,
            inline=True
        )

        embed.add_field(
            name="👥 Members",
            value=str(interaction.guild.member_count),
            inline=True
        )

        embed.set_footer(
            text="Welcome system test"
        )

        try:
            await channel.send(embed=embed)

            await interaction.response.send_message(
                f"✅ Test message sent to {channel.mention}.",
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
                "❌ Failed to send the test message.",
                ephemeral=True
            )

    @commands.Cog.listener()
    async def on_member_join(
        self,
        member: discord.Member
    ):
        channel_id = self.get_welcome_channel_id(
            member.guild.id
        )

        if not channel_id:
            return

        channel = member.guild.get_channel(channel_id)

        if channel is None:
            return

        embed = self.create_welcome_embed(member)

        try:
            await channel.send(
                content=member.mention,
                embed=embed
            )

        except discord.Forbidden:
            pass

        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
