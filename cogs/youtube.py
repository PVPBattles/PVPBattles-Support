# cogs/youtube.py

import asyncio
import html
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

import storage


DEFAULT_MESSAGE = "@Stream Pings {channel}'s LIVE\n\n{url}"

MAX_CHANNELS = 25
MAX_ROLES = 25


# =========================================================
# Config
# =========================================================

def get_config(guild_id: int) -> dict:
    config = storage.get_guild_config(guild_id)

    if not isinstance(config, dict):
        return {}

    data = config.get("youtube", {})

    if not isinstance(data, dict):
        return {}

    return data


def save_config(guild_id: int, data: dict):
    storage.set_guild_value(
        guild_id,
        "youtube",
        data
    )


def get_channels(guild_id: int) -> list:
    config = get_config(guild_id)

    channels = config.get(
        "channels",
        []
    )

    if not isinstance(channels, list):
        return []

    return channels


# =========================================================
# YouTube URL / Handle
# =========================================================

def parse_channel_input(value: str):
    value = value.strip()

    match = re.search(
        r"(?:https?://)?(?:www\.)?"
        r"youtube\.com/channel/"
        r"(UC[\w-]+)",
        value,
        re.IGNORECASE
    )

    if match:
        return None, match.group(1)

    match = re.search(
        r"(?:https?://)?(?:www\.)?"
        r"youtube\.com/@([^/\s?#]+)",
        value,
        re.UNICODE
    )

    if match:
        return match.group(1), None

    if value.startswith("@"):
        handle = value[1:].strip()

        if handle:
            return handle, None

    if (
        value
        and not value.startswith("http://")
        and not value.startswith("https://")
        and "/" not in value
        and " " not in value
    ):
        return value, None

    return None, None


# =========================================================
# HTTP
# =========================================================

async def fetch_text(
    session: aiohttp.ClientSession,
    url: str
) -> str:

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Linux; Android 10) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/130.0.0.0 "
            "Mobile Safari/537.36"
        ),
        "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
    }

    async with session.get(
        url,
        headers=headers,
        allow_redirects=True
    ) as response:

        response.raise_for_status()

        return await response.text()


# =========================================================
# Resolve Channel
# =========================================================

async def resolve_channel(
    session: aiohttp.ClientSession,
    value: str
):
    handle, channel_id = parse_channel_input(
        value
    )

    if channel_id:
        name = await get_channel_name(
            session,
            channel_id
        )

        return (
            channel_id,
            None,
            name
        )

    if not handle:
        raise ValueError(
            "YouTubeのチャンネルURLまたは"
            "@ハンドルを入力してください。"
        )

    encoded_handle = quote(
        handle,
        safe=""
    )

    urls = [
        f"https://www.youtube.com/@{encoded_handle}/videos",
        f"https://www.youtube.com/@{encoded_handle}",
    ]

    last_error = None

    for url in urls:

        try:
            text = await fetch_text(
                session,
                url
            )

            channel_match = re.search(
                r'"channelId":"(UC[\w-]+)"',
                text
            )

            if not channel_match:
                channel_match = re.search(
                    r'"externalId":"(UC[\w-]+)"',
                    text
                )

            if not channel_match:
                channel_match = re.search(
                    r'"browseId":"(UC[\w-]+)"',
                    text
                )

            if not channel_match:
                continue

            channel_id = channel_match.group(1)

            name = None

            title_match = re.search(
                r'<meta[^>]+property=["\']og:title["\']'
                r'[^>]+content=["\']([^"\']+)',
                text,
                re.IGNORECASE
            )

            if title_match:
                name = html.unescape(
                    title_match.group(1)
                ).strip()

            if not name:
                title_match = re.search(
                    r'<title>(.*?)</title>',
                    text,
                    re.IGNORECASE |
                    re.DOTALL
                )

                if title_match:
                    name = html.unescape(
                        title_match.group(1)
                    ).strip()

                    name = re.sub(
                        r"\s*-\s*YouTube\s*$",
                        "",
                        name,
                        flags=re.IGNORECASE
                    ).strip()

            if not name:
                name = handle

            return (
                channel_id,
                handle,
                name
            )

        except Exception as exc:
            last_error = exc

    if last_error:
        raise ValueError(
            "YouTubeチャンネルを取得できませんでした。"
        )

    raise ValueError(
        "YouTubeチャンネルIDを取得できませんでした。\n"
        "URLまたは@ハンドルが正しいか確認してください。"
    )


