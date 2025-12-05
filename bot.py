# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button, Select
import os
import json
import datetime
import asyncio
from flask import Flask
from threading import Thread

# ---------------------------
# GLOBAL CONFIGURATION
# ---------------------------
# Apps requiring the two-step verification process (MUST be lowercase)
V2_APPS_LIST = ["bilibili", "hotstar", "vpn"] 

# Cooldown time in hours (168 hours = 7 days)
COOLDOWN_HOURS = 168

# Ticket operational hours (2:00 PM UTC to 11:59 PM UTC)
TICKET_START_HOUR_UTC = 14  # 2:00 PM UTC
TICKET_END_HOUR_UTC = 24    # Represents 00:00 (midnight) to include 11:59 PM UTC

TICKET_CREATION_STATUS = True 

# ---------------------------
# Environment Variables
# ---------------------------
TOKEN = os.getenv("DISCORD_TOKEN")
try:
    GUILD_ID = int(os.getenv("GUILD_ID"))
    TICKET_LOG_CHANNEL_ID = int(os.getenv("TICKET_LOG_CHANNEL_ID"))
    VERIFICATION_CHANNEL_ID = int(os.getenv("VERIFICATION_CHANNEL_ID"))
    
    # Optional Channels
    TICKET_PANEL_CHANNEL_ID = os.getenv("TICKET_PANEL_CHANNEL_ID")
    if TICKET_PANEL_CHANNEL_ID:
        TICKET_PANEL_CHANNEL_ID = int(TICKET_PANEL_CHANNEL_ID)

    INSTRUCTIONS_CHANNEL_ID = os.getenv("INSTRUCTIONS_CHANNEL_ID")
    if INSTRUCTIONS_CHANNEL_ID:
        INSTRUCTIONS_CHANNEL_ID = int(INSTRUCTIONS_CHANNEL_ID)
    
except (TypeError, ValueError) as e:
    raise ValueError(f"Missing or invalid required environment variable ID: {e}")

YOUTUBE_CHANNEL_URL = os.getenv("YOUTUBE_CHANNEL_URL")
if not YOUTUBE_CHANNEL_URL or not TOKEN:
    raise ValueError("DISCORD_TOKEN and YOUTUBE_CHANNEL_URL environment variables are required.")


# ---------------------------
# Load / Save Apps (JSON Database)
# ---------------------------
def load_apps():
    """Loads the app list (final links) from apps.json."""
    try:
        with open("apps.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        default_apps = {
            "spotify": "https://link-target.net/1438550/4r4pWdwOV2gK",
            "youtube": "https://example.com/youtube-download",
            "kinemaster": "https://link-center.net/1438550/dP4XtgqcsuU1",
            "hotstar": "https://final-link.com/hotstar-premium",
            "vpn": "https://final-link.com/vpn-premium", 
            "truecaller": "https://link-target.net/1438550/kvu1lPW7ZsKu",
            "bilibili": "https://final-link.com/bilibili-premium", 
        }
        print("Warning: apps.json not found. Creating file with default data.")
        with open("apps.json", "w") as f:
            json.dump(default_apps, f, indent=4)
        return default_apps

def save_apps(apps):
    """Saves the app list to apps.json."""
    try:
        with open("apps.json", "w") as f:
            json.dump(apps, f, indent=4)
        print("DEBUG: Successfully saved apps.json.")
    except Exception as e:
        print(f"CRITICAL ERROR: Failed to write to apps.json. Check hosting permissions: {e}")


