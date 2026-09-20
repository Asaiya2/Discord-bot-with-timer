import discord
from discord.ext import commands
import sqlite3
import time
import os
import asyncio
import random
import re
from datetime import datetime

# ===== CONFIGURATION =====
DB_FOLDER = r"C:\Users\Kelly\Desktop\discord database"
MAIN_DB_PATH = os.path.join(DB_FOLDER, "asaiya_bot.db")

STORAGE_SERVER_ID  = 1484265140215087235
VAULT_CHANNEL_NAME = "asaiya-vault"
STAFF_ROLES        = ["AsaiyaBot", "AsaiyaKick", "AsaiyaBan", "AsaiyaPass", "AsaiyaClear", "asaiya-support"]
OWNER_SERVER_ID    = 1484265140215087235
BOT_ROLE           = "AsaiyaBot"


# ──────────────────────────────────────────────────────────────────────────────
# STANDALONE HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _detect_media_type(url: str, content_type: str = "") -> str:
    """Return 'gif' | 'image' | 'unknown'."""
    lower = url.lower().split("?")[0]
    ct    = content_type.lower()

    # Check for GIFs first
    if ct == "image/gif" or lower.endswith(".gif"):
        return "gif"
    if "tenor.com" in lower or "giphy.com" in lower:
        return "gif"

    image_exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".avif")
    if ct.startswith("image/") or any(lower.endswith(e) for e in image_exts):
        return "image"

    return "unknown"


# ──────────────────────────────────────────────────────────────────────────────

