import re
import discord
from discord.ext import commands
from discord import app_commands
from storage import get_guild_config, set_guild_value

TICKET_CREATE_ID = 'ticket:create'
TICKET_CLOSE_ID = 'ticket:close'


def sanitize_channel_name(name):
    name = str(name).lower().replace(' ', '-')
    name = ''.join(c for c in name if c in 'abcdefghijklmnopqrstuvwxyz0123456789-_')
    return name[:90] or 'ticket'


def replace_placeholders(text, member, category=None):
    for k, v in {
        '{username}': member.name,
        '{displayname}': member.display_name,
        '{userid}': str(member.id),
        '{user}': member.mention,
        '{category}': category or '',
    }.items():
        text = str(text).replace(k, v)
    return text


def state(topic):
    creator = None
    replied = False
    if topic:
        for p in topic.split(';'):
            if p.startswith('ticket_creator:') and p.split(':', 1)[1].isdigit():
                creator = int(p.split(':', 1)[1])
            if p == 'first_replied:1':
                replied = True
    return creator, replied


def topic(creator, replied=False):
    return f'ticket_creator:{creator};first_replied:{1 if replied else 0}'


def staff(member, ids):
    return any(r.id in {int(x) for x in ids if str(x).isdigit()} for r in member.roles)


def categories(config):
    value = config.get('ticket_support_categories', [])
    return [str(x).strip()[:100] for x in value if isinstance(x, str) and x.strip()][:25] if isinstance(value, list) else []


def cfg(guild_id):
    c = get_guild_config(guild_id)
    defaults = {
        'ticket_title': '🎫 PVPBattles Support',
        'ticket_message': 'お困りですか？\n下のボタンからチケットを作成してください。',
        'ticket_button_label': 'チケットを作成',
        'ticket_close_label': 'チケットを閉じる',
        'ticket_embed_color': '58A6FF',
        'ticket_greeting': 'こんにちは、{user}！\n\nチケットを作成していただきありがとうございます！\n至急スタッフが対応いたしますので、ご要件を記入した上でしばらくお待ちください！\n\nまた、夜間などは対応ができない可能性がございますので、あらかじめご了承ください！',
        'ticket_name': 'ticket-{username}',
        'ticket_first_reply': 'スタッフが対応いたしますので、しばらくお待ちください！',
    }
    defaults.update(c)
    return defaults


def color(c):
    try:
        return discord.Color(int(str(c).replace('#', ''), 16))
    except Exception:
        return discord.Color(0x58A6FF)


async def create_ticket(interaction, support_category=None):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message('❌ サーバー内でのみ使用できます。', ephemeral=True)
        return
    c = cfg(interaction.guild.id)
    try:
        category = interaction.guild.get_channel(int(c.get('ticket_category_id')))
    except (TypeError, ValueError):
        category = None
    if not isinstance(category, discord.CategoryChannel):
        await interaction.response.send_message('❌ チケットを作成するDiscordカテゴリが設定されていません。', ephemeral=True)
        return
    for ch in category.text_channels:
        creator, _ = state(ch.topic)
        if creator == interaction.user.id:
            await interaction.response.send_message(f'❌ すでにチケットがあります。\n{ch.mention}', ephemeral=True)
            return
    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True),
    }
    if interaction.guild.me:
        overwrites[interaction.guild.me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True, manage_messages=True)
    mentions = []
    ids = c.get('ticket_staff_role_ids', [])
    if isinstance(ids, list):
        for rid in ids:
            try: role = interaction.guild.get_role(int(rid))
            except (TypeError, ValueError): role = None
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True)
                mentions.append(role.mention)
    name = sanitize_channel_name(replace_placeholders(c['ticket_name'], interaction.user, support_category))
    await interaction.response.defer(ephemeral=True)
    try:
        ch = await interaction.guild.create_text_channel(name=name, category=category, overwrites=overwrites, topic=topic(interaction.user.id), reason=f'Ticket created by {interaction.user}')
        parts = []
        if mentions: parts.append(' '.join(mentions))
        if support_category: parts.append(f'📂 **お問い合わせカテゴリ:** {support_category}')
        parts.append(replace_placeholders(c['ticket_greeting'], interaction.user, support_category))
        await ch.send('\n\n'.join(parts), view=TicketCloseView(c))
        await interaction.followup.send(f'✅ チケットを作成しました！\n{ch.mention}', ephemeral=True)
    except discord.HTTPException:
        await interaction.followup.send('❌ チケットの作成に失敗しました。', ephemeral=True)


