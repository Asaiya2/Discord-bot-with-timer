import discord
from discord.ext import commands
import asyncio
import sqlite3
import os
import signal
import sys
import time
import re
from datetime import datetime

# ===== CONFIGURATION =====
BOT_TOKEN = "Bot token Here"
DB_FOLDER = r"C:\Users\Kelly\Desktop\discord database"
MAIN_DB_PATH = os.path.join(DB_FOLDER, "asaiya_bot.db")

OWNER_SERVER_ID = 1484265140215087235  # Your owner server ID
MLBB_SERVER_ID = 1485978412219891834   # MLBB Server ID

# ===== KEY SYSTEM TOGGLE =====
# Set to False with !keyoff to allow any server to use the bot (use after buying VPS)
KEY_SYSTEM_ENABLED = True

# ===== CHANNEL RESTRICTION CONFIGURATION =====
# These constants are used for the global channel restriction check
BOT_CHANNEL_NAME    = "asaiya-bot"
VERIFY_CHANNEL_NAME = "asaiya-verification"
HUB_CHANNEL_NAME    = "asaiya-hub"

# Music commands list for hub channel
MUSIC_COMMANDS = ['play', 'stop', 'skip', 'queue', 'nowplaying', 'leave', 'music', 'stopall']

# ALL_COMMANDS - Set True = must be used in #asaiya-bot (restricted), False = can be used ANYWHERE
ALL_COMMANDS = {
    # ----- admin.py -----
    "modsetup":         False,  # Setup wizard — may run before asaiya-bot exists
    "showservers":      False,  # Show all servers with invite links - owner only
    "modsetupcancel":   False,  # Cancel stuck setup session
    "modstatus":        False,
    "Arole":            True,
    "botkey":           False,  # Must work anywhere — run before channels exist
    "cbotkey":          False,  # Force reactivate key — owner only
    "ckey":             False,
    "cmkey":            False,
    "ctkey":            False,
    "cmultikey":        False,
    "cdelkey":          False,
    "skey":             False,
    "helpkey":          False,
    "setserver":        False,  # Creates channels — must work before asaiya-bot exists
    "permset":          False,
    "nuke":             True,
    "staffroles":       False,
    "addfilter":        False,
    "removefilter":     False,
    "listfilters":      False,
    "clearfilters":     False,
    "filterbypass":     False,
    "refreshfilter":    False,
    "hackoff":          False,
    "hackon":           False,
    "stopspam":         False,
    "startspam":        False,
    "stopraid":         False,
    "startraid":        False,
    "antinukeoff":      False,
    "antinukeon":       False,
    "startverify":      False,
    "stopverify":       False,
    "showrole":         False,
    "sserver":          False,
    "checklog":         False,  # Debug command
    "checklogtable":    False,  # Debug command
    "cleanlogtable":    False,  # Debug command
    "showlogdata":      False,  # Debug command
    "findlog":          False,  # Debug command
    "checkskey":        False,  # Debug command

    # ----- anti_raid.py -----
    "antiraidstatus":   True,
    "raidstatus":       True,
    "raidhistory":      True,
    "raidclear":        True,
    "resetviolations":  True,
    "checkstatus":      True,
    "resetstatus":      True,

    # ----- backup.py -----
    "backups":          True,
    "backupstats":      True,
    "delbackup":        True,
    "cleanbackups":     True,   # now in backup.py
    "cleanoldbackups":  True,
    "restore":          True,

    # ----- cross_server.py -----
    "talkcross":        False,
    "talkcrosslist":    False,
    "talkdm":           False,

    # ----- events.py -----
    "filteroff":        True,
    "filteron":         True,
    "inviteoff":        True,   # now in anti_raid.py
    "inviteon":         True,   # now in anti_raid.py
    "event":            True,
    "event create":     True,
    "event end":        True,
    "event list":       True,

    # ----- giveaway.py -----
    "ga":               True,
    "ga start":         True,
    "ga end":           True,
    "ga re":            True,
    "ga list":          True,

    # ----- id_system.py -----
    "id":               False,
    "gid":              False,
    "idhelp":           False,
    "idset_users":      False,
    "idset_server":     False,
    "idset_channel":    False,
    "idsetglobal":      False,

    # ----- level.py -----
    "rank":             False,
    "level":            False,
    "xp":               False,
    "leaderboard":      False,
    "lb":               False,
    "reborn":           False,
    "lvlhelp":          False,
    "expchannel":       False,
    "setbasexp":        True,
    "expsettings":      True,
    "addlevel":         True,
    "addre":            True,
    "addxp":            True,
    "setlevel":         True,
    "rebornreset":      True,
    "levelrole":        True,
    "noexp":            True,
    "onexp":            True,
    "levelon":          False,  # Enable leveling system for server
    "leveloff":         False,  # Disable leveling system for server

    # ----- MLBB.py -----
    "mlbb-status":      False,
    "mlbb-roles":       False,
    "mlbbserver":       False,
    "mlbbid":           False,
    "mlid":             False,

    # ----- moderation.py -----
    "warn":             False,
    "warnings":         True,
    "kick":             False,
    "ban":              False,
    "unban":            False,
    "timeout":          False,
    "untimeout":        False,
    "clear":            False,
    "lock":             False,
    "unlock":           False,
    "slock":            False,
    "sunlock":          False,
    "slowmode":         False,
    "afk":              False,
    "timer":            False,
    "role":             True,
    "filter":           True,
    "checkdict":        False,
    "testlog":          False,  # Debug command

    # ----- musical.py -----
    "play":             False,
    "stop":             False,
    "skip":             False,
    "queue":            False,
    "nowplaying":       False,
    "leave":            False,
    "music":            False,
    "stopall":          False,

    # ----- protection.py -----
    "protect":          True,
    "unprotect":        True,
    "fprotect":         True,
    "mprotect":         True,
    "sprotect":         True,
    "protected":        True,
    "recover":          True,
    "remake":           True,
    "setlog":           True,
    "setwelcome":       True,
    "setleave":         True,

    # ----- reaction_roles.py -----
    "rrole":            False,
    "onerole":          False,
    "rrole create":     False,
    "rrole add":        False,
    "rrole remove":     False,
    "rrole list":       False,
    "rrole delete":     False,
    "rrole show":       False,
    "rrole publish":    False,

    # ----- status_tracker.py -----
    "track":            False,
    "untrack":          False,

    # ----- tasks.py -----
    # (no user-facing commands — cleanbackups moved to backup.py)

    # ----- tickets.py -----
    "ticket":           False,
    "close":            False,
    "rename":           False,
    "ticketadd":        False,
    "remove":           False,
    "transfer":         False,
    "tickethelp":       False,
    "ratingstats":      False,
    "ratingdetail":     False,
    "ticketson":        False,
    "ticketsoff":       False,

    # ----- utility.py -----
    "ping":             False,
    "serverinfo":       False,
    "uptime":           False,
    "av":               False,
    "help":             False,
    "snipe":            False,
    "snipelist":        False,
    "say":              False,
    "repeat":           False,
    "repeatstop":       False,
    "hello":            True,
    "botfor":           False,
    "botservers":       False,
    "cmdtest":          True,
    "fullcmdtest":      True,
    "fixverify":        True,
    "verifyall":        True,
    "imageonly":        False,
    "imageonly-remove": False,
    "imageonly-list":   False,
    "roblox":           True,

    # ----- verification.py -----
    "setverify":        True,
    "verify":           False,  # User command — can be used in verification channel

    # ----- bug_report.py -----
    "reportbug":        False,
    "fixbug":           False,
    "unfix":            False,
    "impossiblefix":    False,

    # ----- Workout Server -----
    "start":            True,
    "end":              True,
    "today":            True,
    "day":              True,
    "days":             True,
    "resetdays":        True,
    "addfood":          True,
    "logfood":          True,
    "logworkout":       True,
    "treadmill":        True,
    "myfoods":          True,

    # ----- detector.py -----
    "detect":           False,
    "detect_add":       False,
    "detect_multiple":  False,
    "detect_list":      False,
    "detect_remove":    False,
    "detect_stats":     False,

    # ----- Media.py -----
    "save":             False,  # Save image/gif (no channel restriction)
    "delimg":           False,
    "delgif":           False,
    "img":              False,  # Send image by code
    "gif":              False,  # Send gif by code
    "imgr":             False,  # Send random image
    "gifr":             False,  # Send random gif
    "imgs":             False,  # List all images (DM)
    "gifs":             False,  # List all gifs (DM)
    "clearimg":         False,  # List all gifs (DM)
    "cleargif":         False,  # List all gifs (DM)
    "delgif":           False,
    "delimg":           False,
    "mlog":             True,   # Set message log channel

    # ------ RANDOM ---------
    "random":           False,  # Random fact command - can be used anywhere
    "fact":             False,  # Alias for random
    "rand":             False,  # Alias for random

    # ----- owner commands -----
    "keyoff":           False,  # Disable key system (owner only)
    "keyon":            False,  # Re-enable key system (owner only)
    "nick":             False,  # Set a user's nickname
    "update":           False,  # Broadcast update message to all servers

    # ------ GAMES --------
    "snake":            False,  # Start snake game
    "snakequit":        False,  # Force quit snake game
    "snakeleaderboard": False,  # Show snake high scores
    "snakelb":          False,  # Alias for snakeleaderboard
    "snakehighscores":  False,  # Alias for snakeleaderboard
    "chess":            False,  # Start chess lobby
    "chesscancel":      False,  # Cancel chess lobby
    "chessmove":        False,  # Make chess move
    "chessboard":       False,  # Show chess board
    "draw":             False,  # Accept/decline draw offer
    "cards":            False,
}

