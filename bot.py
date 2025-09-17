# --- imports & setup ---
import os
import time
import random
import asyncio
import json
import asyncpg
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv


# --------------------------------
# Version / Bot setup
# --------------------------------
BOT_VERSION = "V0.0.09"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --------------------------------
# Channel IDs (replace with yours)
# --------------------------------
ANNOUNCE_CHANNEL_ID = 1417338592359092235
WORK_CHANNEL_ID = 1417332114453430282
ROULETTE_CHANNEL_ID = 1417369961172697090
PATCH_NOTES_CHANNEL_ID = 1417353769037070366  # unused here but kept for parity

# --------------------------------
# Database (Postgres via asyncpg)
# --------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")

async def init_db():
    async with pool.acquire() as conn:
        # balances
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS balances (
                user_id BIGINT PRIMARY KEY,
                balance DOUBLE PRECISION DEFAULT 0
            )
        """)
        # job counts
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS job_counts (
                user_id BIGINT PRIMARY KEY,
                common INT DEFAULT 0,
                uncommon INT DEFAULT 0,
                rare INT DEFAULT 0,
                epic INT DEFAULT 0,
                legendary INT DEFAULT 0,
                secret INT DEFAULT 0,
                special INT DEFAULT 0
            )
        """)
        # highest jobs
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS highest_jobs (
                user_id BIGINT PRIMARY KEY,
                job TEXT,
                rarity TEXT,
                amount DOUBLE PRECISION DEFAULT 0
            )
        """)
        # buffs
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS buffs (
                user_id BIGINT PRIMARY KEY,
                uses INT DEFAULT 0,
                cooldown_until BIGINT DEFAULT 0
            )
        """)

# ---------- DB helpers ----------
async def get_balance(uid: int) -> float:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT balance FROM balances WHERE user_id=$1", uid)
        return float(row["balance"]) if row else 0.0

async def set_balance(uid: int, amount: float):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO balances (user_id, balance)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET balance=EXCLUDED.balance
        """, uid, amount)

async def add_balance(uid: int, delta: float) -> float:
    new_bal = await get_balance(uid) + float(delta)
    await set_balance(uid, new_bal)
    return new_bal

async def get_job_counts(uid: int) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT common,uncommon,rare,epic,legendary,secret,special
            FROM job_counts WHERE user_id=$1
        """, uid)
    if not row:
        return {"common":0,"uncommon":0,"rare":0,"epic":0,"legendary":0,"secret":0,"special":0}
    return {
        "common": row["common"], "uncommon": row["uncommon"], "rare": row["rare"],
        "epic": row["epic"], "legendary": row["legendary"], "secret": row["secret"],
        "special": row["special"]
    }

async def set_job_counts(uid: int, counts: dict):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO job_counts (user_id, common, uncommon, rare, epic, legendary, secret, special)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            ON CONFLICT (user_id) DO UPDATE SET
              common=EXCLUDED.common, uncommon=EXCLUDED.uncommon, rare=EXCLUDED.rare,
              epic=EXCLUDED.epic, legendary=EXCLUDED.legendary, secret=EXCLUDED.secret, special=EXCLUDED.special
        """, uid, counts["common"], counts["uncommon"], counts["rare"],
             counts["epic"], counts["legendary"], counts["secret"], counts["special"])

async def increment_job(uid: int, rarity: str):
    # fetch & bump atomic enough for our use (single instance)
    counts = await get_job_counts(uid)
    counts[rarity] = counts.get(rarity, 0) + 1
    await set_job_counts(uid, counts)

async def get_total_jobs(uid: int) -> int:
    c = await get_job_counts(uid)
    return int(sum(c.values()))

async def get_highest_job(uid: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT job, rarity, amount FROM highest_jobs WHERE user_id=$1", uid)
    return {"job": row["job"], "rarity": row["rarity"], "amount": float(row["amount"])} if row else None

async def update_highest_job(uid: int, job: str, rarity: str, amount: float):
    current = await get_highest_job(uid)
    if (not current) or amount > current["amount"]:
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO highest_jobs (user_id, job, rarity, amount)
                VALUES ($1,$2,$3,$4)
                ON CONFLICT (user_id) DO UPDATE SET
                  job=EXCLUDED.job, rarity=EXCLUDED.rarity, amount=EXCLUDED.amount
            """, uid, job, rarity, amount)

async def reset_all_balances():
    async with pool.acquire() as conn:
        await conn.execute("UPDATE balances SET balance=0")

async def reset_user_balance(uid: int):
    await set_balance(uid, 0.0)

async def reset_all_jobs():
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM job_counts")
        await conn.execute("DELETE FROM highest_jobs")

async def reset_user_jobs(uid: int):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM job_counts WHERE user_id=$1", uid)
        await conn.execute("DELETE FROM highest_jobs WHERE user_id=$1", uid)

async def export_state_to_file(path: str):
    dump = {"balances": {}, "job_counts": {}, "highest_jobs": {}, "buffs": {}}
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, balance FROM balances")
        dump["balances"] = {str(r["user_id"]): float(r["balance"]) for r in rows}
        rows = await conn.fetch("SELECT * FROM job_counts")
        for r in rows:
            dump["job_counts"][str(r["user_id"])] = {
                "common": r["common"], "uncommon": r["uncommon"], "rare": r["rare"],
                "epic": r["epic"], "legendary": r["legendary"], "secret": r["secret"], "special": r["special"]
            }
        rows = await conn.fetch("SELECT user_id, job, rarity, amount FROM highest_jobs")
        dump["highest_jobs"] = {str(r["user_id"]): {"job": r["job"], "rarity": r["rarity"], "amount": float(r["amount"])} for r in rows}
        rows = await conn.fetch("SELECT user_id, uses, cooldown_until FROM buffs")
        dump["buffs"] = {str(r["user_id"]): {"uses": r["uses"], "cooldown_until": r["cooldown_until"]} for r in rows}

    with open(path, "w", encoding="utf-8") as f:
        json.dump(dump, f, indent=2)

