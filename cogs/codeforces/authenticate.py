import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
from utility.db_helpers import get_user_by_discord, add_user, delete_user
from utility.config_manager import get_auth_role_id

class HandleModal(discord.ui.Modal, title="Codeforces Authentication"):
    handle_input = discord.ui.TextInput(
        label="Enter your Codeforces handle",
        placeholder="Your Codeforces username (e.g., tourist)",
        required=True,
        min_length=1,
        max_length=50
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        self.handle = self.handle_input.value
        await interaction.response.defer(ephemeral=True)

class Authentication(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @app_commands.command(
        name="authenticate", 
        description="Authenticate your Codeforces account with the bot"
    )
    async def authenticate(self, interaction: discord.Interaction):
        """Authenticate your Codeforces account with the bot"""
        discord_id = str(interaction.user.id)
        existing_user = await get_user_by_discord(discord_id)
        
        if existing_user:
            embed = discord.Embed(
                title="Already Authenticated",
                description=f"You are already authenticated with Codeforces handle: **{existing_user['cf_handle']}**",
                color=discord.Color.orange()
            )
            embed.add_field(
                name="Want to change?", 
                value="If you want to link a different account, please use `/deauthenticate` first."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        modal = HandleModal()
        await interaction.response.send_modal(modal)
        
        if await modal.wait():
            # The modal timed out
            return
        
        handle = modal.handle
        
        session = getattr(self.bot, "session", aiohttp.ClientSession())
        should_close = not hasattr(self.bot, "session")

        try:
            url = f"https://codeforces.com/api/user.info?handles={handle}"
            async with session.get(url) as response:
                if response.status != 200:
                    await interaction.followup.send("Error: Couldn't connect to Codeforces API.", ephemeral=True)
                    return
                
                data = await response.json()
                if data["status"] != "OK":
                    await interaction.followup.send(f"Error: Codeforces handle '{handle}' not found.", ephemeral=True)
                    return
                
                user_data = data["result"][0]
                
            embed = discord.Embed(
                title="Codeforces Authentication",
                description=f"Please confirm you want to link your Discord account to the Codeforces handle: **{handle}**",
                color=discord.Color.blue()
            )
            embed.add_field(name="Current Rating", value=str(user_data.get("rating", "N/A")), inline=True)
            embed.add_field(name="Current Rank", value=str(user_data.get("rank", "N/A")).capitalize(), inline=True)
            embed.add_field(name="Profile Link", value=f"[View on Codeforces](https://codeforces.com/profile/{handle})", inline=False)
            
            # MODIFIED: Corrected the thumbnail URL formatting
            if "titlePhoto" in user_data:
                photo_url = user_data["titlePhoto"]
                if photo_url.startswith("//"):
                    photo_url = f"https:{photo_url}"
                
                # Basic check to ensure it's a valid URL before setting
                if photo_url.startswith("http"):
                    embed.set_thumbnail(url=photo_url)

            view = discord.ui.View(timeout=60)
            confirm_button = discord.ui.Button(label="Confirm", style=discord.ButtonStyle.green)
            cancel_button = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.red)
            
            async def confirm_callback(confirm_interaction: discord.Interaction):
                if confirm_interaction.user != interaction.user:
                    await confirm_interaction.response.send_message("This is not your authentication process.", ephemeral=True)
                    return
                
                await confirm_interaction.response.defer(ephemeral=True)
                
                await add_user(discord_id, handle)
                
                auth_role_id = await get_auth_role_id(interaction.guild.id)
                auth_role = interaction.guild.get_role(auth_role_id) if auth_role_id else None

                result_embed = discord.Embed(
                    title="✅ Authentication Successful",
                    description=f"Your Discord account has been linked to Codeforces handle: **{handle}**",
                    color=discord.Color.green()
                )
                
                if auth_role:
                    await interaction.user.add_roles(auth_role, reason="Codeforces Authentication")
                    result_embed.add_field(name="Auth Role", value=f"You have been given the {auth_role.mention} role.", inline=False)
                else:
                    result_embed.add_field(name="Auth Role", value="⚠️ Could not assign Auth role (not configured on this server).", inline=False)

                await confirm_interaction.followup.send(embed=result_embed, ephemeral=True)
                await confirm_interaction.message.edit(content="Authentication completed! ✅", view=None, embed=None)

            
            async def cancel_callback(cancel_interaction: discord.Interaction):
                if cancel_interaction.user != interaction.user:
                    await cancel_interaction.response.send_message("This is not your authentication process.", ephemeral=True)
                    return
                await cancel_interaction.message.edit(content="Authentication cancelled. ❌", view=None, embed=None)
            
            confirm_button.callback = confirm_callback
            cancel_button.callback = cancel_callback
            
            view.add_item(confirm_button)
            view.add_item(cancel_button)
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        
        finally:
            if should_close and session:
                await session.close()

    @app_commands.command(
        name="deauthenticate", 
        description="Remove your Codeforces authentication from the bot"
    )
    @app_commands.describe(user="The user to deauthenticate (MOD only)")
    async def deauthenticate(self, interaction: discord.Interaction, user: discord.Member = None):
        await interaction.response.defer(ephemeral=True)
        
        target_user = user if user else interaction.user
        
        if user and user != interaction.user and not interaction.user.guild_permissions.manage_roles:
            await interaction.followup.send("You don't have permission to deauthenticate other users.", ephemeral=True)
            return

        discord_id = str(target_user.id)
        user_data = await get_user_by_discord(discord_id)
        
        if not user_data:
            await interaction.followup.send(f"{target_user.mention} is not authenticated.", ephemeral=True)
            return
        
        cf_handle = user_data['cf_handle']
        
        view = discord.ui.View(timeout=60)
        confirm_button = discord.ui.Button(label="Confirm", style=discord.ButtonStyle.danger)
        cancel_button = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        
        async def confirm_callback(confirm_interaction: discord.Interaction):
            if confirm_interaction.user != interaction.user:
                await confirm_interaction.response.send_message("This is not your deauthentication process.", ephemeral=True)
                return
            
            await confirm_interaction.response.defer(ephemeral=True)
            
            if await delete_user(discord_id=discord_id):
                auth_role_id = await get_auth_role_id(interaction.guild.id)
                auth_role = interaction.guild.get_role(auth_role_id) if auth_role_id else None
                
                result_embed = discord.Embed(
                    title="✅ Deauthentication Successful",
                    description=f"Removed Codeforces authentication for {target_user.mention} (handle: `{cf_handle}`).",
                    color=discord.Color.green()
                )

                if auth_role and auth_role in target_user.roles:
                    try:
                        await target_user.remove_roles(auth_role, reason="Deauthenticated Codeforces account")
                        result_embed.add_field(name="Auth Role", value=f"The {auth_role.mention} role has been removed.")
                    except discord.Forbidden:
                        result_embed.add_field(name="Auth Role", value="⚠️ Could not remove Auth role (insufficient permissions).")
                
                await confirm_interaction.followup.send(embed=result_embed, ephemeral=True)
                await confirm_interaction.message.edit(content="Deauthentication completed! ✅", view=None, embed=None)
            else:
                await confirm_interaction.followup.send("Failed to remove authentication from the database.", ephemeral=True)
                await confirm_interaction.message.edit(content="Deauthentication failed. ❌", view=None, embed=None)

        async def cancel_callback(cancel_interaction: discord.Interaction):
            if cancel_interaction.user != interaction.user:
                await cancel_interaction.response.send_message("This is not your deauthentication process.", ephemeral=True)
                return
            await cancel_interaction.message.edit(content="Deauthentication cancelled. ❌", view=None, embed=None)
        
        confirm_button.callback = confirm_callback
        cancel_button.callback = cancel_callback
        
        view.add_item(confirm_button)
        view.add_item(cancel_button)
        
        confirm_embed = discord.Embed(
            title="⚠️ Confirm Deauthentication",
            description=f"Are you sure you want to remove the Codeforces authentication for {target_user.mention}?",
            color=discord.Color.orange()
        )
        await interaction.followup.send(embed=confirm_embed, view=view, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Authentication(bot))
