import discord
from discord.ext import commands, tasks
import yt_dlp as youtube_dl
import asyncio
import re
import time
import os
import math
import traceback

# ===== CONFIGURATION =====
BOT_CHANNEL = "asaiya-hub"       # Channel where music commands are allowed
STAFF_ROLE  = "AsaiyaBot"        # Role required for stopall

# ===== YT-DLP CONFIGURATION =====
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'extract_flat': False,
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)


# ===== AUDIO SOURCE =====
class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('webpage_url') or data.get('url')
        self.uploader = data.get('uploader', 'Unknown Artist')
        self.uploader_url = data.get('uploader_url')
        self.duration = data.get('duration')
        self.start_time = None  # Will be set when playback starts
        self.requester = None

    @classmethod
    async def from_data(cls, data, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        stream_url = data['url']
        return cls(discord.FFmpegPCMAudio(stream_url, **ffmpeg_options), data=data)


# ===== QUEUE ENTRY =====
class QueueEntry:
    def __init__(self, data, requester, original_url):
        self.data = data
        self.requester = requester
        self.original_url = original_url
        self.title = data.get('title', 'Unknown Title')
        self.uploader = data.get('uploader', 'Unknown Artist')
        self.duration = data.get('duration')
        self.webpage_url = data.get('webpage_url', original_url)


# ===== MUSIC PLAYER =====
class MusicPlayer:
    def __init__(self, ctx, voice_client, bot):
        self.bot = bot
        self.channel = ctx.channel
        self.guild_id = ctx.guild.id
        self.guild_name = ctx.guild.name
        self._voice_client = voice_client

        self.queue = asyncio.Queue()
        self.next = asyncio.Event()
        self.current = None
        self.current_source = None
        self._queue_list = []
        self.now_playing_message = None  # Store the now playing message to edit it
        self.now_playing_message_id = None  # Store just the ID for linking
        
        # Start the countdown updater task
        self.countdown_task = self.bot.loop.create_task(self.update_countdown())

        self.task = ctx.bot.loop.create_task(self.player_loop())
        print(f"✅ MusicPlayer created for guild {ctx.guild.name}")

    @property
    def guild(self):
        return self.bot.get_guild(self.guild_id)

    def _get_vc(self):
        """Get the voice client, checking both cached and guild state"""
        if self._voice_client and self._voice_client.is_connected():
            return self._voice_client
        guild = self.guild
        if guild and guild.voice_client and guild.voice_client.is_connected():
            self._voice_client = guild.voice_client
            return self._voice_client
        return None

    async def player_loop(self):
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            self.next.clear()

            try:
                entry = await asyncio.wait_for(self.queue.get(), timeout=300.0)
                if entry in self._queue_list:
                    self._queue_list.remove(entry)
            except asyncio.TimeoutError:
                # No songs for 5 minutes, disconnect
                await self.destroy()
                return
            except Exception as e:
                print(f"❌ Queue error in {self.guild_name}: {e}")
                continue

            self.current = entry

            vc = self._get_vc()
            if not vc:
                await self.channel.send("❌ Lost connection to voice channel!")
                self.current = None
                continue

            try:
                source = await YTDLSource.from_data(entry.data, loop=self.bot.loop)
                source.requester = entry.requester
                source.start_time = time.time()  # Record when playback starts
                self.current_source = source
            except Exception as e:
                await self.channel.send(f"❌ Could not load audio: {e}")
                self.current = None
                self.next.set()
                continue

            try:
                if not hasattr(vc, 'play_lock'):
                    vc.play_lock = asyncio.Lock()
                async with vc.play_lock:
                    if vc.is_playing():
                        vc.stop()
                        await asyncio.sleep(0.1)
                    
                    def after_playing(error):
                        if error:
                            print(f"❌ Playback error in {self.guild_name}: {error}")
                        asyncio.run_coroutine_threadsafe(self._song_done(error), self.bot.loop)
                    
                    vc.play(source, after=after_playing)
                    
            except Exception as e:
                await self.channel.send(f"❌ Playback error: {e}")
                self.current = None
                self.next.set()
                continue

            # Send now playing message and store it
            await self._send_now_playing()
            
            # Wait for song to finish
            await self.next.wait()
            
            # Clear the now playing message reference
            self.now_playing_message = None
            self.now_playing_message_id = None
            self.current = None
            self.current_source = None

    async def update_countdown(self):
        """Background task to update the countdown every second"""
        await self.bot.wait_until_ready()
        
        while not self.bot.is_closed():
            try:
                await asyncio.sleep(1)  # Update every second
                
                # If there's a now playing message and a current song
                if self.now_playing_message and self.current and self.current_source:
                    # Calculate time remaining
                    elapsed = time.time() - self.current_source.start_time
                    total = self.current_source.duration
                    remaining = max(0, total - elapsed)
                    
                    # Create progress bar
                    progress = self._create_progress_bar(elapsed, total)
                    
                    # Create updated embed with more details
                    embed = discord.Embed(
                        title="▶️ Now Playing",
                        color=discord.Color.green()
                    )
                    
                    # Add video title as main description
                    embed.description = f"**{self.current.title}**"
                    
                    # Add YouTube link field
                    embed.add_field(name="YouTube Link", value=f"[Click here]({self.current.webpage_url})", inline=True)
                    
                    # Add uploader/author
                    uploader_display = f"[{self.current.uploader}]({self.current_source.uploader_url})" if self.current_source.uploader_url else self.current.uploader
                    embed.add_field(name="Uploader", value=uploader_display, inline=True)
                    
                    # Add requester
                    embed.add_field(name="Requested by", value=self.current.requester.mention, inline=True)
                    
                    # Show countdown with progress bar
                    time_display = f"{progress} `{self._format_time(remaining)} / {self._format_time(total)}`"
                    embed.add_field(name="Duration", value=time_display, inline=False)
                    
                    # Show queue below if there are songs waiting
                    if self._queue_list:
                        lines = []
                        for i, e in enumerate(self._queue_list[:5], 1):
                            lines.append(f"`{i}.` **{e.title}** — by {e.requester.display_name}")
                        if len(self._queue_list) > 5:
                            lines.append(f"*...and {len(self._queue_list) - 5} more*")
                        embed.add_field(name="Up Next", value="\n".join(lines), inline=False)
                    
                    # Edit the message
                    try:
                        await self.now_playing_message.edit(embed=embed)
                    except:
                        # Message was deleted or something went wrong
                        self.now_playing_message = None
                        self.now_playing_message_id = None
                        
            except Exception as e:
                print(f"❌ Countdown update error in {self.guild_name}: {e}")
                await asyncio.sleep(5)  # Wait longer if there's an error

    def _create_progress_bar(self, elapsed, total, length=20):
        """Create a text progress bar"""
        if total <= 0:
            return "█" * length + "░" * 0
        
        progress = min(1.0, elapsed / total)
        filled = int(length * progress)
        bar = "█" * filled + "░" * (length - filled)
        return bar

    def _format_time(self, seconds):
        """Format seconds into MM:SS or HH:MM:SS"""
        if seconds is None:
            return "LiveStream"
        try:
            s = int(seconds)
            h, s = divmod(s, 3600)
            m, s = divmod(s, 60)
            if h > 0:
                return f"{h}:{m:02d}:{s:02d}"
            else:
                return f"{m}:{s:02d}"
        except:
            return "Unknown"

    async def _song_done(self, error=None):
        self.next.set()

    async def _send_now_playing(self):
        if not self.current:
            return
        
        # Initial embed with full details
        embed = discord.Embed(
            title="▶️ Now Playing",
            color=discord.Color.green()
        )
        
        # Add video title as main description
        embed.description = f"**{self.current.title}**"
        
        # Add YouTube link field
        embed.add_field(name="YouTube Link", value=f"[Click here]({self.current.webpage_url})", inline=True)
        
        # Add uploader/author
        embed.add_field(name="Uploader", value=self.current.uploader, inline=True)
        
        # Add requester
        embed.add_field(name="Requested by", value=self.current.requester.mention, inline=True)
        
        # Initial duration (will be updated by countdown)
        embed.add_field(name="Duration", value=self._format_time(self.current.duration), inline=False)

        if self._queue_list:
            lines = []
            for i, e in enumerate(self._queue_list[:5], 1):
                lines.append(f"`{i}.` **{e.title}** — by {e.requester.display_name}")
            if len(self._queue_list) > 5:
                lines.append(f"*...and {len(self._queue_list) - 5} more*")
            embed.add_field(name="Up Next", value="\n".join(lines), inline=False)

        # Send the message and store it
        self.now_playing_message = await self.channel.send(embed=embed)
        self.now_playing_message_id = self.now_playing_message.id

    async def add(self, entry: QueueEntry):
        self._queue_list.append(entry)
        await self.queue.put(entry)

    def remove_by_user(self, user_id):
        for entry in list(self._queue_list):
            if entry.requester.id == user_id:
                self._queue_list.remove(entry)
                new_q = asyncio.Queue()
                for e in self._queue_list:
                    new_q.put_nowait(e)
                self.queue = new_q
                return entry
        return None

    async def stop_current(self, user_id):
        if not self.current:
            return False
        if self.current.requester.id != user_id:
            return False
        vc = self._get_vc()
        if vc and vc.is_playing():
            vc.stop()
        return True

    async def destroy(self):
        # Cancel the countdown task
        if hasattr(self, 'countdown_task') and not self.countdown_task.done():
            self.countdown_task.cancel()
        
        vc = self._get_vc()
        if vc:
            try:
                if vc.is_playing():
                    vc.stop()
                await asyncio.wait_for(vc.disconnect(force=False), timeout=3.0)
            except Exception:
                try:
                    await vc.disconnect(force=True)
                except Exception:
                    pass

        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        self._queue_list.clear()
        self.current = None
        self.current_source = None
        self._voice_client = None
        self.now_playing_message = None
        self.now_playing_message_id = None

        if hasattr(self, 'task') and not self.task.done():
            self.task.cancel()

        music_cog = self.bot.get_cog('Music')
        if music_cog and hasattr(music_cog, 'music_players'):
            if self.guild_id in music_cog.music_players:
                del music_cog.music_players[self.guild_id]


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.music_players = {}
        self.processed_msg_ids = set()
        self.processed_commands = {}
        print(f"✅ Music cog initialized (ID: {id(self)})")

    # ===== DUPLICATE PREVENTION =====
    async def check_duplicate(self, ctx):
        key = f"{ctx.author.id}:{ctx.command.name}"
        current_time = time.time()
        
        if key in self.processed_commands:
            if current_time - self.processed_commands[key] < 3:
                return True
        
        self.processed_commands[key] = current_time
        
        if len(self.processed_commands) > 100:
            to_delete = [k for k, t in self.processed_commands.items() if current_time - t > 10]
            for k in to_delete:
                del self.processed_commands[k]
        
        return False

    # ===== HELPER FUNCTIONS =====

    def get_player(self, ctx) -> MusicPlayer:
        gid = ctx.guild.id
        if gid not in self.music_players:
            vc = ctx.voice_client
            self.music_players[gid] = MusicPlayer(ctx, vc, self.bot)
        else:
            p = self.music_players[gid]
            if ctx.voice_client and ctx.voice_client.is_connected():
                p._voice_client = ctx.voice_client
        return self.music_players[gid]

    def check_channel(self, ctx):
        return ctx.channel.name == BOT_CHANNEL

    async def ensure_voice(self, ctx):
        if not ctx.author.voice:
            await ctx.send("❌ You need to join a voice channel first!")
            return None

        channel = ctx.author.voice.channel
        perms = channel.permissions_for(ctx.guild.me)
        
        if not perms.connect:
            await ctx.send("❌ I don't have permission to join that voice channel!")
            return None
        if not perms.speak:
            await ctx.send("❌ I don't have permission to speak in that voice channel!")
            return None

        if ctx.voice_client and ctx.voice_client.is_connected():
            if ctx.voice_client.channel == channel:
                return ctx.voice_client
            else:
                await ctx.voice_client.move_to(channel)
                await asyncio.sleep(1)
                return ctx.voice_client

        try:
            vc = await channel.connect(timeout=20.0, reconnect=True, self_deaf=True)
            await asyncio.sleep(1)
            return vc
        except asyncio.TimeoutError:
            await ctx.send("❌ Connection timed out. Please try again.")
            return None
        except Exception as e:
            await ctx.send(f"❌ Failed to connect: {str(e)}")
            return None

    async def extract_info(self, url: str):
        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(
                None, lambda: ytdl.extract_info(url, download=False)
            )
            if data is None:
                return None
            if 'entries' in data:
                data = data['entries'][0]
            return data
        except Exception as e:
            print(f"❌ extract_info error: {e}")
            return None

    # ===== COMMANDS =====

    @commands.command(name='play', aliases=['p'])
    async def play(self, ctx, *, url: str = None):
        if await self.check_duplicate(ctx):
            return

        if ctx.message.id in self.processed_msg_ids:
            return
        self.processed_msg_ids.add(ctx.message.id)
        if len(self.processed_msg_ids) > 1000:
            self.processed_msg_ids = set(list(self.processed_msg_ids)[-500:])

        if not self.check_channel(ctx):
            await ctx.send(f"❌ Music commands only work in #{BOT_CHANNEL}!")
            return

        if not url:
            await ctx.send("❌ Please provide a YouTube link!")
            return

        if not re.match(r'https?://', url):
            await ctx.send("❌ Please paste a full YouTube URL.")
            return

        vc = await self.ensure_voice(ctx)
        if not vc:
            return

        status = await ctx.send("🎵 Loading music...")
        data = await self.extract_info(url)

        if not data:
            await status.edit(content="❌ Couldn't load that video.")
            return

        entry = QueueEntry(data=data, requester=ctx.author, original_url=url)
        player = self.get_player(ctx)

        await player.add(entry)
        position = len(player._queue_list)

        if player.current is None and position == 1:
            await status.delete()
        else:
            await status.delete()
            
            embed = discord.Embed(
                title="✅ Added to Queue",
                description=f"Your music will be played after the current song.",
                color=discord.Color.blue()
            )
            
            # Song details
            embed.add_field(name="Song", value=f"**{entry.title}**", inline=False)
            embed.add_field(name="Position", value=f"#{position} in queue", inline=True)
            
            # Make duration clickable if there's a now playing message
            if player.now_playing_message_id:
                jump_url = f"https://discord.com/channels/{ctx.guild.id}/{ctx.channel.id}/{player.now_playing_message_id}"
                embed.add_field(name="Duration", value=f"[{player._format_time(entry.duration)}]({jump_url})", inline=True)
            else:
                embed.add_field(name="Duration", value=player._format_time(entry.duration), inline=True)
            
            # Queue display
            current_line = (
                f"[CURRENT] **{player.current.title}** — by {player.current.requester.display_name}"
                if player.current else "[CURRENT] *loading...*"
            )
            queue_lines = []
            for i, e in enumerate(player._queue_list, 1):
                queue_lines.append(f"`{i}.` **{e.title}** — by {e.requester.display_name}")
            
            embed.add_field(
                name="Queue",
                value=current_line + "\n" + "\n".join(queue_lines[:5]) if queue_lines else current_line,
                inline=False
            )
            
            await ctx.send(embed=embed)

    @commands.command(name='stop')
    async def stop(self, ctx):
        if await self.check_duplicate(ctx):
            return

        if not self.check_channel(ctx):
            await ctx.send(f"❌ Use #{BOT_CHANNEL} for music commands!")
            return

        gid = ctx.guild.id
        if gid not in self.music_players:
            await ctx.send("❌ Nothing is playing right now!")
            return

        player = self.music_players[gid]

        if await player.stop_current(ctx.author.id):
            await ctx.send(f"⏭️ Your song was skipped, moving to the next one.")
            return

        removed = player.remove_by_user(ctx.author.id)
        if removed:
            await ctx.send(f"🗑️ Removed **{removed.title}** from the queue.")
            return

        await ctx.send("❌ You don't have any songs in the queue right now.")

    @commands.command(name='skip', aliases=['s'])
    async def skip(self, ctx):
        """Skip the currently playing song (staff only) or vote to skip your own song."""
        if await self.check_duplicate(ctx):
            return

        if not self.check_channel(ctx):
            await ctx.send(f"❌ Use #{BOT_CHANNEL} for music commands!")
            return

        gid = ctx.guild.id
        if gid not in self.music_players:
            await ctx.send("❌ Nothing is playing right now!")
            return

        player = self.music_players[gid]

        if not player.current:
            await ctx.send("❌ Nothing is currently playing!")
            return

        is_staff = any(r.name == STAFF_ROLE for r in ctx.author.roles)

        # Staff can skip any song
        if is_staff:
            vc = player._get_vc()
            if vc and vc.is_playing():
                vc.stop()
            await ctx.send(f"⏭️ **{player.current.title}** was skipped by staff.")
            return

        # Regular users can only skip their own song
        if player.current.requester.id == ctx.author.id:
            vc = player._get_vc()
            if vc and vc.is_playing():
                vc.stop()
            await ctx.send(f"⏭️ You skipped your own song: **{player.current.title}**")
            return

        await ctx.send(
            f"❌ You can only skip your own song! "
            f"This song was requested by {player.current.requester.mention}."
        )

    @commands.command(name='stopall')
    async def stopall(self, ctx):
        if await self.check_duplicate(ctx):
            return

        if not self.check_channel(ctx):
            await ctx.send(f"❌ Use #{BOT_CHANNEL} for music commands!")
            return

        has_role = any(r.name == STAFF_ROLE for r in ctx.author.roles)
        if not has_role:
            await ctx.send(f"❌ You need the **{STAFF_ROLE}** role to use `stopall`.")
            return

        gid = ctx.guild.id
        if gid not in self.music_players:
            await ctx.send("❌ Nothing is playing right now!")
            return

        await self.music_players[gid].destroy()
        await ctx.send("⏹️ Stopped all music and cleared the queue.")

    @commands.command(name='queue', aliases=['q'])
    async def queue_cmd(self, ctx):
        if await self.check_duplicate(ctx):
            return

        if not self.check_channel(ctx):
            await ctx.send(f"❌ Use #{BOT_CHANNEL} for music commands!")
            return

        gid = ctx.guild.id
        if gid not in self.music_players:
            await ctx.send("📭 The queue is empty.")
            return

        player = self.music_players[gid]

        if not player.current and not player._queue_list:
            await ctx.send("📭 The queue is empty.")
            return

        embed = discord.Embed(title="🎵 Music Queue", color=discord.Color.blurple())

        if player.current:
            embed.add_field(
                name="▶️ CURRENT",
                value=(
                    f"**{player.current.title}**\n"
                    f"Requested by {player.current.requester.mention}"
                ),
                inline=False
            )

        if player._queue_list:
            lines = []
            for i, e in enumerate(player._queue_list[:15], 1):
                lines.append(f"`{i}.` **{e.title}** — by {e.requester.display_name}")
            if len(player._queue_list) > 15:
                lines.append(f"*...and {len(player._queue_list) - 15} more*")
            embed.add_field(name="Up Next", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Up Next", value="*Queue is empty after this song.*", inline=False)

        await ctx.send(embed=embed)

    @commands.command(name='leave', aliases=['disconnect', 'dc'])
    async def leave(self, ctx):
        if await self.check_duplicate(ctx):
            return

        if not self.check_channel(ctx):
            await ctx.send(f"❌ Use #{BOT_CHANNEL} for music commands!")
            return

        is_staff = any(r.name == STAFF_ROLE for r in ctx.author.roles)

        gid = ctx.guild.id
        if gid in self.music_players:
            player = self.music_players[gid]

            # Only the requester of the current song or staff can disconnect
            is_requester = player.current and player.current.requester.id == ctx.author.id

            if not is_staff and not is_requester:
                requester_mention = player.current.requester.mention if player.current else "someone else"
                await ctx.send(
                    f"❌ Only {requester_mention} (who started the music) "
                    f"or a staff member can disconnect the bot!"
                )
                return

            await player.destroy()
            await ctx.send("👋 Disconnected.")

        elif ctx.voice_client:
            # Bot is in VC but no active player — staff only
            if not is_staff:
                await ctx.send(
                    f"❌ Only staff members can disconnect the bot when no music is playing!"
                )
                return
            try:
                await ctx.voice_client.disconnect()
                await ctx.send("👋 Disconnected.")
            except Exception as e:
                await ctx.send(f"❌ Error disconnecting: {e}")
        else:
            await ctx.send("❌ I'm not in a voice channel!")

    @commands.command(name='nowplaying', aliases=['np'])
    async def nowplaying(self, ctx):
        if await self.check_duplicate(ctx):
            return

        if not self.check_channel(ctx):
            await ctx.send(f"❌ Use #{BOT_CHANNEL} for music commands!")
            return

        gid = ctx.guild.id
        if gid not in self.music_players or not self.music_players[gid].current:
            await ctx.send("❌ Nothing is playing right now.")
            return

        player = self.music_players[gid]
        current = player.current

        embed = discord.Embed(
            title="▶️ Now Playing",
            color=discord.Color.green()
        )
        
        embed.description = f"**{current.title}**"
        embed.add_field(name="YouTube Link", value=f"[Click here]({current.webpage_url})", inline=True)
        embed.add_field(name="Uploader", value=current.uploader, inline=True)
        embed.add_field(name="Requested by", value=current.requester.mention, inline=True)
        
        # If we have a current source with start time, show live countdown
        if player.current_source and player.current_source.start_time:
            elapsed = time.time() - player.current_source.start_time
            total = player.current_source.duration
            remaining = max(0, total - elapsed)
            progress = player._create_progress_bar(elapsed, total)
            time_display = f"{progress} `{player._format_time(remaining)} / {player._format_time(total)}`"
            embed.add_field(name="Duration", value=time_display, inline=False)
        else:
            embed.add_field(name="Duration", value=player._format_time(current.duration), inline=False)
            
        await ctx.send(embed=embed)

    @commands.command(name='music')
    async def music_help(self, ctx):
        if await self.check_duplicate(ctx):
            return

        embed = discord.Embed(
            title="🎵 Music Commands",
            description=f"All commands must be used in **#{BOT_CHANNEL}**",
            color=discord.Color.blurple()
        )
        embed.add_field(
            name="!play [youtube link]",
            value=(
                "Join a voice channel first, then paste a YouTube link.\n"
                "Example: `!play https://www.youtube.com/watch?v=BXzCuvAJLps`"
            ),
            inline=False
        )
        embed.add_field(
            name="!stop",
            value="Remove **your** song from the queue, or skip it if it's currently playing.",
            inline=False
        )
        embed.add_field(
            name=f"!stopall  *(requires {STAFF_ROLE})*",
            value="Stop all songs, clear the queue, and disconnect the bot.",
            inline=False
        )
        embed.add_field(
            name="!queue / !q",
            value="Show the current song and everything waiting in the queue.",
            inline=False
        )
        embed.add_field(
            name="!nowplaying / !np",
            value="Show what's currently playing (with live countdown!).",
            inline=False
        )
        embed.add_field(
            name="!leave / !dc",
            value="Disconnect the bot from voice.",
            inline=False
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Music(bot))
