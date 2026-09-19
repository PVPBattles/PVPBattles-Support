import re
import discord

from discord import app_commands
from discord.ext import commands

from storage import get_guild_config, set_guild_value


# =========================================================
# Default Settings
# =========================================================

DEFAULTS = {
    "ticket_panel_title": "🎫 PVPBattles Support",
    "ticket_panel_description": (
        "Need help?\n"
        "Click the button below to create a ticket."
    ),
    "ticket_create_name": "Create Ticket",
    "ticket_create_emoji": "🎫",
    "ticket_name": "ticket-{username}",
    "ticket_color": "#5865F2",
    "ticket_close_name": "Close Ticket",
    "ticket_close_emoji": "🔒",
    "ticket_welcome": (
        "こんにちは、{user}！\n\n"
        "チケットを作成していただきありがとうございます！\n"
        "至急スタッフが対応いたしますので、ご要件を記入した上で"
        "しばらくお待ちください！\n\n"
        "また、夜間などは対応ができない可能性がございますので、"
        "あらかじめご了承ください！"
    ),
    "ticket_first_reply": (
        "ご要件を確認いたしました！\n"
        "スタッフが対応いたしますので、しばらくお待ちください。"
    ),
}


# =========================================================
# Utility
# =========================================================

def get_config(guild_id: int) -> dict:
    config = get_guild_config(guild_id)

    for key, value in DEFAULTS.items():
        config.setdefault(key, value)

    return config


def clean_emoji(emoji: str) -> str:
    if not emoji:
        return ""

    # Remove variation selector
    return emoji.replace("\ufe0f", "")


def parse_color(value: str) -> discord.Color:
    value = value.strip()

    if value.startswith("#"):
        value = value[1:]

    try:
        number = int(value, 16)
        return discord.Color(number)
    except ValueError:
        return discord.Color.blurple()


def replace_variables(
    text: str,
    member: discord.Member
) -> str:

    replacements = {
        "{username}": member.name,
        "{displayname}": member.display_name,
        "{userid}": str(member.id),
        "{user}": member.mention,
    }

    for key, value in replacements.items():
        text = text.replace(key, value)

    return text


def make_ticket_name(
    pattern: str,
    member: discord.Member
) -> str:

    name = replace_variables(pattern, member)

    # Discord channel names should be lowercase
    name = name.lower()

    # Keep only safe characters
    name = re.sub(r"[^a-z0-9_-]", "-", name)

    # Prevent repeated hyphens
    name = re.sub(r"-+", "-", name)

    # Discord channel name limit
    name = name[:100]

    if not name:
        name = f"ticket-{member.id}"

    return name


def is_staff(
    member: discord.Member,
    role: discord.Role | None
) -> bool:

    if role is None:
        return False

    return role in member.roles


# =========================================================
# Ticket Create Button
# =========================================================

