# --- imports & basic setup ---
import discord
from discord.ext import commands
import random
import json
import os
from discord import app_commands
import asyncio
from dotenv import load_dotenv
import os



# Version of the bot
BOT_VERSION = "V0.0.01"


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
ANNOUNCE_CHANNEL_ID = 1417338592359092235  # paste your channel ID here
WORK_CHANNEL_ID = 1417332114453430282  # replace with your work channel ID
ROULETTE_CHANNEL_ID = 1417369961172697090  # replace with your roulette channel ID


ROLE_TIERS = [
    # Worker path
    {"rarity": "common", "required": 100, "role_id": 1417347155617644545, "name": "Worker 2", "prev": None},
    {"rarity": "common", "required": 400, "role_id": 1417347223875751976, "name": "Worker 3", "prev": 1417347155617644545},
    # Uncommon path
    {"rarity": "uncommon", "required": 100, "role_id": 1417347300807938150, "name": "Worker 4", "prev": 1417347223875751976},
    # Hard Worker path
    {"rarity": "rare", "required": 200, "role_id": 1417347359196577913, "name": "Hard Worker 1", "prev": 1417347300807938150},
    {"rarity": "epic", "required": 50, "role_id": 1417347412845924372, "name": "Hard Worker 2", "prev": 1417347359196577913},
    # Job Master path
    {"rarity": "legendary", "required": 25, "role_id": 1417347538968903855, "name": "Job Master 1", "prev": 1417347412845924372},
    {"rarity": "secret", "required": 1, "role_id": 1417347593700380703, "name": "Job Master 2", "prev": 1417347538968903855},
    # Employed — total jobs milestone
    {"rarity": "total", "required": 10000, "role_id": 1417348260926062712, "name": "Employed", "prev": 1417347593700380703}
]


# default values
SPECIAL_CHANCE = 0.02
TIP_BASE_CHANCE = 0.25
DEV_CHANCE_DENOM = 7777   # dev job roll (1 in this number)


BALANCE_FILE = "balances.json"

if os.path.exists(BALANCE_FILE):
    with open(BALANCE_FILE, "r") as f:
        data = json.load(f)
        balances = {int(k): float(v) for k, v in data.get("balances", {}).items()}
        job_counts = {int(k): v for k, v in data.get("job_counts", {}).items()}
else:
    balances = {}
    job_counts = {}

# Global roulette state
roulette_game = {
    "active": False,
    "bets": [],
    "channel_id": None
}


def save_balances():
    with open(BALANCE_FILE, "w") as f:
        json.dump({
            "balances": balances,
            "job_counts": job_counts
        }, f)


# --- flavor & colors for embeds ---
flavor_texts = {
    "common":    "Wow, a **Common job**? Better than nothing…",
    "uncommon":  "Nice, an **Uncommon job**! You’re moving up.",
    "rare":      "Whoa, a **Rare job**! That’s some serious cash.",
    "epic":      "Incredible! You scored an **Epic job**!",
    "legendary": "✨ **Legendary job!!** You’re rolling in it! ✨",
    "secret":    "💎 **SECRET JOB?!** You just hit the jackpot!",
    "dev":       "👀 **DEV JOB** — how did you get this? Are you cheating? What? Who are you?!?!"
}

rarity_colors = {
    "common":    discord.Color.light_gray(),
    "uncommon":  discord.Color.green(),
    "rare":      discord.Color.blue(),
    "epic":      discord.Color.purple(),
    "legendary": discord.Color.orange(),
    "secret":    discord.Color.gold(),
    "dev":       discord.Color.red()
}

# Emojis per rarity for announcements
rarity_emojis = {
    "common": "🪱",
    "uncommon": "🌿",
    "rare": "💎",
    "epic": "🌌",
    "legendary": "🔥",
    "secret": "💰",
    "dev": "👀",
    "toilet": "🚽",
    "glitch": "⚡",
    "flash-sale": "🛒"
}

