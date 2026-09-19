import re
import discord
from discord.ext import commands
from discord import app_commands

from storage import get_guild_config, set_guild_value


DEFAULT_CATEGORIES = [
    {"name": "General Support", "emoji": "🛠️"},
    {"name": "Player Report", "emoji": "🚨"},
    {"name": "Bug Report", "emoji": "🐛"},
    {"name": "Appeal", "emoji": "⚖️"},
    {"name": "Other", "emoji": "❓"},
]

DEFAULTS = {
    "ticket_panel_title": "🎫 PVPBattles Support",
    "ticket_panel_description": (
        "Need help?\n"
        "Click the button below to create a ticket."
    ),
    "ticket_name": "ticket-{username}",
    "ticket_color": "#5865F2",
    "ticket_welcome": (
        "こんにちは、{user}！\n\n"
        "チケットを作成していただきありがとうございます！\n"
        "至急スタッフが対応いたしますので、"
        "ご要件を記入した上でしばらくお待ちください！\n\n"
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

    if "ticket_support_categories" not in config:
        config["ticket_support_categories"] = [
            dict(category)
            for category in DEFAULT_CATEGORIES
        ]

    return config


def clean_emoji(value: str) -> str | None:
    value = (value or "").strip()
    return value or None


def parse_color(value: str) -> discord.Color:
    try:
        return discord.Color(
            int(str(value).replace("#", ""), 16)
        )
    except (ValueError, TypeError):
        return discord.Color.blurple()


def replace_variables(
    text: str,
    user: discord.Member,
) -> str:
    return (
        text
        .replace("{username}", user.name)
        .replace("{displayname}", user.display_name)
        .replace("{userid}", str(user.id))
        .replace("{user}", user.mention)
    )


def make_ticket_name(
    template: str,
    user: discord.Member,
) -> str:
    name = replace_variables(template, user).lower()

    name = re.sub(
        r"[^a-z0-9_-]+",
        "-",
        name,
    )

    name = re.sub(
        r"-+",
        "-",
        name,
    ).strip("-")

    return name[:95] or f"ticket-{user.id}"


def get_staff_roles(
    guild: discord.Guild,
    config: dict,
) -> list[discord.Role]:

    role_ids = config.get(
        "ticket_staff_role_ids",
        [],
    )

    if not isinstance(role_ids, list):
        role_ids = []

    # 旧バージョンとの互換
    if not role_ids:
        old_role_id = config.get(
            "ticket_staff_role_id"
        )

        if old_role_id:
            try:
                role_ids = [int(old_role_id)]
            except (ValueError, TypeError):
                pass

    roles = []

    for role_id in role_ids:
        try:
            role = guild.get_role(
                int(role_id)
            )
        except (ValueError, TypeError):
            role = None

        if role and role not in roles:
            roles.append(role)

    return roles


def is_staff(
    member: discord.Member,
    config: dict,
) -> bool:

    staff_roles = get_staff_roles(
        member.guild,
        config,
    )

    return any(
        role in member.roles
        for role in staff_roles
    )


def get_support_categories(
    config: dict,
) -> list[dict]:

    categories = config.get(
        "ticket_support_categories",
        [],
    )

    if not isinstance(categories, list):
        return []

    result = []

    for category in categories[:25]:

        if not isinstance(category, dict):
            continue

        name = str(
            category.get("name", "")
        ).strip()

        emoji = clean_emoji(
            str(category.get("emoji", ""))
        )

        if not name:
            continue

        result.append(
            {
                "name": name[:100],
                "emoji": emoji,
            }
        )

    return result


def category_text(
    category: dict,
) -> str:

    if category.get("emoji"):
        return (
            f"{category['emoji']} "
            f"{category['name']}"
        )

    return category["name"]


# =========================================================
# Support Category Select
# =========================================================

class SupportCategorySelect(
    discord.ui.Select
):

    def __init__(
        self,
        categories: list[dict],
    ):

        options = []

        for index, category in enumerate(
            categories[:25]
        ):

            kwargs = {
                "label": category["name"][:100],
                "value": str(index),
            }

            if category.get("emoji"):
                kwargs["emoji"] = category["emoji"]

            options.append(
                discord.SelectOption(
                    **kwargs
                )
            )

        if not options:
            options = [
                discord.SelectOption(
                    label="Other",
                    value="0",
                    emoji="❓",
                )
            ]

        super().__init__(
            placeholder="Select Support Category",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket:support",
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):

        if (
            not interaction.guild
            or not interaction.channel
        ):
            await interaction.response.send_message(
                "❌ This can only be used inside a ticket.",
                ephemeral=True,
            )
            return

        config = get_config(
            interaction.guild.id
        )

        categories = get_support_categories(
            config
        )

        try:
            index = int(
                self.values[0]
            )

            category = categories[index]

        except (
            ValueError,
            IndexError,
        ):

            await interaction.response.send_message(
                "❌ This category is no longer available.",
                ephemeral=True,
            )
            return

        selected = config.get(
            "ticket_selected_categories",
            {},
        )

        if not isinstance(selected, dict):
            selected = {}

        selected[
            str(interaction.channel.id)
        ] = category["name"]

        set_guild_value(
            interaction.guild.id,
            "ticket_selected_categories",
            selected,
        )

        embed = discord.Embed(
            title="🎯 Support Category",
            description=(
                f"**{category_text(category)}**\n\n"
                f"Selected by {interaction.user.mention}"
            ),
            color=parse_color(
                config["ticket_color"]
            ),
        )

        await interaction.response.send_message(
            embed=embed
        )


class TicketSupportView(
    discord.ui.View
):

    def __init__(
        self,
        categories: list[dict],
    ):

        super().__init__(
            timeout=None
        )

        self.add_item(
            SupportCategorySelect(
                categories
            )
        )


# =========================================================
# Ticket Create
# =========================================================

class TicketCreateButton(
    discord.ui.Button
):

    def __init__(self):

        super().__init__(
            label="Create Ticket",
            emoji="🎫",
            style=discord.ButtonStyle.primary,
            custom_id="ticket:create",
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):

        if not interaction.guild:
            return

        if not isinstance(
            interaction.user,
            discord.Member,
        ):
            return

        guild = interaction.guild
        user = interaction.user

        config = get_config(
            guild.id
        )

        category_id = config.get(
            "ticket_category_id"
        )

        try:
            ticket_category = guild.get_channel(
                int(category_id)
            )
        except (
            ValueError,
            TypeError,
        ):
            ticket_category = None

        if not isinstance(
            ticket_category,
            discord.CategoryChannel,
        ):

            await interaction.response.send_message(
                "❌ The ticket category has not been configured.",
                ephemeral=True,
            )
            return

        staff_roles = get_staff_roles(
            guild,
            config,
        )

        if not staff_roles:

            await interaction.response.send_message(
                "❌ No staff roles have been configured.",
                ephemeral=True,
            )
            return

        # 既にチケットがあるか確認
        for channel in guild.text_channels:

            if channel.topic == (
                f"ticket_owner:{user.id}"
            ):

                await interaction.response.send_message(
                    f"❌ You already have an open ticket: "
                    f"{channel.mention}",
                    ephemeral=True,
                )

                return

        name = make_ticket_name(
            config["ticket_name"],
            user,
        )

        overwrites = {
            guild.default_role:
                discord.PermissionOverwrite(
                    view_channel=False
                ),

            user:
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    embed_links=True,
                ),
        }

        if guild.me:

            overwrites[guild.me] = (
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_channels=True,
                    manage_messages=True,
                )
            )

        # 複数スタッフロール
        for role in staff_roles:

            overwrites[role] = (
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    embed_links=True,
                )
            )

        try:

            channel = await guild.create_text_channel(
                name=name,
                category=ticket_category,
                overwrites=overwrites,
                topic=f"ticket_owner:{user.id}",
                reason=f"Ticket created by {user}",
            )

        except discord.Forbidden:

            await interaction.response.send_message(
                "❌ I don't have permission to create ticket channels.",
                ephemeral=True,
            )

            return

        except discord.HTTPException:

            await interaction.response.send_message(
                "❌ Failed to create the ticket channel.",
                ephemeral=True,
            )

            return

        await interaction.response.send_message(
            f"✅ Ticket created: {channel.mention}",
            ephemeral=True,
        )

        # 全スタッフロールをメンション
        role_mentions = " ".join(
            role.mention
            for role in staff_roles
        )

        welcome = replace_variables(
            config["ticket_welcome"],
            user,
        )

        embed = discord.Embed(
            title="🎫 PVPBattles Support",
            description=welcome,
            color=parse_color(
                config["ticket_color"]
            ),
        )

        await channel.send(
            content=role_mentions,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(
                roles=True,
                users=True,
                everyone=False,
            ),
        )

        # サポートカテゴリ選択
        categories = get_support_categories(
            config
        )

        category_embed = discord.Embed(
            title="🎯 Support Category",
            description=(
                "サポート内容を選択してください。\n"
                "下のメニューから該当するものを選んでください。"
            ),
            color=parse_color(
                config["ticket_color"]
            ),
        )

        await channel.send(
            embed=category_embed,
            view=TicketSupportView(
                categories
            ),
        )

        # Closeボタン
        await channel.send(
            view=TicketCloseView()
        )


