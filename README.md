# MarketAlert

MarketAlert is a lightweight Discord bot for economic event notifications. It fetches upcoming calendar data through `investpy`, stores the dataset locally, and sends reminder messages to a configured Discord thread before scheduled releases.

## Introduction

MarketAlert is built for Discord communities, trading groups, and internal teams that want a simple way to monitor macroeconomic events such as CPI, interest-rate decisions, and other scheduled announcements.

The current version focuses on a single responsibility:

- Fetch economic calendar data
- Persist the result as a local CSV dataset
- Schedule reminders from that dataset
- Send notifications to Discord automatically

## Current Capabilities

- Automated economic calendar collection via `investpy`
- CSV export to `data/calendar.csv`
- Reminder delivery 10 minutes before each event
- Daily refresh of the schedule at `00:00` in `UTC+8`
- Discord thread-based notification workflow

## Project Structure

```text
MarketAlert/
├── README.md
├── LICENSE
└── MarketAlert/
    ├── DiscordBot.py
    ├── MarketWorm.py
    └── config.json
```

### Core Modules

- `MarketAlert/DiscordBot.py`
  Starts the Discord client, loads the calendar file, creates reminder tasks, and sends alerts.
- `MarketAlert/MarketWorm.py`
  Requests economic calendar data from `investpy` and writes the result to `data/calendar.csv`.
- `MarketAlert/config.json`
  Stores the bot token and the Discord target identifiers.

## Tech Stack

- Python `3.10+`
- `discord.py`
- `investpy`

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/CodeRyoStudio/MarketAlert.git
cd MarketAlert/MarketAlert
```

### 2. Install dependencies

```bash
pip install discord.py investpy
```

### 3. Configure the bot

Edit `config.json` with your Discord values:

```json
{
  "discord_bot_token": "YOUR_BOT_TOKEN",
  "Guild": 123456789012345678,
  "Thread": 123456789012345678
}
```

### 4. Run the bot

```bash
python3 DiscordBot.py
```

## Configuration Reference

| Key | Type | Description |
| --- | --- | --- |
| `discord_bot_token` | `string` | Discord bot token |
| `Guild` | `integer` | Discord server ID |
| `Thread` | `integer` | Discord thread ID used for alert delivery |

## Runtime Flow

1. `DiscordBot.py` loads `config.json`
2. `DiscordBot.py` starts `MarketWorm.py`
3. `MarketWorm.py` fetches calendar data from `investpy`
4. The result is saved to `data/calendar.csv`
5. `DiscordBot.py` reads the CSV and creates reminder tasks
6. The bot posts an alert to the configured Discord thread when the target time is reached

## Operational Notes

- The bot should be started from the `MarketAlert/` directory
- Events marked as `Tentative` are normalized to `00:00`
- Reminder timing is currently fixed at `10 minutes before release`
- The scheduler refreshes automatically once per day
- Runtime behavior currently depends on local files and the working directory

## Current Limitations

- No slash-command support in the current implementation
- No in-Discord configuration workflow
- Notification filters are static
- The current repository does not yet include a packaged deployment flow or environment-based configuration

## Roadmap Direction

The following improvements would make the project more production-ready:

- Slash commands for setup and administration
- Configurable reminder timing
- Event filtering by country, currency, or importance
- Better deployment and environment management
- Logging, error handling, and health monitoring improvements

## License

Released under the [MIT License](LICENSE).
