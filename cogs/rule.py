import logging

import discord
from discord import app_commands
from discord.ext import commands

from storage import get_guild_config, set_guild_value


logger = logging.getLogger("discord_bot")


# =========================================================
# Rule Edit Modal
# =========================================================

class RuleEditModal(discord.ui.Modal, title="Edit Rules"):

    rules = discord.ui.TextInput(
        label="Rules",
        style=discord.TextStyle.paragraph,
        placeholder="Enter your server rules here.",
        required=True,
        max_length=4000
    )

    def __init__(self, guild_id: int):
        super().__init__()

        self.guild_id = guild_id

        config = get_guild_config(guild_id)
        current_rules = config.get("rule_text")

        if current_rules:
            self.rules.default = current_rules

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):
        set_guild_value(
            self.guild_id,
            "rule_text",
            self.rules.value
        )

        await interaction.response.send_message(
            "✅ Rules have been saved!\n"
            "Run `/rule` to send the updated rules panel.",
            ephemeral=True
        )


# =========================================================
# Verify Button
# =========================================================

class VerifyButton(discord.ui.Button):

    def __init__(self):
        super().__init__(
            label="Verify",
            emoji="🔒",
            style=discord.ButtonStyle.success,
            custom_id="rule:verify"
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ This button can only be used in a server.",
                ephemeral=True
            )
            return

        config = get_guild_config(
            interaction.guild.id
        )

        role_id = config.get(
            "rule_role_id"
        )

        if not role_id:
            await interaction.response.send_message(
                "❌ The verification role has not been configured.",
                ephemeral=True
            )
            return

        role = interaction.guild.get_role(
            role_id
        )

        if role is None:
            await interaction.response.send_message(
                "❌ The verification role could not be found.",
                ephemeral=True
            )
            return

        member = interaction.user

        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "❌ Could not retrieve your member information.",
                ephemeral=True
            )
            return

        # Already verified
        if role in member.roles:
            await interaction.response.send_message(
                "🔓 **You are already Verified!**",
                ephemeral=True
            )
            return

        bot_member = interaction.guild.me

        if bot_member is None:
            await interaction.response.send_message(
                "❌ Could not retrieve the bot information.",
                ephemeral=True
            )
            return

        # Role hierarchy check
        if role >= bot_member.top_role:
            await interaction.response.send_message(
                "❌ I cannot give you this role.\n"
                "Please move the bot's role above the verification role.",
                ephemeral=True
            )
            return

        try:
            await member.add_roles(
                role,
                reason="Rule verification"
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I could not give you the verification role.\n"
                "Please make sure the bot has the Manage Roles permission.",
                ephemeral=True
            )
            return

        except discord.HTTPException:
            await interaction.response.send_message(
                "❌ Verification failed. Please try again.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "🔓 **You are now Verified!**\n"
            "You now have access to the server.",
            ephemeral=True
        )


# =========================================================
# Persistent Verify View
# =========================================================

class VerifyView(discord.ui.View):

    def __init__(self):
        super().__init__(
            timeout=None
        )

        self.add_item(
            VerifyButton()
        )


# =========================================================
# Rule Cog
# =========================================================

