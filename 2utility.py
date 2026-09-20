import discord
import random
from discord.ext import commands
import sqlite3
import time
import asyncio
import os
import subprocess
from datetime import datetime

# ===== CONFIGURATION =====
DB_FOLDER = r"C:\Users\Kelly\Desktop\discord database"
MAIN_DB_PATH = os.path.join(DB_FOLDER, "asaiya_bot.db")

BOT_CHANNEL_NAME = "asaiya-bot"
BOT_ROLE = "AsaiyaBot"
LOG_CHANNEL_NAME = "asaiya-log"
SNIPE_LIMIT = 100

# Server IDs
WORKOUT_SERVER_ID = 1484565350879330416
MLBB_SERVER_ID = 1485978412219891834
OWNER_SERVER_ID = 1484265140215087235


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot_start_time = time.time()
        self._help_cooldown = {}
        self.processed_commands = {}  # Track processed commands to prevent duplicates
        
        # Feature toggles cache
        self.word_filter_enabled = {}  # {guild_id: bool}
        self.invite_protection_enabled = {}  # {guild_id: bool}
        self.mlog_enabled = {}  # {guild_id: bool}
        
        # Repeat message tracking: {channel_id: {'message_id': int, 'content': str, 'task': Task}}
        self.repeat_messages = {}

        # Load settings
        self.load_all_settings()
        self.load_mlog_settings()
        
        print(f"✅ Utility cog initialized (ID: {id(self)})")

    # ===== LOAD SETTINGS =====
    def load_all_settings(self):
        """Load all per-server settings from database"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            
            # ===== CREATE TABLES IF NOT EXISTS =====
            c.execute('''CREATE TABLE IF NOT EXISTS anti_raid_settings
                         (guild_id TEXT PRIMARY KEY,
                          hack_detection INTEGER DEFAULT 1,
                          spam_detection INTEGER DEFAULT 1,
                          raid_detection INTEGER DEFAULT 1,
                          word_filter INTEGER DEFAULT 1,
                          invite_protection INTEGER DEFAULT 1,
                          updated_at REAL)''')
            
            # Load word filter settings
            c.execute("SELECT guild_id, word_filter FROM anti_raid_settings")
            rows = c.fetchall()
            for guild_id, enabled in rows:
                self.word_filter_enabled[int(guild_id)] = bool(enabled)
            
            # Load invite protection settings
            c.execute("SELECT guild_id, invite_protection FROM anti_raid_settings")
            rows = c.fetchall()
            for guild_id, enabled in rows:
                self.invite_protection_enabled[int(guild_id)] = bool(enabled)
            
            conn.close()
        except Exception as e:
            print(f"Error loading settings: {e}")

    def load_mlog_settings(self):
        """Load mlog enabled/disabled settings from database"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS mlog_settings
                         (guild_id TEXT PRIMARY KEY,
                          enabled INTEGER DEFAULT 1,
                          updated_at REAL)''')
            c.execute("SELECT guild_id, enabled FROM mlog_settings")
            rows = c.fetchall()
            for guild_id, enabled in rows:
                self.mlog_enabled[int(guild_id)] = bool(enabled)
            conn.close()
        except Exception as e:
            print(f"Error loading mlog settings: {e}")

    def save_mlog_setting(self, guild_id, enabled):
        """Save mlog enabled/disabled setting"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''INSERT OR REPLACE INTO mlog_settings
                         (guild_id, enabled, updated_at)
                         VALUES (?, ?, ?)''',
                      (str(guild_id), 1 if enabled else 0, time.time()))
            conn.commit()
            conn.close()
            self.mlog_enabled[guild_id] = enabled
            return True
        except Exception as e:
            print(f"Error saving mlog setting: {e}")
            return False

    def is_mlog_enabled(self, guild_id):
        """Check if mlog is enabled for a guild"""
        return self.mlog_enabled.get(guild_id, True)  # Default to enabled

    def is_word_filter_enabled(self, guild_id):
        """Check if word filter is enabled for a guild"""
        return self.word_filter_enabled.get(guild_id, True)

    def is_invite_protection_enabled(self, guild_id):
        """Check if invite protection is enabled for a guild"""
        return self.invite_protection_enabled.get(guild_id, True)

    # ===== REPEAT PERSISTENCE HELPERS =====

    def save_repeat(self, guild_id, channel_id, content, message_id=None):
        """Save an active repeat message to the server database."""
        try:
            conn = self.get_cached_connection(guild_id)
            if not conn:
                return
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS repeat_messages (
                channel_id  TEXT PRIMARY KEY,
                guild_id    TEXT,
                content     TEXT,
                message_id  TEXT
            )''')
            # Migration: add message_id column if it doesn't exist yet
            try:
                c.execute("ALTER TABLE repeat_messages ADD COLUMN message_id TEXT")
            except:
                pass
            c.execute('''INSERT OR REPLACE INTO repeat_messages
                         (channel_id, guild_id, content, message_id) VALUES (?, ?, ?, ?)''',
                      (str(channel_id), str(guild_id), content, str(message_id) if message_id else None))
            conn.commit()
        except Exception as e:
            print(f"Error saving repeat: {e}")

    def delete_repeat(self, guild_id, channel_id):
        """Remove a repeat message entry from the server database."""
        try:
            conn = self.get_cached_connection(guild_id)
            if not conn:
                return
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS repeat_messages (
                channel_id  TEXT PRIMARY KEY,
                guild_id    TEXT,
                content     TEXT
            )''')
            c.execute('DELETE FROM repeat_messages WHERE channel_id = ?',
                      (str(channel_id),))
            conn.commit()
        except Exception as e:
            print(f"Error deleting repeat: {e}")

    def load_repeats_for_guild(self, guild_id):
        """Load all saved repeat messages for a guild."""
        try:
            conn = self.get_cached_connection(guild_id)
            if not conn:
                return []
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS repeat_messages (
                channel_id  TEXT PRIMARY KEY,
                guild_id    TEXT,
                content     TEXT,
                message_id  TEXT
            )''')
            # Migration: add message_id column if it doesn't exist yet
            try:
                c.execute("ALTER TABLE repeat_messages ADD COLUMN message_id TEXT")
            except:
                pass
            c.execute('SELECT channel_id, content, message_id FROM repeat_messages WHERE guild_id = ?',
                      (str(guild_id),))
            return c.fetchall()
        except Exception as e:
            print(f"Error loading repeats: {e}")
            return []

    # ===== ON READY: restore repeat tasks =====

    @commands.Cog.listener()
    async def on_ready(self):
        """Restore all active repeat tasks from the database after a restart."""
        restored = 0
        for guild in self.bot.guilds:
            rows = self.load_repeats_for_guild(guild.id)
            for channel_id_str, content, saved_message_id in rows:
                channel_id = int(channel_id_str)
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    continue
                if channel_id in self.repeat_messages:
                    continue

                # ── Option A: try to reuse the existing message ──────────
                reused_msg = None
                if saved_message_id:
                    try:
                        reused_msg = await channel.fetch_message(int(saved_message_id))
                    except (discord.NotFound, discord.HTTPException):
                        reused_msg = None

                # Only send a new message if the old one no longer exists
                if reused_msg is None:
                    try:
                        reused_msg = await channel.send(content)
                        # Persist the new message_id so future restarts reuse it
                        self.save_repeat(guild.id, channel_id, content, reused_msg.id)
                    except Exception as e:
                        print(f"Could not restore repeat in {channel}: {e}")
                        continue

                sent = reused_msg

                async def watch_channel(ch=channel, ch_id=channel_id):
                    try:
                        while True:
                            await asyncio.sleep(2)
                            data = self.repeat_messages.get(ch_id)
                            if not data:
                                break
                            try:
                                latest = [m async for m in ch.history(limit=1)][0]
                            except Exception:
                                continue
                            if latest.id != data['message_id']:
                                try:
                                    old_msg = await ch.fetch_message(data['message_id'])
                                    await old_msg.delete()
                                except:
                                    pass
                                new_msg = await ch.send(data['content'])
                                data['message_id'] = new_msg.id
                                # Keep DB in sync with the new message_id
                                self.save_repeat(data['guild_id'], ch_id, data['content'], new_msg.id)
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        print(f"repeat watch_channel error in {ch_id}: {e}")

                task = asyncio.create_task(watch_channel())
                self.repeat_messages[channel_id] = {
                    'message_id': sent.id,
                    'content':    content,
                    'task':       task,
                    'guild_id':   guild.id,
                }
                restored += 1

        if restored:
            print(f"✅ Utility: restored {restored} repeat message(s)")

    # ===== DUPLICATE PREVENTION =====
    async def check_duplicate(self, ctx):
        """Check if this command was already processed"""
        key = f"{ctx.author.id}:{ctx.command.name}"
        current_time = time.time()
        
        if key in self.processed_commands:
            if current_time - self.processed_commands[key] < 3:
                print(f"⚠️ Prevented dual execution: {ctx.command.name} by {ctx.author} in {ctx.guild.name}")
                return True
        
        self.processed_commands[key] = current_time
        
        if len(self.processed_commands) > 100:
            to_delete = [k for k, t in self.processed_commands.items() if current_time - t > 10]
            for k in to_delete:
                del self.processed_commands[k]
        
        return False

    # ===== HELPERS =====

    def get_server_db_path(self, guild_id):
        """Get database path for a specific server"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT db_path FROM authorized_servers WHERE guild_id = ?", (str(guild_id),))
            result = c.fetchone()
            
            if not result:
                c.execute("SELECT db_path FROM servers WHERE guild_id = ?", (str(guild_id),))
                result = c.fetchone()
            
            conn.close()
            
            if result and result[0]:
                return result[0]
            return None
        except Exception as e:
            print(f"Error getting server db path for {guild_id}: {e}")
            return None

    def get_cached_connection(self, guild_id):
        """Get cached database connection with proper error handling"""
        current_time = time.time()

        # Clean up old connections periodically
        if hasattr(self.bot, 'db_connections') and len(self.bot.db_connections) > 10:
            for gid, last_used in list(self.bot.last_db_use.items()):
                if current_time - last_used > 300:
                    try:
                        if gid in self.bot.db_connections:
                            self.bot.db_connections[gid].close()
                            del self.bot.db_connections[gid]
                        del self.bot.last_db_use[gid]
                        print(f"🧹 Closed idle connection for guild {gid}")
                    except:
                        pass

        if hasattr(self.bot, 'db_connections') and guild_id in self.bot.db_connections:
            try:
                self.bot.db_connections[guild_id].execute("SELECT 1")
                if hasattr(self.bot, 'last_db_use'):
                    self.bot.last_db_use[guild_id] = current_time
                return self.bot.db_connections[guild_id]
            except:
                try:
                    self.bot.db_connections[guild_id].close()
                except:
                    pass
                if guild_id in self.bot.db_connections:
                    del self.bot.db_connections[guild_id]

        db_path = self.get_server_db_path(guild_id)
        if not db_path:
            return None

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        if not hasattr(self.bot, 'db_connections'):
            self.bot.db_connections = {}
        if not hasattr(self.bot, 'last_db_use'):
            self.bot.last_db_use = {}
            
        self.bot.db_connections[guild_id] = conn
        self.bot.last_db_use[guild_id] = current_time
        return conn

    async def get_log_channel(self, guild):
        try:
            conn = self.get_cached_connection(guild.id)
            if not conn:
                return None
            c = conn.cursor()
            c.execute("SELECT log_channel_id FROM log_channels")
            result = c.fetchone()
            if result and result[0]:
                return guild.get_channel(int(result[0]))
        except:
            pass
        return None

    async def get_mlog_channel(self, guild):
        """Get the message log channel for this server"""
        try:
            conn = self.get_cached_connection(guild.id)
            if conn:
                c = conn.cursor()
                try:
                    c.execute("ALTER TABLE log_channels ADD COLUMN mlog_channel_id TEXT")
                    conn.commit()
                except:
                    pass
                c.execute("SELECT mlog_channel_id FROM log_channels")
                result = c.fetchone()
                if result and result[0]:
                    return guild.get_channel(int(result[0]))
        except Exception as e:
            print(f"Error getting mlog channel: {e}")
        return None

    def get_time_afk(self, timestamp):
        seconds = int(time.time() - timestamp)
        if seconds < 60:
            return f"{seconds} second{'s' if seconds != 1 else ''}"
        elif seconds < 3600:
            minutes = seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        elif seconds < 86400:
            hours = seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''}"
        else:
            days = seconds // 86400
            return f"{days} day{'s' if days != 1 else ''}"

    # ===== BOTFOR COMMAND =====
    @commands.command(name='botfor')
    async def botfor(self, ctx):
        """Show what Asaiya Bot is for - detailed explanation of all features"""
        if await self.check_duplicate(ctx):
            return
        
        # Check for AsaiyaBot role
        has_bot_role = any(role.name == BOT_ROLE for role in ctx.author.roles) \
                       if isinstance(ctx.author, discord.Member) else False
        
        if not has_bot_role:
            await ctx.send(f"❌ You need the **{BOT_ROLE}** role to use this command.")
            return
        
        # Check if this is the workout server
        is_workout_server = ctx.guild and ctx.guild.id == WORKOUT_SERVER_ID
        is_owner_server = ctx.guild and ctx.guild.id == OWNER_SERVER_ID
        
        if is_workout_server:
            # Workout server - detailed fitness tracking explanation
            pages = [
                (
                    "**🏋️ ASAIYA BOT - WORKOUT & FITNESS TRACKER**\n\n"
                    "Asaiya Bot is a comprehensive fitness tracking system designed to help you document and track your fitness journey.\n\n"
                    "**🎯 PURPOSE**\n"
                    "This bot was created to help you:\n"
                    "• Track daily workouts, meals, and cardio sessions\n"
                    "• Build a library of foods with their nutritional info\n"
                    "• Monitor progress across days, months, and years\n"
                    "• Stay motivated by visualizing your consistency\n\n"
                    "**📅 HOW IT WORKS**\n"
                    "1. **Start Your Day** - Use `!start today` to begin tracking\n"
                    "2. **Log Everything** - Add foods, workouts, and cardio throughout the day\n"
                    "3. **End Your Day** - Use `!end today` to save and generate a summary channel\n"
                    "4. **Review Progress** - Check past days with `!day [number]` or browse month categories\n\n"
                    "**Support:** https://discord.gg/UqqeejzCgs"
                ),
                (
                    "**🏋️ WORKOUT FEATURES**\n\n"
                    "**💪 STRENGTH TRAINING**\n"
                    "• Log exercises with weight, sets, reps, and notes\n"
                    "• Track progressive overload over time\n"
                    "• Save custom notes for technique, form, or improvements\n\n"
                    "**🏃 CARDIO TRACKING**\n"
                    "• Interactive treadmill timer with speed input\n"
                    "• Tracks duration in minutes and seconds\n"
                    "• Records speed for pace analysis\n\n"
                    "**🍽️ NUTRITION TRACKING**\n"
                    "• Build your personal food library with `!addfood`\n"
                    "• Each food stores calories and protein per serving\n"
                    "• Quick logging with `!log [food] [amount]`\n"
                    "• Track daily totals for calories and protein\n\n"
                    "**📊 DAILY SUMMARY**\n"
                    "• Each completed day gets its own channel in monthly categories\n"
                    "• Summaries include all workouts, foods, and totals\n"
                    "• Lazy days (no activity) are marked for accountability\n\n"
                    "**Support:** https://discord.gg/UqqeejzCgs"
                ),
                (
                    "**🏋️ ORGANIZATION & PROGRESS**\n\n"
                    "**📁 AUTO-ORGANIZATION**\n"
                    "• Days 1-30 → Month 1 category\n"
                    "• Days 31-60 → Month 2 category\n"
                    "• Days 61-90 → Month 3 category\n"
                    "• Each day channel contains a complete summary embed\n\n"
                    "**📈 PROGRESS REVIEW**\n"
                    "• `!days` - See all completed days at a glance\n"
                    "• `!day [number]` - Review any completed day in detail\n"
                    "• `!today` - Check current day's progress before ending\n\n"
                    "**⚠️ DATA MANAGEMENT**\n"
                    "• All data is stored in your personal profile\n"
                    "• `!resetdays` - Complete reset (with confirmation)\n"
                    "• Food library is permanent unless reset\n\n"
                    "**💡 TIPS**\n"
                    "• Log foods immediately after eating for accuracy\n"
                    "• Add notes to workouts for future reference\n"
                    "• Use the treadmill timer for precise cardio tracking\n"
                    "• End each day even if lazy - accountability matters!\n\n"
                    "**Support:** https://discord.gg/UqqeejzCgs"
                )
            ]
        else:
            # Normal server - detailed explanation of all bot features (filtered for owner-only commands)
            owner_only_keywords = ["Key System", "!ckey", "!cmkey", "!ctkey", "!cmultikey", "!cdelkey", "!skey", "!helpkey", "!showservers", "!cbotkey"]
            
            if is_owner_server:
                # Owner server - show everything including key system
                pages = [
                    (
                        "**🤖 ASAIYA BOT - COMPLETE SERVER MANAGEMENT SYSTEM**\n\n"
                        "Asaiya Bot is a comprehensive Discord moderation and management bot designed to protect your server and enhance user experience.\n\n"
                        "**🎯 PRIMARY PURPOSE**\n"
                        "This bot was created to:\n"
                        "• Protect servers from raids, spam, and hacked accounts\n"
                        "• Provide organized ticket support systems\n"
                        "• Engage members with leveling, giveaways, and events\n"
                        "• Backup and restore server structures\n"
                        "• Manage member verification and ID profiles\n\n"
                        "**🔑 GETTING STARTED**\n"
                        "1. **Activate** - Use `!botkey [key]` to activate the server\n"
                        "2. **Setup** - Run `!setserver` to create channels and roles\n"
                        "3. **Configure** - Use `!modsetup` to set up moderation features\n"
                        "4. **Customize** - Add staff roles with `!staffroles add @role`\n\n"
                        "**⚠️ IMPORTANT:** The **AsaiyaBot** role has **Administrator permissions** - only give this to trusted staff!\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**🛡️ MODERATION & ANTI-RAID SYSTEM**\n\n"
                        "Asaiya Bot includes a progressive moderation system that automatically detects and handles threats.\n\n"
                        "**🤖 HACKED ACCOUNT PROTECTION**\n"
                        "Detects when a user sends the same message in multiple channels within 5 seconds.\n"
                        "• 1st offense: 24-hour timeout\n"
                        "• 2nd offense: Kick with rejoin invite\n"
                        "• 3rd+ offense: Permanent ban\n\n"
                        "**💬 SPAM DETECTION**\n"
                        "Detects 5+ messages in 3 seconds.\n"
                        "• All spam messages are automatically deleted\n"
                        "• User receives 10-minute timeout\n"
                        "• Staff are alerted via log channel\n\n"
                        "**👥 RAID DETECTION**\n"
                        "Alerts staff when 30+ users join within 60 seconds.\n"
                        "• Automatic alert in staff log channel\n"
                        "• Join rate history tracking with `!raidhistory`\n"
                        "• Clear join history with `!raidclear`\n"
                        "• Reset user violation counts with `!resetviolations @user`\n\n"
                        "**🔇 WORD FILTER**\n"
                        "Blocks inappropriate words (configurable with `!addfilter`, `!removefilter`, `!listfilters`)\n"
                        "• Toggle with `!filteron` / `!filteroff`\n"
                        "• Staff with AsaiyaBot role bypass the filter\n"
                        "• Manage filtered words:\n"
                        "  • `!addfilter <word>` - Add a word to filter\n"
                        "  • `!removefilter <word>` - Remove a word from filter\n"
                        "  • `!listfilters` - Show all filtered words\n"
                        "  • `!clearfilters` - Clear all filtered words\n\n"
                        "**🔗 INVITE LINK PROTECTION**\n"
                        "Blocks Discord invite links from non-staff members\n"
                        "• Toggle with `!inviteon` / `!inviteoff`\n"
                        "• Users with AsaiyaPass role can post invites\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**🎫 TICKET SYSTEM**\n\n"
                        "A complete support ticket system with intelligent categorization.\n\n"
                        "**📝 HOW TICKETS WORK**\n"
                        "1. Users click the \"Create Ticket\" button\n"
                        "2. They describe their issue in one sentence\n"
                        "3. Bot auto-categorizes based on keywords:\n"
                        "   • `bug/error/glitch` → Bug Ticket\n"
                        "   • `buy/payment/robux` → Buy Ticket\n"
                        "   • `hack/stolen/scam` → Report Ticket\n"
                        "   • `verify/roblox` → Verify Ticket\n"
                        "4. Support staff can claim and manage tickets\n\n"
                        "**👥 STAFF FEATURES**\n"
                        "• Claim tickets to show responsibility\n"
                        "• Transfer tickets between support members\n"
                        "• Add or remove users from tickets\n"
                        "• Rename ticket channels for clarity\n"
                        "• Private staff alerts in #ticket-alerts\n"
                        "• Ticket logs in #ticket-logs\n\n"
                        "**⭐ ANONYMOUS RATING SYSTEM**\n"
                        "After tickets are closed, users receive a surprise DM to rate support:\n"
                        "• 1-5 star rating system\n"
                        "• Completely anonymous - staff don't know who rated them\n"
                        "• Staff see only aggregated statistics with `!ratingstats`\n"
                        "• Individual staff can check their own ratings with `!ratingdetail`\n"
                        "• Promotes honest feedback without fear\n\n"
                        "**📁 TICKET ORGANIZATION**\n"
                        "• Active tickets in categorized channels\n"
                        "• Closed tickets moved to Asaiya-Done category\n"
                        "• Permanent logs kept for reference\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**🔐 VERIFICATION & ID SYSTEM**\n\n"
                        "A secure, global verification system that protects your server from bots and trolls.\n\n"
                        "**📱 HOW VERIFICATION WORKS**\n"
                        "1. New members receive a DM with a verification button\n"
                        "2. They can choose \"Verify Now\" or \"I'm Just Looking\"\n"
                        "3. Upon verification, they receive the verification role\n"
                        "4. Verification channel is automatically hidden from them\n"
                        "5. ID system triggers to create their profile\n\n"
                        "**🌍 GLOBAL VERIFICATION**\n"
                        "• Users verified in one server are auto-verified in all servers\n"
                        "• Reduces friction for members of multiple servers\n"
                        "• Maintains security across all communities\n\n"
                        "**🆔 ID SYSTEM**\n"
                        "After verification, users answer:\n"
                        "1. Who are you? (Display name/nickname)\n"
                        "2. Why did you join this server?\n"
                        "3. What do you like? (Hobbies/interests)\n"
                        "• Each member gets a unique server number (join order)\n"
                        "• `!id @user` - View user's profile\n"
                        "• `!id server` - View server profile\n"
                        "• `!id channel` - View channel profile\n"
                        "• `!gid @user` - View global profile\n\n"
                        "**⚙️ SERVER ADMIN CONTROLS**\n"
                        "• `!setverify @role` - Assign verification role\n"
                        "• `!startverify` / `!stopverify` - Toggle system\n"
                        "• `!fixverify` - Hide channel from verified users\n"
                        "• `!verifyall` - Send DMs to all unverified users\n"
                        "• `!idset users` - DM all users without profiles\n"
                        "• `!idset server` - Set up server profile\n"
                        "• `!idset channel` - Set up channel profile\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**📊 LEVELING & ENGAGEMENT SYSTEM**\n\n"
                        "Reward active members with leveling and role rewards.\n\n"
                        "**⚡ HOW LEVELING WORKS**\n"
                        "• 5-15 XP per message (configurable with `!setbasexp`)\n"
                        "• 5-second cooldown between XP gains\n"
                        "• Level requires Level × 300 XP\n"
                        "  (Level 1: 300 XP, Level 2: 600 XP, etc.)\n\n"
                        "**🛡️ ANTI-EXPLOIT MEASURES**\n"
                        "• Spam detection: 30% XP for repeated messages\n"
                        "• Gibberish detection: 20% XP for nonsense\n"
                        "• Fast messaging: Reduced XP for rapid messages\n"
                        "• Command messages don't give XP\n"
                        "• `!noexp` / `!onexp` to block/unblock users from gaining XP\n\n"
                        "**🎁 ROLE REWARDS**\n"
                        "• Configure roles that unlock at specific levels with `!levelrole add`\n"
                        "• Automatic assignment upon level up\n"
                        "• `!levelrole list` - View all rewards\n\n"
                        "**🏆 LEADERBOARDS**\n"
                        "• `!rank` - Check your level and progress\n"
                        "• `!leaderboard` - See top members in server\n"
                        "• `!reborn` - Reborn at max level to increase cap and gain XP bonus\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**🎉 GIVEAWAYS & REACTION ROLES**\n\n"
                        "Engage your community with interactive features.\n\n"
                        "**🎁 GIVEAWAY SYSTEM**\n"
                        "• Create giveaways with `!ga [prize] [amount] [time]`\n"
                        "• Users enter with button click\n"
                        "• Automatic winner selection at end time\n"
                        "• Reroll winners with `!ga re [msg_id]`\n"
                        "• End early with `!ga end [msg_id]`\n\n"
                        "**🎭 REACTION ROLES**\n"
                        "Two types available:\n\n"
                        "**Multiple Roles Allowed**\n"
                        "• Users can select any combination of roles\n"
                        "• Great for interests, games, preferences\n"
                        "• Setup with `!rrole`\n\n"
                        "**One-Role-Only Groups**\n"
                        "• Users can only have ONE role from the group\n"
                        "• Selecting a new role removes the old one\n"
                        "• Perfect for class selection, factions, teams\n"
                        "• Setup with `!onerole`\n\n"
                        "**📝 COMMANDS**\n"
                        "• `!rrole create #channel 'title'` - Quick create\n"
                        "• `!rrole add <msg_id> :emoji: @role` - Add to existing\n"
                        "• `!rrole remove <msg_id> :emoji:` - Remove from existing\n"
                        "• `!rrole list` - List all reaction roles\n"
                        "• `!rrole delete <msg_id>` - Delete reaction role\n"
                        "• `!rrole show <msg_id>` - Show details\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**🛡️ CHANNEL PROTECTION & BACKUP**\n\n"
                        "Never lose important channels or messages again.\n\n"
                        "**🛡️ PROTECTION LEVELS**\n"
                        "• **Full Protection** - Channel + message backup (`!fprotect`)\n"
                        "• **Channel Only** - Restore channel structure (`!protect`)\n"
                        "• **Messages Only** - Backup messages only (`!mprotect`)\n"
                        "• Apply to entire server with `!sprotect`\n\n"
                        "**🔄 RECOVERY SYSTEM**\n"
                        "• Deleted protected channels are automatically logged\n"
                        "• Recover with `!recover #channel` or `!recover all`\n"
                        "• Messages restore with timestamps and author info\n"
                        "• Channel categories are recreated automatically\n\n"
                        "**💾 SERVER BACKUP**\n"
                        "• `!sserver [password]` - Backup all roles, categories, channels\n"
                        "• One backup per user - ensures accountability\n"
                        "• `!remake [password]` - Restore entire server structure\n"
                        "• Backups auto-delete after 30 days\n"
                        "• `!backupstats` - View backup statistics\n"
                        "• `!cleanoldbackups [days]` - Manually clean old backups\n\n"
                        "**📝 MESSAGE BACKUPS**\n"
                        "• All messages in protected channels are backed up\n"
                        "• Deleted messages are logged with author and timestamp\n"
                        "• Restore with `!restore #channel [limit]`\n"
                        "• Auto-cleanup of old backups with `!cleanbackups`\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**🎵 MUSIC SYSTEM**\n\n"
                        "High-quality YouTube music playback with queue management.\n\n"
                        "**🎵 HOW MUSIC WORKS**\n"
                        "• Commands only work in #asaiya-hub channel\n"
                        "• Join a voice channel first\n"
                        "• Use `!play [YouTube link]` to add songs\n"
                        "• Automatic queue management\n"
                        "• Live countdown display with progress bar\n\n"
                        "**📋 COMMANDS**\n"
                        "• `!play` / `!p` - Play music\n"
                        "• `!queue` / `!q` - See upcoming songs\n"
                        "• `!stop` - Remove your song from queue\n"
                        "• `!stopall` - Staff only, clears everything\n"
                        "• `!nowplaying` / `!np` - Current song with live timer\n"
                        "• `!leave` / `!dc` - Disconnect from voice\n"
                        "• `!music` - Show music commands\n\n"
                        "**🎯 FEATURES**\n"
                        "• Persistent queue across bot restarts\n"
                        "• Shows requester for each song\n"
                        "• Clickable YouTube links in embed\n"
                        "• Volume control via Discord client\n"
                        "• Auto-disconnect after 5 minutes of inactivity\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**👁️ STATUS TRACKER**\n\n"
                        "Live member status monitoring with automatic updates.\n\n"
                        "**📊 FEATURES**\n"
                        "• Live member status monitoring\n"
                        "• Shows online/offline durations\n"
                        "• Global timezone display\n"
                        "• Updates every 10 seconds\n\n"
                        "**📋 COMMANDS**\n"
                        "• `!track #channel [@role]` - Start live status tracking\n"
                        "• `!untrack` - Stop status tracking\n"
                        "• `!checkstatus [@user]` - Check member status\n"
                        "• `!checkdict @user` - Dictionary check (admin)\n"
                        "• `!resetstatus @user` - Reset tracking data\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**🖼️ IMAGE-ONLY MODE & REPEAT MESSAGES**\n\n"
                        "Special utility commands for specific use cases.\n\n"
                        "**🖼️ IMAGE-ONLY MODE**\n"
                        "Restrict a channel to images and videos only.\n"
                        "• `!imageonly [#channel]` - Set channel to images/videos only\n"
                        "• `!imageonly-remove [#channel]` - Remove restriction\n"
                        "• `!imageonly-list` - List all image-only channels\n\n"
                        "**🔄 REPEAT MESSAGES**\n"
                        "Keep a message pinned at the bottom of a channel.\n"
                        "• `!repeat <message>` - Keep message at bottom of channel\n"
                        "• `!repeatstop [#channel]` - Stop repeating message\n\n"
                        "**📋 MESSAGE LOGGING**\n"
                        "Log deleted and edited messages to #message-logger\n"
                        "• `!mlog [#channel]` - Set message log channel\n"
                        "• `!onmlog` - Enable message logging\n"
                        "• `!offmlog` - Disable message logging\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**🔑 KEY ACTIVATION SYSTEM (ONLY IN ASAIYA HQ)**\n\n"
                        "Secure server activation with various key types.\n\n"
                        "**🔑 KEY TYPES**\n"
                        "• **Single-use** - One server activation (`!ckey`)\n"
                        "• **Multi-use** - Multiple activations (`!cmultikey`)\n"
                        "• **Timed** - Expires after set duration (`!ctkey`)\n"
                        "• **Master** - Unlimited uses, permanent (`!cmkey`)\n\n"
                        "**📊 MANAGEMENT**\n"
                        "• `!skey` - View all keys and active servers\n"
                        "• `!cdelkey` - Delete key and deactivate servers\n"
                        "• `!helpkey` - Show key system help\n\n"
                        "**🔄 AUTOMATIC MAINTENANCE**\n"
                        "• Servers with expired keys are auto-deactivated\n"
                        "• Keys with no remaining uses are deactivated\n"
                        "• Server owners notified when key expires\n"
                        "• Active server list updates every 20 minutes\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**📅 EVENTS & UTILITY COMMANDS**\n\n"
                        "Create interactive events and use utility commands.\n\n"
                        "**🎉 EVENT SYSTEM**\n"
                        "• Create events with join/leave buttons\n"
                        "• Optional role requirement for joining\n"
                        "• Real-time participant counter\n"
                        "• `!event create [title] [@role]`\n"
                        "• `!event list` - View all active events\n"
                        "• `!event end [msg_id]` - End events early\n\n"
                        "**🔧 UTILITY COMMANDS**\n"
                        "• `!ping` - Check bot latency\n"
                        "• `!serverinfo` - Show server info\n"
                        "• `!uptime` - Check bot uptime\n"
                        "• `!av [@user]` - Get user avatar\n"
                        "• `!afk [reason]` - Set AFK status\n"
                        "• `!timer` - Start an interactive countdown timer (sent via DM)\n"
                        "• `!snipe` - Show last deleted message\n"
                        "• `!snipelist [count]` - Show deleted messages\n"
                        "• `!asaiya` - Easter egg\n"
                        "• `!say <message>` - Bot says message\n"
                        "• `!showrole` - Show role hierarchy\n"
                        "• `!hello` - Bot introduction\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**⚙️ SETUP & CONFIGURATION**\n\n"
                        "Complete server setup wizards and templates.\n\n"
                        "**🎯 SERVER TEMPLATES**\n"
                        "• **Minimal** - Basic channels (bot, hub, log, welcome, goodbye)\n"
                        "• **Gaming** - Gaming-focused roles and channels\n"
                        "• **Community** - Community-focused roles and channels\n"
                        "• **Ticket** - Complete ticket system\n"
                        "• **Full** - Everything combined\n"
                        "• **Custom** - Build your own structure\n\n"
                        "**🏷️ AUTOMATIC ROLES**\n"
                        "When using templates, the bot creates:\n"
                        "• **AsaiyaBot** - Core bot role (ADMINISTRATOR PERMISSIONS)\n"
                        "• AsaiyaPass - Bypass invite protection\n"
                        "• AsaiyaClear - Bypass protected messages\n"
                        "• asaiya-support - Ticket support staff\n"
                        "• asaiya-request - Ticket creators\n"
                        "• Gaming/Community specific roles based on template\n\n"
                        "**📁 CATEGORIES CREATED**\n"
                        "• COMMAND CENTER - Bot commands\n"
                        "• GATEWAY - Welcome/goodbye/log channels\n"
                        "• INFORMATION HUB/CENTER - Rules, announcements\n"
                        "• COMMUNITY LOUNGE/GENERAL - Chat spaces\n"
                        "• VOICE CHANNELS/LOUNGE - Voice spaces\n"
                        "• Staff Team - Private staff area\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**👥 STAFF ROLES & PERMISSIONS**\n\n"
                        "Comprehensive staff role system with immunity.\n\n"
                        "**👑 STAFF IMMUNITY**\n"
                        "Staff members (with specified roles) bypass:\n"
                        "• Hacked account detection\n"
                        "• Spam detection\n"
                        "• Word filter\n"
                        "• Invite link protection\n"
                        "• Raid detection\n\n"
                        "**🔧 CONFIGURATION**\n"
                        "• `!staffroles` - View current staff roles\n"
                        "• `!staffroles add @role1 @role2` - Add staff roles\n"
                        "• `!staffroles remove @role` - Remove staff roles\n"
                        "• `!staffroles clear` - Remove all custom roles\n\n"
                        "**🛡️ PERMISSION SETUP**\n"
                        "• `!permset @role` - Set channel permissions for verified members\n"
                        "• Automatically locks all channels for unverified users\n"
                        "• Grants access to staff and verified members\n"
                        "• Skips public channels (verification, info)\n\n"
                        "**🛡️ HEALTH CHECK**\n"
                        "• `!cmdtest` - Comprehensive health check\n"
                        "• `!fullcmdtest` - ⚠️ DANGEROUS: Test all commands\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    )
                ]
            else:
                # Regular server - hide key system and owner-only commands
                pages = [
                    (
                        "**🤖 ASAIYA BOT - COMPLETE SERVER MANAGEMENT SYSTEM**\n\n"
                        "Asaiya Bot is a comprehensive Discord moderation and management bot designed to protect your server and enhance user experience.\n\n"
                        "**🎯 PRIMARY PURPOSE**\n"
                        "This bot was created to:\n"
                        "• Protect servers from raids, spam, and hacked accounts\n"
                        "• Provide organized ticket support systems\n"
                        "• Engage members with leveling, giveaways, and events\n"
                        "• Backup and restore server structures\n"
                        "• Manage member verification and ID profiles\n\n"
                        "**🔑 GETTING STARTED**\n"
                        "1. **Activate** - Use `!botkey [key]` to activate the server\n"
                        "2. **Setup** - Run `!setserver` to create channels and roles\n"
                        "3. **Configure** - Use `!modsetup` to set up moderation features\n"
                        "4. **Customize** - Add staff roles with `!staffroles add @role`\n\n"
                        "**⚠️ IMPORTANT:** The **AsaiyaBot** role has **Administrator permissions** - only give this to trusted staff!\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**🛡️ MODERATION & ANTI-RAID SYSTEM**\n\n"
                        "Asaiya Bot includes a progressive moderation system that automatically detects and handles threats.\n\n"
                        "**🤖 HACKED ACCOUNT PROTECTION**\n"
                        "Detects when a user sends the same message in multiple channels within 5 seconds.\n"
                        "• 1st offense: 24-hour timeout\n"
                        "• 2nd offense: Kick with rejoin invite\n"
                        "• 3rd+ offense: Permanent ban\n\n"
                        "**💬 SPAM DETECTION**\n"
                        "Detects 5+ messages in 3 seconds.\n"
                        "• All spam messages are automatically deleted\n"
                        "• User receives 10-minute timeout\n"
                        "• Staff are alerted via log channel\n\n"
                        "**👥 RAID DETECTION**\n"
                        "Alerts staff when 30+ users join within 60 seconds.\n"
                        "• Automatic alert in staff log channel\n"
                        "• Join rate history tracking with `!raidhistory`\n"
                        "• Clear join history with `!raidclear`\n"
                        "• Reset user violation counts with `!resetviolations @user`\n\n"
                        "**🔇 WORD FILTER**\n"
                        "Blocks inappropriate words (configurable with `!addfilter`, `!removefilter`, `!listfilters`)\n"
                        "• Toggle with `!filteron` / `!filteroff`\n"
                        "• Staff with AsaiyaBot role bypass the filter\n"
                        "• Manage filtered words:\n"
                        "  • `!addfilter <word>` - Add a word to filter\n"
                        "  • `!removefilter <word>` - Remove a word from filter\n"
                        "  • `!listfilters` - Show all filtered words\n"
                        "  • `!clearfilters` - Clear all filtered words\n\n"
                        "**🔗 INVITE LINK PROTECTION**\n"
                        "Blocks Discord invite links from non-staff members\n"
                        "• Toggle with `!inviteon` / `!inviteoff`\n"
                        "• Users with AsaiyaPass role can post invites\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**🎫 TICKET SYSTEM**\n\n"
                        "A complete support ticket system with intelligent categorization.\n\n"
                        "**📝 HOW TICKETS WORK**\n"
                        "1. Users click the \"Create Ticket\" button\n"
                        "2. They describe their issue in one sentence\n"
                        "3. Bot auto-categorizes based on keywords:\n"
                        "   • `bug/error/glitch` → Bug Ticket\n"
                        "   • `buy/payment/robux` → Buy Ticket\n"
                        "   • `hack/stolen/scam` → Report Ticket\n"
                        "   • `verify/roblox` → Verify Ticket\n"
                        "4. Support staff can claim and manage tickets\n\n"
                        "**👥 STAFF FEATURES**\n"
                        "• Claim tickets to show responsibility\n"
                        "• Transfer tickets between support members\n"
                        "• Add or remove users from tickets\n"
                        "• Rename ticket channels for clarity\n"
                        "• Private staff alerts in #ticket-alerts\n"
                        "• Ticket logs in #ticket-logs\n\n"
                        "**⭐ ANONYMOUS RATING SYSTEM**\n"
                        "After tickets are closed, users receive a surprise DM to rate support:\n"
                        "• 1-5 star rating system\n"
                        "• Completely anonymous - staff don't know who rated them\n"
                        "• Staff see only aggregated statistics with `!ratingstats`\n"
                        "• Individual staff can check their own ratings with `!ratingdetail`\n"
                        "• Promotes honest feedback without fear\n\n"
                        "**📁 TICKET ORGANIZATION**\n"
                        "• Active tickets in categorized channels\n"
                        "• Closed tickets moved to Asaiya-Done category\n"
                        "• Permanent logs kept for reference\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**🔐 VERIFICATION & ID SYSTEM**\n\n"
                        "A secure, global verification system that protects your server from bots and trolls.\n\n"
                        "**📱 HOW VERIFICATION WORKS**\n"
                        "1. New members receive a DM with a verification button\n"
                        "2. They can choose \"Verify Now\" or \"I'm Just Looking\"\n"
                        "3. Upon verification, they receive the verification role\n"
                        "4. Verification channel is automatically hidden from them\n"
                        "5. ID system triggers to create their profile\n\n"
                        "**🌍 GLOBAL VERIFICATION**\n"
                        "• Users verified in one server are auto-verified in all servers\n"
                        "• Reduces friction for members of multiple servers\n"
                        "• Maintains security across all communities\n\n"
                        "**🆔 ID SYSTEM**\n"
                        "After verification, users answer:\n"
                        "1. Who are you? (Display name/nickname)\n"
                        "2. Why did you join this server?\n"
                        "3. What do you like? (Hobbies/interests)\n"
                        "• Each member gets a unique server number (join order)\n"
                        "• `!id @user` - View user's profile\n"
                        "• `!id server` - View server profile\n"
                        "• `!id channel` - View channel profile\n"
                        "• `!gid @user` - View global profile\n\n"
                        "**⚙️ SERVER ADMIN CONTROLS**\n"
                        "• `!setverify @role` - Assign verification role\n"
                        "• `!startverify` / `!stopverify` - Toggle system\n"
                        "• `!fixverify` - Hide channel from verified users\n"
                        "• `!verifyall` - Send DMs to all unverified users\n"
                        "• `!idset users` - DM all users without profiles\n"
                        "• `!idset server` - Set up server profile\n"
                        "• `!idset channel` - Set up channel profile\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**📊 LEVELING & ENGAGEMENT SYSTEM**\n\n"
                        "Reward active members with leveling and role rewards.\n\n"
                        "**⚡ HOW LEVELING WORKS**\n"
                        "• 5-15 XP per message (configurable with `!setbasexp`)\n"
                        "• 5-second cooldown between XP gains\n"
                        "• Level requires Level × 300 XP\n"
                        "  (Level 1: 300 XP, Level 2: 600 XP, etc.)\n\n"
                        "**🛡️ ANTI-EXPLOIT MEASURES**\n"
                        "• Spam detection: 30% XP for repeated messages\n"
                        "• Gibberish detection: 20% XP for nonsense\n"
                        "• Fast messaging: Reduced XP for rapid messages\n"
                        "• Command messages don't give XP\n"
                        "• `!noexp` / `!onexp` to block/unblock users from gaining XP\n\n"
                        "**🎁 ROLE REWARDS**\n"
                        "• Configure roles that unlock at specific levels with `!levelrole add`\n"
                        "• Automatic assignment upon level up\n"
                        "• `!levelrole list` - View all rewards\n\n"
                        "**🏆 LEADERBOARDS**\n"
                        "• `!rank` - Check your level and progress\n"
                        "• `!leaderboard` - See top members in server\n"
                        "• `!reborn` - Reborn at max level to increase cap and gain XP bonus\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**🎉 GIVEAWAYS & REACTION ROLES**\n\n"
                        "Engage your community with interactive features.\n\n"
                        "**🎁 GIVEAWAY SYSTEM**\n"
                        "• Create giveaways with `!ga [prize] [amount] [time]`\n"
                        "• Users enter with button click\n"
                        "• Automatic winner selection at end time\n"
                        "• Reroll winners with `!ga re [msg_id]`\n"
                        "• End early with `!ga end [msg_id]`\n\n"
                        "**🎭 REACTION ROLES**\n"
                        "Two types available:\n\n"
                        "**Multiple Roles Allowed**\n"
                        "• Users can select any combination of roles\n"
                        "• Great for interests, games, preferences\n"
                        "• Setup with `!rrole`\n\n"
                        "**One-Role-Only Groups**\n"
                        "• Users can only have ONE role from the group\n"
                        "• Selecting a new role removes the old one\n"
                        "• Perfect for class selection, factions, teams\n"
                        "• Setup with `!onerole`\n\n"
                        "**📝 COMMANDS**\n"
                        "• `!rrole create #channel 'title'` - Quick create\n"
                        "• `!rrole add <msg_id> :emoji: @role` - Add to existing\n"
                        "• `!rrole remove <msg_id> :emoji:` - Remove from existing\n"
                        "• `!rrole list` - List all reaction roles\n"
                        "• `!rrole delete <msg_id>` - Delete reaction role\n"
                        "• `!rrole show <msg_id>` - Show details\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**🛡️ CHANNEL PROTECTION & BACKUP**\n\n"
                        "Never lose important channels or messages again.\n\n"
                        "**🛡️ PROTECTION LEVELS**\n"
                        "• **Full Protection** - Channel + message backup (`!fprotect`)\n"
                        "• **Channel Only** - Restore channel structure (`!protect`)\n"
                        "• **Messages Only** - Backup messages only (`!mprotect`)\n"
                        "• Apply to entire server with `!sprotect`\n\n"
                        "**🔄 RECOVERY SYSTEM**\n"
                        "• Deleted protected channels are automatically logged\n"
                        "• Recover with `!recover #channel` or `!recover all`\n"
                        "• Messages restore with timestamps and author info\n"
                        "• Channel categories are recreated automatically\n\n"
                        "**💾 SERVER BACKUP**\n"
                        "• `!sserver [password]` - Backup all roles, categories, channels\n"
                        "• One backup per user - ensures accountability\n"
                        "• `!remake [password]` - Restore entire server structure\n"
                        "• Backups auto-delete after 30 days\n"
                        "• `!backupstats` - View backup statistics\n"
                        "• `!cleanoldbackups [days]` - Manually clean old backups\n\n"
                        "**📝 MESSAGE BACKUPS**\n"
                        "• All messages in protected channels are backed up\n"
                        "• Deleted messages are logged with author and timestamp\n"
                        "• Restore with `!restore #channel [limit]`\n"
                        "• Auto-cleanup of old backups with `!cleanbackups`\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**🎵 MUSIC SYSTEM**\n\n"
                        "High-quality YouTube music playback with queue management.\n\n"
                        "**🎵 HOW MUSIC WORKS**\n"
                        "• Commands only work in #asaiya-hub channel\n"
                        "• Join a voice channel first\n"
                        "• Use `!play [YouTube link]` to add songs\n"
                        "• Automatic queue management\n"
                        "• Live countdown display with progress bar\n\n"
                        "**📋 COMMANDS**\n"
                        "• `!play` / `!p` - Play music\n"
                        "• `!queue` / `!q` - See upcoming songs\n"
                        "• `!stop` - Remove your song from queue\n"
                        "• `!stopall` - Staff only, clears everything\n"
                        "• `!nowplaying` / `!np` - Current song with live timer\n"
                        "• `!leave` / `!dc` - Disconnect from voice\n"
                        "• `!music` - Show music commands\n\n"
                        "**🎯 FEATURES**\n"
                        "• Persistent queue across bot restarts\n"
                        "• Shows requester for each song\n"
                        "• Clickable YouTube links in embed\n"
                        "• Volume control via Discord client\n"
                        "• Auto-disconnect after 5 minutes of inactivity\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**👁️ STATUS TRACKER**\n\n"
                        "Live member status monitoring with automatic updates.\n\n"
                        "**📊 FEATURES**\n"
                        "• Live member status monitoring\n"
                        "• Shows online/offline durations\n"
                        "• Global timezone display\n"
                        "• Updates every 10 seconds\n\n"
                        "**📋 COMMANDS**\n"
                        "• `!track #channel [@role]` - Start live status tracking\n"
                        "• `!untrack` - Stop status tracking\n"
                        "• `!checkstatus [@user]` - Check member status\n"
                        "• `!checkdict @user` - Dictionary check (admin)\n"
                        "• `!resetstatus @user` - Reset tracking data\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**🖼️ IMAGE-ONLY MODE & REPEAT MESSAGES**\n\n"
                        "Special utility commands for specific use cases.\n\n"
                        "**🖼️ IMAGE-ONLY MODE**\n"
                        "Restrict a channel to images and videos only.\n"
                        "• `!imageonly [#channel]` - Set channel to images/videos only\n"
                        "• `!imageonly-remove [#channel]` - Remove restriction\n"
                        "• `!imageonly-list` - List all image-only channels\n\n"
                        "**🔄 REPEAT MESSAGES**\n"
                        "Keep a message pinned at the bottom of a channel.\n"
                        "• `!repeat <message>` - Keep message at bottom of channel\n"
                        "• `!repeatstop [#channel]` - Stop repeating message\n\n"
                        "**📋 MESSAGE LOGGING**\n"
                        "Log deleted and edited messages to #message-logger\n"
                        "• `!mlog [#channel]` - Set message log channel\n"
                        "• `!onmlog` - Enable message logging\n"
                        "• `!offmlog` - Disable message logging\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**📅 EVENTS & UTILITY COMMANDS**\n\n"
                        "Create interactive events and use utility commands.\n\n"
                        "**🎉 EVENT SYSTEM**\n"
                        "• Create events with join/leave buttons\n"
                        "• Optional role requirement for joining\n"
                        "• Real-time participant counter\n"
                        "• `!event create [title] [@role]`\n"
                        "• `!event list` - View all active events\n"
                        "• `!event end [msg_id]` - End events early\n\n"
                        "**🔧 UTILITY COMMANDS**\n"
                        "• `!ping` - Check bot latency\n"
                        "• `!serverinfo` - Show server info\n"
                        "• `!uptime` - Check bot uptime\n"
                        "• `!av [@user]` - Get user avatar\n"
                        "• `!afk [reason]` - Set AFK status\n"
                        "• `!timer` - Start an interactive countdown timer (sent via DM)\n"
                        "• `!snipe` - Show last deleted message\n"
                        "• `!snipelist [count]` - Show deleted messages\n"
                        "• `!asaiya` - Easter egg\n"
                        "• `!say <message>` - Bot says message\n"
                        "• `!showrole` - Show role hierarchy\n"
                        "• `!hello` - Bot introduction\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**⚙️ SETUP & CONFIGURATION**\n\n"
                        "Complete server setup wizards and templates.\n\n"
                        "**🎯 SERVER TEMPLATES**\n"
                        "• **Minimal** - Basic channels (bot, hub, log, welcome, goodbye)\n"
                        "• **Gaming** - Gaming-focused roles and channels\n"
                        "• **Community** - Community-focused roles and channels\n"
                        "• **Ticket** - Complete ticket system\n"
                        "• **Full** - Everything combined\n"
                        "• **Custom** - Build your own structure\n\n"
                        "**🏷️ AUTOMATIC ROLES**\n"
                        "When using templates, the bot creates:\n"
                        "• **AsaiyaBot** - Core bot role (ADMINISTRATOR PERMISSIONS)\n"
                        "• AsaiyaPass - Bypass invite protection\n"
                        "• AsaiyaClear - Bypass protected messages\n"
                        "• asaiya-support - Ticket support staff\n"
                        "• asaiya-request - Ticket creators\n"
                        "• Gaming/Community specific roles based on template\n\n"
                        "**📁 CATEGORIES CREATED**\n"
                        "• COMMAND CENTER - Bot commands\n"
                        "• GATEWAY - Welcome/goodbye/log channels\n"
                        "• INFORMATION HUB/CENTER - Rules, announcements\n"
                        "• COMMUNITY LOUNGE/GENERAL - Chat spaces\n"
                        "• VOICE CHANNELS/LOUNGE - Voice spaces\n"
                        "• Staff Team - Private staff area\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    ),
                    (
                        "**👥 STAFF ROLES & PERMISSIONS**\n\n"
                        "Comprehensive staff role system with immunity.\n\n"
                        "**👑 STAFF IMMUNITY**\n"
                        "Staff members (with specified roles) bypass:\n"
                        "• Hacked account detection\n"
                        "• Spam detection\n"
                        "• Word filter\n"
                        "• Invite link protection\n"
                        "• Raid detection\n\n"
                        "**🔧 CONFIGURATION**\n"
                        "• `!staffroles` - View current staff roles\n"
                        "• `!staffroles add @role1 @role2` - Add staff roles\n"
                        "• `!staffroles remove @role` - Remove staff roles\n"
                        "• `!staffroles clear` - Remove all custom roles\n\n"
                        "**🛡️ PERMISSION SETUP**\n"
                        "• `!permset @role` - Set channel permissions for verified members\n"
                        "• Automatically locks all channels for unverified users\n"
                        "• Grants access to staff and verified members\n"
                        "• Skips public channels (verification, info)\n\n"
                        "**🛡️ HEALTH CHECK**\n"
                        "• `!cmdtest` - Comprehensive health check\n"
                        "• `!fullcmdtest` - ⚠️ DANGEROUS: Test all commands\n\n"
                        "**Support:** https://discord.gg/UqqeejzCgs"
                    )
                ]
        
        try:
            for i, page in enumerate(pages, 1):
                embed = discord.Embed(
                    description=page,
                    color=discord.Color.purple()
                )
                if len(pages) > 1:
                    embed.set_footer(text=f"Page {i}/{len(pages)} • What Asaiya Bot is For")
                await ctx.author.send(embed=embed)
                await asyncio.sleep(0.5)
            
            await ctx.send(f"📬 I've sent you {len(pages)} DMs explaining everything Asaiya Bot can do!")
            
        except discord.Forbidden:
            await ctx.send("❌ I couldn't DM you. Please enable DMs and try again.")

    # ===== SHOWROLE COMMAND =====
    @commands.command(name='showrole')
    async def showrole(self, ctx):
        """Show the current role hierarchy of the server (AsaiyaBot role required)"""
        if await self.check_duplicate(ctx):
            return
        
        has_bot_role = any(role.name == BOT_ROLE for role in ctx.author.roles) \
                       if isinstance(ctx.author, discord.Member) else False
        
        if not has_bot_role:
            await ctx.send(f"❌ You need the **{BOT_ROLE}** role to use this command.")
            return
        
        roles = sorted(ctx.guild.roles, key=lambda r: r.position, reverse=True)
        
        hierarchy_lines = []
        hierarchy_lines.append(f"**Role Hierarchy for {ctx.guild.name}**")
        hierarchy_lines.append("")
        hierarchy_lines.append("```")
        
        for i, role in enumerate(roles):
            if role.name == "@everyone":
                hierarchy_lines.append(f"{i+1}. @everyone (ID: {role.id})")
            else:
                managed = " [BOT]" if role.managed else ""
                hoist = " [DISPLAYED]" if role.hoist else ""
                mentionable = " [MENTIONABLE]" if role.mentionable else ""
                perms = " [ADMIN]" if role.permissions.administrator else ""
                
                hierarchy_lines.append(
                    f"{i+1}. {role.name}{managed}{hoist}{mentionable}{perms} (ID: {role.id})"
                )
        
        hierarchy_lines.append("```")
        hierarchy_lines.append("")
        hierarchy_lines.append("**Legend:**")
        hierarchy_lines.append("• [BOT] - Role managed by a bot")
        hierarchy_lines.append("• [DISPLAYED] - Role shows in member list separately")
        hierarchy_lines.append("• [MENTIONABLE] - Role can be mentioned")
        hierarchy_lines.append("• [ADMIN] - Role has Administrator permission")
        hierarchy_lines.append("")
        hierarchy_lines.append(f"**Total Roles:** {len(roles)}")
        
        content = "\n".join(hierarchy_lines)
        chunks = [content[i:i+1900] for i in range(0, len(content), 1900)]
        
        try:
            for chunk in chunks:
                await ctx.author.send(chunk)
            await ctx.send(f"📬 I've sent the role hierarchy to your DMs!")
        except discord.Forbidden:
            await ctx.send("❌ I couldn't DM you. Please enable DMs and try again.")

    # ===== HELP COMMAND =====
    @commands.command(name='help')
    async def help(self, ctx):
        """Show all available commands"""
        user_id = ctx.author.id
        current_time = time.time()
        if user_id in self._help_cooldown:
            if current_time - self._help_cooldown[user_id] < 3:
                print(f"⚠️ Prevented dual execution: help by {ctx.author} in {ctx.guild.name}")
                return
        self._help_cooldown[user_id] = current_time

        # Check which server this is
        is_workout_server = ctx.guild and ctx.guild.id == WORKOUT_SERVER_ID
        is_mlbb_server = ctx.guild and ctx.guild.id == MLBB_SERVER_ID
        is_owner_server = ctx.guild and ctx.guild.id == OWNER_SERVER_ID

        if is_mlbb_server:
            # MLBB SERVER - Show all available commands from allowed cogs
            help_pages = [
                (
                    "**🎮 MLBB SERVER - Available Commands**\n\n"
                    "Welcome to the MLBB Server! Here are all the commands you can use:\n\n"
                    "**🎮 MLBB Commands**\n"
                    "`!mlbbid` - Create or edit your MLBB profile\n"
                    "`!mlid [@user]` - View MLBB profile (staff can view anyone)\n"
                    "`!mlbb-status [@user]` - View verified lanes and levels\n"
                    "`!mlbb-roles` - Show all available MLBB level roles\n"
                    "`!mlidlist` - List all MLBB profiles (staff only)\n"
                    "`!mliddelete @user` - Delete user's MLBB profile (staff only)\n\n"
                    "**⚔️ Battle Spell Tracker**\n"
                    "`!mlbbspell` - Track enemy battle spell cooldowns\n\n"
                    "**📊 Leveling System**\n"
                    "`!rank [@user]` - Check your rank\n"
                    "`!leaderboard [limit]` - Show server leaderboard\n"
                    "`!lvlhelp` - Show all leveling commands\n\n"
                    "**🆔 ID System**\n"
                    "`!gid [@user]` - View a user's global profile\n"
                    "`!idhelp` - Show ID system commands\n\n"
                    "**🎉 Giveaways**\n"
                    "`!ga [item] [amount] [time]` - Quick giveaway\n"
                    "`!ga start` - Interactive giveaway setup\n"
                    "`!ga end [msg_id]` - End giveaway early\n"
                    "`!ga re [msg_id]` - Reroll winner\n"
                    "`!ga list` - List active giveaways\n\n"
                    "**🎭 Reaction Roles**\n"
                    "`!rrole` - Start reaction role setup\n"
                    "`!onerole` - Start one-role-only setup\n"
                    "`!rrole list` - List all reaction roles\n"
                    "`!rrole delete <msg_id>` - Delete reaction role\n\n"
                    "**📅 Events**\n"
                    "`!event create [title] [@role]` - Create event\n"
                    "`!event end [msg_id]` - End event early\n"
                    "`!event list` - List active events\n\n"
                    "**Support:** https://discord.gg/UqqeejzCgs"
                ),
                (
                    "**🎮 MLBB SERVER - Commands (Page 2/3)**\n\n"
                    "**🛡️ Anti-Raid & Moderation**\n"
                    "`!raidstatus` - Check join rate and raid status\n"
                    "`!raidhistory [minutes]` - Show join history\n"
                    "`!raidclear` - Clear join history\n"
                    "`!resetviolations @user` - Reset user's violation count\n"
                    "`!hackon` - Enable hacked account detection\n"
                    "`!hackoff` - Disable hacked account detection\n"
                    "`!startspam` - Enable spam detection\n"
                    "`!stopspam` - Disable spam detection\n"
                    "`!startraid` - Enable raid detection\n"
                    "`!stopraid` - Disable raid detection\n"
                    "`!antiraidstatus` - Show all anti-raid settings\n"
                    "`!addfilter <word>` - Add word to filter\n"
                    "`!removefilter <word>` - Remove word from filter\n"
                    "`!listfilters` - Show all filtered words\n"
                    "`!clearfilters` - Clear all filtered words\n"
                    "`!timeout @user mins [reason]` - Timeout user\n"
                    "`!untimeout @user` - Remove timeout\n"
                    "`!warn @user <reason>` - Warn member\n"
                    "`!warnings [@user]` - Check warnings\n"
                    "`!clear [amount]` - Clear messages\n"
                    "`!lock [#channel]` - Lock channel\n"
                    "`!unlock [#channel]` - Unlock channel\n"
                    "`!slowmode <seconds>` - Set slowmode\n\n"
                    "**👑 Admin Commands**\n"
                    "`!modsetup` - Run moderation setup wizard\n"
                    "`!modstatus` - Show current moderation settings\n"
                    "`!staffroles` - View/add/remove staff immunity roles\n"
                    "`!staffroles add @role` - Add staff role\n"
                    "`!staffroles remove @role` - Remove staff role\n"
                    "`!Arole` - Grant Administrator to AsaiyaBot role\n\n"
                    "**Support:** https://discord.gg/UqqeejzCgs"
                ),
                (
                    "**🎮 MLBB SERVER - Commands (Page 3/3)**\n\n"
                    "**🎵 Music Commands**\n"
                    "`!play [link]` - Play music (in #asaiya-hub)\n"
                    "`!stop` - Remove your song from queue\n"
                    "`!queue` - Show queue\n"
                    "`!nowplaying` - Current song with live timer\n"
                    "`!leave` - Leave voice channel\n"
                    "`!stopall` - Stop all music (staff only)\n"
                    "`!music` - Show music commands\n\n"
                    "**👁️ Status Tracker**\n"
                    "`!track #channel [@role]` - Start live status tracking\n"
                    "`!untrack` - Stop status tracking\n"
                    "`!checkstatus [@user]` - Check member status\n"
                    "`!checkdict @user` - Dictionary check (admin)\n"
                    "`!resetstatus @user` - Reset tracking data\n\n"
                    "**🖼️ Utility Commands**\n"
                    "`!imageonly [#channel]` - Set channel to images/videos only\n"
                    "`!imageonly-remove [#channel]` - Remove restriction\n"
                    "`!imageonly-list` - List image-only channels\n"
                    "`!repeat <message>` - Keep message at bottom of channel\n"
                    "`!repeatstop [#channel]` - Stop repeating message\n"
                    "`!mlog [#channel]` - Set message log channel\n"
                    "`!onmlog` - Enable message logging\n"
                    "`!offmlog` - Disable message logging\n\n"
                    "**📋 Basic Utility**\n"
                    "`!ping` - Check bot latency\n"
                    "`!serverinfo` - Show server info\n"
                    "`!uptime` - Check bot uptime\n"
                    "`!avatar [@user]` - Get user avatar\n"
                    "`!afk [reason]` - Set AFK status\n"
                    "`!timer` - Start an interactive countdown timer (sent via DM)\n"
                    "`!snipe` - Show last deleted message\n"
                    "`!snipelist [count]` - Show deleted messages\n"
                    "`!asaiya` - Easter egg\n"
                    "`!say <message>` - Bot says message (staff)\n\n"
                    "**🔑 Activation**\n"
                    "`!botkey [key]` - Activate server (if needed)\n\n"
                    "**Support:** https://discord.gg/UqqeejzCgs"
                )
            ]
            
        elif is_workout_server:
            # Workout server - only show workout commands
            help_pages = [
                (
                    "**🏋️ Asaiya - Workout & Fitness**\n\n"
                    "**📅 Workout Tracking**\n"
                    "`!start today` - Begin tracking your day (Day 1, 2, 3...)\n"
                    "`!end today` - End current day, save data, create day channel\n"
                    "`!today` - Show current day's progress\n"
                    "`!day [number]` - View summary of a specific completed day\n"
                    "`!days` - List all completed days\n"
                    "`!resetdays` - ⚠️ DELETE ALL your workout data (with confirmation)\n\n"
                    "**🍽️ Food Tracking**\n"
                    "`!addfood` - Interactive: add food to your library\n"
                    "`!logfood` - Interactive: log food eaten today\n"
                    "`!log [food] [amount]` - Quick log (e.g., `!log egg 2`)\n"
                    "`!myfoods` - List all foods in your library\n\n"
                    "**💪 Workout Logging**\n"
                    "`!logworkout` - Interactive: log strength workout\n"
                    "`!treadmill` - Interactive timer: speed → start → stop → saves\n\n"
                    "**📁 Auto-Organization**\n"
                    "• Days 1-30 → Month 1 category\n"
                    "• Days 31-60 → Month 2 category\n"
                    "• Days 61-90 → Month 3 category\n"
                    "• Each day gets its own channel with summary\n\n"
                    "**Support:** https://discord.gg/UqqeejzCgs"
                )
            ]
            
        else:
            # Normal server - Check for mod roles
            MOD_ROLES = ["AsaiyaBot", "AsaiyaBan", "AsaiyaKick"]
            has_mod = any(role.name in MOD_ROLES for role in ctx.author.roles) \
                      if isinstance(ctx.author, discord.Member) else False

            if has_mod:
                # Full help pages for staff (filtered for owner-only if not owner server)
                if is_owner_server:
                    # Owner server - show everything including key system
                    help_pages = [
                        (
                            "**📋 Asaiya - General & Music (Page 1/8)**\n\n"
                            "**🔧 General**\n"
                            "`!help` - Shows this menu\n"
                            "`!botfor` - Shows detailed feature guide (AsaiyaBot role required)\n"
                            "`!ping` - Check bot latency\n"
                            "`!serverinfo` - Show server info\n"
                            "`!uptime` - Check bot uptime\n"
                            "`!avatar [@user]` - Get user avatar\n"
                            "`!say <message>` - Bot says message\n"
                            "`!hello` - Bot introduction\n"
                            "`!afk [reason]` - Set AFK status\n"
                            "`!timer` - Start an interactive countdown timer (sent via DM)\n"
                            "`!warnings [@user]` - Check warnings\n"
                            "`!snipe` - Show last deleted message\n"
                            "`!snipelist [count]` - Show deleted messages\n"
                            "`!asaiya` - Easter egg - info about Asaiya\n"
                            "`!showrole` - Show role hierarchy (AsaiyaBot role required)\n\n"
                            "**🎵 Music**\n"
                            "`!play [link]` - Play music (in #asaiya-hub)\n"
                            "`!stop` - Remove your song from queue\n"
                            "`!queue` - Show queue\n"
                            "`!nowplaying` - Current song\n"
                            "`!leave` - Leave voice channel\n"
                            "`!stopall` - Stop all music (staff only)\n"
                            "`!music` - Show music commands\n\n"
                            "**Support:** https://discord.gg/UqqeejzCgs"
                        ),
                        (
                            "**📋 Asaiya - Setup & Moderation (Page 2/8)**\n\n"
                            "**🔧 Setup**\n"
                            "`!setserver` - Interactive server setup wizard\n"
                            "`!setlog [#channel]` - Set log channel\n"
                            "`!setwelcome #channel` - Set welcome channel\n"
                            "`!setleave #channel` - Set leave channel\n"
                            "`!mlog [#channel]` - Set message log channel\n"
                            "`!onmlog` - Enable message logging\n"
                            "`!offmlog` - Disable message logging\n"
                            "`!imageonly` - The bot will delete any messages sent if not image/video\n"
                            "`!role @user RoleName` - Assign a role\n"
                            "`!filter add/remove <word>` - Manage word filter\n"
                            "`!addfilter <word>` - Add word to filter\n"
                            "`!removefilter <word>` - Remove word from filter\n"
                            "`!listfilters` - Show all filtered words\n"
                            "`!clearfilters` - Clear all filtered words\n"
                            "`!permset @role` - Set channel permissions\n"
                            "`!modsetup` - Run moderation setup wizard\n"
                            "`!modstatus` - Show current moderation settings\n"
                            "`!staffroles` - View/add/remove staff immunity roles\n\n"
                            "**⚔️ Moderation**\n"
                            "`!timeout @user mins [reason]` - Timeout user\n"
                            "`!untimeout @user` - Remove timeout\n"
                            "`!kick @user [reason]` - Kick member\n"
                            "`!ban @user [reason]` - Ban member\n"
                            "`!unban <userID>` - Unban user\n"
                            "`!warn @user <reason>` - Warn member\n"
                            "`!slowmode <seconds>` - Set slowmode\n"
                            "`!clear [amount]` - Clear messages\n"
                            "`!lock [#channel]` - Lock channel\n"
                            "`!unlock [#channel]` - Unlock channel\n"
                            "`!slock` - Lock all channels\n"
                            "`!sunlock` - Unlock all channels\n\n"
                            "**Support:** https://discord.gg/UqqeejzCgs"
                        ),
                        (
                            "**📋 Asaiya - Protection & Tickets (Page 3/8)**\n\n"
                            "**🛡️ Protection**\n"
                            "`!sprotect` - Protect all channels\n"
                            "`!fprotect #channel` - Full protection (channel + messages)\n"
                            "`!protect #channel` - Channel protection only\n"
                            "`!mprotect #channel` - Message protection only\n"
                            "`!unprotect #channel` - Remove protection\n"
                            "`!protected` - List protected channels\n"
                            "`!recover [#name/all]` - Recover deleted channels\n"
                            "`!restore #channel [limit]` - Restore messages\n"
                            "`!cleanbackups [days]` - Clean old message backups\n"
                            "`!filteron` - Enable word filter\n"
                            "`!filteroff` - Disable word filter\n"
                            "`!inviteon` - Enable invite link protection\n"
                            "`!inviteoff` - Disable invite link protection\n\n"
                            "**🎫 Tickets**\n"
                            "`!ticket` - Create ticket panel\n"
                            "`!close` - Close ticket (in ticket channel)\n"
                            "`!rename <name>` - Rename ticket channel\n"
                            "`!transfer` - Transfer to another support\n"
                            "`!ticketadd <name>` - Add user to ticket\n"
                            "`!remove @user` - Remove user from ticket\n"
                            "`!tickethelp` - Show ticket commands\n"
                            "`!ratingstats` - Show anonymous rating stats\n"
                            "`!ratingdetail [@support]` - Show detailed ratings\n\n"
                            "**Support:** https://discord.gg/UqqeejzCgs"
                        ),
                        (
                            "**📋 Asaiya - Giveaways, Reaction Roles & Anti-Raid (Page 4/8)**\n\n"
                            "**🎉 Giveaways**\n"
                            "`!ga [item] [amount] [time]` - Quick giveaway\n"
                            "`!ga start` - Interactive giveaway setup\n"
                            "`!ga end [msg_id]` - End giveaway early\n"
                            "`!ga re [msg_id]` - Reroll winner\n"
                            "`!ga list` - List active giveaways\n\n"
                            "**🎭 Reaction Roles**\n"
                            "`!rrole` - Start reaction role setup (multiple roles)\n"
                            "`!onerole` - Start one-role-only setup\n"
                            "`!rrole create #channel 'title'` - Quick create\n"
                            "`!rrole add <msg_id> :emoji: @role` - Add to existing\n"
                            "`!rrole remove <msg_id> :emoji:` - Remove from existing\n"
                            "`!rrole list` - List all reaction roles\n"
                            "`!rrole delete <msg_id>` - Delete reaction role\n"
                            "`!rrole show <msg_id>` - Show reaction role details\n"
                            "`!rrole publish [msg_id]` - Publish saved setup\n\n"
                            "**🛡️ Anti-Raid**\n"
                            "`!raidstatus` - Check join rate and raid status\n"
                            "`!raidhistory [minutes]` - Show join history\n"
                            "`!raidclear` - Clear join history\n"
                            "`!resetviolations @user` - Reset user's violation count\n"
                            "`!hackon` - Enable hacked account detection\n"
                            "`!hackoff` - Disable hacked account detection\n"
                            "`!startspam` - Enable spam detection\n"
                            "`!stopspam` - Disable spam detection\n"
                            "`!startraid` - Enable raid detection\n"
                            "`!stopraid` - Disable raid detection\n"
                            "`!antiraidstatus` - Show all anti-raid settings\n\n"
                            "**Support:** https://discord.gg/UqqeejzCgs"
                        ),
                        (
                            "**📋 Asaiya - Verification, Leveling & ID System (Page 5/8)**\n\n"
                            "**🔐 Verification**\n"
                            "`!setverify @role` - Set verification role\n"
                            "`!startverify` - Enable verification system\n"
                            "`!stopverify` - Disable verification system\n"
                            "`!fixverify` - Hide verify channel from verified users\n"
                            "`!verifyall` - Send verification DMs to all (owner server)\n\n"
                            "**🆔 ID System**\n"
                            "`!id @user` - View user's ID profile\n"
                            "`!id server` - View server profile\n"
                            "`!id channel` - View channel profile\n"
                            "`!gid @user` - View global profile\n"
                            "`!idset users` - DM all users without profiles\n"
                            "`!idset server` - Set up server profile\n"
                            "`!idset channel` - Set up channel profile\n"
                            "`!idhelp` - Show ID system commands\n\n"
                            "**📊 Leveling**\n"
                            "`!rank [@user]` - Check your rank\n"
                            "`!leaderboard [limit]` - Show server leaderboard\n"
                            "`!reborn` - Reborn at max level\n"
                            "`!lvlhelp` - Show all leveling commands\n"
                            "`!expchannel` - Set announcement channel\n"
                            "`!setbasexp <amount>` - Set base XP per message\n"
                            "`!expsettings` - Show current settings\n"
                            "`!addlevel @user <amount>` - Add levels\n"
                            "`!addre @user <amount>` - Add reborn counts\n"
                            "`!addxp @user <amount>` - Add raw XP\n"
                            "`!setlevel @user <level>` - Set user's level\n"
                            "`!rebornreset @user` - Reset reborn count\n"
                            "`!levelrole add <level> @role` - Add level role reward\n"
                            "`!levelrole remove <level>` - Remove level role reward\n"
                            "`!noexp @user` - Block user from gaining XP\n"
                            "`!onexp @user` - Allow user to gain XP again\n\n"
                            "**Support:** https://discord.gg/UqqeejzCgs"
                        ),
                        (
                            "**📋 Asaiya - Backup, Status & Utility (Page 6/8)**\n\n"
                            "**💾 Backup**\n"
                            "`!sserver [password]` - Backup server structure\n"
                            "`!remake [password]` - Restore from backup\n"
                            "`!backups` - Check your backup\n"
                            "`!delbackup [password]` - Delete your backup\n"
                            "`!backupstats` - Show backup statistics\n"
                            "`!cleanoldbackups [days]` - Clean old server backups\n\n"
                            "**👁️ Status Tracker**\n"
                            "`!track #channel [@role]` - Start live status tracking\n"
                            "`!untrack` - Stop status tracking\n"
                            "`!checkstatus [@user]` - Check member status\n"
                            "`!checkdict @user` - Dictionary check (admin)\n"
                            "`!resetstatus @user` - Reset tracking data\n\n"
                            "**🖼️ Image-Only Mode**\n"
                            "`!imageonly [#channel]` - Set channel to images/videos only\n"
                            "`!imageonly-remove [#channel]` - Remove restriction\n"
                            "`!imageonly-list` - List image-only channels\n\n"
                            "**🔄 Repeat Messages**\n"
                            "`!repeat <message>` - Keep message at bottom of channel\n"
                            "`!repeatstop [#channel]` - Stop repeating message\n\n"
                            "**📅 Events**\n"
                            "`!event create [title] [@role]` - Create event\n"
                            "`!event end [msg_id]` - End event early\n"
                            "`!event list` - List active events\n\n"
                            "**Support:** https://discord.gg/UqqeejzCgs"
                        ),
                        (
                            "**📋 Asaiya - Key System (Page 7/8)**\n\n"
                            "**🔑 Key System**\n"
                            "`!botkey [key]` - Activate server\n"
                            "`!ckey [key]` - Create single-use key (owner only)\n"
                            "`!cmkey [key]` - Create master key (owner only)\n"
                            "`!ctkey [key] [time]` - Create timed key (owner only)\n"
                            "`!cmultikey [key] [uses]` - Create multi-use key (owner only)\n"
                            "`!cdelkey [key]` - Delete key (owner only)\n"
                            "`!cbotkey [key]` - Force reactivate key (owner only)\n"
                            "`!skey` - View all keys (owner only)\n"
                            "`!helpkey` - Show key system help\n\n"
                            "**Support:** https://discord.gg/UqqeejzCgs"
                        ),
                        (
                            "**📋 Asaiya - Admin & Cross-Server (Page 8/8)**\n\n"
                            "**👑 Admin**\n"
                            "`!nuke` - Nuke server (requires approval)\n"
                            "`!cmdtest` - Comprehensive health check\n"
                            "`!fullcmdtest` - ⚠️ DANGEROUS: Test all commands\n"
                            "`!showservers` - List all servers with invites (owner only)\n\n"
                            "**🌐 Cross-Server**\n"
                            "`!botservers` - List all servers (owner only)\n"
                            "`!talkcross [link] [msg]` - Send message to another server\n"
                            "`!talkcrosslist` - Interactive server selector\n"
                            "`!talkdm [user_id] [msg]` - Send DM to user\n\n"
                            f"**Note:** Most commands work in #{BOT_CHANNEL_NAME}\n"
                            "**Support:** https://discord.gg/UqqeejzCgs"
                        ),
                    ]
                else:
                    # Regular server - hide owner-only commands
                    help_pages = [
                        (
                            "**📋 Asaiya - General & Music (Page 1/7)**\n\n"
                            "**🔧 General**\n"
                            "`!help` - Shows this menu\n"
                            "`!botfor` - Shows detailed feature guide (AsaiyaBot role required)\n"
                            "`!ping` - Check bot latency\n"
                            "`!serverinfo` - Show server info\n"
                            "`!uptime` - Check bot uptime\n"
                            "`!avatar [@user]` - Get user avatar\n"
                            "`!say <message>` - Bot says message\n"
                            "`!hello` - Bot introduction\n"
                            "`!afk [reason]` - Set AFK status\n"
                            "`!timer` - Start an interactive countdown timer (sent via DM)\n"
                            "`!warnings [@user]` - Check warnings\n"
                            "`!snipe` - Show last deleted message\n"
                            "`!snipelist [count]` - Show deleted messages\n"
                            "`!asaiya` - Easter egg - info about Asaiya\n"
                            "`!showrole` - Show role hierarchy (AsaiyaBot role required)\n\n"
                            "**🎵 Music**\n"
                            "`!play [link]` - Play music (in #asaiya-hub)\n"
                            "`!stop` - Remove your song from queue\n"
                            "`!queue` - Show queue\n"
                            "`!nowplaying` - Current song\n"
                            "`!leave` - Leave voice channel\n"
                            "`!stopall` - Stop all music (staff only)\n"
                            "`!music` - Show music commands"
                        ),
                        (
                            "**📋 Asaiya - Setup & Moderation (Page 2/7)**\n\n"
                            "**🔧 Setup**\n"
                            "`!setserver` - Interactive server setup wizard\n"
                            "`!setlog [#channel]` - Set log channel\n"
                            "`!setwelcome #channel` - Set welcome channel\n"
                            "`!setleave #channel` - Set leave channel\n"
                            "`!mlog [#channel]` - Set message log channel\n"
                            "`!onmlog` - Enable message logging\n"
                            "`!offmlog` - Disable message logging\n"
                            "`!imageonly` - The bot will delete any messages sent if not image/video\n"
                            "`!role @user RoleName` - Assign a role\n"
                            "`!filter add/remove <word>` - Manage word filter\n"
                            "`!addfilter <word>` - Add word to filter\n"
                            "`!removefilter <word>` - Remove word from filter\n"
                            "`!listfilters` - Show all filtered words\n"
                            "`!clearfilters` - Clear all filtered words\n"
                            "`!permset @role` - Set channel permissions\n"
                            "`!modsetup` - Run moderation setup wizard\n"
                            "`!modstatus` - Show current moderation settings\n"
                            "`!staffroles` - View/add/remove staff immunity roles\n\n"
                            "**⚔️ Moderation**\n"
                            "`!timeout @user mins [reason]` - Timeout user\n"
                            "`!untimeout @user` - Remove timeout\n"
                            "`!kick @user [reason]` - Kick member\n"
                            "`!ban @user [reason]` - Ban member\n"
                            "`!unban <userID>` - Unban user\n"
                            "`!warn @user <reason>` - Warn member\n"
                            "`!slowmode <seconds>` - Set slowmode\n"
                            "`!clear [amount]` - Clear messages\n"
                            "`!lock [#channel]` - Lock channel\n"
                            "`!unlock [#channel]` - Unlock channel\n"
                            "`!slock` - Lock all channels\n"
                            "`!sunlock` - Unlock all channels"
                        ),
                        (
                            "**📋 Asaiya - Protection & Tickets (Page 3/7)**\n\n"
                            "**🛡️ Protection**\n"
                            "`!sprotect` - Protect all channels\n"
                            "`!fprotect #channel` - Full protection (channel + messages)\n"
                            "`!protect #channel` - Channel protection only\n"
                            "`!mprotect #channel` - Message protection only\n"
                            "`!unprotect #channel` - Remove protection\n"
                            "`!protected` - List protected channels\n"
                            "`!recover [#name/all]` - Recover deleted channels\n"
                            "`!restore #channel [limit]` - Restore messages\n"
                            "`!cleanbackups [days]` - Clean old message backups\n"
                            "`!filteron` - Enable word filter\n"
                            "`!filteroff` - Disable word filter\n"
                            "`!inviteon` - Enable invite link protection\n"
                            "`!inviteoff` - Disable invite link protection\n\n"
                            "**🎫 Tickets**\n"
                            "`!ticket` - Create ticket panel\n"
                            "`!close` - Close ticket (in ticket channel)\n"
                            "`!rename <name>` - Rename ticket channel\n"
                            "`!transfer` - Transfer to another support\n"
                            "`!ticketadd <name>` - Add user to ticket\n"
                            "`!remove @user` - Remove user from ticket\n"
                            "`!tickethelp` - Show ticket commands\n"
                            "`!ratingstats` - Show anonymous rating stats\n"
                            "`!ratingdetail [@support]` - Show detailed ratings"
                        ),
                        (
                            "**📋 Asaiya - Giveaways, Reaction Roles & Anti-Raid (Page 4/7)**\n\n"
                            "**🎉 Giveaways**\n"
                            "`!ga [item] [amount] [time]` - Quick giveaway\n"
                            "`!ga start` - Interactive giveaway setup\n"
                            "`!ga end [msg_id]` - End giveaway early\n"
                            "`!ga re [msg_id]` - Reroll winner\n"
                            "`!ga list` - List active giveaways\n\n"
                            "**🎭 Reaction Roles**\n"
                            "`!rrole` - Start reaction role setup (multiple roles)\n"
                            "`!onerole` - Start one-role-only setup\n"
                            "`!rrole create #channel 'title'` - Quick create\n"
                            "`!rrole add <msg_id> :emoji: @role` - Add to existing\n"
                            "`!rrole remove <msg_id> :emoji:` - Remove from existing\n"
                            "`!rrole list` - List all reaction roles\n"
                            "`!rrole delete <msg_id>` - Delete reaction role\n"
                            "`!rrole show <msg_id>` - Show reaction role details\n"
                            "`!rrole publish [msg_id]` - Publish saved setup\n\n"
                            "**🛡️ Anti-Raid**\n"
                            "`!raidstatus` - Check join rate and raid status\n"
                            "`!raidhistory [minutes]` - Show join history\n"
                            "`!raidclear` - Clear join history\n"
                            "`!resetviolations @user` - Reset user's violation count\n"
                            "`!hackon` - Enable hacked account detection\n"
                            "`!hackoff` - Disable hacked account detection\n"
                            "`!startspam` - Enable spam detection\n"
                            "`!stopspam` - Disable spam detection\n"
                            "`!startraid` - Enable raid detection\n"
                            "`!stopraid` - Disable raid detection\n"
                            "`!antiraidstatus` - Show all anti-raid settings"
                        ),
                        (
                            "**📋 Asaiya - Verification, Leveling & ID System (Page 5/7)**\n\n"
                            "**🔐 Verification**\n"
                            "`!setverify @role` - Set verification role\n"
                            "`!startverify` - Enable verification system\n"
                            "`!stopverify` - Disable verification system\n"
                            "`!fixverify` - Hide verify channel from verified users\n"
                            "`!verifyall` - Send verification DMs to all (owner server)\n\n"
                            "**🆔 ID System**\n"
                            "`!id @user` - View user's ID profile\n"
                            "`!id server` - View server profile\n"
                            "`!id channel` - View channel profile\n"
                            "`!gid @user` - View global profile\n"
                            "`!idset users` - DM all users without profiles\n"
                            "`!idset server` - Set up server profile\n"
                            "`!idset channel` - Set up channel profile\n"
                            "`!idhelp` - Show ID system commands\n\n"
                            "**📊 Leveling**\n"
                            "`!rank [@user]` - Check your rank\n"
                            "`!leaderboard [limit]` - Show server leaderboard\n"
                            "`!reborn` - Reborn at max level\n"
                            "`!lvlhelp` - Show all leveling commands\n"
                            "`!expchannel` - Set announcement channel\n"
                            "`!setbasexp <amount>` - Set base XP per message\n"
                            "`!expsettings` - Show current settings\n"
                            "`!addlevel @user <amount>` - Add levels\n"
                            "`!addre @user <amount>` - Add reborn counts\n"
                            "`!addxp @user <amount>` - Add raw XP\n"
                            "`!setlevel @user <level>` - Set user's level\n"
                            "`!rebornreset @user` - Reset reborn count\n"
                            "`!levelrole add <level> @role` - Add level role reward\n"
                            "`!levelrole remove <level>` - Remove level role reward\n"
                            "`!noexp @user` - Block user from gaining XP\n"
                            "`!onexp @user` - Allow user to gain XP again"
                        ),
                        (
                            "**📋 Asaiya - Backup, Status & Utility (Page 6/7)**\n\n"
                            "**💾 Backup**\n"
                            "`!sserver [password]` - Backup server structure\n"
                            "`!remake [password]` - Restore from backup\n"
                            "`!backups` - Check your backup\n"
                            "`!delbackup [password]` - Delete your backup\n"
                            "`!backupstats` - Show backup statistics\n"
                            "`!cleanoldbackups [days]` - Clean old server backups\n\n"
                            "**👁️ Status Tracker**\n"
                            "`!track #channel [@role]` - Start live status tracking\n"
                            "`!untrack` - Stop status tracking\n"
                            "`!checkstatus [@user]` - Check member status\n"
                            "`!checkdict @user` - Dictionary check (admin)\n"
                            "`!resetstatus @user` - Reset tracking data\n\n"
                            "**🖼️ Image-Only Mode**\n"
                            "`!imageonly [#channel]` - Set channel to images/videos only\n"
                            "`!imageonly-remove [#channel]` - Remove restriction\n"
                            "`!imageonly-list` - List image-only channels\n\n"
                            "**🔄 Repeat Messages**\n"
                            "`!repeat <message>` - Keep message at bottom of channel\n"
                            "`!repeatstop [#channel]` - Stop repeating message\n\n"
                            "**📅 Events**\n"
                            "`!event create [title] [@role]` - Create event\n"
                            "`!event end [msg_id]` - End event early\n"
                            "`!event list` - List active events"
                        ),
                        (
                            "**📋 Asaiya - Admin & Cross-Server (Page 7/7)**\n\n"
                            "**👑 Admin**\n"
                            "`!nuke` - Nuke server (requires approval)\n"
                            "`!cmdtest` - Comprehensive health check\n"
                            "`!fullcmdtest` - ⚠️ DANGEROUS: Test all commands\n\n"
                            "**🌐 Cross-Server**\n"
                            "`!talkcross [link] [msg]` - Send message to another server\n"
                            "`!talkcrosslist` - Interactive server selector\n"
                            "`!talkdm [user_id] [msg]` - Send DM to user\n\n"
                            f"**Note:** Most commands work in #{BOT_CHANNEL_NAME}\n"
                            "**Support:** https://discord.gg/UqqeejzCgs"
                        ),
                    ]
            else:
                # Limited help for regular users
                help_pages = [(
                    "**📋 Asaiya - Available Commands**\n\n"
                    "`!help` - Shows this message\n"
                    "`!botfor` - Shows detailed feature guide (AsaiyaBot role required)\n"
                    "`!ping` - Check bot latency\n"
                    "`!serverinfo` - Show server info\n"
                    "`!uptime` - Check bot uptime\n"
                    "`!avatar [@user]` - Get user avatar\n"
                    "`!afk [reason]` - Set AFK status\n"
                    "`!warnings [@user]` - Check warnings\n"
                    "`!snipe` - Show last deleted message\n"
                    "`!snipelist [count]` - Show deleted messages\n"
                    "`!asaiya` - Easter egg\n"
                    "`!timer` - Start an interactive countdown timer (sent via DM)\n\n"
                    "**🎵 Music**\n"
                    "`!play [link]` - Play music\n"
                    "`!stop` - Stop music\n"
                    "`!queue` - Show music queue\n"
                    "`!nowplaying` - Show current song\n"
                    "`!leave` - Leave voice channel\n\n"
                    "**🔐 Verification**\n"
                    "`!verify [code]` - Submit verification code\n"
                    "`!getcode` - Get new verification code\n\n"
                    "**📊 Leveling**\n"
                    "`!rank [@user]` - Check your rank\n"
                    "`!leaderboard [limit]` - Show leaderboard\n"
                    "`!lvlhelp` - Show leveling commands\n\n"
                    f"**Note:** Most commands must be used in #{BOT_CHANNEL_NAME}\n"
                    "**Support:** https://discord.gg/UqqeejzCgs"
                )]

        try:
            for i, page in enumerate(help_pages, 1):
                embed = discord.Embed(
                    description=page,
                    color=discord.Color.blue()
                )
                if len(help_pages) > 1:
                    embed.set_footer(text=f"Page {i}/{len(help_pages)} • Use !botfor for detailed feature guide")
                else:
                    embed.set_footer(text="Use !botfor for detailed feature guide")
                await ctx.author.send(embed=embed)
                await asyncio.sleep(0.5)

            if len(help_pages) > 1:
                await ctx.send(f"📬 I've sent you {len(help_pages)} DMs with the full command list!")
            else:
                await ctx.send("📬 I've sent you a DM with the command list!")

        except discord.Forbidden:
            await ctx.send("❌ I couldn't DM you. Please enable DMs and try again.")

    # ===== MLOG COMMAND =====
    @commands.command(name='mlog')
    @commands.has_permissions(administrator=True)
    async def mlog(self, ctx, channel: discord.TextChannel = None):
        """Set the message log channel. Creates #message-logger if no channel given."""
        if await self.check_duplicate(ctx):
            return

        # Check if server is activated (has database)
        conn = self.get_cached_connection(ctx.guild.id)
        if not conn:
            # Try to create server database if not exists
            try:
                db_path = self.get_server_db_path(ctx.guild.id)
                if not db_path:
                    # Need to activate server first
                    embed = discord.Embed(
                        title="🔐 Server Not Activated",
                        description="This server needs to be activated before using `!mlog`.\n\n"
                                    "Please use `!botkey [your-key]` first to activate the bot.\n"
                                    "If you don't have a key, contact the bot owner.",
                        color=discord.Color.red()
                    )
                    await ctx.send(embed=embed)
                    return
            except:
                await ctx.send("❌ Server not activated. Please use `!botkey` first.")
                return

        if channel is None:
            channel = discord.utils.get(ctx.guild.text_channels, name="message-logger")
            if not channel:
                try:
                    channel = await ctx.guild.create_text_channel(
                        "message-logger",
                        reason="Message log channel created by bot"
                    )
                    await ctx.send(f"✅ Created #message-logger channel. This channel is currently public, please make it private.")
                except Exception as e:
                    await ctx.send(f"❌ Failed to create channel: {str(e)}")
                    return

        # Get connection and save
        conn = self.get_cached_connection(ctx.guild.id)
        if not conn:
            await ctx.send("❌ Could not connect to database. Server may not be activated.")
            return

        c = conn.cursor()
        # Add mlog_channel_id column if it doesn't exist
        try:
            c.execute("ALTER TABLE log_channels ADD COLUMN mlog_channel_id TEXT")
            conn.commit()
        except:
            pass

        c.execute("SELECT log_channel_id FROM log_channels")
        existing = c.fetchone()
        if existing:
            c.execute("UPDATE log_channels SET mlog_channel_id = ?", (str(channel.id),))
        else:
            c.execute("INSERT INTO log_channels (mlog_channel_id) VALUES (?)", (str(channel.id),))
        conn.commit()
        
        # Enable mlog by default when setting channel
        self.save_mlog_setting(ctx.guild.id, True)
        
        await ctx.send(f"✅ Message log channel set to {channel.mention}\n"
                       f"   Message logging is now **ENABLED**. Use `!offmlog` to disable.")

    @commands.command(name='onmlog')
    @commands.has_permissions(administrator=True)
    async def onmlog(self, ctx):
        """Enable message logging for this server"""
        if await self.check_duplicate(ctx):
            return
        
        if self.save_mlog_setting(ctx.guild.id, True):
            await ctx.send("✅ **Message logging ENABLED**\n"
                           f"   Deleted and edited messages will be logged to the message-logger channel.")
        else:
            await ctx.send("❌ Failed to enable message logging.")

    @commands.command(name='offmlog')
    @commands.has_permissions(administrator=True)
    async def offmlog(self, ctx):
        """Disable message logging for this server"""
        if await self.check_duplicate(ctx):
            return
        
        if self.save_mlog_setting(ctx.guild.id, False):
            await ctx.send("🔇 **Message logging DISABLED**\n"
                           f"   Deleted and edited messages will no longer be logged.")
        else:
            await ctx.send("❌ Failed to disable message logging.")

    # ===== CMDTEST COMMAND =====
    @commands.command(name='cmdtest')
    @commands.has_permissions(administrator=True)
    async def cmdtest(self, ctx):
        """Comprehensive health check for EVERY bot command. Nothing actually happens."""
        if await self.check_duplicate(ctx):
            return

        results = []

        def check(name, passed, note=""):
            icon = "✅" if passed else "❌"
            line = f"{icon} `!{name}`"
            if note:
                line += f" — {note}"
            results.append((passed, line))

        guild = ctx.guild
        member = ctx.author
        bot_member = guild.get_member(self.bot.user.id)

        perms = bot_member.guild_permissions
        check("setserver / role [Manage Roles]", perms.manage_roles, "✔ granted" if perms.manage_roles else "MISSING")
        check("setserver / setlog [Manage Channels]", perms.manage_channels, "✔ granted" if perms.manage_channels else "MISSING")
        check("kick", perms.kick_members, "✔ granted" if perms.kick_members else "MISSING")
        check("ban / unban", perms.ban_members, "✔ granted" if perms.ban_members else "MISSING")
        check("timeout / untimeout", perms.moderate_members, "✔ granted" if perms.moderate_members else "MISSING")
        check("clear", perms.manage_messages, "✔ granted" if perms.manage_messages else "MISSING")
        check("slowmode", perms.manage_channels, "✔ granted" if perms.manage_channels else "MISSING")
        check("play [Connect voice]", perms.connect, "✔ granted" if perms.connect else "MISSING")
        check("play [Speak voice]", perms.speak, "✔ granted" if perms.speak else "MISSING")
        check("say / snipe [Read Messages]", perms.read_messages, "✔ granted" if perms.read_messages else "MISSING")
        check("say / clear [Send Messages]", perms.send_messages, "✔ granted" if perms.send_messages else "MISSING")
        check("add_reactions", perms.add_reactions, "✔ granted" if perms.add_reactions else "MISSING")
        check("embed_links", perms.embed_links, "✔ granted" if perms.embed_links else "MISSING")
        check("attach_files", perms.attach_files, "✔ granted" if perms.attach_files else "MISSING")
        check("read_message_history", perms.read_message_history, "✔ granted" if perms.read_message_history else "MISSING")

        db_ok = False
        try:
            conn = self.get_cached_connection(ctx.guild.id)
            if conn:
                conn.execute("SELECT 1")
                check("database", True, f"connected to server database")
                db_ok = True
            else:
                check("database", False, f"CANNOT CONNECT")
        except Exception as e:
            check("database", False, f"CANNOT CONNECT: {e}")

        check("hello", True, "command registered — requires AsaiyaBot role")
        check("setserver", perms.manage_roles and perms.manage_channels, "ready" if (perms.manage_roles and perms.manage_channels) else "missing")

        if db_ok:
            conn = self.get_cached_connection(ctx.guild.id)
            c = conn.cursor()
            c.execute("SELECT log_channel_id, welcome_channel_id, leave_channel_id FROM log_channels")
            ch_row = c.fetchone()
            log_ch = guild.get_channel(int(ch_row[0])) if ch_row and ch_row[0] else None
            wel_ch = guild.get_channel(int(ch_row[1])) if ch_row and ch_row[1] else None
            lea_ch = guild.get_channel(int(ch_row[2])) if ch_row and ch_row[2] else None
            check("setlog", log_ch is not None, f"→ #{log_ch.name}" if log_ch else "not set")
            check("setwelcome", wel_ch is not None, f"→ #{wel_ch.name}" if wel_ch else "not set")
            check("setleave", lea_ch is not None, f"→ #{lea_ch.name}" if lea_ch else "not set")
        else:
            check("setlog", False, "skipped — database unreachable")

        bot_ch = discord.utils.get(guild.text_channels, name=BOT_CHANNEL_NAME)
        music_ch = discord.utils.get(guild.text_channels, name="asaiya-hub")
        verify_ch = discord.utils.get(guild.text_channels, name="asaiya-verification")
        hub_ch = discord.utils.get(guild.text_channels, name="asaiya-hub")
        log_channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
        
        check(f"bot channel (#{BOT_CHANNEL_NAME})", bot_ch is not None, f"found" if bot_ch else "MISSING")
        check(f"music channel (#asaiya-hub)", music_ch is not None, f"found" if music_ch else "MISSING")
        check(f"verification channel (#asaiya-verification)", verify_ch is not None, f"found" if verify_ch else "MISSING")
        check(f"hub channel (#asaiya-hub)", hub_ch is not None, f"found" if hub_ch else "MISSING")
        check(f"log channel (#{LOG_CHANNEL_NAME})", log_channel is not None, f"found" if log_channel else "MISSING")

        for rname in [BOT_ROLE, "AsaiyaBan", "AsaiyaKick", "AsaiyaPass", "AsaiyaClear", "asaiya-support", "asaiya-request"]:
            r = discord.utils.get(guild.roles, name=rname)
            check(f"role:{rname}", r is not None, "exists" if r else "MISSING")

        if db_ok:
            try:
                conn = self.get_cached_connection(ctx.guild.id)
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM filter_words")
                fcount = c.fetchone()[0]
                check("addfilter / removefilter / listfilters / clearfilters", True, f"{fcount} word(s) in filter")
            except Exception as e:
                check("addfilter / removefilter / listfilters / clearfilters", False, str(e))
        else:
            check("addfilter / removefilter / listfilters / clearfilters", False, "skipped")

        check("say", perms.send_messages and perms.manage_messages,
              "can send and delete messages" if (perms.send_messages and perms.manage_messages) else "MISSING")

        total_sniped = sum(len(v) for v in self.bot.snipe_cache.values()) if hasattr(self.bot, 'snipe_cache') else 0
        check("snipe", True, f"{total_sniped} deleted message(s) in cache")
        check("snipelist", True, f"shows up to {SNIPE_LIMIT} recent deleted messages")

        check("timeout", perms.moderate_members, "ready" if perms.moderate_members else "MISSING")
        check("untimeout", perms.moderate_members, "ready" if perms.moderate_members else "MISSING")
        check("kick", perms.kick_members, "ready" if perms.kick_members else "MISSING")
        check("ban", perms.ban_members, "ready" if perms.ban_members else "MISSING")
        check("unban", perms.ban_members, "ready" if perms.ban_members else "MISSING")
        check("lock", perms.manage_channels, "ready" if perms.manage_channels else "MISSING")
        check("unlock", perms.manage_channels, "ready" if perms.manage_channels else "MISSING")
        check("slock", perms.manage_channels, "ready" if perms.manage_channels else "MISSING")
        check("sunlock", perms.manage_channels, "ready" if perms.manage_channels else "MISSING")

        if db_ok:
            try:
                conn = self.get_cached_connection(ctx.guild.id)
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM warnings")
                wcount = c.fetchone()[0]
                check("warn", True, f"{wcount} warning(s) logged")
                check("warnings", True, f"{wcount} warning(s) logged")
            except Exception as e:
                check("warn", False, str(e))
                check("warnings", False, str(e))
        else:
            check("warn", False, "skipped")
            check("warnings", False, "skipped")

        check("slowmode", perms.manage_channels, "ready" if perms.manage_channels else "MISSING")
        check("clear", perms.manage_messages, "ready" if perms.manage_messages else "MISSING")

        anti_raid_cog = self.bot.get_cog('AntiRaid')
        if anti_raid_cog:
            check("raidstatus", True, "anti-raid cog loaded")
            check("raidhistory", True, "anti-raid cog loaded")
            check("raidclear", True, "anti-raid cog loaded")
            check("resetviolations", True, "anti-raid cog loaded")
            check("hackon/off", True, "anti-raid cog loaded")
            check("startspam/stopspam", True, "anti-raid cog loaded")
            check("startraid/stopraid", True, "anti-raid cog loaded")
            check("antiraidstatus", True, "anti-raid cog loaded")
        else:
            check("raidstatus", False, "anti-raid cog NOT loaded")

        check("staffroles", True, "manage staff immunity roles")
        check("modsetup", True, "run moderation setup wizard")
        check("modstatus", True, "show current moderation settings")

        check("ping", True, f"current latency: {round(self.bot.latency * 1000)}ms")
        check("serverinfo", True, f"{guild.member_count} members")
        check("avatar", True, "fetches member avatars")
        check("uptime", True, f"bot has been up for {int(time.time() - self.bot_start_time)}s")
        check("asaiya", True, "shows info about Asaiya")
        check("showrole", True, "shows role hierarchy — requires AsaiyaBot role")
        check("botfor", True, "shows detailed feature guide — requires AsaiyaBot role")
        check("help", True, "sends DM")
        check("mlog", True, "set message log channel")
        check("onmlog/offmlog", True, "toggle message logging")

        if db_ok:
            try:
                main_conn = sqlite3.connect(MAIN_DB_PATH)
                main_c = main_conn.cursor()
                main_c.execute(
                    "SELECT COUNT(*) FROM timer_sessions ts JOIN timers t ON t.session_id = ts.session_id "
                    "WHERE ts.user_id = ? AND t.status IN ('running','paused','queued')",
                    (str(member.id),)
                )
                timer_count = main_c.fetchone()[0]
                main_conn.close()
                check("timer", True, f"{timer_count} active timer(s)")
            except Exception as e:
                check("timer", False, str(e))

            try:
                conn = self.get_cached_connection(ctx.guild.id)
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM afk")
                acount = c.fetchone()[0]
                check("afk", True, f"{acount} member(s) currently AFK")
            except Exception as e:
                check("afk", False, str(e))
        else:
            check("timer", False, "skipped")
            check("afk", False, "skipped")

        check("botkey", True, "activates server with a key")
        check("talkcross", True, "send message to another server")
        check("talkcrosslist", True, "list all servers bot is in")
        check("talkdm", True, "send DM to user")
        check("botservers", True, "list all servers — owner only")
        check("permset", True, "set up channel permissions")
        check("nuke", True, "nuke server (requires approval)")
        check("imageonly", True, "set channel to images/videos only")
        check("imageonly-remove", True, "remove image-only restriction")
        check("imageonly-list", True, "list image-only channels")
        check("repeat", True, "keep message at bottom of channel")
        check("repeatstop", True, "stop repeating message")
        check("music", True, "show music commands")
        check("checkdict", True, "dictionary check (admin)")
        check("resetstatus", True, "reset tracking data")

        try:
            import yt_dlp
            check("play [yt_dlp]", True, "yt_dlp installed")
        except ImportError:
            check("play [yt_dlp]", False, "NOT installed")

        try:
            proc = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=3)
            check("play [ffmpeg]", proc.returncode == 0, "ffmpeg found" if proc.returncode == 0 else "ffmpeg NOT found")
        except:
            check("play [ffmpeg]", False, "NOT found")

        passed = sum(1 for ok, _ in results if ok)
        failed = sum(1 for ok, _ in results if not ok)
        total = len(results)

        chunk_size = 15
        chunks = [results[i:i + chunk_size] for i in range(0, len(results), chunk_size)]
        
        await ctx.send(f"🧪 **Command Health Check**\n**{passed}/{total} checks passed** — {failed} issue(s) found")
        
        for i, chunk in enumerate(chunks, 1):
            embed = discord.Embed(
                title=f"Results (Part {i}/{len(chunks)})",
                color=discord.Color.green() if failed == 0 else discord.Color.orange() if failed <= 3 else discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            chunk_text = "\n".join(line for _, line in chunk)
            embed.description = chunk_text
            
            if i == len(chunks):
                footer = "✅ All systems operational!" if failed == 0 else f"⚠️ Fix the ❌ items above"
                embed.set_footer(text=footer)
            
            await ctx.send(embed=embed)

    # ===== FULLCMDTEST COMMAND =====
    @commands.command(name='fullcmdtest')
    @commands.has_permissions(administrator=True)
    async def fullcmdtest(self, ctx):
        """⚠️ DANGEROUS: Actually runs ALL commands to test them.
        Only works in servers with less than 5 members.
        You must confirm each dangerous command manually.
        """
        if await self.check_duplicate(ctx):
            return
            
        if ctx.guild.member_count >= 5:
            await ctx.send("❌ This command is disabled in servers with 5 or more members for safety reasons.")
            return
            
        await ctx.send(f"⚠️ **ULTRA DANGEROUS COMMAND** ⚠️\n"
                      f"This will actually execute EVERY command in this server.\n"
                      f"Type the server name `{ctx.guild.name}` to continue or anything else to cancel.")
        
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        
        try:
            msg = await self.bot.wait_for('message', timeout=30.0, check=check)
            if msg.content != ctx.guild.name:
                await ctx.send("❌ Test cancelled.")
                return
            try:
                await msg.delete()
            except:
                pass
        except asyncio.TimeoutError:
            await ctx.send("⏰ Timed out. Test cancelled.")
            return
        
        status_msg = await ctx.send("🧪 Running FULL command test... This will take a while.\n"
                                    "You will need to confirm dangerous commands when prompted.")
    
        results = []
        failed_commands = []
        
        async def test_command(command_name, *args, **kwargs):
            try:
                command = self.bot.get_command(command_name)
                if not command:
                    results.append(f"❌ `!{command_name}` - Command not found")
                    failed_commands.append(command_name)
                    return
                
                dangerous_commands = ['nuke', 'slock', 'sunlock', 'sprotect', 'clear', 'kick', 'ban', 'timeout']
                if command_name in dangerous_commands:
                    await ctx.send(f"⚠️ About to run `!{command_name}`. Type `YES` to continue or anything else to skip.")
                    try:
                        confirm = await self.bot.wait_for('message', timeout=30.0, check=check)
                        if confirm.content != "YES":
                            results.append(f"⏭️ `!{command_name}` - Skipped (user cancelled)")
                            return
                    except asyncio.TimeoutError:
                        results.append(f"⏭️ `!{command_name}` - Skipped (timeout)")
                        return
                
                await ctx.invoke(command, *args, **kwargs)
                results.append(f"✅ `!{command_name}` - Executed successfully")
                
            except Exception as e:
                results.append(f"❌ `!{command_name}` - Error: {str(e)[:50]}")
                failed_commands.append(command_name)
        
        # Test all commands
        await test_command("ping")
        await test_command("serverinfo")
        await test_command("uptime")
        await test_command("avatar", ctx.author)
        await test_command("asaiya")
        await test_command("showrole")
        await test_command("afk", reason="Testing")
        await test_command("snipe")
        await test_command("snipelist", 5)
        await test_command("say", "Test message")
        await test_command("hello")
        await test_command("slowmode", 0)
        await test_command("lock", ctx.channel)
        await test_command("unlock", ctx.channel)
        await test_command("slock")
        await test_command("sunlock")
        await test_command("clear", 5)
        await test_command("warn", ctx.author, "Test warning")
        await test_command("warnings", ctx.author)
        await test_command("timeout", ctx.author, 1, "Test timeout")
        await test_command("untimeout", ctx.author)
        await test_command("kick", ctx.author, "Test kick (should fail)")
        await test_command("ban", ctx.author, "Test ban (should fail)")
        await test_command("sprotect")
        await test_command("protect", ctx.channel)
        await test_command("mprotect", ctx.channel)
        await test_command("fprotect", ctx.channel)
        await test_command("protected")
        await test_command("unprotect", ctx.channel)
        await test_command("filteron")
        await test_command("filteroff")
        await test_command("inviteon")
        await test_command("inviteoff")
        await test_command("addfilter", "testword")
        await test_command("listfilters")
        await test_command("removefilter", "testword")
        await test_command("recover")
        await test_command("restore", ctx.channel, 5)
        await test_command("cleanbackups", 1)
        await test_command("rrole")
        await test_command("onerole")
        await test_command("rrole list")
        await test_command("ga")
        await test_command("ga list")
        await test_command("event")
        await test_command("event list")
        await test_command("ticket")
        await test_command("tickethelp")
        await test_command("ratingstats")
        await test_command("ratingdetail", ctx.author)
        await test_command("setverify", ctx.author.top_role or ctx.guild.default_role)
        await test_command("startverify")
        await test_command("stopverify")
        await test_command("fixverify")
        await test_command("backups")
        await test_command("backupstats")
        await test_command("cleanoldbackups", 1)
        await test_command("rank")
        await test_command("leaderboard", 5)
        await test_command("lvlhelp")
        await test_command("levelrole list")
        await test_command("noexp", ctx.author)
        await test_command("onexp", ctx.author)
        await test_command("play", "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        await test_command("stop")
        await test_command("queue")
        await test_command("nowplaying")
        await test_command("leave")
        await test_command("music")
        await test_command("checkstatus", ctx.author)
        await test_command("track", ctx.channel)
        await test_command("untrack")
        await test_command("checkdict", ctx.author)
        await test_command("resetstatus", ctx.author)
        await test_command("imageonly", ctx.channel)
        await test_command("imageonly-list")
        await test_command("imageonly-remove", ctx.channel)
        await test_command("repeat", "Test repeat message")
        await test_command("repeatstop", ctx.channel)
        await test_command("botkey", "test-key-123")
        await test_command("helpkey")
        await test_command("permset", ctx.author.top_role or ctx.guild.default_role)
        await test_command("modsetup")
        await test_command("modstatus")
        await test_command("staffroles")
        await test_command("raidstatus")
        await test_command("raidhistory", 5)
        await test_command("raidclear")
        await test_command("resetviolations", ctx.author)
        await test_command("hackon")
        await test_command("hackoff")
        await test_command("startspam")
        await test_command("stopspam")
        await test_command("startraid")
        await test_command("stopraid")
        await test_command("antiraidstatus")
        await test_command("botservers")
        await test_command("talkcrosslist")
        await test_command("talkdm", ctx.author.id, "Test DM")
        
        await ctx.send("⚠️ **FINAL WARNING**: The next command is `!nuke` which will request to delete EVERYTHING.\n"
                      "Type `NUKE` to test it (it will only send a request, not actually nuke without approval).")
        try:
            confirm = await self.bot.wait_for('message', timeout=30.0, check=check)
            if confirm.content == "NUKE":
                await test_command("nuke")
            else:
                results.append(f"⏭️ `!nuke` - Skipped")
        except asyncio.TimeoutError:
            results.append(f"⏭️ `!nuke` - Skipped (timeout)")
        
        await status_msg.delete()
        
        embed = discord.Embed(
            title="🧪 FULL Command Test Results",
            description=f"Tested in {ctx.guild.name} ({ctx.guild.member_count} members)",
            color=discord.Color.red() if failed_commands else discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        
        total_tested = len(results)
        passed = total_tested - len(failed_commands)
        embed.add_field(name="Summary", 
                       value=f"✅ Passed: {passed}\n❌ Failed: {len(failed_commands)}\n📊 Total: {total_tested}",
                       inline=False)
        
        if failed_commands:
            embed.add_field(name="❌ Failed Commands", 
                           value="\n".join([f"• `!{cmd}`" for cmd in failed_commands[:10]]),
                           inline=False)
            if len(failed_commands) > 10:
                embed.add_field(name="", value=f"... and {len(failed_commands)-10} more", inline=False)
        
        sample_results = "\n".join(results[:10])
        if len(results) > 10:
            sample_results += f"\n... and {len(results)-10} more"
        embed.add_field(name="Sample Results", value=sample_results, inline=False)
        
        embed.set_footer(text="⚠️ This test actually executed commands in this server")
        
        await ctx.send(embed=embed)
        
        try:
            detailed = "\n".join(results)
            chunks = [detailed[i:i+1900] for i in range(0, len(detailed), 1900)]
            
            await ctx.author.send(f"📋 **FULL Test Results for {ctx.guild.name}**")
            for i, chunk in enumerate(chunks):
                await ctx.author.send(f"```{chunk}```")
        except:
            pass


    @commands.command(name='random', aliases=['fact', 'rand'])
    async def random_fact(self, ctx):
        """Get a random fun fact!"""
        if await self.check_duplicate(ctx):
            return
        
        # List of random fun facts
        facts = [
            "Did you know that 1+1 is 11? Because it's 1+1, not 1+1 =, it's just two 1's being added together!",
            "Did you know that a group of flamingos is called a 'flamboyance'?",
            "Did you know that honey never spoils? Archaeologists found 3,000-year-old honey in Egyptian tombs that was still edible!",
            "Did you know that octopuses have three hearts? Two pump blood to the gills, one pumps it to the rest of the body.",
            "Did you know that bananas are berries, but strawberries aren't?",
            "Did you know that a day on Venus is longer than a year on Venus?",
            "Did you know that cows have best friends and get stressed when separated from them?",
            "Did you know that the shortest war in history lasted only 38 minutes? (Britain vs Zanzibar, 1896)",
            "Did you know that a jiffy is an actual unit of time? It's 1/100th of a second!",
            "Did you know that octopuses can taste with their arms?",
            "Did you know that the Eiffel Tower grows about 6 inches taller in summer due to heat expansion?",
            "Did you know that a crocodile cannot stick its tongue out?",
            "Did you know that a shrimp's heart is located in its head?",
            "Did you know that there are more stars in space than grains of sand on all Earth's beaches?",
            "Did you know that the first oranges weren't orange? They were green!",
            "Did you know that the average person walks the equivalent of three times around the Earth in a lifetime?",
            "Did you know that a snail can sleep for three years?",
            "Did you know that elephants are the only mammals that can't jump?",
            "Did you know that the unicorn is the national animal of Scotland?",
            "Did you know that your nose can remember 50,000 different scents?",
            "Did you know that the human brain generates enough electricity to power a small light bulb?",
            "Did you know that you can't hum while holding your nose closed? Try it!",
            "Did you know that the average person produces enough saliva in a lifetime to fill two swimming pools?",
            "Did you know that a single cloud can weigh more than a million pounds?",
            "Did you know that the first computer virus was created in 1983 and was called 'Elk Cloner'?",
            "Did you know that the first item sold on eBay was a broken laser pointer?",
            "Did you know that the world's oldest piece of chewing gum is over 9,000 years old?",
            "Did you know that the first-ever selfie was taken in 1839 by Robert Cornelius?",
            "Did you know that the average cloud weighs about 1.1 million pounds?",
            "Did you know that a group of pandas is called an 'embarrassment'?",
            "Did you know that a cockroach can live for several weeks without its head?",
            "Did you know that a cat's nose print is as unique as a human's fingerprint?",
            "Did you know that the shortest commercial flight lasts only 57 seconds? (Westray to Papa Westray, Scotland)",
            "Did you know that the first product to have a barcode was Wrigley's gum?",
            "Did you know that a group of owls is called a 'parliament'?",
            "Did you know that the first email was sent in 1971 by Ray Tomlinson to himself?",
            "Did you know that the first-ever photograph of a person was taken in 1838 in Paris?",
            "Did you know that the first-ever music video was 'Video Killed the Radio Star' in 1981?",
            "Did you know that the first-ever ice cream sundae was created in 1881?",
            "Did you know that the first-ever Ferris wheel was built in 1893 for the World's Fair in Chicago?",
            "Did you know that the first-ever roller coaster was built in 1817 in Paris?",
            "Did you know that the first-ever pair of jeans was created in 1873 by Levi Strauss?",
            "Did you know that the first-ever animated film was 'Fantasmagorie' in 1908?",
            "Did you know that the first-ever comic book was published in 1837?",
            "Did you know that the first-ever video game was 'Tennis for Two' in 1958?",
            "Did you know that the first-ever smartphone was created by IBM in 1992?",
            "Did you know that the first-ever website is still online? It was created in 1991!",
            "Did you know that the first-ever YouTube video was uploaded in 2005 and is called 'Me at the zoo'?",
            "Did you know that the first-ever tweet was sent by Jack Dorsey in 2006: 'just setting up my twttr'?",
            "Did you know that the first-ever Instagram post was a photo of a dog in 2010?",
        ]
        
        # Pick a random fact
        fact = random.choice(facts)
        
        # Create embed
        embed = discord.Embed(
            title="🤔 Random Fact",
            description=fact,
            color=discord.Color.purple(),
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text=f"Requested by {ctx.author.name} • Use !random for another fact!")
        
        await ctx.send(embed=embed)

    @commands.command(name='roblox')
    async def roblox_role(self, ctx):
        """Gives you the Roblox role"""
        if await self.check_duplicate(ctx):
            return
        
        role_id = 1488620528167157971
        role = ctx.guild.get_role(role_id)
        
        if not role:
            await ctx.send("❌ Roblox role not found in this server.")
            return
        
        if role in ctx.author.roles:
            await ctx.send(f"❌ {ctx.author.mention} You already have the {role.mention} role!")
            return
        
        try:
            await ctx.author.add_roles(role, reason=f"!roblox command used by {ctx.author}")
            await ctx.send(f"✅ {ctx.author.mention} You now have the ||Roblox Scripts|| role!")
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to assign that role.")
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")
        
        # Delete the command message
        try:
            await ctx.message.delete()
        except:
            pass


    # ===== EXISTING COMMANDS (unchanged) =====
    @commands.command(name='ping')
    async def ping(self, ctx):
        """Check bot latency"""
        if await self.check_duplicate(ctx):
            return
        latency = round(self.bot.latency * 1000)
        await ctx.send(f"🏓 Pong! Latency: `{latency}ms`")

    @commands.command(name='serverinfo')
    async def serverinfo(self, ctx):
        """Show server information"""
        if await self.check_duplicate(ctx):
            return
            
        guild = ctx.guild
        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        categories = len(guild.categories)
        roles = len(guild.roles)
        total_members = guild.member_count
        bots = sum(1 for member in guild.members if member.bot)
        humans = total_members - bots

        embed = discord.Embed(
            title=f"📊 {guild.name}",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(name="🆔 Server ID", value=guild.id, inline=True)
        embed.add_field(name="📅 Created", value=guild.created_at.strftime("%Y-%m-%d"), inline=True)
        embed.add_field(name="👑 Owner", value=guild.owner.mention, inline=True)
        embed.add_field(name="👥 Members",
                        value=f"Total: {total_members}\nHumans: {humans}\nBots: {bots}",
                        inline=True)
        embed.add_field(name="📚 Channels",
                        value=f"Text: {text_channels}\nVoice: {voice_channels}\nCategories: {categories}",
                        inline=True)
        embed.add_field(name="🎭 Roles", value=str(roles), inline=True)
        embed.add_field(name="✨ Boost Level", value=str(guild.premium_tier), inline=True)
        embed.add_field(name="🚀 Boosts", value=str(guild.premium_subscription_count), inline=True)

        await ctx.send(embed=embed)

    @commands.command(name='av')
    async def avatar(self, ctx, member: discord.Member = None):
        """Get a user's avatar"""
        if await self.check_duplicate(ctx):
            return
            
        if member is None:
            member = ctx.author

        embed = discord.Embed(
            title=f"🖼️ {member.display_name}'s Avatar",
            color=member.color if member.color.value != 0 else discord.Color.blue()
        )
        embed.set_image(url=member.avatar.url if member.avatar else member.default_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name='uptime')
    async def uptime(self, ctx):
        """Check bot uptime"""
        if await self.check_duplicate(ctx):
            return
            
        uptime_seconds = int(time.time() - self.bot_start_time)
        days = uptime_seconds // 86400
        hours = (uptime_seconds % 86400) // 3600
        minutes = (uptime_seconds % 3600) // 60
        seconds = uptime_seconds % 60

        uptime_str = []
        if days > 0:
            uptime_str.append(f"{days}d")
        if hours > 0:
            uptime_str.append(f"{hours}h")
        if minutes > 0:
            uptime_str.append(f"{minutes}m")
        uptime_str.append(f"{seconds}s")

        await ctx.send(f"⏱️ Bot Uptime: `{' '.join(uptime_str)}`")

    @commands.command(name='afk')
    async def afk(self, ctx, *, reason: str = "AFK"):
        """Set your AFK status"""
        if await self.check_duplicate(ctx):
            return
            
        conn = self.get_cached_connection(ctx.guild.id)
        if not conn:
            await ctx.send("❌ Could not connect to database.")
            return
            
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO afk (user_id, reason, timestamp) VALUES (?, ?, ?)",
                  (str(ctx.author.id), reason, time.time()))
        conn.commit()

        try:
            current_nick = ctx.author.nick or ctx.author.name
            clean_nick = current_nick.replace("[AFK]", "").strip()
            await ctx.author.edit(nick=f"[AFK]{clean_nick}")
        except:
            pass

        await ctx.send(f"✅ {ctx.author.mention} is now AFK: {reason}")

    @commands.command(name='snipe')
    async def snipe(self, ctx):
        """Show the most recently deleted message in this channel"""
        if await self.check_duplicate(ctx):
            return
            
        channel_id = ctx.channel.id

        if not hasattr(self.bot, 'snipe_cache') or channel_id not in self.bot.snipe_cache or not self.bot.snipe_cache[channel_id]:
            await ctx.send("📭 No recently deleted messages found in this channel.")
            return

        last_deleted = self.bot.snipe_cache[channel_id][-1]

        embed = discord.Embed(
            title="🔫 Sniped!",
            description=last_deleted["content"],
            color=discord.Color.orange(),
            timestamp=datetime.fromtimestamp(last_deleted["time"])
        )
        embed.set_footer(text=f"Deleted message from {last_deleted['author']}")
        await ctx.send(embed=embed)

    @commands.command(name='snipelist')
    async def snipelist(self, ctx, count: int = 5):
        """Show multiple recently deleted messages"""
        if await self.check_duplicate(ctx):
            return
            
        channel_id = ctx.channel.id
        count = min(count, SNIPE_LIMIT)

        if not hasattr(self.bot, 'snipe_cache') or channel_id not in self.bot.snipe_cache or not self.bot.snipe_cache[channel_id]:
            await ctx.send("📭 No recently deleted messages found in this channel.")
            return

        messages = self.bot.snipe_cache[channel_id][-count:]

        embed = discord.Embed(
            title=f"🔫 Last {len(messages)} Deleted Messages",
            color=discord.Color.orange()
        )

        for i, msg in enumerate(reversed(messages), 1):
            time_str = datetime.fromtimestamp(msg["time"]).strftime("%H:%M:%S")
            content = msg["content"][:50] + "..." if len(msg["content"]) > 50 else msg["content"]
            embed.add_field(
                name=f"{i}. {msg['author']} at {time_str}",
                value=content or "*No content*",
                inline=False
            )

        await ctx.send(embed=embed)

    @commands.command(name='say')
    @commands.has_permissions(administrator=True)
    async def say(self, ctx, *, message: str):
        """Bot says whatever you type"""
        if await self.check_duplicate(ctx):
            return
            
        try:
            await ctx.message.delete()
        except:
            pass
        await ctx.send(message)


    @commands.command(name='repeat')
    @commands.has_permissions(administrator=True)
    async def repeat(self, ctx, *, message: str):
        """Keep a message at the bottom of the channel. Usage: !repeat <message>
        The bot will re-send the message whenever someone else sends after it.
        Use !repeatstop to cancel."""
        if await self.check_duplicate(ctx):
            return

        try:
            await ctx.message.delete()
        except:
            pass

        channel_id = ctx.channel.id

        # Cancel any existing repeat task for this channel
        if channel_id in self.repeat_messages:
            existing = self.repeat_messages[channel_id]
            existing['task'].cancel()
            try:
                old_msg = await ctx.channel.fetch_message(existing['message_id'])
                await old_msg.delete()
            except:
                pass

        # Send the initial message
        sent = await ctx.send(message)

        async def watch_channel():
            try:
                while True:
                    await asyncio.sleep(2)

                    data = self.repeat_messages.get(channel_id)
                    if not data:
                        break

                    try:
                        latest = [m async for m in ctx.channel.history(limit=1)][0]
                    except Exception:
                        continue

                    if latest.id != data['message_id']:
                        try:
                            old_msg = await ctx.channel.fetch_message(data['message_id'])
                            await old_msg.delete()
                        except:
                            pass
                        new_msg = await ctx.channel.send(data['content'])
                        data['message_id'] = new_msg.id
                        # Keep DB in sync with the new message_id
                        self.save_repeat(data['guild_id'], channel_id, data['content'], new_msg.id)

            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"repeat watch_channel error in {channel_id}: {e}")

        task = asyncio.create_task(watch_channel())

        self.repeat_messages[channel_id] = {
            'message_id': sent.id,
            'content':    message,
            'task':       task,
            'guild_id':   ctx.guild.id,
        }

        # Persist so repeat survives a bot restart (including message_id)
        self.save_repeat(ctx.guild.id, channel_id, message, sent.id)

    @commands.command(name='repeatstop')
    @commands.has_permissions(administrator=True)
    async def repeatstop(self, ctx, channel: discord.TextChannel = None):
        """Stop a repeating message. Usage: !repeatstop [#channel]"""
        if await self.check_duplicate(ctx):
            return

        target = channel or ctx.channel
        channel_id = target.id

        if channel_id not in self.repeat_messages:
            await ctx.send(f"No active repeat message in {target.mention}.")
            return

        data = self.repeat_messages.pop(channel_id)
        data['task'].cancel()

        try:
            old_msg = await target.fetch_message(data['message_id'])
            await old_msg.delete()
        except:
            pass

        # Remove from database so it doesn't restore on next restart
        guild_id = data.get('guild_id') or ctx.guild.id
        self.delete_repeat(guild_id, channel_id)

        try:
            await ctx.message.delete()
        except:
            pass

        await ctx.send(f"Repeat message stopped in {target.mention}.", delete_after=5)

    @commands.command(name='hello')
    @commands.has_permissions(administrator=True)
    async def hello(self, ctx):
        """Bot introduces itself"""
        if await self.check_duplicate(ctx):
            return
            
        await ctx.send(
            "👋 **Thank You for Adding Asaiya Bot!**\n\n"
            "Hello everyone! I'm **Asaiya Bot**, here to help make your server better.\n\n"
            "📌 **Support Server:** https://discord.gg/UqqeejzCgs\n\n"
            "**Creator:** Zelerator\n\n"
            "📚 **Quick Start:**\n"
            "1️⃣ Create a role named **AsaiyaBot** and assign it to staff\n"
            "2️⃣ Use `!setserver` to set up your server\n"
            "3️⃣ Use `!help` to see all commands"
        )

    @commands.command(name='filter')
    @commands.has_permissions(administrator=True)
    async def filter_word(self, ctx, action: str, *, word: str):
        """Manage filtered words. Usage: !filter add/remove <word>"""
        if await self.check_duplicate(ctx):
            return
            
        word = word.lower()
        conn = self.get_cached_connection(ctx.guild.id)
        if not conn:
            await ctx.send("❌ Could not connect to database.")
            return
            
        c = conn.cursor()

        if action.lower() == 'add':
            try:
                c.execute("INSERT INTO filter_words (word) VALUES (?)", (word,))
                conn.commit()
                if hasattr(self.bot, 'filter_cache') and ctx.guild.id in self.bot.filter_cache:
                    del self.bot.filter_cache[ctx.guild.id]
                await ctx.send(f"✅ Added `{word}` to filter.")
                log_channel = await self.get_log_channel(ctx.guild)
                if log_channel:
                    await log_channel.send(f"🔇 `{word}` added to filter by {ctx.author.mention}")
            except sqlite3.IntegrityError:
                await ctx.send(f"❌ `{word}` is already in the filter.")

        elif action.lower() == 'remove':
            c.execute("DELETE FROM filter_words WHERE word = ?", (word,))
            conn.commit()
            if c.rowcount > 0:
                if hasattr(self.bot, 'filter_cache') and ctx.guild.id in self.bot.filter_cache:
                    del self.bot.filter_cache[ctx.guild.id]
                await ctx.send(f"✅ Removed `{word}` from filter.")
                log_channel = await self.get_log_channel(ctx.guild)
                if log_channel:
                    await log_channel.send(f"🔊 `{word}` removed from filter by {ctx.author.mention}")
            else:
                await ctx.send(f"❌ `{word}` not found in filter.")
        else:
            await ctx.send("❌ Use `!filter add <word>` or `!filter remove <word>`")

    @commands.command(name='setlog')
    @commands.has_permissions(administrator=True)
    async def setlog(self, ctx, channel: discord.TextChannel = None):
        """Set the log channel"""
        if await self.check_duplicate(ctx):
            return
            
        if channel is None:
            channel = discord.utils.get(ctx.guild.text_channels, name=LOG_CHANNEL_NAME)
            if not channel:
                try:
                    channel = await ctx.guild.create_text_channel(
                        LOG_CHANNEL_NAME,
                        reason="Log channel created by bot"
                    )
                    await ctx.send(f"✅ Created #{LOG_CHANNEL_NAME} channel.")
                except Exception as e:
                    await ctx.send(f"❌ Failed to create log channel: {str(e)}")
                    return

        conn = self.get_cached_connection(ctx.guild.id)
        if not conn:
            await ctx.send("❌ Could not connect to database.")
            return
            
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO log_channels (log_channel_id) VALUES (?)",
                  (str(channel.id),))
        conn.commit()
        await ctx.send(f"✅ Log channel set to {channel.mention}")

    @commands.command(name='setwelcome')
    @commands.has_permissions(administrator=True)
    async def setwelcome(self, ctx, channel: discord.TextChannel):
        """Set the welcome channel"""
        if await self.check_duplicate(ctx):
            return
            
        conn = self.get_cached_connection(ctx.guild.id)
        if not conn:
            await ctx.send("❌ Could not connect to database.")
            return
            
        c = conn.cursor()
        c.execute("UPDATE log_channels SET welcome_channel_id = ?", (str(channel.id),))
        if c.rowcount == 0:
            c.execute("INSERT INTO log_channels (welcome_channel_id) VALUES (?)", (str(channel.id),))
        conn.commit()
        await ctx.send(f"✅ Welcome messages will be sent to {channel.mention}")

    @commands.command(name='setleave')
    @commands.has_permissions(administrator=True)
    async def setleave(self, ctx, channel: discord.TextChannel):
        """Set the leave channel"""
        if await self.check_duplicate(ctx):
            return
            
        conn = self.get_cached_connection(ctx.guild.id)
        if not conn:
            await ctx.send("❌ Could not connect to database.")
            return
            
        c = conn.cursor()
        c.execute("UPDATE log_channels SET leave_channel_id = ?", (str(channel.id),))
        if c.rowcount == 0:
            c.execute("INSERT INTO log_channels (leave_channel_id) VALUES (?)", (str(channel.id),))
        conn.commit()
        await ctx.send(f"✅ Leave messages will be sent to {channel.mention}")

    @commands.command(name='role')
    @commands.has_permissions(administrator=True)
    async def role(self, ctx, member: discord.Member, *, role_name: str):
        """Assign a role to a user. Usage: !role @user RoleName"""
        if await self.check_duplicate(ctx):
            return
            
        role = discord.utils.get(ctx.guild.roles, name=role_name)

        if not role:
            await ctx.send(f"❌ Role `{role_name}` not found in this server.")
            return

        bot_member = ctx.guild.get_member(self.bot.user.id)
        if role >= bot_member.top_role:
            await ctx.send(f"❌ I cannot assign {role.mention} because it's higher than my highest role.")
            return

        if role in member.roles:
            await ctx.send(f"ℹ️ {member.mention} already has {role.mention}.")
            return

        try:
            await member.add_roles(role, reason=f"Assigned by {ctx.author.name}")
            await ctx.send(f"✅ Added {role.mention} to {member.mention}")
            log_channel = await self.get_log_channel(ctx.guild)
            if log_channel:
                await log_channel.send(f"👤 {role.mention} assigned to {member.mention} by {ctx.author.mention}")
        except Exception as e:
            await ctx.send(f"❌ Error assigning role: {str(e)}")

    # ===== IMAGEONLY COMMANDS =====
    @commands.command(name='imageonly')
    @commands.has_permissions(administrator=True)
    async def imageonly(self, ctx, channel: discord.TextChannel = None):
        """Set a channel to accept images and videos only."""
        if await self.check_duplicate(ctx):
            return

        target = channel or ctx.channel

        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()

        c.execute('''CREATE TABLE IF NOT EXISTS imageonly_channels
                     (channel_id TEXT PRIMARY KEY,
                      guild_id   TEXT NOT NULL,
                      set_by     TEXT NOT NULL,
                      set_at     REAL NOT NULL)''')

        c.execute("SELECT channel_id FROM imageonly_channels WHERE channel_id = ?", (str(target.id),))
        existing = c.fetchone()

        if existing:
            await ctx.send(f"ℹ️ {target.mention} is already in image-only mode.")
            conn.close()
            return

        c.execute(
            "INSERT INTO imageonly_channels (channel_id, guild_id, set_by, set_at) VALUES (?, ?, ?, ?)",
            (str(target.id), str(ctx.guild.id), str(ctx.author.id), time.time())
        )
        conn.commit()
        conn.close()

        if not hasattr(self.bot, 'imageonly_channels'):
            self.bot.imageonly_channels = set()
        self.bot.imageonly_channels.add(target.id)

        await ctx.send(
            f"✅ {target.mention} is now **image/video only**.\n"
            f"All text-only messages will be automatically deleted."
        )

    @commands.command(name='imageonly-remove')
    @commands.has_permissions(administrator=True)
    async def imageonly_remove(self, ctx, channel: discord.TextChannel = None):
        """Remove image-only restriction from a channel."""
        if await self.check_duplicate(ctx):
            return

        target = channel or ctx.channel

        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()

        c.execute('''CREATE TABLE IF NOT EXISTS imageonly_channels
                     (channel_id TEXT PRIMARY KEY,
                      guild_id   TEXT NOT NULL,
                      set_by     TEXT NOT NULL,
                      set_at     REAL NOT NULL)''')

        c.execute("DELETE FROM imageonly_channels WHERE channel_id = ?", (str(target.id),))
        removed = c.rowcount > 0
        conn.commit()
        conn.close()

        if hasattr(self.bot, 'imageonly_channels'):
            self.bot.imageonly_channels.discard(target.id)

        if removed:
            await ctx.send(f"✅ {target.mention} is no longer image-only.")
        else:
            await ctx.send(f"ℹ️ {target.mention} was not in image-only mode.")

    @commands.command(name='imageonly-list')
    @commands.has_permissions(administrator=True)
    async def imageonly_list(self, ctx):
        """List all image-only channels in this server."""
        if await self.check_duplicate(ctx):
            return

        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS imageonly_channels
                     (channel_id TEXT PRIMARY KEY,
                      guild_id   TEXT NOT NULL,
                      set_by     TEXT NOT NULL,
                      set_at     REAL NOT NULL)''')
        c.execute(
            "SELECT channel_id FROM imageonly_channels WHERE guild_id = ?",
            (str(ctx.guild.id),)
        )
        rows = c.fetchall()
        conn.close()

        if not rows:
            await ctx.send("📭 No image-only channels configured in this server.")
            return

        lines = []
        for (ch_id,) in rows:
            ch = ctx.guild.get_channel(int(ch_id))
            lines.append(f"• {ch.mention if ch else f'Unknown ({ch_id})'}")

        embed = discord.Embed(
            title="🖼️ Image-Only Channels",
            description="\n".join(lines),
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)

    # ===== ON_MESSAGE: ENFORCE IMAGE-ONLY CHANNELS =====
    def _load_imageonly_cache(self):
        """Load image-only channel IDs from DB into bot cache."""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS imageonly_channels
                         (channel_id TEXT PRIMARY KEY,
                          guild_id   TEXT NOT NULL,
                          set_by     TEXT NOT NULL,
                          set_at     REAL NOT NULL)''')
            c.execute("SELECT channel_id FROM imageonly_channels")
            rows = c.fetchall()
            conn.close()
            return {int(row[0]) for row in rows}
        except Exception as e:
            print(f"⚠️ Could not load imageonly cache: {e}")
            return set()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Delete non-image/video messages in image-only channels."""
        if message.author.bot:
            return
        if not message.guild:
            return

        if not hasattr(self.bot, 'imageonly_channels'):
            self.bot.imageonly_channels = self._load_imageonly_cache()

        if message.channel.id not in self.bot.imageonly_channels:
            return

        staff_roles = [BOT_ROLE, "AsaiyaBan", "AsaiyaKick"]
        if any(r.name in staff_roles for r in message.author.roles):
            return

        allowed_types = ("image/", "video/")
        has_media = any(
            att.content_type and att.content_type.startswith(allowed_types)
            for att in message.attachments
        )

        if not has_media:
            try:
                await message.delete()
                await message.channel.send(
                    f"⚠️ {message.author.mention} Only images and videos are allowed here!",
                    delete_after=5
                )
            except discord.Forbidden:
                pass
            return

        await self.bot.process_commands(message)


async def setup(bot):
    await bot.add_cog(Utility(bot))
