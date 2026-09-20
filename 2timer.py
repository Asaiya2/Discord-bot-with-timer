import discord
from discord.ext import commands, tasks
import sqlite3
import time
import asyncio
import os
import re

# ===== CONFIGURATION =====
DB_FOLDER = r"C:\Users\Kelly\Desktop\discord database"
MAIN_DB_PATH = os.path.join(DB_FOLDER, "asaiya_bot.db")

DURATION_RE = re.compile(r'(\d+)\s*([sSmMhHdD])')
MAX_NAME_LENGTH = 15


# ===== HELPERS (no DB / no bot needed) =====
def parse_duration(text):
    """Parse strings like '2m 3s', '1h 30m', '1d2h3m4s' into total seconds.
    Returns None if nothing valid was found."""
    if not text:
        return None
    matches = DURATION_RE.findall(text.strip())
    if not matches:
        return None
    units = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
    total = 0
    for value, unit in matches:
        total += int(value) * units[unit.lower()]
    return total if total > 0 else None


def format_countdown(total_seconds):
    """Format seconds as D H:MM:SS, dropping leading zero units."""
    total_seconds = max(0, int(round(total_seconds)))
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    if days:
        return f"{days}d {hours:02}:{minutes:02}:{seconds:02}"
    if hours:
        return f"{hours}:{minutes:02}:{seconds:02}"
    return f"{minutes:02}:{seconds:02}"


def label_for(row):
    """Display name for a timer row: its custom name, or 'Timer <position>'."""
    return row['name'] if row['name'] else f"Timer {row['position']}"


def format_position_list(positions):
    """[1,2,3] -> '1, 2 and 3'   [1,2] -> '1 and 2'   [1] -> '1'"""
    positions = sorted(positions)
    if len(positions) == 1:
        return str(positions[0])
    if len(positions) == 2:
        return f"{positions[0]} and {positions[1]}"
    return ", ".join(str(p) for p in positions[:-1]) + f" and {positions[-1]}"


def parse_timer_selection(text, valid_positions):
    """Parse '1', '1/2/3', '1,2', '1 2 3' or 'all' into a list of valid positions.
    Returns None if the input didn't resolve to any valid position."""
    text = text.strip().lower()
    if text in ('all', 'a'):
        return list(valid_positions)
    parts = re.split(r'[^\d]+', text)
    parts = [p for p in parts if p]
    if not parts:
        return None
    try:
        nums = sorted(set(int(p) for p in parts))
    except ValueError:
        return None
    if not nums or any(n not in valid_positions for n in nums):
        return None
    return nums


