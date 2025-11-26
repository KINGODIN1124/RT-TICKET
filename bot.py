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
# NOTE: Using a robust way to ensure environment variables are present and valid integers
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
# Load / Save Apps
# ---------------------------
def load_apps():
    try:
        with open("apps.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print("Warning: apps.json not found. Creating empty file.")
        with open("apps.json", "w") as f:
            json.dump({}, f)
        return {}

def save_apps(apps):
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

# Using UTC timezone for consistent comparison
cooldowns = {}  # 48-hour ticket cooldowns

# ---------------------------
# Helper Function for Transcripts
# ---------------------------
async def create_transcript(channel: discord.TextChannel) -> list[str]:
    """Fetches channel history and splits it into chunks of 4000 characters."""
    messages = [msg async for msg in channel.history(limit=None)]
    messages.reverse()

    transcript_chunks = []
    current = ""

    for msg in messages:
        # Use UTC timestamp for consistency
        line = f"[{msg.created_at.replace(tzinfo=datetime.timezone.utc):%Y-%m-%d %H:%M}] {msg.author.display_name}: {msg.content}\n"
        for a in msg.attachments:
            line += f"📎 {a.url}\n"

        if len(current) + len(line) > 4000:
            transcript_chunks.append(current)
            current = ""

        current += line

    if current:
        transcript_chunks.append(current)
        
    return transcript_chunks


# =============================
# APP SELECT VIEW
# =============================
class AppDropdown(Select):
    def __init__(self, options, user):
        super().__init__(
            placeholder="Select an app...", 
            min_values=1, 
            max_values=1, 
            options=options,
            custom_id="app_select_dropdown"
        )
        self.user = user

    async def callback(self, interaction: discord.Interaction):
        app_name = self.values[0]

        embed = discord.Embed(
            title="🔐 Verification Process",
            description=f"To get **{app_name}**, follow the steps:\n"
                        "1️⃣ Subscribe to our channel\n"
                        "2️⃣ Take a screenshot\n"
                        "3️⃣ Send screenshot in this ticket\n\n"
                        f"📺 [Subscribe Here]({YOUTUBE_CHANNEL_URL})",
            color=discord.Color.blue()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


class AppSelect(View):
    def __init__(self, user):
        super().__init__(timeout=1800) # 30 minutes timeout for selection
        apps = load_apps()
        options = [discord.SelectOption(label=app, value=app) for app in apps.keys()]
        self.add_item(AppDropdown(options, user))


# =============================
# CLOSE TICKET VIEW (PERSISTENT)
# =============================
class CloseTicketView(View):
    def __init__(self):
        super().__init__(timeout=None) # Required for persistence

    @discord.ui.button(
        label="🔒 Close Ticket",
        style=discord.ButtonStyle.red,
        custom_id="persistent_close_ticket_button" # Required for persistence
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):

        if not interaction.channel.name.startswith("ticket-"):
            return await interaction.response.send_message("❌ Not a ticket channel.", ephemeral=True)

        # Defer the response while we process the history/transcript
        await interaction.response.defer(ephemeral=True, thinking=True)

        log_channel = bot.get_channel(TICKET_LOG_CHANNEL_ID)
        
        # Collect Transcript using helper function
        transcript_parts = await create_transcript(interaction.channel)

        for i, part in enumerate(transcript_parts):
            embed = discord.Embed(
                title=f"📜 Transcript — {interaction.channel.name} (Part {i+1})",
                description=part,
                color=discord.Color.blurple()
            )
            await log_channel.send(embed=embed)

        # Notify ticket closed
        await log_channel.send(
            embed=discord.Embed(
                title="🔒 Ticket Closed",
                description=f"Closed by {interaction.user.mention}\nChannel: **{interaction.channel.name}**",
                color=discord.Color.red()
            )
        )
        
        # Give confirmation before deletion
        await interaction.followup.send("✅ Ticket closed and transcript saved.", ephemeral=True)

        # Delete Channel
        await interaction.channel.delete()


# =============================
# VERIFICATION VIEW
# =============================
class VerificationView(View):
    def __init__(self, ticket_channel, user, app_name, screenshot_url):
        super().__init__(timeout=3600) # Timeout after 1 hour if not acted upon
        self.ticket_channel = ticket_channel
        self.user = user
        self.app_name = app_name
        self.screenshot_url = screenshot_url

    @discord.ui.button(label="✅ Verify", style=discord.ButtonStyle.green, custom_id="verify_button")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Admin permission check
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ You do not have permission to verify.", ephemeral=True)

        apps = load_apps()
        app_link = apps.get(self.app_name)

        if not app_link:
            return await interaction.response.send_message("❌ App not found.", ephemeral=True)

        embed = discord.Embed(
            title="✅ Verification Approved",
            description=f"{self.user.mention}, your verification for **{self.app_name}** is approved!\n"
                        f"[Click Here]({app_link})",
            color=discord.Color.green()
        )

        embed.set_image(url=self.screenshot_url)

        await self.ticket_channel.send(embed=embed)

        try:
            await self.user.send(embed=embed)
        except discord.Forbidden:
            await self.ticket_channel.send("⚠ User has DMs disabled.")

        await self.ticket_channel.send(
            embed=discord.Embed(
                title="🎉 Service Completed",
                description="Click the button below to close the ticket.",
                color=discord.Color.green(),
            ),
            view=CloseTicketView()
        )
        
        # Disable buttons after action is taken
        self.stop()
        await interaction.message.edit(view=self)

        await interaction.response.send_message("Verified!", ephemeral=True)

    @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.red, custom_id="decline_button")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Admin permission check
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ You do not have permission to decline.", ephemeral=True)
            
        embed = discord.Embed(
            title="❌ Verification Declined",
            description="Please submit a valid screenshot.",
            color=discord.Color.red()
        )

        await self.ticket_channel.send(embed=embed)
        
        # Disable buttons after action is taken
        self.stop()
        await interaction.message.edit(view=self)
        
        await interaction.response.send_message("Declined!", ephemeral=True)


# =============================
# SLASH COMMANDS
# =============================

# --- /ticket ---
@bot.tree.command(name="ticket", description="🎟️ Create a support ticket")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def ticket(interaction: discord.Interaction):

    user = interaction.user
    now = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)

    # Cooldown check
    if user.id in cooldowns and cooldowns[user.id] > now:
        remaining = cooldowns[user.id] - now
        hours = int(remaining.total_seconds() // 3600)
        return await interaction.response.send_message(
            embed=discord.Embed(
                title="⏳ Cooldown Active",
                description=f"You can open another ticket in **{hours} hours**.",
                color=discord.Color.orange()
            ),
            ephemeral=True
        )

    cooldowns[user.id] = now + datetime.timedelta(hours=48)

    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        # Staff roles should be added here for viewing tickets
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
    }

    # Use user ID for reliable channel naming (f"ticket-{user.id}")
    channel_name = f"ticket-{interaction.user.id}"

    channel = await interaction.guild.create_text_channel(
        channel_name,
        overwrites=overwrites
    )

    embed = discord.Embed(
        title="🎫 Ticket Created",
        description="Choose the app you want help with.",
        color=discord.Color.blurple()
    )

    await channel.send(f"Welcome {user.mention}!", embed=embed, view=AppSelect(interaction.user))

    await interaction.response.send_message(
        f"Ticket created: {channel.mention}",
        ephemeral=True
    )