class SupportSelect(discord.ui.Select):
    def __init__(self, items):
        super().__init__(placeholder='お問い合わせ内容を選択してください', options=[discord.SelectOption(label=x[:100], value=str(i), emoji='📂') for i, x in enumerate(items)], min_values=1, max_values=1)
    async def callback(self, interaction):
        items = categories(get_guild_config(interaction.guild.id))
        try: item = items[int(self.values[0])]
        except (ValueError, IndexError):
            await interaction.response.send_message('❌ カテゴリの取得に失敗しました。', ephemeral=True); return
        await create_ticket(interaction, item)

class SupportSelectView(discord.ui.View):
    def __init__(self, items):
        super().__init__(timeout=120); self.add_item(SupportSelect(items))

class TicketPanelView(discord.ui.View):
    def __init__(self, config=None):
        super().__init__(timeout=None)
        label = str((config or {}).get('ticket_button_label', 'チケットを作成'))[:80] or 'チケットを作成'
        b = discord.ui.Button(label=label, emoji='🎫', style=discord.ButtonStyle.primary, custom_id=TICKET_CREATE_ID)
        b.callback = self.create; self.add_item(b)
    async def create(self, interaction):
        if not interaction.guild:
            await interaction.response.send_message('❌ サーバー内でのみ使用できます。', ephemeral=True); return
        items = categories(get_guild_config(interaction.guild.id))
        if items:
            await interaction.response.send_message('📂 お問い合わせ内容を選択してください。', view=SupportSelectView(items), ephemeral=True); return
        await create_ticket(interaction)

class TicketCloseView(discord.ui.View):
    def __init__(self, config=None):
        super().__init__(timeout=None)
        label = str((config or {}).get('ticket_close_label', 'チケットを閉じる'))[:80] or 'チケットを閉じる'
        b = discord.ui.Button(label=label, emoji='🔒', style=discord.ButtonStyle.danger, custom_id=TICKET_CLOSE_ID)
        b.callback = self.close; self.add_item(b)
    async def close(self, interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message('❌ このチャンネルでは使用できません。', ephemeral=True); return
        creator, _ = state(interaction.channel.topic)
        if creator == interaction.user.id:
            await interaction.response.send_message('❌ チケットを作成した本人はチケットを閉じることができません。', ephemeral=True); return
        c = get_guild_config(interaction.guild.id)
        if not staff(interaction.user, c.get('ticket_staff_role_ids', [])):
            await interaction.response.send_message('❌ このチケットを閉じられるのはスタッフのみです。', ephemeral=True); return
        await interaction.response.send_message('🔒 チケットを閉じています……', ephemeral=True)
        try: await interaction.channel.delete(reason=f'Ticket closed by {interaction.user}')
        except discord.HTTPException: pass

class CategorySelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(placeholder='チケットを作成するDiscordカテゴリを選択', channel_types=[discord.ChannelType.category], min_values=1, max_values=1)
    async def callback(self, interaction):
        selected = self.values[0]; cid = getattr(selected, 'id', None)
        category = interaction.guild.get_channel(int(cid)) if cid is not None else None
        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message('❌ カテゴリを取得できませんでした。', ephemeral=True); return
        set_guild_value(interaction.guild.id, 'ticket_category_id', category.id)
        await interaction.response.send_message(f'✅ チケットカテゴリを **{category.name}** に設定しました。', ephemeral=True)

class CategoryView(discord.ui.View):
    def __init__(self): super().__init__(timeout=120); self.add_item(CategorySelect())

class StaffSelect(discord.ui.RoleSelect):
    def __init__(self): super().__init__(placeholder='スタッフロールを選択', min_values=1, max_values=25)
    async def callback(self, interaction):
        ids = [r.id for r in self.values]
        set_guild_value(interaction.guild.id, 'ticket_staff_role_ids', ids)
        await interaction.response.send_message(f'✅ {len(ids)}個のスタッフロールを設定しました。', ephemeral=True)

class StaffView(discord.ui.View):
    def __init__(self): super().__init__(timeout=120); self.add_item(StaffSelect())

class TextModal(discord.ui.Modal):
    def __init__(self, title, field, label, value, max_length=4000):
        super().__init__(title=title); self.field = field
        self.input = discord.ui.TextInput(label=label, default=str(value)[:max_length], max_length=max_length, required=True, style=discord.TextStyle.paragraph)
        self.add_item(self.input)
    async def on_submit(self, interaction):
        value = str(self.input).strip()
        if not value:
            await interaction.response.send_message('❌ 内容を入力してください。', ephemeral=True); return
        set_guild_value(interaction.guild.id, self.field, value)
        await interaction.response.send_message('✅ 設定を更新しました。', ephemeral=True)

class ColorModal(discord.ui.Modal):
    def __init__(self, current):
        super().__init__(title='パネルカラーを変更')
        self.input = discord.ui.TextInput(label='カラーコード', placeholder='#58A6FF', default=str(current), max_length=7, required=True)
        self.add_item(self.input)
    async def on_submit(self, interaction):
        value = str(self.input).strip().replace('#', '')
        if not re.fullmatch(r'[0-9A-Fa-f]{6}', value):
            await interaction.response.send_message('❌ 6桁のカラーコードを入力してください。例: `#58A6FF`', ephemeral=True); return
        set_guild_value(interaction.guild.id, 'ticket_embed_color', value)
        await interaction.response.send_message('✅ パネルカラーを変更しました。', ephemeral=True)

class AddSupportModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title='お問い合わせカテゴリを追加')
        self.input = discord.ui.TextInput(label='カテゴリ名', placeholder='例：お問い合わせ / Minecraft / Discord', max_length=100, required=True)
        self.add_item(self.input)
    async def on_submit(self, interaction):
        items = categories(get_guild_config(interaction.guild.id)); value = str(self.input).strip()
        if not value: await interaction.response.send_message('❌ カテゴリ名を入力してください。', ephemeral=True); return
        if len(items) >= 25: await interaction.response.send_message('❌ 最大25個までです。', ephemeral=True); return
        if value in items: await interaction.response.send_message('❌ そのカテゴリはすでに存在します。', ephemeral=True); return
        items.append(value); set_guild_value(interaction.guild.id, 'ticket_support_categories', items)
        await interaction.response.send_message(f'✅ **{value}** を追加しました。', ephemeral=True)

