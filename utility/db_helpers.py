import aiosqlite
import os
import json
from typing import Dict, List, Optional


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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT UNIQUE NOT NULL,
                cf_handle TEXT UNIQUE NOT NULL,
                verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                Number_of_problem_solved INTEGER DEFAULT 0,
                overall_score INTEGER DEFAULT 0,
                daily_score INTEGER DEFAULT 0,
                weekly_score INTEGER DEFAULT 0,
                monthly_score INTEGER DEFAULT 0
            )
        """)
        
        # Challenges table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS challenges (
                challenge_id INTEGER PRIMARY KEY AUTOINCREMENT,
                problem_link TEXT NOT NULL,
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
                PRIMARY KEY (challenge_id, user_id),
                FOREIGN KEY (challenge_id) REFERENCES challenges(challenge_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        
        # Contests table (modified to support bot contests)
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
                contest_type TEXT DEFAULT 'codeforces'
            )
        """)
        
        # Contest Participants table (enhanced)
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
        
        # Contest Scores table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS contest_scores (
                contest_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                cf_handle TEXT NOT NULL,
                problem_solved INTEGER DEFAULT 0,
                score INTEGER DEFAULT 0,
                PRIMARY KEY (contest_id, user_id),
                FOREIGN KEY (contest_id) REFERENCES contests(contest_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        
        await db.commit()


async def add_user(discord_id: str, cf_handle: str) -> int:
    """Add a new user and return their user_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (discord_id, cf_handle, Number_of_problem_solved) VALUES (?, ?, 0)",
            (discord_id, cf_handle)
        )
        await db.commit()
        cursor = await db.execute(
            "SELECT user_id FROM users WHERE discord_id = ?", (discord_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None


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


async def create_challenge(problem_link: str) -> int:
    """Create a new challenge and return the challenge_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "INSERT INTO challenges (problem_link) VALUES (?)",
            (problem_link,)
        )
        await db.commit()
        return cursor.lastrowid


