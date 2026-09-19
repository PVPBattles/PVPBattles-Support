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
    "ticket_panel_description": "Need help?\nClick the button below to create a ticket.",
    "ticket_name": "ticket-{username}",
    "ticket_color": "#5865F2",
    "ticket_welcome": "こんにちは、{user}！\n\nチケットを作成していただきありがとうございます！\n至急スタッフが対応いたしますので、ご要件を記入した上でしばらくお待ちください！\n\nまた、夜間などは対応ができない可能性がございますので、あらかじめご了承ください！",
    "ticket_first_reply": "ご要件を確認いたしました！\nスタッフが対応いたしますので、しばらくお待ちください。",
}

def cfg(gid):
    c = get_guild_config(gid)
    for k, v in DEFAULTS.items(): c.setdefault(k, v)
    c.setdefault("ticket_support_categories", [dict(x) for x in DEFAULT_CATEGORIES])
    return c

def color(v):
    try: return discord.Color(int(str(v).replace("#", ""), 16))
    except: return discord.Color.blurple()

def clean_emoji(v):
    v = (v or "").strip()
    return v or None

def replace_vars(s, u):
    return s.replace("{username}", u.name).replace("{displayname}", u.display_name).replace("{userid}", str(u.id)).replace("{user}", u.mention)

def ticket_name(t, u):
    n = re.sub(r"[^a-z0-9_-]+", "-", replace_vars(t, u).lower())
    return re.sub(r"-+", "-", n).strip("-")[:95] or f"ticket-{u.id}"

def staff_roles(guild, c):
    ids = c.get("ticket_staff_role_ids", [])
    if not isinstance(ids, list): ids = []
    if not ids and c.get("ticket_staff_role_id"):
        try: ids = [int(c["ticket_staff_role_id"])]
        except: pass
    return [r for i in ids if (r := guild.get_role(int(i))) is not None]

def is_staff(member, c): return any(r in member.roles for r in staff_roles(member.guild, c))

def categories(c):
    out=[]
    for x in c.get("ticket_support_categories", [])[:25]:
        if isinstance(x, dict) and str(x.get("name", "")).strip():
            out.append({"name": str(x["name"]).strip()[:100], "emoji": clean_emoji(str(x.get("emoji", "")))})
    return out

def cat_text(x): return f"{x['emoji']} {x['name']}" if x.get("emoji") else x["name"]

class SupportSelect(discord.ui.Select):
    def __init__(self, cats):
        opts=[]
        for i,x in enumerate(cats[:25]):
            kw={"label":x["name"],"value":str(i)}
            if x.get("emoji"): kw["emoji"]=x["emoji"]
            opts.append(discord.SelectOption(**kw))
        if not opts: opts=[discord.SelectOption(label="Other",value="0",emoji="❓")]
        super().__init__(placeholder="Select Support Category", min_values=1, max_values=1, options=opts, custom_id="ticket:support")
    async def callback(self, interaction):
        if not interaction.guild: return
        c=cfg(interaction.guild.id); cats=categories(c)
        try: selected=cats[int(self.values[0])]
        except (ValueError,IndexError):
            await interaction.response.send_message("❌ This category is no longer available.", ephemeral=True); return
        saved=c.get("ticket_selected_categories", {})
        if not isinstance(saved,dict): saved={}
        saved[str(interaction.channel.id)]=selected["name"]
        set_guild_value(interaction.guild.id,"ticket_selected_categories",saved)
        await interaction.response.send_message(embed=discord.Embed(title="🎯 Support Category",description=f"**{cat_text(selected)}**\n\nSelected by {interaction.user.mention}",color=color(c["ticket_color"])))

class SupportView(discord.ui.View):
    def __init__(self,cats):
        super().__init__(timeout=None); self.add_item(SupportSelect(cats))

class CloseButton(discord.ui.Button):
    def __init__(self): super().__init__(label="Close Ticket",emoji="🔒",style=discord.ButtonStyle.danger,custom_id="ticket:close")
    async def callback(self,interaction):
        if not interaction.guild or not isinstance(interaction.user,discord.Member): return
        c=cfg(interaction.guild.id)
        if not is_staff(interaction.user,c):
            await interaction.response.send_message("❌ Only staff members can close this ticket.",ephemeral=True); return
        if (getattr(interaction.channel,"topic","") or "") == f"ticket_owner:{interaction.user.id}":
            await interaction.response.send_message("❌ The ticket creator cannot close this ticket.",ephemeral=True); return
        await interaction.response.send_message("🔒 Closing ticket...",ephemeral=True)
        try: await interaction.channel.delete(reason=f"Ticket closed by {interaction.user}")
        except (discord.Forbidden,discord.HTTPException): pass

class TicketCloseView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None); self.add_item(CloseButton())

