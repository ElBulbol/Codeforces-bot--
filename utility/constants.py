"""
Permissions and role/channel management utilities for the Discord bot.
This module contains all role IDs and channel IDs that are used across
different cogs for access control.
"""

# ============================================================================
# ROLE CONSTANTS
# ============================================================================

# Role Names (string-based roles)
CP_ROLE_NAME = "staff"
MOD_ROLE_NAME = "staff"
AUTH_ROLE_NAME = "staff"

# Role IDs (ID-based roles)
MENTOR_ROLE_ID = 906647154687377448
PARTICIPANT_ROLE_ID = 906647154687377448
AUTH_ROLE_ID = 906647154687377448

# ============================================================================
# CHANNEL CONSTANTS
# ============================================================================

# Contest and announcement channels
CONTEST_CHANNEL_ID = 637013889439105058  # bot-testing channel (used in roles.py and contest_builder.py)
CHALLENGE_CHANNEL_ID = 637013889439105058  # bot-testing channel (used in roles.py and contest_builder.py)
ANNOUNCEMENT_CHANNEL_ID = 637013889439105058  # Same as contest channel (contest_builder.py)
ANNOUNCEMENT_CHANNEL_ID_ALT = 637013889439105058  # Alternative announcement channel (contest_interactions.py)