async def add_challenge_participant(
    challenge_id: int, 
    user_id: int, 
    score_awarded: int = 0, 
    is_winner: bool = False
) -> None:
    """Add a participant to a challenge."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "INSERT INTO challenge_participants (challenge_id, user_id, score_awarded, is_winner) VALUES (?, ?, ?, ?)",
            (challenge_id, user_id, score_awarded, is_winner)
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
    discord_id: str, 
    problem_link: str, 
    points: int
) -> bool:
    """
    Update a user's contest score and add the solved problem to their list.
    
    Args:
        contest_id: The contest ID
        discord_id: The user's Discord ID
        problem_link: The link to the solved problem
        points: Points to add for this problem
        
    Returns:
        True if successful, False otherwise
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # First get current values
        cursor = await db.execute(
            "SELECT score, problem_solved FROM contest_scores WHERE contest_id = ? AND discord_id = ?",
            (contest_id, discord_id)
        )
        row = await cursor.fetchone()
        
        if not row:
            return False
            
        current_score = row[0]
        problem_solved_str = row[1] if row[1] else ""  # Handle None or empty string
        
        # Check if problem already solved
        if problem_solved_str and problem_link in problem_solved_str:
            return False
            
        # Update problem_solved column
        if problem_solved_str:
            new_problem_solved = f"{problem_solved_str}, {problem_link}"
        else:
            new_problem_solved = problem_link
            
        # Update score and problem_solved
        new_score = current_score + points
        await db.execute(
            "UPDATE contest_scores SET score = ?, problem_solved = ? WHERE contest_id = ? AND discord_id = ?",
            (new_score, new_problem_solved, contest_id, discord_id)
        )
        await db.commit()
        return True


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
    """Get leaderboard based on total scores from score history."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT 
                u.user_id,
                u.discord_id,
                u.cf_handle,
                COALESCE(SUM(sh.score), 0) as total_score
            FROM users u
            LEFT JOIN score_history sh ON u.user_id = sh.user_id
            GROUP BY u.user_id, u.discord_id, u.cf_handle
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


# Bot contest functions using existing tables
async def create_bot_contest(name: str, duration: int, start_time: str, unix_timestamp: int = None) -> int:
    """Create a new bot contest and return the contest_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # If unix_timestamp not provided, calculate it from start_time
        if unix_timestamp is None and start_time:
            try:
                from datetime import datetime
                start_time_dt = datetime.fromisoformat(start_time)
                unix_timestamp = int(start_time_dt.timestamp())
            except:
                unix_timestamp = None
        
        # Check if we need to add the unix_timestamp column
        cursor = await db.execute("PRAGMA table_info(contests)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]
        
        if 'unix_timestamp' not in column_names:
            await db.execute("ALTER TABLE contests ADD COLUMN unix_timestamp INTEGER")
            await db.commit()
        
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
        cursor = await db.execute(
            "SELECT solves_info FROM contests WHERE contest_id = ?",
            (contest_id,)
        )
        row = await cursor.fetchone()
        if not row or not row[0]:
            return {}
        try:
            return json.loads(row[0])
        except:
            return {}

async def update_contest_solves_info(contest_id: int, solves_info: Dict) -> None:
    """Update solves info for a contest."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE contests SET solves_info = ? WHERE contest_id = ?",
            (json.dumps(solves_info), contest_id)
        )
        await db.commit()


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

async def update_problems_solved(discord_id: str, session) -> tuple[bool, int]:
    """Update problems solved count for a user using Codeforces API."""
    import aiohttp
    
    # Get user's CF handle
    user = await get_user_by_discord(discord_id)
    if not user:
        return False, 0
    
    cf_handle = user['cf_handle']
    
    try:
        # Get user's submissions from Codeforces API
        url = f"https://codeforces.com/api/user.status?handle={cf_handle}"
        async with session.get(url) as response:
            if response.status != 200:
                return False, 0
            
            data = await response.json()
            if data.get("status") != "OK":
                return False, 0
        
        # Count unique solved problems
        solved_problems = set()
        for submission in data["result"]:
            if submission.get("verdict") == "OK":
                problem = submission.get("problem", {})
                contest_id = problem.get("contestId")
                index = problem.get("index")
                if contest_id and index:
                    solved_problems.add(f"{contest_id}{index}")
        
        problems_count = len(solved_problems)
        
        # Update the database (we'll add a problems_solved field if needed)
        async with aiosqlite.connect(DB_PATH) as db:
            # Check if problems_solved column exists
            cursor = await db.execute("PRAGMA table_info(users)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            
            if 'problems_solved' not in column_names:
                await db.execute("ALTER TABLE users ADD COLUMN problems_solved INTEGER DEFAULT 0")
                await db.commit()
            
            # Update the count
            await db.execute(
                "UPDATE users SET problems_solved = ? WHERE discord_id = ?",
                (problems_count, discord_id)
            )
            await db.commit()
        
        return True, problems_count
        
    except Exception as e:
        print(f"Error updating problems solved for {cf_handle}: {e}")
        return False, 0

async def get_user_info(discord_id: str, session=None) -> Dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row  # <-- Add this line
        cursor = await db.execute(
            "SELECT discord_id, cf_handle, Number_of_problem_solved FROM users WHERE discord_id = ?",
            (discord_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return {"exists": False}
        return {
            "exists": True,
            "discord_id": row["discord_id"],
            "cf_handle": row["cf_handle"],
            "Number_of_problem_solved": row["Number_of_problem_solved"]
        }

async def get_user_score(discord_id: str) -> Dict:
    """Get user scoring information."""
    user = await get_user_by_discord(discord_id)
    if not user:
        return {"exists": False}
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Check if scoring columns exist and add them if needed
        cursor = await db.execute("PRAGMA table_info(users)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]
        
        scoring_columns = ['daily_points', 'weekly_points', 'monthly_points', 'overall_points', 'problems_solved', 'last_updated']
        for col in scoring_columns:
            if col not in column_names:
                await db.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0")
        await db.commit()
        
        # Get the scoring data
        cursor = await db.execute(
            "SELECT daily_points, weekly_points, monthly_points, overall_points, problems_solved, last_updated FROM users WHERE discord_id = ?",
            (discord_id,)
        )
        row = await cursor.fetchone()
        
        if not row:
            return {"exists": False}
        
        return {
            "exists": True,
            "codeforces_name": user['cf_handle'],
            "daily_points": row['daily_points'] or 0,
            "weekly_points": row['weekly_points'] or 0,
            "monthly_points": row['monthly_points'] or 0,
            "overall_points": row['overall_points'] or 0,
            "solved_problems": row['problems_solved'] or 0,
            "last_updated": row['last_updated'] or 0
        }

async def get_custom_leaderboard(category: str, limit: int = 10) -> List[Dict]:
    """Get leaderboard for different scoring categories."""
    # Map category to column name
    category_map = {
        "daily": "daily_points",
        "weekly": "weekly_points", 
        "monthly": "monthly_points",
        "overall": "overall_points",
        "solved": "problems_solved"
    }
    
    column = category_map.get(category, "overall_points")
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Check if the scoring columns exist
        cursor = await db.execute("PRAGMA table_info(users)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]
        
        if column not in column_names:
            # Add missing columns
            scoring_columns = ['daily_points', 'weekly_points', 'monthly_points', 'overall_points', 'problems_solved']
            for col in scoring_columns:
                if col not in column_names:
                    await db.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0")
            await db.commit()
        
        # Get the leaderboard
        cursor = await db.execute(f"""
            SELECT 
                discord_id,
                cf_handle as codeforces_name,
                {column} as score,
                ROW_NUMBER() OVER (ORDER BY {column} DESC) as rank
            FROM users 
            WHERE {column} > 0
            ORDER BY {column} DESC 
            LIMIT ?
        """, (limit,))
        
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

# Leaderboard-specific helper functions
async def get_leaderboard_user(discord_id: str) -> Dict:
    """Get or create a leaderboard user with scoring fields."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Check if leaderboard columns exist and add them if needed
        cursor = await db.execute("PRAGMA table_info(users)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]
        
        leaderboard_columns = ['daily_score', 'weekly_score', 'monthly_score', 'overall_score']
        for col in leaderboard_columns:
            if col not in column_names:
                await db.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0")
        await db.commit()
        
        # Get user, create if doesn't exist
        cursor = await db.execute(
            "SELECT discord_id, cf_handle, daily_score, weekly_score, monthly_score, overall_score FROM users WHERE discord_id = ?",
            (discord_id,)
        )
        row = await cursor.fetchone()
        
        if not row:
            await db.execute(
                "INSERT INTO users (discord_id, daily_score, weekly_score, monthly_score, overall_score) VALUES (?, 0, 0, 0, 0)",
                (discord_id,)
            )
            await db.commit()
            return {
                "discord_id": discord_id,
                "cf_handle": None,
                "daily_score": 0,
                "weekly_score": 0,
                "monthly_score": 0,
                "overall_score": 0
            }
        
        return dict(row)

async def add_leaderboard_points(discord_id: str, points: int, cf_handle: str = None) -> None:
    """Add points to all leaderboard categories for a user."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Ensure leaderboard columns exist
        cursor = await db.execute("PRAGMA table_info(users)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]
        
        leaderboard_columns = ['daily_score', 'weekly_score', 'monthly_score', 'overall_score']
        for col in leaderboard_columns:
            if col not in column_names:
                await db.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0")
        await db.commit()
        
        # Check if user exists
        cursor = await db.execute("SELECT discord_id FROM users WHERE discord_id = ?", (discord_id,))
        user = await cursor.fetchone()
        
        if not user:
            # Create user with points
            await db.execute(
                "INSERT INTO users (discord_id, cf_handle, daily_score, weekly_score, monthly_score, overall_score) VALUES (?, ?, ?, ?, ?, ?)",
                (discord_id, cf_handle, points, points, points, points)
            )
        else:
            # Update existing user scores
            update_query = "UPDATE users SET daily_score = daily_score + ?, weekly_score = weekly_score + ?, monthly_score = monthly_score + ?, overall_score = overall_score + ?"
            params = [points, points, points, points]
            
            if cf_handle:
                update_query += ", cf_handle = ?"
                params.append(cf_handle)
            
            update_query += " WHERE discord_id = ?"
            params.append(discord_id)
            
            await db.execute(update_query, params)
        
        await db.commit()

async def get_leaderboard_by_type(score_type: str, limit: int = 20) -> List[Dict]:
    """Get leaderboard for a specific score type."""
    valid_types = ["daily_score", "weekly_score", "monthly_score", "overall_score"]
    if score_type not in valid_types:
        score_type = "overall_score"
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Ensure leaderboard columns exist
        cursor = await db.execute("PRAGMA table_info(users)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]
        
        leaderboard_columns = ['daily_score', 'weekly_score', 'monthly_score', 'overall_score']
        for col in leaderboard_columns:
            if col not in column_names:
                await db.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0")
        await db.commit()
        
        cursor = await db.execute(f"""
            SELECT discord_id, {score_type} as score
            FROM users 
            WHERE {score_type} > 0 
            ORDER BY {score_type} DESC 
            LIMIT ?
        """, (limit,))
        
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def reset_leaderboard_scores(score_type: str) -> None:
    """Reset specific leaderboard scores to 0."""
    valid_types = ["daily_score", "weekly_score", "monthly_score", "overall_score"]
    if score_type not in valid_types:
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE users SET {score_type} = 0", ())
        await db.commit()

async def get_user_leaderboard_rank(discord_id: str, score_type: str) -> int:
    """Get user's rank in a specific leaderboard."""
    valid_types = ["daily_score", "weekly_score", "monthly_score", "overall_score"]
    if score_type not in valid_types:
        return 0
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(f"""
            SELECT COUNT(*) + 1 as rank FROM users 
            WHERE {score_type} > (SELECT {score_type} FROM users WHERE discord_id = ?)
        """, (discord_id,))
        row = await cursor.fetchone()
        return row['rank'] if row else 0

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

async def create_challenge_history_table() -> None:
    """Create challenge history table if it doesn't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS challenge_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                challenge_id TEXT,
                discord_id TEXT,
                cf_handle TEXT,
                problem_name TEXT,
                problem_link TEXT,
                finish_time INTEGER,
                rank INTEGER,
                points INTEGER,
                timestamp INTEGER
            )
        ''')
        await db.commit()

async def add_challenge_history(challenge_id: str, discord_id: str, cf_handle: str, 
                               problem_name: str, problem_link: str, finish_time: int, 
                               rank: int, points: int, timestamp: int) -> None:
    """Add an entry to challenge history."""
    await create_challenge_history_table()
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO challenge_history (challenge_id, discord_id, cf_handle, problem_name, problem_link, finish_time, rank, points, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (challenge_id, discord_id, cf_handle, problem_name, problem_link, finish_time, rank, points, timestamp)
        )
        await db.commit()

async def add_contest_score_entry(contest_id: int, discord_id: str, cf_handle: str, score: int = 0, problem_solved: int = 0) -> None:
    """Add an entry to contest_scores table."""
    user_data = await get_user_by_discord(discord_id)
    if not user_data:
        raise ValueError(f"User with discord_id {discord_id} not found")
    user_id = user_data['user_id']
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO contest_scores (contest_id, user_id, cf_handle, problem_solved, score) VALUES (?, ?, ?, ?, ?)",
            (contest_id, user_id, cf_handle, problem_solved, score)
        )
        await db.commit()

async def increment_user_solved_count(discord_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET Number_of_problem_solved = Number_of_problem_solved + 1 WHERE discord_id = ?",
            (discord_id,)
        )
        await db.commit()

async def migrate_challenges_table() -> None:
    """Migrate challenges table to new format."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Step 1: Rename old table
        await db.execute("ALTER TABLE challenges RENAME TO challenges_old")
        
        # Step 2: Create new challenges table
        await db.execute("""
            CREATE TABLE challenges (
                challenge_id INTEGER PRIMARY KEY AUTOINCREMENT,
                problem_link TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Step 3: Copy data from old table to new table
        await db.execute("""
            INSERT INTO challenges (challenge_id, problem_link, created_at)
            SELECT challenge_id, problem_id, created_at FROM challenges_old
        """)
        
        # Step 4: Drop old table
        await db.execute("DROP TABLE challenges_old")
        
        await db.commit()
