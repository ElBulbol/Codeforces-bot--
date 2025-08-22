import aiosqlite
import os
import json
from typing import Dict, List, Optional
from datetime import datetime, timedelta


# Global database path
DB_PATH = "db/db.db"


async def init_db() -> None:
    """
    Initialize the SQLite database with all required tables.
    Creates the database file if it doesn't exist.
    """
    # Ensure directory exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Users table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT UNIQUE NOT NULL,
                cf_handle TEXT UNIQUE NOT NULL,
                problems_solved INTEGER DEFAULT 0,
                last_updated INTEGER DEFAULT 0,
                verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Challenges table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS challenges (
                challenge_id INTEGER PRIMARY KEY AUTOINCREMENT,
                problem_id TEXT NOT NULL,
                problem_name TEXT,
                problem_link TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Challenge Participants table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS challenge_participants (
                challenge_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                score_awarded INTEGER DEFAULT 0,
                is_winner BOOLEAN,
                finish_time INTEGER,
                rank INTEGER,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (challenge_id, user_id),
                FOREIGN KEY (challenge_id) REFERENCES challenges(challenge_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        
        # Contests table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS contests (
                contest_id INTEGER PRIMARY KEY AUTOINCREMENT,
                cf_contest_id INTEGER,
                name TEXT NOT NULL,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                duration INTEGER,
                problems TEXT,
                solves_info TEXT DEFAULT '{}',
                status TEXT DEFAULT 'PENDING',
                contest_type TEXT DEFAULT 'codeforces',
                unix_timestamp INTEGER
            )
        """)
        
        # Contest Participants table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS contest_participants (
                contest_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                score INTEGER DEFAULT 0,
                solved_problems TEXT DEFAULT '[]',
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (contest_id, user_id),
                FOREIGN KEY (contest_id) REFERENCES contests(contest_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        
        await db.commit()


async def add_user(discord_id: str, cf_handle: str) -> int:
    """Add a new user and return their user_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "INSERT INTO users (discord_id, cf_handle) VALUES (?, ?)",
            (discord_id, cf_handle)
        )
        await db.commit()
        return cursor.lastrowid


async def get_user_by_discord(discord_id: str) -> Optional[Dict]:
    """Get user by Discord ID, returns None if not found."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE discord_id = ?",
            (discord_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def create_challenge(problem_id: str, problem_name: str = None, problem_link: str = None) -> int:
    """Create a new challenge and return the challenge_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "INSERT INTO challenges (problem_id, problem_name, problem_link) VALUES (?, ?, ?)",
            (problem_id, problem_name, problem_link)
        )
        await db.commit()
        return cursor.lastrowid


async def add_challenge_participant(
    challenge_id: int, 
    user_id: int, 
    score_awarded: int = 0, 
    is_winner: bool = False,
    finish_time: int = None,
    rank: int = None
) -> None:
    """Add a participant to a challenge."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "INSERT INTO challenge_participants (challenge_id, user_id, score_awarded, is_winner, finish_time, rank) VALUES (?, ?, ?, ?, ?, ?)",
            (challenge_id, user_id, score_awarded, is_winner, finish_time, rank)
        )
        await db.commit()


async def create_contest(
    cf_contest_id: int, 
    name: str, 
    start_time: str, 
    end_time: str
) -> int:
    """Create a new contest and return the contest_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "INSERT INTO contests (cf_contest_id, name, start_time, end_time) VALUES (?, ?, ?, ?)",
            (cf_contest_id, name, start_time, end_time)
        )
        await db.commit()
        return cursor.lastrowid


async def update_contest_score(
    contest_id: int, 
    user_id: int, 
    score: int, 
    rank: int
) -> None:
    """Update or insert a contest score for a user."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "INSERT OR REPLACE INTO contest_scores (contest_id, user_id, score, rank) VALUES (?, ?, ?, ?)",
            (contest_id, user_id, score, rank)
        )
        await db.commit()


async def add_score_history(
    user_id: int, 
    score_type: str, 
    score: int
) -> None:
    """Add an entry to score history."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "INSERT INTO score_history (user_id, score_type, score) VALUES (?, ?, ?)",
            (user_id, score_type, score)
        )
        await db.commit()