# ===== RESTRICTED SERVERS =====
# Servers where only specific cogs are allowed to run.
# Format: { server_id: ["CogName1", "CogName2"] }
# These servers are also automatically exempt from botkey.
RESTRICTED_SERVERS = {
    1484565350879330416: ["Workout"],           # Workout server — workout commands only
    1485978412219891834: ["Level", "MLBB", "IDSystem", "Events", "Giveaway", "AntiRaid", "Admin", "StatusTracker", "Tasks", "Utility", "Music", "Moderation"],  # MLBB Server
}

# ===== BOTKEY EXEMPT SERVERS =====
# Servers that never need to use !botkey, even if the database is wiped.
# Restricted servers above are automatically included — add any others here.
BOTKEY_EXEMPT_SERVERS = {
    OWNER_SERVER_ID,
    1317268636817162311,  # NLLS server
    1484265140215087235,
    1477970013490249860,  # ASAIYA MARKET
    1485978412219891834,  # MLBB Server
    333949691962195969,   # TOP.GG SERVER
    # Add extra exempt server IDs below:
    # 123456789012345678,
}


def sanitize_filename(name):
    """Convert server name to safe filename"""
    safe = re.sub(r'[^\w\s-]', '', name)
    safe = safe.replace(' ', '_')
    return safe[:50]


