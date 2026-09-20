import discord
from discord.ext import commands, tasks
import sqlite3
import time
import asyncio
import os
import random
from datetime import datetime, timedelta

# ===== CONFIGURATION =====
DB_FOLDER = r"C:\Users\Kelly\Desktop\discord database"
MAIN_DB_PATH = os.path.join(DB_FOLDER, "asaiya_bot.db")

MAX_JOBS_PER_MINUTE = 30
RAID_CHECK_INTERVAL = 10
JOIN_CLEANUP_INTERVAL = 60
MESSAGE_TRACK_WINDOW = 5  # Track messages within 5 seconds for hacked account detection
SPAM_MESSAGE_COUNT = 5  # Number of messages to trigger spam detection
SPAM_TIME_WINDOW = 3  # Time window in seconds for spam detection
SPAM_TIMEOUT_MINUTES = 10  # Timeout duration for spam

# Anti-nuke settings
NUKE_WINDOW_SECONDS = 10   # Was 2 — too short, manual deletions take 3-5s each
NUKE_ACTION_THRESHOLD = 3  # Was 2 — now requires 3 actions in 10s to trigger

DEFAULT_STAFF_ROLES = ["AsaiyaBot", "AsaiyaKick", "AsaiyaBan", "AsaiyaPass", "AsaiyaClear", "asaiya-support"]
WHITELISTED_ROLE = "AsaiyaBot"  # Only role immune to anti-nuke punishment

# Log channel for anti-nuke (owner server)
NUKE_LOG_SERVER_ID = 1484265140215087235
NUKE_LOG_CHANNEL_ID = 1491106949368910024