# --- /remove_cooldown (NEW COMMAND) ---
@bot.tree.command(name="remove_cooldown", description="🧹 Remove a user's ticket cooldown")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(manage_guild=True)
async def remove_cooldown(interaction: discord.Interaction, user: discord.Member):

    if user.id in cooldowns:
        del cooldowns[user.id]

        await interaction.response.send_message(
            embed=discord.Embed(
                title="✅ Cooldown Removed",
                description=f"{user.mention} can now create a ticket again.",
                color=discord.Color.green()
            ),
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            embed=discord.Embed(
                title="ℹ️ No Cooldown Found",
                description=f"{user.mention} currently has **no cooldown**.",
                color=discord.Color.blue()
            ),
            ephemeral=True
        )


# --- /send_app ---
@bot.tree.command(name="send_app", description="📤 Send a premium app to a user")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(manage_guild=True)
async def send_app(interaction: discord.Interaction, app_name: str, user: discord.Member):

    apps = load_apps()

    if app_name not in apps:
        return await interaction.response.send_message("❌ App not found.", ephemeral=True)

    link = apps[app_name]

    # Find ticket channel using the reliable ID format (f"ticket-{user.id}")
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
        title="💎 Premium App Delivered",
        description=f"**{app_name}**\n[Click Here]({link})",
        color=discord.Color.green()
    )

    await ticket_channel.send(embed=embed)
    await ticket_channel.send(
        embed=discord.Embed(
            title="🎉 Service Completed",
            description="Click below to close your ticket.",
            color=discord.Color.green()
        ),
        view=CloseTicketView()
    )

    await interaction.response.send_message("Link sent to the ticket!", ephemeral=True)

