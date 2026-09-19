import re
import unicodedata

import discord
from discord import app_commands
from discord.ext import commands

from storage import get_guild_config, set_guild_value


DEFAULT_TITLE = "🎫 PVPBattles Support"

DEFAULT_DESCRIPTION = (
    "Need help?\n"
    "Click the button below to create a ticket."
)

DEFAULT_BUTTON_LABEL = "Create Ticket"
DEFAULT_BUTTON_EMOJI = "🎫"

DEFAULT_SUPPORT_CATEGORIES = [
    {"name": "General Support", "emoji": "🛠️"},
    {"name": "Player Report", "emoji": "🚨"},
    {"name": "Bug Report", "emoji": "🐛"},
    {"name": "Appeal", "emoji": "⚖️"},
    {"name": "Other", "emoji": "❓"},
]

TICKET_GREETING = (
    "こんにちは、{user}！\n\n"
    "チケットを作成していただきありがとうございます！\n"
    "至急スタッフが対応いたしますので、ご要件を記入した上でしばらくお待ちください！\n\n"
    "また、夜間などは対応ができない可能性がございますので、あらかじめご了承ください！"
)

AUTO_REPLY = (
    "お問い合わせありがとうございます！\n"
    "スタッフが確認しますので、しばらくお待ちください。"
)


def get_categories(guild_id: int) -> list[dict]:
    config = get_guild_config(guild_id)

    categories = config.get("ticket_support_categories")

    if not isinstance(categories, list) or not categories:
        return [item.copy() for item in DEFAULT_SUPPORT_CATEGORIES]

    result = []

    for item in categories:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name", "")).strip()
        emoji = str(item.get("emoji", "❓")).strip()

        if name:
            result.append(
                {
                    "name": name[:80],
                    "emoji": emoji[:10] or "❓",
                }
            )

    return result or [
        item.copy()
        for item in DEFAULT_SUPPORT_CATEGORIES
    ]


def clean_channel_name(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)

    text = text.encode(
        "ascii",
        "ignore"
    ).decode("ascii")

    text = text.lower()

    text = re.sub(
        r"[^a-z0-9_-]+",
        "-",
        text
    )

    text = re.sub(
        r"-{2,}",
        "-",
        text
    )

    text = text.strip("-_")

    return text[:90] or "ticket"


def render_ticket_name(
    template: str,
    user: discord.Member
) -> str:

    values = {
        "username": user.name,
        "displayname": user.display_name,
        "userid": str(user.id),
        "user": user.name,
    }

    result = template

    for key, value in values.items():
        result = result.replace(
            "{" + key + "}",
            value
        )

    return clean_channel_name(result)


def get_ticket_name_template(guild_id: int) -> str:
    config = get_guild_config(guild_id)

    return str(
        config.get(
            "ticket_name",
            "ticket-{username}"
        )
    )


def get_staff_role_ids(guild_id: int) -> list[int]:
    config = get_guild_config(guild_id)

    raw = config.get(
        "ticket_staff_role_ids",
        []
    )

    if not isinstance(raw, list):
        return []

    result = []

    for role_id in raw:
        try:
            result.append(int(role_id))
        except (TypeError, ValueError):
            pass

    return result


def is_staff(
    member: discord.Member,
    guild_id: int
) -> bool:

    role_ids = set(
        get_staff_role_ids(guild_id)
    )

    return any(
        role.id in role_ids
        for role in member.roles
    )


def get_panel_settings(
    guild_id: int
) -> tuple[str, str, str, str]:

    config = get_guild_config(guild_id)

    title = str(
        config.get(
            "ticket_title",
            DEFAULT_TITLE
        )
    )

    description = str(
        config.get(
            "ticket_description",
            DEFAULT_DESCRIPTION
        )
    )

    button_label = str(
        config.get(
            "ticket_button_label",
            DEFAULT_BUTTON_LABEL
        )
    )

    button_emoji = str(
        config.get(
            "ticket_button_emoji",
            DEFAULT_BUTTON_EMOJI
        )
    )

    return (
        title,
        description,
        button_label,
        button_emoji,
    )