async def get_leaderboard(limit: int = 10) -> List[Dict]:
    """Get leaderboard based on total scores from challenges and contests."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT 
                u.user_id,
                u.discord_id,
                u.cf_handle,
                COALESCE(challenge_scores.total_challenge_score, 0) + COALESCE(contest_scores.total_contest_score, 0) as total_score
            FROM users u
            LEFT JOIN (
                SELECT user_id, SUM(score_awarded) as total_challenge_score
                FROM challenge_participants
                GROUP BY user_id
            ) challenge_scores ON u.user_id = challenge_scores.user_id
            LEFT JOIN (
                SELECT user_id, SUM(score) as total_contest_score
                FROM contest_participants
                GROUP BY user_id
            ) contest_scores ON u.user_id = contest_scores.user_id
            ORDER BY total_score DESC
            LIMIT ?
        """, (limit,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def delete_user(discord_id: str = None, cf_handle: str = None) -> bool:
    """
    Delete a user from the database by either Discord ID or Codeforces handle.
    Returns True if user was deleted, False if not found.
    """
    if not discord_id and not cf_handle:
        raise ValueError("Either discord_id or cf_handle must be provided")
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        if discord_id:
            cursor = await db.execute(
                "DELETE FROM users WHERE discord_id = ?",
                (discord_id,)
            )
        else:
            cursor = await db.execute(
                "DELETE FROM users WHERE cf_handle = ?",
                (cf_handle,)
            )
        
        await db.commit()
        return cursor.rowcount > 0


# Bot contest functions
async def create_bot_contest(name: str, duration: int, start_time: str, unix_timestamp: int = None) -> int:
    """Create a new bot contest and return the contest_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # If unix_timestamp not provided, calculate it from start_time
        if unix_timestamp is None and start_time:
            try:
                start_time_dt = datetime.fromisoformat(start_time)
                unix_timestamp = int(start_time_dt.timestamp())
            except:
                unix_timestamp = None
        
        cursor = await db.execute(
            "INSERT INTO contests (name, duration, start_time, unix_timestamp, status, contest_type) VALUES (?, ?, ?, ?, ?, ?)",
            (name, duration, start_time, unix_timestamp, "PENDING", "bot")
        )
        await db.commit()
        return cursor.lastrowid


async def get_bot_contest(contest_id: int) -> Optional[Dict]:
    """Get bot contest by ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM contests WHERE contest_id = ? AND contest_type = 'bot'",
            (contest_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_pending_and_active_contests() -> List[Dict]:
    """Get all bot contests that are not ended."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM contests WHERE status != 'ENDED' AND contest_type = 'bot'"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def update_contest_status(contest_id: int, status: str) -> None:
    """Update contest status."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE contests SET status = ? WHERE contest_id = ?",
            (status, contest_id)
        )
        await db.commit()


async def update_contest_problems(contest_id: int, problems: List[str]) -> None:
    """Update problems list for a contest."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE contests SET problems = ? WHERE contest_id = ?",
            (json.dumps(problems), contest_id)
        )
        await db.commit()


async def get_contest_problems(contest_id: int) -> List[str]:
    """Get problems list for a contest."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT problems FROM contests WHERE contest_id = ?",
            (contest_id,)
        )
        row = await cursor.fetchone()
        if row and row[0]:
            return json.loads(row[0])
        return []


async def update_contest_solves_info(contest_id: int, solves_info: Dict) -> None:
    """Update solves info for a contest."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE contests SET solves_info = ? WHERE contest_id = ?",
            (json.dumps(solves_info), contest_id)
        )
        await db.commit()


async def get_contest_solves_info(contest_id: int) -> Dict:
    """Get solves info for a contest."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT solves_info FROM contests WHERE contest_id = ?",
            (contest_id,)
        )
        row = await cursor.fetchone()
        if row and row[0]:
            return json.loads(row[0])
        return {}


async def join_contest(contest_id: int, discord_id: str, codeforces_handle: str) -> None:
    """Add user to contest participants."""
    # Get user_id from users table
    user_data = await get_user_by_discord(discord_id)
    if not user_data:
        raise ValueError(f"User with discord_id {discord_id} not found")
    
    user_id = user_data['user_id']
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO contest_participants (contest_id, user_id) VALUES (?, ?)",
            (contest_id, user_id)
        )
        await db.commit()