# --- /view_tickets (FIXED COUNT) ---
@bot.tree.command(name="view_tickets", description="📊 View number of currently open tickets")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(manage_channels=True)
async def view_tickets(interaction: discord.Interaction):

    # FIX: Counts only existing TextChannels starting with "ticket-"
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
        # Limit display to prevent hitting embed field limits
        ticket_mentions = "\n".join(f"📌 {c.mention}" for c in open_tickets[:20])
        if len(open_tickets) > 20:
             ticket_mentions += f"\n...and {len(open_tickets) - 20} more."
             
        embed.add_field(
            name="Active Ticket Channels",
            value=ticket_mentions,
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)


# --- /force_close ---
@bot.tree.command(name="force_close", description="🔒 Force close a ticket")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(manage_channels=True)
async def force_close(interaction: discord.Interaction, channel: discord.TextChannel):

    if not channel.name.startswith("ticket-"):
        return await interaction.response.send_message(
            "❌ Not a ticket channel.",
            ephemeral=True
        )

    # Defer response to allow time for transcript fetching
    await interaction.response.defer(ephemeral=True, thinking=True)
    
    # Manually create an instance of the view and call the close method.
    view = CloseTicketView()
    # Pass None for the button argument
    await view.close_ticket(interaction, None) 
    
    await interaction.followup.send(f"Successfully force-closed {channel.name} and logged transcript.")


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

    matched_app = next((a for a in apps if a.lower() in content), None)

    if matched_app:

        if message.attachments:

            screenshot = message.attachments[0].url
            ver_channel = bot.get_channel(VERIFICATION_CHANNEL_ID)

            embed = discord.Embed(
                title="🧾 Verification Request",
                description=f"{message.author.mention} requested **{matched_app}**",
                color=discord.Color.yellow()
            )
            embed.set_image(url=screenshot)

            await ver_channel.send(
                embed=embed,
                view=VerificationView(message.channel, message.author, matched_app, screenshot)
            )

            await message.channel.send(
                embed=discord.Embed(
                    title="📸 Screenshot Received",
                    description="Screenshot received! An Admin will verify soon. ⏳",
                    color=discord.Color.blue()
                )
            )

        else:

            await message.channel.send(
                embed=discord.Embed(
                    title="📷 Screenshot Required",
                    description=f"You mentioned **{matched_app}**. Please upload the subscription screenshot.",
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
# Start Flask server in a separate thread for the keep-alive function
Thread(target=run_flask).start()
bot.run(TOKEN)