class CreateButton(discord.ui.Button):
    def __init__(self): super().__init__(label="Create Ticket",emoji="🎫",style=discord.ButtonStyle.primary,custom_id="ticket:create")
    async def callback(self,interaction):
        if not interaction.guild or not isinstance(interaction.user,discord.Member): return
        g=interaction.guild; u=interaction.user; c=cfg(g.id)
        try: category=g.get_channel(int(c.get("ticket_category_id")))
        except: category=None
        if not isinstance(category,discord.CategoryChannel):
            await interaction.response.send_message("❌ The ticket category has not been configured.",ephemeral=True); return
        roles=staff_roles(g,c)
        if not roles:
            await interaction.response.send_message("❌ No staff roles have been configured.",ephemeral=True); return
        if any(ch.topic==f"ticket_owner:{u.id}" for ch in g.text_channels):
            ch=next(ch for ch in g.text_channels if ch.topic==f"ticket_owner:{u.id}")
            await interaction.response.send_message(f"❌ You already have an open ticket: {ch.mention}",ephemeral=True); return
        ow={g.default_role:discord.PermissionOverwrite(view_channel=False),u:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,attach_files=True,embed_links=True)}
        if g.me: ow[g.me]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,manage_channels=True,manage_messages=True)
        for r in roles: ow[r]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,attach_files=True,embed_links=True)
        try: ch=await g.create_text_channel(name=ticket_name(c["ticket_name"],u),category=category,overwrites=ow,topic=f"ticket_owner:{u.id}",reason=f"Ticket created by {u}")
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to create ticket channels.",ephemeral=True); return
        except discord.HTTPException:
            await interaction.response.send_message("❌ Failed to create the ticket channel.",ephemeral=True); return
        await interaction.response.send_message(f"✅ Ticket created: {ch.mention}",ephemeral=True)
        mentions=" ".join(r.mention for r in roles)
        e=discord.Embed(title="🎫 PVPBattles Support",description=replace_vars(c["ticket_welcome"],u),color=color(c["ticket_color"]))
        await ch.send(content=mentions,embed=e,allowed_mentions=discord.AllowedMentions(roles=True,users=True,everyone=False))
        await ch.send(embed=discord.Embed(title="🎯 Support Category",description="サポート内容を選択してください。\n下のメニューから該当するものを選んでください。",color=color(c["ticket_color"])),view=SupportView(categories(c)))
        await ch.send(view=TicketCloseView())

class TicketPanelView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None); self.add_item(CreateButton())

class RoleSetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180); self.add_item(RoleSetupSelect())

class RoleSetupSelect(discord.ui.RoleSelect):
    def __init__(self): super().__init__(placeholder="Select staff roles",min_values=1,max_values=25)
    async def callback(self,interaction):
        roles=list(self.values)
        set_guild_value(interaction.guild.id,"ticket_staff_role_ids",[r.id for r in roles])
        set_guild_value(interaction.guild.id,"ticket_staff_role_id",roles[0].id)
        await interaction.response.send_message("✅ Staff roles saved:\n"+"\n".join(r.mention for r in roles),ephemeral=True)

class AddCategoryModal(discord.ui.Modal,title="Add Support Category"):
    name=discord.ui.TextInput(label="Category Name",placeholder="Player Report",max_length=100)
    emoji=discord.ui.TextInput(label="Emoji",placeholder="🚨",required=False,max_length=100)
    async def on_submit(self,interaction):
        c=cfg(interaction.guild.id); cats=categories(c)
        name=str(self.name).strip()
        if len(cats)>=25:
            await interaction.response.send_message("❌ You can have up to 25 categories.",ephemeral=True); return
        if any(x["name"].lower()==name.lower() for x in cats):
            await interaction.response.send_message("❌ That category already exists.",ephemeral=True); return
        new={"name":name,"emoji":clean_emoji(str(self.emoji))}; cats.append(new)
        set_guild_value(interaction.guild.id,"ticket_support_categories",cats)
        await interaction.response.send_message(f"✅ Added: {cat_text(new)}",ephemeral=True)

class CategoryManageView(discord.ui.View):
    def __init__(self,cats):
        super().__init__(timeout=180); self.add_item(AddCategoryButton())
        if cats: self.add_item(RemoveCategorySelect(cats))

class AddCategoryButton(discord.ui.Button):
    def __init__(self): super().__init__(label="Add Category",emoji="➕",style=discord.ButtonStyle.success)
    async def callback(self,interaction): await interaction.response.send_modal(AddCategoryModal())

