import discord
from discord.ext import commands
import sqlite3
import time
import asyncio
import os
from datetime import datetime

# ===== CONFIGURATION =====
DB_FOLDER = r"C:\Users\Kelly\Desktop\discord database"
MAIN_DB_PATH = os.path.join(DB_FOLDER, "asaiya_bot.db")

PROTECTED_CHANNELS_TABLE = "protected_channels"
MESSAGE_BACKUP_TABLE = "message_backup"
DELETED_CHANNELS_TABLE = "deleted_channels"


class Protection(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ===== HELPERS =====

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

    # ===== COMMANDS =====

    @commands.command(name='sprotect')
    @commands.has_permissions(administrator=True)
    async def sprotect(self, ctx):
        """Protect every channel in the server (channel-only protection)"""
        guild = ctx.guild
        conn = self.get_cached_connection(guild.id)
        c = conn.cursor()

        protected_count = 0
        upgraded_count = 0

        for channel in guild.text_channels:
            c.execute(f"SELECT protect_type FROM {PROTECTED_CHANNELS_TABLE} WHERE channel_id = ?",
                      (str(channel.id),))
            existing = c.fetchone()

            if existing:
                c.execute(f"UPDATE {PROTECTED_CHANNELS_TABLE} SET protect_type = 'channel' WHERE channel_id = ?",
                          (str(channel.id),))
                upgraded_count += 1
            else:
                c.execute(f"""INSERT INTO {PROTECTED_CHANNELS_TABLE}
                             (channel_id, channel_name, protected_since, protect_type)
                             VALUES (?, ?, ?, ?)""",
                          (str(channel.id), channel.name, time.time(), 'channel'))
                protected_count += 1

        conn.commit()

        msg = f"✅ **Server Protected!** {protected_count} new channel(s) protected"
        if upgraded_count:
            msg += f", {upgraded_count} channel(s) updated to channel-only protection"
        msg += " (no message backup)."
        await ctx.send(msg)

        log_channel = await self.get_log_channel(guild)
        if log_channel:
            await log_channel.send(f"🛡️ Server-wide protection activated by {ctx.author.mention}")

    @commands.command(name='fprotect')
    @commands.has_permissions(administrator=True)
    async def fprotect(self, ctx, channel: discord.TextChannel):
        """Full protection — protects the channel AND backs up messages"""
        conn = self.get_cached_connection(ctx.guild.id)
        c = conn.cursor()

        c.execute(f"SELECT protect_type FROM {PROTECTED_CHANNELS_TABLE} WHERE channel_id = ?",
                  (str(channel.id),))
        existing = c.fetchone()

        if existing:
            if existing[0] == 'full':
                await ctx.send(f"ℹ️ {channel.mention} is already fully protected.")
                return
            c.execute(f"UPDATE {PROTECTED_CHANNELS_TABLE} SET protect_type = 'full' WHERE channel_id = ?",
                      (str(channel.id),))
            conn.commit()
            await ctx.send(f"✅ {channel.mention} protection upgraded to **full** (channel + message backup).")
        else:
            c.execute(f"""INSERT INTO {PROTECTED_CHANNELS_TABLE}
                         (channel_id, channel_name, protected_since, protect_type)
                         VALUES (?, ?, ?, ?)""",
                      (str(channel.id), channel.name, time.time(), 'full'))
            conn.commit()
            await ctx.send(f"✅ {channel.mention} is now **fully protected** (channel + message backup).")

        log_channel = await self.get_log_channel(ctx.guild)
        if log_channel:
            await log_channel.send(f"🛡️ {channel.mention} fully protected by {ctx.author.mention}")

    @commands.command(name='protect')
    @commands.has_permissions(administrator=True)
    async def protect(self, ctx, channel: discord.TextChannel):
        """Channel protection — protects the channel only (no message backup)"""
        conn = self.get_cached_connection(ctx.guild.id)
        c = conn.cursor()

        c.execute(f"SELECT protect_type FROM {PROTECTED_CHANNELS_TABLE} WHERE channel_id = ?",
                  (str(channel.id),))
        existing = c.fetchone()

        if existing:
            if existing[0] == 'channel':
                await ctx.send(f"ℹ️ {channel.mention} is already channel-protected.")
                return
            c.execute(f"UPDATE {PROTECTED_CHANNELS_TABLE} SET protect_type = 'channel' WHERE channel_id = ?",
                      (str(channel.id),))
            conn.commit()
            await ctx.send(f"✅ {channel.mention} protection changed to **channel only** (no message backup).")
        else:
            c.execute(f"""INSERT INTO {PROTECTED_CHANNELS_TABLE}
                         (channel_id, channel_name, protected_since, protect_type)
                         VALUES (?, ?, ?, ?)""",
                      (str(channel.id), channel.name, time.time(), 'channel'))
            conn.commit()
            await ctx.send(f"✅ {channel.mention} is now **channel protected** (no message backup).")

        log_channel = await self.get_log_channel(ctx.guild)
        if log_channel:
            await log_channel.send(f"🛡️ {channel.mention} channel-protected by {ctx.author.mention}")

    @commands.command(name='mprotect')
    @commands.has_permissions(administrator=True)
    async def mprotect(self, ctx, channel: discord.TextChannel):
        """Message protection — backs up messages only (channel won't be auto-restored)"""
        conn = self.get_cached_connection(ctx.guild.id)
        c = conn.cursor()

        c.execute(f"SELECT protect_type FROM {PROTECTED_CHANNELS_TABLE} WHERE channel_id = ?",
                  (str(channel.id),))
        existing = c.fetchone()

        if existing:
            if existing[0] == 'messages':
                await ctx.send(f"ℹ️ {channel.mention} is already message-protected.")
                return
            c.execute(f"UPDATE {PROTECTED_CHANNELS_TABLE} SET protect_type = 'messages' WHERE channel_id = ?",
                      (str(channel.id),))
            conn.commit()
            await ctx.send(f"✅ {channel.mention} protection changed to **messages only**.")
        else:
            c.execute(f"""INSERT INTO {PROTECTED_CHANNELS_TABLE}
                         (channel_id, channel_name, protected_since, protect_type)
                         VALUES (?, ?, ?, ?)""",
                      (str(channel.id), channel.name, time.time(), 'messages'))
            conn.commit()
            await ctx.send(f"✅ {channel.mention} is now **message protected** (messages backed up, channel won't be restored).")

        log_channel = await self.get_log_channel(ctx.guild)
        if log_channel:
            await log_channel.send(f"📝 {channel.mention} message-protected by {ctx.author.mention}")

    @commands.command(name='unprotect')
    @commands.has_permissions(administrator=True)
    async def unprotect(self, ctx, channel: discord.TextChannel):
        """Remove protection from a channel"""
        conn = self.get_cached_connection(ctx.guild.id)
        c = conn.cursor()

        c.execute(f"DELETE FROM {PROTECTED_CHANNELS_TABLE} WHERE channel_id = ?", (str(channel.id),))

        if c.rowcount > 0:
            c.execute(f"DELETE FROM {MESSAGE_BACKUP_TABLE} WHERE channel_id = ?", (str(channel.id),))
            conn.commit()
            await ctx.send(f"✅ {channel.mention} is no longer protected. Backups deleted.")

            log_channel = await self.get_log_channel(ctx.guild)
            if log_channel:
                await log_channel.send(f"🛡️ {channel.mention} unprotected by {ctx.author.mention}")
        else:
            await ctx.send(f"ℹ️ {channel.mention} was not protected.")

    @commands.command(name='protected')
    async def protected(self, ctx):
        """List all protected channels in this server"""
        conn = self.get_cached_connection(ctx.guild.id)
        c = conn.cursor()
        c.execute(f"SELECT channel_name, protect_type, protected_since FROM {PROTECTED_CHANNELS_TABLE}")
        results = c.fetchall()

        if not results:
            await ctx.send("📭 No protected channels in this server.")
            return

        embed = discord.Embed(
            title="🛡️ Protected Channels",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )

        type_emojis = {
            'full': '🛡️💬',
            'channel': '🛡️',
            'messages': '💬'
        }
        type_names = {
            'full': 'Full (Channel + Messages)',
            'channel': 'Channel Only',
            'messages': 'Messages Only'
        }

        for channel_name, protect_type, since in results:
            time_str = datetime.fromtimestamp(since).strftime("%Y-%m-%d")
            emoji = type_emojis.get(protect_type, '🛡️')
            type_name = type_names.get(protect_type, protect_type)
            embed.add_field(
                name=f"{emoji} #{channel_name}",
                value=f"Type: {type_name}\nSince: {time_str}",
                inline=True
            )

        await ctx.send(embed=embed)

    @commands.command(name='recover')
    @commands.has_permissions(administrator=True)
    async def recover(self, ctx, target: str = None):
        """Recover deleted channels. Usage: !recover | !recover #name | !recover all"""
        conn = self.get_cached_connection(ctx.guild.id)
        c = conn.cursor()

        # No target — list recoverable channels
        if target is None:
            c.execute(f"SELECT channel_name, category_name, deleted_at FROM {DELETED_CHANNELS_TABLE} ORDER BY deleted_at DESC")
            results = c.fetchall()

            if not results:
                await ctx.send("📭 No deleted channels available for recovery.")
                return

            embed = discord.Embed(
                title="🔄 Recoverable Channels",
                description="Use `!recover #channelname` or `!recover all`.",
                color=discord.Color.blue()
            )
            for channel_name, category_name, deleted_at in results[:10]:
                time_str = datetime.fromtimestamp(deleted_at).strftime("%Y-%m-%d %H:%M")
                embed.add_field(
                    name=f"#{channel_name}",
                    value=f"Category: {category_name}\nDeleted: {time_str}",
                    inline=True
                )
            await ctx.send(embed=embed)
            return

        # Recover all
        if target.lower() == 'all':
            c.execute(f"SELECT channel_name, category_name FROM {DELETED_CHANNELS_TABLE}")
            channels = c.fetchall()

            if not channels:
                await ctx.send("📭 No channels to recover.")
                return

            await ctx.send(f"🔄 Attempting to recover {len(channels)} channel(s)...")
            recovered = 0

            for channel_name, category_name in channels:
                try:
                    category = None
                    if category_name != "None":
                        category = discord.utils.get(ctx.guild.categories, name=category_name)
                        if not category:
                            category = await ctx.guild.create_category(category_name)

                    await ctx.guild.create_text_channel(
                        channel_name,
                        category=category,
                        reason=f"Channel recovered by {ctx.author.name}"
                    )
                    c.execute(f"DELETE FROM {DELETED_CHANNELS_TABLE} WHERE channel_name = ?", (channel_name,))
                    recovered += 1
                except Exception as e:
                    await ctx.send(f"❌ Failed to recover #{channel_name}: {str(e)}")

            conn.commit()
            await ctx.send(f"✅ Recovered {recovered} channel(s).")
            return

        # Recover specific channel
        channel_name = target.lstrip('#')
        c.execute(f"SELECT category_name FROM {DELETED_CHANNELS_TABLE} WHERE channel_name = ?",
                  (channel_name,))
        result = c.fetchone()

        if not result:
            await ctx.send(f"❌ Channel #{channel_name} not found in recoverable list.")
            return

        category_name = result[0]

        try:
            category = None
            if category_name != "None":
                category = discord.utils.get(ctx.guild.categories, name=category_name)
                if not category:
                    category = await ctx.guild.create_category(category_name)

            await ctx.guild.create_text_channel(
                channel_name,
                category=category,
                reason=f"Channel recovered by {ctx.author.name}"
            )
            c.execute(f"DELETE FROM {DELETED_CHANNELS_TABLE} WHERE channel_name = ?", (channel_name,))
            conn.commit()
            await ctx.send(f"✅ Channel #{channel_name} has been recovered!")
        except Exception as e:
            await ctx.send(f"❌ Failed to recover channel: {str(e)}")

    @commands.command(name='restore')
    @commands.has_permissions(administrator=True)
    async def restore(self, ctx, channel: discord.TextChannel, limit: int = 20):
        """Manually restore backed-up messages into a channel"""
        conn = self.get_cached_connection(ctx.guild.id)
        c = conn.cursor()
        c.execute(f"""SELECT author_name, content, timestamp FROM {MESSAGE_BACKUP_TABLE}
                     WHERE channel_name = ? ORDER BY timestamp ASC LIMIT ?""",
                  (channel.name, min(limit, 50)))
        messages = c.fetchall()

        if not messages:
            await ctx.send(f"📭 No backups found for #{channel.name}.")
            return

        await ctx.send(f"🔄 Restoring {len(messages)} message(s) to {channel.mention}...")

        for author_name, content, timestamp in messages:
            member = discord.utils.find(lambda m: m.name == author_name, ctx.guild.members)
            time_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")

            if member:
                await channel.send(f"📝 [{time_str}] {member.mention}: {content}")
            else:
                await channel.send(f"📝 [{time_str}] **[Unknown]**: {content}")

            await asyncio.sleep(1)

        await ctx.send(f"✅ Restored {len(messages)} message(s) to {channel.mention}.")


async def setup(bot):
    await bot.add_cog(Protection(bot))
