import discord
from discord.ext import commands, tasks
import sqlite3
import time
import asyncio
import os
import json
import re
from datetime import datetime

# ===== CONFIGURATION =====
DB_FOLDER = r"C:\Users\Kelly\Desktop\discord database"
MAIN_DB_PATH = os.path.join(DB_FOLDER, "asaiya_bot.db")

BOT_ROLE = "AsaiyaBot"
KICK_ROLE = "AsaiyaKick"
BAN_ROLE = "AsaiyaBan"
PASS_ROLE = "AsaiyaPass"
CLEAR_ROLE = "AsaiyaClear"
SUPPORT_ROLE = "asaiya-support"
REQUEST_ROLE = "asaiya-request"

OWNER_SERVER_ID = 1484265140215087235
KEY_LOG_CHANNEL_ID = 1477349072070246480

NUKE_APPROVAL_CHANNEL = 1477599424208179303
NUKE_APPROVAL_SERVER = 1476790704914305134

# ===== SETUP TEMPLATE CONSTANTS =====
BOT_CHANNEL = "asaiya-bot"
HUB_CHANNEL = "asaiya-hub"
LOG_CHANNEL = "asaiya-log"
WELCOME_CHANNEL = "welcome"
GOODBYE_CHANNEL = "goodbye"
VERIFICATION_CHANNEL = "asaiya-verification"
TICKET_ALERTS_CHANNEL = "ticket-alerts"
TICKET_LOGS_CHANNEL = "ticket-logs"

BUG_CATEGORY = "bug-ticket"
BUY_CATEGORY = "buy-ticket"
REPORT_CATEGORY = "report-ticket"
VERIFY_CATEGORY = "verify-ticket"
ASAIYA_TICKET_CATEGORY = "Asaiya Ticket"
ASAIYA_DONE_CATEGORY = "Asaiya-Done"
STAFF_CATEGORY = "Staff Team"

GAMING_INFO_CATEGORY = "📌 INFORMATION HUB"
GAMING_COMMUNITY_CATEGORY = "💬 COMMUNITY LOUNGE"
GAMING_COMP_CATEGORY = "🏆 COMPETITIVE ARENA"
GAMING_CONTENT_CATEGORY = "🎥 CONTENT CREATOR ZONE"
GAMING_VOICE_CATEGORY = "🔊 VOICE CHANNELS"

GAMING_INFO_CHANNELS = ["📜｜rules", "📢｜announcements", "📆｜events", "🎁｜giveaways", "📊｜server-updates"]
GAMING_COMMUNITY_CHANNELS = ["💬｜general-chat", "🎮｜what-are-you-playing", "😂｜memes", "📸｜clips-and-screenshots", "🤝｜looking-for-group"]
GAMING_COMP_TEXT_CHANNELS = ["📈｜rank-discussion", "🧠｜strategy-talk", "🥊｜scrims"]
GAMING_COMP_VOICE_CHANNELS = ["🎙️｜duo-voice", "🎙️｜squad-voice"]
GAMING_CONTENT_CHANNELS = ["📹｜self-promo", "🎬｜stream-notifs", "✂️｜editing-talk", "🎙️｜recording-room"]
GAMING_VOICE_CHANNELS = ["🎮 Lobby 1", "🎮 Lobby 2", "🎮 5-Stack Room", "🎮 Chill Room", "🎵 Music Room"]

COMMUNITY_INFO_CATEGORY = "📌 INFORMATION CENTER"
COMMUNITY_GENERAL_CATEGORY = "💬 GENERAL COMMUNITY"
COMMUNITY_DISCUSSION_CATEGORY = "🎯 DISCUSSION HUB"
COMMUNITY_CONNECTION_CATEGORY = "🤝 CONNECTION ZONE"
COMMUNITY_VOICE_CATEGORY = "🔊 VOICE LOUNGE"