# ---------------------------
# Load / Save V2 Links (New Data Source)
# ---------------------------
def load_v2_links():
    """Loads the V2 website links for the second verification step."""
    try:
        with open("v2_links.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print("Warning: v2_links.json not found. Creating file with default data.")
        v2_site_url = "https://verification2-djde.onrender.com"
        default_v2 = {
            "bilibili": v2_site_url, 
            "hotstar": v2_site_url, 
            "vpn": v2_site_url, 
        }
        with open("v2_links.json", "w") as f:
            json.dump(default_v2, f, indent=4)
        return default_v2

v2_links = load_v2_links()
# ---------------------------

# ---------------------------
# GLOBAL HELPER: Utility Functions
# ---------------------------
def get_app_emoji(app_key: str) -> str:
    """Assigns an appropriate emoji based on the app key (lowercase)."""
    
    app_key = app_key.lower()
    
    emoji_map = {
        "bilibili": "🅱️", 
        "spotify": "🎶", 
        "youtube": "📺", 
        "kinemaster": "✍️", 
        "hotstar": "⭐",
        "truecaller": "📞", 
        "castle": "🏰",
        "netflix": "🎬",
        "hulu": "🍿",
        "vpn": "🛡️",
        "prime": "👑",
        "editor": "✏️",
        "music": "🎵",
        "streaming": "📡",
        "photo": "📸",
        "file": "📁",
    }
    
    if app_key in emoji_map:
        return emoji_map[app_key]
    
    for keyword, emoji in emoji_map.items():
        if keyword in app_key:
            return emoji

    return "✨"

def is_ticket_time_allowed() -> bool:
    """Checks if the current day is Saturday AND the time is between 2:00 PM and 11:59 PM UTC."""
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    current_hour = now_utc.hour
    current_weekday = now_utc.weekday() # Monday is 0, Saturday is 5, Sunday is 6

    # 1. Check Day: Only allow on Saturday (5)
    if current_weekday != 5:
        return False

    # 2. Check Time: 14 <= hour < 24
    if TICKET_START_HOUR_UTC <= current_hour < TICKET_END_HOUR_UTC:
        return True
    
    return False

# ---------------------------
# Flask Keepalive Server
# ---------------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

# ---------------------------
# Bot Setup
# ---------------------------
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

cooldowns = {} 

# ---------------------------
# Helper Function for Transcripts
# ---------------------------
async def create_transcript(channel: discord.TextChannel) -> tuple[list[str], list[discord.Message]]:
    """Fetches channel history, splits into chunks, and returns messages list."""
    
    messages = [msg async for msg in channel.history(limit=None)]
    messages.reverse() 

    transcript_chunks = []
    current = ""

    for msg in messages:
        line = f"[{msg.created_at.replace(tzinfo=datetime.timezone.utc):%Y-%m-%d %H:%M:%S}] {msg.author.display_name} ({msg.author.id}): {msg.content}\n"
        for a in msg.attachments:
            line += f"📎 ATTACHMENT: {a.url}\n"

        if len(current) + len(line) > 4000:
            transcript_chunks.append(current)
            current = ""

        current += line + "\n"

    if current:
        transcript_chunks.append(current)
        
    return transcript_chunks, messages

# ---------------------------
# CORE TICKET CLOSURE LOGIC
# ---------------------------
async def perform_ticket_closure(channel: discord.TextChannel, closer: discord.User):
    """Performs logging and final deletion of the channel."""
    
    log_channel = bot.get_channel(TICKET_LOG_CHANNEL_ID)
    
    transcript_parts, messages = await create_transcript(channel)

    # Get Ticket Metadata
    ticket_opener = messages[0].author if messages else closer
    open_time = messages[0].created_at if messages else datetime.datetime.now(datetime.timezone.utc)
    close_time = datetime.datetime.now(datetime.timezone.utc)
    duration = close_time - open_time
    duration_str = str(duration).split('.')[0] 

    # Log Metadata (Single Embed)
    metadata_embed = discord.Embed(
        title=f"📜 TICKET TRANSCRIPT LOG — {channel.name}",
        description=f"Transcript for the ticket channel **{channel.name}** is attached below in multiple parts.",
        color=discord.Color.red()
    )
    metadata_embed.add_field(name="Ticket Opener", value=ticket_opener.mention, inline=True)
    metadata_embed.add_field(name="Ticket Closer", value=closer.mention, inline=True)
    metadata_embed.add_field(name="\u200b", value="\u200b", inline=True)
    
    metadata_embed.add_field(name="Time Opened", value=f"{open_time.strftime('%Y-%m-%d %H:%M:%S UTC')}", inline=False)
    metadata_embed.add_field(name="Time Closed", value=f"{close_time.strftime('%Y-%m-%d %H:%M:%S UTC')}", inline=False)
    metadata_embed.add_field(name="Ticket Duration", value=duration_str, inline=False)

    await log_channel.send(embed=metadata_embed)

    # Log Transcript Parts
    for i, part in enumerate(transcript_parts):
        embed = discord.Embed(
            title=f"📄 Transcript Data — Part {i+1}",
            description=part,
            color=discord.Color.blurple()
        )
        await log_channel.send(embed=embed)
    
    # Delete Channel (CRITICAL STEP)
    await channel.delete()

# ---------------------------
# CORE TICKET LOGIC (Shared by /ticket and Button)
# ---------------------------
async def create_new_ticket(interaction: discord.Interaction):
    """Handles the shared logic of checking status, cooldown, creating channel, and sending welcome message."""
    global TICKET_CREATION_STATUS

    # 1. Check Global/Clock Status
    if not TICKET_CREATION_STATUS or not is_ticket_time_allowed():
        
        closed_embed = discord.Embed(
            # UPDATED TEXT TO REFLECT NEW HOURS
            title="Ticket System Offline 💥",
            description=f"The premium ticket creation system is currently closed for maintenance or outside of operational hours (Saturday: {TICKET_START_HOUR_UTC}:00 to {TICKET_END_HOUR_UTC - 1}:59 UTC).",
            color=discord.Color.red()
        )
        await interaction.response.send_message(
            content="Ticket system shutting down... 🔴", 
            ephemeral=True
        )
        await asyncio.sleep(0.5) 
        
        return await interaction.edit_original_response(
            content=f"Ticket system closed! 💨",
            embed=closed_embed
        )

    # 2. Check Cooldown
    user = interaction.user
    now = datetime.datetime.now(datetime.timezone.utc)

    if user.id in cooldowns and cooldowns[user.id] > now:
        remaining = cooldowns[user.id] - now
        time_left_str = str(remaining).split('.')[0] 
        
        return await interaction.response.send_message(
            embed=discord.Embed(
                title="⏳ Cooldown Active - Please Wait",
                description=f"You recently opened a ticket. You can open your next ticket in:\n"
                            f"**`{time_left_str}`**",
                color=discord.Color.orange()
            ),
            ephemeral=True
        )
    
    await interaction.response.defer(ephemeral=True, thinking=True)

    cooldowns[user.id] = now + datetime.timedelta(hours=COOLDOWN_HOURS)

    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
    }

    channel_name = f"ticket-{interaction.user.id}"

    channel = await interaction.guild.create_text_channel(
        channel_name,
        overwrites=overwrites
    )

    # --- ENHANCED STYLISH WELCOME MESSAGE ---
    embed = discord.Embed(
        title="🌟 Welcome to the Premium Access Ticket Center! 🚀",
        description=f"Hello {user.mention}! Thank free for choosing our services. We are here to provide you with quick access to premium content. \n\n"
                    "**Please read the information below before proceeding.**",
        color=discord.Color.from_rgb(50, 200, 255)
    )

    if INSTRUCTIONS_CHANNEL_ID:
        embed.add_field(
            name="🔴 IMPORTANT: READ BEFORE PROCEEDING",
            value=f"Before selecting an app, you **MUST** go to {bot.get_channel(INSTRUCTIONS_CHANNEL_ID).mention} and follow the initial setup steps. Failure to comply will result in denial.",
            inline=False
        )
    
    embed.add_field(
        name="1️⃣ Server Benefits & Guarantee",
        value="We specialize in providing verified links to the best premium apps. All our links are regularly checked and guaranteed to work upon successful verification.",
        inline=False
    )
    
    two_step_message = "Depending on the app selected, you will either receive your link immediately after verification OR be directed to a short second security step."
    
    embed.add_field(
        name="2️⃣ How to Get Your App Link (1 or 2 Steps)",
        value=f"1. **Select the app** you want from the dropdown menu below.\n"
              f"2. Follow the verification steps (subscribing/screenshotting).\n"
              f"3. **Complete the final step** (1-step apps receive link now, 2-step apps require a short final security check).\n"
              f"**{two_step_message}**",
        inline=False
    )
    
    embed.add_field(
        name="3️⃣ Rules & Support",
        value="* **Be Polite:** Respect the staff members.\n"
              "* **No Spamming:** Only submit the required screenshot.\n"
              "* **Patience:** Verification takes time. Do not ping admins excessively.",
        inline=False
    )
    
    embed.set_footer(text="Your satisfaction is our priority! Select an app below to get started.")
    # --- END ENHANCED WELCOME MESSAGE ---


    await channel.send(f"Welcome {user.mention}! Please select an application below.", embed=embed, view=AppSelect(interaction.user))

    await interaction.followup.send(
        f"✅ Ticket created successfully! Head over to {channel.mention} to continue.",
        ephemeral=True
    )


