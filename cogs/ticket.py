import re
import discord

from discord import app_commands
from discord.ext import commands

from storage import get_guild_config, set_guild_value


# =========================================================
# 設定
# =========================================================

DEFAULT_PANEL_TITLE = "🎫 PVPBattles Support"

DEFAULT_PANEL_DESCRIPTION = (
    "Need help?\n"
    "Click the button below to create a ticket."
)

DEFAULT_BUTTON_LABEL = "🎫 Create Ticket"

DEFAULT_TICKET_NAME = "ticket-{username}"

DEFAULT_GREETING = (
    "こんにちは、{user}！\n\n"
    "チケットを作成していただきありがとうございます！\n"
    "至急スタッフが対応いたしますので、ご要件を記入した上でしばらくお待ちください！\n\n"
    "また、夜間などは対応ができない可能性がございますので、"
    "あらかじめご了承ください！"
)

DEFAULT_FIRST_MESSAGE = (
    "お問い合わせありがとうございます！\n"
    "スタッフが確認しますので、少々お待ちください。"
)


# =========================================================
# Utility
# =========================================================

def get_ticket_config(guild_id: int) -> dict:
    config = get_guild_config(guild_id)
    ticket = config.get("ticket", {})

    if not isinstance(ticket, dict):
        ticket = {}

    return ticket


def sanitize_channel_name(name: str) -> str:
    """
    Discordチャンネル名用に文字を整形する。
    """

    name = name.lower()

    # 英数字、ハイフン、アンダーバー以外を削除
    name = re.sub(r"[^a-z0-9_-]+", "-", name)

    # 連続したハイフンを整理
    name = re.sub(r"-+", "-", name)

    # 前後の記号を整理
    name = name.strip("-_")

    if not name:
        name = "ticket"

    return name[:90]


def replace_ticket_placeholders(
    text: str,
    user: discord.Member | discord.User
) -> str:
    """
    チケット名などのプレースホルダーを置換。

    {username}
    {displayname}
    {userid}
    {user}
    """

    username = user.name
    displayname = getattr(user, "display_name", user.name)
    userid = str(user.id)

    replacements = {
        "{username}": username,
        "{displayname}": displayname,
        "{userid}": userid,
        "{user}": f"<@{user.id}>",
    }

    for key, value in replacements.items():
        text = text.replace(key, value)

    return text


def get_staff_role_ids(ticket_config: dict) -> list[int]:
    """
    保存されているスタッフロールIDを取得。
    """

    role_ids = ticket_config.get("staff_role_ids", [])

    if not isinstance(role_ids, list):
        return []

    result = []

    for role_id in role_ids:
        try:
            result.append(int(role_id))
        except (TypeError, ValueError):
            continue

    return result


def member_is_staff(
    member: discord.Member,
    ticket_config: dict
) -> bool:
    """
    設定されたスタッフロールのうち、
    1つでも所持していればスタッフ扱い。
    """

    staff_role_ids = get_staff_role_ids(ticket_config)

    if not staff_role_ids:
        return False

    member_role_ids = {role.id for role in member.roles}

    return bool(
        member_role_ids.intersection(staff_role_ids)
    )


def get_ticket_creator_id(channel: discord.TextChannel) -> int | None:
    """
    チケットチャンネルのtopicから作成者IDを取得。

    topic:
        ticket_creator:123456789
    """

    topic = channel.topic or ""

    match = re.search(
        r"ticket_creator:(\d+)",
        topic
    )

    if not match:
        return None

    try:
        return int(match.group(1))
    except ValueError:
        return None


def is_ticket_channel(channel: discord.abc.GuildChannel) -> bool:
    if not isinstance(channel, discord.TextChannel):
        return False

    topic = channel.topic or ""

    return "ticket_creator:" in topic


# =========================================================
# Ticket Create View
# =========================================================

