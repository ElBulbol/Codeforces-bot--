import asyncio
import random
import string
import json
from datetime import datetime, timedelta
import aiosqlite

# --- Configuration ---
DB_FILE = "db/db.db"
SPECIFIC_DISCORD_ID = "543172445155098624" # Specific user to ensure exists

async def generate_dummy_data():
    """
    Populates the database with dummy data matching the new schema,
    ensuring a specific user is included and has records across different tables.
    """
    async with aiosqlite.connect(DB_FILE) as db:
        print("Wiping existing dummy data (if any)...")
        # Clear tables in the correct order to respect foreign key constraints
        await db.execute("DELETE FROM challenge_participants")
        await db.execute("DELETE FROM contest_participants")
        await db.execute("DELETE FROM users")
        await db.execute("DELETE FROM challenges")
        await db.execute("DELETE FROM contests")
        await db.commit()
        print("Existing data wiped.")

        # 1. Insert users, ensuring the specific user exists
        print(f"Inserting users, including specific user {SPECIFIC_DISCORD_ID}...")
        
        # Insert or ignore the specific user to ensure they are in the DB
        await db.execute(
            """
            INSERT OR IGNORE INTO users (discord_id, cf_handle, problems_solved, last_updated, verified_at) 
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                SPECIFIC_DISCORD_ID, 
                "mayman007", 
                random.randint(5, 50), 
                int((datetime.now() - timedelta(days=random.randint(0, 5))).timestamp()),
                datetime.now() - timedelta(days=random.randint(10, 60)) # Add verified_at
            )
        )

        # Insert 9 other random users
        for i in range(9):
            discord_id = str(random.randint(10**17, 10**18 - 1))
            cf_handle = "cf_" + ''.join(random.choices(string.ascii_lowercase, k=8))
            problems_solved = random.randint(0, 100)
            last_updated = int((datetime.now() - timedelta(minutes=random.randint(1, 1440))).timestamp())
            verified_at = datetime.now() - timedelta(days=random.randint(10, 60))
            await db.execute(
                "INSERT OR IGNORE INTO users (discord_id, cf_handle, problems_solved, last_updated, verified_at) VALUES (?, ?, ?, ?, ?)",
                (discord_id, cf_handle, problems_solved, last_updated, verified_at)
            )
        await db.commit()
        print("Users inserted.")

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
            created_at = datetime.now() - timedelta(days=random.randint(0, 30))
            problem_id = f"{random.randint(1500, 1800)}{random.choice(string.ascii_uppercase)}"
            problem_name = f"Dummy Challenge Problem {i+1}"
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
        print("Challenges inserted.")

        # 3. Insert contests and participants
        print("Inserting contests and participants...")
        for i in range(3): # 3 contests
            start_time = datetime.now() - timedelta(days=random.randint(1, 45))
            duration = random.randint(7200, 10800) # 2-3 hours in seconds
            end_time = start_time + timedelta(seconds=duration)
            
            # Generate dummy problems and solves info
            num_problems = random.randint(3, 6)
            problems_list = [f"Problem {c}" for c in string.ascii_uppercase[:num_problems]]
            solves_info_dict = {p: random.randint(0, 8) for p in problems_list}

            cur = await db.execute(
                """
                INSERT INTO contests (guild_id, cf_contest_id, name, start_time, end_time, duration, problems, solves_info, status, contest_type, unix_timestamp) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    random.randint(10**17, 10**18 - 1), # guild_id
                    random.randint(1000, 2000), # cf_contest_id
                    f"Dummy Contest #{i+1}",
                    start_time,
                    end_time, # end_time
                    duration,
                    json.dumps(problems_list), # problems
                    json.dumps(solves_info_dict), # solves_info
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
                # User solves a subset of the available problems
                solved_count = random.randint(1, num_problems)
                solved_problems_list = random.sample(problems_list, k=solved_count)

                await db.execute(
                    """
                    INSERT INTO contest_participants (contest_id, user_id, score, solved_problems, joined_at) 
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        contest_id,
                        user_id,
                        random.randint(100, 2500),
                        json.dumps(solved_problems_list),
                        start_time
                    )
                )
        await db.commit()
        print("Contests inserted.")

        print("\n✅ Dummy data inserted successfully!")

if __name__ == "__main__":
    # This ensures the 'db' directory exists before trying to create the file
    import os
    os.makedirs("db", exist_ok=True)
    
    asyncio.run(generate_dummy_data())
