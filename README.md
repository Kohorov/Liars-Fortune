# Liar's Fortune

A Telegram bot for playing a multiplayer bluffing card game, based on Liar's Bar. Written in Python with aiogram 3 and PostgreSQL.

## Features

- Private games with invite links, or group games with `/newgame`
- 2 to 4 players per game
- Russian roulette elimination (6 chambers, 1 bullet)
- Special cards: Universal and Joker
- Coins and referral system
- Tournaments
- English, Russian and Uzbek
- Admin panel (stats, broadcasts, users, balances, game archive)

## Rules

Each player gets 5 cards and a card on the table sets the suit. On your turn you play 1 to 3 cards face down and claim they match. The next player can continue or call "Liar". If you told the truth, the caller pulls the trigger. If you lied, you do. Last player alive wins.

## Setup

### Prerequisites

- Python 3.11+
- PostgreSQL
- Bot token from @BotFather

### Install

```
git clone https://github.com/Kohorov/Liars-Fortune.git
cd Liars-Fortune
pip install -r requirements.txt
```

### Database

Create an empty database. Tables are created automatically on first run.

```
createdb -U postgres liars_fortune
```

### Configuration

Copy `.env.example` to `.env` and fill it in:

- `BOT_TOKEN` - token from @BotFather
- `MAIN_ADMIN_ID` - your Telegram user ID
- `MAIN_ADMIN_IDS` - extra admins, comma-separated (optional)
- `SUPPORT_CHAT_ID` - chat that receives support messages (optional)
- `CHANNEL_URL` - channel link used in broadcasts (optional)
- `PG_HOST`, `PG_PORT`, `PG_DB`, `PG_USER`, `PG_PASSWORD` - database connection

### Run

```
python main.py
```

## Commands

- `/start` - main menu (private chat)
- `/newgame` - open a game lobby (group)
- `/stopgame` - stop the current game (group, creator only)
- `/language` - change the group language (group, admins only)

## License

MIT
