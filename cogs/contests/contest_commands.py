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
        self.contest_loop.start()

    def cog_unload(self):
        self.contest_loop.cancel()

    @tasks.loop(minutes=1)
    async def contest_loop(self):
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
        # Update status in DB to prevent restarts
        await update_contest_status(contest_id, 'ACTIVE')

        channel = self.bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        if not channel:
            return

        self.active_contests[contest_id] = {}
        
        embed = discord.Embed(
            title=f"Contest Started: {contest_name}",
            description="Solve the problems and check your solutions below.",
            color=discord.Color.green()
        )
        
        view = discord.ui.View(timeout=None)
        for i, problem_link in enumerate(problems):
            embed.add_field(name=f"Problem {i+1}", value=f"[Link]({problem_link})", inline=False)
            view.add_item(discord.ui.Button(label=f"Check Solved - P{i+1}", style=discord.ButtonStyle.secondary, custom_id=f"check_{contest_id}_{i}"))

        # Always try to get the participant role from the guild where the channel is
        if not participant_role and channel.guild:
            participant_role = channel.guild.get_role(PARTICIPANT_ROLE_ID)
        
        await channel.send(content=f"{participant_role.mention if participant_role else 'Participants'}", embed=embed, view=view)
        print(f"Started contest {contest_id}")

    async def end_contest(self, contest_id, contest_name):
        # Update status in DB
        await update_contest_status(contest_id, 'ENDED')

        channel = self.bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        if channel:
            await channel.send(f"Contest '{contest_name}' (ID: {contest_id}) has ended! 🏁")
            
            # Get and display the results
            results = await get_contest_leaderboard(contest_id)
            
            if results:
                embed = discord.Embed(
                    title=f"🏆 Final Results: {contest_name}",
                    description=f"Contest ID: {contest_id}",
                    color=discord.Color.gold()
                )
                
                results_text = ""
                for rank, result in enumerate(results, 1):
                    discord_id = result['discord_id']
                    handle = result['codeforces_handle']
                    score = result['score']
                    user = self.bot.get_user(int(discord_id))
                    user_mention = user.mention if user else f"ID: {discord_id}"
                    
                    # Add medal emojis for top 3
                    if rank == 1:
                        medal = "🥇"
                    elif rank == 2:
                        medal = "🥈"
                    elif rank == 3:
                        medal = "🥉"
                    else:
                        medal = f"**{rank}.**"
                    
                    results_text += f"{medal} {user_mention} ({handle}) - **{score} points**\n"
                
                embed.add_field(name="Leaderboard", value=results_text, inline=False)
                
                # Add congratulations message
                if len(results) > 0:
                    winner = results[0]
                    winner_user = self.bot.get_user(int(winner['discord_id']))
                    winner_mention = winner_user.mention if winner_user else f"ID: {winner['discord_id']}"
                    embed.add_field(
                        name="🎉 Congratulations!", 
                        value=f"Winner: {winner_mention} with {winner['score']} points!", 
                        inline=False
                    )
                
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
            start_time_display = f"<t:{unix_timestamp}:F> (<t:{unix_timestamp}:R>)"
        else:
            # Fallback to regular format and try to convert to unix timestamp
            try:
                start_time_dt = datetime.fromisoformat(start_time_str)
                unix_timestamp = int(start_time_dt.timestamp())
                start_time_display = f"<t:{unix_timestamp}:F> (<t:{unix_timestamp}:R>)"
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

async def setup(bot):
    await bot.add_cog(ContestCommands(bot))
