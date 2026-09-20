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
        .secondary,
        row=1,
    )
    async def message_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.send_modal(
            TicketMessageModal()
        )

    # -----------------------------------------------------
    # Greeting
    # -----------------------------------------------------

    @discord.ui.button(
        label="挨拶文章",
        emoji="👋",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def greeting_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.send_modal(
            TicketGreetingModal()
        )

    # -----------------------------------------------------
    # Ticket Name
    # -----------------------------------------------------

    @discord.ui.button(
        label="チャンネル名",
        emoji="🏷️",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def name_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.send_modal(
            TicketNameModal()
        )

    # -----------------------------------------------------
    # Support Categories
    # -----------------------------------------------------

    @discord.ui.button(
        label="サポートカテゴリ",
        emoji="🗂️",
        style=discord.ButtonStyle.success,
        row=2,
    )
    async def support_category_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.send_message(
            (
                "🗂️ **サポートカテゴリの管理**\n\n"
                "下のボタンから追加・削除できます。"
            ),
            view=SupportCategoryManageView(),
            ephemeral=True,
        )


# =========================================================
# Support Category Management
# =========================================================

class SupportCategoryManageView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=300
        )

    @discord.ui.button(
        label="カテゴリを追加",
        emoji="➕",
        style=discord.ButtonStyle.success,
    )
    async def add_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.send_modal(
            SupportCategoryAddModal()
        )

    @discord.ui.button(
        label="カテゴリを削除",
        emoji="➖",
        style=discord.ButtonStyle.danger,
    )
    async def remove_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        if not interaction.guild:
            return

        config = get_guild_config(
            interaction.guild.id
        )

        categories = get_support_categories(
            config
        )

        if not categories:

            await interaction.response.send_message(
                "❌ 登録されているサポートカテゴリがありません。",
                ephemeral=True,
            )

            return

        await interaction.response.send_message(
            "削除するサポートカテゴリを選択してください。",
            view=SupportCategoryDeleteView(
                categories
            ),
            ephemeral=True,
        )


# =========================================================
# Add Support Category Modal
# =========================================================

class SupportCategoryAddModal(
    discord.ui.Modal,
    title="サポートカテゴリを追加",
):

    name = discord.ui.TextInput(
        label="カテゴリ名",
        placeholder="例: 一般的なお問い合わせ",
        max_length=100,
        required=True,
    )

    value = discord.ui.TextInput(
        label="内部値",
        placeholder="例: general",
        max_length=100,
        required=False,
    )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):

        if not interaction.guild:
            return

        config = get_guild_config(
            interaction.guild.id
        )

        categories = get_support_categories(
            config
        )

        if len(categories) >= 25:

            await interaction.response.send_message(
                "❌ サポートカテゴリは最大25個までです。",
                ephemeral=True,
            )

            return

        name = str(
            self.name.value
        ).strip()

        value = str(
            self.value.value
        ).strip()

        if not value:
            value = name

        if any(
            item["value"] == value
            for item in categories
        ):

            await interaction.response.send_message(
                "❌ 同じ内部値のカテゴリがすでに存在します。",
                ephemeral=True,
            )

            return

        categories.append(
            {
                "name": name,
                "value": value,
            }
        )

        save_support_categories(
            interaction.guild.id,
            categories,
        )

        await interaction.response.send_message(
            (
                "✅ サポートカテゴリを追加しました。\n"
                f"🗂️ **{name}**"
            ),
            ephemeral=True,
        )


# =========================================================
# Delete Support Category
# =========================================================

class SupportCategoryDeleteSelect(
    discord.ui.Select
):

    def __init__(
        self,
        categories: list[dict],
    ):

        options = []

        for category in categories[:25]:

            options.append(
                discord.SelectOption(
                    label=category["name"][:100],
                    value=category["value"][:100],
                )
            )

        super().__init__(
            placeholder="削除するカテゴリを選択",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):

        if not interaction.guild:
            return

        selected_value = self.values[0]

        config = get_guild_config(
            interaction.guild.id
        )

        categories = get_support_categories(
            config
        )

        new_categories = []
        removed_name = selected_value

        for category in categories:

            if category["value"] == selected_value:

                removed_name = category["name"]

                continue

            new_categories.append(
                category
            )

        save_support_categories(
            interaction.guild.id,
            new_categories,
        )

        await interaction.response.send_message(
            (
                "✅ サポートカテゴリを削除しました。\n"
                f"🗑️ **{removed_name}**"
            ),
            ephemeral=True,
        )