# ---------- Alcohol / Buffs ----------
ALCOHOL_PRICE = 5_000.0
ALCOHOL_COOLDOWN = 6 * 60 * 60
ALCOHOL_BOOST_USES = 5
COINFLIP_BOOST_WINPROB = 0.54
ROULETTE_COLOR_SALVAGE = 0.025

async def get_boost_record(uid: int) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT uses, cooldown_until FROM buffs WHERE user_id=$1", uid)
    return {"uses": row["uses"], "cooldown_until": row["cooldown_until"]} if row else {"uses": 0, "cooldown_until": 0}

async def set_boost_record(uid: int, uses: int, cooldown_until: int):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO buffs (user_id, uses, cooldown_until)
            VALUES ($1,$2,$3)
            ON CONFLICT (user_id) DO UPDATE SET
              uses=EXCLUDED.uses, cooldown_until=EXCLUDED.cooldown_until
        """, uid, uses, cooldown_until)

async def has_active_alcohol(uid: int) -> bool:
    return (await get_boost_record(uid)).get("uses", 0) > 0

async def consume_alcohol_use(uid: int) -> int:
    rec = await get_boost_record(uid)
    uses = max(0, int(rec.get("uses", 0)) - 1)
    await set_boost_record(uid, uses, int(rec.get("cooldown_until", 0)))
    return uses

def alcohol_cooldown_left_sync(rec: dict) -> int:
    return max(0, int(rec.get("cooldown_until", 0)) - int(time.time()))

# ---------- Test / Debug globals ----------
test_mode = False
BYPASS_CAREER = False

# default odds
SPECIAL_CHANCE = 0.02
TIP_BASE_CHANCE = 0.25
DEV_CHANCE_DENOM = 7777

# test-mode overrides
_TEST_SPECIAL_CHANCE = 0.5
_TEST_TIP_BASE_CHANCE = 1.0
_TEST_DEV_CHANCE_DENOM = 5

# test-mode allowed distribution
_TEST_ALLOWED = {
    "common": 30, "uncommon": 25, "rare": 20, "epic": 15, "legendary": 7, "secret": 3
}

# ---------- Career Path ----------
CAREER_PATH = [
    {"name": "Temp Worker",         "required": 0,     "role_id": 1417346927246315551, "allowed": {"common": 100, "uncommon": 0,  "rare": 0,  "epic": 0,  "legendary": 0,  "secret": 0}},
    {"name": "Intern",              "required": 100,   "role_id": 1417347155617644545, "allowed": {"common": 80,  "uncommon": 15, "rare": 5,  "epic": 0,  "legendary": 0,  "secret": 0}},
    {"name": "Low-Level Associate", "required": 250,   "role_id": 1417347223875751976, "allowed": {"common": 70,  "uncommon": 20, "rare": 8,  "epic": 2,  "legendary": 0,  "secret": 0}},
    {"name": "Mid-Level Associate", "required": 500,   "role_id": 1417347300807938150, "allowed": {"common": 60,  "uncommon": 25, "rare":10,  "epic": 5,  "legendary": 0,  "secret": 0}},
    {"name": "Senior Associate",    "required": 1000,  "role_id": 1417347359196577913, "allowed": {"common": 50,  "uncommon": 30, "rare":12,  "epic": 7,  "legendary": 1,  "secret": 0}},
    {"name": "Lower Management",    "required": 1500,  "role_id": 1417347412845924372, "allowed": {"common": 40,  "uncommon": 35, "rare":15,  "epic": 8,  "legendary": 2,  "secret": 0}},
    {"name": "Upper Management",    "required": 2500,  "role_id": 1417347538968903855, "allowed": {"common": 35,  "uncommon": 35, "rare":18,  "epic":10,  "legendary": 2,  "secret": 0}},
    {"name": "HR Administrator",    "required": 3500,  "role_id": 1417347593700380703, "allowed": {"common": 30,  "uncommon": 35, "rare":20,  "epic":12,  "legendary": 3,  "secret": 0}},
    {"name": "Senior Director",     "required": 5000,  "role_id": 1417668804606955581, "allowed": {"common": 25,  "uncommon": 35, "rare":22,  "epic":13,  "legendary": 5,  "secret": 0}},
    {"name": "Vice President",      "required": 7500,  "role_id": 1417668874026876948, "allowed": {"common": 20,  "uncommon": 35, "rare":25,  "epic":15,  "legendary": 5,  "secret": 0}},
    {"name": "President",           "required": 15000, "role_id": 1417668935569899630, "allowed": {"common": 15,  "uncommon": 30, "rare":25,  "epic":20,  "legendary": 8,  "secret": 2}},
    {"name": "Board of Affairs",    "required": 20000, "role_id": 1417669003890921583, "allowed": {"common": 10,  "uncommon": 25, "rare":30,  "epic":20,  "legendary":10,  "secret": 5}},
    {"name": "CEO",                 "required": 30000, "role_id": 1417669100976734218, "allowed": {"common": 5,   "uncommon": 20, "rare":30,  "epic":25,  "legendary":15,  "secret": 5}},
    {"name": "Employed",            "required": 50000, "role_id": 1417348260926062712, "allowed": {"common": 0,   "uncommon": 15, "rare":25,  "epic":30,  "legendary":20,  "secret":10}},
]

async def get_career_tier(user_id: int) -> dict:
    total_jobs = await get_total_jobs(user_id)
    current = CAREER_PATH[0]
    for tier in CAREER_PATH:
        if total_jobs >= tier["required"]:
            current = tier
        else:
            break
    return current

# ---------- Flair / Colors / Emojis ----------
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

# ---------- Special Jobs ----------
special_jobs = [
    {"name": "lightning",   "desc": "⚡ A flash sale struck! You flipped items like crazy.",           "color": discord.Color.yellow(),     "payout": (80_000, 200_000)},
    {"name": "glitch",      "desc": "zzzzAAAAAAZ_>>>////\\| Wow! the job is, bugged? who knows here is some cash for finding this!", "color": discord.Color.magenta(), "payout": (200_000, 300_000)},
    {"name": "dev",         "desc": "👨‍💻 how did you find this? this should exist, who are you?",     "color": discord.Color.dark_red(),   "payout": (1_500_000, 1_500_000)},
    {"name": "toilet",      "desc": "🚽 You cleaned the toilets but got covered in poo, womp womp",    "color": discord.Color.dark_gray(),  "payout": (0.25, 0.25)},
    {"name": "meme69",      "desc": "😂 Nice. Somebody tipped you $69.",                               "color": discord.Color.green(),      "payout": (69, 69)},
    {"name": "meme420",     "desc": "🔥 pass da kush You got tipped $420 for style.",                  "color": discord.Color.dark_green(), "payout": (420, 420)},
    {"name": "goldrush",    "desc": "🏆 GOLD RUSH! You sold golden nuggets.",                          "color": discord.Color.gold(),       "payout": (300_000, 600_000)},
    {"name": "lottery",     "desc": "🎟️ holy shit YOU WON THE POWERBALL!",                            "color": discord.Color.teal(),       "payout": (150_000, 500_000)},
    {"name": "sponsorship", "desc": "📢 Sponsored by a Shady Brand™.",                                 "color": discord.Color.orange(),     "payout": (100_000, 250_000)},
    {"name": "artifact",    "desc": "🗿 You found a priceless artifact.",                              "color": discord.Color.blue(),       "payout": (200_000, 400_000)}
]

def _special_job_gate(name: str) -> bool:
    if name == "dev":
        return random.randint(1, DEV_CHANCE_DENOM) == 777
    if name == "glitch":
        return random.random() <= 0.30
    return True  # others pass once special triggers

def pick_special_job():
    if random.random() > SPECIAL_CHANCE:
        return None
    job = random.choice(special_jobs)
    if not _special_job_gate(job["name"]):
        return None
    payout_value = round(random.uniform(*job["payout"]), 2)
    return {"name": job["name"], "desc": job["desc"], "color": job["color"], "payout_value": payout_value}

# ---------- Tips ----------
# Note: you said 100% during test mode, base 0.25 normally (we set default above)
tip_tiers = [
    {"name": "coffee change",        "emoji": "☕", "range": (1.05, 1.15), "weight": 25, "flavor": "a quick thanks and some coffee money."},
    {"name": "spare cash",           "emoji": "💵", "range": (1.10, 1.25), "weight": 20, "flavor": "they tossed in a little extra."},
    {"name": "sweet old lady",       "emoji": "🧓", "range": (1.25, 1.75), "weight": 16, "flavor": "you did a great job — she insisted you take more!"},
    {"name": "great review bonus",   "emoji": "⭐", "range": (1.75, 2.25), "weight": 12, "flavor": "5★ review and a thank-you bonus."},
    {"name": "weekend rush",         "emoji": "📈", "range": (2.25, 2.75), "weight": 9,  "flavor": "busy day surge pricing hits."},
    {"name": "manager’s envelope",   "emoji": "✉️", "range": (2.75, 3.25), "weight": 7,  "flavor": "the boss quietly slipped you something extra."},
    {"name": "billionaire bonus",    "emoji": "🤑", "range": (3.00, 5.00), "weight": 5,  "flavor": "you worked for a rich billionaire — they loved it!"},
    {"name": "angel investor",       "emoji": "😇", "range": (5.00, 7.00), "weight": 3,  "flavor": "an ‘angel’ dropped a very generous tip."},
    {"name": "whale tip",            "emoji": "🐋", "range": (7.00, 10.00), "weight": 2, "flavor": "a high-roller was wildly impressed."},
    {"name": "legend of generosity", "emoji": "🏆", "range": (10.00, 12.00), "weight": 1, "flavor": "a once-in-a-blue-moon legendary gratuity!"}
]

def roll_tip():
    if random.random() > TIP_BASE_CHANCE:
        return None
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
    return {"name": chosen["name"], "emoji": chosen["emoji"], "flavor": chosen["flavor"], "mult": mult}

# ---------- Normal Jobs ----------
jobs = {
    "common": {
        "chance": 0.55,
        "payout": (10, 80),
        "list": [
            "washed someone’s car","buttered a baguette","mowed a lawn","delivered a pizza","walked a dog","helped carry groceries",
            "cleaned a garage","painted a fence","tutored a kid","bagged groceries","worked as a cashier","raked leaves","did laundry",
            "shoveled snow","washed dishes","babysat for a neighbor","picked up trash","organized a closet","recycled cans","swept a porch",
            "helped move furniture","assembled flat-pack furniture","sorted library books","wiped store shelves","restocked a cooler",
            "cleaned aquarium glass","handed out flyers","watered plants","vacuumed a car interior","cleaned windows","ran a coffee errand",
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
            "modeled for a commercial","played pickleball","worked backstage at a concert","helped a local news team",
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
        "payout": (15000, 75000),
        "list": [
            "helped launch a rocket","jorked off a dwarf","discovered hidden treasure","performed in a world-famous concert",
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
            "won a mysterious briefcase auction","found a safe behind a wall","sold a rare diamond at midnight",
            "hacked into a forgotten crypto wallet","discovered hidden cave paintings","restored an ancient manuscript",
            "found $500,000 in attic","traded a golden Pokémon card","repaired a broken Fabergé egg","auctioned ancient coins"
        ]
    }
}

RARITY_ORDER = ["common","uncommon","rare","epic","legendary","secret"]

async def pick_job(user_id: int):
    if test_mode or BYPASS_CAREER:
        allowed = _TEST_ALLOWED.copy()
        career_name = "TEST MODE"
    else:
        tier = await get_career_tier(user_id)
        allowed = dict(tier.get("allowed", {}))
        career_name = tier.get("name", "Temp Worker")

    total_pct = sum(allowed.values()) or 100
    roll = random.uniform(0, total_pct)
    cum = 0.0
    chosen_rarity = "common"
    for r, pct in allowed.items():
        cum += pct
        if roll <= cum:
            chosen_rarity = r
            break

    if chosen_rarity not in jobs:
        chosen_rarity = "common"

    job = random.choice(jobs[chosen_rarity]["list"])
    payout = round(random.uniform(*jobs[chosen_rarity]["payout"]), 2)
    return chosen_rarity, job, payout, career_name

# ---------- Discord events ----------
import ssl

pool = None  # define at top of file, but don’t await here

@bot.event
async def on_ready():
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(DATABASE_URL)  # no ssl
        await init_db()

    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user} and slash commands synced!")
    activity = discord.CustomActivity(name=f"Getting a J*B at {BOT_VERSION}")
    await bot.change_presence(status=discord.Status.online, activity=activity)



# ---------- Commands ----------
@bot.tree.command(name="balance", description="Check how much money you have")
async def balance_cmd(interaction: discord.Interaction):
    user_id = interaction.user.id
    dollars = await get_balance(user_id)

    embed = discord.Embed(
        title="💰 Balance Check",
        description=f"Your wallet has: **${dollars:,.2f}**",
        color=discord.Color.green()
    )
    embed.set_footer(text=f"Requested by {interaction.user.name}")
    await interaction.response.send_message(embed=embed)

# Test mode toggler
@bot.tree.command(name="testmode", description="Toggle test mode (admin only)")
async def testmode_cmd(interaction: discord.Interaction, toggle: str):
    global test_mode, BYPASS_CAREER, SPECIAL_CHANCE, TIP_BASE_CHANCE, DEV_CHANCE_DENOM
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You don’t have permission to use this.", ephemeral=True)
        return

    tgl = toggle.lower()
    if tgl == "on":
        test_mode = True
        BYPASS_CAREER = True
        SPECIAL_CHANCE = _TEST_SPECIAL_CHANCE
        TIP_BASE_CHANCE = _TEST_TIP_BASE_CHANCE
        DEV_CHANCE_DENOM = _TEST_DEV_CHANCE_DENOM
        await interaction.response.send_message(
            "🧪 Test mode **ON** — career restrictions bypassed, tips forced, and special/dev odds boosted."
        )
    elif tgl == "off":
        test_mode = False
        BYPASS_CAREER = False
        SPECIAL_CHANCE = 0.02
        TIP_BASE_CHANCE = 0.25
        DEV_CHANCE_DENOM = 7777
        await interaction.response.send_message(
            "🧪 Test mode **OFF** — odds restored to normal and career gating re-enabled."
        )
    else:
        await interaction.response.send_message("Usage: `/testmode on` or `/testmode off`", ephemeral=True)

# Coinflip (cooldown)
coinflip_cooldown = app_commands.checks.cooldown(1, 15.0, key=lambda i: i.user.id)

@bot.tree.command(name="coinflip", description="Bet money on a coinflip (heads or tails)")
@app_commands.describe(choice="Your guess: heads or tails", amount="How much money to bet")
@coinflip_cooldown
async def coinflip(interaction: discord.Interaction, choice: str, amount: float):
    uid = interaction.user.id
    choice = choice.lower()
    if choice not in ["heads", "tails"]:
        await interaction.response.send_message("❌ Please choose either 'heads' or 'tails'.", ephemeral=True)
        return

    bal = await get_balance(uid)
    if amount <= 0:
        await interaction.response.send_message("❌ Bet amount must be greater than zero.", ephemeral=True); return
    if amount > 500_000:
        await interaction.response.send_message("❌ The maximum bet is $500,000.", ephemeral=True); return
    if amount > bal:
        await interaction.response.send_message("❌ You don’t have enough money for that bet.", ephemeral=True); return

    boosted = await has_active_alcohol(uid)
    win_prob = COINFLIP_BOOST_WINPROB if boosted else 0.5
    win = random.random() < win_prob
    result = choice if win else ("tails" if choice == "heads" else "heads")

    if win:
        await add_balance(uid, amount)
        outcome = f"🎉 You guessed **{choice}** and it landed **{result}**! You won **${amount:,.2f}**."
        color = discord.Color.green()
    else:
        await add_balance(uid, -amount)
        outcome = f"😢 You guessed **{choice}** but it landed **{result}**. You lost **${amount:,.2f}**."
        color = discord.Color.red()

    boost_line = ""
    if boosted:
        left = await consume_alcohol_use(uid)
        boost_line = f"\n🍺 Alcohol boost used. **{left}** use(s) left."

    new_bal = await get_balance(uid)
    embed = discord.Embed(
        title="🪙 Coinflip",
        description=f"{outcome}{boost_line}\n\n💼 Wallet Balance: **${new_bal:,.2f}**",
        color=color
    )
    embed.set_footer(text=f"Bet: ${amount:,.2f}")
    await interaction.response.send_message(embed=embed)

@coinflip.error
async def coinflip_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"⏳ You need to wait {error.retry_after:.1f} seconds before using /coinflip again.",
            ephemeral=True
        )

# Roulette
ROULETTE_WINDOW_SECONDS = 15
roulette_game = {"active": False, "bets": [], "channel_id": None}

@bot.tree.command(name="roulette", description="Join the roulette table and place your bet")
@app_commands.describe(
    bet="Your bet type (red, black, green, odd, even, 1-18, 19-36, 1st12, 2nd12, 3rd12, or a number 0-36/00)",
    amount="How much money to bet"
)
async def roulette(interaction: discord.Interaction, bet: str, amount: float):
    global roulette_game
    await interaction.response.defer(thinking=False, ephemeral=False)

    if interaction.channel_id != ROULETTE_CHANNEL_ID:
        await interaction.followup.send(
            f"❌ Roulette can only be played in <#{ROULETTE_CHANNEL_ID}>.",
            ephemeral=True
        )
        return

    uid = interaction.user.id
    bet = bet.lower()

    valid_bets = ["red","black","green","odd","even","1-18","19-36","1st12","2nd12","3rd12"] + [str(n) for n in range(37)] + ["00"]
    if bet not in valid_bets:
        await interaction.followup.send(
            "❌ Invalid bet. Try red, black, green, odd, even, 1-18, 19-36, 1st12, 2nd12, 3rd12, or a number (0-36, 00).",
            ephemeral=True
        )
        return

    bal = await get_balance(uid)
    if amount <= 0:
        await interaction.followup.send("❌ Bet amount must be greater than zero.", ephemeral=True); return
    if amount > 500_000:
        await interaction.followup.send("❌ The maximum bet is $500,000.", ephemeral=True); return
    if amount > bal:
        await interaction.followup.send("❌ You don’t have enough money to place that bet.", ephemeral=True); return

    async def append_bet(first: bool):
        boosted_now = (await has_active_alcohol(uid)) and (bet in ["red","black"])
        await add_balance(uid, -amount)

        if boosted_now:
            left = await consume_alcohol_use(uid)
            boost_note = f"\n🍺 Alcohol luck will apply to this **{bet}** bet. ({left} uses left)"
        else:
            boost_note = ""

        roulette_game["bets"].append({
            "user_id": uid, "bet": bet, "amount": amount, "boosted_color": boosted_now
        })

        embed_bet = discord.Embed(
            title="🎲 First Bet Placed" if first else "🎲 Bet Placed",
            description=f"{interaction.user.mention} wagered **${amount:,.2f}** on **{bet}**!{boost_note}",
            color=discord.Color.blurple()
        )
        chan = bot.get_channel(roulette_game["channel_id"])
        if first:
            await chan.send(embed=embed_bet)
        else:
            await interaction.followup.send(embed=embed_bet)

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

            # spin wheel
            spin = random.randint(0, 37)
            if spin == 37:
                result = "00"; color = "green"
            else:
                result = str(spin)
                if spin in {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}:
                    color = "red"
                elif spin in {2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35}:
                    color = "black"
                else:
                    color = "green"

            if chan:
                await chan.send(embed=discord.Embed(
                    title="🎲 The Ball Landed!",
                    description=f"**{color.capitalize()} {result}**",
                    color=discord.Color.green() if color == "green" else (discord.Color.red() if color == "red" else discord.Color.dark_gray())
                ))

                # settle bets
                for bet_data in roulette_game["bets"]:
                    uid2 = bet_data["user_id"]
                    bet_choice = bet_data["bet"]
                    wager = bet_data["amount"]
                    boosted_color = bet_data.get("boosted_color", False)

                    payout = 0.0
                    win = False
                    salvaged = False

                    if bet_choice == result or (bet_choice == "00" and result == "00"):
                        payout = wager * 35; win = True
                    if bet_choice in ["red","black"] and bet_choice == color:
                        payout = max(payout, wager * 2); win = True
                    if bet_choice == "green" and color == "green":
                        payout = max(payout, wager * 35); win = True
                    if bet_choice == "odd" and result not in ["0","00"] and int(result) % 2 == 1:
                        payout = max(payout, wager * 2); win = True
                    if bet_choice == "even" and result not in ["0","00"] and int(result) % 2 == 0:
                        payout = max(payout, wager * 2); win = True
                    if bet_choice == "1-18" and result not in ["0","00"] and 1 <= int(result) <= 18:
                        payout = max(payout, wager * 2); win = True
                    if bet_choice == "19-36" and result not in ["0","00"] and 19 <= int(result) <= 36:
                        payout = max(payout, wager * 2); win = True
                    if bet_choice == "1st12" and result not in ["0","00"] and 1 <= int(result) <= 12:
                        payout = max(payout, wager * 3); win = True
                    if bet_choice == "2nd12" and result not in ["0","00"] and 13 <= int(result) <= 24:
                        payout = max(payout, wager * 3); win = True
                    if bet_choice == "3rd12" and result not in ["0","00"] and 25 <= int(result) <= 36:
                        payout = max(payout, wager * 3); win = True

                    # salvage if boosted color bet and lost
                    if not win and boosted_color and bet_choice in ["red","black"]:
                        if random.random() < ROULETTE_COLOR_SALVAGE:
                            payout = wager * 2
                            win = True
                            salvaged = True

                    if win:
                        await add_balance(uid2, payout)
                        note = " (🍺 lucky sway!)" if salvaged else ""
                        await chan.send(embed=discord.Embed(
                            title="✅ Winner!",
                            description=f"<@{uid2}> won **${payout:,.2f}** betting **{bet_choice}**{note}.",
                            color=discord.Color.green()
                        ))
                    else:
                        await chan.send(embed=discord.Embed(
                            title="❌ Lost",
                            description=f"<@{uid2}> lost **${wager:,.2f}** betting **{bet_choice}**.",
                            color=discord.Color.red()
                        ))

            roulette_game["active"] = False
            roulette_game["bets"] = []
            roulette_game["channel_id"] = None

        asyncio.create_task(finish_round())
        return

    # join active game
    if roulette_game["active"]:
        if interaction.channel_id != roulette_game["channel_id"]:
            chan = bot.get_channel(roulette_game["channel_id"])
            mention = chan.mention if chan else "#unknown"
            await interaction.followup.send(
                f"❌ A roulette game is already running in {mention}. Please join it there!",
                ephemeral=True
            ); return
        await append_bet(first=False)

# Jobstats
@bot.tree.command(name="jobstats", description="Check detailed job stats")
async def jobstats(interaction: discord.Interaction):
    uid = interaction.user.id
    counts = await get_job_counts(uid)
    total_jobs = sum(counts.values())

    embed = discord.Embed(
        title=f"📊 Job Stats for {interaction.user.display_name}",
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
    await interaction.response.send_message(embed=embed)

# Fish (punishment)
@bot.tree.command(name="fish", description="Try to fish (but not in this bot!)")
async def fish(interaction: discord.Interaction):
    uid = interaction.user.id
    balance = await get_balance(uid)

    if balance <= 0:
        await interaction.response.send_message("🎣 not here, wrong server dummy, Punishment time!")
        return

    penalty = round(balance * 0.05, 2)
    await add_balance(uid, -penalty)

    new_balance = await get_balance(uid)
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

# Leaderboards
async def get_top_balances(limit=10):
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, balance FROM balances ORDER BY balance DESC LIMIT $1", limit)
    return [(int(r["user_id"]), float(r["balance"])) for r in rows]

@bot.tree.command(name="leaderboardmoney", description="Show the top users by wallet balance")
async def leaderboardmoney(interaction: discord.Interaction):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("❌ This command can only be used in a server.")
        return

    rows = await get_top_balances(10)
    if not rows:
        await interaction.response.send_message("No balances to show yet!", ephemeral=True)
        return

    lines = []
    for i, (uid, bal) in enumerate(rows, start=1):
        member = guild.get_member(uid)
        if member:
            name = member.mention
        else:
            try:
                user = await bot.fetch_user(uid)
                name = user.name
            except:
                name = f"User {uid}"
        medal = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"{i}."
        lines.append(f"{medal} {name} — **${bal:,.2f}**")

    embed = discord.Embed(
        title="💰 Economy Leaderboard",
        description="**Top 10 Users by Balance**\n\n" + "\n".join(lines),
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed)

async def get_top_jobs(limit=10):
    # compute totals in SQL, defaulting NULLs to 0
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT user_id,
                COALESCE(common,0)+COALESCE(uncommon,0)+COALESCE(rare,0)+
                COALESCE(epic,0)+COALESCE(legendary,0)+COALESCE(secret,0)+COALESCE(special,0) AS total
            FROM job_counts
            ORDER BY total DESC
            LIMIT $1
        """, limit)
    return [(int(r["user_id"]), int(r["total"])) for r in rows]