async def update_job_progress(interaction: discord.Interaction, rarity: str):
    user_id = interaction.user.id

    # increment counts
    counts = job_counts.get(user_id, {
        "common": 0, "uncommon": 0, "rare": 0,
        "epic": 0, "legendary": 0, "secret": 0,
        "special": 0
    })
    counts[rarity] = counts.get(rarity, 0) + 1
    job_counts[user_id] = counts
    save_balances()

    # compute total jobs
    total_jobs = sum(counts.values())

    member = interaction.user
    guild = interaction.guild
    if not guild:
        return

    for tier in ROLE_TIERS:
        # normal rarity tiers
        if tier["rarity"] != "total":
            if tier["rarity"] == rarity and counts[rarity] >= tier["required"]:
                role = guild.get_role(tier["role_id"])
                if not role:
                    continue

                # skip if they already have this role
                if role in member.roles:
                    continue

                # check if they need a previous role
                if tier["prev"] is not None:
                    prev_role = guild.get_role(tier["prev"])
                    if prev_role not in member.roles:
                        continue

                await member.add_roles(role)

                # 🎉 announce in the server, not DM
                await interaction.channel.send(
                    f"🎉 {interaction.user.mention} has leveled up and unlocked **{tier['name']}** "
                    f"for working {tier['required']} {rarity} jobs!"
                )

        # total-job milestone tiers
        else:
            if total_jobs >= tier["required"]:
                role = guild.get_role(tier["role_id"])
                if role and role not in member.roles:
                    await member.add_roles(role)

                    # 🎉 announce in the server, not DM
                    await interaction.channel.send(
                        f"🏆 {interaction.user.mention} has unlocked **{tier['name']}** "
                        f"for completing {total_jobs} total jobs!"
                    )



# --- special event jobs (rolled separately from normal rarities) ---
SPECIAL_CHANCE = 0.02  # 2% chance per /work to try a special job

special_jobs = [
    {
        "name": "dev",
        "desc": "👀 DEV JOB — how did you get this? Are you cheating? What? Who are you?!?!",
        "payout": (1_000_000, 1_000_000),  # flat $1,000,000
        "color": discord.Color.red()
    },
    {
        "name": "toilet",
        "desc": "🚽 yikes… you cleaned toilets and got 💩 on yourself. loser.",
        "payout": (0.25, 0.25),            # flat 25 cents
        "color": discord.Color.from_rgb(105, 105, 105)  # dim gray
    },
    {
        "name": "glitch",
        "desc": "⚡ ERR0R_J0B_N0T_F0UND_??? you glitched reality and hit a bug bounty.",
        "payout": (10_000, 50_000),
        "color": discord.Color.from_rgb(139, 0, 139)    # dark magenta
    },
    {
        "name": "flash-sale",
        "desc": "🛒 you got in on a meme stock, nice! sold that quickly huh? stonks.",
        "payout": (2_500, 15_000),
        "color": discord.Color.from_rgb(218, 165, 32)   # goldenrod
    }
]

def pick_special_job():
    # first gate: global special chance
    if random.random() > SPECIAL_CHANCE:
        return None

    job = random.choice(special_jobs)

    # extra “random checks” per special to make some rarer than others
    if job["name"] == "dev":
        if random.randint(1, DEV_CHANCE_DENOM) != 777:
            return None
    elif job["name"] == "glitch":
        # 30% pass after the special trigger
        if random.random() > 0.30:
            return None
    # toilet and flash-sale always pass once special triggers

    payout_value = round(random.uniform(*job["payout"]), 2)
    return {
        "name": job["name"],
        "desc": job["desc"],
        "color": job["color"],
        "payout_value": payout_value
    }

# --- tip system: 10 multipliers with weighted odds ---
# base chance that ANY tip may happen on a work roll
TIP_BASE_CHANCE = 0.08  # 25% (tweak as you like)

# each tier has: name, emoji, multiplier range (min, max), and a weight for selection
# weights are relative (higher = more common when a tip occurs)
tip_tiers = [
    {"name": "coffee change",        "emoji": "☕", "range": (1.05, 1.15), "weight": 25,
     "flavor": "a quick thanks and some coffee money."},
    {"name": "spare cash",           "emoji": "💵", "range": (1.10, 1.25), "weight": 20,
     "flavor": "they tossed in a little extra."},
    {"name": "sweet old lady",       "emoji": "🧓", "range": (1.25, 1.75), "weight": 16,
     "flavor": "you did a great job — she insisted you take more!"},
    {"name": "great review bonus",   "emoji": "⭐", "range": (1.75, 2.25), "weight": 12,
     "flavor": "5★ review and a thank-you bonus."},
    {"name": "weekend rush",         "emoji": "📈", "range": (2.25, 2.75), "weight": 9,
     "flavor": "busy day surge pricing hits."},
    {"name": "manager’s envelope",   "emoji": "✉️", "range": (2.75, 3.25), "weight": 7,
     "flavor": "the boss quietly slipped you something extra."},
    {"name": "billionaire bonus",    "emoji": "🤑", "range": (3.00, 5.00), "weight": 5,
     "flavor": "you worked for a rich billionaire — they loved it!"},
    {"name": "angel investor",       "emoji": "😇", "range": (5.00, 7.00), "weight": 3,
     "flavor": "an ‘angel’ dropped a very generous tip."},
    {"name": "whale tip",            "emoji": "🐋", "range": (7.00, 10.00), "weight": 2,
     "flavor": "a high-roller was wildly impressed."},
    {"name": "legend of generosity", "emoji": "🏆", "range": (10.00, 12.00), "weight": 1,
     "flavor": "a once-in-a-blue-moon legendary gratuity!"}
]

