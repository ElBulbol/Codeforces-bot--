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

## Commands

### General
- `/help` – Shows all available commands

### Codeforces
- `/authenticate <handle>` – Link Discord account to Codeforces handle
- `/de_link_cf [user]` – Unlink Codeforces account
- `/challenge <members> [tags] [rating]` – Challenge users to solve a problem
- `/challenge info <challenge_id>` – Get detailed information about a challenge

### Leaderboard
- `/daily_leaderboard` – Show daily leaderboard
- `/weekly_leaderboard` – Show weekly leaderboard
- `/monthly_leaderboard` – Show monthly leaderboard
- `/overall_leaderboard` – Show all-time leaderboard
- `/my_stats` – Show personal statistics

## Management Commands (Moderators Only)

These commands are available for server administrators and are implemented in `server_setup.py`:

- `/setroles`
  - Set the essential roles for the server:
    - CP Role (Competitive Programming participants)
    - Moderator Role
    - Authenticated Role (after authentication)
    - Mentor Role (can create contests/challenges)

- `/setchannels`
  - Set the essential channels for the server:
    - Contest Channel (for contest announcements and running contests)
    - Challenge Channel (for posting challenges)
    - Announcement Channel (for general bot announcements)

- `/viewsettings`
  - View the current role and channel settings for the server.

## Contributing

Pull requests and suggestions are welcome!  
We made it for all competitive programmers in . 

----

### Huge shout-out to [MAyman007](https://github.com/MAyman007) for handeling the back-end and hosting.

---