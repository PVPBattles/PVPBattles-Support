import discord
from discord.ext import commands
from discord import app_commands

from storage import get_guild_config, set_guild_value


TICKET_CREATE_ID = "ticket:create"
TICKET_CLOSE_ID = "ticket:close"


# =========================================================
# Utility
# =========================================================

def sanitize_channel_name(name: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789-_"

    name = name.lower()
    name = name.replace(" ", "-")
    name = "".join(char for char in name if char in allowed)

    return name[:90] or "ticket"


def replace_placeholders(
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


def get_ticket_state(topic: str | None):
    creator_id = None
    first_message_replied = False

    if not topic:
        return creator_id, first_message_replied

    for part in topic.split(";"):

        if part.startswith("ticket_creator:"):

            value = part.split(":", 1)[1]

            if value.isdigit():
                creator_id = int(value)

        elif part == "first_replied:1":
            first_message_replied = True

    return creator_id, first_message_replied


def make_ticket_topic(
    creator_id: int,
    first_replied: bool = False
) -> str:

    return (
        f"ticket_creator:{creator_id};"
        f"first_replied:{1 if first_replied else 0}"
    )


def is_staff(
    member: discord.Member,
    role_ids: list
) -> bool:

    configured_roles = {
        int(role_id)
        for role_id in role_ids
        if str(role_id).isdigit()
    }

    return any(
        role.id in configured_roles
        for role in member.roles
    )


# =========================================================
# Ticket Panel
# =========================================================

class TicketPanelView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

        button = discord.ui.Button(
            label="Create Ticket",
            emoji="🎫",
            style=discord.ButtonStyle.primary,
            custom_id=TICKET_CREATE_ID,
        )

        button.callback = self.create_ticket

        self.add_item(button)

    async def create_ticket(
        self,
        interaction: discord.Interaction
    ):

        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This button can only be used in a server.",
                ephemeral=True,
            )
            return

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "❌ Unable to identify the member.",
                ephemeral=True,
            )
            return

        config = get_guild_config(
            interaction.guild.id
        )

        category_id = config.get(
            "ticket_category_id"
        )

        if not category_id:

            await interaction.response.send_message(
                "❌ Ticket category is not configured.",
                ephemeral=True,
            )

            return

        category = interaction.guild.get_channel(
            int(category_id)
        )

        if not isinstance(
            category,
            discord.CategoryChannel
        ):

            await interaction.response.send_message(
                "❌ The configured ticket category no longer exists.",
                ephemeral=True,
            )

            return

        # -------------------------------------------------
        # Prevent duplicate tickets
        # -------------------------------------------------

        for channel in category.text_channels:

            creator_id, _ = get_ticket_state(
                channel.topic
            )

            if creator_id == interaction.user.id:

                await interaction.response.send_message(
                    f"❌ You already have an open ticket: {channel.mention}",
                    ephemeral=True,
                )

                return

        # -------------------------------------------------
        # Ticket channel name
        # -------------------------------------------------

        ticket_template = config.get(
            "ticket_name",
            "ticket-{username}"
        )

        channel_name = sanitize_channel_name(
            replace_placeholders(
                ticket_template,
                interaction.user
            )
        )

        # -------------------------------------------------
        # Permissions
        # -------------------------------------------------

        overwrites = {

            interaction.guild.default_role:
                discord.PermissionOverwrite(
                    view_channel=False
                ),

            interaction.user:
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    embed_links=True,
                ),
        }

        if interaction.guild.me:

            overwrites[
                interaction.guild.me
            ] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_messages=True,
            )

        # -------------------------------------------------
        # Staff roles
        # -------------------------------------------------

        staff_mentions = []

        staff_role_ids = config.get(
            "ticket_staff_role_ids",
            []
        )

        for role_id in staff_role_ids:

            role = interaction.guild.get_role(
                int(role_id)
            )

            if role:

                overwrites[role] = (
                    discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        attach_files=True,
                        embed_links=True,
                    )
                )

                staff_mentions.append(
                    role.mention
                )

        # -------------------------------------------------
        # Create channel
        # -------------------------------------------------

        await interaction.response.defer(
            ephemeral=True
        )

        try:

            channel = (
                await interaction.guild.create_text_channel(
                    channel_name,
                    category=category,
                    overwrites=overwrites,
                    topic=make_ticket_topic(
                        interaction.user.id
                    ),
                    reason=(
                        f"Ticket created by "
                        f"{interaction.user}"
                    ),
                )
            )

            # -------------------------------------------------
            # Greeting
            # -------------------------------------------------

            greeting = config.get(
                "ticket_greeting",
                (
                    "こんにちは、{user}！\n\n"
                    "チケットを作成していただきありがとうございます！\n"
                    "至急スタッフが対応いたしますので、"
                    "ご要件を記入した上でしばらくお待ちください！\n\n"
                    "また、夜間などは対応ができない可能性がございますので、"
                    "あらかじめご了承ください！"
                ),
            )

            greeting = replace_placeholders(
                greeting,
                interaction.user
            )

            content = []

            if staff_mentions:
                content.append(
                    " ".join(staff_mentions)
                )

            content.append(
                greeting
            )

            await channel.send(
                "\n\n".join(content),
                view=TicketCloseView(),
            )

            await interaction.followup.send(
                f"✅ Ticket created: {channel.mention}",
                ephemeral=True,
            )

        except discord.HTTPException:

            await interaction.followup.send(
                "❌ Failed to create the ticket.",
                ephemeral=True,
            )


