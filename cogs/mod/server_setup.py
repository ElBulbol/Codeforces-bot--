import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite
import os
from utility.config_manager import get_guild_settings # Import the new helper

# --- Database Setup ---
DB_PATH = "db/roles_and_channels.db"

async def init_db():
    """Initializes the database and creates the settings table if it doesn't exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        # Added columns for role names
        await db.execute("""
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                cp_role_id INTEGER,
                mod_role_id INTEGER,
                auth_role_id INTEGER,
                mentor_role_id INTEGER,
                cp_role_name TEXT,
                mod_role_name TEXT,
                auth_role_name TEXT,
                mentor_role_name TEXT,
                contest_channel_id INTEGER,
                challenge_channel_id INTEGER,
                announcement_channel_id INTEGER
            )
        """)
        await db.commit()

# --- Cog Implementation ---

class SetupCommands(commands.Cog):
    """A cog for setting up server-specific roles and channels."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        """Ensures the database is initialized when the cog is loaded."""
        await init_db()

    @app_commands.command(name="setroles", description="Set the essential roles for the server.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        cp_role="The main role for competitive programming participants.",
        mod_role="The role for server moderators.",
        auth_role="The role given to users after they authenticate.",
        mentor_role="The role for mentors who can create contests and challenges."
    )
    async def setroles(self, interaction: discord.Interaction, 
                       cp_role: discord.Role, 
                       mod_role: discord.Role, 
                       auth_role: discord.Role, 
                       mentor_role: discord.Role):
        """Saves the specified role IDs and names to the database for the current server."""
        await interaction.response.defer()
        
        guild_id = interaction.guild.id
        
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (guild_id,))
                
                # Updated to save both role IDs and names
                await db.execute("""
                    UPDATE guild_settings 
                    SET 
                        cp_role_id = ?, mod_role_id = ?, auth_role_id = ?, mentor_role_id = ?,
                        cp_role_name = ?, mod_role_name = ?, auth_role_name = ?, mentor_role_name = ?
                    WHERE guild_id = ?
                """, (
                    cp_role.id, mod_role.id, auth_role.id, mentor_role.id,
                    cp_role.name, mod_role.name, auth_role.name, mentor_role.name,
                    guild_id
                ))
                
                await db.commit()

            embed = discord.Embed(
                title="✅ Roles Successfully Set",
                description="The following roles have been configured for this server:",
                color=discord.Color.green()
            )
            embed.add_field(name="CP Role", value=cp_role.mention, inline=False)
            embed.add_field(name="Moderator Role", value=mod_role.mention, inline=False)
            embed.add_field(name="Authenticated Role", value=auth_role.mention, inline=False)
            embed.add_field(name="Mentor Role", value=mentor_role.mention, inline=False)
            
            await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(f"An error occurred while setting roles: {e}")

    @app_commands.command(name="setchannels", description="Set the essential channels for the server.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        contest_channel="The channel where contests will be announced and run.",
        challenge_channel="The channel where challenges will be posted.",
        announcement_channel="The channel for general bot announcements."
    )
    async def setchannels(self, interaction: discord.Interaction, 
                          contest_channel: discord.TextChannel, 
                          challenge_channel: discord.TextChannel, 
                          announcement_channel: discord.TextChannel):
        """Saves the specified channel IDs to the database for the current server."""
        await interaction.response.defer()
        
        guild_id = interaction.guild.id
        
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (guild_id,))
                
                await db.execute("""
                    UPDATE guild_settings 
                    SET contest_channel_id = ?, challenge_channel_id = ?, announcement_channel_id = ?
                    WHERE guild_id = ?
                """, (contest_channel.id, challenge_channel.id, announcement_channel.id, guild_id))
                
                await db.commit()

            embed = discord.Embed(
                title="✅ Channels Successfully Set",
                description="The following channels have been configured for this server:",
                color=discord.Color.green()
            )
            embed.add_field(name="Contest Channel", value=contest_channel.mention, inline=False)
            embed.add_field(name="Challenge Channel", value=challenge_channel.mention, inline=False)
            embed.add_field(name="Announcement Channel", value=announcement_channel.mention, inline=False)

            await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(f"An error occurred while setting channels: {e}")

    @app_commands.command(name="viewsettings", description="View the current role and channel settings for the server.")
    @app_commands.checks.has_permissions(administrator=True)
    async def viewsettings(self, interaction: discord.Interaction):
        """Displays the currently configured settings for the server."""
        await interaction.response.defer()
        
        guild_id = interaction.guild.id
        settings = await get_guild_settings(guild_id)
        
        if not settings:
            await interaction.followup.send("No settings have been configured for this server yet. Use `/setroles` and `/setchannels` to begin.", ephemeral=True)
            return
            
        embed = discord.Embed(
            title=f"⚙️ Settings for {interaction.guild.name}",
            color=discord.Color.blue()
        )

        # Format roles
        roles_description = []
        role_keys = [("CP Role", "cp_role_id"), ("Moderator Role", "mod_role_id"), 
                     ("Authenticated Role", "auth_role_id"), ("Mentor Role", "mentor_role_id")]
        
        for name, key in role_keys:
            role_id = settings.get(key)
            if role_id:
                role = interaction.guild.get_role(role_id)
                roles_description.append(f"**{name}:** {role.mention if role else f'`{role_id}` (Not Found)'}")
            else:
                roles_description.append(f"**{name}:** Not Set")
        
        embed.add_field(name="Roles", value="\n".join(roles_description), inline=False)

        # Format channels
        channels_description = []
        channel_keys = [("Contest Channel", "contest_channel_id"), 
                        ("Challenge Channel", "challenge_channel_id"), 
                        ("Announcement Channel", "announcement_channel_id")]

        for name, key in channel_keys:
            channel_id = settings.get(key)
            if channel_id:
                channel = interaction.guild.get_channel(channel_id)
                channels_description.append(f"**{name}:** {channel.mention if channel else f'`{channel_id}` (Not Found)'}")
            else:
                channels_description.append(f"**{name}:** Not Set")
        
        embed.add_field(name="Channels", value="\n".join(channels_description), inline=False)
        
        await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    """Adds the SetupCommands cog to the bot."""
    await bot.add_cog(SetupCommands(bot))
