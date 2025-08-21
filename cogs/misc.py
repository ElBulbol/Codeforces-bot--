import discord
from discord.ext import commands
from discord import app_commands
from utility.db_helpers import init_db

class ResetDatabaseModal(discord.ui.Modal, title="Reset Database"):
    password = discord.ui.TextInput(
        label="Enter password to reset database",
        style=discord.TextStyle.short,
        min_length=1,
        max_length=32,
        required=True
    )

    def __init__(self, interaction: discord.Interaction):
        super().__init__()
        self.interaction = interaction

    async def on_submit(self, interaction: discord.Interaction):
        if self.password.value == "secret":
            await init_db()
            await interaction.response.send_message("✅ Database has been reset successfully.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Incorrect password. Database reset aborted.", ephemeral=True)

def has_admin_role():   
    async def predicate(interaction: discord.Interaction):
        return any(role.id == 1404742889681981440 for role in interaction.user.roles)
    return app_commands.check(predicate)

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
            embed.add_field(name=problem_name, value=f"[{problem_name}]({problem_link})", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="init", description="check the connection to the bot")
    @app_commands.checks.cooldown(1, 5, key = lambda i: (i.user.id))
    async def hello(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"I am with you sir{interaction.user.mention} !")

    @app_commands.command(name="rest_database", description="Reset and rebuild the database (admin only)")
    @has_admin_role()
    @app_commands.checks.cooldown(1, 10, key=lambda i: (i.user.id))
    async def rest_database(self, interaction: discord.Interaction):
        """Opens a modal to enter password and resets the database if correct."""
        await interaction.response.send_modal(ResetDatabaseModal(interaction))

async def setup(bot: commands.Bot):
    await bot.add_cog(Misc(bot))
