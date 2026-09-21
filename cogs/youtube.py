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

LIVE_MARKERS = (
    "live",
    "livestream",
    "stream",
    "配信",
    "生放送",
    "ライブ",
)


def get_config(guild_id: int) -> dict:
    config = storage.get_guild_config(guild_id)
    data = config.get("youtube", {})
    return data if isinstance(data, dict) else {}


def save_config(guild_id: int, data: dict) -> None:
    storage.set_guild_value(guild_id, "youtube", data)


def parse_channel_input(value: str):
    value = value.strip()

    match = re.search(
        r"https?://(?:www\.)?youtube\.com/channel/(UC[\w-]+)",
        value,
        re.IGNORECASE,
    )
    if match:
        return None, match.group(1)

    match = re.search(
        r"https?://(?:www\.)?youtube\.com/@([^/\s?]+)",
        value,
        re.IGNORECASE,
    )
    if match:
        return match.group(1), None

    if value.startswith("@"):
        return value[1:], None

    if re.fullmatch(r"[A-Za-z0-9._-]+", value):
        return value, None

    return None, None


async def fetch_text(session, url: str) -> str:
    async with session.get(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 10) "
                "AppleWebKit/537.36 Chrome/130 Safari/537.36"
            )
        },
    ) as response:
        response.raise_for_status()
        return await response.text()


async def resolve_channel(session, value: str):
    handle, channel_id = parse_channel_input(value)

    if channel_id:
        return channel_id, "", await get_channel_name(session, channel_id)

    if not handle:
        raise ValueError(
            "YouTubeの@ハンドルまたはチャンネルURLを入力してください。"
        )

    text = await fetch_text(
        session,
        f"https://www.youtube.com/@{quote(handle)}/videos",
    )

    channel_match = re.search(
        r'"channelId":"(UC[\w-]+)"',
        text,
    )

    if not channel_match:
        channel_match = re.search(
            r'"externalId":"(UC[\w-]+)"',
            text,
        )

    if not channel_match:
        raise ValueError(
            "YouTubeチャンネルIDを取得できませんでした。"
        )

    title_match = re.search(
        r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"',
        text,
        re.IGNORECASE,
    )

    name = (
        html.unescape(title_match.group(1)).strip()
        if title_match
        else handle
    )

    return channel_match.group(1), handle, name


async def get_channel_name(session, channel_id: str) -> str:
    try:
        text = await fetch_text(
            session,
            f"https://www.youtube.com/channel/{channel_id}/videos",
        )

        match = re.search(
            r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"',
            text,
            re.IGNORECASE,
        )

        if match:
            return html.unescape(match.group(1)).strip()

    except Exception:
        pass

    return channel_id


async def get_live(session, channel_id: str, handle: str):
    url = (
        f"https://www.youtube.com/@{quote(handle)}/live"
        if handle
        else f"https://www.youtube.com/channel/{channel_id}/live"
    )

    try:
        text = await fetch_text(session, url)

        is_live = any(
            re.search(pattern, text)
            for pattern in (
                r'"isLiveNow":true',
                r'"isLive":true',
                r'"liveBroadcastDetails"',
            )
        )

        if not is_live:
            return None

        match = re.search(
            r'"videoId":"([A-Za-z0-9_-]{11})"',
            text,
        )

        if not match:
            return None

        video_id = match.group(1)

        title_match = re.search(
            r'"title":\{"runs":\[\{"text":"([^"]+)"',
            text,
        )

        title = (
            html.unescape(title_match.group(1))
            if title_match
            else "LIVE"
        )

        return video_id, title

    except Exception:
        return None


async def get_latest_rss(session, channel_id: str):
    url = (
        "https://www.youtube.com/feeds/videos.xml"
        f"?channel_id={quote(channel_id)}"
    )

    try:
        xml_text = await fetch_text(session, url)
        root = ET.fromstring(xml_text)

        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "yt": "http://www.youtube.com/xml/schemas/2015",
        }

        entry = root.find("atom:entry", ns)

        if entry is None:
            return None

        video_id = entry.findtext(
            "yt:videoId",
            default="",
            namespaces=ns,
        )

        title = entry.findtext(
            "atom:title",
            default="",
            namespaces=ns,
        )

        if not video_id:
            return None

        return video_id, title

    except Exception:
        return None


def looks_like_live(title: str) -> bool:
    title = title.casefold()
    return any(marker.casefold() in title for marker in LIVE_MARKERS)


