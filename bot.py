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
# Environment Variables
# ---------------------------
TOKEN = os.getenv("DISCORD_TOKEN")
try:
    GUILD_ID = int(os.getenv("GUILD_ID"))
    TICKET_LOG_CHANNEL_ID = int(os.getenv("TICKET_LOG_CHANNEL_ID"))
    VERIFICATION_CHANNEL_ID = int(os.getenv("VERIFICATION_CHANNEL_ID"))
except (TypeError, ValueError) as e:
    raise ValueError(f"Missing or invalid required environment variable ID: {e}")

YOUTUBE_CHANNEL_URL = os.getenv("YOUTUBE_CHANNEL_URL")
if not YOUTUBE_CHANNEL_URL or not TOKEN:
    raise ValueError("DISCORD_TOKEN and YOUTUBE_CHANNEL_URL environment variables are required.")


# ---------------------------
# Load / Save Apps (JSON Database)
# ---------------------------
def load_apps():
    """Loads the app list from apps.json."""
    try:
        with open("apps.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        # Define a default structure based on your data if file is missing
        default_apps = {
            "spotify": "https://link-target.net/1438550/4r4pWdwOV2gK",
            "youtube": "https://example.com/youtube-download",
            "kinemaster": "https://link-center.net/1438550/dP4XtgqcsuU1",
            "hotstar": "https://link-target.net/1438550/WEPSuAD5cl5A",
            "truecaller": "https://link-target.net/1438550/kvu1lPW7ZsKu",
            "castle": "https://example.com/castle-download"
        }
        print("Warning: apps.json not found. Using default data and creating file.")
        with open("apps.json", "w") as f:
            json.dump(default_apps, f, indent=4)
        return default_apps

def save_apps(apps):
    """Saves the app list to apps.json."""
    with open("apps.json", "w") as f:
        json.dump(apps, f, indent=4)

apps = load_apps()

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

# Cooldowns stores timezone-aware datetime objects
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
        # Ensure consistent time format in transcript
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


# =============================
# APP SELECT VIEW
# =============================
class AppDropdown(Select):
    def __init__(self, options, user):
        super().__init__(
            placeholder="✨ Select the Premium App you need...", 
            min_values=1, 
            max_values=1, 
            options=options,
            custom_id="app_select_dropdown"
        )
        self.user = user

    async def callback(self, interaction: discord.Interaction):
        app_key = self.values[0]
        app_name_display = app_key.title()
        
        app_emoji = {
            "spotify": "🎧", 
            "youtube": "▶️", 
            "kinemaster": "🎬", 
            "hotstar": "📺",
            "truecaller": "📞", 
            "castle": "🏰"
        }.get(app_key, "💎")

        embed = discord.Embed(
            title=f"{app_emoji} Verification Process for {app_name_display} - 3 Steps to Success!",
            description=f"Welcome to the final stage for your **{app_name_display}** Premium access! Follow these steps carefully:\n\n"
                        "1️⃣ **SUBSCRIBE:** You must be subscribed to our official channel.\n"
                        "2️⃣ **SCREENSHOT:** Take a clear, full screenshot of your subscription proof.\n"
                        "3️⃣ **UPLOAD:** **Send the screenshot** in this ticket now. Please do not type any additional text.\n\n"
                        f"⏳ Once uploaded, the **Owner/Admin** will review your proof. This may take a few minutes.\n"
                        f"🔗 **[Click Here to Subscribe]({YOUTUBE_CHANNEL_URL})**",
            color=discord.Color.blue()
        )

        await interaction.response.send_message(embed=embed, ephemeral=False)


class AppSelect(View):
    def __init__(self, user):
        super().__init__(timeout=1800)
        
        current_apps = load_apps()
        
        options = []
        for app_key in current_apps.keys():
            app_name_display = app_key.title()
            
            emoji = {
                "spotify": "🎧", 
                "youtube": "▶️", 
                "kinemaster": "🎬", 
                "hotstar": "📺",
                "truecaller": "📞", 
                "castle": "🏰"
            }.get(app_key, "💎")
            
            options.append(
                discord.SelectOption(
                    label=f"🌟 {app_name_display} Premium Access", 
                    value=app_key,
                    description=f"Instantly request the link for {app_name_display} access.",
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
# CLOSE TICKET VIEW
# =============================
class CloseTicketView(View):
    def __init__(self):
        super().__init__(timeout=None) 

    @discord.ui.button(
        label="🔒 Close Ticket",
        style=discord.ButtonStyle.red,
        custom_id="persistent_close_ticket_button" 
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        
        await interaction.response.send_message("Initiating 5-second countdown to close ticket... ⏳", ephemeral=True)
        
        # --- COUNTDOWN LOGIC ---
        for i in range(5, 0, -1):
            content = f"Ticket closing in **{i}** seconds... 🗑️"
            await interaction.edit_original_response(content=content)
            await asyncio.sleep(1)

        await interaction.edit_original_response(content="Ticket processing transcript and deleting now. 💨")
        
        # --- CLOSING AND LOGIC ---
        
        log_channel = bot.get_channel(TICKET_LOG_CHANNEL_ID)
        
        # Collect Transcript and Message Data
        transcript_parts, messages = await create_transcript(interaction.channel)

        # Get Ticket Metadata
        ticket_opener = messages[0].author if messages else interaction.user
        open_time = messages[0].created_at if messages else datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
        close_time = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
        duration = close_time - open_time
        
        duration_str = str(duration).split('.')[0] 

        # Log Metadata (Single Embed)
        metadata_embed = discord.Embed(
            title=f"📜 TICKET TRANSCRIPT LOG — {interaction.channel.name}",
            description=f"Transcript for the ticket channel **{interaction.channel.name}** is attached below in multiple parts.",
            color=discord.Color.red()
        )
        metadata_embed.add_field(name="Ticket Opener", value=ticket_opener.mention, inline=True)
        metadata_embed.add_field(name="Ticket Closer", value=interaction.user.mention, inline=True)
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
        
        # Delete Channel
        await interaction.channel.delete()


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

        apps = load_apps()
        app_link = apps.get(self.app_name_key)
        app_name_display = self.app_name_key.title()

        if not app_link:
            return await interaction.response.send_message("❌ App not found.", ephemeral=True)

        embed = discord.Embed(
            title="✅ Verification Approved! Access Granted!",
            description=f"Congratulations, {self.user.mention}! Your verification for **{app_name_display}** has been approved by {interaction.user.mention} (Admin/Owner).\n\n"
                        f"➡️ **[CLICK HERE FOR YOUR PREMIUM APP LINK]({app_link})** ⬅️\n\n"
                        "Please use the link immediately.",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=self.user.display_avatar.url)

        await self.ticket_channel.send(embed=embed)

        try:
            await self.user.send(embed=embed)
        except discord.Forbidden:
            await self.ticket_channel.send("⚠ User has DMs disabled. Link sent only in the channel.")

        await self.ticket_channel.send(
            embed=discord.Embed(
                title="🎉 Service Completed — Time to Close!",
                description="We hope you received your premium link! Please close the ticket using the button below.",
                color=discord.Color.green(),
            ),
            view=CloseTicketView()
        )
        
        self.stop()
        await interaction.message.edit(content="✅ **VERIFIED:** Link has been sent.", view=None)

        await interaction.response.send_message("Verified! Link sent to user and ticket channel.", ephemeral=True)

    @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.red, custom_id="decline_button")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ You do not have permission to decline.", ephemeral=True)
            
        app_name_display = self.app_name_key.title()
        
        embed = discord.Embed(
            title="❌ Verification Declined",
            description=f"Your screenshot proof for **{app_name_display}** was declined by {interaction.user.mention}. This usually means:\n"
                        "1. The subscription proof was incomplete.\n"
                        "2. The image was unclear/blurry.\n"
                        "Please resubmit a valid, full screenshot in the ticket.",
            color=discord.Color.red()
        )

        await self.ticket_channel.send(embed=embed)
        
        self.stop()
        await interaction.message.edit(content="❌ **DECLINED:** User has been notified.", view=None)
        
        await interaction.response.send_message("Declined! User notified.", ephemeral=True)


# =============================
# SLASH COMMANDS (ADMIN GROUP)
# =============================

# --- /add_app ---
@bot.tree.command(name="add_app", description="➕ Add a new premium app to the database")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(manage_guild=True)
async def add_app(interaction: discord.Interaction, app_name: str, app_link: str):
    
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
    await interaction.response.send_message(embed=embed, ephemeral=True)


# --- /remove_app ---
@bot.tree.command(name="remove_app", description="➖ Remove an app from the database")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(manage_guild=True)
async def remove_app(interaction: discord.Interaction, app_name: str):
    
    app_key = app_name.lower()
    
    current_apps = load_apps()
    
    if app_key not in current_apps:
        return await interaction.response.send_message(f"❌ App **{app_name.title()}** not found in the list. Please check the spelling.", ephemeral=True)
        
    del current_apps[app_key]
    save_apps(current_apps)
    
    embed = discord.Embed(
        title="🗑️ App Permanently Removed",
        description=f"The application **{app_name.title()}** has been successfully removed from the database and will no longer appear in the ticket dropdown.",
        color=discord.Color.red()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- /view_apps ---
@bot.tree.command(name="view_apps", description="📋 View all applications and their links in the database")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(manage_guild=True)
async def view_apps(interaction: discord.Interaction):
    
    current_apps = load_apps()
    
    if not current_apps:
        embed = discord.Embed(
            title="⚠️ No Apps Found",
            description="The `apps.json` file is empty. Use `/add_app` to populate the list.",
            color=discord.Color.orange()
        )
        return await interaction.response.send_message(embed=embed, ephemeral=True)

    app_list_str = ""
    for app_key, link in current_apps.items():
        app_list_str += f"**{app_key.title()}**: [Link]({link})\n"

    embed = discord.Embed(
        title="📋 Current Premium Apps List",
        description="Below are all applications currently available in the ticket selection:",
        color=discord.Color.green()
    )
    embed.add_field(name="App Name & Link", value=app_list_str, inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)
    

# --- /remove_cooldown ---
@bot.tree.command(name="remove_cooldown", description="🧹 Remove a user's ticket cooldown")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(manage_guild=True)
async def remove_cooldown(interaction: discord.Interaction, user: discord.Member):

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
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


# --- /force_close (FIXED CONTEXT) ---
@bot.tree.command(name="force_close", description="🔒 Force close a specific ticket channel (or current one)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.describe(channel="Optional: Specify a ticket channel to close.")
async def force_close(interaction: discord.Interaction, channel: discord.TextChannel = None): 

    # Determine the target channel
    target_channel = channel or interaction.channel

    if not isinstance(target_channel, discord.TextChannel) or not target_channel.name.startswith("ticket-"):
        return await interaction.response.send_message(
            "❌ This command must be used inside a ticket channel, or you must specify a valid ticket channel (e.g., `/force_close channel:#ticket-123`).",
            ephemeral=True
        )

    await interaction.response.defer(ephemeral=True, thinking=True)
    
    # Create a temporary interaction object using the target channel for the close logic
    class ForceCloseInteraction:
        def __init__(self, interaction, channel):
            self.user = interaction.user
            self.guild = interaction.guild
            self.response = interaction.followup
            self.followup = interaction.followup
            self.channel = channel
            
        async def edit_original_response(self, content):
            await interaction.edit_original_response(content=content)

        async def send_message(self, *args, **kwargs):
            # This is primarily used for the final confirmation message, which must go to the followup
            await interaction.followup.send(*args, **kwargs)

    # Send initial message which will be edited by the countdown
    await interaction.edit_original_response(content=f"Preparing to force close {target_channel.mention}...")

    view = CloseTicketView()
    # Call the close logic using the target channel context. 
    # NOTE: The actual log sending and deletion relies on global bot object and the target_channel reference.
    await view.close_ticket(ForceCloseInteraction(interaction, target_channel), None) 
    
    # The channel is deleted inside close_ticket, so this final followup will fail if the channel is gone.
    # We rely on the log being successful inside the view. 
    # Final confirmation sent to the admin via the ephemeral message:
    try:
        await interaction.followup.send(f"✅ Force close successful! {target_channel.name} is deleted.", ephemeral=True)
    except discord.errors.NotFound:
        # If the channel is already deleted, the original interaction message might be gone.
        pass. ")


# --- /send_app ---
@bot.tree.command(name="send_app", description="📤 Send a premium app link to a user's ticket")
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


# =============================
# SLASH COMMANDS (USER/GENERAL GROUP)
# =============================

# --- /ticket (COOLDOWN FIX) ---
@bot.tree.command(name="ticket", description="🎟️ Create a support ticket")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def ticket(interaction: discord.Interaction):

    user = interaction.user
    # FIX: Use UTC.now() for accurate, timezone-aware comparison
    now = datetime.datetime.now(datetime.timezone.utc)

    if user.id in cooldowns and cooldowns[user.id] > now:
        remaining = cooldowns[user.id] - now
        
        # Calculate time remaining in HH:MM:SS format
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

    # FIX: Ensure cooldown expiry is also timezone-aware
    cooldowns[user.id] = now + datetime.timedelta(hours=48)

    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
    }

    channel_name = f"ticket-{interaction.user.id}"

    channel = await interaction.guild.create_text_channel(
        channel_name,
        overwrites=overwrites
    )

    embed = discord.Embed(
        title="🎫 Welcome to your Ticket!",
        description="👋 Please select the application you need assistance with from the dropdown menu below.",
        color=discord.Color.blurple()
    )

    await channel.send(f"Welcome {user.mention}!", embed=embed, view=AppSelect(interaction.user))

    await interaction.followup.send(
        f"✅ Ticket created successfully! Head over to {channel.mention} to continue.",
        ephemeral=True
    )


# =============================
# ON MESSAGE — SCREENSHOT + APP DETECTION
# =============================
@bot.event
async def on_message(message):

    if message.author.bot:
        return

    if not message.channel.name.startswith("ticket-"):
        return

    apps = load_apps()
    content = message.content.lower()

    matched_app_key = next((key for key in apps if key in content), None)

    if matched_app_key:
        matched_app_display = matched_app_key.title()

        if message.attachments:

            screenshot = message.attachments[0].url
            ver_channel = bot.get_channel(VERIFICATION_CHANNEL_ID)

            embed = discord.Embed(
                title="📸 Verification Proof Received!",
                description=f"User {message.author.mention} submitted proof for **{matched_app_display}**.",
                color=discord.Color.yellow()
            )
            embed.set_image(url=screenshot)

            await ver_channel.send(
                embed=embed,
                view=VerificationView(message.channel, message.author, matched_app_key, screenshot)
            )

            await message.channel.send(
                embed=discord.Embed(
                    title="✅ Upload Successful! 🎉",
                    description="Thank you for providing proof! Please wait patiently while the **Owner/Admin** verifies your screenshot. Once verified, you will receive your app link here. ⏳",
                    color=discord.Color.blue()
                )
            )

        else:

            await message.channel.send(
                embed=discord.Embed(
                    title="📷 Screenshot Required",
                    description=f"You mentioned **{matched_app_display}**. Please upload the subscription screenshot to proceed.",
                    color=discord.Color.orange()
                )
            )

    await bot.process_commands(message)


# =============================
# ON READY
# =============================
@bot.event
async def on_ready():
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))

    # Register persistent views
    bot.add_view(CloseTicketView())

    print(f"🟢 Logged in as {bot.user}")


# =============================
# RUN BOT
# =============================
Thread(target=run_flask).start()
bot.run(TOKEN)
