import discord
from discord.ext import commands
from discord import app_commands
from utility.config_manager import get_cp_role_id, get_mod_role_id


class Management(commands.GroupCog, name = "role"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="assign", description="Assigns CP role to a member.")
    @app_commands.checks.cooldown(1, 5, key = lambda i: (i.user.id))
    async def assign_role(self, interaction: discord.Interaction, member: discord.Member):
        """Assigns CP role to a member."""
        mod_role_id = await get_mod_role_id(interaction.guild.id)
        if not mod_role_id or not discord.utils.get(interaction.user.roles, id=mod_role_id):
            await interaction.followup.send("You do not have permission to use this command.", ephemeral=True)
            return

        cp_role_id = await get_cp_role_id(interaction.guild.id)
        if not cp_role_id:
            await interaction.followup.send("The CP role has not been configured for this server. Please ask an admin to run `/setroles`.", ephemeral=True)
            return

        cp_role = interaction.guild.get_role(cp_role_id)
        if not cp_role:
            await interaction.followup.send("The configured CP role was not found. It may have been deleted.", ephemeral=True)
            return

        await member.add_roles(cp_role)
        await interaction.response.send_message(f"{member.mention} has been assigned the {cp_role.name} role.")

    @app_commands.command(name="remove", description="Removes CP role from a member.")
    @app_commands.checks.cooldown(1, 5, key = lambda i: (i.user.id))
    async def remove_role(self, interaction: discord.Interaction, member: discord.Member):
        """Removes CP role from a member."""
        mod_role_id = await get_mod_role_id(interaction.guild.id)
        if not mod_role_id or not discord.utils.get(interaction.user.roles, id=mod_role_id):
            await interaction.followup.send("You do not have permission to use this command.", ephemeral=True)
            return

        cp_role_id = await get_cp_role_id(interaction.guild.id)
        if not cp_role_id:
            await interaction.followup.send("The CP role has not been configured for this server. Please ask an admin to run `/setroles`.", ephemeral=True)
            return

        cp_role = interaction.guild.get_role(cp_role_id)
        if not cp_role:
            await interaction.followup.send("The configured CP role was not found. It may have been deleted.", ephemeral=True)
            return

        await member.remove_roles(cp_role)
        await interaction.response.send_message(f"{member.mention} has been removed from the {cp_role.name} role.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Management(bot))