class SupportCategoryDeleteView(
    discord.ui.View
):

    def __init__(
        self,
        categories: list[dict],
    ):

        super().__init__(
            timeout=120
        )

        self.add_item(
            SupportCategoryDeleteSelect(
                categories
            )
        )


# =========================================================
# Ticket Message Modal
# =========================================================

class TicketMessageModal(
    discord.ui.Modal,
    title="チケットパネル文章を編集",
):

    message = discord.ui.TextInput(
        label="パネルに表示する文章",
        style=discord.TextStyle.paragraph,
        max_length=4000,
        required=True,
    )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):

        if not interaction.guild:
            return

        set_guild_value(
            interaction.guild.id,
            "ticket_message",
            str(self.message.value),
        )

        await interaction.response.send_message(
            "✅ チケットパネルの文章を更新しました。",
            ephemeral=True,
        )


# =========================================================
# Ticket Greeting Modal
# =========================================================

class TicketGreetingModal(
    discord.ui.Modal,
    title="チケット挨拶文章を編集",
):

    message = discord.ui.TextInput(
        label="チケット作成時の文章",
        style=discord.TextStyle.paragraph,
        max_length=4000,
        required=True,
    )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):

        if not interaction.guild:
            return

        set_guild_value(
            interaction.guild.id,
            "ticket_greeting",
            str(self.message.value),
        )

        await interaction.response.send_message(
            "✅ チケットの挨拶文章を更新しました。",
            ephemeral=True,
        )


# =========================================================
# Ticket Name Modal
# =========================================================

class TicketNameModal(
    discord.ui.Modal,
    title="チケットチャンネル名を編集",
):

    template = discord.ui.TextInput(
        label="チャンネル名テンプレート",
        placeholder="ticket-{username}",
        max_length=100,
        required=True,
    )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):

        if not interaction.guild:
            return

        template = str(
            self.template.value
        ).strip()

        set_guild_value(
            interaction.guild.id,
            "ticket_name",
            template,
        )

        await interaction.response.send_message(
            (
                "✅ チケットチャンネル名の設定を更新しました。\n\n"
                "**使用できる変数:**\n"
                "`{username}`\n"
                "`{displayname}`\n"
                "`{userid}`\n"
                "`{user}`\n"
                "`{category}`"
            ),
            ephemeral=True,
        )


# =========================================================
# Ticket Cog
# =========================================================

