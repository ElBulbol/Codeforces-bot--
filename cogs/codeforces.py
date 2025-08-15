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
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional

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
                "rating": problem.get("rating", "N/A"),
                "contestId": problem["contestId"],
                "index": problem["index"]
            }
            return problem_data

        if type_of_problem.lower() != "random":
            break

    return None

async def save_current_request(problem, filename="current-request.json"):
    async with aiofiles.open(filename, "w", encoding="utf-8") as f:
        await f.write(json.dumps(problem, indent=4))

async def load_current_request(filename="current-request.json"):
    if not os.path.exists(filename):
        return None
    async with aiofiles.open(filename, "r", encoding="utf-8") as f:
        return json.loads(await f.read())

async def load_links() -> Dict[str, str]:
    if not os.path.exists(CF_LINKS_FILE):
        return {}
    
    try:
        with open(CF_LINKS_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

async def save_links(data: Dict[str, str]):
    with open(CF_LINKS_FILE, 'w') as f:
        json.dump(data, f, indent=4)

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

class Codeforces(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("Codeforces cog initialized successfully!")
    
    @commands.Cog.listener()
    async def on_ready(self):
        print("Codeforces cog is ready!")
    
    # The _SolveView class for tracking challenges
    class _SolveView(discord.ui.View):
        def __init__(self, challenge_id, participants, handle_map, contest_id, index, started_ts, bot, cog):
            super().__init__(timeout=None)  # No timeout for challenge tracking
            self.challenge_id = challenge_id
            self.participants = set(user.id for user in participants)
            self.handle_map = handle_map
            self.contest_id = contest_id
            self.index = index
            self.started_ts = started_ts
            self.bot = bot
            self.cog = cog
            self.finished = set()
            self.surrendered = set()
        
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
                self.finished.add(interaction.user.id)
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
            
            await interaction.followup.send("You have surrendered this challenge.", ephemeral=True)
            
            # Update the message to reflect the current status
            await self._update_status(interaction)
        
        async def _update_status(self, interaction):
            # Create an updated embed
            embed = discord.Embed(
                title="Challenge Status Update",
                description=f"Challenge ID: {self.challenge_id}",
                color=discord.Color.blue()
            )
            
            # Format the completed users
            if self.finished:
                finished_names = []
                for user_id in self.finished:
                    member = interaction.guild.get_member(user_id)
                    name = member.display_name if member else f"User {user_id}"
                    handle = self.handle_map.get(str(user_id), "Unknown")
                    finished_names.append(f"{name} ({handle})")
                
                embed.add_field(
                    name="Completed",
                    value=", ".join(finished_names),
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
                    name="Surrendered",
                    value=", ".join(surrender_names),
                    inline=False
                )
                
            # If everyone has finished or surrendered, show completion message
            if self.finished.union(self.surrendered) == self.participants:
                if self.surrendered:
                    embed.add_field(
                        name="Challenge Complete",
                        value="All participants have completed or surrendered the challenge.",
                        inline=False
                    )
                else:
                    embed.add_field(
                        name="Challenge Complete",
                        value="🎉 All participants have successfully solved the problem!",
                        inline=False
                    )
                
                await interaction.channel.send(embed=embed)

    # Link Codeforces account command
    @app_commands.command(name="link_cf", description="Link your Codeforces account.")
    @app_commands.describe(handle="Your Codeforces handle or profile URL")
    async def link_cf(self, interaction: discord.Interaction, handle: str):
        """Link a Codeforces handle to your Discord account"""
        await interaction.response.defer(ephemeral=True)
        
        # Extract handle if a full URL is provided
        if handle.startswith("https://codeforces.com/profile/"):
            handle = handle.replace("https://codeforces.com/profile/", "")
        
        # Validate the handle exists on Codeforces
        valid = False
        try:
            async with self.bot.session.get(f"https://codeforces.com/api/user.info?handles={handle}") as resp:
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
    
    # Unlink Codeforces account command
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
    
    # Challenge command
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
        print("Challenge command called!")
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

# Setup function at the end of the file
async def setup(bot):
    print("Setting up Codeforces cog...")
    await bot.add_cog(Codeforces(bot))
    print("Codeforces cog setup complete!")
