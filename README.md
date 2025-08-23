# MUST CPC Discord Bot

This bot provides several utilities for the MUST CPC community Discord server, including fetching Codeforces problems, managing roles, and organizing challenges.

---

## Features
- Fetch random or specific Codeforces problems based on tags and ratings.
- Link and unlink Codeforces accounts to Discord users.
- Organize challenges for solving Codeforces problems.
- Manage roles for competitive programming (CP) members.
- Track leaderboards for daily, weekly, monthly, and overall scores.
- Notify CP members about contests and challenges.

---

## Setup

### 1. Environment Variables
Create a `.env` file in the root directory and add your Discord bot token:
```
DISCORD_TOKEN="your_bot_token_here"
```

### 2. Install Dependencies
Run the following command to install the required Python packages:
```shell
pip install -r requirements.txt
```

### 3. Run the Bot
Start the bot using:
```shell
python bot.py
```

---

## Commands

### General Commands
- `/help` – Shows a list of all available commands.
- `/hello` – Greet the user.
- `/hello_eyad` – Greet Eyad.

### Codeforces Commands
- `/link_cf <handle>` – Link your Discord account to a Codeforces handle.
- `/de_link_cf [user]` – Unlink your Codeforces account (or another user's account if you are a moderator).
- `/challenge <members> [tags] [rating]` – Challenge users with the `Auth` role to solve a Codeforces problem. Specify tags and rating for the problem or use "random".

### Leaderboard Commands
- `/daily_leaderboard` – Show the daily leaderboard.
- `/weekly_leaderboard` – Show the weekly leaderboard.
- `/monthly_leaderboard` – Show the monthly leaderboard.
- `/overall_leaderboard` – Show the all-time leaderboard.
- `/my_stats` – Show your personal leaderboard statistics.

### Management Commands (Moderators Only)
- `/assign_role <member>` – Assign the CP role to a member.
- `/remove_role <member>` – Remove the CP role from a member.
- `/contest_notify <message>` – Notify all CP members about a contest.

### Temporary Contest Commands
- `/create_leader_board <name> <time> <problems>` – Create a temporary contest with a separate leaderboard.
- `/leader-board-temp [contest_id]` – Show the leaderboard for a temporary contest.
- `/join-contest <contest_id>` – Join a temporary contest.
- `/end-contest <contest_id>` – End a temporary contest early.

---

## Auto Actions
- Welcomes new members via DM.
- Replies “I agree” if a message contains “eyad m3aras”.

---

## File Structure
```
.env
.gitignore
bot.py
cf_links.db
cf_links.json
current-request.json
discord.log
leaderboard.db
README.md
requirements.txt
temp_contests.db
cogs/
    codeforces.py
    leaderboard.py
    management.py
    misc.py
    temp_contests.py
```

---

## Notes
- Ensure the `cf_links.json` file exists to store Codeforces handle links.
- The bot uses SQLite databases (`leaderboard.db`, `temp_contests.db`) for storing leaderboard and contest data.
- Logs are stored in `discord.log` for debugging purposes.
