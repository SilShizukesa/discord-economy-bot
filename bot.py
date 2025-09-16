# --- imports & basic setup ---
import discord
from discord.ext import commands
import random
import json
import os
from discord import app_commands
import asyncio
from dotenv import load_dotenv
import time
from discord import Member
from discord import app_commands
import subprocess

# Version of the bot
BOT_VERSION = "V0.0.04.1"




intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
ANNOUNCE_CHANNEL_ID = 1417338592359092235  # paste your channel ID here
WORK_CHANNEL_ID = 1417332114453430282  # replace with your work channel ID
ROULETTE_CHANNEL_ID = 1417369961172697090  # replace with your roulette channel ID
PATCH_NOTES_CHANNEL_ID = 1417353769037070366  # replace with your channel ID
META_FILE = "meta.json"

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

BUFFS_FILE = "buffs.json"
buffs = {}

def save_buffs():
    with open(BUFFS_FILE, "w") as f:
        json.dump(buffs, f)

def load_buffs():
    global buffs
    if os.path.exists(BUFFS_FILE):
        with open(BUFFS_FILE, "r") as f:
            buffs = json.load(f)
    else:
        buffs = {}


# --- Alcohol luck system config ---
ALCOHOL_PRICE = 5_000.0                 # $5k to buy
ALCOHOL_COOLDOWN = 6 * 60 * 60          # 6 hours in seconds
ALCOHOL_BOOST_USES = 5                  # applies to next 5 gambling commands
COINFLIP_BOOST_WINPROB = 0.54           # 54/46 when boosted (normal is 0.5)
ROULETTE_COLOR_SALVAGE = 0.025          # ~8.8% “second chance” on color bets to reach ~52% effective
BUFFS_FILE = "buffs.json"               # persisted here so it survives restarts

# load/save for alcohol buffs
alcohol_status: dict[int, dict] = {}

def load_buffs():
    global alcohol_status
    if os.path.exists(BUFFS_FILE):
        with open(BUFFS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # keys are strings in JSON; convert to int
        alcohol_status = {int(k): v for k, v in raw.items()}
    else:
        alcohol_status = {}

def save_buffs():
    # store as string keys for JSON
    with open(BUFFS_FILE, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in alcohol_status.items()}, f, indent=2)

def get_boost_record(uid: int) -> dict:
    rec = alcohol_status.get(uid) or {"uses": 0, "cooldown_until": 0}
    alcohol_status[uid] = rec
    return rec

def has_active_alcohol(uid: int) -> bool:
    return get_boost_record(uid).get("uses", 0) > 0

def consume_alcohol_use(uid: int) -> int:
    """Decrease uses by 1 if any. Returns remaining uses."""
    rec = get_boost_record(uid)
    if rec.get("uses", 0) > 0:
        rec["uses"] -= 1
        save_buffs()
    return rec.get("uses", 0)

def alcohol_cooldown_left(uid: int) -> int:
    """Seconds left until they can buy again."""
    rec = get_boost_record(uid)
    return max(0, int(rec.get("cooldown_until", 0) - time.time()))


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

