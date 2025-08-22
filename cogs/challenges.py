from datetime import datetime
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
    get_custom_leaderboard,
    create_challenge,
    add_challenge_participant,
    get_user_by_discord,
    get_challenge_history,
    get_user_challenge_history,
    increment_user_problems_solved,
    get_challenge_details 
)


def _parse_contest_and_index_from_link(link: str) -> Optional[Dict[str, str]]:
    # Use a more robust regex to handle various URL formats including /gym/
    m = re.search(r'/(?:contest|problemset/problem|gym)/(\d+)/problem/([A-Z0-9]+)', link)
    if not m:
        return None
    return {
        "contestId": int(m.group(1)), 
        "index": m.group(2),
        "link": link
    }

async def _cf_check_solved(session: aiohttp.ClientSession, handle: str, contest_id: int, index: str, since_ts: int) -> Optional[Dict]:
    """
    Checks if a user has solved a problem since a certain timestamp.
    Returns the submission object if solved, otherwise None.
    """
    url = f"https://codeforces.com/api/contest.status?contestId={contest_id}&handle={handle}"
    try:
        async with session.get(url) as resp:
            data = await resp.json()
            
        if data.get("status") != "OK":
            return None

        for sub in data["result"]:
            if sub.get("verdict") != "OK":
                continue
            prob = sub.get("problem", {})
            if prob.get("contestId") == contest_id and prob.get("index") == index:
                # Only count solves after challenge was created
                if sub.get("creationTimeSeconds", 0) >= since_ts:
                    return sub # Return the submission object
        return None
    except Exception as e:
        print(f"Error checking CF problem solved: {e}")
        return None

# ---------------- Cog Implementation ---------------- #