class TicketCreateButton(discord.ui.Button):

    def __init__(self):
        super().__init__(
            label=DEFAULTS["ticket_create_name"],
            emoji=clean_emoji(DEFAULTS["ticket_create_emoji"]),
            style=discord.ButtonStyle.primary,
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
                "❌ Failed to identify your account.",
                ephemeral=True
            )
            return

        config = get_config(guild.id)

        category_id = config.get("ticket_category_id")
        staff_role_id = config.get("ticket_staff_role_id")

        if not category_id or not staff_role_id:
            await interaction.response.send_message(
                "❌ Ticket system has not been configured yet.",
                ephemeral=True
            )
            return

        category = guild.get_channel(int(category_id))
        staff_role = guild.get_role(int(staff_role_id))

        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message(
                "❌ The configured ticket category could not be found.",
                ephemeral=True
            )
            return

        if staff_role is None:
            await interaction.response.send_message(
                "❌ The configured staff role could not be found.",
                ephemeral=True
            )
            return

        # -------------------------------------------------
        # Prevent duplicate tickets
        # -------------------------------------------------

        existing_ticket = None

        for channel in guild.text_channels:
            if not channel.topic:
                continue

            if channel.topic == f"ticket_owner:{member.id}":
                existing_ticket = channel
                break

        if existing_ticket is not None:
            await interaction.response.send_message(
                f"❌ You already have an open ticket: {existing_ticket.mention}",
                ephemeral=True
            )
            return

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
                manage_messages=True,
                attach_files=True,
                embed_links=True
            ),

            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_messages=True
            )
        }

        channel_name = make_ticket_name(
            config.get(
                "ticket_name",
                DEFAULTS["ticket_name"]
            ),
            member
        )

        try:
            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                topic=f"ticket_owner:{member.id}",
                overwrites=overwrites,
                reason=f"Ticket created by {member}"
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to create ticket channels.",
                ephemeral=True
            )
            return

        except discord.HTTPException:
            await interaction.response.send_message(
                "❌ Failed to create the ticket.",
                ephemeral=True
            )
            return

        # -------------------------------------------------
        # Save ticket information
        # -------------------------------------------------

        ticket_channels = config.get("ticket_channels", {})

        if not isinstance(ticket_channels, dict):
            ticket_channels = {}

        ticket_channels[str(channel.id)] = {
            "owner_id": member.id,
            "created_at": discord.utils.utcnow().isoformat()
        }

        set_guild_value(
            guild.id,
            "ticket_channels",
            ticket_channels
        )

        # -------------------------------------------------
        # Interaction response
        # -------------------------------------------------

        await interaction.response.send_message(
            f"🎫 Ticket created: {channel.mention}",
            ephemeral=True
        )

        # -------------------------------------------------
        # Staff mention
        # -------------------------------------------------

        await channel.send(
            staff_role.mention,
            allowed_mentions=discord.AllowedMentions(
                roles=True
            )
        )

        # -------------------------------------------------
        # Welcome message
        # -------------------------------------------------

        welcome_text = config.get(
            "ticket_welcome",
            DEFAULTS["ticket_welcome"]
        )

        welcome_text = replace_variables(
            welcome_text,
            member
        )

        await channel.send(welcome_text)

        # -------------------------------------------------
        # Ticket embed
        # -------------------------------------------------

        embed = discord.Embed(
            title="🎫 Ticket",
            description=(
                f"**Ticket Creator**\n"
                f"{member.mention}\n\n"
                "スタッフが対応するまでしばらくお待ちください。"
            ),
            color=parse_color(
                config.get(
                    "ticket_color",
                    DEFAULTS["ticket_color"]
                )
            )
        )

        embed.set_footer(
            text="PVPBattles Support"
        )

        await channel.send(
            embed=embed,
            view=TicketCloseView()
        )


# =========================================================
# Ticket Panel View
# =========================================================

class TicketPanelView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

        self.add_item(
            TicketCreateButton()
        )


# =========================================================
# Ticket Close Button
# =========================================================

class TicketCloseButton(discord.ui.Button):

    def __init__(self):
        super().__init__(
            label=DEFAULTS["ticket_close_name"],
            emoji=clean_emoji(DEFAULTS["ticket_close_emoji"]),
            style=discord.ButtonStyle.danger,
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

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "❌ Failed to identify your account.",
                ephemeral=True
            )
            return

        config = get_config(
            interaction.guild.id
        )

        staff_role_id = config.get(
            "ticket_staff_role_id"
        )

        staff_role = None

        if staff_role_id:
            staff_role = interaction.guild.get_role(
                int(staff_role_id)
            )

        # Creator cannot close
        ticket_owner_id = None

        if interaction.channel is not None:
            topic = getattr(
                interaction.channel,
                "topic",
                None
            )

            if topic and topic.startswith(
                "ticket_owner:"
            ):
                try:
                    ticket_owner_id = int(
                        topic.split(":", 1)[1]
                    )
                except ValueError:
                    ticket_owner_id = None

        if ticket_owner_id == interaction.user.id:
            await interaction.response.send_message(
                "❌ Only staff members can close this ticket.",
                ephemeral=True
            )
            return

        # Staff check
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

        channel = interaction.channel

        if not isinstance(
            channel,
            discord.TextChannel
        ):
            return

        # Remove from config
        ticket_channels = config.get(
            "ticket_channels",
            {}
        )

        if isinstance(ticket_channels, dict):
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
                reason=(
                    f"Ticket closed by "
                    f"{interaction.user}"
                )
            )

        except discord.Forbidden:
            pass

        except discord.HTTPException:
            pass


# =========================================================
# Ticket Close View
# =========================================================

class TicketCloseView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

        self.add_item(
            TicketCloseButton()
        )


# =========================================================
# Ticket Edit Modal
# =========================================================

