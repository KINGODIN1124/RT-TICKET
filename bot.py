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
GUILD_ID = int(os.getenv("GUILD_ID"))
TICKET_LOG_CHANNEL_ID = int(os.getenv("TICKET_LOG_CHANNEL_ID"))
YOUTUBE_CHANNEL_URL = os.getenv("YOUTUBE_CHANNEL_URL")
VERIFICATION_CHANNEL_ID = int(os.getenv("VERIFICATION_CHANNEL_ID"))

# ---------------------------
# Load / Save Apps
# ---------------------------
def load_apps():
    with open("apps.json", "r") as f:
        return json.load(f)

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

cooldowns = {}  # 48-hour ticket cooldowns


# =============================
# APP SELECT VIEW
# =============================
class AppDropdown(Select):
    def __init__(self, options, user):
        super().__init__(placeholder="Select an app...", min_values=1, max_values=1, options=options)
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
        super().__init__(timeout=None)
        apps = load_apps()
        options = [discord.SelectOption(label=app, value=app) for app in apps.keys()]
        self.add_item(AppDropdown(options, user))


# =============================
# CLOSE TICKET VIEW
# =============================
class CloseTicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Close Ticket", style=discord.ButtonStyle.red)
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):

        if not interaction.channel.name.startswith("ticket-"):
            return await interaction.response.send_message("❌ Not a ticket channel.", ephemeral=True)

        log_channel = bot.get_channel(TICKET_LOG_CHANNEL_ID)

        # Fetch messages
        messages = [msg async for msg in interaction.channel.history(limit=None)]
        messages.reverse()

        # Build transcript safely
        transcript_chunks = []
        current = ""

        for msg in messages:
            line = f"[{msg.created_at:%Y-%m-%d %H:%M}] {msg.author.display_name}: {msg.content}\n"
            for a in msg.attachments:
                line += f"📎 {a.url}\n"

            if len(current) + len(line) > 4000:
                transcript_chunks.append(current)
                current = ""

            current += line

        transcript_chunks.append(current)

        # Send transcript parts
        for part in transcript_chunks:
            embed = discord.Embed(
                title=f"📜 Transcript — {interaction.channel.name}",
                description=part,
                color=discord.Color.blurple()
            )
            await log_channel.send(embed=embed)

        await interaction.channel.delete()


# =============================
# VERIFICATION VIEW
# =============================
class VerificationView(View):
    def __init__(self, ticket_channel, user, app_name, screenshot_url):
        super().__init__(timeout=None)
        self.ticket_channel = ticket_channel
        self.user = user
        self.app_name = app_name
        self.screenshot_url = screenshot_url

    @discord.ui.button(label="✅ Verify", style=discord.ButtonStyle.green)
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):

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
        except:
            await self.ticket_channel.send("⚠ User has DMs disabled.")

        await self.ticket_channel.send(
            embed=discord.Embed(
                title="🎉 Service Completed",
                description="Click the button below to close the ticket.",
                color=discord.Color.green(),
            ),
            view=CloseTicketView()
        )

        await interaction.response.send_message("Verified!", ephemeral=True)

    @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.red)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):

        embed = discord.Embed(
            title="❌ Verification Declined",
            description="Please submit a valid screenshot.",
            color=discord.Color.red()
        )

        await self.ticket_channel.send(embed=embed)
        await interaction.response.send_message("Declined!", ephemeral=True)


# =============================
# SLASH COMMANDS
# =============================

# --- /ticket ---
@bot.tree.command(name="ticket", description="🎟️ Create a support ticket")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def ticket(interaction: discord.Interaction):

    user = interaction.user
    now = datetime.datetime.utcnow()

    if user.id in cooldowns and cooldowns[user.id] > now:
        hours = int((cooldowns[user.id] - now).total_seconds() // 3600)
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
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
    }

    channel = await interaction.guild.create_text_channel(
        f"ticket-{interaction.user.id}",
        overwrites=overwrites
    )

    embed = discord.Embed(
        title="🎫 Ticket Created",
        description="Choose the app you want help with.",
        color=discord.Color.blurple()
    )

    await channel.send(embed=embed, view=AppSelect(interaction.user))

    await interaction.response.send_message(
        f"Ticket created: {channel.mention}",
        ephemeral=True
    )


# --- /send_app ---
@bot.tree.command(name="send_app", description="📤 Send a premium app to a user")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(manage_guild=True)
async def send_app(interaction: discord.Interaction, app_name: str, user: discord.Member):

    apps = load_apps()

    if app_name not in apps:
        return await interaction.response.send_message(
            "❌ App not found.",
            ephemeral=True
        )

    link = apps[app_name]

    ticket_channel = discord.utils.get(
        interaction.guild.channels,
        name=f"ticket-{user.id}"
    )

    if not ticket_channel:
        return await interaction.response.send_message(
            "❌ User has no open ticket.",
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

    await interaction.response.send_message("Sent!", ephemeral=True)


# --- /view_tickets ---
@bot.tree.command(name="view_tickets", description="📊 View open tickets")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def view_tickets(interaction: discord.Interaction):

    tickets = [
        c for c in interaction.guild.channels
        if isinstance(c, discord.TextChannel) and c.name.startswith("ticket-")
    ]

    embed = discord.Embed(
        title="🎟️ Ticket Overview",
        description=f"Open tickets: **{len(tickets)}**",
        color=discord.Color.blurple()
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


# --- /force_close FIXED ---
@bot.tree.command(name="force_close", description="🔒 Force close a ticket")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(manage_channels=True)
async def force_close(interaction: discord.Interaction, channel: discord.TextChannel):

    if not channel.name.startswith("ticket-"):
        return await interaction.response.send_message(
            "❌ Not a ticket channel.",
            ephemeral=True
        )

    await interaction.response.send_message("Closing...", ephemeral=True)

    # Manually trigger the close logic without faking a button click
    view = CloseTicketView()
    # We pass 'None' as the button argument because we are forcing it via command
    await view.close_ticket(interaction, None)


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
                description=f"User requested **{matched_app}**",
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
                    description="Admin will verify soon!",
                    color=discord.Color.blue()
                )
            )

        else:

            await message.channel.send(
                embed=discord.Embed(
                    title="📷 Screenshot Required",
                    description="Upload the subscription screenshot.",
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