class Ticket(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot,
    ):

        self.bot = bot

    # =====================================================
    # /ticket-setup
    # =====================================================

    @app_commands.command(
        name="ticket-setup",
        description="チケットパネルを設置します。",
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def ticket_setup(
        self,
        interaction: discord.Interaction,
    ):

        if not interaction.guild:
            return

        config = get_guild_config(
            interaction.guild.id
        )

        message = config.get(
            "ticket_message",
            (
                "お困りですか？\n"
                "下のボタンを押してチケットを作成してください。"
            ),
        )

        embed = discord.Embed(
            title="🎫 PVPBattles Support",
            description=message,
            color=discord.Color.blurple(),
        )

        await interaction.response.send_message(
            embed=embed,
            view=TicketPanelView(),
        )

    # =====================================================
    # /ticket-edit
    # =====================================================

    @app_commands.command(
        name="ticket-edit",
        description="チケットの設定を編集します。",
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def ticket_edit(
        self,
        interaction: discord.Interaction,
    ):

        if not interaction.guild:
            return

        config = get_guild_config(
            interaction.guild.id
        )

        category_text = "未設定"

        category_id = config.get(
            "ticket_category_id"
        )

        if category_id:

            try:
                category = interaction.guild.get_channel(
                    int(category_id)
                )
            except (TypeError, ValueError):
                category = None

            if isinstance(
                category,
                discord.CategoryChannel,
            ):
                category_text = category.name

        staff_roles = []

        for role_id in config.get(
            "ticket_staff_role_ids",
            [],
        ):

            try:
                role = interaction.guild.get_role(
                    int(role_id)
                )
            except (TypeError, ValueError):
                role = None

            if role:
                staff_roles.append(
                    role.mention
                )

        staff_text = (
            ", ".join(staff_roles)
            if staff_roles
            else "未設定"
        )

        support_categories = (
            get_support_categories(
                config
            )
        )

        support_text = (
            ", ".join(
                category["name"]
                for category in support_categories
            )
            if support_categories
            else "未設定"
        )

        ticket_name = config.get(
            "ticket_name",
            "ticket-{username}",
        )

        embed = discord.Embed(
            title="🎫 チケット設定",
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="📁 Discordカテゴリー",
            value=category_text,
            inline=False,
        )

        embed.add_field(
            name="👥 スタッフロール",
            value=staff_text,
            inline=False,
        )

        embed.add_field(
            name="🗂️ サポートカテゴリ",
            value=support_text,
            inline=False,
        )

        embed.add_field(
            name="🏷️ チャンネル名",
            value=f"`{ticket_name}`",
            inline=False,
        )

        await interaction.response.send_message(
            embed=embed,
            view=TicketSettingsView(),
            ephemeral=True,
        )

    # =====================================================
    # /ticket-message
    # =====================================================

    @app_commands.command(
        name="ticket-message",
        description="チケットパネルの文章を変更します。",
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def ticket_message(
        self,
        interaction: discord.Interaction,
        message: str,
    ):

        if not interaction.guild:
            return

        set_guild_value(
            interaction.guild.id,
            "ticket_message",
            message,
        )

        await interaction.response.send_message(
            "✅ チケットパネルの文章を更新しました。",
            ephemeral=True,
        )

    # =====================================================
    # /ticket-greeting
    # =====================================================

    @app_commands.command(
        name="ticket-greeting",
        description="チケット作成時の挨拶文章を変更します。",
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def ticket_greeting(
        self,
        interaction: discord.Interaction,
        message: str,
    ):

        if not interaction.guild:
            return

        set_guild_value(
            interaction.guild.id,
            "ticket_greeting",
            message,
        )

        await interaction.response.send_message(
            "✅ チケットの挨拶文章を更新しました。",
            ephemeral=True,
        )

    # =====================================================
    # /ticket-name
    # =====================================================

    @app_commands.command(
        name="ticket-name",
        description="チケットチャンネル名を変更します。",
    )
    @app_commands.default_permissions(
        manage_guild=True
    )
    async def ticket_name(
        self,
        interaction: discord.Interaction,
        template: str,
    ):

        if not interaction.guild:
            return

        set_guild_value(
            interaction.guild.id,
            "ticket_name",
            template,
        )

        await interaction.response.send_message(
            (
                "✅ チケットチャンネル名を更新しました。\n\n"
                "**使用できる変数:**\n"
                "`{username}`\n"
                "`{displayname}`\n"
                "`{userid}`\n"
                "`{user}`\n"
                "`{category}`"
            ),
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
        bot: commands.Bot,
    ):

        self.bot = bot

    @commands.Cog.listener()
    async def on_message(
        self,
        message: discord.Message,
    ):

        if message.author.bot:
            return

        if not message.guild:
            return

        topic = getattr(
            message.channel,
            "topic",
            None,
        )

        if not topic:
            return

        creator_id, already_replied = (
            get_ticket_state(
                topic
            )
        )

        if creator_id is None:
            return

        if already_replied:
            return

        if message.author.id != creator_id:
            return

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
                "✅ ご要件を確認しました。\n"
                "スタッフが対応するまでしばらくお待ちください！"
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
    bot: commands.Bot,
):

    await bot.add_cog(
        Ticket(bot)
    )

    await bot.add_cog(
        TicketMessageListener(bot)
    )