def format_message(template: str, data: dict) -> str:
    class SafeDict(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    return template.format_map(SafeDict(data))


def live_url(handle: str, video_id: str) -> str:
    if handle:
        return f"https://www.youtube.com/@{handle}/live/"

    return f"https://www.youtube.com/watch?v={video_id}"


class SetupModal(discord.ui.Modal, title="YouTube通知を登録"):
    source = discord.ui.TextInput(
        label="YouTube @ハンドル / チャンネルURL",
        placeholder="@NaruMaroMC",
        required=True,
        max_length=200,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=20)
            ) as session:
                channel_id, handle, name = await resolve_channel(
                    session,
                    str(self.source),
                )

        except Exception as exc:
            await interaction.followup.send(
                f"❌ 登録に失敗しました。\n{exc}",
                ephemeral=True,
            )
            return

        config = get_config(interaction.guild.id)
        channels = config.setdefault("channels", [])

        if any(
            item.get("channel_id") == channel_id
            for item in channels
            if isinstance(item, dict)
        ):
            await interaction.followup.send(
                "⚠️ このYouTubeチャンネルは既に登録されています。",
                ephemeral=True,
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
                "last_video_id": None,
            }
        )

        save_config(interaction.guild.id, config)

        await interaction.followup.send(
            f"✅ **{name}** を登録しました。\n"
            "次に `/youtube-edit` から通知先を設定してください。",
            ephemeral=True,
        )


class MessageModal(discord.ui.Modal, title="通知メッセージ"):
    message = discord.ui.TextInput(
        label="通知メッセージ",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=2000,
    )

    def __init__(self, guild_id: int, index: int):
        super().__init__()
        self.guild_id = guild_id
        self.index = index

        channels = get_config(guild_id).get("channels", [])
        self.message.default = channels[index].get(
            "message",
            DEFAULT_MESSAGE,
        )

    async def on_submit(self, interaction: discord.Interaction):
        config = get_config(self.guild_id)
        channels = config.get("channels", [])

        if self.index >= len(channels):
            await interaction.response.send_message(
                "❌ 登録情報が見つかりません。",
                ephemeral=True,
            )
            return

        channels[self.index]["message"] = str(self.message)
        save_config(self.guild_id, config)

        await interaction.response.send_message(
            "✅ 通知メッセージを更新しました。",
            ephemeral=True,
        )


class DiscordChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, guild_id: int, index: int):
        super().__init__(
            channel_types=[discord.ChannelType.text],
            placeholder="📢 通知先チャンネルを選択",
        )
        self.guild_id = guild_id
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        channel = interaction.guild.get_channel(selected.id)

        if channel is None:
            await interaction.response.send_message(
                "❌ チャンネルを取得できませんでした。",
                ephemeral=True,
            )
            return

        config = get_config(self.guild_id)
        channels = config.get("channels", [])

        if self.index >= len(channels):
            await interaction.response.send_message(
                "❌ 登録情報が見つかりません。",
                ephemeral=True,
            )
            return

        channels[self.index]["discord_channel_id"] = channel.id
        save_config(self.guild_id, config)

        await interaction.response.send_message(
            f"✅ 通知先を {channel.mention} に設定しました。",
            ephemeral=True,
        )


class MentionRoleSelect(discord.ui.RoleSelect):
    def __init__(self, guild_id: int, index: int):
        super().__init__(
            placeholder="🔔 メンションするロールを選択（最大25個）",
            min_values=1,
            max_values=25,
        )
        self.guild_id = guild_id
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        config = get_config(self.guild_id)
        channels = config.get("channels", [])

        if self.index >= len(channels):
            await interaction.response.send_message(
                "❌ 登録情報が見つかりません。",
                ephemeral=True,
            )
            return

        channels[self.index]["role_ids"] = [
            role.id for role in self.values
        ]

        save_config(self.guild_id, config)

        await interaction.response.send_message(
            "✅ メンションロールを更新しました。",
            ephemeral=True,
        )