# =========================================================
# Channel Name
# =========================================================

async def get_channel_name(
    session: aiohttp.ClientSession,
    channel_id: str
) -> str:

    try:
        url = (
            "https://www.youtube.com/channel/"
            f"{channel_id}/videos"
        )

        text = await fetch_text(
            session,
            url
        )

        match = re.search(
            r'<meta[^>]+property=["\']og:title["\']'
            r'[^>]+content=["\']([^"\']+)',
            text,
            re.IGNORECASE
        )

        if match:
            return html.unescape(
                match.group(1)
            ).strip()

    except Exception:
        pass

    return channel_id


# =========================================================
# Live Detection
# =========================================================

async def get_live(
    session: aiohttp.ClientSession,
    channel_id: str,
    handle: str | None
):
    """
    現在LIVE中の配信だけを返す。

    RSSやタイトル文字列はLIVE判定には使用しない。
    YouTubeページ上の現在の配信状態を確認する。
    """

    if handle:
        encoded_handle = quote(
            handle,
            safe=""
        )

        url = (
            f"https://www.youtube.com/"
            f"@{encoded_handle}/live"
        )
    else:
        url = (
            "https://www.youtube.com/channel/"
            f"{channel_id}/live"
        )

    try:
        text = await fetch_text(
            session,
            url
        )

        # -------------------------------------------------
        # ytInitialPlayerResponse
        # -------------------------------------------------

        player_match = re.search(
            r"ytInitialPlayerResponse\s*=\s*(\{.*?\})\s*;",
            text,
            re.DOTALL
        )

        if player_match:
            player_text = player_match.group(1)

            # videoDetails.isLive が true であることを要求
            is_live_match = re.search(
                r'"videoDetails"\s*:\s*\{.*?'
                r'"isLive"\s*:\s*true',
                player_text,
                re.DOTALL
            )

            if not is_live_match:
                return None

            # videoDetails.isLiveContent も確認
            is_live_content_match = re.search(
                r'"videoDetails"\s*:\s*\{.*?'
                r'"isLiveContent"\s*:\s*true',
                player_text,
                re.DOTALL
            )

            if not is_live_content_match:
                return None

            # 同じ videoDetails の中から videoId を取得
            video_match = re.search(
                r'"videoDetails"\s*:\s*\{.*?'
                r'"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"',
                player_text,
                re.DOTALL
            )

            if not video_match:
                return None

            video_id = video_match.group(1)

            # -------------------------------------------------
            # Title
            # -------------------------------------------------

            title = "LIVE"

            title_match = re.search(
                r'"videoDetails"\s*:\s*\{.*?'
                r'"title"\s*:\s*"([^"]+)"',
                player_text,
                re.DOTALL
            )

            if title_match:
                title = html.unescape(
                    title_match.group(1)
                )

            return (
                video_id,
                title
            )

        # -------------------------------------------------
        # playerResponse が取得できない場合
        # -------------------------------------------------

        # isLiveNow がページ上に存在する場合のみ
        # 厳格に videoId を探す。
        is_live_now = re.search(
            r'"isLiveNow"\s*:\s*true',
            text,
            re.IGNORECASE
        )

        if not is_live_now:
            return None

        video_ids = re.findall(
            r'"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"',
            text
        )

        video_ids = list(
            dict.fromkeys(video_ids)
        )

        if len(video_ids) != 1:
            return None

        video_id = video_ids[0]

        title = "LIVE"

        title_patterns = [
            r'"title":\{"runs":\[\{"text":"([^"]+)"',
            r'"title":"([^"]+)"',
        ]

        for pattern in title_patterns:
            match = re.search(
                pattern,
                text
            )

            if match:
                title = html.unescape(
                    match.group(1)
                )
                break

        return (
            video_id,
            title
        )

    except Exception:
        return None


# =========================================================
# RSS
# =========================================================

async def get_latest_rss(
    session: aiohttp.ClientSession,
    channel_id: str
):
    url = (
        "https://www.youtube.com/feeds/videos.xml"
        f"?channel_id={quote(channel_id)}"
    )

    try:
        xml_text = await fetch_text(
            session,
            url
        )

        root = ET.fromstring(
            xml_text
        )

        namespace = {
            "atom": "http://www.w3.org/2005/Atom",
            "yt": "http://www.youtube.com/xml/schemas/2015",
        }

        entry = root.find(
            "atom:entry",
            namespace
        )

        if entry is None:
            return None

        video_id = entry.findtext(
            "yt:videoId",
            default="",
            namespaces=namespace
        )

        title = entry.findtext(
            "atom:title",
            default="",
            namespaces=namespace
        )

        if not video_id:
            return None

        return (
            video_id,
            title
        )

    except Exception:
        return None


