import re

import discord
from discord import app_commands
from discord.ext import commands

from storage import get_guild_config, set_guild_value


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


def get_config(guild_id: int) -> dict:
    config = get_guild_config(guild_id)

    for key, value in DEFAULTS.items():
        if key not in config:
            config[key] = value

    return config


def clean_emoji(emoji: str) -> str:
    if not emoji:
        return ""
    return emoji.replace("\ufe0f", "")


def parse_color(value: str) -> discord.Color:
    if not value:
        return discord.Color.blurple()

    value = value.strip().replace("#", "")

    try:
        return discord.Color(int(value, 16))
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
    name = replace_variables(pattern, member).lower()

    name = re.sub(
        r"[^a-z0-9_-]",
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


def get_staff_role(
    guild: discord.Guild,
    config: dict
):
    role_id = config.get("ticket_staff_role_id")

    if not role_id:
        return None

    try:
        return guild.get_role(int(role_id))
    except (TypeError, ValueError):
        return None


def is_staff(
    member: discord.Member,
    role: discord.Role | None
) -> bool:
    if role is None:
        return False

    return role in member.roles


class TicketCreateButton(discord.ui.Button):

    def __init__(self):
        super().__init__(
            label=DEFAULTS["ticket_create_name"],
            emoji=clean_emoji(
                DEFAULTS["ticket_create_emoji"]
            ),
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

        member = interaction.user

        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "❌ Failed to identify your account.",
                ephemeral=True
            )
            return

        guild = interaction.guild
        config = get_config(guild.id)

        category_id = config.get("ticket_category_id")
        staff_role = get_staff_role(guild, config)

        if not category_id or staff_role is None:
            await interaction.response.send_message(
                "❌ The ticket system has not been configured yet.",
                ephemeral=True
            )
            return

        try:
            category = guild.get_channel(int(category_id))
        except (TypeError, ValueError):
            category = None

        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message(
                "❌ The configured ticket category could not be found.",
                ephemeral=True
            )
            return

        for channel in guild.text_channels:
            if channel.topic == f"ticket_owner:{member.id}":
                await interaction.response.send_message(
                    f"❌ You already have an open ticket: {channel.mention}",
                    ephemeral=True
                )
                return

        bot_member = guild.me

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
        }

        if bot_member is not None:
            overwrites[bot_member] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_messages=True
            )

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

        ticket_channels = config.get("ticket_channels", {})

        if not isinstance(ticket_channels, dict):
            ticket_channels = {}

        ticket_channels[str(channel.id)] = {
            "owner_id": member.id,
            "first_reply_sent": False
        }

        set_guild_value(
            guild.id,
            "ticket_channels",
            ticket_channels
        )

        await interaction.response.send_message(
            f"🎫 Ticket created: {channel.mention}",
            ephemeral=True
        )

        await channel.send(
            staff_role.mention,
            allowed_mentions=discord.AllowedMentions(
                roles=True
            )
        )

        welcome = config.get(
            "ticket_welcome",
            DEFAULTS["ticket_welcome"]
        )

        welcome = replace_variables(
            welcome,
            member
        )

        await channel.send(welcome)

        embed = discord.Embed(
            title="🎫 Ticket",
            description=(
                "Ticket Creator\n"
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


class TicketPanelView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketCreateButton())


class TicketCloseButton(discord.ui.Button):

    def __init__(self):
        super().__init__(
            label=DEFAULTS["ticket_close_name"],
            emoji=clean_emoji(
                DEFAULTS["ticket_close_emoji"]
            ),
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

        member = interaction.user

        if not isinstance(member, discord.Member):
            return

        config = get_config(interaction.guild.id)
        staff_role = get_staff_role(
            interaction.guild,
            config
        )

        if not is_staff(member, staff_role):
            await interaction.response.send_message(
                "❌ Only staff members can close this ticket.",
                ephemeral=True
            )
            return

        channel = interaction.channel

        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "❌ This is not a ticket channel.",
                ephemeral=True
            )
            return

        if not channel.topic or not channel.topic.startswith(
            "ticket_owner:"
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
                reason=f"Ticket closed by {member}"
            )
        except discord.HTTPException:
            pass


class TicketCloseView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketCloseButton())


