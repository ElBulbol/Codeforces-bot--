"""
Contest interaction handlers for join contest and check solved buttons
"""
import discord
from discord.ext import commands
from datetime import datetime
from utility.db_helpers import (
    get_bot_contest, get_user_by_discord, join_contest, get_contest_participant_count,
    get_contest_participant, get_contest_problems, update_contest_participant_score,
    add_contest_score_entry, update_contest_score, get_contest_solves_info, update_contest_solves_info,
    increment_user_solved_count
)
from utility.recording_score import update_contest_score

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
            # Ensure row exists in contest_participants
            import aiosqlite
            async with aiosqlite.connect("db/db.db") as db:
                await db.execute(
                    "INSERT OR IGNORE INTO contest_participants (contest_id, user_id, score, solved_problems) VALUES (?, ?, 0, '')",
                    (contest_id, str(interaction.user.id))
                )
                await db.commit()
                # --- Cleanup orphaned contest_participants rows ---
                await db.execute("""
                    DELETE FROM contest_participants
                    WHERE user_id NOT IN (SELECT user_id FROM users)
                """)
                await db.commit()
            # Add entry to contest_scores table
            await add_contest_score_entry(contest_id, str(interaction.user.id), user_data['cf_handle'], score=0, problem_solved=0)
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
            # Debug print to see the URL parts
            print(f"Problem URL parts: {parts}")
            
            if "contest" in parts:
                contest_index = parts.index("contest")
                cf_contest_id = parts[contest_index + 1]
            elif "problemset" in parts:
                problem_index_in_url = parts.index("problem")
                cf_contest_id = parts[problem_index_in_url + 1]
            elif "gym" in parts:
                gym_index = parts.index("gym")
                cf_contest_id = parts[gym_index + 1]
            else:
                await interaction.followup.send("Unsupported problem URL format.", ephemeral=True)
                return
            
            problem_letter = parts[-1]
            print(f"Extracted contest ID: {cf_contest_id}, problem letter: {problem_letter}")
            
        except (IndexError, ValueError) as e:
            await interaction.followup.send(f"Invalid problem link format: {str(e)}", ephemeral=True)
            return

        # Check if user solved the problem
        try:
            cf_handle = participant['codeforces_handle']
            print(f"Checking submissions for user: {cf_handle}")
            
            api_url = f"https://codeforces.com/api/user.status?handle={cf_handle}&from=1&count=1000"
            print(f"API URL: {api_url}")
            
            async with self.bot.session.get(api_url) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    print(f"API error: {resp.status}, {error_text}")
                    await interaction.followup.send(
                        f"Error checking Codeforces API. Status: {resp.status}", 
                        ephemeral=True
                    )
                    return
                
                data = await resp.json()
                if data.get('status') != 'OK':
                    print(f"API returned non-OK status: {data}")
                    await interaction.followup.send(
                        f"Codeforces API error: {data.get('comment', 'Unknown error')}", 
                        ephemeral=True
                    )
                    return

                # Check if problem is solved
                solved = False
                problem_rating = 0
                for submission in data['result']:
                    submission_contest_id = str(submission['problem'].get('contestId', ''))
                    submission_index = submission['problem'].get('index', '')
                    submission_verdict = submission.get('verdict', '')
                    
                    print(f"Comparing: {submission_contest_id}=={cf_contest_id} and {submission_index}=={problem_letter} and verdict={submission_verdict}")
                    
                    if (submission_contest_id == cf_contest_id and 
                        submission_index == problem_letter and 
                        submission_verdict == 'OK'):
                        solved = True
                        # Get problem rating if available
                        if 'rating' in submission['problem']:
                            problem_rating = submission['problem']['rating']
                        print(f"Found matching solved submission! Problem rating: {problem_rating}")
                        break

                print(f"Final solved status: {solved}")
                
                if solved:
                    # --- Prevent multiple rewards for the same problem ---
                    # Get solves info for this contest
                    solves_info = await get_contest_solves_info(contest_id)
                    user_id = str(interaction.user.id)
                    problem_key = f"{contest_id}-{problem_link}"

                    # Check if user already got points for this problem
                    already_solved = solves_info.get(user_id, [])
                    if problem_key in already_solved:
                        await interaction.followup.send(
                            "You have already received points for solving this problem.",
                            ephemeral=True
                        )
                        return

                    # Mark as solved for this user
                    if user_id not in solves_info:
                        solves_info[user_id] = []
                    solves_info[user_id].append(problem_key)
                    await update_contest_solves_info(contest_id, solves_info)

                    # --- Continue with scoring logic ---
                    # Calculate score
                    score = (problem_rating / 100) if problem_rating else 8
                    # First solver bonus (if needed)
                    is_first_solver = False
                    try:
                        # Get current solves info for this contest
                        solves_info = await get_contest_solves_info(contest_id)
                        if not solves_info or problem_link not in solves_info:
                            # First solver gets bonus points
                            is_first_solver = True
                            score += 3
                            # Update solves info
                            if not solves_info:
                                solves_info = {}
                            solves_info[problem_link] = str(interaction.user.id)
                            await update_contest_solves_info(contest_id, solves_info)
                    except Exception as e:
                        print(f"Error checking first solver: {e}")

                    # --- Integrate update_contest_score function here ---
                    # This will update contest_participants and contest_scores tables
                    try:
                        user_id = int(interaction.user.id)
                        # Ensure participant row exists
                        await add_contest_score_entry(contest_id, str(interaction.user.id), participant['codeforces_handle'], score=0, problem_solved=0)
                        # Now update score
                        # Fetch user_id from users table using Discord ID
                        user_data = await get_user_by_discord(str(interaction.user.id))
                        if not user_data:
                            await interaction.response.send_message("You need to link your Codeforces account first.", ephemeral=True)
                            return
                        user_id = user_data['user_id']  # This is the correct user_id from the database

                        update_contest_score(contest_id, user_id, problem_link)
                    except Exception as e:
                        print(f"Error in update_contest_score: {e}")

                    await interaction.followup.send(
                        f"🎉 Congratulations! You solved problem {problem_index + 1} and earned {int(score)} points!",
                        ephemeral=True
                    )

                    # Send public message to the solved notification channel
                    solved_channel_id = 1404857696666128405
                    solved_channel = self.bot.get_channel(solved_channel_id)
                    if solved_channel:
                        if is_first_solver:
                            await solved_channel.send(
                                f"🚀 First accepted for problem {problem_index + 1} by <@{interaction.user.id}> in contest **{contest_data['name']}**!"
                            )
                        else:
                            await solved_channel.send(
                                f"✅ <@{interaction.user.id}> has solved problem {problem_index + 1} in contest **{contest_data['name']}**!"
                            )
                else:
                    await interaction.followup.send(
                        f"Problem {problem_index + 1} is not solved yet. Keep trying! 💪", 
                        ephemeral=True
                    )

        except Exception as e:
            print(f"Exception in handle_check_solved: {e}")
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
                        starts_at_text = f"<t:{unix_timestamp}:R>"
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