class TicketPanelView(discord.ui.View):
    """
    チケット作成パネルの永続View。
    """

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label=DEFAULT_BUTTON_LABEL,
        style=discord.ButtonStyle.primary,
        emoji="🎫",
        custom_id="ticket:create"
    )
    async def create_ticket(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ このボタンはサーバー内でのみ使用できます。",
                ephemeral=True
            )
            return

        guild = interaction.guild
        user = interaction.user

        if not isinstance(user, discord.Member):
            await interaction.response.send_message(
                "❌ メンバー情報を取得できませんでした。",
                ephemeral=True
            )
            return

        ticket_config = get_ticket_config(guild.id)

        category_id = ticket_config.get("category_id")

        if not category_id:
            await interaction.response.send_message(
                "❌ チケットカテゴリが設定されていません。\n"
                "`/ticket-edit` から設定してください。",
                ephemeral=True
            )
            return

        try:
            category_id = int(category_id)
        except (TypeError, ValueError):
            await interaction.response.send_message(
                "❌ チケットカテゴリの設定が壊れています。",
                ephemeral=True
            )
            return

        category = guild.get_channel(category_id)

        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message(
                "❌ 設定されたチケットカテゴリが見つかりません。",
                ephemeral=True
            )
            return

        # -------------------------------------------------
        # 既存チケット確認
        # -------------------------------------------------

        for channel in guild.text_channels:
            if not is_ticket_channel(channel):
                continue

            creator_id = get_ticket_creator_id(channel)

            if creator_id == user.id:
                await interaction.response.send_message(
                    f"❌ すでにチケットがあります: {channel.mention}",
                    ephemeral=True
                )
                return

        await interaction.response.defer(
            ephemeral=True
        )

        # -------------------------------------------------
        # チャンネル名
        # -------------------------------------------------

        ticket_name_template = ticket_config.get(
            "ticket_name",
            DEFAULT_TICKET_NAME
        )

        if not isinstance(ticket_name_template, str):
            ticket_name_template = DEFAULT_TICKET_NAME

        channel_name = replace_ticket_placeholders(
            ticket_name_template,
            user
        )

        channel_name = sanitize_channel_name(
            channel_name
        )

        # -------------------------------------------------
        # Permission
        # -------------------------------------------------

        overwrites = {}

        # @everyone
        overwrites[guild.default_role] = discord.PermissionOverwrite(
            view_channel=False
        )

        # チケット作成者
        overwrites[user] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True
        )

        # Bot
        me = guild.me

        if me is not None:
            overwrites[me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_messages=True,
                embed_links=True,
                attach_files=True
            )

        # スタッフロール
        staff_role_ids = get_staff_role_ids(
            ticket_config
        )

        for role_id in staff_role_ids:
            role = guild.get_role(role_id)

            if role is None:
                continue

            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True
            )

        # -------------------------------------------------
        # チャンネル作成
        # -------------------------------------------------

        try:
            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"ticket_creator:{user.id}",
                reason=f"Ticket created by {user} ({user.id})"
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ チケットチャンネルを作成する権限がありません。",
                ephemeral=True
            )
            return

        except discord.HTTPException as e:
            await interaction.followup.send(
                f"❌ チケットの作成に失敗しました。\n"
                f"`{e}`",
                ephemeral=True
            )
            return

        # -------------------------------------------------
        # Greeting
        # -------------------------------------------------

        greeting = ticket_config.get(
            "greeting",
            DEFAULT_GREETING
        )

        if not isinstance(greeting, str):
            greeting = DEFAULT_GREETING

        greeting = replace_ticket_placeholders(
            greeting,
            user
        )

        # -------------------------------------------------
        # スタッフロールMention
        # -------------------------------------------------

        role_mentions = []

        for role_id in staff_role_ids:
            role = guild.get_role(role_id)

            if role is not None:
                role_mentions.append(role.mention)

        staff_mentions = ""

        if role_mentions:
            staff_mentions = (
                "\n\n"
                + " ".join(role_mentions)
            )

        # -------------------------------------------------
        # Close View
        # -------------------------------------------------

        embed = discord.Embed(
            title="🎫 Ticket",
            description=greeting,
            color=discord.Color.blurple()
        )

        embed.set_footer(
            text="PVPBattles Support"
        )

        try:
            await channel.send(
                content=staff_mentions if staff_mentions else None,
                embed=embed,
                view=TicketCloseView()
            )

        except discord.HTTPException:
            # 作成後の送信に失敗した場合、チャンネルを削除
            try:
                await channel.delete(
                    reason="Failed to initialize ticket"
                )
            except Exception:
                pass

            await interaction.followup.send(
                "❌ チケットの初期メッセージ送信に失敗しました。",
                ephemeral=True
            )
            return

        # -------------------------------------------------
        # 作成完了
        # -------------------------------------------------

        await interaction.followup.send(
            f"✅ チケットを作成しました！\n{channel.mention}",
            ephemeral=True
        )


# =========================================================
# Ticket Close View
# =========================================================

class TicketCloseView(discord.ui.View):
    """
    チケット閉じるボタンの永続View。
    """

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Close Ticket",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="ticket:close"
    )
    async def close_ticket(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ サーバー内でのみ使用できます。",
                ephemeral=True
            )
            return

        channel = interaction.channel

        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "❌ このチャンネルでは使用できません。",
                ephemeral=True
            )
            return

        if not is_ticket_channel(channel):
            await interaction.response.send_message(
                "❌ このチャンネルはチケットではありません。",
                ephemeral=True
            )
            return

        user = interaction.user

        if not isinstance(user, discord.Member):
            await interaction.response.send_message(
                "❌ メンバー情報を取得できませんでした。",
                ephemeral=True
            )
            return

        ticket_config = get_ticket_config(
            interaction.guild.id
        )

        # -------------------------------------------------
        # チケット作成者はClose不可
        # -------------------------------------------------

        creator_id = get_ticket_creator_id(channel)

        if creator_id == user.id:
            await interaction.response.send_message(
                "❌ チケット作成者はこのチケットを閉じることができません。",
                ephemeral=True
            )
            return

        # -------------------------------------------------
        # スタッフ判定
        # -------------------------------------------------

        if not member_is_staff(
            user,
            ticket_config
        ):
            await interaction.response.send_message(
                "❌ Only staff members can close this ticket.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "🗑️ チケットを閉じています...",
            ephemeral=True
        )

        try:
            await channel.delete(
                reason=f"Ticket closed by {user} ({user.id})"
            )
        except discord.Forbidden:
            # 既にinteractionは返しているためfollowup
            try:
                await interaction.followup.send(
                    "❌ チャンネルを削除する権限がありません。",
                    ephemeral=True
                )
            except Exception:
                pass

        except discord.HTTPException as e:
            try:
                await interaction.followup.send(
                    f"❌ チケットの削除に失敗しました。\n`{e}`",
                    ephemeral=True
                )
            except Exception:
                pass


