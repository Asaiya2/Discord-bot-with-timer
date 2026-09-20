import discord
from discord.ext import commands
import sqlite3
import time
import asyncio
import os
import re  # <-- MAKE SURE THIS IS HERE
import unicodedata
from datetime import datetime

# ===== CONFIGURATION =====
DB_FOLDER = r"C:\Users\Kelly\Desktop\discord database"
MAIN_DB_PATH = os.path.join(DB_FOLDER, "asaiya_bot.db")

BOT_CHANNEL_NAME = "asaiya-bot"
VERIFY_CHANNEL_NAME = "asaiya-verification"
HUB_CHANNEL_NAME = "asaiya-hub"

# =============================================================
# BOT ROLES & CONSTANTS
# =============================================================
BOT_ROLE = "AsaiyaBot"
PASS_ROLE = "AsaiyaPass"
CLEAR_ROLE = "AsaiyaClear"
FILTER_CACHE_TTL = 60
SNIPE_LIMIT = 100

PROTECTED_CHANNELS_TABLE = "protected_channels"
MESSAGE_BACKUP_TABLE = "message_backup"
DELETED_CHANNELS_TABLE = "deleted_channels"
REACTION_ROLES_TABLE = "reaction_roles"
REACTION_ROLE_ITEMS_TABLE = "reaction_role_items"

NUKE_APPROVAL_CHANNEL = 1477599424208179303
NUKE_APPROVAL_SERVER = 1476790704914305134
NUKE_APPROVE_ROLE = "."

# Default staff role names (will be overridden by database)
DEFAULT_STAFF_ROLES = ["AsaiyaBot", "AsaiyaKick", "AsaiyaBan", "AsaiyaPass", "AsaiyaClear", "asaiya-support"]


