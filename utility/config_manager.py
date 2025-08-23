import aiosqlite
from typing import Optional, Dict

# --- Database Path ---
# This should point to the same database file used by the setup commands.
DB_PATH = "db/roles_and_channels.db"

# --- Cache ---
# A simple cache to reduce database queries for the same guild.
_settings_cache: Dict[int, Dict] = {}

async def get_guild_settings(guild_id: int) -> Dict:
    """
    Fetches all settings for a given guild from the database and caches the result.
    
    Args:
        guild_id: The ID of the guild to fetch settings for.
        
    Returns:
        A dictionary containing the settings, or an empty dictionary if not found.
    """
    if guild_id in _settings_cache:
        return _settings_cache[guild_id]
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
            settings = await cursor.fetchone()
            
            if settings:
                settings_dict = dict(settings)
                _settings_cache[guild_id] = settings_dict
                return settings_dict
    except aiosqlite.OperationalError as e:
        # NOTE: If you add new columns for role names, you may need to recreate your database table.
        # The table in `setup_commands.py` should be updated to include:
        # cp_role_name TEXT, mod_role_name TEXT, auth_role_name TEXT, mentor_role_name TEXT
        print(f"Database error (is the table created and up-to-date?): {e}")

    return {}

# --- Role ID Getters ---

async def get_cp_role_id(guild_id: int) -> Optional[int]:
    """Fetches the Competitive Programming (Participant) role ID for a guild."""
    settings = await get_guild_settings(guild_id)
    return settings.get("cp_role_id")

async def get_mod_role_id(guild_id: int) -> Optional[int]:
    """Fetches the Moderator role ID for a guild."""
    settings = await get_guild_settings(guild_id)
    return settings.get("mod_role_id")

async def get_auth_role_id(guild_id: int) -> Optional[int]:
    """Fetches the Authenticated role ID for a guild."""
    settings = await get_guild_settings(guild_id)
    return settings.get("auth_role_id")

async def get_mentor_role_id(guild_id: int) -> Optional[int]:
    """Fetches the Mentor role ID for a guild."""
    settings = await get_guild_settings(guild_id)
    return settings.get("mentor_role_id")


# --- Channel Getters ---

async def get_contest_channel_id(guild_id: int) -> Optional[int]:
    """Fetches the Contest channel ID for a guild."""
    settings = await get_guild_settings(guild_id)
    return settings.get("contest_channel_id")

async def get_challenge_channel_id(guild_id: int) -> Optional[int]:
    """Fetches the Challenge channel ID for a guild."""
    settings = await get_guild_settings(guild_id)
    return settings.get("challenge_channel_id")

async def get_announcement_channel_id(guild_id: int) -> Optional[int]:
    """Fetches the Announcement channel ID for a guild."""
    settings = await get_guild_settings(guild_id)
    return settings.get("announcement_channel_id")