# =============================
# APP SELECT VIEW
# =============================
class AppDropdown(Select):
    def __init__(self, options, user):
        super().__init__(
            placeholder="🛒 Tap here to select your desired Premium App...", 
            min_values=1, 
            max_values=1, 
            options=options,
            custom_id="app_select_dropdown"
        )
        self.user = user

    async def callback(self, interaction: discord.Interaction):
        # Acknowledge interaction immediately
        await interaction.response.defer() 
        
        app_key = self.values[0]
        app_name_display = app_key.title()
        app_emoji = get_app_emoji(app_key)
        
        is_v2_app = app_key in V2_APPS_LIST
        
        # --- LOCK THE SELECTION ---
        await interaction.message.edit(
            content=f"**✅ Selection Locked: {app_name_display}**\n\nSee the specific instructions below.",
            embed=None,
            view=None
        )
        # --------------------------

        # --- CONDITIONAL INSTRUCTION LOGIC ---
        if is_v2_app:
            v2_link = v2_links.get(app_key)
            
            if not v2_link:
                 embed_error = discord.Embed(
                    title="❌ Setup Error: V2 Link Missing",
                    description=f"Admin: V2 link for {app_name_display} is not configured in v2_links.json.", 
                    color=discord.Color.red()
                 )
                 return await interaction.followup.send(embed=embed_error, ephemeral=False)

            # V2 App: Detailed, specific instructions (V1 + V2 explained upfront)
            embed = discord.Embed(
                title=f"{app_emoji} 2-STEP VERIFICATION REQUIRED: {app_name_display} 🔒",
                description=f"You have selected **{app_name_display}**. This app requires two security steps. Please complete **Step 1** now.",
                color=discord.Color.from_rgb(255, 165, 0) # Orange/Gold
            )
            
            embed.add_field(
                name="➡️ STEP 1: INITIAL SUBSCRIPTION PROOF (V1)",
                value=f"1. Subscribe to our channel: **[Click Here]({YOUTUBE_CHANNEL_URL})**\n"
                      f"2. Take a clear **screenshot** of your subscription.\n"
                      f"3. **Post the screenshot** and type **`RASH TECH`** in the message.",
                inline=False
            )
            
            embed.add_field(
                name="➡️ STEP 2: FINAL KEY CHECK (V2)",
                value=f"This step is required **AFTER** Admin approves your Step 1 proof.\n"
                      f"1. Go to the final verification site: **[Click Here]({v2_link})**\n"
                      f"2. Download the file, find the secret code (e.g., **`{app_name_display} KEY`**).\n"
                      f"3. **Resubmit the screenshot** of the open file and type the exact code: **`{app_name_display} KEY: <code_here>`**.",
                inline=False
            )
        
        else:
            # Standard App: Brief, simple instructions (V1 only)
            embed = discord.Embed(
                title=f"{app_emoji} 1-STEP VERIFICATION REQUIRED: {app_name_display}",
                description=f"You have selected **{app_name_display}**. Please complete the single verification step below to receive your link.",
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="➡️ STEP 1: INITIAL SUBSCRIPTION PROOF (V1)",
                value=f"1. Subscribe to our channel: **[Click Here]({YOUTUBE_CHANNEL_URL})**\n"
                      f"2. Take a clear **screenshot** of your subscription.\n"
                      f"3. **Post the screenshot** and type **`RASH TECH`**. The bot will send your final link upon approval.",
                inline=False
            )
            
        await interaction.followup.send(embed=embed, ephemeral=False)


