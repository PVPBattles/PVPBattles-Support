import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from storage import get_guild_config, set_guild_value


logger = logging.getLogger("discord_bot")


# =========================================================
# Default Settings
# =========================================================

DEFAULT_TITLE = "🎫 PVPBattles Support"

DEFAULT_DESCRIPTION = (
    "Need help?\n"
    "Click the button below to create a private support ticket."
)

DEFAULT_CREATE_BUTTON_LABEL = "Create Ticket"
DEFAULT_CREATE_BUTTON_EMOJI = "🎫"

DEFAULT_CLOSE_BUTTON_LABEL = "Close Ticket"
DEFAULT_CLOSE_BUTTON_EMOJI = "🔒"

DEFAULT_TICKET_NAME = "ticket-{username}"

DEFAULT_WELCOME_MESSAGE = (
    "こんにちは、{user}！\n\n"
    "チケットを作成していただきありがとうございます！\n"
    "至急スタッフが対応いたしますので、"
    "ご要件を記入した上でしばらくお待ちください！\n\n"
    "また、夜間などは対応ができない可能性がございますので、"
    "あらかじめご了承ください！"
)

DEFAULT_AUTO_REPLY = (
    "📩 **お問い合わせありがとうございます！**\n"
    "ご要件を確認しました。\n"
    "スタッフが対応いたしますので、しばらくお待ちください！"
)

DEFAULT_COLOR = 0x5865F2


# =========================================================
# Utility
# =========================================================

def get_ticket_config(guild_id: int) -> dict:
    config = get_guild_config(guild_id)

    defaults = {
        "ticket_title": DEFAULT_TITLE,
        "ticket_description": DEFAULT_DESCRIPTION,
        "ticket_create_label": DEFAULT_CREATE_BUTTON_LABEL,
        "ticket_create_emoji": DEFAULT_CREATE_BUTTON_EMOJI,
        "ticket_close_label": DEFAULT_CLOSE_BUTTON_LABEL,
        "ticket_close_emoji": DEFAULT_CLOSE_BUTTON_EMOJI,
        "ticket_name": DEFAULT_TICKET_NAME,
        "ticket_welcome": DEFAULT_WELCOME_MESSAGE,
        "ticket_auto_reply": DEFAULT_AUTO_REPLY,
        "ticket_color": DEFAULT_COLOR,
        "ticket_category_id": None,
        "ticket_staff_role_id": None,
        "ticket_panel_channel_id": None,
        "ticket_channels": {}
    }

    for key, value in defaults.items():
        if key not in config:
            config[key] = value

    return config


def safe_channel_name(name: str) -> str:
    name = name.lower()

    name = re.sub(
        r"[^a-z0-9\-_]",
        "-",
        name
    )

    name = re.sub(
        r"-+",
        "-",
        name
    )

    name = name.strip("-")

    if not name:
        name = "ticket"

    return name[:100]


def replace_ticket_variables(
    template: str,
    member: discord.Member
) -> str:

    replacements = {
        "{username}": member.name,
        "{displayname}": member.display_name,
        "{userid}": str(member.id),
        "{user}": member.mention
    }

    result = template

    for key, value in replacements.items():
        result = result.replace(
            key,
            value
        )

    return result


def parse_color(value: str) -> int:
    value = value.strip()

    if value.startswith("#"):
        value = value[1:]

    if value.lower().startswith("0x"):
        value = value[2:]

    if len(value) != 6:
        raise ValueError(
            "Color must contain exactly 6 hexadecimal characters."
        )

    return int(
        value,
        16
    )


def make_embed_color(config: dict) -> discord.Color:
    try:
        return discord.Color(
            int(
                config.get(
                    "ticket_color",
                    DEFAULT_COLOR
                )
            )
        )

    except Exception:
        return discord.Color.blurple()


# =========================================================
# Ticket Create Button
# =========================================================