class Challenges(commands.GroupCog, name = "challenge"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    # The _SolveView class for tracking challenges
    class _SolveView(discord.ui.View):
        def __init__(self, challenge_id, participants, handle_map, contest_id, index, started_ts, bot, cog, problem_name, problem_link, problem_rating):
            super().__init__(timeout=None)
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
            self.problem_rating = problem_rating
            self.finished = {} # Store user_id: points
            self.surrendered = set()
            self.finish_order = []
        
        @discord.ui.button(label="Check If Solved", style=discord.ButtonStyle.green)
        async def check_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id not in self.participants:
                await interaction.response.send_message("You are not part of this challenge.", ephemeral=True)
                return
            
            await interaction.response.defer(ephemeral=True)
            
            user_id = str(interaction.user.id)
            if user_id not in self.handle_map or not self.handle_map[user_id]:
                await interaction.followup.send("You don't have a linked Codeforces handle.", ephemeral=True)
                return
            
            handle = self.handle_map[user_id]
            
            session = getattr(self.bot, "session", aiohttp.ClientSession())
            accepted_submission = await _cf_check_solved(session, handle, self.contest_id, self.index, self.started_ts)
            
            if accepted_submission:
                if interaction.user.id not in self.finished:
                    self.finish_order.append(interaction.user.id)
                    
                    # MODIFIED: Calculate score based on problem rating
                    rating = accepted_submission['problem'].get('rating', 0)
                    points = rating // 100
                    if points == 0:
                        points = 10 # Fallback for unrated problems

                    self.finished[interaction.user.id] = points

                    await self._save_challenge_result(user_id, len(self.finish_order), points)
                    
                    if interaction.user.id in self.surrendered:
                        self.surrendered.remove(interaction.user.id)
                
                    await interaction.followup.send(f"✅ Congratulations! You've solved the problem and earned {points} points!", ephemeral=True)
                    await self._update_status(interaction)
                else:
                    await interaction.followup.send("You have already solved this challenge.", ephemeral=True)
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
                del self.finished[interaction.user.id]
                if interaction.user.id in self.finish_order:
                    self.finish_order.remove(interaction.user.id)
            
            await self._save_challenge_result(str(interaction.user.id), None, 0, is_surrender=True)
            await interaction.followup.send("You have surrendered this challenge.", ephemeral=True)
            await self._update_status(interaction)
        
        async def _save_challenge_result(self, discord_id: str, rank: int = None, points: int = 0, is_surrender: bool = False):
            """Save challenge result to database"""
            try:
                user = await get_user_by_discord(discord_id)
                if not user:
                    print(f"Warning: User {discord_id} not found in database, skipping challenge result save")
                    return
                
                user_id = user['user_id']
                
                finish_time = int(time.time()) if not is_surrender else None
                await add_challenge_participant(
                    challenge_id=self.challenge_id,
                    user_id=user_id,
                    score_awarded=points,
                    is_winner=(rank == 1) if rank else False,
                    finish_time=finish_time,
                    rank=rank
                )
                
                if not is_surrender and rank is not None:
                    await increment_user_problems_solved(discord_id)
            except Exception as e:
                print(f"Error saving challenge result: {e}")
        
        async def _update_status(self, interaction):
            embed = discord.Embed(
                title="Challenge Status Update",
                description=f"Challenge ID: `{self.challenge_id}`",
                color=discord.Color.blue()
            )
            
            if self.finished:
                finished_names = []
                for i, user_id in enumerate(self.finish_order):
                    if user_id in self.finished:
                        member = interaction.guild.get_member(user_id)
                        name = member.display_name if member else f"User {user_id}"
                        handle = self.handle_map.get(str(user_id), "Unknown")
                        points = self.finished[user_id]
                        finished_names.append(f"{i + 1}. {name} ({handle}) - {points} pts")
                
                embed.add_field(
                    name="✅ Completed",
                    value="\n".join(finished_names) if finished_names else "None",
                    inline=False
                )
            
            if self.surrendered:
                surrender_names = [interaction.guild.get_member(uid).display_name for uid in self.surrendered if interaction.guild.get_member(uid)]
                embed.add_field(
                    name="❌ Surrendered",
                    value=", ".join(surrender_names),
                    inline=False
                )
            
            if len(self.finished) + len(self.surrendered) == len(self.participants):
                winner_text = "Challenge ended - all participants surrendered."
                if self.finish_order:
                    winner_id = self.finish_order[0]
                    winner = interaction.guild.get_member(winner_id)
                    winner_name = winner.display_name if winner else f"User {winner_id}"
                    winner_text = f"🎉 Challenge completed! Winner: **{winner_name}**"
                
                embed.add_field(name="🏆 Challenge Complete", value=winner_text, inline=False)
                await interaction.channel.send(embed=embed)
            else:
                await interaction.message.edit(embed=embed)
    
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
        await interaction.response.defer()
        
        challenger_user = await get_user_by_discord(str(interaction.user.id))
        if not challenger_user:
            await interaction.followup.send("You need to authenticate with `/authenticate` before creating challenges.", ephemeral=True)
            return
        
        user_ids = set(int(uid) for uid in re.findall(r'\d+', members))
        
        challenged_members = [m for m in [interaction.guild.get_member(uid) for uid in user_ids] if m and not m.bot]
        
        if not challenged_members:
            await interaction.followup.send("No valid members were found to challenge.", ephemeral=True)
            return
        
        authenticated_members = [m for m in challenged_members if await get_user_by_discord(str(m.id))]
        
        if not authenticated_members:
            await interaction.followup.send("None of the mentioned users are authenticated. They must use `/authenticate` first.", ephemeral=True)
            return
        
        session = getattr(self.bot, "session", aiohttp.ClientSession())
        problem = await get_random_problem(session, type_of_problem=tags, rating=rating)
        
        if not problem:
            await interaction.followup.send("Couldn't find a problem matching these criteria.", ephemeral=True)
            return
        
        problem_id = f"{problem.get('contestId', 0)}{problem.get('index', '')}"
        challenge_id = await create_challenge(
            problem_id=problem_id,
            problem_name=problem['name'],
            problem_link=problem['link']
        )
        
        class ChallengeView(discord.ui.View):
            def __init__(self, bot, challenge_id, valid_users, problem, cog_instance):
                super().__init__(timeout=300)
                self.bot = bot
                self.challenge_id = challenge_id
                self.valid_users = {user.id for user in valid_users}
                self.accepted_users = set()
                self.rejected_users = set()
                self.problem = problem
                self.cog_instance = cog_instance

            async def interaction_check(self, interaction):
                if interaction.user.id not in self.valid_users:
                    await interaction.response.send_message("This challenge isn't for you.", ephemeral=True)
                    return False
                return True
            
            @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
            async def accept_button(self, interaction, button):
                self.accepted_users.add(interaction.user.id)
                if interaction.user.id in self.rejected_users:
                    self.rejected_users.remove(interaction.user.id)
                await self._update_message(interaction)
                await interaction.response.send_message(f"You accepted the challenge!", ephemeral=True)
            
            @discord.ui.button(label="Reject", style=discord.ButtonStyle.red)
            async def reject_button(self, interaction, button):
                self.rejected_users.add(interaction.user.id)
                if interaction.user.id in self.accepted_users:
                    self.accepted_users.remove(interaction.user.id)
                await self._update_message(interaction)
                await interaction.response.send_message("You rejected the challenge.", ephemeral=True)
            
            async def _update_message(self, interaction):
                message = interaction.message
                embed = message.embeds[0]
                
                accepted_list = [interaction.guild.get_member(uid).mention for uid in self.accepted_users if interaction.guild.get_member(uid)]
                rejected_list = [interaction.guild.get_member(uid).mention for uid in self.rejected_users if interaction.guild.get_member(uid)]
                pending_list = [interaction.guild.get_member(uid).mention for uid in self.valid_users if uid not in self.accepted_users and uid not in self.rejected_users and interaction.guild.get_member(uid)]

                embed.set_field_at(1, name="Status", value="Waiting for responses...", inline=False)
                if accepted_list:
                    embed.set_field_at(1, name="✅ Accepted", value=", ".join(accepted_list), inline=False)
                if rejected_list:
                    embed.add_field(name="❌ Rejected", value=", ".join(rejected_list), inline=False)
                if pending_list:
                    embed.add_field(name="⏳ Pending", value=", ".join(pending_list), inline=False)

                await message.edit(embed=embed, view=self)
                
                if not pending_list:
                    self.stop()
                    if self.accepted_users:
                        await self._start_solve_tracking(interaction.channel, [interaction.guild.get_member(uid) for uid in self.accepted_users])
                    else:
                        await interaction.channel.send("Challenge canceled - all participants rejected.")

            async def _start_solve_tracking(self, channel, accepted_members):
                handle_map = {str(m.id): await get_cf_handle(str(m.id)) for m in accepted_members}
                parsed = _parse_contest_and_index_from_link(self.problem["link"])
                if not parsed:
                    await channel.send("Error parsing problem link. Solve tracking unavailable.")
                    return

                solve_view = self.cog_instance._SolveView(
                    challenge_id=self.challenge_id,
                    participants=accepted_members,
                    handle_map=handle_map,
                    contest_id=parsed["contestId"],
                    index=parsed["index"],
                    started_ts=int(time.time()),
                    bot=self.bot,
                    cog=self.cog_instance,
                    problem_name=self.problem['name'],
                    problem_link=self.problem['link'],
                    problem_rating=self.problem.get('rating')
                )
                
                embed = discord.Embed(
                    title=f"Challenge Started: {self.problem['name']}",
                    url=self.problem['link'],
                    description=f"The challenge has begun! Challenge ID: `{self.challenge_id}`",
                    color=discord.Color.green()
                )
                embed.add_field(name="Participants", value=", ".join(m.mention for m in accepted_members), inline=False)
                embed.add_field(name="Rating", value=str(self.problem.get('rating', 'N/A')), inline=True)
                embed.add_field(name="Tags", value=", ".join(self.problem.get('tags', [])), inline=True)
                
                await channel.send(embed=embed, view=solve_view)
        
        embed = discord.Embed(
            title=f"Codeforces Challenge: {problem['name']}",
            url=problem['link'],
            description=f"**ID**: `{challenge_id}`\n**Rating**: {problem.get('rating', 'N/A')}\n**Tags**: {', '.join(problem.get('tags', []))}",
            color=discord.Color.blue()
        )
        embed.add_field(name="Challenged Users", value=", ".join(m.mention for m in authenticated_members), inline=False)
        embed.add_field(name="Status", value="Waiting for responses...", inline=False)
        embed.set_footer(text=f"Challenge ID: {challenge_id} | Initiated by {interaction.user.display_name}")
        
        view = ChallengeView(self.bot, challenge_id, authenticated_members, problem, self)
        
        challenge_channel = self.bot.get_channel(CHALLENGE_CHANNEL_ID) or interaction.channel
        await challenge_channel.send(f"New challenge from {interaction.user.mention} to {', '.join(m.mention for m in authenticated_members)}!", embed=embed, view=view)
        if challenge_channel != interaction.channel:
            await interaction.followup.send(f"Challenge created in <#{challenge_channel.id}>!", ephemeral=True)

    @app_commands.command(name="info", description="Get detailed information about a specific challenge.")
    @app_commands.describe(challenge_id="The ID of the challenge to look up")
    async def info(self, interaction: discord.Interaction, challenge_id: int):
        await interaction.response.defer()
        challenge_data = await get_challenge_details(challenge_id) 

        if not challenge_data:
            await interaction.followup.send(f"❌ Challenge with ID `{challenge_id}` not found.", ephemeral=True)
            return

        challenge = challenge_data["challenge"]
        participants = challenge_data["participants"]
        embed = discord.Embed(title=f"Challenge #{challenge['challenge_id']}: {challenge['problem_name']}", url=challenge['problem_link'], color=discord.Color.blue())
        
        created_at_dt = datetime.fromisoformat(challenge['created_at'])
        created_at_ts = int(created_at_dt.timestamp())
        embed.add_field(name="Problem Details", value=f"**ID**: `{challenge['challenge_id']}`\n**Created**: <t:{created_at_ts}:F>", inline=False)

        if not participants:
            embed.add_field(name="Participants", value="No participants found for this challenge.", inline=False)
        else:
            participant_lines = []
            for p in participants:
                user = interaction.guild.get_member(int(p['discord_id']))
                user_name = user.mention if user else p['cf_handle']
                winner_emoji = "🏆" if p['is_winner'] else ""
                rank = f"#{p['rank']}" if p['rank'] else "N/A"
                participant_lines.append(f"`{rank}` {user_name} - **{p['score_awarded']} pts** {winner_emoji}")
            embed.add_field(name="Leaderboard", value="\n".join(participant_lines), inline=False)
        
        embed.set_footer(text=f"Requested by {interaction.user.display_name}")
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="history", description="View recent challenge history")
    @app_commands.describe(user="View history for a specific user (optional)", limit="Number of challenges to show (default: 10)")
    async def challenge_history(self, interaction: discord.Interaction, user: discord.Member = None, limit: int = 10):
        await interaction.response.defer(ephemeral=False)
        limit = max(1, min(limit, 50))
        
        history_data = await (get_user_challenge_history(str(user.id), limit) if user else get_challenge_history(limit))
        title = f"🏆 Challenge History for {user.display_name}" if user else "🏆 Recent Challenge History"
        
        if not history_data:
            await interaction.followup.send("No challenge history found.", ephemeral=False)
            return
        
        embed = discord.Embed(title=title, color=discord.Color.blue())
        
        if user:
            # For a specific user, the old format is fine as there are no duplicates.
            entries = []
            for entry in history_data:
                ts = int(datetime.fromisoformat(entry['timestamp']).timestamp())
                time_str = f"<t:{ts}:R>"
                rank_str = f"#{entry['rank']}" if entry['rank'] else "Surrendered"
                points_str = f"{entry['points']} pts"
                challenge_id_str = f"(ID: `{entry['challenge_id']}`)"
                entries.append(f"{challenge_id_str} **[{entry['problem_name']}]({entry['problem_link']})** - {rank_str} ({points_str}) {time_str}")
            embed.description = "\n".join(entries)
        else:
            # For general history, group by challenge ID to prevent duplicates
            grouped_challenges = {}
            for entry in history_data:
                challenge_id = entry['challenge_id']
                if challenge_id not in grouped_challenges:
                    grouped_challenges[challenge_id] = {
                        'name': entry['problem_name'],
                        'link': entry['problem_link'],
                        'timestamp': entry['timestamp'],
                        'participants': []
                    }
                grouped_challenges[challenge_id]['participants'].append(entry)

            description_lines = []
            # Sort challenges by timestamp, newest first
            sorted_challenge_ids = sorted(grouped_challenges.keys(), key=lambda cid: grouped_challenges[cid]['timestamp'], reverse=True)

            for challenge_id in sorted_challenge_ids:
                challenge = grouped_challenges[challenge_id]
                ts = int(datetime.fromisoformat(challenge['timestamp']).timestamp())
                time_str = f"<t:{ts}:R>"
                
                header = f"**[{challenge['name']}]({challenge['link']})** - (ID: `{challenge_id}`) {time_str}"
                description_lines.append(header)
                
                # Sort participants by rank
                sorted_participants = sorted(challenge['participants'], key=lambda p: p['rank'] if p['rank'] is not None else float('inf'))

                for p_entry in sorted_participants:
                    member = interaction.guild.get_member(int(p_entry['discord_id']))
                    user_name = member.display_name if member else p_entry['cf_handle']
                    rank_str = f"#{p_entry['rank']}" if p_entry['rank'] else "Surrendered"
                    points_str = f"{p_entry['points']} pts"
                    description_lines.append(f"└ {rank_str} {user_name} - {points_str}")
                description_lines.append("") # Add a blank line for spacing
            
            embed.description = "\n".join(description_lines)

        embed.timestamp = discord.utils.utcnow()
        embed.set_footer(text=f"Requested by {interaction.user.display_name}")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="leaderboard", description="View the scoring leaderboard")
    @app_commands.describe(category="The scoring category to view", limit="Number of users to show (default: 10)")
    @app_commands.choices(category=[
        app_commands.Choice(name="Daily Points", value="daily"),
        app_commands.Choice(name="Weekly Points", value="weekly"),
        app_commands.Choice(name="Monthly Points", value="monthly"),
        app_commands.Choice(name="Overall Points", value="overall"),
        app_commands.Choice(name="Problems Solved", value="solved")
    ])
    async def leaderboard(self, interaction: discord.Interaction, category: app_commands.Choice[str] = None, limit: int = 10):
        await interaction.response.defer(ephemeral=False)
        limit = max(1, min(limit, 50))
        category_value = category.value if category else "overall"
        leaderboard_data = await get_custom_leaderboard(category_value, limit)
        
        if not leaderboard_data:
            await interaction.followup.send("No users found in this leaderboard category.", ephemeral=False)
            return
        
        category_display = {
            "daily": "Daily Points", "weekly": "Weekly Points", "monthly": "Monthly Points",
            "overall": "Overall Points", "solved": "Problems Solved"
        }.get(category_value, "Overall Points")
        
        embed = discord.Embed(title=f"🏆 Challenges Leaderboard ({category_display})", color=discord.Color.gold())
        entries = []
        for entry in leaderboard_data:
            user = interaction.guild.get_member(int(entry["discord_id"]))
            name = user.mention if user else f"{entry['codeforces_name']}"
            entries.append(f"#{entry['rank']}: {name} - **{entry['score']}**")
        
        embed.description = "\n".join(entries)
        embed.timestamp = discord.utils.utcnow()
        embed.set_footer(text=f"Requested by {interaction.user.display_name}")
        await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Challenges(bot))