@bot.tree.command(name="leaderboardjob", description="Show the top users by total jobs worked")
async def leaderboardjob(interaction: discord.Interaction):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("❌ This command can only be used in a server.")
        return

    rows = await get_top_jobs(10)
    if not rows:
        await interaction.response.send_message("No job records to show yet!", ephemeral=True)
        return

    lines = []
    for i, (uid, total) in enumerate(rows, start=1):
        member = guild.get_member(uid)
        if member:
            name = member.mention
        else:
            try:
                user = await bot.fetch_user(uid)
                name = user.name
            except:
                name = f"User {uid}"
        medal = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"{i}."
        lines.append(f"{medal} {name} — **{total:,} jobs**")

    embed = discord.Embed(
        title="📊 Jobs Leaderboard",
        description="**Top 10 Users by Jobs Worked**\n\n" + "\n".join(lines),
        color=discord.Color.blurple()
    )
    await interaction.response.send_message(embed=embed)

# Reset balances (all)
@bot.tree.command(name="resetbalances", description="Admin: reset ALL user balances to $0 (irreversible without backup)")
@app_commands.describe(confirm="Type CONFIRM to perform the reset")
async def resetbalances(interaction: discord.Interaction, confirm: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You must be a server administrator to use this.", ephemeral=True)
        return

    if confirm != "CONFIRM":
        await interaction.response.send_message(
            "⚠️ This will reset everyone's balance to $0. To confirm, re-run with `confirm=CONFIRM`.",
            ephemeral=True
        )
        return

    # backup dump to a file in the container (ephemeral, but helpful)
    try:
        ts = int(time.time())
        backup_name = f"db_backup_{ts}.json"
        await export_state_to_file(backup_name)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to create backup: {e}", ephemeral=True)
        return

    await reset_all_balances()
    await interaction.response.send_message(
        f"✅ All balances reset to $0. Backup saved as `{backup_name}`.",
        ephemeral=True
    )
    await interaction.channel.send(f"⚠️ All balances were reset by {interaction.user.mention}. Backup: `{backup_name}`")

# Reset one balance
@bot.tree.command(name="resetbalance", description="Admin: reset one user's balance to $0.00")
@app_commands.describe(member="The user to reset")
async def resetbalance(interaction: discord.Interaction, member: discord.Member):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You must be an administrator to use this.", ephemeral=True)
        return
    await reset_user_balance(member.id)
    await interaction.response.send_message(f"✅ Reset {member.mention}'s balance to $0.00.", ephemeral=False)

# Alcohol
@bot.tree.command(name="alcohol", description="Buy a temporary luck boost for gambling (5 uses). Costs $5,000. 6h cooldown.")
async def alcohol_cmd(interaction: discord.Interaction):
    uid = interaction.user.id
    bal = await get_balance(uid)

    rec = await get_boost_record(uid)
    cd_left = alcohol_cooldown_left_sync(rec)
    if cd_left > 0:
        hours = cd_left // 3600
        mins = (cd_left % 3600) // 60
        secs = cd_left % 60
        await interaction.response.send_message(
            f"⏳ You can buy alcohol again in **{hours}h {mins}m {secs}s**.",
            ephemeral=True
        )
        return

    if bal < ALCOHOL_PRICE:
        await interaction.response.send_message("❌ You don’t have $5,000 for this.", ephemeral=True)
        return

    await add_balance(uid, -ALCOHOL_PRICE)
    until = int(time.time()) + ALCOHOL_COOLDOWN
    await set_boost_record(uid, ALCOHOL_BOOST_USES, until)

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
    uid = interaction.user.id
    rec = await get_boost_record(uid)
    uses = rec.get("uses", 0)
    if uses <= 0:
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🍹 Active Buffs",
                description="You don’t have any active buffs right now.",
                color=discord.Color.red()
            ),
            ephemeral=True
        )
        return

    left_cd = alcohol_cooldown_left_sync(rec)
    cd_str = f"{left_cd//3600}h {(left_cd%3600)//60}m {left_cd%60}s" if left_cd>0 else "ready to rebuy when uses are 0"
    desc = f"🍺 **Alcohol Luck** — {uses} uses left (cooldown {cd_str})"
    embed = discord.Embed(title="🍹 Active Buffs", description=desc, color=discord.Color.green())
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Pay
@bot.tree.command(name="pay", description="Pay another user some of your money")
@app_commands.describe(member="The user you want to pay", amount="How much money to send")
async def pay_cmd(interaction: discord.Interaction, member: discord.Member, amount: float):
    payer_id = interaction.user.id
    receiver_id = member.id
    if payer_id == receiver_id:
        await interaction.response.send_message("❌ You cannot pay yourself.", ephemeral=True); return
    if amount <= 0:
        await interaction.response.send_message("❌ Payment amount must be greater than 0.", ephemeral=True); return
    if await get_balance(payer_id) < amount:
        await interaction.response.send_message("❌ You don’t have enough money to complete this payment.", ephemeral=True); return

    await add_balance(payer_id, -amount)
    await add_balance(receiver_id, +amount)

    embed = discord.Embed(
        title="💸 Payment Successful!",
        description=(
            f"{interaction.user.mention} paid {member.mention} **${amount:,.2f}**.\n\n"
            f"Your new balance: **${await get_balance(payer_id):,.2f}**"
        ),
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed)

