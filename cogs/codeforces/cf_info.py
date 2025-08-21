from discord.ext import commands
from discord import app_commands
import discord
import aiohttp
from utility.db_helpers import get_user_info

class CFInfo(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="cf_info", description="Display Codeforces account information")
    @app_commands.describe(user="The user to get information about (leave empty for your own info)")
    async def cf_info(self, interaction: discord.Interaction, user: discord.Member = None):
        """Display Codeforces account information for yourself or another user"""
        
        await interaction.response.defer(ephemeral=False)
        
        # Determine which user to check
        target_user = user if user else interaction.user
        
        # Get the session for API calls
        session = getattr(self.bot, "session", None)
        if not session:
            session = aiohttp.ClientSession()
            should_close = True
        else:
            should_close = False
        
        try:
            # Get user info from database
            user_info = await get_user_info(str(target_user.id), session)
            
            if not user_info["exists"]:
                if target_user == interaction.user:
                    message = "You haven't linked a Codeforces account yet. Use `/authenticate` to link your account."
                    await interaction.followup.send(message, ephemeral=True)
                else:
                    message = f"{target_user.mention} hasn't linked a Codeforces account yet."
                    await interaction.followup.send(message, ephemeral=True)
                return
            
            # Get additional info from Codeforces API
            cf_handle = user_info["cf_handle"]
            
            # Fetch user info
            url = f"https://codeforces.com/api/user.info?handles={cf_handle}"
            try:
                async with session.get(url) as response:
                    if response.status != 200:
                        api_data = None
                    else:
                        api_data = await response.json()
                        if api_data["status"] != "OK":
                            api_data = None
            except Exception as e:
                print(f"Error fetching CF user info: {e}")
                api_data = None
            
            # Create embed with user information
            if target_user == interaction.user:
                title = "Your Codeforces Information"
                description = "Here's your account information:"
            else:
                title = f"{target_user.display_name}'s Codeforces Information"
                description = "Here's the account information:"
            
            embed = discord.Embed(
                title=title,
                description=description,
                color=discord.Color.blue()
            )
            
            # Add user avatar
            embed.set_author(name=target_user.display_name, icon_url=target_user.display_avatar.url)
            
            # Add basic fields
            embed.add_field(name="Discord ID", value=user_info["discord_id"], inline=True)
            embed.add_field(name="Codeforces Handle", value=cf_handle, inline=True)
            
            # Add API-based information if available
            if api_data and "result" in api_data and api_data["result"]:
                cf_user = api_data["result"][0]
                
                # Add rating and rank
                rating = cf_user.get("rating", "Unrated")
                rank = cf_user.get("rank", "Unrated")
                max_rating = cf_user.get("maxRating", "Unrated")
                max_rank = cf_user.get("maxRank", "Unrated")
                
                embed.add_field(name="Current Rating", value=str(rating), inline=True)
                embed.add_field(name="Current Rank", value=rank.capitalize() if isinstance(rank, str) else "Unrated", inline=True)
                embed.add_field(name="Max Rating", value=str(max_rating), inline=True)
                embed.add_field(name="Max Rank", value=max_rank.capitalize() if isinstance(max_rank, str) else "Unrated", inline=True)
                
                # Set thumbnail to user's CF avatar
                if "titlePhoto" in cf_user:
                    embed.set_thumbnail(url=cf_user["titlePhoto"])
            else:
                # If API data not available, show basic info
                embed.add_field(name="Rating & Rank", value="Could not fetch from Codeforces API", inline=True)
            
            # Add view with button to profile
            view = discord.ui.View()
            view.add_item(
                discord.ui.Button(
                    label="View on Codeforces",
                    url=f"https://codeforces.com/profile/{cf_handle}",
                    style=discord.ButtonStyle.url
                )
            )
            
            await interaction.followup.send(embed=embed, view=view)
    
        finally:
            if should_close:
                await session.close()

async def setup(bot: commands.Bot):
    await bot.add_cog(CFInfo(bot))
