from discord.ext import commands
from discord import app_commands
import discord
import aiohttp
from utility.db_helpers import get_user_score # Use the more comprehensive helper

class CFInfo(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="show_status", description="Display a user's complete competitive status")
    @app_commands.describe(user="The user to get information about (leave empty for your own info)")
    async def show_status(self, interaction: discord.Interaction, user: discord.Member = None):
        """Display comprehensive Codeforces and server stats for a user."""
        
        await interaction.response.defer(ephemeral=False)
        
        target_user = user if user else interaction.user
        
        session = getattr(self.bot, "session", None)
        if not session:
            session = aiohttp.ClientSession()
            should_close = True
        else:
            should_close = False
        
        try:
            score_data = await get_user_score(str(target_user.id))
            
            if not score_data.get("exists"):
                message = f"{target_user.mention} hasn't linked a Codeforces account. Use `/authenticate` to link an account."
                await interaction.followup.send(message, ephemeral=True)
                return
            
            cf_handle = score_data["codeforces_name"]
            api_data = None
            
            url = f"https://codeforces.com/api/user.info?handles={cf_handle}"
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("status") == "OK":
                            api_data = data
            except Exception as e:
                print(f"Error fetching CF user info: {e}")
            
            embed = discord.Embed(
                title=f"📊 Competitive Status for {target_user.display_name}",
                color=discord.Color.purple()
            )

            # --- **FIXED THUMBNAIL LOGIC** ---
            # Default to the user's Discord avatar
            embed.set_thumbnail(url=target_user.display_avatar.url)
            
            # If API data is available, try to use the Codeforces avatar
            if api_data and api_data.get("result"):
                cf_user_api = api_data["result"][0]
                photo_url_path = cf_user_api.get("titlePhoto")

                # Check if the photo path exists and is not empty
                if photo_url_path:
                    # If it's a protocol-relative URL (starts with //), add https:
                    if photo_url_path.startswith("//"):
                        full_photo_url = f"https:{photo_url_path}"
                    # Otherwise, assume it's a full URL
                    else:
                        full_photo_url = photo_url_path
                    
                    # Set the thumbnail to the correctly formed URL
                    embed.set_thumbnail(url=full_photo_url)
            
            embed.add_field(
                name="Codeforces Profile",
                value=f"**[{cf_handle}](https://codeforces.com/profile/{cf_handle})**",
                inline=False
            )

            if api_data and api_data.get("result"):
                cf_user_api = api_data["result"][0]
                rating = cf_user_api.get("rating", "N/A")
                rank = cf_user_api.get("rank", "Unrated").capitalize()
                max_rating = cf_user_api.get("maxRating", "N/A")
                
                embed.add_field(name="📈 Rating", value=str(rating), inline=True)
                embed.add_field(name="🎖️ Rank", value=str(rank), inline=True)
                embed.add_field(name="⭐ Max Rating", value=str(max_rating), inline=True)
            else:
                embed.add_field(name="API Status", value="Could not fetch live CF data.", inline=False)
            
            embed.add_field(name="\u200b", value="**--- Server Stats ---**", inline=False)

            embed.add_field(name="🏆 Overall Points", value=f"**{score_data['overall_points']}**", inline=True)
            embed.add_field(name="🧩 Problems Solved", value=f"**{score_data['solved_problems']}**", inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)

            embed.add_field(name="🗓️ Monthly Points", value=str(score_data['monthly_points']), inline=True)
            embed.add_field(name="📅 Weekly Points", value=str(score_data['weekly_points']), inline=True)
            embed.add_field(name="☀️ Daily Points", value=str(score_data['daily_points']), inline=True)

            embed.set_footer(text=f"Requested by {interaction.user.display_name}")
            embed.timestamp = discord.utils.utcnow()
            
            await interaction.followup.send(embed=embed)
    
        finally:
            if should_close:
                await session.close()

async def setup(bot: commands.Bot):
    await bot.add_cog(CFInfo(bot))