def make_panel_embed(
    guild_id: int
) -> discord.Embed:

    title, description, _, _ = get_panel_settings(
        guild_id
    )

    return discord.Embed(
        title=title,
        description=description,
        color=discord.Color.blurple(),
    )


class TicketPanelView(discord.ui.View):

    def __init__(
        self,
        guild_id: int | None = None
    ):
        super().__init__(timeout=None)

        if guild_id is not None:
            _, _, label, emoji = get_panel_settings(
                guild_id
            )
        else:
            label = DEFAULT_BUTTON_LABEL
            emoji = DEFAULT_BUTTON_EMOJI

        self.add_item(
            TicketCreateButton(
                label=label,
                emoji=emoji,
            )
        )


class TicketCreateButton(discord.ui.Button):

    def __init__(
        self,
        label: str = DEFAULT_BUTTON_LABEL,
        emoji: str = DEFAULT_BUTTON_EMOJI,
    ):

        super().__init__(
            style=discord.ButtonStyle.primary,
            label=(
                label[:80]
                or DEFAULT_BUTTON_LABEL
            ),
            emoji=(
                emoji
                or DEFAULT_BUTTON_EMOJI
            ),
            custom_id="ticket:create",
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        cog = interaction.client.get_cog(
            "Ticket"
        )

        if cog is None:
            await interaction.response.send_message(
                "❌ Ticket system is unavailable.",
                ephemeral=True,
            )
            return

        await cog.create_ticket(
            interaction
        )


class TicketCloseView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

        self.add_item(
            TicketCloseButton()
        )


class TicketCloseButton(discord.ui.Button):

    def __init__(self):

        super().__init__(
            style=discord.ButtonStyle.danger,
            label="Close Ticket",
            emoji="🔒",
            custom_id="ticket:close",
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        if (
            not interaction.guild
            or not isinstance(
                interaction.user,
                discord.Member
            )
        ):
            await interaction.response.send_message(
                "❌ This button can only be used in a server.",
                ephemeral=True,
            )
            return

        if not is_staff(
            interaction.user,
            interaction.guild.id
        ):
            await interaction.response.send_message(
                "❌ Only staff members can close this ticket.",
                ephemeral=True,
            )
            return

        channel = interaction.channel

        if not isinstance(
            channel,
            discord.TextChannel
        ):
            await interaction.response.send_message(
                "❌ This is not a ticket channel.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "🔒 Ticket will be closed.",
            ephemeral=True,
        )

        try:
            await channel.delete(
                reason=(
                    f"Ticket closed by "
                    f"{interaction.user}"
                )
            )
        except discord.HTTPException:
            pass


class SupportSelect(discord.ui.Select):

    def __init__(
        self,
        categories: list[dict]
    ):

        options = []

        for index, item in enumerate(
            categories[:25]
        ):

            emoji = item.get(
                "emoji"
            ) or "❓"

            try:
                option = discord.SelectOption(
                    label=item["name"][:100],
                    value=str(index),
                    emoji=emoji,
                )
            except (
                discord.HTTPException,
                ValueError
            ):
                option = discord.SelectOption(
                    label=item["name"][:100],
                    value=str(index),
                )

            options.append(option)

        if not options:
            options.append(
                discord.SelectOption(
                    label="General Support",
                    value="0",
                    emoji="🛠️",
                )
            )

        super().__init__(
            placeholder=(
                "Select a support category..."
            ),
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket:support",
        )

        self.categories = categories

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        if not interaction.channel:
            return

        try:
            selected_index = int(
                self.values[0]
            )
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid support category.",
                ephemeral=True,
            )
            return

        if selected_index >= len(
            self.categories
        ):
            await interaction.response.send_message(
                "❌ Invalid support category.",
                ephemeral=True,
            )
            return

        category = self.categories[
            selected_index
        ]

        await interaction.response.send_message(
            f"📌 Category selected: "
            f"**{category['name']}**",
            ephemeral=True,
        )

        try:
            await interaction.channel.edit(
                topic=(
                    f"Support category: "
                    f"{category['name']}"
                )
            )
        except discord.HTTPException:
            pass


class SupportView(discord.ui.View):

    def __init__(
        self,
        categories: list[dict]
    ):

        super().__init__(timeout=None)

        self.add_item(
            SupportSelect(categories)
        )


class CategoryManageView(
    discord.ui.View
):

    def __init__(
        self,
        cog: "Ticket"
    ):

        super().__init__(
            timeout=300
        )

        self.cog = cog

    @discord.ui.button(
        label="Add Category",
        emoji="➕",
        style=discord.ButtonStyle.success,
    )
    async def add_category(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.send_modal(
            AddCategoryModal(self.cog)
        )

    @discord.ui.button(
        label="Remove Category",
        emoji="➖",
        style=discord.ButtonStyle.danger,
    )
    async def remove_category(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        categories = get_categories(
            interaction.guild.id
        )

        if not categories:
            await interaction.response.send_message(
                "❌ No categories are configured.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "削除するカテゴリを選択してください。",
            view=RemoveCategoryView(
                self.cog,
                categories
            ),
            ephemeral=True,
        )


class AddCategoryModal(
    discord.ui.Modal,
    title="Add Support Category"
):

    name = discord.ui.TextInput(
        label="Category name",
        placeholder="e.g. Partnership",
        max_length=80,
    )

    emoji = discord.ui.TextInput(
        label="Emoji",
        placeholder="e.g. 🤝",
        required=False,
        max_length=10,
    )

    def __init__(
        self,
        cog: "Ticket"
    ):

        super().__init__()

        self.cog = cog

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        categories = get_categories(
            interaction.guild.id
        )

        if len(categories) >= 25:
            await interaction.response.send_message(
                "❌ You can have up to 25 categories.",
                ephemeral=True,
            )
            return

        name = str(
            self.name.value
        ).strip()

        emoji = (
            str(
                self.emoji.value
            ).strip()
            or "❓"
        )

        categories.append(
            {
                "name": name,
                "emoji": emoji,
            }
        )

        set_guild_value(
            interaction.guild.id,
            "ticket_support_categories",
            categories,
        )

        await interaction.response.send_message(
            f"✅ Added **{name}**.",
            ephemeral=True,
        )


class RemoveCategoryView(
    discord.ui.View
):

    def __init__(
        self,
        cog: "Ticket",
        categories: list[dict]
    ):

        super().__init__(
            timeout=120
        )

        options = []

        for index, item in enumerate(
            categories[:25]
        ):

            options.append(
                discord.SelectOption(
                    label=item["name"][:100],
                    value=str(index),
                    emoji=item.get(
                        "emoji"
                    ) or "❓",
                )
            )

        self.add_item(
            RemoveCategorySelect(
                cog,
                categories,
                options
            )
        )


class RemoveCategorySelect(
    discord.ui.Select
):

    def __init__(
        self,
        cog: "Ticket",
        categories: list[dict],
        options: list[discord.SelectOption]
    ):

        super().__init__(
            placeholder=(
                "Select a category to remove..."
            ),
            min_values=1,
            max_values=1,
            options=options,
        )

        self.cog = cog
        self.categories = categories

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        index = int(
            self.values[0]
        )

        if index >= len(
            self.categories
        ):
            await interaction.response.send_message(
                "❌ Invalid category.",
                ephemeral=True,
            )
            return

        removed = self.categories.pop(
            index
        )

        if not self.categories:
            self.categories = [
                {
                    "name": "Other",
                    "emoji": "❓"
                }
            ]

        set_guild_value(
            interaction.guild.id,
            "ticket_support_categories",
            self.categories,
        )

        await interaction.response.send_message(
            f"✅ Removed **{removed['name']}**.",
            ephemeral=True,
        )


class TicketMessageModal(
    discord.ui.Modal,
    title="Edit Ticket Panel"
):

    title_input = discord.ui.TextInput(
        label="Panel title",
        placeholder=DEFAULT_TITLE,
        max_length=256,
        required=True,
    )

    description_input = discord.ui.TextInput(
        label="Panel description",
        placeholder=DEFAULT_DESCRIPTION,
        style=discord.TextStyle.paragraph,
        max_length=4000,
        required=True,
    )

    button_label_input = discord.ui.TextInput(
        label="Button label",
        placeholder=DEFAULT_BUTTON_LABEL,
        max_length=80,
        required=True,
    )

    button_emoji_input = discord.ui.TextInput(
        label="Button emoji",
        placeholder=DEFAULT_BUTTON_EMOJI,
        max_length=10,
        required=False,
    )

    def __init__(
        self,
        guild_id: int
    ):

        super().__init__()

        self.guild_id = guild_id

        (
            title,
            description,
            label,
            emoji
        ) = get_panel_settings(
            guild_id
        )

        self.title_input.default = title
        self.description_input.default = description
        self.button_label_input.default = label
        self.button_emoji_input.default = emoji

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        set_guild_value(
            self.guild_id,
            "ticket_title",
            str(
                self.title_input.value
            ),
        )

        set_guild_value(
            self.guild_id,
            "ticket_description",
            str(
                self.description_input.value
            ),
        )

        set_guild_value(
            self.guild_id,
            "ticket_button_label",
            str(
                self.button_label_input.value
            ),
        )

        set_guild_value(
            self.guild_id,
            "ticket_button_emoji",
            (
                str(
                    self.button_emoji_input.value
                ).strip()
                or DEFAULT_BUTTON_EMOJI
            ),
        )

        await interaction.response.send_message(
            "✅ Ticket panel settings have been saved.",
            ephemeral=True,
        )


class TicketNameModal(
    discord.ui.Modal,
    title="Edit Ticket Name"
):

    name_input = discord.ui.TextInput(
        label="Ticket channel name",
        placeholder="ticket-{username}",
        max_length=100,
        required=True,
    )

    def __init__(
        self,
        guild_id: int
    ):

        super().__init__()

        self.guild_id = guild_id

        self.name_input.default = (
            get_ticket_name_template(
                guild_id
            )
        )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        set_guild_value(
            self.guild_id,
            "ticket_name",
            (
                str(
                    self.name_input.value
                ).strip()
                or "ticket-{username}"
            ),
        )

        await interaction.response.send_message(
            "✅ Ticket name template saved.\n"
            "Available: `{username}`, `{displayname}`, "
            "`{userid}`, `{user}`",
            ephemeral=True,
        )


class StaffRoleSelect(
    discord.ui.RoleSelect
):

    def __init__(
        self,
        guild_id: int
    ):

        super().__init__(
            placeholder="Select staff roles...",
            min_values=1,
            max_values=25,
            custom_id="ticket:staff_roles",
        )

        self.guild_id = guild_id

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        roles = [
            role
            for role in self.values
            if isinstance(
                role,
                discord.Role
            )
        ]

        set_guild_value(
            self.guild_id,
            "ticket_staff_role_ids",
            [
                role.id
                for role in roles
            ],
        )

        mentions = " ".join(
            role.mention
            for role in roles
        )

        await interaction.response.send_message(
            f"✅ Staff roles saved:\n{mentions}",
            ephemeral=True,
        )


class StaffRoleView(
    discord.ui.View
):

    def __init__(
        self,
        guild_id: int
    ):

        super().__init__(
            timeout=300
        )

        self.add_item(
            StaffRoleSelect(
                guild_id
            )
        )


class Ticket(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot
    ):

        self.bot = bot

    @app_commands.command(
        name="ticket-setup",
        description=(
            "Set up the ticket panel "
            "and support categories."
        ),
    )
    @app_commands.describe(
        category=(
            "Discord cat
