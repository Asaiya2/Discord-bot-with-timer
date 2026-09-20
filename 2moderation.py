import discord
from discord.ext import commands
import sqlite3
import time
import asyncio
from datetime import datetime, timedelta
import os

# ===== CONFIGURATION =====
DB_FOLDER = r"C:\Users\Kelly\Desktop\discord database"
BOT_ROLE = "AsaiyaBot"
KICK_ROLE = "AsaiyaKick"
BAN_ROLE = "AsaiyaBan"


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Track processed commands to prevent duplicates
        self.processed_commands = {}
        print(f"✅ Moderation cog initialized (ID: {id(self)})")

    # ===== DUPLICATE PREVENTION =====
    async def check_duplicate(self, ctx):
        """Check if this command was already processed"""
        key = f"{ctx.author.id}:{ctx.command.name}"
        current_time = time.time()
        
        # Check if command was recently used by this user
        if key in self.processed_commands:
            if current_time - self.processed_commands[key] < 3:  # 3 second cooldown
                print(f"⚠️ Prevented dual execution: {ctx.command.name} by {ctx.author} in {ctx.guild.name}")
                return True
        
        self.processed_commands[key] = current_time
        
        # Clean up old entries
        if len(self.processed_commands) > 100:
            to_delete = [k for k, t in self.processed_commands.items() if current_time - t > 10]
            for k in to_delete:
                del self.processed_commands[k]
        
        return False

    # ===== DATABASE HELPERS =====
    def get_server_db_path(self, guild_id):
        """Get database path for a specific server"""
        try:
            conn = sqlite3.connect(os.path.join(DB_FOLDER, "asaiya_bot.db"))
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
        """Get the log channel for a guild (must be manually set with !setlog)"""
        try:
            conn = self.get_cached_connection(guild.id)
            if not conn:
                return None
            c = conn.cursor()
            # Only get log_channel_id that was manually set
            c.execute("SELECT log_channel_id FROM log_channels WHERE log_channel_id IS NOT NULL ORDER BY rowid DESC LIMIT 1")
            result = c.fetchone()
            if result and result[0]:
                channel = guild.get_channel(int(result[0]))
                if channel:
                    return channel
        except Exception as e:
            print(f"Error getting log channel: {e}")
        return None

    async def log_punishment(self, guild, punished_user, punishment_type, reason, moderator, duration=None, warning_id=None):
        """Send formatted punishment embed to the server's log channel"""
        log_channel = await self.get_log_channel(guild)
        if not log_channel:
            return
        
        # Colors for different punishment types
        colors = {
            "Timeout": discord.Color.orange(),
            "Kick": discord.Color.gold(),
            "Ban": discord.Color.dark_red(),
            "Unban": discord.Color.green(),
            "Warning": discord.Color.orange(),
            "Clear": discord.Color.blue()
        }
        
        embed = discord.Embed(
            title=f"🔨 {punishment_type.upper()}",
            color=colors.get(punishment_type, discord.Color.red()),
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(name="Punished User", value=f"{punished_user.mention} ({punished_user})", inline=False)
        embed.add_field(name="User ID", value=f"`{punished_user.id}`", inline=True)
        embed.add_field(name="Punishment", value=punishment_type, inline=True)
        
        if duration:
            embed.add_field(name="Duration", value=duration, inline=True)
        
        if warning_id:
            embed.add_field(name="Warning ID", value=f"#{warning_id}", inline=True)
        
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="By", value=f"{moderator.mention} ({moderator})", inline=False)
        
        await log_channel.send(embed=embed)

    # ===== KICK COMMAND =====
    @commands.command(name='kick')
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        """Kick a member from the server"""
        if await self.check_duplicate(ctx):
            return
            
        if member == ctx.author:
            await ctx.send("❌ You cannot kick yourself!")
            return
        if member.top_role >= ctx.author.top_role:
            await ctx.send("❌ You cannot kick someone with higher or equal roles!")
            return
        
        try:
            await member.kick(reason=reason)
            await ctx.send(f"✅ {member.mention} has been kicked. Reason: {reason}")
            
            # Log to log channel with formatted embed
            await self.log_punishment(ctx.guild, member, "Kick", reason, ctx.author)
                
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to kick that user!")
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")

    # ===== BAN COMMAND =====
    @commands.command(name='ban')
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        """Ban a member from the server"""
        if await self.check_duplicate(ctx):
            return
            
        if member == ctx.author:
            await ctx.send("❌ You cannot ban yourself!")
            return
        if member.top_role >= ctx.author.top_role:
            await ctx.send("❌ You cannot ban someone with higher or equal roles!")
            return
        
        try:
            await member.ban(reason=reason)
            await ctx.send(f"✅ {member.mention} has been banned. Reason: {reason}")
            
            # Log to log channel with formatted embed
            await self.log_punishment(ctx.guild, member, "Ban", reason, ctx.author)
                
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to ban that user!")
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")

    # ===== UNBAN COMMAND =====
    @commands.command(name='unban')
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, user_id: int):
        """Unban a user by ID"""
        if await self.check_duplicate(ctx):
            return
            
        try:
            user = await self.bot.fetch_user(user_id)
            await ctx.guild.unban(user)
            await ctx.send(f"✅ {user} has been unbanned.")
            
            # Log to log channel with formatted embed
            log_channel = await self.get_log_channel(ctx.guild)
            if log_channel:
                embed = discord.Embed(
                    title="🔓 UNBAN",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Unbanned User", value=f"{user}", inline=False)
                embed.add_field(name="User ID", value=f"`{user_id}`", inline=True)
                embed.add_field(name="Punishment", value="Unban", inline=True)
                embed.add_field(name="By", value=f"{ctx.author.mention} ({ctx.author})", inline=False)
                await log_channel.send(embed=embed)
                
        except discord.NotFound:
            await ctx.send("❌ User not found or not banned.")
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")

    # ===== CLEAR COMMAND =====
    @commands.command(name='clear')
    @commands.has_permissions(manage_messages=True)
    async def clear(self, ctx, amount: int):
        """Clear messages in the channel"""
        if await self.check_duplicate(ctx):
            return
            
        if amount < 1 or amount > 1000:
            await ctx.send("❌ Amount must be between 1 and 1000.")
            return
        
        try:
            await ctx.message.delete()
            deleted = await ctx.channel.purge(limit=amount)
            msg = await ctx.send(f"✅ Deleted {len(deleted)} messages.")
            
            # Log to log channel
            log_channel = await self.get_log_channel(ctx.guild)
            if log_channel:
                embed = discord.Embed(
                    title="🧹 CLEAR",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Channel", value=ctx.channel.mention, inline=False)
                embed.add_field(name="Messages Deleted", value=str(len(deleted)), inline=True)
                embed.add_field(name="By", value=f"{ctx.author.mention} ({ctx.author})", inline=True)
                await log_channel.send(embed=embed)
                
            await asyncio.sleep(3)
            await msg.delete()
            
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")

    # ===== WARN COMMAND =====
    @commands.command(name='warn')
    @commands.has_permissions(kick_members=True)
    async def warn(self, ctx, member: discord.Member, *, reason: str):
        """Warn a member"""
        if await self.check_duplicate(ctx):
            return
            
        conn = sqlite3.connect(os.path.join(DB_FOLDER, "asaiya_bot.db"))
        c = conn.cursor()
        
        # Create warnings table if it doesn't exist
        c.execute('''CREATE TABLE IF NOT EXISTS warnings
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id TEXT,
                      mod_id TEXT,
                      reason TEXT,
                      timestamp REAL)''')
        
        c.execute("INSERT INTO warnings (user_id, mod_id, reason, timestamp) VALUES (?, ?, ?, ?)",
                  (str(member.id), str(ctx.author.id), reason, time.time()))
        warning_id = c.lastrowid
        conn.commit()
        conn.close()
        
        await ctx.send(f"⚠️ {member.mention} has been warned. (Warning #{warning_id})\nReason: {reason}")
        
        # Log to log channel with formatted embed
        log_channel = await self.get_log_channel(ctx.guild)
        if log_channel:
            embed = discord.Embed(
                title="⚠️ WARNING",
                color=discord.Color.orange(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Punished User", value=f"{member.mention} ({member})", inline=False)
            embed.add_field(name="User ID", value=f"`{member.id}`", inline=True)
            embed.add_field(name="Punishment", value="Warning", inline=True)
            embed.add_field(name="Warning ID", value=f"#{warning_id}", inline=True)
            embed.add_field(name="Reason", value=reason, inline=False)
            embed.add_field(name="By", value=f"{ctx.author.mention} ({ctx.author})", inline=False)
            await log_channel.send(embed=embed)
        
        # Try to DM the user
        try:
            embed = discord.Embed(
                title=f"⚠️ You have been warned in {ctx.guild.name}",
                description=f"**Reason:** {reason}\n**Warning ID:** #{warning_id}",
                color=discord.Color.orange()
            )
            await member.send(embed=embed)
        except:
            pass

    # ===== WARNINGS COMMAND =====
    @commands.command(name='warnings')
    async def warnings(self, ctx, member: discord.Member = None):
        """Check warnings for a member"""
        if await self.check_duplicate(ctx):
            return
            
        if member is None:
            member = ctx.author
        
        conn = sqlite3.connect(os.path.join(DB_FOLDER, "asaiya_bot.db"))
        c = conn.cursor()
        c.execute("SELECT id, reason, timestamp, mod_id FROM warnings WHERE user_id = ?",
                  (str(member.id),))
        results = c.fetchall()
        conn.close()
        
        if not results:
            await ctx.send(f"✅ {member.mention} has no warnings.")
            return
        
        embed = discord.Embed(
            title=f"⚠️ Warnings for {member.display_name}",
            color=discord.Color.orange()
        )
        
        for i, (warning_id, reason, timestamp, mod_id) in enumerate(results, 1):
            mod = ctx.guild.get_member(int(mod_id))
            mod_name = mod.mention if mod else f"<@{mod_id}>"
            time_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
            embed.add_field(
                name=f"Warning #{warning_id}",
                value=f"**Reason:** {reason}\n**Mod:** {mod_name}\n**Date:** {time_str}",
                inline=False
            )
        
        await ctx.send(embed=embed)

    # ===== TIMEOUT COMMAND =====
    @commands.command(name='timeout')
    @commands.has_permissions(moderate_members=True)
    async def timeout(self, ctx, member: discord.Member, minutes: int, *, reason: str = "No reason provided"):
        """Timeout a member"""
        if await self.check_duplicate(ctx):
            return
            
        if member == ctx.author:
            await ctx.send("❌ You cannot timeout yourself!")
            return
        if member.top_role >= ctx.author.top_role:
            await ctx.send("❌ You cannot timeout someone with higher or equal roles!")
            return
        
        try:
            await member.timeout(timedelta(minutes=minutes), reason=f"Timeout by {ctx.author.name}: {reason}")
            await ctx.send(f"⏰ {member.mention} has been timed out for {minutes} minutes. Reason: {reason}")
            
            # Log to log channel with formatted embed
            log_channel = await self.get_log_channel(ctx.guild)
            if log_channel:
                embed = discord.Embed(
                    title="⏰ TIMEOUT",
                    color=discord.Color.orange(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Punished User", value=f"{member.mention} ({member})", inline=False)
                embed.add_field(name="User ID", value=f"`{member.id}`", inline=True)
                embed.add_field(name="Punishment", value="Timeout", inline=True)
                embed.add_field(name="Duration", value=f"{minutes} minute(s)", inline=True)
                embed.add_field(name="Reason", value=reason, inline=False)
                embed.add_field(name="By", value=f"{ctx.author.mention} ({ctx.author})", inline=False)
                await log_channel.send(embed=embed)
                
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to timeout that user!")
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")

    # ===== UNTIMEOUT COMMAND =====
    @commands.command(name='untimeout')
    @commands.has_permissions(moderate_members=True)
    async def untimeout(self, ctx, member: discord.Member):
        """Remove timeout from a member"""
        if await self.check_duplicate(ctx):
            return
            
        try:
            await member.timeout(None, reason=f"Timeout removed by {ctx.author.name}")
            await ctx.send(f"✅ Timeout removed from {member.mention}")
            
            # Log to log channel with formatted embed
            log_channel = await self.get_log_channel(ctx.guild)
            if log_channel:
                embed = discord.Embed(
                    title="✅ UNTIMEOUT",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="User", value=f"{member.mention} ({member})", inline=False)
                embed.add_field(name="User ID", value=f"`{member.id}`", inline=True)
                embed.add_field(name="Action", value="Timeout Removed", inline=True)
                embed.add_field(name="By", value=f"{ctx.author.mention} ({ctx.author})", inline=False)
                await log_channel.send(embed=embed)
                
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to remove timeout from that user!")
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")

    # ===== NICK COMMAND =====
    @commands.command(name='nick')
    @commands.has_permissions(manage_nicknames=True)
    async def nick(self, ctx, member: discord.Member, *, nickname: str):
        """Set a user's nickname in this server. Usage: !nick @user new nickname"""
        if await self.check_duplicate(ctx):
            return

        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            await ctx.send("❌ You cannot change the nickname of someone with a higher or equal role!")
            return

        try:
            old_nick = member.display_name
            await member.edit(nick=nickname, reason=f"Nickname changed by {ctx.author}")
            await ctx.send(f"✅ Changed {member.mention}'s nickname to **{nickname}**.")

            await self.log_punishment(ctx.guild, member, "Nickname Change", f"Old: {old_nick} → New: {nickname}", ctx.author)

        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to change that user's nickname!")
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")

    # ===== UPDATE COMMAND =====
    @commands.command(name='update')
    async def update(self, ctx, *, message: str):
        """Broadcast an update message to all servers with #asaiya-bot. AsaiyaBot role + owner server only."""
        OWNER_SERVER_ID = 1484265140215087235

        # Must be in the owner server
        if ctx.guild.id != OWNER_SERVER_ID:
            await ctx.send("❌ This command can only be used in the owner server.")
            return

        # Must have the AsaiyaBot role
        asaiya_role = discord.utils.get(ctx.guild.roles, name="AsaiyaBot")
        if not asaiya_role or asaiya_role not in ctx.author.roles:
            await ctx.send("❌ You need the **AsaiyaBot** role to use this command.")
            return

        embed = discord.Embed(
            title="📢 AsaiyaBot Update",
            description=message,
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="AsaiyaBot • Official Update")

        success = 0
        failed = 0
        skipped = 0

        status_msg = await ctx.send(f"📡 Broadcasting to {len(self.bot.guilds)} servers...")

        for guild in self.bot.guilds:
            channel = discord.utils.get(guild.text_channels, name="asaiya-bot")
            if not channel:
                skipped += 1
                continue
            try:
                await channel.send(embed=embed)
                success += 1
                await asyncio.sleep(1.5)
            except Exception as e:
                print(f"⚠️ Could not send update to {guild.name}: {e}")
                failed += 1

        result = discord.Embed(
            title="✅ Broadcast Complete",
            color=discord.Color.green()
        )
        result.add_field(name="✅ Sent", value=str(success), inline=True)
        result.add_field(name="⏭️ Skipped (no channel)", value=str(skipped), inline=True)
        result.add_field(name="❌ Failed", value=str(failed), inline=True)
        await status_msg.edit(content=None, embed=result)

    # ===== SLOWMODE COMMAND =====
    @commands.command(name='slowmode')
    @commands.has_permissions(manage_channels=True)
    async def slowmode(self, ctx, seconds: int):
        """Set slowmode in the current channel"""
        if await self.check_duplicate(ctx):
            return
            
        if seconds < 0 or seconds > 21600:
            await ctx.send("❌ Slowmode must be between 0 and 21600 seconds (6 hours).")
            return
        
        try:
            await ctx.channel.edit(slowmode_delay=seconds)
            await ctx.send(f"✅ Slowmode set to {seconds} seconds in this channel.")
            
            # Log to log channel
            log_channel = await self.get_log_channel(ctx.guild)
            if log_channel:
                embed = discord.Embed(
                    title="⏱️ SLOWMODE",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Channel", value=ctx.channel.mention, inline=False)
                embed.add_field(name="Slowmode", value=f"{seconds} seconds", inline=True)
                embed.add_field(name="By", value=f"{ctx.author.mention} ({ctx.author})", inline=True)
                await log_channel.send(embed=embed)
                
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")

    # ===== LOCK COMMAND =====
    @commands.command(name='lock')
    @commands.has_permissions(manage_channels=True)
    async def lock(self, ctx, channel: discord.TextChannel = None):
        """Lock a channel so members cannot send messages"""
        if await self.check_duplicate(ctx):
            return
            
        target = channel or ctx.channel
        everyone = ctx.guild.default_role
        
        try:
            # Check if already locked
            current_overwrite = target.overwrites_for(everyone)
            if current_overwrite.send_messages is False:
                await ctx.send(f"🔒 {target.mention} is already locked.")
                return
            
            overwrite = target.overwrites_for(everyone)
            overwrite.send_messages = False
            await target.set_permissions(everyone, overwrite=overwrite)
            
            embed = discord.Embed(
                title="🔒 Channel Locked",
                description=f"{target.mention} has been locked. Members cannot send messages.",
                color=discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text=f"Locked by {ctx.author}")
            await target.send(embed=embed)
            
            if target != ctx.channel:
                await ctx.send(f"✅ {target.mention} has been locked.")
            
            # Log to log channel
            log_channel = await self.get_log_channel(ctx.guild)
            if log_channel:
                embed = discord.Embed(
                    title="🔒 LOCK",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Channel", value=target.mention, inline=False)
                embed.add_field(name="Action", value="Locked", inline=True)
                embed.add_field(name="By", value=f"{ctx.author.mention} ({ctx.author})", inline=True)
                await log_channel.send(embed=embed)
                
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to lock that channel.")
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")

    # ===== UNLOCK COMMAND =====
    @commands.command(name='unlock')
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx, channel: discord.TextChannel = None):
        """Unlock a previously locked channel"""
        if await self.check_duplicate(ctx):
            return
            
        target = channel or ctx.channel
        everyone = ctx.guild.default_role
        
        try:
            # Check if already unlocked
            current_overwrite = target.overwrites_for(everyone)
            if current_overwrite.send_messages is not False:
                await ctx.send(f"🔓 {target.mention} is not locked.")
                return
            
            overwrite = target.overwrites_for(everyone)
            overwrite.send_messages = None  # Reset to default
            await target.set_permissions(everyone, overwrite=overwrite)
            
            embed = discord.Embed(
                title="🔓 Channel Unlocked",
                description=f"{target.mention} has been unlocked. Members can send messages again.",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text=f"Unlocked by {ctx.author}")
            await target.send(embed=embed)
            
            if target != ctx.channel:
                await ctx.send(f"✅ {target.mention} has been unlocked.")
            
            # Log to log channel
            log_channel = await self.get_log_channel(ctx.guild)
            if log_channel:
                embed = discord.Embed(
                    title="🔓 UNLOCK",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Channel", value=target.mention, inline=False)
                embed.add_field(name="Action", value="Unlocked", inline=True)
                embed.add_field(name="By", value=f"{ctx.author.mention} ({ctx.author})", inline=True)
                await log_channel.send(embed=embed)
                
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to unlock that channel.")
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")

    # ===== SLOCK COMMAND (Lock All Channels) =====
    @commands.command(name='slock')
    @commands.has_permissions(administrator=True)
    async def slock(self, ctx):
        """Lock every channel in the server"""
        if await self.check_duplicate(ctx):
            return
            
        guild = ctx.guild
        everyone = guild.default_role
        bot_member = guild.get_member(self.bot.user.id)

        locked = []
        skipped = []
        failed = []

        status_msg = await ctx.send("🔒 Locking server... please wait.")

        for channel in guild.text_channels:
            # Skip channels where send_messages is already False
            overwrite = channel.overwrites_for(everyone)
            if overwrite.send_messages is False:
                skipped.append(channel.name)
                continue

            # Skip if bot doesn't have permission
            if not channel.permissions_for(bot_member).manage_channels:
                skipped.append(channel.name)
                continue

            try:
                overwrite.send_messages = False
                await channel.edit(overwrites={everyone: overwrite})
                locked.append(channel)
                await asyncio.sleep(0.2)  # Small delay to avoid rate limits
            except Exception:
                failed.append(channel.name)

        # Send lock notice in each locked channel
        for channel in locked:
            try:
                embed = discord.Embed(
                    title="🔒 Server Locked",
                    description="This server has been locked by a moderator.",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                embed.set_footer(text=f"Locked by {ctx.author}")
                await channel.send(embed=embed)
            except Exception:
                pass

        await status_msg.delete()

        summary = discord.Embed(
            title="🔒 Server Lock Complete",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        summary.add_field(name="Locked", value=f"{len(locked)} channel(s)", inline=True)
        summary.add_field(name="Skipped", value=f"{len(skipped)} channel(s)", inline=True)
        if failed:
            summary.add_field(name="Failed", value=", ".join(failed), inline=False)
        summary.set_footer(text=f"Use !sunlock to unlock | Locked by {ctx.author}")
        await ctx.send(embed=summary)

        # Log to log channel
        log_channel = await self.get_log_channel(guild)
        if log_channel:
            embed = discord.Embed(
                title="🔒 SERVER LOCK",
                color=discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Locked", value=f"{len(locked)} channel(s)", inline=True)
            embed.add_field(name="Skipped", value=f"{len(skipped)} channel(s)", inline=True)
            if failed:
                embed.add_field(name="Failed", value=", ".join(failed), inline=True)
            embed.add_field(name="By", value=f"{ctx.author.mention} ({ctx.author})", inline=False)
            await log_channel.send(embed=embed)

    # ===== SUNLOCK COMMAND (Unlock All Channels) =====
    @commands.command(name='sunlock')
    @commands.has_permissions(administrator=True)
    async def sunlock(self, ctx):
        """Unlock every channel in the server"""
        if await self.check_duplicate(ctx):
            return
            
        guild = ctx.guild
        everyone = guild.default_role
        bot_member = guild.get_member(self.bot.user.id)

        unlocked = []
        skipped = []
        failed = []

        status_msg = await ctx.send("🔓 Unlocking server... please wait.")

        for channel in guild.text_channels:
            overwrite = channel.overwrites_for(everyone)
            if overwrite.send_messages is not False:
                skipped.append(channel.name)
                continue

            if not channel.permissions_for(bot_member).manage_channels:
                skipped.append(channel.name)
                continue

            try:
                overwrite.send_messages = None  # Reset to default
                await channel.edit(overwrites={everyone: overwrite})
                unlocked.append(channel)
                await asyncio.sleep(0.2)
            except Exception:
                failed.append(channel.name)

        # Send unlock notice in each channel
        for channel in unlocked:
            try:
                embed = discord.Embed(
                    title="🔓 Server Unlocked",
                    description="This server has been unlocked. You may chat again.",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                embed.set_footer(text=f"Unlocked by {ctx.author}")
                await channel.send(embed=embed)
            except Exception:
                pass

        await status_msg.delete()

        summary = discord.Embed(
            title="🔓 Server Unlock Complete",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        summary.add_field(name="Unlocked", value=f"{len(unlocked)} channel(s)", inline=True)
        summary.add_field(name="Skipped", value=f"{len(skipped)} channel(s)", inline=True)
        if failed:
            summary.add_field(name="Failed", value=", ".join(failed), inline=False)
        summary.set_footer(text=f"Unlocked by {ctx.author}")
        await ctx.send(embed=summary)

        # Log to log channel
        log_channel = await self.get_log_channel(guild)
        if log_channel:
            embed = discord.Embed(
                title="🔓 SERVER UNLOCK",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Unlocked", value=f"{len(unlocked)} channel(s)", inline=True)
            embed.add_field(name="Skipped", value=f"{len(skipped)} channel(s)", inline=True)
            if failed:
                embed.add_field(name="Failed", value=", ".join(failed), inline=True)
            embed.add_field(name="By", value=f"{ctx.author.mention} ({ctx.author})", inline=False)
            await log_channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
