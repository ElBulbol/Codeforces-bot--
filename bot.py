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
                print(f"Loaded extension: {extension}")
            except Exception as e:
                print(f"Failed to load extension {extension}: {e}")
        
        # Sync commands with Discord
        await self.tree.sync()
        print("Commands synced.")
        
    async def close(self):
        if hasattr(self, 'session'):
            await self.session.close()
        await super().close()

    async def on_ready(self):
        print(f"Bot is online as {self.user.name}")
        await self.change_presence(activity=discord.Game(name="/help"))
        
        # Improved command logging
        registered_commands = await self.tree.fetch_commands()
        command_names = [cmd.name for cmd in registered_commands]
        command_names.sort()  # Sort alphabetically for easier reading
        
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

# Utility functions for link_cf command
async def load_links():
    """Load the CodeForces links from file"""
    if not os.path.exists(CF_LINKS_FILE):
        return {}
    
    try:
        with open(CF_LINKS_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

async def save_links(data):
    """Save the CodeForces links to file"""
    with open(CF_LINKS_FILE, 'w') as f:
        json.dump(data, f, indent=4)

@bot.tree.command(name="link_cf", description="Link your Codeforces account.")
@app_commands.describe(handle="Your Codeforces handle or profile URL")
async def link_cf(interaction: discord.Interaction, handle: str):
    """Link a Codeforces handle to your Discord account"""
    await interaction.response.defer(ephemeral=True)
    
    # Extract handle if a full URL is provided
    if handle.startswith("https://codeforces.com/profile/"):
        handle = handle.replace("https://codeforces.com/profile/", "")
    
    # Validate the handle exists on Codeforces
    valid = False
    try:
        async with bot.session.get(f"https://codeforces.com/api/user.info?handles={handle}") as resp:
            data = await resp.json()
            valid = data.get("status") == "OK"
    except Exception as e:
        await interaction.followup.send(f"Error validating handle: {str(e)}", ephemeral=True)
        return
    
    if not valid:
        await interaction.followup.send(f"Could not find Codeforces handle: `{handle}`", ephemeral=True)
        return
    
    # Load existing links
    links = await load_links()
    
    # Check if handle is already linked to another user
    for user_id, linked_handle in links.items():
        if linked_handle.lower() == handle.lower() and user_id != str(interaction.user.id):
            await interaction.followup.send(
                f"Error: The Codeforces handle `{handle}` is already linked to another Discord user. "
                f"Each Codeforces handle can only be linked to one Discord account.",
                ephemeral=True
            )
            return
    
    # Update the link
    links[str(interaction.user.id)] = handle
    await save_links(links)
    
    # Update the user in leaderboard database if it exists
    leaderboard_cog = bot.get_cog("Leaderboard")
    if leaderboard_cog:
        try:
            async with leaderboard_cog.db_lock:
                conn = sqlite3.connect("leaderboard.db")
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO users (discord_id, cf_handle) VALUES (?, ?)",
                    (str(interaction.user.id), handle)
                )
                conn.commit()
                conn.close()
        except Exception as e:
            print(f"Error updating leaderboard database: {e}")
    
    # Assign the Auth role to the user
    try:
        # Try to get the role by name first
        auth_role = discord.utils.get(interaction.guild.roles, name="Auth")
        
        # If not found by name, try to get by ID
        if not auth_role:
            auth_role = interaction.guild.get_role(1405358190400508005)
        
        if auth_role:
            await interaction.user.add_roles(auth_role, reason="Linked Codeforces account")
            await interaction.followup.send(
                f"Successfully linked your Discord account to Codeforces handle: `{handle}`\n"
                f"You have been given the {auth_role.mention} role!",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"Successfully linked your Discord account to Codeforces handle: `{handle}`\n"
                f"Note: Could not assign Auth role (not found).",
                ephemeral=True
            )
    except discord.Forbidden:
        await interaction.followup.send(
            f"Successfully linked your Discord account to Codeforces handle: `{handle}`\n"
            f"Note: Could not assign Auth role (insufficient permissions).",
            ephemeral=True
        )
    except Exception as e:
        print(f"Error assigning Auth role: {e}")
        await interaction.followup.send(
            f"Successfully linked your Discord account to Codeforces handle: `{handle}`\n"
            f"Note: Could not assign Auth role due to an error.",
            ephemeral=True
        )