class DeleteSupportSelect(discord.ui.Select):
    def __init__(self, items):
        super().__init__(placeholder='削除するカテゴリを選択', options=[discord.SelectOption(label=x[:100], value=str(i), emoji='🗑️') for i,x in enumerate(items)], min_values=1, max_values=1)
    async def callback(self, interaction):
        items = categories(get_guild_config(interaction.guild.id))
        try: removed = items.pop(int(self.values[0]))
        except (ValueError, IndexError): await interaction.response.send_message('❌ カテゴリの取得に失敗しました。', ephemeral=True); return
        set_guild_value(interaction.guild.id, 'ticket_support_categories', items)
        await interaction.response.send_message(f'🗑️ **{removed}** を削除しました。', ephemeral=True)

class DeleteSupportView(discord.ui.View):
    def __init__(self, items): super().__init__(timeout=120); self.add_item(DeleteSupportSelect(items))

class TicketSettingsView(discord.ui.View):
    def __init__(self): super().__init__(timeout=300)
    async def modal(self, interaction, field, title, label, max_length=4000):
        c = cfg(interaction.guild.id); await interaction.response.send_modal(TextModal(title, field, label, c[field], max_length))
    @discord.ui.button(label='タイトル', emoji='📝', style=discord.ButtonStyle.primary, row=0)
    async def title(self, i, b): await self.modal(i, 'ticket_title', 'チケットタイトルを編集', 'タイトル', 256)
    @discord.ui.button(label='説明文', emoji='📄', style=discord.ButtonStyle.primary, row=0)
    async def message(self, i, b): await self.modal(i, 'ticket_message', 'チケット説明文を編集', '説明文')
    @discord.ui.button(label='作成ボタン', emoji='🎫', style=discord.ButtonStyle.primary, row=0)
    async def button(self, i, b): await self.modal(i, 'ticket_button_label', '作成ボタンを編集', 'ボタン文字', 80)
    @discord.ui.button(label='パネルカラー', emoji='🎨', style=discord.ButtonStyle.secondary, row=1)
    async def panel_color(self, i, b): await i.response.send_modal(ColorModal(cfg(i.guild.id)['ticket_embed_color']))
    @discord.ui.button(label='挨拶', emoji='👋', style=discord.ButtonStyle.secondary, row=1)
    async def greeting(self, i, b): await self.modal(i, 'ticket_greeting', 'チケット挨拶を編集', '挨拶メッセージ')
    @discord.ui.button(label='チャンネル名', emoji='📛', style=discord.ButtonStyle.secondary, row=1)
    async def channel_name(self, i, b): await self.modal(i, 'ticket_name', 'チャンネル名を編集', 'テンプレート', 90)
    @discord.ui.button(label='Discordカテゴリ', emoji='📂', style=discord.ButtonStyle.secondary, row=2)
    async def category(self, i, b): await i.response.send_message('📂 Discordカテゴリを選択してください。', view=CategoryView(), ephemeral=True)
    @discord.ui.button(label='スタッフロール', emoji='👥', style=discord.ButtonStyle.secondary, row=2)
    async def roles(self, i, b): await i.response.send_message('👥 スタッフロールを選択してください。複数選択できます。', view=StaffView(), ephemeral=True)
    @discord.ui.button(label='カテゴリ追加', emoji='➕', style=discord.ButtonStyle.success, row=3)
    async def add_category(self, i, b): await i.response.send_modal(AddSupportModal())
    @discord.ui.button(label='カテゴリ削除', emoji='🗑️', style=discord.ButtonStyle.danger, row=3)
    async def delete_category(self, i, b):
        items = categories(get_guild_config(i.guild.id))
        if not items: await i.response.send_message('❌ 削除できるカテゴリがありません。', ephemeral=True); return
        await i.response.send_message('🗑️ 削除するカテゴリを選択してください。', view=DeleteSupportView(items), ephemeral=True)
    @discord.ui.button(label='閉じるボタン', emoji='🔒', style=discord.ButtonStyle.secondary, row=4)
    async def close_label(self, i, b): await self.modal(i, 'ticket_close_label', '閉じるボタンを編集', 'ボタン文字', 80)
    @discord.ui.button(label='自動返信', emoji='💬', style=discord.ButtonStyle.secondary, row=4)
    async def auto_reply(self, i, b): await self.modal(i, 'ticket_first_reply', '最初のメッセージへの自動返信', '自動返信', 2000)