async def get_contest_participant(contest_id: int, discord_id: str) -> Optional[Dict]:
    """Get contest participant data."""
    user_data = await get_user_by_discord(discord_id)
    if not user_data:
        return None
    
    user_id = user_data['user_id']
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT cp.*, u.cf_handle as codeforces_handle 
               FROM contest_participants cp 
               JOIN users u ON cp.user_id = u.user_id 
               WHERE cp.contest_id = ? AND cp.user_id = ?""",
            (contest_id, user_id)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_contest_participant_score(contest_id: int, discord_id: str, score_increase: int, solved_problems: List[str]) -> None:
    """Update participant's score and solved problems."""
    user_data = await get_user_by_discord(discord_id)
    if not user_data:
        raise ValueError(f"User with discord_id {discord_id} not found")
    
    user_id = user_data['user_id']
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE contest_participants SET score = score + ?, solved_problems = ? WHERE contest_id = ? AND user_id = ?",
            (score_increase, json.dumps(solved_problems), contest_id, user_id)
        )
        await db.commit()


async def get_contest_leaderboard(contest_id: int) -> List[Dict]:
    """Get contest leaderboard ordered by score."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT cp.*, u.discord_id, u.cf_handle as codeforces_handle 
               FROM contest_participants cp 
               JOIN users u ON cp.user_id = u.user_id 
               WHERE cp.contest_id = ? 
               ORDER BY cp.score DESC""",
            (contest_id,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_contest_participant_count(contest_id: int) -> int:
    """Get the number of participants in a contest."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT COUNT(*) as count FROM contest_participants WHERE contest_id = ?",
            (contest_id,)
        )
        row = await cursor.fetchone()
        return row['count'] if row else 0


async def get_all_bot_contests() -> List[Dict]:
    """Get all bot contests ordered by start time (newest first)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM contests WHERE contest_type = 'bot' ORDER BY start_time DESC"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


# Functions for Codeforces functionality
async def get_cf_handle(discord_id: str) -> Optional[str]:
    """Get Codeforces handle for a Discord user."""
    user = await get_user_by_discord(discord_id)
    return user['cf_handle'] if user else None


async def get_all_cf_handles() -> Dict[str, str]:
    """Get all Discord ID to Codeforces handle mappings."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT discord_id, cf_handle FROM users")
        rows = await cursor.fetchall()
        return {row['discord_id']: row['cf_handle'] for row in rows}


async def increment_user_problems_solved(discord_id: str):
    """Increment the user's bot problems solved count by 1"""
    try:
        current_timestamp = int(datetime.now().timestamp())
        
        # Increment the problems_solved counter by 1
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE users SET problems_solved = problems_solved + 1, last_updated = ? WHERE discord_id = ?",
                (current_timestamp, discord_id)
            )
            await db.commit()
            
            # Get the updated count for logging
            cursor = await db.execute(
                "SELECT problems_solved FROM users WHERE discord_id = ?",
                (discord_id,)
            )
            row = await cursor.fetchone()
            new_count = row[0] if row else 0
            
            print(f"Incremented bot problems solved count for user {discord_id}: now {new_count} problems")
            
    except Exception as e:
        print(f"Error incrementing problems solved count for user {discord_id}: {e}")


async def get_user_info(discord_id: str, session=None) -> Dict:
    """Get user information including last updated timestamp."""
    user = await get_user_by_discord(discord_id)
    if not user:
        return {
            "exists": False,
            "discord_id": discord_id,
            "cf_handle": "",
            "last_updated": 0
        }
    
    return {
        "exists": True,
        "discord_id": user['discord_id'],
        "cf_handle": user['cf_handle'],
        "last_updated": user['last_updated'] or 0
    }