class AppSelect(View):
    def __init__(self, user):
        super().__init__(timeout=1800)
        
        current_apps = load_apps()
        
        options = []
        for app_key in current_apps.keys():
            app_name_display = app_key.title()
            
            emoji = get_app_emoji(app_key)
            
            options.append(
                discord.SelectOption(
                    label=f"{app_name_display} — Instant Access", 
                    value=app_key,
                    description=f"Secure your link for {app_name_display} Premium features.",
                    emoji=emoji
                )
            )
        
        if options:
            self.add_item(AppDropdown(options, user))
        else:
            self.add_item(
                discord.ui.Button(label="No Apps Available Yet", style=discord.ButtonStyle.grey, disabled=True)
            )


# =============================
# CREATE TICKET BUTTON VIEW
# =============================
class TicketPanelButton(View):
    def __init__(self):
        super().__init__(timeout=None) 

    @discord.ui.button(
        label="Create New Ticket",
        style=discord.ButtonStyle.blurple,
        emoji="📩",
        custom_id="persistent_create_ticket_button" 
    )
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await create_new_ticket(interaction)
        except discord.errors.Forbidden:
            await interaction.response.send_message(
                "❌ Error: I lack necessary permissions (e.g., Manage Channels or Send Messages) to create your ticket.", 
                ephemeral=True
            )
        except Exception as e:
            print(f"CRITICAL ERROR in Ticket Creation Button: {e}")
            
            if not interaction.response.is_done():
                 await interaction.response.send_message(
                    "❌ An unexpected error occurred while processing your ticket request. Please notify an administrator.", 
                    ephemeral=True
                )

