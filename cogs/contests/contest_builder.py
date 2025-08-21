import re
from typing import Dict, List, Optional
from typing import Optional
import discord
from discord.ext import commands
from discord import app_commands
from discord.ext import tasks
import aiohttp
from datetime import datetime, timedelta
import asyncio
import json
from utility.random_problems import get_random_problem
from utility.db_helpers import get_contest_participant_count, update_contest_problems, create_bot_contest

# Role and Channel IDs
MENTOR_ROLE_ID = 1405870294471540807 # Mentor
PARTICIPANT_ROLE_ID = 1404736993035812934 # CP
ANNOUNCEMENT_CHANNEL_ID = 1404857696666128405 # bot-testing

class ContestBuilder:
    """Temporary storage for contest data while building"""
    def __init__(self):
        self.contests: Dict[str, Dict] = {}  # key: interaction_id, value: contest data
    
    def create_contest(self, interaction_id: str) -> Dict:
        """Create a new contest builder session"""
        start_time_dt = datetime.now() + timedelta(minutes=1)
        unix_timestamp = int(start_time_dt.timestamp())
        self.contests[interaction_id] = {
            'name': 'Untitled Contest',
            'duration': 1,
            'start_time': start_time_dt.isoformat(),
            'start_minutes': 1,
            'unix_timestamp': unix_timestamp,
            'problems': []  # List of dicts with {link, display_name, criteria}
        }
        return self.contests[interaction_id]
    
    def get_contest(self, interaction_id: str) -> Optional[Dict]:
        """Get contest data for a session"""
        return self.contests.get(interaction_id)
    
    def update_contest(self, interaction_id: str, **kwargs) -> Dict:
        """Update contest data"""
        if interaction_id in self.contests:
            self.contests[interaction_id].update(kwargs)
        return self.contests.get(interaction_id, {})
    
    def delete_contest(self, interaction_id: str):
        """Clean up contest session"""
        self.contests.pop(interaction_id, None)

# Global contest builder instance
contest_builder = ContestBuilder()

class SetNameModal(discord.ui.Modal, title='Set Contest Name'):
    contest_name = discord.ui.TextInput(
        label='Contest Name',
        placeholder='Enter the contest name...',
        style=discord.TextStyle.short,
        required=True,
        max_length=100
    )

    def __init__(self, interaction_id: str):
        super().__init__()
        self.interaction_id = interaction_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        contest_data = contest_builder.update_contest(
            self.interaction_id, 
            name=self.contest_name.value
        )
        
        embed = create_contest_setup_embed(contest_data)
        view = ContestBuilderView(self.interaction_id)
        view._update_remove_select(contest_data)
        
        await interaction.edit_original_response(embed=embed, view=view)

class SetDurationModal(discord.ui.Modal, title='Set Contest Duration'):
    duration = discord.ui.TextInput(
        label='Duration (in minutes)',
        placeholder='e.g., 120',
        style=discord.TextStyle.short,
        required=True
    )

    def __init__(self, interaction_id: str):
        super().__init__()
        self.interaction_id = interaction_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            duration_val = int(self.duration.value)
            if duration_val <= 0:
                raise ValueError("Duration must be positive")
        except ValueError:
            await interaction.response.send_message(
                "Duration must be a valid positive number of minutes.", 
                ephemeral=True
            )
            return
        
        await interaction.response.defer()
        
        contest_data = contest_builder.update_contest(
            self.interaction_id, 
            duration=duration_val
        )
        
        embed = create_contest_setup_embed(contest_data)
        view = ContestBuilderView(self.interaction_id)
        view._update_remove_select(contest_data)
        
        await interaction.edit_original_response(embed=embed, view=view)