class TicketPanelView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )

        self.add_item(
            TicketCreateButton()
        )


# =========================================================
# Ticket Close
# =========================================================

class TicketCloseButton(
    discord.ui.Button
):

    def __init__(self):

        super().__init__(
            label="Close Ticket",
            emoji="🔒",
            style=discord.ButtonStyle.danger,
            custom_id="ticket:close",
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):

        if not interaction.guild:
            return

        if not isinstance(
            interaction.user,
            discord.Member,
        ):
            return

        config = get_config(
            interaction.guild.id
        )

        if not is_staff(
            interaction.user,
            config,
        ):

            await interaction.response.send_message(
                "❌ Only staff members can close this ticket.",
                ephemeral=True,
            )

            return

        topic = (
            getattr(
                interaction.channel,
                "topic",
                "",
            )
            or ""
        )

        # チケット作成者はClose不可
        if topic == (
            f"ticket_owner:{interaction.user.id}"
        ):

            await interaction.response.send_message(
                "❌ The ticket creator cannot close this ticket.",
                ephemeral=True,
            )

            return

        await interaction.response.send_message(
            "🔒 Closing ticket...",
            ephemeral=True,
        )

        selected = config.get(
            "ticket_selected_categories",
            {},
        )

        if isinstance(selected, dict):

            selected.pop(
                str(interaction.channel.id),
                None,
            )

            set_guild_value(
                interaction.guild.id,
                "ticket_selected_categories",
                selected,
            )

        sent = config.get(
            "ticket_first_reply_sent",
            {},
        )

        if isinstance(sent, dict):

            sent.pop(
                str(interaction.channel.id),
                None,
            )

            set_guild_value(
                interaction.guild.id,
                "ticket_first_reply_sent",
                sent,
            )

        try:

            await interaction.channel.delete(
                reason=(
                    f"Ticket closed by "
                    f"{interaction.user}"
                ),
            )

        except (
            discord.Forbidden,
            discord.HTTPException,
        ):
            pass