# ===== MAIN DATABASE INITIALIZATION =====
def init_main_database():
    """Initialize the main database with all required tables"""
    os.makedirs(DB_FOLDER, exist_ok=True)
    conn = sqlite3.connect(MAIN_DB_PATH)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS servers
                 (guild_id TEXT PRIMARY KEY,
                  server_number INTEGER UNIQUE,
                  added_at REAL,
                  name TEXT,
                  owner_id TEXT,
                  db_path TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS server_counter
                 (id INTEGER PRIMARY KEY,
                  last_number INTEGER)''')
    c.execute("INSERT OR IGNORE INTO server_counter (id, last_number) VALUES (1, 0)")

    c.execute('''CREATE TABLE IF NOT EXISTS authorized_servers
                 (guild_id TEXT PRIMARY KEY,
                  key_used TEXT,
                  authorized_since REAL,
                  expires_at REAL,
                  last_verified REAL,
                  db_path TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS bot_keys
                 (key TEXT PRIMARY KEY,
                  key_type TEXT,
                  created_by TEXT,
                  created_at REAL,
                  max_uses INTEGER,
                  uses_remaining INTEGER,
                  expiry_duration REAL,
                  is_active INTEGER DEFAULT 1)''')

    c.execute('''CREATE TABLE IF NOT EXISTS key_uses
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  key TEXT,
                  guild_id TEXT,
                  guild_name TEXT,
                  used_at REAL,
                  expires_at REAL,
                  is_active INTEGER DEFAULT 1)''')

    c.execute('''CREATE TABLE IF NOT EXISTS persistent_reaction_setup
                 (user_id TEXT PRIMARY KEY,
                  guild_id TEXT,
                  setup_data TEXT,
                  created_at REAL,
                  expires_at REAL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS persistent_nuke_requests
                 (guild_id TEXT PRIMARY KEY,
                  requester_id TEXT,
                  approval_msg_id TEXT,
                  guild_name TEXT,
                  source_channel_id TEXT,
                  requested_at REAL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS persistent_template_history
                 (guild_id TEXT PRIMARY KEY,
                  last_template TEXT,
                  updated_at REAL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS captcha_sessions
                 (user_id TEXT PRIMARY KEY,
                  guild_id TEXT,
                  code TEXT,
                  expires_at REAL,
                  created_at REAL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS verify_settings
                 (guild_id TEXT PRIMARY KEY,
                  role_id TEXT,
                  role_name TEXT,
                  set_by TEXT,
                  set_at REAL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS global_verified_users
                 (user_id TEXT PRIMARY KEY,
                  verified_at REAL,
                  verified_in_guild TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS server_backups_v2
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  guild_id TEXT,
                  server_name TEXT,
                  password_hash TEXT,
                  backup_data TEXT,
                  created_by TEXT,
                  created_by_name TEXT,
                  created_at REAL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS active_tickets
                 (guild_id TEXT,
                  user_id TEXT,
                  channel_id TEXT,
                  created_at REAL,
                  PRIMARY KEY (guild_id, user_id))''')

    c.execute('''CREATE TABLE IF NOT EXISTS join_timestamps
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id TEXT,
                  guild_id TEXT,
                  timestamp REAL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS ticket_ratings
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  channel_id TEXT,
                  ticket_name TEXT,
                  rating INTEGER,
                  support_name TEXT,
                  support_id TEXT,
                  user_id TEXT,
                  created_at REAL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS skey_messages
                 (guild_id TEXT PRIMARY KEY,
                  channel_id TEXT,
                  message_id TEXT,
                  updated_at REAL)''')

    conn.commit()
    conn.close()
    print("✅ Main database initialized")


def ensure_anti_raid_columns():
    """Add missing columns to anti_raid_settings table if they don't exist"""
    conn = sqlite3.connect(MAIN_DB_PATH)
    c = conn.cursor()

    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='anti_raid_settings'")
    table_exists = c.fetchone()

    if not table_exists:
        c.execute('''CREATE TABLE anti_raid_settings
                     (guild_id TEXT PRIMARY KEY,
                      hack_detection INTEGER DEFAULT 1,
                      spam_detection INTEGER DEFAULT 1,
                      raid_detection INTEGER DEFAULT 1,
                      word_filter INTEGER DEFAULT 1,
                      invite_protection INTEGER DEFAULT 1,
                      updated_at REAL)''')
        print("✅ Created anti_raid_settings table with all columns")
    else:
        columns_to_add = [
            ('word_filter', 'INTEGER DEFAULT 1'),
            ('invite_protection', 'INTEGER DEFAULT 1')
        ]
        c.execute("PRAGMA table_info(anti_raid_settings)")
        existing_columns = [row[1] for row in c.fetchall()]
        for col_name, col_type in columns_to_add:
            if col_name not in existing_columns:
                try:
                    c.execute(f"ALTER TABLE anti_raid_settings ADD COLUMN {col_name} {col_type}")
                    print(f"✅ Added column '{col_name}' to anti_raid_settings")
                except Exception as e:
                    print(f"⚠️ Could not add column {col_name}: {e}")

    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='server_mod_settings'")
    mod_table_exists = c.fetchone()

    if not mod_table_exists:
        c.execute('''CREATE TABLE server_mod_settings
                     (guild_id TEXT PRIMARY KEY,
                      hack_detection INTEGER DEFAULT 1,
                      spam_detection INTEGER DEFAULT 1,
                      raid_detection INTEGER DEFAULT 1,
                      verification_enabled INTEGER DEFAULT 0,
                      verification_role_id TEXT,
                      word_filter INTEGER DEFAULT 1,
                      invite_protection INTEGER DEFAULT 1,
                      updated_at REAL)''')
        print("✅ Created server_mod_settings table with all columns")
    else:
        c.execute("PRAGMA table_info(server_mod_settings)")
        existing_mod_columns = [row[1] for row in c.fetchall()]
        mod_columns_to_add = [
            ('word_filter', 'INTEGER DEFAULT 1'),
            ('invite_protection', 'INTEGER DEFAULT 1'),
            ('leveling_enabled', 'INTEGER DEFAULT 0')
        ]
        for col_name, col_type in mod_columns_to_add:
            if col_name not in existing_mod_columns:
                try:
                    c.execute(f"ALTER TABLE server_mod_settings ADD COLUMN {col_name} {col_type}")
                    print(f"✅ Added column '{col_name}' to server_mod_settings")
                except Exception as e:
                    print(f"⚠️ Could not add column {col_name} to server_mod_settings: {e}")

    conn.commit()
    conn.close()


def ensure_staff_immunity_table():
    """Ensure staff_immunity_roles table exists"""
    conn = sqlite3.connect(MAIN_DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS staff_immunity_roles
                 (guild_id TEXT,
                  role_id TEXT,
                  role_name TEXT,
                  added_by TEXT,
                  added_at REAL,
                  PRIMARY KEY (guild_id, role_id))''')
    conn.commit()
    conn.close()
    print("✅ Staff immunity roles table ensured")


def ensure_user_violations_table():
    """Ensure user_violations table exists for anti-raid tracking"""
    conn = sqlite3.connect(MAIN_DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS user_violations
                 (user_id TEXT,
                  guild_id TEXT,
                  violation_count INTEGER DEFAULT 0,
                  last_violation REAL,
                  created_at REAL,
                  PRIMARY KEY (user_id, guild_id))''')
    conn.commit()
    conn.close()
    print("✅ User violations table ensured")


def ensure_level_database_columns():
    """Add missing columns to level database"""
    level_db_path = os.path.join(DB_FOLDER, "levels.db")

    if not os.path.exists(level_db_path):
        print("📁 Level database not found, will be created on first use")
        return

    try:
        conn = sqlite3.connect(level_db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        table_exists = cursor.fetchone()

        if table_exists:
            cursor.execute("PRAGMA table_info(users)")
            columns = [col[1] for col in cursor.fetchall()]

            if 'total_xp' not in columns:
                print("⚠️ Adding missing 'total_xp' column to level database...")
                cursor.execute("ALTER TABLE users ADD COLUMN total_xp INTEGER DEFAULT 0")
                print("✅ Added 'total_xp' column")
            else:
                print("✅ 'total_xp' column already exists in level database")

            if 'reborns' not in columns:
                print("⚠️ Adding missing 'reborns' column to level database...")
                cursor.execute("ALTER TABLE users ADD COLUMN reborns INTEGER DEFAULT 0")
                print("✅ Added 'reborns' column")

            if 'last_message_time' not in columns:
                print("⚠️ Adding missing 'last_message_time' column to level database...")
                cursor.execute("ALTER TABLE users ADD COLUMN last_message_time TIMESTAMP")
                print("✅ Added 'last_message_time' column")

            conn.commit()
        else:
            print("📁 Users table not found in level database, will be created on first use")

        conn.close()
        print("✅ Level database migration complete")

    except Exception as e:
        print(f"❌ Error migrating level database: {e}")


# ===== SERVER DATABASE INITIALIZATION =====
def init_server_database(db_path, guild_name):
    """Initialize a server-specific database with all required tables"""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS warnings
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id TEXT,
                  mod_id TEXT,
                  reason TEXT,
                  timestamp REAL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS afk
                 (user_id TEXT PRIMARY KEY,
                  reason TEXT,
                  timestamp REAL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS reminders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id TEXT,
                  channel_id TEXT,
                  message TEXT,
                  remind_time REAL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS protected_channels
                 (channel_id TEXT PRIMARY KEY,
                  channel_name TEXT,
                  protected_since REAL,
                  protect_type TEXT DEFAULT 'channel')''')

    c.execute('''CREATE TABLE IF NOT EXISTS message_backup
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  channel_id TEXT,
                  channel_name TEXT,
                  author_id TEXT,
                  author_name TEXT,
                  content TEXT,
                  timestamp REAL,
                  attachments TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS deleted_channels
                 (channel_name TEXT PRIMARY KEY,
                  category_name TEXT,
                  deleted_at REAL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS reaction_roles
                 (message_id TEXT PRIMARY KEY,
                  channel_id TEXT,
                  title TEXT,
                  description TEXT,
                  created_at REAL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS reaction_role_items
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  message_id TEXT,
                  emoji TEXT,
                  role_id TEXT,
                  role_name TEXT,
                  FOREIGN KEY (message_id) REFERENCES reaction_roles(message_id))''')

    c.execute('''CREATE TABLE IF NOT EXISTS reaction_one_role_groups
                 (group_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  guild_id TEXT,
                  message_id TEXT,
                  group_name TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS reaction_one_role_items
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  group_id INTEGER,
                  emoji TEXT,
                  role_id TEXT,
                  role_name TEXT,
                  FOREIGN KEY (group_id) REFERENCES reaction_one_role_groups(group_id))''')

    c.execute('''CREATE TABLE IF NOT EXISTS log_channels
                 (log_channel_id TEXT,
                  welcome_channel_id TEXT,
                  leave_channel_id TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS filter_words
                 (word TEXT PRIMARY KEY,
                  reason TEXT,
                  added_by TEXT,
                  added_at REAL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS filter_bypass_roles
                 (word TEXT,
                  role_id TEXT,
                  role_name TEXT,
                  added_by TEXT,
                  added_at REAL,
                  PRIMARY KEY (word, role_id))''')

    c.execute('''CREATE TABLE IF NOT EXISTS join_timestamps
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id TEXT,
                  timestamp REAL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS active_tickets
                 (guild_id TEXT,
                  user_id TEXT,
                  channel_id TEXT,
                  PRIMARY KEY (guild_id, user_id))''')

    conn.commit()
    conn.close()
    print(f"📁 Created server database for: {guild_name}")


# ===== DATABASE CONNECTION CLEANUP =====
def close_all_connections():
    """Close all database connections gracefully on shutdown"""
    print("\n🔄 Closing all database connections...")

    if hasattr(bot, 'db_connections'):
        closed_count = 0
        for guild_id, conn in list(bot.db_connections.items()):
            try:
                conn.close()
                closed_count += 1
                print(f"   ✅ Closed connection for guild {guild_id}")
            except Exception as e:
                print(f"   ❌ Error closing connection for guild {guild_id}: {e}")

        bot.db_connections.clear()
        if hasattr(bot, 'last_db_use'):
            bot.last_db_use.clear()

        print(f"✅ Closed {closed_count} database connection(s)")
    else:
        print("   No active database connections found")

    try:
        import gc
        gc.collect()
    except:
        pass

    print("✅ Database cleanup complete")


# ===== RUN DATABASE INIT BEFORE BOT STARTS =====
init_main_database()
ensure_anti_raid_columns()
ensure_staff_immunity_table()
ensure_user_violations_table()
ensure_level_database_columns()


# ===== BOT SETUP =====
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.presences = True
intents.voice_states = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# ===== GLOBAL DUPLICATE PREVENTION =====
processed_message_ids = set()
channel_warning_cooldown = {}


@bot.before_invoke
async def before_invoke(ctx):
    """Run before every command to prevent duplicate execution"""
    msg_id = ctx.message.id

    if msg_id in processed_message_ids:
        print(f"⚠️ Duplicate command detected: {ctx.command.name if ctx.command else 'unknown'} "
              f"by {ctx.author} (message {msg_id})")
        raise commands.CommandError("Duplicate command ignored")

    processed_message_ids.add(msg_id)

    if len(processed_message_ids) > 500:
        processed_message_ids.clear()


# ===== CHANNEL RESTRICTION CHECK =====
async def channel_restriction_check(ctx):
    """Global check that runs before EVERY command to enforce channel restrictions.

    Channel rules:
      - Commands marked True in ALL_COMMANDS → must be used in #asaiya-bot
      - Commands marked False                → can be used anywhere
      - Music commands                       → also allowed in #asaiya-hub
      - !verify                              → also allowed in #asaiya-verification

    In the MLBB server (RESTRICTED_SERVERS), the bot channel is #asaiya-bot
    which is created by !mlbbserver inside the 💬 GENERAL category.
    """

    # Skip for DMs
    if ctx.guild is None:
        return True

    cmd_name = ctx.command.name if ctx.command else ""

    # Check if this command is restricted to #asaiya-bot
    is_restricted = ALL_COMMANDS.get(cmd_name, True)

    # Not restricted — allow anywhere
    if not is_restricted:
        return True

    # !verify can be used in the verification channel too
    if cmd_name == 'verify' and ctx.channel.name == VERIFY_CHANNEL_NAME:
        return True

    # ── asaiya-hub: only music commands allowed ────────────────────────────
    if ctx.channel.name == HUB_CHANNEL_NAME:
        if cmd_name in MUSIC_COMMANDS:
            return True  # Music command in hub — allow

        # Non-music command in hub — block with specific message
        user_id      = ctx.author.id
        current_time = time.time()
        cooldown_key = f"{user_id}:{cmd_name}:hub"

        if cooldown_key not in channel_warning_cooldown or \
                current_time - channel_warning_cooldown[cooldown_key] >= 10:
            channel_warning_cooldown[cooldown_key] = current_time

            bot_channel     = discord.utils.get(ctx.guild.text_channels, name=BOT_CHANNEL_NAME)
            channel_mention = bot_channel.mention if bot_channel else f"**#{BOT_CHANNEL_NAME}**"

            await ctx.send(
                f"⚠️ {ctx.author.mention} Only music commands are allowed here! "
                f"Go to {channel_mention} to run other commands.",
                delete_after=8
            )

        try:
            await ctx.message.delete()
        except:
            pass

        return False

    # Restricted commands must be in #asaiya-bot
    if ctx.channel.name == BOT_CHANNEL_NAME:
        return True

    # ── BLOCKED: wrong channel ──────────────────────────────────────────────
    user_id      = ctx.author.id
    current_time = time.time()
    cooldown_key = f"{user_id}:{cmd_name}"

    if cooldown_key in channel_warning_cooldown:
        if current_time - channel_warning_cooldown[cooldown_key] < 10:
            return False  # Still on cooldown — block silently

    channel_warning_cooldown[cooldown_key] = current_time

    # Clean old cooldowns
    for key, timestamp in list(channel_warning_cooldown.items()):
        if current_time - timestamp > 60:
            del channel_warning_cooldown[key]

    bot_channel     = discord.utils.get(ctx.guild.text_channels, name=BOT_CHANNEL_NAME)
    channel_mention = bot_channel.mention if bot_channel else f"**#{BOT_CHANNEL_NAME}**"

    await ctx.send(
        f"⚠️ {ctx.author.mention} Please use `!{cmd_name}` in {channel_mention}!",
        delete_after=8
    )

    try:
        await ctx.message.delete()
    except:
        pass

    return False


# ===== REGISTER GLOBAL CHECKS =====
bot.add_check(channel_restriction_check)
print("✅ Channel restriction check registered")


# ===== COMMAND-ONLY CHANNEL ENFORCEMENT =====
# Channels where only bot commands are allowed
COMMAND_ONLY_CHANNELS = {BOT_CHANNEL_NAME, HUB_CHANNEL_NAME}

# Cooldown so the warning doesn't spam the same user repeatedly
command_only_warn_cooldown = {}

@bot.event
async def on_message(message):
    """Delete non-command messages in command-only channels and warn the user."""

    # Always ignore bots
    if message.author.bot:
        await bot.process_commands(message)
        return

    # Only apply in guilds
    if not message.guild:
        await bot.process_commands(message)
        return

    # ===== EARLY WORD FILTER CHECK (BLOCKS COMMANDS BEFORE PROCESSING) =====
    events_cog = bot.get_cog('Events')
    if events_cog and events_cog.is_word_filter_enabled(message.guild.id):
        if not events_cog.is_staff(message.author, message.guild.id):
            msg_lower = message.content.lower()
            # Extract command name if it starts with !
            if msg_lower.startswith('!'):
                cmd_name = msg_lower[1:].split()[0].lower() if len(msg_lower) > 1 else ""
                if cmd_name:
                    try:
                        conn = events_cog.get_cached_connection(message.guild.id)
                        if conn:
                            c = conn.cursor()
                            c.execute("SELECT word, reason FROM filter_words WHERE word = ?", (cmd_name,))
                            result = c.fetchone()
                            if result:
                                # Command is filtered! Delete and block
                                try:
                                    await message.delete()
                                    reason = result[1]
                                    await message.channel.send(
                                        f"❌ {message.author.mention}, the command `!{cmd_name}` is blocked!" +
                                        (f"\n**Reason:** {reason}" if reason else ""),
                                        delete_after=5
                                    )
                                except:
                                    pass
                                return  # STOP - don't process this command
                    except:
                        pass

    channel_name = message.channel.name.lower()

    if channel_name in COMMAND_ONLY_CHANNELS:
        content = message.content.strip()

        # Allow messages that start with the command prefix
        is_command = content.startswith(bot.command_prefix)

        if not is_command:
            # Delete the message
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            except discord.NotFound:
                pass

            # Warn the user (with cooldown — once every 15 seconds per user per channel)
            current_time = time.time()
            cooldown_key = f"{message.author.id}:{message.channel.id}"

            last_warned = command_only_warn_cooldown.get(cooldown_key, 0)
            if current_time - last_warned >= 15:
                command_only_warn_cooldown[cooldown_key] = current_time

                # Clean old cooldown entries
                for k in list(command_only_warn_cooldown.keys()):
                    if current_time - command_only_warn_cooldown[k] > 60:
                        del command_only_warn_cooldown[k]

                if channel_name == HUB_CHANNEL_NAME:
                    bot_channel     = discord.utils.get(message.guild.text_channels, name=BOT_CHANNEL_NAME)
                    channel_mention = bot_channel.mention if bot_channel else f"**#{BOT_CHANNEL_NAME}**"
                    await message.channel.send(
                        f"⚠️ {message.author.mention} Only music commands are allowed here! "
                        f"Go to {channel_mention} to run other commands.",
                        delete_after=8
                    )
                else:
                    await message.channel.send(
                        f"⚠️ {message.author.mention} Only bot commands are allowed in this channel! "
                        f"Use `!help` to see available commands.",
                        delete_after=8
                    )

            return  # Don't process further — message was not a command

    # For all other channels, process commands normally
    await bot.process_commands(message)

# ===== SHARED BOT ATTRIBUTES =====
bot.snipe_cache        = {}
bot.filter_cache       = {}
bot.filter_cache_time  = {}
bot.join_timestamps    = []
bot.active_tickets     = {}
bot.pending_nukes      = {}
bot.guild_template_history = {}
bot.db_connections     = {}
bot.last_db_use        = {}
bot.active_giveaways   = {}
bot.ended_giveaways    = {}  # Stores entries from ended giveaways for reroll
bot.online_times       = {}
bot.offline_times      = {}
bot.status_trackers    = {}
bot.active_events      = {}
bot.skey_messages      = {}  # {guild_id: {"channel_id": int, "message_id": int}}

# ===== DUPLICATE PREVENTION FOR GLOBAL CHECKS =====
auth_failure_cooldown = {}


# ===== OWNER COMMANDS =====
@bot.command(name='keyoff')
async def keyoff(ctx):
    """Disable the key system so any server can use the bot. Requires AsaiyaBot role in owner server."""
    if ctx.guild is None or ctx.guild.id != OWNER_SERVER_ID:
        await ctx.send("❌ This command can only be used in the owner server.")
        return
    asaiya_role = discord.utils.get(ctx.guild.roles, name="AsaiyaBot")
    if not asaiya_role or asaiya_role not in ctx.author.roles:
        await ctx.send("❌ You need the **AsaiyaBot** role to use this command.")
        return
    bot.key_system_enabled = False
    embed = discord.Embed(
        title="🔓 Key System Disabled",
        description="Any server can now use the bot without a key.\nUse `!keyon` to re-enable.",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)
    print(f"⚠️ Key system disabled by {ctx.author}")

@bot.command(name='keyon')
async def keyon(ctx):
    """Re-enable the key system. Requires AsaiyaBot role in owner server."""
    if ctx.guild is None or ctx.guild.id != OWNER_SERVER_ID:
        await ctx.send("❌ This command can only be used in the owner server.")
        return
    asaiya_role = discord.utils.get(ctx.guild.roles, name="AsaiyaBot")
    if not asaiya_role or asaiya_role not in ctx.author.roles:
        await ctx.send("❌ You need the **AsaiyaBot** role to use this command.")
        return
    bot.key_system_enabled = True
    embed = discord.Embed(
        title="🔐 Key System Enabled",
        description="Servers now require a valid key to use the bot.",
        color=discord.Color.red()
    )
    await ctx.send(embed=embed)
    print(f"✅ Key system re-enabled by {ctx.author}")


# ===== ON READY — RESTORE SKEY LIVE MESSAGES =====
@bot.event
async def on_ready():
    """Runs once when the bot connects. Restores any live !skey messages from the database."""
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")

    admin_cog = bot.cogs.get('Admin')
    if admin_cog and hasattr(admin_cog, 'restore_skey_tasks'):
        await admin_cog.restore_skey_tasks()
    else:
        print("⚠️ Admin cog not ready yet — skey restore skipped")


# ===== WORD FILTER COMMAND BLOCK CHECK =====
@bot.check
async def block_filtered_commands(ctx):
    """Block commands that contain filtered words"""
    # Skip for DMs
    if ctx.guild is None:
        return True
    
    # Get the command name
    cmd_name = ctx.command.name if ctx.command else ""
    
    # Get the events cog to check filter
    events_cog = bot.get_cog('Events')
    if not events_cog:
        return True
    
    # Check if word filter is enabled
    if not events_cog.is_word_filter_enabled(ctx.guild.id):
        return True
    
    # Check if user is staff (bypass)
    if events_cog.is_staff(ctx.author, ctx.guild.id):
        return True
    
    # Check if the command name is filtered
    try:
        conn = events_cog.get_cached_connection(ctx.guild.id)
        if conn:
            c = conn.cursor()
            c.execute("SELECT word, reason FROM filter_words WHERE word = ?", (cmd_name.lower(),))
            result = c.fetchone()
            if result:
                # Command is filtered! Delete the message and block
                try:
                    await ctx.message.delete()
                    reason = result[1]
                    if reason:
                        await ctx.send(f"❌ {ctx.author.mention}, the command `!{cmd_name}` is blocked!\n**Reason:** {reason}", delete_after=5)
                    else:
                        await ctx.send(f"❌ {ctx.author.mention}, the command `!{cmd_name}` is blocked!", delete_after=5)
                except:
                    pass
                return False  # Block the command
    except:
        pass
    
    return True

# ===== GLOBAL AUTHORIZATION CHECK =====
@bot.check
async def globally_check_authorization(ctx):
    """Global check that runs before EVERY command.
    Order of checks:
      1. Allow DMs always
      2. Allow !botkey command always
      3. Restricted server check (only certain cogs allowed; also botkey-exempt)
      4. Botkey-exempt servers (skip authorization entirely)
      5. Owner server (skip authorization)
      6. Botkey / expiry check
    """

    # 1. Always allow DMs
    if ctx.guild is None:
        return True

    # 2. Always allow the botkey command itself
    if ctx.command and ctx.command.name == 'botkey':
        return True

    guild_id = ctx.guild.id
    cog_name = ctx.command.cog.__class__.__name__ if ctx.command and ctx.command.cog else None

    # 3. Restricted server check
    if guild_id in RESTRICTED_SERVERS:
        allowed_cogs = RESTRICTED_SERVERS[guild_id]
        if cog_name not in allowed_cogs:
            user_id      = ctx.author.id
            current_time = time.time()

            if user_id not in auth_failure_cooldown or current_time - auth_failure_cooldown[user_id] > 5:
                auth_failure_cooldown[user_id] = current_time
                try:
                    await ctx.message.delete()
                except Exception:
                    pass
                embed = discord.Embed(
                    title="⚠️ Command Not Available Here",
                    description=(
                        f"This server only has access to a limited set of commands.\n\n"
                        f"**Available commands on this server:**\n"
                        + "\n".join([f"• `{c}` cog commands" for c in allowed_cogs])
                        + f"\n\nContact the bot owner if you believe this is a mistake."
                    ),
                    color=discord.Color.orange()
                )
                embed.set_footer(text="Some features are restricted to specific servers.")
                await ctx.send(embed=embed, delete_after=10)
            return False
        # Restricted servers are also botkey-exempt — skip auth check
        return True

    # 4. Botkey-exempt servers skip authorization
    if guild_id in BOTKEY_EXEMPT_SERVERS:
        return True

    # 5. Owner server skips authorization
    if guild_id == OWNER_SERVER_ID:
        return True

    # 6. Key system disabled by owner — allow all
    if not getattr(bot, 'key_system_enabled', KEY_SYSTEM_ENABLED):
        return True

    # 7. Botkey / expiry check
    conn = sqlite3.connect(MAIN_DB_PATH)
    c = conn.cursor()
    c.execute("SELECT expires_at FROM authorized_servers WHERE guild_id = ?", (str(guild_id),))
    result = c.fetchone()
    conn.close()

    if not result:
        user_id      = ctx.author.id
        current_time = time.time()

        if user_id not in auth_failure_cooldown or current_time - auth_failure_cooldown[user_id] > 5:
            auth_failure_cooldown[user_id] = current_time

            embed = discord.Embed(
                title="🔐 Server Activation Required",
                description="This server is not activated. Use `!botkey [your key here]` first.",
                color=discord.Color.red()
            )
            embed.add_field(name="Need a key?", value="Contact the bot owner to obtain a key.")
            embed.add_field(name="Have a key?", value="Use `!botkey your-key-here` to activate.")
            await ctx.send(embed=embed)

            if len(auth_failure_cooldown) > 100:
                to_delete = [uid for uid, t in auth_failure_cooldown.items() if current_time - t > 60]
                for uid in to_delete:
                    del auth_failure_cooldown[uid]

        return False

    expires_at = result[0]
    if expires_at and time.time() > expires_at:
        user_id      = ctx.author.id
        current_time = time.time()

        if user_id not in auth_failure_cooldown or current_time - auth_failure_cooldown[user_id] > 5:
            auth_failure_cooldown[user_id] = current_time
            await ctx.send("❌ Your server's key has expired. Contact the bot owner for a new key.")

            if len(auth_failure_cooldown) > 100:
                to_delete = [uid for uid, t in auth_failure_cooldown.items() if current_time - t > 60]
                for uid in to_delete:
                    del auth_failure_cooldown[uid]

        return False

    return True


# ===== REGISTER CLEANUP HANDLERS =====
def register_cleanup_handlers():
    """Register signal handlers for graceful shutdown"""

    def sigint_handler(sig, frame):
        print("\n👋 Received shutdown signal (SIGINT)")
        close_all_connections()
        sys.exit(0)

    def sigterm_handler(sig, frame):
        print("\n👋 Received shutdown signal (SIGTERM)")
        close_all_connections()
        sys.exit(0)

    signal.signal(signal.SIGINT, sigint_handler)
    signal.signal(signal.SIGTERM, sigterm_handler)

    print("✅ Cleanup handlers registered")


# ===== LOAD ALL COGS =====
async def load_extensions():
    cogs = [
        'cogs.2events',
        'cogs.2tasks',
        'cogs.2level',
        'cogs.2moderation',
        'cogs.2tickets',
        'cogs.2verification',
        'cogs.2protection',
        'cogs.2giveaway',
        'cogs.2reaction_roles',
        'cogs.2backup',       
        'cogs.2cross_server',   # ← Commands and messages that can be said to other servers, Need to update: Make it so it only runs if in owner server.
        'cogs.2utility',        # ← Commands like "!say" "!help" etc...
        'cogs.2timer',          # ← Interactive DM countdown timers ("!timer")
        'cogs.2status_tracker', # ← Status tracker - Broken. Keeps sending the same message if it can't find the message from earlier due to problems like lag, disconnection, etc...
        'cogs.2admin',          # ← Administrator stuff = Main server
        'cogs.2id_system',      # ← ID System
        'cogs.2musical',        # ← Music system
        'cogs.2workout',        # My Personal Stuff
        'cogs.2anti_raid',      # ← Anti raid and Server automod
        'cogs.2MLBB',           # ← MLBB cog
        'cogs.2bug_report',     # ← Bug reporting system
        'cogs.2audit',          # ← Audit - Records all Commands ran
        'cogs.2games',          # ← Game System to make the bot more active
        'cogs.2absolute_detect',
    ]

    print("🔄 Loading cogs...")
    for cog in cogs:
        try:
            await bot.load_extension(cog)
            print(f"✅ Loaded: {cog}")
        except Exception as e:
            print(f"❌ Failed to load {cog}: {e}")
    print("✅ All cogs processed!")


async def main():
    register_cleanup_handlers()

    async with bot:
        try:
            await load_extensions()
            await bot.start(BOT_TOKEN)
        except KeyboardInterrupt:
            print("\n👋 Keyboard interrupt received")
        except Exception as e:
            print(f"❌ Fatal error: {e}")
        finally:
            close_all_connections()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot shut down gracefully by user")
        close_all_connections()
    except Exception as e:
        print(f"❌ Unhandled exception: {e}")
        close_all_connections()