# =========================================================
# Ticket Close Button
# =========================================================

class TicketCloseView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

        button = discord.ui.Button(
            label="Close Ticket",
            emoji="🔒",
            style=discord.ButtonStyle.danger,
            custom_id=TICKET_CLOSE_ID,
        )

        button.callback = self.close_ticket

        self.add_item(button)

    async def close_ticket(
        self,
        interaction: discord.Interaction
    ):

        if not interaction.guild:

            await interaction.response.send_message(
                "❌ This button can only be used in a server.",
                ephemeral=True,
            )

            return

        if not isinstance(
            interaction.user,
            discord.Member
        ):

            await interaction.response.send_message(
                "❌ Unable to identify the member.",
                ephemeral=True,
            )

            return

        config = get_guild_config(
            interaction.guild.id
        )

        staff_role_ids = config.get(
            "ticket_staff_role_ids",
            []
        )

        creator_id, _ = get_ticket_state(
            interaction.channel.topic
        )

        # -------------------------------------------------
        # Creator cannot close
        # -------------------------------------------------

        if creator_id == interaction.user.id:

            await interaction.response.send_message(
                "❌ The ticket creator cannot close this ticket.",
                ephemeral=True,
            )

            return

        # -------------------------------------------------
        # Staff check
        # -------------------------------------------------

        if not is_staff(
            interaction.user,
            staff_role_ids
        ):

            await interaction.response.send_message(
                "❌ Only staff members can close this ticket.",
                ephemeral=True,
            )

            return

        await interaction.response.send_message(
            "🔒 Closing this ticket...",
            ephemeral=True,
        )

        try:

            await interaction.channel.delete(
                reason=(
                    f"Ticket closed by "
                    f"{interaction.user}"
                )
            )

        except discord.HTTPException:
            pass


# =========================================================
# Category Select
# =========================================================

class CategorySelect(
    discord.ui.ChannelSelect
):

    def __init__(self):

        super().__init__(
            placeholder="Select the ticket category",
            channel_types=[
                discord.ChannelType.category
            ],
            min_values=1,
            max_values=1,
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        category = self.values[0]

        if not isinstance(
            category,
            discord.CategoryChannel
        ):

            await interaction.response.send_message(
                "❌ Please select a category.",
                ephemeral=True,
            )

            return

        set_guild_value(
            interaction.guild.id,
            "ticket_category_id",
            category.id,
        )

        await interaction.response.send_message(
            f"✅ Ticket category set to **{category.name}**.",
            ephemeral=True,
        )


class CategorySelectView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=120
        )

        self.add_item(
            CategorySelect()
        )


# =========================================================
# Staff Role Select
# =========================================================

class StaffRoleSelect(
    discord.ui.RoleSelect
):

    def __init__(self):

        super().__init__(
            placeholder="Select staff roles",
            min_values=1,
            max_values=25,
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        role_ids = [
            role.id
            for role in self.values
        ]

        set_guild_value(
            interaction.guild.id,
            "ticket_staff_role_ids",
            role_ids,
        )

        await interaction.response.send_message(
            f"✅ {len(role_ids)} staff role(s) configured.",
            ephemeral=True,
        )


class StaffRoleSelectView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=120
        )

        self.add_item(
            StaffRoleSelect()
        )


# =========================================================
# Ticket Settings
# =========================================================

