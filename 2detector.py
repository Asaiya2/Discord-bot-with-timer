import discord
from discord.ext import commands
import sqlite3
import os
import time
import asyncio
import re
from datetime import datetime

# ===== CONFIGURATION =====
DB_FOLDER = r"C:\Users\Kelly\Desktop\discord database"
MAIN_DB_PATH = os.path.join(DB_FOLDER, "asaiya_bot.db")

# Staff roles that bypass keyword detection
STAFF_ROLES = ["AsaiyaBot", "AsaiyaKick", "AsaiyaBan", "AsaiyaPass", "AsaiyaClear", "asaiya-support"]


class Detector(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.processed_messages = set()
        self.setup_database()
        print("✅ Detector cog initialized")

    # ── DATABASE SETUP ──────────────────────────────────────────────────────────

    def setup_database(self):
        """Create detector settings table if it doesn't exist"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            
            # Table for detector settings per server
            c.execute('''CREATE TABLE IF NOT EXISTS detector_settings
                         (guild_id TEXT PRIMARY KEY,
                          enabled INTEGER DEFAULT 1,
                          channel_id TEXT,
                          updated_at REAL)''')
            
            # Table for keyword triggers (simple keywords)
            c.execute('''CREATE TABLE IF NOT EXISTS detector_keywords
                         (guild_id TEXT,
                          keyword TEXT,
                          added_by TEXT,
                          added_at REAL,
                          PRIMARY KEY (guild_id, keyword))''')
            
            # Table for multiple-word triggers (phrases)
            c.execute('''CREATE TABLE IF NOT EXISTS detector_phrases
                         (guild_id TEXT,
                          phrase TEXT,
                          added_by TEXT,
                          added_at REAL,
                          PRIMARY KEY (guild_id, phrase))''')
            
            # Table for keyword statistics
            c.execute('''CREATE TABLE IF NOT EXISTS detector_stats
                         (guild_id TEXT,
                          keyword TEXT,
                          trigger_count INTEGER DEFAULT 0,
                          last_trigger REAL,
                          PRIMARY KEY (guild_id, keyword))''')
            
            conn.commit()
            conn.close()
            print("✅ Detector database initialized")
        except Exception as e:
            print(f"❌ Detector setup_database error: {e}")

    # ── HELPER METHODS ──────────────────────────────────────────────────────────

    def is_staff(self, member, guild_id):
        """Check if member has staff role"""
        if not isinstance(member, discord.Member):
            return False
        
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return False
        
        if member.guild != guild:
            member = guild.get_member(member.id)
            if not member:
                return False
        
        return any(role.name in STAFF_ROLES for role in member.roles)

    def is_detector_enabled(self, guild_id):
        """Check if detector is enabled for this server"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT enabled FROM detector_settings WHERE guild_id = ?", (str(guild_id),))
            row = c.fetchone()
            conn.close()
            return row[0] == 1 if row else True
        except:
            return True

    def get_detector_channel(self, guild_id):
        """Get the channel where detector should respond (None = same channel)"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT channel_id FROM detector_settings WHERE guild_id = ?", (str(guild_id),))
            row = c.fetchone()
            conn.close()
            return row[0] if row and row[0] else None
        except:
            return None

    def get_all_keywords(self, guild_id):
        """Get all simple keywords for a server"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT keyword FROM detector_keywords WHERE guild_id = ?", (str(guild_id),))
            keywords = [row[0].lower() for row in c.fetchall()]
            conn.close()
            return keywords
        except:
            return []

    def get_all_phrases(self, guild_id):
        """Get all phrases for a server"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT phrase FROM detector_phrases WHERE guild_id = ?", (str(guild_id),))
            phrases = [row[0].lower() for row in c.fetchall()]
            conn.close()
            return phrases
        except:
            return []

    def add_keyword(self, guild_id, keyword, added_by):
        """Add a keyword trigger"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO detector_keywords (guild_id, keyword, added_by, added_at) VALUES (?, ?, ?, ?)",
                      (str(guild_id), keyword.lower(), str(added_by), time.time()))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"❌ add_keyword error: {e}")
            return False

    def add_phrase(self, guild_id, phrase, added_by):
        """Add a phrase trigger"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO detector_phrases (guild_id, phrase, added_by, added_at) VALUES (?, ?, ?, ?)",
                      (str(guild_id), phrase.lower(), str(added_by), time.time()))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"❌ add_phrase error: {e}")
            return False

    def remove_keyword(self, guild_id, keyword):
        """Remove a keyword trigger"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM detector_keywords WHERE guild_id = ? AND keyword = ?",
                      (str(guild_id), keyword.lower()))
            conn.commit()
            conn.close()
            return True
        except:
            return False

    def remove_phrase(self, guild_id, phrase):
        """Remove a phrase trigger"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM detector_phrases WHERE guild_id = ? AND phrase = ?",
                      (str(guild_id), phrase.lower()))
            conn.commit()
            conn.close()
            return True
        except:
            return False

    def clear_all_keywords(self, guild_id):
        """Remove all keywords for a server"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM detector_keywords WHERE guild_id = ?", (str(guild_id),))
            c.execute("DELETE FROM detector_phrases WHERE guild_id = ?", (str(guild_id),))
            conn.commit()
            conn.close()
            return True
        except:
            return False

    def increment_stats(self, guild_id, keyword):
        """Increment trigger count for a keyword"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("INSERT INTO detector_stats (guild_id, keyword, trigger_count, last_trigger) VALUES (?, ?, 1, ?) "
                      "ON CONFLICT(guild_id, keyword) DO UPDATE SET trigger_count = trigger_count + 1, last_trigger = ?",
                      (str(guild_id), keyword.lower(), time.time(), time.time()))
            conn.commit()
            conn.close()
        except:
            pass

    def get_stats(self, guild_id, keyword=None):
        """Get trigger statistics"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            if keyword:
                c.execute("SELECT trigger_count, last_trigger FROM detector_stats WHERE guild_id = ? AND keyword = ?",
                          (str(guild_id), keyword.lower()))
                row = c.fetchone()
                conn.close()
                return row if row else (0, None)
            else:
                c.execute("SELECT keyword, trigger_count, last_trigger FROM detector_stats WHERE guild_id = ? ORDER BY trigger_count DESC",
                          (str(guild_id),))
                rows = c.fetchall()
                conn.close()
                return rows
        except:
            return [] if not keyword else (0, None)

    # ── CORE DETECTION LOGIC ────────────────────────────────────────────────────

    async def check_and_respond(self, message):
        """Check if message contains any triggers and respond"""
        
        # Ignore bots
        if message.author.bot:
            return
        
        # Only work in guilds
        if not message.guild:
            return
        
        guild_id = message.guild.id
        
        # Check if detector is enabled
        if not self.is_detector_enabled(guild_id):
            return
        
        # Check if user is staff (bypass)
        if self.is_staff(message.author, guild_id):
            return
        
        # Get message content
        content = message.content.lower().strip()
        if not content:
            return
        
        # Get all keywords and phrases from detector settings
        keywords = self.get_all_keywords(guild_id)
        phrases = self.get_all_phrases(guild_id)
        
        if not keywords and not phrases:
            return
        
        # Check for exact word matches (keywords)
        words = re.findall(r'\b\w+\b', content)
        matched_keywords = [word for word in words if word in keywords]
        
        # Check for phrases (multi-word)
        matched_phrases = [phrase for phrase in phrases if phrase in content]
        
        # Combine matches
        all_matches = matched_keywords + matched_phrases
        
        if not all_matches:
            return
        
        # Get the media vault cog
        media_vault = self.bot.get_cog('MediaVault')
        if not media_vault:
            print("⚠️ MediaVault cog not found")
            return
        
        # Check each match for associated media in the vault
        for match in all_matches:
            # Get a random media with this keyword from the vault
            media = media_vault.get_random_media_by_keyword(match)
            
            if media:
                # media = (id, media_type, url, saved_by, saved_by_id, saved_at, vault_msg_id, keyword)
                media_id = media[0]
                media_type = media[1]
                media_url = media[2]
                saved_by = media[3]
                
                # Count how many media have this keyword
                all_with_keyword = media_vault.get_all_media_by_keyword(match)
                count = len(all_with_keyword)
                
                # Increment statistics
                self.increment_stats(guild_id, match)
                
                # Determine where to send response
                response_channel = message.channel
                detector_channel_id = self.get_detector_channel(guild_id)
                if detector_channel_id:
                    channel = message.guild.get_channel(int(detector_channel_id))
                    if channel:
                        response_channel = channel
                
                # Send the media
                try:
                    if media_type == "gif":
                        # Send just the URL for GIFs (auto-play)
                        await response_channel.send(media_url)
                        # Optional: add a note if multiple exist
                        if count > 1:
                            await response_channel.send(f"*(Random from {count} media with keyword `{match}`)*", delete_after=5)
                    else:
                        # For images, send as file to avoid cropping
                        import aiohttp
                        import io
                        try:
                            async with aiohttp.ClientSession() as session:
                                async with session.get(media_url) as resp:
                                    if resp.status == 200:
                                        data = await resp.read()
                                        filename = media_url.split("/")[-1].split("?")[0]
                                        if not filename or '.' not in filename:
                                            filename = f"image_{media_id}.png"
                                        file = discord.File(fp=io.BytesIO(data), filename=filename)
                                        await response_channel.send(file=file)
                                        if count > 1:
                                            await response_channel.send(f"*(Random from {count} media with keyword `{match}`)*", delete_after=5)
                                    else:
                                        await response_channel.send(media_url)
                        except:
                            await response_channel.send(media_url)
                    
                    # Add a reaction to the original message
                    try:
                        await message.add_reaction("🔍")
                    except:
                        pass
                    
                    # Only respond to the first match
                    break
                    
                except Exception as e:
                    print(f"❌ Error sending media for keyword '{match}': {e}")

    # ── EVENT LISTENER ──────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for messages and check for triggers"""
        # Anti-spam: ignore if we've seen this message recently
        msg_id = message.id
        
        # Clean old processed messages every 500 messages
        if len(self.processed_messages) > 500:
            old_count = len(self.processed_messages)
            self.processed_messages = set()
            print(f"🧹 Cleaned {old_count} processed message IDs")
        
        # Process if not recently processed
        if msg_id not in self.processed_messages:
            self.processed_messages.add(msg_id)
            await self.check_and_respond(message)

    # ════════════════════════════════════════════════════════════════════════════
    # COMMANDS
    # ════════════════════════════════════════════════════════════════════════════

    @commands.group(name="detect", invoke_without_command=True)
    async def detect(self, ctx):
        """Detector system - keyword/phrase triggered responses"""
        embed = discord.Embed(
            title="🔍 Detector System",
            description="Automatically respond to keywords and phrases with saved media",
            color=discord.Color.blurple()
        )
        embed.add_field(name="Commands", value="""
        `!detect add <keyword>` - Add a keyword trigger
        `!detect addphrase <phrase>` - Add a phrase trigger (multiple words)
        `!detect remove <keyword>` - Remove a keyword trigger
        `!detect removephrase <phrase>` - Remove a phrase trigger
        `!detect list` - List all triggers
        `!detect clear` - Remove all triggers
        `!detect on` - Enable detector
        `!detect off` - Disable detector
        `!detect channel #channel` - Set response channel (or none for same channel)
        `!detect stats` - Show trigger statistics
        """, inline=False)
        embed.set_footer(text="Staff only commands | Keywords match exact words only")
        await ctx.send(embed=embed)

    @detect.command(name="add")
    @commands.has_permissions(administrator=True)
    async def detect_add(self, ctx, *, keyword: str):
        """Add a keyword trigger (exact word match only)"""
        if not keyword:
            await ctx.send("❌ Please provide a keyword. Example: `!detect add hello`")
            return
        
        # Check if media exists with this keyword in vault
        media_vault = self.bot.get_cog('MediaVault')
        if not media_vault:
            await ctx.send("❌ MediaVault cog not found")
            return
        
        media = media_vault.get_random_media_by_keyword(keyword)
        if not media:
            await ctx.send(f"❌ No media found with keyword `{keyword}`. Use `!save {keyword}` (replying to media) first.")
            return
        
        # Count how many media have this keyword
        all_media = media_vault.get_all_media_by_keyword(keyword)
        
        if self.add_keyword(ctx.guild.id, keyword, ctx.author.id):
            embed = discord.Embed(
                title="✅ Keyword Added",
                description=f"`{keyword}` will now trigger its associated media.",
                color=discord.Color.green()
            )
            embed.add_field(name="Associated Media", value=f"#{media[0]} ({media[1]})", inline=True)
            if len(all_media) > 1:
                embed.add_field(name="Note", value=f"⚠️ {len(all_media)} media share this keyword. A random one will be sent each time.", inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Failed to add keyword.")

    @detect.command(name="addphrase")
    @commands.has_permissions(administrator=True)
    async def detect_addphrase(self, ctx, *, phrase: str):
        """Add a phrase trigger (multiple words, partial match)"""
        if not phrase:
            await ctx.send("❌ Please provide a phrase. Example: `!detect addphrase hello there`")
            return
        
        # Check if media exists with this phrase as keyword in vault
        media_vault = self.bot.get_cog('MediaVault')
        if not media_vault:
            await ctx.send("❌ MediaVault cog not found")
            return
        
        media = media_vault.get_random_media_by_keyword(phrase)
        if not media:
            await ctx.send(f"❌ No media found with keyword `{phrase}`. Use `!save {phrase}` (replying to media) first.")
            return
        
        # Count how many media have this keyword
        all_media = media_vault.get_all_media_by_keyword(phrase)
        
        if self.add_phrase(ctx.guild.id, phrase, ctx.author.id):
            embed = discord.Embed(
                title="✅ Phrase Added",
                description=f"`{phrase}` will now trigger its associated media.",
                color=discord.Color.green()
            )
            embed.add_field(name="Associated Media", value=f"#{media[0]} ({media[1]})", inline=True)
            if len(all_media) > 1:
                embed.add_field(name="Note", value=f"⚠️ {len(all_media)} media share this keyword. A random one will be sent each time.", inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Failed to add phrase.")

    @detect.command(name="remove")
    @commands.has_permissions(administrator=True)
    async def detect_remove(self, ctx, *, keyword: str):
        """Remove a keyword trigger"""
        if self.remove_keyword(ctx.guild.id, keyword):
            await ctx.send(f"✅ Removed keyword trigger: `{keyword}`")
        else:
            await ctx.send(f"❌ Keyword `{keyword}` not found or could not be removed.")

    @detect.command(name="removephrase")
    @commands.has_permissions(administrator=True)
    async def detect_removephrase(self, ctx, *, phrase: str):
        """Remove a phrase trigger"""
        if self.remove_phrase(ctx.guild.id, phrase):
            await ctx.send(f"✅ Removed phrase trigger: `{phrase}`")
        else:
            await ctx.send(f"❌ Phrase `{phrase}` not found or could not be removed.")

    @detect.command(name="list")
    @commands.has_permissions(administrator=True)
    async def detect_list(self, ctx):
        """List all keyword and phrase triggers"""
        keywords = self.get_all_keywords(ctx.guild.id)
        phrases = self.get_all_phrases(ctx.guild.id)
        
        if not keywords and not phrases:
            await ctx.send("📭 No triggers set up for this server.")
            return
        
        embed = discord.Embed(
            title=f"🔍 Detector Triggers - {ctx.guild.name}",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow()
        )
        
        if keywords:
            embed.add_field(
                name=f"📌 Keywords ({len(keywords)})",
                value="`" + "`, `".join(keywords) + "`" if keywords else "None",
                inline=False
            )
        
        if phrases:
            embed.add_field(
                name=f"💬 Phrases ({len(phrases)})",
                value="`" + "`, `".join(phrases) + "`" if phrases else "None",
                inline=False
            )
        
        # Show response channel
        channel_id = self.get_detector_channel(ctx.guild.id)
        if channel_id:
            channel = ctx.guild.get_channel(int(channel_id))
            embed.add_field(name="📢 Response Channel", value=channel.mention if channel else "Unknown", inline=False)
        else:
            embed.add_field(name="📢 Response Channel", value="Same channel as trigger", inline=False)
        
        # Show enabled status
        enabled = self.is_detector_enabled(ctx.guild.id)
        embed.add_field(name="Status", value="✅ Enabled" if enabled else "❌ Disabled", inline=False)
        
        await ctx.send(embed=embed)

    @detect.command(name="clear")
    @commands.has_permissions(administrator=True)
    async def detect_clear(self, ctx):
        """Remove ALL triggers for this server"""
        confirm_msg = await ctx.send("⚠️ Are you sure you want to remove ALL triggers? Reply with `yes` to confirm.")
        
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() == 'yes'
        
        try:
            await self.bot.wait_for('message', timeout=30.0, check=check)
            if self.clear_all_keywords(ctx.guild.id):
                await ctx.send("✅ All triggers have been cleared.")
            else:
                await ctx.send("❌ Failed to clear triggers.")
        except asyncio.TimeoutError:
            await ctx.send("⏰ Cancelled - no confirmation received.")
        
        await confirm_msg.delete()

    @detect.command(name="on")
    @commands.has_permissions(administrator=True)
    async def detect_on(self, ctx):
        """Enable detector for this server"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO detector_settings (guild_id, enabled, updated_at) VALUES (?, 1, ?)",
                      (str(ctx.guild.id), time.time()))
            conn.commit()
            conn.close()
            await ctx.send("✅ Detector system **ENABLED** for this server.")
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

    @detect.command(name="off")
    @commands.has_permissions(administrator=True)
    async def detect_off(self, ctx):
        """Disable detector for this server"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO detector_settings (guild_id, enabled, updated_at) VALUES (?, 0, ?)",
                      (str(ctx.guild.id), time.time()))
            conn.commit()
            conn.close()
            await ctx.send("✅ Detector system **DISABLED** for this server.")
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

    @detect.command(name="channel")
    @commands.has_permissions(administrator=True)
    async def detect_channel(self, ctx, channel: discord.TextChannel = None):
        """Set the channel where detector responses go (or omit for same channel)"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            channel_id = str(channel.id) if channel else None
            c.execute("INSERT OR REPLACE INTO detector_settings (guild_id, channel_id, updated_at) VALUES (?, ?, ?)",
                      (str(ctx.guild.id), channel_id, time.time()))
            conn.commit()
            conn.close()
            
            if channel:
                await ctx.send(f"✅ Detector responses will be sent to {channel.mention}")
            else:
                await ctx.send("✅ Detector responses will be sent to the **same channel** where the trigger was detected.")
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

    @detect.command(name="stats")
    @commands.has_permissions(administrator=True)
    async def detect_stats(self, ctx, *, keyword: str = None):
        """Show trigger statistics for a keyword or all"""
        if keyword:
            count, last = self.get_stats(ctx.guild.id, keyword)
            if count > 0:
                last_time = datetime.fromtimestamp(last).strftime("%Y-%m-%d %H:%M") if last else "Never"
                embed = discord.Embed(
                    title=f"📊 Statistics for `{keyword}`",
                    color=discord.Color.blurple()
                )
                embed.add_field(name="Times Triggered", value=str(count), inline=True)
                embed.add_field(name="Last Trigger", value=last_time, inline=True)
                await ctx.send(embed=embed)
            else:
                await ctx.send(f"📭 No statistics found for `{keyword}`.")
        else:
            stats = self.get_stats(ctx.guild.id)
            if not stats:
                await ctx.send("📭 No trigger statistics available yet.")
                return
            
            embed = discord.Embed(
                title=f"📊 Detector Statistics - {ctx.guild.name}",
                color=discord.Color.blurple(),
                timestamp=datetime.utcnow()
            )
            
            stats_text = ""
            for kw, count, last in stats[:20]:
                stats_text += f"`{kw}`: {count} time(s)\n"
            
            embed.add_field(name="Top Triggers", value=stats_text or "No data", inline=False)
            embed.set_footer(text="Use !detect stats <keyword> for detailed info")
            await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Detector(bot))
