from discord.ext import commands
from discord import app_commands
from typing import Dict, Optional
import discord
import aiohttp
import re
import asyncio
import time
from utility.random_problems import get_random_problem
from utility.db_helpers import (
    get_cf_handle,
    get_user_info,
    update_problems_solved,
    get_user_score,
    get_custom_leaderboard,
    get_all_cf_handles
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

class Challenges(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
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
    
    # Challenge command - keep your existing implementation
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
                parsed = _parse_contest_and_index_from_link(problem["link"])
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

    # Add this command to your Codeforces class

    @commands.command()
    @commands.is_owner()
    async def update_all_cf_counts(self, ctx):
        """Update problem solved counts for ALL users (owner only)"""
        await ctx.send("Starting update of all users' problem counts...")
        
        # Get session for API calls
        session = getattr(self.bot, "session", None)
        if not session:
            session = aiohttp.ClientSession()
            should_close = True
        else:
            should_close = False
        
        try:
            # Get all users
            all_handles = await get_all_cf_handles()
            
            total = len(all_handles)
            updated = 0
            failed = 0
            
            # Update status message
            status_msg = await ctx.send(f"Updating 0/{total} users...")
            
            # Update each user
            for i, (discord_id, cf_handle) in enumerate(all_handles.items()):
                print(f"Updating user {i+1}/{total}: {cf_handle}")
                success, count = await update_problems_solved(discord_id, session)
                
                if success:
                    updated += 1
                    print(f"Successfully updated {cf_handle}: {count} problems (ALL TIME)")
                    
                    # Also update the scoring system
                    #await update_solved_problems(discord_id, count)
                else:
                    failed += 1
                    print(f"Failed to update {cf_handle}")
                
                # Update status every 5 users or at the end
                if (i + 1) % 5 == 0 or i == total - 1:
                    await status_msg.edit(content=f"Updating {i+1}/{total} users... ({updated} successful, {failed} failed)")
                
                # Avoid rate limiting
                await asyncio.sleep(1)
            
            # Add final summary message
            await ctx.send(f"✅ Update complete! Updated {updated}/{total} users with ALL-TIME solved problem counts and scoring system data.")
    
        except Exception as e:
            await ctx.send(f"❌ Error during update: {str(e)}")
            import traceback
            traceback.print_exc()
        
        finally:
            if should_close:
                await session.close()

    @app_commands.command(name="update_cf_count", description="Update your Codeforces solved problems count")
    async def update_cf_count(self, interaction: discord.Interaction):
        """Manually update your Codeforces solved problems count"""
        await interaction.response.defer(ephemeral=True)
        
        # Get the session for API calls
        session = getattr(self.bot, "session", None)
        if not session:
            session = aiohttp.ClientSession()
            should_close = True
        else:
            should_close = False
        
        try:
            # Check if user has linked CF account
            cf_handle = await get_cf_handle(str(interaction.user.id))
            if not cf_handle:
                await interaction.followup.send(
                    "You haven't linked a Codeforces account yet. Use `/authenticate` to link your account.",
                    ephemeral=True
                )
                return
            
            # Update problems count
            success, count = await update_problems_solved(str(interaction.user.id), session)
            
            if success:
                # Also update the scoring system
                #await update_solved_problems(str(interaction.user.id), count)
                
                await interaction.followup.send(
                    f"Successfully updated your solved problems count. You have solved {count} unique problems on Codeforces!\n"
                    f"Your score in the scoring system has been updated.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Failed to update your solved problems count. Please try again later.",
                    ephemeral=True
                )
    
        finally:
            if should_close:
                await session.close()

    @app_commands.command(name="score", description="View your or another user's scoring information")
    @app_commands.describe(user="The user to check scores for (optional)")
    async def score(self, interaction: discord.Interaction, user: discord.Member = None):
        """View scoring information for yourself or another user"""
        await interaction.response.defer(ephemeral=False)
        
        # Determine which user to check
        target_user = user if user else interaction.user
        
        # Get the score information
        score_data = await get_user_score(str(target_user.id))
        
        if not score_data["exists"]:
            await interaction.followup.send(
                f"{target_user.mention} is not in the scoring system. They need to link their Codeforces account with `/authenticate`.",
                ephemeral=False
            )
            return
        
        # Create the embed
        embed = discord.Embed(
            title=f"🏆 Scoring Information for {target_user.display_name}",
            description=f"Codeforces Handle: **{score_data['codeforces_name']}**",
            color=discord.Color.gold()
        )
        
        # Set the user's avatar
        embed.set_thumbnail(url=target_user.display_avatar.url)
        
        # Add score fields
        embed.add_field(name="📅 Daily Points", value=str(score_data["daily_points"]), inline=True)
        embed.add_field(name="📆 Weekly Points", value=str(score_data["weekly_points"]), inline=True)
        embed.add_field(name="📊 Monthly Points", value=str(score_data["monthly_points"]), inline=True)
        embed.add_field(name="💯 Overall Points", value=str(score_data["overall_points"]), inline=True)
        embed.add_field(name="🧩 Problems Solved", value=str(score_data["solved_problems"]), inline=True)
        
        # Add last updated time
        if score_data["last_updated"] > 0:
            last_updated = f"<t:{score_data['last_updated']}:R>"
            embed.add_field(name="🔄 Last Updated", value=last_updated, inline=True)
        
        # Add link to Codeforces profile
        embed.add_field(
            name="Codeforces Profile", 
            value=f"[View Profile](https://codeforces.com/profile/{score_data['codeforces_name']})",
            inline=False
        )
        
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
            title=f"🏆 {category_display} Leaderboard",
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
