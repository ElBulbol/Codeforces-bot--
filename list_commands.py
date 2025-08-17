import discord
from discord.ext import commands
import asyncio
from bot import bot

async def list_commands():
    # Wait for bot to be ready
    await bot.wait_until_ready()
    
    print(f"\nGlobal commands for {bot.user}:")
    all_commands = await bot.tree.fetch_commands()
    
    if not all_commands:
        print("No commands registered!")
    else:
        for cmd in all_commands:
            print(f"- /{cmd.name}: {cmd.description}")
    
    print("\nCommands by cog:")
    for cog_name, cog in bot.cogs.items():
        print(f"\n{cog_name} Cog:")
        commands = cog.get_app_commands()
        if not commands:
            print("  No commands")
        for cmd in commands:
            print(f"  - /{cmd.name}: {cmd.description}")

async def main():
    await bot.login(bot.token)
    asyncio.create_task(list_commands())
    await asyncio.sleep(5)  # Give enough time to fetch commands
    await bot.close()

if __name__ == "__main__":
    asyncio.run(main())
