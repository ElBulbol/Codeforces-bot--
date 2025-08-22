import asyncio
import random
import string
import json
from datetime import datetime, timedelta
import aiosqlite

DB_FILE = "db/db.db"
SPECIFIC_DISCORD_ID = "543172445155098624"

async def generate_dummy_data():
    """
    Populates the database with dummy data matching the new schema,
    ensuring a specific user is included and has records.
    """
    async with aiosqlite.connect(DB_FILE) as db:
        print("Wiping existing dummy data (if any)...")
        # Optional: Clear tables to avoid conflicts on re-runs
        await db.execute("DELETE FROM challenge_participants")
        await db.execute("DELETE FROM contest_participants")
        await db.execute("DELETE FROM users")
        await db.execute("DELETE FROM challenges")
        await db.execute("DELETE FROM contests")
        await db.commit()

        # 1. Insert users, ensuring the specific user exists
        print(f"Inserting users, including specific user {SPECIFIC_DISCORD_ID}...")
        
        # Insert or ignore the specific user to ensure they are in the DB
        await db.execute(
            """
            INSERT OR IGNORE INTO users (discord_id, cf_handle, problems_solved, last_updated) 
            VALUES (?, ?, ?, ?)
            """,
            (
                SPECIFIC_DISCORD_ID, 
                "mayman007", 
                random.randint(5, 50), 
                int((datetime.now() - timedelta(days=random.randint(0, 5))).timestamp())
            )
        )

        # Insert 9 other random users
        for i in range(9):
            discord_id = str(random.randint(10**17, 10**18 - 1))
            cf_handle = "cf_" + ''.join(random.choices(string.ascii_lowercase, k=8))
            problems_solved = random.randint(0, 100)
            last_updated = int((datetime.now() - timedelta(minutes=random.randint(1, 1440))).timestamp())
            await db.execute(
                "INSERT OR IGNORE INTO users (discord_id, cf_handle, problems_solved, last_updated) VALUES (?, ?, ?, ?)",
                (discord_id, cf_handle, problems_solved, last_updated)
            )
        await db.commit()

        # Fetch all user IDs for participation pools
        async with db.execute("SELECT user_id FROM users") as cursor:
            user_ids = [row[0] for row in await cursor.fetchall()]
        
        # Get the database user_id for our specific user
        async with db.execute("SELECT user_id FROM users WHERE discord_id = ?", (SPECIFIC_DISCORD_ID,)) as cursor:
            specific_user_row = await cursor.fetchone()
            if not specific_user_row:
                print(f"Error: Could not find specific user {SPECIFIC_DISCORD_ID} after insertion.")
                return
            specific_user_id = specific_user_row[0]
            

        # 2. Insert challenges and participants
        print("Inserting challenges and participants...")
        for i in range(5):  # 5 challenges
            # Create the challenge with a random past creation date
            created_at = datetime.now() - timedelta(days=random.randint(0, 30))
            problem_id = f"{random.randint(1500, 1800)}{random.choice(string.ascii_uppercase)}"
            problem_name = f"Dummy Problem {i+1}"
            problem_link = f"https://codeforces.com/problemset/problem/{problem_id[:-1]}/{problem_id[-1]}"

            cur = await db.execute(
                "INSERT INTO challenges (problem_id, problem_name, problem_link, created_at) VALUES (?, ?, ?, ?)",
                (problem_id, problem_name, problem_link, created_at)
            )
            challenge_id = cur.lastrowid

            # Create a set of participants, ensuring our specific user is included
            participants = set(random.sample(user_ids, k=random.randint(2, 4)))
            participants.add(specific_user_id) # Guarantee the specific user is a participant

            # Insert into challenge_participants
            for rank, user_id in enumerate(participants, 1):
                is_winner = (rank == 1)
                await db.execute(
                    """
                    INSERT INTO challenge_participants (challenge_id, user_id, score_awarded, is_winner, finish_time, rank, joined_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        challenge_id, 
                        user_id, 
                        random.randint(50, 100) if is_winner else random.randint(10, 40), 
                        is_winner, 
                        int(created_at.timestamp()) + random.randint(300, 3600), 
                        rank,
                        created_at
                    )
                )
        await db.commit()


        # 3. Insert contests and participants
        print("Inserting contests and participants...")
        for i in range(3): # 3 contests
            start_time = datetime.now() - timedelta(days=random.randint(1, 45))
            duration = random.randint(7200, 10800) # 2-3 hours in seconds
            
            cur = await db.execute(
                """
                INSERT INTO contests (name, start_time, duration, status, contest_type, unix_timestamp) 
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f"Dummy Contest #{i+1}",
                    start_time,
                    duration,
                    "ENDED",
                    random.choice(['bot', 'codeforces']),
                    int(start_time.timestamp())
                )
            )
            contest_id = cur.lastrowid

            # Create a set of participants, ensuring our specific user is included
            participants = set(random.sample(user_ids, k=random.randint(3, 7)))
            participants.add(specific_user_id)

            for user_id in participants:
                await db.execute(
                    """
                    INSERT INTO contest_participants (contest_id, user_id, score, solved_problems, joined_at) 
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        contest_id,
                        user_id,
                        random.randint(100, 2500),
                        json.dumps([f"Problem {c}" for c in string.ascii_uppercase[:random.randint(1,4)]]),
                        start_time
                    )
                )
        await db.commit()

        print("✅ Dummy data inserted successfully!")

if __name__ == "__main__":
    asyncio.run(generate_dummy_data())