class Ticket(commands.Cog):
    def __init__(self, bot): self.bot = bot
    @app_commands.command(name='ticket-setup', description='チケットパネルを設置します')
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_ticket(self, interaction):
        c = cfg(interaction.guild.id)
        embed = discord.Embed(title=c['ticket_title'], description=c['ticket_message'], color=color(c['ticket_embed_color']))
        await interaction.channel.send(embed=embed, view=TicketPanelView(c))
        await interaction.response.send_message('✅ チケットパネルを設置しました。', ephemeral=True)
    @app_commands.command(name='ticket-edit', description='チケット設定を編集します')
    @app_commands.checks.has_permissions(administrator=True)
    async def edit_ticket(self, interaction):
        embed = discord.Embed(title='🎫 チケット設定', description='下のボタンからタイトル、説明文、色、挨拶、チャンネル名、カテゴリなどを編集できます。', color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, view=TicketSettingsView(), ephemeral=True)
    @app_commands.command(name='ticket-message', description='チケットパネル説明文を設定します')
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_message(self, interaction, message: str):
        set_guild_value(interaction.guild.id, 'ticket_message', message); await interaction.response.send_message('✅ 説明文を更新しました。', ephemeral=True)
    @app_commands.command(name='ticket-greeting', description='チケット作成時の挨拶を設定します')
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_greeting(self, interaction, message: str):
        set_guild_value(interaction.guild.id, 'ticket_greeting', message); await interaction.response.send_message('✅ 挨拶を更新しました。', ephemeral=True)
    @app_commands.command(name='ticket-name', description='チケットチャンネル名を設定します')
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_name(self, interaction, template: str):
        set_guild_value(interaction.guild.id, 'ticket_name', template); await interaction.response.send_message('✅ チャンネル名テンプレートを更新しました。', ephemeral=True)
    @app_commands.command(name='ticket-disable', description='チケット設定をリセットします')
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_disable(self, interaction):
        for k in ['ticket_category_id','ticket_staff_role_ids','ticket_support_categories','ticket_title','ticket_message','ticket_button_label','ticket_close_label','ticket_embed_color','ticket_greeting','ticket_name','ticket_first_reply']:
            set_guild_value(interaction.guild.id, k, None)
        await interaction.response.send_message('✅ チケット設定をリセットしました。', ephemeral=True)

class TicketMessageListener(commands.Cog):
    def __init__(self, bot): self.bot = bot
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild or not isinstance(message.channel, discord.TextChannel): return
        creator, replied = state(message.channel.topic)
        if not creator or replied or message.author.id != creator: return
        if not message.content.strip() and not message.attachments: return
        c = cfg(message.guild.id)
        if c['ticket_first_reply'].strip():
            try: await message.channel.send(replace_placeholders(c['ticket_first_reply'], message.author))
            except discord.HTTPException: return
        try: await message.channel.edit(topic=topic(creator, True))
        except discord.HTTPException: pass

async def setup(bot):
    await bot.add_cog(Ticket(bot))
    await bot.add_cog(TicketMessageListener(bot))