def roll_tip():
    """Return None if no tip, else a dict with multiplier info."""
    if random.random() > TIP_BASE_CHANCE:
        return None

    # weighted pick among tiers
    total_weight = sum(t["weight"] for t in tip_tiers)
    pick = random.uniform(0, total_weight)
    upto = 0
    chosen = tip_tiers[-1]
    for t in tip_tiers:
        upto += t["weight"]
        if pick <= upto:
            chosen = t
            break

    mult = round(random.uniform(*chosen["range"]), 2)
    return {
        "name": chosen["name"],
        "emoji": chosen["emoji"],
        "flavor": chosen["flavor"],
        "mult": mult
    }


# --- job table with moderate inflation ---
# Payout ranges in dollars
# common:    50–200
# uncommon:  150–500
# rare:      400–2,000
# epic:      1,500–6,000
# legendary: 10,000–50,000
# secret:    100,000–1,000,000
# dev:       flat 1,000,000 (special)
jobs = {
    "common": {
        "chance": 0.55,
        "payout": (50, 200),
        "list": [
            "washed someone’s car","mowed a lawn","delivered a pizza","walked a dog","helped carry groceries",
            "cleaned a garage","painted a fence","tutored a kid","bagged groceries","worked as a cashier",
            "raked leaves","did laundry","shoveled snow","washed dishes","babysat for a neighbor",
            "picked up trash","organized a closet","recycled cans","swept a porch","helped move furniture",
            "assembled flat-pack furniture","sorted library books","wiped store shelves","restocked a cooler","cleaned aquarium glass",
            "handed out flyers","watered plants","vacuumed a car interior","cleaned windows","ran a coffee errand",
            "set up folding chairs","took down decorations","organized a toolbox","wiped down gym equipment","carried groceries to a car",
            "rolled silverware at a diner","sorted mail","counted inventory","bagged leaves","refilled bird feeders"
        ]
    },
    "uncommon": {
        "chance": 0.25,
        "payout": (150, 500),
        "list": [
            "fixed a bike","painted a room","carried heavy boxes","helped repair a fence","dog-sat overnight",
            "assembled a PC","installed a ceiling fan","detailed a car","set up a backyard tent","mounted a TV",
            "repaired a leaky faucet","edited a short video","designed a flyer","photographed a birthday","set up a sound system",
            "installed window blinds","organized a garage sale","prepped meal boxes","built a garden bed","patched drywall"
        ]
    },
    "rare": {
        "chance": 0.12,
        "payout": (400, 2000),
        "list": [
            "modeled for a commercial","worked backstage at a concert","helped a local news team",
            "carried VIP luggage","painted a mural","assisted a photographer","drove a limo for a wedding",
            "ran lights for a theater show","catered a private event","guided a city tour",
            "commissioned a pet portrait","fixed a vintage record player","restored a bicycle",
            "DJ’d a school dance","shot drone footage for real estate"
        ]
    },
    "epic": {
        "chance": 0.06,
        "payout": (1500, 6000),
        "list": [
            "helped on a movie set","delivered a speech for the mayor","flew as a private-jet assistant",
            "guided a celebrity tour","modeled designer clothes","staged a luxury home",
            "produced a pop-up event","shot a brand campaign","ghost-wrote a viral post",
            "consulted on game balance","built a custom keyboard","restored a classic arcade cabinet"
        ]
    },
    "legendary": {
        "chance": 0.02,
        "payout": (10000, 50000),
        "list": [
            "helped launch a rocket","discovered hidden treasure","performed in a world-famous concert",
            "auctioned a rare collector’s card","found a mint-condition comic","rescued a stranded yacht",
            "won a hackathon grand prize","flipped a barn-find motorcycle","sold a vintage camera collection"
        ]
    },
    "secret": {
        "chance": 0.001,  # 0.1%
        "payout": (100000, 1000000),
        "list": [
            "won a mysterious briefcase auction","found a safe behind a wall","sold a rare diamond at midnight"
        ]
    },
    # we’ll keep 'dev' here so the table is complete; we’ll wire special mechanics later.
    "dev": {
        "chance": 0.0,  # picked by special logic later
        "payout": (1_000_000, 1_000_000),
        "list": ["how did you get this? are you cheating? what? who are you?!?!"]
    }
}