class SetStartTimeModal(discord.ui.Modal, title='Set Contest Start Time'):
    start_minutes = discord.ui.TextInput(
        label='Start after how many minutes?',
        placeholder='e.g., 30 (for 30 minutes from now)',
        style=discord.TextStyle.short,
        required=True
    )

    def __init__(self, interaction_id: str):
        super().__init__()
        self.interaction_id = interaction_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            minutes = int(self.start_minutes.value)
            if minutes <= 0:
                raise ValueError("Minutes must be positive")
        except ValueError:
            await interaction.response.send_message(
                "Please enter a valid positive number of minutes.", 
                ephemeral=True
            )
            return
        
        await interaction.response.defer()
        
        # Calculate start time from current time + minutes
        start_time_dt = datetime.now() + timedelta(minutes=minutes)
        
        # Convert to Unix timestamp for Discord formatting
        unix_timestamp = int(start_time_dt.timestamp())
        
        contest_data = contest_builder.update_contest(
            self.interaction_id, 
            start_time=start_time_dt.isoformat(),
            start_minutes=minutes,  # Store for display
            unix_timestamp=unix_timestamp  # Store for Discord timestamp formatting
        )
        
        embed = create_contest_setup_embed(contest_data)
        view = ContestBuilderView(self.interaction_id)
        view._update_remove_select(contest_data)
        
        await interaction.edit_original_response(embed=embed, view=view)

class AddProblemBuilderModal(discord.ui.Modal, title='Add Problem to Contest'):
    problem_link = discord.ui.TextInput(
        label='Problem Link (Optional)',
        placeholder='https://codeforces.com/problemset/problem/1234/A',
        style=discord.TextStyle.short,
        required=False
    )
    
    tags = discord.ui.TextInput(
        label='Tags (Optional)',
        placeholder='e.g., dp,graphs,implementation',
        style=discord.TextStyle.short,
        required=False
    )
    
    rating = discord.ui.TextInput(
        label='Rating (Optional)',
        placeholder='e.g., 1200',
        style=discord.TextStyle.short,
        required=False
    )
    
    min_solved = discord.ui.TextInput(
        label='Min Solved Count (Optional)',
        placeholder='e.g., 1000',
        style=discord.TextStyle.short,
        required=False
    )

    def __init__(self, interaction_id: str):
        super().__init__()
        self.interaction_id = interaction_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        # Validate that at least one field is provided
        if not any([
            self.problem_link.value.strip(),
            self.tags.value.strip(),
            self.rating.value.strip(),
            self.min_solved.value.strip()
        ]):
            await interaction.followup.send(
                "Please provide at least one field (Problem Link, Tags, Rating, or Min Solved).", 
                ephemeral=True
            )
            return
        
        contest_data = contest_builder.get_contest(self.interaction_id)
        if not contest_data:
            await interaction.followup.send("Contest session not found.", ephemeral=True)
            return
        
        session = getattr(interaction.client, 'session', aiohttp.ClientSession())
        
        # If problem link is provided, validate and use it
        if self.problem_link.value.strip():
            link = self.problem_link.value.strip()
            if not self._validate_codeforces_link(link):
                await interaction.followup.send(
                    "Invalid Codeforces problem link format.", 
                    ephemeral=True
                )
                return
            
            # Try to get problem name from API
            problem_name = await self._get_problem_name(session, link)
            display_name = problem_name if problem_name else self._extract_problem_code(link)
            
            problem_data = {
                'link': link,
                'display_name': display_name,
                'criteria': 'Direct Link'
            }
        else:
            # Generate random problem with criteria
            tags_val = self.tags.value.strip() or "random"
            rating_val = self.rating.value.strip() or "random"
            min_solved_val = None
            
            if self.min_solved.value.strip():
                try:
                    min_solved_val = int(self.min_solved.value.strip())
                except ValueError:
                    await interaction.followup.send(
                        "Min Solved must be a valid number.", 
                        ephemeral=True
                    )
                    return
            
            # Fetch random problem
            problem_data_api = await get_random_problem(session, tags_val, rating_val, min_solved_val)
            if not problem_data_api or not problem_data_api.get("link"):
                await interaction.followup.send(
                    "Could not find a problem matching your criteria. Please try different filters.", 
                    ephemeral=True
                )
                return
            
            # Create display criteria
            criteria_parts = []
            if tags_val != "random":
                criteria_parts.append(f"[{tags_val}]")
            if rating_val != "random":
                criteria_parts.append(f"Rating: {rating_val}")
            if min_solved_val:
                criteria_parts.append(f"Min Solved: >{min_solved_val}")
            
            criteria_display = " ".join(criteria_parts) if criteria_parts else "Random"
            
            problem_data = {
                'link': problem_data_api['link'],
                'display_name': problem_data_api.get('name', self._extract_problem_code(problem_data_api['link'])),
                'criteria': f"Random {criteria_display}" if criteria_parts else "Random"
            }
        
        # Add problem to contest
        contest_data['problems'].append(problem_data)
        contest_builder.update_contest(self.interaction_id, problems=contest_data['problems'])
        
        # Update embed
        embed = create_contest_setup_embed(contest_data)
        view = ContestBuilderView(self.interaction_id)
        view._update_remove_select(contest_data)
        
        await interaction.edit_original_response(embed=embed, view=view)

    def _validate_codeforces_link(self, link: str) -> bool:
        """Validate Codeforces problem link format"""
        patterns = [
            r'https?://codeforces\.com/problemset/problem/\d+/[A-Z]\d*',
            r'https?://codeforces\.com/contest/\d+/problem/[A-Z]\d*',
            r'https?://codeforces\.com/gym/\d+/problem/[A-Z]\d*'
        ]
        
        for pattern in patterns:
            if re.match(pattern, link):
                return True
        return False
    
    def _extract_problem_code(self, link: str) -> str:
        """Extract problem code from Codeforces link"""
        try:
            parts = link.strip('/').split('/')
            contest_id = parts[-2]
            problem_index = parts[-1]
            return f"{contest_id}{problem_index}"
        except:
            return "Unknown Problem"
    
    async def _get_problem_name(self, session, link: str) -> Optional[str]:
        """Try to get problem name from Codeforces API"""
        try:
            parts = link.strip('/').split('/')
            contest_id = parts[-2]
            problem_index = parts[-1]
            
            async with session.get(f"https://codeforces.com/api/problemset.problems") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('status') == 'OK':
                        for problem in data['result']['problems']:
                            if str(problem['contestId']) == contest_id and problem['index'] == problem_index:
                                return f"{contest_id}{problem_index} - {problem['name']}"
        except:
            pass
        return None