# =============================
# CLOSE TICKET VIEW
# =============================
class CloseTicketView(View):
    def __init__(self):
        super().__init__(timeout=None)
         @discord.ui.button(
        label="🔒 Close Ticket",style=discord.ButtonStyle.red,custom_id="persistent_close_ticket_button" 
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        
        await interaction.response.send_message("Initiating 5-second countdown to close ticket... ⏳", ephemeral=True)
        
        for i in range(5, 0, -1):
            content = f"Ticket closing in **{i}** seconds... 🗑️"
            await interaction.edit_original_response(content=content)
            await asyncio.sleep(1)

        await interaction.edit_original_response(content="Ticket processing transcript and deleting now. 💨")
        
        await perform_ticket_closure(interaction.channel, interaction.user) 


# =============================
# VERIFICATION VIEW
# =============================
class VerificationView(View):
    def __init__(self, ticket_channel, user, app_name_key, screenshot_url):
        super().__init__(timeout=3600) 
        self.ticket_channel = ticket_channel
        self.user = user
        self.app_name_key = app_name_key
        self.screenshot_url = screenshot_url

    @discord.ui.button(label="✅ Verify", style=discord.ButtonStyle.green, custom_id="verify_button")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ You do not have permission to verify.", ephemeral=True)

        app_key = self.app_name_key
        user = self.user
        app_name_display = app_key.title()
        
        # --- PATH A: V2 (Multi-Step Verification) ---
        if self.app_name_key in V2_APPS_LIST:
            
            links_v2 = load_v2_links()
            v2_link = links_v2.get(self.app_name_key)
            
            if not v2_link:
                return await interaction.response.send_message(f"❌ Error: V2 link not configured for {app_name_display}.", ephemeral=True)

            # V1 is manually approved. Now send V2 prompt to user.
            embed_prompt = discord.Embed(
                title=f"✅ V1 Proof Approved for {app_name_display}!",
                description=f"Initial subscription proof verified by {interaction.user.mention}. \n\n"
                            "**{self.user.mention}** please proceed to the next step using the link and instructions provided when you selected the app.",
                color=discord.Color.gold()
            )
            
            class V2LinkView(View):
                def __init__(self, url):
                    super().__init__(timeout=None)
                    self.add_item(discord.ui.Button(label=f"GO TO V2 VERIFICATION SITE", url=url, style=discord.ButtonStyle.link))
            
            await self.ticket_channel.send(embed=embed_prompt, view=V2LinkView(v2_link))
            
            # Update verification panel message and disable button
            self.stop()
            await interaction.message.edit(content=f"✅ **V1 Approved:** Waiting for V2 proof from {self.user.mention}.", view=None)

            return await interaction.response.send_message(f"✅ V1 approved. Waiting for V2 screenshot.", ephemeral=True)

        else:
            # --- PATH B: STANDARD (Single-Step Verification) ---
            
            await deliver_and_close(self.ticket_channel, user, app_key)
            
            # Update verification panel message and disable button
            self.stop()
            await interaction.message.edit(content=f"✅ **VERIFIED:** Link sent to {user.mention}.", view=None)
            
            await interaction.response.send_message("Verified! Link sent.", ephemeral=True)


    @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.red, custom_id="decline_button")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ You do not have permission to decline.", ephemeral=True)
            
        app_name_display = self.app_name_key.title()
        
        embed = discord.Embed(
            title="❌ Verification Declined",
            description=f"Your screenshot proof for **{app_name_display}** was declined by {interaction.user.mention}. Please resubmit a valid, full screenshot in the ticket.",
            color=discord.Color.red()
        )

        await self.ticket_channel.send(embed=embed)
        
        self.stop()
        await interaction.message.edit(content="❌ **DECLINED:** User has been notified.", view=None)
        
        await interaction.response.send_message("Declined! User notified.", ephemeral=True)
    # =============================
# SLASH COMMANDS (ADMIN GROUP)
# =============================

# --- /verify_v2_final ---
@bot.tree.command(name="verify_v2_final", description="✅ Complete Verification 2 and send the final premium link.")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(manage_guild=True)
async def verify_v2_final(interaction: discord.Interaction, app_name: str, user: discord.Member):

    app_key = app_name.lower()
    app_name_display = app_key.title()
    apps = load_apps()
    link = apps.get(app_key)

    if app_key not in V2_APPS_LIST:
        return await interaction.response.send_message("❌ Error: This command is only for Verification 2 apps.", ephemeral=True)
    
    if not link:
        return await interaction.response.send_message(f"❌ Error: Final link not found for {app_name_display}.", ephemeral=True)
    
    # Find the ticket channel
    ticket_channel = discord.utils.get(
        interaction.guild.channels,
        name=f"ticket-{user.id}"
    )
    if not ticket_channel:
        return await interaction.response.send_message(f"❌ User has no open ticket.", ephemeral=True)

    # Use the shared delivery logic
    await deliver_and_close(ticket_channel, user, app_key)
    
    await interaction.response.send_message(f"✅ Final link delivered to {ticket_channel.mention}", ephemeral=True)