# order matters for cumulative roll
RARITY_ORDER = ["common","uncommon","rare","epic","legendary","secret"]

def pick_job():
    """Simple % roll version (we’ll upgrade to your special multi-roll later)."""
    roll = random.random()  # 0.0–1.0
    cum = 0.0
    for r in RARITY_ORDER:
        data = jobs[r]
        cum += data["chance"]
        if roll <= cum:
            job = random.choice(data["list"])
            payout = round(random.uniform(*data["payout"]), 2)
            return r, job, payout
    # fallback: common
    job = random.choice(jobs["common"]["list"])
    payout = round(random.uniform(*jobs["common"]["payout"]), 2)
    return "common", job, payout

# --- events & commands ---
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user} and slash commands synced!")

    # Custom status (no "Playing/Watching" prefix)
    activity = discord.CustomActivity(name=f"getting a j*b at {BOT_VERSION}")
    await bot.change_presence(status=discord.Status.online, activity=activity)



@bot.tree.command(name="balance", description="Check how much money you have")
async def balance_cmd(interaction: discord.Interaction):
    user_id = interaction.user.id
    dollars = balances.get(user_id, 0.0)

    embed = discord.Embed(
        title="💰 Balance Check",
        description=f"Your wallet has: **${dollars:,.2f}**",
        color=discord.Color.green()
    )
    embed.set_footer(text=f"Requested by {interaction.user.name}")
    await interaction.response.send_message(embed=embed)

# Emojis per rarity for announcements (keep this where you had it)
rarity_emojis = {
    "common": "🪱",
    "uncommon": "🌿",
    "rare": "💎",
    "epic": "🌌",
    "legendary": "🔥",
    "secret": "💰",
    "dev": "👀",
    "toilet": "🚽",
    "glitch": "⚡",
    "flash-sale": "🛒"
}

@bot.tree.command(name="progress", description="Check your job progress and next role unlock")
async def progress(interaction: discord.Interaction):
    user_id = interaction.user.id
    counts = job_counts.get(user_id, {"common":0,"uncommon":0,"rare":0,"epic":0,"legendary":0,"secret":0,"special":0})
    total_jobs = sum(counts.values())

    # figure out the next unlock
    next_unlock = None
    for tier in ROLE_TIERS:
        if tier["rarity"] == "total":
            if total_jobs < tier["required"]:
                next_unlock = (tier["name"], tier["required"] - total_jobs, "total jobs")
                break
        else:
            if counts.get(tier["rarity"], 0) < tier["required"]:
                next_unlock = (tier["name"], tier["required"] - counts[tier["rarity"]], f"{tier['rarity']} jobs")
                break

    # make an embed
    embed = discord.Embed(
        title=f"📊 Job Progress for {interaction.user.display_name}",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="Jobs Completed",
        value=(
            f"Common: {counts['common']}\n"
            f"Uncommon: {counts['uncommon']}\n"
            f"Rare: {counts['rare']}\n"
            f"Epic: {counts['epic']}\n"
            f"Legendary: {counts['legendary']}\n"
            f"Secret: {counts['secret']}\n"
            f"Special: {counts['special']}\n"
            f"**Total:** {total_jobs}"
        ),
        inline=False
    )

    if next_unlock:
        embed.add_field(
            name="Next Unlock",
            value=f"**{next_unlock[0]}** → {next_unlock[1]} more {next_unlock[2]}",
            inline=False
        )
    else:
        embed.add_field(
            name="Next Unlock",
            value="✅ You’ve unlocked everything currently available!",
            inline=False
        )

    await interaction.response.send_message(embed=embed)


