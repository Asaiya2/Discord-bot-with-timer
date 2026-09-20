import discord
from discord.ext import commands, tasks
import time
import sqlite3
import os
import asyncio
from datetime import datetime, timezone
import sys
import zoneinfo

# Windows compatibility for zoneinfo
if sys.platform == "win32":
    try:
        import tzdata
        zoneinfo.reset_tzpath()
        print("✅ tzdata loaded for Windows timezone support")
    except ImportError:
        print("⚠️ tzdata not found, timezone support may be limited")
        try:
            import pytz
            print("✅ pytz found as fallback")
        except ImportError:
            print("⚠️ No timezone library available")

from zoneinfo import ZoneInfo
from typing import Dict, Optional

DB_FOLDER = r"C:\Users\Kelly\Desktop\discord database"
MAIN_DB_PATH = os.path.join(DB_FOLDER, "asaiya_bot.db")

ITEMS_PER_PAGE = 10


# =============================================================================
# SEARCH MODAL
# =============================================================================
class SearchModal(discord.ui.Modal, title='Search Users'):
    def __init__(self, cog, guild_id: int, role_id=None, tracker_id: str = None):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.role_id = role_id
        self.tracker_id = tracker_id

        self.search_input = discord.ui.TextInput(
            label='Search by username / nickname',
            placeholder='Type a name to filter the list…',
            required=True,
            max_length=50
        )
        self.add_item(self.search_input)

    async def on_submit(self, interaction: discord.Interaction):
        search_term = self.search_input.value.strip().lower()
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ Could not find server.", ephemeral=True)
            return

        # Gather members
        if self.role_id:
            role = guild.get_role(self.role_id)
            members = role.members if role else list(guild.members)
        else:
            members = list(guild.members)

        members = [m for m in members if not m.bot]

        # Filter by search term
        matched = [
            m for m in members
            if search_term in m.display_name.lower() or search_term in m.name.lower()
        ]

        if not matched:
            await interaction.response.send_message(
                f"🔍 No members found matching **{discord.utils.escape_markdown(search_term)}**.",
                ephemeral=True
            )
            return

        matched.sort(key=lambda m: m.display_name.lower())

        embed = discord.Embed(
            title=f"🔍 Search: \"{discord.utils.escape_markdown(search_term)}\"",
            description=f"{len(matched)} member(s) found  • with \"{discord.utils.escape_markdown(search_term)}\" in their Username/Nickname",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow()
        )

        online_lines = []
        offline_lines = []

        for member in matched:
            name = discord.utils.escape_markdown(member.display_name)
            if member.id in self.cog.online_times:
                ts = int(self.cog.online_times[member.id])
                emoji = {
                    discord.Status.online: "🟢",
                    discord.Status.idle: "🟡",
                    discord.Status.dnd: "🔴",
                }.get(member.status, "🟢")
                online_lines.append(f"{emoji} **{name}** — online since <t:{ts}:R>")
            elif member.id in self.cog.offline_times:
                ts = int(self.cog.offline_times[member.id])
                offline_lines.append(f"⚫ **{name}** — offline since <t:{ts}:R>")
            else:
                offline_lines.append(f"❓ **{name}** — status unknown")

        def safe_field(lines: list) -> str:
            text = "\n".join(lines)
            return text[:1020] + "\n…" if len(text) > 1024 else text

        if online_lines:
            embed.add_field(name=f"🟢 Online ({len(online_lines)})", value=safe_field(online_lines), inline=False)
        if offline_lines:
            embed.add_field(name=f"⚫ Offline ({len(offline_lines)})", value=safe_field(offline_lines), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)


