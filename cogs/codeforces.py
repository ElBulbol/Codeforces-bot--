import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import aiofiles
import random
import json
import os
import re
import time
import sqlite3  # Add this import
from datetime import datetime, timedelta
from typing import List, Dict, Optional  # Add this import

CF_LINKS_FILE = "cf_links.json"

# ---------------- Utility Functions ---------------- #

async def get_random_problem(session: aiohttp.ClientSession, type_of_problem="random", rating=None, max_retries=5):
    url = "https://codeforces.com/api/problemset.problems"
    try:
        async with session.get(url) as response:
            response.raise_for_status()
            data = await response.json()
    except aiohttp.ClientError as e:
        print(f"Error fetching from Codeforces API: {e}")
        return None

    if data["status"] != "OK":
        print("Codeforces API error")
        return None

    problems = data["result"]["problems"]

    for attempt in range(max_retries):
        if type_of_problem.lower() == "random":
            tag_counts = {}
            for p in problems:
                for tag in p.get("tags", []):
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
            viable_tags = [tag for tag, count in tag_counts.items() if count >= 10]
            if not viable_tags:
                viable_tags = list(tag_counts.keys())
            if not viable_tags:
                return None
            chosen_tag = random.choice(viable_tags)
            tagged = [p for p in problems if chosen_tag in [t.lower() for t in p.get("tags", [])]]
        else:
            required_tags = {t.strip().lower() for t in type_of_problem.split(',')}
            tagged = [p for p in problems if required_tags.issubset({t.lower() for t in p.get("tags", [])})]

        if not tagged:
            if type_of_problem.lower() != "random":
                return None
            continue

        rating_filtered = tagged.copy()

        if isinstance(rating, str) and rating.lower() == "random":
            all_ratings = sorted({p["rating"] for p in tagged if "rating" in p})
            if all_ratings:
                selected_rating = random.choice(all_ratings)
                rating_filtered = [p for p in tagged if p.get("rating") == selected_rating]
        elif rating is not None:
            try:
                rating_int = int(rating)
                rating_filtered = [p for p in tagged if p.get("rating") == rating_int]
            except (ValueError, TypeError):
                pass

        if rating_filtered:
            problem = random.choice(rating_filtered)
            link = f"https://codeforces.com/contest/{problem['contestId']}/problem/{problem['index']}"
            problem_data = {
                "name": problem["name"],
                "link": link,
                "tags": problem.get("tags", []),
                "rating": problem.get("rating", "N/A")
            }
            await save_current_request(problem_data)
            return problem_data

        if type_of_problem.lower() != "random":
            break

    return None


async def save_current_request(problem, filename="current-request.json"):
    path = os.path.abspath(filename)
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(problem, indent=4, ensure_ascii=False))


async def load_current_request(filename="current-request.json"):
    path = os.path.abspath(filename)
    if not os.path.exists(path):
        return None
    async with aiofiles.open(path, "r", encoding="utf-8") as f:
        content = await f.read()
        return json.loads(content)


async def load_links() -> Dict[str, str]:
    if not os.path.exists(CF_LINKS_FILE):
        return {}
    async with aiofiles.open(CF_LINKS_FILE, "r", encoding="utf-8") as f:
        return json.loads(await f.read())


async def save_links(data: Dict[str, str]):
    async with aiofiles.open(CF_LINKS_FILE, "w", encoding="utf-8") as f:
        await f.write(json.dumps(data, indent=4))


def _parse_contest_and_index_from_link(link: str) -> Optional[Dict[str, str]]:
    # Expected: https://codeforces.com/contest/{contestId}/problem/{index}
    m = re.search(r"/contest/(\d+)/problem/([A-Za-z0-9]+)", link)
    if not m:
        return None
    return {"contestId": int(m.group(1)), "index": m.group(2)}


async def _cf_check_solved(session: aiohttp.ClientSession, handle: str, contest_id: int, index: str, since_ts: int) -> bool:
    url = f"https://codeforces.com/api/user.status?handle={handle}"
    async with session.get(url) as resp:
        data = await resp.json()
    if data.get("status") != "OK":
        return False

    for sub in data["result"]:
        if sub.get("verdict") != "OK":
            continue
        prob = sub.get("problem", {})
        if prob.get("contestId") == contest_id and prob.get("index") == index:
            # Only count solves after challenge start time
            if sub.get("creationTimeSeconds", 0) >= since_ts:
                return True
    return False