class TicketCloseView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )

        self.add_item(
            TicketCloseButton()
        )


# =========================================================
# Ticket Settings
# =========================================================

class TicketSettingsModal(
    discord.ui.Modal,
    title="Ticket Panel Settings",
):

    panel_title = discord.ui.TextInput(
        label="Panel Title",
        default=DEFAULTS[
            "ticket_panel_title"
        ],
        max_length=256,
    )

    panel_description = discord.ui.TextInput(
        label="Panel Description",
        default=DEFAULTS[
            "ticket_panel_description"
        ],
        style=discord.TextStyle.paragraph,
        max_length=4000,
    )

    ticket_name = discord.ui.TextInput(
        label="Ticket Channel Name",
        default=DEFAULTS[
            "ticket_name"
        ],
        max_length=100,
    )

    welcome = discord.ui.TextInput(
        label="Welcome Message",
        default=DEFAULTS[
            "ticket_welcome"
        ],
        style=discord.TextStyle.paragraph,
        max_length=4000,
    )

    first_reply = discord.ui.TextInput(
        label="First Requirement Reply",
        default=DEFAULTS[
            "ticket_first_reply"
        ],
        style=discord.TextStyle.paragraph,
        max_length=4000,
    )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):

        guild_id = interaction.guild.id

        set_guild_value(
            guild_id,
            "ticket_panel_title",
            str(self.panel_title),
        )

        set_guild_value(
            guild_id,
            "ticket_panel_description",
            str(self.panel_description),
        )

        set_guild_value(
            guild_id,
            "ticket_name",
            str(self.ticket_name),
        )

        set_guild_value(
            guild_id,
            "ticket_welcome",
            str(self.welcome),
        )

        set_guild_value(
            guild_id,
            "ticket_first_reply",
            str(self.first_reply),
        )

        await interaction.response.send_message(
            "✅ Ticket settings saved.",
            ephemeral=True,
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
        interaction: discord.Interaction,
    ):

        roles = list(self.values)

        set_guild_value(
            interaction.guild.id,
            "ticket_staff_role_ids",
            [
                role.id
                for role in roles
            ],
        )

        # 旧設定との互換
        if roles:

            set_guild_value(
                interaction.guild.id,
                "ticket_staff_role_id",
                roles[0].id,
            )

        await interaction.response.send_message(
            "✅ Staff roles saved:\n"
            + "\n".join(
                role.mention
                for role in roles
            ),
            ephemeral=True,
        )


class StaffRoleView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=180
        )

        self.add_item(
            StaffRoleSelect()
        )


# =========================================================
# Add Support Category
# =========================================================

class AddSupportCategoryModal(
    discord.ui.Modal,
    title="Add Support Category",
):

    name = discord.ui.TextInput(
        label="Category Name",
        placeholder="Player Report",
        max_length=100,
    )

    emoji = discord.ui.TextInput(
        label="Emoji",
        placeholder="🚨",
        required=False,
        max_length=100,
    )

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):

        config = get_config(
   
