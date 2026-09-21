import discord
from discord import app_commands
from discord.ext import commands


class EmbedModal(discord.ui.Modal, title="Embed作成"):

    title_input = discord.ui.TextInput(
        label="タイトル",
        placeholder="Embedのタイトル",
        max_length=256,
        required=False
    )

    description_input = discord.ui.TextInput(
        label="説明",
        placeholder="Embedの内容",
        style=discord.TextStyle.paragraph,
        max_length=4000,
        required=True
    )

    color_input = discord.ui.TextInput(
        label="色",
        placeholder="#58A6FF",
        max_length=7,
        required=False,
        default="#58A6FF"
    )

    footer_input = discord.ui.TextInput(
        label="フッター",
        placeholder="フッター（任意）",
        max_length=2048,
        required=False
    )

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):
        color_text = str(
            self.color_input
        ).strip()

        if not color_text:
            color_text = "#58A6FF"

        if color_text.startswith("#"):
            color_text = color_text[1:]

        try:
            color_value = int(
                color_text,
                16
            )

            if not 0 <= color_value <= 0xFFFFFF:
                raise ValueError

        except ValueError:
            await interaction.response.send_message(
                "❌ 色は `#58A6FF` のような形式で入力してください。",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title=str(self.title_input).strip() or None,
            description=str(
                self.description_input
            ),
            color=discord.Color(
                color_value
            )
        )

        footer = str(
            self.footer_input
        ).strip()

        if footer:
            embed.set_footer(
                text=footer
            )

        try:
            await self.channel.send(
                embed=embed
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ そのチャンネルにメッセージを送信する権限がありません。",
                ephemeral=True
            )
            return

        except discord.HTTPException:
            await interaction.response.send_message(
                "❌ Embedの送信に失敗しました。",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ {self.channel.mention} にEmbedを送信しました。",
            ephemeral=True
        )


class EmbedChannelSelect(
    discord.ui.ChannelSelect
):

    def __init__(self):
        super().__init__(
            placeholder="📢 送信先チャンネルを選択",
            channel_types=[
                discord.ChannelType.text,
                discord.ChannelType.news
            ]
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        channel = self.values[0]

        await interaction.response.send_modal(
            EmbedModal(
                channel
            )
        )


class EmbedView(
    discord.ui.View
):

    def __init__(self):
        super().__init__(
            timeout=300
        )

        self.add_item(
            EmbedChannelSelect()
        )


class EmbedCog(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot
    ):
        self.bot = bot

    @app_commands.command(
        name="embed",
        description="Embedを作成して送信します。"
    )
    @app_commands.checks.has_permissions(
        manage_messages=True
    )
    async def embed(
        self,
        interaction: discord.Interaction
    ):

        embed = discord.Embed(
            title="Embed作成",
            description=(
                "下のメニューから送信先チャンネルを選択してください。"
            ),
            color=discord.Color.blurple()
        )

        await interaction.response.send_message(
            embed=embed,
            view=EmbedView(),
            ephemeral=True
        )


async def setup(
    bot: commands.Bot
):
    await bot.add_cog(
        EmbedCog(bot)
    )