class ChannelPicker(discord.ui.Select):
    def __init__(self, guild_id: int, cog):
        config = get_config(guild_id)
        channels = config.get("channels", [])

        options = [
            discord.SelectOption(
                label=str(item.get("name", "YouTube"))[:100],
                description=(
                    f"@{item.get('handle')}"
                    if item.get("handle")
                    else "Channel ID"
                )[:100],
                value=str(index),
            )
            for index, item in enumerate(channels[:25])
        ]

        super().__init__(
            placeholder="📺 編集するYouTubeチャンネルを選択",
            options=options,
        )

        self.guild_id = guild_id
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        index = int(self.values[0])

        await interaction.response.edit_message(
            embed=self.cog.settings_embed(
                self.guild_id,
                index,
            ),
            view=EditView(
                self.cog,
                self.guild_id,
                index,
            ),
        )


class ChannelPickerView(discord.ui.View):
    def __init__(self, guild_id: int, cog):
        super().__init__(timeout=300)
        self.add_item(ChannelPicker(guild_id, cog))


class EditView(discord.ui.View):
    def __init__(self, cog, guild_id: int, index: int):
        super().__init__(timeout=300)

        self.cog = cog
        self.guild_id = guild_id
        self.index = index

        self.add_item(
            DiscordChannelSelect(guild_id, index)
        )

        self.add_item(
            MentionRoleSelect(guild_id, index)
        )

    @discord.ui.button(
        label="💬 通知メッセージ",
        style=discord.ButtonStyle.primary,
        row=2,
    )
    async def message_button(self, interaction, button):
        await interaction.response.send_modal(
            MessageModal(
                self.guild_id,
                self.index,
            )
        )

    @discord.ui.button(
        label="📋 現在の設定",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def settings_button(self, interaction, button):
        await interaction.response.send_message(
            embed=self.cog.settings_embed(
                self.guild_id,
                self.index,
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="🔴 テスト通知",
        style=discord.ButtonStyle.success,
        row=3,
    )
    async def test_button(self, interaction, button):
        await self.cog.send_test(
            interaction,
            self.guild_id,
            self.index,
        )

    @discord.ui.button(
        label="🗑️ 登録解除",
        style=discord.ButtonStyle.danger,
        row=3,
    )
    async def unregister_button(self, interaction, button):
        config = get_config(self.guild_id)
        channels = config.get("channels", [])

        if self.index >= len(channels):
            await interaction.response.send_message(
                "❌ 登録情報が見つかりません。",
                ephemeral=True,
            )
            return

        removed = channels.pop(self.index)
        save_config(self.guild_id, config)

        await interaction.response.edit_message(
            content=f"🗑️ **{removed.get('name', 'YouTube')}** の登録を解除しました。",
            embed=None,
            view=None,
        )


class YouTube(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.poll.start()

    def cog_unload(self):
        self.poll.cancel()

    @app_commands.command(
        name="youtube-setup",
        description="YouTubeチャンネルを通知対象に登録します。",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def youtube_setup(self, interaction):
        await interaction.response.send_modal(
            SetupModal()
        )

    @app_commands.command(
        name="youtube-edit",
        description="YouTubeライブ通知の設定を編集します。",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def youtube_edit(self, interaction):
        config = get_config(interaction.guild.id)
        channels = config.get("channels", [])

        if not channels:
            await interaction.response.send_message(
                "❌ YouTubeチャンネルが登録されていません。\n"
                "先に `/youtube-setup` を実行してください。",
                ephemeral=True,
            )
            return

        if len(channels) == 1:
            await interaction.response.send_message(
                embed=self.settings_embed(
                    interaction.guild.id,
                    0,
                ),
                view=EditView(
                    self,
                    interaction.guild.id,
                    0,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "編集するYouTubeチャンネルを選択してください。",
            view=ChannelPickerView(
                interaction.guild.id,
                self,
            ),
            ephemeral=True,
        )

    def settings_embed(self, guild_id: int, index: int):
        config = get_config(guild_id)
        item = config["channels"][index]

        target = None

        if item.get("discord_channel_id"):
            target = self.bot.get_channel(
                int(item["discord_channel_id"])
            )

        role_ids = item.get("role_ids", [])

        role_text = (
            " ".join(
                f"<@&{role_id}>"
                for role_id in role_ids
            )
            if role_ids
            else "未設定"
        )

        handle = item.get("handle", "")

        embed = discord.Embed(
            title="YouTube LIVE 通知設定",
            color=discord.Color.red(),
        )

        embed.add_field(
            name="📺 YouTubeチャンネル",
            value=(
                f"**{item.get('name', 'Unknown')}**\n"
                f"@{handle or '未設定'}"
            ),
            inline=False,
        )

        embed.add_field(
            name="📢 通知先",
            value=target.mention if target else "未設定",
            inline=True,
        )

        embed.add_field(
            name="🔔 メンションロール",
            value=role_text,
            inline=False,
        )

        embed.add_field(
            name="💬 通知メッセージ",
            value=item.get(
                "message",
                DEFAULT_MESSAGE,
            )[:1024],
            inline=False,
        )

        embed.add_field(
            name="⏱️ チェック間隔",
            value="1分",
            inline=True,
        )

        embed.add_field(
            name="🔗 LIVE URL",
            value=(
                f"https://www.youtube.com/@{handle}/live/"
                if handle
                else "チャンネルURL"
            ),
            inline=False,
        )

        return embed

    async def send_test(
        self,
        interaction,
        guild_id: int,
        index: int,
    ):
        config = get_config(guild_id)
        item = config["channels"][index]

        target_id = item.get("discord_channel_id")

        if not target_id:
            await interaction.response.send_message(
                "❌ 先に通知先チャンネルを設定してください。",
                ephemeral=True,
            )
            return

        target = self.bot.get_channel(
            int(target_id)
        )

        if target is None:
            await interaction.response.send_message(
                "❌ 通知先チャンネルが見つかりません。",
                ephemeral=True,
            )
            return

        handle = item.get("handle", "")

        data = {
            "channel": item.get(
                "name",
                "YouTube",
            ),
            "handle": (
                f"@{handle}"
                if handle
                else ""
            ),
            "title": "LIVE",
            "url": (
                f"https://www.youtube.com/@{handle}/live/"
                if handle
                else "https://www.youtube.com/"
            ),
        }

        message = format_message(
            item.get(
                "message",
                DEFAULT_MESSAGE,
            ),
            data,
        )

        mentions = " ".join(
            f"<@&{role_id}>"
            for role_id in item.get(
                "role_ids",
                [],
            )
        )

        await target.send(
            content=f"{mentions} {message}".strip(),
            allowed_mentions=discord.AllowedMentions(
                roles=True,
                users=False,
                everyone=False,
            ),
        )

        await interaction.response.send_message(
            "✅ テスト通知を送信しました。",
            ephemeral=True,
        )

    @tasks.loop(minutes=1)
    async def poll(self):
        await self.bot.wait_until_ready()

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20)
        ) as session:

            for guild in self.bot.guilds:
                config = get_config(guild.id)
                channels = config.get(
                    "channels",
                    [],
                )

                if not isinstance(channels, list):
                    continue

                changed = False

                for item in channels:
                    if not isinstance(item, dict):
                        continue

                    channel_id = item.get(
                        "channel_id"
                    )

                    if not channel_id:
                        continue

                    live = await get_live(
                        session,
                        channel_id,
                        item.get(
                            "handle",
                            "",
                        ),
                    )

                    if live is None:
                        rss = await get_latest_rss(
                            session,
                            channel_id,
                        )

                        if rss and looks_like_live(
                            rss[1]
                        ):
                            live = rss

                    if live is None:
                        continue

                    video_id, title = live

                    if item.get(
                        "last_video_id"
                    ) == video_id:
                        continue

                    item["last_video_id"] = video_id
                    changed = True

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

                    handle = item.get(
                        "handle",
                        "",
                    )

                    data = {
                        "channel": item.get(
                            "name",
                            channel_id,
                        ),
                        "handle": (
                            f"@{handle}"
                            if handle
                            else ""
                        ),
                        "title": title,
                        "url": live_url(
                            handle,
                            video_id,
                        ),
                    }

                    message = format_message(
                        item.get(
                            "message",
                            DEFAULT_MESSAGE,
                        ),
                        data,
                    )

                    mentions = " ".join(
                        f"<@&{role_id}>"
                        for role_id in item.get(
                            "role_ids",
                            [],
                        )
                    )

                    try:
                        await target.send(
                            content=(
                                f"{mentions} {message}"
                            ).strip(),
                            allowed_mentions=(
                                discord.AllowedMentions(
                                    roles=True,
                                    users=False,
                                    everyone=False,
                                )
                            ),
                        )
                    except (
                        discord.Forbidden,
                        discord.HTTPException,
                    ):
                        pass

                    await asyncio.sleep(0.2)

                if changed:
                    save_config(
                        guild.id,
                        config,
                    )

    @poll.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(
        YouTube(bot)
    )
