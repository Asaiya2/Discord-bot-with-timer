import discord
from discord.ext import commands, tasks
import sqlite3
import time
import asyncio
import json
import hashlib
import os
from datetime import datetime, timedelta

# ===== CONFIGURATION =====
DB_FOLDER = r"C:\Users\Kelly\Desktop\discord database"
MAIN_DB_PATH = os.path.join(DB_FOLDER, "asaiya_bot.db")

ACTION_DELAY = 1
BACKUP_EXPIRY_DAYS = 30  # Delete backups older than 30 days
BACKUP_CLEANUP_INTERVAL = 24  # Check every 24 hours


def hash_backup_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


class Backup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Track processed commands to prevent duplicates
        self.processed_commands = {}
        
        self.setup_database()
        
        # Start the backup cleanup task
        self.cleanup_old_backups.start()
        
        print(f"✅ Backup cog initialized (ID: {id(self)})")

    def cog_unload(self):
        """Stop tasks when cog is unloaded"""
        self.cleanup_old_backups.cancel()
        print("🛑 Backup cleanup tasks stopped")

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

    def setup_database(self):
        """Initialize backup table"""
        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS server_backups_v2
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      guild_id TEXT,
                      server_name TEXT,
                      password_hash TEXT,
                      backup_data TEXT,
                      created_by TEXT,
                      created_by_name TEXT,
                      created_at REAL)''')
        conn.commit()
        conn.close()
        print("✅ Backup database initialized")

    # ===== BACKGROUND TASK: CLEANUP OLD BACKUPS =====
    @tasks.loop(hours=BACKUP_CLEANUP_INTERVAL)
    async def cleanup_old_backups(self):
        """Delete backups older than BACKUP_EXPIRY_DAYS"""
        print(f"🧹 [{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] Running server backup cleanup...")
        
        cutoff_time = time.time() - (BACKUP_EXPIRY_DAYS * 86400)
        
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            
            # Find old backups to log them
            c.execute("SELECT id, server_name, created_by_name, created_at FROM server_backups_v2 WHERE created_at < ?",
                      (cutoff_time,))
            old_backups = c.fetchall()
            
            # Delete old backups
            c.execute("DELETE FROM server_backups_v2 WHERE created_at < ?", (cutoff_time,))
            deleted = c.rowcount
            
            conn.commit()
            conn.close()
            
            if deleted > 0:
                print(f"✅ Deleted {deleted} expired server backup(s) older than {BACKUP_EXPIRY_DAYS} days")
                
                # Log the first few deleted backups for reference
                for i, (backup_id, server_name, creator, created_at) in enumerate(old_backups[:3]):
                    time_str = datetime.fromtimestamp(created_at).strftime("%Y-%m-%d")
                    print(f"   🗑️ {server_name} (by {creator}) from {time_str}")
                
                if len(old_backups) > 3:
                    print(f"   ... and {len(old_backups) - 3} more")
            else:
                print("   No expired backups found")
                
        except Exception as e:
            print(f"❌ Error cleaning up old backups: {e}")

    @cleanup_old_backups.before_loop
    async def before_cleanup(self):
        """Wait for bot to be ready before starting task"""
        await self.bot.wait_until_ready()
        print("⏱️ Backup cleanup task ready")

    # ===== MANUAL CLEANUP COMMAND =====
    @commands.command(name='cleanoldbackups')
    @commands.has_permissions(administrator=True)
    async def cleanoldbackups(self, ctx, days: int = None):
        """Manually clean up old server backups.
        Usage: !cleanoldbackups [days] (default: 30)
        """
        if await self.check_duplicate(ctx):
            return
            
        if days is None:
            days = BACKUP_EXPIRY_DAYS
            
        if days < 1:
            await ctx.send("❌ Days must be at least 1.")
            return
            
        cutoff_time = time.time() - (days * 86400)
        
        status_msg = await ctx.send(f"🧹 Cleaning up server backups older than {days} days...")
        
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            
            # Count backups that will be deleted
            c.execute("SELECT COUNT(*) FROM server_backups_v2 WHERE created_at < ?", (cutoff_time,))
            count = c.fetchone()[0]
            
            if count == 0:
                await status_msg.edit(content=f"📭 No server backups older than {days} days found.")
                conn.close()
                return
            
            # Delete them
            c.execute("DELETE FROM server_backups_v2 WHERE created_at < ?", (cutoff_time,))
            deleted = c.rowcount
            conn.commit()
            conn.close()
            
            await status_msg.edit(content=f"✅ Deleted {deleted} server backup(s) older than {days} days!")
            
            # Log to channel
            await ctx.send(f"🧹 Manual cleanup completed by {ctx.author.mention}")
            
        except Exception as e:
            await status_msg.edit(content=f"❌ Error: {str(e)}")

    # ===== CLEAN MESSAGE BACKUPS COMMAND =====
    @commands.command(name='cleanbackups')
    @commands.has_permissions(administrator=True)
    async def cleanbackups(self, ctx, days: int = 30):
        """Manually clean up message backups older than specified days.
        Usage: !cleanbackups [days] (default: 30)
        """
        if await self.check_duplicate(ctx):
            return

        if days < 1:
            await ctx.send("❌ Days must be at least 1.")
            return

        status_msg = await ctx.send(f"🧹 Cleaning up message backups older than {days} days...")

        try:
            cutoff_time = time.time() - (days * 86400)
            conn = self.get_cached_connection(ctx.guild.id)

            if not conn:
                await status_msg.edit(content="❌ Could not connect to database.")
                return

            c = conn.cursor()
            c.execute("DELETE FROM message_backup WHERE timestamp < ?", (cutoff_time,))
            deleted = c.rowcount
            conn.commit()

            await status_msg.edit(content=f"✅ Deleted {deleted} message backup(s) older than {days} day(s)!")

            log_channel = await self.get_log_channel(ctx.guild)
            if log_channel:
                await log_channel.send(f"🧹 {ctx.author.mention} manually cleaned {deleted} old message backups")

        except Exception as e:
            await status_msg.edit(content=f"❌ Error: {str(e)}")

    # ===== BACKUP STATS COMMAND =====
    @commands.command(name='backupstats')
    @commands.has_permissions(administrator=True)
    async def backupstats(self, ctx):
        """Show statistics about server backups"""
        if await self.check_duplicate(ctx):
            return
            
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            
            # Total backups
            c.execute("SELECT COUNT(*) FROM server_backups_v2")
            total = c.fetchone()[0]
            
            # Backups by age
            now = time.time()
            c.execute("SELECT COUNT(*) FROM server_backups_v2 WHERE created_at > ?", (now - 86400,))  # Last 24h
            last_24h = c.fetchone()[0]
            
            c.execute("SELECT COUNT(*) FROM server_backups_v2 WHERE created_at > ?", (now - 604800,))  # Last 7d
            last_7d = c.fetchone()[0]
            
            c.execute("SELECT COUNT(*) FROM server_backups_v2 WHERE created_at > ?", (now - 2592000,))  # Last 30d
            last_30d = c.fetchone()[0]
            
            # Oldest and newest
            c.execute("SELECT MIN(created_at), MAX(created_at) FROM server_backups_v2")
            oldest, newest = c.fetchone()
            
            # Top backup creators
            c.execute('''SELECT created_by_name, COUNT(*) as count 
                         FROM server_backups_v2 
                         GROUP BY created_by_name 
                         ORDER BY count DESC 
                         LIMIT 5''')
            top_creators = c.fetchall()
            
            conn.close()
            
            embed = discord.Embed(
                title="📊 Server Backup Statistics",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(name="Total Backups", value=str(total), inline=True)
            embed.add_field(name="Last 24h", value=str(last_24h), inline=True)
            embed.add_field(name="Last 7d", value=str(last_7d), inline=True)
            embed.add_field(name="Last 30d", value=str(last_30d), inline=True)
            
            if oldest:
                oldest_str = datetime.fromtimestamp(oldest).strftime("%Y-%m-%d")
                embed.add_field(name="Oldest Backup", value=oldest_str, inline=True)
            if newest:
                newest_str = datetime.fromtimestamp(newest).strftime("%Y-%m-%d")
                embed.add_field(name="Newest Backup", value=newest_str, inline=True)
            
            if top_creators:
                creators_text = ""
                for name, count in top_creators:
                    creators_text += f"• {name}: **{count}** backup(s)\n"
                embed.add_field(name="Top Backup Creators", value=creators_text, inline=False)
            
            embed.set_footer(text=f"Backups older than {BACKUP_EXPIRY_DAYS} days are auto-deleted")
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")

    # ===== EXISTING COMMANDS (with duplicate prevention added) =====

    @commands.command(name='sserver')
    @commands.has_permissions(administrator=True)
    async def sserver(self, ctx, password: str):
        """Backup the current server structure. Only ONE backup per user allowed.
        Usage: !sserver [password]
        """
        if await self.check_duplicate(ctx):
            return
            
        await ctx.message.delete()

        # Check if user already has a backup
        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT server_name, created_at FROM server_backups_v2 WHERE created_by = ?",
                  (str(ctx.author.id),))
        existing = c.fetchone()
        conn.close()

        if existing:
            server_name, created_at = existing
            time_str = datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M")
            try:
                embed = discord.Embed(
                    title="❌ Backup Already Exists",
                    description=(
                        f"You already have a backup from **{server_name}** (created {time_str}).\n\n"
                        f"You can only have **one backup at a time**.\n\n"
                        f"To create a new backup, first restore your existing one using:\n"
                        f"`!remake [your password]`\n\n"
                        f"Once the restore is complete, your old backup will be deleted automatically."
                    ),
                    color=discord.Color.red()
                )
                await ctx.author.send(embed=embed)
            except discord.Forbidden:
                pass
            return

        # Create invite link
        try:
            invite = await ctx.channel.create_invite(max_age=300, max_uses=1)
            invite_link = invite.url
        except:
            invite_link = "Could not create invite"

        # Send initial DM
        embed = discord.Embed(
            title="🔄 Server Backup Initiated",
            description=f"Backup started for: **{ctx.guild.name}**",
            color=discord.Color.green()
        )
        embed.add_field(name="📊 Server Details",
                        value=f"ID: `{ctx.guild.id}`\nMembers: {ctx.guild.member_count}",
                        inline=False)
        embed.add_field(name="🔗 Server Link", value=f"[Click to join]({invite_link})", inline=False)
        embed.add_field(name="⏳ Status", value="```\n📥 Capturing server structure...```", inline=False)

        try:
            await ctx.author.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("❌ I couldn't DM you. Please enable DMs and try again.")
            return

        # Capture server data
        server_data = {
            "name": ctx.guild.name,
            "roles": [],
            "categories": [],
            "channels": []
        }

        # Roles (skip @everyone)
        for role in ctx.guild.roles:
            if role.name != "@everyone":
                server_data["roles"].append({
                    "name": role.name,
                    "color": role.color.value,
                    "permissions": role.permissions.value,
                    "position": role.position,
                    "mentionable": role.mentionable,
                    "hoist": role.hoist
                })
        server_data["roles"].sort(key=lambda x: x['position'])

        # Categories and their channels
        for category in ctx.guild.categories:
            cat_data = {
                "name": category.name,
                "position": category.position,
                "channels": []
            }
            for channel in category.channels:
                ch = {
                    "name": channel.name,
                    "type": str(channel.type),
                    "position": channel.position,
                    "overwrites": []
                }
                for target, overwrite in channel.overwrites.items():
                    ch["overwrites"].append({
                        "target_id": target.id,
                        "target_type": "role" if isinstance(target, discord.Role) else "member",
                        "allow": overwrite.pair()[0].value,
                        "deny": overwrite.pair()[1].value
                    })
                cat_data["channels"].append(ch)
            server_data["categories"].append(cat_data)

        # Channels without categories
        for channel in ctx.guild.channels:
            if channel.category is None and not isinstance(channel, discord.CategoryChannel):
                ch = {
                    "name": channel.name,
                    "type": str(channel.type),
                    "position": channel.position,
                    "category": None,
                    "overwrites": []
                }
                for target, overwrite in channel.overwrites.items():
                    ch["overwrites"].append({
                        "target_id": target.id,
                        "target_type": "role" if isinstance(target, discord.Role) else "member",
                        "allow": overwrite.pair()[0].value,
                        "deny": overwrite.pair()[1].value
                    })
                server_data["channels"].append(ch)

        # Save to database
        password_hash = hash_backup_password(password)
        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()
        c.execute('''INSERT INTO server_backups_v2
                     (guild_id, server_name, password_hash, backup_data, created_by, created_by_name, created_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (str(ctx.guild.id), ctx.guild.name, password_hash,
                   json.dumps(server_data), str(ctx.author.id), ctx.author.name, time.time()))
        conn.commit()
        conn.close()

        # Send completion DM
        embed = discord.Embed(
            title="✅ Backup Complete!",
            description=f"Server **{ctx.guild.name}** has been backed up.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="📋 Summary",
            value=(
                f"Roles: {len(server_data['roles'])}\n"
                f"Categories: {len(server_data['categories'])}\n"
                f"Channels: {len(server_data['channels'])}"
            ),
            inline=False
        )
        embed.add_field(
            name="🔑 Restore Command",
            value=f"`!remake {password}`\n\n**Keep this password safe!**",
            inline=False
        )
        embed.add_field(
            name="⚠️ Important",
            value=(
                "You can only hold **one backup at a time**.\n"
                "Once you use `!remake`, your backup will be **automatically deleted**.\n"
                f"Backups older than {BACKUP_EXPIRY_DAYS} days are automatically deleted."
            ),
            inline=False
        )
        await ctx.author.send(embed=embed)

    @commands.command(name='remake')
    @commands.has_permissions(administrator=True)
    async def remake(self, ctx, password: str):
        """Restore a server from backup. Backup is auto-deleted after restoration.
        Usage: !remake [password]
        """
        if await self.check_duplicate(ctx):
            return
            
        await ctx.message.delete()

        password_hash = hash_backup_password(password)
        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT * FROM server_backups_v2 WHERE password_hash = ? AND created_by = ?",
                  (password_hash, str(ctx.author.id)))
        backup = c.fetchone()
        conn.close()

        if not backup:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT created_by_name FROM server_backups_v2 WHERE password_hash = ?",
                      (password_hash,))
            other = c.fetchone()
            conn.close()

            try:
                if other:
                    await ctx.author.send("❌ That backup belongs to someone else.")
                else:
                    await ctx.author.send("❌ No backup found with that password.")
            except:
                pass
            return

        _, guild_id, server_name, _, backup_json, creator_id, creator_name, created_at = backup
        server_data = json.loads(backup_json)

        try:
            invite = await ctx.channel.create_invite(max_age=300, max_uses=1)
            invite_link = invite.url
        except:
            invite_link = "Could not create invite"

        total_items = (
            len(server_data['roles']) +
            len(server_data['categories']) +
            sum(len(cat['channels']) for cat in server_data['categories']) +
            len(server_data['channels'])
        )

        embed = discord.Embed(
            title="🔄 Server Restoration Initiated",
            description=f"Restoring **{server_name}** → **{ctx.guild.name}**",
            color=discord.Color.green()
        )
        embed.add_field(name="🎯 Target Server",
                        value=f"[Click to join]({invite_link})", inline=False)
        embed.add_field(name="⏳ Estimated Time",
                        value=f"~{max(1, (total_items * ACTION_DELAY) // 60)} minute(s)", inline=False)
        embed.add_field(name="🗑️ Note",
                        value="Your backup will be **automatically deleted** once restoration is complete.",
                        inline=False)

        try:
            progress_msg = await ctx.author.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("❌ I couldn't DM you. Please enable DMs and try again.")
            return

        asyncio.create_task(
            self.process_restoration(
                ctx.guild, server_data, ctx.author, progress_msg,
                password_hash=password_hash, creator_id=str(ctx.author.id)
            )
        )

    async def process_restoration(self, guild, server_data, user, progress_msg,
                                   password_hash=None, creator_id=None):
        """Restore roles, categories, and channels with progress updates"""
        total_steps = (
            len(server_data['roles']) +
            len(server_data['categories']) +
            sum(len(cat['channels']) for cat in server_data['categories']) +
            len(server_data['channels'])
        )
        current_step = 0

        async def update_progress(action):
            nonlocal current_step
            current_step += 1
            percentage = int((current_step / total_steps) * 100)
            bar_length = 20
            filled = int(bar_length * current_step // total_steps)
            bar = "█" * filled + "░" * (bar_length - filled)

            embed = discord.Embed(title="🔄 Restoration Progress", color=discord.Color.yellow())
            embed.add_field(
                name="Progress",
                value=f"```{bar}```\n**{percentage}%** ({current_step}/{total_steps})",
                inline=False
            )
            embed.add_field(name="Current Action", value=f"⏳ {action}", inline=False)
            try:
                await progress_msg.edit(embed=embed)
            except:
                pass

        # Create roles
        for role_data in server_data['roles']:
            try:
                if not discord.utils.get(guild.roles, name=role_data['name']):
                    await guild.create_role(
                        name=role_data['name'],
                        color=discord.Color(role_data['color']),
                        permissions=discord.Permissions(role_data['permissions']),
                        mentionable=role_data['mentionable'],
                        hoist=role_data['hoist']
                    )
            except Exception as e:
                await user.send(f"⚠️ Error creating role **{role_data['name']}**: {e}")
            await update_progress(f"Creating role: {role_data['name']}")
            await asyncio.sleep(ACTION_DELAY)

        # Create categories
        for cat_data in server_data['categories']:
            try:
                if not discord.utils.get(guild.categories, name=cat_data['name']):
                    await guild.create_category(cat_data['name'])
            except Exception as e:
                await user.send(f"⚠️ Error creating category **{cat_data['name']}**: {e}")
            await update_progress(f"Creating category: {cat_data['name']}")
            await asyncio.sleep(ACTION_DELAY)

        # Create channels inside categories
        for cat_data in server_data['categories']:
            category = discord.utils.get(guild.categories, name=cat_data['name'])
            for ch_data in cat_data['channels']:
                try:
                    if ch_data['type'] == 'text':
                        await guild.create_text_channel(ch_data['name'], category=category)
                    elif ch_data['type'] == 'voice':
                        await guild.create_voice_channel(ch_data['name'], category=category)
                except Exception as e:
                    await user.send(f"⚠️ Error creating channel **{ch_data['name']}**: {e}")
                await update_progress(f"Creating channel: {ch_data['name']}")
                await asyncio.sleep(ACTION_DELAY)

        # Create channels without categories
        for ch_data in server_data['channels']:
            try:
                if ch_data['type'] == 'text':
                    await guild.create_text_channel(ch_data['name'])
                elif ch_data['type'] == 'voice':
                    await guild.create_voice_channel(ch_data['name'])
            except Exception as e:
                await user.send(f"⚠️ Error creating channel **{ch_data['name']}**: {e}")
            await update_progress(f"Creating channel: {ch_data['name']}")
            await asyncio.sleep(ACTION_DELAY)

        # Auto-delete backup
        if password_hash and creator_id:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM server_backups_v2 WHERE password_hash = ? AND created_by = ?",
                      (password_hash, creator_id))
            conn.commit()
            conn.close()

        embed = discord.Embed(
            title="✅ Restoration Complete!",
            description=f"Server **{guild.name}** has been restored.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="📊 Summary",
            value=(
                f"Roles: {len(server_data['roles'])}\n"
                f"Categories: {len(server_data['categories'])}\n"
                f"Channels: {len(server_data['channels'])}"
            ),
            inline=False
        )
        embed.add_field(
            name="🗑️ Backup Deleted",
            value="Your backup has been removed. You can now create a new one with `!sserver`.",
            inline=False
        )
        try:
            await progress_msg.edit(embed=embed)
        except:
            await user.send(embed=embed)

    @commands.command(name='backups')
    @commands.has_permissions(administrator=True)
    async def backups(self, ctx):
        """Check if you have a saved backup"""
        if await self.check_duplicate(ctx):
            return
            
        await ctx.message.delete()

        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT server_name, created_at, guild_id FROM server_backups_v2 WHERE created_by = ?",
                  (str(ctx.author.id),))
        row = c.fetchone()
        conn.close()

        if not row:
            try:
                await ctx.author.send(
                    "📭 You have no saved backup.\n"
                    "Use `!sserver [password]` to create one."
                )
            except:
                await ctx.send("📭 You have no saved backup.")
            return

        server_name, created_at, guild_id = row
        time_str = datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M")
        
        # Calculate when it will expire
        expiry_time = created_at + (BACKUP_EXPIRY_DAYS * 86400)
        days_left = int((expiry_time - time.time()) / 86400)

        embed = discord.Embed(
            title="📋 Your Server Backup",
            color=discord.Color.blue()
        )
        embed.add_field(name="Server Name", value=server_name, inline=True)
        embed.add_field(name="Server ID", value=f"`{guild_id}`", inline=True)
        embed.add_field(name="Created", value=time_str, inline=True)
        embed.add_field(name="Expires in", value=f"**{days_left}** days", inline=True)
        embed.set_footer(text="Use !remake [password] to restore • Backups are auto-deleted after 30 days")

        try:
            await ctx.author.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("❌ I couldn't DM you. Please enable DMs.")

    @commands.command(name='delbackup')
    @commands.has_permissions(administrator=True)
    async def delbackup(self, ctx, password: str):
        """Manually delete your backup. Usage: !delbackup [password]"""
        if await self.check_duplicate(ctx):
            return
            
        await ctx.message.delete()

        password_hash = hash_backup_password(password)
        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT server_name FROM server_backups_v2 WHERE password_hash = ? AND created_by = ?",
                  (password_hash, str(ctx.author.id)))
        result = c.fetchone()

        if not result:
            try:
                await ctx.author.send("❌ No backup found with that password, or it doesn't belong to you.")
            except:
                pass
            conn.close()
            return

        c.execute("DELETE FROM server_backups_v2 WHERE password_hash = ? AND created_by = ?",
                  (password_hash, str(ctx.author.id)))
        conn.commit()
        conn.close()

        try:
            await ctx.author.send(
                f"✅ Backup for **{result[0]}** has been deleted.\n"
                f"You can now create a new backup with `!sserver [password]`."
            )
        except:
            pass


async def setup(bot):
    await bot.add_cog(Backup(bot))
