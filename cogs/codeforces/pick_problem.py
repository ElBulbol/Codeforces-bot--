import discord
from discord.ext import commands
from discord import app_commands

from utility.random_problems import get_random_problem

class PickProblem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="pick_problem", description="Pick a Codeforces problem by tags and optional rating.")
    @app_commands.describe(
        tags="Problem tags, comma-separated (e.g., 'dp,graphs'). Leave empty or use 'random' for a random tag.",
        rating="The problem rating (e.g., 800). Leave empty or use 'random' for a random rating.",
        min_solved="Minimum number of users who solved the problem (e.g., 100)."
    )
    @app_commands.checks.cooldown(1, 5, key = lambda i: (i.user.id))
    async def pick_problem(self, interaction: discord.Interaction, tags: str = None, rating: str = None, min_solved: str = None):
        """Pick a Codeforces problem by tags and optional rating (use 'random' for rating)."""
        await interaction.response.defer()
        
        # Default to random if no tags are provided
        type_of_problem = tags if tags else "random"
        
        problem = await get_random_problem(self.bot.session, type_of_problem=type_of_problem, rating=rating, min_solved=min_solved)
        
        if not problem:
            # Provide more helpful error message
            if tags and rating and min_solved:
                await interaction.followup.send(f"No problem found for tags '{type_of_problem}' with rating '{rating}' and min solved '{min_solved}'. Try different criteria.")
            elif tags and rating:
                await interaction.followup.send(f"No problem found for tags '{type_of_problem}' with rating '{rating}'. Try different tags or rating.")
            elif tags and min_solved:
                await interaction.followup.send(f"No problem found for tags '{type_of_problem}' with min solved '{min_solved}'. Try different criteria.")
            elif rating and min_solved:
                await interaction.followup.send(f"No problem found with rating '{rating}' and min solved '{min_solved}'. Try different criteria.")
            elif tags:
                await interaction.followup.send(f"No problem found for tags '{type_of_problem}'. Please check if the tags are valid.")
            elif rating:
                await interaction.followup.send(f"No problem found with rating '{rating}'. Try a different rating or leave it empty.")
            elif min_solved:
                await interaction.followup.send(f"No problem found with min solved '{min_solved}'. Try a lower number or leave it empty.")
            else:
                await interaction.followup.send("Unable to find any problems. Please try again later.")
            return

        embed = discord.Embed(
            title=problem["name"],
            url=problem["link"],
            description=f"**Tags:** {', '.join(problem['tags'])}\n**Rating:** {problem['rating']}\n**Solved by:** {problem['solvedCount']:,}",
            color=discord.Color.blue()
        )
        await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(PickProblem(bot))