class TicketSettingsView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=180
        )

    @discord.ui.button(
        label="Set Category",
        emoji="📁",
        style=discord.ButtonStyle.primary,
    )
    async def category(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.send_message(
            (
                "Select the Discord category "
                "where tickets should be created."
            ),
            view=CategorySelectView(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Set Staff Roles",
        emoji="👥",
        style=discord.ButtonStyle.primary,
    )
    async def staff(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.send_message(
            (
                "Select all roles that should "
                "be treated as staff."
            ),
            view=StaffRoleSelectView(),
            ephemeral=True,
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
        description=(
            "Create the PVPBattles Support ticket panel."
        ),
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def ticket_setup(
        self,
        interaction: discord.Interaction
    ):

        if not interaction.guild:
            return

        config = get_guild_config(
            interaction.guild.id
        )

        embed = discord.Embed(
            title="🎫 PVPBattles Support",
            description=config.get(
                "ticket_message",
                (
                    "Need help?\n"
                    "Click the button below "
                    "to create a ticket."
                ),
            ),
            color=discord.Color.blurple(),
        )

        await interaction.response.send_message(
            embed=embed,
            view=TicketPanelView(),
        )

    # -----------------------------------------------------
    # /ticket-edit
    # -----------------------------------------------------

    @app_commands.command(
        name="ticket-edit",
        description="Edit ticket settings.",
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def ticket_edit(
        self,
        interaction: discord.Interaction
    ):

        if not interaction.guild:
            return

        config = get_guild_config(
            interaction.guild.id
        )

        category_text = "Not configured"

        category_id = config.get(
            "ticket_category_id"
        )

        if category_id:

            category = interaction.guild.get_channel(
                int(category_id)
            )

            if isinstance(
                category,
                discord.CategoryChannel
            ):

                category_text = category.name

        ticket_name = config.get(
            "ticket_name",
            "ticket-{username}"
        )

        staff_count = len(
            config.get(
                "ticket_staff_role_ids",
                []
            )
        )

        embed = discord.Embed(
            title="🎫 Ticket Settings",
            description=(
                f"**Category:** {category_text}\n"
                f"**Ticket name:** `{ticket_name}`\n"
                f"**Staff roles:** {staff_count}"
            ),
            color=discord.Color.blurple(),
        )

        await interaction.response.send_message(
            embed=embed,
            view=TicketSettingsView(),
            ephemeral=True,
        )

    # -----------------------------------------------------
    # /ticket-message
    # -----------------------------------------------------

    @app_commands.command(
        name="ticket-message",
        description=(
            "Set the ticket panel message."
        ),
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def ticket_message(
        self,
        interaction: discord.Interaction,
        message: str
    ):

        if not interaction.guild:
            return

        set_guild_value(
            interaction.guild.id,
            "ticket_message",
            message,
        )

        await interaction.response.send_message(
            "✅ Ticket panel message updated.",
            ephemeral=True,
        )

    # -----------------------------------------------------
    # /ticket-greeting
    # -----------------------------------------------------

    @app_commands.command(
        name="ticket-greeting",
        description=(
            "Set the greeting sent "
            "when a ticket is created."
        ),
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def ticket_greeting(
        self,
        interaction: discord.Interaction,
        message: str
    ):

        if not interaction.guild:
            return

        set_guild_value(
            interaction.guild.id,
            "ticket_greeting",
            message,
        )

        await interaction.response.send_message(
            "✅ Ticket greeting updated.",
            ephemeral=True,
        )

    # -----------------------------------------------------
    # /ticket-name
    # -----------------------------------------------------

    @app_commands.command(
        name="ticket-name",
        description=(
            "Set the ticket channel name template."
        ),
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def ticket_name(
        self,
        interaction: discord.Interaction,
        template: str
    ):

        if not interaction.guild:
            return

        set_guild_value(
            interaction.guild.id,
            "ticket_name",
            template,
        )

        await interaction.response.send_message(
            "✅ Ticket name template updated.",
            ephemeral=True,
        )


# =========================================================
# First Message Listener
# =========================================================

class TicketMessageListener(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot
    ):

        self.bot = bot

    @commands.Cog.listener()
    async def on_message(
        self,
        message: discord.Message
    ):

        # Ignore bots
        if message.author.bot:
            return

        # Ignore DMs
        if not message.guild:
            return

        # Only ticket channels
        if not message.channel.topic:
            return

        creator_id, already_replied = (
            get_ticket_state(
                message.channel.topic
            )
        )

        if creator_id is None:
            return

        if already_replied:
            return

        # Only the ticket creator triggers this
        if message.author.id != creator_id:
            return

        # Ignore completely empty messages
        if (
            not message.content.strip()
            and not message.attachments
        ):
            return

        config = get_guild_config(
            message.guild.id
        )

        reply = config.get(
            "ticket_first_message_reply",
            (
                "✅ ご要件を確認しました。"
                "スタッフが対応するまで"
                "しばらくお待ちください！"
            ),
        )

        try:

            await message.channel.send(
                reply
            )

            await message.channel.edit(
                topic=make_ticket_topic(
                    creator_id,
                    first_replied=True,
                )
            )

        except discord.HTTPException:
            pass


# =========================================================
# Setup
# =========================================================

async def setup(
    bot: commands.Bot
):

    await bot.add_cog(
        Ticket(bot)
    )

    await bot.add_cog(
        TicketMessageListener(bot)
    )