class TicketSettingsModal(discord.ui.Modal):

    def __init__(
        self,
        guild_id: int
    ):
        super().__init__(title="Ticket Settings")

        self.guild_id = guild_id
        config = get_config(guild_id)

        self.panel_title = discord.ui.TextInput(
            label="Panel Title",
            default=config.get(
                "ticket_panel_title",
                DEFAULTS["ticket_panel_title"]
            ),
            max_length=256,
            required=True
        )

        self.panel_description = discord.ui.TextInput(
            label="Panel Description",
            default=config.get(
                "ticket_panel_description",
                DEFAULTS["ticket_panel_description"]
            ),
            style=discord.TextStyle.paragraph,
            max_length=4000,
            required=True
        )

        self.ticket_name = discord.ui.TextInput(
            label="Ticket Channel Name",
            default=config.get(
                "ticket_name",
                DEFAULTS["ticket_name"]
            ),
            placeholder="ticket-{username}",
            max_length=100,
            required=True
        )

        self.welcome = discord.ui.TextInput(
            label="Welcome Message",
            default=config.get(
                "ticket_welcome",
                DEFAULTS["ticket_welcome"]
            ),
            style=discord.TextStyle.paragraph,
            max_length=4000,
            required=True
        )

        self.first_reply = discord.ui.TextInput(
            label="First Requirement Reply",
            default=config.get(
                "ticket_first_reply",
                DEFAULTS["ticket_first_reply"]
            ),
            style=discord.TextStyle.paragraph,
            max_length=4000,
            required=True
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
        guild_id = self.guild_id

        set_guild_value(
            guild_id,
            "ticket_panel_title",
            self.panel_title.value
        )

        set_guild_value(
            guild_id,
            "ticket_panel_description",
            self.panel_description.value
        )

        set_guild_value(
            guild_id,
            "ticket_name",
            self.ticket_name.value
        )

        set_guild_value(
            guild_id,
            "ticket_welcome",
            self.welcome.value
        )

        set_guild_value(
            guild_id,
            "ticket_first_reply",
            self.first_reply.value
        )

        await interaction.response.send_message(
            "✅ Ticket settings saved.",
            ephemeral=True
        )


class Ticket(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot
    ):
        self.bot = bot

    @app_commands.command(
        name="ticket-setup",
        description="Create the ticket panel."
    )
    @app_commands.describe(
        channel="Channel where the ticket panel will be sent."
    )
    async def ticket_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel
    ):
        if interaction.guild is None:
            return

        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "❌ You need Manage Server permission.",
                ephemeral=True
            )
            return

        config = get_config(interaction.guild.id)

        embed = discord.Embed(
            title=config.get(
                "ticket_panel_title",
                DEFAULTS["ticket_panel_title"]
            ),
            description=config.get(
                "ticket_panel_description",
                DEFAULTS["ticket_panel_description"]
            ),
            color=parse_color(
                config.get(
                    "ticket_color",
                    DEFAULTS["ticket_color"]
                )
            )
        )

        embed.set_footer(text="PVPBattles Support")

        try:
            await channel.send(
                embed=embed,
                view=TicketPanelView()
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to send messages there.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ Ticket panel sent to {channel.mention}.",
            ephemeral=True
        )

    @app_commands.command(
        name="ticket-edit",
        description="Configure the ticket system."
    )
    @app_commands.describe(
        category="Category where tickets will be created.",
        staff_role="Staff role."
    )
    async def ticket_edit(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel,
        staff_role: discord.Role
    ):
        if interaction.guild is None:
            return

        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "❌ You need Manage Server permission.",
                ephemeral=True
            )
            return

        set_guild_value(
            interaction.guild.id,
            "ticket_category_id",
            category.id
        )

        set_guild_value(
            interaction.guild.id,
            "ticket_staff_role_id",
            staff_role.id
        )

        await interaction.response.send_modal(
            TicketSettingsModal(
                interaction.guild.id
            )
        )

    @app_commands.command(
        name="ticket-message",
        description="Edit ticket messages."
    )
    async def ticket_message(
        self,
        interaction: discord.Interaction
    ):
        if interaction.guild is None:
            return

        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "❌ You need Manage Server permission.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            TicketSettingsModal(
                interaction.guild.id
            )
        )

    @app_commands.command(
        name="ticket-color",
        description="Change the ticket embed color."
    )
    @app_commands.describe(
        color="Hex color, for example #5865F2"
    )
    async def ticket_color(
        self,
        interaction: discord.Interaction,
        color: str
    ):
        if interaction.guild is None:
            return

        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "❌ You need Manage Server permission.",
                ephemeral=True
            )
            return

        value = color.strip()

        if value.startswith("#"):
            value = value[1:]

        if not re.fullmatch(
            r"[0-9a-fA-F]{6}",
            value
        ):
            await interaction.response.send_message(
                "❌ Invalid color. Example: `#5865F2`",
                ephemeral=True
            )
            return

        set_guild_value(
            interaction.guild.id,
            "ticket_color",
            f"#{value}"
        )

        await interaction.response.send_message(
            f"✅ Ticket color changed to `#{value}`.",
            ephemeral=True
        )

    @app_commands.command(
        name="ticket-disable",
        description="Disable the ticket system."
    )
    async def ticket_disable(
        self,
        interaction: discord.Interaction
    ):
        if interaction.guild is None:
            return

        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "❌ You need Manage Server permission.",
                ephemeral=True
            )
            return

        set_guild_value(
            interaction.guild.id,
            "ticket_category_id",
            None
        )

        set_guild_value(
            interaction.guild.id,
            "ticket_staff_role_id",
            None
        )

        await interaction.response.send_message(
            "✅ Ticket system has been disabled.",
            ephemeral=True
        )

    @commands.Cog.listener()
    async def on_message(
        self,
        message: discord.Message
    ):
        if message.author.bot:
            return

        if message.guild is None:
            return

        if not isinstance(
            message.channel,
            discord.TextChannel
        ):
            return

        config = get_config(message.guild.id)

        ticket_channels = config.get(
            "ticket_channels",
            {}
        )

        if not isinstance(ticket_channels, dict):
            return

        ticket_data = ticket_channels.get(
            str(message.channel.id)
        )

        if not isinstance(ticket_data, dict):
            return

        owner_id = ticket_data.get("owner_id")

        if message.author.id != owner_id:
            return

        if ticket_data.get(
            "first_reply_sent",
            False
        ):
            return

        ticket_data["first_reply_sent"] = True

        ticket_channels[str(message.channel.id)] = ticket_data

        set_guild_value(
            message.guild.id,
            "ticket_channels",
            ticket_channels
        )

        reply = config.get(
            "ticket_first_reply",
            DEFAULTS["ticket_first_reply"]
        )

        reply = replace_variables(
            reply,
            message.author
        )

        await message.channel.send(reply)


async def setup(
    bot: commands.Bot
):
    await bot.add_cog(
        Ticket(bot)
    )