# Reset jobs (one/all)
@bot.tree.command(name="resetjobs", description="Reset all your job stats (admin only)")
async def resetjobs(interaction: discord.Interaction, member: discord.Member = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You don’t have permission to use this.", ephemeral=True); return
    target = member or interaction.user
    await reset_user_jobs(target.id)
    await interaction.response.send_message(f"🧹 All job stats for {target.mention} have been reset.", ephemeral=False)

@bot.tree.command(name="resetjobsall", description="Reset ALL users' job stats (admin only)")
async def resetjobsall(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You don’t have permission to use this.", ephemeral=True); return
    await reset_all_jobs()
    await interaction.response.send_message("🧹 All users' job stats have been reset across the server.", ephemeral=False)

# Resume
@bot.tree.command(name="resume", description="Check your career ladder progress and highest-paying job")
async def resume(interaction: discord.Interaction):
    uid = interaction.user.id
    counts = await get_job_counts(uid)
    total_jobs = sum(counts.values())

    # next unlock
    next_unlock = None
    for tier in CAREER_PATH:
        if total_jobs < tier["required"]:
            next_unlock = (tier["name"], tier["required"] - total_jobs)
            break

    record = await get_highest_job(uid)
    embed = discord.Embed(title=f"📄 Resume for {interaction.user.display_name}", color=discord.Color.green())

    if record:
        embed.add_field(
            name="Highest Paying Job",
            value=f"**{record['job']}** ({record['rarity'].title()}) → ${record['amount']:,.2f}",
            inline=False
        )
    else:
        embed.add_field(name="Highest Paying Job", value="No jobs recorded yet!", inline=False)

    if next_unlock:
        embed.add_field(name="Next Career Step", value=f"{next_unlock[1]} more jobs → **{next_unlock[0]}**", inline=False)
    else:
        embed.add_field(name="Next Career Step", value="✅ You’ve reached the top of the career ladder!", inline=False)

    await interaction.response.send_message(embed=embed)

# Update job progress (roles + counts)
async def update_job_progress(interaction: discord.Interaction, rarity: str):
    user_id = interaction.user.id
    await increment_job(user_id, rarity)
    counts = await get_job_counts(user_id)
    total_jobs = sum(counts.values())

    member = interaction.user
    guild = interaction.guild
    if not guild:
        return

    unlocked_stage = None
    for stage in CAREER_PATH:
        if total_jobs >= stage["required"]:
            unlocked_stage = stage
        else:
            break

    if unlocked_stage:
        new_role = guild.get_role(unlocked_stage["role_id"])
        if new_role and new_role not in member.roles:
            # remove any older career roles
            career_role_ids = [s["role_id"] for s in CAREER_PATH]
            roles_to_remove = [r for r in member.roles if r.id in career_role_ids]
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove)
            await member.add_roles(new_role)
            # announce in channel
            await interaction.channel.send(
                f"🎉 {interaction.user.mention} has been promoted to **{unlocked_stage['name']}** "
                f"for working {total_jobs} total jobs!"
            )

# Work command
@bot.tree.command(name="work", description="Do an odd job to earn some money")
async def work_cmd(interaction: discord.Interaction):
    # channel check
    if interaction.channel_id != WORK_CHANNEL_ID:
        await interaction.response.send_message(
            f"❌ You can only use this command in <#{WORK_CHANNEL_ID}>.",
            ephemeral=True
        )
        return

    uid = interaction.user.id

    # 1) small chance to waste a turn
    if random.random() < 0.05:
        fail_texts = [
            "❌ ATS didn’t like your resume, try again.",
            "❌ You threw up in your interview, GGs.",
            "❌ The employer saw your social media history, you’re cooked buddy.",
            "❌ HR ghosted you, better luck next time.",
            "❌ You overslept and missed the shift entirely."
        ]
        fail_text = random.choice(fail_texts)
        embed = discord.Embed(
            title=f"{interaction.user.name} tried to work...",
            description=fail_text,
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)
        return

    # 2) special job check
    special = pick_special_job()
    if special is not None:
        base_payout = special["payout_value"]
        tip = roll_tip()
        final_payout = round(base_payout * tip["mult"], 2) if tip else base_payout

        new_balance = await add_balance(uid, final_payout)
        await update_job_progress(interaction, "special")
        await update_highest_job(uid, special["name"], "special", final_payout)

        desc_lines = [f"{special['desc']}", "", f"you earned **${base_payout:,.2f}**."]
        if tip:
            desc_lines.append(
                f"{tip['emoji']} tip! {tip['flavor']} ×**{tip['mult']}** → **${final_payout:,.2f}** total."
            )
        desc_lines.append(f"💰 current balance: **${new_balance:,.2f}**")

        embed = discord.Embed(
            title=f"{interaction.user.name} worked a special job!",
            description="\n".join(desc_lines),
            color=special["color"]
        )
        embed.set_footer(text=f"special job: {special['name'].upper()}")
        await interaction.response.send_message(embed=embed)

        # announce
        announce_channel = bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if announce_channel:
            emoji = rarity_emojis.get(special["name"], "✨")
            msg = f"{emoji} {interaction.user.mention} hit a **Special Job: {special['name'].upper()}** and earned ${final_payout:,.2f}"
            msg += f" (tipped ×{tip['mult']})!" if tip else "!"
            await announce_channel.send(msg)
        return

    # 3) normal roll
    rarity, job, base_payout, career_name = await pick_job(uid)
    tip = roll_tip()
    final_payout = round(base_payout * tip["mult"], 2) if tip else base_payout

    new_balance = await add_balance(uid, final_payout)
    await update_job_progress(interaction, rarity)
    await update_highest_job(uid, job, rarity, final_payout)

    desc_lines = [f"{flavor_texts[rarity]}", "", f"you {job} and earned **${base_payout:,.2f}**."]
    if tip:
        extra = " (from crumbs to caviar!)" if rarity == "common" and tip["mult"] >= 3 else ""
        desc_lines.append(
            f"{tip['emoji']} tip! {tip['flavor']} ×**{tip['mult']}** → **${final_payout:,.2f}** total.{extra}"
        )
    desc_lines.append(f"💰 current balance: **${new_balance:,.2f}**")

    embed = discord.Embed(
        title=f"{interaction.user.name} worked!",
        description="\n".join(desc_lines),
        color=rarity_colors[rarity]
    )
    embed.set_footer(text=f"career tier: {career_name}")
    await interaction.response.send_message(embed=embed)

    # announce big hits
    if rarity in ["legendary", "secret"]:
        announce_channel = bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if announce_channel:
            emoji = rarity_emojis.get(rarity, "✨")
            msg = f"{emoji} {interaction.user.mention} just worked a **{rarity.upper()} job** and made ${final_payout:,.2f}"
            msg += f" (tipped ×{tip['mult']})!" if tip else "!"
            await announce_channel.send(msg)

# --- run ---
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")
bot.run(TOKEN)
