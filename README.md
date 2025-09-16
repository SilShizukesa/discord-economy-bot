# Discord Economy Bot 🎮💰

A custom Discord bot with an economy system, fun jobs, gambling games, and more — built with [discord.py](https://discordpy.readthedocs.io).

## Features
- `/work` — earn money by doing odd jobs (common → secret rarity, with flavor text + embeds).
- Job progress tracking + role unlocks as you climb worker tiers.
- Tips system — chance to earn extra money multipliers.
- `/balance` — check your wallet balance.
- `/leaderboard` — see who has the most money in the server.
- `/leaderboardjob` — see who has worked the most jobs.
- `/coinflip` — gamble your money on heads or tails.
- `/roulette` — full roulette game with multiple players in a single round.
- Fun joke commands like `/fish` (that takes money instead of giving it 😅).

## Setup

### Requirements
- Python 3.10+ (tested on 3.13)
- [discord.py](https://pypi.org/project/discord.py/)
- [python-dotenv](https://pypi.org/project/python-dotenv/)

Install dependencies:
```bash
pip install -r requirements.txt
Environment Variables
Create a .env file in the project root:

ini
Copy code
DISCORD_TOKEN=your-bot-token-here
⚠️ Never commit your .env file to GitHub!

Running the Bot
bash
Copy code
python bot.py
Hosting
This bot can run locally or be deployed on platforms like Railway for 24/7 uptime.
Add your DISCORD_TOKEN as a secret in the platform’s environment settings.

## License
This project is licensed under the MIT License.  
See the [LICENSE](LICENSE) file for details.