test_mode = False

@bot.tree.command(name="testmode", description="Toggle test mode (admin only)")
async def testmode(interaction: discord.Interaction, toggle: str):
    global test_mode, SPECIAL_CHANCE, TIP_BASE_CHANCE, DEV_CHANCE_DENOM

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You don’t have permission to use this.", ephemeral=True)
        return

    if toggle.lower() == "on":
        test_mode = True
        SPECIAL_CHANCE = 0.5
        TIP_BASE_CHANCE = 0.9
        DEV_CHANCE_DENOM = 5
        await interaction.response.send_message("🧪 Test mode ON — odds boosted for specials and tips.")
    elif toggle.lower() == "off":
        test_mode = False
        SPECIAL_CHANCE = 0.02
        TIP_BASE_CHANCE = 0.25
        DEV_CHANCE_DENOM = 7777
        await interaction.response.send_message("🧪 Test mode OFF — odds restored to normal.")
    else:
        await interaction.response.send_message("Usage: `/testmode on` or `/testmode off`")


# Track cooldowns: 1 use per 15 seconds, per user
coinflip_cooldown = app_commands.checks.cooldown(1, 15.0, key=lambda i: i.user.id)

@bot.tree.command(name="coinflip", description="Bet money on a coinflip (heads or tails)")
@app_commands.describe(choice="Your guess: heads or tails", amount="How much money to bet")
@coinflip_cooldown
async def coinflip(interaction: discord.Interaction, choice: str, amount: float):
    user_id = interaction.user.id

    # normalize choice
    choice = choice.lower()
    if choice not in ["heads", "tails"]:
        await interaction.response.send_message("❌ Please choose either 'heads' or 'tails'.", ephemeral=True)
        return

    # check balance
    balance = balances.get(user_id, 0.0)
    if amount <= 0:
        await interaction.response.send_message("❌ Bet amount must be greater than zero.", ephemeral=True)
        return
    if amount > 500_000:
        await interaction.response.send_message("❌ The maximum bet is $500,000.", ephemeral=True)
        return
    if amount > balance:
        await interaction.response.send_message("❌ You don’t have enough money for that bet.", ephemeral=True)
        return

    # flip coin
    result = random.choice(["heads", "tails"])

    if result == choice:
        winnings = amount
        balances[user_id] = balance + winnings
        outcome = f"🎉 You guessed **{choice}** and it landed **{result}**! You won **${winnings:,.2f}**."
        color = discord.Color.green()
    else:
        losses = amount
        balances[user_id] = balance - losses
        outcome = f"😢 You guessed **{choice}** but it landed **{result}**. You lost **${losses:,.2f}**."
        color = discord.Color.red()

    save_balances()
    new_balance = balances[user_id]

    # build embed
    embed = discord.Embed(
        title="🪙 Coinflip",
        description=f"{outcome}\n\n💼 Wallet Balance: **${new_balance:,.2f}**",
        color=color
    )
    embed.set_footer(text=f"Bet: ${amount:,.2f}")

    await interaction.response.send_message(embed=embed)

# register choices
@coinflip.autocomplete("choice")
async def coinflip_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> list[app_commands.Choice[str]]:
    choices = ["heads", "tails"]
    return [
        app_commands.Choice(name=c.capitalize(), value=c)
        for c in choices
        if current.lower() in c
    ]


# Handle cooldown errors (show nice message instead of crashing)
@coinflip.error
async def coinflip_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"⏳ You need to wait {error.retry_after:.1f} seconds before using /coinflip again.",
            ephemeral=True
        )