COMMUNITY_INFO_CHANNELS = ["📜｜rules", "📢｜announcements", "📖｜server-guide", "❓｜faq", "📝｜suggestions"]
COMMUNITY_GENERAL_CHANNELS = ["💬｜general-chat", "👋｜introductions", "🌎｜random-talk", "📸｜media-share", "😂｜memes"]
COMMUNITY_DISCUSSION_CHANNELS = ["🧠｜deep-talk", "💼｜career-talk", "📚｜study-zone", "💻｜tech-talk", "🎨｜creative-corner"]
COMMUNITY_CONNECTION_CHANNELS = ["🙌｜support", "🗳️｜polls", "🎉｜community-events", "🎁｜giveaways"]
COMMUNITY_VOICE_CHANNELS = ["☕｜Chill Room", "📚｜Study Room", "🎙️｜Community Lounge 1", "🎙️｜Community Lounge 2", "🎙️｜Community Lounge 3"]


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Add duplicate prevention
        self.processed_commands = {}
        # Store custom setup data temporarily
        self.custom_setup_data = {}
        # Store pending moderation setup sessions
        self.pending_mod_setup = {}  # {user_id: {"step": int, "guild_id": int, "data": dict, "started_at": float}}
        
        # Start auto-cleanup task for stale sessions
        self.auto_cleanup_setup_sessions.start()
        
        # Start background task to check for bot removals from servers
        self.check_deactivated_servers.start()
        
        print(f"✅ Admin cog initialized (ID: {id(self)})")

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

    # ===== CLEANUP STALE SETUP SESSIONS =====
    async def cleanup_stale_setup_sessions(self):
        """Periodically clean up stale moderation setup sessions"""
        current_time = time.time()
        stale_sessions = []
        
        for user_id, session in self.pending_mod_setup.items():
            # Check if session has a timestamp, if not, add one
            if 'started_at' not in session:
                session['started_at'] = current_time
                continue
            
            # Sessions older than 10 minutes are considered stale
            if current_time - session.get('started_at', current_time) > 600:  # 10 minutes
                stale_sessions.append(user_id)
        
        for user_id in stale_sessions:
            del self.pending_mod_setup[user_id]
            print(f"🧹 Cleaned up stale moderation setup session for user {user_id}")
        
        return len(stale_sessions)
    
    @tasks.loop(minutes=5)
    async def auto_cleanup_setup_sessions(self):
        """Auto cleanup task for stale setup sessions"""
        cleaned = await self.cleanup_stale_setup_sessions()
        if cleaned > 0:
            print(f"🧹 Cleaned up {cleaned} stale setup session(s)")
    
    @auto_cleanup_setup_sessions.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    # ===== CHECK DEACTIVATED SERVERS (KEY REACTIVATION) =====
    @tasks.loop(hours=1)
    async def check_deactivated_servers(self):
        """Check if bot has been removed from any activated servers and free up keys"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            
            # Get all active key uses
            c.execute("SELECT id, key, guild_id, guild_name, is_active FROM key_uses WHERE is_active = 1")
            active_uses = c.fetchall()
            
            freed_keys = []
            
            for use_id, key, guild_id_str, guild_name, is_active in active_uses:
                guild_id = int(guild_id_str)
                guild = self.bot.get_guild(guild_id)
                
                # If bot is not in this guild anymore, deactivate this key use
                if guild is None:
                    print(f"🔑 Bot no longer in guild {guild_name} ({guild_id}) - freeing key {key}")
                    
                    # Deactivate this key use
                    c.execute("UPDATE key_uses SET is_active = 0 WHERE id = ?", (use_id,))
                    
                    # Remove from authorized_servers
                    c.execute("DELETE FROM authorized_servers WHERE guild_id = ?", (guild_id_str,))
                    
                    # For single-use keys, also reactivate the key itself
                    c.execute("SELECT key_type, is_active FROM bot_keys WHERE key = ?", (key,))
                    key_data = c.fetchone()
                    
                    if key_data:
                        key_type, key_is_active = key_data
                        # Single-use keys become available again
                        if key_type == 'single' and not key_is_active:
                            c.execute("UPDATE bot_keys SET is_active = 1 WHERE key = ?", (key,))
                            freed_keys.append(key)
                            print(f"🔑 Reactivated single-use key: {key}")
                        # Multi-use keys - just increment remaining uses
                        elif key_type == 'multi':
                            c.execute("UPDATE bot_keys SET uses_remaining = uses_remaining + 1 WHERE key = ?", (key,))
                            print(f"🔑 Increased uses_remaining for multi-key: {key}")
                    
                    freed_keys.append(key)
            
            if freed_keys:
                conn.commit()
                print(f"✅ Freed {len(freed_keys)} key(s) from deactivated servers")
                
                # Refresh ALL skey messages (in all servers that have them)
                for guild_id in list(self.bot.skey_messages.keys()):
                    await self.refresh_skey_message(guild_id)
            
            conn.close()
            
        except Exception as e:
            print(f"Error checking deactivated servers: {e}")
    
    @check_deactivated_servers.before_loop
    async def before_check_deactivated(self):
        await self.bot.wait_until_ready()

    # ===== FORCE REACTIVATE KEY COMMAND =====
    @commands.command(name='cbotkey')
    async def cbotkey(self, ctx, key: str):
        """Force reactivate a key by deactivating all servers using it.
        Usage: !cbotkey [key]
        
        This will:
        - Deactivate all servers currently using this key
        - Make the key available again for new servers
        - For multi-use keys, restore remaining uses
        """
        if await self.check_duplicate(ctx):
            return
            
        if not self.is_owner_server(ctx):
            await ctx.send("🔐 This command can only be used in the bot owner's server!")
            return
            
        if not self.has_bot_role(ctx.author):
            await ctx.send(f"❌ You need the **{BOT_ROLE}** role to use this command!")
            return
        
        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()
        
        # Check if key exists
        c.execute("SELECT key_type, max_uses, uses_remaining, is_active FROM bot_keys WHERE key = ?", (key,))
        key_data = c.fetchone()
        
        if not key_data:
            await ctx.send(f"❌ Key `{key}` not found.")
            conn.close()
            return
        
        key_type, max_uses, uses_remaining, is_active = key_data
        
        # Get all active servers using this key
        c.execute("SELECT id, guild_id, guild_name FROM key_uses WHERE key = ? AND is_active = 1", (key,))
        active_servers = c.fetchall()
        
        if not active_servers:
            await ctx.send(f"ℹ️ Key `{key}` is not currently in use by any server.")
            conn.close()
            return
        
        # Deactivate all servers using this key
        deactivated_servers = []
        for use_id, guild_id_str, guild_name in active_servers:
            c.execute("UPDATE key_uses SET is_active = 0 WHERE id = ?", (use_id,))
            c.execute("DELETE FROM authorized_servers WHERE guild_id = ?", (guild_id_str,))
            deactivated_servers.append(f"{guild_name} (`{guild_id_str}`)")
            
            # Try to notify the server
            try:
                guild = self.bot.get_guild(int(guild_id_str))
                if guild and guild.system_channel:
                    await guild.system_channel.send(
                        "⚠️ **Bot Deactivated**\n"
                        f"The key for this server has been force-reactivated by the bot owner.\n"
                        f"Key `{key}` is no longer valid for this server.\n"
                        "Contact the bot owner for a new key if needed."
                    )
            except:
                pass
        
        # Reactivate the key based on type
        if key_type == 'single':
            c.execute("UPDATE bot_keys SET is_active = 1 WHERE key = ?", (key,))
            new_status = "reactivated (single-use)"
        elif key_type == 'multi':
            # Restore all uses
            c.execute("UPDATE bot_keys SET uses_remaining = max_uses, is_active = 1 WHERE key = ?", (key,))
            new_status = f"reactivated with {max_uses} uses remaining"
        elif key_type == 'master':
            c.execute("UPDATE bot_keys SET is_active = 1 WHERE key = ?", (key,))
            new_status = "reactivated (master key)"
        elif key_type == 'timed':
            c.execute("UPDATE bot_keys SET is_active = 1 WHERE key = ?", (key,))
            new_status = "reactivated (timed key - will need to be used again)"
        else:
            new_status = "reactivated"
        
        conn.commit()
        
        await self.log_key_event('key_reactivated', ctx.guild, ctx.author, key, True,
                                 f"Force reactivated - removed from {len(active_servers)} server(s)")
        
        embed = discord.Embed(
            title="🔑 Key Force Reactivated",
            description=f"Key `{key}` has been force reactivated.",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Key Type", value=key_type.title(), inline=True)
        embed.add_field(name="New Status", value=new_status, inline=True)
        embed.add_field(name="Servers Deactivated", value=str(len(active_servers)), inline=True)
        
        if deactivated_servers:
            embed.add_field(name="Affected Servers", value="\n".join(deactivated_servers[:5]), inline=False)
            if len(deactivated_servers) > 5:
                embed.add_field(name="", value=f"... and {len(deactivated_servers) - 5} more", inline=False)
        
        await ctx.send(embed=embed)
        
        # Refresh skey message
        await self.refresh_skey_message(ctx.guild.id)
        
        conn.close()

    # ===== WORD FILTER MANAGEMENT COMMANDS =====
    
    @commands.command(name='addfilter')
    @commands.has_permissions(administrator=True)
    async def add_filter_word(self, ctx):
        """Interactive: Add a word to the filter list with optional bypass roles."""
        if await self.check_duplicate(ctx):
            return
            
        has_bot_role = any(role.name == BOT_ROLE for role in ctx.author.roles)
        if not has_bot_role:
            await ctx.send(f"❌ You need the {BOT_ROLE} role to use this command.")
            return
        
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        
        # Step 1: Get word
        await ctx.send(f"🔇 **Step 1/4:** What keyword would you like filtered from **{ctx.guild.name}**?\nType the word/phrase, or `cancel` to abort.")
        
        try:
            word_msg = await self.bot.wait_for('message', timeout=60.0, check=check)
            if word_msg.content.lower() == 'cancel':
                await ctx.send("❌ Cancelled.")
                return
            word = word_msg.content.lower().strip()
            if not word:
                await ctx.send("❌ Invalid word.")
                return
            await word_msg.delete()
            
            # Step 2: Get reason
            await ctx.send(f"📝 **Step 2/4:** Any reason for filtering `{word}`?\nType your reason, or `skip` to skip.")
            reason_msg = await self.bot.wait_for('message', timeout=60.0, check=check)
            if reason_msg.content.lower() == 'cancel':
                await ctx.send("❌ Cancelled.")
                return
            reason = reason_msg.content.strip() if reason_msg.content.lower() != 'skip' else None
            await reason_msg.delete()
            
            # Step 3: Get bypass roles
            await ctx.send(f"👥 **Step 3/4:** Any roles that can bypass this filter?\nType role names separated by commas (e.g., `Admin, Moderator`), or `skip` for none. Type, not Mention.\n*Note: Users without these roles will be blocked.*")
            roles_msg = await self.bot.wait_for('message', timeout=60.0, check=check)
            if roles_msg.content.lower() == 'cancel':
                await ctx.send("❌ Cancelled.")
                return
            
            bypass_role_ids = []
            bypass_role_names = []
            if roles_msg.content.lower() != 'skip':
                role_names = [r.strip() for r in roles_msg.content.split(',')]
                for role_name in role_names:
                    role = discord.utils.get(ctx.guild.roles, name=role_name)
                    if role:
                        bypass_role_ids.append(str(role.id))
                        bypass_role_names.append(role.name)
                    else:
                        await ctx.send(f"⚠️ Role `{role_name}` not found - skipping.")
            await roles_msg.delete()
            
            # Step 4: Confirm and save
            conn = self.get_cached_connection(ctx.guild.id)
            if not conn:
                await ctx.send("❌ Database error.")
                return
            c = conn.cursor()
            
            # Create filter_bypass_roles table if not exists
            c.execute('''CREATE TABLE IF NOT EXISTS filter_bypass_roles
                         (word TEXT, role_id TEXT, role_name TEXT, added_by TEXT, added_at REAL,
                          PRIMARY KEY (word, role_id))''')
            
            # Check if word already exists
            c.execute("SELECT word FROM filter_words WHERE word = ?", (word,))
            if c.fetchone():
                await ctx.send(f"⚠️ `{word}` is already in the filter list.")
                return
            
            # Add the word with reason
            c.execute("INSERT INTO filter_words (word, reason, added_by, added_at) VALUES (?, ?, ?, ?)",
                      (word, reason, str(ctx.author.id), time.time()))
            
            # Add bypass roles
            for role_id, role_name in zip(bypass_role_ids, bypass_role_names):
                c.execute("INSERT INTO filter_bypass_roles (word, role_id, role_name, added_by, added_at) VALUES (?, ?, ?, ?, ?)",
                          (word, role_id, role_name, str(ctx.author.id), time.time()))
            
            conn.commit()
            
            # Invalidate filter cache so the new word takes effect immediately
            if hasattr(self.bot, 'filter_cache') and ctx.guild.id in self.bot.filter_cache:
                del self.bot.filter_cache[ctx.guild.id]
            if hasattr(self.bot, 'filter_cache_time') and ctx.guild.id in self.bot.filter_cache_time:
                del self.bot.filter_cache_time[ctx.guild.id]
            
            # Build response
            embed = discord.Embed(
                title="✅ Filter Added!",
                description=f"`{word}` will now be filtered.",
                color=discord.Color.green()
            )
            if reason:
                embed.add_field(name="Reason", value=reason, inline=False)
            if bypass_role_names:
                embed.add_field(name="Bypass Roles", value=", ".join(bypass_role_names), inline=False)
            else:
                embed.add_field(name="Bypass Roles", value="*None - everyone will be affected*", inline=False)
            
            await ctx.send(embed=embed)
            
            # Log to log channel
            log_channel = await self.get_log_channel(ctx.guild)
            if log_channel:
                await log_channel.send(f"🔇 `{word}` added to filter by {ctx.author.mention}" + (f" (Reason: {reason})" if reason else ""))
            
        except asyncio.TimeoutError:
            await ctx.send("⏰ Timed out. Use `!addfilter` again to restart.")

    @commands.command(name='removefilter', aliases=['delfilter', 'rmfilter'])
    @commands.has_permissions(administrator=True)
    async def remove_filter_word(self, ctx, *, word: str = None):
        """Remove a word from the filter list. Usage: !removefilter <word>"""
        if await self.check_duplicate(ctx):
            return
            
        has_bot_role = any(role.name == BOT_ROLE for role in ctx.author.roles)
        if not has_bot_role:
            await ctx.send(f"❌ You need the {BOT_ROLE} role to use this command.")
            return
        
        if not word:
            await ctx.send("❌ Please provide a word to remove: `!removefilter badword`")
            return
        
        word_lower = word.lower().strip()
        
        try:
            conn = self.get_cached_connection(ctx.guild.id)
            c = conn.cursor()
            
            c.execute("SELECT word FROM filter_words WHERE word = ?", (word_lower,))
            if not c.fetchone():
                await ctx.send(f"⚠️ `{word}` is not in the filter list.")
                return
            
            # Remove the word and its bypass roles
            c.execute("DELETE FROM filter_words WHERE word = ?", (word_lower,))
            c.execute("DELETE FROM filter_bypass_roles WHERE word = ?", (word_lower,))
            conn.commit()
            
            # Invalidate filter cache so removal takes effect immediately
            if hasattr(self.bot, 'filter_cache') and ctx.guild.id in self.bot.filter_cache:
                del self.bot.filter_cache[ctx.guild.id]
            if hasattr(self.bot, 'filter_cache_time') and ctx.guild.id in self.bot.filter_cache_time:
                del self.bot.filter_cache_time[ctx.guild.id]
            
            await ctx.send(f"✅ Removed `{word}` from the word filter list.")
            
            log_channel = await self.get_log_channel(ctx.guild)
            if log_channel:
                await log_channel.send(f"🔊 `{word}` removed from filter by {ctx.author.mention}")
            
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

    @commands.command(name='listfilters', aliases=['filterlist', 'showfilters'])
    @commands.has_permissions(administrator=True)
    async def list_filters(self, ctx):
        """List all words currently in the filter list with their bypass roles."""
        if await self.check_duplicate(ctx):
            return
            
        has_bot_role = any(role.name == BOT_ROLE for role in ctx.author.roles)
        if not has_bot_role:
            await ctx.send(f"❌ You need the {BOT_ROLE} role to use this command.")
            return
        
        try:
            conn = self.get_cached_connection(ctx.guild.id)
            c = conn.cursor()
            
            c.execute('''CREATE TABLE IF NOT EXISTS filter_bypass_roles
                         (word TEXT, role_id TEXT, role_name TEXT, added_by TEXT, added_at REAL,
                          PRIMARY KEY (word, role_id))''')
            
            c.execute("SELECT word FROM filter_words ORDER BY word")
            words = c.fetchall()
            
            if not words:
                embed = discord.Embed(
                    title="📋 Word Filter List",
                    description="No words are currently filtered.",
                    color=discord.Color.blue()
                )
                embed.set_footer(text="Use !addfilter to add words")
                await ctx.send(embed=embed)
                return
            
            embed = discord.Embed(
                title=f"📋 Word Filter List ({len(words)} words)",
                color=discord.Color.green()
            )
            
            for (word,) in words:
                # Get bypass roles for this word
                c.execute("SELECT role_name FROM filter_bypass_roles WHERE word = ?", (word,))
                bypass_roles = [r[0] for r in c.fetchall()]
                
                if bypass_roles:
                    value = f"*Bypass: {', '.join(bypass_roles)}*"
                else:
                    value = "*Affects everyone*"
                
                embed.add_field(name=f"🔇 `{word}`", value=value, inline=False)
            
            embed.set_footer(text="Use !removefilter <word> to remove • Use !addfilter to add new words")
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

    @commands.command(name='clearfilters', aliases=['clearfilterlist'])
    @commands.has_permissions(administrator=True)
    async def clear_filters(self, ctx):
        """Clear ALL words from the filter list."""
        if await self.check_duplicate(ctx):
            return
            
        has_bot_role = any(role.name == BOT_ROLE for role in ctx.author.roles)
        if not has_bot_role:
            await ctx.send(f"❌ You need the {BOT_ROLE} role to use this command.")
            return
        
        try:
            conn = self.get_cached_connection(ctx.guild.id)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM filter_words")
            count = c.fetchone()[0]
            
            if count == 0:
                await ctx.send("📋 The filter list is already empty.")
                return
            
            await ctx.send(f"⚠️ **WARNING:** This will remove all {count} filtered words.\nType `CONFIRM` in the next 30 seconds to proceed.")
            
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel and m.content == "CONFIRM"
            
            try:
                await self.bot.wait_for('message', timeout=30.0, check=check)
                c.execute("DELETE FROM filter_words")
                c.execute("DELETE FROM filter_bypass_roles")
                conn.commit()
                await ctx.send(f"✅ Cleared all {count} words from the filter list.")
            except asyncio.TimeoutError:
                await ctx.send("❌ Confirmation timed out.")
                
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

    @commands.command(name='filterbypass')
    @commands.has_permissions(administrator=True)
    async def filter_bypass(self, ctx, action: str, word: str, *, roles: str = None):
        """Manage bypass roles for a filtered word.
        Usage: !filterbypass add <word> Admin,Moderator
               !filterbypass remove <word> Admin
               !filterbypass list <word>
        """
        if await self.check_duplicate(ctx):
            return
            
        has_bot_role = any(role.name == BOT_ROLE for role in ctx.author.roles)
        if not has_bot_role:
            await ctx.send(f"❌ You need the {BOT_ROLE} role to use this command.")
            return
        
        word_lower = word.lower().strip()
        conn = self.get_cached_connection(ctx.guild.id)
        if not conn:
            await ctx.send("❌ Database error.")
            return
        c = conn.cursor()
        
        # Check if word exists
        c.execute("SELECT word FROM filter_words WHERE word = ?", (word_lower,))
        if not c.fetchone():
            await ctx.send(f"❌ `{word}` is not in the filter list.")
            return
        
        if action.lower() == 'add':
            if not roles:
                await ctx.send("❌ Please provide role names: `!filterbypass add word Admin,Moderator`")
                return
            role_names = [r.strip() for r in roles.split(',')]
            added = []
            for role_name in role_names:
                role = discord.utils.get(ctx.guild.roles, name=role_name)
                if role:
                    try:
                        c.execute("INSERT INTO filter_bypass_roles (word, role_id, role_name, added_by, added_at) VALUES (?, ?, ?, ?, ?)",
                                  (word_lower, str(role.id), role.name, str(ctx.author.id), time.time()))
                        added.append(role.name)
                    except sqlite3.IntegrityError:
                        await ctx.send(f"⚠️ {role.name} already bypasses `{word}`")
                else:
                    await ctx.send(f"⚠️ Role `{role_name}` not found")
            conn.commit()
            if added:
                await ctx.send(f"✅ Added bypass for `{word}` to: {', '.join(added)}")
        
        elif action.lower() == 'remove':
            if not roles:
                await ctx.send("❌ Please provide a role name: `!filterbypass remove word Admin`")
                return
            role = discord.utils.get(ctx.guild.roles, name=roles.strip())
            if not role:
                await ctx.send(f"❌ Role `{roles}` not found")
                return
            c.execute("DELETE FROM filter_bypass_roles WHERE word = ? AND role_id = ?", (word_lower, str(role.id)))
            conn.commit()
            if c.rowcount > 0:
                await ctx.send(f"✅ Removed bypass for `{word}` from {role.name}")
            else:
                await ctx.send(f"⚠️ {role.name} was not bypassing `{word}`")
        
        elif action.lower() == 'list':
            c.execute("SELECT role_name FROM filter_bypass_roles WHERE word = ?", (word_lower,))
            bypass_roles = [r[0] for r in c.fetchall()]
            if bypass_roles:
                await ctx.send(f"👥 **Bypass roles for `{word}`:**\n{', '.join(bypass_roles)}")
            else:
                await ctx.send(f"ℹ️ No bypass roles for `{word}` - affects everyone")
        
        else:
            await ctx.send("❌ Invalid action. Use `add`, `remove`, or `list`")

    @commands.command(name='fixfiltertable')
    @commands.has_permissions(administrator=True)
    async def fix_filter_table(self, ctx):
        """Fix missing columns in filter_words table"""
        conn = self.get_cached_connection(ctx.guild.id)
        if conn:
            c = conn.cursor()
            try:
                c.execute("ALTER TABLE filter_words ADD COLUMN reason TEXT")
                await ctx.send("✅ Added 'reason' column")
            except Exception as e:
                await ctx.send(f"reason column: {e}")
            try:
                c.execute("ALTER TABLE filter_words ADD COLUMN added_by TEXT")
                await ctx.send("✅ Added 'added_by' column")
            except Exception as e:
                await ctx.send(f"added_by column: {e}")
            try:
                c.execute("ALTER TABLE filter_words ADD COLUMN added_at REAL")
                await ctx.send("✅ Added 'added_at' column")
            except Exception as e:
                await ctx.send(f"added_at column: {e}")
            conn.commit()
            await ctx.send("✅ Filter table migration complete! Now run `!refreshfilter` and try again.")
        else:
            await ctx.send("❌ Could not connect to database")

    @commands.command(name='checklog')
    @commands.has_permissions(administrator=True)
    async def check_log(self, ctx):
        """Check what log channel is set"""
        try:
            # First try to get from server database
            conn = self.get_cached_connection(ctx.guild.id)
            if conn:
                c = conn.cursor()
                c.execute("SELECT log_channel_id FROM log_channels")
                result = c.fetchone()
                if result and result[0]:
                    channel = ctx.guild.get_channel(int(result[0]))
                    await ctx.send(f"✅ Log channel is set to: {channel.mention if channel else 'Unknown channel'}")
                    return
            
            # If not found, check main database
            main_conn = sqlite3.connect(MAIN_DB_PATH)
            main_c = main_conn.cursor()
            main_c.execute("SELECT db_path FROM servers WHERE guild_id = ?", (str(ctx.guild.id),))
            db_path_result = main_c.fetchone()
            main_conn.close()
            
            if db_path_result and db_path_result[0]:
                server_conn = sqlite3.connect(db_path_result[0])
                server_c = server_conn.cursor()
                server_c.execute("SELECT log_channel_id FROM log_channels")
                result = server_c.fetchone()
                server_conn.close()
                if result and result[0]:
                    channel = ctx.guild.get_channel(int(result[0]))
                    await ctx.send(f"✅ Log channel is set to: {channel.mention if channel else 'Unknown channel'}")
                    return
            
            await ctx.send("❌ No log channel set! Use `!setlog #channel`")
        except Exception as e:
            await ctx.send(f"❌ Error checking log channel: {e}")

    @commands.command(name='checklogtable')
    @commands.has_permissions(administrator=True)
    async def check_log_table(self, ctx):
        """Check if log_channels table exists and has data"""
        conn = self.get_cached_connection(ctx.guild.id)
        if conn:
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='log_channels'")
            table_exists = c.fetchone()
            if table_exists:
                c.execute("SELECT * FROM log_channels")
                rows = c.fetchall()
                await ctx.send(f"✅ log_channels table exists. Rows: {rows}")
            else:
                await ctx.send("❌ log_channels table does NOT exist in server database!")
        else:
            await ctx.send("❌ Could not connect to server database")

    @commands.command(name='showlogdata')
    @commands.has_permissions(administrator=True)
    async def show_log_data(self, ctx):
        """Show the actual log channel data"""
        conn = self.get_cached_connection(ctx.guild.id)
        if conn:
            c = conn.cursor()
            c.execute("SELECT * FROM log_channels")
            rows = c.fetchall()
            for row in rows:
                # Convert row to dict to see column names
                await ctx.send(f"Row: {dict(row)}")
        else:
            await ctx.send("❌ No connection")

    @commands.command(name='cleanlogtable')
    @commands.has_permissions(administrator=True)
    async def clean_log_table(self, ctx):
        """Clean up duplicate rows in log_channels table"""
        conn = self.get_cached_connection(ctx.guild.id)
        if conn:
            c = conn.cursor()
            # Keep only the row with log_channel_id, delete others
            c.execute("DELETE FROM log_channels WHERE log_channel_id IS NULL")
            # Keep only one row with log_channel_id
            c.execute("DELETE FROM log_channels WHERE rowid NOT IN (SELECT MIN(rowid) FROM log_channels WHERE log_channel_id IS NOT NULL)")
            conn.commit()
            await ctx.send("✅ Cleaned up log_channels table")
        else:
            await ctx.send("❌ No connection")

    # ===== HELPER FUNCTIONS FOR READING SETTINGS =====
    
    def get_anti_raid_setting(self, guild_id, setting_name):
        """Get a setting from anti_raid_settings table"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute(f"SELECT {setting_name} FROM anti_raid_settings WHERE guild_id = ?", (str(guild_id),))
            result = c.fetchone()
            conn.close()
            return bool(result[0]) if result else False
        except Exception as e:
            print(f"Error getting {setting_name}: {e}")
            return False
    
    def get_invite_protection_setting(self, guild_id):
        """Get invite protection setting from anti_raid_settings"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT invite_protection FROM anti_raid_settings WHERE guild_id = ?", (str(guild_id),))
            result = c.fetchone()
            conn.close()
            return bool(result[0]) if result else False
        except Exception as e:
            print(f"Error getting invite_protection: {e}")
            return False

    # ===== TEMPLATE HISTORY FUNCTIONS =====
    def save_template_history(self, guild_id, template_type):
        """Save the last used template for a guild"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS persistent_template_history
                         (guild_id TEXT PRIMARY KEY,
                          last_template TEXT,
                          updated_at REAL)''')
            c.execute('''INSERT OR REPLACE INTO persistent_template_history
                         (guild_id, last_template, updated_at)
                         VALUES (?, ?, ?)''',
                      (str(guild_id), template_type, time.time()))
            conn.commit()
            conn.close()
            print(f"✅ Saved template history for guild {guild_id}: {template_type}")
        except Exception as e:
            print(f"❌ Error saving template history: {e}")

    def load_template_history(self, guild_id):
        """Load the last used template for a guild"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS persistent_template_history
                         (guild_id TEXT PRIMARY KEY,
                          last_template TEXT,
                          updated_at REAL)''')
            c.execute("SELECT last_template FROM persistent_template_history WHERE guild_id = ?",
                      (str(guild_id),))
            result = c.fetchone()
            conn.close()
            
            if result:
                print(f"✅ Loaded template history for guild {guild_id}: {result[0]}")
                return result[0]
        except Exception as e:
            print(f"❌ Error loading template history: {e}")
        return None

    # ===== MODERATION SETUP HELPERS =====
    def save_server_mod_setting(self, guild_id, setting_name, value):
        """Save a server moderation setting to database.
        leveling_enabled goes to server_mod_settings.
        All other settings go to anti_raid_settings.
        """
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()

            # ── leveling_enabled → server_mod_settings ────────────────────
            if setting_name == "leveling_enabled":
                c.execute('''CREATE TABLE IF NOT EXISTS server_mod_settings
                             (guild_id TEXT PRIMARY KEY,
                              hack_detection INTEGER DEFAULT 0,
                              spam_detection INTEGER DEFAULT 0,
                              raid_detection INTEGER DEFAULT 0,
                              verification_enabled INTEGER DEFAULT 0,
                              verification_role_id TEXT,
                              word_filter INTEGER DEFAULT 0,
                              invite_protection INTEGER DEFAULT 0,
                              leveling_enabled INTEGER DEFAULT 0,
                              updated_at REAL)''')
                # Add column if upgrading old DB
                try:
                    c.execute("ALTER TABLE server_mod_settings ADD COLUMN leveling_enabled INTEGER DEFAULT 0")
                except sqlite3.OperationalError:
                    pass
                c.execute("SELECT guild_id FROM server_mod_settings WHERE guild_id = ?", (str(guild_id),))
                if c.fetchone():
                    c.execute("UPDATE server_mod_settings SET leveling_enabled = ?, updated_at = ? WHERE guild_id = ?",
                              (1 if value else 0, time.time(), str(guild_id)))
                else:
                    c.execute('''INSERT INTO server_mod_settings
                                 (guild_id, leveling_enabled, updated_at)
                                 VALUES (?, ?, ?)''',
                              (str(guild_id), 1 if value else 0, time.time()))
                conn.commit()
                conn.close()
                return True

            # ── All other settings → anti_raid_settings ───────────────────
            c.execute('''CREATE TABLE IF NOT EXISTS anti_raid_settings
                         (guild_id TEXT PRIMARY KEY,
                          hack_detection INTEGER DEFAULT 0,
                          spam_detection INTEGER DEFAULT 0,
                          raid_detection INTEGER DEFAULT 0,
                          anti_nuke INTEGER DEFAULT 0,
                          word_filter INTEGER DEFAULT 0,
                          invite_protection INTEGER DEFAULT 0,
                          updated_at REAL)''')

            for col in ["anti_nuke", "word_filter", "invite_protection"]:
                try:
                    c.execute(f"ALTER TABLE anti_raid_settings ADD COLUMN {col} INTEGER DEFAULT 0")
                except sqlite3.OperationalError:
                    pass

            c.execute("SELECT * FROM anti_raid_settings WHERE guild_id = ?", (str(guild_id),))
            existing = c.fetchone()

            if existing:
                c.execute(f"UPDATE anti_raid_settings SET {setting_name} = ?, updated_at = ? WHERE guild_id = ?",
                          (1 if value else 0, time.time(), str(guild_id)))
            else:
                defaults = {
                    "hack_detection": 0,
                    "spam_detection": 0,
                    "raid_detection": 0,
                    "anti_nuke": 0,
                    "word_filter": 0,
                    "invite_protection": 0
                }
                defaults[setting_name] = 1 if value else 0
                c.execute('''INSERT INTO anti_raid_settings
                             (guild_id, hack_detection, spam_detection, raid_detection,
                              anti_nuke, word_filter, invite_protection, updated_at)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                          (str(guild_id), defaults["hack_detection"], defaults["spam_detection"],
                           defaults["raid_detection"], defaults["anti_nuke"],
                           defaults["word_filter"], defaults["invite_protection"], time.time()))

            conn.commit()
            conn.close()

            anti_raid_cog = self.bot.get_cog('AntiRaid')
            if anti_raid_cog and hasattr(anti_raid_cog, 'save_server_setting'):
                anti_raid_cog.save_server_setting(guild_id, setting_name, value)

            return True
        except Exception as e:
            print(f"Error saving server mod setting: {e}")
            return False

    def add_staff_role(self, guild_id, role_id, role_name, added_by):
        """Add a staff immunity role (used by anti_raid cog)"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''INSERT OR REPLACE INTO staff_immunity_roles
                         (guild_id, role_id, role_name, added_by, added_at)
                         VALUES (?, ?, ?, ?, ?)''',
                      (str(guild_id), str(role_id), role_name, str(added_by), time.time()))
            conn.commit()
            conn.close()
            
            # Also update anti_raid cog's staff roles
            anti_raid_cog = self.bot.get_cog('AntiRaid')
            if anti_raid_cog and hasattr(anti_raid_cog, 'add_staff_role'):
                anti_raid_cog.add_staff_role(guild_id, role_id, role_name, added_by)
            
            return True
        except Exception as e:
            print(f"Error adding staff role: {e}")
            return False

    def save_verification_role(self, guild_id, role_id, role_name, set_by):
        """Save verification role setting"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''INSERT OR REPLACE INTO verify_settings
                         (guild_id, role_id, role_name, set_by, set_at)
                         VALUES (?, ?, ?, ?, ?)''',
                      (str(guild_id), str(role_id), role_name, str(set_by), time.time()))
            conn.commit()
            conn.close()
            
            # Also update server_mod_settings
            self.save_server_mod_setting(guild_id, "verification_enabled", True)
            
            return True
        except Exception as e:
            print(f"Error saving verification role: {e}")
            return False

    # ===== MODERATION SETUP VIEW =====
    class ModSetupView(discord.ui.View):
        def __init__(self, cog, guild_id):
            super().__init__(timeout=300)
            self.cog = cog
            self.guild_id = guild_id

        @discord.ui.button(label="Yes, set up moderation", style=discord.ButtonStyle.green, custom_id="mod_setup_yes")
        async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.guild_id != self.guild_id:
                await interaction.response.send_message("❌ This setup is for a different server.", ephemeral=True)
                return
            
            await interaction.response.defer()
            await self.cog.start_moderation_setup(interaction)

        @discord.ui.button(label="No, skip for now", style=discord.ButtonStyle.grey, custom_id="mod_setup_no")
        async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.guild_id != self.guild_id:
                await interaction.response.send_message("❌ This setup is for a different server.", ephemeral=True)
                return
            
            embed = discord.Embed(
                title="❌ Moderation Setup Skipped",
                description=(
                    "That's okay! You can enable moderation features later:\n\n"
                    "• `!modsetup` - Run the setup wizard\n"
                    "• `!staffroles` - Configure staff immunity roles\n"
                    "• `!hackon` - Enable hacked account protection\n"
                    "• `!startspam` - Enable spam detection\n"
                    "• `!startraid` - Enable anti-raid\n"
                    "• `!antinukeon` - Enable anti-nuke protection\n"
                    "• `!inviteon` - Enable invite link protection\n\n"
                    "**Word Filter Management:**\n"
                    "• `!addfilter <word>` - Add a word to filter\n"
                    "• `!removefilter <word>` - Remove a word from filter\n"
                    "• `!listfilters` - Show all filtered words\n"
                    "• `!clearfilters` - Clear all filtered words\n\n"
                    "Thank you for adding Asaiya Bot! 🎉"
                ),
                color=discord.Color.orange(),
                timestamp=datetime.utcnow()
            )
            await interaction.response.send_message(embed=embed, ephemeral=False)
            self.stop()

    # ===== MODERATION SETUP FLOW =====
    async def start_moderation_setup(self, interaction):
        """Start the interactive moderation setup wizard"""
        user_id = interaction.user.id
        guild_id = interaction.guild_id
        
        # Store setup session with start time
        self.pending_mod_setup[user_id] = {
            "step": "staff_roles",
            "guild_id": guild_id,
            "data": {},
            "started_at": time.time()
        }
        
        # Step 1: Staff Roles
        embed = discord.Embed(
            title="👥 Staff Role Setup",
            description=(
                "To ensure staff members aren't accidentally punished, please list the roles that should have **immunity** from moderation features.\n\n"
                "These roles will be able to:\n"
                "• Spam without being timed out\n"
                "• Send duplicate messages without being flagged as hacked\n"
                "• Bypass word filter\n"
                "• Send invite links\n"
                "• Bypass raid detection\n\n"
                "**Note:** Anti-nuke protection ONLY respects the AsaiyaBot role for immunity.\n\n"
                "Enter role names separated by commas. Type them, not ping them.:\n"
                "Example: `Admin, Moderator, Helper`\n\n"
                "Or type `skip` to use only the default AsaiyaBot role."
            ),
            color=discord.Color.blue()
        )
        await interaction.followup.send(embed=embed, ephemeral=False)
        
        # Wait for response
        def check(m):
            return m.author.id == user_id and m.channel.id == interaction.channel.id
        
        try:
            msg = await self.bot.wait_for('message', timeout=120.0, check=check)
            await msg.delete()
            content = msg.content.strip()
            
            if content.lower() != "skip":
                # Parse role names
                role_names = [name.strip() for name in content.split(',')]
                added_roles = []
                
                for role_name in role_names:
                    role = discord.utils.get(interaction.guild.roles, name=role_name)
                    if role:
                        if self.add_staff_role(guild_id, role.id, role.name, user_id):
                            added_roles.append(role.mention)
                    else:
                        await interaction.followup.send(f"⚠️ Role `{role_name}` not found. Skipping.", ephemeral=False)
                
                if added_roles:
                    await interaction.followup.send(f"✅ Added staff roles: {', '.join(added_roles)}", ephemeral=False)
                else:
                    await interaction.followup.send("⚠️ No valid roles found. Using default staff roles only.", ephemeral=False)
            else:
                await interaction.followup.send("✅ Skipped custom staff roles. Using default AsaiyaBot role only.", ephemeral=False)
            
            # Move to next step
            await self.verification_setup_step(interaction, user_id)
            
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timed out. You can run `!modsetup` later to continue setup.", ephemeral=False)
            if user_id in self.pending_mod_setup:
                del self.pending_mod_setup[user_id]

    async def verification_setup_step(self, interaction, user_id):
        """Step 2: Ask about verification system"""
        embed = discord.Embed(
            title="🔐 Verification System",
            description=(
                "Would you like to set up a captcha verification system for new members?\n\n"
                "This will:\n"
                "• Send new members a captcha code via DM\n"
                "• Require them to verify before accessing the server\n"
                "• Auto-verify users who are already verified in other servers"
            ),
            color=discord.Color.blue()
        )
        
        class VerificationChoiceView(discord.ui.View):
            def __init__(self, cog, user_id):
                super().__init__(timeout=120)
                self.cog = cog
                self.user_id = user_id
            
            @discord.ui.button(label="✅ Yes, set up verification", style=discord.ButtonStyle.green, custom_id="verif_yes")
            async def yes_verif(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                await btn_interaction.response.defer()
                await self.cog.verification_role_step(btn_interaction, self.user_id)
                self.stop()
            
            @discord.ui.button(label="❌ No, skip for now", style=discord.ButtonStyle.grey, custom_id="verif_no")
            async def no_verif(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                await btn_interaction.response.defer()
                await btn_interaction.followup.send("⏭️ Verification setup skipped. You can set up later with `!setverify @role`", ephemeral=False)
                await self.cog.feature_selection_step(btn_interaction, self.user_id)
                self.stop()
        
        view = VerificationChoiceView(self, user_id)
        await interaction.followup.send(embed=embed, view=view, ephemeral=False)

    async def verification_role_step(self, interaction, user_id):
        """Step 2b: Get verification role"""
        embed = discord.Embed(
            title="🔐 Verification Role",
            description=(
                "Please provide the role that verified members should receive.\n\n"
                "Options:\n"
                "• Ping the role: `@Verified`\n"
                "• Provide the role name: `Verified`\n"
                "• Provide the role ID: `123456789`\n\n"
                "Type the role now, or type `skip` to set up later with `!setverify`"
            ),
            color=discord.Color.blue()
        )
        await interaction.followup.send(embed=embed, ephemeral=False)
        
        def check(m):
            return m.author.id == user_id and m.channel.id == interaction.channel.id
        
        try:
            msg = await self.bot.wait_for('message', timeout=120.0, check=check)
            await msg.delete()
            content = msg.content.strip()
            
            if content.lower() == "skip":
                await interaction.followup.send("⏭️ Verification setup skipped. You can set up later with `!setverify @role`", ephemeral=False)
            else:
                # Try to find the role
                role = None
                
                # Check if it's a mention
                if msg.role_mentions:
                    role = msg.role_mentions[0]
                else:
                    # Try by ID
                    try:
                        role_id = int(content)
                        role = interaction.guild.get_role(role_id)
                    except ValueError:
                        # Try by name
                        role = discord.utils.get(interaction.guild.roles, name=content)
                
                if role:
                    if self.save_verification_role(interaction.guild_id, role.id, role.name, user_id):
                        await interaction.followup.send(f"✅ Verification role set to {role.mention}!", ephemeral=False)
                    else:
                        await interaction.followup.send("❌ Failed to save verification role. You can set up later with `!setverify @role`", ephemeral=False)
                else:
                    await interaction.followup.send(f"❌ Role `{content}` not found. You can set up later with `!setverify @role`", ephemeral=False)
            
            # Move to feature selection
            await self.feature_selection_step(interaction, user_id)
            
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timed out. You can set up verification later with `!setverify @role`", ephemeral=False)
            await self.feature_selection_step(interaction, user_id)

    async def feature_selection_step(self, interaction, user_id):
        """Step 3: Select which moderation features to enable"""
        embed = discord.Embed(
            title="🛡️ Moderation Features",
            description=(
                "Which features would you like to enable?\n\n"
                "**Available Features:**\n\n"
                "**1️⃣ Hacked Account Protection**\n"
                "   • Timeout 24h (1st offense)\n"
                "   • Kick (2nd offense)\n"
                "   • Ban (3rd+ offense)\n"
                "   • Detects same message in multiple channels within 5 seconds\n\n"
                "**2️⃣ Spam Detection**\n"
                "   • Timeout 10 minutes for 5+ messages in 3 seconds\n"
                "   • Deletes all spam messages\n\n"
                "**3️⃣ Anti-Raid**\n"
                "   • Alerts staff when 30+ users join in 1 minute\n\n"
                "**4️⃣ Word Filter**\n"
                "   • Blocks inappropriate words\n"
                "   • Manage with: `!addfilter`, `!removefilter`, `!listfilters`\n\n"
                "**5️⃣ Invite Link Protection**\n"
                "   • Blocks Discord invite links\n\n"
                "**6️⃣ Anti-Nuke Protection**\n"
                "   • The role [ASAIYA DC BOT] must be at the top of the role hierarchy for this to work.\n"
                "   • Detects mass deletions/creations (2+ actions in 2 seconds)\n"
                "   • Strips all roles from perpetrator\n"
                "   • Only AsaiyaBot role is immune\n\n"
                "**7️⃣ Leveling System**\n"
                "   • Members earn XP for chatting\n"
                "   • Level up announcements\n"
                "   • Leaderboard, rank cards, reborn system\n"
                "   • Existing levels and XP are preserved\n\n"
                "---\n"
                "Select which features to enable:\n\n"
                "Reply with:\n"
                "• `all` - Enable everything\n"
                "• `1,2,3,4,5,6,7` - Enable specific features (comma-separated)\n"
                "• `none` - Skip for now"
            ),
            color=discord.Color.blue()
        )
        await interaction.followup.send(embed=embed, ephemeral=False)
        
        def check(m):
            return m.author.id == user_id and m.channel.id == interaction.channel.id
        
        try:
            msg = await self.bot.wait_for('message', timeout=120.0, check=check)
            await msg.delete()
            content = msg.content.strip().lower()
            
            enabled_features = []
            
            if content == "all":
                enabled_features = [1, 2, 3, 4, 5, 6, 7]
            elif content == "none":
                enabled_features = []
            else:
                try:
                    # Parse comma-separated numbers
                    parts = content.split(',')
                    for part in parts:
                        try:
                            num = int(part.strip())
                            if 1 <= num <= 7:
                                enabled_features.append(num)
                        except ValueError:
                            pass
                except:
                    await interaction.followup.send("❌ Invalid format. Using default (none enabled).", ephemeral=False)
                    enabled_features = []
            
            # Save settings (ENABLE the selected features, DISABLE others)
            
            # Feature 1: Hacked Account Protection
            if 1 in enabled_features:
                self.save_server_mod_setting(interaction.guild_id, "hack_detection", True)
                await interaction.followup.send("✅ **Hacked Account Protection** enabled!", ephemeral=False)
            else:
                self.save_server_mod_setting(interaction.guild_id, "hack_detection", False)
            
            # Feature 2: Spam Detection
            if 2 in enabled_features:
                self.save_server_mod_setting(interaction.guild_id, "spam_detection", True)
                await interaction.followup.send("✅ **Spam Detection** enabled!", ephemeral=False)
            else:
                self.save_server_mod_setting(interaction.guild_id, "spam_detection", False)
            
            # Feature 3: Anti-Raid
            if 3 in enabled_features:
                self.save_server_mod_setting(interaction.guild_id, "raid_detection", True)
                await interaction.followup.send("✅ **Anti-Raid** enabled!", ephemeral=False)
            else:
                self.save_server_mod_setting(interaction.guild_id, "raid_detection", False)
            
            # Feature 4: Word Filter
            if 4 in enabled_features:
                self.save_server_mod_setting(interaction.guild_id, "word_filter", True)
                await interaction.followup.send("✅ **Word Filter** enabled!", ephemeral=False)
            else:
                self.save_server_mod_setting(interaction.guild_id, "word_filter", False)
            
            # Feature 5: Invite Link Protection
            if 5 in enabled_features:
                self.save_server_mod_setting(interaction.guild_id, "invite_protection", True)
                await interaction.followup.send("✅ **Invite Link Protection** enabled!", ephemeral=False)
            else:
                self.save_server_mod_setting(interaction.guild_id, "invite_protection", False)
            
            # Feature 6: Anti-Nuke Protection
            if 6 in enabled_features:
                self.save_server_mod_setting(interaction.guild_id, "anti_nuke", True)
                await interaction.followup.send("✅ **Anti-Nuke Protection** enabled!", ephemeral=False)
            else:
                self.save_server_mod_setting(interaction.guild_id, "anti_nuke", False)

            # Feature 7: Leveling System
            if 7 in enabled_features:
                self.save_server_mod_setting(interaction.guild_id, "leveling_enabled", True)
                await interaction.followup.send("✅ **Leveling System** enabled! Existing levels and XP are preserved.", ephemeral=False)
            else:
                self.save_server_mod_setting(interaction.guild_id, "leveling_enabled", False)

            # Show completion message
            feature_names = {
                1: "Hacked Account Protection",
                2: "Spam Detection",
                3: "Anti-Raid",
                4: "Word Filter",
                5: "Invite Link Protection",
                6: "Anti-Nuke Protection",
                7: "Leveling System"
            }
            enabled_names = [feature_names[f] for f in enabled_features if f in feature_names]
            
            embed = discord.Embed(
                title="✅ Moderation Setup Complete!",
                description=(
                    "Your moderation features have been configured!\n\n"
                    f"**Enabled Features:** {', '.join(enabled_names) if enabled_names else 'None'}\n\n"
                    "**How to Manage Features:**\n\n"
                    "| Feature ------------------ Turn OFF --------- Turn ON |\n"
                    "|---------|----------|---------|\n"
                    "| Hacked Account Protection | `!hackoff` | `!hackon` |\n"
                    "| Spam Detection -----------| `!stopspam` | `!startspam` |\n"
                    "| Anti-Raid ----------------| `!stopraid` | `!startraid` |\n"
                    "| Word Filter --------------| `!filteroff` | `!filteron` |\n"
                    "| Invite Link Protection ---| `!inviteoff` | `!inviteon` |\n"
                    "| Anti-Nuke Protection -----| `!antinukeoff` | `!antinukeon` |\n"
                    "| Leveling System -----------| `!leveloff` | `!levelon` |\n\n"
                    "**Word Filter Management:**\n"
                    "• `!addfilter <word>` - Add a word to filter\n"
                    "• `!removefilter <word>` - Remove a word from filter\n"
                    "• `!listfilters` - Show all filtered words\n"
                    "• `!clearfilters` - Clear all filtered words\n\n"
                    "**Staff Management:**\n"
                    "• `!staffroles` - View/add/remove staff immunity roles\n"
                    "• `!modstatus` - View current settings\n"
                    "• `!modsetup` - Re-run this setup wizard\n\n"
                    "Thank you for choosing Asaiya Bot! 🎉"
                ),
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            await interaction.followup.send(embed=embed, ephemeral=False)
            
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timed out. You can run `!modsetup` later to continue setup.", ephemeral=False)
        finally:
            # Clean up pending setup
            if user_id in self.pending_mod_setup:
                del self.pending_mod_setup[user_id]

    # ===== MODERATION SETUP COMMAND =====
    @commands.command(name='modsetup')
    @commands.has_permissions(administrator=True)
    async def modsetup(self, ctx):
        """Run the moderation setup wizard manually"""
        if await self.check_duplicate(ctx):
            return
            
        # Check for AsaiyaBot role
        has_bot_role = any(role.name == BOT_ROLE for role in ctx.author.roles)
        if not has_bot_role:
            await ctx.send(f"❌ You need the {BOT_ROLE} role to use this command.")
            return
        
        # Check if user already has a setup session
        if ctx.author.id in self.pending_mod_setup:
            session = self.pending_mod_setup[ctx.author.id]
            session_age = time.time() - session.get('started_at', time.time())
            
            # If session is older than 10 minutes, offer to clear it
            if session_age > 600:  # 10 minutes
                await ctx.send(
                    f"⚠️ You have a stale setup session from {int(session_age // 60)} minutes ago.\n"
                    f"Type `!modsetupcancel` to clear it and start fresh, or wait for automatic cleanup."
                )
                return
            else:
                await ctx.send(
                    f"⚠️ You already have an active setup. Please complete it or use `!modsetupcancel` to cancel.\n"
                    f"Session started {int(session_age // 60)} minute(s) ago."
                )
                return
        
        # Clean up any stale sessions before starting new one
        await self.cleanup_stale_setup_sessions()
        
        await ctx.send("🛡️ Starting moderation setup wizard...")
        
        # Create a new interaction-like context for the setup
        class MockInteraction:
            def __init__(self, ctx, guild_id, channel_id, user):
                self.user = user
                self.guild_id = guild_id
                self.channel_id = channel_id
                self.guild = ctx.guild
                self.channel = ctx.channel
                self.response = MockResponse()
                self.followup = MockFollowup(ctx)
            
            async def defer(self):
                pass
        
        class MockResponse:
            async def send_message(self, content, embed=None, view=None, ephemeral=False):
                pass
        
        class MockFollowup:
            def __init__(self, ctx):
                self.ctx = ctx
            
            async def send(self, content=None, embed=None, view=None, ephemeral=False):
                if embed:
                    await self.ctx.send(embed=embed)
                elif content:
                    await self.ctx.send(content)
                if view:
                    await self.ctx.send(view=view)
            
            async def defer(self):
                pass
        
        mock_interaction = MockInteraction(ctx, ctx.guild.id, ctx.channel.id, ctx.author)
        await self.start_moderation_setup(mock_interaction)

    @commands.command(name='modsetupcancel')
    @commands.has_permissions(administrator=True)
    async def modsetup_cancel(self, ctx):
        """Cancel an active moderation setup session"""
        if await self.check_duplicate(ctx):
            return
            
        # Check for AsaiyaBot role
        has_bot_role = any(role.name == BOT_ROLE for role in ctx.author.roles)
        if not has_bot_role:
            await ctx.send(f"❌ You need the {BOT_ROLE} role to use this command.")
            return
        
        if ctx.author.id in self.pending_mod_setup:
            del self.pending_mod_setup[ctx.author.id]
            await ctx.send("✅ Your active moderation setup has been cancelled. You can now run `!modsetup` again.")
        else:
            await ctx.send("ℹ️ You don't have an active moderation setup session.")

    @commands.command(name='modstatus')
    @commands.has_permissions(administrator=True)
    async def modstatus(self, ctx):
        """Show current moderation settings for this server"""
        if await self.check_duplicate(ctx):
            return
            
        # Check for AsaiyaBot role
        has_bot_role = any(role.name == BOT_ROLE for role in ctx.author.roles)
        if not has_bot_role:
            await ctx.send(f"❌ You need the {BOT_ROLE} role to use this command.")
            return
        
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            
            # Ensure anti_raid_settings table exists
            c.execute('''CREATE TABLE IF NOT EXISTS anti_raid_settings
                         (guild_id TEXT PRIMARY KEY,
                          hack_detection INTEGER DEFAULT 0,
                          spam_detection INTEGER DEFAULT 0,
                          raid_detection INTEGER DEFAULT 0,
                          anti_nuke INTEGER DEFAULT 0,
                          word_filter INTEGER DEFAULT 0,
                          invite_protection INTEGER DEFAULT 0,
                          updated_at REAL)''')
            
            # Get settings from anti_raid_settings
            c.execute("SELECT hack_detection, spam_detection, raid_detection, anti_nuke, word_filter, invite_protection FROM anti_raid_settings WHERE guild_id = ?",
                      (str(ctx.guild.id),))
            result = c.fetchone()

            # Get verification_enabled from server_mod_settings
            c.execute("SELECT verification_enabled FROM server_mod_settings WHERE guild_id = ?",
                      (str(ctx.guild.id),))
            verif_row = c.fetchone()
            
            # Get verification role
            c.execute("SELECT role_name FROM verify_settings WHERE guild_id = ?", (str(ctx.guild.id),))
            verif_result = c.fetchone()
            
            # Get staff roles
            c.execute("SELECT role_name FROM staff_immunity_roles WHERE guild_id = ?", (str(ctx.guild.id),))
            staff_roles = c.fetchall()
            
            # Get filter word count
            server_conn = self.get_cached_connection(ctx.guild.id)
            if server_conn:
                server_c = server_conn.cursor()
                server_c.execute("SELECT COUNT(*) FROM filter_words")
                filter_count = server_c.fetchone()[0]
            else:
                filter_count = 0
            
            conn.close()
            
            # Default to OFF if no settings exist
            hack = bool(result[0]) if result else False
            spam = bool(result[1]) if result else False
            raid = bool(result[2]) if result else False
            anti_nuke = bool(result[3]) if result else False
            word_filter = bool(result[4]) if result else False
            invite_protection = bool(result[5]) if result else False
            verif_enabled = bool(verif_row[0]) if verif_row else False
            
            embed = discord.Embed(
                title="🛡️ Server Moderation Status",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(name="🤖 Hacked Account Protection", value="🟢 ON" if hack else "🔴 OFF", inline=True)
            embed.add_field(name="💬 Spam Detection", value="🟢 ON" if spam else "🔴 OFF", inline=True)
            embed.add_field(name="👥 Anti-Raid", value="🟢 ON" if raid else "🔴 OFF", inline=True)
            embed.add_field(name="💥 Anti-Nuke", value="🟢 ON" if anti_nuke else "🔴 OFF", inline=True)
            embed.add_field(name="🔇 Word Filter", value=f"🟢 ON ({filter_count} words)" if word_filter else "🔴 OFF", inline=True)
            embed.add_field(name="🚫 Invite Link Protection", value="🟢 ON" if invite_protection else "🔴 OFF", inline=True)
            embed.add_field(name="🔐 Verification System", value="🟢 ON" if verif_enabled else "🔴 OFF", inline=True)

            # Get leveling setting — ensure column exists first (upgrade safety)
            try:
                conn2 = sqlite3.connect(MAIN_DB_PATH)
                c2 = conn2.cursor()
                try:
                    c2.execute("ALTER TABLE server_mod_settings ADD COLUMN leveling_enabled INTEGER DEFAULT 0")
                    conn2.commit()
                except sqlite3.OperationalError:
                    pass  # Column already exists
                c2.execute("SELECT leveling_enabled FROM server_mod_settings WHERE guild_id = ?", (str(ctx.guild.id),))
                level_row = c2.fetchone()
                conn2.close()
                level_enabled = bool(level_row[0]) if level_row and level_row[0] is not None else False
            except Exception:
                level_enabled = False
            embed.add_field(name="⭐ Leveling System", value="🟢 ON" if level_enabled else "🔴 OFF", inline=True)

            if verif_enabled and verif_result:
                embed.add_field(name="Verification Role", value=verif_result[0], inline=True)
            
            if staff_roles:
                staff_list = "\n".join([f"• {r[0]}" for r in staff_roles[:10]])
                embed.add_field(name="👥 Staff Immunity Roles", value=staff_list, inline=False)
            else:
                embed.add_field(name="👥 Staff Immunity Roles", value="*Default: AsaiyaBot*", inline=False)
            
            embed.set_footer(text="Use !modsetup to reconfigure • !addfilter to add words")
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error loading settings: {e}")

    @commands.command(name='Arole')
    async def arole(self, ctx):
        """Grant Administrator permission to AsaiyaBot role, make roles hoisted, and assign bot to a Bot role"""
        if await self.check_duplicate(ctx):
            return

        # Check for AsaiyaBot role on the caller
        has_bot_role = any(role.name == BOT_ROLE for role in ctx.author.roles)
        if not has_bot_role:
            await ctx.send(f"❌ You need the {BOT_ROLE} role to use this command.")
            return

        changes_made = []
        errors = []

        # ===== PROCESS ASAIYABOT ROLE =====
        bot_role = discord.utils.get(ctx.guild.roles, name=BOT_ROLE)
        if not bot_role:
            errors.append(f"❌ Could not find the **{BOT_ROLE}** role in this server.")
        else:
            try:
                # Grant Administrator permission
                if bot_role.permissions.administrator:
                    changes_made.append(f"✅ The **{BOT_ROLE}** role already has Administrator permission.")
                else:
                    new_perms = bot_role.permissions
                    new_perms = discord.Permissions(new_perms.value | discord.Permissions.administrator.flag)
                    await bot_role.edit(permissions=new_perms, reason=f"!Arole used by {ctx.author}")
                    changes_made.append(f"✅ Granted **Administrator** permission to the **{BOT_ROLE}** role!")

                # Make AsaiyaBot role hoisted
                if not bot_role.hoist:
                    await bot_role.edit(hoist=True, reason=f"!Arole used by {ctx.author}")
                    changes_made.append(f"✅ Made **{BOT_ROLE}** role hoisted (displays separately in member list).")
                else:
                    changes_made.append(f"✅ **{BOT_ROLE}** role is already hoisted.")

            except discord.Forbidden:
                errors.append("❌ I don't have permission to edit the AsaiyaBot role. Make sure my role is above it in the role hierarchy.")
            except Exception as e:
                errors.append(f"❌ Failed to update AsaiyaBot role: {e}")

        # ===== PROCESS BOT ROLE =====
        # Check for existing Bot role (case insensitive)
        bot_role_names = ["Bot", "Bots", "bot", "bots"]
        existing_bot_role = None

        for role_name in bot_role_names:
            existing_bot_role = discord.utils.get(ctx.guild.roles, name=role_name)
            if existing_bot_role:
                changes_made.append(f"✅ Found existing role: **{existing_bot_role.name}**")
                break

        # If no Bot role exists, create one
        if not existing_bot_role:
            try:
                # Create the Bot role
                existing_bot_role = await ctx.guild.create_role(
                    name="Bot",
                    reason="Created by !Arole command",
                    hoist=True,
                    mentionable=False
                )
                changes_made.append(f"✅ Created new **Bot** role and made it hoisted.")
            except Exception as e:
                errors.append(f"❌ Failed to create Bot role: {e}")

        # If we have a Bot role (existing or newly created), process it
        if existing_bot_role:
            try:
                # Make sure the role is hoisted
                if not existing_bot_role.hoist:
                    await existing_bot_role.edit(hoist=True, reason="!Arole command")
                    changes_made.append(f"✅ Made **{existing_bot_role.name}** role hoisted.")
                else:
                    changes_made.append(f"✅ **{existing_bot_role.name}** role is already hoisted.")

                # Get the bot member and assign the role
                bot_member = ctx.guild.get_member(self.bot.user.id)
                if bot_member:
                    if existing_bot_role not in bot_member.roles:
                        await bot_member.add_roles(existing_bot_role, reason="!Arole command")
                        changes_made.append(f"✅ Assigned **{existing_bot_role.name}** role to {bot_member.name}.")
                    else:
                        changes_made.append(f"✅ {bot_member.name} already has the **{existing_bot_role.name}** role.")
                else:
                    errors.append("❌ Could not find the bot member in this server.")

            except discord.Forbidden:
                errors.append("❌ I don't have permission to edit the Bot role.")
            except Exception as e:
                errors.append(f"❌ Failed to update Bot role: {e}")

        # ===== ALSO CHECK FOR "Asaiya DC Bot" ROLE (legacy) =====
        asaiya_dc_bot_role = discord.utils.get(ctx.guild.roles, name="Asaiya DC Bot")
        if asaiya_dc_bot_role:
            try:
                if not asaiya_dc_bot_role.hoist:
                    await asaiya_dc_bot_role.edit(hoist=True, reason=f"!Arole used by {ctx.author}")
                    changes_made.append(f"✅ Made **Asaiya DC Bot** role hoisted (legacy role).")
                else:
                    changes_made.append(f"✅ **Asaiya DC Bot** role is already hoisted.")
            except Exception as e:
                errors.append(f"⚠️ Could not update Asaiya DC Bot role: {e}")

        # ===== SEND RESULTS =====
        from datetime import datetime
        embed = discord.Embed(
            title="🔧 Role Configuration Complete",
            color=discord.Color.green() if not errors else discord.Color.orange(),
            timestamp=datetime.utcnow()
        )

        if changes_made:
            # Split into chunks if too many (embed field limit is 1024 chars)
            changes_text = "\n".join(changes_made)
            if len(changes_text) > 1000:
                # Split into multiple fields
                chunk_size = 800
                chunks = [changes_text[i:i+chunk_size] for i in range(0, len(changes_text), chunk_size)]
                for i, chunk in enumerate(chunks):
                    embed.add_field(
                        name=f"✅ Changes Made ({i+1}/{len(chunks)})",
                        value=chunk,
                        inline=False
                    )
            else:
                embed.add_field(name="✅ Changes Made", value=changes_text, inline=False)

        if errors:
            embed.add_field(name="⚠️ Errors", value="\n".join(errors), inline=False)

        embed.set_footer(text=f"Run by {ctx.author}")
        await ctx.send(embed=embed)

    # ===== HELPER FUNCTIONS (existing) =====

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

        # Get database path from main database
        db_path = None
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
                db_path = result[0]
        except Exception as e:
            print(f"Error getting server db path for {guild_id}: {e}")
            return None

        if not db_path:
            # Server not activated
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

    def is_owner_server(self, ctx):
        return ctx.guild and ctx.guild.id == OWNER_SERVER_ID
        
    def has_bot_role(self, member):
        """Check if member has the AsaiyaBot role"""
        if not isinstance(member, discord.Member):
            return False
        return any(role.name == BOT_ROLE for role in member.roles)

    async def log_key_event(self, event_type, guild, user=None, key=None, success=True, extra_info=""):
        channel = self.bot.get_channel(KEY_LOG_CHANNEL_ID)
        if not channel:
            return

        colors = {
            'activation_success': discord.Color.green(),
            'activation_fail': discord.Color.red(),
            'key_created': discord.Color.blue(),
            'key_deleted': discord.Color.orange(),
            'key_reactivated': discord.Color.purple(),
            'verification_success': discord.Color.green(),
            'verification_fail': discord.Color.red(),
            'server_left': discord.Color.purple(),
            'expiry_soon': discord.Color.gold()
        }

        embed = discord.Embed(
            title=f"🔐 {event_type.replace('_', ' ').title()}",
            color=colors.get(event_type, discord.Color.greyple()),
            timestamp=datetime.utcnow()
        )

        if guild:
            embed.add_field(name="Server", value=guild.name, inline=True)
            embed.add_field(name="Server ID", value=guild.id, inline=True)
            embed.add_field(name="Members", value=guild.member_count, inline=True)

        if key:
            embed.add_field(name="Key", value=f"`{key}`", inline=True)

        if user:
            embed.add_field(name="User", value=f"{user} ({user.id})", inline=True)

        embed.add_field(name="Status", value="✅ Success" if success else "❌ Failed", inline=True)

        if extra_info:
            embed.add_field(name="Details", value=extra_info, inline=False)

        await channel.send(embed=embed)

    async def auto_register_server(self, guild):
        """Auto-register a server when key system is disabled — creates DB like !botkey would"""
        try:
            # Check if already registered
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT guild_id FROM authorized_servers WHERE guild_id = ?", (str(guild.id),))
            already = c.fetchone()
            conn.close()
            if already:
                return  # Already registered, skip

            # Sanitize server name for filename (inline — no import needed)
            import re
            safe_name = re.sub(r'[^\w\s-]', '', guild.name)
            safe_name = safe_name.replace(' ', '_')[:50]

            # Create server DB file path
            db_filename = f"server_{guild.id}_{safe_name}.db"
            db_path = os.path.join(DB_FOLDER, db_filename)

            # Initialize the server database with all required tables (inline)
            srv_conn = sqlite3.connect(db_path)
            srv_c = srv_conn.cursor()
            srv_c.executescript('''
                CREATE TABLE IF NOT EXISTS warnings
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, mod_id TEXT, reason TEXT, timestamp REAL);
                CREATE TABLE IF NOT EXISTS afk
                    (user_id TEXT PRIMARY KEY, reason TEXT, timestamp REAL);
                CREATE TABLE IF NOT EXISTS reminders
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, channel_id TEXT, message TEXT, remind_time REAL);
                CREATE TABLE IF NOT EXISTS protected_channels
                    (channel_id TEXT PRIMARY KEY, channel_name TEXT, protected_since REAL, protect_type TEXT DEFAULT 'channel');
                CREATE TABLE IF NOT EXISTS message_backup
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT, channel_name TEXT,
                     author_id TEXT, author_name TEXT, content TEXT, timestamp REAL, attachments TEXT);
                CREATE TABLE IF NOT EXISTS deleted_channels
                    (channel_name TEXT PRIMARY KEY, category_name TEXT, deleted_at REAL);
                CREATE TABLE IF NOT EXISTS reaction_roles
                    (message_id TEXT PRIMARY KEY, channel_id TEXT, title TEXT, description TEXT, created_at REAL);
                CREATE TABLE IF NOT EXISTS reaction_role_items
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT, emoji TEXT,
                     role_id TEXT, role_name TEXT,
                     FOREIGN KEY (message_id) REFERENCES reaction_roles(message_id));
                CREATE TABLE IF NOT EXISTS reaction_one_role_groups
                    (group_id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT, message_id TEXT, group_name TEXT);
                CREATE TABLE IF NOT EXISTS reaction_one_role_items
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER, emoji TEXT,
                     role_id TEXT, role_name TEXT,
                     FOREIGN KEY (group_id) REFERENCES reaction_one_role_groups(group_id));
                CREATE TABLE IF NOT EXISTS log_channels
                    (log_channel_id TEXT, welcome_channel_id TEXT, leave_channel_id TEXT);
                CREATE TABLE IF NOT EXISTS filter_words
                    (word TEXT PRIMARY KEY, reason TEXT, added_by TEXT, added_at REAL);
                CREATE TABLE IF NOT EXISTS filter_bypass_roles
                    (word TEXT, role_id TEXT, role_name TEXT, added_by TEXT, added_at REAL,
                     PRIMARY KEY (word, role_id));
                CREATE TABLE IF NOT EXISTS join_timestamps
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, timestamp REAL);
                CREATE TABLE IF NOT EXISTS active_tickets
                    (guild_id TEXT, user_id TEXT, channel_id TEXT, PRIMARY KEY (guild_id, user_id));
            ''')
            srv_conn.commit()
            srv_conn.close()

            # Register in authorized_servers with no expiry (permanent while key system is off)
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("""INSERT OR REPLACE INTO authorized_servers
                         (guild_id, key_used, authorized_since, expires_at, last_verified, db_path)
                         VALUES (?, ?, ?, ?, ?, ?)""",
                      (str(guild.id), "KEY_SYSTEM_DISABLED", time.time(), None, time.time(), db_path))

            # Also register in servers table
            c.execute("SELECT last_number FROM server_counter WHERE id = 1")
            row = c.fetchone()
            next_num = (row[0] if row else 0) + 1
            c.execute("UPDATE server_counter SET last_number = ? WHERE id = 1", (next_num,))
            c.execute("""INSERT OR IGNORE INTO servers
                         (guild_id, server_number, added_at, name, owner_id, db_path)
                         VALUES (?, ?, ?, ?, ?, ?)""",
                      (str(guild.id), next_num, time.time(), guild.name, str(guild.owner_id), db_path))
            conn.commit()
            conn.close()

            # ── Create AsaiyaBot role if it doesn't exist ────────────────
            bot_role = discord.utils.get(guild.roles, name=BOT_ROLE)
            if not bot_role:
                try:
                    permissions = discord.Permissions(administrator=True)
                    bot_role = await guild.create_role(
                        name=BOT_ROLE,
                        permissions=permissions,
                        color=discord.Color.blurple(),
                        reason="Auto-created by Asaiya Bot (key system disabled)"
                    )
                    # Position it just below the bot's highest role
                    bot_member = guild.get_member(self.bot.user.id)
                    if bot_member:
                        target_position = max(bot_member.top_role.position - 1, 1)
                        await bot_role.edit(position=target_position)
                    print(f"✅ Created AsaiyaBot role in {guild.name}")
                except Exception as e:
                    print(f"⚠️ Could not create AsaiyaBot role in {guild.name}: {e}")

            # ── Assign role to all members with Administrator permissions ──
            if bot_role:
                assigned = 0
                for member in guild.members:
                    if member.bot:
                        continue
                    if member.guild_permissions.administrator:
                        try:
                            await member.add_roles(bot_role, reason="Auto-assigned by Asaiya Bot (key system disabled)")
                            assigned += 1
                        except Exception as e:
                            print(f"⚠️ Could not assign AsaiyaBot role to {member} in {guild.name}: {e}")
                print(f"✅ Assigned AsaiyaBot role to {assigned} admin(s) in {guild.name}")

            # ── Send instructions to the target channel ───────────────────
            try:
                target_channel = (
                    discord.utils.get(guild.text_channels, name="general")
                    or guild.system_channel
                    or next((ch for ch in guild.text_channels if ch.permissions_for(guild.me).send_messages), None)
                )
                if target_channel and bot_role:
                    embed = discord.Embed(
                        title="🎉 Asaiya Bot is Ready!",
                        description=(
                            f"The **AsaiyaBot** role has been created and automatically given to "
                            f"everyone with Administrator permissions.\n\n"
                            f"**You can also give this role to other trusted staff** — "
                            f"it grants full access to all bot management commands.\n\n"
                            f"**Get started:**\n"
                            f"• `!modsetup` — Configure moderation features\n"
                            f"• `!setserver` — Set up server channels and roles\n"
                            f"• `!help` — See all available commands"
                        ),
                        color=discord.Color.blurple()
                    )
                    embed.set_footer(text="Key system is currently disabled — no key required")
                    await target_channel.send(embed=embed)
            except Exception as e:
                print(f"⚠️ Could not send setup instructions in {guild.name}: {e}")

            print(f"✅ Auto-registered server: {guild.name} (ID: {guild.id})")
        except Exception as e:
            print(f"❌ Failed to auto-register {guild.name}: {e}")

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

    # ===== TEMPLATE CLEANUP METHOD (existing) =====
    async def cleanup_previous_template(self, guild, new_template, results):
        """Delete ALL previous template channels and roles"""
        guild_id = guild.id
        
        # Get the last used template from database
        last_template = self.load_template_history(guild_id)

        # If no previous template, skip cleanup
        if not last_template:
            print(f"📝 No previous template found for guild {guild_id}")
            return

        results["categories"].append(f"🔄 Cleaning up previous **{last_template}** template...")
        print(f"🔄 Cleaning up {last_template} to make way for {new_template} in {guild.name}")

        # ===== DEFINE ALL CATEGORIES AND ROLES BY TEMPLATE =====
        
        # Gaming categories
        gaming_categories = [
            GAMING_INFO_CATEGORY,
            GAMING_COMMUNITY_CATEGORY,
            GAMING_COMP_CATEGORY,
            GAMING_CONTENT_CATEGORY,
            GAMING_VOICE_CATEGORY
        ]
        
        # Gaming roles
        gaming_roles = [
            "👑 Owner", "🛡️ Admin", "⚔️ Moderator", "🧠 Strategist", "🎮 Gamer",
            "🆕 New Recruit", "🥇 MVP", "🔥 Tryhard", "🖥️ PC", "🎮 PlayStation",
            "❎ Xbox", "📱 Mobile"
        ]
        
        # Community categories
        community_categories = [
            COMMUNITY_INFO_CATEGORY,
            COMMUNITY_GENERAL_CATEGORY,
            COMMUNITY_DISCUSSION_CATEGORY,
            COMMUNITY_CONNECTION_CATEGORY,
            COMMUNITY_VOICE_CATEGORY
        ]
        
        # Community roles
        community_roles = [
            "👑 Owner", "🛡️ Admin", "🔧 Moderator", "🧩 Helper", "🌱 New Member",
            "💬 Active Member", "🌟 Contributor", "🎨 Creative", "💻 Tech Enthusiast",
            "🌙 Night Owl", "👻 Lurker"
        ]
        
        # Ticket categories
        ticket_categories = [
            BUG_CATEGORY,
            BUY_CATEGORY,
            REPORT_CATEGORY,
            VERIFY_CATEGORY,
            ASAIYA_TICKET_CATEGORY,
            ASAIYA_DONE_CATEGORY,
            STAFF_CATEGORY
        ]
        
        # Ticket roles
        ticket_roles = [SUPPORT_ROLE, REQUEST_ROLE]

        # ===== DETERMINE WHAT TO DELETE BASED ON LAST TEMPLATE =====
        categories_to_delete = []
        roles_to_delete = []

        if last_template == 'gaming':
            categories_to_delete = gaming_categories
            roles_to_delete = gaming_roles
        elif last_template == 'community':
            categories_to_delete = community_categories
            roles_to_delete = community_roles
        elif last_template == 'ticket':
            categories_to_delete = ticket_categories
            roles_to_delete = ticket_roles
        elif last_template == 'full':
            categories_to_delete = gaming_categories + community_categories + ticket_categories
            roles_to_delete = gaming_roles + community_roles + ticket_roles
        elif last_template == 'minimal':
            # Minimal template only has Command Center and Gateway - don't delete them
            # as they're shared across all templates
            categories_to_delete = []
            roles_to_delete = []
        elif last_template == 'custom':
            # For custom template, we don't know what was created, so we'll skip automatic cleanup
            # User will need to manually delete if they want to start fresh
            categories_to_delete = []
            roles_to_delete = []
            results["categories"].append("⚠️ Custom template detected - manual cleanup may be needed")

        # ===== DELETE CATEGORIES =====
        deleted_cats = 0
        for cat_name in categories_to_delete:
            category = discord.utils.get(guild.categories, name=cat_name)
            if category:
                try:
                    print(f"🗑️ Deleting category: {cat_name}")
                    # Delete all channels in the category first
                    for channel in category.channels:
                        try:
                            await channel.delete()
                            await asyncio.sleep(0.2)
                        except Exception as e:
                            print(f"Could not delete channel in {cat_name}: {e}")
                    # Then delete the category
                    await category.delete()
                    deleted_cats += 1
                    await asyncio.sleep(0.3)
                except Exception as e:
                    results["errors"].append(f"⚠️ Could not delete {cat_name}: {e}")
                    print(f"Error deleting category {cat_name}: {e}")

        if deleted_cats > 0:
            results["categories"].append(f"✅ Deleted {deleted_cats} old categories")

        # ===== DELETE ROLES =====
        bot_member = guild.get_member(self.bot.user.id)
        deleted_roles = 0
        
        for role_name in roles_to_delete:
            role = discord.utils.get(guild.roles, name=role_name)
            if role and role < bot_member.top_role:  # Can't delete roles higher than bot
                try:
                    print(f"🗑️ Deleting role: {role_name}")
                    await role.delete()
                    deleted_roles += 1
                    await asyncio.sleep(0.3)
                except Exception as e:
                    results["errors"].append(f"⚠️ Could not delete {role_name}: {e}")
                    print(f"Error deleting role {role_name}: {e}")

        if deleted_roles > 0:
            results["roles"].append(f"✅ Deleted {deleted_roles} old roles")

    # ===== KEY COMMANDS (with moderation setup trigger) =====

    @commands.command(name='botkey')
    async def botkey(self, ctx, key: str = None):
        """Activate this server with a key.
        Usage: !botkey [your-key-here]
        """
        if await self.check_duplicate(ctx):
            return
            
        if not key:
            await ctx.send("❌ Please provide a key: `!botkey [your-key-here]`")
            return

        guild = ctx.guild
        author = ctx.author
        has_bot_role = any(role.name == BOT_ROLE for role in author.roles) \
                       if isinstance(author, discord.Member) else False

        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT key_used, expires_at FROM authorized_servers WHERE guild_id = ?",
                  (str(guild.id),))
        existing = c.fetchone()
        conn.close()

        if existing:
            key_used, expires_at = existing

            if expires_at is None or time.time() < expires_at:
                if has_bot_role:
                    if expires_at:
                        embed = discord.Embed(
                            title="✅ Server Already Activated",
                            description=(
                                f"This server is already activated.\n\n"
                                f"Your current key expires <t:{int(expires_at)}:R>."
                            ),
                            color=discord.Color.green()
                        )
                    else:
                        embed = discord.Embed(
                            title="✅ Server Already Activated",
                            description="This server is already activated with a permanent key.",
                            color=discord.Color.green()
                        )
                    await ctx.send(embed=embed)
                return

            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM authorized_servers WHERE guild_id = ?", (str(guild.id),))
            c.execute("UPDATE key_uses SET is_active = 0 WHERE key = ? AND guild_id = ?",
                      (key_used, str(guild.id)))
            conn.commit()
            conn.close()

        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT key_type, max_uses, uses_remaining, expiry_duration, is_active FROM bot_keys WHERE key = ?",
                  (key,))
        key_data = c.fetchone()
        conn.close()

        if not key_data:
            await self.log_key_event('activation_fail', guild, author, key, False, "Key not found")
            await ctx.send("❌ Invalid key. Please check and try again.")
            return

        key_type, max_uses, uses_remaining, expiry_duration, is_active = key_data

        if not is_active:
            await self.log_key_event('activation_fail', guild, author, key, False, "Key is deactivated")
            await ctx.send("❌ This key has been deactivated.")
            return

        success = False
        expires_at = None
        extra_info = ""

        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()

        if key_type == 'master':
            success = True
            extra_info = "Master key - unlimited uses"

        elif key_type == 'single':
            c.execute("SELECT id FROM key_uses WHERE key = ? AND is_active = 1", (key,))
            if c.fetchone():
                await self.log_key_event('activation_fail', guild, author, key, False, "Key already in use")
                await ctx.send("❌ This key is already in use by another server.")
                conn.close()
                return
            success = True
            uses_remaining = 0

        elif key_type == 'multi':
            if uses_remaining <= 0:
                await self.log_key_event('activation_fail', guild, author, key, False, "No uses remaining")
                await ctx.send("❌ This key has no remaining uses.")
                conn.close()
                return
            success = True
            uses_remaining -= 1

        elif key_type == 'timed':
            if expiry_duration:
                expires_at = time.time() + expiry_duration
                extra_info = f"Expires: <t:{int(expires_at)}:R>"
            success = True

        if success:
            c.execute("INSERT INTO key_uses (key, guild_id, guild_name, used_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                      (key, str(guild.id), guild.name, time.time(), expires_at))
            c.execute("""INSERT OR REPLACE INTO authorized_servers
                         (guild_id, key_used, authorized_since, expires_at, last_verified)
                         VALUES (?, ?, ?, ?, ?)""",
                      (str(guild.id), key, time.time(), expires_at, time.time()))

            if key_type in ['single', 'multi']:
                c.execute("UPDATE bot_keys SET uses_remaining = ? WHERE key = ?", (uses_remaining, key))

            conn.commit()
            conn.close()

            await self.log_key_event('activation_success', guild, author, key, True, extra_info)

            # ===== CREATE SERVER DATABASE WITH NAME =====
            # Sanitize server name for filename
            safe_name = re.sub(r'[^\w\s-]', '', guild.name)
            safe_name = safe_name.replace(' ', '_')[:50]
            db_path = os.path.join(DB_FOLDER, f"{safe_name}.db")
            
            # Initialize the server database
            try:
                # Create tables in the new database
                server_conn = sqlite3.connect(db_path)
                server_c = server_conn.cursor()
                
                server_c.execute('''CREATE TABLE IF NOT EXISTS warnings
                             (id INTEGER PRIMARY KEY AUTOINCREMENT,
                              user_id TEXT,
                              mod_id TEXT,
                              reason TEXT,
                              timestamp REAL)''')
                
                server_c.execute('''CREATE TABLE IF NOT EXISTS afk
                             (user_id TEXT PRIMARY KEY,
                              reason TEXT,
                              timestamp REAL)''')
                
                server_c.execute('''CREATE TABLE IF NOT EXISTS reminders
                             (id INTEGER PRIMARY KEY AUTOINCREMENT,
                              user_id TEXT,
                              channel_id TEXT,
                              message TEXT,
                              remind_time REAL)''')
                
                server_c.execute('''CREATE TABLE IF NOT EXISTS protected_channels
                             (channel_id TEXT PRIMARY KEY,
                              channel_name TEXT,
                              protected_since REAL,
                              protect_type TEXT DEFAULT 'channel')''')
                
                server_c.execute('''CREATE TABLE IF NOT EXISTS message_backup
                             (id INTEGER PRIMARY KEY AUTOINCREMENT,
                              channel_id TEXT,
                              channel_name TEXT,
                              author_id TEXT,
                              author_name TEXT,
                              content TEXT,
                              timestamp REAL,
                              attachments TEXT)''')
                
                server_c.execute('''CREATE TABLE IF NOT EXISTS deleted_channels
                             (channel_name TEXT PRIMARY KEY,
                              category_name TEXT,
                              deleted_at REAL)''')
                
                server_c.execute('''CREATE TABLE IF NOT EXISTS reaction_roles
                             (message_id TEXT PRIMARY KEY,
                              channel_id TEXT,
                              title TEXT,
                              description TEXT,
                              created_at REAL)''')
                
                server_c.execute('''CREATE TABLE IF NOT EXISTS reaction_role_items
                             (id INTEGER PRIMARY KEY AUTOINCREMENT,
                              message_id TEXT,
                              emoji TEXT,
                              role_id TEXT,
                              role_name TEXT,
                              FOREIGN KEY (message_id) REFERENCES reaction_roles(message_id))''')
                
                server_c.execute('''CREATE TABLE IF NOT EXISTS reaction_one_role_groups
                             (group_id INTEGER PRIMARY KEY AUTOINCREMENT,
                              guild_id TEXT,
                              message_id TEXT,
                              group_name TEXT)''')
                
                server_c.execute('''CREATE TABLE IF NOT EXISTS reaction_one_role_items
                             (id INTEGER PRIMARY KEY AUTOINCREMENT,
                              group_id INTEGER,
                              emoji TEXT,
                              role_id TEXT,
                              role_name TEXT,
                              FOREIGN KEY (group_id) REFERENCES reaction_one_role_groups(group_id))''')
                
                server_c.execute('''CREATE TABLE IF NOT EXISTS log_channels
                             (log_channel_id TEXT,
                              welcome_channel_id TEXT,
                              leave_channel_id TEXT)''')
                
                server_c.execute('''CREATE TABLE IF NOT EXISTS filter_words
                             (word TEXT PRIMARY KEY)''')
                
                server_c.execute('''CREATE TABLE IF NOT EXISTS join_timestamps
                             (id INTEGER PRIMARY KEY AUTOINCREMENT,
                              user_id TEXT,
                              timestamp REAL)''')
                
                server_c.execute('''CREATE TABLE IF NOT EXISTS active_tickets
                             (guild_id TEXT,
                              user_id TEXT,
                              channel_id TEXT,
                              PRIMARY KEY (guild_id, user_id))''')
                
                server_conn.commit()
                server_conn.close()
                
                print(f"📁 Created server database for: {guild.name} at {db_path}")
                
                # Update the servers table with the db_path
                main_conn = sqlite3.connect(MAIN_DB_PATH)
                main_c = main_conn.cursor()
                
                # Check if server already exists in servers table
                main_c.execute("SELECT server_number FROM servers WHERE guild_id = ?", (str(guild.id),))
                existing_server = main_c.fetchone()
                
                if existing_server:
                    # Update existing record
                    main_c.execute("UPDATE servers SET db_path = ? WHERE guild_id = ?", 
                                  (db_path, str(guild.id)))
                else:
                    # Insert new server record
                    main_c.execute("SELECT last_number FROM server_counter WHERE id = 1")
                    last = main_c.fetchone()
                    last_number = last[0] if last else 0
                    server_number = last_number + 1
                    main_c.execute("UPDATE server_counter SET last_number = ? WHERE id = 1", (server_number,))
                    main_c.execute("INSERT INTO servers (guild_id, server_number, added_at, name, owner_id, db_path) VALUES (?, ?, ?, ?, ?, ?)",
                                  (str(guild.id), server_number, time.time(), guild.name, str(guild.owner_id), db_path))
                
                # Update authorized_servers with db_path
                main_c.execute("UPDATE authorized_servers SET db_path = ? WHERE guild_id = ?", 
                              (db_path, str(guild.id)))
                
                main_conn.commit()
                main_conn.close()
                
            except Exception as e:
                print(f"❌ Error creating server database for {guild.name}: {e}")
                # Continue even if database creation fails - the server is still activated

            bot_role = discord.utils.get(guild.roles, name=BOT_ROLE)
            if not bot_role:
                try:
                    # Create role with Administrator permissions
                    permissions = discord.Permissions(administrator=True)
                    bot_role = await guild.create_role(
                        name=BOT_ROLE,
                        permissions=permissions,
                        reason="Auto-created by !botkey"
                    )
                    bot_member = guild.get_member(self.bot.user.id)
                    bot_highest = bot_member.top_role
                    target_position = min(bot_highest.position - 1, 1)
                    await bot_role.edit(position=target_position)
                except Exception as e:
                    print(f"Could not create {BOT_ROLE} role: {e}")

            try:
                member = guild.get_member(author.id) or await guild.fetch_member(author.id)
                if member and bot_role:
                    await member.add_roles(bot_role, reason="Activated server with !botkey")
            except Exception as e:
                print(f"Could not assign {BOT_ROLE} role: {e}")

            embed = discord.Embed(
                title="✅ Server Activated!",
                description=f"Key `{key}` has been successfully activated for this server.",
                color=discord.Color.green()
            )
            embed.add_field(name="Key Type", value=key_type.title(), inline=True)
            if expires_at:
                embed.add_field(name="Expires", value=f"<t:{int(expires_at)}:R>", inline=True)
            embed.add_field(
                name="What now?",
                value=(
                    f"All bot commands are now available!\n"
                    f"You've been given the **{BOT_ROLE}** role automatically.\n"
                    f"Run `!setserver` to finish setting up your server.\n"
                    f"Run `!modsetup` to configure moderation features.\n"
                    f"Use `!addfilter` to add words to the word filter."
                ),
                inline=False
            )
            embed.set_footer(text=f"Activated by {author}")
            await ctx.send(embed=embed)
            
            # ===== TRIGGER MODERATION SETUP =====
            # Create a message with buttons for moderation setup
            setup_embed = discord.Embed(
                title="🛡️ Server Moderation Setup",
                description=(
                    f"{self.bot.user.mention} offers automatic server moderation features to protect your server.\n\n"
                    f"**Features include:**\n"
                    f"• Hacked Account Protection\n"
                    f"• Spam Detection\n"
                    f"• Anti-Raid Detection\n"
                    f"• Word Filter (manage with `!addfilter`, `!listfilters`, `!removefilter`)\n"
                    f"• Invite Link Protection\n"
                    f"• Anti-Nuke Protection\n\n"
                    f"Would you like to set up moderation now?"
                ),
                color=discord.Color.blue()
            )
            
            view = self.ModSetupView(self, guild.id)
            await ctx.send(embed=setup_embed, view=view)

            # Refresh skey live message in owner server if it exists
            await self.refresh_skey_message(OWNER_SERVER_ID)
            
        else:
            conn.close()

    # ===== EXISTING COMMANDS (unchanged from original) =====
    @commands.command(name='ckey')
    async def ckey(self, ctx, key: str):
        """Create a single-use key. Owner server only."""
        if await self.check_duplicate(ctx):
            return
            
        if not self.is_owner_server(ctx):
            await ctx.send("🔐 This command can only be used in the bot owner's server!")
            return
            
        if not self.has_bot_role(ctx.author):
            await ctx.send(f"❌ You need the **{BOT_ROLE}** role to create keys!")
            return

        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO bot_keys (key, key_type, created_by, created_at, max_uses, uses_remaining) VALUES (?, ?, ?, ?, ?, ?)",
                      (key, 'single', str(ctx.author.id), time.time(), 1, 1))
            conn.commit()
            await self.log_key_event('key_created', ctx.guild, ctx.author, key, True, "Single-use key")
            embed = discord.Embed(title="🔑 Key Created", color=discord.Color.blue())
            embed.add_field(name="Key", value=f"`{key}`", inline=True)
            embed.add_field(name="Type", value="Single Use", inline=True)
            await ctx.send(embed=embed)
            await self.refresh_skey_message(ctx.guild.id)
        except sqlite3.IntegrityError:
            await ctx.send(f"❌ Key `{key}` already exists!")
        finally:
            conn.close()

    @commands.command(name='cmkey')
    async def cmkey(self, ctx, key: str):
        """Create a master key (unlimited uses). Owner server only."""
        if await self.check_duplicate(ctx):
            return
            
        if not self.is_owner_server(ctx):
            await ctx.send("🔐 This command can only be used in the bot owner's server!")
            return
            
        if not self.has_bot_role(ctx.author):
            await ctx.send(f"❌ You need the **{BOT_ROLE}** role to create keys!")
            return

        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO bot_keys (key, key_type, created_by, created_at, max_uses, uses_remaining) VALUES (?, ?, ?, ?, ?, ?)",
                      (key, 'master', str(ctx.author.id), time.time(), 999999, 999999))
            conn.commit()
            await self.log_key_event('key_created', ctx.guild, ctx.author, key, True, "Master key")
            embed = discord.Embed(title="👑 Master Key Created", color=discord.Color.gold())
            embed.add_field(name="Key", value=f"`{key}`", inline=True)
            embed.add_field(name="Type", value="Master (Unlimited)", inline=True)
            await ctx.send(embed=embed)
            await self.refresh_skey_message(ctx.guild.id)
        except sqlite3.IntegrityError:
            await ctx.send(f"❌ Key `{key}` already exists!")
        finally:
            conn.close()

    @commands.command(name='ctkey')
    async def ctkey(self, ctx, key: str, duration: str):
        """Create a timed key. Owner server only.
        Format: 20s, 30m, 2d, 1w
        Usage: !ctkey mykey 7d
        """
        if await self.check_duplicate(ctx):
            return
            
        if not self.is_owner_server(ctx):
            await ctx.send("🔐 This command can only be used in the bot owner's server!")
            return
            
        if not self.has_bot_role(ctx.author):
            await ctx.send(f"❌ You need the **{BOT_ROLE}** role to create keys!")
            return

        time_units = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800}
        unit = duration[-1]
        if unit not in time_units:
            await ctx.send("❌ Invalid time format. Use s/m/h/d/w (e.g., 7d)")
            return

        try:
            value = int(duration[:-1])
            seconds = value * time_units[unit]
        except:
            await ctx.send("❌ Invalid time value.")
            return

        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO bot_keys (key, key_type, created_by, created_at, max_uses, uses_remaining, expiry_duration) VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (key, 'timed', str(ctx.author.id), time.time(), 1, 1, seconds))
            conn.commit()
            await self.log_key_event('key_created', ctx.guild, ctx.author, key, True, f"Timed key ({duration})")
            embed = discord.Embed(title="⏰ Timed Key Created", color=discord.Color.purple())
            embed.add_field(name="Key", value=f"`{key}`", inline=True)
            embed.add_field(name="Duration", value=duration, inline=True)
            await ctx.send(embed=embed)
            await self.refresh_skey_message(ctx.guild.id)
        except sqlite3.IntegrityError:
            await ctx.send(f"❌ Key `{key}` already exists!")
        finally:
            conn.close()

    @commands.command(name='cmultikey')
    async def cmultikey(self, ctx, key: str, uses: int):
        """Create a multi-use key. Owner server only.
        Usage: !cmultikey mykey 5
        """
        if await self.check_duplicate(ctx):
            return
            
        if not self.is_owner_server(ctx):
            await ctx.send("🔐 This command can only be used in the bot owner's server!")
            return
            
        if not self.has_bot_role(ctx.author):
            await ctx.send(f"❌ You need the **{BOT_ROLE}** role to create keys!")
            return

        if uses < 1 or uses > 1000:
            await ctx.send("❌ Uses must be between 1 and 1000.")
            return

        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO bot_keys (key, key_type, created_by, created_at, max_uses, uses_remaining) VALUES (?, ?, ?, ?, ?, ?)",
                      (key, 'multi', str(ctx.author.id), time.time(), uses, uses))
            conn.commit()
            await self.log_key_event('key_created', ctx.guild, ctx.author, key, True, f"Multi-use key ({uses} uses)")
            embed = discord.Embed(title="🔑 Multi-Use Key Created", color=discord.Color.blue())
            embed.add_field(name="Key", value=f"`{key}`", inline=True)
            embed.add_field(name="Uses", value=str(uses), inline=True)
            await ctx.send(embed=embed)
            await self.refresh_skey_message(ctx.guild.id)
        except sqlite3.IntegrityError:
            await ctx.send(f"❌ Key `{key}` already exists!")
        finally:
            conn.close()

    @commands.command(name='cdelkey')
    async def cdelkey(self, ctx, key: str):
        """Delete a key and deactivate all servers using it. Owner server only."""
        if await self.check_duplicate(ctx):
            return
            
        if not self.is_owner_server(ctx):
            await ctx.send("🔐 This command can only be used in the bot owner's server!")
            return
            
        if not self.has_bot_role(ctx.author):
            await ctx.send(f"❌ You need the **{BOT_ROLE}** role to delete keys!")
            return

        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()

        c.execute("SELECT key_type FROM bot_keys WHERE key = ?", (key,))
        key_data = c.fetchone()

        if not key_data:
            await ctx.send(f"❌ Key `{key}` not found.")
            conn.close()
            return

        c.execute("SELECT guild_id, guild_name FROM key_uses WHERE key = ? AND is_active = 1", (key,))
        servers = c.fetchall()

        for guild_id, guild_name in servers:
            c.execute("DELETE FROM authorized_servers WHERE guild_id = ?", (guild_id,))
            guild = self.bot.get_guild(int(guild_id))
            if guild and guild.system_channel:
                try:
                    await guild.system_channel.send(
                        "⚠️ **Bot Deactivated**\n"
                        f"The key for this server has been deleted.\n"
                        "Contact the bot owner for a new key."
                    )
                except:
                    pass

        c.execute("UPDATE key_uses SET is_active = 0 WHERE key = ?", (key,))
        c.execute("DELETE FROM bot_keys WHERE key = ?", (key,))
        conn.commit()
        conn.close()

        await self.log_key_event('key_deleted', ctx.guild, ctx.author, key, True,
                                 f"Deleted — {len(servers)} server(s) deactivated")

        embed = discord.Embed(title="🗑️ Key Deleted", color=discord.Color.orange())
        embed.add_field(name="Key", value=f"`{key}`", inline=True)
        embed.add_field(name="Servers Deactivated", value=str(len(servers)), inline=True)
        await ctx.send(embed=embed)
        await self.refresh_skey_message(ctx.guild.id)

    # ===== FIXED SKEY BUILD METHOD WITH CONSECUTIVE NUMBERING =====

    def build_skey_embed(self):
        """Build the !skey status embed from current database state."""
        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()

        # ── Fetch all keys ────────────────────────────────────────────────
        c.execute(
            "SELECT key, key_type, max_uses, uses_remaining, is_active "
            "FROM bot_keys ORDER BY created_at DESC"
        )
        keys = c.fetchall()

        # ── Fetch all authorized servers ──────────────────────────────────
        c.execute(
            "SELECT guild_id, key_used FROM authorized_servers ORDER BY authorized_since ASC"
        )
        all_servers = c.fetchall()

        conn.close()

        # ── Build key type map for quick lookup ───────────────────────────
        key_type_map = {}
        for key, key_type, max_uses, uses_remaining, is_active in keys:
            if key_type == 'master':
                label = "👑 master"
            elif key_type == 'multi':
                label = f"🗝️ multi ({uses_remaining}/{max_uses} left)"
            elif key_type == 'single':
                label = "🔑 single"
            elif key_type == 'timed':
                label = "⏰ timed"
            else:
                label = key_type
            if not is_active:
                label += " · deleted"
            key_type_map[key] = label

        # ── Separate available keys with CONSECUTIVE numbering ────────────
        used_keys = {row[1] for row in all_servers if row[1] and row[1] != "KEY_SYSTEM_DISABLED"}
        available_lines = []
        counter = 1  # Separate counter for displayed items
        for key, key_type, max_uses, uses_remaining, is_active in keys:
            if not is_active:
                continue
            if key_type == 'master':
                available_lines.append(f"`{counter}.` **{key}** — {key_type_map[key]}")
                counter += 1
            elif key_type == 'multi' and uses_remaining > 0:
                available_lines.append(f"`{counter}.` **{key}** — {key_type_map[key]}")
                counter += 1
            elif key_type == 'single' and key not in used_keys:
                available_lines.append(f"`{counter}.` **{key}** — {key_type_map[key]}")
                counter += 1
            elif key_type == 'timed' and key not in used_keys:
                available_lines.append(f"`{counter}.` **{key}** — {key_type_map[key]}")
                counter += 1

        # ── Build key servers list with CONSECUTIVE numbering ─────────────
        key_server_lines = []
        server_counter = 1
        for guild_id, key_used in all_servers:
            if key_used and key_used != "KEY_SYSTEM_DISABLED":
                guild_obj = self.bot.get_guild(int(guild_id))
                guild_name = guild_obj.name if guild_obj else f"Unknown ({guild_id})"
                key_label = key_type_map.get(key_used, key_used)
                key_server_lines.append(f"`{server_counter}.` **{guild_name}** = `{key_used}` · {key_label}")
                server_counter += 1

        # ── Build keyless servers list with CONSECUTIVE numbering ────────
        keyless_lines = []
        keyless_counter = 1
        for guild_id, key_used in all_servers:
            if key_used == "KEY_SYSTEM_DISABLED":
                guild_obj = self.bot.get_guild(int(guild_id))
                guild_name = guild_obj.name if guild_obj else f"Unknown ({guild_id})"
                keyless_lines.append(f"`{keyless_counter}.` **{guild_name}**")
                keyless_counter += 1

        # ── Assemble embed ────────────────────────────────────────────────
        embed = discord.Embed(
            title="🔑 Key Status",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow()
        )

        # Field 1: Available keys
        avail_text = "\n".join(available_lines) if available_lines else "*No available keys*"
        if len(avail_text) > 1024:
            avail_text = avail_text[:1020] + "..."
        embed.add_field(
            name=f"✅ Available Keys ({len(available_lines)})",
            value=avail_text,
            inline=False
        )

        # Field 2: Key servers
        key_srv_text = "\n".join(key_server_lines) if key_server_lines else "*No servers using keys*"
        if len(key_srv_text) > 1024:
            key_srv_text = key_srv_text[:1020] + "..."
        embed.add_field(
            name=f"🔐 Key Servers ({len(key_server_lines)})",
            value=key_srv_text,
            inline=False
        )

        # Field 3: Keyless servers
        keyless_text = "\n".join(keyless_lines) if keyless_lines else "*None*"
        if len(keyless_text) > 1024:
            keyless_text = keyless_text[:1020] + "..."
        embed.add_field(
            name=f"🔓 Keyless Servers ({len(keyless_lines)})",
            value=keyless_text,
            inline=False
        )

        total_servers = len(key_server_lines) + len(keyless_lines)
        embed.set_footer(
            text=f"{total_servers} server(s) · Auto-updates · Last refreshed"
        )
        return embed

    def save_skey_message(self, guild_id, channel_id, message_id):
        """Persist the skey live message info to the database so it survives restarts."""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS skey_messages
                         (guild_id TEXT PRIMARY KEY,
                          channel_id TEXT,
                          message_id TEXT,
                          updated_at REAL)''')
            c.execute('''INSERT OR REPLACE INTO skey_messages
                         (guild_id, channel_id, message_id, updated_at)
                         VALUES (?, ?, ?, ?)''',
                      (str(guild_id), str(channel_id), str(message_id), time.time()))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"⚠️ save_skey_message error: {e}")

    def load_skey_messages(self):
        """Load all saved skey message references from the database."""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS skey_messages
                         (guild_id TEXT PRIMARY KEY,
                          channel_id TEXT,
                          message_id TEXT,
                          updated_at REAL)''')
            c.execute("SELECT guild_id, channel_id, message_id FROM skey_messages")
            rows = c.fetchall()
            conn.close()
            return rows
        except Exception as e:
            print(f"⚠️ load_skey_messages error: {e}")
            return []

    def delete_skey_message(self, guild_id):
        """Remove a skey message record from the database (e.g. message was deleted)."""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM skey_messages WHERE guild_id = ?", (str(guild_id),))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"⚠️ delete_skey_message error: {e}")

    @commands.command(name='skey')
    async def skey(self, ctx):
        """View all keys and their status in a single live-updating message. Owner server only."""
        if await self.check_duplicate(ctx):
            return

        if not self.is_owner_server(ctx):
            await ctx.send("🔐 This command can only be used in the bot owner's server!")
            return

        if not self.has_bot_role(ctx.author):
            await ctx.send(f"❌ You need the **{BOT_ROLE}** role to view keys!")
            return

        # Check if there are any keys at all
        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM bot_keys")
        count = c.fetchone()[0]
        conn.close()

        if count == 0:
            await ctx.send("📭 No keys exist yet.")
            return

        # Post the initial embed
        embed = self.build_skey_embed()
        status_msg = await ctx.send(embed=embed)

        # Store in memory
        if not hasattr(self.bot, 'skey_messages'):
            self.bot.skey_messages = {}
        self.bot.skey_messages[ctx.guild.id] = {
            'channel_id': ctx.channel.id,
            'message_id': status_msg.id
        }

        # Persist to database so it survives restarts
        self.save_skey_message(ctx.guild.id, ctx.channel.id, status_msg.id)

        # Launch the auto-refresh loop for this message
        self._launch_skey_refresh_task(ctx.guild.id, ctx.channel.id, status_msg.id)

    def _launch_skey_refresh_task(self, guild_id, channel_id, message_id):
        """Spawn a background task that re-edits the skey message every 30 seconds indefinitely."""
        async def auto_refresh():
            while True:
                await asyncio.sleep(5)
                try:
                    channel = self.bot.get_channel(int(channel_id))
                    if not channel:
                        break
                    msg = await channel.fetch_message(int(message_id))
                    new_embed = self.build_skey_embed()
                    await msg.edit(embed=new_embed)
                except discord.NotFound:
                    # Message was deleted — clean up DB record
                    self.delete_skey_message(guild_id)
                    if hasattr(self.bot, 'skey_messages'):
                        self.bot.skey_messages.pop(guild_id, None)
                    break
                except Exception as e:
                    print(f"⚠️ skey auto-refresh error: {e}")
                    break
        
        self.bot.loop.create_task(auto_refresh())

    async def restore_skey_tasks(self):
        """Called on bot ready. Reloads all saved skey messages and re-launches their refresh tasks."""
        rows = self.load_skey_messages()
        if not rows:
            print("ℹ️ No skey messages to restore")
            return

        restored = 0
        for guild_id, channel_id, message_id in rows:
            try:
                channel = self.bot.get_channel(int(channel_id))
                if not channel:
                    print(f"⚠️ skey restore: channel {channel_id} not found, skipping")
                    continue

                # Try to fetch the message to confirm it still exists
                msg = await channel.fetch_message(int(message_id))

                # Immediately refresh the embed with current data
                new_embed = self.build_skey_embed()
                await msg.edit(embed=new_embed)

                # Restore in-memory reference
                if not hasattr(self.bot, 'skey_messages'):
                    self.bot.skey_messages = {}
                self.bot.skey_messages[int(guild_id)] = {
                    'channel_id': int(channel_id),
                    'message_id': int(message_id)
                }

                # Re-launch the auto-refresh loop
                self._launch_skey_refresh_task(int(guild_id), int(channel_id), int(message_id))

                restored += 1
                print(f"✅ Restored skey live message for guild {guild_id}")

            except discord.NotFound:
                print(f"⚠️ skey restore: message {message_id} no longer exists, removing from DB")
                self.delete_skey_message(guild_id)
            except Exception as e:
                print(f"⚠️ skey restore error for guild {guild_id}: {e}")

        print(f"✅ skey restore complete — {restored} message(s) restored")

    async def refresh_skey_message(self, guild_id):
        """Instantly re-edits the live skey message. Falls back to DB if not in memory."""
        # Try memory first
        if not hasattr(self.bot, 'skey_messages'):
            self.bot.skey_messages = {}

        data = self.bot.skey_messages.get(guild_id)

        # Fall back to database if not in memory (e.g. after restart)
        if not data:
            rows = self.load_skey_messages()
            for g_id, ch_id, msg_id in rows:
                if int(g_id) == guild_id:
                    data = {'channel_id': int(ch_id), 'message_id': int(msg_id)}
                    self.bot.skey_messages[guild_id] = data
                    break

        if not data:
            return  # No live message for this guild

        try:
            channel = self.bot.get_channel(data['channel_id'])
            if not channel:
                return
            msg = await channel.fetch_message(data['message_id'])
            new_embed = self.build_skey_embed()
            await msg.edit(embed=new_embed)
        except discord.NotFound:
            # Message was deleted — clean up
            self.delete_skey_message(guild_id)
            self.bot.skey_messages.pop(guild_id, None)
        except Exception as e:
            print(f"⚠️ refresh_skey_message error: {e}")

    @commands.command(name='helpkey')
    async def helpkey(self, ctx):
        """Show key system commands. Owner server only."""
        if await self.check_duplicate(ctx):
            return
            
        if not self.is_owner_server(ctx):
            await ctx.send("🔐 This command can only be used in the bot owner's server!")
            return

        embed = discord.Embed(
            title="🔑 Key System Commands",
            description="Commands for managing bot activation keys.",
            color=discord.Color.gold()
        )
        embed.add_field(
            name="🌐 For Any Server",
            value="`!botkey [key]` - Activate a server with a key",
            inline=False
        )
        embed.add_field(
            name="🛠️ Owner Only",
            value=(
                "`!ckey [key]` - Create a single-use key\n"
                "`!cmultikey [key] [uses]` - Create a multi-use key\n"
                "`!cmkey [key]` - Create a master key (unlimited)\n"
                "`!ctkey [key] [time]` - Create a timed key\n"
                "`!cdelkey [key]` - Delete a key\n"
                "`!cbotkey [key]` - Force reactivate a key (deactivates all servers using it)\n"
                "`!skey` - View all keys and servers"
            ),
            inline=False
        )
        embed.add_field(
            name="⏰ Time Format for !ctkey",
            value="`20s` `30m` `2h` `7d` `2w`\nExample: `!ctkey mykey123 7d`",
            inline=False
        )
        embed.set_footer(text="This command only works in the owner server and requires the AsaiyaBot role.")
        await ctx.send(embed=embed)


    @commands.command(name='showservers')
    async def show_servers(self, ctx):
        """Show all servers the bot is in with invite links. Owner server only."""
        if await self.check_duplicate(ctx):
            return
            
        if not self.is_owner_server(ctx):
            await ctx.send("🔐 This command can only be used in the bot owner's server!")
            return
            
        if not self.has_bot_role(ctx.author):
            await ctx.send(f"❌ You need the **{BOT_ROLE}** role to use this command!")
            return
        
        # Defer response in case there are many servers
        await ctx.typing()
        
        servers = self.bot.guilds
        total_servers = len(servers)
        total_members = sum(guild.member_count for guild in servers)
        
        # Create initial embed
        embed = discord.Embed(
            title="🌐 Asaiya Bot - Server List",
            description=f"Currently in **{total_servers}** servers with **{total_members:,}** total members",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        
        # Process servers in batches to avoid rate limits
        server_list = []
        invite_errors = []
        
        for guild in servers:
            try:
                # Try to get an invite link
                invite = None
                
                # Method 1: Try to find an existing invite in the server
                try:
                    async for invite_obj in guild.invites():
                        if invite_obj.max_age == 0 or invite_obj.max_uses == 0:
                            invite = invite_obj.url
                            break
                except:
                    pass
                
                # Method 2: If no invite found, try to create one
                if not invite:
                    # Find a channel to create invite in
                    target_channel = None
                    for channel in guild.text_channels:
                        if channel.permissions_for(guild.me).create_instant_invite:
                            target_channel = channel
                            break
                    
                    if target_channel:
                        try:
                            invite_obj = await target_channel.create_invite(max_age=86400, max_uses=1, reason="!showservers command")
                            invite = invite_obj.url
                        except:
                            invite = "❌ Could not create invite"
                    else:
                        invite = "❌ No channel with invite permission"
                
                server_list.append({
                    'name': guild.name,
                    'id': guild.id,
                    'member_count': guild.member_count,
                    'invite': invite or "❌ No invite available",
                    'owner': guild.owner.name if guild.owner else "Unknown"
                })
                
            except Exception as e:
                invite_errors.append(f"❌ {guild.name}: {str(e)[:50]}")
        
        # Sort by member count (largest first)
        server_list.sort(key=lambda x: x['member_count'], reverse=True)
        
        # Send in chunks to avoid message limit
        chunk_size = 5
        chunks = [server_list[i:i + chunk_size] for i in range(0, len(server_list), chunk_size)]
        
        await ctx.send(embed=embed)
        
        for i, chunk in enumerate(chunks, 1):
            chunk_embed = discord.Embed(
                title=f"📋 Servers (Page {i}/{len(chunks)})",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            for server in chunk:
                value = (
                    f"**ID:** `{server['id']}`\n"
                    f"**Members:** {server['member_count']:,}\n"
                    f"**Owner:** {server['owner']}\n"
                    f"**Invite:** {server['invite']}"
                )
                chunk_embed.add_field(
                    name=f"🌍 {server['name']}",
                    value=value,
                    inline=False
                )
            
            chunk_embed.set_footer(text=f"Total servers: {total_servers} • Page {i}/{len(chunks)}")
            await ctx.send(embed=chunk_embed)
            await asyncio.sleep(0.5)  # Small delay between pages
        
        if invite_errors:
            error_embed = discord.Embed(
                title="⚠️ Invite Errors",
                description="\n".join(invite_errors[:10]),
                color=discord.Color.orange()
            )
            await ctx.send(embed=error_embed)

    # ===== SETSERVER COMMAND =====
    @commands.command(name='setserver')
    @commands.has_permissions(administrator=True)
    async def setserver(self, ctx):
        """Interactive server setup wizard"""
        if await self.check_duplicate(ctx):
            return
            
        guild = ctx.guild
        bot_member = guild.get_member(self.bot.user.id)

        if not bot_member.guild_permissions.manage_roles:
            await ctx.send("❌ I need 'Manage Roles' permission!")
            return
        if not bot_member.guild_permissions.manage_channels:
            await ctx.send("❌ I need 'Manage Channels' permission!")
            return

        embed = discord.Embed(
            title="🛠️ Server Setup Wizard",
            description=(
                "Welcome to the Asaiya server setup! Choose a template below.\n\n"
                "**Minimal** - Basic channels (bot, hub, log) - This is always kept\n"
                "**Gaming** - Gaming-focused roles and channels\n"
                "**Community** - Community-focused roles and channels\n"
                "**Ticket** - Just the ticket system\n"
                "**Full** - Everything combined\n"
                "**Custom** - Build your own server structure interactively\n\n"
                "⚠️ **IMPORTANT:** Choosing a new template will **DELETE** the previous template's structure!"
            ),
            color=discord.Color.blue()
        )

        view = SetupView(ctx.author.id, self)
        await ctx.send(embed=embed, view=view)

    # ===== PERMSET COMMAND =====
    @commands.command(name='permset')
    @commands.has_permissions(administrator=True)
    async def permset(self, ctx, role: discord.Role):
        """Set up channel permissions for verified members.
        Usage: !permset @VerifiedRole
        """
        if await self.check_duplicate(ctx):
            return
            
        guild = ctx.guild
        bot_member = guild.get_member(self.bot.user.id)

        if not bot_member.guild_permissions.manage_roles:
            await ctx.send("❌ I need 'Manage Roles' permission!")
            return
        if not bot_member.guild_permissions.manage_channels:
            await ctx.send("❌ I need 'Manage Channels' permission!")
            return

        status_msg = await ctx.send("🔄 Setting up channel permissions...")

        everyone_role = guild.default_role
        
        # Staff roles that should always have access
        staff_role_names = [BOT_ROLE, KICK_ROLE, BAN_ROLE, PASS_ROLE, CLEAR_ROLE, SUPPORT_ROLE, REQUEST_ROLE]
        staff_roles = [discord.utils.get(guild.roles, name=r) for r in staff_role_names]
        staff_roles = [r for r in staff_roles if r]
        
        # All roles that should have access (staff + the specified role)
        allowed_roles = staff_roles + [role]

        # Channels that should remain public (verification channel and info category)
        public_channels = []
        verification_channel = discord.utils.get(guild.text_channels, name="asaiya-verification")
        if verification_channel:
            public_channels.append(verification_channel)

        info_category = discord.utils.get(guild.categories, name="Information")
        if info_category:
            public_channels.extend([ch for ch in info_category.channels
                                     if isinstance(ch, discord.TextChannel)])

        modified_count = 0
        skipped_count = 0
        error_count = 0

        for channel in guild.text_channels:
            try:
                # Skip public channels
                if channel in public_channels:
                    skipped_count += 1
                    continue
                
                # Check if @everyone permissions have been manually changed
                current_overwrites = channel.overwrites_for(everyone_role)
                
                # If @everyone permissions are already modified, skip this channel
                if current_overwrites.read_messages is not None or \
                   current_overwrites.send_messages is not None or \
                   current_overwrites.attach_files is not None or \
                   current_overwrites.embed_links is not None:
                    skipped_count += 1
                    print(f"⏭️ Skipping #{channel.name} - @everyone permissions already modified")
                    continue
                
                # Lock the channel by denying @everyone all permissions
                await channel.set_permissions(
                    everyone_role,
                    read_messages=False,
                    send_messages=False,
                    attach_files=False,
                    embed_links=False,
                    add_reactions=False,
                    read_message_history=False
                )
                
                # Grant full access to all allowed roles
                for allowed_role in allowed_roles:
                    if allowed_role:  # Make sure role exists
                        await channel.set_permissions(
                            allowed_role,
                            read_messages=True,
                            send_messages=True,
                            attach_files=True,
                            embed_links=True,
                            add_reactions=True,
                            read_message_history=True
                        )
                
                modified_count += 1
                await asyncio.sleep(0.2)  # Small delay to avoid rate limits
                
            except Exception as e:
                print(f"Error setting permissions for #{channel.name}: {e}")
                error_count += 1

        await status_msg.delete()

        embed = discord.Embed(
            title="🔒 Channel Permissions Updated",
            description=(
                f"**Modified:** {modified_count} channel(s)\n"
                f"**Skipped:** {skipped_count} channel(s) (public or already modified)\n"
                f"**Errors:** {error_count} channel(s)"
            ),
            color=discord.Color.green() if error_count == 0 else discord.Color.orange(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(
            name="📋 Access Granted To",
            value="\n".join([f"• {r.mention}" for r in allowed_roles if r]),
            inline=False
        )
        embed.add_field(
            name="🌍 Public Channels (Skipped)",
            value="\n".join([f"• #{c.name}" for c in public_channels if c]),
            inline=False
        )
        embed.set_footer(text=f"Set up by {ctx.author}")
        await ctx.send(embed=embed)

    # ===== NUKE COMMAND =====
    @commands.command(name='nuke')
    async def nuke(self, ctx):
        """Delete every channel and role in this server after owner approval.
        Only works in #asaiya-bot. Requires AsaiyaBot role.
        """
        if await self.check_duplicate(ctx):
            return
            
        if ctx.channel.name != BOT_CHANNEL:
            return

        guild = ctx.guild
        author = ctx.author
        has_bot_role = any(role.name == BOT_ROLE for role in author.roles) \
                       if isinstance(author, discord.Member) else False

        if not has_bot_role:
            conn = self.get_cached_connection(guild.id)
            c = conn.cursor()
            c.execute("INSERT INTO warnings (user_id, mod_id, reason, timestamp) VALUES (?, ?, ?, ?)",
                      (str(author.id), str(self.bot.user.id), "Attempting to Nuke The Server", time.time()))
            warning_id = c.lastrowid
            conn.commit()

            await ctx.send(
                f"🚫 {author.mention} Nice Try, but here's a warning: **Attempting to Nuke The Server**\n"
                f"(Warning #{warning_id})"
            )

            log_channel = await self.get_log_channel(guild)
            if log_channel:
                embed = discord.Embed(
                    title="🚨 Unauthorized Nuke Attempt",
                    description=f"{author.mention} tried to use `!nuke` without the **{BOT_ROLE}** role.",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="User", value=f"{author} (`{author.id}`)", inline=True)
                embed.add_field(name="Warning ID", value=f"#{warning_id}", inline=True)
                await log_channel.send(embed=embed)
            return

        approval_channel = self.bot.get_channel(NUKE_APPROVAL_CHANNEL)
        if not approval_channel:
            await ctx.send("❌ Could not reach the approval channel. Contact bot owner.")
            return

        embed = discord.Embed(
            title="💣 NUKE REQUEST",
            description=(
                f"**{author}** (`{author.id}`) wants to nuke their server.\n\n"
                f"**Server:** {guild.name}\n"
                f"**Server ID:** `{guild.id}`\n"
                f"**Members:** {guild.member_count}\n"
                f"**Channels:** {len(guild.channels)}\n"
                f"**Roles:** {len(guild.roles)}\n\n"
                f"Someone with the **\".\"** role must reply `yes` in this channel to confirm."
            ),
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )

        approval_msg = await approval_channel.send(embed=embed)

        nuke_data = {
            'requester_id': author.id,
            'approval_msg_id': approval_msg.id,
            'guild_id': guild.id,
            'guild_name': guild.name,
            'source_channel_id': ctx.channel.id
        }

        if not hasattr(self.bot, 'pending_nukes'):
            self.bot.pending_nukes = {}
        self.bot.pending_nukes[guild.id] = nuke_data

        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS persistent_nuke_requests
                         (guild_id TEXT PRIMARY KEY,
                          requester_id TEXT,
                          approval_msg_id TEXT,
                          guild_name TEXT,
                          source_channel_id TEXT,
                          requested_at REAL)''')
            c.execute('''INSERT OR REPLACE INTO persistent_nuke_requests
                         (guild_id, requester_id, approval_msg_id, guild_name, source_channel_id, requested_at)
                         VALUES (?, ?, ?, ?, ?, ?)''',
                      (str(guild.id), str(author.id), str(approval_msg.id),
                       guild.name, str(ctx.channel.id), time.time()))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error saving nuke request: {e}")

        await ctx.send(
            "💣 **Nuke request sent for approval.**\n"
            "Waiting for owner confirmation..."
        )


# ===== SETUP VIEW FOR SETSERVER =====
class SetupView(discord.ui.View):
    def __init__(self, author_id, cog):
        super().__init__(timeout=None)
        self.author_id = author_id
        self.cog = cog

    async def check_author(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Only the command user can use this.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Minimal", style=discord.ButtonStyle.blurple, custom_id="setup_minimal")
    async def minimal_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_author(interaction):
            return
        await interaction.response.defer()
        await self.cog.run_setup(interaction, 'minimal')

    @discord.ui.button(label="Gaming", style=discord.ButtonStyle.blurple, custom_id="setup_gaming")
    async def gaming_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_author(interaction):
            return
        await interaction.response.defer()
        await self.cog.run_setup(interaction, 'gaming')

    @discord.ui.button(label="Community", style=discord.ButtonStyle.blurple, custom_id="setup_community")
    async def community_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_author(interaction):
            return
        await interaction.response.defer()
        await self.cog.run_setup(interaction, 'community')

    @discord.ui.button(label="Ticket System", style=discord.ButtonStyle.blurple, custom_id="setup_ticket")
    async def ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_author(interaction):
            return
        await interaction.response.defer()
        await self.cog.run_setup(interaction, 'ticket')

    @discord.ui.button(label="Full", style=discord.ButtonStyle.green, custom_id="setup_full")
    async def full_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_author(interaction):
            return
        await interaction.response.defer()
        await self.cog.run_setup(interaction, 'full')

    @discord.ui.button(label="Custom", style=discord.ButtonStyle.grey, custom_id="setup_custom")
    async def custom_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_author(interaction):
            return
        await interaction.response.defer()
        await self.cog.start_custom_setup(interaction)


# ===== CUSTOM SETUP METHODS =====
async def start_custom_setup(self, interaction):
    """Start the interactive custom setup process"""
    user_id = str(interaction.user.id)
    
    # Initialize custom setup data
    self.custom_setup_data[user_id] = {
        "guild_id": interaction.guild.id,
        "categories": [],
        "channels": {},  # Dict of category_name: [channel_names]
        "roles": [],      # List of {"name": str, "permissions": [str]}
        "hierarchy": [],  # List of role names in order
        "step": "categories"
    }
    
    await interaction.followup.send(
        "**🛠️ Custom Server Setup**\n\n"
        "Let's build your server step by step.\n\n"
        "First, enter category names. Type the category name with emoji (e.g., `📣│Community`)\n"
        "Type `done` when finished:",
        ephemeral=False
    )
    
    # Start the category collection loop
    await self.collect_categories(interaction, user_id)

async def collect_categories(self, interaction, user_id):
    """Collect category names from user"""
    
    def check(m):
        return m.author.id == interaction.user.id and m.channel.id == interaction.channel.id
    
    while True:
        try:
            msg = await self.bot.wait_for('message', timeout=120.0, check=check)
            
            if msg.content.lower() == 'done':
                if len(self.custom_setup_data[user_id]["categories"]) == 0:
                    await interaction.followup.send("❌ You must add at least one category. Please add a category:", ephemeral=False)
                    continue
                break
            
            category_name = msg.content.strip()
            if category_name:
                self.custom_setup_data[user_id]["categories"].append(category_name)
                self.custom_setup_data[user_id]["channels"][category_name] = []
                await interaction.followup.send(f"✅ Added category: {category_name}\nEnter next category or `done`:")
            
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timed out. Custom setup cancelled.")
            if user_id in self.custom_setup_data:
                del self.custom_setup_data[user_id]
            return
    
    # Move to channels collection
    await interaction.followup.send("✅ Categories saved! Now let's add channels to each category.")
    await self.collect_channels(interaction, user_id, 0)

async def collect_channels(self, interaction, user_id, category_index):
    """Collect channels for each category"""
    categories = self.custom_setup_data[user_id]["categories"]
    
    if category_index >= len(categories):
        # All categories processed, move to roles
        await interaction.followup.send("✅ All channels saved! Now let's add roles.")
        await self.collect_roles(interaction, user_id)
        return
    
    current_category = categories[category_index]
    await interaction.followup.send(
        f"**Category {category_index + 1}/{len(categories)}: {current_category}**\n"
        f"Enter channel names (with emoji, e.g., `💬│general`). Type `done` when finished:"
    )
    
    def check(m):
        return m.author.id == interaction.user.id and m.channel.id == interaction.channel.id
    
    while True:
        try:
            msg = await self.bot.wait_for('message', timeout=120.0, check=check)
            
            if msg.content.lower() == 'done':
                break
            
            channel_name = msg.content.strip()
            if channel_name:
                self.custom_setup_data[user_id]["channels"][current_category].append(channel_name)
                await interaction.followup.send(f"✅ Added channel: {channel_name} to {current_category}\nEnter next channel or `done`:")
            
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timed out. Custom setup cancelled.")
            if user_id in self.custom_setup_data:
                del self.custom_setup_data[user_id]
            return
    
    # Move to next category
    await self.collect_channels(interaction, user_id, category_index + 1)

async def collect_roles(self, interaction, user_id):
    """Collect roles and their permissions"""
    await interaction.followup.send(
        "**Now let's add roles.**\n\n"
        "For each role, enter:\n"
        "`role name` then on next line, enter permissions (comma-separated)\n"
        "Example:\n"
        "`🤖│Manager`\n"
        "`kick_members, ban_members, manage_channels`\n\n"
        "Type `done` when finished adding roles:"
    )
    
    def check(m):
        return m.author.id == interaction.user.id and m.channel.id == interaction.channel.id
    
    while True:
        try:
            # Get role name
            name_msg = await self.bot.wait_for('message', timeout=120.0, check=check)
            
            if name_msg.content.lower() == 'done':
                if len(self.custom_setup_data[user_id]["roles"]) == 0:
                    await interaction.followup.send("❌ You must add at least one role. Please add a role:")
                    continue
                break
            
            role_name = name_msg.content.strip()
            
            # Get permissions
            await interaction.followup.send(f"Enter permissions for **{role_name}** (comma-separated, or `none`):")
            perm_msg = await self.bot.wait_for('message', timeout=120.0, check=check)
            
            perms = []
            if perm_msg.content.lower() != 'none':
                perms = [p.strip() for p in perm_msg.content.split(',')]
            
            self.custom_setup_data[user_id]["roles"].append({
                "name": role_name,
                "permissions": perms
            })
            
            await interaction.followup.send(f"✅ Added role: {role_name}\n\nAdd another role or `done`:")
            
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timed out. Custom setup cancelled.")
            if user_id in self.custom_setup_data:
                del self.custom_setup_data[user_id]
            return
    
    # Move to hierarchy setup
    await self.collect_hierarchy(interaction, user_id)

async def collect_hierarchy(self, interaction, user_id):
    """Collect role hierarchy"""
    roles = self.custom_setup_data[user_id]["roles"]
    role_names = [r["name"] for r in roles]
    
    role_list = "\n".join([f"{i+1}. {name}" for i, name in enumerate(role_names)])
    
    await interaction.followup.send(
        "**Now let's set the role hierarchy (highest to lowest).**\n\n"
        f"Current roles:\n{role_list}\n\n"
        "Enter the role for position 1:"
    )
    
    def check(m):
        return m.author.id == interaction.user.id and m.channel.id == interaction.channel.id
    
    position = 1
    used_roles = set()
    
    while len(used_roles) < len(role_names):
        try:
            msg = await self.bot.wait_for('message', timeout=120.0, check=check)
            role_name = msg.content.strip()
            
            # Check if role exists
            if role_name not in role_names:
                await interaction.followup.send(f"❌ Role '{role_name}' not found. Available roles:\n{role_list}")
                continue
            
            # Check if already used
            if role_name in used_roles:
                await interaction.followup.send(f"❌ Role '{role_name}' already placed at a higher position.")
                continue
            
            self.custom_setup_data[user_id]["hierarchy"].append(role_name)
            used_roles.add(role_name)
            
            if len(used_roles) < len(role_names):
                await interaction.followup.send(f"✅ Added {role_name} at position {position}\n\nEnter role for position {position + 1}:")
                position += 1
            
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timed out. Custom setup cancelled.")
            if user_id in self.custom_setup_data:
                del self.custom_setup_data[user_id]
            return
    
    # All done, create the server
    await interaction.followup.send("✅ Hierarchy set! Now creating your custom server...")
    await self.create_custom_server(interaction, user_id)

async def create_custom_server(self, interaction, user_id):
    """Create the custom server structure"""
    data = self.custom_setup_data[user_id]
    guild = interaction.guild
    results = {
        "roles": [],
        "categories": [],
        "channels": [],
        "errors": []
    }
    
    status_msg = await interaction.followup.send("🔄 Creating custom server structure...", ephemeral=False)
    
    try:
        # Create roles first
        created_roles = {}
        for role_data in data["roles"]:
            try:
                # Convert permission strings to discord.Permissions
                perms = discord.Permissions()
                for perm_name in role_data["permissions"]:
                    if hasattr(discord.Permissions, perm_name):
                        setattr(perms, perm_name, True)
                
                role = await guild.create_role(
                    name=role_data["name"],
                    permissions=perms,
                    reason="Custom server setup"
                )
                created_roles[role_data["name"]] = role
                results["roles"].append(f"✅ Created {role_data['name']}")
                await asyncio.sleep(0.3)
            except Exception as e:
                results["errors"].append(f"❌ Failed to create role {role_data['name']}: {str(e)}")
        
        # Apply hierarchy
        position = len(data["hierarchy"])
        for role_name in data["hierarchy"]:
            role = created_roles.get(role_name)
            if role:
                try:
                    await role.edit(position=position)
                    position -= 1
                    await asyncio.sleep(0.3)
                except Exception as e:
                    results["errors"].append(f"❌ Failed to set hierarchy for {role_name}: {str(e)}")
        
        # Create categories and channels
        for category_name in data["categories"]:
            try:
                category = await guild.create_category(category_name, reason="Custom server setup")
                results["categories"].append(f"✅ Created {category_name}")
                await asyncio.sleep(0.5)
                
                # Create channels in this category
                for channel_name in data["channels"].get(category_name, []):
                    try:
                        # Determine if voice or text channel (check for 🎙️ emoji)
                        if "🎙️" in channel_name or "voice" in channel_name.lower():
                            await guild.create_voice_channel(channel_name, category=category)
                        else:
                            await guild.create_text_channel(channel_name, category=category)
                        results["channels"].append(f"✅ Created {channel_name}")
                        await asyncio.sleep(0.3)
                    except Exception as e:
                        results["errors"].append(f"❌ Failed to create {channel_name}: {str(e)}")
                
            except Exception as e:
                results["errors"].append(f"❌ Failed to create category {category_name}: {str(e)}")
        
        await status_msg.delete()
        
        # Save template history as 'custom'
        self.save_template_history(guild.id, 'custom')
        
        embed = discord.Embed(
            title=f"✅ Custom Setup Complete!",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        if results["roles"]:
            embed.add_field(name="👥 Roles", value="\n".join(results["roles"][:10]), inline=False)
        if results["categories"]:
            embed.add_field(name="📁 Categories", value="\n".join(results["categories"]), inline=False)
        if results["channels"]:
            embed.add_field(name="📢 Channels", value="\n".join(results["channels"][:10]), inline=False)
        if results["errors"]:
            embed.add_field(name="⚠️ Issues", value="\n".join(results["errors"][:5]), inline=False)
        embed.set_footer(text=f"Set up by {interaction.user}")
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        await status_msg.delete()
        await interaction.followup.send(f"❌ Custom setup failed: {str(e)}")
    finally:
        # Clean up stored data
        if user_id in self.custom_setup_data:
            del self.custom_setup_data[user_id]


# ===== SETUP RUNNER METHODS =====
async def run_setup(self, interaction, setup_type):
    guild = interaction.guild
    results = {"roles": [], "categories": [], "channels": [], "errors": []}

    status_msg = await interaction.followup.send(
        f"🔄 Setting up **{setup_type.title()}** template...", ephemeral=False
    )

    try:
        # ===== ALWAYS CLEAN UP PREVIOUS TEMPLATE FIRST =====
        await self.cleanup_previous_template(guild, setup_type, results)
        
        # ===== UPDATE TEMPLATE HISTORY IN DATABASE =====
        self.save_template_history(guild.id, setup_type)
        print(f"✅ Updated template history for {guild.name} to {setup_type}")
        
        # ===== THEN RUN THE NEW TEMPLATE =====
        if setup_type == 'minimal':
            await self.setup_minimal(guild, interaction.user, results)
        elif setup_type == 'gaming':
            await self.setup_minimal(guild, interaction.user, results)
            await self.setup_gaming(guild, results)
        elif setup_type == 'community':
            await self.setup_minimal(guild, interaction.user, results)
            await self.setup_community(guild, results)
        elif setup_type == 'ticket':
            await self.setup_minimal(guild, interaction.user, results)
            await self.setup_ticket(guild, results)
        elif setup_type == 'full':
            await self.setup_minimal(guild, interaction.user, results)
            await self.setup_gaming(guild, results)
            await self.setup_community(guild, results)
            await self.setup_ticket(guild, results)

        await status_msg.delete()

        embed = discord.Embed(
            title=f"✅ {setup_type.title()} Setup Complete!",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        if results["roles"]:
            embed.add_field(name="👥 Roles", value="\n".join(results["roles"][:10]), inline=False)
        if results["categories"]:
            embed.add_field(name="📁 Categories", value="\n".join(results["categories"]), inline=False)
        if results["channels"]:
            embed.add_field(name="📢 Channels", value="\n".join(results["channels"][:10]), inline=False)
        if results["errors"]:
            embed.add_field(name="⚠️ Issues", value="\n".join(results["errors"][:5]), inline=False)
        embed.set_footer(text=f"Set up by {interaction.user}")
        await interaction.followup.send(embed=embed)

    except Exception as e:
        await status_msg.delete()
        await interaction.followup.send(f"❌ Setup failed: {str(e)}")


async def setup_minimal(self, guild, author, results):
    bot_role = discord.utils.get(guild.roles, name=BOT_ROLE)
    if not bot_role:
        # Create role with Administrator permissions
        permissions = discord.Permissions(administrator=True)
        bot_role = await guild.create_role(
            name=BOT_ROLE,
            permissions=permissions,
            reason="Minimal setup"
        )
        results["roles"].append(f"✅ Created {BOT_ROLE} (Administrator)")
        await asyncio.sleep(0.5)

    pass_role = discord.utils.get(guild.roles, name=PASS_ROLE)
    if not pass_role:
        pass_role = await guild.create_role(name=PASS_ROLE, reason="Minimal setup")
        results["roles"].append(f"✅ Created {PASS_ROLE}")
        await asyncio.sleep(0.5)

    staff_roles = [bot_role, pass_role]

    # Command Center
    cmd_category = discord.utils.get(guild.categories, name="📁 COMMAND CENTER")
    if not cmd_category:
        cmd_category = await guild.create_category("📁 COMMAND CENTER")
        results["categories"].append("✅ Created 📁 COMMAND CENTER")
        await asyncio.sleep(0.5)

    for ch_name in [BOT_CHANNEL, HUB_CHANNEL]:
        if not discord.utils.get(cmd_category.channels, name=ch_name):
            await guild.create_text_channel(ch_name, category=cmd_category)
            results["channels"].append(f"✅ Created #{ch_name}")
            await asyncio.sleep(0.3)

    # Gateway
    gateway_category = discord.utils.get(guild.categories, name="📁 GATEWAY")
    if not gateway_category:
        gateway_category = await guild.create_category("📁 GATEWAY")
        results["categories"].append("✅ Created 📁 GATEWAY")
        await asyncio.sleep(0.5)

    welcome_ch = discord.utils.get(gateway_category.channels, name=WELCOME_CHANNEL)
    if not welcome_ch:
        welcome_ch = await guild.create_text_channel(WELCOME_CHANNEL, category=gateway_category)
        await welcome_ch.set_permissions(guild.default_role, read_messages=True, send_messages=False)
        results["channels"].append(f"✅ Created #{WELCOME_CHANNEL}")
        await asyncio.sleep(0.3)

    goodbye_ch = discord.utils.get(gateway_category.channels, name=GOODBYE_CHANNEL)
    if not goodbye_ch:
        goodbye_ch = await guild.create_text_channel(GOODBYE_CHANNEL, category=gateway_category)
        await goodbye_ch.set_permissions(guild.default_role, read_messages=True, send_messages=False)
        results["channels"].append(f"✅ Created #{GOODBYE_CHANNEL}")
        await asyncio.sleep(0.3)

    logs_ch = discord.utils.get(gateway_category.channels, name=LOG_CHANNEL)
    if not logs_ch:
        logs_ch = await guild.create_text_channel(LOG_CHANNEL, category=gateway_category)
        await logs_ch.set_permissions(guild.default_role, read_messages=False, send_messages=False)
        for role in staff_roles:
            if role:
                await logs_ch.set_permissions(role, read_messages=True, send_messages=True)
        results["channels"].append(f"✅ Created #{LOG_CHANNEL}")
        await asyncio.sleep(0.3)

    # ===== AUTO-SETUP WELCOME AND LEAVE CHANNELS ONLY =====
    # Moderation log channel requires manual !setlog command
    try:
        conn = self.get_cached_connection(guild.id)
        c = conn.cursor()
        
        # Check if log_channels table exists, create if not
        c.execute('''CREATE TABLE IF NOT EXISTS log_channels
                     (log_channel_id TEXT,
                      welcome_channel_id TEXT,
                      leave_channel_id TEXT)''')
        
        # Set welcome channel (if it exists)
        if welcome_ch:
            c.execute("INSERT OR REPLACE INTO log_channels (welcome_channel_id) VALUES (?)", (str(welcome_ch.id),))
            results["channels"].append(f"✅ Auto-set #{WELCOME_CHANNEL} as welcome channel")
        
        # Set leave channel (if it exists)
        if goodbye_ch:
            c.execute("UPDATE log_channels SET leave_channel_id = ? WHERE welcome_channel_id IS NOT NULL OR rowid = (SELECT MIN(rowid) FROM log_channels)", (str(goodbye_ch.id),))
            if c.rowcount == 0:
                c.execute("INSERT INTO log_channels (leave_channel_id) VALUES (?)", (str(goodbye_ch.id),))
            results["channels"].append(f"✅ Auto-set #{GOODBYE_CHANNEL} as leave channel")
        
        conn.commit()
        print(f"✅ Auto-configured welcome/leave channels for {guild.name}")
        
    except Exception as e:
        print(f"⚠️ Error auto-setting welcome/leave channels: {e}")

    # Assign roles to author
    if bot_role and bot_role not in author.roles:
        await author.add_roles(bot_role, reason="Auto-assigned by setup")
        results["roles"].append(f"✅ Assigned {BOT_ROLE} to you")
    if pass_role and pass_role not in author.roles:
        await author.add_roles(pass_role, reason="Auto-assigned by setup")
        results["roles"].append(f"✅ Assigned {PASS_ROLE} to you")


async def setup_gaming(self, guild, results):
    color_map = {
        "gold": discord.Color.gold(), "red": discord.Color.red(),
        "green": discord.Color.green(), "purple": discord.Color.purple(),
        "blue": discord.Color.blue(), "lighter_grey": discord.Color.lighter_grey(),
        "orange": discord.Color.orange(), "dark_green": discord.Color.dark_green(),
        "teal": discord.Color.teal(), "dark_blue": discord.Color.dark_blue(),
        "dark_red": discord.Color.dark_red(), "dark_purple": discord.Color.dark_purple(),
        "yellow": discord.Color.yellow(), "dark_teal": discord.Color.dark_teal(),
        "dark_orange": discord.Color.dark_orange(), "dark_gold": discord.Color.dark_gold(),
        "light_grey": discord.Color.light_grey(), "magenta": discord.Color.magenta(),
    }

    gaming_roles = [
        {"name": "👑 Owner", "color": "gold", "hoist": True},
        {"name": "🛡️ Admin", "color": "red", "hoist": True},
        {"name": "⚔️ Moderator", "color": "green", "hoist": True},
        {"name": "🧠 Strategist", "color": "purple", "hoist": True},
        {"name": "🎮 Gamer", "color": "blue", "hoist": True},
        {"name": "🆕 New Recruit", "color": "lighter_grey", "hoist": False},
        {"name": "🥇 MVP", "color": "gold", "hoist": False},
        {"name": "🔥 Tryhard", "color": "orange", "hoist": False},
        {"name": "🖥️ PC", "color": "blue", "hoist": False},
        {"name": "🎮 PlayStation", "color": "blue", "hoist": False},
        {"name": "❎ Xbox", "color": "green", "hoist": False},
        {"name": "📱 Mobile", "color": "purple", "hoist": False},
    ]

    for role_data in gaming_roles:
        if not discord.utils.get(guild.roles, name=role_data["name"]):
            try:
                color = color_map.get(role_data["color"], discord.Color.default())
                await guild.create_role(name=role_data["name"], color=color, hoist=role_data["hoist"])
                results["roles"].append(f"✅ Created {role_data['name']}")
                await asyncio.sleep(0.3)
            except Exception as e:
                results["errors"].append(f"❌ Failed to create {role_data['name']}: {str(e)}")

    gaming_categories = {
        GAMING_INFO_CATEGORY: GAMING_INFO_CHANNELS,
        GAMING_COMMUNITY_CATEGORY: GAMING_COMMUNITY_CHANNELS,
        GAMING_CONTENT_CATEGORY: GAMING_CONTENT_CHANNELS,
    }

    for cat_name, channels in gaming_categories.items():
        cat = discord.utils.get(guild.categories, name=cat_name)
        if not cat:
            cat = await guild.create_category(cat_name)
            results["categories"].append(f"✅ Created {cat_name}")
            await asyncio.sleep(0.5)
        for ch_name in channels:
            if not discord.utils.get(cat.channels, name=ch_name):
                await guild.create_text_channel(ch_name, category=cat)
                results["channels"].append(f"✅ Created {ch_name}")
                await asyncio.sleep(0.3)

    # Competitive category
    comp_cat = discord.utils.get(guild.categories, name=GAMING_COMP_CATEGORY)
    if not comp_cat:
        comp_cat = await guild.create_category(GAMING_COMP_CATEGORY)
        results["categories"].append(f"✅ Created {GAMING_COMP_CATEGORY}")
        await asyncio.sleep(0.5)
    for ch_name in GAMING_COMP_TEXT_CHANNELS:
        if not discord.utils.get(comp_cat.channels, name=ch_name):
            await guild.create_text_channel(ch_name, category=comp_cat)
            results["channels"].append(f"✅ Created {ch_name}")
            await asyncio.sleep(0.3)
    for ch_name in GAMING_COMP_VOICE_CHANNELS:
        if not discord.utils.get(comp_cat.channels, name=ch_name):
            await guild.create_voice_channel(ch_name, category=comp_cat)
            results["channels"].append(f"✅ Created {ch_name} (voice)")
            await asyncio.sleep(0.3)

    # Voice category
    voice_cat = discord.utils.get(guild.categories, name=GAMING_VOICE_CATEGORY)
    if not voice_cat:
        voice_cat = await guild.create_category(GAMING_VOICE_CATEGORY)
        results["categories"].append(f"✅ Created {GAMING_VOICE_CATEGORY}")
        await asyncio.sleep(0.5)
    for ch_name in GAMING_VOICE_CHANNELS:
        if not discord.utils.get(voice_cat.channels, name=ch_name):
            await guild.create_voice_channel(ch_name, category=voice_cat)
            results["channels"].append(f"✅ Created {ch_name} (voice)")
            await asyncio.sleep(0.3)


async def setup_community(self, guild, results):
    community_roles = [
        {"name": "👑 Owner", "color": discord.Color.gold(), "hoist": True},
        {"name": "🛡️ Admin", "color": discord.Color.red(), "hoist": True},
        {"name": "🔧 Moderator", "color": discord.Color.green(), "hoist": True},
        {"name": "🧩 Helper", "color": discord.Color.blue(), "hoist": True},
        {"name": "🌱 New Member", "color": discord.Color.lighter_grey(), "hoist": False},
        {"name": "💬 Active Member", "color": discord.Color.teal(), "hoist": False},
        {"name": "🌟 Contributor", "color": discord.Color.gold(), "hoist": False},
        {"name": "🎨 Creative", "color": discord.Color.purple(), "hoist": False},
        {"name": "💻 Tech Enthusiast", "color": discord.Color.dark_blue(), "hoist": False},
        {"name": "🌙 Night Owl", "color": discord.Color.dark_blue(), "hoist": False},
        {"name": "👻 Lurker", "color": discord.Color.light_grey(), "hoist": False},
    ]

    for role_data in community_roles:
        if not discord.utils.get(guild.roles, name=role_data["name"]):
            try:
                await guild.create_role(
                    name=role_data["name"],
                    color=role_data["color"],
                    hoist=role_data["hoist"]
                )
                results["roles"].append(f"✅ Created {role_data['name']}")
                await asyncio.sleep(0.3)
            except Exception as e:
                results["errors"].append(f"❌ Failed to create {role_data['name']}: {str(e)}")

    community_categories = {
        COMMUNITY_INFO_CATEGORY: COMMUNITY_INFO_CHANNELS,
        COMMUNITY_GENERAL_CATEGORY: COMMUNITY_GENERAL_CHANNELS,
        COMMUNITY_DISCUSSION_CATEGORY: COMMUNITY_DISCUSSION_CHANNELS,
        COMMUNITY_CONNECTION_CATEGORY: COMMUNITY_CONNECTION_CHANNELS,
    }

    for cat_name, channels in community_categories.items():
        cat = discord.utils.get(guild.categories, name=cat_name)
        if not cat:
            cat = await guild.create_category(cat_name)
            results["categories"].append(f"✅ Created {cat_name}")
            await asyncio.sleep(0.5)
        for ch_name in channels:
            if not discord.utils.get(cat.channels, name=ch_name):
                await guild.create_text_channel(ch_name, category=cat)
                results["channels"].append(f"✅ Created {ch_name}")
                await asyncio.sleep(0.3)

    # Voice lounge
    voice_cat = discord.utils.get(guild.categories, name=COMMUNITY_VOICE_CATEGORY)
    if not voice_cat:
        voice_cat = await guild.create_category(COMMUNITY_VOICE_CATEGORY)
        results["categories"].append(f"✅ Created {COMMUNITY_VOICE_CATEGORY}")
        await asyncio.sleep(0.5)
    for ch_name in COMMUNITY_VOICE_CHANNELS:
        if not discord.utils.get(voice_cat.channels, name=ch_name):
            await guild.create_voice_channel(ch_name, category=voice_cat)
            results["channels"].append(f"✅ Created {ch_name} (voice)")
            await asyncio.sleep(0.3)


async def setup_ticket(self, guild, results):
    ticket_roles = [
        {"name": SUPPORT_ROLE, "color": discord.Color.blue(), "hoist": True},
        {"name": REQUEST_ROLE, "color": discord.Color.green(), "hoist": False},
    ]

    for role_data in ticket_roles:
        if not discord.utils.get(guild.roles, name=role_data["name"]):
            try:
                await guild.create_role(
                    name=role_data["name"],
                    color=role_data["color"],
                    hoist=role_data["hoist"]
                )
                results["roles"].append(f"✅ Created {role_data['name']}")
                await asyncio.sleep(0.3)
            except Exception as e:
                results["errors"].append(f"❌ Failed to create {role_data['name']}: {str(e)}")

    # ── Build staff overwrites BEFORE creating any categories ────────────
    everyone       = guild.default_role
    bot_role_obj   = discord.utils.get(guild.roles, name=BOT_ROLE)
    kick_role_obj  = discord.utils.get(guild.roles, name=KICK_ROLE)
    ban_role_obj   = discord.utils.get(guild.roles, name=BAN_ROLE)
    support_role   = discord.utils.get(guild.roles, name=SUPPORT_ROLE)

    staff_overwrites = {
        everyone: discord.PermissionOverwrite(
            view_channel=False,
            read_messages=False,
            send_messages=False
        ),
    }
    for r in [bot_role_obj, kick_role_obj, ban_role_obj, support_role]:
        if r:
            staff_overwrites[r] = discord.PermissionOverwrite(
                view_channel=True,
                read_messages=True,
                send_messages=True,
                manage_messages=True,
                attach_files=True,
                embed_links=True,
                read_message_history=True
            )

    # ── Public ticket categories (visible to everyone) ───────────────────
    public_ticket_categories = [
        BUG_CATEGORY, BUY_CATEGORY, REPORT_CATEGORY,
        VERIFY_CATEGORY, ASAIYA_TICKET_CATEGORY, ASAIYA_DONE_CATEGORY
    ]

    created_categories = {}
    for cat_name in public_ticket_categories:
        cat = discord.utils.get(guild.categories, name=cat_name)
        if not cat:
            try:
                cat = await guild.create_category(cat_name)
                results["categories"].append(f"✅ Created {cat_name}")
                await asyncio.sleep(0.5)
            except Exception as e:
                results["errors"].append(f"❌ Failed to create {cat_name}: {str(e)}")
                continue
        created_categories[cat_name] = cat

    # ── Staff Team category — private from the start ─────────────────────
    staff_category = discord.utils.get(guild.categories, name=STAFF_CATEGORY)
    if not staff_category:
        try:
            # Create with overwrites baked in so it's NEVER publicly visible
            staff_category = await guild.create_category(
                STAFF_CATEGORY,
                overwrites=staff_overwrites,
                reason="Staff-only category"
            )
            results["categories"].append(f"✅ Created {STAFF_CATEGORY} (private)")
            await asyncio.sleep(0.5)
        except Exception as e:
            results["errors"].append(f"❌ Failed to create {STAFF_CATEGORY}: {str(e)}")
    else:
        # Category already exists — force-apply the correct overwrites
        try:
            await staff_category.edit(overwrites=staff_overwrites)
            results["categories"].append(f"✅ Updated {STAFF_CATEGORY} permissions (private)")
            await asyncio.sleep(0.3)
        except Exception as e:
            results["errors"].append(f"⚠️ Could not update {STAFF_CATEGORY} overwrites: {e}")

    # ── Create staff channels with explicit overwrites ────────────────────
    if staff_category:
        for ch_name in [TICKET_ALERTS_CHANNEL, TICKET_LOGS_CHANNEL]:
            existing = discord.utils.get(staff_category.channels, name=ch_name)
            if not existing:
                try:
                    await guild.create_text_channel(
                        ch_name,
                        category=staff_category,
                        overwrites=staff_overwrites,
                        reason="Staff-only ticket channel"
                    )
                    results["channels"].append(f"✅ Created #{ch_name} (private, staff only)")
                    await asyncio.sleep(0.3)
                except Exception as e:
                    results["errors"].append(f"❌ Failed to create #{ch_name}: {str(e)}")
            else:
                # Channel already exists — fix its overwrites too
                try:
                    await existing.edit(overwrites=staff_overwrites)
                    results["channels"].append(f"✅ Fixed #{ch_name} permissions (private)")
                    await asyncio.sleep(0.2)
                except Exception as e:
                    results["errors"].append(f"⚠️ Could not fix #{ch_name} overwrites: {e}")

    # ── Verification channel — public read, no send ───────────────────────
    if not discord.utils.get(guild.text_channels, name=VERIFICATION_CHANNEL):
        try:
            verif_ch = await guild.create_text_channel(VERIFICATION_CHANNEL)
            await verif_ch.set_permissions(guild.default_role, read_messages=True, send_messages=False)
            results["channels"].append(f"✅ Created #{VERIFICATION_CHANNEL}")
            await asyncio.sleep(0.3)
        except Exception as e:
            results["errors"].append(f"❌ Failed to create #{VERIFICATION_CHANNEL}: {str(e)}")


# Bind methods to Admin cog
Admin.run_setup = run_setup
Admin.setup_minimal = setup_minimal
Admin.setup_gaming = setup_gaming
Admin.setup_community = setup_community
Admin.setup_ticket = setup_ticket
Admin.start_custom_setup = start_custom_setup
Admin.collect_categories = collect_categories
Admin.collect_channels = collect_channels
Admin.collect_roles = collect_roles
Admin.collect_hierarchy = collect_hierarchy
Admin.create_custom_server = create_custom_server


async def setup(bot):
    await bot.add_cog(Admin(bot))