class Rule(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot
    ):
        self.bot = bot

    # =====================================================
    # /rule-setup
    # =====================================================

    @app_commands.command(
        name="rule-setup",
        description="Configure the rule verification panel."
    )
    @app_commands.describe(
        channel="The channel where the rule panel will be sent.",
        role="The role given after verification."
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def rule_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        role: discord.Role
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ This command can only be used in a server.",
                ephemeral=True
            )
            return

        bot_member = interaction.guild.me

        if bot_member is not None:
            if role >= bot_member.top_role:
                await interaction.response.send_message(
                    "❌ I cannot give users this role.\n"
                    "Please move the bot's role above the verification role.",
                    ephemeral=True
                )
                return

        set_guild_value(
            interaction.guild.id,
            "rule_channel_id",
            channel.id
        )

        set_guild_value(
            interaction.guild.id,
            "rule_role_id",
            role.id
        )

        await interaction.response.send_message(
            "✅ Rule verification has been configured!\n\n"
            f"📢 Channel: {channel.mention}\n"
            f"🛡️ Verification Role: {role.mention}\n\n"
            "Next, use `/rule-edit` to set your rules.",
            ephemeral=True
        )

    # =====================================================
    # /rule-edit
    # =====================================================

    @app_commands.command(
        name="rule-edit",
        description="Edit the server rules."
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def rule_edit(
        self,
        interaction: discord.Interaction
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ This command can only be used in a server.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            RuleEditModal(
                interaction.guild.id
            )
        )

    # =====================================================
    # /rule
    # =====================================================

    @app_commands.command(
        name="rule",
        description="Send the server rules and verification panel."
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def rule(
        self,
        interaction: discord.Interaction
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ This command can only be used in a server.",
                ephemeral=True
            )
            return

        config = get_guild_config(
            interaction.guild.id
        )

        channel_id = config.get(
            "rule_channel_id"
        )

        role_id = config.get(
            "rule_role_id"
        )

        rules = config.get(
            "rule_text"
        )

        # -------------------------------------------------
        # Channel check
        # -------------------------------------------------

        if not channel_id:
            await interaction.response.send_message(
                "❌ The rule channel has not been configured.\n"
                "Use `/rule-setup` first.",
                ephemeral=True
            )
            return

        # -------------------------------------------------
        # Role check
        # -------------------------------------------------

        if not role_id:
            await interaction.response.send_message(
                "❌ The verification role has not been configured.\n"
                "Use `/rule-setup` first.",
                ephemeral=True
            )
            return

        # -------------------------------------------------
        # Rules check
        # -------------------------------------------------

        if not rules:
            await interaction.response.send_message(
                "❌ The rules have not been configured.\n"
                "Use `/rule-edit` first.",
                ephemeral=True
            )
            return

        # -------------------------------------------------
        # Get channel
        # -------------------------------------------------

        channel = interaction.guild.get_channel(
            channel_id
        )

        if channel is None:
            await interaction.response.send_message(
                "❌ The configured rule channel could not be found.",
                ephemeral=True
            )
            return

        # -------------------------------------------------
        # Get role
        # -------------------------------------------------

        role = interaction.guild.get_role(
            role_id
        )

        if role is None:
            await interaction.response.send_message(
                "❌ The configured verification role could not be found.",
                ephemeral=True
            )
            return

        # -------------------------------------------------
        # Bot member
        # -------------------------------------------------

        bot_member = interaction.guild.me

        if bot_member is None:
            await interaction.response.send_message(
                "❌ Could not retrieve the bot information.",
                ephemeral=True
            )
            return

        # -------------------------------------------------
        # Permission check
        # -------------------------------------------------

        permissions = channel.permissions_for(
            bot_member
        )

        missing_permissions = []

        if not permissions.view_channel:
            missing_permissions.append(
                "View Channel"
            )

        if not permissions.send_messages:
            missing_permissions.append(
                "Send Messages"
            )

        if not permissions.embed_links:
            missing_permissions.append(
                "Embed Links"
            )

        if not permissions.manage_roles:
            missing_permissions.append(
                "Manage Roles"
            )

        if missing_permissions:
            missing = "\n".join(
                f"• {permission}"
                for permission in missing_permissions
            )

            await interaction.response.send_message(
                "❌ I don't have the required permissions "
                "in the rule channel.\n\n"
                f"{missing}",
                ephemeral=True
            )
            return

        # -------------------------------------------------
        # Create embed
        # -------------------------------------------------

        embed = discord.Embed(
            title="🔒 Server Rules",
            description=rules,
            color=discord.Color.blurple()
        )

        embed.set_footer(
            text=f"{interaction.guild.name} • Verification"
        )

        # -------------------------------------------------
        # Send panel
        # -------------------------------------------------

        try:
            await channel.send(
                embed=embed,
                view=VerifyView()
            )

        except discord.Forbidden:
            logger.exception(
                "Forbidden while sending rule panel "
                "in guild %s / channel %s",
                interaction.guild.id,
                channel.id
            )

            await interaction.response.send_message(
                "❌ Discord rejected the message.\n"
                "Please check the bot's permissions in the rule channel.",
                ephemeral=True
            )
            return

        except discord.HTTPException as e:
            logger.exception(
                "HTTPException while sending rule panel "
                "in guild %s / channel %s: %s",
                interaction.guild.id,
                channel.id,
                e
            )

            await interaction.response.send_message(
                "❌ Failed to send the rule panel.\n"
                f"Discord error: `{e}`",
                ephemeral=True
            )
            return

        except Exception as e:
            logger.exception(
                "Unexpected error while sending rule panel "
                "in guild %s / channel %s",
                interaction.guild.id,
                channel.id
            )

            await interaction.response.send_message(
                "❌ An unexpected error occurred.\n"
                f"`{type(e).__name__}: {e}`",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ Rule panel sent to {channel.mention}.",
            ephemeral=True
        )

    # =====================================================
    # /rule-disable
    # =====================================================

    @app_commands.command(
        name="rule-disable",
        description="Disable rule verification."
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def rule_disable(
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
            "rule_channel_id",
            None
        )

        set_guild_value(
            interaction.guild.id,
            "rule_role_id",
            None
        )

        set_guild_value(
            interaction.guild.id,
            "rule_text",
            None
        )

        await interaction.response.send_message(
            "✅ Rule verification has been disabled.",
            ephemeral=True
        )


# =========================================================
# Extension Setup
# =========================================================

async def setup(
    bot: commands.Bot
):
    await bot.add_cog(
        Rule(bot)
    )
