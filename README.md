# MUST CPC Discord Bot

Engineered & built a full-fledged Competitive Programming platform for our ICPC community.

## Features

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

- **Role & Channel Management**
  - Assign and remove competitive programming roles
  - Automated role assignments based on activity
  - Configure essential channels for contests, challenges, and announcements

## Installation & Setup

0. **Install prerequisits**
    - [Python](https://www.python.org/downloads) 3.7 or higher
    - [Git](https://git-scm.com/downloads)
    - Make sure they both are added to your `PATH`.

1. **Clone the repository & change directory**
    ```shell
    git clone https://github.com/ElBulbol/MUST-CPC-BOT.git
    cd MUST-CPC-BOT
    ```

2. **(Optional) Create a virtual environment and activate it**
   ```shell
    python -m venv venv
    # On Windows
    .\venv\Scripts\activate
    # On macOS/Linux
    source venv/bin/activate
   ```

3. **Install the required dependencies**
    ```shell
    pip install -r requirements.txt
    ```

4. **Environment Variables**
    - Go to [Discord Developer Portal](https://discord.com/developers/applications) → New Application → Add Bot, then copy the Bot Token from the "Bot" tab.
    - Create a `.env` file in the root directory and put your token like the following example:
    ```
    DISCORD_TOKEN="your_bot_token_here"
    ```

5. **Run the Bot**
   ```shell
   python bot.py
   ```

## Commands & Usage

> Note: `<>` denotes required arguments and `[]` denotes optional arguments.

### General
- `/help` – Shows a list of all available commands.
- `/authenticate` – Link your Discord account to a Codeforces handle (opens a modal).
- `/deauthenticate [user]` – Remove Codeforces link for yourself or a specified user (mods can deauthenticate others).
- `/pick_problem [tags] [rating] [min_solved]` – Pick a Codeforces problem by tags, optional rating, and minimum solved count.
- `/show_status [user]` – Display a user's Codeforces profile and bot statistics.

### Server Setup (Admin only)
- `/setroles <cp_role> <mod_role> <auth_role> <mentor_role>` – Configure server roles used by the bot.
- `/setchannels <contest_channel> <challenge_channel> <announcement_channel>` – Configure server channels used by the bot.
- `/viewsettings` – View the currently configured role and channel settings for the server.

### Contests
- `/contest create` – Open the interactive contest builder (mentor role required).
- `/contest start <contest_id>` – Immediately start a pending contest (mentor role required).
- `/contest end <contest_id>` – Immediately end an active contest (mentor role required).
- `/contest history` – List all past contests with IDs and dates.
- `/contest info <contest_id>` – Show contest information and problems.
- `/contest leaderboard [category] [limit]` – View contest leaderboard (categories: daily, weekly, monthly, overall).
- `/contest notify <message>` – Send a notification to CP members and announcement channel (mentor role required).

### Challenges
- `/challenge create <members> [tags] [rating]` – Create a challenge targeting specified members.
- `/challenge history [user] [limit]` – View recent challenge history (optionally for a specific user).
- `/challenge info <challenge_id>` – Get detailed information about a specific challenge.
- `/challenge leaderboard [category] [limit]` – View the challenges leaderboard (categories: daily, weekly, monthly, overall, solved).

### Roles
- `/role assign <member>` – Assign the CP role to a member (moderator role required).
- `/role remove <member>` – Remove the CP role from a member (moderator role required).

## Contributing

Pull requests and suggestions are welcome!  
We made it for all competitive programmers in . 

----

### Huge shout-out to [MAyman007](https://github.com/MAyman007) for handeling the back-end and hosting.

---