# ===== PERSISTENT VIEWS =====
class TimerControlView(discord.ui.View):
    """Attached to the live timer message.
    Add time / Reduce time / New Timer / Remove Timer / Name Timer."""

    def __init__(self, cog, session_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.session_id = session_id

        add_btn = discord.ui.Button(
            label="Add time", style=discord.ButtonStyle.green,
            custom_id=f"timer_add_{session_id}"
        )
        reduce_btn = discord.ui.Button(
            label="Reduce time", style=discord.ButtonStyle.red,
            custom_id=f"timer_reduce_{session_id}"
        )
        new_btn = discord.ui.Button(
            label="New Timer", style=discord.ButtonStyle.blurple,
            custom_id=f"timer_new_{session_id}"
        )
        remove_btn = discord.ui.Button(
            label="Remove Timer", style=discord.ButtonStyle.gray,
            custom_id=f"timer_remove_{session_id}"
        )
        name_btn = discord.ui.Button(
            label="Name Timer", style=discord.ButtonStyle.gray,
            custom_id=f"timer_name_{session_id}"
        )

        add_btn.callback = self.on_add
        reduce_btn.callback = self.on_reduce
        new_btn.callback = self.on_new
        remove_btn.callback = self.on_remove
        name_btn.callback = self.on_name

        self.add_item(add_btn)
        self.add_item(reduce_btn)
        self.add_item(new_btn)
        self.add_item(remove_btn)
        self.add_item(name_btn)

    async def on_add(self, interaction: discord.Interaction):
        await self.cog.handle_add_time(interaction, self.session_id)

    async def on_reduce(self, interaction: discord.Interaction):
        await self.cog.handle_reduce_time(interaction, self.session_id)

    async def on_new(self, interaction: discord.Interaction):
        await self.cog.handle_new_timer(interaction, self.session_id)

    async def on_remove(self, interaction: discord.Interaction):
        await self.cog.handle_remove_timer(interaction, self.session_id)

    async def on_name(self, interaction: discord.Interaction):
        await self.cog.handle_name_timer(interaction, self.session_id)


class TimerAckView(discord.ui.View):
    """Attached to the 'timer is done' ping. Single Understood button."""

    def __init__(self, cog, timer_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.timer_id = timer_id

        btn = discord.ui.Button(
            label="Understood", style=discord.ButtonStyle.gray,
            custom_id=f"timer_ack_{timer_id}"
        )
        btn.callback = self.on_ack
        self.add_item(btn)

    async def on_ack(self, interaction: discord.Interaction):
        self.cog.acknowledge_timer(self.timer_id)
        try:
            await interaction.response.edit_message(content="✅ Acknowledged.", embed=None, view=None)
        except discord.NotFound:
            pass

        # If every timer this session ever had is now completed + acknowledged
        # (and none are still running/paused/queued), wipe the whole DM trail.
        session_id = self.cog.get_session_for_timer(self.timer_id)
        if session_id:
            await self.cog.maybe_cleanup_session(session_id)


# ===== MAIN COG =====
class TimerCog(commands.Cog, name="Timer"):
    def __init__(self, bot):
        self.bot = bot
        self.processed_commands = {}
        # Sessions currently mid-prompt (waiting on a DM reply) — prevents two
        # button presses from racing to consume the same reply message.
        self.active_prompts = set()
        self.ensure_tables()
        self.tick.start()
        self.resurface_check.start()
        print(f"✅ Timer cog initialized (ID: {id(self)})")

    def cog_unload(self):
        self.tick.cancel()
        self.resurface_check.cancel()

    # ---------- duplicate guard (matches the pattern used elsewhere in this bot) ----------
    async def check_duplicate(self, ctx):
        key = f"{ctx.author.id}:{ctx.command.name}"
        now = time.time()
        if key in self.processed_commands and now - self.processed_commands[key] < 3:
            return True
        self.processed_commands[key] = now
        if len(self.processed_commands) > 100:
            for k, t in list(self.processed_commands.items()):
                if now - t > 10:
                    del self.processed_commands[k]
        return False

    # ---------- prompt lock (one conversational prompt at a time per session) ----------
    async def _acquire_prompt(self, interaction, session_id):
        if session_id in self.active_prompts:
            await interaction.response.send_message(
                "⚠️ Please finish answering the current prompt first.", ephemeral=True
            )
            return False
        self.active_prompts.add(session_id)
        await interaction.response.defer()
        return True

    def _release_prompt(self, session_id):
        self.active_prompts.discard(session_id)

    # ---------- DB setup ----------
    def _conn(self):
        os.makedirs(DB_FOLDER, exist_ok=True)
        return sqlite3.connect(MAIN_DB_PATH)

    def ensure_tables(self):
        conn = self._conn()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS timer_sessions
                     (session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id TEXT,
                      guild_id TEXT,
                      dm_channel_id TEXT,
                      dm_message_id TEXT,
                      created_at REAL,
                      active INTEGER DEFAULT 1)''')
        c.execute('''CREATE TABLE IF NOT EXISTS timers
                     (timer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                      session_id INTEGER,
                      position INTEGER,
                      name TEXT,
                      total_seconds INTEGER,
                      remaining_seconds INTEGER,
                      status TEXT,
                      ends_at REAL,
                      created_at REAL,
                      completed_at REAL,
                      acknowledged INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS timer_dm_messages
                     (session_id INTEGER,
                      message_id TEXT,
                      created_at REAL)''')

        # Migration safety: add 'name' column if this table already existed without it.
        c.execute("PRAGMA table_info(timers)")
        cols = [row[1] for row in c.fetchall()]
        if 'name' not in cols:
            c.execute("ALTER TABLE timers ADD COLUMN name TEXT")
            print("✅ Added 'name' column to timers table")

        conn.commit()
        conn.close()
        print("✅ Timer tables ensured")

    # ---------- session / timer row helpers ----------
    def create_session(self, user_id, guild_id):
        conn = self._conn()
        c = conn.cursor()
        c.execute("INSERT INTO timer_sessions (user_id, guild_id, created_at, active) VALUES (?, ?, ?, 1)",
                  (str(user_id), str(guild_id) if guild_id else None, time.time()))
        session_id = c.lastrowid
        conn.commit()
        conn.close()
        return session_id

    def set_session_message(self, session_id, channel_id, message_id):
        conn = self._conn()
        c = conn.cursor()
        c.execute("UPDATE timer_sessions SET dm_channel_id=?, dm_message_id=? WHERE session_id=?",
                  (str(channel_id) if channel_id else None,
                   str(message_id) if message_id else None, session_id))
        conn.commit()
        conn.close()

    def next_position(self, session_id):
        conn = self._conn()
        c = conn.cursor()
        c.execute("SELECT COALESCE(MAX(position), 0) FROM timers WHERE session_id=? "
                   "AND status IN ('running','paused','queued')", (session_id,))
        n = c.fetchone()[0]
        conn.close()
        return n + 1

    def create_timer(self, session_id, seconds, position, status, name=None):
        now = time.time()
        ends_at = now + seconds if status == 'running' else None
        conn = self._conn()
        c = conn.cursor()
        c.execute('''INSERT INTO timers
                     (session_id, position, name, total_seconds, remaining_seconds,
                      status, ends_at, created_at, completed_at, acknowledged)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 0)''',
                  (session_id, position, name, seconds, seconds, status, ends_at, now))
        timer_id = c.lastrowid
        conn.commit()
        conn.close()
        return timer_id

    def get_active_timers(self, session_id):
        """All non-completed timers for a session, ordered by position."""
        conn = self._conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM timers WHERE session_id=? AND status IN ('running','paused','queued') "
                   "ORDER BY position ASC", (session_id,))
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return rows

    def get_current_timer(self, session_id):
        """The position-1 (primary) timer, if any."""
        rows = self.get_active_timers(session_id)
        return rows[0] if rows else None

    def has_active_session(self, user_id):
        """True if this user already has a timer session with something
        running, paused, or queued — used to block a second !timer."""
        conn = self._conn()
        c = conn.cursor()
        c.execute('''SELECT COUNT(*) FROM timer_sessions ts
                     JOIN timers t ON t.session_id = ts.session_id
                     WHERE ts.user_id=? AND ts.active=1
                     AND t.status IN ('running','paused','queued')''',
                  (str(user_id),))
        count = c.fetchone()[0]
        conn.close()
        return count > 0

    def pause_timer(self, timer_id):
        conn = self._conn()
        c = conn.cursor()
        c.execute("SELECT status, ends_at, remaining_seconds FROM timers WHERE timer_id=?", (timer_id,))
        status, ends_at, remaining = c.fetchone()
        if status == 'running':
            remaining = max(0, ends_at - time.time())
        c.execute("UPDATE timers SET status='paused', ends_at=NULL, remaining_seconds=? WHERE timer_id=?",
                  (int(remaining), timer_id))
        conn.commit()
        conn.close()

    def add_time_to_timer(self, timer_id, add_seconds):
        """Apply an 'Add time' amount. If the timer was frozen by pause_timer()
        (i.e. it was running) it resumes counting down; if it was already
        queued, it just gets a bigger remaining_seconds for whenever it starts."""
        conn = self._conn()
        c = conn.cursor()
        c.execute("SELECT status, remaining_seconds, total_seconds FROM timers WHERE timer_id=?", (timer_id,))
        status, remaining, total = c.fetchone()
        new_remaining = remaining + add_seconds
        new_total = total + add_seconds
        if status == 'paused':
            c.execute("UPDATE timers SET status='running', ends_at=?, remaining_seconds=?, total_seconds=? "
                       "WHERE timer_id=?", (time.time() + new_remaining, new_remaining, new_total, timer_id))
        else:
            c.execute("UPDATE timers SET remaining_seconds=?, total_seconds=? WHERE timer_id=?",
                      (new_remaining, new_total, timer_id))
        conn.commit()
        conn.close()

    def reduce_running_timer(self, timer_id, reduce_seconds):
        conn = self._conn()
        c = conn.cursor()
        c.execute("SELECT status, ends_at, remaining_seconds FROM timers WHERE timer_id=?", (timer_id,))
        status, ends_at, remaining = c.fetchone()
        if status == 'running':
            current_remaining = max(0, ends_at - time.time())
        else:
            current_remaining = remaining
        new_remaining = max(1, int(current_remaining - reduce_seconds))
        if status == 'running':
            c.execute("UPDATE timers SET ends_at=?, remaining_seconds=? WHERE timer_id=?",
                      (time.time() + new_remaining, new_remaining, timer_id))
        else:
            c.execute("UPDATE timers SET remaining_seconds=? WHERE timer_id=?",
                      (new_remaining, timer_id))
        conn.commit()
        conn.close()

    def delete_timer(self, timer_id):
        conn = self._conn()
        c = conn.cursor()
        c.execute("DELETE FROM timers WHERE timer_id=?", (timer_id,))
        conn.commit()
        conn.close()

    def rename_timer(self, timer_id, name):
        conn = self._conn()
        c = conn.cursor()
        c.execute("UPDATE timers SET name=? WHERE timer_id=?", (name, timer_id))
        conn.commit()
        conn.close()

    def acknowledge_timer(self, timer_id):
        conn = self._conn()
        c = conn.cursor()
        c.execute("UPDATE timers SET acknowledged=1 WHERE timer_id=?", (timer_id,))
        conn.commit()
        conn.close()

    def is_acknowledged(self, timer_id):
        conn = self._conn()
        c = conn.cursor()
        c.execute("SELECT acknowledged FROM timers WHERE timer_id=?", (timer_id,))
        row = c.fetchone()
        conn.close()
        return bool(row and row[0])

    def get_session_for_timer(self, timer_id):
        conn = self._conn()
        c = conn.cursor()
        c.execute("SELECT session_id FROM timers WHERE timer_id=?", (timer_id,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else None

    def is_session_fully_done(self, session_id):
        """True once nothing is running/paused/queued AND every completed timer
        has been acknowledged — i.e. there's nothing left for the user to see."""
        conn = self._conn()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM timers WHERE session_id=? AND status IN ('running','paused','queued')",
                  (session_id,))
        active_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM timers WHERE session_id=? AND status='completed' AND acknowledged=0",
                  (session_id,))
        pending_ack_count = c.fetchone()[0]
        conn.close()
        return active_count == 0 and pending_ack_count == 0

    def renumber_and_promote(self, session_id):
        """Re-pack positions after a completion/removal, and start the next queued
        timer if it has landed on position 1."""
        rows = self.get_active_timers(session_id)
        conn = self._conn()
        c = conn.cursor()
        for i, row in enumerate(rows, start=1):
            c.execute("UPDATE timers SET position=? WHERE timer_id=?", (i, row['timer_id']))
        conn.commit()
        conn.close()

        if rows and rows[0]['status'] == 'queued':
            first = rows[0]
            conn = self._conn()
            c = conn.cursor()
            c.execute("UPDATE timers SET status='running', ends_at=? WHERE timer_id=?",
                      (time.time() + first['remaining_seconds'], first['timer_id']))
            conn.commit()
            conn.close()

    def get_session_message_ref(self, session_id):
        conn = self._conn()
        c = conn.cursor()
        c.execute("SELECT user_id, dm_channel_id, dm_message_id FROM timer_sessions WHERE session_id=?",
                  (session_id,))
        row = c.fetchone()
        conn.close()
        return row  # (user_id, dm_channel_id, dm_message_id) or None

    # ---------- DM message tracking (so we can wipe the bot's trail later) ----------
    def track_message(self, session_id, message_id):
        conn = self._conn()
        c = conn.cursor()
        c.execute("INSERT INTO timer_dm_messages (session_id, message_id, created_at) VALUES (?, ?, ?)",
                  (session_id, str(message_id), time.time()))
        conn.commit()
        conn.close()

    def get_tracked_messages(self, session_id):
        conn = self._conn()
        c = conn.cursor()
        c.execute("SELECT message_id FROM timer_dm_messages WHERE session_id=?", (session_id,))
        ids = [r[0] for r in c.fetchall()]
        conn.close()
        return ids

    def clear_tracked_messages(self, session_id):
        conn = self._conn()
        c = conn.cursor()
        c.execute("DELETE FROM timer_dm_messages WHERE session_id=?", (session_id,))
        conn.commit()
        conn.close()

    def untrack_message(self, session_id, message_id):
        conn = self._conn()
        c = conn.cursor()
        c.execute("DELETE FROM timer_dm_messages WHERE session_id=? AND message_id=?",
                  (session_id, str(message_id)))
        conn.commit()
        conn.close()

    async def _send_tracked(self, dm_channel, session_id, *args, **kwargs):
        """Send a message into the timer DM and remember its ID so it can be
        wiped once the whole session is finished."""
        msg = await dm_channel.send(*args, **kwargs)
        self.track_message(session_id, msg.id)
        return msg

    async def maybe_cleanup_session(self, session_id):
        """Once every timer this session ever had is completed + acknowledged
        (nothing left running/paused/queued/pending-ack), delete every bot
        message sent in that DM for this session — box, prompts, confirmations,
        the completion ping, all of it. The user's own messages are untouched."""
        if not self.is_session_fully_done(session_id):
            return

        ref = self.get_session_message_ref(session_id)
        if not ref:
            return
        user_id, dm_channel_id, dm_message_id = ref
        if not dm_channel_id:
            return

        message_ids = self.get_tracked_messages(session_id)
        partial_channel = self.bot.get_partial_messageable(int(dm_channel_id))
        for mid in message_ids:
            try:
                await partial_channel.get_partial_message(int(mid)).delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        self.clear_tracked_messages(session_id)
        self.set_session_message(session_id, dm_channel_id, None)

    # ---------- embed rendering ----------
    def build_embed(self, session_id):
        rows = self.get_active_timers(session_id)
        embed = discord.Embed(title="⏱️ Your Timers", color=discord.Color.blurple())

        if not rows:
            embed.description = "No active timers. Press **New Timer** to start one."
            return embed

        current = rows[0]
        if current['status'] == 'running':
            remaining = max(0, current['ends_at'] - time.time())
        else:
            remaining = current['remaining_seconds']

        embed.add_field(
            name="▶ Current Timer",
            value=f"**{label_for(current)}** — ⏳ `{format_countdown(remaining)}`" + (
                "\n⏸️ *Paused*" if current['status'] == 'paused' else ""
            ),
            inline=False
        )

        lines = []
        for row in rows:
            label = label_for(row)
            if row['status'] == 'queued':
                lines.append(f"{row['position']}. {label} — queued, starts after current "
                             f"(`{format_countdown(row['remaining_seconds'])}`)")
            else:
                live = max(0, row['ends_at'] - time.time()) if row['status'] == 'running' else row['remaining_seconds']
                marker = " ◀ current" if row['position'] == 1 else " — running in parallel"
                lines.append(f"{row['position']}. {label} — ⏳ `{format_countdown(live)}`{marker}")
        embed.add_field(name=f"Timer List ({len(rows)})", value="\n".join(lines), inline=False)

        embed.set_footer(text="Add/Reduce time ask which timer(s) to apply to. Remove/Name Timer ask for a # from the list.")
        return embed

    async def refresh_embed(self, session_id):
        ref = self.get_session_message_ref(session_id)
        if not ref:
            return
        user_id, dm_channel_id, dm_message_id = ref
        if not dm_channel_id or not dm_message_id:
            return
        try:
            # get_partial_messageable / get_partial_message build local references with
            # NO API call — unlike fetch_channel()/fetch_message(), which each cost a
            # full round-trip.
            partial_channel = self.bot.get_partial_messageable(int(dm_channel_id))
            partial_msg = partial_channel.get_partial_message(int(dm_message_id))
            embed = self.build_embed(session_id)
            await partial_msg.edit(embed=embed, view=TimerControlView(self, session_id))
        except (discord.NotFound, discord.Forbidden):
            pass
        except Exception as e:
            print(f"⚠️ Error refreshing timer embed for session {session_id}: {e}")

    # ---------- !timer command ----------
    @commands.command(name='timer')
    async def timer_cmd(self, ctx):
        """Start an interactive countdown timer, delivered via DM."""
        if await self.check_duplicate(ctx):
            return

        if self.has_active_session(ctx.author.id):
            await ctx.send(
                f"{ctx.author.mention} ❌ You already have a timer running. "
                f"Let it finish (or clear it with **Remove Timer**) before starting a new one with `!timer`."
            )
            return

        prompt_msg = await ctx.send(
            f"{ctx.author.mention} ⏱️ Define how long: `s`/`S` seconds, `m`/`M` minutes, "
            f"`h`/`H` hours, `d`/`D` days (e.g. `2m 3s`)"
        )

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        try:
            reply = await self.bot.wait_for('message', check=check, timeout=60)
        except asyncio.TimeoutError:
            await ctx.send(f"{ctx.author.mention} ⌛ Timed out waiting for a duration. Run `!timer` again.")
            return

        seconds = parse_duration(reply.content)
        if not seconds:
            await ctx.send(f"{ctx.author.mention} ❌ Couldn't understand that duration. Run `!timer` again.")
            return

        try:
            dm_channel = await ctx.author.create_dm()
            session_id = self.create_session(ctx.author.id, ctx.guild.id if ctx.guild else None)
            self.create_timer(session_id, seconds, position=1, status='running')
            embed = self.build_embed(session_id)
            view = TimerControlView(self, session_id)
            msg = await dm_channel.send(embed=embed, view=view)
            self.track_message(session_id, msg.id)
            self.set_session_message(session_id, dm_channel.id, msg.id)
            confirm_msg = await ctx.send(f"✅ {ctx.author.mention} Timer sent to your DMs!")

            # The DM timer box now exists — clean up the whole !timer exchange
            # in the server channel (command, prompt, reply, confirmation).
            if ctx.guild:
                for m in (ctx.message, prompt_msg, reply, confirm_msg):
                    try:
                        await m.delete()
                    except (discord.NotFound, discord.Forbidden):
                        pass
        except discord.Forbidden:
            await ctx.send(
                f"❌ {ctx.author.mention} I couldn't DM you. Please enable DMs from server members and try again."
            )

    # ---------- shared "which timer(s)?" prompt for Add/Reduce time ----------
    async def _prompt_timer_selection(self, dm_channel, session_id, user, rows):
        """Asks which timer(s) to act on and returns a list of chosen positions,
        or None if the flow should stop (no reply / bad input)."""
        valid_positions = [r['position'] for r in rows]
        pos_str = "/".join(str(p) for p in valid_positions)
        list_str = format_position_list(valid_positions)

        await self._send_tracked(
            dm_channel, session_id,
            f"{user.mention} Which timer? ({pos_str} = {list_str}. All = all timers.)"
        )

        def check(m):
            return m.author.id == user.id and m.channel.id == dm_channel.id

        try:
            reply = await self.bot.wait_for('message', check=check, timeout=60)
        except asyncio.TimeoutError:
            await self._send_tracked(dm_channel, session_id, "⌛ Timed out.")
            return None

        selected = parse_timer_selection(reply.content, valid_positions)
        if not selected:
            await self._send_tracked(dm_channel, session_id, "❌ Couldn't understand that selection.")
            return None
        return selected

    # ---------- button handlers ----------
    async def handle_add_time(self, interaction, session_id):
        if not await self._acquire_prompt(interaction, session_id):
            return
        try:
            dm_channel = interaction.channel
            user = interaction.user
            rows = self.get_active_timers(session_id)
            if not rows:
                await self._send_tracked(dm_channel, session_id, "No active timer to modify.")
                return

            selected = await self._prompt_timer_selection(dm_channel, session_id, user, rows)
            if not selected:
                return

            def check(m):
                return m.author.id == user.id and m.channel.id == dm_channel.id

            # Freeze any selected timers that are actively running so they don't
            # keep ticking while we ask for the amount (queued ones are already
            # static, so they're left alone here).
            rows_by_pos = {r['position']: r for r in rows}
            for pos in selected:
                row = rows_by_pos[pos]
                if row['status'] == 'running':
                    self.pause_timer(row['timer_id'])
            await self.refresh_embed(session_id)

            await self._send_tracked(dm_channel, session_id, "How much time do you want to add? (e.g. `1m 30s`)")

            try:
                reply2 = await self.bot.wait_for('message', check=check, timeout=60)
            except asyncio.TimeoutError:
                await self._send_tracked(
                    dm_channel, session_id,
                    "⌛ Timed out. The selected timer(s) stay paused — press **Add time** again when ready."
                )
                return

            add_seconds = parse_duration(reply2.content)
            if not add_seconds:
                await self._send_tracked(dm_channel, session_id, "❌ Couldn't understand that. The selected timer(s) stay paused.")
                return

            for pos in selected:
                self.add_time_to_timer(rows_by_pos[pos]['timer_id'], add_seconds)

            await self._send_tracked(
                dm_channel, session_id,
                f"✅ Added {format_countdown(add_seconds)} on timer {format_position_list(selected)}."
            )
            await self.refresh_embed(session_id)
        finally:
            self._release_prompt(session_id)

    async def handle_reduce_time(self, interaction, session_id):
        if not await self._acquire_prompt(interaction, session_id):
            return
        try:
            dm_channel = interaction.channel
            user = interaction.user
            rows = self.get_active_timers(session_id)
            if not rows:
                await self._send_tracked(dm_channel, session_id, "No active timer to modify.")
                return

            selected = await self._prompt_timer_selection(dm_channel, session_id, user, rows)
            if not selected:
                return

            def check(m):
                return m.author.id == user.id and m.channel.id == dm_channel.id

            await self._send_tracked(dm_channel, session_id, "How much time do you want to reduce? (e.g. `30s`)")

            try:
                reply2 = await self.bot.wait_for('message', check=check, timeout=60)
            except asyncio.TimeoutError:
                await self._send_tracked(dm_channel, session_id, "⌛ Timed out.")
                return

            reduce_seconds = parse_duration(reply2.content)
            if not reduce_seconds:
                await self._send_tracked(dm_channel, session_id, "❌ Couldn't understand that.")
                return

            rows_by_pos = {r['position']: r for r in rows}
            for pos in selected:
                self.reduce_running_timer(rows_by_pos[pos]['timer_id'], reduce_seconds)

            await self._send_tracked(
                dm_channel, session_id,
                f"✅ Reduced timer {format_position_list(selected)} by {format_countdown(reduce_seconds)}."
            )
            await self.refresh_embed(session_id)
        finally:
            self._release_prompt(session_id)

    async def handle_new_timer(self, interaction, session_id):
        if not await self._acquire_prompt(interaction, session_id):
            return
        try:
            dm_channel = interaction.channel
            user = interaction.user

            await self._send_tracked(
                dm_channel, session_id, f"{user.mention} ⏱️ Define how long for the new timer (e.g. `2m 3s`)"
            )

            def check(m):
                return m.author.id == user.id and m.channel.id == dm_channel.id

            try:
                reply = await self.bot.wait_for('message', check=check, timeout=60)
            except asyncio.TimeoutError:
                await self._send_tracked(dm_channel, session_id, "⌛ Timed out. New timer not created.")
                return

            seconds = parse_duration(reply.content)
            if not seconds:
                await self._send_tracked(dm_channel, session_id, "❌ Couldn't understand that duration. New timer not created.")
                return

            existing = self.get_active_timers(session_id)
            if not existing:
                # Nothing running — just start it as the new current timer.
                self.create_timer(session_id, seconds, position=1, status='running')
                await self._send_tracked(dm_channel, session_id, "✅ New timer started.")
                await self.refresh_embed(session_id)
                return

            await self._send_tracked(
                dm_channel, session_id,
                "Run this while the current timer is running? "
                "`y`/`yes` = run in parallel, `n`/`no` = queue until the current timer finishes"
            )
            try:
                reply2 = await self.bot.wait_for('message', check=check, timeout=60)
            except asyncio.TimeoutError:
                await self._send_tracked(dm_channel, session_id, "⌛ Timed out. New timer not created.")
                return

            ans = reply2.content.strip().lower()
            parallel = ans in ('y', 'yes')
            status = 'running' if parallel else 'queued'
            self.create_timer(session_id, seconds, position=self.next_position(session_id), status=status)
            await self._send_tracked(dm_channel, session_id, "✅ New timer added to the list.")
            await self.refresh_embed(session_id)
        finally:
            self._release_prompt(session_id)

    async def handle_remove_timer(self, interaction, session_id):
        if not await self._acquire_prompt(interaction, session_id):
            return
        try:
            dm_channel = interaction.channel
            user = interaction.user

            rows = self.get_active_timers(session_id)
            if not rows:
                await self._send_tracked(dm_channel, session_id, "No active timers to remove.")
                return

            await self._send_tracked(dm_channel, session_id, f"{user.mention} Which timer do you want removed? (#)")

            def check(m):
                return m.author.id == user.id and m.channel.id == dm_channel.id

            try:
                reply = await self.bot.wait_for('message', check=check, timeout=60)
            except asyncio.TimeoutError:
                await self._send_tracked(dm_channel, session_id, "⌛ Timed out.")
                return

            try:
                pos = int(reply.content.strip())
            except ValueError:
                await self._send_tracked(dm_channel, session_id, "❌ That's not a valid number.")
                return

            rows = self.get_active_timers(session_id)  # re-fetch in case it changed
            target = next((r for r in rows if r['position'] == pos), None)
            if not target:
                await self._send_tracked(dm_channel, session_id, f"❌ No timer at position {pos}.")
                return

            self.delete_timer(target['timer_id'])
            self.renumber_and_promote(session_id)
            remaining_rows = self.get_active_timers(session_id)

            if remaining_rows:
                if pos == 1:
                    await self._send_tracked(dm_channel, session_id, "✅ Removed current timer, skipping to next.")
                else:
                    await self._send_tracked(dm_channel, session_id, f"✅ Removed timer #{pos}.")
            else:
                await self._send_tracked(dm_channel, session_id, "✅ Removed timer, no longer counting down.")

            await self.refresh_embed(session_id)
        finally:
            self._release_prompt(session_id)

    async def handle_name_timer(self, interaction, session_id):
        if not await self._acquire_prompt(interaction, session_id):
            return
        try:
            dm_channel = interaction.channel
            user = interaction.user

            rows = self.get_active_timers(session_id)
            if not rows:
                await self._send_tracked(dm_channel, session_id, "No active timers to name.")
                return

            await self._send_tracked(dm_channel, session_id, f"{user.mention} Which timer would you like named? (#)")

            def check(m):
                return m.author.id == user.id and m.channel.id == dm_channel.id

            try:
                reply = await self.bot.wait_for('message', check=check, timeout=60)
            except asyncio.TimeoutError:
                await self._send_tracked(dm_channel, session_id, "⌛ Timed out.")
                return

            try:
                pos = int(reply.content.strip())
            except ValueError:
                await self._send_tracked(dm_channel, session_id, "❌ That's not a valid number.")
                return

            rows = self.get_active_timers(session_id)
            target = next((r for r in rows if r['position'] == pos), None)
            if not target:
                await self._send_tracked(dm_channel, session_id, f"❌ No timer at position {pos}.")
                return

            await self._send_tracked(
                dm_channel, session_id, f"What would you like it to be named? (Maximum {MAX_NAME_LENGTH} letters)"
            )

            try:
                reply2 = await self.bot.wait_for('message', check=check, timeout=60)
            except asyncio.TimeoutError:
                await self._send_tracked(dm_channel, session_id, "⌛ Timed out. Timer not renamed.")
                return

            new_name = reply2.content.strip()
            if not new_name:
                await self._send_tracked(dm_channel, session_id, "❌ Name can't be empty.")
                return
            if len(new_name) > MAX_NAME_LENGTH:
                await self._send_tracked(
                    dm_channel, session_id,
                    f"❌ Name must be {MAX_NAME_LENGTH} characters or fewer. Press **Name Timer** to try again."
                )
                return

            self.rename_timer(target['timer_id'], new_name)
            await self._send_tracked(dm_channel, session_id, f"✅ Timer #{pos} renamed to **{new_name}**.")
            await self.refresh_embed(session_id)
        finally:
            self._release_prompt(session_id)

    # ---------- completion + repeated ping until acknowledged ----------
    async def notify_completion(self, session_id, timer_id, label):
        ref = self.get_session_message_ref(session_id)
        if not ref:
            return
        user_id = ref[0]
        try:
            user = self.bot.get_user(int(user_id)) or await self.bot.fetch_user(int(user_id))
        except discord.NotFound:
            return

        completed_at = time.time()
        view = TimerAckView(self, timer_id)

        try:
            msg = await user.send(f"{user.mention} ⏰ **{label}** is up!", view=view)
            self.track_message(session_id, msg.id)
        except discord.Forbidden:
            return

        while True:
            await asyncio.sleep(60)
            if self.is_acknowledged(timer_id):
                return
            lapsed = time.time() - completed_at
            try:
                await msg.delete()
            except (discord.NotFound, discord.Forbidden):
                pass
            try:
                msg = await user.send(
                    f"{user.mention} ⏰ **{label}** is done! "
                    f"Time lapsed: `{format_countdown(lapsed)}`",
                    view=view
                )
                self.track_message(session_id, msg.id)
            except discord.Forbidden:
                return

    # ---------- background tick ----------
    @tasks.loop(seconds=1.1)
    async def tick(self):
        conn = self._conn()
        c = conn.cursor()
        c.execute("SELECT session_id FROM timer_sessions WHERE active=1")
        session_ids = [r[0] for r in c.fetchall()]
        now = time.time()

        to_refresh = []

        for session_id in session_ids:
            c.execute(
                "SELECT timer_id, status, ends_at, name, position FROM timers WHERE session_id=? "
                "AND status='running' ORDER BY position", (session_id,)
            )
            running = c.fetchall()

            completed = []  # (timer_id, label)
            for timer_id, status, ends_at, name, position in running:
                if ends_at is not None and ends_at - now <= 0:
                    c.execute(
                        "UPDATE timers SET status='completed', remaining_seconds=0, completed_at=? "
                        "WHERE timer_id=?", (now, timer_id)
                    )
                    completed.append((timer_id, name if name else f"Timer {position}"))

            conn.commit()

            for timer_id, label in completed:
                asyncio.create_task(self.notify_completion(session_id, timer_id, label))

            if completed:
                self.renumber_and_promote(session_id)

            # Skip idle sessions with nothing left to show.
            c.execute(
                "SELECT COUNT(*) FROM timers WHERE session_id=? AND status IN ('running','paused','queued')",
                (session_id,)
            )
            has_active = c.fetchone()[0] > 0
            if not has_active and not completed:
                continue

            to_refresh.append(session_id)

        conn.close()

        # Edit every session's message CONCURRENTLY instead of one-at-a-time.
        # Sequentially awaiting each edit meant the loop's real-world duration
        # scaled with how many sessions needed updating — with several boxes
        # active at once, ticks could land many seconds apart instead of 1.1s.
        # Running them together keeps the update rate flat regardless of count.
        if to_refresh:
            await asyncio.gather(*(self.refresh_embed(sid) for sid in to_refresh), return_exceptions=True)

    @tick.before_loop
    async def before_tick(self):
        await self.bot.wait_until_ready()

    # ---------- hourly resurface: keep the box as the newest DM message ----------
    @tasks.loop(hours=1)
    async def resurface_check(self):
        conn = self._conn()
        c = conn.cursor()
        c.execute("SELECT session_id, dm_channel_id, dm_message_id FROM timer_sessions "
                   "WHERE active=1 AND dm_channel_id IS NOT NULL AND dm_message_id IS NOT NULL")
        sessions = c.fetchall()
        conn.close()

        for session_id, dm_channel_id, dm_message_id in sessions:
            active_rows = self.get_active_timers(session_id)
            if not active_rows:
                continue  # nothing running — don't bother resurfacing an idle box

            try:
                channel = self.bot.get_channel(int(dm_channel_id)) or await self.bot.fetch_channel(int(dm_channel_id))
                newest = [m async for m in channel.history(limit=1)]
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue

            if not newest or str(newest[0].id) == str(dm_message_id):
                continue  # already the newest message — nothing to do

            # Not the newest anymore — delete it and resend at the bottom.
            # (If a completion ping happens to be newer, it's untouched here;
            # the resurfaced box just ends up below it, not replacing it.)
            try:
                partial_channel = self.bot.get_partial_messageable(int(dm_channel_id))
                await partial_channel.get_partial_message(int(dm_message_id)).delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
            self.untrack_message(session_id, dm_message_id)

            try:
                embed = self.build_embed(session_id)
                view = TimerControlView(self, session_id)
                new_msg = await channel.send(embed=embed, view=view)
            except (discord.Forbidden, discord.HTTPException):
                continue

            self.set_session_message(session_id, dm_channel_id, new_msg.id)
            self.track_message(session_id, new_msg.id)

    @resurface_check.before_loop
    async def before_resurface(self):
        await self.bot.wait_until_ready()

    # ---------- restore state on restart ----------
    @commands.Cog.listener()
    async def on_ready(self):
        # Re-attach persistent control views to any live timer messages,
        # and resume ping loops for anything that finished but wasn't acknowledged.
        conn = self._conn()
        c = conn.cursor()
        c.execute("SELECT session_id, dm_message_id FROM timer_sessions WHERE active=1")
        sessions = c.fetchall()

        for session_id, dm_message_id in sessions:
            if dm_message_id:
                self.bot.add_view(TimerControlView(self, session_id), message_id=int(dm_message_id))

        c.execute("SELECT timer_id, session_id, name, position FROM timers WHERE status='completed' AND acknowledged=0")
        pending = c.fetchall()
        conn.close()

        for timer_id, session_id, name, position in pending:
            label = name if name else f"Timer {position}"
            asyncio.create_task(self.notify_completion(session_id, timer_id, label))

        print(f"✅ Timer cog restored {len(sessions)} session(s), resumed {len(pending)} pending ack(s)")


async def setup(bot):
    await bot.add_cog(TimerCog(bot))