class RemoveCategorySelect(discord.ui.Select):
    def __init__(self,cats):
        opts=[]
        for i,x in enumerate(cats[:25]):
            kw={"label":x["name"],"value":str(i)}
            if x.get("emoji"): kw["emoji"]=x["emoji"]
            opts.append(discord.SelectOption(**kw))
        super().__init__(placeholder="Select a category to remove",min_values=1,max_values=1,options=opts)
    async def callback(self,interaction):
        c=cfg(interaction.guild.id); cats=categories(c)
        try: removed=cats.pop(int(self.values[0]))
        except (ValueError,IndexError):
            await interaction.response.send_message("❌ Invalid category.",ephemeral=True); return
        set_guild_value(interaction.guild.id,"ticket_support_categories",cats)
        await interaction.response.send_message(f"✅ Removed: {cat_text(removed)}",ephemeral=True)

class Ticket(commands.Cog):
    def __init__(self,bot): self.bot=bot

    @app_commands.command(name="ticket-setup",description="Create a ticket panel.")
    @app_commands.describe(channel="The channel where the ticket panel will be sent.")
    async def ticket_setup(self,interaction,channel:discord.TextChannel):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ You need Manage Server permission.",ephemeral=True); return
        c=cfg(interaction.guild.id)
        e=discord.Embed(title=c["ticket_panel_title"],description=c["ticket_panel_description"],color=color(c["ticket_color"]))
        await channel.send(embed=e,view=TicketPanelView())
        set_guild_value(interaction.guild.id,"ticket_panel_channel_id",channel.id)
        await interaction.response.send_message("✅ Ticket panel created!\n\nここからサポートカテゴリを追加・削除できます。",view=CategoryManageView(categories(c)),ephemeral=True)

    @app_commands.command(name="ticket-edit",description="Configure ticket category and staff roles.")
    async def ticket_edit(self,interaction,category:discord.CategoryChannel):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ You need Manage Server permission.",ephemeral=True); return
        set_guild_value(interaction.guild.id,"ticket_category_id",category.id)
        await interaction.response.send_message("👥 Select the staff roles that can manage tickets.",view=RoleSetupView(),ephemeral=True)

    @app_commands.command(name="ticket-category",description="Manage support categories inside tickets.")
    async def ticket_category(self,interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ You need Manage Server permission.",ephemeral=True); return
        await interaction.response.send_message("🎯 **Support Categories**\n\n"+"\n".join(f"{i+1}. {cat_text(x)}" for i,x in enumerate(categories(cfg(interaction.guild.id))))+"\n\n➕ Add Category で追加できます。",view=CategoryManageView(categories(cfg(interaction.guild.id))),ephemeral=True)

    @app_commands.command(name="ticket-category-reset",description="Reset support categories to default.")
    async def ticket_category_reset(self,interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ You need Manage Server permission.",ephemeral=True); return
        set_guild_value(interaction.guild.id,"ticket_support_categories",[dict(x) for x in DEFAULT_CATEGORIES])
        await interaction.response.send_message("✅ Support categories reset to default.",ephemeral=True)

    @app_commands.command(name="ticket-message",description="Edit ticket panel messages.")
    async def ticket_message(self,interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ You need Manage Server permission.",ephemeral=True); return
        await interaction.response.send_message("この版ではパネル文章編集は既存設定を維持します。",ephemeral=True)

    @app_commands.command(name="ticket-color",description="Change ticket embed color.")
    async def ticket_color(self,interaction,color_value:str):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ You need Manage Server permission.",ephemeral=True); return
        v=color_value.replace("#","")
        if len(v)!=6:
            await interaction.response.send_message("❌ Invalid color. Example: `#5865F2`",ephemeral=True); return
        try: int(v,16)
        except ValueError:
            await interaction.response.send_message("❌ Invalid color. Example: `#5865F2`",ephemeral=True); return
        set_guild_value(interaction.guild.id,"ticket_color",f"#{v.upper()}")
        await interaction.response.send_message(f"✅ Ticket color changed to `#{v.upper()}`.",ephemeral=True)

    @app_commands.command(name="ticket-disable",description="Disable ticket configuration.")
    async def ticket_disable(self,interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ You need Manage Server permission.",ephemeral=True); return
        for k in ("ticket_panel_channel_id","ticket_category_id","ticket_staff_role_id","ticket_staff_role_ids","ticket_selected_categories","ticket_first_reply_sent"):
            set_guild_value(interaction.guild.id,k,None)
        await interaction.response.send_message("✅ Ticket system configuration disabled.",ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self,message):
        if message.author.bot or not message.guild or not isinstance(message.author,discord.Member): return
        topic=getattr(message.channel,"topic","") or ""
        if not topic.startswith("ticket_owner:"): return
        c=cfg(message.guild.id)
        if is_staff(message.author,c): return
        sent=c.get("ticket_first_reply_sent",{})
        if not isinstance(sent,dict): sent={}
        key=str(message.channel.id)
        if sent.get(key): return
        await message.channel.send(c["ticket_first_reply"])
        sent[key]=True
        set_guild_value(message.guild.id,"ticket_first_reply_sent",sent)

async def setup(bot):
    await bot.add_cog(Ticket(bot))
