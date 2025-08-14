import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import os
import datetime
import aiohttp
from typing import List, Dict, Optional, Tuple
import asyncio
import time

DB_PATH = "leaderboard.db"

class Leaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_init()
        self.reset_daily.start()
        self.reset_weekly.start()
        self.reset_monthly.start()
        self.db_lock = asyncio.Lock()  
        
    def db_init(self):
        """Initialize the database if it doesn't exist"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Create users table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            discord_id TEXT PRIMARY KEY,
            cf_handle TEXT,
            daily_score INTEGER DEFAULT 0,
            weekly_score INTEGER DEFAULT 0,
            monthly_score INTEGER DEFAULT 0,
            overall_score INTEGER DEFAULT 0
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS challenge_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            challenge_id TEXT,
            discord_id TEXT,
            cf_handle TEXT,
            problem_name TEXT,
            problem_link TEXT,
            finish_time INTEGER,
            rank INTEGER,
            points INTEGER,
            timestamp INTEGER
        )
        ''')
        
        conn.commit()
        conn.close()
    
    def cog_unload(self):
        """Stop the tasks when the cog is unloaded"""
        self.reset_daily.cancel()
        self.reset_weekly.cancel()
        self.reset_monthly.cancel()
    
    @tasks.loop(time=datetime.time(hour=0, minute=0))  # Reset daily at midnight
    async def reset_daily(self):
        """Reset daily scores at midnight"""
        async with self.db_lock:
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET daily_score = 0")
                conn.commit()
                conn.close()
                print(f"[{datetime.datetime.now()}] Daily scores reset")
            except Exception as e:
                print(f"Error resetting daily scores: {e}")
    
    @tasks.loop(time=datetime.time(hour=0, minute=0))  # Check weekly reset on every midnight
    async def reset_weekly(self):
        """Reset weekly scores at midnight on Monday"""
        if datetime.datetime.now().weekday() == 0:  # Monday is 0
            async with self.db_lock:
                try:
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.cursor()
                    cursor.execute("UPDATE users SET weekly_score = 0")
                    conn.commit()
                    conn.close()
                    print(f"[{datetime.datetime.now()}] Weekly scores reset")
                except Exception as e:
                    print(f"Error resetting weekly scores: {e}")
    
    @tasks.loop(time=datetime.time(hour=0, minute=0))  # Check monthly reset on every midnight
    async def reset_monthly(self):
        """Reset monthly scores on the first day of each month"""
        if datetime.datetime.now().day == 1:
            async with self.db_lock:
                try:
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.cursor()
                    cursor.execute("UPDATE users SET monthly_score = 0")
                    conn.commit()
                    conn.close()
                    print(f"[{datetime.datetime.now()}] Monthly scores reset")
                except Exception as e:
                    print(f"Error resetting monthly scores: {e}")
    
    async def get_user(self, discord_id):
        """Get a user from the database, create if not exists"""
        async with self.db_lock:
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                
                cursor.execute("SELECT * FROM users WHERE discord_id = ?", (str(discord_id),))
                user = cursor.fetchone()
                
                if not user:
                    cursor.execute("INSERT INTO users (discord_id) VALUES (?)", (str(discord_id),))
                    conn.commit()
                    user = (str(discord_id), None, 0, 0, 0, 0)
                
                conn.close()
                return user
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
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            # Get current user data
            cursor.execute("SELECT * FROM users WHERE discord_id = ?", (str(discord_id),))
            user = cursor.fetchone()
            
            if not user:
                # Create user if not exists
                cursor.execute(
                    "INSERT INTO users (discord_id, daily_score, weekly_score, monthly_score, overall_score) VALUES (?, ?, ?, ?, ?)",
                    (str(discord_id), points, points, points, points)
                )
            else:
                # Update existing user scores
                cursor.execute(
                    "UPDATE users SET daily_score = daily_score + ?, weekly_score = weekly_score + ?, "
                    "monthly_score = monthly_score + ?, overall_score = overall_score + ? WHERE discord_id = ?",
                    (points, points, points, points, str(discord_id))
                )
            
            # Record the challenge in history if challenge data is provided
            if challenge_data:
                cf_handle = user[1] if user and user[1] else "Unknown"
                problem_name = challenge_data.get("problem", {}).get("name", "Unknown Problem")
                problem_link = challenge_data.get("problem", {}).get("link", "")
                
                # Use challenge_id from the outer object, not inside challenge_data
                challenge_id = getattr(challenge_data, "challenge_id", str(int(time.time())))
                
                cursor.execute(
                    "INSERT INTO challenge_history (challenge_id, discord_id, cf_handle, problem_name, problem_link, "
                    "finish_time, rank, points, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
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
                )
            
            conn.commit()
            conn.close()
            return points
        except Exception as e:
            print(f"Error adding points for user {discord_id}: {e}")
            return points
    
    async def get_leaderboard(self, score_type):
        """Get the leaderboard for a specific score type"""
        async with self.db_lock:
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                
                if score_type not in ["daily_score", "weekly_score", "monthly_score", "overall_score"]:
                    score_type = "overall_score"
                
                cursor.execute(f"SELECT discord_id, {score_type} FROM users WHERE {score_type} > 0 ORDER BY {score_type} DESC LIMIT 20")
                leaderboard = cursor.fetchall()
                conn.close()
                return leaderboard
            except Exception as e:
                print(f"Error getting leaderboard for {score_type}: {e}")
                return []
    
    async def sync_cf_handles(self):
        """Sync CF handles from CF_LINKS_FILE to the database"""
        async with self.db_lock:
            try:
                # Path to the CF links file from the codeforces cog
                cf_links_file = "cf_links.json"
                if not os.path.exists(cf_links_file):
                    return
                
                import json
                with open(cf_links_file, 'r') as f:
                    links = json.load(f)
                
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                
                for discord_id, cf_handle in links.items():
                    cursor.execute("SELECT * FROM users WHERE discord_id = ?", (discord_id,))
                    user = cursor.fetchone()
                    
                    if not user:
                        cursor.execute(
                            "INSERT INTO users (discord_id, cf_handle) VALUES (?, ?)",
                            (discord_id, cf_handle)
                        )
                    else:
                        cursor.execute(
                            "UPDATE users SET cf_handle = ? WHERE discord_id = ?",
                            (cf_handle, discord_id)
                        )
                
                conn.commit()
                conn.close()
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
            async with self.db_lock:
                try:
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.cursor()
                    
                    for score_type, score_name in [
                        ("daily_score", "Daily Rank"), 
                        ("weekly_score", "Weekly Rank"), 
                        ("monthly_score", "Monthly Rank"),
                        ("overall_score", "Overall Rank")
                    ]:
                        cursor.execute(f"""
                            SELECT COUNT(*) + 1 FROM users 
                            WHERE {score_type} > (SELECT {score_type} FROM users WHERE discord_id = ?)
                        """, (discord_id,))
                        rank = cursor.fetchone()[0]
                        embed.add_field(name=score_name, value=f"#{rank}", inline=True)
                    
                    conn.close()
                except Exception as e:
                    print(f"Error getting ranks for user {discord_id}: {e}")
            
            await interaction.followup.send(embed=embed)
        except Exception as e:
            print(f"Error in my_stats command: {e}")
            await interaction.followup.send("An error occurred while retrieving your stats.")

async def setup(bot: commands.Bot):
    await bot.add_cog(Leaderboard(bot))