@bot.tree.command(name="roulette", description="Join the roulette table and place your bet")
@app_commands.describe(
    bet="Your bet type (red, black, green, odd, even, 1-18, 19-36, 1st12, 2nd12, 3rd12, or a number 0-36/00)",
    amount="How much money to bet"
)
async def roulette(interaction: discord.Interaction, bet: str, amount: float):
    global roulette_game

    # Lock command to one channel
    if interaction.channel_id != ROULETTE_CHANNEL_ID:
        await interaction.response.send_message(
            f"❌ Roulette can only be played in <#{ROULETTE_CHANNEL_ID}>.",
            ephemeral=True
        )
        return

    user_id = interaction.user.id
    bet = bet.lower()

    # Validate bet
    valid_bets = ["red", "black", "green", "odd", "even", "1-18", "19-36", "1st12", "2nd12", "3rd12"] \
                 + [str(n) for n in range(37)] + ["00"]
    if bet not in valid_bets:
        await interaction.response.send_message(
            "❌ Invalid bet. Try red, black, green, odd, even, 1-18, 19-36, 1st12, 2nd12, 3rd12, or a number (0-36, 00).",
            ephemeral=True
        )
        return

    # Validate balance
    balance = balances.get(user_id, 0.0)
    if amount <= 0:
        await interaction.response.send_message("❌ Bet amount must be greater than zero.", ephemeral=True)
        return
    if amount > 500_000:
        await interaction.response.send_message("❌ The maximum bet is $500,000.", ephemeral=True)
        return
    if amount > balance:
        await interaction.response.send_message("❌ You don’t have enough money to place that bet.", ephemeral=True)
        return

    # If no active game, start one
    if not roulette_game["active"]:
        roulette_game["active"] = True
        roulette_game["bets"] = []
        roulette_game["channel_id"] = interaction.channel_id

        # Announce game start
        embed_start = discord.Embed(
            title="🎰 Roulette Game Started!",
            description="Place your bets in the next **15 seconds** with `/roulette`!",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed_start)

        # Add first bet
        roulette_game["bets"].append({"user_id": user_id, "bet": bet, "amount": amount})
        balances[user_id] = balance - amount
        save_balances()

        # Announce first bet too
        embed_bet = discord.Embed(
            title="🎲 First Bet Placed",
            description=f"{interaction.user.mention} wagered **${amount:,.2f}** on **{bet}**!",
            color=discord.Color.blurple()
        )
        channel = bot.get_channel(roulette_game["channel_id"])
        if channel:
            await channel.send(embed=embed_bet)

        # Start timer
        async def finish_round():
            await asyncio.sleep(10)
            if channel:
                await channel.send(embed=discord.Embed(
                    title="⏳ Last Call",
                    description="5 seconds left to place your bets!",
                    color=discord.Color.orange()
                ))

            await asyncio.sleep(5)

            # Spin the wheel
            spin_num = random.randint(0, 37)  # 0–36 + 37 = "00"
            if spin_num == 37:
                result = "00"
                color = "green"
            else:
                result = str(spin_num)
                if spin_num in {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}:
                    color = "red"
                elif spin_num in {2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35}:
                    color = "black"
                else:
                    color = "green"

            if channel:
                embed_result = discord.Embed(
                    title="🎲 The Ball Landed!",
                    description=f"**{color.capitalize()} {result}**",
                    color=discord.Color.green() if color == "green" else (
                        discord.Color.red() if color == "red" else discord.Color.dark_gray()
                    )
                )
                await channel.send(embed=embed_result)

                # Resolve bets
                for bet_data in roulette_game["bets"]:
                    uid = bet_data["user_id"]
                    bet_choice = bet_data["bet"]
                    wager = bet_data["amount"]
                    payout = 0
                    win = False

                    # Straight bet
                    if bet_choice == result:
                        payout = wager * 35
                        win = True
                    if bet_choice == "00" and result == "00":
                        payout = wager * 35
                        win = True

                    # Color bets
                    if bet_choice in ["red", "black"] and bet_choice == color:
                        payout = wager * 2
                        win = True
                    if bet_choice == "green" and color == "green":
                        payout = wager * 35
                        win = True

                    # Odd/Even
                    if bet_choice == "odd" and result not in ["0", "00"] and int(result) % 2 == 1:
                        payout = wager * 2
                        win = True
                    if bet_choice == "even" and result not in ["0", "00"] and int(result) % 2 == 0:
                        payout = wager * 2
                        win = True

                    # Low/High
                    if bet_choice == "1-18" and result not in ["0", "00"] and 1 <= int(result) <= 18:
                        payout = wager * 2
                        win = True
                    if bet_choice == "19-36" and result not in ["0", "00"] and 19 <= int(result) <= 36:
                        payout = wager * 2
                        win = True

                    # Dozens
                    if bet_choice == "1st12" and result not in ["0", "00"] and 1 <= int(result) <= 12:
                        payout = wager * 3
                        win = True
                    if bet_choice == "2nd12" and result not in ["0", "00"] and 13 <= int(result) <= 24:
                        payout = wager * 3
                        win = True
                    if bet_choice == "3rd12" and result not in ["0", "00"] and 25 <= int(result) <= 36:
                        payout = wager * 3
                        win = True

                    # Update balance + announce
                    if win:
                        balances[uid] = balances.get(uid, 0.0) + payout
                        embed_win = discord.Embed(
                            title="✅ Winner!",
                            description=f"<@{uid}> won **${payout:,.2f}** betting **{bet_choice}**!",
                            color=discord.Color.green()
                        )
                        await channel.send(embed=embed_win)
                    else:
                        embed_lose = discord.Embed(
                            title="❌ Lost",
                            description=f"<@{uid}> lost **${wager:,.2f}** betting **{bet_choice}**.",
                            color=discord.Color.red()
                        )
                        await channel.send(embed=embed_lose)

                save_balances()

            roulette_game["active"] = False
            roulette_game["bets"] = []
            roulette_game["channel_id"] = None

        asyncio.create_task(finish_round())
        return

    # If game already active, join it
    if roulette_game["active"]:
        if interaction.channel_id != roulette_game["channel_id"]:
            channel = bot.get_channel(roulette_game["channel_id"])
            channel_mention = channel.mention if channel else "#unknown"
            await interaction.response.send_message(
                f"❌ A roulette game is already running in {channel_mention}. Please join it there!",
                ephemeral=True
            )
            return

        roulette_game["bets"].append({"user_id": user_id, "bet": bet, "amount": amount})
        balances[user_id] = balance - amount
        save_balances()

        embed_bet = discord.Embed(
            title="🎲 Bet Placed",
            description=f"{interaction.user.mention} wagered **${amount:,.2f}** on **{bet}**!",
            color=discord.Color.blurple()
        )
        await interaction.response.send_message(embed=embed_bet)