# =============================================================================
# PERSISTENT VIEW — WITH UNIQUE CUSTOM_IDS
# =============================================================================
class StatusTrackerView(discord.ui.View):
    """
    Persistent view for status tracker with proper button callbacks.
    timeout=None is required for persistence.
    Each button has a UNIQUE custom_id that includes the message ID
    so Discord can route interactions correctly after restart.
    """

    def __init__(self, cog, guild_id: int, channel_id: int, message_id: int, role_id=None):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.message_id = message_id
        self.role_id = role_id

        # Unique identifier for this tracker instance
        self.tracker_id = f"{guild_id}_{message_id}"

        # Add buttons with UNIQUE custom_ids and explicit callbacks
        self.prev_button = discord.ui.Button(
            label="◀ Previous",
            style=discord.ButtonStyle.blurple,
            custom_id=f"status_tracker:prev:{self.tracker_id}"
        )
        self.prev_button.callback = self.prev_callback
        self.add_item(self.prev_button)

        self.next_button = discord.ui.Button(
            label="Next ▶",
            style=discord.ButtonStyle.blurple,
            custom_id=f"status_tracker:next:{self.tracker_id}"
        )
        self.next_button.callback = self.next_callback
        self.add_item(self.next_button)

        self.search_button = discord.ui.Button(
            label="🔍 Search",
            style=discord.ButtonStyle.grey,
            custom_id=f"status_tracker:search:{self.tracker_id}"
        )
        self.search_button.callback = self.search_callback
        self.add_item(self.search_button)

        # Per-user pagination
        self.user_pages: Dict[int, int] = {}

        # Member cache
        self.cached_members = None
        self.cache_timestamp = 0
        self.cache_ttl = 60

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Verify the interaction is for this tracker."""
        return True

    async def prev_callback(self, interaction: discord.Interaction):
        """Handle previous page button"""
        await self.handle_page_change(interaction, -1)

    async def next_callback(self, interaction: discord.Interaction):
        """Handle next page button"""
        await self.handle_page_change(interaction, 1)

    async def handle_page_change(self, interaction: discord.Interaction, delta: int):
        """Handle page navigation"""
        await interaction.response.defer()
        
        # Get current page for this user
        current_page = self.user_pages.get(interaction.user.id, 0)
        new_page = max(0, current_page + delta)
        
        # Get members and page data
        members = await self.get_members(interaction.guild)
        page_data = self.get_page_data(members, new_page)
        
        # Check if page is valid
        if new_page >= page_data['total_pages']:
            await interaction.followup.send("You're already on the last page!", ephemeral=True)
            return
        
        # Update user's page
        self.user_pages[interaction.user.id] = new_page
        
        # Build and send new embed
        embed = await self.build_embed(interaction.guild, page_data)
        await interaction.edit_original_response(embed=embed)

    async def search_callback(self, interaction: discord.Interaction):
        """Handle search button - opens a modal"""
        modal = SearchModal(self.cog, self.guild_id, self.role_id, self.tracker_id)
        await interaction.response.send_modal(modal)

    async def get_members(self, guild):
        now = time.time()
        if self.cached_members and (now - self.cache_timestamp) < self.cache_ttl:
            return self.cached_members

        if self.role_id:
            role = guild.get_role(self.role_id)
            members = role.members if role else list(guild.members)
        else:
            members = list(guild.members)

        members = [m for m in members if not m.bot]
        members.sort(key=lambda m: m.display_name.lower())

        self.cached_members = members
        self.cache_timestamp = now
        return members

    def get_page_data(self, all_members: list, page: int) -> dict:
        online_members = []
        offline_members = []

        for member in all_members:
            if member.id in self.cog.online_times:
                online_members.append(member)
            elif member.id in self.cog.offline_times:
                offline_members.append(member)
            else:
                if member.status == discord.Status.offline:
                    self.cog.offline_times[member.id] = time.time()
                    offline_members.append(member)
                else:
                    self.cog.online_times[member.id] = time.time()
                    online_members.append(member)

        online_pages = max(1, (len(online_members) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        offline_pages = max(1, (len(offline_members) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        total_pages = max(online_pages, offline_pages)

        page = max(0, min(page, total_pages - 1))
        start = page * ITEMS_PER_PAGE
        end = start + ITEMS_PER_PAGE

        return {
            'online': online_members[start:end],
            'offline': offline_members[start:end],
            'online_total': len(online_members),
            'offline_total': len(offline_members),
            'current_page': page,
            'total_pages': total_pages,
        }

    async def build_embed(self, guild, page_data: dict) -> discord.Embed:
        embed = discord.Embed(
            title=f"📊 Live Status Tracker — {guild.name}",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )

        online_slice = page_data['online']
        offline_slice = page_data['offline']
        online_total = page_data['online_total']
        offline_total = page_data['offline_total']
        current_page = page_data['current_page']
        total_pages = page_data['total_pages']

        embed.description = f"**{online_total} online** • **{offline_total} offline**"

        # Global clock
        current_utc = datetime.now(timezone.utc)
        timezones = [
            ("🇺🇸 New York (EDT/EST)", "America/New_York"),
            ("🇨🇳 China (Beijing)", "Asia/Shanghai"),
            ("🇯🇵 Japan (Tokyo)", "Asia/Tokyo"),
            ("🇵🇭 Philippines (Manila)", "Asia/Manila"),
            ("🇻🇳 Vietnam (HCMC)", "Asia/Ho_Chi_Minh"),
            ("🇹🇭 Thailand (Bangkok)", "Asia/Bangkok"),
        ]
        clock_lines = []
        for name, tz_name in timezones:
            try:
                tz_time = current_utc.astimezone(ZoneInfo(tz_name))
                time_str = tz_time.strftime("%I:%M %p").lstrip("0")
                clock_lines.append(f"{name}: {time_str}")
            except Exception as e:
                print(f"⚠️ Timezone error {tz_name}: {e}")
                clock_lines.append(f"{name}: ⚠️ unavailable")

        embed.add_field(name="🌍 GLOBAL CLOCK", value="\n".join(clock_lines), inline=False)

        # Online
        if online_slice:
            text = ""
            for member in online_slice:
                ts = int(self.cog.online_times.get(member.id, time.time()))
                emoji = {
                    discord.Status.online: "🟢",
                    discord.Status.idle: "🟡",
                    discord.Status.dnd: "🔴",
                }.get(member.status, "🟢")
                text += f"{emoji} **<@{member.id}>** — online since <t:{ts}:R>\n"
            embed.add_field(name=f"🟢 Online ({len(online_slice)} / {online_total})", value=text, inline=False)
        else:
            label = "*No online members*" if online_total == 0 else "*No online members on this page*"
            embed.add_field(name=f"🟢 Online (0 / {online_total})", value=label, inline=False)

        # Offline
        if offline_slice:
            text = ""
            for member in offline_slice:
                ts = int(self.cog.offline_times.get(member.id, time.time()))
                text += f"⚫ **<@{member.id}>** — offline since <t:{ts}:R>\n"
            embed.add_field(name=f"⚫ Offline ({len(offline_slice)} / {offline_total})", value=text, inline=False)
        else:
            label = "*No offline members*" if offline_total == 0 else "*No offline members on this page*"
            embed.add_field(name=f"⚫ Offline (0 / {offline_total})", value=label, inline=False)

        embed.set_footer(
            text=f"Page {current_page + 1}/{total_pages}"
                 f" • 🔍 Search results are private to you"
                 f" • ⏱️ Updates every 10s"
        )
        return embed

    async def update_default(self, message: discord.Message):
        """Called by the auto-update loop — always resets to page 0."""
        self.cached_members = None
        members = await self.get_members(message.guild)
        page_data = self.get_page_data(members, 0)
        embed = await self.build_embed(message.guild, page_data)
        await message.edit(embed=embed, view=self)


# =============================================================================
# COG
# =============================================================================
class StatusTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.online_times = bot.online_times
        self.offline_times = bot.offline_times

        self.tracked_servers: Dict[int, dict] = {}
        self.active_views: Dict[int, StatusTrackerView] = {}
        self.processed_commands: dict = {}
        self.pending_updates: dict = {}
        self.update_queue = asyncio.Queue()
        self.failed_update_count: Dict[int, int] = {}
        self.last_update_times: Dict[int, float] = {}

        # Setup database with proper schema
        self.setup_database()
        
        self.update_status.start()
        self.process_queue.start()
        print(f"✅ StatusTracker cog loaded (id={id(self)})")

    def cog_unload(self):
        self.save_tracked_servers()
        self.update_status.cancel()
        self.process_queue.cancel()

    # ── database setup with migration ──────────────────────────────────────
    
    def setup_database(self):
        """Setup database tables with proper schema and migration"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            
            # Check if table exists
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='status_tracker'")
            table_exists = c.fetchone()
            
            if table_exists:
                # Check current columns
                c.execute("PRAGMA table_info(status_tracker)")
                columns = [col[1] for col in c.fetchall()]
                
                # Add missing columns if needed
                if 'message_id' not in columns:
                    print("⚠️ Adding missing 'message_id' column to status_tracker...")
                    c.execute("ALTER TABLE status_tracker ADD COLUMN message_id TEXT")
                    print("✅ Added 'message_id' column")
                
                if 'role_id' not in columns:
                    print("⚠️ Adding missing 'role_id' column to status_tracker...")
                    c.execute("ALTER TABLE status_tracker ADD COLUMN role_id TEXT")
                    print("✅ Added 'role_id' column")
            else:
                # Create new table with all columns
                c.execute('''CREATE TABLE IF NOT EXISTS status_tracker (
                    guild_id TEXT PRIMARY KEY,
                    channel_id TEXT,
                    role_id TEXT,
                    message_id TEXT
                )''')
                print("✅ Created status_tracker table with full schema")
            
            conn.commit()
            conn.close()
            print("✅ Database setup complete")
            
        except Exception as e:
            print(f"❌ Database setup error: {e}")

    def _ensure_table(self, cursor):
        """Ensure table exists with correct schema before operations"""
        cursor.execute('''CREATE TABLE IF NOT EXISTS status_tracker (
            guild_id TEXT PRIMARY KEY,
            channel_id TEXT,
            role_id TEXT,
            message_id TEXT
        )''')

    def save_tracked_servers(self):
        """Save tracked servers to database"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            self._ensure_table(c)
            
            for guild_id, cfg in self.tracked_servers.items():
                c.execute('''INSERT OR REPLACE INTO status_tracker
                             (guild_id, channel_id, role_id, message_id)
                             VALUES (?, ?, ?, ?)''',
                          (str(guild_id),
                           str(cfg['channel_id']),
                           str(cfg['role_id']) if cfg['role_id'] else None,
                           str(cfg['message_id'])))
            conn.commit()
            conn.close()
            print(f"✅ Saved {len(self.tracked_servers)} tracker(s) to DB")
        except Exception as e:
            print(f"❌ save_tracked_servers: {e}")

    def _delete_from_db(self, guild_id_str: str):
        """Delete a tracker from database"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            self._ensure_table(c)
            c.execute("DELETE FROM status_tracker WHERE guild_id = ?", (guild_id_str,))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"❌ _delete_from_db: {e}")

    async def load_tracked_servers(self):
        """Restore tracker views after a restart."""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            self._ensure_table(c)
            c.execute("SELECT guild_id, channel_id, role_id, message_id FROM status_tracker")
            rows = c.fetchall()
            conn.close()

            loaded = 0
            for guild_id_str, channel_id_str, role_id_str, message_id_str in rows:
                try:
                    guild_id = int(guild_id_str)
                    channel_id = int(channel_id_str)
                    message_id = int(message_id_str)
                    role_id = int(role_id_str) if role_id_str else None

                    guild = self.bot.get_guild(guild_id)
                    if not guild:
                        print(f"⚠️ Guild {guild_id} not found — skipping")
                        continue

                    channel = guild.get_channel(channel_id)
                    if not channel:
                        print(f"⚠️ Channel {channel_id} not found in {guild.name} — skipping")
                        continue

                    # Verify message exists and get it
                    try:
                        message = await channel.fetch_message(message_id)
                    except discord.NotFound:
                        print(f"⚠️ Message {message_id} gone in {guild.name} — removing from DB")
                        self._delete_from_db(guild_id_str)
                        continue
                    except Exception as e:
                        print(f"⚠️ Error fetching message {message_id} in {guild.name}: {e}")
                        continue

                    # Create view with the ACTUAL message_id
                    view = StatusTrackerView(self, guild_id, channel_id, message_id, role_id)

                    self.active_views[guild_id] = view
                    self.tracked_servers[guild_id] = {
                        'channel_id': channel_id,
                        'message_id': message_id,
                        'role_id': role_id,
                    }

                    # Register with Discord - this is CRITICAL for persistence
                    self.bot.add_view(view, message_id=message_id)

                    # Update the embed to show current data
                    await view.update_default(message)

                    loaded += 1
                    print(f"✅ Restored tracker for {guild.name} (msg {message_id})")

                except Exception as e:
                    print(f"❌ Restoring tracker for guild {guild_id_str}: {e}")
                    import traceback
                    traceback.print_exc()

            print(f"✅ Loaded {loaded} tracker(s) from DB")
            return loaded

        except Exception as e:
            print(f"❌ load_tracked_servers: {e}")
            import traceback
            traceback.print_exc()
            return 0

    # ── presence tracking ─────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        if before.status == after.status:
            return

        user_id = after.id
        self.pending_updates[user_id] = {
            'status': after.status,
            'timestamp': time.time(),
            'name': after.name,
            'update_count': self.pending_updates.get(user_id, {}).get('update_count', 0) + 1,
        }
        asyncio.create_task(self.delayed_status_check(user_id))

    async def delayed_status_check(self, user_id: int):
        await asyncio.sleep(3)
        if user_id not in self.pending_updates:
            return

        pending = self.pending_updates[user_id]
        if time.time() - pending['timestamp'] < 2:
            asyncio.create_task(self.delayed_status_check(user_id))
            return

        if pending['status'] != discord.Status.offline:
            self.offline_times.pop(user_id, None)
            self.online_times[user_id] = time.time()
            print(f"🟢 FINAL: {pending['name']} online")
        else:
            self.online_times.pop(user_id, None)
            self.offline_times[user_id] = time.time()
            print(f"⚫ FINAL: {pending['name']} offline")

        del self.pending_updates[user_id]
        await self.update_queue.put(user_id)

    @tasks.loop(seconds=2)
    async def process_queue(self):
        processed = set()
        while not self.update_queue.empty():
            try:
                user_id = await self.update_queue.get()
                if user_id not in processed:
                    processed.add(user_id)
                    await self.force_update_for_user(user_id)
            except asyncio.QueueEmpty:
                break
            except Exception as e:
                print(f"process_queue error: {e}")

    @process_queue.before_loop
    async def before_process_queue(self):
        await self.bot.wait_until_ready()

    async def force_update_for_user(self, user_id: int):
        for guild_id, config in list(self.tracked_servers.items()):
            guild = self.bot.get_guild(guild_id)
            if guild and guild.get_member(user_id):
                await self.update_single_tracker(guild_id, config)

    # ── member join / leave ───────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.bot:
            return
        self.online_times[member.id] = time.time()
        await self.force_update_for_user(member.id)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        self.online_times.pop(member.id, None)
        self.offline_times.pop(member.id, None)
        await self.force_update_for_user(member.id)

    # ── on_ready ──────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self):
        print("🔄 Seeding status tracking for all members…")
        self.online_times.clear()
        self.offline_times.clear()
        online_count = offline_count = 0

        for guild in self.bot.guilds:
            for member in guild.members:
                if member.bot:
                    continue
                if member.status == discord.Status.offline:
                    self.offline_times[member.id] = time.time()
                    offline_count += 1
                else:
                    self.online_times[member.id] = time.time()
                    online_count += 1

        print(f"✅ Status seeded: {online_count} online, {offline_count} offline")

        # Restore views after bot is ready
        await self.load_tracked_servers()

    # ── auto-update loop ──────────────────────────────────────────────────────

    @tasks.loop(seconds=10)
    async def update_status(self):
        for guild_id, config in list(self.tracked_servers.items()):
            await self.update_single_tracker(guild_id, config)

    @update_status.before_loop
    async def before_update(self):
        await self.bot.wait_until_ready()

    async def update_single_tracker(self, guild_id: int, config: dict):
        now = time.time()
        if now - self.last_update_times.get(guild_id, 0) < 60:
            return
        self.last_update_times[guild_id] = now

        view = self.active_views.get(guild_id)
        if not view:
            return

        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        channel = guild.get_channel(config['channel_id'])
        if not channel:
            return

        try:
            message = await channel.fetch_message(config['message_id'])
            await view.update_default(message)
            self.failed_update_count[guild_id] = 0

        except discord.NotFound:
            print(f"⚠️ Tracker message gone in {guild.name} — removing")
            self.tracked_servers.pop(guild_id, None)
            self.active_views.pop(guild_id, None)
            self.save_tracked_servers()

        except Exception as e:
            self.failed_update_count[guild_id] = self.failed_update_count.get(guild_id, 0) + 1
            print(f"⚠️ update_single_tracker [{guild.name}]: {e}")

    # ── duplicate-command guard ───────────────────────────────────────────────

    async def check_duplicate(self, ctx) -> bool:
        key = f"{ctx.author.id}:{ctx.command.name}"
        now = time.time()
        if key in self.processed_commands and now - self.processed_commands[key] < 2:
            return True
        self.processed_commands[key] = now
        if len(self.processed_commands) > 100:
            self.processed_commands = {
                k: v for k, v in self.processed_commands.items() if now - v < 10
            }
        return False

    # ── commands ──────────────────────────────────────────────────────────────

    @commands.command(name='track')
    @commands.has_permissions(administrator=True)
    async def track(self, ctx, channel: discord.TextChannel = None, role: discord.Role = None):
        """Start live status tracking. Usage: !track [#channel] [@role]"""
        if await self.check_duplicate(ctx):
            return

        if channel is None:
            channel = ctx.channel

        guild_id = ctx.guild.id

        # Clean up any existing tracker for this guild
        if guild_id in self.tracked_servers:
            old = self.tracked_servers[guild_id]
            try:
                old_ch = ctx.guild.get_channel(old['channel_id'])
                if old_ch:
                    old_msg = await old_ch.fetch_message(old['message_id'])
                    await old_msg.delete()
            except Exception:
                pass

        # Build initial embed with members
        role_id = role.id if role else None
        temp_members = await self.get_members_for_guild(ctx.guild, role_id)
        page_data = self.get_initial_page_data(temp_members, 0)
        embed = await self.build_initial_embed(ctx.guild, page_data, role_id)

        # Send message FIRST to get message_id
        message = await channel.send(embed=embed)

        # NOW create view with the actual message_id
        view = StatusTrackerView(self, guild_id, channel.id, message.id, role_id)

        # Edit message to add the view
        await message.edit(embed=embed, view=view)

        self.tracked_servers[guild_id] = {
            'channel_id': channel.id,
            'message_id': message.id,
            'role_id': role_id,
        }
        self.active_views[guild_id] = view
        self.failed_update_count[guild_id] = 0

        # Register with Discord - this ensures the view persists after restart
        self.bot.add_view(view, message_id=message.id)

        self.save_tracked_servers()

        role_text = f" for {role.mention}" if role else ""
        await ctx.send(f"✅ Status tracking started in {channel.mention}{role_text}")

    async def get_members_for_guild(self, guild, role_id):
        """Helper to get members for initial embed building"""
        if role_id:
            role = guild.get_role(role_id)
            members = role.members if role else list(guild.members)
        else:
            members = list(guild.members)
        members = [m for m in members if not m.bot]
        members.sort(key=lambda m: m.display_name.lower())
        return members

    def get_initial_page_data(self, all_members: list, page: int) -> dict:
        """Helper for initial page data"""
        online_members = []
        offline_members = []

        for member in all_members:
            if member.id in self.online_times:
                online_members.append(member)
            elif member.id in self.offline_times:
                offline_members.append(member)
            else:
                if member.status == discord.Status.offline:
                    offline_members.append(member)
                else:
                    online_members.append(member)

        online_pages = max(1, (len(online_members) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        offline_pages = max(1, (len(offline_members) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        total_pages = max(online_pages, offline_pages)

        page = max(0, min(page, total_pages - 1))
        start = page * ITEMS_PER_PAGE
        end = start + ITEMS_PER_PAGE

        return {
            'online': online_members[start:end],
            'offline': offline_members[start:end],
            'online_total': len(online_members),
            'offline_total': len(offline_members),
            'current_page': page,
            'total_pages': total_pages,
        }

    async def build_initial_embed(self, guild, page_data: dict, role_id: int = None) -> discord.Embed:
        """Helper for initial embed building"""
        embed = discord.Embed(
            title=f"📊 Live Status Tracker — {guild.name}",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )

        online_slice = page_data['online']
        offline_slice = page_data['offline']
        online_total = page_data['online_total']
        offline_total = page_data['offline_total']
        current_page = page_data['current_page']
        total_pages = page_data['total_pages']

        embed.description = f"**{online_total} online** • **{offline_total} offline**"

        # Global clock
        current_utc = datetime.now(timezone.utc)
        timezones = [
            ("🇺🇸 New York (EDT/EST)", "America/New_York"),
            ("🇨🇳 China (Beijing)", "Asia/Shanghai"),
            ("🇯🇵 Japan (Tokyo)", "Asia/Tokyo"),
            ("🇵🇭 Philippines (Manila)", "Asia/Manila"),
            ("🇻🇳 Vietnam (HCMC)", "Asia/Ho_Chi_Minh"),
            ("🇹🇭 Thailand (Bangkok)", "Asia/Bangkok"),
        ]
        clock_lines = []
        for name, tz_name in timezones:
            try:
                tz_time = current_utc.astimezone(ZoneInfo(tz_name))
                time_str = tz_time.strftime("%I:%M %p").lstrip("0")
                clock_lines.append(f"{name}: {time_str}")
            except Exception as e:
                clock_lines.append(f"{name}: ⚠️ unavailable")

        embed.add_field(name="🌍 GLOBAL CLOCK", value="\n".join(clock_lines), inline=False)

        if online_slice:
            text = ""
            for member in online_slice:
                ts = int(self.online_times.get(member.id, time.time()))
                emoji = {
                    discord.Status.online: "🟢",
                    discord.Status.idle: "🟡",
                    discord.Status.dnd: "🔴",
                }.get(member.status, "🟢")
                text += f"{emoji} **<@{member.id}>** — online since <t:{ts}:R>\n"
            embed.add_field(name=f"🟢 Online ({len(online_slice)} / {online_total})", value=text, inline=False)
        else:
            label = "*No online members*" if online_total == 0 else "*No online members on this page*"
            embed.add_field(name=f"🟢 Online (0 / {online_total})", value=label, inline=False)

        if offline_slice:
            text = ""
            for member in offline_slice:
                ts = int(self.offline_times.get(member.id, time.time()))
                text += f"⚫ **<@{member.id}>** — offline since <t:{ts}:R>\n"
            embed.add_field(name=f"⚫ Offline ({len(offline_slice)} / {offline_total})", value=text, inline=False)
        else:
            label = "*No offline members*" if offline_total == 0 else "*No offline members on this page*"
            embed.add_field(name=f"⚫ Offline (0 / {offline_total})", value=label, inline=False)

        embed.set_footer(
            text=f"Page {current_page + 1}/{total_pages}"
                 f" • 🔍 Search results are private to you"
                 f" • ⏱️ Updates every 10s"
        )
        return embed

    @commands.command(name='untrack')
    @commands.has_permissions(administrator=True)
    async def untrack(self, ctx):
        """Stop status tracking in this server."""
        if await self.check_duplicate(ctx):
            return

        guild_id = ctx.guild.id
        if guild_id not in self.tracked_servers:
            await ctx.send("❌ No active tracking in this server.")
            return

        config = self.tracked_servers.pop(guild_id)
        self.active_views.pop(guild_id, None)
        self.failed_update_count.pop(guild_id, None)
        self.last_update_times.pop(guild_id, None)

        try:
            ch = ctx.guild.get_channel(config['channel_id'])
            if ch:
                msg = await ch.fetch_message(config['message_id'])
                await msg.delete()
        except Exception:
            pass

        self._delete_from_db(str(guild_id))
        await ctx.send("✅ Status tracking stopped and removed.")

    @commands.command(name='checkstatus')
    @commands.has_permissions(administrator=True)
    async def checkstatus(self, ctx, member: discord.Member = None):
        """Check a user's current tracked status."""
        if await self.check_duplicate(ctx):
            return

        target = member or ctx.author
        embed = discord.Embed(
            title=f"Status Check — {target.display_name}",
            color=target.color if target.color.value != 0 else discord.Color.blue()
        )
        status_map = {
            discord.Status.online: "🟢 Online",
            discord.Status.idle: "🟡 Idle",
            discord.Status.dnd: "🔴 Do Not Disturb",
            discord.Status.offline: "⚫ Offline",
        }
        embed.add_field(name="Current Status", value=status_map.get(target.status, "❓ Unknown"), inline=True)

        if target.id in self.online_times:
            embed.add_field(name="Online Since", value=f"<t:{int(self.online_times[target.id])}:R>", inline=True)
        elif target.id in self.offline_times:
            embed.add_field(name="Offline Since", value=f"<t:{int(self.offline_times[target.id])}:R>", inline=True)
        else:
            embed.add_field(name="Tracked Duration", value="Not tracked yet", inline=True)

        embed.add_field(name="Bot?", value="Yes" if target.bot else "No", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name='checkdict')
    @commands.has_permissions(administrator=True)
    async def checkdict(self, ctx, member: discord.Member = None):
        """Debug: show raw tracking dict entries for a user."""
        if await self.check_duplicate(ctx):
            return

        target = member or ctx.author
        embed = discord.Embed(title=f"Dict Check — {target.display_name}", color=discord.Color.blue())

        if target.id in self.online_times:
            ts = self.online_times[target.id]
            embed.add_field(name="📗 online_times", value=f"✅ Yes\n`{ts}`\n<t:{int(ts)}:R>", inline=False)
        else:
            embed.add_field(name="📗 online_times", value="❌ No", inline=False)

        if target.id in self.offline_times:
            ts = self.offline_times[target.id]
            embed.add_field(name="📕 offline_times", value=f"✅ Yes\n`{ts}`\n<t:{int(ts)}:R>", inline=False)
        else:
            embed.add_field(name="📕 offline_times", value="❌ No", inline=False)

        embed.add_field(name="🟢 Discord Status", value=str(target.status), inline=False)
        embed.add_field(
            name="📊 Dict sizes",
            value=f"online: `{len(self.online_times)}` • offline: `{len(self.offline_times)}`",
            inline=False
        )
        await ctx.send(embed=embed)

    @commands.command(name='resetstatus')
    @commands.has_permissions(administrator=True)
    async def resetstatus(self, ctx, member: discord.Member):
        """Reset a user's tracking data."""
        if await self.check_duplicate(ctx):
            return

        removed = self.online_times.pop(member.id, None)
        removed2 = self.offline_times.pop(member.id, None)

        if removed or removed2:
            await ctx.send(f"✅ Reset tracking data for {member.mention}")
        else:
            await ctx.send(f"ℹ️ No tracking data found for {member.mention}")


async def setup(bot):
    await bot.add_cog(StatusTracker(bot))