# --- /add_app ---
@bot.tree.command(name="add_app", description="➕ Add a new premium app to the database")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(manage_guild=True)
async def add_app(interaction: discord.Interaction, app_name: str, app_link: str):
    
    await interaction.response.defer(ephemeral=True)
    
    app_key = app_name.lower()
    
    current_apps = load_apps()
    current_apps[app_key] = app_link
    save_apps(current_apps)
    
    embed = discord.Embed(
        title="✅ App Successfully Added to Database",
        description=f"The application **{app_name.title()}** is now available for users to select.\n\n"
                    f"🔗 **Direct Link:** [Click Here]({app_link})",
        color=discord.Color.green()
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


# --- /remove_app ---
@bot.tree.command(name="remove_app", description="➖ Remove an app from the database")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(manage_guild=True)
async def remove_app(interaction: discord.Interaction, app_name: str):
    
    await interaction.response.defer(ephemeral=True)
    
    app_key = app_name.lower()
    
    current_apps = load_apps()
    
    if app_key not in current_apps:
        embed = discord.Embed(
            title="❌ App Not Found",
            description=f"App **{app_name.title()}** not found in the list.",
            color=discord.Color.red()
        )
        return await interaction.followup.send(embed=embed, ephemeral=True)
        
    del current_apps[app_key]
    save_apps(current_apps)
    
    embed = discord.Embed(
        title="🗑️ App Permanently Removed",
        description=f"The application **{app_name.title()}** has been successfully removed from the database and will no longer appear in the ticket dropdown.",
        color=discord.Color.red()
    )
    await interaction.followup.send(embed=embed, ephemeral=True)

# --- /view_apps ---
@bot.tree.command(name="view_apps", description="📋 View all applications and their links in the database")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(manage_guild=True)
async def view_apps(interaction: discord.Interaction):
    
    await interaction.response.defer(ephemeral=True)
    
    current_apps = load_apps()
    
    if not current_apps:
        embed = discord.Embed(
            title="⚠️ No Apps Found",
            description="The `apps.json` file is empty. Use `/add_app` to populate the list.",
            color=discord.Color.orange()
        )
        return await interaction.followup.send(embed=embed, ephemeral=True)

    app_list_str = ""
    for app_key, link in current_apps.items():
        app_list_str += f"**{app_key.title()}**: [Link]({link})\n"

    embed = discord.Embed(
        title="📋 Current Premium Apps List",
        description="Below are all applications currently available in the ticket selection:",
        color=discord.Color.green()
    )
    embed.add_field(name="App Name & Link", value=app_list_str, inline=False)
    
    await interaction.followup.send(embed=embed, ephemeral=True)


# --- /remove_cooldown ---
@bot.tree.command(name="remove_cooldown", description="🧹 Remove a user's ticket cooldown")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(manage_guild=True)
async def remove_cooldown(interaction: discord.Interaction, user: discord.Member):

    await interaction.response.defer(ephemeral=True)

    if user.id in cooldowns:
        del cooldowns[user.id]

        embed = discord.Embed(
            title="✅ Cooldown Removed",
            description=f"The 48-hour cooldown for {user.mention} has been manually cleared. They can now create a new ticket immediately. 🔓",
            color=discord.Color.green()
        )
    else:
        embed = discord.Embed(
            title="ℹ️ No Active Cooldown Found",
            description=f"User {user.mention} currently has no ticket cooldown active.",
            color=discord.Color.blue()
        )
    
    await interaction.followup.send(embed=embed, ephemeral=True)


# --- /force_close ---
@bot.tree.command(name="force_close", description="🔒 Force close a specific ticket channel (or current one)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.describe(channel="Optional: Specify a ticket channel to close.")
async def force_close(interaction: discord.Interaction, channel: discord.TextChannel = None): 

    target_channel = channel or interaction.channel

    if not isinstance(target_channel, discord.TextChannel) or not target_channel.name.startswith("ticket-"):
        return await interaction.response.send_message(
            "❌ This command must be used inside a ticket channel, or you must specify a valid ticket channel (e.g., `/force_close channel:#ticket-123`).",
            ephemeral=True
        )

    await interaction.response.defer(ephemeral=True, thinking=True)
    
    await interaction.edit_original_response(content=f"Preparing to force close {target_channel.mention}...")

    await perform_ticket_closure(target_channel, interaction.user) 
    
    try:
        await interaction.followup.send(f"✅ Force close successful! {target_channel.name} is deleted.", ephemeral=True)
    except:
        pass


# --- /send_app ---
@bot.tree.command(name="send_app", description="📤 Send a premium app link to a user's ticket (legacy/manual send)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(manage_guild=True)
async def send_app(interaction: discord.Interaction, app_name: str, user: discord.Member):

    app_key = app_name.lower()
    app_name_display = app_name.title()

    apps = load_apps()

    if app_key not in apps:
        return await interaction.response.send_message(f"❌ App **{app_name_display}** not found.", ephemeral=True)

    link = apps[app_key]

    ticket_channel = discord.utils.get(
        interaction.guild.channels,
        name=f"ticket-{user.id}"
    )

    if not ticket_channel:
        return await interaction.response.send_message(
            f"❌ User has no open ticket named ticket-{user.id}.",
            ephemeral=True
        )

    embed = discord.Embed(
        title="✨ Premium App Delivered!",
        description=f"Here is your link for **{app_name_display}**:\n[Click Here]({link})",
        color=discord.Color.green()
    )

    await ticket_channel.send(embed=embed)
    await ticket_channel.send(
        embed=discord.Embed(
            title="🎉 Service Completed",
            description="If you're all set, close the ticket using the button below.",
            color=discord.Color.green()
        ),
        view=CloseTicketView()
    )

    await interaction.response.send_message("Link sent to the ticket!", ephemeral=True)

# --- /view_tickets ---
@bot.tree.command(name="view_tickets", description="📊 View number of currently open tickets")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(manage_channels=True)
async def view_tickets(interaction: discord.Interaction):

    open_tickets = [
        c for c in interaction.guild.text_channels
        if c.name.startswith("ticket-")
    ]

    embed = discord.Embed(
        title="🎟️ Open Ticket Overview",
        description=f"Currently open tickets: **{len(open_tickets)}**",
        color=discord.Color.blurple()
    )

    if open_tickets:
        ticket_mentions = "\n".join(f"📌 {c.mention}" for c in open_tickets[:20])
        if len(open_tickets) > 20:
             ticket_mentions += f"\n...and {len(open_tickets) - 20} more."
             
        embed.add_field(
            name="Active Ticket Channels",
            value=ticket_mentions,
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- /refresh_panel ---
@bot.tree.command(name="refresh_panel", description="🔄 Deletes and resends the ticket creation panel.")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(manage_guild=True)
async def refresh_panel(interaction: discord.Interaction):
    
    if not TICKET_PANEL_CHANNEL_ID:
        return await interaction.response.send_message("❌ Error: TICKET_PANEL_CHANNEL_ID is not configured.", ephemeral=True)

    await interaction.response.defer(ephemeral=True, thinking=True)
    
    await setup_ticket_panel(force_resend=True)
    
    await interaction.followup.send("✅ Ticket panel refreshed and sent with the latest app list.", ephemeral=True)
    # =============================
# SLASH COMMANDS (USER/GENERAL GROUP)
# =============================

# --- /ticket ---
@bot.tree.command(name="ticket", description="🎟️ Create a support ticket")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def ticket(interaction: discord.Interaction):
    await create_new_ticket(interaction)


# =============================
# ON MESSAGE — SCREENSHOT + APP DETECTION
# =============================
@bot.event
async def on_message(message):

    if message.author.bot or not message.channel.name.startswith("ticket-"):
        return

    content_upper = message.content.upper()
    content_lower = message.content.lower()
    
    apps = load_apps()
    matched_app_key = next((key for key in apps if key in content_lower), None)
    has_attachment = bool(message.attachments)
    
    # We only proceed if an app key is mentioned AND an attachment exists
    if matched_app_key and has_attachment:
        
        app_key = matched_app_key
        app_name_display = app_key.title()
        screenshot = message.attachments[0].url
        ver_channel = bot.get_channel(VERIFICATION_CHANNEL_ID)
        is_v2_app = app_key in V2_APPS_LIST
        
        # --- CHECK 1: V2 Final Screenshot Submission ---
        v2_key_word = f"{app_name_display.upper()} KEY" 
        is_v2_verified = v2_key_word in content_upper
        
        if is_v2_app and is_v2_verified:
            # SUCCESS PATH: V2 Proof Confirmed!
            
            embed = discord.Embed(
                title=f"🎉 V2 Proof Received for {app_name_display}!",
                description=f"Final proof confirmed by keyword check. The process is complete.\n\n"
                            f"✅ **Admin Action Required:** Review the attached screenshot and use the `/verify_v2_final app_name:{app_key}` to send the final link.",
                color=discord.Color.green()
            )
            embed.set_image(url=screenshot)
            await ver_channel.send(embed=embed)
            
            await message.channel.send(
                embed=discord.Embed(
                    title="✅ Upload Successful! Final Step Proof Received.",
                    description="Thank you! The final verification proof has been forwarded to the Admin for review. You will receive your link shortly. ⏳",
                    color=discord.Color.blue()
                )
            )
            return

        # --- CHECK 2: V1 Subscription Proof Submission ---
        # Look for 'RASH TECH' keyword for V1 proof
        is_rash_tech_verified = "RASH TECH" in content_upper

        if is_rash_tech_verified:
            # V1 Proof is valid—forward to admin for manual button approval
            
            embed = discord.Embed(
                title="📸 Verification Proof Received!",
                description=f"User {message.author.mention} submitted proof for **{app_name_display}**.",
                color=discord.Color.yellow()
            )
            embed.set_image(url=screenshot)
            
            # Send the V1 verification panel with buttons
            await ver_channel.send(
                embed=embed,
                view=VerificationView(message.channel, message.author, app_key, screenshot)
            )
            
            # Give immediate user feedback
            await message.channel.send(
                embed=discord.Embed(
                    title="✅ Upload Successful! 🎉",
                    description="Thank you for providing proof! Please wait patiently while the **Owner/Admin** verifies your screenshot. Once verified, you will receive your app link here. ⏳",
                    color=discord.Color.blue()
                )
            )
            return
        
        # --- CHECK 3: Failed Keyword Check ---
        else:
            # Failed V1 (Security Keyword) check
            
            required_keywords = ["RASH TECH"]
            if is_v2_app:
                required_keywords.append(f"{app_name_display.upper()} KEY")
                
            required_keyword_str = ' or '.join(f"**`{kw}`**" for kw in required_keywords)

            embed = discord.Embed(
                title="⚠️ Security Check Failed: Keyword Missing",
                description=f"You must include the required security keyword (**{required_keyword_str}**) in your message along with the screenshot. This confirms you read the instructions.",
                color=discord.Color.red()
            )
            return await message.channel.send(embed=embed)


    # If app name was mentioned but no attachment was found
    elif matched_app_key and not has_attachment:
         await message.channel.send(
            embed=discord.Embed(
                title="📷 Screenshot Required",
                description=f"You mentioned **{app_name_display}**. Please ensure you upload the screenshot along with the keyword.",
                color=discord.Color.orange()
            )
        )
    
    await bot.process_commands(message)

# ---------------------------
# STARTUP FUNCTIONS
# ---------------------------

async def setup_ticket_panel(force_resend=False):
    """Finds or sends the persistent ticket creation button."""
    if not TICKET_PANEL_CHANNEL_ID:
        print("WARNING: TICKET_PANEL_CHANNEL_ID is not set. Skipping ticket panel setup.")
        return

    channel = bot.get_channel(TICKET_PANEL_CHANNEL_ID)
    if not channel:
        print(f"ERROR: Could not find ticket panel channel with ID {TICKET_PANEL_CHANNEL_ID}")
        return

    panel_embed = discord.Embed(
        title="📩 Need a Premium App Link? Create a Ticket!",
        description="Click the button below to start the verification process and receive your requested premium app link. This will open a private channel for you.",
        color=discord.Color.dark_teal()
    )
    
    try:
        panel_message_found = False
        panel_message = None 

        async for message in channel.history(limit=5):
            if message.author == bot.user and message.components:
                if message.components[0].children[0].custom_id == "persistent_create_ticket_button":
                    panel_message_found = True
                    panel_message = message
                    break
        
        if panel_message_found and force_resend:
            await panel_message.delete()
            panel_message_found = False
            print("Deleted old ticket panel message due to /refresh_panel command.")

        if not panel_message_found:
            await channel.send(embed=panel_embed, view=TicketPanelButton())
            print("Sent new persistent ticket panel.")

    except discord.Forbidden:
        print("ERROR: Missing permissions to read or send messages in the ticket panel channel.")
    except Exception as e:
        print(f"An unexpected error occurred during panel setup: {e}")


# =============================
# ON READY
# =============================
@bot.event
async def on_ready():
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))

    # Register persistent views
    bot.add_view(CloseTicketView())
    bot.add_view(TicketPanelButton())
    
    await setup_ticket_panel()

    print(f"🟢 Bot logged in successfully as {bot.user}")


# =============================
# RUN BOT (Protected Initialization)
# =============================
if __name__ == "__main__":
    
    # 1. Start Flask thread (only once)
    Thread(target=run_flask).start()
    
    # 2. Start the Discord client (only once)
    bot.run(TOKEN)