@bot.tree.command(name="fish", description="Try to fish (but not in this bot!)")
async def fish(interaction: discord.Interaction):
    user_id = interaction.user.id
    balance = balances.get(user_id, 0.0)

    if balance <= 0:
        await interaction.response.send_message("🎣 not here, wrong server dummy, Punishment time!")
        return

    # take 5% of balance
    penalty = round(balance * 0.05, 2)
    balances[user_id] = round(balance - penalty, 2)
    save_balances()

    new_balance = balances[user_id]

    embed = discord.Embed(
        title="🎣 Not Here, Dummy!",
        description=(
            f"not here, wrong server dummy!\n\n"
            f"You lost **${penalty:,.2f}** (5% of your wallet).\n"
            f"💼 New Balance: **${new_balance:,.2f}**"
        ),
        color=discord.Color.red()
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="leaderboardmoney", description="Show the top users by wallet balance")
async def leaderboard(interaction: discord.Interaction):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("❌ This command can only be used in a server.")
        return

    if not balances:
        await interaction.response.send_message("No balances to show yet!", ephemeral=True)
        return

    sorted_balances = sorted(balances.items(), key=lambda x: x[1], reverse=True)[:10]

    lines = []
    for i, (uid, bal) in enumerate(sorted_balances, start=1):
        member = guild.get_member(uid)
        if member:
            name = member.mention
        else:
            try:
                user = await bot.fetch_user(uid)
                name = user.name
            except:
                name = f"User {uid}"

        # pick medal for top 3
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."

        lines.append(f"{medal} {name} — **${bal:,.2f}**")

    embed = discord.Embed(
        title="💰 Economy Leaderboard",
        description="**Top 10 Users by Balance**\n\n" + "\n".join(lines),
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed)



@bot.tree.command(name="leaderboardjob", description="Show the top users by total jobs worked")
async def leaderboardjob(interaction: discord.Interaction):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("❌ This command can only be used in a server.")
        return

    if not job_counts:
        await interaction.response.send_message("No job records to show yet!", ephemeral=True)
        return

    server_jobs = {uid: sum(counts.values()) for uid, counts in job_counts.items()}
    sorted_jobs = sorted(server_jobs.items(), key=lambda x: x[1], reverse=True)[:10]

    lines = []
    for i, (uid, total) in enumerate(sorted_jobs, start=1):
        member = guild.get_member(uid)
        if member:
            name = member.mention
        else:
            try:
                user = await bot.fetch_user(uid)
                name = user.name
            except:
                name = f"User {uid}"

        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        lines.append(f"{medal} {name} — **{total:,} jobs**")

    embed = discord.Embed(
        title="📊 Jobs Leaderboard",
        description="**Top 10 Users by Jobs Worked**\n\n" + "\n".join(lines),
        color=discord.Color.blurple()
    )
    await interaction.response.send_message(embed=embed)




