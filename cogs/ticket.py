import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from storage import get_guild_config, set_guild_value


logger = logging.getLogger("discord_bot")


# =========================================================
# Defaults
# =========================================================

DEFAULT_TITLE = "🎫 PVPBattles Support"

DEFAULT_DESCRIPTION = (
    "Need help?\n"
    "Click the button below to create a ticket."
)

DEFAULT_CREATE_LABEL = "Create Ticket"
DEFAULT_CREATE_EMOJI = "🎫"

DEFAULT_CLOSE_LABEL = "Close Ticket"
DEFAULT_CLOSE_EMOJI = "🔒"

DEFAULT_TICKET_NAME = "ticket-{username}"

DEFAULT_WELCOME = (
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
# Config
# =========================================================

def get_ticket_config(guild_id: int) -> dict:
    config = get_guild_config(guild_id)

    defaults = {
        "ticket_title": DEFAULT_TITLE,
        "ticket_description": DEFAULT_DESCRIPTION,
        "ticket_create_label": DEFAULT_CREATE_LABEL,
        "ticket_create_emoji": DEFAULT_CREATE_EMOJI,
        "ticket_close_label": DEFAULT_CLOSE_LABEL,
        "ticket_close_emoji": DEFAULT_CLOSE_EMOJI,
        "ticket_name": DEFAULT_TICKET_NAME,
        "ticket_welcome": DEFAULT_WELCOME,
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


# =========================================================
# Utility
# =========================================================

def clean_emoji(value: str, fallback: str) -> str:
    """
    Discordで問題になりやすいVariation Selectorを除去。
    空の場合はfallback。
    """
    value = value.strip()
    value = value.replace("\ufe0f", "")

    if not value:
        return fallback

    return value[:10]


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

    if not re.fullmatch(r"[0-9a-fA-F]{6}", value):
        raise ValueError(
            "Invalid hexadecimal color."
        )

    return int(value, 16)


def get_color(config: dict) -> discord.Color:
    try:
        return discord.Color(
            int(config.get("ticket_color", DEFAULT_COLOR))
        )
    except Exception:
        return discord.Color.blurple()


def replace_variables(
    text: str,
    member: discord.Member
) -> str:

    replacements = {
        "{user}": member.mention,
        "{username}": member.name,
        "{displayname}": member.display_name,
        "{userid}": str(member.id)
    }

    result = text

    for key, value in replacements.items():
        result = result.replace(key, value)

    return result


def make_ticket_name(
    template: str,
    member: discord.Member
) -> str:

    name = replace_variables(
        template,
        member
    )

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
        name = f"ticket-{member.id}"

    return name[:100]


def is_staff(
    member: discord.Member,
    role: discord.Role
) -> bool:
    return role in member.roles


# =========================================================
# Ticket Create Button
# =========================================================

class TicketCreateButton(discord.ui.Button):

    def __init__(
        self,
        label: str = DEFAULT_CREATE_LABEL,
        emoji: str = DEFAULT_CREATE_EMOJI
    ):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label=label[:80],
            emoji=clean_emoji(
                emoji,
                DEFAULT_CREATE_EMOJI
            ),
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

        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "❌ Could not retrieve your member information.",
                ephemeral=True
            )
            return

        config = get_ticket_config(guild.id)

        category_id = config.get(
            "ticket_category_id"
        )

        staff_role_id = config.get(
            "ticket_staff_role_id"
        )

        if not category_id or not staff_role_id:
            await interaction.response.send_message(
                "❌ The ticket system has not been configured yet.",
                ephemeral=True
            )
            return

        category = guild.get_channel(
            int(category_id)
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
            int(staff_role_id)
        )

        if staff_role is None:
            await interaction.response.send_message(
                "❌ The configured staff role could not be found.",
                ephemeral=True
            )
            return

        # -------------------------------------------------
        # Check existing ticket
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

        for channel_id, data in list(
            ticket_channels.items()
        ):

            if not isinstance(data, dict):
                continue

            if data.get("owner_id") != member.id:
                continue

            existing = guild.get_channel(
                int(channel_id)
            )

            if existing is not None:
                await interaction.response.send_message(
                    f"❌ You already have an open ticket:\n"
                    f"{existing.mention}",
                    ephemeral=True
                )
                return

            # Remove deleted channel from config.
            ticket_channels.pop(
                channel_id,
                None
            )

        set_guild_value(
            guild.id,
            "ticket_channels",
            ticket_channels
        )

        # -------------------------------------------------
        # Bot member
        # -------------------------------------------------

        bot_member = guild.me

        if bot_member is None:
            await interaction.response.send_message(
                "❌ Could not retrieve the bot member.",
                ephemeral=True
            )
            return

        # -------------------------------------------------
        # Channel name
        # -------------------------------------------------

        template = config.get(
            "ticket_name",
            DEFAULT_TICKET_NAME
        )

        channel_name = make_ticket_name(
            template,
            member
        )

        # -------------------------------------------------
        # Permissions
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

        except discord.HTTPException as error:
            logger.exception(
                "Failed to create ticket channel: %s",
                error
            )

            await interaction.response.send_message(
                "❌ Failed to create the ticket.",
                ephemeral=True
            )
            return

        # -------------------------------------------------
        # Save ticket
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

        welcome = config.get(
            "ticket_welcome",
            DEFAULT_WELCOME
        )

        welcome = replace_variables(
            welcome,
            member
        )

        # -------------------------------------------------
        # Ticket Embed
        # -------------------------------------------------

        embed = discord.Embed(
            title="🎫 Ticket",
            description=welcome,
            color=get_color(config)
        )

        embed.set_footer(
            text=f"{guild.name} • Support"
        )

        close_view = TicketCloseView(
            label=config.get(
                "ticket_close_label",
                DEFAULT_CLOSE_LABEL
            ),
            emoji=config.get(
                "ticket_close_emoji",
                DEFAULT_CLOSE_EMOJI
            )
        )

        try:
            await channel.send(
                content=staff_role.mention,
                embed=embed,
                view=close_view,
                allowed_mentions=discord.AllowedMentions(
                    roles=True
                )
            )

        except discord.HTTPException as error:
            logger.exception(
                "Failed to send ticket message: %s",
                error
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

    def __init__(
        self,
        label: str = DEFAULT_CREATE_LABEL,
        emoji: str = DEFAULT_CREATE_EMOJI
    ):
        super().__init__(
            timeout=None
        )

        self.add_item(
            TicketCreateButton(
                label=label,
                emoji=emoji
            )
        )


# =========================================================
# Ticket Close Button
# =========================================================

class TicketCloseButton(discord.ui.Button):

    def __init__(
        self,
        label: str = DEFAULT_CLOSE_LABEL,
        emoji: str = DEFAULT_CLOSE_EMOJI
    ):
        super().__init__(
            style=discord.ButtonStyle.danger,
            label=label[:80],
            emoji=clean_emoji(
                emoji,
                DEFAULT_CLOSE_EMOJI
            ),
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

        if not isinstance(
            interaction.user,
            discord.Member
        ):
            await interaction.response.send_message(
                "❌ Could not retrieve your member information.",
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

        config = get_ticket_config(
            interaction.guild.id
        )

        ticket_channels = config.get(
            "ticket_channels",
            {}
        )

        if not isinstance(
            ticket_channels,
            dict
        ):
            ticket_channels = {}

        ticket_data = ticket_channels.get(
            str(channel.id)
        )

        if not isinstance(
            ticket_data,
            dict
        ):
            await interaction.response.send_message(
                "❌ This channel is not registered as a ticket.",
                ephemeral=True
            )
            return

        staff_role_id = ticket_data.get(
            "staff_role_id"
        )

        if not staff_role_id:
            await interaction.response.send_message(
                "❌ Staff role information is missing.",
                ephemeral=True
            )
            return

        staff_role = interaction.guild.get_role(
            int(staff_role_id)
        )

        if staff_role is None:
            await interaction.response.send_message(
                "❌ The staff role no longer exists.",
                ephemeral=True
            )
            return

        # -------------------------------------------------
        # Staff only
        # -------------------------------------------------

        if not is_staff(
            interaction.user,
            staff_role
        ):
            await interaction.response.send_message(
                "❌ Only staff members can close this ticket.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "🔒 Closing this ticket...",
            ephemeral=True
        )

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
                reason=f"Ticket closed by {interaction.user}"
            )

        except discord.Forbidden:
            logger.exception(
                "Missing permission to delete ticket channel."
            )

        except discord.HTTPException:
            logger.exception(
                "Failed to delete ticket channel."
            )


# =========================================================
# Ticket Close View
# =========================================================

class TicketCloseView(discord.ui.View):

    def __init__(
        self,
        label: str = DEFAULT_CLOSE_LABEL,
        emoji: str = DEFAULT_CLOSE_EMOJI
    ):
        super().__init__(
            timeout=None
        )

        self.add_item(
            TicketCloseButton(
                label=label,
                emoji=emoji
            )
        )


# =========================================================
# Panel Edit Modal
# =========================================================

class TicketEditModal(discord.ui.Modal):

    def __init__(
        self,
        guild_id: int
    ):
        super().__init__(
            title="Edit Ticket Panel"
        )

        self.guild_id = guild_id

        config = get_ticket_config(
            guild_id
        )

        self.panel_title = discord.ui.TextInput(
            label="Panel Title",
            default=config.get(
                "ticket_title",
                DEFAULT_TITLE
            ),
            required=True,
            max_length=256
        )

        self.panel_description = discord.ui.TextInput(
            label="Panel Description",
            default=config.get(
                "ticket_description",
                DEFAULT_DESCRIPTION
            ),
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=4000
        )

        self.create_label = discord.ui.TextInput(
            label="Create Button Name",
            default=config.get(
                "ticket_create_label",
                DEFAULT_CREATE_LABEL
            ),
            required=True,
            max_length=80
        )

        self.create_emoji = discord.ui.TextInput(
            label="Create Button Emoji",
            default=config.get(
                "ticket_create_emoji",
                DEFAULT_CREATE_EMOJI
            ),
            required=True,
            max_length=20
        )

        self.ticket_name = discord.ui.TextInput(
            label="Ticket Channel Name",
            default=config.get(
                "ticket_name",
                DEFAULT_TICKET_NAME
            ),
            required=True,
            max_length=100
        )

        self.add_item(
            self.panel_title
        )

        self.add_item(
            self.panel_description
        )

        self.add_item(
            self.create_label
        )

        self.add_item(
            self.create_emoji
        )

        self.add_item(
            self.ticket_name
        )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        set_guild_value(
            self.guild_id,
            "ticket_title",
            self.panel_title.value
        )

        set_guild_value(
            self.guild_id,
            "ticket_description",
            self.panel_description.value
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

     
