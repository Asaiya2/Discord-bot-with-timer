import discord
from discord.ext import commands, tasks
import sqlite3
import time
import asyncio
import os
import random
from datetime import datetime

# ===== CONFIGURATION =====
DB_FOLDER = r"C:\Users\Kelly\Desktop\discord database"
MAIN_DB_PATH = os.path.join(DB_FOLDER, "asaiya_bot.db")
MESSAGE_BACKUP_TABLE = "message_backup"


class Tasks(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Track processed commands to prevent duplicates
        self.processed_commands = {}
        print(f"✅ Tasks cog initialized (ID: {id(self)})")

    # ===== COG LOAD/UNLOAD =====
    def cog_unload(self):
        """Stop all tasks when cog is unloaded"""
        self.cleanup_old_backups_task.cancel()
        self.clean_expired_captcha_sessions.cancel()
        self.cleanup_expired_setups.cancel()
        self.verify_server_keys.cancel()
        self.check_expired_giveaways.cancel()
        print("🛑 All background tasks stopped")

    def start_all_tasks(self):
        """Start all background tasks (called from events.py)"""
        self.cleanup_old_backups_task.start()
        self.clean_expired_captcha_sessions.start()
        self.cleanup_expired_setups.start()
        self.verify_server_keys.start()
        self.check_expired_giveaways.start()
        print("✅ All background tasks started")

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

    async def get_log_channel(self, guild):
        """Get log channel for a guild"""
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

    # ===== TASK: CLEANUP OLD BACKUPS (Daily) =====
    @tasks.loop(hours=24)
    async def cleanup_old_backups_task(self):
        """Run backup cleanup every 24 hours - Deletes message backups older than 30 days"""
        print(f"🧹 [{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] Running scheduled backup cleanup...")
        
        cutoff_time = time.time() - (30 * 86400)  # 30 days in seconds
        total_deleted = 0
        servers_processed = 0
        
        # Get all registered servers
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT guild_id, server_number FROM servers")
            servers = c.fetchall()
            conn.close()
        except Exception as e:
            print(f"❌ Error fetching servers for cleanup: {e}")
            return

        # Clean each server's database
        for guild_id, server_number in servers:
            try:
                db_path = os.path.join(DB_FOLDER, f"asaiya_bot_server{server_number}.db")
                if not os.path.exists(db_path):
                    continue
                    
                server_conn = sqlite3.connect(db_path)
                server_c = server_conn.cursor()
                
                # Ensure table exists
                server_c.execute(f'''CREATE TABLE IF NOT EXISTS {MESSAGE_BACKUP_TABLE}
                                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                                     channel_id TEXT,
                                     channel_name TEXT,
                                     author_id TEXT,
                                     author_name TEXT,
                                     content TEXT,
                                     timestamp REAL,
                                     attachments TEXT)''')
                
                # Delete old backups
                server_c.execute(f"DELETE FROM {MESSAGE_BACKUP_TABLE} WHERE timestamp < ?", (cutoff_time,))
                deleted = server_c.rowcount
                total_deleted += deleted
                servers_processed += 1
                
                if deleted > 0:
                    print(f"   🗑️ Deleted {deleted} old message backups from server {server_number}")
                    
                server_conn.commit()
                server_conn.close()
                
            except Exception as e:
                print(f"❌ Error cleaning backups for server {server_number}: {e}")
        
        print(f"✅ Backup cleanup complete: Deleted {total_deleted} old messages from {servers_processed} servers")

    @cleanup_old_backups_task.before_loop
    async def before_cleanup(self):
        """Wait for bot to be ready before starting task"""
        await self.bot.wait_until_ready()

    # ===== TASK: CLEAN EXPIRED CAPTCHA SESSIONS (Every 10 minutes) =====
    @tasks.loop(minutes=10)
    async def clean_expired_captcha_sessions(self):
        """Remove expired captcha sessions from database"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM captcha_sessions WHERE expires_at < ?", (time.time(),))
            deleted = c.rowcount
            conn.commit()
            conn.close()
            if deleted > 0:
                print(f"🧹 Cleaned {deleted} expired captcha session(s)")
        except Exception as e:
            print(f"Error cleaning captcha sessions: {e}")

    # ===== TASK: CLEAN EXPIRED REACTION SETUPS (Every hour) =====
    @tasks.loop(hours=1)
    async def cleanup_expired_setups(self):
        """Remove expired reaction role setups from database"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM persistent_reaction_setup WHERE expires_at < ?", (time.time(),))
            deleted = c.rowcount
            conn.commit()
            conn.close()
            if deleted > 0:
                print(f"🧹 Cleaned {deleted} expired reaction setups")
        except Exception as e:
            print(f"Error cleaning expired setups: {e}")

    # ===== TASK: VERIFY SERVER KEYS (Every 20 minutes) =====
    @tasks.loop(minutes=20)
    async def verify_server_keys(self):
        """Check all authorized servers every 20 minutes"""
        print(f"🔑 [{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] Running key verification...")
        
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT guild_id, key_used, expires_at FROM authorized_servers")
            authorized = c.fetchall()
            
            for guild_id, key_used, expires_at in authorized:
                guild = self.bot.get_guild(int(guild_id))
                
                # Case 1: Server kicked the bot or is gone
                if not guild:
                    # Free up the key
                    c.execute("UPDATE bot_keys SET uses_remaining = uses_remaining + 1 WHERE key = ?", (key_used,))
                    c.execute("UPDATE key_uses SET is_active = 0 WHERE key = ? AND guild_id = ?", (key_used, guild_id))
                    c.execute("DELETE FROM authorized_servers WHERE guild_id = ?", (guild_id,))
                    print(f"   🗑️ Server {guild_id} left - key {key_used} freed")
                    continue
                
                # Case 2: Check if expired
                if expires_at and time.time() > expires_at:
                    c.execute("DELETE FROM authorized_servers WHERE guild_id = ?", (guild_id,))
                    c.execute("UPDATE key_uses SET is_active = 0 WHERE key = ? AND guild_id = ?", (key_used, guild_id))
                    
                    if guild.system_channel:
                        try:
                            await guild.system_channel.send(
                                "⚠️ **Bot Deactivated**\n"
                                "Your server's key has expired.\n"
                                "Contact the bot owner for a new key."
                            )
                        except:
                            pass
                    print(f"   ⏰ Server {guild.name} key expired")
                    continue
                
                # Case 3: Update last verified
                c.execute("UPDATE authorized_servers SET last_verified = ? WHERE guild_id = ?", 
                          (time.time(), guild_id))
            
            conn.commit()
            conn.close()
            print(f"✅ Key verification complete")
            
        except Exception as e:
            print(f"Error in key verification: {e}")

    # ===== TASK: CHECK EXPIRED GIVEAWAYS (Every 30 seconds) =====
    @tasks.loop(seconds=30)
    async def check_expired_giveaways(self):
        """Check for expired giveaways"""
        if not hasattr(self.bot, 'active_giveaways'):
            self.bot.active_giveaways = {}
            return
            
        current_time = time.time()
        expired = []
        
        for message_id, giveaway_data in list(self.bot.active_giveaways.items()):
            if current_time >= giveaway_data['end_time']:
                expired.append((message_id, giveaway_data))
        
        for message_id, giveaway_data in expired:
            await self.finish_giveaway(message_id, giveaway_data)
            del self.bot.active_giveaways[message_id]

    async def finish_giveaway(self, message_id, giveaway_data):
        """Finish a giveaway and pick winners"""
        channel = self.bot.get_channel(giveaway_data['channel_id'])
        if not channel:
            return

        try:
            msg = await channel.fetch_message(message_id)
        except:
            return

        entries = list(giveaway_data['entries'])

        # Parse amount (e.g., "3x" -> 3)
        amount_str = giveaway_data['amount']
        try:
            if 'x' in amount_str:
                winner_count = int(amount_str.replace('x', ''))
            else:
                winner_count = 1
        except:
            winner_count = 1

        # ── Save entries for reroll ────────────────────────────────────────
        if not hasattr(self.bot, 'ended_giveaways'):
            self.bot.ended_giveaways = {}

        self.bot.ended_giveaways[message_id] = {
            'entries': set(entries),
            'winner_count': winner_count,
            'prize': giveaway_data.get('prize', giveaway_data.get('item', 'Unknown')),
            'channel_id': giveaway_data['channel_id'],
        }

        # Keep only the last 50 ended giveaways to avoid memory bloat
        if len(self.bot.ended_giveaways) > 50:
            oldest_key = next(iter(self.bot.ended_giveaways))
            del self.bot.ended_giveaways[oldest_key]
        # ──────────────────────────────────────────────────────────────────

        if not entries:
            embed = discord.Embed(
                title="🎉 Giveaway Ended",
                description=f"**Prize:** {giveaway_data['prize']}\nNo one entered 😢",
                color=discord.Color.red()
            )
            await msg.edit(embed=embed, view=None)
            return

        winner_count = min(winner_count, len(entries))
        winners = random.sample(entries, winner_count)
        winner_mentions = [f"<@{w}>" for w in winners]

        embed = discord.Embed(
            title="🎉 **GIVEAWAY ENDED**",
            description=f"**Prize:** {giveaway_data['prize']}",
            color=discord.Color.gold()
        )
        embed.add_field(name="Winners", value=", ".join(winner_mentions), inline=False)
        embed.add_field(name="Total Entries", value=str(len(entries)), inline=True)

        await msg.edit(embed=embed, view=None)
        await channel.send(f"🎉 Congratulations {', '.join(winner_mentions)}! You won **{giveaway_data['prize']}**!")

    # ===== MANUAL CLEANUP COMMAND =====


async def setup(bot):
    await bot.add_cog(Tasks(bot))
