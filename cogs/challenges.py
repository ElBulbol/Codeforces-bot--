from discord.ext import commands
from discord import app_commands
from typing import Dict, Optional
import discord
import aiohttp
import re
import time
from utility.random_problems import get_random_problem
from utility.constants import CHALLENGE_CHANNEL_ID
from utility.db_helpers import (
    get_cf_handle,
    get_user_score,
    get_custom_leaderboard,
    create_challenge,
    add_challenge_participant,
    get_user_by_discord,
    get_challenge_history,
    get_user_challenge_history,
    increment_user_problems_solved
)


def _parse_contest_and_index_from_link(link: str) -> Optional[Dict[str, str]]:
    # Expected: https://codeforces.com/contest/{contestId}/problem/{index}
    m = re.search(r"/contest/(\d+)/problem/([A-Za-z0-9]+)", link)
    if not m:
        return None
    return {
        "contestId": int(m.group(1)), 
        "index": m.group(2),
        "link": link
    }

async def _cf_check_solved(session: aiohttp.ClientSession, handle: str, contest_id: int, index: str, since_ts: int) -> bool:
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
                # Only count solves after challenge was created
                if sub.get("creationTimeSeconds", 0) >= since_ts:
                    return True
        return False
    except Exception as e:
        print(f"Error checking CF problem solved: {e}")
        return False

# ---------------- Cog Implementation ---------------- #