# =========================================================
# Ticket Cog
# =========================================================

class Ticket(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # =====================================================
    # /ticket-setup
    # =====================================================

    @app_commands.command(
        name="ticket-setup",
        description="チケットパネルを設置します。"
    )
    @app_commands.describe(
        channel="チケットパネルを設置するチャンネル"
    )
    async def ticket_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ サーバー内でのみ使用できます。",
                ephemeral=True
            )
            return

        # 管理者チェック
        if not isinstance(
            interaction.user,
            discord.Member
        ) or not interaction.user.guild_permissions.manage_guild:

            await interaction.response.send_message(
                "❌ このコマンドを使用するにはサーバー管理権限が必要です。",
                ephemeral=True
            )
            return

        ticket_config = get_ticket_config(
            interaction.guild.id
        )

        title = ticket_config.get(
            "panel_title",
            DEFAULT_PANEL_TITLE
        )

        description = ticket_config.get(
            "panel_description",
            DEFAULT_PANEL_DESCRIPTION
        )

        button_label = ticket_config.get(
            "button_label",
            DEFAULT_BUTTON_LABEL
        )

        # -------------------------------------------------
        # Embed
        # -------------------------------------------------

        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.blurple()
        )

        embed.set_footer(
            text="PVPBattles Support"
        )

        try:
            await channel.send(
                embed=embed,
                view=TicketPanelView()
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ 指定されたチャンネルにメッセージを送信する権限がありません。",
                ephemeral=True
            )
            return

        except discord.HTTPException as e:
            await interaction.response.send_message(
                f"❌ チケットパネルの設置に失敗しました。\n`{e}`",
                ephemeral=True
            )
            return

        # ボタンラベルは現在のViewの固定値を使用
        # 保存設定としても保持
        if not isinstance(button_label, str):
            button_label = DEFAULT_BUTTON_LABEL

        set_guild_value(
            interaction.guild.id,
            "ticket",
            {
                **ticket_config,
                "panel_channel_id": channel.id,
                "panel_title": title,
                "panel_description": description,
                "button_label": button_label
            }
        )

        await interaction.response.send_message(
            f"✅ チケットパネルを設置しました！\n"
            f"{channel.mention}",
            ephemeral=True
        )

    # =====================================================
    # /ticket-edit
    # =====================================================

    @app_commands.command(
        name="ticket-edit",
        description="チケットの設定を変更します。"
    )
    @app_commands.describe(
        category="チケットを作成するDiscordカテゴリ",
        ticket_name="チケット名。{username} {displayname} {userid} {user} が使用できます。"
    )
    async def ticket_edit(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel | None = None,
        ticket_name: str | None = None
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ サーバー内でのみ使用できます。",
                ephemeral=True
            )
            return

        if not isinstance(
            interaction.user,
            discord.Member
        ) or not interaction.user.guild_permissions.manage_guild:

            await interaction.response.send_message(
                "❌ このコマンドを使用するにはサーバー管理権限が必要です。",
                ephemeral=True
            )
            return

        current = get_ticket_config(
            interaction.guild.id
        )

        if category is not None:
            current["category_id"] = category.id

        if ticket_name is not None:
            ticket_name = ticket_name.strip()

            if not ticket_name:
                await interaction.response.send_message(
                    "❌ チケット名を空にすることはできません。",
                    ephemeral=True
                )
                return

            current["ticket_name"] = ticket_name

        set_guild_value(
            interaction.guild.id,
            "ticket",
            current
        )

        # -------------------------------------------------
        # 現在のスタッフロール
        # -------------------------------------------------

        staff_role_ids = get_staff_role_ids(current)

        staff_roles = []

        for role_id in staff_role_ids:
            role = interaction.guild.get_role(role_id)

            if role is not None:
                staff_roles.append(role.mention)

        category_text = "未設定"

        saved_category_id = current.get(
            "category_id"
        )

        if saved_category_id:
            try:
                saved_category = interaction.guild.get_channel(
                    int(saved_category_id)
                )

                if isinstance(
                    saved_category,
                    discord.CategoryChannel
                ):
                    category_text = saved_category.name
            except (TypeError, ValueError):
                pass

        ticket_name_text = current.get(
  
