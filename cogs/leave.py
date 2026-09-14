import discord
from discord import app_commands
from discord.ext import commands

from storage import get_guild_config, set_guild_value


class Leave(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def get_channel(self, guild: discord.Guild):
        config = get_guild_config(guild.id)
        channel_id = config.get("leave_channel_id")

        if not channel_id:
            return None

        return guild.get_channel(channel_id)

    @app_commands.command(
        name="leave-setup",
        description="Set the leave notification channel."
    )
    @app_commands.describe(
        channel="The channel for leave notifications."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def leave_setup(
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
            "leave_channel_id",
            channel.id
        )

        await interaction.response.send_message(
            f"✅ Leave notifications will be sent to "
            f"{channel.mention}.",
            ephemeral=True
        )

    @app_commands.command(
        name="leave-disable",
        description="Disable leave notifications."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def leave_disable(
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
            "leave_channel_id",
            None
        )

        await interaction.response.send_message(
            "✅ Leave notifications have been disabled.",
            ephemeral=True
        )

    @app_commands.command(
        name="leave-test",
        description="Send a test leave notification."
    )
    @app_commands.default_permissions(manage_guild=True)
    async def leave_test(
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
                "❌ Leave channel is not configured.\n"
                "Use `/leave-setup` first.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🧪 Goodbye Test",
            description=(
                f"**{interaction.user.display_name}** "
                f"has left **{interaction.guild.name}**.\n\n"
                "This is a test leave notification."
            ),
            color=discord.Color.red()
        )

        embed.set_thumbnail(
            url=interaction.user.display_avatar.url
        )

        embed.add_field(
            name="👤 Member",
            value=discord.utils.escape_markdown(
                interaction.user.name
            ),
            inline=True
        )

        embed.add_field(
            name="👥 Members",
            value=str(interaction.guild.member_count),
            inline=True
        )

        embed.set_footer(
            text=f"{interaction.guild.name} • Goodbye"
        )

        try:
            await channel.send(embed=embed)

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
    async def on_member_remove(
        self,
        member: discord.Member
    ):
        channel = self.get_channel(member.guild)

        if channel is None:
            return

        member_count = member.guild.member_count

        if member_count is None:
            member_count = "Unknown"

        embed = discord.Embed(
            title="👋 Goodbye!",
            description=(
                f"**{member.display_name}** has left "
                f"**{member.guild.name}**."
            ),
            color=discord.Color.red()
        )

        embed.set_thumbnail(
            url=member.display_avatar.url
        )

        embed.add_field(
            name="👤 Member",
            value=discord.utils.escape_markdown(
                member.name
            ),
            inline=True
        )

        embed.add_field(
            name="👥 Members",
            value=str(member_count),
            inline=True
        )

        embed.set_footer(
            text=f"{member.guild.name} • Goodbye"
        )

        try:
            await channel.send(embed=embed)

        except (
            discord.Forbidden,
            discord.HTTPException
        ):
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Leave(bot))