def looks_like_live(title: str) -> bool:
    title = title.casefold()

    keywords = (
        "live",
        "livestream",
        "stream",
        "配信",
        "生放送",
        "ライブ",
    )

    return any(
        keyword.casefold() in title
        for keyword in keywords
    )


# =========================================================
# URL
# =========================================================

def make_live_url(
    handle: str | None,
    video_id: str
):
    if handle:
        encoded_handle = quote(
            handle,
            safe=""
        )

        return (
            f"https://www.youtube.com/"
            f"@{encoded_handle}/live/"
        )

    return (
        "https://www.youtube.com/watch?v="
        f"{video_id}"
    )


# =========================================================
# Message Format
# =========================================================

def format_message(
    template: str,
    data: dict
):

    class SafeDict(dict):

        def __missing__(self, key):
            return (
                "{"
                + key
                + "}"
            )

    return template.format_map(
        SafeDict(data)
    )


# =========================================================
# Setup Modal
# =========================================================

class SetupModal(
    discord.ui.Modal,
    title="YouTube通知を登録"
):

    source = discord.ui.TextInput(
        label="YouTube @ハンドル / チャンネルURL",
        placeholder="@NaruMaroMC または https://youtube.com/@なるまろ",
        max_length=300,
        required=True
    )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        await interaction.response.defer(
            ephemeral=True
        )

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(
                    total=20
                )
            ) as session:

                (
                    channel_id,
                    handle,
                    name
                ) = await resolve_channel(
                    session,
                    str(self.source)
                )

        except Exception as exc:

            await interaction.followup.send(
                "❌ YouTubeチャンネルの取得に失敗しました。\n\n"
                f"{exc}",
                ephemeral=True
            )

            return

        config = get_config(
            interaction.guild.id
        )

        channels = config.setdefault(
            "channels",
            []
        )

        if any(
            item.get("channel_id") == channel_id
            for item in channels
            if isinstance(item, dict)
        ):

            await interaction.followup.send(
                "⚠️ このYouTubeチャンネルは"
                "既に登録されています。",
                ephemeral=True
            )

            return

        channels.append(
            {
                "channel_id": channel_id,
                "handle": handle,
                "name": name,
                "discord_channel_id": None,
                "role_ids": [],
                "message": DEFAULT_MESSAGE,
                "last_video_id": None
            }
        )

        save_config(
            interaction.guild.id,
            config
        )

        await interaction.followup.send(
            f"✅ **{name}** を登録しました。\n\n"
            "次に `/youtube-edit` から"
            "通知先などを設定してください。",
            ephemeral=True
        )


# =========================================================
# Message Modal
# =========================================================

class MessageModal(
    discord.ui.Modal,
    title="通知メッセージ"
):

    message = discord.ui.TextInput(
        label="通知メッセージ",
        style=discord.TextStyle.paragraph,
        max_length=2000,
        required=True
    )

    def __init__(
        self,
        guild_id: int,
        index: int
    ):

        super().__init__()

        self.guild_id = guild_id
        self.index = index

        channels = get_channels(
            guild_id
        )

        if 0 <= index < len(channels):

            self.message.default = channels[
                index
            ].get(
                "message",
                DEFAULT_MESSAGE
            )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        config = get_config(
            self.guild_id
        )

        channels = config.get(
            "channels",
            []
        )

        if not (
            0 <= self.index < len(channels)
        ):

            await interaction.response.send_message(
                "❌ 登録情報が見つかりません。",
                ephemeral=True
            )

            return

        channels[
            self.index
        ]["message"] = str(
            self.message
        )

        save_config(
            self.guild_id,
            config
        )

        await interaction.response.send_message(
            "✅ 通知メッセージを更新しました。",
            ephemeral=True
        )


# =========================================================
# Discord Channel Select
# =========================================================