async def get_user_score(discord_id: str) -> Dict:
    """Get user scoring information including time-based scores."""
    user = await get_user_by_discord(discord_id)
    if not user:
        return {"exists": False}
    
    user_id = user['user_id']
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # --- Overall Score ---
        cursor = await db.execute(
            "SELECT COALESCE(SUM(score), 0) as contest_score FROM contest_participants WHERE user_id = ?",
            (user_id,)
        )
        contest_row = await cursor.fetchone()
        contest_score = contest_row['contest_score'] if contest_row else 0
        
        cursor = await db.execute(
            "SELECT COALESCE(SUM(score_awarded), 0) as challenge_score FROM challenge_participants WHERE user_id = ?",
            (user_id,)
        )
        challenge_row = await cursor.fetchone()
        challenge_score = challenge_row['challenge_score'] if challenge_row else 0
        
        total_score = contest_score + challenge_score

        # --- Time-based Scores ---
        now = datetime.now()
        time_thresholds = {
            "daily": (now - timedelta(days=1)).isoformat(),
            "weekly": (now - timedelta(days=7)).isoformat(),
            "monthly": (now - timedelta(days=30)).isoformat()
        }

        scores = {}
        for period, threshold in time_thresholds.items():
            # Contest score for the period
            cursor = await db.execute(
                "SELECT COALESCE(SUM(score), 0) as score FROM contest_participants WHERE user_id = ? AND joined_at >= ?",
                (user_id, threshold)
            )
            contest_period_score = (await cursor.fetchone())['score']

            # Challenge score for the period
            cursor = await db.execute(
                """SELECT COALESCE(SUM(chp.score_awarded), 0) as score
                   FROM challenge_participants chp
                   JOIN challenges ch ON chp.challenge_id = ch.challenge_id
                   WHERE chp.user_id = ? AND ch.created_at >= ?""",
                (user_id, threshold)
            )
            challenge_period_score = (await cursor.fetchone())['score']
            
            scores[f"{period}_points"] = contest_period_score + challenge_period_score

        return {
            "exists": True,
            "codeforces_name": user['cf_handle'],
            "daily_points": scores["daily_points"],
            "weekly_points": scores["weekly_points"],
            "monthly_points": scores["monthly_points"],
            "overall_points": total_score,
            "solved_problems": user['problems_solved'] or 0,
            "last_updated": user['last_updated'] or 0
        }