@bot.tree.command(name="work", description="Do an odd job to earn some money")
async def work_cmd(interaction: discord.Interaction):
    # check if this command is being run in the work channel
    if interaction.channel_id != WORK_CHANNEL_ID:
        await interaction.response.send_message(
            f"❌ You can only use this command in <#{WORK_CHANNEL_ID}>.",
            ephemeral=True
        )
        return

    user_id = interaction.user.id

    # ---- 1) try special-event jobs first ----
    special = pick_special_job()
    if special is not None:
        base_payout = special["payout_value"]

        # try for a tip on special jobs too
        tip = roll_tip()
        if tip:
            final_payout = round(base_payout * tip["mult"], 2)
        else:
            final_payout = base_payout

        balances[user_id] = balances.get(user_id, 0.0) + final_payout
        save_balances()
        new_balance = balances[user_id]

        # ✅ update job progress
        await update_job_progress(interaction, "special")

        desc_lines = [
            f"{special['desc']}",
            "",
            f"you earned **${base_payout:,.2f}**."
        ]
        if tip:
            desc_lines.append(
                f"{tip['emoji']} tip! {tip['flavor']} ×**{tip['mult']}** → **${final_payout:,.2f}** total."
            )
        desc_lines.extend([
            "",
            f"💰 current balance: **${new_balance:,.2f}**"
        ])

        embed = discord.Embed(
            title=f"{interaction.user.name} worked a special job!",
            description="\n".join(desc_lines),
            color=special["color"]
        )
        embed.set_footer(text=f"special job: {special['name'].upper()}")
        await interaction.response.send_message(embed=embed)

        # announce in the announcement channel
        announce_channel = bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if announce_channel:
            emoji = rarity_emojis.get(special["name"], "✨")
            if tip:
                await announce_channel.send(
                    f"{emoji} {interaction.user.mention} hit a **Special Job: {special['name'].upper()}** "
                    f"and earned ${final_payout:,.2f} (tipped ×{tip['mult']})!"
                )
            else:
                await announce_channel.send(
                    f"{emoji} {interaction.user.mention} hit a **Special Job: {special['name'].upper()}** "
                    f"and earned ${final_payout:,.2f}!"
                )
        return

    # ---- 2) normal rarity roll ----
    rarity, job, base_payout = pick_job()

    # try for a tip
    tip = roll_tip()
    if tip:
        final_payout = round(base_payout * tip["mult"], 2)
    else:
        final_payout = base_payout

    balances[user_id] = balances.get(user_id, 0.0) + final_payout
    save_balances()
    new_balance = balances[user_id]

    # ✅ update job progress
    await update_job_progress(interaction, rarity)

    desc_lines = [
        f"{flavor_texts[rarity]}",
        "",
        f"you {job} and earned **${base_payout:,.2f}**."
    ]
    if tip:
        extra = ""
        if rarity == "common" and tip["mult"] >= 3:
            extra = " (from crumbs to caviar!)"
        desc_lines.append(
            f"{tip['emoji']} tip! {tip['flavor']} ×**{tip['mult']}** → **${final_payout:,.2f}** total.{extra}"
        )
    desc_lines.extend([
        "",
        f"💰 current balance: **${new_balance:,.2f}**"
    ])

    embed = discord.Embed(
        title=f"{interaction.user.name} worked!",
        description="\n".join(desc_lines),
        color=rarity_colors[rarity]
    )
    embed.set_footer(text=f"job type: {rarity.upper()}")
    await interaction.response.send_message(embed=embed)

    # announcements only for legendary/secret
    if rarity in ["legendary", "secret"]:
        announce_channel = bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if announce_channel:
            emoji = rarity_emojis.get(rarity, "✨")
            if tip:
                await announce_channel.send(
                    f"{emoji} {interaction.user.mention} just worked a **{rarity.upper()} job** "
                    f"and made ${final_payout:,.2f} (tipped ×{tip['mult']})!"
                )
            else:
                await announce_channel.send(
                    f"{emoji} {interaction.user.mention} just worked a **{rarity.upper()} job** "
                    f"and made ${final_payout:,.2f}!"
                )




load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)

