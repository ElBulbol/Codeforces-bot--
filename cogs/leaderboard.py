import discord
from discord.ext import commands, tasks
from discord import app_commands
import datetime
import asyncio
import time
from utility.db_helpers import (
    get_leaderboard_user,
    add_leaderboard_points, 
    get_leaderboard_by_type,
    reset_leaderboard_scores,
    get_user_leaderboard_rank,
    sync_cf_handles_from_file,
    add_challenge_history
)

class Leaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reset_daily.start()
        self.reset_weekly.start()
        self.reset_monthly.start()
        
    def cog_unload(self):
        """Stop the tasks when the cog is unloaded"""
        self.reset_daily.cancel()
        self.reset_weekly.cancel()
        self.reset_monthly.cancel()
    
    @tasks.loop(time=datetime.time(hour=0, minute=0))  # Reset daily at midnight
    async def reset_daily(self):
        """Reset daily scores at midnight"""
        try:
            await reset_leaderboard_scores("daily_score")
            print(f"[{datetime.datetime.now()}] Daily scores reset")
        except Exception as e:
            print(f"Error resetting daily scores: {e}")
    
    @tasks.loop(time=datetime.time(hour=0, minute=0))  # Check weekly reset on every midnight
    async def reset_weekly(self):
        """Reset weekly scores at midnight on Monday"""
        if datetime.datetime.now().weekday() == 0:  # Monday is 0
            try:
                await reset_leaderboard_scores("weekly_score")
                print(f"[{datetime.datetime.now()}] Weekly scores reset")
            except Exception as e:
                print(f"Error resetting weekly scores: {e}")
    
    @tasks.loop(time=datetime.time(hour=0, minute=0))  # Check monthly reset on every midnight
    async def reset_monthly(self):
        """Reset monthly scores on the first day of each month"""
        if datetime.datetime.now().day == 1:
            try:
                await reset_leaderboard_scores("monthly_score")
                print(f"[{datetime.datetime.now()}] Monthly scores reset")
            except Exception as e:
                print(f"Error resetting monthly scores: {e}")
    
    async def get_user(self, discord_id):
        """Get a user from the database, create if not exists"""
        try:
            user_data = await get_leaderboard_user(str(discord_id))
            return (
                user_data["discord_id"],
                user_data.get("cf_handle"),
                user_data.get("daily_score", 0),
                user_data.get("weekly_score", 0),
                user_data.get("monthly_score", 0),
                user_data.get("overall_score", 0)
            )
        except Exception as e:
            print(f"Error getting user {discord_id}: {e}")
            return (str(discord_id), None, 0, 0, 0, 0)
    
    def add_points(self, discord_id, rank, challenge_data=None):
        """Add points based on rank"""
        points = 0
        if rank == 1:
            points = 25
        elif rank == 2:
            points = 18
        elif rank == 3:
            points = 15
        elif rank == 4:
            points = 12
        elif rank == 5:
            points = 10
        elif rank == 6:
            points = 8
        elif rank == 7:
            points = 6
        elif rank == 8:
            points = 4
        elif rank == 9:
            points = 2
        else:
            points = 1
        
        try:
            # Add points using helper function
            asyncio.create_task(add_leaderboard_points(str(discord_id), points))
            
            # Record the challenge in history if challenge data is provided
            if challenge_data:
                # Get cf_handle from user data
                user_task = asyncio.create_task(get_leaderboard_user(str(discord_id)))
                
                async def record_history():
                    try:
                        user_data = await user_task
                        cf_handle = user_data.get("cf_handle", "Unknown")
                        problem_name = challenge_data.get("problem", {}).get("name", "Unknown Problem")
                        problem_link = challenge_data.get("problem", {}).get("link", "")
                        
                        # Use challenge_id from the outer object, not inside challenge_data
                        challenge_id = getattr(challenge_data, "challenge_id", str(int(time.time())))
                        
                        await add_challenge_history(
                            challenge_id,
                            str(discord_id),
                            cf_handle,
                            problem_name,
                            problem_link,
                            challenge_data.get("finish_time", int(time.time())),
                            rank,
                            points,
                            int(datetime.datetime.now().timestamp())
                        )
                    except Exception as e:
                        print(f"Error recording challenge history: {e}")
                
                asyncio.create_task(record_history())
            
            return points
        except Exception as e:
            print(f"Error adding points for user {discord_id}: {e}")
            return points
    
    async def get_leaderboard(self, score_type):
        """Get the leaderboard for a specific score type"""
        try:
            if score_type not in ["daily_score", "weekly_score", "monthly_score", "overall_score"]:
                score_type = "overall_score"
            
            leaderboard_data = await get_leaderboard_by_type(score_type, 20)
            return [(entry["discord_id"], entry["score"]) for entry in leaderboard_data]
        except Exception as e:
            print(f"Error getting leaderboard for {score_type}: {e}")
            return []
    
    async def sync_cf_handles(self):
        """Sync CF handles from CF_LINKS_FILE to the database"""
        try:
            # Path to the CF links file from the codeforces cog
            cf_links_file = "cf_links.json"
            await sync_cf_handles_from_file(cf_links_file)
        except Exception as e:
            print(f"Error syncing CF handles: {e}")
    
    @app_commands.command(name="daily_leaderboard", description="Show the daily leaderboard")
    async def daily_leaderboard(self, interaction: discord.Interaction):
        """Show the daily leaderboard"""
        await interaction.response.defer()  # Defer response to avoid timeout
        
        try:
            await self.sync_cf_handles()  # Make sure CF handles are up to date
            leaderboard = await self.get_leaderboard("daily_score")
            
            if not leaderboard:
                await interaction.followup.send("No scores on the daily leaderboard yet.")
                return
            
            embed = discord.Embed(
                title="Daily Leaderboard",
                description="Top performers for today",
                color=discord.Color.gold()
            )
            
            for i, (discord_id, score) in enumerate(leaderboard, 1):
                member = interaction.guild.get_member(int(discord_id))
                name = member.display_name if member else f"User {discord_id}"
                embed.add_field(
                    name=f"{i}. {name}",
                    value=f"**{score} points**",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
        except Exception as e:
            print(f"Error in daily_leaderboard command: {e}")
            await interaction.followup.send("An error occurred while retrieving the leaderboard.")
    
    @app_commands.command(name="weekly_leaderboard", description="Show the weekly leaderboard")
    async def weekly_leaderboard(self, interaction: discord.Interaction):
        """Show the weekly leaderboard"""
        await interaction.response.defer()
        
        try:
            await self.sync_cf_handles()
            leaderboard = await self.get_leaderboard("weekly_score")
            
            if not leaderboard:
                await interaction.followup.send("No scores on the weekly leaderboard yet.")
                return
            
            embed = discord.Embed(
                title="Weekly Leaderboard",
                description="Top performers this week",
                color=discord.Color.blue()
            )
            
            for i, (discord_id, score) in enumerate(leaderboard, 1):
                member = interaction.guild.get_member(int(discord_id))
                name = member.display_name if member else f"User {discord_id}"
                embed.add_field(
                    name=f"{i}. {name}",
                    value=f"**{score} points**",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
        except Exception as e:
            print(f"Error in weekly_leaderboard command: {e}")
            await interaction.followup.send("An error occurred while retrieving the leaderboard.")
    
    @app_commands.command(name="monthly_leaderboard", description="Show the monthly leaderboard")
    async def monthly_leaderboard(self, interaction: discord.Interaction):
        """Show the monthly leaderboard"""
        await interaction.response.defer()
        
        try:
            await self.sync_cf_handles()
            leaderboard = await self.get_leaderboard("monthly_score")
            
            if not leaderboard:
                await interaction.followup.send("No scores on the monthly leaderboard yet.")
                return
            
            embed = discord.Embed(
                title="Monthly Leaderboard",
                description="Top performers this month",
                color=discord.Color.green()
            )
            
            for i, (discord_id, score) in enumerate(leaderboard, 1):
                member = interaction.guild.get_member(int(discord_id))
                name = member.display_name if member else f"User {discord_id}"
                embed.add_field(
                    name=f"{i}. {name}",
                    value=f"**{score} points**",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
        except Exception as e:
            print(f"Error in monthly_leaderboard command: {e}")
            await interaction.followup.send("An error occurred while retrieving the leaderboard.")
    
    @app_commands.command(name="overall_leaderboard", description="Show the overall leaderboard")
    async def overall_leaderboard(self, interaction: discord.Interaction):
        """Show the overall leaderboard"""
        await interaction.response.defer()
        
        try:
            await self.sync_cf_handles()
            leaderboard = await self.get_leaderboard("overall_score")
            
            if not leaderboard:
                await interaction.followup.send("No scores on the overall leaderboard yet.")
                return
            
            embed = discord.Embed(
                title="Overall Leaderboard",
                description="All-time top performers",
                color=discord.Color.purple()
            )
            
            for i, (discord_id, score) in enumerate(leaderboard, 1):
                member = interaction.guild.get_member(int(discord_id))
                name = member.display_name if member else f"User {discord_id}"
                embed.add_field(
                    name=f"{i}. {name}",
                    value=f"**{score} points**",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
        except Exception as e:
            print(f"Error in overall_leaderboard command: {e}")
            await interaction.followup.send("An error occurred while retrieving the leaderboard.")
    
    @app_commands.command(name="my_stats", description="Show your leaderboard statistics")
    async def my_stats(self, interaction: discord.Interaction):
        """Show your personal statistics"""
        await interaction.response.defer()
        
        try:
            await self.sync_cf_handles()
            discord_id = str(interaction.user.id)
            
            user = await self.get_user(discord_id)
            
            if not user or (user[2] == 0 and user[3] == 0 and user[4] == 0 and user[5] == 0):
                await interaction.followup.send("You don't have any points yet. Solve some challenges to earn points!")
                return
            
            cf_handle = user[1] if user[1] else "Not linked"
            daily = user[2]
            weekly = user[3]
            monthly = user[4]
            overall = user[5]
            
            embed = discord.Embed(
                title=f"Stats for {interaction.user.display_name}",
                description=f"CodeForces Handle: {cf_handle}",
                color=discord.Color.brand_green()
            )
            
            embed.add_field(name="Daily Score", value=str(daily), inline=True)
            embed.add_field(name="Weekly Score", value=str(weekly), inline=True)
            embed.add_field(name="Monthly Score", value=str(monthly), inline=True)
            embed.add_field(name="Overall Score", value=str(overall), inline=False)
            
            # Get ranks for each leaderboard
            try:
                for score_type, score_name in [
                    ("daily_score", "Daily Rank"), 
                    ("weekly_score", "Weekly Rank"), 
                    ("monthly_score", "Monthly Rank"),
                    ("overall_score", "Overall Rank")
                ]:
                    rank = await get_user_leaderboard_rank(discord_id, score_type)
                    embed.add_field(name=score_name, value=f"#{rank}", inline=True)
            except Exception as e:
                print(f"Error getting ranks for user {discord_id}: {e}")
            
            await interaction.followup.send(embed=embed)
        except Exception as e:
            print(f"Error in my_stats command: {e}")
            await interaction.followup.send("An error occurred while retrieving your stats.")

async def setup(bot: commands.Bot):
    await bot.add_cog(Leaderboard(bot))