# Load alcohol buffs (luck system)
load_buffs()


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
        "name": "lightning",
        "desc": "⚡ A flash sale struck! You flipped items like crazy.",
        "color": discord.Color.yellow(),
        "payout": (80_000, 200_000)
    },
    {
        "name": "glitch",
        "desc": "🌀 The job glitched out! Reality bent in your favor.",
        "color": discord.Color.magenta(),
        "payout": (200_000, 300_000)
    },
    {
        "name": "dev",
        "desc": "👨‍💻 You stumbled into dev commands... jackpot.",
        "color": discord.Color.dark_red(),
        "payout": (1_500_000, 1_500_000)
    },
    {
        "name": "toilet",
        "desc": "🚽 You cleaned the toilets but… disaster. Covered in 💩",
        "color": discord.Color.dark_gray(),
        "payout": (0.25, 0.25)
    },
    {
        "name": "meme69",
        "desc": "😂 Nice job. Somebody tipped you $69. Nice.",
        "color": discord.Color.green(),
        "payout": (69, 69)
    },
    {
        "name": "meme420",
        "desc": "🔥 Blazing! You got tipped $420 for style.",
        "color": discord.Color.dark_green(),
        "payout": (420, 420)
    },
    {
        "name": "goldrush",
        "desc": "🏆 GOLD RUSH! You sold golden nuggets.",
        "color": discord.Color.gold(),
        "payout": (300_000, 600_000)
    },
    {
        "name": "lottery",
        "desc": "🎟️ You hit the underground lotto!",
        "color": discord.Color.teal(),
        "payout": (150_000, 500_000)
    },
    {
        "name": "sponsorship",
        "desc": "📢 Sponsored by Shady Brand™.",
        "color": discord.Color.orange(),
        "payout": (100_000, 250_000)
    },
    {
        "name": "artifact",
        "desc": "🗿 You found a priceless artifact.",
        "color": discord.Color.blue(),
        "payout": (200_000, 400_000)
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
# --- job table with moderate inflation ---
# Payout ranges in dollars
# common:    10–80
# uncommon:  150–500
# rare:      400–2,000
# epic:      1,500–6,000
# legendary: 10,000–50,000
# secret:    100,000–1,000,000
# specials handled separately

jobs = {
    "common": {
        "chance": 0.55,
        "payout": (10, 80),
        "list": [
            # ~100 filler commons
            "washed someone’s car","buttered a baguette", "mowed a lawn","delivered a pizza","walked a dog","helped carry groceries",
            "cleaned a garage","painted a fence","tutored a kid","bagged groceries","worked as a cashier",
            "raked leaves","did laundry","shoveled snow","washed dishes","babysat for a neighbor",
            "picked up trash","organized a closet","recycled cans","swept a porch","helped move furniture",
            "assembled flat-pack furniture","sorted library books","wiped store shelves","restocked a cooler","cleaned aquarium glass",
            "handed out flyers","watered plants","vacuumed a car interior","cleaned windows","ran a coffee errand",
            "set up folding chairs","took down decorations","organized a toolbox","wiped down gym equipment","carried groceries to a car",
            "rolled silverware at a diner","sorted mail","counted inventory","bagged leaves","refilled bird feeders",
            "folded laundry at a laundromat","sorted recycling","swept up sawdust","collected carts in a lot","refilled napkin dispensers",
            "stacked soda cans into a pyramid","swept up popcorn in a theater","tested pens at a bank","restocked vending machines","moved chairs in a classroom",
            "bagged candy at a fair","swept gym floors","helped paint faces at a carnival","stacked chairs after an event","helped set up a lemonade stand",
            "sorted pencils in a jar","filled water balloons","helped inflate bouncy castle","folded origami for tips","carried signs in a parade",
            "reset bowling pins manually","helped sell popcorn","folded brochures","counted tickets at arcade","sprayed down muddy boots",
            "swept parking lot","cleaned public benches","organized lost and found","helped sweep leaves off roof","shined shoes for commuters",
            "bagged bread at bakery","tied balloons for kids","cleaned chalkboards","erased whiteboards","restocked printer paper",
            "sorted library DVDs","helped set up karaoke","carried drinks to tables","stacked fruit crates","watered public park plants",
            "folded cardboard boxes","restocked office supplies","helped clean fish tanks","emptied wastebaskets","organized shelves in store"
        ]
    },
    "uncommon": {
        "chance": 0.25,
        "payout": (150, 500),
        "list": [
            # ~60 uncommon
            "fixed a bike","painted a room","carried heavy boxes","helped repair a fence","dog-sat overnight",
            "assembled a PC","installed a ceiling fan","detailed a car","set up a backyard tent","mounted a TV",
            "repaired a leaky faucet","edited a short video","designed a flyer","photographed a birthday","set up a sound system",
            "installed window blinds","organized a garage sale","prepped meal boxes","built a garden bed","patched drywall",
            "carried DJ equipment","helped build IKEA furniture","repaired a skateboard","painted murals for a café","assisted in a classroom",
            "helped cook at a food stall","assembled shelves","polished shoes at a wedding","built a treehouse","repaired garden lights",
            "set up fireworks (carefully!)","stitched a costume","filmed a school play","edited YouTube vlogs","fixed a leaky roof corner",
            "tuned a guitar","set up a LAN party","wired holiday lights","designed a menu board","carved a pumpkin for display",
            "spray painted a mural wall","set up science fair booth","organized cosplay props","cleaned projector lenses","assisted at art gallery",
            "tuned roller skates","painted garden gnomes","helped build birdhouses","carved wood toys","decorated cakes for a party",
            "painted parking lot stripes","stitched patches on jeans","fixed a fan belt","helped with recycling project","installed shelves"
        ]
    },
    "rare": {
        "chance": 0.12,
        "payout": (400, 2000),
        "list": [
            # ~40 rares
            "modeled for a commercial","played pickleball", "worked backstage at a concert","helped a local news team",
            "carried VIP luggage","painted a mural","assisted a photographer","drove a limo for a wedding",
            "ran lights for a theater show","catered a private event","guided a city tour",
            "commissioned a pet portrait","fixed a vintage record player","restored a bicycle",
            "DJ’d a school dance","shot drone footage for real estate","sold merch at a big event",
            "handled fireworks display","built props for theater","staged a gallery show","sold flowers at festival",
            "helped at esports tournament","set up streamer gear","painted an esports logo","installed neon signs",
            "guided tourists on segways","restored antiques","designed game avatars","painted tabletop minis","built arcade fight sticks",
            "handled school radio show","helped code a small app","staged a DJ booth","set up gaming chairs","drove catering van",
            "organized comic-con booth","fixed lighting rigs","did background acting","ran local VR demo","edited pro cosplay photos"
        ]
    },
    "epic": {
        "chance": 0.06,
        "payout": (1500, 6000),
        "list": [
            # ~25 epics
            "helped on a movie set","delivered a speech for the mayor","flew as a private-jet assistant",
            "guided a celebrity tour","modeled designer clothes","staged a luxury home",
            "produced a pop-up event","shot a brand campaign","ghost-wrote a viral post",
            "consulted on game balance","built a custom keyboard","restored a classic arcade cabinet",
            "helped host TED Talk","painted luxury cars","did voice acting for anime","built esports stage","handled VR showcase",
            "set up streaming marathon","filmed esports finals","modeled jewelry","helped run science expo","did live radio hosting",
            "managed backstage pyrotechnics","helped build escape room","set up crypto mining rigs"
        ]
    },
    "legendary": {
        "chance": 0.02,
        "payout": (10000, 50000),
        "list": [
            # ~15 legendaries
            "helped launch a rocket","jorked off a dwarf", "discovered hidden treasure","performed in a world-famous concert",
            "auctioned a rare collector’s card","found a mint-condition comic","rescued a stranded yacht",
            "won a hackathon grand prize","flipped a barn-find motorcycle","sold a vintage camera collection",
            "restored a lost painting","won underground chess grandmaster","streamed to 1M live viewers",
            "caught rare Pokémon GO spawn IRL","helped launch indie game","found a gold vein while hiking"
        ]
    },
    "secret": {
        "chance": 0.001,
        "payout": (100000, 1000000),
        "list": [
            # ~10 secrets
            "won a mysterious briefcase auction","found a safe behind a wall","sold a rare diamond at midnight",
            "hacked into a forgotten crypto wallet","discovered hidden cave paintings","restored an ancient manuscript",
            "found $500,000 in attic","traded a golden Pokémon card","repaired a broken Fabergé egg","auctioned ancient coins"
        ]
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


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user} and slash commands synced!")

    # Set custom status
    activity = discord.CustomActivity(name=f"Getting a J*B at {BOT_VERSION}")
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

# 15s per-user cooldown already present above in your file
@bot.tree.command(name="coinflip", description="Bet money on a coinflip (heads or tails)")
@app_commands.describe(choice="Your guess: heads or tails", amount="How much money to bet")
@coinflip_cooldown
async def coinflip(interaction: discord.Interaction, choice: str, amount: float):
    uid = interaction.user.id
    choice = choice.lower()

    if choice not in ["heads", "tails"]:
        await interaction.response.send_message("❌ Please choose either 'heads' or 'tails'.", ephemeral=True)
        return

    bal = balances.get(uid, 0.0)
    if amount <= 0:
        await interaction.response.send_message("❌ Bet amount must be greater than zero.", ephemeral=True)
        return
    if amount > 500_000:
        await interaction.response.send_message("❌ The maximum bet is $500,000.", ephemeral=True)
        return
    if amount > bal:
        await interaction.response.send_message("❌ You don’t have enough money for that bet.", ephemeral=True)
        return

    boosted = has_active_alcohol(uid)
    win_prob = COINFLIP_BOOST_WINPROB if boosted else 0.5

    win = random.random() < win_prob
    result = choice if win else ("tails" if choice == "heads" else "heads")

    if win:
        balances[uid] = bal + amount
        outcome = f"🎉 You guessed **{choice}** and it landed **{result}**! You won **${amount:,.2f}**."
        color = discord.Color.green()
    else:
        balances[uid] = bal - amount
        outcome = f"😢 You guessed **{choice}** but it landed **{result}**. You lost **${amount:,.2f}**."
        color = discord.Color.red()

    # if boosted, consume one use
    boost_line = ""
    if boosted:
        left = consume_alcohol_use(uid)
        save_buffs()  # <--- make sure we persist after decrement
        boost_line = f"\n🍺 Alcohol boost used. **{left}** use(s) left."

    save_balances()
    new_bal = balances[uid]

    embed = discord.Embed(
        title="🪙 Coinflip",
        description=f"{outcome}{boost_line}\n\n💼 Wallet Balance: **${new_bal:,.2f}**",
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

ROULETTE_WINDOW_SECONDS = 15  # total window for bets

@bot.tree.command(name="roulette", description="Join the roulette table and place your bet")
@app_commands.describe(
    bet="Your bet type (red, black, green, odd, even, 1-18, 19-36, 1st12, 2nd12, 3rd12, or a number 0-36/00)",
    amount="How much money to bet"
)
async def roulette(interaction: discord.Interaction, bet: str, amount: float):
    global roulette_game

    # defer immediately so Discord doesn't time out
    await interaction.response.defer(thinking=False, ephemeral=False)

    if interaction.channel_id != ROULETTE_CHANNEL_ID:
        await interaction.followup.send(
            f"❌ Roulette can only be played in <#{ROULETTE_CHANNEL_ID}>.",
            ephemeral=True
        )
        return

    uid = interaction.user.id
    bet = bet.lower()

    valid_bets = ["red", "black", "green", "odd", "even", "1-18", "19-36", "1st12", "2nd12", "3rd12"] \
                 + [str(n) for n in range(37)] + ["00"]
    if bet not in valid_bets:
        await interaction.followup.send(
            "❌ Invalid bet. Try red, black, green, odd, even, 1-18, 19-36, 1st12, 2nd12, 3rd12, or a number (0-36, 00).",
            ephemeral=True
        )
        return

    bal = balances.get(uid, 0.0)
    if amount <= 0:
        await interaction.followup.send("❌ Bet amount must be greater than zero.", ephemeral=True)
        return
    if amount > 500_000:
        await interaction.followup.send("❌ The maximum bet is $500,000.", ephemeral=True)
        return
    if amount > bal:
        await interaction.followup.send("❌ You don’t have enough money to place that bet.", ephemeral=True)
        return

    # helper to append a bet (handles alcohol + pre-deduct)
    async def append_bet(first: bool):
        boosted_now = has_active_alcohol(uid) and (bet in ["red", "black"])
        balances[uid] = bal - amount if first else balances.get(uid, 0.0) - amount
        save_balances()

        if boosted_now:
            left = consume_alcohol_use(uid)
            boost_note = f"\n🍺 Alcohol luck will apply to this **{bet}** bet. ({left} uses left)"
        else:
            boost_note = ""

        roulette_game["bets"].append({
            "user_id": uid,
            "bet": bet,
            "amount": amount,
            "boosted_color": boosted_now
        })

        embed_bet = discord.Embed(
            title="🎲 Bet Placed" if not first else "🎲 First Bet Placed",
            description=f"{interaction.user.mention} wagered **${amount:,.2f}** on **{bet}**!{boost_note}",
            color=discord.Color.blurple()
        )
        chan = bot.get_channel(roulette_game["channel_id"])
        if first:
            await chan.send(embed=embed_bet)
        else:
            await interaction.followup.send(embed=embed_bet)

    # start new game
    if not roulette_game["active"]:
        roulette_game["active"] = True
        roulette_game["bets"] = []
        roulette_game["channel_id"] = interaction.channel_id

        embed_start = discord.Embed(
            title="🎰 Roulette Game Started!",
            description=f"Place your bets in the next **{ROULETTE_WINDOW_SECONDS} seconds** with `/roulette`!",
            color=discord.Color.gold()
        )
        await interaction.followup.send(embed=embed_start)

        await append_bet(first=True)

        async def finish_round():
            chan = bot.get_channel(roulette_game["channel_id"])
            await asyncio.sleep(max(0, ROULETTE_WINDOW_SECONDS - 5))
            if chan:
                await chan.send(embed=discord.Embed(
                    title="⏳ Last Call",
                    description="5 seconds left to place your bets!",
                    color=discord.Color.orange()
                ))
            await asyncio.sleep(5)

            spin = random.randint(0, 37)
            if spin == 37:
                result = "00"
                color = "green"
            else:
                result = str(spin)
                if spin in {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}:
                    color = "red"
                elif spin in {2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35}:
                    color = "black"
                else:
                    color = "green"

            if chan:
                embed_result = discord.Embed(
                    title="🎲 The Ball Landed!",
                    description=f"**{color.capitalize()} {result}**",
                    color=discord.Color.green() if color == "green" else (
                        discord.Color.red() if color == "red" else discord.Color.dark_gray()
                    )
                )
                await chan.send(embed=embed_result)

                for bet_data in roulette_game["bets"]:
                    uid2 = bet_data["user_id"]
                    bet_choice = bet_data["bet"]
                    wager = bet_data["amount"]
                    boosted_color = bet_data.get("boosted_color", False)

                    payout = 0.0
                    win = False
                    salvaged = False

                    if bet_choice == result:
                        payout = wager * 35
                        win = True
                    if bet_choice == "00" and result == "00":
                        payout = wager * 35
                        win = True

                    if bet_choice in ["red", "black"] and bet_choice == color:
                        payout = wager * 2
                        win = True
                    if bet_choice == "green" and color == "green":
                        payout = wager * 35
                        win = True

                    if bet_choice == "odd" and result not in ["0", "00"] and int(result) % 2 == 1:
                        payout = wager * 2
                        win = True
                    if bet_choice == "even" and result not in ["0", "00"] and int(result) % 2 == 0:
                        payout = wager * 2
                        win = True

                    if bet_choice == "1-18" and result not in ["0", "00"] and 1 <= int(result) <= 18:
                        payout = wager * 2
                        win = True
                    if bet_choice == "19-36" and result not in ["0", "00"] and 19 <= int(result) <= 36:
                        payout = wager * 2
                        win = True

                    if bet_choice == "1st12" and result not in ["0", "00"] and 1 <= int(result) <= 12:
                        payout = wager * 3
                        win = True
                    if bet_choice == "2nd12" and result not in ["0", "00"] and 13 <= int(result) <= 24:
                        payout = wager * 3
                        win = True
                    if bet_choice == "3rd12" and result not in ["0", "00"] and 25 <= int(result) <= 36:
                        payout = wager * 3
                        win = True

                    # 🍺 salvage luck on color bets only
                    if not win and boosted_color and bet_choice in ["red", "black"]:
                        if random.random() < ROULETTE_COLOR_SALVAGE:
                            payout = wager * 2
                            win = True
                            salvaged = True

                    if win:
                        balances[uid2] = balances.get(uid2, 0.0) + payout
                        note = " (🍺 lucky sway!)" if salvaged else ""
                        embed_win = discord.Embed(
                            title="✅ Winner!",
                            description=f"<@{uid2}> won **${payout:,.2f}** betting **{bet_choice}**{note}.",
                            color=discord.Color.green()
                        )
                        await chan.send(embed=embed_win)
                    else:
                        embed_lose = discord.Embed(
                            title="❌ Lost",
                            description=f"<@{uid2}> lost **${wager:,.2f}** betting **{bet_choice}**.",
                            color=discord.Color.red()
                        )
                        await chan.send(embed=embed_lose)

                save_balances()

            # decrement buffs
            for bet_data in roulette_game["bets"]:
                uid = str(bet_data["user_id"])
                if uid in buffs and "alcohol" in buffs[uid]:
                    buffs[uid]["alcohol"]["uses"] -= 1
                    if buffs[uid]["alcohol"]["uses"] <= 0:
                        del buffs[uid]["alcohol"]
            save_buffs()

            roulette_game["active"] = False
            roulette_game["bets"] = []
            roulette_game["channel_id"] = None

        asyncio.create_task(finish_round())
        return

    # join active game
    if roulette_game["active"]:
        if interaction.channel_id != roulette_game["channel_id"]:
            chan = bot.get_channel(roulette_game["channel_id"])
            chan_mention = chan.mention if chan else "#unknown"
            await interaction.followup.send(
                f"❌ A roulette game is already running in {chan_mention}. Please join it there!",
                ephemeral=True
            )
            return

        await append_bet(first=False)




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


@bot.tree.command(name="resetbalances", description="Admin: reset ALL user balances to $0 (irreversible without backup)")
@app_commands.describe(confirm="Type CONFIRM to perform the reset")
async def resetbalances(interaction: discord.Interaction, confirm: str):
    # admin check
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You must be a server administrator to use this.", ephemeral=True)
        return

    if confirm != "CONFIRM":
        await interaction.response.send_message(
            "⚠️ This will reset everyone's balance to $0. To confirm, re-run the command with `confirm=CONFIRM`.",
            ephemeral=True
        )
        return

    # Backup current balances & job_counts
    try:
        ts = int(time.time())
        backup_name = f"balances_backup_{ts}.json"
        data_to_backup = {
            "balances": balances,
            "job_counts": job_counts
        }
        with open(backup_name, "w", encoding="utf-8") as bf:
            json.dump(data_to_backup, bf, indent=2)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to create backup: {e}", ephemeral=True)
        return

    # Reset balances in memory
    for uid in list(balances.keys()):
        balances[uid] = 0.0

    # Save to disk (use your existing save function)
    try:
        save_balances()
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to save balances: {e}", ephemeral=True)
        return

    # public-ish confirmation (ephemeral + channel note)
    await interaction.response.send_message(
        f"✅ All balances reset to $0. Backup saved as `{backup_name}`.",
        ephemeral=True
    )

    # optional public announcement in the channel
    await interaction.channel.send(f"⚠️ All balances were reset by {interaction.user.mention}. Backup: `{backup_name}`")

@bot.tree.command(name="resetbalance", description="Admin: reset one user's balance to $0.00")
@app_commands.describe(member="The user to reset")
async def resetbalance(interaction: discord.Interaction, member: discord.Member):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You must be an administrator to use this.", ephemeral=True)
        return

    uid = member.id
    if uid not in balances:
        await interaction.response.send_message(f"ℹ️ {member.display_name} has no balance recorded.", ephemeral=True)
        return

    balances[uid] = 0.0
    save_balances()
    await interaction.response.send_message(f"✅ Reset {member.mention}'s balance to $0.00.", ephemeral=False)

@bot.tree.command(name="alcohol", description="Buy a temporary luck boost for gambling (5 uses). Costs $5,000. 6h cooldown.")
async def alcohol_cmd(interaction: discord.Interaction):
    uid = interaction.user.id
    bal = balances.get(uid, 0.0)

    # cooldown check
    cd_left = alcohol_cooldown_left(uid)
    if cd_left > 0:
        hours = cd_left // 3600
        mins = (cd_left % 3600) // 60
        secs = cd_left % 60
        await interaction.response.send_message(
            f"⏳ You can buy alcohol again in **{hours}h {mins}m {secs}s**.",
            ephemeral=True
        )
        return

    # cost check
    if bal < ALCOHOL_PRICE:
        await interaction.response.send_message("❌ You don’t have $5,000 for this.", ephemeral=True)
        return

    # charge and grant
    balances[uid] = bal - ALCOHOL_PRICE
    save_balances()

    rec = get_boost_record(uid)
    rec["uses"] = ALCOHOL_BOOST_USES
    rec["cooldown_until"] = int(time.time()) + ALCOHOL_COOLDOWN
    save_buffs()

    embed = discord.Embed(
        title="🍺 Liquid Courage Purchased!",
        description=(
            f"You bought alcohol for **${ALCOHOL_PRICE:,.2f}**.\n"
            f"**Boosts:** {ALCOHOL_BOOST_USES} gambling commands\n"
            f"**Coinflip:** {int(COINFLIP_BOOST_WINPROB*100)}/{int((1-COINFLIP_BOOST_WINPROB)*100)} odds\n"
            f"**Roulette:** color bets get a small per-bet luck sway (only for you).\n"
            f"**Cooldown:** 6 hours"
        ),
        color=discord.Color.gold()
    )
    embed.set_footer(text="You feel...Courageous...The roads look mighty fine right now...")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="buffs", description="Check your active buffs")
async def show_buffs(interaction: discord.Interaction):
    user_id = str(interaction.user.id)

    if user_id not in buffs or not buffs[user_id]:
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🍹 Active Buffs",
                description="You don’t have any active buffs right now.",
                color=discord.Color.red()
            ),
            ephemeral=True
        )
        return

    desc_lines = []
    for buff_name, buff_data in buffs[user_id].items():
        if buff_name == "alcohol":
            desc_lines.append(
                f"🍺 **Alcohol Luck** — {buff_data['uses']} uses left "
                f"(cooldown 6h before rebuy)"
            )

    embed = discord.Embed(
        title="🍹 Active Buffs",
        description="\n".join(desc_lines),
        color=discord.Color.green()
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)




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