class Challenges(commands.GroupCog, name = "challenge"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    # The _SolveView class for tracking challenges
    class _SolveView(discord.ui.View):
        def __init__(self, challenge_id, participants, handle_map, contest_id, index, started_ts, bot, cog, problem_name, problem_link):
            super().__init__(timeout=None)  # No timeout for challenge tracking
            self.challenge_id = challenge_id
            self.participants = set(user.id for user in participants)
            self.handle_map = handle_map
            self.contest_id = contest_id
            self.index = index
            self.started_ts = started_ts
            self.bot = bot
            self.cog = cog
            self.problem_name = problem_name
            self.problem_link = problem_link
            self.finished = set()
            self.surrendered = set()
            self.finish_order = []  # Track order of completion
        
        @discord.ui.button(label="Check If Solved", style=discord.ButtonStyle.green)
        async def check_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id not in self.participants:
                await interaction.response.send_message("You are not part of this challenge.", ephemeral=True)
                return
            
            await interaction.response.defer(ephemeral=True)
            
            # Get user's CF handle
            user_id = str(interaction.user.id)
            if user_id not in self.handle_map or not self.handle_map[user_id]:
                await interaction.followup.send("You don't have a linked Codeforces handle.", ephemeral=True)
                return
            
            handle = self.handle_map[user_id]
            
            # Check if the problem is solved
            session = getattr(self.bot, "session", None)
            solved = False
            
            if session:
                solved = await _cf_check_solved(session, handle, self.contest_id, self.index, self.started_ts)
            else:
                async with aiohttp.ClientSession() as tmp_session:
                    solved = await _cf_check_solved(tmp_session, handle, self.contest_id, self.index, self.started_ts)
            
            if solved:
                if interaction.user.id not in self.finished:
                    self.finished.add(interaction.user.id)
                    self.finish_order.append(interaction.user.id)
                    
                    # Calculate rank and points
                    rank = len(self.finish_order)
                    points = max(100 - (rank - 1) * 10, 10)  # 100, 90, 80, ..., minimum 10
                    
                    # Save to database
                    await self._save_challenge_result(user_id, rank, points)
                    
                if interaction.user.id in self.surrendered:
                    self.surrendered.remove(interaction.user.id)
                
                await interaction.followup.send("✅ Congratulations! You've solved the problem!", ephemeral=True)
                
                # Update the message to reflect the current status
                await self._update_status(interaction)
            else:
                await interaction.followup.send("❌ You haven't solved this problem yet.", ephemeral=True)
        
        @discord.ui.button(label="Surrender", style=discord.ButtonStyle.danger)
        async def surrender(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id not in self.participants:
                await interaction.response.send_message("You are not part of this challenge.", ephemeral=True)
                return
            
            await interaction.response.defer(ephemeral=True)
            
            self.surrendered.add(interaction.user.id)
            if interaction.user.id in self.finished:
                self.finished.remove(interaction.user.id)
                # Remove from finish order if they were there
                if interaction.user.id in self.finish_order:
                    self.finish_order.remove(interaction.user.id)
            
            # Save surrender to database (0 points, no rank)
            await self._save_challenge_result(str(interaction.user.id), None, 0, is_surrender=True)
            
            await interaction.followup.send("You have surrendered this challenge.", ephemeral=True)
            
            # Update the message to reflect the current status
            await self._update_status(interaction)
        
        async def _save_challenge_result(self, discord_id: str, rank: int = None, points: int = 0, is_surrender: bool = False):
            """Save challenge result to database"""
            try:
                # Get user - don't create if doesn't exist (only authenticated users can participate)
                user = await get_user_by_discord(discord_id)
                if not user:
                    print(f"Warning: User {discord_id} not found in database, skipping challenge result save")
                    return
                
                user_id = user['user_id']
                
                # Add challenge participant record
                finish_time = int(time.time()) if not is_surrender else None
                await add_challenge_participant(
                    challenge_id=self.challenge_id,
                    user_id=user_id,
                    score_awarded=points,
                    is_winner=(rank == 1) if rank else False,
                    finish_time=finish_time,
                    rank=rank
                )
                
                # If user successfully solved the problem (not surrender), increment their bot problems count
                if not is_surrender and rank is not None:
                    await increment_user_problems_solved(discord_id)
                
            except Exception as e:
                print(f"Error saving challenge result: {e}")
        
        async def _update_status(self, interaction):
            # Create an updated embed
            embed = discord.Embed(
                title="Challenge Status Update",
                description=f"Challenge ID: {self.challenge_id}",
                color=discord.Color.blue()
            )
            
            # Format the completed users (in order of completion)
            if self.finished:
                finished_names = []
                for i, user_id in enumerate(self.finish_order):
                    if user_id in self.finished:  # Double check they're still in finished set
                        member = interaction.guild.get_member(user_id)
                        name = member.display_name if member else f"User {user_id}"
                        handle = self.handle_map.get(str(user_id), "Unknown")
                        rank = i + 1
                        points = max(100 - (rank - 1) * 10, 10)
                        finished_names.append(f"{rank}. {name} ({handle}) - {points} pts")
                
                embed.add_field(
                    name="✅ Completed",
                    value="\n".join(finished_names) if finished_names else "None",
                    inline=False
                )
            
            # Format the surrendered users
            if self.surrendered:
                surrender_names = []
                for user_id in self.surrendered:
                    member = interaction.guild.get_member(user_id)
                    name = member.display_name if member else f"User {user_id}"
                    handle = self.handle_map.get(str(user_id), "Unknown")
                    surrender_names.append(f"{name} ({handle})")
                
                embed.add_field(
                    name="❌ Surrendered",
                    value=", ".join(surrender_names),
                    inline=False
                )
                
            # If everyone has finished or surrendered, show completion message
            if self.finished.union(self.surrendered) == self.participants:
                if self.finished:
                    winner_id = self.finish_order[0] if self.finish_order else None
                    if winner_id:
                        winner = interaction.guild.get_member(winner_id)
                        winner_name = winner.display_name if winner else f"User {winner_id}"
                        embed.add_field(
                            name="🏆 Challenge Complete",
                            value=f"🎉 Challenge completed! Winner: **{winner_name}**",
                            inline=False
                        )
                    else:
                        embed.add_field(
                            name="🏆 Challenge Complete",
                            value="🎉 Challenge completed!",
                            inline=False
                        )
                else:
                    embed.add_field(
                        name="Challenge Complete",
                        value="Challenge ended - all participants surrendered.",
                        inline=False
                    )
                
                await interaction.channel.send(embed=embed)
    
    @app_commands.command(
        name="create", 
        description="Challenge users to solve a CF problem. Members must be mentioned and authenticated."
    )
    @app_commands.describe(
        members="Comma-separated list of mentions or IDs to challenge",
        tags="Problem tags (e.g., 'dp,graphs') or 'random'",
        rating="Problem rating (e.g., '800') or 'random'"
    )
    async def challenge(self, interaction: discord.Interaction, members: str, tags: str = "random", rating: str = "random"):
        """Challenge users to solve a Codeforces problem"""
        print("Challenge command called!")
        await interaction.response.defer()
        
        # Check if the command user is authenticated
        challenger_user = await get_user_by_discord(str(interaction.user.id))
        if not challenger_user:
            await interaction.followup.send(
                "You need to authenticate with `/authenticate` before creating challenges.",
                ephemeral=True
            )
            return
        
        # Parse mentions (supports comma-separated, space-separated, or both)
        user_ids = set()
        for segment in members.replace(',', ' ').split():
            match = re.search(r'<@!?(\d+)>', segment)
            if match:
                user_ids.add(int(match.group(1)))
    
        # Get the challenged members
        challenged_members = []
        for user_id in user_ids:
            member = interaction.guild.get_member(user_id)
            if member and not member.bot:
                challenged_members.append(member)
    
        if not challenged_members:
            await interaction.followup.send("No valid members were found to challenge.", ephemeral=True)
            return
    
        # Check which members are authenticated (in the users table)
        authenticated_members = []
        unauthenticated_members = []
        
        for member in challenged_members:
            user_data = await get_user_by_discord(str(member.id))
            if user_data:
                authenticated_members.append(member)
            else:
                unauthenticated_members.append(member)
        
        # Handle case where no one is authenticated
        if not authenticated_members:
            await interaction.followup.send(
                "None of the mentioned users are authenticated. Users need to link their Codeforces account with `/authenticate` first.",
                ephemeral=True
            )
            return
        
        # Prepare warning message for unauthenticated users
        if unauthenticated_members:
            unauth_mentions = ", ".join(m.mention for m in unauthenticated_members)
            warning_text = (
                "The following users will be ignored because they are not authenticated:\n"
                f"**Not authenticated:** {unauth_mentions}. They must use `/authenticate` to participate."
            )
            await interaction.followup.send(warning_text, ephemeral=True)
    
        # Continue with only authenticated members
        valid_members = authenticated_members
    
        # Get problem based on rating and tags
        session = getattr(self.bot, "session", None)
        if session is None:
            async with aiohttp.ClientSession() as tmp_session:
                problem = await get_random_problem(tmp_session, type_of_problem=tags, rating=rating)
        else:
            problem = await get_random_problem(session, type_of_problem=tags, rating=rating)
    
        if not problem:
            await interaction.followup.send(
                "Couldn't find a problem matching these criteria. Try different tags or rating.",
                ephemeral=True
            )
            return
    
        # Create challenge in database
        problem_id = f"{problem.get('contestId', 0)}{problem.get('index', '')}"
        challenge_id = await create_challenge(
            problem_id=problem_id,
            problem_name=problem['name'],
            problem_link=problem['link']
        )
    
        # Prepare the challenge view
        class ChallengeView(discord.ui.View):
            def __init__(self, bot, challenge_id, valid_users, problem):
                super().__init__(timeout=300)  # 5 minute timeout
                self.bot = bot
                self.challenge_id = challenge_id
                self.valid_users = {user.id for user in valid_users}
                self.accepted_users = set()
                self.rejected_users = set()
                self.problem = problem
            
            async def interaction_check(self, interaction):
                # Only allow challenged users to interact with buttons
                if interaction.user.id not in self.valid_users:
                    await interaction.response.send_message(
                        "This challenge isn't for you.", 
                        ephemeral=True
                    )
                    return False
                return True
            
            @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
            async def accept_button(self, interaction, button):
                # Mark user as accepted
                self.accepted_users.add(interaction.user.id)
            
                # Remove from rejected if they changed their mind
                if interaction.user.id in self.rejected_users:
                    self.rejected_users.remove(interaction.user.id)
            
                # Update the original message to reflect the status
                await self._update_message(interaction)
            
                # Acknowledge the button press
                await interaction.response.send_message(
                    f"You accepted the challenge to solve {self.problem['name']}!", 
                    ephemeral=True
                )
            
            @discord.ui.button(label="Reject", style=discord.ButtonStyle.red)
            async def reject_button(self, interaction, button):
                # Mark user as rejected
                self.rejected_users.add(interaction.user.id)
            
                # Remove from accepted if they changed their mind
                if interaction.user.id in self.accepted_users:
                    self.accepted_users.remove(interaction.user.id)
            
                # Update the original message to reflect the status
                await self._update_message(interaction)
            
                # Acknowledge the button press
                await interaction.response.send_message(
                    "You rejected the challenge.", 
                    ephemeral=True
                )
            
            async def _update_message(self, interaction):
                # Get the original message
                message = interaction.message
            
                # Create a new embed with updated information
                embed = discord.Embed(
                    title=f"Codeforces Challenge: {self.problem['name']}",
                    url=self.problem['link'],
                    description=f"Rating: {self.problem['rating']}\nTags: {', '.join(self.problem['tags'])}",
                    color=discord.Color.blue()
                )
            
                # Add status fields
                accepted_list = []
                for user_id in self.accepted_users:
                    user = interaction.guild.get_member(user_id)
                    if user:
                        accepted_list.append(user.mention)
            
                rejected_list = []
                for user_id in self.rejected_users:
                    user = interaction.guild.get_member(user_id)
                    if user:
                        rejected_list.append(user.mention)
            
                pending_list = []
                for user_id in self.valid_users:
                    if user_id not in self.accepted_users and user_id not in self.rejected_users:
                        user = interaction.guild.get_member(user_id)
                        if user:
                            pending_list.append(user.mention)
            
                if accepted_list:
                    embed.add_field(
                        name="✅ Accepted",
                        value=", ".join(accepted_list),
                        inline=False
                    )
            
                if rejected_list:
                    embed.add_field(
                        name="❌ Rejected",
                        value=", ".join(rejected_list),
                        inline=False
                    )
            
                if pending_list:
                    embed.add_field(
                        name="⏳ Pending",
                        value=", ".join(pending_list),
                        inline=False
                    )
            
                embed.set_footer(text=f"Challenge ID: {self.challenge_id} | Initiated by {interaction.guild.get_member(interaction.user.id).display_name}")
            
                # Update the message
                await message.edit(embed=embed, view=self)
            
                # If everyone has responded, start tracking solves
                if not pending_list:
                    if accepted_list:
                        # Create a solve tracking task
                        self.bot.loop.create_task(
                            self._start_solve_tracking(interaction.channel, [
                                interaction.guild.get_member(uid) for uid in self.accepted_users
                            ])
                        )
                    else:
                        # Everyone rejected
                        await interaction.channel.send(
                            "Challenge canceled - all participants rejected."
                        )
            
            async def _start_solve_tracking(self, channel, accepted_members):
                # Create a new message with solve tracking view
                accepted_ids = [m.id for m in accepted_members]

                # Get CF handles for participants
                handle_map = {}
                for member in accepted_members:
                    cf_handle = await get_cf_handle(str(member.id))
                    if cf_handle:
                        handle_map[str(member.id)] = cf_handle
                    else:
                        # Notify if a user doesn't have a linked handle
                        await channel.send(f"⚠️ {member.mention} doesn't have a linked Codeforces handle. Their solutions won't be tracked.")
                        handle_map[str(member.id)] = ""

                # Extract contest ID and problem index from the link
                parsed = _parse_contest_and_index_from_link(self.problem["link"])
                if not parsed:
                    await channel.send("Error parsing problem link. Solve tracking unavailable.")
                    return

                contest_id = parsed["contestId"]
                index = parsed["index"]

                # Send the message with the solve tracking view
                solve_view = Challenges._SolveView(
                    challenge_id=self.challenge_id,
                    participants=accepted_members,
                    handle_map=handle_map,
                    contest_id=contest_id,
                    index=index,
                    started_ts=int(time.time()),
                    bot=self.bot,
                    cog=self.bot.get_cog("Challenges"),
                    problem_name=self.problem['name'],
                    problem_link=self.problem['link']
                )
            
                embed = discord.Embed(
                    title=f"Challenge Started: {self.problem['name']}",
                    url=self.problem['link'],
                    description=f"The challenge has begun! Use the buttons below to mark when you're done or to surrender.",
                    color=discord.Color.green()
                )
            
                embed.add_field(
                    name="Participants",
                    value=", ".join(m.mention for m in accepted_members),
                    inline=False
                )
            
                embed.add_field(
                    name="Rating",
                    value=str(self.problem['rating']),
                    inline=True
                )
            
                embed.add_field(
                    name="Tags",
                    value=", ".join(self.problem['tags']),
                    inline=True
                )
            
                await channel.send(embed=embed, view=solve_view)
    
        # Create the initial embed
        embed = discord.Embed(
            title=f"Codeforces Challenge: {problem['name']}",
            url=problem['link'],
            description=f"Rating: {problem['rating']}\nTags: {', '.join(problem['tags'])}",
            color=discord.Color.blue()
        )
    
        # Add participant field
        valid_mentions = ", ".join(m.mention for m in valid_members)
        embed.add_field(
            name="Challenged Users",
            value=valid_mentions,
            inline=False
        )
    
        embed.add_field(
            name="Status",
            value="Waiting for responses...",
            inline=False
        )
    
        embed.set_footer(text=f"Challenge ID: {challenge_id} | Initiated by {interaction.user.display_name}")
    
        # Create the view with buttons
        view = ChallengeView(self.bot, challenge_id, valid_members, problem)
    
        # Get the specified channel
        challenge_channel = self.bot.get_channel(CHALLENGE_CHANNEL_ID)
    
        if challenge_channel:
            # Send to the designated channel
            await challenge_channel.send(
                f"New challenge from {interaction.user.mention} to {valid_mentions}!",
                embed=embed,
                view=view
            )
            
            # Notify the user that the challenge was created
            await interaction.followup.send(
                f"Challenge created in <#{challenge_channel.id}>!",
                ephemeral=True
            )
        else:
            # Fallback to the current channel if the specified one isn't found
            await interaction.followup.send(
                f"Challenge channel not found. Creating challenge here instead.",
                embed=embed,
                view=view
            )

    @app_commands.command(name="history", description="View recent challenge history")
    @app_commands.describe(
        user="View history for a specific user (optional)",
        limit="Number of challenges to show (default: 10)"
    )
    async def challenge_history(self, interaction: discord.Interaction, user: discord.Member = None, limit: int = 10):
        """View challenge history"""
        await interaction.response.defer(ephemeral=False)
        
        # Validate and cap the limit
        if limit < 1:
            limit = 10
        elif limit > 50:
            limit = 50
        
        if user:
            # Get history for specific user
            history_data = await get_user_challenge_history(str(user.id), limit)
            title = f"🏆 Challenge History for {user.display_name}"
        else:
            # Get general challenge history
            history_data = await get_challenge_history(limit)
            title = "🏆 Recent Challenge History"
        
        if not history_data:
            await interaction.followup.send(
                "No challenge history found.",
                ephemeral=False
            )
            return
        
        # Create the embed
        embed = discord.Embed(
            title=title,
            color=discord.Color.blue()
        )
        
        # Format history entries
        entries = []
        for entry in history_data:
            if user:
                # User-specific format
                rank_str = f"#{entry['rank']}" if entry['rank'] else "Surrendered"
                points_str = f"{entry['points']} pts" if entry['points'] > 0 else "0 pts"
                time_str = f"<t:{int(entry['timestamp'].timestamp()) if hasattr(entry['timestamp'], 'timestamp') else entry['timestamp']}:R>"
                
                entries.append(f"**{entry['problem_name']}** - {rank_str} ({points_str}) {time_str}")
            else:
                # General format - show user info
                member = interaction.guild.get_member(int(entry['discord_id']))
                user_name = member.display_name if member else entry['cf_handle']
                rank_str = f"#{entry['rank']}" if entry['rank'] else "Surrendered"
                points_str = f"{entry['points']} pts" if entry['points'] > 0 else "0 pts"
                
                entries.append(f"**{entry['problem_name']}** - {user_name} {rank_str} ({points_str})")
        
        if entries:
            # Split into multiple fields if too long
            description = "\n".join(entries)
            if len(description) <= 4096:
                embed.description = description
            else:
                # Split into multiple fields
                current_field = ""
                field_count = 1
                for entry in entries:
                    if len(current_field + "\n" + entry) <= 1024:
                        current_field += "\n" + entry if current_field else entry
                    else:
                        embed.add_field(
                            name=f"History (Part {field_count})",
                            value=current_field,
                            inline=False
                        )
                        current_field = entry
                        field_count += 1
                
                # Add the last field
                if current_field:
                    embed.add_field(
                        name=f"History (Part {field_count})",
                        value=current_field,
                        inline=False
                    )
        else:
            embed.description = "No entries found."
        
        # Add timestamp
        embed.timestamp = discord.utils.utcnow()
        embed.set_footer(text=f"Requested by {interaction.user.display_name}")
        
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="leaderboard", description="View the scoring leaderboard")
    @app_commands.describe(
        category="The scoring category to view",
        limit="Number of users to show (default: 10)"
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="Daily Points", value="daily"),
        app_commands.Choice(name="Weekly Points", value="weekly"),
        app_commands.Choice(name="Monthly Points", value="monthly"),
        app_commands.Choice(name="Overall Points", value="overall"),
        app_commands.Choice(name="Problems Solved", value="solved")
    ])
    async def leaderboard(
        self, 
        interaction: discord.Interaction, 
        category: str = "overall",
        limit: int = 10
    ):
        """View the scoring leaderboard"""
        await interaction.response.defer(ephemeral=False)
        
        # Validate and cap the limit
        if limit < 1:
            limit = 10
        elif limit > 50:
            limit = 50
        
        # Get the leaderboard data
        leaderboard_data = await get_custom_leaderboard(category, limit)
        
        if not leaderboard_data:
            await interaction.followup.send(
                "No users found in the leaderboard. Users need to link their Codeforces accounts with `/authenticate`.",
                ephemeral=False
            )
            return
        
        # Map category to display name
        category_names = {
            "daily": "Daily Points",
            "weekly": "Weekly Points",
            "monthly": "Monthly Points",
            "overall": "Overall Points",
            "solved": "Problems Solved"
        }
        category_display = category_names.get(category, "Overall Points")
        
        # Create the embed
        embed = discord.Embed(
            title=f"🏆 Challenges Leaderboard ({category_display})",
            description=f"Top {limit} users",
            color=discord.Color.gold()
        )
        
        # Format leaderboard entries
        entries = []
        for entry in leaderboard_data:
            # Try to get member object for mention
            user = interaction.guild.get_member(int(entry["discord_id"]))
            if user:
                name = user.mention
            else:
                name = f"{entry['codeforces_name']}"
        
            entries.append(f"{entry['rank']}. {name} - **{entry['score']}**")
        
        if entries:
            embed.description = "\n".join(entries)
        else:
            embed.description = "No entries found."
        
        # Add timestamp
        embed.timestamp = discord.utils.utcnow()
        embed.set_footer(text=f"Requested by {interaction.user.display_name}")
        
        await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Challenges(bot))