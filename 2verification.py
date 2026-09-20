import discord
from discord.ext import commands
import sqlite3
import time
import asyncio
import random
import os
from datetime import datetime

# ===== CONFIGURATION =====
DB_FOLDER = r"C:\Users\Kelly\Desktop\discord database"
MAIN_DB_PATH = os.path.join(DB_FOLDER, "asaiya_bot.db")

VERIFY_CHANNEL_NAME = "asaiya-verification"
ALLOWED_SERVER_ID = 1484265140215087235  # Only server where verifyall command can be used


class VerificationDMView(discord.ui.View):
    def __init__(self, guild_name, guild_id):
        super().__init__(timeout=300)  # 5 minute timeout
        self.guild_name = guild_name
        self.guild_id = guild_id

    @discord.ui.button(label="✅ Verify Now", style=discord.ButtonStyle.green, custom_id="verify_now")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog('Verification')
        if not cog:
            await interaction.response.send_message("❌ Verification system unavailable.", ephemeral=True)
            return
        
        # Get the guild
        guild = interaction.client.get_guild(self.guild_id)
        if not guild:
            await interaction.response.send_message("❌ Server not found.", ephemeral=True)
            return
        
        # Get the member
        member = guild.get_member(interaction.user.id)
        if not member:
            await interaction.response.send_message("❌ You are not in that server anymore.", ephemeral=True)
            return
        
        # Check if verification is enabled
        if not cog.is_verification_enabled(guild.id):
            await interaction.response.send_message("❌ Verification is disabled in that server.", ephemeral=True)
            return
        
        # Get the verification role
        role_id = cog.get_verify_role(str(guild.id))
        if not role_id:
            await interaction.response.send_message("❌ Verification role not set up.", ephemeral=True)
            return
        
        role = guild.get_role(int(role_id))
        if not role:
            await interaction.response.send_message("❌ Verification role not found.", ephemeral=True)
            return
        
        # Check if already verified
        if role in member.roles:
            await interaction.response.send_message("✅ You are already verified!", ephemeral=True)
            return
        
        # Verify the user
        cog.mark_globally_verified(interaction.user.id, guild.id)
        
        try:
            await member.add_roles(role, reason="Verification button")
            
            # Hide verification channel
            verify_channel = discord.utils.get(guild.text_channels, name=VERIFY_CHANNEL_NAME)
            if verify_channel:
                try:
                    await verify_channel.set_permissions(member, read_messages=False, view_channel=False)
                except:
                    pass
            
            # Trigger ID setup
            id_cog = interaction.client.get_cog('IDSystem')
            if id_cog:
                await id_cog.start_id_setup(member, guild)
            
            await interaction.response.send_message(
                f"✅ **Verification Successful!**\n\nYou have been verified in **{guild.name}**!\nYou now have full access to the server.",
                ephemeral=True
            )
            
            # Send success message to verification channel
            if verify_channel:
                await verify_channel.send(f"✅ {member.mention} has been verified!", delete_after=10)
            
            print(f"✅ Verified {member.name} in {guild.name}")
            
        except Exception as e:
            await interaction.response.send_message(f"❌ Error verifying: {str(e)}", ephemeral=True)
            print(f"Error verifying user: {e}")
        
        self.stop()

    @discord.ui.button(label="👀 I'm Just Looking", style=discord.ButtonStyle.grey, custom_id="just_looking")
    async def looking_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog('Verification')
        if not cog:
            await interaction.response.send_message("❌ Verification system unavailable.", ephemeral=True)
            return
        
        # Get the guild
        guild = interaction.client.get_guild(self.guild_id)
        if not guild:
            await interaction.response.send_message("❌ Server not found.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="👋 You're a Guest!",
            description=(
                f"Welcome to **{guild.name}** as a guest!\n\n"
                f"As a guest, you can only see the **guest channels**.\n\n"
                f"When you're ready to verify, click the **Verify Now** button.\n\n"
                f"*This message will be deleted in 30 seconds.*"
            ),
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
        # Also send a message in the server to inform about guest
        verify_channel = discord.utils.get(guild.text_channels, name=VERIFY_CHANNEL_NAME)
        if verify_channel:
            try:
                await verify_channel.send(
                    f"👋 {interaction.user.mention} has chosen to join as a guest! "
                    f"They will only have access to guest channels until they verify.",
                    delete_after=30
                )
            except:
                pass
        
        self.stop()


class Verification(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.setup_database()
        # Add a cooldown dictionary to prevent duplicate processing
        self.processing_users = {}
        self.processing_commands = {}  # Track command executions by message ID
        self.processed_commands = {}   # ← FIX: was missing, caused AttributeError in check_duplicate
        self.ALLOWED_SERVER_ID = ALLOWED_SERVER_ID
        
        # Feature toggle cache
        self.verification_enabled = {}  # {guild_id: bool}
        
        # Load settings
        self.load_all_settings()
        
        print("✅ Verification cog initialized")
        print(f"   Loaded verification settings for {len(self.verification_enabled)} server(s)")

    # ===== LOAD SETTINGS =====
    def load_all_settings(self):
        """Load all per-server settings from database"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            
            # Load verification enabled status from server_mod_settings
            c.execute('''CREATE TABLE IF NOT EXISTS server_mod_settings
                         (guild_id TEXT PRIMARY KEY,
                          hack_detection INTEGER DEFAULT 1,
                          spam_detection INTEGER DEFAULT 1,
                          raid_detection INTEGER DEFAULT 1,
                          verification_enabled INTEGER DEFAULT 0,
                          verification_role_id TEXT,
                          updated_at REAL)''')
            
            c.execute("SELECT guild_id, verification_enabled FROM server_mod_settings")
            rows = c.fetchall()
            for guild_id, enabled in rows:
                self.verification_enabled[int(guild_id)] = bool(enabled)
            
            conn.close()
        except Exception as e:
            print(f"Error loading settings: {e}")

    def save_verification_setting(self, guild_id, enabled):
        """Save verification enabled setting to database"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            
            c.execute('''INSERT OR REPLACE INTO server_mod_settings
                         (guild_id, hack_detection, spam_detection, raid_detection, verification_enabled, verification_role_id, updated_at)
                         VALUES (?, 
                                 COALESCE((SELECT hack_detection FROM server_mod_settings WHERE guild_id = ?), 1),
                                 COALESCE((SELECT spam_detection FROM server_mod_settings WHERE guild_id = ?), 1),
                                 COALESCE((SELECT raid_detection FROM server_mod_settings WHERE guild_id = ?), 1),
                                 ?, 
                                 COALESCE((SELECT verification_role_id FROM server_mod_settings WHERE guild_id = ?), ""),
                                 ?)''',
                      (str(guild_id), str(guild_id), str(guild_id), str(guild_id), 1 if enabled else 0, str(guild_id), time.time()))
            
            conn.commit()
            conn.close()
            self.verification_enabled[guild_id] = enabled
            return True
        except Exception as e:
            print(f"Error saving verification setting: {e}")
            return False

    def is_verification_enabled(self, guild_id):
        """Check if verification is enabled for a guild"""
        return self.verification_enabled.get(guild_id, False)  # Default to disabled

    # ===== DATABASE CONNECTION FUNCTIONS =====
    def get_server_db_path(self, guild_id):
        """Get database path for a specific server using the server name from main database"""
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
        if not hasattr(self.bot, 'db_connections'):
            self.bot.db_connections = {}
        if not hasattr(self.bot, 'last_db_use'):
            self.bot.last_db_use = {}
        
        current_time = time.time()
        
        # Clean up old connections
        if len(self.bot.db_connections) > 10:
            for gid, last_used in list(self.bot.last_db_use.items()):
                if current_time - last_used > 300:
                    try:
                        if gid in self.bot.db_connections:
                            self.bot.db_connections[gid].close()
                            del self.bot.db_connections[gid]
                        del self.bot.last_db_use[gid]
                    except:
                        pass
        
        # Check existing connection
        if guild_id in self.bot.db_connections:
            try:
                self.bot.db_connections[guild_id].execute("SELECT 1")
                self.bot.last_db_use[guild_id] = current_time
                return self.bot.db_connections[guild_id]
            except:
                try:
                    self.bot.db_connections[guild_id].close()
                except:
                    pass
                del self.bot.db_connections[guild_id]
        
        # Create new connection
        db_path = self.get_server_db_path(guild_id)
        if not db_path or not os.path.exists(db_path):
            return None
        
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        self.bot.db_connections[guild_id] = conn
        self.bot.last_db_use[guild_id] = current_time
        return conn

    def setup_database(self):
        """Initialize verification tables"""
        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()

        c.execute('''CREATE TABLE IF NOT EXISTS verify_settings
                     (guild_id TEXT PRIMARY KEY,
                      role_id TEXT,
                      role_name TEXT,
                      set_by TEXT,
                      set_at REAL)''')

        c.execute('''CREATE TABLE IF NOT EXISTS global_verified_users
                     (user_id TEXT PRIMARY KEY,
                      verified_at REAL,
                      verified_in_guild TEXT)''')

        c.execute('''CREATE TABLE IF NOT EXISTS verification_dm_log
                     (user_id TEXT,
                      guild_id TEXT,
                      sent_at REAL,
                      PRIMARY KEY (user_id, guild_id))''')

        conn.commit()
        conn.close()
        print("✅ Verification database initialized")

    # ===== DATABASE HELPERS =====

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

    def is_globally_verified(self, user_id):
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT 1 FROM global_verified_users WHERE user_id = ?", (str(user_id),))
            result = c.fetchone()
            conn.close()
            return result is not None
        except:
            return False

    def mark_globally_verified(self, user_id, guild_id):
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''INSERT OR REPLACE INTO global_verified_users
                         (user_id, verified_at, verified_in_guild)
                         VALUES (?, ?, ?)''',
                      (str(user_id), time.time(), str(guild_id)))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error saving global verification: {e}")

    def has_recent_dm(self, user_id, guild_id, cooldown=60):
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''SELECT sent_at FROM verification_dm_log
                         WHERE user_id = ? AND guild_id = ?''',
                      (str(user_id), str(guild_id)))
            result = c.fetchone()
            conn.close()
            
            if result:
                return time.time() - result[0] < cooldown
            return False
        except:
            return False

    def log_dm_sent(self, user_id, guild_id):
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''INSERT OR REPLACE INTO verification_dm_log
                         (user_id, guild_id, sent_at)
                         VALUES (?, ?, ?)''',
                      (str(user_id), str(guild_id), time.time()))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error logging DM: {e}")

    # ===== TOGGLE COMMANDS =====

    @commands.command(name='stopverify')
    @commands.has_permissions(administrator=True)
    async def stop_verify(self, ctx):
        """Turn off verification system for this server"""
        if await self.check_duplicate(ctx):
            return
            
        if self.save_verification_setting(ctx.guild.id, False):
            embed = discord.Embed(
                title="🔴 Verification System: OFF",
                description="New members will no longer be required to verify.",
                color=discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="Use !startverify to re-enable")
            await ctx.send(embed=embed)
            print(f"⚠️ Verification system turned OFF by {ctx.author} in {ctx.guild.name}")
        else:
            await ctx.send("❌ Failed to save settings. Please try again.")

    @commands.command(name='startverify')
    @commands.has_permissions(administrator=True)
    async def start_verify(self, ctx):
        """Turn on verification system for this server"""
        if await self.check_duplicate(ctx):
            return
            
        role_id = self.get_verify_role(str(ctx.guild.id))
        if not role_id:
            await ctx.send("❌ Cannot enable verification: No verification role set. Use `!setverify @role` first.")
            return
            
        if self.save_verification_setting(ctx.guild.id, True):
            embed = discord.Embed(
                title="🟢 Verification System: ON",
                description="New members will now be required to verify.",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="Use !stopverify to disable")
            await ctx.send(embed=embed)
            print(f"✅ Verification system turned ON by {ctx.author} in {ctx.guild.name}")
        else:
            await ctx.send("❌ Failed to save settings. Please try again.")

    # ===== SEND VERIFICATION DM =====

    async def send_verification_dm(self, member):
        """Send verification DM to a new member"""
        role_id = self.get_verify_role(str(member.guild.id))
        if not role_id:
            print(f"ℹ️ No verification role set for {member.guild.name}, skipping DM to {member.name}")
            return
        
        if not self.is_verification_enabled(member.guild.id):
            print(f"ℹ️ Verification disabled for {member.guild.name}, skipping DM to {member.name}")
            return

        if self.is_globally_verified(member.id):
            print(f"ℹ️ {member.name} is globally verified, auto-verifying in {member.guild.name}")
            await self.auto_verify_global_user(member)
            return

        if member.id in self.processing_users:
            print(f"⚠️ {member.name} is already being processed, skipping")
            return

        if self.has_recent_dm(member.id, member.guild.id):
            print(f"⚠️ Recent DM already sent to {member.name} in {member.guild.name}, skipping")
            return

        self.processing_users[member.id] = time.time()

        try:
            guild = member.guild
            embed = discord.Embed(
                title=f"👋 Welcome to {guild.name}!",
                description=(
                    f"Hey {member.mention}! To access **{guild.name}**, please verify you're human.\n\n"
                    f"**Guests** can only see guest channels until they verify."
                ),
                color=discord.Color.blurple()
            )
            embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
            embed.set_footer(text="This message will expire in 5 minutes.")

            view = VerificationDMView(guild.name, guild.id)
            await member.send(embed=embed, view=view)
            self.log_dm_sent(member.id, guild.id)
            print(f"✅ Sent verification DM to {member.name} in {guild.name}")
            
        except discord.Forbidden:
            verify_channel = discord.utils.get(member.guild.text_channels, name=VERIFY_CHANNEL_NAME)
            if verify_channel:
                try:
                    await verify_channel.send(
                        f"👋 {member.mention} I couldn't DM you! Please enable DMs, then use the button below to verify.",
                        delete_after=60
                    )
                    print(f"⚠️ DMs disabled for {member.name}, directed to verify channel in {guild.name}")
                except:
                    pass
        except Exception as e:
            print(f"❌ Error sending verification to {member.name}: {e}")
        finally:
            await asyncio.sleep(10)
            if member.id in self.processing_users:
                del self.processing_users[member.id]

    async def auto_verify_global_user(self, member):
        """Automatically verify a globally verified user"""
        guild = member.guild
        
        if not self.is_verification_enabled(guild.id):
            return
            
        role_id = self.get_verify_role(str(guild.id))
        if not role_id:
            return

        role = guild.get_role(int(role_id))
        if not role or role in member.roles:
            return

        try:
            await member.add_roles(role, reason="Global verification (auto)")

            verify_channel = discord.utils.get(guild.text_channels, name=VERIFY_CHANNEL_NAME)
            if verify_channel:
                try:
                    await verify_channel.set_permissions(member, read_messages=False, view_channel=False)
                except:
                    pass

            id_cog = self.bot.get_cog('IDSystem')
            if id_cog:
                await id_cog.start_id_setup(member, guild)

            print(f"✅ Auto-verified {member.name} in {guild.name} (global)")
        except Exception as e:
            print(f"Error auto-verifying in {guild.name}: {e}")

    # ===== COMMANDS =====

    @commands.command(name='setverify')
    @commands.has_permissions(administrator=True)
    async def setverify(self, ctx, role: discord.Role):
        """Set the role given after passing verification"""
        if ctx.message.id in self.processing_commands:
            return
        self.processing_commands[ctx.message.id] = time.time()

        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''INSERT OR REPLACE INTO verify_settings
                         (guild_id, role_id, role_name, set_by, set_at)
                         VALUES (?, ?, ?, ?, ?)''',
                      (str(ctx.guild.id), str(role.id), role.name,
                       str(ctx.author.id), time.time()))
            conn.commit()
            conn.close()
            
            # Update server_mod_settings
            try:
                conn2 = sqlite3.connect(MAIN_DB_PATH)
                c2 = conn2.cursor()
                c2.execute('''INSERT OR REPLACE INTO server_mod_settings
                             (guild_id, hack_detection, spam_detection, raid_detection, verification_enabled, verification_role_id, updated_at)
                             VALUES (?, 
                                     COALESCE((SELECT hack_detection FROM server_mod_settings WHERE guild_id = ?), 1),
                                     COALESCE((SELECT spam_detection FROM server_mod_settings WHERE guild_id = ?), 1),
                                     COALESCE((SELECT raid_detection FROM server_mod_settings WHERE guild_id = ?), 1),
                                     COALESCE((SELECT verification_enabled FROM server_mod_settings WHERE guild_id = ?), 0),
                                     ?, ?)''',
                          (str(ctx.guild.id), str(ctx.guild.id), str(ctx.guild.id), str(ctx.guild.id), str(ctx.guild.id), str(role.id), time.time()))
                conn2.commit()
                conn2.close()
            except:
                pass

            embed = discord.Embed(
                title="✅ Verification Role Set",
                description=(
                    f"Members will receive **{role.mention}** after clicking the verify button.\n\n"
                    f"Verification system is currently **{'ON' if self.is_verification_enabled(ctx.guild.id) else 'OFF'}**.\n"
                    f"Use `!startverify` to enable it."
                ),
                color=discord.Color.green()
            )
            embed.set_footer(text=f"Set by {ctx.author}")
            await ctx.send(embed=embed)
            print(f"✅ Verification role set in {ctx.guild.name} to {role.name}")
            
        finally:
            await asyncio.sleep(10)
            if ctx.message.id in self.processing_commands:
                del self.processing_commands[ctx.message.id]

    @commands.command(name='fixverify')
    @commands.has_permissions(administrator=True)
    async def fixverify(self, ctx):
        """Hide verification channel from all verified users"""
        if ctx.message.id in self.processing_commands:
            return
        self.processing_commands[ctx.message.id] = time.time()

        try:
            guild = ctx.guild
            verify_channel = discord.utils.get(guild.text_channels, name=VERIFY_CHANNEL_NAME)

            if not verify_channel:
                await ctx.send("❌ No verification channel found!")
                return

            role_id = self.get_verify_role(str(guild.id))
            if not role_id:
                await ctx.send("❌ No verification role set! Use `!setverify @role` first.")
                return

            role = guild.get_role(int(role_id))
            if not role:
                await ctx.send("❌ Verification role not found!")
                return

            status_msg = await ctx.send("🔄 Hiding verification channel from verified users...")

            hidden_count = 0
            for member in guild.members:
                if role in member.roles:
                    try:
                        await verify_channel.set_permissions(member, read_messages=False, view_channel=False)
                        hidden_count += 1
                        await asyncio.sleep(0.1)
                    except:
                        pass

            await status_msg.delete()
            await ctx.send(f"✅ Hidden #{VERIFY_CHANNEL_NAME} from **{hidden_count}** verified users!")
            
        finally:
            await asyncio.sleep(5)
            if ctx.message.id in self.processing_commands:
                del self.processing_commands[ctx.message.id]

    @commands.command(name='verifyall')
    @commands.has_permissions(administrator=True)
    async def verifyall(self, ctx):
        """Send verification DMs to all unverified users across all servers with verification enabled"""
        if ctx.guild.id != self.ALLOWED_SERVER_ID:
            await ctx.send("❌ This command is only available in the designated server.")
            print(f"⚠️ verifyall attempted in unauthorized server: {ctx.guild.name} ({ctx.guild.id})")
            return
        
        if ctx.message.id in self.processing_commands:
            print(f"⚠️ verifyall command {ctx.message.id} already being processed, skipping")
            return
        self.processing_commands[ctx.message.id] = time.time()
        print(f"✅ Processing verifyall command {ctx.message.id} from {ctx.author} in {ctx.guild.name}")

        try:
            status_msg = await ctx.send("🔍 Scanning all servers for unverified users...")

            total_stats = {
                'dm_success': 0,
                'dm_failed': 0,
                'auto_verified': 0,
                'skipped': 0,
                'servers_checked': 0,
                'servers_with_verification': 0
            }
            
            server_results = []

            for guild in self.bot.guilds:
                role_id = self.get_verify_role(str(guild.id))
                if not role_id:
                    continue
                    
                if not self.is_verification_enabled(guild.id):
                    continue

                role = guild.get_role(int(role_id))
                if not role:
                    print(f"⚠️ Server {guild.name} has verification role ID {role_id} but role not found, skipping")
                    continue

                total_stats['servers_with_verification'] += 1
                print(f"🔍 Checking server: {guild.name} ({guild.id})")

                server_dm_success = 0
                server_dm_failed = 0
                server_auto_verified = 0
                server_skipped = 0

                for member in guild.members:
                    if member.bot:
                        continue
                        
                    if role in member.roles:
                        continue

                    if member.id in self.processing_users:
                        server_skipped += 1
                        continue

                    if self.is_globally_verified(member.id):
                        await self.auto_verify_global_user(member)
                        server_auto_verified += 1
                        await asyncio.sleep(0.5)
                        continue

                    if self.has_recent_dm(member.id, guild.id):
                        server_skipped += 1
                        continue

                    try:
                        await self.send_verification_dm(member)
                        server_dm_success += 1
                        await asyncio.sleep(1)
                    except Exception as e:
                        print(f"Error sending verification to {member.name} in {guild.name}: {e}")
                        server_dm_failed += 1

                total_stats['dm_success'] += server_dm_success
                total_stats['dm_failed'] += server_dm_failed
                total_stats['auto_verified'] += server_auto_verified
                total_stats['skipped'] += server_skipped
                total_stats['servers_checked'] += 1

                if server_dm_success > 0 or server_dm_failed > 0 or server_auto_verified > 0:
                    server_results.append(
                        f"**{guild.name}**: ✅{server_dm_success} | ❌{server_dm_failed} | 🤖{server_auto_verified} | ⏭️{server_skipped}"
                    )

                await asyncio.sleep(2)

            await status_msg.delete()

            embed = discord.Embed(
                title="🌐 Global Verification Scan Complete",
                description=(
                    f"Scanned **{total_stats['servers_checked']}** servers with verification enabled "
                    f"(out of {total_stats['servers_with_verification']} total with verification set up)"
                ),
                color=discord.Color.green() if total_stats['dm_failed'] == 0 else discord.Color.orange(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(name="📨 DM Success", value=str(total_stats['dm_success']), inline=True)
            embed.add_field(name="❌ DM Failed", value=str(total_stats['dm_failed']), inline=True)
            embed.add_field(name="🤖 Auto-Verified", value=str(total_stats['auto_verified']), inline=True)
            embed.add_field(name="⏭️ Skipped", value=str(total_stats['skipped']), inline=True)
            
            if server_results:
                results_text = "\n".join(server_results[:10])
                if len(server_results) > 10:
                    results_text += f"\n*... and {len(server_results) - 10} more servers*"
                
                embed.add_field(
                    name="📊 Server Breakdown (DM Success/Failed/Auto/Skipped)",
                    value=results_text,
                    inline=False
                )

            embed.set_footer(text=f"Command used by {ctx.author}")
            await ctx.send(embed=embed)
            
            print(f"✅ Global verifyall completed: {total_stats}")

        except Exception as e:
            print(f"❌ Error in verifyall: {e}")
            await ctx.send(f"❌ An error occurred: {str(e)}")
        finally:
            await asyncio.sleep(30)
            if ctx.message.id in self.processing_commands:
                del self.processing_commands[ctx.message.id]

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


async def setup(bot):
    await bot.add_cog(Verification(bot))
