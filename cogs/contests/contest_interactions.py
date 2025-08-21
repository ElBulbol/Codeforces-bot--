"""
Contest interaction handlers for join contest and check solved buttons
"""
import discord
from discord.ext import commands
import json
from datetime import datetime
from utility.db_helpers import (
    get_bot_contest, get_user_by_discord, join_contest, get_contest_participant_count,
    get_contest_participant, get_contest_problems, update_contest_participant_score
)

class ContestInteractionHandler:
    """Handles contest-related interactions like join and check solved buttons"""
    
    def __init__(self, bot):
        self.bot = bot
        self.ANNOUNCEMENT_CHANNEL_ID = 637013889439105058  # bot-testing
    
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

        # Update the announcement message with participant count (only if successfully joined or to refresh count)
        if not was_already_joined or True:  # Always update to show current count
            try:
                participant_count = await get_contest_participant_count(contest_id)
                await self._update_announcement_with_participant_count(interaction, contest_data, contest_id, participant_count)
            except Exception as e:
                print(f"Error updating announcement with participant count: {e}")

    async def handle_check_solved(self, interaction: discord.Interaction, custom_id: str):
        """Handle check solved button clicks"""
        try:
            parts = custom_id.split('_')
            contest_id = int(parts[1])
            problem_index = int(parts[2])
        except (IndexError, ValueError):
            await interaction.response.send_message("Invalid button data.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # Check if contest is still active
        contest_data = await get_bot_contest(contest_id)
        if not contest_data:
            await interaction.followup.send("Contest not found.", ephemeral=True)
            return
        
        if contest_data['status'] != 'ACTIVE':
            await interaction.followup.send(
                f"This contest is no longer active (Status: {contest_data['status']}). You can only check solutions during active contests.", 
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
        
        # Extract contest and problem from URL
        try:
            parts = problem_link.strip('/').split('/')
            cf_contest_id = parts[-2]
            problem_letter = parts[-1]
        except (IndexError, ValueError):
            await interaction.followup.send("Invalid problem link format.", ephemeral=True)
            return

        # Check if user solved the problem
        try:
            async with self.bot.session.get(
                f"https://codeforces.com/api/user.status?handle={participant['codeforces_handle']}&from=1&count=1000"
            ) as resp:
                if resp.status != 200:
                    await interaction.followup.send(
                        "Error checking Codeforces API. Please try again later.", 
                        ephemeral=True
                    )
                    return
                
                data = await resp.json()
                if data.get('status') != 'OK':
                    await interaction.followup.send(
                        f"Codeforces API error: {data.get('comment', 'Unknown error')}", 
                        ephemeral=True
                    )
                    return

                # Check if problem is solved
                solved = False
                for submission in data['result']:
                    if (str(submission['problem']['contestId']) == cf_contest_id and 
                        submission['problem']['index'] == problem_letter and 
                        submission['verdict'] == 'OK'):
                        solved = True
                        break

                if solved:
                    # Check if already counted
                    solved_problems = json.loads(participant.get('solved_problems', '[]'))
                    if problem_index not in solved_problems:
                        solved_problems.append(problem_index)
                        
                        # Award points (could be adjusted based on your scoring system)
                        points = 100  # Base points per problem
                        
                        await update_contest_participant_score(
                            contest_id, str(interaction.user.id), points, solved_problems
                        )
                        
                        await interaction.followup.send(
                            f"🎉 Congratulations! You solved problem {problem_index + 1} and earned {points} points!", 
                            ephemeral=True
                        )
                    else:
                        await interaction.followup.send(
                            f"You've already been awarded points for problem {problem_index + 1}.", 
                            ephemeral=True
                        )
                else:
                    await interaction.followup.send(
                        f"Problem {problem_index + 1} is not solved yet. Keep trying! 💪", 
                        ephemeral=True
                    )

        except Exception as e:
            await interaction.followup.send(
                f"Error checking solution status: {str(e)}", 
                ephemeral=True
            )

    async def _update_announcement_with_participant_count(self, interaction: discord.Interaction, contest_data: dict, contest_id: int, participant_count: int):
        """Update the original announcement message with participant count"""
        announcement_channel = self.bot.get_channel(self.ANNOUNCEMENT_CHANNEL_ID)
        if not announcement_channel:
            return

        try:
            # Search for the announcement message in recent messages
            # Look for messages that contain the contest ID in the footer
            async for message in announcement_channel.history(limit=50):
                if (message.author == self.bot.user and 
                    message.embeds and 
                    message.embeds[0].footer and 
                    f"Contest ID: {contest_id}" in message.embeds[0].footer.text):
                    
                    # Use Discord timestamp if available, otherwise fallback to formatted time
                    if contest_data.get('unix_timestamp'):
                        unix_timestamp = contest_data['unix_timestamp']
                        starts_at_text = f"<t:{unix_timestamp}:F> (<t:{unix_timestamp}:R>)"
                    else:
                        start_time_dt = datetime.fromisoformat(contest_data['start_time'])
                        starts_at_text = start_time_dt.strftime('%d/%m/%Y %H:%M')
                    
                    # Get the actual problems list to count properly
                    problems_list = await get_contest_problems(contest_id)
                    problems_count = len(problems_list) if problems_list else 0
                    
                    # Create updated embed with participant count
                    embed = discord.Embed(
                        title=f"📢 New Contest: {contest_data['name']}",
                        description=f"A new contest has been scheduled!\n\n"
                                    f"**Starts at:** {starts_at_text}\n"
                                    f"**Duration:** {contest_data['duration']} minutes\n"
                                    f"**Problems:** {problems_count}\n"
                                    f"**Participants:** {participant_count}",
                        color=discord.Color.blue()
                    )
                    embed.set_footer(text=f"Contest ID: {contest_id}")
                    
                    # Keep the same view (Join Contest button)
                    view = discord.ui.View(timeout=None)
                    view.add_item(discord.ui.Button(
                        label="Join Contest", 
                        style=discord.ButtonStyle.success, 
                        custom_id=f"join_{contest_id}"
                    ))
                    
                    await message.edit(embed=embed, view=view)
                    break
                    
        except Exception as e:
            print(f"Error updating announcement message: {e}")

class ContestInteractions(commands.Cog):
    """Cog to handle contest-related interactions"""
    
    def __init__(self, bot):
        self.bot = bot
        self.handler = ContestInteractionHandler(bot)
    
    async def handle_contest_interaction(self, interaction: discord.Interaction):
        """Main handler for contest interactions"""
        custom_id = interaction.data.get('custom_id', '')
        
        # Handle Join Contest buttons
        if custom_id.startswith('join_'):
            await self.handler.handle_join_contest(interaction, custom_id)
        
        # Handle Check Solved buttons
        elif custom_id.startswith('check_'):
            await self.handler.handle_check_solved(interaction, custom_id)

async def setup(bot):
    await bot.add_cog(ContestInteractions(bot))
