import discord
import asyncio
import sys

# Add this to your bot.py to debug
async def debug_commands(bot):
    await bot.wait_until_ready()
    print("\n=== DEBUG: REGISTERED COMMANDS ===")
    print(f"Bot is logged in as: {bot.user}")
    print("\nGlobal Commands:")
    try:
        commands = await bot.tree.fetch_commands()
        if commands:
            for cmd in commands:
                print(f"- /{cmd.name}: {cmd.description}")
        else:
            print("No global commands registered!")
    except Exception as e:
        print(f"Error fetching global commands: {e}")
    
    print("\nCogs and their commands:")
    for cog_name, cog in bot.cogs.items():
        print(f"\n{cog_name} Cog:")
        try:
            app_commands = cog.get_app_commands()
            if app_commands:
                for cmd in app_commands:
                    print(f"- /{cmd.name}: {cmd.description}")
            else:
                print("  No commands in this cog")
        except Exception as e:
            print(f"  Error getting commands for {cog_name}: {e}")
    
    print("\n=== END DEBUG ===\n")

# Run this standalone script
async def main():
    from bot import bot
    import asyncio
    
    # Setup and start bot
    task = asyncio.create_task(bot.start(bot.token))
    
    # Wait for bot to be ready
    await asyncio.sleep(5)  # Give bot time to connect
    
    # Debug commands
    await debug_commands(bot)
    
    # Clean shutdown
    await bot.close()
    task.cancel()

if __name__ == "__main__":
    asyncio.run(main())
