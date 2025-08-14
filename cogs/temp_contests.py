
# warning this is demo ha ya moahmed ayman , eyad ! 
import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import os
import datetime
import aiohttp
import asyncio
import time as time_module  # Rename the time module import to avoid conflicts
import re
from typing import List, Dict, Optional, Set, Tuple
import json

TEMP_CONTESTS_DB = "temp_contests.db"

def _parse_cf_problem_link(link: str) -> Optional[Dict[str, str]]:
    # Expected: https://codeforces.com/contest/{contestId}/problem/{index}
    m = re.search(r"/contest/(\d+)/problem/([A-Za-z0-9]+)", link)
    if not m:
        return None
    return {
        "contestId": int(m.group(1)), 
        "index": m.group(2), 
        "link": link,
        "platform": "codeforces"
    }

def _parse_datetime(datetime_str: str) -> Optional[datetime.datetime]:
    try:
        return datetime.datetime.strptime(datetime_str, "%d/%m/%y %H:%M")
    except ValueError:
        return None

async def _check_cf_problem_solved(session: aiohttp.ClientSession, handle: str, contest_id: int, index: str, since_ts: int) -> bool:
    url = f"https://codeforces.com/api/user.status?handle={handle}"
    try:
        async with session.get(url) as resp:
            data = await resp.json()
            
        if data.get("status") != "OK":
            return False

        for sub in data["result"]:
            if sub.get("verdict") != "OK":
                continue
            prob = sub.get("problem", {})
            if prob.get("contestId") == contest_id and prob.get("index") == index:
                if sub.get("creationTimeSeconds", 0) >= since_ts:
                    return True
        return False
    except Exception as e:
        print(f"Error checking CF problem solved: {e}")
        return False