class MediaVault(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.processed_commands = {}
        self.setup_database()
        print("✅ MediaVault cog initialized")

    # ── DATABASE ──────────────────────────────────────────────────────────────

    def setup_database(self):
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()

            # Check if media_vault table exists
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='media_vault'")
            table_exists = c.fetchone()
            
            if not table_exists:
                # Create new table with keyword column
                c.execute("""
                    CREATE TABLE media_vault (
                        id           INTEGER PRIMARY KEY AUTOINCREMENT,
                        media_type   TEXT NOT NULL,
                        url          TEXT NOT NULL,
                        saved_by     TEXT NOT NULL,
                        saved_by_id  TEXT NOT NULL,
                        saved_at     REAL NOT NULL,
                        vault_msg_id TEXT,
                        keyword      TEXT
                    )
                """)
                print("✅ Created media_vault table with keyword column")
            else:
                # Check if keyword column exists, add it if not
                c.execute("PRAGMA table_info(media_vault)")
                columns = [col[1] for col in c.fetchall()]
                
                if 'keyword' not in columns:
                    c.execute("ALTER TABLE media_vault ADD COLUMN keyword TEXT")
                    print("✅ Added 'keyword' column to media_vault table")
                else:
                    print("✅ 'keyword' column already exists in media_vault")
            
            # Create index for faster keyword lookups
            c.execute("CREATE INDEX IF NOT EXISTS idx_keyword ON media_vault(keyword)")

            c.execute("""
                CREATE TABLE IF NOT EXISTS vault_config (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            conn.commit()
            conn.close()
            
            # Drop old keyword tables if they exist (cleanup)
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            try:
                c.execute("DROP TABLE IF EXISTS saved_images")
                c.execute("DROP TABLE IF EXISTS saved_gifs")
                conn.commit()
                print("✅ Cleaned up old keyword tables")
            except:
                pass
            conn.close()
            
            print("✅ MediaVault database initialized")
        except Exception as e:
            print(f"❌ [MediaVault] setup_database error: {e}")

    # ── HELPERS ───────────────────────────────────────────────────────────────

    async def check_duplicate(self, ctx):
        key  = f"{ctx.author.id}:{ctx.command.name}"
        now  = time.time()
        last = self.processed_commands.get(key, 0)
        if now - last < 3:
            return True
        self.processed_commands[key] = now
        if len(self.processed_commands) > 100:
            self.processed_commands = {k: v for k, v in self.processed_commands.items() if now - v <= 10}
        return False

    def is_staff(self, member):
        if not isinstance(member, discord.Member):
            return False
        return any(r.name in STAFF_ROLES for r in member.roles)

    def is_owner_server(self, ctx):
        if not ctx.guild or ctx.guild.id != OWNER_SERVER_ID:
            return False
        return isinstance(ctx.author, discord.Member) and any(r.name == BOT_ROLE for r in ctx.author.roles)

    async def get_vault_channel(self):
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT value FROM vault_config WHERE key = 'vault_channel_id'")
            row = c.fetchone()
            conn.close()
            if row and row[0]:
                guild = self.bot.get_guild(STORAGE_SERVER_ID)
                if guild:
                    ch = guild.get_channel(int(row[0]))
                    if ch:
                        return ch
        except Exception as e:
            print(f"[MediaVault] get_vault_channel error: {e}")
        guild = self.bot.get_guild(STORAGE_SERVER_ID)
        if not guild:
            return None
        return discord.utils.get(guild.text_channels, name=VAULT_CHANNEL_NAME)

    # ── VAULT DB QUERIES ─────────────────────────────────────────────────────

    def _get_all_entries(self, media_type: str = None):
        """Get all entries, optionally filtered by media_type"""
        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()
        if media_type:
            c.execute(
                "SELECT id, url, saved_by, saved_by_id, saved_at, vault_msg_id, keyword "
                "FROM media_vault WHERE media_type=? ORDER BY id ASC",
                (media_type,)
            )
        else:
            c.execute(
                "SELECT id, url, saved_by, saved_by_id, saved_at, vault_msg_id, keyword "
                "FROM media_vault ORDER BY id ASC"
            )
        rows = c.fetchall()
        conn.close()
        return rows

    def _get_entry_by_number(self, media_type: str, number: int):
        rows = self._get_all_entries(media_type)
        if 1 <= number <= len(rows):
            return rows[number - 1]
        return None

    def _get_next_id(self, media_type: str) -> int:
        return len(self._get_all_entries(media_type)) + 1

    def _update_vault_msg_id(self, db_id: int, msg_id: int):
        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE media_vault SET vault_msg_id=? WHERE id=?", (str(msg_id), db_id))
        conn.commit()
        conn.close()

    def _get_entry_by_keyword(self, keyword: str):
        """Find media by keyword (case-insensitive)"""
        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()
        c.execute(
            "SELECT id, media_type, url, saved_by, saved_by_id, saved_at, vault_msg_id, keyword "
            "FROM media_vault WHERE LOWER(keyword) = LOWER(?)",
            (keyword,)
        )
        row = c.fetchone()
        conn.close()
        return row

    def _update_keyword(self, media_id: int, keyword: str):
        """Update keyword for a media entry"""
        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE media_vault SET keyword=? WHERE id=?", (keyword, media_id))
        conn.commit()
        conn.close()

    def _remove_keyword_from_old(self, keyword: str):
        """Remove keyword from any existing entry that has it (for replacement)"""
        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE media_vault SET keyword=NULL WHERE LOWER(keyword)=LOWER(?)", (keyword,))
        conn.commit()
        conn.close()

    def _delete_entry(self, media_id: int):
        """Delete entry from database"""
        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM media_vault WHERE id=?", (media_id,))
        conn.commit()
        conn.close()

    def _delete_all_entries(self, media_type: str):
        """Delete all entries of a specific media type and return their vault_msg_ids"""
        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()
        # Get all vault_msg_ids to delete from channel
        c.execute("SELECT vault_msg_id FROM media_vault WHERE media_type=?", (media_type,))
        msg_ids = [row[0] for row in c.fetchall() if row[0]]
        # Delete all entries
        c.execute("DELETE FROM media_vault WHERE media_type=?", (media_type,))
        conn.commit()
        conn.close()
        return msg_ids

    def _get_random_entry(self, media_type: str):
        """Get a random entry of specified media type"""
        rows = self._get_all_entries(media_type)
        if rows:
            return random.choice(rows)
        return None

    def _type_display(self, media_type: str):
        """Returns (emoji, singular_label, cmd_prefix)."""
        return {
            "image": ("🖼️", "Image", "img"),
            "gif":   ("🎞️", "GIF",   "gif"),
        }.get(media_type, ("📎", media_type.title(), media_type))

    # ── MEDIA EXTRACTION ─────────────────────────────────────────────────────

    async def _extract_media(self, message: discord.Message):
        """
        Pull media out of a Discord message.
        Priority: 
        1. Original URL from message content
        2. File attachments
        3. Embeds
        Returns (url, media_type).
        """
        # FIRST: Check message content for URLs
        parts = message.content.strip().split()
        for part in parts:
            if part.startswith("http"):
                if "giphy.com" in part.lower() or "tenor.com" in part.lower():
                    return part, "gif"
                mtype = _detect_media_type(part)
                if mtype != "unknown":
                    return part, mtype
                return part, "image"

        # SECOND: File attachments
        if message.attachments:
            att = message.attachments[0]
            ct = att.content_type or ""
            mtype = _detect_media_type(att.url, ct)
            if mtype == "unknown":
                fname = att.filename.lower()
                if fname.endswith(".gif"):
                    mtype = "gif"
                else:
                    mtype = "image"
            return att.url, mtype

        # THIRD: Embeds
        if message.embeds:
            em = message.embeds[0]
            url = None
            if em.image and em.image.url:
                url = em.image.url
            elif em.thumbnail and em.thumbnail.url:
                url = em.thumbnail.url
            if url:
                mtype = _detect_media_type(url)
                if "tenor" in url.lower() or "giphy" in url.lower():
                    mtype = "gif"
                return url, mtype if mtype != "unknown" else "image"

        return None, None

    # ── CORE SAVE (vault) ────────────────────────────────────────────────────

    async def _do_save(self, ctx, url: str, media_type: str, keyword: str = None):
        vault_ch = await self.get_vault_channel()
        if not vault_ch:
            await ctx.send(f"❌ Vault channel not found. Run `!vaultsetup` in server `{STORAGE_SERVER_ID}`.")
            return

        # If keyword provided, remove it from any existing media
        if keyword:
            self._remove_keyword_from_old(keyword)

        number            = self._get_next_id(media_type)
        emoji, label, pfx = self._type_display(media_type)
        retrieve_cmd      = f"!{pfx} {number}"
        saved_by_str      = (
            f"{ctx.author.name}#{ctx.author.discriminator}"
            if ctx.author.discriminator != "0" else ctx.author.name
        )

        conn = sqlite3.connect(MAIN_DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT INTO media_vault (media_type, url, saved_by, saved_by_id, saved_at, keyword) VALUES (?,?,?,?,?,?)",
            (media_type, url, saved_by_str, str(ctx.author.id), time.time(), keyword)
        )
        db_id = c.lastrowid
        conn.commit()
        conn.close()

        header = f"{emoji} **{label} #{number}** | Saved by **{saved_by_str}** | Use: `{retrieve_cmd}`"
        
        if media_type == "gif":
            await vault_ch.send(url)
            vault_msg = await vault_ch.send(header)
        else:
            embed = discord.Embed(title=f"{label} #{number}", color=discord.Color.blurple())
            embed.set_image(url=url)
            embed.set_footer(text=f"Saved by {saved_by_str} | Use: {retrieve_cmd}")
            vault_msg = await vault_ch.send(content=header, embed=embed)

        self._update_vault_msg_id(db_id, vault_msg.id)

        # Create confirmation embed
        embed = discord.Embed(title=f"{emoji} {label} Saved!", color=discord.Color.green(), timestamp=datetime.utcnow())
        embed.add_field(name="Number",        value=f"`#{number}`",      inline=True)
        embed.add_field(name="Retrieve with", value=f"`{retrieve_cmd}`", inline=True)
        embed.add_field(name="Saved by",      value=ctx.author.mention,  inline=True)
        if keyword:
            embed.add_field(name="Keyword",   value=f"`{keyword}`",      inline=True)
        if media_type == "image":
            embed.set_image(url=url)
        embed.set_footer(text="Stored in owner vault server")
        await ctx.send(embed=embed)

    # ── CORE SEND (vault) ────────────────────────────────────────────────────

    async def _send_media(self, ctx, media_type: str, number: int):
        if await self.check_duplicate(ctx):
            return
        row = self._get_entry_by_number(media_type, number)
        if not row:
            await ctx.send(f"❌ No {media_type} #{number} found.")
            return
        db_id, url, saved_by, saved_by_id, saved_at, vault_msg_id, keyword = row
        emoji, label, pfx = self._type_display(media_type)

        if media_type == "gif":
            await ctx.send(url)
        else:
            ts = datetime.fromtimestamp(saved_at).strftime("%Y-%m-%d")
            embed = discord.Embed(
                title=f"{emoji} {label} #{number}",
                color=discord.Color.blurple(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Saved by", value=saved_by, inline=True)
            embed.add_field(name="Saved on", value=ts, inline=True)
            embed.set_image(url=url)
            await ctx.send(embed=embed)

    # ── CORE DELETE (vault) ───────────────────────────────────────────────────

    async def _delete_media(self, ctx, media_type: str, number: int):
        if await self.check_duplicate(ctx):
            return
        all_entries = self._get_all_entries(media_type)
        if not (1 <= number <= len(all_entries)):
            await ctx.send(f"❌ No {media_type} #{number} found.")
            return

        target      = all_entries[number - 1]
        target_id   = target[0]
        target_url  = target[1]
        target_by   = target[2]
        target_vmid = target[5]
        emoji, label, pfx = self._type_display(media_type)

        vault_ch = await self.get_vault_channel()
        if vault_ch and target_vmid:
            try:
                msg = await vault_ch.fetch_message(int(target_vmid))
                await msg.delete()
                if media_type == "gif":
                    try:
                        url_msg = await vault_ch.fetch_message(int(target_vmid) - 1)
                        await url_msg.delete()
                    except:
                        pass
            except Exception as e:
                print(f"[MediaVault] vault delete error: {e}")

        self._delete_entry(target_id)

        remaining = self._get_all_entries(media_type)
        updated = 0
        if vault_ch:
            for idx, entry in enumerate(remaining, start=1):
                old_mid = entry[5]
                if old_mid:
                    try:
                        msg = await vault_ch.fetch_message(int(old_mid))
                        if media_type == "gif":
                            new_header = f"{emoji} **{label} #{idx}** | Saved by **{entry[2]}** | Use: `!{pfx} {idx}`"
                            await msg.edit(content=new_header)
                        else:
                            embed = discord.Embed(title=f"{label} #{idx}", color=discord.Color.blurple())
                            embed.set_image(url=entry[1])
                            embed.set_footer(text=f"Saved by {entry[2]} | Use: !{pfx} {idx}")
                            await msg.edit(content=f"{emoji} **{label} #{idx}** | Saved by **{entry[2]}** | Use: `!{pfx} {idx}`", embed=embed)
                        updated += 1
                        await asyncio.sleep(0.1)
                    except discord.NotFound:
                        pass
                    except Exception as e:
                        print(f"[MediaVault] renumber error: {e}")

        embed = discord.Embed(
            title=f"{emoji} {label} Deleted",
            description=f"Deleted **{label} #{number}**",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Saved by", value=target_by,                     inline=True)
        embed.add_field(name="URL",      value=f"[Click here]({target_url})", inline=True)
        if updated:
            embed.add_field(name="Renumbered", value=f"{updated} item(s)", inline=False)
        embed.set_footer(text=f"Deleted by {ctx.author}")
        await ctx.send(embed=embed)

    # ── CORE CLEAR ALL (vault) ─────────────────────────────────────────────────

    async def _clear_all_media(self, ctx, media_type: str):
        """Delete all media of a specific type"""
        if await self.check_duplicate(ctx):
            return
        
        rows = self._get_all_entries(media_type)
        if not rows:
            await ctx.send(f"❌ No {media_type}s saved to clear.")
            return
        
        emoji, label, pfx = self._type_display(media_type)
        count = len(rows)
        
        # Confirm with user
        confirm_msg = await ctx.send(f"⚠️ Are you sure you want to delete **ALL {count} {label.upper()}S**? This cannot be undone.\nReply with `yes` to confirm or `no` to cancel.")
        
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in ['yes', 'no']
        
        try:
            response = await self.bot.wait_for('message', timeout=30.0, check=check)
            if response.content.lower() != 'yes':
                await ctx.send(f"✅ Cancelled. No {label.lower()}s were deleted.")
                await confirm_msg.delete()
                await response.delete()
                return
            await response.delete()
        except asyncio.TimeoutError:
            await ctx.send(f"⏰ Timed out. No {label.lower()}s were deleted.")
            await confirm_msg.delete()
            return
        
        await confirm_msg.delete()
        
        # Get all vault message IDs to delete
        msg_ids = self._delete_all_entries(media_type)
        
        # Delete messages from vault channel
        vault_ch = await self.get_vault_channel()
        deleted_count = 0
        if vault_ch and msg_ids:
            for msg_id in msg_ids:
                if msg_id:
                    try:
                        msg = await vault_ch.fetch_message(int(msg_id))
                        await msg.delete()
                        deleted_count += 1
                        # For GIFs, also delete the URL message (one ID before)
                        if media_type == "gif":
                            try:
                                url_msg = await vault_ch.fetch_message(int(msg_id) - 1)
                                await url_msg.delete()
                            except:
                                pass
                        await asyncio.sleep(0.2)  # Rate limit protection
                    except discord.NotFound:
                        pass
                    except Exception as e:
                        print(f"[MediaVault] clear delete error: {e}")
        
        embed = discord.Embed(
            title=f"{emoji} All {label.upper()}S Cleared!",
            description=f"Deleted **{count}** {label.lower()}s from the vault.",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Cleared by", value=ctx.author.mention, inline=True)
        embed.add_field(name="Channel messages deleted", value=f"{deleted_count}", inline=True)
        embed.set_footer(text="All associated keywords have also been removed")
        await ctx.send(embed=embed)

    # ── CORE LIST (vault) ─────────────────────────────────────────────────────

    async def _list_media(self, ctx, media_type: str):
        if await self.check_duplicate(ctx):
            return
        rows = self._get_all_entries(media_type)
        emoji, label, pfx = self._type_display(media_type)
        label_pl = label + "s"
        if not rows:
            await ctx.send(f"{emoji} No {label_pl.lower()} saved yet.")
            return
        pages = [rows[i:i+10] for i in range(0, len(rows), 10)]
        for pnum, page in enumerate(pages, 1):
            embed = discord.Embed(
                title=f"{emoji} Saved {label_pl} — Page {pnum}/{len(pages)}",
                color=discord.Color.blurple(),
                timestamp=datetime.utcnow()
            )
            for idx, (db_id, url, saved_by, saved_by_id, saved_at, vault_msg_id, keyword) in enumerate(page, 1):
                actual = (pnum - 1) * 10 + idx
                ts = datetime.fromtimestamp(saved_at).strftime("%Y-%m-%d")
                value = f"Saved by **{saved_by}** on {ts}\n[Link]({url})"
                if keyword:
                    value += f"\n🔑 Keyword: `{keyword}`"
                embed.add_field(
                    name=f"#{actual}  |  !{pfx} {actual}",
                    value=value,
                    inline=False
                )
            embed.set_footer(text=f"Total {label_pl}: {len(rows)}")
            await ctx.send(embed=embed)

    # ══════════════════════════════════════════════════════════════════════════
    # COMMANDS — VAULT
    # ══════════════════════════════════════════════════════════════════════════

    @commands.command(name="save")
    async def save(self, ctx, *, keyword: str = None):
        """
        Save an image or GIF to the vault.
        
        Usage:
          • Reply to a message with media: !save
          • Reply with a keyword: !save funny cat
          • Direct URL: !save https://example.com/image.jpg
          • Direct URL with keyword: !save funny cat https://example.com/gif.gif
        """
        if await self.check_duplicate(ctx):
            return
        if not self.is_staff(ctx.author):
            await ctx.send("❌ Only staff can save media.")
            return

        # Check if the keyword argument might contain a URL
        url_from_keyword = None
        if keyword:
            # Check if the keyword string contains a URL
            parts = keyword.split()
            for part in parts:
                if part.startswith("http"):
                    url_from_keyword = part
                    # Remove the URL from keyword
                    keyword = ' '.join([p for p in parts if not p.startswith("http")]).strip()
                    if not keyword:
                        keyword = None
                    break

        source = ctx.message
        if ctx.message.reference:
            try:
                source = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            except Exception:
                pass

        url, media_type = await self._extract_media(source)

        # If no media found in replied message, check if there's a URL in the command
        if not url and url_from_keyword:
            url = url_from_keyword
            if "giphy.com" in url.lower() or "tenor.com" in url.lower():
                media_type = "gif"
            else:
                media_type = _detect_media_type(url)
                if media_type == "unknown":
                    media_type = "image"

        # If still no URL, check if the command has a URL as argument
        if not url and keyword and not url_from_keyword:
            # Maybe the keyword is actually a URL
            if keyword.startswith("http"):
                url = keyword
                keyword = None
                if "giphy.com" in url.lower() or "tenor.com" in url.lower():
                    media_type = "gif"
                else:
                    media_type = _detect_media_type(url)
                    if media_type == "unknown":
                        media_type = "image"

        if not url:
            await ctx.send(
                "❌ Nothing to save!\n"
                "• Reply to a message with media attached, then run `!save`\n"
                "• Or: `!save https://link-to-image-or-gif`\n"
                "• Or with keyword: `!save funny cat` (replying to media)"
            )
            return

        await self._do_save(ctx, url, media_type, keyword)

    @commands.command(name="img")
    async def img(self, ctx, number: int = None):
        """Send saved image by number. !img 3"""
        if number is None:
            await ctx.send("❌ Usage: `!img 3`")
            return
        await self._send_media(ctx, "image", number)

    @commands.command(name="gif")
    async def gif(self, ctx, number: int = None):
        """Send saved GIF by number. !gif 2"""
        if number is None:
            await ctx.send("❌ Usage: `!gif 2`")
            return
        await self._send_media(ctx, "gif", number)

    @commands.command(name="imgs")
    async def imgs(self, ctx):
        """List all saved images."""
        await self._list_media(ctx, "image")

    @commands.command(name="gifs")
    async def gifs(self, ctx):
        """List all saved GIFs."""
        await self._list_media(ctx, "gif")

    @commands.command(name="imgr")
    async def imgr(self, ctx):
        """Send a random saved image from the vault."""
        if await self.check_duplicate(ctx):
            return
        row = self._get_random_entry("image")
        if not row:
            await ctx.send("❌ No images saved yet.")
            return
        # row = (id, url, saved_by, saved_by_id, saved_at, vault_msg_id, keyword)
        number = row[0]  # The ID is the number
        await self._send_media(ctx, "image", number)

    @commands.command(name="gifr")
    async def gifr(self, ctx):
        """Send a random saved GIF from the vault."""
        if await self.check_duplicate(ctx):
            return
        row = self._get_random_entry("gif")
        if not row:
            await ctx.send("❌ No GIFs saved yet.")
            return
        number = row[0]
        await self._send_media(ctx, "gif", number)

    # ══════════════════════════════════════════════════════════════════════════
    # COMMANDS — DELETE & CLEAR
    # ══════════════════════════════════════════════════════════════════════════

    @commands.command(name="delimg")
    async def delimg(self, ctx, number: int = None):
        """Delete saved image by number (owner server + AsaiyaBot role)."""
        if not self.is_owner_server(ctx):
            await ctx.send("🔐 Owner server + AsaiyaBot role required.")
            return
        if number is None:
            await ctx.send("❌ Usage: `!delimg 3`")
            return
        await self._delete_media(ctx, "image", number)

    @commands.command(name="delgif")
    async def delgif(self, ctx, number: int = None):
        """Delete saved GIF by number (owner server + AsaiyaBot role)."""
        if not self.is_owner_server(ctx):
            await ctx.send("🔐 Owner server + AsaiyaBot role required.")
            return
        if number is None:
            await ctx.send("❌ Usage: `!delgif 3`")
            return
        await self._delete_media(ctx, "gif", number)

    @commands.command(name="clearimg")
    async def clearimg(self, ctx):
        """Delete ALL saved images from the vault (owner server + AsaiyaBot role)."""
        if not self.is_owner_server(ctx):
            await ctx.send("🔐 Owner server + AsaiyaBot role required.")
            return
        await self._clear_all_media(ctx, "image")

    @commands.command(name="cleargif")
    async def cleargif(self, ctx):
        """Delete ALL saved GIFs from the vault (owner server + AsaiyaBot role)."""
        if not self.is_owner_server(ctx):
            await ctx.send("🔐 Owner server + AsaiyaBot role required.")
            return
        await self._clear_all_media(ctx, "gif")

    @commands.command(name="vaultsetup")
    @commands.is_owner()
    async def vaultsetup(self, ctx, channel: discord.TextChannel = None):
        """(Owner only) Configure the vault storage channel."""
        if await self.check_duplicate(ctx):
            return
        if ctx.guild.id != STORAGE_SERVER_ID:
            await ctx.send(f"❌ Must be used in the storage server (ID: `{STORAGE_SERVER_ID}`).")
            return
        if channel is None:
            channel = discord.utils.get(ctx.guild.text_channels, name=VAULT_CHANNEL_NAME)
            if not channel:
                try:
                    channel = await ctx.guild.create_text_channel(VAULT_CHANNEL_NAME, reason="Media vault")
                    await ctx.send(f"✅ Created {channel.mention}.")
                except Exception as e:
                    await ctx.send(f"❌ Failed: {e}")
                    return
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute(
                "INSERT OR REPLACE INTO vault_config (key, value) VALUES ('vault_channel_id', ?)",
                (str(channel.id),)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            await ctx.send(f"❌ DB error: {e}")
            return

        embed = discord.Embed(
            title="🔒 Media Vault Configured",
            description=f"All saved media will be stored in {channel.mention}.",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Channel ID", value=f"`{channel.id}`",  inline=True)
        embed.add_field(name="Server ID",  value=f"`{ctx.guild.id}`", inline=True)
        embed.set_footer(text=f"Set by {ctx.author}")
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(MediaVault(bot))
