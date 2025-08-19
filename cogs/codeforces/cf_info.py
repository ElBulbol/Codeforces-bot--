from discord.ext import commands
from discord import app_commands
import discord
import aiohttp
from utility.db_helpers import get_user_info

class CFInfo(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="show_status", description="Display your Codeforces profile and stats")
    @app_commands.describe(user="The user to get information about (leave empty for your own info)")
    async def show_status(self, interaction: discord.Interaction, user: discord.Member = None):
        """Display Codeforces account information for yourself or another user"""
        await self._send_status(interaction, user)

    @app_commands.command(name="my_status", description="Display your Codeforces profile and stats (yourself only)")
    async def my_status(self, interaction: discord.Interaction):
        """Display Codeforces account information for yourself only"""
        await self._send_status(interaction, None)

    async def _send_status(self, interaction: discord.Interaction, user: discord.Member = None):
        await interaction.response.defer(ephemeral=False)
        target_user = user if user else interaction.user

        session = getattr(self.bot, "session", None)
        if not session:
            session = aiohttp.ClientSession()
            should_close = True
        else:
            should_close = False

        try:
            user_info = await get_user_info(str(target_user.id), session)
            if not user_info["exists"]:
                if target_user == interaction.user:
                    message = "You haven't linked a Codeforces account yet. Use `/authenticate` to link your account."
                    await interaction.followup.send(message, ephemeral=True)
                else:
                    message = f"{target_user.mention} hasn't linked a Codeforces account yet."
                    await interaction.followup.send(message, ephemeral=True)
                return

            cf_handle = user_info["cf_handle"]
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
            embed.set_author(name=target_user.display_name, icon_url=target_user.display_avatar.url)
            embed.add_field(name="Discord ID", value=user_info["discord_id"], inline=True)
            embed.add_field(name="Codeforces Handle", value=cf_handle, inline=True)

            if api_data and "result" in api_data and api_data["result"]:
                cf_user = api_data["result"][0]
                rating = cf_user.get("rating", "Unrated")
                rank = cf_user.get("rank", "Unrated")
                max_rating = cf_user.get("maxRating", "Unrated")
                max_rank = cf_user.get("maxRank", "Unrated")
                embed.add_field(name="Current Rating", value=str(rating), inline=True)
                embed.add_field(name="Current Rank", value=rank.capitalize() if isinstance(rank, str) else "Unrated", inline=True)
                embed.add_field(name="Max Rating", value=str(max_rating), inline=True)
                embed.add_field(name="Max Rank", value=max_rank.capitalize() if isinstance(max_rank, str) else "Unrated", inline=True)
                if "titlePhoto" in cf_user:
                    embed.set_thumbnail(url=cf_user["titlePhoto"])
            else:
                embed.add_field(name="Rating & Rank", value="Could not fetch from Codeforces API", inline=True)

            embed.add_field(name="Number of Problems Solved", value=str(user_info.get("Number_of_problem_solved", 0)), inline=True)

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
