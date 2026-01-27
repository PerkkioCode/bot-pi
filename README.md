# bot-pi

Simple Discord bot starter with a few prefix commands.

## Setup
1) Create a Discord application + bot at https://discord.com/developers/applications
2) Copy your bot token.
3) Enable the **Message Content Intent** in the bot settings.
4) Invite the bot to a server with the **bot** scope.

## Run
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and add your token
python bot.py
```

## Commands
- `!ping` -> Pong!
- `!help` -> list commands
- `!name` -> bot name
- `!say <text>` -> repeats text

## Config
Use `.env` to customize:
- `DISCORD_TOKEN` (required)
- `BOT_NAME` (default: Dip)
- `BOT_PREFIX` (default: `!`)
