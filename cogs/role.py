import string

import discord
from discord import app_commands
from discord.ext import commands

ROLEPANEL_PREFIX = "rolepanel:"
MAX_ROLES = 15
ROLE_LETTERS = string.ascii_uppercase


def letter_emoji(index: int) -> str:
    return chr(0x1F1E6 + index)


def build_panel_view(roles: list[discord.Role]) -> discord.ui.View:
    view = discord.ui.View(timeout=None)

    for i, role in enumerate(roles):
        view.add_item(
            discord.ui.Button(
                emoji=letter_emoji(i),
                style=discord.ButtonStyle.primary,
                custom_id=f"{ROLEPANEL_PREFIX}{role.id}",
            )
        )

    return view


def build_role_list_text(
    roles: list[discord.Role]
) -> str:
    return "\n".join(
        f"{letter_emoji(i)} ： {r.mention}"
        for i, r in enumerate(roles)
    )


class RolePanel(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_interaction(
        self,
        interaction: discord.Interaction
    ):
        if interaction.type != discord.InteractionType.component:
            return

        data = interaction.data or {}
        custom_id = data.get("custom_id", "")

        if not custom_id.startswith(ROLEPANEL_PREFIX):
            return

        guild = interaction.guild

        if guild is None:
            return

        try:
            role_id = int(
                custom_id.removeprefix(
                    ROLEPANEL_PREFIX
                )
            )
        except ValueError:
            return

        role = guild.get_role(role_id)

        if role is None:
            await interaction.response.send_message(
                "このロールは削除されたようです。管理者に伝えてください。",
                ephemeral=True
            )
            return

        member = interaction.user

        try:

            if role in member.roles:

                await member.remove_roles(
                    role,
                    reason="ロールパネル"
                )

                await interaction.response.send_message(
                    f"{role.name} を外しました。",
                    ephemeral=True
                )

            else:

                await member.add_roles(
                    role,
                    reason="ロールパネル"
                )

                await interaction.response.send_message(
                    f"{role.name} を付与しました。",
                    ephemeral=True
                )

        except discord.Forbidden:

            await interaction.response.send_message(
                "権限不足でロールを変更できませんでした。"
                "Botのロール順位を確認してください。",
                ephemeral=True
            )

    @app_commands.command(
        name="rolepanel",
        description=f"ロールパネルをこのチャンネルに設置します(最大{MAX_ROLES}個)"
    )
    @app_commands.describe(
        title="パネルのタイトル",
        description="パネルの説明文",
        role1="1個目のロール",
        role2="2個目のロール(任意)",
        role3="3個目のロール(任意)",
        role4="4個目のロール(任意)",
        role5="5個目のロール(任意)",
        role6="6個目のロール(任意)",
        role7="7個目のロール(任意)",
        role8="8個目のロール(任意)",
        role9="9個目のロール(任意)",
        role10="10個目のロール(任意)",
        role11="11個目のロール(任意)",
        role12="12個目のロール(任意)",
        role13="13個目のロール(任意)",
        role14="14個目のロール(任意)",
        role15="15個目のロール(任意)",
    )
    @app_commands.checks.has_permissions(
        administrator=True
    )
    async def rolepanel(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
        role1: discord.Role,
        role2: discord.Role = None,
        role3: discord.Role = None,
        role4: discord.Role = None,
        role5: discord.Role = None,
        role6: discord.Role = None,
        role7: discord.Role = None,
        role8: discord.Role = None,
        role9: discord.Role = None,
        role10: discord.Role = None,
        role11: discord.Role = None,
        role12: discord.Role = None,
        role13: discord.Role = None,
        role14: discord.Role = None,
        role15: discord.Role = None,
    ):

        candidates = [
            role1,
            role2,
            role3,
            role4,
            role5,
            role6,
            role7,
            role8,
            role9,
            role10,
            role11,
            role12,
            role13,
            role14,
            role15,
        ]

        seen_ids = set()
        roles = []

        for role in candidates:

            if role is None:
                continue

            if role.id in seen_ids:
                continue

            seen_ids.add(role.id)
            roles.append(role)

        bot_member = interaction.guild.me

        for role in roles:

            if role >= bot_member.top_role:

                await interaction.response.send_message(
                    f"{role.mention} はBotのロールより上位のため"
                    "付与できません。ロール順位を調整してください。",
                    ephemeral=True
                )
                return

        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.blurple()
        )

        embed.add_field(
            name="ロール一覧",
            value=build_role_list_text(roles),
            inline=False
        )

        view = build_panel_view(roles)

        await interaction.channel.send(
            embed=embed,
            view=view
        )

        await interaction.response.send_message(
            f"ロールパネルを設置しました。({len(roles)}個のロール)",
            ephemeral=True
        )


async def setup(
    bot: commands.Bot
):
    await bot.add_cog(
        RolePanel(bot)
    )
