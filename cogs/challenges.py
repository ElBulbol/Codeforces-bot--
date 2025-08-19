from discord.ext import commands
from discord import app_commands
import discord
import aiohttp
import re
import time
from utility.random_problems import get_random_problem
from utility.db_helpers import get_cf_handle, increment_user_solved_count, get_user_by_discord
from utility.recording_score import update_user_scores, update_user_score_in_challenge_participants
import sqlite3


MOD_ROLE_ID = 1404742889681981440

class Challenges(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- NESTED _SolveView CLASS ---
    # This class handles the view once the challenge has started
    class _SolveView(discord.ui.View):
        def __init__(self, challenge_id, participants, handle_map, contest_id, index, problem_rating, started_ts, bot, cog):
            super().__init__(timeout=None)
            self.challenge_id = challenge_id
            self.participants = {p.id for p in participants}
            self.handle_map = handle_map
            self.contest_id = contest_id
            self.index = index
            self.problem_rating = problem_rating  # Store the rating
            self.started_ts = started_ts
            self.bot = bot
            self.cog = cog
            self.finished = set()
            self.surrendered = set()

        async def check_if_solved(self, handle):
            if not handle:
                return False
            url = f"https://codeforces.com/api/user.status?handle={handle}&from=1&count=50"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return False
                    data = await resp.json()
                    if data.get("status") == "OK":
                        for sub in data["result"]:
                            if (sub["problem"].get("contestId") == self.contest_id and
                                    sub["problem"].get("index") == self.index and
                                    sub.get("verdict") == "OK"):
                                return True
            return False

        @discord.ui.button(label="Check If Solved", style=discord.ButtonStyle.green)
        async def check_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id in self.finished:
                await interaction.response.send_message("You have already solved this problem.", ephemeral=True)
                return
            if interaction.user.id in self.surrendered:
                await interaction.response.send_message("You have already surrendered and cannot check for a solution.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)
            handle = self.handle_map.get(str(interaction.user.id))
            
            # If handle is missing, we can't check.
            if not handle:
                await interaction.followup.send("❌ Your Codeforces handle is not linked. I cannot check your solution.", ephemeral=True)
                return

            solved = await self.check_if_solved(handle)

            if solved:
                self.finished.add(interaction.user.id)
                await interaction.followup.send("✅ Congratulations! Your solution is correct. Recording your score...", ephemeral=True)

                # --- Corrected Winner and Scoring Logic ---
                conn = None
                try:
                    user_info = await get_user_by_discord(str(interaction.user.id))
                    if not user_info:
                        print(f"Error: Could not find internal user_id for Discord ID {interaction.user.id}")
                        return
                    
                    internal_user_id = user_info['user_id']

                    # 1. Check if a winner already exists
                    conn = sqlite3.connect('db/db.db')
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT 1 FROM challenge_participants WHERE challenge_id = ? AND is_winner = 1",
                        (self.challenge_id,)
                    )
                    winner_exists = cursor.fetchone()

                    # 2. Set winner status (1 if first, 0 otherwise)
                    is_winner_flag = 1 if not winner_exists else 0
                    
                    cursor.execute(
                        "UPDATE challenge_participants SET is_winner = ? WHERE challenge_id = ? AND user_id = ?",
                        (is_winner_flag, self.challenge_id, internal_user_id)
                    )
                    conn.commit()

                    # 3. Calculate points and update scores using imported functions
                    try:
                        rating = int(self.problem_rating)
                    except (ValueError, TypeError):
                        rating = 0 # Default to 0 if rating is invalid
                    
                    # Update score for this specific challenge
                    update_user_score_in_challenge_participants(self.challenge_id, internal_user_id, rating)

                    # Update the user's global scores
                    points_awarded = rating / 100
                    update_user_scores(internal_user_id, points_awarded)
                    
                    print(f"User {internal_user_id} solved challenge {self.challenge_id}. Winner: {bool(is_winner_flag)}. Points: {points_awarded}")

                except Exception as e:
                    print(f"An error occurred during scoring for challenge {self.challenge_id}: {e}")
                    import traceback
                    traceback.print_exc()
                finally:
                    if conn:
                        conn.close()
                # --- End of Logic ---

            else:
                await interaction.followup.send("❌ You haven't solved this problem yet. Keep trying!", ephemeral=True)

            # Check if everyone has finished or surrendered to end the challenge
            if self.finished.union(self.surrendered) == self.participants:
                await self._update_status(interaction)

        @discord.ui.button(label="Surrender", style=discord.ButtonStyle.danger)
        async def surrender(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id in self.finished or interaction.user.id in self.surrendered:
                await interaction.response.send_message("You have already completed or surrendered this challenge.", ephemeral=True)
                return
            
            self.surrendered.add(interaction.user.id)
            await interaction.response.send_message("You have surrendered.", ephemeral=True)

            if self.finished.union(self.surrendered) == self.participants:
                await self._update_status(interaction)

        async def _update_status(self, interaction):
            import sqlite3

            embed = discord.Embed(
                title=f"🏁 Challenge result",
                description=f"**Challenge ID:** `{self.challenge_id}`\n\n",
                color=discord.Color.purple()
            )

            conn = sqlite3.connect('db/db.db')
            cursor = conn.cursor()
            cursor.execute(
                "SELECT user_id, is_winner, score_awarded FROM challenge_participants WHERE challenge_id = ?",
                (self.challenge_id,)
            )
            rows = cursor.fetchall()

            winners = []
            losers = []
            for user_id, is_winner, score_awarded in rows:
                # Fetch discord_id for mention
                cursor.execute("SELECT discord_id FROM users WHERE user_id = ?", (user_id,))
                result = cursor.fetchone()
                if result:
                    discord_id = result[0]
                    mention = f"<@{discord_id}>"
                else:
                    mention = f"User {user_id}"
                handle = self.handle_map.get(str(user_id))
                points_text = f"**{score_awarded or 0} pts**"
                if handle and handle != "None":
                    entry = f"{mention} • `{handle}` • {points_text}"
                else:
                    entry = f"{mention} • {points_text}"
                if is_winner == 1:
                    winners.append(entry)
                else:
                    losers.append(entry)
            conn.close()

            # Add winners field
            if winners:
                embed.add_field(
                    name="🏆 Winner(s)",
                    value="\n".join(winners),
                    inline=False
                )
            else:
                embed.add_field(
                    name="🏆 Winner(s)",
                    value="No winners this time.",
                    inline=False
                )

            # Add losers field
            if losers:
                embed.add_field(
                    name="❌ Loser(s)",
                    value="\n".join(losers),
                    inline=False
                )
            else:
                embed.add_field(
                    name="❌ Loser(s)",
                    value="No losers! Everyone solved the challenge!",
                    inline=False
                )

            # Add summary and completion
            embed.add_field(
                name="📊 Challenge Summary",
                value=f"Total Participants: **{len(winners) + len(losers)}**\n"
                      f"Winners: **{len(winners)}**\n"
                      f"Losers: **{len(losers)}**",
                inline=False
            )

            embed.add_field(
                name="✅ Challenge Complete",
                value="All participants have completed or surrendered the challenge.",
                inline=False
            )

            # Store your Discord IDs as variables
            OWNER1_ID = 585540481937833984
            OWNER2_ID = 543172445155098624

            # Get member display names
            owner1_member = interaction.guild.get_member(OWNER1_ID)
            owner2_member = interaction.guild.get_member(OWNER2_ID)
            owner1_name = owner1_member.display_name if owner1_member else str(OWNER1_ID)
            owner2_name = owner2_member.display_name if owner2_member else str(OWNER2_ID)

            embed.set_footer(
                text=f"If you are facing any bug dm us {owner1_name}, {owner2_name}"
            )

            await interaction.channel.send(embed=embed)

    async def _pick_problem(self, tags, rating, min_solved):
        async with aiohttp.ClientSession() as session:
            return await get_random_problem(session, type_of_problem=tags, rating=rating, min_solved=min_solved)

    async def _get_problem_from_link(self, link):
        m = re.search(r"/contest/(\d+)/problem/([A-Za-z0-9]+)", link)
        if not m: return None
        contest_id, index = int(m.group(1)), m.group(2)
        async with aiohttp.ClientSession() as session:
            url = "https://codeforces.com/api/problemset.problems"
            async with session.get(url) as resp:
                data = await resp.json()
            if data.get("status") == "OK":
                for p in data["result"]["problems"]:
                    if p.get("contestId") == contest_id and p.get("index") == index:
                        stats = next((s for s in data["result"]["problemStatistics"] if s["contestId"] == contest_id and s["index"] == index), {})
                        return {"name": p.get("name"), "link": link, "rating": p.get("rating"), "tags": p.get("tags", []), "solvedCount": stats.get("solvedCount", "N/A")}
        return None

    async def _challenge_logic(self, interaction, members, problem):
        user_ids = set(re.findall(r'\d+', members))
        user_ids.add(str(interaction.user.id))

        challenged_members = [interaction.guild.get_member(int(uid)) for uid in user_ids if interaction.guild.get_member(int(uid)) and not interaction.guild.get_member(int(uid)).bot]
        if not challenged_members:
            await interaction.followup.send("No valid members found.", ephemeral=True)
            return

        auth_role = discord.utils.get(interaction.guild.roles, name="Auth") or interaction.guild.get_role(1405358190400508005)
        if not auth_role:
            await interaction.followup.send("Auth role not found.", ephemeral=True)
            return

        valid_members = [m for m in challenged_members if auth_role in m.roles]
        invalid_members = [m for m in challenged_members if m not in valid_members]

        if not valid_members:
            await interaction.followup.send("None of the challenged users have the 'Auth' role.", ephemeral=True)
            return
        if invalid_members:
            await interaction.followup.send(f"Ignoring users without 'Auth' role: {', '.join(m.mention for m in invalid_members)}", ephemeral=True)

        challenge_id = str(int(time.time()))

        class ChallengeView(discord.ui.View):
            def __init__(self, bot, valid_users):
                super().__init__(timeout=300)
                self.bot = bot
                self.valid_users = {user.id for user in valid_users}
                self.accepted_users = set()
                self.rejected_users = set()

            async def interaction_check(self, interaction: discord.Interaction) -> bool:
                if interaction.user.id not in self.valid_users:
                    await interaction.response.send_message("This challenge isn't for you.", ephemeral=True)
                    return False
                return True

            async def _update_and_check_complete(self, interaction: discord.Interaction):
                # Defer the interaction to prevent "interaction failed"
                await interaction.response.defer()

                message = interaction.message
                embed = message.embeds[0]
                
                accepted_list = [f"<@{uid}>" for uid in self.accepted_users]
                rejected_list = [f"<@{uid}>" for uid in self.rejected_users]
                
                # Clear existing status fields
                embed.clear_fields()
                embed.add_field(name="Challenged Users", value=", ".join(f"<@{uid}>" for uid in self.valid_users), inline=False)
                if accepted_list:
                    embed.add_field(name="✅ Accepted", value=", ".join(accepted_list), inline=False)
                if rejected_list:
                    embed.add_field(name="❌ Rejected", value=", ".join(rejected_list), inline=False)

                all_responded = (len(self.accepted_users) + len(self.rejected_users)) == len(self.valid_users)

                if all_responded:
                    self.stop()
                    await message.edit(embed=embed, view=None)
                    if self.accepted_users:
                        self.bot.loop.create_task(self._start_solve_tracking(message.channel, [interaction.guild.get_member(uid) for uid in self.accepted_users]))
                    else:
                        await message.channel.send("Challenge canceled - all participants rejected.")
                else:
                    await message.edit(embed=embed, view=self)

            @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
            async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                self.accepted_users.add(interaction.user.id)
                self.rejected_users.discard(interaction.user.id)
                await self._update_and_check_complete(interaction)

            @discord.ui.button(label="Reject", style=discord.ButtonStyle.red)
            async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                self.rejected_users.add(interaction.user.id)
                self.accepted_users.discard(interaction.user.id)
                await self._update_and_check_complete(interaction)

            async def _start_solve_tracking(self, channel, accepted_members):
                try:
                    from utility.db_helpers import store_challenge, add_participant
                    
                    # Store the challenge and participants in the database
                    store_challenge(challenge_id, problem["link"])
                    for member in accepted_members:
                        user_info = await get_user_by_discord(str(member.id))
                        if user_info:
                            add_participant(challenge_id, user_info['user_id'])
                        else:
                            print(f"Warning: Could not find user_info for Discord ID {member.id}")

                    # Get Codeforces handles for all participants
                    handle_map = {}
                    for m in accepted_members:
                        handle = await get_cf_handle(str(m.id))
                        handle_map[str(m.id)] = handle
                        if not handle:
                            await channel.send(f"⚠️ **Warning:** {m.mention} does not have a linked Codeforces handle. Their solves cannot be tracked automatically.")

                    # Parse problem details from the link
                    m = re.search(r"/contest/(\d+)/problem/([A-Za-z0-9]+)", problem["link"])
                    if not m:
                        await channel.send("❌ **Error:** Could not parse problem details from the link. Solve tracking is unavailable.")
                        return
                    
                    contest_id, index = int(m.group(1)), m.group(2)

                    # Create and send the new view for solving the challenge
                    solve_view = Challenges._SolveView(
                        challenge_id=challenge_id, 
                        participants=accepted_members, 
                        handle_map=handle_map, 
                        contest_id=contest_id, 
                        index=index, 
                        problem_rating=problem['rating'], # Pass the rating here
                        started_ts=int(time.time()), 
                        bot=self.bot, 
                        cog=self.bot.get_cog("Challenges")
                    )
                    
                    embed = discord.Embed(
                        title=f"Challenge Started: {problem['name']}", 
                        url=problem['link'], 
                        description="The challenge has begun! Use the buttons below to check your solution or to surrender.", 
                        color=discord.Color.green()
                    )
                    embed.add_field(name="Participants", value=", ".join(m.mention for m in accepted_members), inline=False)
                    
                    await channel.send(embed=embed, view=solve_view)

                except Exception as e:
                    # Catch any error, print it for debugging, and notify the channel
                    print(f"---! ERROR IN _start_solve_tracking !---")
                    print(f"Error: {e}")
                    import traceback
                    traceback.print_exc()
                    print(f"-----------------------------------------")
                    await channel.send(f"❌ **Critical Error:** An unexpected error occurred while starting the challenge. Please check the bot's console logs. Challenge ID: `{challenge_id}`")

        embed = discord.Embed(title="Codeforces Challenge", description=f"[{problem['name']}]({problem['link']})\nRating: {problem['rating']}\nTags: {', '.join(problem['tags']) if problem['tags'] else 'None'}", color=discord.Color.blue())
        embed.add_field(name="Challenged Users", value=", ".join(m.mention for m in valid_members), inline=False)
        embed.set_footer(text=f"Challenge ID: {challenge_id} | Initiated by {interaction.user.display_name}")

        view = ChallengeView(self.bot, valid_members)
        challenge_channel = self.bot.get_channel(1404857696666128405)
        await (challenge_channel or interaction.channel).send(embed=embed, view=view)
        await interaction.followup.send(f"Challenge created in <#{challenge_channel.id if challenge_channel else interaction.channel.id}>!", ephemeral=True)

    @app_commands.command(name="challenge_admin", description="(MOD only) Challenge users to solve a CF problem.")
    @app_commands.describe(members="Users to challenge", tags="Problem tags", rating="Problem rating", min_solved="Min solved count", link="Specific problem link")
    async def challenge_admin(self, interaction: discord.Interaction, members: str, tags: str = "random", rating: str = "random", min_solved: str = None, link: str = None):
        if not any(role.id == MOD_ROLE_ID for role in interaction.user.roles):
            await interaction.response.send_message("You do not have permission.", ephemeral=True)
            return
        await interaction.response.defer()
        problem = await self._get_problem_from_link(link) if link else await self._pick_problem(tags, rating, min_solved)
        if not problem:
            await interaction.followup.send("Could not find a suitable problem.", ephemeral=True)
            return
        await self._challenge_logic(interaction, members, problem)

    @app_commands.command(name="challenge", description="Challenge users to solve a random CF problem.")
    @app_commands.describe(members="Users to challenge", tags="Problem tags", rating="Problem rating", min_solved="Min solved count")
    async def challenge(self, interaction: discord.Interaction, members: str, tags: str = "random", rating: str = "random", min_solved: str = None):
        await interaction.response.defer()
        problem = await self._pick_problem(tags, rating, min_solved)
        if not problem:
            await interaction.followup.send("Could not find a suitable problem.", ephemeral=True)
            return
        await self._challenge_logic(interaction, members, problem)

# Setup function
async def setup(bot):
    await bot.add_cog(Challenges(bot))