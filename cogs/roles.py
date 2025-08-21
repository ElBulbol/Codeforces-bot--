import discord
from discord.ext import commands
from discord import app_commands
from utility.constants import CP_ROLE_NAME, MOD_ROLE_NAME, CONTEST_CHANNEL_ID


class Management(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="assign_role", description="Assigns CP role to a member.")
    @app_commands.checks.has_role(MOD_ROLE_NAME)
    @app_commands.checks.cooldown(1, 5, key = lambda i: (i.user.id))
    async def assign_role(self, interaction: discord.Interaction, member: discord.Member):
        """Assigns CP role to a member."""
        cp_role = discord.utils.get(interaction.guild.roles, name=CP_ROLE_NAME)
        if not cp_role:
            await interaction.response.send_message("CP role not found.", ephemeral=True)
            return

        await member.add_roles(cp_role)
        await interaction.response.send_message(f"{member.mention} has been assigned the {CP_ROLE_NAME} role.")

    @app_commands.command(name="remove_role", description="Removes CP role from a member.")
    @app_commands.checks.has_role(MOD_ROLE_NAME)
    @app_commands.checks.cooldown(1, 5, key = lambda i: (i.user.id))
    async def remove_role(self, interaction: discord.Interaction, member: discord.Member):
        """Removes CP role from a member."""
        cp_role = discord.utils.get(interaction.guild.roles, name=CP_ROLE_NAME)
        if not cp_role:
            await interaction.response.send_message("CP role not found.", ephemeral=True)
            return

        if cp_role not in member.roles:
            await interaction.response.send_message(f"{member.mention} does not have the {CP_ROLE_NAME} role.", ephemeral=True)
            return

        await member.remove_roles(cp_role)
        await interaction.response.send_message(f"{member.mention} has been removed from the {CP_ROLE_NAME} role.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Management(bot))
