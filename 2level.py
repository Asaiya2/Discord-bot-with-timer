import discord
from discord.ext import commands
import sqlite3
import time
import asyncio
import re
from datetime import datetime
from collections import deque
import os

# ===== CONFIGURATION =====
DB_FOLDER = r"C:\Users\Kelly\Desktop\discord database"
MAIN_DB_PATH = os.path.join(DB_FOLDER, "asaiya_bot.db")
LEVEL_DB_PATH = os.path.join(DB_FOLDER, "levels.db")

# XP Settings
DEFAULT_BASE_XP = 10
COOLDOWN_SECONDS = 5

# Spam/Effort Detection
SPAM_TIME_WINDOW = 2.5
SPAM_MESSAGE_COUNT = 3

# Gibberish detection thresholds
MIN_WORD_LENGTH = 2
GIBBERISH_THRESHOLD = 0.7
REPEATED_MESSAGE_THRESHOLD = 0.5

# Effort Multipliers
EFFORT_MULTIPLIERS = {
    "normal": 1.0,
    "slightly_fast": 0.8,
    "moderate_spam": 0.5,
    "heavy_spam": 0.3,
    "repeated": 0.3,
    "gibberish": 0.2,
    "combined_zero": 0.0
}

NOXP_ROLE_PREFIX = "NOXP-"


def is_gibberish(text):
    """Check if text is gibberish (random characters, no meaning)"""
    if not text:
        return True

    words = text.split()
    if not words:
        return True

    consecutive_vowels = re.compile(r'[aeiou]{4,}')
    consecutive_consonants = re.compile(r'[bcdfghjklmnpqrstvwxyz]{6,}')
    repeated_chars = re.compile(r'(.)\1{4,}')

    gibberish_count = 0

    for word in words:
        word_lower = word.lower()

        if len(word_lower) < MIN_WORD_LENGTH:
            continue

        if consecutive_vowels.search(word_lower):
            gibberish_count += 1
        elif consecutive_consonants.search(word_lower):
            gibberish_count += 1
        elif repeated_chars.search(word_lower):
            gibberish_count += 1
        elif not any(c in 'aeiou' for c in word_lower):
            gibberish_count += 1

    ratio = gibberish_count / len(words)
    return ratio >= GIBBERISH_THRESHOLD


def is_repeated_spam(text, user_recent_messages):
    """Check if user is spamming repeated messages"""
    if not text or not user_recent_messages:
        return False

    recent = list(user_recent_messages)[-5:]
    if len(recent) < 3:
        return False

    same_count = sum(1 for msg in recent if msg == text)
    return same_count >= REPEATED_MESSAGE_THRESHOLD * len(recent)


def get_effort_multiplier(user_messages, current_time, is_repeated, is_gibberish_msg):
    """Calculate effort multiplier based on message patterns"""
    multiplier = 1.0
    violations = []

    if user_messages:
        recent = [ts for ts in user_messages if current_time - ts <= SPAM_TIME_WINDOW]
        count = len(recent)

        if count >= SPAM_MESSAGE_COUNT + 1:
            multiplier = min(multiplier, EFFORT_MULTIPLIERS["heavy_spam"])
            violations.append("heavy_spam")
        elif count >= SPAM_MESSAGE_COUNT:
            multiplier = min(multiplier, EFFORT_MULTIPLIERS["moderate_spam"])
            violations.append("moderate_spam")
        elif count >= 2:
            multiplier = min(multiplier, EFFORT_MULTIPLIERS["slightly_fast"])
            violations.append("slightly_fast")

    if is_repeated:
        multiplier = min(multiplier, EFFORT_MULTIPLIERS["repeated"])
        violations.append("repeated")

    if is_gibberish_msg:
        multiplier = min(multiplier, EFFORT_MULTIPLIERS["gibberish"])
        violations.append("gibberish")

    if len(violations) >= 3:
        multiplier = EFFORT_MULTIPLIERS["combined_zero"]

    return multiplier, violations


