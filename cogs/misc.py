import discord
from discord.ext import commands
from discord import app_commands

class Misc(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Shows a list of all available commands.")
    @app_commands.checks.cooldown(1, 5, key = lambda i: (i.user.id))
    async def help(self, interaction: discord.Interaction):
        """Shows a list of all available commands."""
        embed = discord.Embed(
            title="Help Desk",
            description="Here is a list of available commands:",
            color=discord.Color.blurple()
        )
        
        commands_list = sorted(self.bot.tree.get_commands(), key=lambda c: c.name)
        for command in commands_list:
            embed.add_field(name=f"/{command.name}", value=command.description, inline=False)
        
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Misc(bot))