class TicketEditModal(discord.ui.Modal):

    def __init__(
        self,
        config: dict,
        guild_id: int
    ):

        super().__init__(
            title="Ticket Settings"
        )

        self.guild_id = guild_id
        self.config = config

        self.panel_title = discord.ui.TextInput(
            label="Panel Title",
            default=config.get(
                "ticket_panel_title",
                DEFAULTS["ticket_panel_title"]
            ),
            required=True,
            max_length=256
        )

        self.panel_description = discord.ui.TextInput(
            label="Panel Description",
            default=config.get(
                "ticket_panel_description",
                DEFAULTS["ticket_panel_description"]
            ),
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=4000
        )

        self.ticket_name = discord.ui.TextInput(
            label="Ticket Channel Name",
            default=config.get(
                "ticket_name",
                DEFAULTS["ticket_name"]
            ),
            placeholder="ticket-{username}",
            required=True,
            max_length=100
        )

        self.welcome = discord.ui.TextInput(
            label="Welcome Message",
            default=config.get(
                "ticket_welcome",
                DEFAULTS["ticket_welcome"]
            ),
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=4000
        )

        self.first_reply = discord.ui.TextInput(
            label="First Requirement Reply",
            default=config.get(
                "ticket_first_reply",
                DEFAULTS["ticket_first_reply"]
            ),
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=4000
        )

        self.add_item(self.panel_title)
        self.add_item(self.panel_description)
        self.add_item(self.ticket_name)
        self.add_item(self.welcome)
        self.add_item(self.first_reply)

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        set_guild_value(
            self.guild_id,
            "ticket_panel_title",
            self.panel_title.value
        )

        set_guild_value(
            self.guild_id,
            "ticket_panel_description",
            self.panel_description.value
        )

        set_guild_value(
            self.guild_id,
            "ticket_name",
            self.ticket_name.value
        )

        set_guild_value(
            self.guild_id,
            "ticket_welcome",
            self.welcome.value
        )

        set_guild_value(
            self.guild_id,
            "ticket_first_reply",
            self.first_reply.value
        )

        await interaction.response.send_message(
            "✅ Ticket settings have been saved.",
            ephemeral=True
        )


# =========================================================
# Ticket Button Modal
# =========================================================

class TicketButtonModal(discord.ui.Modal):

    def __init__(
        self,
        guild_id: int,
        mode: str
    ):

        super().__init__(
            title="Ticket Button Settings"
        )

        self.guild_id = guild_id
        self.mode = mode

        config = get_config(guild_id)

        if mode == "create":

            self.name = discord.ui.TextInput(
                label="Create Button Name",
                default=config.get(
                    "ticket_create_name",
                    DEFAULTS["ticket_create_name"]
                ),
                required=True,
                max_length=80
            )

            self.emoji = discord.ui.TextInput(
                label="Create Button Emoji",
                default=config.get(
                    "ticket_create_emoji",
                    DEFAULTS["ticket_create_emoji"]
                ),
                required=True,
                max_length=32
            )

        else:

            self.name = discord.ui.TextInput(
                label="Close Button Name",
                default=config.get(
                    "ticket_close_name",
                    DEFAULTS["ticket_close_name"]
                ),
                required=True,
                max_length=80
            )

            self.emoji = discord.ui.TextInput(
                label="Close Button Emoji",
                default=config.get(
                    "ticket_close_emoji",
                    DEFAULTS["ticket_close_emoji"]
                ),
                required=True,
                max_length=32
            )

        self.add_item(self.name)
        self.add_item(self.emoji)

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        emoji = clean_emoji(
            self.emoji.value
        )

        if self.mode == "create":

            set_guild_value(
                self.guild_id,
                "ticket_create_name",
                self.name.value
            )

            set_guild_value(
                self.guild_id,
                "ticket_create_emoji",
                emoji
            )

        else:

            set_guild_value(
                self.guild_id,
                "ticket_close_name",
                self.name.value
            )

            set_guild_value(
                self.guild_id,
                "ticket_close_emoji",
                emoji
            )

        await interaction.response.send_message(
            "✅ Button settings have been saved.",
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

    # -----------------------------------------------------
    # /ticket-setup
    # -----------------------------------------------------

    @app_commands.command(
        name="ticket-setup",
        description="Set up the ticket panel."
    )
    @app