class DiscordChannelSelect(
    discord.ui.ChannelSelect
):

    def __init__(
        self,
        guild_id: int,
        index: int
    ):

        super().__init__(
            placeholder="📢 通知先チャンネルを選択",
            channel_types=[
                discord.ChannelType.text,
                discord.ChannelType.news,
            ]
        )

        self.guild_id = guild_id
        self.index = index

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        selected = self.values[0]

        channel = interaction.guild.get_channel(
            selected.id
        )

        if channel is None:

            await interaction.response.send_message(
                "❌ チャンネルを取得できませんでした。",
                ephemeral=True
            )

            return

        config = get_config(
            self.guild_id
        )

        channels = config.get(
            "channels",
            []
        )

        if not (
            0 <= self.index < len(channels)
        ):

            await interaction.response.send_message(
                "❌ 登録情報が見つかりません。",
                ephemeral=True
            )

            return

        channels[
            self.index
        ]["discord_channel_id"] = channel.id

        save_config(
            self.guild_id,
            config
        )

        await interaction.response.send_message(
            f"✅ 通知先を {channel.mention} に設定しました。",
            ephemeral=True
        )


# =========================================================
# Role Select
# =========================================================

class MentionRoleSelect(
    discord.ui.RoleSelect
):

    def __init__(
        self,
        guild_id: int,
        index: int
    ):

        super().__init__(
            placeholder="🔔 メンションするロールを選択",
            min_values=1,
            max_values=MAX_ROLES
        )

        self.guild_id = guild_id
        self.index = index

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        config = get_config(
            self.guild_id
        )

        channels = config.get(
            "channels",
            []
        )

        if not (
            0 <= self.index < len(channels)
        ):

            await interaction.response.send_message(
                "❌ 登録情報が見つかりません。",
                ephemeral=True
            )

            return

        channels[
            self.index
        ]["role_ids"] = [
            role.id
            for role in self.values
        ]

        save_config(
            self.guild_id,
            config
        )

        await interaction.response.send_message(
            "✅ メンションロールを更新しました。",
            ephemeral=True
        )


# =========================================================
# Channel Picker
# =========================================================