class TicketCreateButton(discord.ui.Button):

    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label=DEFAULT_CREATE_BUTTON_LABEL,
            emoji=DEFAULT_CREATE_BUTTON_EMOJI,
            custom_id="ticket:create"
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

        guild = interaction.guild
        member = interaction.user

        if not isinstance(
            member,
            discord.Member
        ):
            await interaction.response.send_message(
                "❌ Could not retrieve your member information.",
                ephemeral=True
            )
            return

        config = get_ticket_config(
            guild.id
        )

        category_id = config.get(
            "ticket_category_id"
        )

        staff_role_id = config.get(
            "ticket_staff_role_id"
        )

        if not category_id:
            await interaction.response.send_message(
                "❌ Ticket category has not been configured.",
                ephemeral=True
            )
            return

        if not staff_role_id:
            await interaction.response.send_message(
                "❌ Staff role has not been configured.",
                ephemeral=True
            )
            return

        category = guild.get_channel(
            category_id
        )

        if not isinstance(
            category,
            discord.CategoryChannel
        ):
            await interaction.response.send_message(
                "❌ The configured ticket category could not be found.",
                ephemeral=True
            )
            return

        staff_role = guild.get_role(
            staff_role_id
        )

        if staff_role is None:
            await interaction.response.send_message(
                "❌ The configured staff role could not be found.",
                ephemeral=True
            )
            return

        # -------------------------------------------------
        # Check for existing ticket
        # -------------------------------------------------

        ticket_channels = config.get(
            "ticket_channels",
            {}
        )

        if not isinstance(
            ticket_channels,
            dict
        ):
            ticket_channels = {}

        for channel_id, ticket_data in ticket_channels.items():

            if not isinstance(
                ticket_data,
                dict
            ):
                continue

            owner_id = ticket_data.get(
                "owner_id"
            )

            if owner_id != member.id:
                continue

            existing_channel = guild.get_channel(
                int(channel_id)
            )

            if existing_channel is not None:
                await interaction.response.send_message(
                    "❌ You already have an open ticket:\n"
                    f"{existing_channel.mention}",
                    ephemeral=True
                )
                return

        # -------------------------------------------------
        # Bot permissions
        # -------------------------------------------------

        bot_member = guild.me

        if bot_member is None:
            await interaction.response.send_message(
                "❌ Could not retrieve the bot information.",
                ephemeral=True
            )
            return

        # -------------------------------------------------
        # Channel name
        # -------------------------------------------------

        name_template = config.get(
            "ticket_name",
            DEFAULT_TICKET_NAME
        )

        channel_name = replace_ticket_variables(
            name_template,
            member
        )

        channel_name = safe_channel_name(
            channel_name
        )

        # -------------------------------------------------
        # Permission overwrites
        # -------------------------------------------------

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False
            ),

            member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True
            ),

            staff_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True
            ),

            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_messages=True,
                attach_files=True,
                embed_links=True
            )
        }

        # -------------------------------------------------
        # Create channel
        # -------------------------------------------------

        try:

            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"Ticket created by {member}"
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to create ticket channels.",
                ephemeral=True
            )
            return

        except discord.HTTPException as e:
            logger.exception(
                "Failed to create ticket channel: %s",
                e
            )

            await interaction.response.send_message(
                "❌ Failed to create the ticket.",
                ephemeral=True
            )
            return

        # -------------------------------------------------
        # Save ticket information
        # -------------------------------------------------

        ticket_channels[str(channel.id)] = {
            "owner_id": member.id,
            "staff_role_id": staff_role.id,
            "replied": False
        }

        set_guild_value(
            guild.id,
            "ticket_channels",
            ticket_channels
        )

        # -------------------------------------------------
        # Welcome message
        # -------------------------------------------------

        welcome_template = config.get(
            "ticket_welcome",
            DEFAULT_WELCOME_MESSAGE
        )

        welcome_message = replace_ticket_variables(
            welcome_template,
            member
        )

        # -------------------------------------------------
        # Ticket embed
        # -------------------------------------------------

        embed = discord.Embed(
            title="🎫 Ticket",
            description=welcome_message,
            color=make_embed_color(config)
        )

        embed.set_footer(
            text=f"{guild.name} • Support"
        )

        try:

            await channel.send(
                content=staff_role.mention,
                embed=embed,
                view=TicketCloseView(),
                allowed_mentions=discord.AllowedMentions(
                    roles=True
                )
            )

        except Exception:
            logger.exception(
                "Failed to send initial ticket message."
            )

        await interaction.response.send_message(
            f"✅ Your ticket has been created!\n"
            f"{channel.mention}",
            ephemeral=True
        )


# =========================================================
# Ticket Panel View
# =========================================================

class TicketPanelView(discord.ui.View):

    def __init__(self):
        super().__init__(
            timeout=None
        )

        self.add_item(
            TicketCreateButton()
        )


# =========================================================
# Ticket Close Button
# =========================================================

