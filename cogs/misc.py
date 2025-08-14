import discord
from discord.ext import commands
from discord import app_commands

eyad = 821524911507374100

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

    @app_commands.command(name="hello", description="Say hello to the bot.")
    @app_commands.checks.cooldown(1, 5, key = lambda i: (i.user.id))
    async def hello(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"hello {interaction.user.mention} !")

    @app_commands.command(name="hello_eyad", description="Say hello to Eyad.")
    @app_commands.checks.cooldown(1, 5, key = lambda i: (i.user.id))
    async def hello_eyad(self, interaction: discord.Interaction):
        member = interaction.guild.get_member(eyad)
        if not member:
            try:
                member = await interaction.guild.fetch_member(eyad)
            except discord.NotFound:
                await interaction.response.send_message("Could not find Eyad in this server.", ephemeral=True)
                return
        
        await interaction.response.send_message(f"hello {member.mention} !")

async def setup(bot: commands.Bot):
    await bot.add_cog(Misc(bot))