async def get_custom_leaderboard(category: str, limit: int = 10) -> List[Dict]:
    """Get leaderboard for different scoring categories."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        if category == "solved":
            # Problems solved leaderboard
            cursor = await db.execute("""
                SELECT 
                    discord_id,
                    cf_handle as codeforces_name,
                    problems_solved as score,
                    ROW_NUMBER() OVER (ORDER BY problems_solved DESC) as rank
                FROM users 
                WHERE problems_solved > 0
                ORDER BY problems_solved DESC 
                LIMIT ?
            """, (limit,))
        elif category in ["daily", "weekly", "monthly"]:
            # Time-based scoring from contests and challenges
            now = datetime.now()
            if category == "daily":
                time_threshold = now - timedelta(days=1)
            elif category == "weekly":
                time_threshold = now - timedelta(days=7)
            else:  # monthly
                time_threshold = now - timedelta(days=30)
            
            time_threshold_str = time_threshold.isoformat()
            
            cursor = await db.execute(f"""
                SELECT 
                    u.discord_id,
                    u.cf_handle as codeforces_name,
                    COALESCE(recent_contest_scores.score, 0) + COALESCE(recent_challenge_scores.score, 0) as score,
                    ROW_NUMBER() OVER (ORDER BY (COALESCE(recent_contest_scores.score, 0) + COALESCE(recent_challenge_scores.score, 0)) DESC) as rank
                FROM users u
                LEFT JOIN (
                    SELECT cp.user_id, SUM(cp.score) as score
                    FROM contest_participants cp
                    WHERE cp.joined_at >= ?
                    GROUP BY cp.user_id
                ) recent_contest_scores ON u.user_id = recent_contest_scores.user_id
                LEFT JOIN (
                    SELECT chp.user_id, SUM(chp.score_awarded) as score
                    FROM challenge_participants chp
                    JOIN challenges ch ON chp.challenge_id = ch.challenge_id
                    WHERE ch.created_at >= ?
                    GROUP BY chp.user_id
                ) recent_challenge_scores ON u.user_id = recent_challenge_scores.user_id
                -- FIXED: Replaced HAVING with WHERE on the calculated score
                WHERE (COALESCE(recent_contest_scores.score, 0) + COALESCE(recent_challenge_scores.score, 0)) > 0
                ORDER BY score DESC 
                LIMIT ?
            """, (time_threshold_str, time_threshold_str, limit))
        else: # "overall"
            # Overall scoring
            cursor = await db.execute("""
                SELECT 
                    u.discord_id,
                    u.cf_handle as codeforces_name,
                    COALESCE(contest_scores.score, 0) + COALESCE(challenge_scores.score, 0) as score,
                    ROW_NUMBER() OVER (ORDER BY (COALESCE(contest_scores.score, 0) + COALESCE(challenge_scores.score, 0)) DESC) as rank
                FROM users u
                LEFT JOIN (
                    SELECT user_id, SUM(score) as score
                    FROM contest_participants
                    GROUP BY user_id
                ) contest_scores ON u.user_id = contest_scores.user_id
                LEFT JOIN (
                    SELECT user_id, SUM(score_awarded) as score
                    FROM challenge_participants
                    GROUP BY user_id
                ) challenge_scores ON u.user_id = challenge_scores.user_id
                -- FIXED: Replaced HAVING with WHERE on the calculated score
                WHERE (COALESCE(contest_scores.score, 0) + COALESCE(challenge_scores.score, 0)) > 0
                ORDER BY score DESC 
                LIMIT ?
            """, (limit,))
        
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def sync_cf_handles_from_file(cf_links_file: str) -> None:
    """Sync Codeforces handles from a JSON file to the database."""
    if not os.path.exists(cf_links_file):
        return
    
    with open(cf_links_file, 'r') as f:
        links = json.load(f)
    
    async with aiosqlite.connect(DB_PATH) as db:
        for discord_id, cf_handle in links.items():
            cursor = await db.execute("SELECT discord_id FROM users WHERE discord_id = ?", (discord_id,))
            user = await cursor.fetchone()
            
            if not user:
                await db.execute(
                    "INSERT INTO users (discord_id, cf_handle) VALUES (?, ?)",
                    (discord_id, cf_handle)
                )
            else:
                await db.execute(
                    "UPDATE users SET cf_handle = ? WHERE discord_id = ?",
                    (cf_handle, discord_id)
                )
        
        await db.commit()


async def add_challenge_history(challenge_id: int, discord_id: str, cf_handle: str, 
                                problem_name: str, problem_link: str, finish_time: int, 
                                rank: int, points: int) -> None:
    """Add an entry to challenge participants (replaces challenge_history)."""
    # Get or create user
    user = await get_user_by_discord(discord_id)
    if not user:
        # Create user if doesn't exist
        user_id = await add_user(discord_id, cf_handle)
    else:
        user_id = user['user_id']
    
    # Update challenge info if provided
    if problem_name or problem_link:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE challenges SET problem_name = COALESCE(?, problem_name), problem_link = COALESCE(?, problem_link) WHERE challenge_id = ?",
                (problem_name, problem_link, challenge_id)
            )
            await db.commit()
    
    # Add participant record
    await add_challenge_participant(challenge_id, user_id, points, rank == 1, finish_time, rank)


async def get_challenge_history(limit: int = 50) -> List[Dict]:
    """Get challenge history from challenge_participants joined with other tables."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT 
                c.challenge_id,
                u.discord_id,
                u.cf_handle,
                c.problem_name,
                c.problem_link,
                cp.finish_time,
                cp.rank,
                cp.score_awarded as points,
                cp.joined_at as timestamp
            FROM challenge_participants cp
            JOIN challenges c ON cp.challenge_id = c.challenge_id
            JOIN users u ON cp.user_id = u.user_id
            ORDER BY cp.joined_at DESC
            LIMIT ?
        """, (limit,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_user_challenge_history(discord_id: str, limit: int = 20) -> List[Dict]:
    """Get challenge history for a specific user."""
    user = await get_user_by_discord(discord_id)
    if not user:
        return []
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT 
                c.challenge_id,
                c.problem_name,
                c.problem_link,
                cp.finish_time,
                cp.rank,
                cp.score_awarded as points,
                cp.joined_at as timestamp
            FROM challenge_participants cp
            JOIN challenges c ON cp.challenge_id = c.challenge_id
            WHERE cp.user_id = ?
            ORDER BY cp.joined_at DESC
            LIMIT ?
        """, (user['user_id'], limit))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]