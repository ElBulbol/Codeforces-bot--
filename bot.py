import discord
from discord.ext import commands
from discord import app_commands
import logging
import logging.handlers
from dotenv import load_dotenv
import os
import asyncio
import aiohttp
import json
import re
import sqlite3
import inspect

load_dotenv()
token = os.getenv('DISCORD_TOKEN')

# CF_LINKS_FILE to store Codeforces handle links
CF_LINKS_FILE = "cf_links.json"

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        
        # Dynamic cog loading
        self.initial_extensions = []
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                self.initial_extensions.append(f'cogs.{filename[:-3]}')

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        for extension in self.initial_extensions:
            try:
                await self.load_extension(extension)
                print(f"✅ Loaded extension: {extension}")
            except Exception as e:
                print(f"❌ Failed to load extension {extension}: {e}")
        
        # Initial sync will happen in on_ready with delay
        print("Initial setup complete, will sync commands after bot is ready")
        
    async def close(self):
        if hasattr(self, 'session'):
            await self.session.close()
        await super().close()

    async def on_ready(self):
        print(f"Bot is online as {self.user.name}")
        await self.change_presence(activity=discord.Game(name="/help"))

        # Delay sync to ensure all cogs are fully loaded
        await asyncio.sleep(2)
        
        # Force sync to ensure all new commands are registered
        await self.tree.sync()

        # Improved command logging
        registered_commands = await self.tree.fetch_commands()
        command_names = [cmd.name for cmd in registered_commands]
        command_names.sort()

        print("Registered commands:")
        for cmd_name in command_names:
            print(f"  - {cmd_name}")

    async def on_member_join(self, member):
        welcome_channel = discord.utils.get(member.guild.text_channels, name="welcome")
        if welcome_channel:
            await welcome_channel.send(f"Welcome to the server, {member.mention}!")

    async def on_message(self, message):
        if message.author == self.user:
            return
        await self.process_commands(message)

bot = MyBot()

# NOTE: The link_cf and de_link_cf commands have been moved to codeforces.py
# Their definitions have been removed from here

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(f"This command is on cooldown. Try again in {error.retry_after:.2f} seconds.", ephemeral=True)
    elif isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
    elif isinstance(error, app_commands.BotMissingPermissions):
        await interaction.response.send_message("I don't have the necessary permissions to execute this command.", ephemeral=True)
    else:
        # For other errors, show a generic message but log the full error
        error_message = f"An error occurred: {str(error)}"
        print(f"Command error: {error}")
        try:
            await interaction.response.send_message(error_message, ephemeral=True)
        except:
            # If responding fails (e.g., interaction already responded to)
            try:
                await interaction.followup.send(error_message, ephemeral=True)
            except:
                print(f"Could not send error message to user for error: {error}")

def setup_logging():
    logger = logging.getLogger("discord")
    logger.setLevel(logging.INFO)
    handler = logging.handlers.RotatingFileHandler(
        filename="discord.log",
        encoding="utf-8",
        maxBytes=32 * 1024 * 1024,
        backupCount=5,
    )
    dt_fmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter("[{asctime}] [{levelname:<8}] {name}: {message}", dt_fmt, style="{")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

@bot.command()
@commands.is_owner()
async def sync(ctx):
    """Sync the application commands with Discord."""
    await ctx.send("Syncing commands...")
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"Synced {len(synced)} commands!")
        
        # Print the names of synced commands for debugging
        command_names = [cmd.name for cmd in synced]
        await ctx.send(f"Command names: {', '.join(command_names)}")
    except Exception as e:
        await ctx.send(f"Error syncing commands: {e}")

@bot.command()
@commands.is_owner()
async def guild_sync(ctx):
    """Sync commands to this guild only (faster for testing)."""
    await ctx.send("Syncing commands to this guild...")
    synced = await bot.tree.sync(guild=ctx.guild)
    await ctx.send(f"Synced {len(synced)} commands to this guild!")
    command_names = [cmd.name for cmd in synced]
    await ctx.send(f"Command names: {', '.join(command_names)}")

@bot.command()
@commands.is_owner()
async def check_commands(ctx):
    """Check what commands are registered."""
    commands = await bot.tree.fetch_commands()
    command_list = "\n".join([f"- {cmd.name}: {cmd.description}" for cmd in commands])
    await ctx.send(f"Registered commands:\n{command_list}")

@bot.command()
@commands.is_owner()
async def force_sync(ctx):
    """Force sync all application commands."""
    await ctx.send("Syncing commands...")
    
    # Clear and resync commands
    bot.tree.clear_commands(guild=None)
    synced = await bot.tree.sync()
    
    # Print the synced commands
    command_names = [cmd.name for cmd in synced]
    await ctx.send(f"Synced {len(synced)} commands: {', '.join(command_names)}")

@bot.command()
@commands.is_owner()
async def debug_cogs(ctx):
    """Debug loaded cogs"""
    loaded_cogs = [cog for cog in bot.cogs]
    await ctx.send(f"Loaded cogs: {', '.join(loaded_cogs)}")
    
    # Try to get the Codeforces cog specifically
    codeforces_cog = bot.get_cog('Codeforces')
    if codeforces_cog:
        await ctx.send(f"✅ Found Codeforces cog: {type(codeforces_cog).__name__}")
        # Check if it has the challenge method
        if hasattr(codeforces_cog, 'challenge'):
            await ctx.send("✅ Challenge method exists")
            
            # Check the method's parameters
            sig = inspect.signature(codeforces_cog.challenge)
            params = list(sig.parameters.keys())
            await ctx.send(f"Method parameters: {params}")
        else:
            await ctx.send("❌ Challenge method not found in cog")
    else:
        await ctx.send("❌ Codeforces cog not found")
        
        # Try with different capitalization
        for cog_name in bot.cogs:
            if cog_name.lower() == 'codeforces':
                await ctx.send(f"Found cog with similar name: {cog_name}")

@bot.command()
@commands.is_owner()
async def debug_command(ctx, command_name: str):
    """Debug a specific command"""
    await ctx.send(f"Debugging command: {command_name}")
    
    # Search for the command in global commands
    global_commands = await bot.tree.fetch_commands()
    command = None
    for cmd in global_commands:
        if cmd.name == command_name:
            command = cmd
            break
    
    if command:
        await ctx.send(f"✅ Command found in global commands: {command.name}")
        await ctx.send(f"Description: {command.description}")
        await ctx.send(f"Parameters: {[p.name for p in command.parameters]}")
    else:
        await ctx.send(f"❌ Command not found in global commands")
    
    # Check all cogs for the command
    for cog_name, cog in bot.cogs.items():
        for method_name, method in inspect.getmembers(cog, predicate=inspect.ismethod):
            if hasattr(method, "binding") and isinstance(method.binding, app_commands.Command):
                if method.binding.name == command_name:
                    await ctx.send(f"✅ Command found in cog: {cog_name}.{method_name}")
                    await ctx.send(f"Description: {method.binding.description}")
                    await ctx.send(f"Parameters: {[p.name for p in method.binding.parameters]}")

if __name__ == "__main__":
    setup_logging()
    asyncio.run(bot.start(token))