class AntiRaid(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.processed_commands = {}
        
        # Initialize join timestamps if not exists
        if not hasattr(self.bot, 'join_timestamps'):
            self.bot.join_timestamps = []
        
        # Track recent messages for hacked account detection
        self.recent_messages = {}  # {user_id: [{"content": str, "channel_id": int, "timestamp": float, "message_id": int}]}
        
        # Track message timestamps for spam detection
        self.message_timestamps = {}  # {user_id: [timestamp1, timestamp2, ...]}
        
        # ===== ANTI-NUKE TRACKING =====
        # Track destructive actions per user/bot per guild
        # Structure: {guild_id: {user_id: {"message_deletes": [(msg_id, ts), ...], "channel_deletes": [(ch_id, ts), ...], etc}}}
        self.nuke_tracker = {}
        
        # Setup database
        self.setup_database()
        
        # Load per-server settings
        self.server_settings = {}  # {guild_id: {"hack_detection": bool, "spam_detection": bool, "raid_detection": bool, "anti_nuke": bool}}
        self.staff_roles = {}  # {guild_id: [role_ids]}
        self.load_all_settings()
        
        print(f"✅ Anti-Raid cog initialized (ID: {id(self)})")
        print(f"   Loaded settings for {len(self.server_settings)} server(s)")
        print(f"   Loaded staff roles for {len(self.staff_roles)} server(s)")
        
        # Start background tasks
        self.anti_raid_check.start()
        self.cleanup_old_joins.start()
        self.cleanup_old_messages.start()
        self.cleanup_old_violations.start()
        self.cleanup_old_timestamps.start()
        self.cleanup_nuke_tracker.start()

    def cog_unload(self):
        """Stop tasks when cog is unloaded"""
        self.anti_raid_check.cancel()
        self.cleanup_old_joins.cancel()
        self.cleanup_old_messages.cancel()
        self.cleanup_old_violations.cancel()
        self.cleanup_old_timestamps.cancel()
        self.cleanup_nuke_tracker.cancel()
        print("🛑 Anti-raid tasks stopped")

    # ===== DATABASE SETUP =====
    def setup_database(self):
        """Create tables for tracking user violations and server settings"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            
            # User violations table
            c.execute('''CREATE TABLE IF NOT EXISTS user_violations
                         (user_id TEXT,
                          guild_id TEXT,
                          violation_count INTEGER DEFAULT 0,
                          last_violation REAL,
                          created_at REAL,
                          PRIMARY KEY (user_id, guild_id))''')
            
            # Server anti-raid settings (with anti_nuke column)
            c.execute('''CREATE TABLE IF NOT EXISTS anti_raid_settings
                         (guild_id TEXT PRIMARY KEY,
                          hack_detection INTEGER DEFAULT 0,
                          spam_detection INTEGER DEFAULT 0,
                          raid_detection INTEGER DEFAULT 0,
                          anti_nuke INTEGER DEFAULT 0,
                          updated_at REAL)''')
            
            # Staff immunity roles (per server)
            c.execute('''CREATE TABLE IF NOT EXISTS staff_immunity_roles
                         (guild_id TEXT,
                          role_id TEXT,
                          role_name TEXT,
                          added_by TEXT,
                          added_at REAL,
                          PRIMARY KEY (guild_id, role_id))''')
            
            conn.commit()
            conn.close()
            print("✅ Anti-Raid database initialized (default settings: OFF)")
        except Exception as e:
            print(f"❌ Error setting up anti-raid database: {e}")

    def load_all_settings(self):
        """Load all per-server settings from database"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            
            # Ensure anti_nuke column exists (for existing databases)
            try:
                c.execute("ALTER TABLE anti_raid_settings ADD COLUMN anti_nuke INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # Column already exists
            
            # Load anti-raid settings
            c.execute("SELECT guild_id, hack_detection, spam_detection, raid_detection, anti_nuke FROM anti_raid_settings")
            rows = c.fetchall()
            for guild_id, hack, spam, raid, anti_nuke in rows:
                self.server_settings[int(guild_id)] = {
                    "hack_detection": bool(hack),
                    "spam_detection": bool(spam),
                    "raid_detection": bool(raid),
                    "anti_nuke": bool(anti_nuke)
                }
            
            # Load staff roles
            c.execute("SELECT guild_id, role_id FROM staff_immunity_roles")
            rows = c.fetchall()
            for guild_id, role_id in rows:
                gid = int(guild_id)
                if gid not in self.staff_roles:
                    self.staff_roles[gid] = []
                self.staff_roles[gid].append(int(role_id))
            
            conn.close()
            print(f"📊 Loaded {len(self.server_settings)} server settings, {len(self.staff_roles)} staff role sets")
        except Exception as e:
            print(f"Error loading settings: {e}")

    def save_server_setting(self, guild_id, setting_name, value):
        """Save a server setting to database"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            
            # Get existing settings or create default
            if guild_id not in self.server_settings:
                self.server_settings[guild_id] = {
                    "hack_detection": False,
                    "spam_detection": False,
                    "raid_detection": False,
                    "anti_nuke": False
                }
            
            # Update in-memory
            self.server_settings[guild_id][setting_name] = value
            
            # Update database - use COALESCE to preserve word_filter and invite_protection
            c.execute('''INSERT INTO anti_raid_settings
                         (guild_id, hack_detection, spam_detection, raid_detection, anti_nuke, word_filter, invite_protection, updated_at)
                         VALUES (?, ?, ?, ?, ?, 1, 1, ?)
                         ON CONFLICT(guild_id) DO UPDATE SET
                             hack_detection = excluded.hack_detection,
                             spam_detection = excluded.spam_detection,
                             raid_detection = excluded.raid_detection,
                             anti_nuke = excluded.anti_nuke,
                             updated_at = excluded.updated_at''',
                      (str(guild_id),
                       1 if self.server_settings[guild_id]["hack_detection"] else 0,
                       1 if self.server_settings[guild_id]["spam_detection"] else 0,
                       1 if self.server_settings[guild_id]["raid_detection"] else 0,
                       1 if self.server_settings[guild_id]["anti_nuke"] else 0,
                       time.time()))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error saving server setting: {e}")
            return False

    def get_server_setting(self, guild_id, setting_name):
        """Get a server setting value - defaults to OFF (False)"""
        if guild_id not in self.server_settings:
            return False  # DEFAULT: OFF
        return self.server_settings[guild_id].get(setting_name, False)

    def add_staff_role(self, guild_id, role_id, role_name, added_by):
        """Add a staff immunity role"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''INSERT OR REPLACE INTO staff_immunity_roles
                         (guild_id, role_id, role_name, added_by, added_at)
                         VALUES (?, ?, ?, ?, ?)''',
                      (str(guild_id), str(role_id), role_name, str(added_by), time.time()))
            conn.commit()
            conn.close()
            
            if guild_id not in self.staff_roles:
                self.staff_roles[guild_id] = []
            if role_id not in self.staff_roles[guild_id]:
                self.staff_roles[guild_id].append(role_id)
            return True
        except Exception as e:
            print(f"Error adding staff role: {e}")
            return False

    def remove_staff_role(self, guild_id, role_id):
        """Remove a staff immunity role"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM staff_immunity_roles WHERE guild_id = ? AND role_id = ?",
                      (str(guild_id), str(role_id)))
            deleted = c.rowcount
            conn.commit()
            conn.close()
            
            if deleted > 0 and guild_id in self.staff_roles:
                if role_id in self.staff_roles[guild_id]:
                    self.staff_roles[guild_id].remove(role_id)
            return deleted > 0
        except Exception as e:
            print(f"Error removing staff role: {e}")
            return False

    def get_staff_roles(self, guild_id):
        """Get all staff immunity role IDs for a guild"""
        return self.staff_roles.get(guild_id, [])

    def is_staff(self, member, guild_id=None):
        """Check if a member has any staff role"""
        if not isinstance(member, discord.Member):
            return False
        
        guild = member.guild
        if guild_id is None:
            guild_id = guild.id
        
        # Get staff role IDs for this guild
        staff_role_ids = self.get_staff_roles(guild_id)
        
        # Also check default staff role names
        for role in member.roles:
            if role.id in staff_role_ids:
                return True
            if role.name in DEFAULT_STAFF_ROLES:
                return True
        
        return False

    def is_whitelisted_for_anti_nuke(self, member):
        """Check if member has the AsaiyaBot role (only whitelisted role for anti-nuke)"""
        if not isinstance(member, discord.Member):
            return False
        return any(role.name == "AsaiyaBot" for role in member.roles)

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

    # ===== DATABASE HELPERS =====

    def get_server_db_path(self, guild_id):
        """Get database path for a specific server"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            # First check authorized_servers for db_path
            c.execute("SELECT db_path FROM authorized_servers WHERE guild_id = ?", (str(guild_id),))
            result = c.fetchone()
            
            if not result:
                # If not in authorized_servers, check servers table
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
        """Get cached database connection"""
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

        # Check if connection exists and is alive
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

        # Get database path
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
        """Get the log channel for a guild"""
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

    async def get_nuke_log_channel(self):
        """Get the anti-nuke log channel in owner server"""
        guild = self.bot.get_guild(NUKE_LOG_SERVER_ID)
        if guild:
            return guild.get_channel(NUKE_LOG_CHANNEL_ID)
        return None

    # ===== JOIN TRACKING =====

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Track member joins for raid detection"""
        # Add join timestamp
        self.bot.join_timestamps.append({
            'user_id': member.id,
            'guild_id': member.guild.id,
            'timestamp': time.time()
        })
        
        # Also save to database for persistence
        try:
            conn = self.get_cached_connection(member.guild.id)
            if conn:
                c = conn.cursor()
                c.execute('''CREATE TABLE IF NOT EXISTS join_timestamps
                             (id INTEGER PRIMARY KEY AUTOINCREMENT,
                              user_id TEXT,
                              guild_id TEXT,
                              timestamp REAL)''')
                c.execute("INSERT INTO join_timestamps (user_id, guild_id, timestamp) VALUES (?, ?, ?)",
                          (str(member.id), str(member.guild.id), time.time()))
                conn.commit()
        except Exception as e:
            print(f"Error saving join to database: {e}")

    # ===== ANTI-NUKE ACTION TRACKING =====
    
    def add_nuke_action(self, guild_id, user_id, action_type, item_id):
        """Track a destructive action for anti-nuke detection"""
        current_time = time.time()
        
        # Initialize tracking for this guild if needed
        if guild_id not in self.nuke_tracker:
            self.nuke_tracker[guild_id] = {}
        
        # Initialize tracking for this user if needed
        if user_id not in self.nuke_tracker[guild_id]:
            self.nuke_tracker[guild_id][user_id] = {
                "message_deletes": [],
                "channel_deletes": [],
                "channel_creates": [],
                "channel_renames": [],
                "category_deletes": [],
                "category_creates": [],
                "category_renames": [],
                "role_deletes": [],
                "role_creates": [],
                "role_updates": [],
                "perm_changes": []
            }
        
        # Add the action
        tracker = self.nuke_tracker[guild_id][user_id]
        tracker[action_type].append((item_id, current_time))
        
        # Clean old actions for this specific type
        cutoff = current_time - NUKE_WINDOW_SECONDS
        tracker[action_type] = [(iid, ts) for iid, ts in tracker[action_type] if ts > cutoff]
        
        # Check if threshold reached for ANY action type
        for action_name, action_list in tracker.items():
            if len(action_list) >= NUKE_ACTION_THRESHOLD:
                return True, action_name, len(action_list)
        
        return False, None, 0
    
    async def execute_anti_nuke(self, guild, user, action_type, action_count):
        """Strip all roles from the perpetrator and log the incident"""
        # Only apply to members (not None)
        if not isinstance(user, discord.Member):
            return False
        
        # Check whitelist - ONLY AsaiyaBot role is safe
        if self.is_whitelisted_for_anti_nuke(user):
            print(f"🛡️ [ANTI-NUKE] {user.name} has AsaiyaBot role - skipping punishment")
            await self.log_anti_nuke_attempt(guild, user, action_type, action_count, whitelisted=True)
            return False
        
        # Strip all roles
        roles_to_remove = [role for role in user.roles if role.name != "@everyone"]
        
        if not roles_to_remove:
            print(f"⚠️ [ANTI-NUKE] {user.name} has no roles to strip")
            return False
        
        try:
            await user.remove_roles(*roles_to_remove, reason=f"Anti-nuke: {action_count} {action_type} in {NUKE_WINDOW_SECONDS}s")
            print(f"💥 [ANTI-NUKE] Stripped {len(roles_to_remove)} roles from {user.name} in {guild.name}")
            
            # Log the incident
            await self.log_anti_nuke_attempt(guild, user, action_type, action_count, whitelisted=False, roles_stripped=len(roles_to_remove))
            
            # Also send a DM to the perpetrator
            try:
                embed = discord.Embed(
                    title="💥 ANTI-NUKE TRIGGERED",
                    description=(
                        f"You have been **stripped of all roles** in **{guild.name}**.\n\n"
                        f"**Reason:** {action_count} {action_type.replace('_', ' ').title()} detected within {NUKE_WINDOW_SECONDS} seconds.\n\n"
                        f"This action has been logged. If this was a mistake, contact the server administrators."
                    ),
                    color=discord.Color.dark_red(),
                    timestamp=datetime.utcnow()
                )
                await user.send(embed=embed)
            except:
                pass
            
            return True
            
        except discord.Forbidden:
            print(f"❌ [ANTI-NUKE] No permission to strip roles from {user.name} in {guild.name}")
            return False
        except Exception as e:
            print(f"❌ [ANTI-NUKE] Error stripping roles: {e}")
            return False
    
    async def log_anti_nuke_attempt(self, guild, user, action_type, action_count, whitelisted=False, roles_stripped=0):
        """Log anti-nuke events to owner server channel"""
        channel = await self.get_nuke_log_channel()
        if not channel:
            return
        
        if whitelisted:
            embed = discord.Embed(
                title="🛡️ ANTI-NUKE: WHITELISTED USER DETECTED",
                description=f"A user with the **AsaiyaBot** role triggered anti-nuke detection but was **not punished**.",
                color=discord.Color.gold(),
                timestamp=datetime.utcnow()
            )
        else:
            embed = discord.Embed(
                title="💥 ANTI-NUKE TRIGGERED",
                description=f"**Punishment applied:** Stripped of all roles",
                color=discord.Color.dark_red(),
                timestamp=datetime.utcnow()
            )
        
        embed.add_field(name="Server", value=f"{guild.name} (`{guild.id}`)", inline=False)
        embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=True)
        embed.add_field(name="Action Type", value=action_type.replace('_', ' ').title(), inline=True)
        embed.add_field(name="Action Count", value=str(action_count), inline=True)
        embed.add_field(name="Window", value=f"{NUKE_WINDOW_SECONDS} seconds", inline=True)
        embed.add_field(name="Threshold", value=f"{NUKE_ACTION_THRESHOLD}+ actions", inline=True)
        
        if not whitelisted:
            embed.add_field(name="Roles Stripped", value=str(roles_stripped), inline=True)
        
        await channel.send(embed=embed)

    # ===== ANTI-NUKE EVENT LISTENERS =====
    
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        """Track message deletions for anti-nuke (ignores self-deletions)"""
        if not message.guild:
            return
        if message.author.bot:
            return
        
        # Check if anti-nuke is enabled for this guild
        if not self.get_server_setting(message.guild.id, "anti_nuke"):
            return
        
        # ===== CRITICAL FIX: Find who deleted the message =====
        deleter = None
        try:
            # Check audit log to see who deleted the message
            async for entry in message.guild.audit_logs(action=discord.AuditLogAction.message_delete, limit=5):
                # Check if the deleted message ID matches
                if entry.target.id == message.author.id:
                    # Check if the deletion happened within the last 5 seconds
                    if entry.created_at.timestamp() > time.time() - 5:
                        deleter = entry.user
                        break
        except discord.Forbidden:
            # If we can't access audit log, skip anti-nuke for deletions
            print(f"⚠️ Missing 'view_audit_log' permission in {message.guild.name} - skipping self-delete check")
            return
        except Exception as e:
            print(f"Error checking audit log for message delete: {e}")
            return
        
        # If we couldn't find the deleter via audit log, assume it was the author themselves
        if deleter is None:
            # No audit log entry found - likely the author deleted their own message
            print(f"ℹ️ No audit log entry for message deletion - assuming {message.author} deleted their own message")
            return
        
        # If the deleter is the message author themselves, skip punishment
        if deleter.id == message.author.id:
            print(f"✅ [ANTI-NUKE] User {message.author.name} deleted their own message - no action taken")
            return
        
        # If we get here, someone else deleted the message
        print(f"⚠️ [ANTI-NUKE] {deleter.name} deleted {message.author.name}'s message")
        
        # Track the action
        triggered, action_type, count = self.add_nuke_action(
            message.guild.id, deleter.id, "message_deletes", message.id
        )
        
        if triggered:
            await self.execute_anti_nuke(message.guild, deleter, action_type, count)
    
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Track channel deletions for anti-nuke"""
        if not channel.guild:
            return
        
        if not self.get_server_setting(channel.guild.id, "anti_nuke"):
            return
        
        await self.check_audit_log_for_actor(channel.guild, channel, "channel_delete")
    
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        """Track channel creations for anti-nuke"""
        if not channel.guild:
            return
        
        if not self.get_server_setting(channel.guild.id, "anti_nuke"):
            return
        
        await self.check_audit_log_for_actor(channel.guild, channel, "channel_create")

    @commands.Cog.listener()
    async def on_guild_category_delete(self, category):
        """Track category deletions for anti-nuke"""
        if not category.guild:
            return
        
        if not self.get_server_setting(category.guild.id, "anti_nuke"):
            return
        
        await self.check_audit_log_for_actor(category.guild, category, "channel_delete")

    @commands.Cog.listener()
    async def on_guild_category_create(self, category):
        """Track category creations for anti-nuke"""
        if not category.guild:
            return
        
        if not self.get_server_setting(category.guild.id, "anti_nuke"):
            return
        
        await self.check_audit_log_for_actor(category.guild, category, "channel_create")
    
    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        """Track role deletions for anti-nuke"""
        if not role.guild:
            return
        
        if not self.get_server_setting(role.guild.id, "anti_nuke"):
            return
        
        await self.check_audit_log_for_actor(role.guild, role, "role_delete")
    
    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        """Track role creations for anti-nuke"""
        if not role.guild:
            return
        
        if not self.get_server_setting(role.guild.id, "anti_nuke"):
            return
        
        await self.check_audit_log_for_actor(role.guild, role, "role_create")
    
    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        """Track role updates (permissions/name changes) for anti-nuke"""
        if not before.guild:
            return
        
        if not self.get_server_setting(before.guild.id, "anti_nuke"):
            return
        
        # Only track significant changes
        if before.name != after.name or before.permissions != after.permissions:
            await self.check_audit_log_for_actor(before.guild, after, "role_update")
    
    async def check_audit_log_for_actor(self, guild, target, action_type):
        """Check audit log to find who performed an action"""
        try:
            action_map = {
                "channel_create": discord.AuditLogAction.channel_create,
                "channel_delete": discord.AuditLogAction.channel_delete,
                "role_create":    discord.AuditLogAction.role_create,
                "role_delete":    discord.AuditLogAction.role_delete,
                "role_update":    discord.AuditLogAction.role_update,
            }

            audit_action = action_map.get(action_type)
            if not audit_action:
                return

            # Wait a moment for Discord audit log to populate
            await asyncio.sleep(1)

            now = time.time()
            async for entry in guild.audit_logs(action=audit_action, limit=10):
                # Match by target ID OR by recency (within 8 seconds) when target no longer exists
                target_matches = False
                try:
                    target_matches = entry.target.id == target.id
                except Exception:
                    pass

                time_matches = (now - entry.created_at.timestamp()) < 8

                if target_matches or time_matches:
                    user = entry.user
                    if user and not user.bot:
                        tracker_key_map = {
                            "channel_create": "channel_creates",
                            "channel_delete": "channel_deletes",
                            "role_create":    "role_creates",
                            "role_delete":    "role_deletes",
                            "role_update":    "role_updates",
                        }
                        tracker_key = tracker_key_map.get(action_type, f"{action_type}s")

                        print(f"🔍 [ANTI-NUKE] {user.name} performed {action_type} in {guild.name}")

                        triggered, action_name, count = self.add_nuke_action(
                            guild.id, user.id, tracker_key, target.id
                        )
                        if triggered:
                            print(f"🚨 [ANTI-NUKE] TRIGGERED — {user.name}: {count}x {action_name} in {NUKE_WINDOW_SECONDS}s")
                            await self.execute_anti_nuke(guild, user, action_name, count)
                    break

        except discord.Forbidden:
            print(f"❌ Missing 'view_audit_log' permission in {guild.name}")
        except Exception as e:
            print(f"Error checking audit log for {action_type}: {e}")

    # ===== MAIN MESSAGE LISTENER =====
    @commands.Cog.listener()
    async def on_message(self, message):
        """Combined message handler for spam and hack detection"""
        # Skip bots and DMs
        if message.author.bot or not message.guild:
            return
        
        # Skip command messages
        if message.content.startswith('!'):
            return
        
        # Debug: Print when a message is received
        print(f"📨 [ANTI-RAID] Message from {message.author.name} in {message.guild.name}: {message.content[:50]}")
        
        # Check if user is staff (bypass all except anti-nuke?)
        if self.is_staff(message.author, message.guild.id):
            print(f"👑 [ANTI-RAID] {message.author.name} is staff - bypassing spam and raid checks")
            # Staff still go through hacked detection but with special handling
        
        current_time = time.time()
        
        # === SPAM DETECTION ===
        if self.get_server_setting(message.guild.id, "spam_detection"):
            print(f"🔍 [ANTI-RAID] Spam detection ENABLED for {message.guild.name}")
            await self._check_spam(message, current_time)
        else:
            print(f"🔴 [ANTI-RAID] Spam detection DISABLED for {message.guild.name}")
        
        # === HACKED ACCOUNT DETECTION ===
        if self.get_server_setting(message.guild.id, "hack_detection"):
            print(f"🔍 [ANTI-RAID] Hack detection ENABLED for {message.guild.name}")
            await self._check_hacked(message, current_time)
        else:
            print(f"🔴 [ANTI-RAID] Hack detection DISABLED for {message.guild.name}")

    async def _check_spam(self, message, current_time):
        """Check for spam"""
        # Skip staff for spam detection
        if self.is_staff(message.author, message.guild.id):
            print(f"👑 [SPAM] {message.author.name} is staff - skipping spam check")
            return False
            
        user_id = message.author.id
        
        # Initialize timestamp list for this user
        if user_id not in self.message_timestamps:
            self.message_timestamps[user_id] = []
        
        # Add current message timestamp
        self.message_timestamps[user_id].append(current_time)
        
        # Clean old timestamps
        self.message_timestamps[user_id] = [t for t in self.message_timestamps[user_id] 
                                            if current_time - t <= SPAM_TIME_WINDOW]
        
        print(f"📊 [SPAM] {message.author.name} has {len(self.message_timestamps[user_id])} messages in last {SPAM_TIME_WINDOW}s")
        
        # Check if spam threshold reached
        if len(self.message_timestamps[user_id]) >= SPAM_MESSAGE_COUNT:
            print(f"🚨 [SPAM] THRESHOLD REACHED for {message.author.name}!")
            
            # Delete all recent messages from this user
            deleted_count = 0
            try:
                async for msg in message.channel.history(limit=SPAM_MESSAGE_COUNT):
                    if msg.author.id == user_id and current_time - msg.created_at.timestamp() <= SPAM_TIME_WINDOW:
                        try:
                            await msg.delete()
                            deleted_count += 1
                        except:
                            pass
            except Exception as e:
                print(f"Error deleting spam messages: {e}")
            
            # Send DM FIRST (before timeout)
            try:
                embed = discord.Embed(
                    title="⏰ **TIMEOUT!**",
                    description=(
                        f"You have been **timed out for {SPAM_TIMEOUT_MINUTES} minutes** in **{message.guild.name}**.\n\n"
                        f"**Reason:** Spamming\n\n"
                        f"You sent **{len(self.message_timestamps[user_id])} messages** in **{SPAM_TIME_WINDOW} seconds**.\n\n"
                        f"Please slow down and avoid sending too many messages too quickly."
                    ),
                    color=discord.Color.orange(),
                    timestamp=datetime.utcnow()
                )
                await message.author.send(embed=embed)
                print(f"📨 [SPAM] DM sent to {message.author.name}")
            except Exception as e:
                print(f"⚠️ [SPAM] Could not DM {message.author.name}: {e}")
            
            # THEN timeout the user
            try:
                await message.author.timeout(
                    timedelta(minutes=SPAM_TIMEOUT_MINUTES),
                    reason=f"Spamming - sent {len(self.message_timestamps[user_id])} messages in {SPAM_TIME_WINDOW} seconds"
                )
                print(f"⏰ [SPAM] Timed out {message.author.name} for {SPAM_TIMEOUT_MINUTES} minutes")
            except Exception as e:
                print(f"Error timing out spammer: {e}")
            
            # Send alert to log channel
            log_channel = await self.get_log_channel(message.guild)
            if log_channel:
                embed = discord.Embed(
                    title="🚨 **SPAM DETECTED**",
                    description=(
                        f"**User:** {message.author.mention} ({message.author.name})\n"
                        f"**User ID:** `{message.author.id}`\n\n"
                        f"**Action Taken:**\n"
                        f"• {deleted_count} spam message(s) deleted\n"
                        f"• Timed out for {SPAM_TIMEOUT_MINUTES} minutes\n\n"
                        f"**Sent {len(self.message_timestamps[user_id])} messages in {SPAM_TIME_WINDOW} seconds**"
                    ),
                    color=discord.Color.orange(),
                    timestamp=datetime.utcnow()
                )
                await log_channel.send(embed=embed)
                print(f"📝 [SPAM] Alert sent to log channel")
            
            # Clear timestamps to prevent immediate re-trigger
            self.message_timestamps[user_id] = []
            return True
        return False

    async def _check_hacked(self, message, current_time):
        """Check for hacked account (duplicate messages in different channels)"""
        user_id = message.author.id
        content = message.content.strip()
        
        # Skip empty messages
        if not content:
            return False
        
        # Initialize tracking for this user if not exists
        if user_id not in self.recent_messages:
            self.recent_messages[user_id] = []
        
        # Get user's recent messages
        user_messages = self.recent_messages[user_id]
        
        # Clean up old messages for this user
        user_messages = [m for m in user_messages if current_time - m['timestamp'] <= MESSAGE_TRACK_WINDOW]
        self.recent_messages[user_id] = user_messages
        
        print(f"📊 [HACK] {message.author.name} has {len(user_messages)} recent messages")
        
        # Check for duplicate content in different channels
        duplicate_channels = set()
        duplicate_message_ids = []
        
        for msg in user_messages:
            if msg['content'] == content and msg['channel_id'] != message.channel.id:
                duplicate_channels.add(msg['channel_id'])
                duplicate_message_ids.append(msg['message_id'])
                print(f"🔁 [HACK] Found duplicate of '{content[:30]}' in channel {msg['channel_id']}")
        
        # If we found duplicates in different channels
        if duplicate_channels:
            print(f"🚨 [HACK] DUPLICATE DETECTED for {message.author.name}!")
            
            # Add current channel
            duplicate_channels.add(message.channel.id)
            
            # Get channel names
            channel_names = []
            for ch_id in duplicate_channels:
                channel = message.guild.get_channel(ch_id)
                if channel:
                    channel_names.append(f"#{channel.name}")
            
            print(f"📋 [HACK] Channels involved: {', '.join(channel_names)}")
            
            # Collect all messages to delete
            all_messages_to_delete = duplicate_message_ids + [message.id]
            
            # Delete all duplicate messages
            deleted_count = 0
            for msg_id in all_messages_to_delete:
                try:
                    if msg_id == message.id:
                        await message.delete()
                    else:
                        # For older messages, find which channel they were in
                        for ch_id in duplicate_channels:
                            channel = message.guild.get_channel(ch_id)
                            if channel:
                                try:
                                    old_msg = await channel.fetch_message(msg_id)
                                    await old_msg.delete()
                                    break
                                except:
                                    continue
                    deleted_count += 1
                except Exception as e:
                    print(f"Could not delete message {msg_id}: {e}")
            
            print(f"🗑️ [HACK] Deleted {deleted_count} duplicate messages")
            
            # Check if user is staff (bypass punishments but still warn)
            is_staff_user = self.is_staff(message.author, message.guild.id)
            
            # Format channel names for DM
            channels_formatted = ", ".join(channel_names)
            
            if is_staff_user:
                # Staff member: Send friendly warning DM, no punishments
                try:
                    embed = discord.Embed(
                        title="⚠️ **Hey! Quick Check** ⚠️",
                        description=(
                            f"Bro did you get hacked? You sent the same messages in:\n"
                            f"**{channels_formatted}**\n\n"
                            f"within **{MESSAGE_TRACK_WINDOW} seconds**.\n\n"
                            f"You're a staff member so you **won't get punished**, but **DO BE CAREFUL**! 🛡️\n\n"
                            f"*If this wasn't you, please change your password immediately!*"
                        ),
                        color=discord.Color.gold(),
                        timestamp=datetime.utcnow()
                    )
                    await message.author.send(embed=embed)
                    print(f"📨 [HACK] Friendly warning DM sent to staff {message.author.name}")
                except Exception as e:
                    print(f"⚠️ [HACK] Could not DM staff {message.author.name}: {e}")
                
                # Send alert to log channel (different color for staff)
                log_channel = await self.get_log_channel(message.guild)
                if log_channel:
                    embed = discord.Embed(
                        title="⚠️ **STAFF DUPLICATE MESSAGES** ⚠️",
                        description=(
                            f"**User:** {message.author.mention} ({message.author.name})\n"
                            f"**User ID:** `{message.author.id}`\n"
                            f"**Role:** STAFF (WARNING ONLY)\n\n"
                            f"**Action:** Deleted {deleted_count} duplicate message(s)\n"
                            f"**Punishment:** None (staff immunity)\n\n"
                            f"**Sent same message in:**\n{', '.join(sorted(set(channel_names)))}\n\n"
                            f"**Message:** {content[:200]}"
                        ),
                        color=discord.Color.gold(),
                        timestamp=datetime.utcnow()
                    )
                    await log_channel.send(embed=embed)
                    print(f"📝 [HACK] Staff alert sent to log channel")
                
                # Still track the message but no punishment
                self.recent_messages[user_id].append({
                    'content': content,
                    'channel_id': message.channel.id,
                    'timestamp': current_time,
                    'message_id': message.id
                })
                
                # Keep only last 20 messages per user
                if len(self.recent_messages[user_id]) > 20:
                    self.recent_messages[user_id] = self.recent_messages[user_id][-20:]
                
                return True
            
            # ===== REGULAR USER PUNISHMENTS =====
            
            # Get violation count
            violation_count = self.get_violation_count(user_id, message.guild.id)
            violation_count = self.increment_violation_count(user_id, message.guild.id)
            print(f"⚠️ [HACK] Violation count for {message.author.name}: {violation_count}")
            
            # Create invite link for potential rejoin (for kick scenario)
            invite_link = None
            if violation_count == 2:
                try:
                    invite = await message.channel.create_invite(max_age=3600, max_uses=1, reason="For kicked user to rejoin")
                    invite_link = invite.url
                    print(f"🔗 [HACK] Created invite link: {invite_link}")
                except Exception as e:
                    print(f"Could not create invite: {e}")
            
            # Determine action
            action_taken = ""
            
            if violation_count == 1:
                # First violation: Send DM FIRST, THEN timeout
                try:
                    embed = discord.Embed(
                        title="⚠️ **Hacked Account Warning - 1st Offense**",
                        description=(
                            f"You have been **timed out for 24 hours** in **{message.guild.name}**.\n\n"
                            f"**Reason:** You were detected sending the same message in multiple channels within {MESSAGE_TRACK_WINDOW} seconds.\n\n"
                            f"This is your **1st warning**. If this happens again:\n"
                            f"• 2nd warning: You will be **kicked** from the server\n"
                            f"• 3rd warning: You will be **banned** from the server"
                        ),
                        color=discord.Color.orange()
                    )
                    await message.author.send(embed=embed)
                    print(f"📨 [HACK] DM sent to {message.author.name} for 1st offense")
                except Exception as e:
                    print(f"⚠️ [HACK] Could not DM {message.author.name}: {e}")
                
                try:
                    await message.author.timeout(
                        timedelta(hours=24),
                        reason=f"Hacked account detection - 1st violation"
                    )
                    action_taken = "timed out for 24 hours"
                    print(f"⏰ [HACK] 1st offense: Timed out {message.author.name} for 24 hours")
                except Exception as e:
                    action_taken = f"timeout failed: {e}"
                    print(f"Error timing out: {e}")
                    
            elif violation_count == 2:
                # Second violation: Send DM FIRST, THEN kick
                try:
                    embed = discord.Embed(
                        title="⚠️ **Hacked Account Warning - 2nd Offense**",
                        description=(
                            f"You have been **kicked** from **{message.guild.name}**.\n\n"
                            f"**Reason:** You were detected sending the same message in multiple channels for the **2nd time**.\n\n"
                            f"**Rejoin Link:** {invite_link}\n\n"
                            f"This is your **2nd warning**. If this happens again, you will be **permanently banned**."
                        ),
                        color=discord.Color.red()
                    )
                    await message.author.send(embed=embed)
                    print(f"📨 [HACK] DM sent to {message.author.name} for 2nd offense")
                except Exception as e:
                    print(f"⚠️ [HACK] Could not DM {message.author.name}: {e}")
                
                try:
                    await message.author.kick(reason=f"Hacked account detection - 2nd violation")
                    action_taken = "kicked from the server"
                    print(f"👢 [HACK] 2nd offense: Kicked {message.author.name}")
                except Exception as e:
                    action_taken = f"kick failed: {e}"
                    print(f"Error kicking: {e}")
                    
            elif violation_count >= 3:
                # Third+ violation: Send DM FIRST, THEN ban
                try:
                    embed = discord.Embed(
                        title="🔨 **Hacked Account Warning - 3rd Offense (BAN)**",
                        description=(
                            f"You have been **permanently banned** from **{message.guild.name}**.\n\n"
                            f"**Reason:** You were detected sending the same message in multiple channels for the **3rd time**.\n\n"
                            f"This is your **final warning**. You are no longer allowed to join this server."
                        ),
                        color=discord.Color.dark_red()
                    )
                    await message.author.send(embed=embed)
                    print(f"📨 [HACK] DM sent to {message.author.name} for 3rd+ offense")
                except Exception as e:
                    print(f"⚠️ [HACK] Could not DM {message.author.name}: {e}")
                
                try:
                    await message.author.ban(reason=f"Hacked account detection - 3rd violation")
                    action_taken = "banned from the server"
                    print(f"🔨 [HACK] 3rd+ offense: Banned {message.author.name}")
                except Exception as e:
                    action_taken = f"ban failed: {e}"
                    print(f"Error banning: {e}")
            
            # Send alert to log channel
            log_channel = await self.get_log_channel(message.guild)
            if log_channel:
                embed = discord.Embed(
                    title="🚨 **HACKED ACCOUNT DETECTED**",
                    description=(
                        f"**User:** {message.author.mention} ({message.author.name})\n"
                        f"**User ID:** `{message.author.id}`\n\n"
                        f"**Violation Count:** {violation_count}\n"
                        f"**Action:** {action_taken}\n\n"
                        f"**Sent same message in:**\n{', '.join(sorted(set(channel_names)))}\n\n"
                        f"**Message:** {content[:200]}"
                    ),
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                await log_channel.send(embed=embed)
                print(f"📝 [HACK] Alert sent to log channel")
            
            return True
        
        # If no duplicates, add this message to tracking
        self.recent_messages[user_id].append({
            'content': content,
            'channel_id': message.channel.id,
            'timestamp': current_time,
            'message_id': message.id
        })
        
        # Keep only last 20 messages per user
        if len(self.recent_messages[user_id]) > 20:
            self.recent_messages[user_id] = self.recent_messages[user_id][-20:]
        
        return False

    # ===== VIOLATION TRACKING =====
    def get_violation_count(self, user_id, guild_id):
        """Get the violation count for a user in a specific guild"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT violation_count FROM user_violations WHERE user_id = ? AND guild_id = ?",
                      (str(user_id), str(guild_id)))
            result = c.fetchone()
            conn.close()
            return result[0] if result else 0
        except:
            return 0

    def increment_violation_count(self, user_id, guild_id):
        """Increment the violation count for a user"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            current = self.get_violation_count(user_id, guild_id)
            new_count = current + 1
            c.execute('''INSERT OR REPLACE INTO user_violations
                         (user_id, guild_id, violation_count, last_violation, created_at)
                         VALUES (?, ?, ?, ?, COALESCE((SELECT created_at FROM user_violations WHERE user_id = ? AND guild_id = ?), ?))''',
                      (str(user_id), str(guild_id), new_count, time.time(), str(user_id), str(guild_id), time.time()))
            conn.commit()
            conn.close()
            return new_count
        except Exception as e:
            print(f"Error incrementing violation count: {e}")
            return 0

    def reset_violation_count(self, user_id, guild_id):
        """Reset the violation count for a user"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM user_violations WHERE user_id = ? AND guild_id = ?",
                      (str(user_id), str(guild_id)))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error resetting violation count: {e}")
            return False

    # ===== CLEANUP TASKS =====

    @tasks.loop(seconds=30)
    async def cleanup_old_messages(self):
        """Clean up old message tracking data"""
        current_time = time.time()
        for user_id in list(self.recent_messages.keys()):
            self.recent_messages[user_id] = [
                msg for msg in self.recent_messages[user_id]
                if current_time - msg['timestamp'] <= MESSAGE_TRACK_WINDOW
            ]
            if not self.recent_messages[user_id]:
                del self.recent_messages[user_id]

    @cleanup_old_messages.before_loop
    async def before_cleanup_messages(self):
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=60)
    async def cleanup_old_timestamps(self):
        """Clean up old message timestamps for spam detection"""
        current_time = time.time()
        for user_id in list(self.message_timestamps.keys()):
            self.message_timestamps[user_id] = [
                t for t in self.message_timestamps[user_id]
                if current_time - t <= SPAM_TIME_WINDOW
            ]
            if not self.message_timestamps[user_id]:
                del self.message_timestamps[user_id]

    @cleanup_old_timestamps.before_loop
    async def before_cleanup_timestamps(self):
        await self.bot.wait_until_ready()

    @tasks.loop(hours=24)
    async def cleanup_old_violations(self):
        """Reset violation counts for users who haven't had violations in 30 days"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            cutoff = time.time() - (30 * 86400)
            c.execute("DELETE FROM user_violations WHERE last_violation < ?", (cutoff,))
            deleted = c.rowcount
            conn.commit()
            conn.close()
            if deleted > 0:
                print(f"🧹 Reset {deleted} old violation record(s)")
        except Exception as e:
            print(f"Error cleaning old violations: {e}")

    @cleanup_old_violations.before_loop
    async def before_cleanup_violations(self):
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=30)
    async def cleanup_nuke_tracker(self):
        """Clean up old anti-nuke tracking data"""
        current_time = time.time()
        cutoff = current_time - NUKE_WINDOW_SECONDS
        
        for guild_id in list(self.nuke_tracker.keys()):
            for user_id in list(self.nuke_tracker[guild_id].keys()):
                tracker = self.nuke_tracker[guild_id][user_id]
                # Clean each action type
                for action_type in list(tracker.keys()):
                    tracker[action_type] = [(iid, ts) for iid, ts in tracker[action_type] if ts > cutoff]
                    if not tracker[action_type]:
                        del tracker[action_type]
                # Remove user if no actions left
                if not tracker:
                    del self.nuke_tracker[guild_id][user_id]
            # Remove guild if no users left
            if not self.nuke_tracker[guild_id]:
                del self.nuke_tracker[guild_id]

    @cleanup_nuke_tracker.before_loop
    async def before_cleanup_nuke(self):
        await self.bot.wait_until_ready()

    # ===== RAID DETECTION TASK =====

    @tasks.loop(seconds=RAID_CHECK_INTERVAL)
    async def anti_raid_check(self):
        """Check for raid conditions every 10 seconds"""
        now = time.time()
        guild_joins = {}
        
        # Filter joins from last 60 seconds
        recent_joins = [j for j in self.bot.join_timestamps if j['timestamp'] > now - 60]
        
        # Count joins per guild
        for join in recent_joins:
            guild_id = join['guild_id']
            guild_joins[guild_id] = guild_joins.get(guild_id, 0) + 1
        
        # Check for raid conditions
        for guild_id, count in guild_joins.items():
            if count > MAX_JOBS_PER_MINUTE:
                guild = self.bot.get_guild(int(guild_id))
                if guild:
                    # Check if raid detection is enabled
                    if not self.get_server_setting(guild.id, "raid_detection"):
                        continue
                    
                    print(f"🚨 [RAID] RAID DETECTED in {guild.name}: {count} joins/min")
                    
                    # Log to log channel only
                    log_channel = await self.get_log_channel(guild)
                    if log_channel:
                        embed = discord.Embed(
                            title="🚨 **RAID DETECTED!**",
                            description=f"**{count}** joins in the last minute (threshold: {MAX_JOBS_PER_MINUTE})",
                            color=discord.Color.red(),
                            timestamp=datetime.utcnow()
                        )
                        embed.add_field(name="Server", value=guild.name, inline=True)
                        embed.add_field(name="Join Rate", value=f"{count}/min", inline=True)
                        embed.set_footer(text="Use !raidstatus to check current status")
                        await log_channel.send(embed=embed)
                        print(f"📝 [RAID] Alert sent to log channel")

    @anti_raid_check.before_loop
    async def before_anti_raid(self):
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=JOIN_CLEANUP_INTERVAL)
    async def cleanup_old_joins(self):
        """Clean up old join timestamps"""
        now = time.time()
        self.bot.join_timestamps = [j for j in self.bot.join_timestamps if j['timestamp'] > now - 120]

    @cleanup_old_joins.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    # ===== TOGGLE COMMANDS =====

    @commands.command(name='hackoff')
    @commands.has_permissions(administrator=True)
    async def hack_off(self, ctx):
        """Turn off hacked account detection for this server"""
        if await self.check_duplicate(ctx):
            return
            
        if self.save_server_setting(ctx.guild.id, "hack_detection", False):
            embed = discord.Embed(
                title="🔴 Hacked Account Detection: OFF",
                description="The bot will no longer detect or punish hacked accounts sending duplicate messages.",
                color=discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="Use !hackon to re-enable")
            await ctx.send(embed=embed)
            print(f"⚠️ Hacked account detection turned OFF by {ctx.author} in {ctx.guild.name}")
        else:
            await ctx.send("❌ Failed to save settings. Please try again.")

    @commands.command(name='hackon')
    @commands.has_permissions(administrator=True)
    async def hack_on(self, ctx):
        """Turn on hacked account detection for this server"""
        if await self.check_duplicate(ctx):
            return
            
        if self.save_server_setting(ctx.guild.id, "hack_detection", True):
            embed = discord.Embed(
                title="🟢 Hacked Account Detection: ON",
                description="The bot will now detect and punish hacked accounts sending duplicate messages.",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="Use !hackoff to disable")
            await ctx.send(embed=embed)
            print(f"✅ Hacked account detection turned ON by {ctx.author} in {ctx.guild.name}")
        else:
            await ctx.send("❌ Failed to save settings. Please try again.")

    @commands.command(name='stopspam')
    @commands.has_permissions(administrator=True)
    async def stop_spam(self, ctx):
        """Turn off spam detection for this server"""
        if await self.check_duplicate(ctx):
            return
            
        if self.save_server_setting(ctx.guild.id, "spam_detection", False):
            embed = discord.Embed(
                title="🔴 Spam Detection: OFF",
                description=f"The bot will no longer detect or punish spamming ({SPAM_MESSAGE_COUNT} messages in {SPAM_TIME_WINDOW} seconds).",
                color=discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="Use !startspam to re-enable")
            await ctx.send(embed=embed)
            print(f"⚠️ Spam detection turned OFF by {ctx.author} in {ctx.guild.name}")
        else:
            await ctx.send("❌ Failed to save settings. Please try again.")

    @commands.command(name='startspam')
    @commands.has_permissions(administrator=True)
    async def start_spam(self, ctx):
        """Turn on spam detection for this server"""
        if await self.check_duplicate(ctx):
            return
            
        if self.save_server_setting(ctx.guild.id, "spam_detection", True):
            embed = discord.Embed(
                title="🟢 Spam Detection: ON",
                description=f"The bot will now detect and punish spamming ({SPAM_MESSAGE_COUNT} messages in {SPAM_TIME_WINDOW} seconds).",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="Use !stopspam to disable")
            await ctx.send(embed=embed)
            print(f"✅ Spam detection turned ON by {ctx.author} in {ctx.guild.name}")
        else:
            await ctx.send("❌ Failed to save settings. Please try again.")

    @commands.command(name='stopraid')
    @commands.has_permissions(administrator=True)
    async def stop_raid(self, ctx):
        """Turn off raid detection for this server"""
        if await self.check_duplicate(ctx):
            return
            
        if self.save_server_setting(ctx.guild.id, "raid_detection", False):
            embed = discord.Embed(
                title="🔴 Raid Detection: OFF",
                description=f"The bot will no longer alert about mass joins ({MAX_JOBS_PER_MINUTE}+ joins in 60 seconds).",
                color=discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="Use !startraid to re-enable")
            await ctx.send(embed=embed)
            print(f"⚠️ Raid detection turned OFF by {ctx.author} in {ctx.guild.name}")
        else:
            await ctx.send("❌ Failed to save settings. Please try again.")

    @commands.command(name='startraid')
    @commands.has_permissions(administrator=True)
    async def start_raid(self, ctx):
        """Turn on raid detection for this server"""
        if await self.check_duplicate(ctx):
            return
            
        if self.save_server_setting(ctx.guild.id, "raid_detection", True):
            embed = discord.Embed(
                title="🟢 Raid Detection: ON",
                description=f"The bot will now alert about mass joins ({MAX_JOBS_PER_MINUTE}+ joins in 60 seconds).",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="Use !stopraid to disable")
            await ctx.send(embed=embed)
            print(f"✅ Raid detection turned ON by {ctx.author} in {ctx.guild.name}")
        else:
            await ctx.send("❌ Failed to save settings. Please try again.")

    # ===== ANTI-NUKE TOGGLE COMMANDS =====

    @commands.command(name='antinukeoff')
    @commands.has_permissions(administrator=True)
    async def antinuke_off(self, ctx):
        """Turn off anti-nuke protection for this server"""
        if await self.check_duplicate(ctx):
            return
            
        if self.save_server_setting(ctx.guild.id, "anti_nuke", False):
            embed = discord.Embed(
                title="🔴 Anti-Nuke Protection: OFF",
                description="The bot will no longer detect or punish nuke attempts (mass deletions/creations).",
                color=discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="Use !antinukeon to re-enable")
            await ctx.send(embed=embed)
            print(f"⚠️ Anti-nuke turned OFF by {ctx.author} in {ctx.guild.name}")
        else:
            await ctx.send("❌ Failed to save settings. Please try again.")

    @commands.command(name='antinukeon')
    @commands.has_permissions(administrator=True)
    async def antinuke_on(self, ctx):
        """Turn on anti-nuke protection for this server"""
        if await self.check_duplicate(ctx):
            return
            
        if self.save_server_setting(ctx.guild.id, "anti_nuke", True):
            embed = discord.Embed(
                title="🟢 Anti-Nuke Protection: ON",
                description=(
                    f"The bot will now detect and punish nuke attempts.\n\n"
                    f"**Detection:** {NUKE_ACTION_THRESHOLD}+ destructive actions in {NUKE_WINDOW_SECONDS} seconds\n"
                    f"**Punishment:** All roles stripped from perpetrator\n"
                    f"**Whitelist:** Only AsaiyaBot role is immune"
                ),
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="Use !antinukeoff to disable")
            await ctx.send(embed=embed)
            print(f"✅ Anti-nuke turned ON by {ctx.author} in {ctx.guild.name}")
        else:
            await ctx.send("❌ Failed to save settings. Please try again.")

    # ===== STAFF ROLE MANAGEMENT COMMANDS =====

    @commands.group(name='staffroles', invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def staff_roles(self, ctx):
        """View or manage staff immunity roles"""
        if await self.check_duplicate(ctx):
            return
            
        staff_role_ids = self.get_staff_roles(ctx.guild.id)
        staff_roles = [ctx.guild.get_role(rid) for rid in staff_role_ids if ctx.guild.get_role(rid)]
        
        embed = discord.Embed(
            title="👥 Staff Immunity Roles",
            description="Users with these roles bypass spam and hacked account detection (but NOT anti-nuke - only AsaiyaBot role is immune to anti-nuke)",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        
        if staff_roles:
            role_list = "\n".join([f"• {r.mention} (ID: {r.id})" for r in staff_roles])
            embed.add_field(name="Current Staff Roles", value=role_list, inline=False)
        else:
            embed.add_field(name="Current Staff Roles", value="*No custom staff roles set*", inline=False)
            embed.add_field(name="Default Staff Roles", value=", ".join(DEFAULT_STAFF_ROLES), inline=False)
        
        embed.add_field(
            name="Commands",
            value=(
                "`!staffroles add @role1 @role2` - Add staff roles\n"
                "`!staffroles remove @role` - Remove a staff role\n"
                "`!staffroles clear` - Remove all custom staff roles"
            ),
            inline=False
        )
        await ctx.send(embed=embed)

    @staff_roles.command(name='add')
    @commands.has_permissions(administrator=True)
    async def staff_roles_add(self, ctx, *roles: discord.Role):
        """Add staff immunity roles"""
        if await self.check_duplicate(ctx):
            return
            
        if not roles:
            await ctx.send("❌ Please specify at least one role to add.")
            return
        
        added = 0
        for role in roles:
            if self.add_staff_role(ctx.guild.id, role.id, role.name, ctx.author.id):
                added += 1
                await ctx.send(f"✅ Added {role.mention} as a staff immunity role.")
            else:
                await ctx.send(f"❌ Failed to add {role.mention}.")
        
        if added > 0:
            await ctx.send(f"✅ Added {added} staff role(s).")

    @staff_roles.command(name='remove')
    @commands.has_permissions(administrator=True)
    async def staff_roles_remove(self, ctx, role: discord.Role):
        """Remove a staff immunity role"""
        if await self.check_duplicate(ctx):
            return
            
        if self.remove_staff_role(ctx.guild.id, role.id):
            await ctx.send(f"✅ Removed {role.mention} from staff immunity roles.")
        else:
            await ctx.send(f"❌ {role.mention} was not in the staff immunity list.")

    @staff_roles.command(name='clear')
    @commands.has_permissions(administrator=True)
    async def staff_roles_clear(self, ctx):
        """Remove all custom staff immunity roles"""
        if await self.check_duplicate(ctx):
            return
            
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM staff_immunity_roles WHERE guild_id = ?", (str(ctx.guild.id),))
            deleted = c.rowcount
            conn.commit()
            conn.close()
            
            if deleted > 0:
                self.staff_roles[ctx.guild.id] = []
                await ctx.send(f"✅ Removed {deleted} custom staff role(s).")
            else:
                await ctx.send("ℹ️ No custom staff roles to remove.")
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

    # ===== INVITE PROTECTION COMMANDS =====

    @commands.command(name='inviteoff')
    @commands.has_permissions(administrator=True)
    async def invite_off(self, ctx):
        """Turn off invite link protection for this server"""
        if await self.check_duplicate(ctx):
            return

        events_cog = self.bot.get_cog('Events')
        if not events_cog:
            await ctx.send("❌ Events cog not loaded.")
            return

        if events_cog.save_invite_protection_setting(ctx.guild.id, False):
            embed = discord.Embed(
                title="🚫 Invite Link Protection: OFF",
                description="The bot will no longer block Discord invite links.",
                color=discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="Use !inviteon to re-enable")
            await ctx.send(embed=embed)
            print(f"⚠️ Invite protection turned OFF by {ctx.author} in {ctx.guild.name}")
        else:
            await ctx.send("❌ Failed to save settings. Please try again.")

    @commands.command(name='inviteon')
    @commands.has_permissions(administrator=True)
    async def invite_on(self, ctx):
        """Turn on invite link protection for this server"""
        if await self.check_duplicate(ctx):
            return

        events_cog = self.bot.get_cog('Events')
        if not events_cog:
            await ctx.send("❌ Events cog not loaded.")
            return

        if events_cog.save_invite_protection_setting(ctx.guild.id, True):
            embed = discord.Embed(
                title="🔒 Invite Link Protection: ON",
                description="The bot will now block Discord invite links.",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="Use !inviteoff to disable")
            await ctx.send(embed=embed)
            print(f"✅ Invite protection turned ON by {ctx.author} in {ctx.guild.name}")
        else:
            await ctx.send("❌ Failed to save settings. Please try again.")

    # ===== STATUS COMMANDS =====

    @commands.command(name='antiraidstatus')
    @commands.has_permissions(administrator=True)
    async def antiraid_status(self, ctx):
        """Show current status of all anti-raid features for this server"""
        if await self.check_duplicate(ctx):
            return
            
        hack_enabled = self.get_server_setting(ctx.guild.id, "hack_detection")
        spam_enabled = self.get_server_setting(ctx.guild.id, "spam_detection")
        raid_enabled = self.get_server_setting(ctx.guild.id, "raid_detection")
        anti_nuke_enabled = self.get_server_setting(ctx.guild.id, "anti_nuke")
        
        staff_role_ids = self.get_staff_roles(ctx.guild.id)
        staff_roles = [ctx.guild.get_role(rid) for rid in staff_role_ids if ctx.guild.get_role(rid)]
        staff_names = [r.name for r in staff_roles] if staff_roles else DEFAULT_STAFF_ROLES
        
        embed = discord.Embed(
            title="🛡️ Anti-Raid System Status",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        
        hack_status = "🟢 **ON**" if hack_enabled else "🔴 **OFF**"
        embed.add_field(
            name="🤖 Hacked Account Detection",
            value=f"{hack_status}\nDetects same message in multiple channels within {MESSAGE_TRACK_WINDOW}s",
            inline=False
        )
        
        spam_status = "🟢 **ON**" if spam_enabled else "🔴 **OFF**"
        embed.add_field(
            name="💬 Spam Detection",
            value=f"{spam_status}\nDetects {SPAM_MESSAGE_COUNT}+ messages in {SPAM_TIME_WINDOW}s → {SPAM_TIMEOUT_MINUTES} min timeout",
            inline=False
        )
        
        raid_status = "🟢 **ON**" if raid_enabled else "🔴 **OFF**"
        embed.add_field(
            name="👥 Raid Detection",
            value=f"{raid_status}\nDetects {MAX_JOBS_PER_MINUTE}+ joins in 60s",
            inline=False
        )
        
        anti_nuke_status = "🟢 **ON**" if anti_nuke_enabled else "🔴 **OFF**"
        embed.add_field(
            name="💥 Anti-Nuke Protection",
            value=f"{anti_nuke_status}\n{NUKE_ACTION_THRESHOLD}+ destructive actions in {NUKE_WINDOW_SECONDS}s → strips all roles\n*Only {WHITELISTED_ROLE} role is immune*",
            inline=False
        )
        
        embed.add_field(
            name="👥 Staff Immunity Roles (Spam/Hack)",
            value=", ".join(staff_names[:5]) + ("..." if len(staff_names) > 5 else ""),
            inline=False
        )
        
        embed.set_footer(text="Use !hackon/hackoff, !startspam/stopspam, !startraid/stopraid, !antinukeon/antinukeoff to toggle")
        await ctx.send(embed=embed)

    @commands.command(name='raidstatus')
    @commands.has_permissions(kick_members=True)
    async def raidstatus(self, ctx):
        """Check the current join rate and raid status"""
        if await self.check_duplicate(ctx):
            return
            
        now = time.time()
        
        guild_joins = [j for j in self.bot.join_timestamps 
                      if j['guild_id'] == ctx.guild.id and j['timestamp'] > now - 60]
        
        join_rate = len(guild_joins)
        
        joins_5min = len([j for j in self.bot.join_timestamps 
                         if j['guild_id'] == ctx.guild.id and j['timestamp'] > now - 300])
        
        if join_rate >= MAX_JOBS_PER_MINUTE:
            status = "🔴 **RAID IN PROGRESS**"
            color = discord.Color.red()
        elif join_rate >= MAX_JOBS_PER_MINUTE * 0.7:
            status = "🟠 **Elevated Risk**"
            color = discord.Color.orange()
        elif join_rate >= MAX_JOBS_PER_MINUTE * 0.3:
            status = "🟡 **Moderate**"
            color = discord.Color.gold()
        else:
            status = "🟢 **Normal**"
            color = discord.Color.green()
        
        embed = discord.Embed(
            title="🚨 Anti-Raid Status",
            color=color,
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(name="Current Join Rate", value=f"**{join_rate}**/min", inline=True)
        embed.add_field(name="Threshold", value=f"**{MAX_JOBS_PER_MINUTE}**/min", inline=True)
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Joins (5 min)", value=str(joins_5min), inline=True)
        
        await ctx.send(embed=embed)

    @commands.command(name='raidhistory')
    @commands.has_permissions(administrator=True)
    async def raidhistory(self, ctx, minutes: int = 10):
        """Show join history for the last X minutes"""
        if await self.check_duplicate(ctx):
            return
            
        minutes = min(max(1, minutes), 60)
        now = time.time()
        cutoff = now - (minutes * 60)
        
        joins = [j for j in self.bot.join_timestamps 
                if j['guild_id'] == ctx.guild.id and j['timestamp'] > cutoff]
        
        if not joins:
            await ctx.send(f"📭 No joins in the last {minutes} minutes.")
            return
            
        minute_counts = {}
        for join in joins:
            minute_key = int((join['timestamp'] - cutoff) / 60)
            minute_counts[minute_key] = minute_counts.get(minute_key, 0) + 1
        
        embed = discord.Embed(
            title=f"📊 Join History - Last {minutes} Minutes",
            description=f"Total joins: **{len(joins)}**",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        
        chart = ""
        max_count = max(minute_counts.values()) if minute_counts else 1
        
        for i in range(minutes):
            count = minute_counts.get(i, 0)
            bar_length = int((count / max_count) * 20) if max_count > 0 else 0
            bar = "█" * bar_length + "░" * (20 - bar_length)
            minute_label = f"Min {i+1}:"
            chart += f"{minute_label:<6} {bar} {count}\n"
        
        embed.add_field(name="Join Rate per Minute", value=f"```{chart}```", inline=False)
        
        await ctx.send(embed=embed)

    @commands.command(name='raidclear')
    @commands.has_permissions(administrator=True)
    async def raidclear(self, ctx):
        """Clear the join history for this server"""
        if await self.check_duplicate(ctx):
            return
            
        self.bot.join_timestamps = [j for j in self.bot.join_timestamps 
                                    if j['guild_id'] != ctx.guild.id]
        
        try:
            conn = self.get_cached_connection(ctx.guild.id)
            if conn:
                c = conn.cursor()
                c.execute("DELETE FROM join_timestamps WHERE guild_id = ?", (str(ctx.guild.id),))
                conn.commit()
        except Exception as e:
            print(f"Error clearing join timestamps: {e}")
            
        await ctx.send("✅ Join history cleared for this server.")

    @commands.command(name='resetviolations')
    @commands.has_permissions(administrator=True)
    async def reset_violations(self, ctx, member: discord.Member):
        """Reset a user's violation count for this server"""
        if await self.check_duplicate(ctx):
            return
            
        if self.reset_violation_count(member.id, ctx.guild.id):
            await ctx.send(f"✅ Reset violation count for {member.mention}")
        else:
            await ctx.send(f"❌ Failed to reset violation count for {member.mention}")


async def setup(bot):
    await bot.add_cog(AntiRaid(bot))