# ---------------- Cog ---------------- #

class Codeforces(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Add a dictionary to track active challenges
        self.active_challenges = {}  # challenge_id -> challenge data

    # Pick Problem Command
    @app_commands.command(name="pick_problem", description="Pick a Codeforces problem by tags and optional rating.")
    @app_commands.describe(
        tags="Problem tags, comma-separated (e.g., 'dp,graphs'). Leave empty or use 'random' for a random tag.",
        rating="The problem rating (e.g., 800). Leave empty or use 'random' for a random rating."
    )
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.user.id))
    async def pick_problem(self, interaction: discord.Interaction, tags: str = None, rating: str = None):
        await interaction.response.defer()
        type_of_problem = tags if tags else "random"
        session = getattr(self.bot, "session", None)
        if session is None:
            async with aiohttp.ClientSession() as tmp_session:
                problem = await get_random_problem(tmp_session, type_of_problem=type_of_problem, rating=rating)
        else:
            problem = await get_random_problem(session, type_of_problem=type_of_problem, rating=rating)

        if not problem:
            await interaction.followup.send("No problem found with the given criteria.")
            return

        embed = discord.Embed(
            title=problem["name"],
            url=problem["link"],
            description=f"Tags: {', '.join(problem['tags'])}\nRating: {problem['rating']}",
            color=discord.Color.blue()
        )
        await interaction.followup.send(embed=embed)

    # Link CF Account
    @app_commands.command(name="link_cf", description="Link your Codeforces account.")
    @app_commands.describe(handle="Your Codeforces handle or profile URL")
    async def link_cf(self, interaction: discord.Interaction, handle: str):
        """Link a Codeforces handle to your Discord account"""
        await interaction.response.defer(ephemeral=True)
        
        # Extract handle if a full URL is provided
        if handle.startswith("https://codeforces.com/profile/"):
            handle = handle.replace("https://codeforces.com/profile/", "")
        
        # Validate the handle exists on Codeforces
        session = getattr(self.bot, "session", None)
        valid = False
        
        try:
            if session is None:
                async with aiohttp.ClientSession() as tmp_session:
                    async with tmp_session.get(f"https://codeforces.com/api/user.info?handles={handle}") as resp:
                        data = await resp.json()
                        valid = data.get("status") == "OK"
            else:
                async with session.get(f"https://codeforces.com/api/user.info?handles={handle}") as resp:
                    data = await resp.json()
                    valid = data.get("status") == "OK"
        except Exception as e:
            await interaction.followup.send(f"Error validating handle: {str(e)}", ephemeral=True)
            return
        
        if not valid:
            await interaction.followup.send(f"Could not find Codeforces handle: `{handle}`", ephemeral=True)
            return
        
        # Load existing links
        links = await load_links()
        
        # Check if handle is already linked to another user
        for user_id, linked_handle in links.items():
            if linked_handle.lower() == handle.lower() and user_id != str(interaction.user.id):
                await interaction.followup.send(
                    f"Error: The Codeforces handle `{handle}` is already linked to another Discord user. "
                    f"Each Codeforces handle can only be linked to one Discord account.",
                    ephemeral=True
                )
                return
        
        # Update the link
        links[str(interaction.user.id)] = handle
        await save_links(links)
        
        # Update the user in leaderboard database if it exists
        leaderboard_cog = self.bot.get_cog("Leaderboard")
        if leaderboard_cog:
            try:
                async with leaderboard_cog.db_lock:
                    conn = sqlite3.connect("leaderboard.db")
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT OR REPLACE INTO users (discord_id, cf_handle) VALUES (?, ?)",
                        (str(interaction.user.id), handle)
                    )
                    conn.commit()
                    conn.close()
            except Exception as e:
                print(f"Error updating leaderboard database: {e}")
        
        # Assign the Auth role to the user
        try:
            # Try to get the role by name first
            auth_role = discord.utils.get(interaction.guild.roles, name="Auth")
            
            # If not found by name, try to get by ID
            if not auth_role:
                auth_role = interaction.guild.get_role(1405358190400508005)
            
            if auth_role:
                await interaction.user.add_roles(auth_role, reason="Linked Codeforces account")
                await interaction.followup.send(
                    f"Successfully linked your Discord account to Codeforces handle: `{handle}`\n"
                    f"You have been given the {auth_role.mention} role!",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"Successfully linked your Discord account to Codeforces handle: `{handle}`\n"
                    f"Note: Could not assign Auth role (not found).",
                    ephemeral=True
                )
        except discord.Forbidden:
            await interaction.followup.send(
                f"Successfully linked your Discord account to Codeforces handle: `{handle}`\n"
                f"Note: Could not assign Auth role (insufficient permissions).",
                ephemeral=True
            )
        except Exception as e:
            print(f"Error assigning Auth role: {e}")
            await interaction.followup.send(
                f"Successfully linked your Discord account to Codeforces handle: `{handle}`\n"
                f"Note: Could not assign Auth role due to an error.",
                ephemeral=True
            )

    # Display CF Info
    @app_commands.command(name="cf_info", description="Display your linked Codeforces account info.")
    async def cf_info(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        links = await load_links()
        handle = links.get(str(member.id))

        if not handle:
            await interaction.response.send_message(f"No Codeforces account linked for {member.display_name}.", ephemeral=True)
            return

        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://codeforces.com/api/user.info?handles={handle}") as resp:
                data = await resp.json()

        if data["status"] != "OK":
            await interaction.response.send_message("Error fetching Codeforces info.", ephemeral=True)
            return

        user = data["result"][0]
        embed = discord.Embed(
            title=user["handle"],
            url=f"https://codeforces.com/profile/{user['handle']}",
            description=f"Rating: {user.get('rating', 'N/A')}\nMax Rating: {user.get('maxRating', 'N/A')}\nRank: {user.get('rank', 'N/A')}",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    # Show Last 10 Solved
    @app_commands.command(name="last_10_solved", description="Show last 10 problems solved by a user (MOD only).")
    @app_commands.checks.has_role("MOD")
    async def last_10_solved(self, interaction: discord.Interaction, member: discord.Member):
        links = await load_links()
        handle = links.get(str(member.id))

        if not handle:
            await interaction.response.send_message(f"No Codeforces account linked for {member.display_name}.", ephemeral=True)
            return

        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://codeforces.com/api/user.status?handle={handle}") as resp:
                data = await resp.json()

        if data["status"] != "OK":
            await interaction.response.send_message("Error fetching submissions.", ephemeral=True)
            return

        solved = []
        seen = set()
        for sub in data["result"]:
            if sub.get("verdict") == "OK":
                problem = sub["problem"]
                key = (problem.get("contestId"), problem.get("index"))
                if key in seen:
                    continue
                seen.add(key)
                name = problem["name"]
                contest_id = problem.get("contestId")
                index = problem.get("index")
                link = f"https://codeforces.com/contest/{contest_id}/problem/{index}"
                solved.append(f"{name} - {link}")
            if len(solved) >= 10:
                break

        if not solved:
            await interaction.response.send_message("No solved problems found.", ephemeral=True)
            return

        await interaction.response.send_message("\n".join(solved))

    # ---------------- Challenge Command and Views ---------------- #

    class _AcceptRejectView(discord.ui.View):
        def __init__(self, allowed_ids: List[int], on_all_accept):
            super().__init__(timeout=120)
            self.allowed = set(allowed_ids)
            self.accepted = set()
            self.rejected = set()
            self.on_all_accept = on_all_accept

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id not in self.allowed:
                await interaction.response.send_message("You are not part of this challenge.", ephemeral=True)
                return False
            return True

        @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
        async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.accepted.add(interaction.user.id)
            await interaction.response.send_message("Accepted.", ephemeral=True)
            if self.accepted == self.allowed:
                # Everyone accepted before timeout -> start immediately
                self.on_all_accept()
                self.stop()

        @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger)
        async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.rejected.add(interaction.user.id)
            await interaction.response.send_message("Rejected.", ephemeral=True)

    class _SolveView(discord.ui.View):
        def __init__(self, challenge_id: str, participants: List[discord.Member], handle_map: Dict[int, str],
                    contest_id: int, index: str, started_ts: int, bot: commands.Bot, cog):
            super().__init__(timeout=None)
            self.challenge_id = challenge_id
            self.participants = {m.id for m in participants}
            self.handles = handle_map
            self.contest_id = contest_id
            self.index = index
            self.started_ts = started_ts
            self.bot = bot
            self.cog = cog
            self.finished = set()
            self.surrendered = set()
            self.finish_times = {}  # User ID -> finish time

        async def _check_user_solved(self, user_id: int) -> bool:
            handle = self.handles.get(user_id)
            if not handle:
                return False
            session = getattr(self.bot, "session", None)
            if session is None:
                async with aiohttp.ClientSession() as s:
                    return await _cf_check_solved(s, handle, self.contest_id, self.index, self.started_ts)
            else:
                return await _cf_check_solved(session, handle, self.contest_id, self.index, self.started_ts)

        def _can_interact(self, interaction: discord.Interaction) -> bool:
            return interaction.user.id in self.participants

        @discord.ui.button(label="Done", style=discord.ButtonStyle.success)
        async def done(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not self._can_interact(interaction):
                await interaction.response.send_message("You are not part of this challenge.", ephemeral=True)
                return

            user_id = interaction.user.id
            if user_id in self.finished or user_id in self.surrendered:
                await interaction.response.send_message("You've already finished or surrendered.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)
            solved = await self._check_user_solved(user_id)
            if solved:
                current_time = int(time.time())
                self.finished.add(user_id)
                self.finish_times[user_id] = current_time
                
                # Calculate rank
                rank = len(self.finished)
                
                # Update challenge data with finish time
                if self.challenge_id in self.cog.active_challenges:
                    self.cog.active_challenges[self.challenge_id]["finish_time"] = current_time
                
                # Get the leaderboard cog to update points
                leaderboard_cog = self.bot.get_cog("Leaderboard")
                if leaderboard_cog:
                    try:
                        # Get challenge data and add challenge_id to it
                        challenge_data = self.cog.active_challenges.get(self.challenge_id, {}).copy()
                        challenge_data["challenge_id"] = self.challenge_id
                        
                        # Award points
                        points = leaderboard_cog.add_points(user_id, rank, challenge_data)
                        await interaction.followup.send(
                            f"Congratulations! You solved the problem and earned {points} points.", 
                            ephemeral=True
                        )
                    except Exception as e:
                        print(f"Error adding points: {e}")
                        await interaction.followup.send(
                            f"Congratulations! You solved the problem!", 
                            ephemeral=True
                        )
                else:
                    await interaction.followup.send(
                        f"Congratulations! You solved the problem!", 
                        ephemeral=True
                    )
                
                await interaction.channel.send(f"{interaction.user.mention} solved the problem! Rank: #{rank}")
                
                # Check if challenge is complete (everyone finished or surrendered)
                if self.finished.union(self.surrendered) == self.participants:
                    # Remove from active challenges
                    if self.challenge_id in self.cog.active_challenges:
                        del self.cog.active_challenges[self.challenge_id]
                        
                    # Send a summary message
                    embed = discord.Embed(
                        title="Challenge Complete",
                        description="All participants have finished or surrendered.",
                        color=discord.Color.green()
                    )
                    
                    # Add rankings to the summary
                    ranked_users = sorted(
                        [(uid, self.finish_times.get(uid, float('inf'))) for uid in self.finished],
                        key=lambda x: x[1]
                    )
                    
                    for i, (uid, finish_time) in enumerate(ranked_users, 1):
                        member = interaction.guild.get_member(uid)
                        name = member.display_name if member else f"User {uid}"
                        time_taken = finish_time - self.started_ts
                        embed.add_field(
                            name=f"#{i}: {name}",
                            value=f"Time: {time_taken//60}m {time_taken%60}s",
                            inline=False
                        )
                    
                    # Add surrendered users
                    if self.surrendered:
                        surrender_names = []
                        for uid in self.surrendered:
                            member = interaction.guild.get_member(uid)
                            name = member.display_name if member else f"User {uid}"
                            surrender_names.append(name)
                        
                        embed.add_field(
                            name="Surrendered",
                            value=", ".join(surrender_names),
                            inline=False
                        )
                    
                    await interaction.channel.send(embed=embed)
            else:
                await interaction.followup.send("You haven't solved the problem yet.", ephemeral=True)

        @discord.ui.button(label="Surrender", style=discord.ButtonStyle.danger)
        async def surrender(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not self._can_interact(interaction):
                await interaction.response.send_message("You are not part of this challenge.", ephemeral=True)
                return

            user_id = interaction.user.id
            if user_id in self.finished or user_id in self.surrendered:
                await interaction.response.send_message("You've already finished or surrendered.", ephemeral=True)
                return

            self.surrendered.add(user_id)
            await interaction.response.send_message("You have surrendered.", ephemeral=True)
            await interaction.channel.send(f"{interaction.user.mention} has surrendered!")
            
            # Check if challenge is complete
            if self.finished.union(self.surrendered) == self.participants:
                # Remove from active challenges
                if self.challenge_id in self.cog.active_challenges:
                    del self.cog.active_challenges[self.challenge_id]
                    
                # Send a summary message with rankings
                embed = discord.Embed(
                    title="Challenge Complete",
                    description="All participants have finished or surrendered.",
                    color=discord.Color.green()
                )
                
                # Add rankings to the summary
                ranked_users = sorted(
                    [(uid, self.finish_times.get(uid, float('inf'))) for uid in self.finished],
                    key=lambda x: x[1]
                )
                
                for i, (uid, finish_time) in enumerate(ranked_users, 1):
                    member = interaction.guild.get_member(uid)
                    name = member.display_name if member else f"User {uid}"
                    time_taken = finish_time - self.started_ts
                    embed.add_field(
                        name=f"#{i}: {name}",
                        value=f"Time: {time_taken//60}m {time_taken%60}s",
                        inline=False
                    )
                
                # Add surrendered users
                if self.surrendered:
                    surrender_names = []
                    for uid in self.surrendered:
                        member = interaction.guild.get_member(uid)
                        name = member.display_name if member else f"User {uid}"
                        surrender_names.append(name)
                    
                    embed.add_field(
                        name="Surrendered",
                        value=", ".join(surrender_names),
                        inline=False
                    )
                
                await interaction.channel.send(embed=embed)

    @app_commands.command(
        name="challenge", 
        description="Challenge Auth users to solve a CF problem. Members must be mentioned and have Auth role."
    )
    @app_commands.describe(
        members="Comma-separated list of mentions or IDs to challenge",
        tags="Problem tags (e.g., 'dp,graphs') or 'random'",
        rating="Problem rating (e.g., '800') or 'random'"
    )
    async def challenge(self, interaction: discord.Interaction, members: str, tags: str = "random", rating: str = "random"):
        """Challenge users to solve a Codeforces problem"""
        await interaction.response.defer()
        
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
    
        # Check for Auth role
        auth_role = discord.utils.get(interaction.guild.roles, name="Auth")
        if not auth_role:
            # Try by ID if name doesn't work
            auth_role = interaction.guild.get_role(1405358190400508005)
            if not auth_role:
                await interaction.followup.send("The 'Auth' role doesn't exist on this server.", ephemeral=True)
                return
    
        # Filter out members without Auth role
        valid_members = [m for m in challenged_members if auth_role in m.roles]
        invalid_members = [m for m in challenged_members if m not in valid_members]
    
        if not valid_members:
            await interaction.followup.send(
                "None of the mentioned users have the required 'Auth' role.", 
                ephemeral=True
            )
            return
    
        if invalid_members:
            # Notify about ignored members
            invalid_mentions = ", ".join(m.mention for m in invalid_members)
            await interaction.followup.send(
                f"The following users don't have the 'Auth' role and will be ignored: {invalid_mentions}",
                ephemeral=True
            )
    
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
    
        # Create challenge ID
        challenge_id = f"{int(time.time())}"
    
        # Prepare the challenge view
        class ChallengeView(discord.ui.View):
            def __init__(self, bot, challenge_id, valid_users):
                super().__init__(timeout=300)  # 5 minute timeout
                self.bot = bot
                self.challenge_id = challenge_id
                self.valid_users = {user.id for user in valid_users}
                self.accepted_users = set()
                self.rejected_users = set()
        
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
                    f"You accepted the challenge to solve {problem['name']}!", 
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
                    title=f"Codeforces Challenge: {problem['name']}",
                    url=problem['link'],
                    description=f"Rating: {problem['rating']}\nTags: {', '.join(problem['tags'])}",
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
                links = await load_links()
                handle_map = {
                    str(member.id): links.get(str(member.id), "") 
                    for member in accepted_members
                }
            
                # Extract contest ID and problem index from the link
                parsed = _parse_contest_and_index_from_link(problem["link"])
                if not parsed:
                    await channel.send("Error parsing problem link. Solve tracking unavailable.")
                    return
            
                contest_id = parsed["contestId"]
                index = parsed["index"]
            
                # Send the message with the solve tracking view
                solve_view = Codeforces._SolveView(
                    challenge_id=self.challenge_id,
                    participants=accepted_members,
                    handle_map=handle_map,
                    contest_id=contest_id,
                    index=index,
                    started_ts=int(time.time()),
                    bot=self.bot,
                    cog=self.bot.get_cog("Codeforces")
                )
            
                embed = discord.Embed(
                    title=f"Challenge Started: {problem['name']}",
                    url=problem['link'],
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
                    value=str(problem['rating']),
                    inline=True
                )
            
                embed.add_field(
                    name="Tags",
                    value=", ".join(problem['tags']),
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
        view = ChallengeView(self.bot, challenge_id, valid_members)
    
        # Get the specified channel
        challenge_channel = self.bot.get_channel(1404857696666128405)
    
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

    # Optional: Command to list active challenges
    @app_commands.command(name="active_challenges", description="List all active challenges")
    async def active_challenges(self, interaction: discord.Interaction):
        if not self.active_challenges:
            await interaction.response.send_message("There are no active challenges.", ephemeral=True)
            return
            
        embed = discord.Embed(
            title="Active Challenges",
            description=f"There are {len(self.active_challenges)} active challenges",
            color=discord.Color.blue()
        )
        
        for challenge_id, data in self.active_challenges.items():
            problem = data["problem"]
            participant_count = len(data["participants"])
            creator = interaction.guild.get_member(data["creator"])
            creator_name = creator.display_name if creator else "Unknown"
            
            embed.add_field(
                name=f"Challenge by {creator_name}",
                value=f"Problem: [{problem['name']}]({problem['link']})\n"
                      f"Participants: {participant_count}\n"
                      f"Rating: {problem.get('rating', 'Unknown')}\n"
                      f"Started: <t:{data['started_ts']}:R>",
                inline=False
            )
            
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="de_link_cf", description="Remove your linked Codeforces account.")
    @app_commands.describe(user="The user to unlink (MOD only)")
    async def de_link_cf(self, interaction: discord.Interaction, user: discord.Member = None):
        """Remove your linked Codeforces account from all databases, or unlink another user (MOD only)"""
        await interaction.response.defer(ephemeral=True)
        
        # Check if trying to unlink another user
        if user is not None and user.id != interaction.user.id:
            # Check if the command user has the MOD role
            mod_role = discord.utils.get(interaction.guild.roles, name="MOD")
            if not mod_role or mod_role not in interaction.user.roles:
                await interaction.followup.send(
                    "You need the MOD role to unlink other users' accounts.", 
                    ephemeral=True
                )
                return
            
            # Using the specified user
            target_user = user
            is_mod_action = True
        else:
            # Using the command author
            target_user = interaction.user
            is_mod_action = False
        
        target_id = str(target_user.id)
        
        # Check if the target user has a linked account
        links = await load_links()
        if target_id not in links:
            await interaction.followup.send(
                f"{'This user does not' if is_mod_action else 'You don\'t'} have a linked Codeforces account.", 
                ephemeral=True
            )
            return
        
        # Store the handle for confirmation message
        handle = links[target_id]
        
        # Remove from cf_links.json
        del links[target_id]
        await save_links(links)
        
        # Remove from leaderboard database if it exists
        leaderboard_cog = self.bot.get_cog("Leaderboard")
        if leaderboard_cog:
            try:
                async with leaderboard_cog.db_lock:
                    conn = sqlite3.connect("leaderboard.db")
                    cursor = conn.cursor()
                    
                    # Update the user's cf_handle to NULL in the users table
                    cursor.execute(
                        "UPDATE users SET cf_handle = NULL WHERE discord_id = ?",
                        (target_id,)
                    )
                    
                    conn.commit()
                    conn.close()
            except Exception as e:
                print(f"Error updating leaderboard database: {e}")
    
        # Remove from temp_contests database if it exists
        try:
            conn = sqlite3.connect("temp_contests.db")
            cursor = conn.cursor()
            
            # We don't delete the user from the contests, but we can update references
            # to the cf_handle if there's a column for it
            # This part depends on your database schema
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error updating temp_contests database: {e}")
    
        # Remove the Auth role
        try:
            # Try to get the role by name first
            auth_role = discord.utils.get(interaction.guild.roles, name="Auth")
            
            # If not found by name, try to get by ID
            if not auth_role:
                auth_role = interaction.guild.get_role(1405358190400508005)
            
            if auth_role and auth_role in target_user.roles:
                await target_user.remove_roles(auth_role, reason="Unlinked Codeforces account")
                
                if is_mod_action:
                    # Mod action message
                    await interaction.followup.send(
                        f"Successfully unlinked {target_user.mention}'s Discord account from Codeforces handle: `{handle}`\n"
                        f"The {auth_role.mention} role has been removed.",
                        ephemeral=True
                    )
                    
                    # Notify the target user
                    try:
                        await target_user.send(
                            f"Your Codeforces handle `{handle}` has been unlinked from your Discord account by a moderator."
                        )
                    except:
                        # Can't DM the user, that's fine
                        pass
                else:
                    # Self-unlink message
                    await interaction.followup.send(
                        f"Successfully unlinked your Discord account from Codeforces handle: `{handle}`\n"
                        f"The {auth_role.mention} role has been removed.",
                        ephemeral=True
                    )
            else:
                if is_mod_action:
                    await interaction.followup.send(
                        f"Successfully unlinked {target_user.mention}'s Discord account from Codeforces handle: `{handle}`",
                        ephemeral=True
                    )
                    
                    # Notify the target user
                    try:
                        await target_user.send(
                            f"Your Codeforces handle `{handle}` has been unlinked from your Discord account by a moderator."
                        )
                    except:
                        # Can't DM the user, that's fine
                        pass
                else:
                    await interaction.followup.send(
                        f"Successfully unlinked your Discord account from Codeforces handle: `{handle}`",
                        ephemeral=True
                    )
        except discord.Forbidden:
            if is_mod_action:
                await interaction.followup.send(
                    f"Successfully unlinked {target_user.mention}'s Discord account from Codeforces handle: `{handle}`\n"
                    f"Note: Could not remove Auth role (insufficient permissions).",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"Successfully unlinked your Discord account from Codeforces handle: `{handle}`\n"
                    f"Note: Could not remove Auth role (insufficient permissions).",
                    ephemeral=True
                )
        except Exception as e:
            print(f"Error removing Auth role: {e}")
            if is_mod_action:
                await interaction.followup.send(
                    f"Successfully unlinked {target_user.mention}'s Discord account from Codeforces handle: `{handle}`\n"
                    f"Note: Could not remove Auth role due to an error.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"Successfully unlinked your Discord account from Codeforces handle: `{handle}`\n"
                    f"Note: Could not remove Auth role due to an error.",
                    ephemeral=True
                )

# Add this at the end of your file, outside the class
async def setup(bot):
    await bot.add_cog(Codeforces(bot))