class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Initialize bot attributes if they don't exist
        if not hasattr(self.bot, 'db_connections'):
            self.bot.db_connections = {}
        if not hasattr(self.bot, 'last_db_use'):
            self.bot.last_db_use = {}
        if not hasattr(self.bot, 'snipe_cache'):
            self.bot.snipe_cache = {}
        if not hasattr(self.bot, 'filter_cache'):
            self.bot.filter_cache = {}
        if not hasattr(self.bot, 'filter_cache_time'):
            self.bot.filter_cache_time = {}
        if not hasattr(self.bot, 'active_tickets'):
            self.bot.active_tickets = {}
        if not hasattr(self.bot, 'pending_nukes'):
            self.bot.pending_nukes = {}
        if not hasattr(self.bot, 'join_timestamps'):
            self.bot.join_timestamps = []
        if not hasattr(self.bot, 'guild_template_history'):
            self.bot.guild_template_history = {}
        if not hasattr(self.bot, 'active_events'):
            self.bot.active_events = {}  # Store active events: {message_id: event_data}
        
        # Feature toggles cache (loaded from database)
        self.word_filter_enabled = {}  # {guild_id: bool}
        self.invite_protection_enabled = {}  # {guild_id: bool}
        self.staff_immunity_roles = {}  # {guild_id: [role_ids]}
        
        # Track processed commands to prevent duplicates
        self.processed_commands = {}
        
        # Track channel warning cooldowns (for other warnings)
        self.channel_warnings = {}
        
        # Flag to track if online message has been sent
        self.online_message_sent = False
        
        # Load settings from database
        self.load_all_settings()
        
        print(f"✅ Events cog initialized (ID: {id(self)})")
        print(f"   Loaded word filter settings for {len(self.word_filter_enabled)} server(s)")
        print(f"   Loaded invite protection settings for {len(self.invite_protection_enabled)} server(s)")

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
            
            # Load word filter settings from anti_raid_settings
            c.execute("SELECT guild_id, word_filter FROM anti_raid_settings")
            rows = c.fetchall()
            for guild_id, enabled in rows:
                self.word_filter_enabled[int(guild_id)] = bool(enabled)
            
            # Load invite protection settings
            c.execute("SELECT guild_id, invite_protection FROM anti_raid_settings")
            rows = c.fetchall()
            for guild_id, enabled in rows:
                self.invite_protection_enabled[int(guild_id)] = bool(enabled)
            
            # Load staff immunity roles
            c.execute("SELECT guild_id, role_id FROM staff_immunity_roles")
            rows = c.fetchall()
            for guild_id, role_id in rows:
                gid = int(guild_id)
                if gid not in self.staff_immunity_roles:
                    self.staff_immunity_roles[gid] = []
                self.staff_immunity_roles[gid].append(int(role_id))
            
            conn.close()
        except Exception as e:
            print(f"Error loading settings: {e}")

    def save_word_filter_setting(self, guild_id, enabled):
        """Save word filter setting to database"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            
            # Ensure anti_raid_settings table has the column
            c.execute('''CREATE TABLE IF NOT EXISTS anti_raid_settings
                         (guild_id TEXT PRIMARY KEY,
                          hack_detection INTEGER DEFAULT 1,
                          spam_detection INTEGER DEFAULT 1,
                          raid_detection INTEGER DEFAULT 1,
                          word_filter INTEGER DEFAULT 1,
                          invite_protection INTEGER DEFAULT 1,
                          updated_at REAL)''')
            
            # Add columns if they don't exist (for existing databases)
            try:
                c.execute("ALTER TABLE anti_raid_settings ADD COLUMN word_filter INTEGER DEFAULT 1")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                c.execute("ALTER TABLE anti_raid_settings ADD COLUMN invite_protection INTEGER DEFAULT 1")
            except sqlite3.OperationalError:
                pass  # Column already exists
            
            # Insert or update - preserve all other columns
            c.execute('''INSERT INTO anti_raid_settings
                         (guild_id, hack_detection, spam_detection, raid_detection, word_filter, invite_protection, updated_at)
                         VALUES (?, 1, 1, 1, ?, 1, ?)
                         ON CONFLICT(guild_id) DO UPDATE SET
                             word_filter = excluded.word_filter,
                             updated_at = excluded.updated_at''',
                      (str(guild_id), 1 if enabled else 0, time.time()))
            
            conn.commit()
            conn.close()
            self.word_filter_enabled[guild_id] = enabled
            return True
        except Exception as e:
            print(f"Error saving word filter setting: {e}")
            return False

    def save_invite_protection_setting(self, guild_id, enabled):
        """Save invite protection setting to database"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            
            # Insert or update - preserve all other columns
            c.execute('''INSERT INTO anti_raid_settings
                         (guild_id, hack_detection, spam_detection, raid_detection, word_filter, invite_protection, updated_at)
                         VALUES (?, 1, 1, 1, 1, ?, ?)
                         ON CONFLICT(guild_id) DO UPDATE SET
                             invite_protection = excluded.invite_protection,
                             updated_at = excluded.updated_at''',
                      (str(guild_id), 1 if enabled else 0, time.time()))
            
            conn.commit()
            conn.close()
            self.invite_protection_enabled[guild_id] = enabled
            return True
        except Exception as e:
            print(f"Error saving invite protection setting: {e}")
            return False

    def is_word_filter_enabled(self, guild_id):
        """Check if word filter is enabled for a guild"""
        return self.word_filter_enabled.get(guild_id, True)  # Default to enabled

    def is_invite_protection_enabled(self, guild_id):
        """Check if invite protection is enabled for a guild"""
        return self.invite_protection_enabled.get(guild_id, True)  # Default to enabled

    def is_staff(self, member, guild_id):
        """Check if a member has AsaiyaBot role (only role that bypasses filter)"""
        if not isinstance(member, discord.Member):
            return False
        
        # ONLY AsaiyaBot role bypasses the filter
        for role in member.roles:
            if role.name == "AsaiyaBot":
                return True
        
        return False

    def can_bypass_filter(self, member, word):
        """Check if a member can bypass a specific filtered word"""
        try:
            conn = self.get_cached_connection(member.guild.id)
            if not conn:
                return False
            c = conn.cursor()
            c.execute("SELECT role_id FROM filter_bypass_roles WHERE word = ?", (word,))
            bypass_role_ids = [r[0] for r in c.fetchall()]
            for role in member.roles:
                if str(role.id) in bypass_role_ids:
                    return True
            return False
        except Exception as e:
            print(f"Error checking filter bypass: {e}")
            return False

    def normalize_leet(self, text):
        """Convert leet speak numbers back to letters (3→e, 4→a, 5→s, etc.)"""
        leet_map = {
            '0': 'o', '3': 'e', '4': 'a', '5': 's', '6': 'g',
            '7': 't', '8': 'b', '1': 'i', '2': 'z', '9': 'g',
            '³': 'e', '⁴': 'a', '⁵': 's', '⁶': 'g', '⁷': 't',
            '⁸': 'b', '¹': 'i', '²': 'z', '⁹': 'g', '⁰': 'o',
            # Symbol replacements
            '√': 'u',      # square root looks like u
            '@': 'a',      # at symbol looks like a
            '$': 's',      # dollar sign looks like s
            '€': 'e',      # euro sign looks like e
            '£': 'l',      # pound sign looks like l
            '!': 'i',      # exclamation looks like i
            '?': '?',      # keep as is
            '+': 't',      # plus looks like t
            '×': 'x',      # multiplication looks like x
            '÷': 'o',      # division looks like o
            '%': 'o',      # percent looks like o (kinda)
            '&': 'e',      # ampersand looks like e
            '*': 'x',      # asterisk looks like x
            '#': 'h',      # hash looks like h
            '~': 'n',      # tilde looks like n
            '`': 'i',      # backtick looks like i
            '´': 'i',      # acute accent
            '¨': 'u',      # diaeresis
            '^': 'u',      # caret looks like u
            '\\': 'l',     # backslash looks like l
            '|': 'i',      # pipe looks like i
            '/': 'l',      # forward slash looks like l
            '(': 'c',      # parenthesis looks like c
            ')': 'c',      # parenthesis looks like c
            '[': 'l',      # bracket looks like l
            ']': 'l',      # bracket looks like l
            '{': 'l',      # brace looks like l
            '}': 'l',      # brace looks like l
            '<': 'c',      # less than looks like c
            '>': 'c',      # greater than looks like c
            '=': 'e',      # equals looks like e
            '_': 'u',      # underscore looks like u
            '-': 'u',      # dash looks like u
        }
        result = []
        for char in text.lower():
            result.append(leet_map.get(char, char))
        return ''.join(result)

    def normalize_text(self, text):
        """Convert accented characters to their base ASCII equivalents (é -> e, ç -> c, etc.)"""
        # Normalize to NFKD form (decomposes accented characters)
        normalized = unicodedata.normalize('NFKD', text)
        # Encode to ASCII, ignoring non-ASCII characters, then decode back
        ascii_text = normalized.encode('ASCII', 'ignore').decode('ASCII')
        # Remove everything except letters a-z
        import re
        return re.sub(r'[^a-z]', '', ascii_text.lower())

    def get_filter_reason(self, guild_id, word):
        """Get the reason for a filtered word"""
        try:
            conn = self.get_cached_connection(guild_id)
            if not conn:
                return None
            c = conn.cursor()
            c.execute("SELECT reason FROM filter_words WHERE word = ?", (word,))
            result = c.fetchone()
            if result and result[0]:
                return result[0]
            return None
        except Exception as e:
            print(f"Error getting filter reason: {e}")
            return None

    def get_time_afk(self, timestamp):
        """Format AFK duration"""
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

    # ===== INTERNAL HELPERS =====

    def get_server_db_path(self, guild_id):
        """Get database path for a specific server using the server name from main database"""
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
                return result[0]  # Return the stored db_path
            
            # If no db_path found, return None (server not activated)
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
                if current_time - last_used > 300:  # 5 minutes timeout
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
                # Connection is dead, remove it
                try:
                    self.bot.db_connections[guild_id].close()
                except:
                    pass
                if guild_id in self.bot.db_connections:
                    del self.bot.db_connections[guild_id]

        # Get database path
        db_path = self.get_server_db_path(guild_id)
        if not db_path:
            # Server not activated - return None instead of raising exception
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

    def get_verify_role(self, guild_id):
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT role_id FROM verify_settings WHERE guild_id = ?", (str(guild_id),))
            result = c.fetchone()
            conn.close()
            return result[0] if result else None
        except:
            return None

    async def get_log_channel(self, guild):
        try:
            conn = self.get_cached_connection(guild.id)
            c = conn.cursor()
            c.execute("SELECT log_channel_id FROM log_channels")
            result = c.fetchone()
            if result and result[0]:
                return guild.get_channel(int(result[0]))
        except:
            pass
        return None

    async def get_welcome_channel(self, guild):
        try:
            conn = self.get_cached_connection(guild.id)
            c = conn.cursor()
            c.execute("SELECT welcome_channel_id FROM log_channels")
            result = c.fetchone()
            if result and result[0]:
                return guild.get_channel(int(result[0]))
        except:
            pass
        return None

    async def get_leave_channel(self, guild):
        try:
            conn = self.get_cached_connection(guild.id)
            c = conn.cursor()
            c.execute("SELECT leave_channel_id FROM log_channels")
            result = c.fetchone()
            if result and result[0]:
                return guild.get_channel(int(result[0]))
        except:
            pass
        return None

    async def get_mlog_channel(self, guild):
        """Get the message log channel for this server (respects mlog_enabled flag)"""
        try:
            conn = self.get_cached_connection(guild.id)
            if conn:
                c = conn.cursor()
                try:
                    c.execute("ALTER TABLE log_channels ADD COLUMN mlog_channel_id TEXT")
                    conn.commit()
                except:
                    pass
                try:
                    c.execute("ALTER TABLE log_channels ADD COLUMN mlog_enabled INTEGER DEFAULT 1")
                    conn.commit()
                except:
                    pass
                c.execute("SELECT mlog_channel_id, mlog_enabled FROM log_channels")
                result = c.fetchone()
                if result and result[0]:
                    enabled = result[1] if result[1] is not None else 1
                    if not enabled:
                        return None
                    return guild.get_channel(int(result[0]))
        except Exception as e:
            print(f"Error getting mlog channel: {e}")
        return None

    def register_server(self, guild_id, guild_name, owner_id):
        try:
            main_conn = sqlite3.connect(MAIN_DB_PATH)
            c = main_conn.cursor()
            
            # Ensure server_counter table exists
            c.execute('''CREATE TABLE IF NOT EXISTS server_counter
                        (id INTEGER PRIMARY KEY, last_number INTEGER)''')
            c.execute("INSERT OR IGNORE INTO server_counter (id, last_number) VALUES (1, 0)")
            
            c.execute("SELECT server_number FROM servers WHERE guild_id = ?", (str(guild_id),))
            existing = c.fetchone()
            if existing:
                server_number = existing[0]
            else:
                c.execute("SELECT last_number FROM server_counter WHERE id = 1")
                last = c.fetchone()
                last_number = last[0] if last else 0
                server_number = last_number + 1
                c.execute("UPDATE server_counter SET last_number = ? WHERE id = 1", (server_number,))
                c.execute("INSERT INTO servers (guild_id, server_number, added_at, name, owner_id) VALUES (?, ?, ?, ?, ?)",
                          (str(guild_id), server_number, time.time(), guild_name, str(owner_id)))
                main_conn.commit()
            main_conn.close()
            return os.path.join(DB_FOLDER, f"asaiya_bot_server{server_number}.db")
        except Exception as e:
            print(f"Error registering server {guild_name}: {e}")
            return None

    def load_nuke_requests(self):
        pending = {}
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS persistent_nuke_requests
                        (guild_id TEXT PRIMARY KEY,
                         requester_id TEXT,
                         approval_msg_id TEXT,
                         guild_name TEXT,
                         source_channel_id TEXT)''')
            c.execute("SELECT guild_id, requester_id, approval_msg_id, guild_name, source_channel_id FROM persistent_nuke_requests")
            rows = c.fetchall()
            conn.close()
            for row in rows:
                guild_id, requester_id, approval_msg_id, guild_name, source_channel_id = row
                pending[int(guild_id)] = {
                    'requester_id': int(requester_id),
                    'approval_msg_id': int(approval_msg_id),
                    'guild_id': int(guild_id),
                    'guild_name': guild_name,
                    'source_channel_id': int(source_channel_id)
                }
        except Exception as e:
            print(f"Error loading nuke requests: {e}")
        return pending

    def delete_nuke_request(self, guild_id):
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM persistent_nuke_requests WHERE guild_id = ?", (str(guild_id),))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error deleting nuke request: {e}")

    # ===== TOGGLE COMMANDS =====

    @commands.command(name='filteroff')
    @commands.has_permissions(administrator=True)
    async def filter_off(self, ctx):
        """Turn off word filter for this server"""
        if await self.check_duplicate(ctx):
            return
            
        if self.save_word_filter_setting(ctx.guild.id, False):
            embed = discord.Embed(
                title="🔇 Word Filter: OFF",
                description="The bot will no longer filter inappropriate words.",
                color=discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="Use !filteron to re-enable")
            await ctx.send(embed=embed)
            print(f"⚠️ Word filter turned OFF by {ctx.author} in {ctx.guild.name}")
        else:
            await ctx.send("❌ Failed to save settings. Please try again.")

    @commands.command(name='filteron')
    @commands.has_permissions(administrator=True)
    async def filter_on(self, ctx):
        """Turn on word filter for this server"""
        if await self.check_duplicate(ctx):
            return
            
        if self.save_word_filter_setting(ctx.guild.id, True):
            embed = discord.Embed(
                title="🔊 Word Filter: ON",
                description="The bot will now filter inappropriate words.",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="Use !filteroff to disable")
            await ctx.send(embed=embed)
            print(f"✅ Word filter turned ON by {ctx.author} in {ctx.guild.name}")
        else:
            await ctx.send("❌ Failed to save settings. Please try again.")

    @commands.command(name='refreshfilter')
    @commands.has_permissions(administrator=True)
    async def refresh_filter(self, ctx):
        """Force refresh the filter cache"""
        guild_id = ctx.guild.id
        if guild_id in self.bot.filter_cache:
            del self.bot.filter_cache[guild_id]
        if guild_id in self.bot.filter_cache_time:
            del self.bot.filter_cache_time[guild_id]
        await ctx.send("✅ Filter cache refreshed! Try the filtered word again.")

    # ===== EVENT SYSTEM =====

    @commands.group(name='event', invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def event(self, ctx):
        """Event management commands"""
        if await self.check_duplicate(ctx):
            return
            
        embed = discord.Embed(
            title="📅 Event Commands",
            description="Create and manage server events",
            color=discord.Color.purple()
        )
        embed.add_field(name="`!event create`", value="Create a new event", inline=False)
        embed.add_field(name="`!event end`", value="End an event", inline=False)
        embed.add_field(name="`!event list`", value="List active events", inline=False)
        await ctx.send(embed=embed)

    @event.command(name='create')
    @commands.has_permissions(administrator=True)
    async def event_create(self, ctx, title: str, required_role: discord.Role = None):
        """Create a new event with join/leave buttons"""
        if await self.check_duplicate(ctx):
            return
            
        # Create the event view with buttons
        class EventView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=None)
                self.participants = set()
                self.event_channel = ctx.channel
                self.event_title = title
                self.required_role = required_role
                
            @discord.ui.button(label="✅ Join Event", style=discord.ButtonStyle.green, custom_id=f"join_event_{int(time.time())}")
            async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                if self.required_role and self.required_role not in interaction.user.roles:
                    await interaction.response.send_message(f"❌ You need the {self.required_role.mention} role to join!", ephemeral=True)
                    return
                
                if interaction.user.id in self.participants:
                    await interaction.response.send_message("❌ You're already in this event!", ephemeral=True)
                    return
                
                self.participants.add(interaction.user.id)
                await interaction.response.send_message("✅ You've joined the event!", ephemeral=True)
                
                # Update the embed
                embed = interaction.message.embeds[0]
                participant_count = len(self.participants)
                
                # Find and update the participants field
                for i, field in enumerate(embed.fields):
                    if field.name == "Participants":
                        embed.set_field_at(i, name="Participants", value=f"Current count: {participant_count}", inline=False)
                        break
                else:
                    embed.add_field(name="Participants", value=f"Current count: {participant_count}", inline=False)
                
                await interaction.message.edit(embed=embed)
            
            @discord.ui.button(label="❌ Leave Event", style=discord.ButtonStyle.red, custom_id=f"leave_event_{int(time.time())}")
            async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id not in self.participants:
                    await interaction.response.send_message("❌ You're not in this event!", ephemeral=True)
                    return
                
                self.participants.remove(interaction.user.id)
                await interaction.response.send_message("✅ You've left the event!", ephemeral=True)
                
                # Update the embed
                embed = interaction.message.embeds[0]
                participant_count = len(self.participants)
                
                for i, field in enumerate(embed.fields):
                    if field.name == "Participants":
                        if participant_count > 0:
                            embed.set_field_at(i, name="Participants", value=f"Current count: {participant_count}", inline=False)
                        else:
                            embed.remove_field(i)
                        break
                
                await interaction.message.edit(embed=embed)
        
        view = EventView()
        
        embed = discord.Embed(
            title=f"📅 {title}",
            description="Click below to join or leave this event!",
            color=discord.Color.purple()
        )
        
        if required_role:
            embed.add_field(name="Requirements", value=f"Requires {required_role.mention} role", inline=False)
        
        embed.add_field(name="Participants", value="Current count: 0", inline=False)
        embed.set_footer(text=f"Hosted by {ctx.author}")
        embed.timestamp = datetime.utcnow()
        
        event_msg = await ctx.send(embed=embed, view=view)
        
        # Store event data
        if not hasattr(self.bot, 'active_events'):
            self.bot.active_events = {}
            
        self.bot.active_events[event_msg.id] = {
            'channel_id': ctx.channel.id,
            'message_id': event_msg.id,
            'host_id': ctx.author.id,
            'title': title,
            'required_role': required_role.id if required_role else None,
            'participants': view.participants,
            'created_at': time.time()
        }
        
        await ctx.send(f"✅ Event created! Use `!event end {event_msg.id}` to end it early.", delete_after=10)

    @event.command(name='end')
    @commands.has_permissions(administrator=True)
    async def event_end(self, ctx, message_id: str = None):
        """End an event early. Usage: !event end [message_id]"""
        if await self.check_duplicate(ctx):
            return
            
        if not message_id:
            await ctx.send("❌ Please provide a message ID! Usage: `!event end 123456789`")
            return
            
        try:
            msg_id = int(message_id)
        except ValueError:
            await ctx.send("❌ Invalid message ID!")
            return
            
        if not hasattr(self.bot, 'active_events') or msg_id not in self.bot.active_events:
            await ctx.send("❌ Event not found or already ended!")
            return
            
        event_data = self.bot.active_events.pop(msg_id)
        
        try:
            channel = self.bot.get_channel(event_data['channel_id'])
            if channel:
                msg = await channel.fetch_message(msg_id)
                if msg:
                    embed = msg.embeds[0]
                    embed.title = f"✅ Event Ended: {event_data['title']}"
                    embed.color = discord.Color.green()
                    embed.add_field(name="Final Participants", value=f"**{len(event_data['participants'])}** joined", inline=False)
                    await msg.edit(embed=embed, view=None)
        except:
            pass
            
        await ctx.send(f"✅ Event ended early! Total participants: {len(event_data['participants'])}")

    @event.command(name='list')
    @commands.has_permissions(administrator=True)
    async def event_list(self, ctx):
        """List all active events in this server"""
        if await self.check_duplicate(ctx):
            return
            
        if not hasattr(self.bot, 'active_events'):
            self.bot.active_events = {}
            
        # Find events in this server
        guild_events = []
        for msg_id, data in self.bot.active_events.items():
            channel = self.bot.get_channel(data['channel_id'])
            if channel and channel.guild.id == ctx.guild.id:
                guild_events.append(data)
        
        if not guild_events:
            await ctx.send("📭 No active events in this server.")
            return
            
        embed = discord.Embed(
            title="📅 Active Events",
            description=f"Found **{len(guild_events)}** active event(s)",
            color=discord.Color.purple()
        )
        
        for event in guild_events:
            channel = self.bot.get_channel(event['channel_id'])
            channel_name = channel.mention if channel else "Unknown"
            
            embed.add_field(
                name=f"**{event['title']}**",
                value=(
                    f"Channel: {channel_name}\n"
                    f"Participants: {len(event['participants'])}\n"
                    f"Message ID: `{event['message_id']}`"
                ),
                inline=False
            )
        
        await ctx.send(embed=embed)

    # ===== EVENTS =====

    @commands.Cog.listener()
    async def on_ready(self):
        print(f'✅ Asaiya is ready! Logged in as {self.bot.user}')
        print("""
░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
░░   █████╗ ███████╗ █████╗ ██╗██╗   ██╗ █████╗             ░░
░░  ██╔══██╗██╔════╝██╔══██╗██║╚██╗ ██╔╝██╔══██╗            ░░
░░  ███████║███████╗███████║██║ ╚████╔╝ ███████║            ░░
░░  ██╔══██║╚════██║██╔══██║██║  ╚██╔╝  ██╔══██║            ░░
░░  ██║  ██║███████║██║  ██║██║   ██║   ██║  ██║            ░░
░░  ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝   ╚═╝   ╚═╝  ╚═╝            ░░
░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
""")

        # ===== LOAD PERSISTENT DATA =====
        self.bot.pending_nukes = self.load_nuke_requests()
        print(f"✅ Loaded {len(self.bot.pending_nukes)} pending nuke requests")

        # ===== RELOAD ACTIVE TICKETS =====
        ticket_count = 0
        for guild in self.bot.guilds:
            try:
                conn = self.get_cached_connection(guild.id)
                if not conn:  # Skip if no connection (server not activated)
                    continue
                    
                c = conn.cursor()
                c.execute('''CREATE TABLE IF NOT EXISTS active_tickets
                            (user_id TEXT, channel_id TEXT, guild_id TEXT)''')
                c.execute("SELECT user_id, channel_id FROM active_tickets WHERE guild_id = ?",
                          (str(guild.id),))
                rows = c.fetchall()
                if rows:
                    guild_id_str = str(guild.id)
                    if guild_id_str not in self.bot.active_tickets:
                        self.bot.active_tickets[guild_id_str] = {}
                    for user_id, channel_id in rows:
                        self.bot.active_tickets[guild_id_str][user_id] = int(channel_id)
                        ticket_count += 1
            except Exception as e:
                print(f"Error reloading tickets for {guild.name}: {e}")
        print(f"✅ Reloaded {ticket_count} active ticket(s)")

        # ===== HIDE VERIFY CHANNEL FROM VERIFIED USERS =====
        hidden_total = 0
        for guild in self.bot.guilds:
            verify_channel = discord.utils.get(guild.text_channels, name=VERIFY_CHANNEL_NAME)
            if not verify_channel:
                continue
            role_id = self.get_verify_role(str(guild.id))
            if not role_id:
                continue
            role = guild.get_role(int(role_id))
            if not role:
                continue
            hidden = 0
            for member in guild.members:
                if role in member.roles:
                    try:
                        await verify_channel.set_permissions(member, read_messages=False, view_channel=False)
                        hidden += 1
                    except:
                        pass
            if hidden > 0:
                print(f"🔒 Hidden #{VERIFY_CHANNEL_NAME} from {hidden} verified users in {guild.name}")
                hidden_total += hidden
        if hidden_total > 0:
            print(f"✅ Total hidden from {hidden_total} verified users across all servers")

        # ===== SCAN FOR UNVERIFIED USERS =====
        print("\n🔍 Scanning for unverified users...")
        total_unverified = 0
        servers_with_verification = 0
        
        for guild in self.bot.guilds:
            role_id = self.get_verify_role(str(guild.id))
            if not role_id:
                continue
            servers_with_verification += 1
            role = guild.get_role(int(role_id))
            if not role:
                continue
            unverified = sum(1 for m in guild.members if not m.bot and role not in m.roles)
            total_unverified += unverified
            if unverified > 0:
                print(f"   📊 {guild.name}: {unverified} unverified users")
        
        if servers_with_verification == 0:
            print("   ⚠️ No servers have verification set up")
        elif total_unverified == 0:
            print("   ✅ No unverified users found")
        else:
            print(f"   ⚠️ Total unverified: {total_unverified} across {servers_with_verification} servers")
        print("✅ Server scan complete\n")

        # ===== START BACKGROUND TASKS =====
        try:
            tasks_cog = self.bot.get_cog('Tasks')
            if tasks_cog and hasattr(tasks_cog, 'start_all_tasks'):
                tasks_cog.start_all_tasks()
                print("✅ Background tasks started")
            else:
                print("⚠️ Tasks cog not loaded — background tasks not started")
        except Exception as e:
            print(f"⚠️ Error starting tasks: {e}")

        # ===== ADD PERSISTENT VIEWS =====
        # Looks up TicketView from whichever cog has "ticket" in its name
        # so it works regardless of filename (tickets.py, 2tickets.py, etc.)
        try:
            import sys
            tickets_cog = next(
                (cog for name, cog in self.bot.cogs.items() if 'ticket' in name.lower()),
                None
            )
            if tickets_cog:
                cog_module = sys.modules[tickets_cog.__module__]
                TicketView = getattr(cog_module, 'TicketView', None)
                if TicketView:
                    self.bot.add_view(TicketView())
                    print("✅ Persistent view added: TicketView")
                else:
                    print("⚠️ TicketView class not found in Tickets cog module")
            else:
                print("⚠️ No Tickets cog loaded — TicketView skipped")
        except Exception as e:
            print(f"⚠️ Error adding persistent views: {e}")

        # ===== SEND ONLINE MESSAGE (ONLY ONCE) =====
        if not self.online_message_sent:
            online_channels_found = 0
            for guild in self.bot.guilds:
                for channel in guild.text_channels:
                    if channel.name == BOT_CHANNEL_NAME:
                        try:
                            await channel.send("") # THIS IS WHERE TO UPDATE MESSAGES ON STARTUP - SEXCHAT
                            online_channels_found += 1
                            await asyncio.sleep(0.01)
                        except Exception as e:
                            print(f"⚠️ Could not send online message in {guild.name}: {e}")
                        break
            
            if online_channels_found > 0:
                print(f"✅ Sent online message in {online_channels_found} server(s)")
            else:
                print("⚠️ No #asaiya-bot channels found to send online message")
            
            self.online_message_sent = True

        # ===== PRELOAD FILTER CACHES =====
        for guild in self.bot.guilds:
            try:
                conn = self.get_cached_connection(guild.id)
                if conn:
                    c = conn.cursor()
                    c.execute("SELECT word, reason FROM filter_words")
                    rows = c.fetchall()
                    if rows:
                        self.bot.filter_cache[guild.id] = [(row[0].lower(), row[1]) for row in rows]
                        self.bot.filter_cache_time[guild.id] = time.time()
                        print(f"📋 Preloaded {len(rows)} filter words for {guild.name}")
            except Exception as e:
                pass

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        print(f"📥 Bot joined: {guild.name} (ID: {guild.id})")

        # Register the server
        self.register_server(guild.id, guild.name, guild.owner_id)

        # ── Log to owner log channel ──────────────────────────────────────
        try:
            log_channel = self.bot.get_channel(1477349072070246480)
            if log_channel:
                log_embed = discord.Embed(
                    title="📥 Bot Joined Server",
                    description=f"**{guild.name}** (ID: `{guild.id}`)",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                log_embed.add_field(name="Members", value=str(guild.member_count), inline=True)
                log_embed.add_field(name="Owner", value=f"<@{guild.owner_id}>", inline=True)
                log_embed.add_field(name="Key System", value="🔴 Disabled" if not getattr(self.bot, 'key_system_enabled', True) else "🟢 Enabled", inline=True)
                await log_channel.send(embed=log_embed)
        except Exception as e:
            print(f"⚠️ Could not log guild join: {e}")

        # ── Find a channel to send welcome message ────────────────────────
        target_channel = (
            discord.utils.get(guild.text_channels, name="general")
            or guild.system_channel
            or next((ch for ch in guild.text_channels if ch.permissions_for(guild.me).send_messages), None)
        )

        key_enabled = getattr(self.bot, 'key_system_enabled', True)

        if not key_enabled:
            # ── Key system OFF: auto-register server and send simplified message ──
            try:
                admin_cog = self.bot.get_cog('Admin')
                if admin_cog and hasattr(admin_cog, 'auto_register_server'):
                    await admin_cog.auto_register_server(guild)
                # Note: auto_register_server handles the welcome message itself
            except Exception as e:
                print(f"⚠️ Could not auto-register {guild.name}: {e}")
        else:
            # ── Key system ON: send normal activation instructions ────────────
            if target_channel:
                embed = discord.Embed(
                    title="👋 Thanks for Adding Asaiya Bot!",
                    description="I'm here to help make your server better!\n\n**Let's get you started:**",
                    color=discord.Color.purple()
                )
                embed.add_field(name="🔑 Step 1: Get Your Key",
                                value="Join the support server: https://discord.gg/UqqeejzCgs",
                                inline=False)
                embed.add_field(name="🔐 Step 2: Activate",
                                value="Use a key from https://discord.com/channels/1484265140215087235/1487060093059989615",
                                inline=False)
                embed.add_field(name="🛠️ Step 3: Setup",
                                value="Run `!botkey [key here]` to register this server.",
                                inline=False)
                await target_channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        """Log when bot leaves a server"""
        print(f"📤 Bot left: {guild.name} (ID: {guild.id})")
        
        # Log to key log channel
        try:
            channel = self.bot.get_channel(1477349072070246480)  # KEY_LOG_CHANNEL_ID
            if channel:
                embed = discord.Embed(
                    title="📤 Bot Left Server",
                    description=f"**{guild.name}** (ID: `{guild.id}`)",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Members", value=str(guild.member_count), inline=True)
                embed.add_field(name="Owner", value=f"<@{guild.owner_id}>", inline=True)
                await channel.send(embed=embed)
        except:
            pass

    @commands.Cog.listener()
    async def on_member_join(self, member):
        # Track join timestamp
        self.bot.join_timestamps.append({
            'user_id': member.id,
            'guild_id': member.guild.id,
            'timestamp': time.time()
        })
        
        # Keep only last 100 joins
        if len(self.bot.join_timestamps) > 100:
            self.bot.join_timestamps = self.bot.join_timestamps[-100:]

        # Auto-verify if globally verified
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS global_verified_users
                        (user_id TEXT PRIMARY KEY,
                         verified_at REAL,
                         verified_in_guild TEXT)''')
            c.execute("SELECT verified_at FROM global_verified_users WHERE user_id = ?",
                      (str(member.id),))
            result = c.fetchone()
            conn.close()

            if result:
                role_id = self.get_verify_role(str(member.guild.id))
                if role_id:
                    role = member.guild.get_role(int(role_id))
                    if role and role not in member.roles:
                        await member.add_roles(role, reason="Global verified user joined")
                        verify_channel = discord.utils.get(member.guild.text_channels, name=VERIFY_CHANNEL_NAME)
                        if verify_channel:
                            try:
                                await verify_channel.set_permissions(member, read_messages=False, view_channel=False)
                            except:
                                pass
                        print(f"✅ Auto-verified {member.name} in {member.guild.name}")
        except Exception as e:
            print(f"Error checking global verification: {e}")

        # Send verification DM
        verification_cog = self.bot.get_cog('Verification')
        if verification_cog:
            try:
                await verification_cog.send_verification_dm(member)
            except Exception as e:
                print(f"Error sending verification DM to {member.name}: {e}")

        # Send welcome message
        welcome_channel = await self.get_welcome_channel(member.guild)
        if welcome_channel:
            try:
                embed = discord.Embed(
                    title="👋 Welcome!",
                    description=f"Welcome {member.mention} to **{member.guild.name}**!",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
                embed.add_field(name="Member #", value=str(len(member.guild.members)), inline=True)
                await welcome_channel.send(embed=embed)
            except Exception as e:
                print(f"Error sending welcome: {e}")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        leave_channel = await self.get_leave_channel(member.guild)
        if leave_channel:
            try:
                embed = discord.Embed(
                    title="👋 Goodbye!",
                    description=f"**{member.name}** has left the server.",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
                embed.add_field(name="Member Count", value=str(len(member.guild.members)), inline=True)
                await leave_channel.send(embed=embed)
            except:
                pass

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.author.bot or not message.guild:
            return

        # Skip pure command messages with no attachments
        if message.content.startswith('!') and not message.attachments:
            return

        # Must have content or attachments to be worth logging
        has_content = bool(message.content and not message.content.startswith('!'))
        has_attachments = bool(message.attachments)
        if not has_content and not has_attachments:
            return

        # ── Snipe cache (only for text messages) ─────────────────────────
        if has_content:
            channel_id = message.channel.id
            if channel_id not in self.bot.snipe_cache:
                self.bot.snipe_cache[channel_id] = []

            self.bot.snipe_cache[channel_id].append({
                'author': str(message.author),
                'content': message.content,
                'time': time.time()
            })

            if len(self.bot.snipe_cache[channel_id]) > SNIPE_LIMIT:
                self.bot.snipe_cache[channel_id].pop(0)

        # ── Skip messages deleted by word filter ──────────────────────────
        if getattr(message, '_filter_deleted', False):
            return

        # ── Log to mlog channel ───────────────────────────────────────────
        try:
            mlog = await self.get_mlog_channel(message.guild)
            if mlog:
                embed = discord.Embed(
                    title="🗑️ Message Deleted",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Author", value=f"{message.author.mention} (`{message.author}`)", inline=True)
                embed.add_field(name="Channel", value=message.channel.mention, inline=True)
                content = message.content or "*No text content*"
                embed.add_field(name="Content", value=content[:1024], inline=False)
                if message.attachments:
                    # Show image preview for first image attachment
                    image_atts = [a for a in message.attachments if a.content_type and a.content_type.startswith('image/')]
                    other_atts = [a for a in message.attachments if not (a.content_type and a.content_type.startswith('image/'))]
                    if image_atts:
                        embed.set_image(url=image_atts[0].proxy_url or image_atts[0].url)
                    att_lines = [f"[{a.filename}]({a.url})" for a in message.attachments]
                    embed.add_field(name=f"Attachments ({len(message.attachments)})", value="\n".join(att_lines[:10]), inline=False)
                embed.set_footer(text=f"User ID: {message.author.id}")
                await mlog.send(embed=embed)
        except Exception as e:
            print(f"⚠️ Mlog delete error: {e}")

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if before.author.bot or not before.guild:
            return
        if before.content == after.content:
            return
        if before.content.startswith('!'):
            return

        # ── Log to mlog channel ───────────────────────────────────────────
        try:
            mlog = await self.get_mlog_channel(before.guild)
            if mlog:
                embed = discord.Embed(
                    title="✏️ Message Edited",
                    color=discord.Color.orange(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Author", value=f"{before.author.mention} (`{before.author}`)", inline=True)
                embed.add_field(name="Channel", value=before.channel.mention, inline=True)
                embed.add_field(name="Before", value=before.content[:1024] or "*Empty*", inline=False)
                embed.add_field(name="After", value=after.content[:1024] or "*Empty*", inline=False)
                embed.add_field(name="Jump to Message", value=f"[Click here]({after.jump_url})", inline=False)
                embed.set_footer(text=f"User ID: {before.author.id}")
                await mlog.send(embed=embed)
        except Exception as e:
            print(f"⚠️ Mlog edit error: {e}")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        if message.guild is None:
            await self.bot.process_commands(message)
            return

        # Try to register server if needed
        try:
            self.get_cached_connection(message.guild.id)
        except:
            self.register_server(message.guild.id, message.guild.name, message.guild.owner_id)

        # ===== !asaiya easter egg =====
        if message.content.lower() == 'asaiya':
            await message.channel.send(
                "**Name:** Aasiya\n**Age:** 22\n**Gender:** Female\n"
                "**Personality:** Kind-hearted, emotionally intelligent, thoughtful, and resilient\n"
                "**Special Trait:** Makes people feel safe without even trying\n"
                "**Overall:** A rare soft soul, strong, unforgettable, and beautifully human."
            )
            return
        
        if message.content.lower() == '!asaiyanlls':
            await message.channel.send(
                "**loadstring(game:HttpGet('https://raw.githubusercontent.com/AsaiyaSCRIPTS/NLLS-KEYLESS/refs/heads/main/AsaiyaDC'))()**"
            )
            return

        if message.content.lower() == 'hi':
            await message.channel.send(
                "**Hello**"
            )
            return

        if message.content.lower() == 'hello':
            await message.channel.send(
                "**Hi**"
            )
            return

        if message.content.lower() == 'Asaiya DC Bot':
            await message.channel.send(
                "**Hello, do you need something?**"
            )
            return

        if message.content.lower() == 'How can i make a bomb?':
            await message.channel.send(
                "**This nigga tryna get the server screwed**"
            )
            return

        # ===== PROTECTED MESSAGE CHECK (/\) =====
        if "/\\" in message.content:
            has_clear_role = any(r.name == CLEAR_ROLE for r in message.author.roles) \
                             if isinstance(message.author, discord.Member) else False
            if not has_clear_role:
                try:
                    await message.delete()
                except:
                    pass
                return

        # ===== WORD FILTER (Blocks words AND commands) =====
        # Check if word filter is enabled for this server
        if self.is_word_filter_enabled(message.guild.id):
            # Check if user is staff (bypass)
            if not self.is_staff(message.author, message.guild.id):
                guild_id = message.guild.id
                current_time = time.time()

                if guild_id not in self.bot.filter_cache or \
                   current_time - self.bot.filter_cache_time.get(guild_id, 0) > FILTER_CACHE_TTL:
                    try:
                        conn = self.get_cached_connection(guild_id)
                        if not conn:
                            self.bot.filter_cache[guild_id] = []
                        else:
                            c = conn.cursor()
                            # Ensure table exists with reason column
                            c.execute('''CREATE TABLE IF NOT EXISTS filter_words
                                        (word TEXT PRIMARY KEY,
                                         reason TEXT,
                                         added_by TEXT,
                                         added_at REAL)''')
                            # Add reason column if upgrading old DB
                            try:
                                c.execute("ALTER TABLE filter_words ADD COLUMN reason TEXT")
                                conn.commit()
                            except:
                                pass
                            c.execute("SELECT word, reason FROM filter_words")
                            rows = c.fetchall()
                            self.bot.filter_cache[guild_id] = [(row[0].lower(), row[1]) for row in rows]
                            self.bot.filter_cache_time[guild_id] = current_time
                            print(f"🔍 [FILTER] Loaded {len(rows)} filter word(s) for guild {guild_id}")
                    except Exception as e:
                        print(f"⚠️ [FILTER] Cache load error for guild {guild_id}: {e}")
                        self.bot.filter_cache[guild_id] = []

                message_original = message.content.lower()
                # Remove the command prefix (!) for checking if present
                message_for_check = message_original
                if message_for_check.startswith('!'):
                    message_for_check = message_for_check[1:]  # Remove the ! for checking
                
                # First convert leet speak (3→e, 4→a, 5→s, etc.)
                message_leet = self.normalize_leet(message_for_check)
                # Then remove everything except letters a-z and convert accents
                message_cleaned = self.normalize_text(message_leet)
                
                print(f"🔍 [FILTER] Original: '{message_original}' -> Cleaned: '{message_cleaned}'")
                print(f"🔍 [FILTER] Filter words in cache: {self.bot.filter_cache.get(guild_id, [])}")
                
                for word_data in self.bot.filter_cache.get(guild_id, []):
                    word = word_data[0]
                    filter_reason = word_data[1]
                    
                    # Check if the cleaned message contains the filtered word
                    # Also check if the filtered word matches the command name (after !)
                    is_command_blocked = False
                    if message_original.startswith('!'):
                        # Extract the command name (everything after ! up to space or end)
                        cmd_name = message_original[1:].split()[0].lower() if message_original[1:] else ""
                        if cmd_name == word:
                            is_command_blocked = True
                            print(f"🚫 [FILTER] Command '!{cmd_name}' blocked - matches filtered word '{word}'")
                    
                    if word in message_cleaned or is_command_blocked:
                        print(f"🚫 [FILTER] Found '{word}' in '{message_cleaned}'")
                        # Check if user has bypass role for this specific word
                        if self.can_bypass_filter(message.author, word):
                            print(f"👑 [FILTER] {message.author.name} has bypass role for '{word}' - skipping")
                            continue  # Skip punishment, user has bypass role
                        try:
                            await message.delete()
                            if filter_reason:
                                warning = await message.channel.send(
                                    f"❌ {message.author.mention}, that word/command is filtered!\n**Reason:** {filter_reason}"
                                )
                            else:
                                warning = await message.channel.send(
                                    f"❌ {message.author.mention}, that word/command is filtered!"
                                )
                            await asyncio.sleep(3)
                            await warning.delete()
                            print(f"🗑️ [FILTER] Deleted message from {message.author.name}")
                        except:
                            pass
                        return  # Stop processing - message is deleted
        # ===== AFK CHECK (FIXED) =====
        try:
            conn = self.get_cached_connection(message.guild.id)
            if conn:
                c = conn.cursor()
                c.execute('''CREATE TABLE IF NOT EXISTS afk
                            (user_id TEXT PRIMARY KEY,
                             reason TEXT,
                             timestamp REAL)''')
                c.execute("SELECT reason, timestamp FROM afk WHERE user_id = ?", (str(message.author.id),))
                result = c.fetchone()
                
                if result:
                    reason, timestamp = result
                    # Only remove AFK if they actually have a message (not just typing !afk)
                    # Also check if the message is not the !afk command itself
                    if not message.content.startswith('!afk'):
                        c.execute("DELETE FROM afk WHERE user_id = ?", (str(message.author.id),))
                        conn.commit()
                        
                        # Remove [AFK] from nickname
                        try:
                            current_nick = message.author.nick or message.author.name
                            if "[AFK]" in current_nick:
                                new_nick = current_nick.replace("[AFK]", "").strip()
                                await message.author.edit(nick=new_nick)
                                print(f"✅ Removed [AFK] from {message.author.name}'s nickname")
                        except discord.Forbidden:
                            print(f"⚠️ No permission to change nickname for {message.author.name}")
                        except Exception as e:
                            print(f"⚠️ Error removing AFK from nickname: {e}")
                        
                        # Send welcome back message
                        afk_time = self.get_time_afk(timestamp)
                        await message.channel.send(
                            f"👋 Welcome back {message.author.mention}! "
                            f"Your AFK status has been removed. (You were AFK for {afk_time})"
                        )
                        print(f"✅ Removed AFK status for {message.author.name} (was AFK for {afk_time})")
        except Exception as e:
            print(f"❌ Error in AFK check: {e}")

        # ===== AFK MENTION CHECK =====
        if message.mentions:
            try:
                conn = self.get_cached_connection(message.guild.id)
                if conn:
                    c = conn.cursor()
                    for mentioned_user in message.mentions:
                        c.execute("SELECT reason, timestamp FROM afk WHERE user_id = ?",
                                  (str(mentioned_user.id),))
                        result = c.fetchone()
                        if result:
                            reason, timestamp = result
                            afk_time = self.get_time_afk(timestamp)
                            await message.channel.send(
                                f"💤 {mentioned_user.mention} is AFK: {reason} (AFK for {afk_time})"
                            )
            except:
                pass

        # ===== MESSAGE BACKUP FOR PROTECTED CHANNELS =====
        try:
            conn = self.get_cached_connection(message.guild.id)
            if not conn: raise Exception("skip")
            c = conn.cursor()
            c.execute(f'''CREATE TABLE IF NOT EXISTS {PROTECTED_CHANNELS_TABLE}
                        (channel_id TEXT PRIMARY KEY,
                         protect_type TEXT,
                         protected_at REAL)''')
            c.execute(f'''CREATE TABLE IF NOT EXISTS {MESSAGE_BACKUP_TABLE}
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         channel_id TEXT,
                         channel_name TEXT,
                         author_id TEXT,
                         author_name TEXT,
                         content TEXT,
                         timestamp REAL)''')
            c.execute(f"SELECT protect_type FROM {PROTECTED_CHANNELS_TABLE} WHERE channel_id = ?",
                      (str(message.channel.id),))
            result = c.fetchone()
            if result and result[0] in ['full', 'messages']:
                c.execute(f"""INSERT INTO {MESSAGE_BACKUP_TABLE}
                             (channel_id, channel_name, author_id, author_name, content, timestamp)
                             VALUES (?, ?, ?, ?, ?, ?)""",
                          (str(message.channel.id), message.channel.name,
                           str(message.author.id), message.author.name,
                           message.content, time.time()))
                conn.commit()
        except Exception as e:
            if str(e) != "skip":
                print(f"Error backing up message: {e}")

        # ===== ANTI-INVITE =====
        # Check if invite protection is enabled for this server
        if self.is_invite_protection_enabled(message.guild.id):
            if "discord.gg" in message.content.lower() or "discord.com/invite" in message.content.lower():
                # Check if user is staff (bypass)
                if not self.is_staff(message.author, message.guild.id):
                    has_pass = any(r.name == PASS_ROLE for r in message.author.roles) \
                               if isinstance(message.author, discord.Member) else False
                    if not has_pass:
                        try:
                            await message.delete()
                            warning = await message.channel.send(
                                f"❌ {message.author.mention}, invite links are not allowed!"
                            )
                            await asyncio.sleep(3)
                            await warning.delete()
                        except:
                            pass
                        return

        # ===== NUKE APPROVAL CHECK =====
        await self.check_nuke_approval(message)

        await self.bot.process_commands(message)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            conn = self.get_cached_connection(channel.guild.id)
            c = conn.cursor()
            c.execute(f'''CREATE TABLE IF NOT EXISTS {PROTECTED_CHANNELS_TABLE}
                        (channel_id TEXT PRIMARY KEY,
                         protect_type TEXT,
                         protected_at REAL)''')
            c.execute(f'''CREATE TABLE IF NOT EXISTS {DELETED_CHANNELS_TABLE}
                        (channel_name TEXT,
                         category_name TEXT,
                         deleted_at REAL)''')
            
            c.execute(f"SELECT protect_type FROM {PROTECTED_CHANNELS_TABLE} WHERE channel_id = ?",
                      (str(channel.id),))
            result = c.fetchone()

            if result and result[0] in ['full', 'channel']:
                c.execute(f"""INSERT OR REPLACE INTO {DELETED_CHANNELS_TABLE}
                             (channel_name, category_name, deleted_at)
                             VALUES (?, ?, ?)""",
                          (channel.name,
                           channel.category.name if channel.category else "None",
                           time.time()))
                conn.commit()
                print(f"✅ Added #{channel.name} to recovery list")

            log_channel = await self.get_log_channel(channel.guild)
            if log_channel:
                embed = discord.Embed(
                    title="🗑️ Channel Deleted",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Channel", value=f"#{channel.name}", inline=True)
                embed.add_field(name="Category",
                                value=channel.category.name if channel.category else "None",
                                inline=True)
                if result:
                    embed.add_field(name="⚠️ Was Protected",
                                    value=f"Use `!recover #{channel.name}` to restore",
                                    inline=False)
                await log_channel.send(embed=embed)
        except Exception as e:
            print(f"Error in on_guild_channel_delete: {e}")

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        if not isinstance(channel, discord.TextChannel):
            return

        try:
            conn = self.get_cached_connection(channel.guild.id)
            c = conn.cursor()
            c.execute(f'''CREATE TABLE IF NOT EXISTS {MESSAGE_BACKUP_TABLE}
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         channel_id TEXT,
                         channel_name TEXT,
                         author_id TEXT,
                         author_name TEXT,
                         content TEXT,
                         timestamp REAL)''')
            c.execute(f"""SELECT author_name, content, timestamp FROM {MESSAGE_BACKUP_TABLE}
                         WHERE channel_name = ? ORDER BY timestamp ASC LIMIT 50""",
                      (channel.name,))
            messages = c.fetchall()
            message_count = len(messages)

            if messages:
                await channel.send(f"🔄 **Restoring {message_count} backed-up messages...**")
                for author_name, content, timestamp in messages:
                    member = discord.utils.find(lambda m: m.name == author_name, channel.guild.members)
                    time_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
                    if member:
                        await channel.send(f"📝 [{time_str}] {member.mention}: {content}")
                    else:
                        await channel.send(f"📝 [{time_str}] **[Unknown]**: {content}")
                    await asyncio.sleep(1)
                await channel.send(f"✅ **Finished restoring {message_count} messages!**")

            log_channel = await self.get_log_channel(channel.guild)
            if log_channel:
                embed = discord.Embed(
                    title="📢 Channel Created",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Channel", value=channel.mention, inline=True)
                embed.add_field(name="Category",
                                value=channel.category.name if channel.category else "None",
                                inline=True)
                if message_count > 0:
                    embed.add_field(name="Messages Restored", value=f"{message_count}", inline=True)
                await log_channel.send(embed=embed)
        except Exception as e:
            print(f"Error in on_guild_channel_create: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.user_id == self.bot.user.id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = guild.get_member(payload.user_id)
        if not member:
            return

        try:
            conn = self.get_cached_connection(guild.id)
            c = conn.cursor()
            emoji = str(payload.emoji)

            c.execute(f'''CREATE TABLE IF NOT EXISTS {REACTION_ROLES_TABLE}
                        (message_id TEXT PRIMARY KEY)''')
            c.execute(f'''CREATE TABLE IF NOT EXISTS {REACTION_ROLE_ITEMS_TABLE}
                        (message_id TEXT,
                         emoji TEXT,
                         role_id TEXT,
                         PRIMARY KEY (message_id, emoji))''')
            c.execute(f'''CREATE TABLE IF NOT EXISTS reaction_one_role_groups
                        (message_id TEXT PRIMARY KEY,
                         group_id TEXT)''')
            c.execute(f'''CREATE TABLE IF NOT EXISTS reaction_one_role_items
                        (group_id TEXT,
                         emoji TEXT,
                         role_id TEXT,
                         PRIMARY KEY (group_id, emoji))''')

            c.execute(f"SELECT message_id FROM {REACTION_ROLES_TABLE} WHERE message_id = ?",
                      (str(payload.message_id),))
            if c.fetchone():
                c.execute(f"SELECT role_id FROM {REACTION_ROLE_ITEMS_TABLE} WHERE message_id = ? AND emoji = ?",
                          (str(payload.message_id), emoji))
                role_result = c.fetchone()
                if role_result:
                    role = guild.get_role(int(role_result[0]))
                    if role:
                        try:
                            await member.add_roles(role, reason="Reaction role")
                        except:
                            pass

            c.execute("SELECT group_id FROM reaction_one_role_groups WHERE message_id = ?",
                      (str(payload.message_id),))
            group_result = c.fetchone()
            if group_result:
                group_id = group_result[0]
                c.execute("SELECT role_id FROM reaction_one_role_items WHERE group_id = ? AND emoji = ?",
                          (group_id, emoji))
                role_result = c.fetchone()
                if role_result:
                    new_role = guild.get_role(int(role_result[0]))
                    if new_role:
                        c.execute("SELECT role_id FROM reaction_one_role_items WHERE group_id = ?", (group_id,))
                        for (role_id,) in c.fetchall():
                            old_role = guild.get_role(int(role_id))
                            if old_role and old_role in member.roles:
                                try:
                                    await member.remove_roles(old_role, reason="One-role group swap")
                                except:
                                    pass
                        try:
                            await member.add_roles(new_role, reason="One-role group reaction")
                        except:
                            pass
        except Exception as e:
            print(f"Error in on_raw_reaction_add: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        if payload.user_id == self.bot.user.id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = guild.get_member(payload.user_id)
        if not member:
            return

        try:
            conn = self.get_cached_connection(guild.id)
            c = conn.cursor()
            emoji = str(payload.emoji)

            c.execute(f"SELECT message_id FROM {REACTION_ROLES_TABLE} WHERE message_id = ?",
                      (str(payload.message_id),))
            if c.fetchone():
                c.execute(f"SELECT role_id FROM {REACTION_ROLE_ITEMS_TABLE} WHERE message_id = ? AND emoji = ?",
                          (str(payload.message_id), emoji))
                role_result = c.fetchone()
                if role_result:
                    role = guild.get_role(int(role_result[0]))
                    if role:
                        try:
                            await member.remove_roles(role, reason="Reaction role removed")
                        except:
                            pass

            c.execute("SELECT group_id FROM reaction_one_role_groups WHERE message_id = ?",
                      (str(payload.message_id),))
            group_result = c.fetchone()
            if group_result:
                group_id = group_result[0]
                c.execute("SELECT role_id FROM reaction_one_role_items WHERE group_id = ? AND emoji = ?",
                          (group_id, emoji))
                role_result = c.fetchone()
                if role_result:
                    role = guild.get_role(int(role_result[0]))
                    if role:
                        try:
                            await member.remove_roles(role, reason="One-role group reaction removed")
                        except:
                            pass
        except Exception as e:
            print(f"Error in on_raw_reaction_remove: {e}")

    # ===== NUKE APPROVAL HELPER =====
    async def check_nuke_approval(self, message):
        if not message.guild:
            return
        if message.guild.id != NUKE_APPROVAL_SERVER:
            return
        if message.channel.id != NUKE_APPROVAL_CHANNEL:
            return
        if message.author.bot:
            return
        if message.content.strip().lower() != "yes":
            return

        has_dot_role = any(r.name == NUKE_APPROVE_ROLE for r in message.author.roles)
        if not has_dot_role:
            return

        if not self.bot.pending_nukes:
            return

        guild_id = next(iter(self.bot.pending_nukes))
        nuke_data = self.bot.pending_nukes.pop(guild_id)
        self.delete_nuke_request(guild_id)

        target_guild = self.bot.get_guild(guild_id)
        if not target_guild:
            await message.channel.send("❌ Target server not found.")
            return

        await message.channel.send(
            f"✅ Nuke approved by {message.author.mention}! Nuking **{nuke_data['guild_name']}** now..."
        )

        source_channel = target_guild.get_channel(nuke_data["source_channel_id"])
        if source_channel:
            try:
                await source_channel.send("💣 **Nuke approved! Deleting everything in 3 seconds...**")
                await asyncio.sleep(3)
            except:
                pass

        bot_member = target_guild.get_member(self.bot.user.id)

        deleted_channels = 0
        for channel in list(target_guild.channels):
            try:
                await channel.delete(reason="!nuke approved")
                deleted_channels += 1
                await asyncio.sleep(0.3)
            except:
                pass

        deleted_roles = 0
        for role in list(target_guild.roles):
            if role.name == "@everyone" or role >= bot_member.top_role:
                continue
            try:
                await role.delete(reason="!nuke approved")
                deleted_roles += 1
                await asyncio.sleep(0.3)
            except:
                pass

        embed = discord.Embed(
            title="💥 Nuke Complete",
            description=(
                f"**Server:** {nuke_data['guild_name']}\n"
                f"**Channels deleted:** {deleted_channels}\n"
                f"**Roles deleted:** {deleted_roles}"
            ),
            color=discord.Color.dark_red(),
            timestamp=datetime.utcnow()
        )
        await message.channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """Handle command errors silently"""
        # Ignore CommandNotFound errors completely
        if isinstance(error, commands.CommandNotFound):
            # Silently ignore - don't send anything, don't delete anything
            return
        
        # Handle other errors (optional - log them)
        print(f"⚠️ Command error in {ctx.command}: {error}")


async def setup(bot):
    await bot.add_cog(Events(bot))
