from typing import Optional
import discord
from discord.ext import commands
from discord import app_commands
from discord.ext import tasks
from datetime import datetime, timedelta
from utility.db_helpers import (
    get_bot_contest, 
    get_pending_and_active_contests, update_contest_status,
    get_contest_problems, get_contest_leaderboard, get_all_bot_contests
)

# Import the contest builder components
from .contest_builder import (
    ContestBuilder, SetNameModal, SetDurationModal, SetStartTimeModal,
    AddProblemBuilderModal, ContestBuilderView, contest_builder,
    create_contest_setup_embed, create_contest_completed_embed,
    MENTOR_ROLE_ID, PARTICIPANT_ROLE_ID, ANNOUNCEMENT_CHANNEL_ID
)

class ContestCommands(commands.GroupCog, name = "contest"):
    def __init__(self, bot):
        self.bot = bot
        self.active_contests = {}  # To store views for active contests
        self.check_contests.start()

    def cog_unload(self):
        self.check_contests.cancel()

    @tasks.loop(seconds=10)  # Check every 10 seconds instead of every minute
    async def check_contests(self):
        # This loop checks for contests to start or end
        contests = await get_pending_and_active_contests()

        for contest_data in contests:
            contest_id = contest_data['contest_id']
            name = contest_data['name']
            duration = contest_data['duration']
            start_time_iso = contest_data['start_time']
            status = contest_data['status']
            
            try:
                start_time = datetime.fromisoformat(start_time_iso)
                end_time = start_time + timedelta(minutes=duration)
                now = datetime.now()

                # Debug logging
                print(f"Contest {contest_id}: status={status}, start_time={start_time}, now={now}, should_start={start_time <= now < end_time}")

                # Start contest if it's time and its status is PENDING
                if status == 'PENDING' and start_time <= now < end_time:
                    problems = await get_contest_problems(contest_id)
                    if not problems:
                        print(f"Contest {contest_id} has no problems, skipping start")
                        continue
                    participant_role = None
                    await self.start_contest(contest_id, name, problems, participant_role)

                # End contest if it's time and its status is ACTIVE
                elif status == 'ACTIVE' and now >= end_time:
                    await self.end_contest(contest_id, name)
                    
            except Exception as e:
                print(f"Error processing contest {contest_id}: {e}")
                continue
    
    async def start_contest(self, contest_id, contest_name, problems, participant_role):
        await update_contest_status(contest_id, 'ACTIVE')

        channel = self.bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        if not channel:
            return

        self.active_contests[contest_id] = {}

        contest_data = await get_bot_contest(contest_id)
        duration = contest_data['duration']

        now_unix = int(datetime.now().timestamp())
        unix_start = contest_data.get('unix_timestamp')
        if not unix_start:
            try:
                start_dt = datetime.fromisoformat(contest_data.get('start_time'))
                unix_start = int(start_dt.timestamp())
            except Exception:
                unix_start = now_unix

        unix_end = unix_start + int(duration) * 60

        starts_at_text = f"<t:{unix_start}:R>"
        countdown_text = f"<t:{unix_end}:R>"

        embed = discord.Embed(
            title=f"🏆 Contest Started: {contest_name}",
            description="Get ready to solve problems and climb the leaderboard!",
            color=discord.Color.blurple()
        )

        embed.add_field(
            name="🕒 Starts At",
            value=starts_at_text,
            inline=True
        )

        embed.add_field(
            name="⏳ Countdown",
            value=countdown_text,
            inline=True
        )

        problem_list = ""
        for i, problem in enumerate(problems, start=1):
            if isinstance(problem, dict):
                problem_name = problem.get("name", f"Problem {i}")
                problem_link = problem.get("link", "")
            else:
                problem_name = f"Problem {i}"
                problem_link = problem
            problem_list += f"**{i}.** [{problem_name}]({problem_link})\n"

        embed.add_field(
            name="📘 Problems",
            value=problem_list if problem_list else "No problems added.",
            inline=False
        )

        embed.set_footer(text=f"Contest ID: {contest_id} • Good luck! 🚀")

        view = discord.ui.View(timeout=None)
        for i in range(len(problems)):
            view.add_item(discord.ui.Button(
                label=f"✅ P{i+1}",
                style=discord.ButtonStyle.primary,
                custom_id=f"check_{contest_id}_{i}"
            ))

        if not participant_role and channel.guild:
            participant_role = channel.guild.get_role(PARTICIPANT_ROLE_ID)

        message = await channel.send(
            content=f"{participant_role.mention if participant_role else 'Participants'}",
            embed=embed,
            view=view
        )
        print(f"Started contest {contest_id}")

        self.active_contests[contest_id]['message'] = message
        self.active_contests[contest_id]['unix_end'] = unix_end

        task = asyncio.create_task(self._countdown_task(contest_id, message, unix_end, contest_name, problems))
        self.active_contests[contest_id]['countdown_task'] = task

        # Get contest data
        contest_data = await get_bot_contest(contest_id)

        # Create a dummy interaction object if needed (for legacy calls)
        # If you have access to the original interaction, pass it instead!
        class DummyInteraction:
            def __init__(self, bot, guild):
                self.client = bot
                self.guild = guild

        # Get the guild object (from channel)
        guild = channel.guild if channel else None
        interaction = DummyInteraction(self.bot, guild)

        # Use ContestBuilderView to send the announcement
        builder_view = ContestBuilderView("unused_interaction_id")  # interaction_id not needed for announcement
        await builder_view._send_announcement(interaction, contest_data, contest_id)

    async def end_contest(self, contest_id, contest_name):
        # Update status in DB
        await update_contest_status(contest_id, 'ENDED')

        # cancel countdown task if exists
        active = self.active_contests.get(contest_id)
        if active:
            task = active.get('countdown_task')
            if task and not task.done():
                try:
                    task.cancel()
                except Exception:
                    pass

        channel = self.bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        if channel:
            await channel.send(f"Contest '{contest_name}' (ID: {contest_id}) has ended! 🏁")
            
            # Get and display the results
            results = await get_contest_leaderboard(contest_id)
            
            if results:
                embed = discord.Embed(
                    title=f"🏆 **FINAL RESULTS**: {contest_name.upper()}",
                    description=f"**📌 Contest ID:** `{contest_id}`\n\n",
                    color=discord.Color.gold()
                )
                embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/1828/1828884.png")  # Trophy icon

                # Build leaderboard text
                top3_text = ""
                others_text = ""

                for rank, result in enumerate(results, 1):
                    discord_id = result['discord_id']
                    handle = result['codeforces_handle']
                    score = result['score']
                    user = self.bot.get_user(int(discord_id))
                    user_mention = user.mention if user else f"ID: {discord_id}"

                    # Top 3 with medals
                    if rank == 1:
                        medal = "🥇"
                        top3_text += f"**{medal} {user_mention} ({handle}) — {score} pts**\n"
                    elif rank == 2:
                        medal = "🥈"
                        top3_text += f"**{medal} {user_mention} ({handle}) — {score} pts**\n"
                    elif rank == 3:
                        medal = "🥉"
                        top3_text += f"**{medal} {user_mention} ({handle}) — {score} pts**\n"
                    else:
                        others_text += f"`#{rank}` {user_mention} ({handle}) — {score} pts\n"

                if top3_text:
                    embed.add_field(name="👑 **Top 3**", value=top3_text, inline=False)
                if others_text:
                    embed.add_field(name="📊 **Other Participants**", value=others_text, inline=False)

                # Highlight winner separately
                if len(results) > 0:
                    winner = results[0]
                    winner_user = self.bot.get_user(int(winner['discord_id']))
                    winner_mention = winner_user.mention if winner_user else f"ID: {winner['discord_id']}"
                    embed.add_field(
                        name="🎉 **CHAMPION**",
                        value=f"🏅 **All hail {winner_mention} with {winner['score']} pts!**",
                        inline=False
                    )

                embed.set_footer(text="Thanks for participating! 🚀")

                await channel.send(embed=embed)
            else:
                await channel.send("No participants found for this contest.")

        if contest_id in self.active_contests:
            del self.active_contests[contest_id]
        print(f"Ended contest {contest_id}")

    @app_commands.command(name="create", description="Opens an interactive contest builder.")
    @app_commands.checks.has_role(MENTOR_ROLE_ID)
    async def create_contest(self, interaction: discord.Interaction):
        """Opens an interactive contest builder interface."""
        interaction_id = f"{interaction.user.id}_{interaction.id}"
        contest_data = contest_builder.create_contest(interaction_id)
    
        embed = create_contest_setup_embed(contest_data)
        view = ContestBuilderView(interaction_id)
        
        # Update the select menu options based on current problems
        view._update_remove_select(contest_data)
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="start", description="Immediately starts a contest.")
    @app_commands.checks.has_role(MENTOR_ROLE_ID)
    @app_commands.describe(contest_id="The ID of the contest to start.")
    async def start_contest_now(self, interaction: discord.Interaction, contest_id: int):
        """Manually starts a contest, bypassing the schedule."""
        await interaction.response.defer(ephemeral=True)

        if contest_id in self.active_contests:
            await interaction.followup.send(f"Contest {contest_id} is already active.", ephemeral=True)
            return

        contest_data = await get_bot_contest(contest_id)
        if not contest_data:
            await interaction.followup.send(f"Contest with ID {contest_id} not found.", ephemeral=True)
            return
        
        name = contest_data['name']
        status = contest_data['status']

        if status == 'ACTIVE':
            await interaction.followup.send(f"Contest {contest_id} is already active.", ephemeral=True)
            return
        if status == 'ENDED':
            await interaction.followup.send(f"Contest {contest_id} has already ended.", ephemeral=True)
            return
        
        problems = await get_contest_problems(contest_id)

        if not problems:
            await interaction.followup.send(f"Contest {contest_id} has no problems. Please add problems before starting.", ephemeral=True)
            return

        participant_role = interaction.guild.get_role(PARTICIPANT_ROLE_ID)
        await self.start_contest(contest_id, name, problems, participant_role)
        await interaction.followup.send(f"Contest {contest_id} ('{name}') has been started manually.", ephemeral=True)

    @app_commands.command(name="end", description="Immediately ends a contest.")
    @app_commands.checks.has_role(MENTOR_ROLE_ID)
    @app_commands.describe(contest_id="The ID of the contest to end.")
    async def end_contest_now(self, interaction: discord.Interaction, contest_id: int):
        """Manually ends a contest."""
        await interaction.response.defer(ephemeral=True)

        contest_data = await get_bot_contest(contest_id)
        if not contest_data:
            await interaction.followup.send(f"Contest with ID {contest_id} not found.", ephemeral=True)
            return

        name = contest_data['name']
        status = contest_data['status']

        if status != 'ACTIVE':
            await interaction.followup.send(f"Contest {contest_id} is not currently active.", ephemeral=True)
            return

        await self.end_contest(contest_id, name)
        await interaction.followup.send(f"Contest {contest_id} ('{name}') has been ended manually.", ephemeral=True)

    @app_commands.command(name="result", description="Display the results of a contest")
    async def result(self, interaction: discord.Interaction, contest_id: int):
        """
        Displays the leaderboard for a specific contest.
        """
        results = await get_contest_leaderboard(contest_id)

        if not results:
            await interaction.response.send_message("No results found for this contest.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"Contest {contest_id} Results",
            color=discord.Color.gold()
        )

        description = ""
        for rank, result in enumerate(results, 1):
            discord_id = result['discord_id']
            handle = result['codeforces_handle']
            score = result['score']
            user = self.bot.get_user(int(discord_id))
            user_mention = user.mention if user else f"ID: {discord_id}"
            description += f"**{rank}.** {user_mention} ({handle}) - **{score} points**\n"
        
        embed.description = description
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="info", description="Shows information and problems for a specific contest.")
    @app_commands.describe(contest_id="The ID of the contest to show.")
    async def show_contest_info(self, interaction: discord.Interaction, contest_id: int):
        """Displays all information for a given contest."""
        await interaction.response.defer(ephemeral=True)

        contest_data = await get_bot_contest(contest_id)
        if not contest_data:
            await interaction.followup.send(f"No contest found with ID: {contest_id}", ephemeral=True)
            return

        name = contest_data['name']
        duration = contest_data['duration']
        start_time_str = contest_data['start_time']
        status = contest_data['status']

        # Format start time using Discord timestamp syntax if unix_timestamp is available
        if contest_data.get('unix_timestamp'):
            unix_timestamp = contest_data['unix_timestamp']
            start_time_display = f"<t:{unix_timestamp}:R>"
        else:
            # Fallback to regular format and try to convert to unix timestamp
            try:
                start_time_dt = datetime.fromisoformat(start_time_str)
                unix_timestamp = int(start_time_dt.timestamp())
                start_time_display = f"<t:{unix_timestamp}:R>"
            except (ValueError, TypeError):
                start_time_display = "Not set or invalid format"

        # Format problems list for display
        problems_list = await get_contest_problems(contest_id)
        problems_display = "No problems have been added yet."
        if problems_list:
            problems_display = "\n".join([f"{i+1}. [Problem Link]({link})" for i, link in enumerate(problems_list)])

        # Get participants list
        participants = await get_contest_leaderboard(contest_id)
        participants_display = "No participants yet."
        if participants:
            participant_list = []
            for participant in participants:
                discord_id = participant['discord_id']
                handle = participant['codeforces_handle']
                score = participant['score']
                user = self.bot.get_user(int(discord_id))
                user_mention = user.mention if user else f"ID: {discord_id}"
                participant_list.append(f"• {user_mention} ({handle}) - {score} points")
            participants_display = "\n".join(participant_list)

        embed = discord.Embed(
            title=f"Contest Info: {name}",
            color=discord.Color.blue()
        )
        embed.add_field(name="Contest ID", value=str(contest_id), inline=True)
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Duration", value=f"{duration} minutes", inline=True)
        embed.add_field(name="Start Time", value=start_time_display, inline=False)
        embed.add_field(name="Problems", value=problems_display, inline=False)
        embed.add_field(name="Participants", value=participants_display, inline=False)
        
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="list", description="Shows all past contests with their IDs and dates.")
    async def list_contests(self, interaction: discord.Interaction):
        """Displays all bot contests with their information."""
        await interaction.response.defer(ephemeral=True)

        contests = await get_all_bot_contests()
        
        if not contests:
            await interaction.followup.send("No contests found.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📋 All Contests",
            description="List of all contests (newest first)",
            color=discord.Color.purple()
        )

        contest_list = []
        for contest in contests:
            contest_id = contest['contest_id']
            name = contest['name']
            status = contest['status']
            start_time_str = contest['start_time']
            
            # Format start time using Discord timestamp syntax if unix_timestamp is available
            if contest.get('unix_timestamp'):
                unix_timestamp = contest['unix_timestamp']
                time_display = f"<t:{unix_timestamp}:D>"  # Date format
            else:
                # Fallback to regular format and try to convert to unix timestamp
                try:
                    start_time_dt = datetime.fromisoformat(start_time_str)
                    unix_timestamp = int(start_time_dt.timestamp())
                    time_display = f"<t:{unix_timestamp}:D>"
                except (ValueError, TypeError):
                    time_display = "Date unknown"

            # Add status emoji
            if status == 'PENDING':
                status_emoji = "🟡"
            elif status == 'ACTIVE':
                status_emoji = "🟢"
            elif status == 'ENDED':
                status_emoji = "🔴"
            else:
                status_emoji = "⚪"

            contest_list.append(f"{status_emoji} **#{contest_id}** - {name}\n└ {time_display} • Status: {status}")

        # Split into multiple embeds if too long
        contest_text = "\n\n".join(contest_list)
        
        if len(contest_text) > 4096:  # Discord embed description limit
            # Split into chunks
            chunks = []
            current_chunk = []
            current_length = 0
            
            for contest_line in contest_list:
                if current_length + len(contest_line) + 2 > 4096:  # +2 for \n\n
                    chunks.append("\n\n".join(current_chunk))
                    current_chunk = [contest_line]
                    current_length = len(contest_line)
                else:
                    current_chunk.append(contest_line)
                    current_length += len(contest_line) + 2
            
            if current_chunk:
                chunks.append("\n\n".join(current_chunk))
            
            # Send first chunk with the main embed
            embed.description = f"List of all contests (newest first)\n\n{chunks[0]}"
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            # Send additional chunks
            for i, chunk in enumerate(chunks[1:], 2):
                embed_chunk = discord.Embed(
                    title=f"📋 All Contests (Page {i})",
                    description=chunk,
                    color=discord.Color.purple()
                )
                await interaction.followup.send(embed=embed_chunk, ephemeral=True)
        else:
            embed.description = f"List of all contests (newest first)\n\n{contest_text}"
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="notify", description="Sends a notification about a contest.")
    @app_commands.checks.has_role(MENTOR_ROLE_ID)
    @app_commands.describe(message="The message to send to CP members.")
    @app_commands.checks.cooldown(1, 5, key = lambda i: (i.user.id))
    async def contest_notify(self, interaction: discord.Interaction, message: str):
        """Send a private message to all CP members and mention CP in a specific channel."""
        await interaction.response.defer(ephemeral=True)
        cp_role = discord.utils.get(interaction.guild.roles, name=PARTICIPANT_ROLE_ID)
        if not cp_role:
            await interaction.followup.send("CP role not found.")
            return

        for member in cp_role.members:
            try:
                await member.send(message)
            except discord.Forbidden:
                print(f"Could not send DM to {member.name}")
            except Exception as e:
                print(f"An error occurred while sending DM to {member.name}: {e}")

        channel = self.bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        if channel:
            await channel.send(f"{cp_role.mention} {message}")
            await interaction.followup.send("Notification sent successfully!")
        else:
            await interaction.followup.send(f"Contest channel with ID {ANNOUNCEMENT_CHANNEL_ID} not found.")

    @app_commands.command(name="addproblem", description="Adds a problem to an existing contest.")
    @app_commands.checks.has_role(MENTOR_ROLE_ID)
    @app_commands.describe(
        contest_id="The ID of the contest",
        problem_link="The link to the problem (Codeforces, AtCoder, etc.)"
    )
    async def add_problem_to_contest(self, interaction: discord.Interaction, contest_id: int, problem_link: str):
        """Adds a problem to an existing contest."""
        await interaction.response.defer(ephemeral=True)

        # Extract contest_id and problem_index from the URL
        try:
            parts = problem_link.strip('/').split('/')
            if "contest" in parts:
                contest_index = parts.index("contest")
                cf_contest_id = parts[contest_index + 1]
                problem_letter = parts[-1]
            else:
                await interaction.followup.send("Unsupported problem URL format.", ephemeral=True)
                return
        except (IndexError, ValueError):
            await interaction.followup.send("Invalid problem link format.", ephemeral=True)
            return

        # Fetch problem name from Codeforces API
        problem_name = get_codeforces_problem_name(cf_contest_id, problem_letter)
        if not problem_name:
            problem_name = f"Problem {problem_letter}"
        await update_contest_problems(contest_id, [{"link": problem_link, "name": problem_name}])        # (Assuming you have a function to do this, e.g., update_contest_problems_with_name)        # Store both link and name in your contest's problems list            problem_name = f"Problem {problem_letter}"    await bot.add_cog(ContestCommands(bot))

async def setup(bot):
    await bot.add_cog(ContestCommands(bot))
