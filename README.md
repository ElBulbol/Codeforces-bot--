# MUST CPC Discord Bot

This bot provides several utilities for the MUST CPC community Discord server, including fetching Codeforces problems and managing roles.

### Setup
Before running the bot, create a `.env` file in the root directory and add your Discord bot token like so:
```
DISCORD_TOKEN="your_bot_token_here"
```

### Download the requirements
```shell
pip install -r requirements.txt
```

### Run the bot
```shell
python bot.py
```

----
**Bot Commands**
`/help` – Shows a list of all available commands.
`/pick_problem [tags] [rating]` – Get a random Codeforces problem. Tags can be comma-separated.
`/assign_role <member>` – (MOD) Give CP role.
`/remove_role <member>` – (MOD) Remove CP role.
`/contest_notify <message>` – (MOD) DM all CP members & mention in contest channel.
`/hello` – Greet the user.
`/hello_eyad` – Greet Eyad.

**Auto Actions**
- Welcomes new members via DM.
- Replies “I agree” if message contains “eyad m3aras”.