class ChannelPicker(
    discord.ui.Select
):

    def __init__(
        self,
        guild_id: int,
        cog
    ):

        self.guild_id = guild_id
        self.cog = cog

        channels = get_channels(
            guild_id
        )

        options = []

        for index, item in enumerate(
            channels[:MAX_CHANNELS]
        ):

            options.append(
                discord.SelectOption(
                    label=str(
                        item.get(
                            "name",
                            "YouTube"
                        )
                    )[:100],
                    description=(
                        "@"
                        + str(
                            item.get(
                                "handle",
                                ""
                            )
                        )
                    )[:100],
                    value=str(index)
                )
            )

        super().__init__(
            placeholder="📺 編集するYouTubeチャンネルを選択",
            options=options
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        index = int(
            self.values[0]
        )

        await interaction.response.edit_message(
            embed=self.cog.settings_embed(
                self.guild_id,
                index
            ),
            view=EditView(
                self.cog,
                self.guild_id,
                index
            )
        )


class ChannelPickerView(
    discord.ui.View
):

    def __init__(
        self,
        guild_id: int,
        cog
    ):

        super().__init__(
            timeout=300
        )

        self.add_item(
            ChannelPicker(
                guild_id,
                cog
            )
        )


# =========================================================
# Edit View
# =========================================================

class EditView(
    discord.ui.View
):

    def __init__(
        self,
        cog,
        guild_id: int,
        index: int
    ):

        super().__init__(
            timeout=300
        )

        self.cog = cog
        self.guild_id = guild_id
        self.index = index

        self.add_item(
            DiscordChannelSelect(
                guild_id,
                index
            )
        )

        self.add_item(
            MentionRoleSelect(
                guild_id,
                index
            )
        )

    @discord.ui.button(
        label="💬 通知メッセージ",
        style=discord.ButtonStyle.primary,
        row=2
    )
    async def message_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.send_modal(
            MessageModal(
                self.guild_id,
                self.index
            )
        )

    @discord.ui.button(
        label="📋 現在の設定",
        style=discord.ButtonStyle.secondary,
        row=2
    )
    async def settings_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.send_message(
            embed=self.cog.settings_embed(
                self.guild_id,
                self.index
            ),
            ephemeral=True
        )

    @discord.ui.button(
        label="🔴 テスト通知",
        style=discord.ButtonStyle.success,
        row=3
    )
    async def test_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await self.cog.send_test(
            interaction,
            self.guild_id,
            self.index
        )

    @discord.ui.button(
        label="🗑️ 登録解除",
        style=discord.ButtonStyle.danger,
        row=3
    )
    async def unregister_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        config = get_config(
            self.guild_id
        )

        channels = config.get(
            "channels",
            []
        )

        if not (
            0 <= self.index < len(channels)
        ):

            await interaction.response.send_message(
                "❌ 登録情報が見つかりません。",
                ephemeral=True
            )

            return

        removed = channels.pop(
            self.index
        )

        save_config(
            self.guild_id,
            config
        )

        await interaction.response.edit_message(
            content=(
                "🗑️ **"
                + str(
                    removed.get(
                        "name",
                        "YouTube"
                    )
                )
                + "** の登録を解除しました。"
            ),
            embed=None,
            view=None
        )


# =========================================================
# YouTube Cog
# =========================================================

class YouTube(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot
    ):

        self.bot = bot

        self.poll.start()

    def cog_unload(self):
        self.poll.cancel()

    # =====================================================
    # /youtube-setup
    # =====================================================

    @app_commands.command(
        name="youtube-setup",
        description="YouTubeチャンネルを通知対象に登録します。"
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def youtube_setup(
        self,
        interaction: discord.Interaction
    ):

        await interaction.response.send_modal(
            SetupModal()
        )

    # =====================================================
    # /youtube-edit
    # =====================================================

    @app_commands.command(
        name="youtube-edit",
        description="YouTubeライブ通知を編集します。"
    )
    @app_commands.checks.has_permissions(
        manage_guild=True
    )
    async def youtube_edit(
        self,
        interaction: discord.Interaction
    ):

        channels = get_channels(
            interaction.guild.id
        )

        if not channels:

            await interaction.response.send_message(
                "❌ YouTubeチャンネルが登録されていません。\n"
                "先に `/youtube-setup` を実行してください。",
                ephemeral=True
            )

            return

        if len(channels) == 1:

            await interaction.response.send_message(
                embed=self.settings_embed(
                    interaction.guild.id,
                    0
                ),
                view=EditView(
                    self,
                    interaction.guild.id,
                    0
                ),
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            "編集するYouTubeチャンネルを選択してください。",
            view=ChannelPickerView(
                interaction.guild.id,
                self
            ),
            ephemeral=True
        )

    # =====================================================
    # Settings Embed
    # =====================================================

    def settings_embed(
        self,
        guild_id: int,
        index: int
    ):

        channels = get_channels(
            guild_id
        )

        if not (
            0 <= index < len(channels)
        ):

            return discord.Embed(
                title="❌ 登録情報がありません"
            )

        item = channels[index]

        target = None

        if item.get(
            "discord_channel_id"
        ):

            target = self.bot.get_channel(
                int(
                    item[
                        "discord_channel_id"
                    ]
                )
            )

        role_ids = item.get(
            "role_ids",
            []
        )

        role_text = (
            " ".join(
                f"<@&{role_id}>"
                for role_id in role_ids
            )
            if role_ids
            else "未設定"
        )

        handle = item.get(
            "handle"
        )

        embed = discord.Embed(
            title="YouTube LIVE 通知設定",
            color=discord.Color.red()
        )

        embed.add_field(
            name="📺 YouTubeチャンネル",
            value=(
                f"**{item.get('name', 'YouTube')}**\n"
                f"{('@' + handle) if handle else 'Channel ID: ' + str(item.get('channel_id'))}"
            ),
            inline=False
        )

        embed.add_field(
            name="📢 通知先",
            value=(
                target.mention
                if target
                else "未設定"
            ),
            inline=True
        )

        embed.add_field(
            name="🔔 メンションロール",
            value=role_text,
            inline=False
        )

        embed.add_field(
            name="💬 通知メッセージ",
            value=item.get(
                "message",
                DEFAULT_MESSAGE
            )[:1024],
            inline=False
        )

        embed.add_field(
            name="⏱️ チェック間隔",
            value="1分",
            inline=True
        )

        if handle:

            encoded_handle = quote(
                handle,
                safe=""
            )

            url = (
                "https://www.youtube.com/"
                f"@{encoded_handle}/live/"
            )

        else:

            url = (
                "https://www.youtube.com/channel/"
                f"{item.get('channel_id')}"
            )

        embed.add_field(
            name="🔗 LIVE URL",
            value=url,
            inline=False
        )

        return embed

    # =====================================================
    # Test
    # =====================================================

    async def send_test(
        self,
        interaction: discord.Interaction,
        guild_id: int,
        index: int
    ):

        channels = get_channels(
            guild_id
        )

        if not (
            0 <= index < len(channels)
        ):

            await interaction.response.send_message(
                "❌ 登録情報が見つかりません。",
                ephemeral=True
            )

            return

        item = channels[index]

        target_id = item.get(
            "discord_channel_id"
        )

        if not target_id:

            await interaction.response.send_message(
                "❌ 先に通知先チャンネルを設定してください。",
                ephemeral=True
            )

            return

        target = self.bot.get_channel(
            int(target_id)
        )

        if target is None:

            await interaction.response.send_message(
                "❌ 通知先チャンネルが見つかりません。",
                ephemeral=True
            )

            return

        handle = item.get(
            "handle"
        )

        data = {
            "channel": item.get(
                "name",
                "YouTube"
            ),
            "handle": (
                "@"
                + handle
                if handle
                else ""
            ),
            "title": "LIVE",
            "url": (
                make_live_url(
                    handle,
                    "00000000000"
                )
            )
        }

        message = format_message(
            item.get(
                "message",
                DEFAULT_MESSAGE
            ),
            data
        )

        mentions = " ".join(
            f"<@&{role_id}>"
            for role_id in item.get(
                "role_ids",
                []
            )
        )

        content = (
            f"{mentions} {message}"
        ).strip()

        await target.send(
            content=content,
            allowed_mentions=discord.AllowedMentions(
                roles=True,
                users=False,
                everyone=False
            )
        )

        await interaction.response.send_message(
            "✅ テスト通知を送信しました。",
            ephemeral=True
        )

    # =====================================================
    # Poll
    # =====================================================

    @tasks.loop(
        minutes=1
    )
    async def poll(self):

        await self.bot.wait_until_ready()

        timeout = aiohttp.ClientTimeout(
            total=20
        )

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            for guild in self.bot.guilds:

                config = get_config(
                    guild.id
                )

                channels = config.get(
                    "channels",
                    []
                )

                if not isinstance(
                    channels,
                    list
                ):
                    continue

                changed = False

                for item in channels:

                    if not isinstance(
                        item,
                        dict
                    ):
                        continue

                    channel_id = item.get(
                        "channel_id"
                    )

                    if not channel_id:
                        continue

                    handle = item.get(
                        "handle"
                    )

                    # =================================================
                    # ここだけが重要な変更点
                    #
                    # RSSをLIVE判定に使わない。
                    # YouTubeページで現在LIVEと確認できた場合のみ通知。
                    # =================================================

                    live = await get_live(
                        session,
                        channel_id,
                        handle
                    )

                    if live is None:
                        continue

                    video_id, title = live

                    # -------------------------------------------------
                    # 同じ配信を二重通知しない
                    # -------------------------------------------------

                    if item.get(
                        "last_video_id"
                    ) == video_id:

                        continue

                    target_id = item.get(
                        "discord_channel_id"
                    )

                    if not target_id:
                        continue

                    target = self.bot.get_channel(
                        int(target_id)
                    )

                    if target is None:
                        continue

                    # -------------------------------------------------
                    # 通知URL
                    # -------------------------------------------------

                    url = make_live_url(
                        handle,
                        video_id
                    )

                    data = {
                        "channel": item.get(
                            "name",
                            channel_id
                        ),
                        "handle": (
                            "@"
                            + handle
                            if handle
                            else ""
                        ),
                        "title": title,
                        "url": url
                    }

                    message = format_message(
                        item.get(
                            "message",
                            DEFAULT_MESSAGE
                        ),
                        data
                    )

                    mentions = " ".join(
                        f"<@&{role_id}>"
                        for role_id in item.get(
                            "role_ids",
                            []
                        )
                    )

                    content = (
                        f"{mentions} {message}"
                    ).strip()

                    try:

                        await target.send(
                            content=content,
                            allowed_mentions=discord.AllowedMentions(
                                roles=True,
                                users=False,
                                everyone=False
                            )
                        )

                    except (
                        discord.Forbidden,
                        discord.HTTPException
                    ):

                        continue

                    # -------------------------------------------------
                    # 通知成功後にだけlast_video_idを保存
                    # -------------------------------------------------

                    item[
                        "last_video_id"
                    ] = video_id

                    changed = True

                    await asyncio.sleep(
                        0.2
                    )

                if changed:

                    save_config(
                        guild.id,
                        config
                    )

    @poll.before_loop
    async def before_poll(self):

        await self.bot.wait_until_ready()


# =========================================================
# Setup
# =========================================================

async def setup(
    bot: commands.Bot
):

    await bot.add_cog(
        YouTube(bot)
    )
