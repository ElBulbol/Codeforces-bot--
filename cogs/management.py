import discord
from discord.ext import commands
from discord import app_commands

ROLE_CP = "CP"
ROLE_MOD = "MOD"
CHANNEL_ID_CONTEST = 1404857696666128405

class Management(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="assign_role", description="Assigns CP role to a member.")
    @app_commands.checks.has_role(ROLE_MOD)
    @app_commands.checks.cooldown(1, 5, key = lambda i: (i.user.id))
    async def assign_role(self, interaction: discord.Interaction, member: discord.Member):
        """Assigns CP role to a member."""
        cp_role = discord.utils.get(interaction.guild.roles, name=ROLE_CP)
        if not cp_role:
            await interaction.response.send_message("CP role not found.", ephemeral=True)
            return

        await member.add_roles(cp_role)
        await interaction.response.send_message(f"{member.mention} has been assigned the {ROLE_CP} role.")

    @app_commands.command(name="remove_role", description="Removes CP role from a member.")
    @app_commands.checks.has_role(ROLE_MOD)
    @app_commands.checks.cooldown(1, 5, key = lambda i: (i.user.id))
    async def remove_role(self, interaction: discord.Interaction, member: discord.Member):
        """Removes CP role from a member."""
        cp_role = discord.utils.get(interaction.guild.roles, name=ROLE_CP)
        if not cp_role:
            await interaction.response.send_message("CP role not found.", ephemeral=True)
            return

        if cp_role not in member.roles:
            await interaction.response.send_message(f"{member.mention} does not have the {ROLE_CP} role.", ephemeral=True)
            return

        await member.remove_roles(cp_role)
        await interaction.response.send_message(f"{member.mention} has been removed from the {ROLE_CP} role.")

    @app_commands.command(name="contest_notify", description="Sends a notification about a contest.")
    @app_commands.checks.has_role(ROLE_MOD)
    @app_commands.checks.cooldown(1, 5, key = lambda i: (i.user.id))
    async def contest_notify(self, interaction: discord.Interaction, message: str):
        """Send a private message to all CP members and mention CP in a specific channel."""
        await interaction.response.defer(ephemeral=True)
        cp_role = discord.utils.get(interaction.guild.roles, name=ROLE_CP)
        if not cp_role:
            await interaction.followup.send("CP role not found.")
            return

        for member in cp_role.members:
            try:
                await member.send(message)
            except discord.Forbidden:
                print(f"Could not send DM to {member.name}")
            except Exception as e:
                print(f"An error occurred while sending DM to {member.name}: {e}")

        channel = self.bot.get_channel(CHANNEL_ID_CONTEST)
        if channel:
            await channel.send(f"{cp_role.mention} {message}")
            await interaction.followup.send("Notification sent successfully!")
        else:
            await interaction.followup.send(f"Contest channel with ID {CHANNEL_ID_CONTEST} not found.")

    # This local error handler is no longer needed as there is a global one in bot.py
    # @assign_role.error
    # ... (and the rest of the error handler)


async def setup(bot: commands.Bot):
    await bot.add_cog(Management(bot))