async def _load_cf_handles() -> Dict[str, str]:
    cf_links_file = "cf_links.json"
    if not os.path.exists(cf_links_file):
        return {}
    
    try:
        with open(cf_links_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading CF handles: {e}")
        return {}

class JoinContestView(discord.ui.View):
    def __init__(self, contest_id: str, contest_name: str):
        super().__init__(timeout=None)
        self.contest_id = contest_id
        self.contest_name = contest_name
    
    @discord.ui.button(label="Join Contest", style=discord.ButtonStyle.success, custom_id=f"join_contest")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        temp_contests_cog = interaction.client.get_cog("TempContests")
        if not temp_contests_cog:
            await interaction.response.send_message("Contest system unavailable. Please try again later.", ephemeral=True)
            return
        
        success = await temp_contests_cog.add_participant(self.contest_id, interaction.user.id)
        
        if success:
            await interaction.response.send_message(
                f"You've successfully joined the contest: **{self.contest_name}**! "
                f"Good luck and have fun! Use `/leader-board-temp {self.contest_id}` to check the leaderboard.", 
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"You've already joined this contest or the contest doesn't exist.", 
                ephemeral=True
            )

class ProblemCheckView(discord.ui.View):
    def __init__(self, contest_id: str, problems: List[Dict], bot: commands.Bot):
        super().__init__(timeout=None)
        self.contest_id = contest_id
        self.problems = problems
        self.bot = bot
        
        for i, problem in enumerate(problems):
            label = f"Check Problem {problem.get('index', str(i+1))}"
            self.add_item(ProblemCheckButton(contest_id, i, label))

class ProblemCheckButton(discord.ui.Button):
    def __init__(self, contest_id: str, problem_idx: int, label: str):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label=label,
            custom_id=f"check_problem_{contest_id}_{problem_idx}"
        )
        self.contest_id = contest_id
        self.problem_idx = problem_idx
    
    async def callback(self, interaction: discord.Interaction):
        temp_contests_cog = interaction.client.get_cog("TempContests")
        if not temp_contests_cog:
            await interaction.response.send_message("Contest system unavailable. Please try again later.", ephemeral=True)
            return
        
        is_participant = await temp_contests_cog.is_participant(self.contest_id, interaction.user.id)
        if not is_participant:
            await interaction.response.send_message(
                "You need to join this contest first! Check your DMs for the invitation or ask a moderator.", 
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        
        result = await temp_contests_cog.check_problem_solved(
            self.contest_id, 
            interaction.user.id, 
            self.problem_idx
        )
        
        if result["solved"]:
            await interaction.followup.send(
                f"Congratulations! You've solved this problem and earned {result['points']} points!", 
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                "You haven't solved this problem yet. Keep trying!", 
                ephemeral=True
            )

class TempContests(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_lock = asyncio.Lock()
        self.db_init()
        self.check_ended_contests.start()
        self.active_contests = {}  # contest_id -> contest data (for quick access)
    
    def cog_unload(self):
        self.check_ended_contests.cancel()
    
    def db_init(self):
        """Initialize the database for temporary contests"""
        conn = sqlite3.connect(TEMP_CONTESTS_DB)
        cursor = conn.cursor()
        
        # Contests table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS temp_contests (
            contest_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            creator_id TEXT NOT NULL,
            start_time INTEGER NOT NULL,
            end_time INTEGER NOT NULL,
            problems TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            created_at INTEGER NOT NULL
        )
        ''')
        
        # Participants table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS temp_contest_participants (
            contest_id TEXT,
            user_id TEXT,
            joined_at INTEGER NOT NULL,
            score INTEGER DEFAULT 0,
            PRIMARY KEY (contest_id, user_id),
            FOREIGN KEY (contest_id) REFERENCES temp_contests(contest_id)
        )
        ''')
        
        # Solved problems table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS temp_contest_solved (
            contest_id TEXT,
            user_id TEXT,
            problem_idx INTEGER,
            solved_time INTEGER NOT NULL,
            points INTEGER DEFAULT 0,
            PRIMARY KEY (contest_id, user_id, problem_idx),
            FOREIGN KEY (contest_id, user_id) REFERENCES temp_contest_participants(contest_id, user_id)
        )
        ''')
        
        conn.commit()
        conn.close()
    
    async def load_active_contests(self):
        """Load active contests into memory cache"""
        async with self.db_lock:
            try:
                conn = sqlite3.connect(TEMP_CONTESTS_DB)
                cursor = conn.cursor()
                
                cursor.execute("SELECT * FROM temp_contests WHERE active = 1")
                contests = cursor.fetchall()
                
                for contest in contests:
                    contest_id = contest[0]
                    self.active_contests[contest_id] = {
                        "contest_id": contest_id,
                        "name": contest[1],
                        "creator_id": contest[2],
                        "start_time": contest[3],
                        "end_time": contest[4],
                        "problems": json.loads(contest[5]),
                        "active": contest[6],
                        "created_at": contest[7]
                    }
                
                conn.close()
                print(f"Loaded {len(self.active_contests)} active contests")
            except Exception as e:
                print(f"Error loading active contests: {e}")
    
    @tasks.loop(minutes=1)
    async def check_ended_contests(self):
        """Check for contests that have ended and mark them as inactive"""
        current_time = int(time_module.time())
        
        async with self.db_lock:
            try:
                conn = sqlite3.connect(TEMP_CONTESTS_DB)
                cursor = conn.cursor()
                
                # Find contests that have ended
                cursor.execute(
                    "SELECT contest_id, name FROM temp_contests WHERE end_time <= ? AND active = 1", 
                    (current_time,)
                )
                ended_contests = cursor.fetchall()
                
                for contest_id, name in ended_contests:
                    # Mark as inactive
                    cursor.execute(
                        "UPDATE temp_contests SET active = 0 WHERE contest_id = ?", 
                        (contest_id,)
                    )
                    
                    # Remove from active contests cache
                    if contest_id in self.active_contests:
                        del self.active_contests[contest_id]
                    
                    print(f"Contest ended: {name} ({contest_id})")
                
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"Error checking ended contests: {e}")
    
    @check_ended_contests.before_loop
    async def before_check_ended_contests(self):
        await self.bot.wait_until_ready()
        await self.load_active_contests()
    
    async def create_contest(self, name: str, end_time: int, problems: List[Dict], creator_id: str) -> str:
        """Create a new temporary contest"""
        contest_id = f"contest_{int(time_module.time())}_{name.lower().replace(' ', '_')}"
        start_time = int(time_module.time())
        
        async with self.db_lock:
            try:
                conn = sqlite3.connect(TEMP_CONTESTS_DB)
                cursor = conn.cursor()
                
                cursor.execute(
                    "INSERT INTO temp_contests (contest_id, name, creator_id, start_time, end_time, problems, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        contest_id, 
                        name, 
                        creator_id, 
                        start_time, 
                        end_time, 
                        json.dumps(problems), 
                        start_time
                    )
                )
                
                conn.commit()
                conn.close()
                
                # Add to active contests cache
                self.active_contests[contest_id] = {
                    "contest_id": contest_id,
                    "name": name,
                    "creator_id": creator_id,
                    "start_time": start_time,
                    "end_time": end_time,
                    "problems": problems,
                    "active": 1,
                    "created_at": start_time
                }
                
                return contest_id
            except Exception as e:
                print(f"Error creating contest: {e}")
                return None
    
    async def get_contest(self, contest_id: str) -> Optional[Dict]:
        """Get contest data by ID"""
        # First check in-memory cache
        if contest_id in self.active_contests:
            return self.active_contests[contest_id]
        
        # Otherwise check database
        async with self.db_lock:
            try:
                conn = sqlite3.connect(TEMP_CONTESTS_DB)
                cursor = conn.cursor()
                
                cursor.execute("SELECT * FROM temp_contests WHERE contest_id = ?", (contest_id,))
                contest = cursor.fetchone()
                
                conn.close()
                
                if not contest:
                    return None
                
                return {
                    "contest_id": contest[0],
                    "name": contest[1],
                    "creator_id": contest[2],
                    "start_time": contest[3],
                    "end_time": contest[4],
                    "problems": json.loads(contest[5]),
                    "active": contest[6],
                    "created_at": contest[7]
                }
            except Exception as e:
                print(f"Error getting contest {contest_id}: {e}")
                return None
    
    async def add_participant(self, contest_id: str, user_id: int) -> bool:
        """Add a participant to a contest"""
        # Check if contest exists and is active
        contest = await self.get_contest(contest_id)
        if not contest or not contest["active"]:
            return False
        
        # Check if user is already a participant
        if await self.is_participant(contest_id, user_id):
            return False
        
        async with self.db_lock:
            try:
                conn = sqlite3.connect(TEMP_CONTESTS_DB)
                cursor = conn.cursor()
                
                joined_at = int(time_module.time())
                cursor.execute(
                    "INSERT INTO temp_contest_participants (contest_id, user_id, joined_at) VALUES (?, ?, ?)",
                    (contest_id, str(user_id), joined_at)
                )
                
                conn.commit()
                conn.close()
                return True
            except Exception as e:
                print(f"Error adding participant {user_id} to contest {contest_id}: {e}")
                return False
    
    async def is_participant(self, contest_id: str, user_id: int) -> bool:
        """Check if a user is a participant in a contest"""
        async with self.db_lock:
            try:
                conn = sqlite3.connect(TEMP_CONTESTS_DB)
                cursor = conn.cursor()
                
                cursor.execute(
                    "SELECT 1 FROM temp_contest_participants WHERE contest_id = ? AND user_id = ?",
                    (contest_id, str(user_id))
                )
                
                result = cursor.fetchone() is not None
                conn.close()
                return result
            except Exception as e:
                print(f"Error checking if user {user_id} is in contest {contest_id}: {e}")
                return False
    
    async def get_participants(self, contest_id: str) -> List[Tuple[str, int]]:
        """Get all participants in a contest with their scores"""
        async with self.db_lock:
            try:
                conn = sqlite3.connect(TEMP_CONTESTS_DB)
                cursor = conn.cursor()
                
                cursor.execute(
                    "SELECT user_id, score FROM temp_contest_participants WHERE contest_id = ? ORDER BY score DESC",
                    (contest_id,)
                )
                
                participants = cursor.fetchall()
                conn.close()
                return participants
            except Exception as e:
                print(f"Error getting participants for contest {contest_id}: {e}")
                return []
    
    async def get_user_solved_problems(self, contest_id: str, user_id: int) -> List[int]:
        """Get indices of problems a user has solved in a contest"""
        async with self.db_lock:
            try:
                conn = sqlite3.connect(TEMP_CONTESTS_DB)
                cursor = conn.cursor()
                
                cursor.execute(
                    "SELECT problem_idx FROM temp_contest_solved WHERE contest_id = ? AND user_id = ?",
                    (contest_id, str(user_id))
                )
                
                solved = [row[0] for row in cursor.fetchall()]
                conn.close()
                return solved
            except Exception as e:
                print(f"Error getting solved problems for user {user_id} in contest {contest_id}: {e}")
                return []
    
    async def check_problem_solved(self, contest_id: str, user_id: int, problem_idx: int) -> Dict:
        """
        Check if a user has solved a specific problem in a contest
        Returns a dict with keys:
        - solved: bool
        - points: int (if solved)
        """
        # Get contest info
        contest = await self.get_contest(contest_id)
        if not contest or not contest["active"]:
            return {"solved": False}
        
        # Check if user is a participant
        if not await self.is_participant(contest_id, user_id):
            return {"solved": False}
        
        # Check if user has already solved this problem
        solved_problems = await self.get_user_solved_problems(contest_id, user_id)
        if problem_idx in solved_problems:
            return {"solved": True, "points": 0}  # Already solved, no new points
        
        # Get problem details
        if problem_idx >= len(contest["problems"]):
            return {"solved": False}
        
        problem = contest["problems"][problem_idx]
        
        # Get user's CF handle
        cf_handles = await _load_cf_handles()
        cf_handle = cf_handles.get(str(user_id))
        if not cf_handle:
            return {"solved": False}
        
        # Check if the problem is solved
        session = getattr(self.bot, "session", None)
        if session is None:
            async with aiohttp.ClientSession() as tmp_session:
                is_solved = await _check_cf_problem_solved(
                    tmp_session, 
                    cf_handle, 
                    problem["contestId"],
                    problem["index"], 
                    contest["start_time"]
                )
        else:
            is_solved = await _check_cf_problem_solved(
                session, 
                cf_handle, 
                problem["contestId"], 
                problem["index"], 
                contest["start_time"]
            )
        
        if not is_solved:
            return {"solved": False}
        
        # If solved, record it and update points
        points = 10  # Base points per problem
        
        async with self.db_lock:
            try:
                conn = sqlite3.connect(TEMP_CONTESTS_DB)
                cursor = conn.cursor()
                
                # Record solved problem
                solved_time = int(time_module.time())
                cursor.execute(
                    "INSERT INTO temp_contest_solved (contest_id, user_id, problem_idx, solved_time, points) VALUES (?, ?, ?, ?, ?)",
                    (contest_id, str(user_id), problem_idx, solved_time, points)
                )
                
                # Update user's score
                cursor.execute(
                    "UPDATE temp_contest_participants SET score = score + ? WHERE contest_id = ? AND user_id = ?",
                    (points, contest_id, str(user_id))
                )
                
                conn.commit()
                conn.close()
                
                return {"solved": True, "points": points}
            except Exception as e:
                print(f"Error recording solved problem: {e}")
                return {"solved": True, "points": 0}
    
    async def get_active_contests(self) -> List[Dict]:
        """Get all active contests"""
        # Return from cache if available
        if self.active_contests:
            return list(self.active_contests.values())
        
        # Otherwise check database
        async with self.db_lock:
            try:
                conn = sqlite3.connect(TEMP_CONTESTS_DB)
                cursor = conn.cursor()
                
                cursor.execute("SELECT * FROM temp_contests WHERE active = 1")
                contests = cursor.fetchall()
                
                result = []
                for contest in contests:
                    result.append({
                        "contest_id": contest[0],
                        "name": contest[1],
                        "creator_id": contest[2],
                        "start_time": contest[3],
                        "end_time": contest[4],
                        "problems": json.loads(contest[5]),
                        "active": contest[6],
                        "created_at": contest[7]
                    })
                
                conn.close()
                return result
            except Exception as e:
                print(f"Error getting active contests: {e}")
                return []
    
    @app_commands.command(
        name="create_leader_board",
        description="Create a temporary contest with a separate leaderboard (MOD only)"
    )
    @app_commands.describe(
        name="Name of the contest",
        time="End time in format dd/mm/yy hh:mm",
        problems="Comma-separated list of Codeforces problem links"
    )
    @app_commands.checks.has_role("MOD")
    async def create_leader_board(self, interaction: discord.Interaction, name: str, time: str, problems: str):
        """Create a temporary contest with a separate leaderboard"""
        await interaction.response.defer()
        
        # Parse end time
        end_time = _parse_datetime(time)
        if not end_time:
            await interaction.followup.send("Invalid time format. Please use dd/mm/yy hh:mm", ephemeral=True)
            return
        
        # Convert to timestamp
        end_timestamp = int(end_time.timestamp())
        
        # Check if end time is in the future
        current_time = int(time_module.time())
        if end_timestamp <= current_time:
            await interaction.followup.send("Contest end time must be in the future.", ephemeral=True)
            return
        
        # Parse problems
        problem_links = [p.strip() for p in problems.split(",")]
        parsed_problems = []
        
        for link in problem_links:
            problem = _parse_cf_problem_link(link)
            if problem:
                parsed_problems.append(problem)
        
        if not parsed_problems:
            await interaction.followup.send(
                "No valid Codeforces problem links found. "
                "Links should be in format: https://codeforces.com/contest/{contestId}/problem/{index}", 
                ephemeral=True
            )
            return
        
        # Create the contest
        contest_id = await self.create_contest(
            name=name,
            end_time=end_timestamp,
            problems=parsed_problems,
            creator_id=str(interaction.user.id)
        )
        
        if not contest_id:
            await interaction.followup.send("Failed to create contest. Please try again.", ephemeral=True)
            return
        
        # Create problem list embed
        embed = discord.Embed(
            title=f"Contest: {name}",
            description=f"Created by {interaction.user.mention}\nEnds: <t:{end_timestamp}:f> (<t:{end_timestamp}:R>)",
            color=discord.Color.blue()
        )
        
        for i, problem in enumerate(parsed_problems):
            embed.add_field(
                name=f"Problem {i+1}: {problem['index']}",
                value=f"[Link]({problem['link']})",
                inline=True
            )
        
        # Create problem check view
        problem_view = ProblemCheckView(contest_id, parsed_problems, self.bot)
        
        # Send confirmation message
        await interaction.followup.send(
            f"Contest **{name}** created successfully! Contest ID: `{contest_id}`\n"
            f"Use `/leader-board-temp {contest_id}` to check the leaderboard.",
            embed=embed,
            view=problem_view
        )
        
        # Send DMs to users with CP role
        cp_role = discord.utils.get(interaction.guild.roles, name="CP")
        if not cp_role:
            await interaction.followup.send("CP role not found. No notifications sent.", ephemeral=True)
            return
        
        # Create join view for DMs
        join_view = JoinContestView(contest_id, name)
        
        # Create DM embed
        dm_embed = discord.Embed(
            title=f"New Contest: {name}",
            description=f"A new contest has been created by {interaction.user.display_name}!\n"
                       f"Ends: <t:{end_timestamp}:f> (<t:{end_timestamp}:R>)",
            color=discord.Color.green()
        )
        
        for i, problem in enumerate(parsed_problems):
            dm_embed.add_field(
                name=f"Problem {i+1}: {problem['index']}",
                value=f"[Link]({problem['link']})",
                inline=True
            )
        
        # Send DMs to all users with CP role
        sent_count = 0
        failed_count = 0
        for member in cp_role.members:
            try:
                await member.send(
                    f"You're invited to join a new contest: **{name}**!",
                    embed=dm_embed,
                    view=join_view
                )
                sent_count += 1
            except Exception as e:
                print(f"Failed to send DM to {member.name}: {e}")
                failed_count += 1
        
        # Send a public message to a specific channel for those who couldn't receive DMs
        try:
            # Use the specific channel ID for public announcements
            public_channel = interaction.guild.get_channel(1404857696666128405)
            
            if public_channel:
                # Create a slightly modified embed for the public announcement
                public_embed = discord.Embed(
                    title=f"New Contest: {name}",
                    description=f"A new contest has been created by {interaction.user.mention}!\n"
                              f"Ends: <t:{end_timestamp}:f> (<t:{end_timestamp}:R>)\n\n"
                              f"**Click the button below to join!**\n\n"
                              f"If you couldn't receive a DM, you can join through this message.",
                    color=discord.Color.blue()
                )
                
                for i, problem in enumerate(parsed_problems):
                    public_embed.add_field(
                        name=f"Problem {i+1}: {problem['index']}",
                        value=f"[Link]({problem['link']})",
                        inline=True
                    )
                
                # Send the public announcement with the join button
                await public_channel.send(
                    f"{cp_role.mention} A new contest is available!",
                    embed=public_embed,
                    view=join_view
                )
                
                await interaction.followup.send(
                    f"Sent notifications to {sent_count} members with CP role via DM.\n"
                    f"Failed to send DMs to {failed_count} members.\n"
                    f"A public announcement was also posted in <#{public_channel.id}>.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"Sent notifications to {sent_count} members with CP role via DM.\n"
                    f"Failed to send DMs to {failed_count} members.\n"
                    f"Could not find the announcement channel (ID: 1404857696666128405).",
                    ephemeral=True
                )
        except Exception as e:
            print(f"Failed to send public announcement: {e}")
            await interaction.followup.send(
                f"Sent notifications to {sent_count} members with CP role via DM.\n"
                f"Failed to send DMs to {failed_count} members.\n"
                f"Failed to send public announcement: {str(e)}",
                ephemeral=True
            )
    
    @app_commands.command(
        name="leader-board-temp",
        description="Show the leaderboard for a temporary contest"
    )
    @app_commands.describe(
        contest_id="ID of the contest (optional - shows list of active contests if omitted)"
    )
    async def leader_board_temp(self, interaction: discord.Interaction, contest_id: str = None):
        """Show the leaderboard for a temporary contest"""
        await interaction.response.defer()
        
        # If no contest ID, show list of active contests
        if not contest_id:
            active_contests = await self.get_active_contests()
            
            if not active_contests:
                await interaction.followup.send("There are no active contests right now.")
                return
            
            embed = discord.Embed(
                title="Active Contests",
                description="Here are the currently active contests:",
                color=discord.Color.blue()
            )
            
            for contest in active_contests:
                embed.add_field(
                    name=contest["name"],
                    value=f"ID: `{contest['contest_id']}`\n"
                          f"Created by: <@{contest['creator_id']}>\n"
                          f"Ends: <t:{contest['end_time']}:R>\n"
                          f"Problems: {len(contest['problems'])}\n"
                          f"Use `/leader-board-temp {contest['contest_id']}` to view",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
            return
        
        # Get contest info
        contest = await self.get_contest(contest_id)
        if not contest:
            await interaction.followup.send(f"Contest with ID `{contest_id}` not found.")
            return
        
        # Get participants and their scores
        participants = await self.get_participants(contest_id)
        
        if not participants:
            await interaction.followup.send(
                f"No participants have joined the contest **{contest['name']}** yet."
            )
            return
        
        # Create leaderboard embed
        embed = discord.Embed(
            title=f"Leaderboard: {contest['name']}",
            description=f"Created by <@{contest['creator_id']}>\n"
                       f"Status: {'Active' if contest['active'] else 'Ended'}\n"
                       f"{'Ends' if contest['active'] else 'Ended'}: <t:{contest['end_time']}:f> (<t:{contest['end_time']}:R>)",
            color=discord.Color.gold() if contest['active'] else discord.Color.light_grey()
        )
        
        # Add participants to leaderboard
        for i, (user_id, score) in enumerate(participants, 1):
            user = interaction.guild.get_member(int(user_id))
            name = user.display_name if user else f"User {user_id}"
            
            # Get solved problems
            solved_problems = await self.get_user_solved_problems(contest_id, int(user_id))
            solved_count = len(solved_problems)
            total_problems = len(contest['problems'])
            
            # Format solved indicators
            problem_indicators = []
            for idx in range(total_problems):
                if idx in solved_problems:
                    problem_indicators.append("✅")
                else:
                    problem_indicators.append("❌")
            
            embed.add_field(
                name=f"{i}. {name}",
                value=f"**{score} points** - Solved: {solved_count}/{total_problems}\n"
                     f"Problems: {' '.join(problem_indicators)}",
                inline=False
            )
        
        await interaction.followup.send(embed=embed)
    
    @app_commands.command(
        name="join-contest",
        description="Join a temporary contest"
    )
    @app_commands.describe(
        contest_id="ID of the contest to join"
    )
    async def join_contest(self, interaction: discord.Interaction, contest_id: str):
        """Join a temporary contest"""
        await interaction.response.defer(ephemeral=True)
        
        # Check if contest exists and is active
        contest = await self.get_contest(contest_id)
        if not contest:
            await interaction.followup.send(f"Contest with ID `{contest_id}` not found.", ephemeral=True)
            return
        
        if not contest["active"]:
            await interaction.followup.send(f"Contest **{contest['name']}** has already ended.", ephemeral=True)
            return
        
        # Check if user is already a participant
        if await self.is_participant(contest_id, interaction.user.id):
            await interaction.followup.send(f"You're already participating in this contest!", ephemeral=True)
            return
        
        # Add user to participants
        success = await self.add_participant(contest_id, interaction.user.id)
        
        if success:
            # Create problem list embed
            embed = discord.Embed(
                title=f"Contest: {contest['name']}",
                description=f"Ends: <t:{contest['end_time']}:f> (<t:{contest['end_time']}:R>)",
                color=discord.Color.blue()
            )
            
            for i, problem in enumerate(contest["problems"]):
                embed.add_field(
                    name=f"Problem {i+1}: {problem['index']}",
                    value=f"[Link]({problem['link']})",
                    inline=True
                )
            
            # Create problem check view
            problem_view = ProblemCheckView(contest_id, contest["problems"], self.bot)
            
            await interaction.followup.send(
                f"You've successfully joined the contest: **{contest['name']}**!\n"
                f"Good luck and have fun! Use `/leader-board-temp {contest_id}` to check the leaderboard.",
                embed=embed,
                view=problem_view,
                ephemeral=True
            )
        else:
            await interaction.followup.send("Failed to join the contest. Please try again.", ephemeral=True)
    
    @app_commands.command(
        name="end-contest",
        description="End a temporary contest early (MOD only)"
    )
    @app_commands.describe(
        contest_id="ID of the contest to end"
    )
    @app_commands.checks.has_role("MOD")
    async def end_contest(self, interaction: discord.Interaction, contest_id: str):
        """End a temporary contest early"""
        await interaction.response.defer()
        
        # Check if contest exists and is active
        contest = await self.get_contest(contest_id)
        if not contest:
            await interaction.followup.send(f"Contest with ID `{contest_id}` not found.")
            return
        
        if not contest["active"]:
            await interaction.followup.send(f"Contest **{contest['name']}** has already ended.")
            return
        
        # End the contest
        async with self.db_lock:
            try:
                conn = sqlite3.connect(TEMP_CONTESTS_DB)
                cursor = conn.cursor()
                
                cursor.execute(
                    "UPDATE temp_contests SET active = 0, end_time = ? WHERE contest_id = ?",
                    (int(time_module.time()), contest_id)
                )
                
                conn.commit()
                conn.close()
                
                # Remove from active contests cache
                if contest_id in self.active_contests:
                    del self.active_contests[contest_id]
                
                await interaction.followup.send(f"Contest **{contest['name']}** has been ended early.")
                
                # Show final leaderboard
                await self.leader_board_temp(interaction, contest_id)
            except Exception as e:
                print(f"Error ending contest {contest_id}: {e}")
                await interaction.followup.send("Failed to end the contest. Please try again.")

async def setup(bot: commands.Bot):
    await bot.add_cog(TempContests(bot))