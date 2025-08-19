import asyncio
import random
import string
from datetime import datetime, timedelta
import aiosqlite

DB_FILE = "db/db.db"

async def generate_dummy_data():
    async with aiosqlite.connect(DB_FILE) as db:
        # 1. Insert users
        user_ids = []
        for i in range(10):  # 10 users
            discord_id = str(random.randint(10**17, 10**18 - 1))
            cf_handle = "cf_" + ''.join(random.choices(string.ascii_lowercase, k=6))
            await db.execute(
                "INSERT INTO users (discord_id, cf_handle) VALUES (?, ?)",
                (discord_id, cf_handle)
            )
        await db.commit()

        async with db.execute("SELECT user_id FROM users") as cursor:
            user_ids = [row[0] for row in await cursor.fetchall()]

        # 2. Insert challenges
        for _ in range(5):  # 5 challenges
            # Create the challenge
            problem_id = "CF" + str(random.randint(1000, 2000))
            cur = await db.execute(
                "INSERT INTO challenges (problem_id) VALUES (?)",
                (problem_id,)
            )
            challenge_id = cur.lastrowid

            # Pick participants
            participants = random.sample(user_ids, k=random.randint(2, 4))
            winner = random.choice(participants)

            # Insert into challenge_participants
            for pid in participants:
                score_awarded = random.randint(10, 50) if pid == winner else 0
                is_winner = pid == winner
                await db.execute(
                    """
                    INSERT INTO challenge_participants (challenge_id, user_id, score_awarded, is_winner)
                    VALUES (?, ?, ?, ?)
                    """,
                    (challenge_id, pid, score_awarded, is_winner)
                )

        await db.commit()


        # 3. Insert contests
        contest_ids = []
        for i in range(3):
            cf_contest_id = random.randint(100, 999)
            name = f"Contest {i+1}"
            start_time = datetime.utcnow()
            end_time = start_time + timedelta(hours=2)
            cur = await db.execute(
                "INSERT INTO contests (cf_contest_id, name, start_time, end_time) VALUES (?, ?, ?, ?)",
                (cf_contest_id, name, start_time, end_time)
            )
            contest_ids.append(cur.lastrowid)
        await db.commit()

        # 4. Insert contest_scores
        for cid in contest_ids:
            participants = random.sample(user_ids, k=random.randint(3, 7))
            rank = 1
            for uid in participants:
                score = random.randint(100, 500)
                await db.execute(
                    "INSERT INTO contest_scores (contest_id, user_id, score, rank) VALUES (?, ?, ?, ?)",
                    (cid, uid, score, rank)
                )
                rank += 1
        await db.commit()

        # 5. Insert score history
        for uid in user_ids:
            for _ in range(5):
                score_type = random.choice(["challenge", "contest"])
                score = random.randint(5, 100)
                created_at = datetime.utcnow() - timedelta(days=random.randint(0, 30))
                await db.execute(
                    "INSERT INTO score_history (user_id, score_type, score, created_at) VALUES (?, ?, ?, ?)",
                    (uid, score_type, score, created_at)
                )
        await db.commit()

    print("✅ Dummy data inserted successfully!")

asyncio.run(generate_dummy_data())
