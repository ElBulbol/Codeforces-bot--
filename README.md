# MUST CPC Discord Bot

A comprehensive Discord bot designed for the MUST Competitive Programming Club, offering Codeforces integration, challenge management, leaderboards, and community engagement features.

## Table of Contents
- Features
- Project Structure
- Setup
- Commands
- Auto Actions
- Contributing

##  Features

- **Codeforces Integration**
  - Link Discord accounts to Codeforces handles
  - Fetch random or specific problems based on tags and difficulty ratings
  - Track user progress and submissions

- **Challenge System**
  - Create challenges with specific problems
  - Track participants and winners
  - Award points for completed challenges

- **Contests Management**
  - Create temporary contests with custom parameters
  - Maintain separate leaderboards for each contest
  - Join/leave contest functionality

- **Leaderboards**
  - Daily, weekly, monthly, and all-time leaderboards
  - Personal statistics tracking
  - Ranking system for active members

- **Role Management**
  - Assign and remove competitive programming roles
  - Automated role assignments based on activity

## Setup

### 1. Environment Variables
Create a [`.env`](.env ) file in the root directory with:
```
DISCORD_TOKEN="your_bot_token_here"
```

### 2. Install Dependencies
```shell
pip install -r requirements.txt
```

### 3. Database Setup
The bot uses a local database stored in the `db/` directory (automatically created on first run).

### 4. Run the Bot
```shell
python bot.py
```

## Commands

### General Commands
- `/help` – Shows all available commands

### Codeforces Commands
- `/authenticate <handle>` – Link Discord account to Codeforces handle
- `/de_link_cf [user]` – Unlink Codeforces account
- `/challenge <members> [tags] [rating]` – Challenge users to solve a problem
- `/challenge info <challenge_id>` – Get detailed information about a challenge

### Leaderboard Commands
- `/daily_leaderboard` – Show daily leaderboard
- `/weekly_leaderboard` – Show weekly leaderboard
- `/monthly_leaderboard` – Show monthly leaderboard
- `/overall_leaderboard` – Show all-time leaderboard
- `/my_stats` – Show personal statistics

### Management Commands (Moderators Only)
- `/assign_role <member>` – Assign CP role to a member
- `/remove_role <member>` – Remove CP role from a member
- `/contest_notify <message>` – Notify all CP members about a contest

### Contest Commands
- `/create_leader_board <name> <time> <problems>` – Create a temporary contest
- `/leader-board-temp [contest_id]` – Show contest leaderboard
- `/join-contest <contest_id>` – Join a temporary contest
- `/end-contest <contest_id>` – End a contest early

---

We made it to all competitive programmers in our community <3