class TicketCloseButton(discord.ui.Button):

    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.danger,
            label=DEFAULT_CLOSE_BUTTON_LABEL,
            emoji=DEFAULT_CLOSE_BUTTON_EMOJI,
            custom_id="ticket:close"
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

        config = get_ticket_config(
            interaction.guild.id
        )

        staff_role_id = config.get(
            "ticket_staff_role_id"
        )

        if not staff_role_id:
            await interaction.response.send_message(
                "❌ Staff role has not been configured.",
                ephemeral=True
            )
            return

        staff_role = interaction.guild.get_role(
            staff_role_id
        )

        if staff_role is None:
            await interaction.response.send_message(
                "❌ The configured staff role could not be found.",
                ephemeral=True
            )
            return

        member = interaction.user

        if not isinstance(
            member,
            discord.Member
        ):
            await interaction.response.send_message(
                "❌ Could not retrieve your member information.",
                ephemeral=True
            )
            return

        # Staff only
        if staff_role not in member.roles:

            await interaction.response.send_message(
                "❌ Only staff members can close tickets.",
                ephemeral=True
            )
            return

        channel = interaction.channel

        if not isinstance(
            channel,
            discord.TextChannel
        ):
            await interaction.response.send_message(
                "❌ This is not a ticket channel.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "🔒 Closing this ticket...",
            ephemeral=True
        )

        # Remove from saved ticket list
        ticket_channels = config.get(
            "ticket_channels",
            {}
        )

        if not isinstance(
            ticket_channels,
            dict
        ):
            ticket_channels = {}

        ticket_channels.pop(
            str(channel.id),
            None
        )

        set_guild_value(
            interaction.guild.id,
            "ticket_channels",
            ticket_channels
        )

        try:

            await channel.delete(
                reason=f"Ticket closed by {member}"
            )

        except discord.Forbidden:
            logger.exception(
                "Could not delete ticket channel."
            )

        except discord.HTTPException:
            logger.exception(
                "Discord error while deleting ticket."
            )


# =========================================================
# Ticket Close View
# =========================================================

class TicketCloseView(discord.ui.View):

    def __init__(self):
        super().__init__(
            timeout=None
        )

        self.add_item(
            TicketCloseButton()
        )


# =========================================================
# Ticket Edit Modal
# =========================================================

class TicketEditModal(
    discord.ui.Modal,
    title="Edit Ticket Settings"
):

    title_text = discord.ui.TextInput(
        label="Panel Title",
        placeholder="PVPBattles Support",
        required=True,
        max_length=256
    )

    description = discord.ui.TextInput(
        label="Panel Description",
        style=discord.TextStyle.paragraph,
        placeholder="Describe your support system.",
        required=True,
        max_length=4000
    )

    create_label = discord.ui.TextInput(
        label="Create Button Name",
        placeholder="Create Ticket",
        required=True,
        max_length=80
    )

    create_emoji = discord.ui.TextInput(
        label="Create Button Emoji",
        placeholder="🎫",
        required=True,
        max_length=20
    )

    ticket_name = discord.ui.TextInput(
        label="Ticket Channel Name",
        placeholder="ticket-{username}",
        required=True,
        max_length=100
    )

    def __init__(
        self,
        guild_id: int
    ):
        super().__init__()

        self.guild_id = guild_id

        config = get_ticket_config(
            guild_id
        )

        self.title_text.default = config.get(
            "ticket_title",
            DEFAULT_TITLE
        )

        self.description.default = config.get(
            "ticket_description",
            DEFAULT_DESCRIPTION
        )

        self.create_label.default = config.get(
            "ticket_create_label",
            DEFAULT_CREATE_BUTTON_LABEL
        )

        self.create_emoji.default = config.get(
            "ticket_create_emoji",
            DEFAULT_CREATE_BUTTON_EMOJI
        )

        self.ticket_name.default = config.get(
            "ticket_name",
            DEFAULT_TICKET_NAME
        )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        config = get_ticket_config(
            self.guild_id
        )

        set_guild_value(
            self.guild_id,
            "ticket_title",
            self.title_text.value
        )

        set_guild_value(
            self.guild_id,
            "ticket_description",
            self.description.value
        )

        set_guild_value(
            self.guild_id,
            "ticket_create_label",
            self.create_label.value
        )

        set_guild_value(
            self.guild_id,
            "ticket_create_emoji",
            self.create_emoji.value
        )

        set_guild_value(
            self.guild_id,
            "ticket_name",
            self.ticket_name.value
        )

        await interaction.response.send_message(
            "✅ Ticket settings have been saved!\n\n"
            "Use `/ticket-setup` again to send a new panel.",
            ephemeral=True
        )


# =========================================================
# Ticket Cog
# =========================================================

class Ticket(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot
    ):
        self.bot = bot

    # =====================================================
    # /ticket-setup
    # =====================================================

    @app_commands.command(
        name="ticket-setup",
        description="Create the ticket panel."
    )
    @app_commands.describe(
        channel="The channel where the ticket panel will be sent."
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def ticket_setup(
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

        config = get_ticket_config(
            interaction.guild.id
        )

        if not config.get(
            "ticket_category_id"
        ):
            await interaction.response.send_message(
                "❌ Ticket category has not been configured.\n"
                "Use `/ticket-edit` first.",
                ephemeral=True
            )
            return

        if not config.get(
            "ticket_staff_role_id"
        ):
            await interaction.response.send_message(
                "❌ Staff role has not been configured.\n"
      
