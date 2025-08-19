import discord
from discord.ext import commands, tasks
import aiosqlite
import datetime

DB_PATH = "db/db.db"

class ResetTimer(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.daily_reset.start()
        self.weekly_reset.start()
        self.monthly_reset.start()

    @tasks.loop(hours=24)
    async def daily_reset(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET daily_score = 0")
            await db.commit()

    @tasks.loop(hours=24)
    async def weekly_reset(self):
        # Reset every Monday at midnight
        if datetime.datetime.utcnow().weekday() == 0:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET weekly_score = 0")
                await db.commit()

    @tasks.loop(hours=24)
    async def monthly_reset(self):
        # Reset on the first day of the month
        if datetime.datetime.utcnow().day == 1:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET monthly_score = 0")
                await db.commit()

    @daily_reset.before_loop
    @weekly_reset.before_loop
    @monthly_reset.before_loop
    async def before_loops(self):
        await self.bot.wait_until_ready()

async def setup(bot: commands.Bot):
    await bot.add_cog(ResetTimer(bot))