@bot.tree.command(name="de_link_cf", description="Remove your linked Codeforces account.")
@app_commands.describe(user="The user to unlink (MOD only)")
async def de_link_cf(interaction: discord.Interaction, user: discord.Member = None):
    """Remove your linked Codeforces account from all databases, or unlink another user (MOD only)"""
    await interaction.response.defer(ephemeral=True)
    
    # Check if trying to unlink another user
    if user is not None and user.id != interaction.user.id:
        # Check if the command user has the MOD role
        mod_role = discord.utils.get(interaction.guild.roles, name="MOD")
        if not mod_role or mod_role not in interaction.user.roles:
            await interaction.followup.send(
                "You need the MOD role to unlink other users' accounts.", 
                ephemeral=True
            )
            return
        
        # Using the specified user
        target_user = user
        is_mod_action = True
    else:
        # Using the command author
        target_user = interaction.user
        is_mod_action = False
    
    target_id = str(target_user.id)
    
    # Check if the target user has a linked account
    links = await load_links()
    if target_id not in links:
        await interaction.followup.send(
            f"{'This user does not' if is_mod_action else 'You don\'t'} have a linked Codeforces account.", 
            ephemeral=True
        )
        return
    
    # Store the handle for confirmation message
    handle = links[target_id]
    
    # Remove from cf_links.json
    del links[target_id]
    await save_links(links)
    
    # Remove from leaderboard database if it exists
    leaderboard_cog = bot.get_cog("Leaderboard")
    if leaderboard_cog:
        try:
            async with leaderboard_cog.db_lock:
                conn = sqlite3.connect("leaderboard.db")
                cursor = conn.cursor()
                
                # Update the user's cf_handle to NULL in the users table
                cursor.execute(
                    "UPDATE users SET cf_handle = NULL WHERE discord_id = ?",
                    (target_id,)
                )
                
                conn.commit()
                conn.close()
        except Exception as e:
            print(f"Error updating leaderboard database: {e}")
    
    # Remove the Auth role
    try:
        # Try to get the role by name first
        auth_role = discord.utils.get(interaction.guild.roles, name="Auth")
        
        # If not found by name, try to get by ID
        if not auth_role:
            auth_role = interaction.guild.get_role(1405358190400508005)
        
        if auth_role and auth_role in target_user.roles:
            await target_user.remove_roles(auth_role, reason="Unlinked Codeforces account")
            
            if is_mod_action:
                # Mod action message
                await interaction.followup.send(
                    f"Successfully unlinked {target_user.mention}'s Discord account from Codeforces handle: `{handle}`\n"
                    f"The {auth_role.mention} role has been removed.",
                    ephemeral=True
                )
                
                # Notify the target user
                try:
                    await target_user.send(
                        f"Your Codeforces handle `{handle}` has been unlinked from your Discord account by a moderator."
                    )
                except:
                    pass
            else:
                # Self-unlink message
                await interaction.followup.send(
                    f"Successfully unlinked your Discord account from Codeforces handle: `{handle}`\n"
                    f"The {auth_role.mention} role has been removed.",
                    ephemeral=True
                )
        else:
            if is_mod_action:
                await interaction.followup.send(
                    f"Successfully unlinked {target_user.mention}'s Discord account from Codeforces handle: `{handle}`",
                    ephemeral=True
                )
                
                # Notify the target user
                try:
                    await target_user.send(
                        f"Your Codeforces handle `{handle}` has been unlinked from your Discord account by a moderator."
                    )
                except:
                    pass
            else:
                await interaction.followup.send(
                    f"Successfully unlinked your Discord account from Codeforces handle: `{handle}`",
                    ephemeral=True
                )
    except discord.Forbidden:
        if is_mod_action:
            await interaction.followup.send(
                f"Successfully unlinked {target_user.mention}'s Discord account from Codeforces handle: `{handle}`\n"
                f"Note: Could not remove Auth role (insufficient permissions).",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"Successfully unlinked your Discord account from Codeforces handle: `{handle}`\n"
                f"Note: Could not remove Auth role (insufficient permissions).",
                ephemeral=True
            )
    except Exception as e:
        print(f"Error removing Auth role: {e}")
        if is_mod_action:
            await interaction.followup.send(
                f"Successfully unlinked {target_user.mention}'s Discord account from Codeforces handle: `{handle}`\n"
                f"Note: Could not remove Auth role due to an error.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"Successfully unlinked your Discord account from Codeforces handle: `{handle}`\n"
                f"Note: Could not remove Auth role due to an error.",
                ephemeral=True
            )

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
    
    # Temporarily remove all existing commands
    bot.tree.clear_commands(guild=None)
    await bot.tree.sync()
    
    # Reload all cogs
    reloaded = []
    failed = []
    for extension in bot.initial_extensions:
        try:
            await bot.reload_extension(extension)
            reloaded.append(extension)
        except Exception as e:
            failed.append(f"{extension}: {e}")
    
    await ctx.send(f"Reloaded cogs: {', '.join(reloaded) or 'None'}")
    if failed:
        await ctx.send(f"Failed to reload: {', '.join(failed)}")
    
    # Sync again to register all commands
    synced = await bot.tree.sync()
    await ctx.send(f"Synced {len(synced)} commands: {', '.join(c.name for c in synced)}")

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
        else:
            await ctx.send("❌ Challenge method not found in cog")
    else:
        await ctx.send("❌ Codeforces cog not found")
        
        # Try with different capitalization
        for cog_name in bot.cogs:
            if cog_name.lower() == 'codeforces':
                await ctx.send(f"Found cog with similar name: {cog_name}")

if __name__ == "__main__":
    setup_logging()
    asyncio.run(bot.start(token))