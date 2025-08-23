import re
from typing import Dict, Optional
import discord
from discord.ext import commands
import aiohttp
from datetime import datetime, timedelta
from utility.random_problems import get_random_problem
from utility.db_helpers import get_contest_participant_count, update_contest_problems, create_bot_contest
from utility.config_manager import get_cp_role_id, get_contest_channel_id


class ContestBuilder:
    """Temporary storage for contest data while building"""
    def __init__(self):
        self.contests: Dict[str, Dict] = {}  # key: interaction_id, value: contest data
    
    def create_contest(self, interaction_id: str) -> Dict:
        """Create a new contest builder session"""
        self.contests[interaction_id] = {
            'name': 'Untitled Contest',
            'duration': None,
            'start_time': None,
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
        
        start_time_dt = datetime.now() + timedelta(minutes=minutes)
        unix_timestamp = int(start_time_dt.timestamp())
        
        contest_data = contest_builder.update_contest(
            self.interaction_id, 
            start_time=start_time_dt.isoformat(),
            start_minutes=minutes,
            unix_timestamp=unix_timestamp
        )
        
        embed = create_contest_setup_embed(contest_data)
        view = ContestBuilderView(self.interaction_id)
        view._update_remove_select(contest_data)
        
        await interaction.edit_original_response(embed=embed, view=view)

class AddProblemBuilderModal(discord.ui.Modal, title='Add Problem to Contest'):
    problem_link = discord.ui.TextInput(label='Problem Link (Optional)', placeholder='https://codeforces.com/problemset/problem/1234/A', style=discord.TextStyle.short, required=False)
    tags = discord.ui.TextInput(label='Tags (Optional)', placeholder='e.g., dp,graphs,implementation', style=discord.TextStyle.short, required=False)
    rating = discord.ui.TextInput(label='Rating (Optional)', placeholder='e.g., 1200', style=discord.TextStyle.short, required=False)
    min_solved = discord.ui.TextInput(label='Min Solved Count (Optional)', placeholder='e.g., 1000', style=discord.TextStyle.short, required=False)

    def __init__(self, interaction_id: str):
        super().__init__()
        self.interaction_id = interaction_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        if not any([self.problem_link.value.strip(), self.tags.value.strip(), self.rating.value.strip(), self.min_solved.value.strip()]):
            await interaction.followup.send("Please provide at least one field.", ephemeral=True)
            return
        
        contest_data = contest_builder.get_contest(self.interaction_id)
        if not contest_data:
            await interaction.followup.send("Contest session not found.", ephemeral=True)
            return
        
        session = getattr(interaction.client, 'session', aiohttp.ClientSession())
        
        if self.problem_link.value.strip():
            link = self.problem_link.value.strip()
            if not self._validate_codeforces_link(link):
                await interaction.followup.send("Invalid Codeforces problem link format.", ephemeral=True)
                return
            
            problem_name = await self._get_problem_name(session, link)
            display_name = problem_name if problem_name else self._extract_problem_code(link)
            
            problem_data = {'link': link, 'display_name': display_name, 'criteria': 'Direct Link'}
        else:
            tags_val = self.tags.value.strip() or "random"
            rating_val = self.rating.value.strip() or "random"
            min_solved_val = int(self.min_solved.value.strip()) if self.min_solved.value.strip().isdigit() else None
            
            problem_data_api = await get_random_problem(session, tags_val, rating_val, min_solved_val)
            if not problem_data_api or not problem_data_api.get("link"):
                await interaction.followup.send("Could not find a problem matching your criteria.", ephemeral=True)
                return
            
            criteria_parts = []
            if tags_val != "random": criteria_parts.append(f"[{tags_val}]")
            if rating_val != "random": criteria_parts.append(f"Rating: {rating_val}")
            if min_solved_val: criteria_parts.append(f"Min Solved: >{min_solved_val}")
            
            criteria_display = " ".join(criteria_parts) if criteria_parts else "Random"
            
            problem_data = {
                'link': problem_data_api['link'],
                'display_name': problem_data_api.get('name', self._extract_problem_code(problem_data_api['link'])),
                'criteria': f"Random {criteria_display}"
            }
        
        contest_data['problems'].append(problem_data)
        contest_builder.update_contest(self.interaction_id, problems=contest_data['problems'])
        
        embed = create_contest_setup_embed(contest_data)
        view = ContestBuilderView(self.interaction_id)
        view._update_remove_select(contest_data)
        
        await interaction.edit_original_response(embed=embed, view=view)

    def _validate_codeforces_link(self, link: str) -> bool:
        pattern = r'https?://codeforces\.com/(?:problemset/problem|contest|gym)/\d+/problem/[A-Z]\d*'
        return bool(re.match(pattern, link))
    
    def _extract_problem_code(self, link: str) -> str:
        match = re.search(r'/(\d+)/problem/([A-Z]\d*)', link)
        return f"{match.group(1)}{match.group(2)}" if match else "Unknown Problem"
    
    async def _get_problem_name(self, session, link: str) -> Optional[str]:
        try:
            match = self._extract_problem_code(link)
            contest_id, problem_index = re.match(r'(\d+)([A-Z]\d*)', match).groups()
            
            async with session.get("https://codeforces.com/api/problemset.problems") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('status') == 'OK':
                        for problem in data['result']['problems']:
                            if str(problem['contestId']) == contest_id and problem['index'] == problem_index:
                                return f"{contest_id}{problem_index} - {problem['name']}"
        except Exception:
            pass
        return None

class ContestBuilderView(discord.ui.View):
    def __init__(self, interaction_id: str):
        super().__init__(timeout=300)
        self.interaction_id = interaction_id

    @discord.ui.button(label='Set Name', style=discord.ButtonStyle.secondary, emoji='📝')
    async def set_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetNameModal(self.interaction_id))

    @discord.ui.button(label='Set Duration', style=discord.ButtonStyle.secondary, emoji='⏱️')
    async def set_duration(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetDurationModal(self.interaction_id))

    @discord.ui.button(label='Set Start After', style=discord.ButtonStyle.secondary, emoji='📅')
    async def set_start_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetStartTimeModal(self.interaction_id))

    @discord.ui.button(label='Add Problem', style=discord.ButtonStyle.primary, emoji='➕')
    async def add_problem(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddProblemBuilderModal(self.interaction_id))

    @discord.ui.button(label='Finish & Create', style=discord.ButtonStyle.success, emoji='✅')
    async def finish_create(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        contest_data = contest_builder.get_contest(self.interaction_id)
        if not contest_data:
            await interaction.followup.send("Your contest creation session has expired or was not found. Please start over.", ephemeral=True)
            return
        
        # MODIFIED: Validate required fields individually for clearer feedback
        if not contest_data.get('duration'):
            await interaction.followup.send("Please set the contest duration before creating.", ephemeral=True)
            return
        
        if not contest_data.get('start_time'):
            await interaction.followup.send("Please set the contest start time before creating.", ephemeral=True)
            return
        
        if not contest_data.get('problems'): # An empty list is falsy
            await interaction.followup.send("Please add at least one problem before creating.", ephemeral=True)
            return
        
        try:
            new_id = await create_bot_contest(
                contest_data['name'], 
                contest_data['duration'], 
                contest_data['start_time'],
                contest_data.get('unix_timestamp'),
                guild_id=interaction.guild.id
            )
            
            problem_links = [p['link'] for p in contest_data['problems']]
            await update_contest_problems(new_id, problem_links)
            
            embed = create_contest_completed_embed(contest_data, new_id)
            
            for item in self.children:
                item.disabled = True
            
            await interaction.edit_original_response(embed=embed, view=self)
            await self._send_announcement(interaction, contest_data, new_id)
            contest_builder.delete_contest(self.interaction_id)
            
        except Exception as e:
            await interaction.followup.send(f"Error creating contest: {str(e)}", ephemeral=True)

    async def _send_announcement(self, interaction: discord.Interaction, contest_data: Dict, contest_id: int):
        contest_channel_id = await get_contest_channel_id(interaction.guild.id)
        participant_role_id = await get_cp_role_id(interaction.guild.id)

        if not contest_channel_id:
            await interaction.followup.send("⚠️ Announcement channel not set. Please use `/setchannels`.", ephemeral=True)
            return
        
        contest_channel = interaction.client.get_channel(contest_channel_id)
        if not contest_channel:
            await interaction.followup.send("⚠️ Announcement channel not found.", ephemeral=True)
            return
        
        try:
            participant_role = interaction.guild.get_role(participant_role_id) if participant_role_id else None
            participant_count = await get_contest_participant_count(contest_id)
            
            if contest_data.get('unix_timestamp'):
                starts_at_text = f"<t:{contest_data['unix_timestamp']}:F> (<t:{contest_data['unix_timestamp']}:R>)"
            else:
                starts_at_text = datetime.fromisoformat(contest_data['start_time']).strftime('%d/%m/%Y %H:%M')
            
            embed = discord.Embed(
                title=f"📢 New Contest: {contest_data['name']}",
                description=(
                    f"A new contest has been scheduled!\n\n"
                    f"**Starts at:** {starts_at_text}\n"
                    f"**Duration:** {contest_data['duration']} minutes\n"
                    f"**Problems:** {len(contest_data.get('problems', []))}\n"
                    f"**Participants:** {participant_count}"
                ),
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Contest ID: {contest_id}")
            
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(label="Join Contest", style=discord.ButtonStyle.success, custom_id=f"join_{contest_id}"))
            
            await contest_channel.send(
                content=f"{participant_role.mention if participant_role else 'Participants'}", 
                embed=embed, 
                view=view
            )
        except Exception as e:
            print(f"Error sending announcement: {e}")

    @discord.ui.select(placeholder="Remove a problem...", min_values=1, max_values=1, row=1)
    async def remove_problem(self, interaction: discord.Interaction, select: discord.ui.Select):
        await interaction.response.defer()
        
        problem_index = int(select.values[0])
        contest_data = contest_builder.get_contest(self.interaction_id)
        
        if contest_data and 0 <= problem_index < len(contest_data['problems']):
            contest_data['problems'].pop(problem_index)
            contest_builder.update_contest(self.interaction_id, problems=contest_data['problems'])
            
            embed = create_contest_setup_embed(contest_data)
            view = ContestBuilderView(self.interaction_id)
            view._update_remove_select(contest_data)
            
            await interaction.edit_original_response(embed=embed, view=view)

    def _update_remove_select(self, contest_data: Dict):
        if contest_data.get('problems'):
            self.remove_problem.options = [
                discord.SelectOption(
                    label=f"Remove: {problem['display_name'][:90]}", 
                    value=str(i),
                    description=problem['criteria'][:100]
                )
                for i, problem in enumerate(contest_data['problems'])
            ]
            self.remove_problem.disabled = False
        else:
            self.remove_problem.options = [discord.SelectOption(label="No problems to remove", value="-1")]
            self.remove_problem.disabled = True

    async def on_timeout(self):
        contest_builder.delete_contest(self.interaction_id)

def create_contest_setup_embed(contest_data: Dict) -> discord.Embed:
    embed = discord.Embed(title="🔧 Contest Setup (In Progress)", color=discord.Color.orange())
    embed.add_field(name="Contest Name", value=contest_data.get('name', 'Untitled Contest'), inline=True)
    embed.add_field(name="Duration", value=f"{contest_data['duration']} minutes" if contest_data.get('duration') else "Not set", inline=True)
    
    if contest_data.get('unix_timestamp'):
        start_time_text = f"<t:{contest_data['unix_timestamp']}:F> (<t:{contest_data['unix_timestamp']}:R>)"
    else:
        start_time_text = "Not set"
    
    embed.add_field(name="Start Time", value=start_time_text, inline=False)
    
    problems = contest_data.get('problems', [])
    problems_text = "\n".join([
        f"{i+1}. [{p['display_name']}]({p['link']})" + (f"\n   └ *{p['criteria']}*" if p['criteria'] != 'Direct Link' else "")
        for i, p in enumerate(problems)
    ]) or "No problems added yet"
    
    embed.add_field(name=f"Problems ({len(problems)})", value=problems_text, inline=False)
    return embed

def create_contest_completed_embed(contest_data: Dict, contest_id: int) -> discord.Embed:
    embed = discord.Embed(title="✅ Contest Created Successfully!", color=discord.Color.green())
    embed.add_field(name="Contest ID", value=str(contest_id), inline=True)
    embed.add_field(name="Name", value=contest_data['name'], inline=True)
    embed.add_field(name="Duration", value=f"{contest_data['duration']} minutes", inline=True)
    
    start_time_text = f"<t:{contest_data['unix_timestamp']}:F>" if contest_data.get('unix_timestamp') else "Not set"
    embed.add_field(name="Start Time", value=start_time_text, inline=False)
    embed.add_field(name="Problems", value=str(len(contest_data['problems'])), inline=True)
    
    return embed

class ContestBuilderCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

async def setup(bot):
    await bot.add_cog(ContestBuilderCog(bot))
