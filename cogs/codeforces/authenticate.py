import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
from utility.db_helpers import get_user_by_discord, add_user, delete_user

class AuthenticationView(discord.ui.View):
    def __init__(self, timeout=180):
        super().__init__(timeout=timeout)
        self.handle = None
        self.cancelled = False
    
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.cancelled = True
        await interaction.response.edit_message(content="Authentication cancelled.", view=None)
        self.stop()

class HandleModal(discord.ui.Modal, title="Codeforces Authentication"):
    handle_input = discord.ui.TextInput(
        label="Enter your Codeforces handle",
        placeholder="Your Codeforces username (e.g., tourist)",
        required=True,
        min_length=1,
        max_length=50
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        # Store the handle and acknowledge submission
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
        # Check if the user is already authenticated
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
                value="If you want to link a different account, please use `/deauthenticate` first to unlink your current account."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Open the modal to collect Codeforces handle
        modal = HandleModal()
        await interaction.response.send_modal(modal)
        
        # Wait for the modal to be submitted
        timed_out = await modal.wait()
        
        if timed_out:
            await interaction.followup.send("Authentication timed out. Please try again.", ephemeral=True)
            return
        
        handle = modal.handle
        
        # Verify the handle exists on Codeforces
        session = getattr(self.bot, "session", None)
        if not session:
            session = aiohttp.ClientSession()
            should_close = True
        else:
            should_close = False
        
        try:
            # Verify handle with Codeforces API
            url = f"https://codeforces.com/api/user.info?handles={handle}"
            
            try:
                async with session.get(url) as response:
                    if response.status != 200:
                        await interaction.followup.send(
                            f"Error: Couldn't connect to Codeforces API. Please try again later.", 
                            ephemeral=True
                        )
                        return
                    
                    data = await response.json()
                    if data["status"] != "OK":
                        await interaction.followup.send(
                            f"Error: Codeforces handle '{handle}' not found. Please check spelling.", 
                            ephemeral=True
                        )
                        return
                    
                    # Extract user info for the embed
                    user_data = data["result"][0]
                    rating = user_data.get("rating", "Unrated")
                    max_rating = user_data.get("maxRating", "Unrated")
                    rank = user_data.get("rank", "Unrated")
                    max_rank = user_data.get("maxRank", "Unrated")
                    
            except Exception as e:
                await interaction.followup.send(
                    f"Error connecting to Codeforces: {str(e)}\nPlease try again later.", 
                    ephemeral=True
                )
                return
            
            # Create a confirmation embed
            embed = discord.Embed(
                title="Codeforces Authentication",
                description=f"Please confirm you want to link your Discord account to the Codeforces handle: **{handle}**",
                color=discord.Color.blue()
            )
            
            # Add user information to the embed
            embed.add_field(name="Current Rating", value=str(rating), inline=True)
            embed.add_field(name="Max Rating", value=str(max_rating), inline=True)
            embed.add_field(name="Current Rank", value=rank.capitalize() if isinstance(rank, str) else "Unrated", inline=True)
            embed.add_field(name="Max Rank", value=max_rank.capitalize() if isinstance(max_rank, str) else "Unrated", inline=True)
            
            # Add profile link
            embed.add_field(
                name="Profile Link", 
                value=f"[View on Codeforces](https://codeforces.com/profile/{handle})", 
                inline=False
            )
            
            # Add a thumbnail if available
            if "titlePhoto" in user_data:
                embed.set_thumbnail(url=user_data["titlePhoto"])
            
            # Create confirm/cancel buttons
            view = discord.ui.View(timeout=60)
            confirm_button = discord.ui.Button(label="Confirm", style=discord.ButtonStyle.green)
            cancel_button = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.red)
            
            async def confirm_callback(confirm_interaction):
                if confirm_interaction.user != interaction.user:
                    await confirm_interaction.response.send_message("This is not your authentication process.", ephemeral=True)
                    return
                
                await confirm_interaction.response.defer(ephemeral=True)
                
                # Process the authentication
                try:
                    # Link in database using db_helpers
                    try:
                        user_id = await add_user(discord_id, handle)
                        cf_db_success = True
                    except Exception as e:
                        print(f"Database error: {e}")
                        cf_db_success = False
                    
                    # Log the operation for debugging
                    print(f"[AUTHENTICATE] Link operation for {interaction.user.display_name} (ID: {discord_id}):")
                    print(f"  → CF Database: {'Success' if cf_db_success else 'Failed'}")
                    print(f"  → Handle: {handle}")
                    
                    if cf_db_success:
                        # Try to assign the Auth role
                        try:
                            # Try to get the role by name first
                            auth_role = discord.utils.get(interaction.guild.roles, name="Auth")
                            
                            # If not found by name, try to get by ID
                            if not auth_role:
                                auth_role = interaction.guild.get_role(1405358190400508005)
                            
                            if auth_role:
                                # Check if user already has the role
                                if auth_role in interaction.user.roles:
                                    result_embed = discord.Embed(
                                        title="✅ Authentication Successful",
                                        description=f"Your Discord account has been linked to Codeforces handle: **{handle}**",
                                        color=discord.Color.green()
                                    )
                                    result_embed.add_field(
                                        name="Database Status", 
                                        value="✅ Added to database successfully", 
                                        inline=False
                                    )
                                    result_embed.add_field(
                                        name="Auth Role", 
                                        value=f"You already have the {auth_role.mention} role", 
                                        inline=False
                                    )
                                    
                                    await confirm_interaction.followup.send(embed=result_embed, ephemeral=True)
                                    try:
                                        await interaction.edit_original_response(content="Authentication completed! ✅", embed=None, view=None)
                                    except discord.NotFound:
                                        # Message no longer exists, this is fine
                                        pass
                                    except Exception as e:
                                        print(f"Non-critical error updating message: {e}")
                                else:
                                    # Add the role
                                    await interaction.user.add_roles(auth_role, reason="Codeforces Authentication")
                                    
                                    result_embed = discord.Embed(
                                        title="✅ Authentication Successful",
                                        description=f"Your Discord account has been linked to Codeforces handle: **{handle}**",
                                        color=discord.Color.green()
                                    )
                                    result_embed.add_field(
                                        name="Database Status", 
                                        value="✅ Added to database successfully", 
                                        inline=False
                                    )
                                    result_embed.add_field(
                                        name="Auth Role", 
                                        value=f"You have been given the {auth_role.mention} role", 
                                        inline=False
                                    )
                                    
                                    await confirm_interaction.followup.send(embed=result_embed, ephemeral=True)
                                    try:
                                        await interaction.edit_original_response(content="Authentication completed! ✅", embed=None, view=None)
                                    except discord.NotFound:
                                        # Message no longer exists, this is fine
                                        pass
                                    except Exception as e:
                                        print(f"Non-critical error updating message: {e}")
                            else:
                                # Role not found
                                result_embed = discord.Embed(
                                    title="✅ Authentication Successful",
                                    description=f"Your Discord account has been linked to Codeforces handle: **{handle}**",
                                    color=discord.Color.green()
                                )
                                result_embed.add_field(
                                    name="Database Status", 
                                    value="✅ Added to database successfully", 
                                    inline=False
                                )
                                result_embed.add_field(
                                    name="Auth Role", 
                                    value="⚠️ Could not assign Auth role (role not found)", 
                                    inline=False
                                )
                                
                                await confirm_interaction.followup.send(embed=result_embed, ephemeral=True)
                                try:
                                    await interaction.edit_original_response(content="Authentication completed! ✅", embed=None, view=None)
                                except discord.NotFound:
                                    # Message no longer exists, this is fine
                                    pass
                                except Exception as e:
                                    print(f"Non-critical error updating message: {e}")
                        except discord.Forbidden:
                            # Permission error
                            result_embed = discord.Embed(
                                title="✅ Authentication Successful",
                                description=f"Your Discord account has been linked to Codeforces handle: **{handle}**",
                                color=discord.Color.green()
                            )
                            result_embed.add_field(
                                name="Database Status", 
                                value="✅ Added to database successfully", 
                                inline=False
                            )
                            result_embed.add_field(
                                name="Auth Role", 
                                value="⚠️ Could not assign Auth role (insufficient permissions)", 
                                inline=False
                            )
                            
                            await confirm_interaction.followup.send(embed=result_embed, ephemeral=True)
                            try:
                                await interaction.edit_original_response(content="Authentication completed! ✅", embed=None, view=None)
                            except discord.NotFound:
                                # Message no longer exists, this is fine
                                pass
                            except Exception as e:
                                print(f"Non-critical error updating message: {e}")
                        except Exception as e:
                            # Other errors
                            result_embed = discord.Embed(
                                title="✅ Authentication Successful",
                                description=f"Your Discord account has been linked to Codeforces handle: **{handle}**",
                                color=discord.Color.green()
                            )
                            result_embed.add_field(
                                name="Database Status", 
                                value="✅ Added to database successfully", 
                                inline=False
                            )
                            result_embed.add_field(
                                name="Auth Role", 
                                value=f"⚠️ Error assigning Auth role: {str(e)}", 
                                inline=False
                            )
                            
                            await confirm_interaction.followup.send(embed=result_embed, ephemeral=True)
                            try:
                                await interaction.edit_original_response(content="Authentication completed! ✅", embed=None, view=None)
                            except discord.NotFound:
                                # Message no longer exists, this is fine
                                pass
                            except Exception as e:
                                print(f"Non-critical error updating message: {e}")
                    else:
                        # Something went wrong with database
                        result_embed = discord.Embed(
                            title="❌ Authentication Failed",
                            description=f"There was an issue linking your account to Codeforces handle: **{handle}**",
                            color=discord.Color.red()
                        )
                        result_embed.add_field(
                            name="Database Status", 
                            value=f"❌ Failed to add to database", 
                            inline=False
                        )
                        result_embed.add_field(
                            name="What to do", 
                            value="Please try again later or contact an administrator if the issue persists.", 
                            inline=False
                        )
                        
                        await confirm_interaction.followup.send(embed=result_embed, ephemeral=True)
                        try:
                            await interaction.edit_original_response(content="Authentication failed. ❌", embed=None, view=None)
                        except discord.NotFound:
                            # Message no longer exists, this is fine
                            pass
                        except Exception as e:
                            print(f"Non-critical error updating message: {e}")
                
                except Exception as e:
                    # Catch any other errors
                    error_embed = discord.Embed(
                        title="❌ Authentication Failed",
                        description=f"An error occurred during authentication: {str(e)}",
                        color=discord.Color.red()
                    )
                    error_embed.add_field(
                        name="What to do", 
                        value="Please try again later or contact an administrator if the issue persists.", 
                        inline=False
                    )
                    
                    await confirm_interaction.followup.send(embed=error_embed, ephemeral=True)
                    try:
                        await interaction.edit_original_response(content="Authentication failed. ❌", embed=None, view=None)
                    except discord.NotFound:
                        # Message no longer exists, this is fine
                        pass
                    except Exception as e:
                        print(f"Non-critical error updating message: {e}")
                
                # Disable the buttons
                view.clear_items()
                await interaction.edit_original_response(view=view)
            
            async def cancel_callback(cancel_interaction):
                if cancel_interaction.user != interaction.user:
                    await cancel_interaction.response.send_message("This is not your authentication process.", ephemeral=True)
                    return
                
                await cancel_interaction.response.defer(ephemeral=True)
                await cancel_interaction.followup.send("Authentication cancelled.", ephemeral=True)
                await interaction.edit_original_response(content="Authentication cancelled. ❌", embed=None, view=None)
            
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
        """Remove your or another user's Codeforces authentication from the database"""
        await interaction.response.defer(ephemeral=True)
        
        # Determine target user (self or specified user)
        target_user = user if user else interaction.user
        
        # Check permissions if deauthenticating someone else
        if user and user != interaction.user:
            # Check if requester has manage_roles permission
            if not interaction.user.guild_permissions.manage_roles:
                embed = discord.Embed(
                    title="❌ Permission Denied",
                    description="You don't have permission to deauthenticate other users.",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

        # Store Discord ID as string for consistency
        discord_id = str(target_user.id)

        # Get the user's handle before we unlink (for logging)
        user_data = await get_user_by_discord(discord_id)
        
        if not user_data:
            embed = discord.Embed(
                title="❌ Not Authenticated",
                description=f"{target_user.mention} is not authenticated with any Codeforces account.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        
        cf_handle = user_data['cf_handle']
        
        # Create a confirmation view
        view = discord.ui.View(timeout=60)
        confirm_button = discord.ui.Button(label="Confirm", style=discord.ButtonStyle.danger)
        cancel_button = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        
        async def confirm_callback(confirm_interaction):
            if confirm_interaction.user != interaction.user:
                await confirm_interaction.response.send_message("This is not your deauthentication process.", ephemeral=True)
                return
            
            await confirm_interaction.response.defer(ephemeral=True)
            
            # Process the deauthentication
            try:
                # Remove from database using db_helpers
                cf_db_success = await delete_user(discord_id=discord_id)
                
                # Log the operation for debugging
                print(f"[DEAUTHENTICATE] Deauthentication for {target_user.display_name} (ID: {discord_id}):")
                print(f"  → CF Handle: {cf_handle}")
                print(f"  → CF Database removal: {'✅ Success' if cf_db_success else '❌ Failed'}")
                
                if cf_db_success:
                    # Try to get the Auth role
                    try:
                        auth_role = discord.utils.get(interaction.guild.roles, name="Auth")
                        if not auth_role:
                            auth_role = interaction.guild.get_role(1405358190400508005)
                        
                        # Remove the role if the target has it
                        role_removed = False
                        if auth_role and auth_role in target_user.roles:
                            await target_user.remove_roles(auth_role, reason="Deauthenticated Codeforces account")
                            role_removed = True
                        
                        # Create the response embed
                        result_embed = discord.Embed(
                            title="✅ Deauthentication Successful",
                            description=f"Removed Codeforces authentication for {target_user.mention}",
                            color=discord.Color.green()
                        )
                        
                        result_embed.add_field(
                            name="Codeforces Handle", 
                            value=f"`{cf_handle}`", 
                            inline=False
                        )
                        
                        result_embed.add_field(
                            name="Database Status", 
                            value=f"✅ Removed from database successfully", 
                            inline=False
                        )
                        
                        if role_removed:
                            result_embed.add_field(
                                name="Auth Role", 
                                value=f"The {auth_role.mention} role has been removed.", 
                                inline=False
                            )
                        elif auth_role:
                            result_embed.add_field(
                                name="Auth Role", 
                                value=f"User did not have the {auth_role.mention} role.", 
                                inline=False
                            )
                        
                        await confirm_interaction.followup.send(embed=result_embed, ephemeral=True)
                        await interaction.edit_original_response(content="Deauthentication completed! ✅", embed=None, view=None)
                        
                    except discord.Forbidden:
                        # Permission error for role removal
                        result_embed = discord.Embed(
                            title="⚠️ Partial Deauthentication",
                            description=f"Removed database entry for {target_user.mention}",
                            color=discord.Color.orange()
                        )
                        
                        result_embed.add_field(
                            name="Codeforces Handle", 
                            value=f"`{cf_handle}`", 
                            inline=False
                        )
                        
                        result_embed.add_field(
                            name="Database Status", 
                            value=f"✅ Removed from database successfully", 
                            inline=False
                        )
                        
                        result_embed.add_field(
                            name="Auth Role", 
                            value="⚠️ Could not remove Auth role (insufficient permissions)", 
                            inline=False
                        )
                        
                        await confirm_interaction.followup.send(embed=result_embed, ephemeral=True)
                        await interaction.edit_original_response(content="Deauthentication partially completed! ⚠️", embed=None, view=None)
                    
                    except Exception as e:
                        # Other errors during role removal
                        result_embed = discord.Embed(
                            title="⚠️ Partial Deauthentication",
                            description=f"Removed database entry for {target_user.mention}",
                            color=discord.Color.orange()
                        )
                        
                        result_embed.add_field(
                            name="Codeforces Handle", 
                            value=f"`{cf_handle}`", 
                            inline=False
                        )
                        
                        result_embed.add_field(
                            name="Database Status", 
                            value=f"✅ Removed from database successfully", 
                            inline=False
                        )
                        
                        result_embed.add_field(
                            name="Auth Role", 
                            value=f"⚠️ Error removing Auth role: {str(e)}", 
                            inline=False
                        )
                        
                        await confirm_interaction.followup.send(embed=result_embed, ephemeral=True)
                        await interaction.edit_original_response(content="Deauthentication partially completed! ⚠️", embed=None, view=None)
                else:
                    # Database operation failed
                    error_embed = discord.Embed(
                        title="❌ Deauthentication Failed",
                        description=f"Failed to remove database entry for {target_user.mention}",
                        color=discord.Color.red()
                    )
                    
                    error_embed.add_field(
                        name="What to do", 
                        value="Please try again later or contact an administrator if the issue persists.", 
                        inline=False
                    )
                    
                    await confirm_interaction.followup.send(embed=error_embed, ephemeral=True)
                    await interaction.edit_original_response(content="Deauthentication failed! ❌", embed=None, view=None)
            
            except Exception as e:
                # Catch any other errors
                error_embed = discord.Embed(
                    title="❌ Deauthentication Failed",
                    description=f"An error occurred during deauthentication: {str(e)}",
                    color=discord.Color.red()
                )
                
                error_embed.add_field(
                    name="What to do", 
                    value="Please try again later or contact an administrator if the issue persists.", 
                    inline=False
                )
                
                await confirm_interaction.followup.send(embed=error_embed, ephemeral=True)
                await interaction.edit_original_response(content="Deauthentication failed! ❌", embed=None, view=None)
            
            # Disable the buttons
            view.clear_items()
            await interaction.edit_original_response(view=view)
        
        async def cancel_callback(cancel_interaction):
            if cancel_interaction.user != interaction.user:
                await cancel_interaction.response.send_message("This is not your deauthentication process.", ephemeral=True)
                return
            
            await cancel_interaction.response.defer(ephemeral=True)
            await cancel_interaction.followup.send("Deauthentication cancelled.", ephemeral=True)
            await interaction.edit_original_response(content="Deauthentication cancelled. ❌", embed=None, view=None)
        
        confirm_button.callback = confirm_callback
        cancel_button.callback = cancel_callback
        
        view.add_item(confirm_button)
        view.add_item(cancel_button)
        
        confirm_embed = discord.Embed(
    title="⚠️ Confirm Deauthentication",
    description=f"Are you sure you want to remove the Codeforces authentication for {target_user.mention}?"
)

        # Send the confirmation embed with view
        await interaction.followup.send(embed=confirm_embed, view=view, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Authentication(bot))