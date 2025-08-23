import discord
import json
import aiohttp
import re
from typing import Optional
from discord.ext import commands
from discord import app_commands
from discord.ext import tasks
from datetime import datetime, timedelta

from .contest_builder import ContestBuilderView, contest_builder, create_contest_setup_embed
# MODIFIED: Corrected imports to use getter functions
from utility.config_manager import get_cp_role_id, get_contest_channel_id, get_mentor_role_id
from utility.db_helpers import (
    get_bot_contest, 
    get_pending_and_active_contests, update_contest_status,
    get_contest_problems, get_contest_leaderboard, get_all_bot_contests,
    get_contest_custom_leaderboard,
    get_contest_solves_info, update_contest_solves_info,
    get_user_by_discord, join_contest, get_contest_participant,
    update_contest_participant_score, get_contest_participant_count,
    increment_user_problems_solved
)

# --- Interaction Handler Class ---

class ContestInteractionHandler:
    """Handles contest-related interactions like join and check solved buttons"""
    
    def __init__(self, bot):
        self.bot = bot
    
    async def handle_join_contest(self, interaction: discord.Interaction, custom_id: str):
        """Handle join contest button clicks"""
        try:
            contest_id = int(custom_id.split('_')[1])
        except (IndexError, ValueError):
            await interaction.response.send_message("Invalid contest ID.", ephemeral=True)
            return

        user_data = await get_user_by_discord(str(interaction.user.id))
        if not user_data:
            await interaction.response.send_message(
                "You need to link your Codeforces account first using `/authenticate` command.",
                ephemeral=True
            )
            return

        contest_data = await get_bot_contest(contest_id)
        if not contest_data:
            await interaction.response.send_message("Contest not found.", ephemeral=True)
            return

        if contest_data['status'] == 'ENDED':
            await interaction.response.send_message("This contest has already ended.", ephemeral=True)
            return

        was_already_joined = False
        try:
            await join_contest(contest_id, str(interaction.user.id), user_data['cf_handle'])
            await interaction.response.send_message(
                f"✅ Successfully joined contest: **{contest_data['name']}**!", 
                ephemeral=True
            )
        except Exception as e:
            if "UNIQUE constraint failed" in str(e) or "already exists" in str(e).lower():
                was_already_joined = True
                await interaction.response.send_message(
                    "You're already registered for this contest!", 
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"Error joining contest: {str(e)}", 
                    ephemeral=True
                )
                return

        if not was_already_joined:
            try:
                participant_count = await get_contest_participant_count(contest_id)
                await self._update_announcement_with_participant_count(interaction, contest_data, contest_id, participant_count)
            except Exception as e:
                print(f"Error updating announcement with participant count: {e}")

    async def handle_check_solved(self, interaction: discord.Interaction, custom_id: str):
        """Handle check solved button clicks with robust API checking and dynamic scoring"""
        try:
            parts = custom_id.split('_')
            contest_id = int(parts[1])
            problem_index = int(parts[2])
        except (IndexError, ValueError):
            await interaction.response.send_message("Invalid button data.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        contest_data = await get_bot_contest(contest_id)
        if not contest_data or contest_data['status'] != 'ACTIVE':
            await interaction.followup.send(
                f"This contest is no longer active (Status: {contest_data.get('status', 'N/A')}).", 
                ephemeral=True
            )
            return

        participant = await get_contest_participant(contest_id, str(interaction.user.id))
        if not participant:
            await interaction.followup.send(
                "You're not registered for this contest! Use the 'Join Contest' button first.", 
                ephemeral=True
            )
            return

        problems = await get_contest_problems(contest_id)
        if problem_index >= len(problems):
            await interaction.followup.send("Invalid problem index.", ephemeral=True)
            return

        problem_link = problems[problem_index]
        
        match = re.search(r'/(?:contest|problemset/problem|gym)/(\d+)/problem/([A-Z0-9]+)', problem_link)
        if not match:
            await interaction.followup.send("Invalid problem link format. Could not parse contest ID.", ephemeral=True)
            return
        cf_contest_id, problem_letter = match.groups()

        try:
            api_url = f"https://codeforces.com/api/contest.status?contestId={cf_contest_id}&handle={participant['codeforces_handle']}"
            
            async with self.bot.session.get(api_url) as resp:
                if resp.status != 200:
                    await interaction.followup.send("Error checking Codeforces API. Please try again later.", ephemeral=True)
                    return
                
                data = await resp.json()
                if data.get('status') != 'OK':
                    await interaction.followup.send(f"Codeforces API error: {data.get('comment', 'Unknown error')}", ephemeral=True)
                    return

                solved = False
                accepted_submission = None
                for submission in data.get('result', []):
                    if (submission['problem']['index'] == problem_letter and 
                        submission['verdict'] == 'OK'):
                        solved = True
                        accepted_submission = submission
                        break

                if solved:
                    solved_problems = json.loads(participant.get('solved_problems', '[]'))
                    if problem_index not in solved_problems:
                        solved_problems.append(problem_index)
                        
                        rating = accepted_submission['problem'].get('rating', 0)
                        points = rating // 100
                        
                        if points == 0:
                            points = 10 # Fallback for unrated problems

                        solves_info = await get_contest_solves_info(contest_id)
                        problem_key = str(problem_index)
                        is_first_solve = problem_key not in solves_info
                        
                        if is_first_solve:
                            points += 3 # Add 3 bonus points
                            solves_info[problem_key] = str(interaction.user.id)
                            await update_contest_solves_info(contest_id, solves_info)
                        
                        feedback_message = f"🎉 Congratulations! You solved problem {problem_index + 1}"
                        if rating > 0:
                            feedback_message += f" (Rating: {rating})"
                        feedback_message += f" and earned {points} points"
                        if is_first_solve:
                            feedback_message += " (including a 3 point First Accepted bonus)!"
                        else:
                            feedback_message += "!"

                        await update_contest_participant_score(
                            contest_id, str(interaction.user.id), points, solved_problems
                        )
                        await increment_user_problems_solved(str(interaction.user.id))
                        await interaction.followup.send(feedback_message, ephemeral=True)

                        if is_first_solve:
                            contest_channel_id = await get_contest_channel_id(interaction.guild.id)
                            announce_channel = self.bot.get_channel(contest_channel_id) if contest_channel_id else None
                            if announce_channel:
                                await announce_channel.send(f"🎈 First accepted on [Problem {problem_index + 1}]({problem_link}) by {interaction.user.mention}!")

                    else:
                        await interaction.followup.send(
                            f"You've already been awarded points for problem {problem_index + 1}.", 
                            ephemeral=True
                        )
                else:
                    await interaction.followup.send(
                        f"I couldn't find an 'Accepted' submission for this problem. Keep trying! 💪", 
                        ephemeral=True
                    )
        except Exception as e:
            await interaction.followup.send(f"An error occurred while checking your solution: {str(e)}", ephemeral=True)

    async def _update_announcement_with_participant_count(self, interaction: discord.Interaction, contest_data: dict, contest_id: int, participant_count: int):
        """Update the original announcement message with participant count"""
        contest_channel_id = await get_contest_channel_id(interaction.guild.id)
        contest_channel = self.bot.get_channel(contest_channel_id) if contest_channel_id else None
        if not contest_channel:
            return
        try:
            async for message in contest_channel.history(limit=50):
                if (message.author == self.bot.user and 
                    message.embeds and 
                    message.embeds[0].footer and 
                    f"Contest ID: {contest_id}" in message.embeds[0].footer.text):
                    
                    if contest_data.get('unix_timestamp'):
                        starts_at_text = f"<t:{contest_data['unix_timestamp']}:F> (<t:{contest_data['unix_timestamp']}:R>)"
                    else:
                        starts_at_text = datetime.fromisoformat(contest_data['start_time']).strftime('%d/%m/%Y %H:%M')
                    
                    problems_list = await get_contest_problems(contest_id)
                    problems_count = len(problems_list) if problems_list else 0
                    
                    embed = discord.Embed(
                        title=f"📢 New Contest: {contest_data['name']}",
                        description=(
                            f"A new contest has been scheduled!\n\n"
                            f"**Starts at:** {starts_at_text}\n"
                            f"**Duration:** {contest_data['duration']} minutes\n"
                            f"**Problems:** {problems_count}\n"
                            f"**Participants:** {participant_count}"
                        ),
                        color=discord.Color.blue()
                    )
                    embed.set_footer(text=f"Contest ID: {contest_id}")
                    
                    view = discord.ui.View(timeout=None)
                    view.add_item(discord.ui.Button(label="Join Contest", style=discord.ButtonStyle.success, custom_id=f"join_{contest_id}"))
                    
                    await message.edit(embed=embed, view=view)
                    break
        except Exception as e:
            print(f"Error updating announcement message: {e}")

# --- Main Slash Command Cog ---

class ContestCommands(commands.GroupCog, name = "contest"):
    def __init__(self, bot):
        self.bot = bot
        self.active_contests = {}
        self.contest_loop.start()

    def cog_unload(self):
        self.contest_loop.cancel()

    @tasks.loop(minutes=1)
    async def contest_loop(self):
        contests = await get_pending_and_active_contests()
        for contest_data in contests:
            try:
                guild_id = contest_data.get('guild_id')
                if not guild_id:
                    print(f"Skipping contest {contest_data['contest_id']} because it has no guild_id.")
                    continue
                
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    print(f"Skipping contest {contest_data['contest_id']} because guild {guild_id} was not found.")
                    continue

                start_time = datetime.fromisoformat(contest_data['start_time'])
                end_time = start_time + timedelta(minutes=contest_data['duration'])
                now = datetime.now()

                if contest_data['status'] == 'PENDING' and start_time <= now < end_time:
                    problems = await get_contest_problems(contest_data['contest_id'])
                    if not problems:
                        continue
                    await self.start_contest(guild, contest_data['contest_id'], contest_data['name'], problems, contest_data['duration'])

                elif contest_data['status'] == 'ACTIVE' and now >= end_time:
                    await self.end_contest(guild, contest_data['contest_id'], contest_data['name'])
            except Exception as e:
                print(f"Error processing contest {contest_data['contest_id']}: {e}")
                continue
    
    async def start_contest(self, guild: discord.Guild, contest_id: int, contest_name: str, problems: list, duration: int):
        await update_contest_status(contest_id, 'ACTIVE')
        
        contest_channel_id = await get_contest_channel_id(guild.id)
        channel = self.bot.get_channel(contest_channel_id) if contest_channel_id else None
        if not channel: return

        embed = discord.Embed(title=f"Contest Started: {contest_name}", description="Solve the problems and check your solutions below.", color=discord.Color.green())
        
        end_time = datetime.now() + timedelta(minutes=duration)
        end_timestamp = int(end_time.timestamp())
        embed.add_field(name="⏳ Ends", value=f"<t:{end_timestamp}:R> (Total: {duration} mins)", inline=False)
        
        view = discord.ui.View(timeout=None)
        for i, problem_link in enumerate(problems):
            embed.add_field(name=f"Problem {i+1}", value=f"[Link]({problem_link})", inline=False)
            view.add_item(discord.ui.Button(label=f"Check Solved - P{i+1}", style=discord.ButtonStyle.secondary, custom_id=f"check_{contest_id}_{i}"))

        participant_role_id = await get_cp_role_id(guild.id)
        participant_role = guild.get_role(participant_role_id) if participant_role_id else None
        
        await channel.send(content=f"{participant_role.mention if participant_role else 'Participants'}", embed=embed, view=view)
        print(f"Started contest {contest_id}")

    async def end_contest(self, guild: discord.Guild, contest_id: int, contest_name: str):
        await update_contest_status(contest_id, 'ENDED')
        
        contest_channel_id = await get_contest_channel_id(guild.id)
        channel = self.bot.get_channel(contest_channel_id) if contest_channel_id else None
        
        if channel:
            await channel.send(f"Contest '{contest_name}' (ID: {contest_id}) has ended! 🏁")
            results = await get_contest_leaderboard(contest_id)
            if results:
                embed = discord.Embed(title=f"🏆 Final Results: {contest_name}", description=f"Contest ID: {contest_id}", color=discord.Color.gold())
                
                winner = results[0]
                winner_user = self.bot.get_user(int(winner['discord_id']))
                winner_mention = winner_user.mention if winner_user else f"ID: {winner['discord_id']}"
                embed.add_field(name="🏆 Champion", value=f"Congratulations to {winner_mention} for winning with **{winner['score']} points**!", inline=False)

                results_text = "\n".join([
                    f"{'🥇' if r == 1 else '🥈' if r == 2 else '🥉' if r == 3 else f'**{r}.**'} {self.bot.get_user(int(res['discord_id'])).mention if self.bot.get_user(int(res['discord_id'])) else f'ID: {res["discord_id"]}'} ({res['codeforces_handle']}) - **{res['score']} points**"
                    for r, res in enumerate(results, 1)
                ])
                
                embed.add_field(name="Full Leaderboard", value=results_text, inline=False)
                await channel.send(embed=embed)
            else:
                await channel.send("No participants found for this contest.")

        if contest_id in self.active_contests:
            del self.active_contests[contest_id]
        print(f"Ended contest {contest_id}")

    @app_commands.command(name="create", description="Opens an interactive contest builder.")
    async def create_contest(self, interaction: discord.Interaction):
        mentor_role_id = await get_mentor_role_id(interaction.guild.id)
        if not mentor_role_id or not discord.utils.get(interaction.user.roles, id=mentor_role_id):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return

        interaction_id = f"{interaction.user.id}_{interaction.id}"
        contest_data = contest_builder.create_contest(interaction_id)
        embed = create_contest_setup_embed(contest_data)
        view = ContestBuilderView(interaction_id)
        view._update_remove_select(contest_data)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="start", description="Immediately starts a contest.")
    @app_commands.describe(contest_id="The ID of the contest to start.")
    async def start_contest_now(self, interaction: discord.Interaction, contest_id: int):
        mentor_role_id = await get_mentor_role_id(interaction.guild.id)
        if not mentor_role_id or not discord.utils.get(interaction.user.roles, id=mentor_role_id):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        contest_data = await get_bot_contest(contest_id)
        if not contest_data or contest_data['status'] != 'PENDING':
            await interaction.followup.send(f"Contest {contest_id} cannot be started.", ephemeral=True)
            return
        
        problems = await get_contest_problems(contest_id)
        if not problems:
            await interaction.followup.send(f"Contest {contest_id} has no problems.", ephemeral=True)
            return

        await self.start_contest(interaction.guild, contest_id, contest_data['name'], problems, contest_data['duration'])
        await interaction.followup.send(f"Contest '{contest_data['name']}' has been started manually.", ephemeral=True)

    @app_commands.command(name="end", description="Immediately ends a contest.")
    @app_commands.describe(contest_id="The ID of the contest to end.")
    async def end_contest_now(self, interaction: discord.Interaction, contest_id: int):
        mentor_role_id = await get_mentor_role_id(interaction.guild.id)
        if not mentor_role_id or not discord.utils.get(interaction.user.roles, id=mentor_role_id):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        contest_data = await get_bot_contest(contest_id)
        if not contest_data or contest_data['status'] != 'ACTIVE':
            await interaction.followup.send(f"Contest {contest_id} is not currently active.", ephemeral=True)
            return

        await self.end_contest(interaction.guild, contest_id, contest_data['name'])
        await interaction.followup.send(f"Contest '{contest_data['name']}' has been ended manually.", ephemeral=True)

    @app_commands.command(name="info", description="Shows information and problems for a specific contest.")
    @app_commands.describe(contest_id="The ID of the contest to show.")
    async def show_contest_info(self, interaction: discord.Interaction, contest_id: int):
        await interaction.response.defer()
        contest_data = await get_bot_contest(contest_id)
        if not contest_data:
            await interaction.followup.send(f"No contest found with ID: {contest_id}", ephemeral=True)
            return

        start_time_display = f"<t:{contest_data['unix_timestamp']}:F> (<t:{contest_data['unix_timestamp']}:R>)" if contest_data.get('unix_timestamp') else "Not set"
        problems_list = await get_contest_problems(contest_id)
        problems_display = "\n".join([f"{i+1}. [Problem Link]({link})" for i, link in enumerate(problems_list)]) or "No problems have been added yet."

        participants = await get_contest_leaderboard(contest_id)
        leaderboard_display = "No participants yet."
        winner_display = ""
        if participants:
            leaderboard_display = "\n".join([
                f"{'🥇' if r == 1 else '🥈' if r == 2 else '🥉' if r == 3 else f'**{r}.**'} {self.bot.get_user(int(p['discord_id'])).mention if self.bot.get_user(int(p['discord_id'])) else f'ID: {p["discord_id"]}'} ({p['codeforces_handle']}) - **{p['score']} pts**"
                for r, p in enumerate(participants, 1)
            ])
            
            winner = participants[0]
            winner_user = self.bot.get_user(int(winner['discord_id']))
            winner_mention = winner_user.mention if winner_user else f"ID: {winner['discord_id']}"
            winner_display = f"🎉 **Winner**: {winner_mention} with **{winner['score']}** points!"

        embed = discord.Embed(title=f"Contest Info: {contest_data['name']}", description=winner_display or None, color=discord.Color.blue())
        embed.add_field(name="Contest ID", value=str(contest_id), inline=True)
        embed.add_field(name="Status", value=contest_data['status'], inline=True)
        embed.add_field(name="Duration", value=f"{contest_data['duration']} minutes", inline=True)
        embed.add_field(name="Start Time", value=start_time_display, inline=False)
        embed.add_field(name="Problems", value=problems_display, inline=False)
        embed.add_field(name="🏆 Leaderboard", value=leaderboard_display, inline=False)
        
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="leaderboard", description="View the contest scoring leaderboard.")
    @app_commands.describe(category="The scoring category to view (defaults to Overall)", limit="Number of users to show (default: 10)")
    @app_commands.choices(category=[
        app_commands.Choice(name="Daily Points", value="daily"),
        app_commands.Choice(name="Weekly Points", value="weekly"),
        app_commands.Choice(name="Monthly Points", value="monthly"),
        app_commands.Choice(name="Overall Points", value="overall"),
    ])
    async def contest_leaderboard(self, interaction: discord.Interaction, category: app_commands.Choice[str] = None, limit: int = 10):
        await interaction.response.defer()
        limit = max(1, min(limit, 25))
        category_value = category.value if category else "overall"

        leaderboard_data = await get_contest_custom_leaderboard(category_value, limit)
        if not leaderboard_data:
            await interaction.followup.send("No contest participants found in this leaderboard category.", ephemeral=True)
            return

        category_names = {"daily": "Daily Points", "weekly": "Weekly Points", "monthly": "Monthly Points", "overall": "Overall Points"}
        category_display = category_names.get(category_value, "Overall Points")

        embed = discord.Embed(title=f"🏆 Contest Leaderboard ({category_display})", color=discord.Color.gold())
        
        entries = [
            f"**#{entry['rank']}:** {self.bot.get_user(int(entry['discord_id'])).mention if self.bot.get_user(int(entry['discord_id'])) else entry['codeforces_name']} - **{entry['score']}** points"
            for entry in leaderboard_data
        ]
        embed.description = "\n".join(entries) if entries else "No entries found for this category."

        embed.timestamp = discord.utils.utcnow()
        embed.set_footer(text=f"Requested by {interaction.user.display_name}")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="history", description="Shows all past contests with their IDs and dates.")
    async def list_contests(self, interaction: discord.Interaction):
        await interaction.response.defer()
        contests = await get_all_bot_contests()
        if not contests:
            await interaction.followup.send("No contests found.", ephemeral=True)
            return

        embed = discord.Embed(title="📋 All Contests", description="List of all contests (newest first)", color=discord.Color.purple())
        contest_list = [
            f'{"🟡" if c["status"] == "PENDING" else "🟢" if c["status"] == "ACTIVE" else "🔴"} **#{c["contest_id"]}** - {c["name"]}\n└ {f"<t:{c["unix_timestamp"]}:D>" if c.get("unix_timestamp") else "Date unknown"} • Status: {c["status"]}'
            for c in contests
        ]

        full_text = "\n\n".join(contest_list)
        if len(full_text) <= 4096:
            embed.description = full_text
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            # Simple pagination if text is too long
            current_page_text = ""
            for line in contest_list:
                if len(current_page_text) + len(line) + 2 > 4096:
                    embed.description = current_page_text
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    embed = discord.Embed(color=discord.Color.purple())
                    current_page_text = line
                else:
                    current_page_text += f"\n\n{line}" if current_page_text else line
            if current_page_text:
                embed.description = current_page_text
                await interaction.followup.send(embed=embed)

    @app_commands.command(name="notify", description="Sends a notification about a contest.")
    @app_commands.describe(message="The message to send to CP members.")
    @app_commands.checks.cooldown(1, 5, key = lambda i: (i.user.id))
    async def contest_notify(self, interaction: discord.Interaction, message: str):
        mentor_role_id = await get_mentor_role_id(interaction.guild.id)
        if not mentor_role_id or not discord.utils.get(interaction.user.roles, id=mentor_role_id):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        
        cp_role_id = await get_cp_role_id(interaction.guild.id)
        cp_role = interaction.guild.get_role(cp_role_id) if cp_role_id else None
        if not cp_role:
            await interaction.followup.send("CP role not found or not configured.", ephemeral=True)
            return

        for member in cp_role.members:
            try: await member.send(message)
            except discord.Forbidden: print(f"Could not send DM to {member.name}")
            except Exception as e: print(f"An error occurred while sending DM to {member.name}: {e}")

        contest_channel_id = await get_contest_channel_id(interaction.guild.id)
        channel = self.bot.get_channel(contest_channel_id) if contest_channel_id else None
        if channel:
            await channel.send(f"{cp_role.mention} {message}")
            await interaction.followup.send("Notification sent successfully!")
        else:
            await interaction.followup.send("Announcement channel not configured.", ephemeral=True)

# --- Interaction Listener Cog ---

class ContestInteractions(commands.Cog):
    """Cog to handle all component interactions for contests"""
    
    def __init__(self, bot):
        self.bot = bot
        self.handler = ContestInteractionHandler(bot)
    
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
            
        custom_id = interaction.data.get('custom_id', '')
        
        if custom_id.startswith('join_'):
            await self.handler.handle_join_contest(interaction, custom_id)
        
        elif custom_id.startswith('check_'):
            await self.handler.handle_check_solved(interaction, custom_id)

# --- Setup Function ---

async def setup(bot):
    if not hasattr(bot, 'session'):
        bot.session = aiohttp.ClientSession()
    
    await bot.add_cog(ContestCommands(bot))
    await bot.add_cog(ContestInteractions(bot))