def get_reborn_bonus(reborns):
    """Calculate XP bonus from reborns.
    Pattern: Every 3 reborns = +100% (+10 XP)
    0: +0, 1: +3, 2: +6, 3: +10, 4: +13, 5: +16, 6: +20, etc.
    """
    base_bonus = (reborns // 3) * 10
    extra_bonus = (reborns % 3) * 3
    return base_bonus + extra_bonus


def get_max_level(reborns):
    """Calculate max level based on reborns"""
    return 10 + (reborns * 10)


def get_xp_for_level(level):
    """Total XP needed to reach a given level.
    FIX: Level 1 = 0 XP (starting floor), Level 2 = 300, Level 3 = 600, etc.
    This prevents the -300/600 XP display bug where stored level 1
    and calculated level 0 disagreed with each other.
    """
    if level <= 1:
        return 0
    return sum(i * 300 for i in range(1, level))


def get_current_level_from_xp(total_xp):
    """Calculate current level from total XP.
    FIX: Starts at level 1 (not 0) to match get_xp_for_level.
    """
    level = 1
    while total_xp >= get_xp_for_level(level + 1):
        level += 1
    return level


def get_xp_progress(total_xp, current_level):
    """Get XP progress towards next level.
    FIX: Returns (xp_earned_this_level, xp_needed_for_this_level)
    instead of (xp_earned, xp_required_for_next_absolute).
    This ensures the progress bar always shows correct positive values.
    """
    xp_at_current_level = get_xp_for_level(current_level)
    xp_at_next_level = get_xp_for_level(current_level + 1)
    xp_earned_this_level = total_xp - xp_at_current_level
    xp_needed_this_level = xp_at_next_level - xp_at_current_level
    return xp_earned_this_level, xp_needed_this_level


# ===== REBORN VIEW =====
class RebornView(discord.ui.View):
    def __init__(self, cog, user_id, current_level, current_reborns, accumulated_xp_warning=False):
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = user_id
        self.current_level = current_level
        self.current_reborns = current_reborns
        self.accumulated_xp_warning = accumulated_xp_warning

    @discord.ui.button(label="✨ Reborn Now", style=discord.ButtonStyle.green, custom_id="reborn_yes")
    async def reborn_yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This message wasn't meant for you.", ephemeral=True)
            return

        guild_id = interaction.guild.id
        # FIX: get_user_data returns exactly 3 values, not 4
        user_data = self.cog.get_user_data(self.user_id, guild_id)

        if not user_data:
            await interaction.response.send_message("❌ Could not find your data.", ephemeral=True)
            return

        current_level, total_xp, reborns = user_data
        max_lvl = get_max_level(reborns)

        if current_level < max_lvl:
            await interaction.response.send_message("❌ You are not at max level anymore!", ephemeral=True)
            return

        new_reborns = reborns + 1
        new_max_level = get_max_level(new_reborns)

        # Reset to level 1 with 0 XP on reborn
        self.cog.update_user_data(self.user_id, guild_id, level=1, total_xp=0, reborns=new_reborns)

        rank = self.cog.get_user_rank(self.user_id, guild_id)

        embed = discord.Embed(
            title="✨ Reborn Successful! ✨",
            description=(
                f"Congratulations {interaction.user.mention}!\n\n"
                f"You now have **{new_reborns}** reborn(s)!\n"
                f"Your max level is now **{new_max_level}**!\n"
                f"Your XP bonus is now **+{get_reborn_bonus(new_reborns)} XP** per message!\n\n"
                f"You are now back at **Level 1** with **0 XP**.\n"
                f"Your rank on the leaderboard is **#{rank}**.\n\n"
                f"Use `!leaderboard` to check the rankings!"
            ),
            color=discord.Color.gold()
        )

        settings = self.cog.get_guild_settings(guild_id)
        announcement_channel_id = settings.get('announcement_channel_id')

        await interaction.response.send_message(embed=embed, ephemeral=True)

        if announcement_channel_id:
            channel = interaction.guild.get_channel(announcement_channel_id)
            if channel:
                public_embed = discord.Embed(
                    title="✨ Reborn! ✨",
                    description=f"{interaction.user.mention} has been reborn! They now have **{new_reborns}** reborn(s)!",
                    color=discord.Color.gold()
                )
                await channel.send(embed=public_embed)

        self.stop()

    @discord.ui.button(label="⏰ Not Now", style=discord.ButtonStyle.secondary, custom_id="reborn_no")
    async def reborn_no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This message wasn't meant for you.", ephemeral=True)
            return

        if self.accumulated_xp_warning:
            embed = discord.Embed(
                title="⚠️ Warning",
                description=(
                    "You have chosen to delay reborn.\n\n"
                    "You can continue earning XP, but when you eventually reborn (via `!reborn`), "
                    "**all accumulated XP will be lost**.\n\n"
                    "Are you sure you want to continue?"
                ),
                color=discord.Color.orange()
            )

            # FIX: "Go Back" now re-sends a fresh RebornView instead of
            # calling reborn_no() with the wrong button reference
            class ConfirmDelayView(discord.ui.View):
                def __init__(self, parent_view):
                    super().__init__(timeout=60)
                    self.parent_view = parent_view

                @discord.ui.button(label="✅ Yes, Delay Reborn", style=discord.ButtonStyle.green)
                async def confirm_delay(self, confirm_interaction: discord.Interaction, confirm_button: discord.ui.Button):
                    if confirm_interaction.user.id != self.parent_view.user_id:
                        await confirm_interaction.response.send_message("❌ This message wasn't meant for you.", ephemeral=True)
                        return

                    embed = discord.Embed(
                        title="Reborn Delayed",
                        description=(
                            f"You have chosen to stay at Level {self.parent_view.current_level}.\n"
                            f"You can continue earning XP. Use `!reborn` when you're ready!\n\n"
                            f"**Remember:** All accumulated XP will be lost when you reborn."
                        ),
                        color=discord.Color.blue()
                    )
                    await confirm_interaction.response.send_message(embed=embed, ephemeral=True)
                    self.parent_view.stop()

                @discord.ui.button(label="❌ Go Back", style=discord.ButtonStyle.red)
                async def go_back(self, confirm_interaction: discord.Interaction, confirm_button: discord.ui.Button):
                    if confirm_interaction.user.id != self.parent_view.user_id:
                        await confirm_interaction.response.send_message("❌ This message wasn't meant for you.", ephemeral=True)
                        return

                    # Re-send the original reborn prompt cleanly
                    next_max = get_max_level(self.parent_view.current_reborns + 1)
                    next_bonus = get_reborn_bonus(self.parent_view.current_reborns + 1)

                    reborn_embed = discord.Embed(
                        title="🌟 **REBORN AVAILABLE!** 🌟",
                        description=(
                            f"You have reached **Level {self.parent_view.current_level}**!\n\n"
                            f"Would you like to **Reborn** and reach a much higher state?\n\n"
                            f"**If you Reborn:**\n"
                            f"• You will go back to **Level 1**\n"
                            f"• Your max level increases to **{next_max}**\n"
                            f"• You gain **+{next_bonus} XP** per message permanently\n\n"
                            f"*You can also use `!reborn` later if you change your mind.*"
                        ),
                        color=discord.Color.purple()
                    )
                    new_view = RebornView(
                        self.parent_view.cog,
                        self.parent_view.user_id,
                        self.parent_view.current_level,
                        self.parent_view.current_reborns,
                        accumulated_xp_warning=self.parent_view.accumulated_xp_warning
                    )
                    await confirm_interaction.response.send_message(embed=reborn_embed, view=new_view, ephemeral=True)

            await interaction.response.send_message(embed=embed, view=ConfirmDelayView(self), ephemeral=True)
        else:
            embed = discord.Embed(
                title="Reborn Delayed",
                description=(
                    f"You have chosen to stay at Level {self.current_level}.\n"
                    f"You can continue earning XP. Use `!reborn` when you're ready!\n\n"
                    f"**Remember:** All accumulated XP will be lost when you reborn."
                ),
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            self.stop()


class Level(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.xp_cooldown = {}
        # FIX: Use deque with maxlen — no manual size trimming needed
        self.message_history = {}   # {user_id: deque of timestamps}
        self.recent_messages = {}   # {user_id: deque of message strings}
        self.processed_messages = deque(maxlen=1000)
        self.processed_commands = {}

        self.setup_database()
        self.load_guild_settings()

        print("✅ Level cog initialized with Reborn system!")
        print(f"   Base XP: {DEFAULT_BASE_XP}")
        print(f"   Effort system: ON")
        print(f"   Reborn system: ON")

    # ===== DATABASE SETUP =====
    def setup_database(self):
        """Initialize level database tables"""
        try:
            conn = sqlite3.connect(LEVEL_DB_PATH)
            cursor = conn.cursor()

            # FIX: Default level is 1, consistent with get_current_level_from_xp(0) = 1
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT,
                    guild_id TEXT,
                    total_xp INTEGER DEFAULT 0,
                    level INTEGER DEFAULT 1,
                    reborns INTEGER DEFAULT 0,
                    last_message_time TIMESTAMP,
                    PRIMARY KEY (user_id, guild_id)
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS level_settings (
                    guild_id TEXT PRIMARY KEY,
                    base_xp INTEGER DEFAULT 10,
                    announcement_channel_id TEXT
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS level_roles (
                    guild_id TEXT,
                    level INTEGER,
                    role_id TEXT,
                    role_name TEXT,
                    PRIMARY KEY (guild_id, level)
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS noxp_users (
                    user_id TEXT,
                    guild_id TEXT,
                    PRIMARY KEY (user_id, guild_id)
                )
            ''')

            conn.commit()
            conn.close()
            print(f"✅ Level database connected: {LEVEL_DB_PATH}")

        except Exception as e:
            print(f"❌ Level database error: {e}")

    def load_guild_settings(self):
        """Load guild settings into memory"""
        self.guild_settings = {}
        try:
            conn = sqlite3.connect(LEVEL_DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT guild_id, base_xp, announcement_channel_id FROM level_settings")
            rows = cursor.fetchall()
            for guild_id, base_xp, channel_id in rows:
                self.guild_settings[int(guild_id)] = {
                    'base_xp': base_xp,
                    'announcement_channel_id': int(channel_id) if channel_id else None
                }
            conn.close()
        except Exception as e:
            print(f"Error loading guild settings: {e}")

    def get_guild_settings(self, guild_id):
        """Get guild settings, create default if not exists"""
        if guild_id not in self.guild_settings:
            self.guild_settings[guild_id] = {
                'base_xp': DEFAULT_BASE_XP,
                'announcement_channel_id': None
            }
        return self.guild_settings[guild_id]

    def is_leveling_enabled(self, guild_id):
        """Check if leveling is enabled for this server. Defaults to OFF."""
        try:
            import sqlite3, os
            db_folder = r"C:\Users\Kelly\Desktop\discord database"
            main_db = os.path.join(db_folder, "asaiya_bot.db")
            conn = sqlite3.connect(main_db)
            c = conn.cursor()
            # Add column if it doesn't exist yet (upgrade safety)
            try:
                c.execute("ALTER TABLE server_mod_settings ADD COLUMN leveling_enabled INTEGER DEFAULT 0")
                conn.commit()
            except sqlite3.OperationalError:
                pass
            c.execute("SELECT leveling_enabled FROM server_mod_settings WHERE guild_id = ?", (str(guild_id),))
            row = c.fetchone()
            conn.close()
            return bool(row[0]) if row and row[0] is not None else False
        except Exception as e:
            print(f"⚠️ Error checking leveling enabled for {guild_id}: {e}")
            return False

    def save_guild_settings(self, guild_id, base_xp=None, announcement_channel_id=None):
        """Save guild settings to database"""
        try:
            conn = sqlite3.connect(LEVEL_DB_PATH)
            cursor = conn.cursor()

            current = self.get_guild_settings(guild_id)
            new_base = base_xp if base_xp is not None else current['base_xp']
            new_channel = announcement_channel_id if announcement_channel_id is not None else current['announcement_channel_id']

            cursor.execute('''INSERT OR REPLACE INTO level_settings
                             (guild_id, base_xp, announcement_channel_id)
                             VALUES (?, ?, ?)''',
                          (str(guild_id), new_base, str(new_channel) if new_channel else None))
            conn.commit()
            conn.close()

            # FIX: Always sync in-memory settings after DB write
            self.guild_settings[guild_id] = {
                'base_xp': new_base,
                'announcement_channel_id': new_channel
            }
            return True
        except Exception as e:
            print(f"Error saving guild settings: {e}")
            return False

    def get_user_data(self, user_id, guild_id):
        """Get user data as (level, total_xp, reborns).
        FIX: Consistently returns exactly 3 values.
             Default level is 1 to match get_current_level_from_xp(0).
        """
        try:
            conn = sqlite3.connect(LEVEL_DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT level, total_xp, reborns FROM users WHERE user_id = ? AND guild_id = ?",
                          (str(user_id), str(guild_id)))
            result = cursor.fetchone()
            conn.close()

            if result:
                level, total_xp, reborns = result
                return level, total_xp, reborns
            return 1, 0, 0  # FIX: Default to level 1 (not 0)
        except Exception as e:
            print(f"Error getting user data: {e}")
            return 1, 0, 0

    def update_user_data(self, user_id, guild_id, level=None, total_xp=None, reborns=None):
        """Update user data in the database"""
        try:
            conn = sqlite3.connect(LEVEL_DB_PATH)
            cursor = conn.cursor()

            current = self.get_user_data(user_id, guild_id)
            new_level = level if level is not None else current[0]
            new_total_xp = total_xp if total_xp is not None else current[1]
            new_reborns = reborns if reborns is not None else current[2]

            cursor.execute('''INSERT OR REPLACE INTO users
                             (user_id, guild_id, level, total_xp, reborns, last_message_time)
                             VALUES (?, ?, ?, ?, ?, ?)''',
                          (str(user_id), str(guild_id), new_level, new_total_xp, new_reborns, datetime.now()))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error updating user data: {e}")
            return False

    def add_xp(self, user_id, guild_id, xp_gain):
        """Add XP to user and handle level ups.
        Returns (new_level, leveled_up, old_level).
        """
        current_level, current_total_xp, reborns = self.get_user_data(user_id, guild_id)
        new_total_xp = current_total_xp + xp_gain
        new_level = get_current_level_from_xp(new_total_xp)
        max_lvl = get_max_level(reborns)

        leveled_up = new_level > current_level

        # Cap at max level and cap XP at that level's threshold
        if new_level > max_lvl:
            new_level = max_lvl
            max_required = get_xp_for_level(max_lvl)
            if new_total_xp > max_required:
                new_total_xp = max_required

        self.update_user_data(user_id, guild_id, level=new_level, total_xp=new_total_xp)

        return new_level, leveled_up, current_level

    def get_user_rank(self, user_id, guild_id):
        """Get user's leaderboard rank by total XP"""
        try:
            conn = sqlite3.connect(LEVEL_DB_PATH)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) + 1 FROM users
                WHERE guild_id = ? AND total_xp > (
                    SELECT total_xp FROM users WHERE user_id = ? AND guild_id = ?
                )
            ''', (str(guild_id), str(user_id), str(guild_id)))
            rank = cursor.fetchone()[0]
            conn.close()
            return rank
        except:
            return 0

    def get_leaderboard(self, guild_id, limit=10, role_ids=None):
        """Get leaderboard data, optionally filtered by a list of role IDs.
        FIX: Fetches extra rows when filtering so the final list still
        reaches the requested limit after role filtering in Python.
        """
        try:
            conn = sqlite3.connect(LEVEL_DB_PATH)
            cursor = conn.cursor()
            # Fetch more rows upfront when we need to filter down later
            fetch_limit = limit * 3 if role_ids else limit
            cursor.execute('''
                SELECT user_id, level, total_xp, reborns FROM users
                WHERE guild_id = ?
                ORDER BY total_xp DESC
                LIMIT ?
            ''', (str(guild_id), fetch_limit))
            results = cursor.fetchall()
            conn.close()

            if role_ids:
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    return []
                filtered = []
                for user_id, level, total_xp, reborns in results:
                    member = guild.get_member(int(user_id))
                    if member and any(r.id in role_ids for r in member.roles):
                        filtered.append((user_id, level, total_xp, reborns))
                    if len(filtered) >= limit:
                        break
                return filtered

            return results
        except Exception as e:
            print(f"Error getting leaderboard: {e}")
            return []

    def is_noxp_user(self, user_id, guild_id):
        """Check if user is blocked from gaining XP"""
        try:
            conn = sqlite3.connect(LEVEL_DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM noxp_users WHERE user_id = ? AND guild_id = ?",
                          (str(user_id), str(guild_id)))
            result = cursor.fetchone()
            conn.close()
            return result is not None
        except:
            return False

    # ===== GAME ACTIVE TRACKING =====
    
    def set_game_active(self, user_id, guild_id, game_active):
        """Mark user as in a game (prevents XP gain from messages)"""
        if not hasattr(self, 'active_game_players'):
            self.active_game_players = set()
        
        key = f"{user_id}:{guild_id}"
        if game_active:
            self.active_game_players.add(key)
        else:
            self.active_game_players.discard(key)
    
    def is_in_game(self, user_id, guild_id):
        """Check if user is currently in a game"""
        if not hasattr(self, 'active_game_players'):
            self.active_game_players = set()
        key = f"{user_id}:{guild_id}"
        return key in self.active_game_players
    
    def get_user_xp(self, user_id, guild_id):
        """Get a user's total XP"""
        _, total_xp, _ = self.get_user_data(user_id, guild_id)
        return total_xp
    
    def deduct_xp(self, user_id, guild_id, amount):
        """Deduct XP from a user. Returns True if successful."""
        current_level, total_xp, reborns = self.get_user_data(user_id, guild_id)
        
        if total_xp < amount:
            return False
        
        new_total_xp = total_xp - amount
        new_level = get_current_level_from_xp(new_total_xp)
        
        self.update_user_data(user_id, guild_id, level=new_level, total_xp=new_total_xp)
        return True
    
    def add_xp_amount(self, user_id, guild_id, amount):
        """Add XP to a user (for game winnings)"""
        current_level, total_xp, reborns = self.get_user_data(user_id, guild_id)
        new_total_xp = total_xp + amount
        new_level = get_current_level_from_xp(new_total_xp)
        max_lvl = get_max_level(reborns)
        
        if new_level > max_lvl:
            new_level = max_lvl
            new_total_xp = get_xp_for_level(max_lvl)
        
        self.update_user_data(user_id, guild_id, level=new_level, total_xp=new_total_xp)

    def set_noxp_user(self, user_id, guild_id, blocked):
        """Set or remove NOXP status for user"""
        try:
            conn = sqlite3.connect(LEVEL_DB_PATH)
            cursor = conn.cursor()
            if blocked:
                cursor.execute("INSERT OR IGNORE INTO noxp_users (user_id, guild_id) VALUES (?, ?)",
                              (str(user_id), str(guild_id)))
            else:
                cursor.execute("DELETE FROM noxp_users WHERE user_id = ? AND guild_id = ?",
                              (str(user_id), str(guild_id)))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error setting NOXP user: {e}")
            return False

    def get_noxp_users(self, guild_id):
        """Get list of NOXP user IDs in guild"""
        try:
            conn = sqlite3.connect(LEVEL_DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM noxp_users WHERE guild_id = ?", (str(guild_id),))
            results = cursor.fetchall()
            conn.close()
            return [r[0] for r in results]
        except:
            return []

    def add_level_role(self, guild_id, level, role_id, role_name):
        """Add level role reward"""
        try:
            conn = sqlite3.connect(LEVEL_DB_PATH)
            cursor = conn.cursor()
            cursor.execute('''INSERT OR REPLACE INTO level_roles
                             (guild_id, level, role_id, role_name)
                             VALUES (?, ?, ?, ?)''',
                          (str(guild_id), level, str(role_id), role_name))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error adding level role: {e}")
            return False

    def remove_level_role(self, guild_id, level):
        """Remove level role reward"""
        try:
            conn = sqlite3.connect(LEVEL_DB_PATH)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM level_roles WHERE guild_id = ? AND level = ?",
                          (str(guild_id), level))
            deleted = cursor.rowcount
            conn.commit()
            conn.close()
            return deleted > 0
        except Exception as e:
            print(f"Error removing level role: {e}")
            return False

    def get_level_roles(self, guild_id):
        """Get all level roles for guild"""
        try:
            conn = sqlite3.connect(LEVEL_DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT level, role_id, role_name FROM level_roles WHERE guild_id = ? ORDER BY level ASC",
                          (str(guild_id),))
            results = cursor.fetchall()
            conn.close()
            return results
        except:
            return []

    async def check_level_roles(self, guild, member, new_level):
        """Assign any earned level roles to member"""
        level_roles = self.get_level_roles(guild.id)
        for level, role_id, role_name in level_roles:
            if new_level >= level:
                role = guild.get_role(int(role_id))
                if role and role not in member.roles:
                    try:
                        await member.add_roles(role, reason=f"Reached level {new_level}")
                    except Exception as e:
                        print(f"Error adding level role {role.name}: {e}")

    # ===== DUPLICATE PREVENTION =====
    async def check_duplicate(self, ctx):
        key = f"{ctx.author.id}:{ctx.command.name}"
        current_time = time.time()

        if key in self.processed_commands:
            if current_time - self.processed_commands[key] < 3:
                return True

        self.processed_commands[key] = current_time

        if len(self.processed_commands) > 100:
            to_delete = [k for k, t in self.processed_commands.items() if current_time - t > 10]
            for k in to_delete:
                del self.processed_commands[k]

        return False

    # ===== MESSAGE LISTENER =====
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        if message.content.startswith('!'):
            return

        # Check if leveling is enabled for this server
        if not self.is_leveling_enabled(message.guild.id):
            return

        if self.is_noxp_user(message.author.id, message.guild.id):
            return
        
        # Skip XP gain if user is in a game
        if self.is_in_game(message.author.id, message.guild.id):
            return

        # FIX: Use deque membership check — no manual size cleanup needed
        if message.id in self.processed_messages:
            return
        self.processed_messages.append(message.id)

        user_id = message.author.id
        guild_id = message.guild.id
        key = f"{user_id}-{guild_id}"
        current_time = time.time()

        # FIX: Cooldown check happens BEFORE appending to message_history,
        # so cooldown-rejected messages don't skew spam detection scores
        if key in self.xp_cooldown:
            if current_time - self.xp_cooldown[key] < COOLDOWN_SECONDS:
                return

        # Track message history using bounded deques
        if user_id not in self.message_history:
            self.message_history[user_id] = deque(maxlen=10)
            self.recent_messages[user_id] = deque(maxlen=10)

        self.message_history[user_id].append(current_time)
        self.recent_messages[user_id].append(message.content)

        # Check effort quality
        is_repeated = is_repeated_spam(message.content, self.recent_messages[user_id])
        is_gibberish_msg = is_gibberish(message.content)
        effort_multiplier, violations = get_effort_multiplier(
            self.message_history[user_id], current_time, is_repeated, is_gibberish_msg
        )

        if effort_multiplier == 0:
            self.xp_cooldown[key] = current_time
            return

        # Get user data and calculate XP
        current_level, total_xp, reborns = self.get_user_data(user_id, guild_id)
        settings = self.get_guild_settings(guild_id)
        base_xp = settings['base_xp']
        reborn_bonus = get_reborn_bonus(reborns)

        xp_gain = base_xp + current_level + reborn_bonus
        xp_gain = int(xp_gain * effort_multiplier)
        if xp_gain < 1:
            xp_gain = 1

        new_level, leveled_up, old_level = self.add_xp(user_id, guild_id, xp_gain)
        self.xp_cooldown[key] = current_time

        if leveled_up:
            await self.send_level_up_message(message, message.author, new_level, reborns, base_xp, reborn_bonus)
            await self.check_level_roles(message.guild, message.author, new_level)

            max_lvl_new = get_max_level(reborns)
            if new_level == max_lvl_new:
                await self.prompt_reborn(message, message.author, new_level, reborns)

    async def send_level_up_message(self, message, user, new_level, reborns, base_xp, reborn_bonus):
        """Send level up announcement to announcement channel or current channel"""
        settings = self.get_guild_settings(message.guild.id)
        announcement_channel_id = settings.get('announcement_channel_id')

        xp_per_message = base_xp + new_level + reborn_bonus

        embed = discord.Embed(
            title="🎉 **LEVEL UP!** 🎉",
            description=(
                f"{user.mention} has leveled up!\n\n"
                f"**Congratulations on reaching Level {new_level}!**\n\n"
                f"**Your Stats:**\n"
                f"• Reborns: {reborns}\n"
                f"• XP per message: **{xp_per_message}**\n"
                f"  (Base: {base_xp} + Level: {new_level} + Reborn: {reborn_bonus})\n"
                f"• Level Boost: +{new_level} XP\n"
                f"• Reborn Boost: +{reborn_bonus} XP"
            ),
            color=discord.Color.gold()
        )

        if announcement_channel_id:
            channel = message.guild.get_channel(announcement_channel_id)
            if channel:
                await channel.send(embed=embed)
                return
        # FIX: Always fall back to current channel so level ups are never silent
        await message.channel.send(embed=embed)

    async def prompt_reborn(self, message, user, current_level, reborns):
        """Prompt user to reborn when they hit max level.
        FIX: No longer silently fails when no announcement channel is set.
        Falls back to the current channel so users always see the prompt.
        """
        settings = self.get_guild_settings(message.guild.id)
        announcement_channel_id = settings.get('announcement_channel_id')

        next_max = get_max_level(reborns + 1)
        next_bonus = get_reborn_bonus(reborns + 1)
        max_lvl = get_max_level(reborns)

        embed = discord.Embed(
            title="🌟 **REBORN AVAILABLE!** 🌟",
            description=(
                f"{user.mention}, you have reached **Level {current_level}**, the pinnacle of your current state!\n\n"
                f"Would you like to **Reborn** and reach a much higher state?\n\n"
                f"**If you Reborn:**\n"
                f"• You will go back to **Level 1**\n"
                f"• Your max level increases to **{next_max}**\n"
                f"• You gain **+{next_bonus} XP** per message permanently\n\n"
                f"**Current XP Bonus:** +{get_reborn_bonus(reborns)} XP\n"
                f"**Next XP Bonus:** +{next_bonus} XP\n\n"
                f"*You can also use `!reborn` later if you change your mind.*"
            ),
            color=discord.Color.purple()
        )

        _, total_xp, _ = self.get_user_data(user.id, message.guild.id)
        required_for_max = get_xp_for_level(max_lvl)
        has_accumulated = total_xp > required_for_max

        view = RebornView(self, user.id, current_level, reborns, accumulated_xp_warning=has_accumulated)

        # Try announcement channel, fall back to current channel
        target_channel = None
        if announcement_channel_id:
            target_channel = message.guild.get_channel(announcement_channel_id)
        if not target_channel:
            target_channel = message.channel

        await target_channel.send(embed=embed, view=view)

    # ===== COMMANDS =====

    @commands.command(name='rank', aliases=['level', 'xp'])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def rank(self, ctx, member: discord.Member = None):
        """Check your rank or someone else's rank"""
        if await self.check_duplicate(ctx):
            return

        target = member or ctx.author

        level, total_xp, reborns = self.get_user_data(target.id, ctx.guild.id)
        rank = self.get_user_rank(target.id, ctx.guild.id)
        settings = self.get_guild_settings(ctx.guild.id)
        base_xp = settings['base_xp']
        reborn_bonus = get_reborn_bonus(reborns)
        xp_per_message = base_xp + level + reborn_bonus
        max_lvl = get_max_level(reborns)

        # FIX: get_xp_progress now returns (earned_this_level, needed_this_level)
        # so progress is always a positive value within 0-300 range
        xp_this_level, xp_needed_this_level = get_xp_progress(total_xp, level)
        progress_percent = int((xp_this_level / xp_needed_this_level) * 100) if xp_needed_this_level > 0 else 100
        progress_percent = max(0, min(100, progress_percent))  # Safety clamp
        progress_bar = "█" * (progress_percent // 10) + "░" * (10 - (progress_percent // 10))

        embed = discord.Embed(
            title=f"📊 {target.display_name}'s Rank",
            color=target.color if target.color.value != 0 else discord.Color.green()
        )
        embed.set_thumbnail(url=target.avatar.url if target.avatar else target.default_avatar.url)

        embed.add_field(name="Level", value=f"**{level}** / {max_lvl}", inline=True)
        embed.add_field(name="Reborns", value=f"**{reborns}**", inline=True)
        embed.add_field(name="Rank", value=f"**#{rank}**", inline=True)
        embed.add_field(name="Total XP", value=f"**{total_xp:,}**", inline=True)
        embed.add_field(name="XP per Message", value=f"**{xp_per_message}**", inline=True)
        embed.add_field(name="XP Bonus", value=f"+{reborn_bonus} (Reborn)", inline=True)

        if level < max_lvl:
            embed.add_field(
                name="Progress to Next Level",
                value=f"`{progress_bar}` {progress_percent}%\n{xp_this_level:,} / {xp_needed_this_level:,} XP",
                inline=False
            )
        else:
            embed.add_field(
                name="Status",
                value="🎯 **MAX LEVEL REACHED!** 🎯\nUse `!reborn` to ascend further!",
                inline=False
            )

        embed.set_footer(text="XP Formula: Base + Level + Reborn Bonus")
        await ctx.send(embed=embed)

    @commands.command(name='leaderboard', aliases=['lb'])
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def leaderboard(self, ctx, *roles: discord.Role):
        """Show paginated server leaderboard with profile pictures."""
        if await self.check_duplicate(ctx):
            return

        try:
            from PIL import Image, ImageDraw, ImageFont
            import aiohttp
            import io
        except ImportError:
            await ctx.send("❌ Pillow or aiohttp is not installed. Run `pip install Pillow aiohttp`.")
            return

        role_filter = list(roles[:3]) if roles else None
        role_ids = [r.id for r in role_filter] if role_filter else None

        leaderboard_data = self.get_leaderboard(ctx.guild.id, limit=200, role_ids=role_ids)

        if not leaderboard_data:
            await ctx.send("📭 No one has earned XP yet! Start chatting to earn XP.")
            return

        PER_PAGE = 10
        total_pages = max(1, (len(leaderboard_data) + PER_PAGE - 1) // PER_PAGE)

        # ── Colour / size constants ────────────────────────────────────────
        W, ROW_H = 680, 64
        PAD_X = 24
        AVATAR_SIZE = 44
        PODIUM_H = 160        # extra height for page-1 podium section

        BG          = (30,  31,  40)
        BG_ROW_ALT  = (38,  39,  50)
        BG_PODIUM   = (24,  25,  34)
        GOLD        = (255, 185,  30)
        SILVER      = (192, 192, 192)
        BRONZE      = (180, 100,  40)
        WHITE       = (255, 255, 255)
        MUTED       = (160, 160, 180)
        RANK_BG     = (50,  51,  65)

        MEDAL_COLORS = [GOLD, SILVER, BRONZE]
        MEDAL_LABELS = ["1ST", "2ND", "3RD"]

        async def fetch_avatar(session, url: str, size: int) -> Image.Image:
            """Download avatar and return a circular RGBA image."""
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    data = await resp.read()
                av = Image.open(io.BytesIO(data)).convert("RGBA").resize((size, size))
            except Exception:
                av = Image.new("RGBA", (size, size), (80, 80, 100, 255))

            # Circular mask
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
            result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            result.paste(av, mask=mask)
            return result

        def get_font(size: int, bold: bool = False):
            """Try to load a system font, fall back to default."""
            candidates = [
                "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            ]
            for path in candidates:
                if os.path.exists(path):
                    try:
                        from PIL import ImageFont
                        return ImageFont.truetype(path, size)
                    except Exception:
                        pass
            from PIL import ImageFont
            return ImageFont.load_default()

        async def build_image(page: int) -> discord.File:
            start = page * PER_PAGE
            page_data = leaderboard_data[start:start + PER_PAGE]

            is_first = page == 0
            top3 = leaderboard_data[:3] if is_first else []

            total_h = (PODIUM_H if is_first else 0) + ROW_H * len(page_data) + 60
            img = Image.new("RGB", (W, total_h), BG)
            draw = ImageDraw.Draw(img)

            fn_big   = get_font(22, bold=True)
            fn_med   = get_font(16, bold=True)
            fn_small = get_font(14, bold=False)
            fn_rank  = get_font(15, bold=True)
            fn_title = get_font(20, bold=True)

            # ── Title bar ─────────────────────────────────────────────────
            draw.rectangle([(0, 0), (W, 44)], fill=(20, 21, 30))
            title_txt = f"🏆  Leaderboard — {ctx.guild.name}  •  Page {page+1}/{total_pages}"
            draw.text((PAD_X, 12), title_txt, font=fn_med, fill=GOLD)

            y = 44

            async with aiohttp.ClientSession() as session:

                # ── Podium (page 1 only) ───────────────────────────────────
                if is_first and top3:
                    draw.rectangle([(0, y), (W, y + PODIUM_H)], fill=BG_PODIUM)

                    # Layout: 2nd left | 1st center | 3rd right
                    slots = [1, 0, 2]   # visual order: 2nd, 1st, 3rd
                    slot_w = W // 3
                    AV_POD = 56

                    for col, idx in enumerate(slots):
                        if idx >= len(top3):
                            continue
                        uid, lvl, xp, rbs = top3[idx]
                        member = ctx.guild.get_member(int(uid))
                        name = (member.display_name if member else "Unknown")[:18]
                        av_url = (member.avatar.url if (member and member.avatar)
                                  else (member.default_avatar.url if member else None))

                        cx = col * slot_w + slot_w // 2
                        color = MEDAL_COLORS[idx]
                        label = MEDAL_LABELS[idx]

                        # Avatar circle
                        av_y = y + 14
                        if av_url:
                            av_img = await fetch_avatar(session, av_url, AV_POD)
                            # Coloured ring
                            ring = Image.new("RGBA", (AV_POD + 6, AV_POD + 6), (0, 0, 0, 0))
                            ImageDraw.Draw(ring).ellipse((0, 0, AV_POD + 5, AV_POD + 5), fill=color + (255,))
                            img.paste(ring, (cx - AV_POD // 2 - 3, av_y - 3), ring)
                            img.paste(av_img, (cx - AV_POD // 2, av_y), av_img)

                        # Medal badge
                        badge_y = av_y + AV_POD + 4
                        bw = 40
                        draw.rounded_rectangle(
                            [(cx - bw // 2, badge_y), (cx + bw // 2, badge_y + 18)],
                            radius=9, fill=color
                        )
                        draw.text((cx - bw // 2 + 6, badge_y + 2), label, font=get_font(11, bold=True), fill=(30, 30, 30))

                        # Name
                        name_y = badge_y + 22
                        draw.text((cx, name_y), name, font=fn_small, fill=WHITE, anchor="mm")

                        # XP + level
                        sub = f"Lv.{lvl}  •  {xp:,} XP"
                        draw.text((cx, name_y + 18), sub, font=get_font(12), fill=MUTED, anchor="mm")

                    y += PODIUM_H

                # ── Row entries ───────────────────────────────────────────
                for i, (uid, lvl, xp, rbs) in enumerate(page_data):
                    rank = start + i + 1
                    row_bg = BG_ROW_ALT if i % 2 == 0 else BG
                    draw.rectangle([(0, y), (W, y + ROW_H)], fill=row_bg)

                    # Rank badge
                    badge_x, badge_y = PAD_X, y + ROW_H // 2 - 13
                    draw.rounded_rectangle(
                        [(badge_x, badge_y), (badge_x + 36, badge_y + 26)],
                        radius=6, fill=RANK_BG
                    )
                    draw.text((badge_x + 18, badge_y + 13), str(rank), font=fn_rank, fill=MUTED, anchor="mm")

                    # Avatar
                    av_x = badge_x + 46
                    av_y2 = y + ROW_H // 2 - AVATAR_SIZE // 2
                    member = ctx.guild.get_member(int(uid))
                    av_url = (member.avatar.url if (member and member.avatar)
                              else (member.default_avatar.url if member else None))
                    if av_url:
                        av_img = await fetch_avatar(session, av_url, AVATAR_SIZE)
                        img.paste(av_img, (av_x, av_y2), av_img)

                    # Name + stats
                    text_x = av_x + AVATAR_SIZE + 12
                    name = (member.display_name if member else "Unknown User")[:24]
                    draw.text((text_x, y + 12), name, font=fn_med, fill=WHITE)
                    sub = f"Lv. {lvl}  •  {rbs} reborn(s)  •  {xp:,} XP"
                    draw.text((text_x, y + 34), sub, font=fn_small, fill=MUTED)

                    # XP bar (right side)
                    bar_x = W - 130
                    bar_y = y + ROW_H // 2 - 5
                    bar_w = 100
                    max_xp = leaderboard_data[0][2] or 1
                    fill_w = int(bar_w * (xp / max_xp))
                    draw.rounded_rectangle([(bar_x, bar_y), (bar_x + bar_w, bar_y + 10)], radius=5, fill=RANK_BG)
                    if fill_w > 0:
                        bar_color = GOLD if rank <= 3 else (80, 120, 200)
                        draw.rounded_rectangle([(bar_x, bar_y), (bar_x + fill_w, bar_y + 10)], radius=5, fill=bar_color)

                    y += ROW_H

                # ── Footer ────────────────────────────────────────────────
                draw.rectangle([(0, y), (W, total_h)], fill=(20, 21, 30))
                draw.text((PAD_X, y + 14), "Sorted by Total XP  •  Use !rank to check your stats", font=fn_small, fill=MUTED)

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            return discord.File(buf, filename=f"leaderboard_page{page+1}.png")

        # ── Navigation View ───────────────────────────────────────────────
        class LeaderboardView(discord.ui.View):
            def __init__(self, page: int):
                super().__init__(timeout=120)
                self.page = page
                self.update_buttons()

            def update_buttons(self):
                self.prev_btn.disabled = self.page == 0
                self.next_btn.disabled = self.page >= total_pages - 1

            @discord.ui.button(label="‹ Previous", style=discord.ButtonStyle.secondary)
            async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user != ctx.author:
                    await interaction.response.send_message("❌ Only the command user can navigate.", ephemeral=True)
                    return
                await interaction.response.defer()
                self.page -= 1
                self.update_buttons()
                f = await build_image(self.page)
                await interaction.edit_original_response(attachments=[f], view=self)

            @discord.ui.button(label="Next ›", style=discord.ButtonStyle.secondary)
            async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user != ctx.author:
                    await interaction.response.send_message("❌ Only the command user can navigate.", ephemeral=True)
                    return
                await interaction.response.defer()
                self.page += 1
                self.update_buttons()
                f = await build_image(self.page)
                await interaction.edit_original_response(attachments=[f], view=self)

            async def on_timeout(self):
                for item in self.children:
                    item.disabled = True

        async with ctx.typing():
            file = await build_image(0)

        view = LeaderboardView(page=0)
        await ctx.send(file=file, view=view)

    @commands.command(name='reborn')
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def reborn_command(self, ctx):
        """Manually trigger reborn if at max level"""
        if await self.check_duplicate(ctx):
            return

        level, total_xp, reborns = self.get_user_data(ctx.author.id, ctx.guild.id)
        max_lvl = get_max_level(reborns)

        if level < max_lvl:
            await ctx.send(f"❌ You are not at max level yet! You need to reach Level {max_lvl} to reborn.")
            return

        settings = self.get_guild_settings(ctx.guild.id)
        announcement_channel_id = settings.get('announcement_channel_id')

        embed = discord.Embed(
            title="🌟 **REBORN AVAILABLE!** 🌟",
            description=(
                f"{ctx.author.mention}, you have reached **Level {level}**!\n\n"
                f"Would you like to **Reborn** and reach a much higher state?\n\n"
                f"**If you Reborn:**\n"
                f"• You will go back to **Level 1**\n"
                f"• Your max level increases to **{get_max_level(reborns + 1)}**\n"
                f"• You gain **+{get_reborn_bonus(reborns + 1)} XP** per message permanently\n\n"
                f"*This will delete all your accumulated XP!*"
            ),
            color=discord.Color.purple()
        )

        required_for_max = get_xp_for_level(max_lvl)
        has_accumulated = total_xp > required_for_max
        view = RebornView(self, ctx.author.id, level, reborns, accumulated_xp_warning=has_accumulated)

        # FIX: Always send — fall back to current channel if no announcement channel set
        target_channel = None
        if announcement_channel_id:
            target_channel = ctx.guild.get_channel(announcement_channel_id)
        if not target_channel:
            target_channel = ctx.channel

        if target_channel != ctx.channel:
            await ctx.send(f"📬 Check {target_channel.mention} to reborn!")

        await target_channel.send(embed=embed, view=view)

    # ===== LEVELING TOGGLE COMMANDS =====

    @commands.command(name='levelon')
    @commands.has_permissions(administrator=True)
    async def level_on(self, ctx):
        """Enable the leveling system for this server"""
        if await self.check_duplicate(ctx):
            return

        admin_cog = self.bot.get_cog('Admin')
        if not admin_cog:
            await ctx.send("❌ Admin cog not loaded.")
            return

        admin_cog.save_server_mod_setting(ctx.guild.id, "leveling_enabled", True)
        embed = discord.Embed(
            title="⭐ Leveling System: ON",
            description="Members will now earn XP for chatting. Existing levels and XP are preserved.",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="Use !leveloff to disable")
        await ctx.send(embed=embed)
        print(f"✅ Leveling enabled in {ctx.guild.name} by {ctx.author}")

    @commands.command(name='leveloff')
    @commands.has_permissions(administrator=True)
    async def level_off(self, ctx):
        """Disable the leveling system for this server"""
        if await self.check_duplicate(ctx):
            return

        admin_cog = self.bot.get_cog('Admin')
        if not admin_cog:
            await ctx.send("❌ Admin cog not loaded.")
            return

        admin_cog.save_server_mod_setting(ctx.guild.id, "leveling_enabled", False)
        embed = discord.Embed(
            title="⭐ Leveling System: OFF",
            description="Members will no longer earn XP. All existing levels and XP are preserved.",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="Use !levelon to re-enable")
        await ctx.send(embed=embed)
        print(f"⚠️ Leveling disabled in {ctx.guild.name} by {ctx.author}")

    @commands.command(name='expchannel')
    @commands.has_permissions(administrator=True)
    async def exp_channel(self, ctx):
        """Set current channel as level-up announcement channel"""
        if await self.check_duplicate(ctx):
            return

        if self.save_guild_settings(ctx.guild.id, announcement_channel_id=ctx.channel.id):
            await ctx.send(f"✅ Level-up announcements will now be sent to {ctx.channel.mention}")
        else:
            await ctx.send("❌ Failed to set announcement channel.")

    @commands.command(name='setbasexp')
    @commands.has_permissions(administrator=True)
    async def set_base_xp(self, ctx, amount: int):
        """Set base XP per message (1-100, default: 10)"""
        if await self.check_duplicate(ctx):
            return

        if amount < 1 or amount > 100:
            await ctx.send("❌ Base XP must be between 1 and 100.")
            return

        if self.save_guild_settings(ctx.guild.id, base_xp=amount):
            await ctx.send(f"✅ Base XP set to **{amount}** per message!")
        else:
            await ctx.send("❌ Failed to save settings.")

    @commands.command(name='expsettings')
    @commands.has_permissions(administrator=True)
    async def exp_settings(self, ctx):
        """Show current leveling settings"""
        if await self.check_duplicate(ctx):
            return

        settings = self.get_guild_settings(ctx.guild.id)
        base_xp = settings['base_xp']
        announcement_channel = ctx.guild.get_channel(settings['announcement_channel_id']) if settings['announcement_channel_id'] else None

        noxp_users = self.get_noxp_users(ctx.guild.id)
        level_roles = self.get_level_roles(ctx.guild.id)

        embed = discord.Embed(
            title="⚙️ Leveling System Settings",
            color=discord.Color.blue()
        )

        embed.add_field(name="Base XP per Message", value=f"**{base_xp}**", inline=True)
        embed.add_field(name="Announcement Channel", value=announcement_channel.mention if announcement_channel else "Not set", inline=True)
        embed.add_field(name="NOXP Users", value=f"**{len(noxp_users)}** user(s) blocked", inline=True)

        if level_roles:
            role_list = "\n".join([f"• Level {lvl}: <@&{role_id}>" for lvl, role_id, _ in level_roles[:10]])
            embed.add_field(name="Level Roles", value=role_list, inline=False)

        embed.set_footer(text="Use !setbasexp to change | !expchannel to set channel")
        await ctx.send(embed=embed)

    @commands.command(name='addlevel')
    @commands.has_permissions(administrator=True)
    async def add_level(self, ctx, member: discord.Member, amount: int):
        """Add levels to a user (respects max level)"""
        if await self.check_duplicate(ctx):
            return

        if amount < 1:
            await ctx.send("❌ Amount must be positive.")
            return

        current_level, total_xp, reborns = self.get_user_data(member.id, ctx.guild.id)
        max_lvl = get_max_level(reborns)

        new_level = min(current_level + amount, max_lvl)
        new_total_xp = get_xp_for_level(new_level)
        self.update_user_data(member.id, ctx.guild.id, level=new_level, total_xp=new_total_xp)

        added = new_level - current_level
        if new_level == max_lvl and new_level > current_level:
            await ctx.send(f"✅ Added {added} level(s) to {member.mention} (reached max level {max_lvl})!")

            settings = self.get_guild_settings(ctx.guild.id)
            announcement_channel_id = settings.get('announcement_channel_id')
            target_channel = ctx.guild.get_channel(announcement_channel_id) if announcement_channel_id else None
            if not target_channel:
                target_channel = ctx.channel

            embed = discord.Embed(
                title="🌟 **REBORN AVAILABLE!** 🌟",
                description=f"{member.mention} has reached max level and can now reborn!",
                color=discord.Color.purple()
            )
            await target_channel.send(embed=embed)
        else:
            await ctx.send(f"✅ Added {added} level(s) to {member.mention}! Now Level {new_level}")

    @commands.command(name='addre')
    @commands.has_permissions(administrator=True)
    async def add_reborn(self, ctx, member: discord.Member, amount: int):
        """Add reborn counts to a user"""
        if await self.check_duplicate(ctx):
            return

        if amount < 1:
            await ctx.send("❌ Amount must be positive.")
            return

        current_level, total_xp, reborns = self.get_user_data(member.id, ctx.guild.id)
        new_reborns = reborns + amount
        self.update_user_data(member.id, ctx.guild.id, reborns=new_reborns)

        new_max = get_max_level(new_reborns)
        if current_level < new_max:
            await ctx.send(f"✅ Added {amount} reborn(s) to {member.mention}! Now at {new_reborns} reborn(s).\nThey can now level up to {new_max}!")
        else:
            await ctx.send(f"✅ Added {amount} reborn(s) to {member.mention}! Now at {new_reborns} reborn(s).\nThey are at max level and can reborn again!")

    @commands.command(name='addxp')
    @commands.has_permissions(administrator=True)
    async def add_xp_cmd(self, ctx, member: discord.Member, amount: int):
        """Add raw XP to a user"""
        if await self.check_duplicate(ctx):
            return

        if amount < 1:
            await ctx.send("❌ Amount must be positive.")
            return

        current_level, total_xp, reborns = self.get_user_data(member.id, ctx.guild.id)
        new_total_xp = total_xp + amount
        new_level = get_current_level_from_xp(new_total_xp)
        max_lvl = get_max_level(reborns)

        if new_level > max_lvl:
            new_level = max_lvl
            new_total_xp = get_xp_for_level(max_lvl)

        self.update_user_data(member.id, ctx.guild.id, level=new_level, total_xp=new_total_xp)
        await ctx.send(f"✅ Added {amount} XP to {member.mention}! Now Level {new_level} with {new_total_xp:,} total XP.")

    @commands.command(name='setlevel')
    @commands.has_permissions(administrator=True)
    async def set_level(self, ctx, member: discord.Member, level: int):
        """Set user's level directly (capped at their max)"""
        if await self.check_duplicate(ctx):
            return

        if level < 1:
            await ctx.send("❌ Level must be at least 1.")
            return

        _, _, reborns = self.get_user_data(member.id, ctx.guild.id)
        max_lvl = get_max_level(reborns)

        if level > max_lvl:
            await ctx.send(f"❌ Cannot set level above {max_lvl} (max based on {reborns} reborn(s)).")
            return

        new_total_xp = get_xp_for_level(level)
        self.update_user_data(member.id, ctx.guild.id, level=level, total_xp=new_total_xp)
        await ctx.send(f"✅ Set {member.mention} to Level {level}!")

    @commands.command(name='rebornreset')
    @commands.has_permissions(administrator=True)
    async def reborn_reset(self, ctx, member: discord.Member):
        """Reset a user's reborn count to 0"""
        if await self.check_duplicate(ctx):
            return

        current_level, total_xp, reborns = self.get_user_data(member.id, ctx.guild.id)

        if reborns == 0:
            await ctx.send(f"ℹ️ {member.mention} already has 0 reborns.")
            return

        self.update_user_data(member.id, ctx.guild.id, reborns=0)

        
        max_lvl = get_max_level(0)
        if current_level > max_lvl:
            self.update_user_data(member.id, ctx.guild.id, level=max_lvl, total_xp=get_xp_for_level(max_lvl))

        await ctx.send(f"✅ Reset {member.mention}'s reborn count from {reborns} to 0.")

    @commands.group(name='levelrole', invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def level_role(self, ctx):
        """Manage level role rewards"""
        if await self.check_duplicate(ctx):
            return

        embed = discord.Embed(
            title="🎭 Level Role Commands",
            description=(
                "`!levelrole add <level> @role` - Add role reward for reaching level\n"
                "`!levelrole remove <level>` - Remove role reward"
            ),
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)

    @level_role.command(name='add')
    @commands.has_permissions(administrator=True)
    async def level_role_add(self, ctx, level: int, role: discord.Role):
        """Add a role reward for reaching a level"""
        if await self.check_duplicate(ctx):
            return

        if level < 1:
            await ctx.send("❌ Level must be at least 1.")
            return

        if self.add_level_role(ctx.guild.id, level, role.id, role.name):
            await ctx.send(f"✅ Added {role.mention} as reward for reaching Level {level}!")
        else:
            await ctx.send("❌ Failed to add role reward.")

    @level_role.command(name='remove')
    @commands.has_permissions(administrator=True)
    async def level_role_remove(self, ctx, level: int):
        """Remove a level role reward"""
        if await self.check_duplicate(ctx):
            return

        if self.remove_level_role(ctx.guild.id, level):
            await ctx.send(f"✅ Removed role reward for Level {level}.")
        else:
            await ctx.send(f"❌ No role reward found for Level {level}.")

    @commands.command(name='noexp')
    @commands.has_permissions(administrator=True)
    async def noexp(self, ctx, member: discord.Member):
        """Prevent a user from gaining any XP"""
        if await self.check_duplicate(ctx):
            return

        if self.is_noxp_user(member.id, ctx.guild.id):
            await ctx.send(f"⚠️ {member.mention} is already blocked from gaining XP.")
            return

        if self.set_noxp_user(member.id, ctx.guild.id, True):
            await ctx.send(f"✅ {member.mention} will no longer gain XP.")
        else:
            await ctx.send("❌ Failed to block user.")

    @commands.command(name='onexp')
    @commands.has_permissions(administrator=True)
    async def onexp(self, ctx, member: discord.Member):
        """Allow a user to gain XP again"""
        if await self.check_duplicate(ctx):
            return

        if not self.is_noxp_user(member.id, ctx.guild.id):
            await ctx.send(f"⚠️ {member.mention} is not blocked from gaining XP.")
            return

        if self.set_noxp_user(member.id, ctx.guild.id, False):
            await ctx.send(f"✅ {member.mention} can now gain XP again.")
        else:
            await ctx.send("❌ Failed to unblock user.")

    @commands.command(name='lvlhelp')
    async def lvl_help(self, ctx):
        """Show all leveling commands"""
        embed = discord.Embed(
            title="🎮 Leveling System - Commands",
            description="Here are all available leveling commands:",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="📊 User Commands",
            value=(
                "`!rank [@user]` - Check your rank or someone else's\n"
                "`!leaderboard [@role1 @role2 @role3]` - Show server leaderboard\n"
                "`!reborn` - Reborn when at max level\n"
                "`!lvlhelp` - Show this help"
            ),
            inline=False
        )

        embed.add_field(
            name="⚙️ Admin Commands",
            value=(
                "`!expchannel` - Set current channel for level announcements\n"
                "`!setbasexp <amount>` - Set base XP per message\n"
                "`!expsettings` - Show current settings\n"
                "`!addlevel @user <amount>` - Add levels to user\n"
                "`!addre @user <amount>` - Add reborn counts\n"
                "`!addxp @user <amount>` - Add raw XP\n"
                "`!setlevel @user <level>` - Set user's level\n"
                "`!rebornreset @user` - Reset reborn count\n"
                "`!levelrole add <level> @role` - Add level role reward\n"
                "`!levelrole remove <level>` - Remove level role reward\n"
                "`!noexp @user` - Block user from gaining XP\n"
                "`!onexp @user` - Allow user to gain XP again"
            ),
            inline=False
        )

        embed.add_field(
            name="ℹ️ How It Works",
            value=(
                f"• Base XP: {DEFAULT_BASE_XP} XP per message (configurable)\n"
                f"• Formula: Base + Level + Reborn Bonus\n"
                f"• Level 1 → 2: {get_xp_for_level(2)} XP needed\n"
                f"• Level 2 → 3: {get_xp_for_level(3) - get_xp_for_level(2)} XP needed\n"
                f"• Level 9 → 10: {get_xp_for_level(10) - get_xp_for_level(9)} XP needed\n"
                f"• Effort system reduces XP for spam/gibberish\n"
                f"• Reborn at max level to increase cap and gain permanent XP bonus"
            ),
            inline=False
        )

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Level(bot))