class ContestBuilderView(discord.ui.View):
    def __init__(self, interaction_id: str):
        super().__init__(timeout=300)  # 5 minute timeout
        self.interaction_id = interaction_id

    @discord.ui.button(label='Set Name', style=discord.ButtonStyle.secondary, emoji='📝')
    async def set_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = SetNameModal(self.interaction_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label='Set Duration', style=discord.ButtonStyle.secondary, emoji='⏱️')
    async def set_duration(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = SetDurationModal(self.interaction_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label='Set Start After', style=discord.ButtonStyle.secondary, emoji='📅')
    async def set_start_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = SetStartTimeModal(self.interaction_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label='Add Problem', style=discord.ButtonStyle.primary, emoji='➕')
    async def add_problem(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AddProblemBuilderModal(self.interaction_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label='Finish & Create', style=discord.ButtonStyle.success, emoji='✅')
    async def finish_create(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        contest_data = contest_builder.get_contest(self.interaction_id)
        if not contest_data:
            await interaction.followup.send("Contest session not found.", ephemeral=True)
            return
        
        # Validate required fields
        if not contest_data.get('duration'):
            await interaction.followup.send("Please set the contest duration before creating.", ephemeral=True)
            return
        
        if not contest_data.get('start_time'):
            await interaction.followup.send("Please set the contest start time before creating.", ephemeral=True)
            return
        
        if not contest_data.get('problems'):
            await interaction.followup.send("Please add at least one problem before creating.", ephemeral=True)
            return
        
        try:
            # Create contest in database
            new_id = await create_bot_contest(
                contest_data['name'], 
                contest_data['duration'], 
                contest_data['start_time'],
                contest_data.get('unix_timestamp')
            )
            
            # Add problems to contest
            problem_links = [p['link'] for p in contest_data['problems']]
            await update_contest_problems(new_id, problem_links)
            
            # Update embed to show completion
            embed = create_contest_completed_embed(contest_data, new_id)
            
            # Disable all buttons
            for item in self.children:
                item.disabled = True
            
            await interaction.edit_original_response(embed=embed, view=self)
            
            # Send announcement
            await self._send_announcement(interaction, contest_data, new_id)
            
            # Clean up session
            contest_builder.delete_contest(self.interaction_id)
            
        except Exception as e:
            await interaction.followup.send(f"Error creating contest: {str(e)}", ephemeral=True)

    async def _send_announcement(self, interaction: discord.Interaction, contest_data: Dict, contest_id: int):
        """Send contest announcement to the announcement channel"""
        announcement_channel = interaction.client.get_channel(ANNOUNCEMENT_CHANNEL_ID)
        if not announcement_channel:
            return
        
        try:
            participant_role = interaction.guild.get_role(PARTICIPANT_ROLE_ID)
            participant_count = await get_contest_participant_count(contest_id)
            # Use Discord timestamp if available, otherwise fallback to formatted time
            if contest_data.get('unix_timestamp'):
                unix_timestamp = contest_data['unix_timestamp']
                starts_at_text = f"<t:{unix_timestamp}:R>"
            else:
                start_time_dt = datetime.fromisoformat(contest_data['start_time'])
                starts_at_text = start_time_dt.strftime('%d/%m/%Y %H:%M')

            embed = discord.Embed(
                title=f"📢 New Contest: {contest_data['name']}",
                description="A new coding challenge has been scheduled! Sharpen your skills and compete 🚀",
                color=discord.Color.gold()
            )

            embed.add_field(name="🕒 Starts At", value=starts_at_text, inline=True)
            embed.add_field(name="⏳ Duration", value=f"{contest_data['duration']} mins", inline=True)
            embed.add_field(name="📘 Problems", value=f"{len(contest_data.get('problems', []))}", inline=True)

            embed.set_footer(text=f"Contest ID: {contest_id} • May the best coder win! 💡")

            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(
                label="🔥 Join Contest", 
                style=discord.ButtonStyle.success, 
                custom_id=f"join_{contest_id}"
            ))

            await announcement_channel.send(
                content=f"{participant_role.mention if participant_role else 'Participants'}",
                embed=embed,
                view=view
            )
        except Exception as e:
            print(f"Error sending announcement: {e}")

    @discord.ui.select(
        placeholder="Remove a problem...",
        min_values=0,
        max_values=1,
        row=1
    )
    async def remove_problem(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not select.values:
            return
        
        await interaction.response.defer()
        
        problem_index = int(select.values[0])
        contest_data = contest_builder.get_contest(self.interaction_id)
        
        if contest_data and 0 <= problem_index < len(contest_data['problems']):
            removed_problem = contest_data['problems'].pop(problem_index)
            contest_builder.update_contest(self.interaction_id, problems=contest_data['problems'])
            
            # Update embed and view
            embed = create_contest_setup_embed(contest_data)
            view = ContestBuilderView(self.interaction_id)
            view._update_remove_select(contest_data)
            
            await interaction.edit_original_response(embed=embed, view=view)

    def _update_remove_select(self, contest_data: Dict):
        """Update the remove problem select menu options"""
        if contest_data.get('problems'):
            self.remove_problem.options = [
                discord.SelectOption(
                    label=f"Remove: {problem['display_name'][:90]}", 
                    value=str(i),
                    description=problem['criteria'][:100] if len(problem['criteria']) <= 100 else problem['criteria'][:97] + "..."
                )
                for i, problem in enumerate(contest_data['problems'])
            ]
            self.remove_problem.max_values = 1
        else:
            # Remove the select menu if no problems
            try:
                self.remove_item(self.remove_problem)
            except ValueError:
                pass  # Already removed

    async def on_timeout(self):
        """Clean up when view times out"""
        contest_builder.delete_contest(self.interaction_id)

def create_contest_setup_embed(contest_data: Dict) -> discord.Embed:
    """Create the contest setup embed"""
    embed = discord.Embed(
        title="🔧 Contest Setup (In Progress)",
        color=discord.Color.orange()
    )
    
    # Basic info
    embed.add_field(
        name="Contest Name", 
        value=contest_data.get('name', 'Untitled Contest'), 
        inline=True
    )
    
    duration_text = f"{contest_data['duration']} minutes" if contest_data.get('duration') else "Not set"
    embed.add_field(name="Duration", value=duration_text, inline=True)
    
    # Start time with Discord timestamp formatting
    if contest_data.get('unix_timestamp'):
        unix_timestamp = contest_data['unix_timestamp']
        # Discord timestamp formats: <t:timestamp:format>
        # F = Full date/time, R = Relative time
        start_time_text = f"<t:{unix_timestamp}:R>"
        
        # Add minutes/hours display if available
        if contest_data.get('start_minutes'):
            minutes = contest_data['start_minutes']
            if minutes >= 60:
                hours = minutes / 60
                if hours == int(hours):
                    time_display = f"\n*Set to start in {int(hours)} hour{'s' if hours != 1 else ''}*"
                else:
                    time_display = f"\n*Set to start in {hours:.1f} hours*"
            else:
                time_display = f"\n*Set to start in {minutes} minute{'s' if minutes != 1 else ''}*"
            start_time_text += time_display
    elif contest_data.get('start_time'):
        try:
            start_time_dt = datetime.fromisoformat(contest_data['start_time'])
            start_time_text = start_time_dt.strftime("%H:%M")
        except:
            start_time_text = "Invalid format"
    else:
        start_time_text = "Not set"
    
    embed.add_field(name="Start Time", value=start_time_text, inline=False)
    
    # Problems with links
    problems = contest_data.get('problems', [])
    if problems:
        problems_text = "\n".join([
            f"{i+1}. [{problem['display_name']}]({problem['link']})"
            + (f"\n   └ *{problem['criteria']}*" if problem['criteria'] != 'Direct Link' else "")
            for i, problem in enumerate(problems)
        ])
    else:
        problems_text = "No problems added yet"
    
    embed.add_field(name=f"Problems ({len(problems)})", value=problems_text, inline=False)
    
    return embed

def create_contest_completed_embed(contest_data: Dict, contest_id: int) -> discord.Embed:
    """Create the contest completion embed"""
    embed = discord.Embed(
        title="✅ Contest Created Successfully!",
        color=discord.Color.green()
    )
    
    embed.add_field(name="Contest ID", value=str(contest_id), inline=True)
    embed.add_field(name="Name", value=contest_data['name'], inline=True)
    embed.add_field(name="Duration", value=f"{contest_data['duration']} minutes", inline=True)
    
    try:
        start_time_dt = datetime.fromisoformat(contest_data['start_time'])
        start_time_text = start_time_dt.strftime("%d/%m/%Y %H:%M")
    except:
        start_time_text = contest_data['start_time']
    
    embed.add_field(name="Start Time", value=start_time_text, inline=False)
    embed.add_field(name="Problems", value=str(len(contest_data['problems'])), inline=True)
    
    return embed

# Add this Cog class at the end of the file
class ContestBuilderCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

async def setup(bot):
    await bot.add_cog(ContestBuilderCog(bot))
