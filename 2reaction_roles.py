import discord
from discord.ext import commands
import sqlite3
import time
import asyncio
import json
import os
from datetime import datetime

# ===== CONFIGURATION =====
DB_FOLDER = r"C:\Users\Kelly\Desktop\discord database"
MAIN_DB_PATH = os.path.join(DB_FOLDER, "asaiya_bot.db")

REACTION_ROLES_TABLE = "reaction_roles"
REACTION_ROLE_ITEMS_TABLE = "reaction_role_items"

BOT_ROLE = "AsaiyaBot"


class ReactionRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Temporary setup storage per user
        # Format: {user_id: {step, channel, items, message, type}}
        self.reaction_role_setup = {}
        # Track processed commands to prevent duplicates
        self.processed_commands = {}
        print(f"✅ Reaction Roles cog initialized (ID: {id(self)})")

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

    def save_reaction_setup(self, user_id, guild_id, setup_data):
        """Save reaction setup to main database"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            expires_at = time.time() + 86400  # 24 hours
            c.execute('''CREATE TABLE IF NOT EXISTS persistent_reaction_setup
                         (user_id TEXT PRIMARY KEY,
                          guild_id TEXT,
                          setup_data TEXT,
                          created_at REAL,
                          expires_at REAL)''')
            c.execute('''INSERT OR REPLACE INTO persistent_reaction_setup
                         (user_id, guild_id, setup_data, created_at, expires_at)
                         VALUES (?, ?, ?, ?, ?)''',
                      (str(user_id), str(guild_id), json.dumps(setup_data), time.time(), expires_at))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error saving reaction setup: {e}")

    def load_reaction_setup(self, user_id):
        """Load reaction setup from main database"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS persistent_reaction_setup
                         (user_id TEXT PRIMARY KEY,
                          guild_id TEXT,
                          setup_data TEXT,
                          created_at REAL,
                          expires_at REAL)''')
            c.execute("SELECT guild_id, setup_data FROM persistent_reaction_setup WHERE user_id = ? AND expires_at > ?",
                      (str(user_id), time.time()))
            result = c.fetchone()
            conn.close()
            if result:
                guild_id, setup_data = result
                setup = json.loads(setup_data)
                setup['guild_id'] = int(guild_id)
                return setup
        except Exception as e:
            print(f"Error loading reaction setup: {e}")
        return None

    def delete_reaction_setup(self, user_id):
        """Delete reaction setup from main database"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM persistent_reaction_setup WHERE user_id = ?", (str(user_id),))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error deleting reaction setup: {e}")

    async def send_reaction_role(self, author, setup, guild):
        """Send the reaction role message to the target channel"""
        channel = setup['channel']

        embed = discord.Embed(
            title="🎭 Reaction Roles",
            description=setup['message'],
            color=discord.Color.purple()
        )

        items_text = ""
        for item in setup['items']:
            items_text += f"{item['emoji']} - {item['role_name']}\n"

        embed.add_field(name="Available Roles", value=items_text, inline=False)

        if setup['type'] == 'one':
            embed.set_footer(text="⚠️ You can only have ONE of these roles at a time!")

        msg = await channel.send(embed=embed)

        # Add reactions
        for item in setup['items']:
            try:
                await msg.add_reaction(item['emoji'])
            except:
                await channel.send(f"⚠️ Could not add reaction {item['emoji']}")

        # Save to database
        conn = self.get_cached_connection(guild.id)
        c = conn.cursor()

        if setup['type'] == 'one':
            c.execute('''CREATE TABLE IF NOT EXISTS reaction_one_role_groups
                         (group_id INTEGER PRIMARY KEY AUTOINCREMENT,
                          guild_id TEXT,
                          message_id TEXT,
                          group_name TEXT)''')
            c.execute('''CREATE TABLE IF NOT EXISTS reaction_one_role_items
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          group_id INTEGER,
                          emoji TEXT,
                          role_id TEXT,
                          role_name TEXT,
                          FOREIGN KEY (group_id) REFERENCES reaction_one_role_groups(group_id))''')
            
            c.execute("""INSERT INTO reaction_one_role_groups (guild_id, message_id, group_name)
                         VALUES (?, ?, ?)""",
                      (str(guild.id), str(msg.id), f"One-Role Group {int(time.time())}"))
            group_id = c.lastrowid

            for item in setup['items']:
                c.execute("""INSERT INTO reaction_one_role_items (group_id, emoji, role_id, role_name)
                             VALUES (?, ?, ?, ?)""",
                          (group_id, item['emoji'], item['role_id'], item['role_name']))
        else:
            c.execute(f'''CREATE TABLE IF NOT EXISTS {REACTION_ROLES_TABLE}
                         (message_id TEXT PRIMARY KEY,
                          channel_id TEXT,
                          title TEXT,
                          description TEXT,
                          created_at REAL)''')
            c.execute(f'''CREATE TABLE IF NOT EXISTS {REACTION_ROLE_ITEMS_TABLE}
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          message_id TEXT,
                          emoji TEXT,
                          role_id TEXT,
                          role_name TEXT,
                          FOREIGN KEY (message_id) REFERENCES {REACTION_ROLES_TABLE}(message_id))''')
            
            c.execute(f"""INSERT INTO {REACTION_ROLES_TABLE}
                         (message_id, channel_id, title, created_at)
                         VALUES (?, ?, ?, ?)""",
                      (str(msg.id), str(channel.id), setup['message'][:100], time.time()))

            for item in setup['items']:
                c.execute(f"""INSERT INTO {REACTION_ROLE_ITEMS_TABLE}
                             (message_id, emoji, role_id, role_name)
                             VALUES (?, ?, ?, ?)""",
                          (str(msg.id), item['emoji'], str(item['role_id']), item['role_name']))

        conn.commit()
        await channel.send(f"✅ Reaction role message sent to {channel.mention}!")

    # ===== LISTENER =====

    @commands.Cog.listener()
    async def on_message(self, message):
        """Handle reaction role setup conversation"""
        if message.author.bot:
            return

        user_id = message.author.id

        # Try to load from database if not in memory
        if user_id not in self.reaction_role_setup:
            loaded = self.load_reaction_setup(user_id)
            if loaded:
                self.reaction_role_setup[user_id] = loaded
                await message.channel.send("🔄 Found your previous reaction role setup! Continuing...")
            else:
                return

        setup = self.reaction_role_setup[user_id]

        # Only process in the same guild
        if message.guild and str(message.guild.id) != str(setup.get('guild_id', '')):
            return

        # Delete user message to keep channel clean
        try:
            await message.delete()
        except:
            pass

        # ===== STEP 1: GET CHANNEL =====
        if setup['step'] == 'channel':
            channel = None

            if message.channel_mentions:
                channel = message.channel_mentions[0]
            else:
                content = message.content.strip()
                try:
                    channel = message.guild.get_channel(int(content))
                except:
                    channel = discord.utils.get(message.guild.text_channels, name=content)

            if not channel:
                await message.channel.send("❌ Could not find that channel. Please try again.")
                return

            setup['channel'] = channel
            setup['step'] = 'emoji'
            self.save_reaction_setup(user_id, message.guild.id, setup)

            embed = discord.Embed(
                title="🎭 Step 2: Choose Emoji",
                description=(
                    f"Channel set to {channel.mention}\n\n"
                    f"What **emoji** would you like to use?\n"
                    f"Type the emoji (default or custom)."
                ),
                color=discord.Color.blue()
            )
            await message.channel.send(embed=embed)

        # ===== STEP 2: GET EMOJI =====
        elif setup['step'] == 'emoji':
            emoji = message.content.strip()
            setup['temp_emoji'] = emoji
            setup['step'] = 'role'
            self.save_reaction_setup(user_id, message.guild.id, setup)

            embed = discord.Embed(
                title="🎭 Step 3: Choose Role",
                description=(
                    f"Emoji set to: {emoji}\n\n"
                    f"Now **ping the role** you want to assign with this emoji.\n"
                    f"(e.g., `@Member` or `@Verified`)"
                ),
                color=discord.Color.blue()
            )
            await message.channel.send(embed=embed)

        # ===== STEP 3: GET ROLE =====
        elif setup['step'] == 'role':
            if not message.role_mentions:
                await message.channel.send("❌ Please ping a valid role (e.g., `@Member`).")
                return

            role = message.role_mentions[0]
            emoji = setup['temp_emoji']

            # Check for duplicates
            for item in setup['items']:
                if item['emoji'] == emoji:
                    await message.channel.send(f"❌ That emoji is already used for **{item['role_name']}**.")
                    return
                if item['role_id'] == str(role.id):
                    await message.channel.send(f"❌ That role is already used for emoji **{item['emoji']}**.")
                    return

            setup['items'].append({
                'emoji': emoji,
                'role_id': str(role.id),
                'role_name': role.name
            })
            setup['step'] = 'more'
            self.save_reaction_setup(user_id, message.guild.id, setup)

            items_text = "\n".join([f"{i+1}. {item['emoji']} → {item['role_name']}"
                                    for i, item in enumerate(setup['items'])])

            embed = discord.Embed(
                title="🎭 Current Items",
                description=items_text,
                color=discord.Color.green()
            )
            embed.add_field(
                name="Add more?",
                value="Type `yes` to add more, or `done` to continue.",
                inline=False
            )
            await message.channel.send(embed=embed)

        # ===== STEP 4: MORE OR DONE =====
        elif setup['step'] == 'more':
            content = message.content.lower()

            if content in ['yes', 'y']:
                setup['step'] = 'emoji'
                self.save_reaction_setup(user_id, message.guild.id, setup)
                await message.channel.send("📝 **What emoji would you like to add next?**")

            elif content in ['done', 'd', 'no', 'n']:
                setup['step'] = 'message'
                self.save_reaction_setup(user_id, message.guild.id, setup)

                embed = discord.Embed(
                    title="🎭 Step 4: Customize Message",
                    description=(
                        f"You've added {len(setup['items'])} item(s).\n\n"
                        f"What **message** would you like the bot to send above the roles?\n\n"
                        f"Example: *Click the reactions below to get your roles!*"
                    ),
                    color=discord.Color.blue()
                )
                await message.channel.send(embed=embed)
            else:
                await message.channel.send("❌ Please type `yes` or `done`.")

        # ===== STEP 5: GET MESSAGE =====
        elif setup['step'] == 'message':
            setup['message'] = message.content
            setup['step'] = 'confirm'
            self.save_reaction_setup(user_id, message.guild.id, setup)

            items_text = "\n".join([f"{item['emoji']} → {item['role_name']}"
                                    for item in setup['items']])

            embed = discord.Embed(
                title="🎭 Preview",
                description=(
                    f"**Message:**\n{setup['message']}\n\n"
                    f"**Items:**\n{items_text}\n\n"
                    f"**Channel:** {setup['channel'].mention}\n"
                    f"**Type:** {'One role only' if setup['type'] == 'one' else 'Multiple roles allowed'}"
                ),
                color=discord.Color.gold()
            )
            embed.add_field(
                name="Send this now?",
                value="Type `yes` to send, `no` to edit, or `cancel` to cancel.",
                inline=False
            )
            await message.channel.send(embed=embed)

        # ===== STEP 6: CONFIRM =====
        elif setup['step'] == 'confirm':
            content = message.content.lower()

            if content == 'yes':
                await self.send_reaction_role(message.author, setup, message.guild)
                del self.reaction_role_setup[user_id]
                self.delete_reaction_setup(user_id)

            elif content == 'no':
                setup['step'] = 'edit'
                self.save_reaction_setup(user_id, message.guild.id, setup)

                embed = discord.Embed(
                    title="🎭 Edit Options",
                    description=(
                        "What would you like to edit?\n\n"
                        "• `roles` - Edit the roles/emojis\n"
                        "• `message` - Edit the message text\n"
                        "• `channel` - Change the channel\n"
                        "• `cancel` - Cancel setup"
                    ),
                    color=discord.Color.orange()
                )
                await message.channel.send(embed=embed)

            elif content == 'cancel':
                del self.reaction_role_setup[user_id]
                self.delete_reaction_setup(user_id)
                await message.channel.send("❌ Setup cancelled.")
            else:
                await message.channel.send("❌ Please type `yes`, `no`, or `cancel`.")

        # ===== EDIT MODE =====
        elif setup['step'] == 'edit':
            content = message.content.lower()

            if content == 'roles':
                setup['step'] = 'emoji'
                setup['items'] = []
                self.save_reaction_setup(user_id, message.guild.id, setup)
                await message.channel.send("🔄 Let's set up the roles again.\n\n**What emoji would you like to use?**")

            elif content == 'message':
                setup['step'] = 'message'
                self.save_reaction_setup(user_id, message.guild.id, setup)
                await message.channel.send("📝 **What new message would you like?**")

            elif content == 'channel':
                setup['step'] = 'channel'
                self.save_reaction_setup(user_id, message.guild.id, setup)
                await message.channel.send("📝 **Please provide the new channel mention, ID, or name:**")

            elif content == 'cancel':
                del self.reaction_role_setup[user_id]
                self.delete_reaction_setup(user_id)
                await message.channel.send("❌ Setup cancelled.")
            else:
                await message.channel.send("❌ Please choose: `roles`, `message`, `channel`, or `cancel`.")

    # ===== MAIN COMMANDS =====

    @commands.group(name='rrole', invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def rrole(self, ctx):
        """Start the reaction role setup process (multiple roles allowed)"""
        if await self.check_duplicate(ctx):
            return
            
        embed = discord.Embed(
            title="🎭 Reaction Role Commands",
            description="Here are all available reaction role commands:",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Interactive Setup",
            value=(
                "`!rrole` - Start interactive setup (multiple roles)\n"
                "`!onerole` - Start one-role-only setup"
            ),
            inline=False
        )
        embed.add_field(
            name="Management Commands",
            value=(
                "`!rrole list` - List all reaction role messages\n"
                "`!rrole delete <message_id>` - Delete a reaction role setup\n"
                "`!rrole show <message_id>` - Show details of a reaction role"
            ),
            inline=False
        )
        embed.add_field(
            name="Quick Commands (Advanced)",
            value=(
                "`!rrole create #channel 'title'` - Create with just channel and title\n"
                "`!rrole add <message_id> :emoji: @role` - Add a pair to existing\n"
                "`!rrole remove <message_id> :emoji:` - Remove a pair"
            ),
            inline=False
        )
        await ctx.send(embed=embed)

    @rrole.command(name='create')
    @commands.has_permissions(administrator=True)
    async def rrole_create(self, ctx, channel: discord.TextChannel, *, title: str):
        """Quick create a reaction role with just channel and title.
        You'll still need to add emoji-role pairs.
        Usage: !rrole create #channel "Your title here"
        """
        if await self.check_duplicate(ctx):
            return
            
        user_id = ctx.author.id
        
        self.reaction_role_setup[user_id] = {
            'step': 'emoji',
            'channel': channel,
            'items': [],
            'message': title,
            'type': 'multi',
            'guild_id': ctx.guild.id
        }
        self.save_reaction_setup(user_id, ctx.guild.id, self.reaction_role_setup[user_id])
        
        embed = discord.Embed(
            title="🎭 Quick Create - Add First Emoji",
            description=(
                f"Channel: {channel.mention}\n"
                f"Title: {title}\n\n"
                f"What **emoji** would you like to use for the first role?"
            ),
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @rrole.command(name='add')
    @commands.has_permissions(administrator=True)
    async def rrole_add(self, ctx, message_id: str, emoji: str, role: discord.Role):
        """Add an emoji-role pair to an existing reaction role message.
        Usage: !rrole add 123456789 😀 @Role
        """
        if await self.check_duplicate(ctx):
            return
            
        try:
            msg_id = int(message_id)
        except ValueError:
            await ctx.send("❌ Invalid message ID!")
            return
        
        # Check if message exists in database
        conn = self.get_cached_connection(ctx.guild.id)
        c = conn.cursor()
        
        c.execute(f'''CREATE TABLE IF NOT EXISTS {REACTION_ROLES_TABLE}
                     (message_id TEXT PRIMARY KEY,
                      channel_id TEXT,
                      title TEXT,
                      description TEXT,
                      created_at REAL)''')
        c.execute(f'''CREATE TABLE IF NOT EXISTS {REACTION_ROLE_ITEMS_TABLE}
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      message_id TEXT,
                      emoji TEXT,
                      role_id TEXT,
                      role_name TEXT,
                      FOREIGN KEY (message_id) REFERENCES {REACTION_ROLES_TABLE}(message_id))''')
        
        c.execute(f"SELECT channel_id FROM {REACTION_ROLES_TABLE} WHERE message_id = ?", (str(msg_id),))
        result = c.fetchone()
        
        if not result:
            await ctx.send("❌ No reaction role found with that message ID!")
            return
            
        # Check if emoji already exists for this message
        c.execute(f"SELECT role_name FROM {REACTION_ROLE_ITEMS_TABLE} WHERE message_id = ? AND emoji = ?",
                  (str(msg_id), emoji))
        existing = c.fetchone()
        if existing:
            await ctx.send(f"❌ Emoji {emoji} is already used for role **{existing[0]}**!")
            return
            
        # Add the new pair
        c.execute(f"INSERT INTO {REACTION_ROLE_ITEMS_TABLE} (message_id, emoji, role_id, role_name) VALUES (?, ?, ?, ?)",
                  (str(msg_id), emoji, str(role.id), role.name))
        conn.commit()
        
        # Try to add reaction to the message
        try:
            channel_id = int(result[0])
            channel = ctx.guild.get_channel(channel_id)
            if channel:
                msg = await channel.fetch_message(msg_id)
                await msg.add_reaction(emoji)
        except:
            pass
            
        await ctx.send(f"✅ Added {emoji} → {role.mention} to reaction role!")
        
    @rrole.command(name='remove')
    @commands.has_permissions(administrator=True)
    async def rrole_remove(self, ctx, message_id: str, emoji: str):
        """Remove an emoji-role pair from an existing reaction role message.
        Usage: !rrole remove 123456789 😀
        """
        if await self.check_duplicate(ctx):
            return
            
        try:
            msg_id = int(message_id)
        except ValueError:
            await ctx.send("❌ Invalid message ID!")
            return
            
        conn = self.get_cached_connection(ctx.guild.id)
        c = conn.cursor()
        
        c.execute(f"DELETE FROM {REACTION_ROLE_ITEMS_TABLE} WHERE message_id = ? AND emoji = ?",
                  (str(msg_id), emoji))
        
        if c.rowcount > 0:
            conn.commit()
            await ctx.send(f"✅ Removed emoji {emoji} from reaction role!")
        else:
            await ctx.send(f"❌ Could not find emoji {emoji} in that reaction role!")

    @rrole.command(name='list')
    @commands.has_permissions(administrator=True)
    async def rrole_list(self, ctx):
        """List all reaction role messages in this server"""
        if await self.check_duplicate(ctx):
            return
            
        conn = self.get_cached_connection(ctx.guild.id)
        c = conn.cursor()
        
        c.execute(f'''CREATE TABLE IF NOT EXISTS {REACTION_ROLES_TABLE}
                     (message_id TEXT PRIMARY KEY,
                      channel_id TEXT,
                      title TEXT,
                      description TEXT,
                      created_at REAL)''')
        c.execute(f'''CREATE TABLE IF NOT EXISTS reaction_one_role_groups
                     (group_id INTEGER PRIMARY KEY AUTOINCREMENT,
                      guild_id TEXT,
                      message_id TEXT,
                      group_name TEXT)''')
        
        # Get regular reaction roles
        c.execute(f"SELECT message_id, channel_id, title, created_at FROM {REACTION_ROLES_TABLE}")
        regular = c.fetchall()
        
        # Get one-role groups
        c.execute("SELECT message_id, group_name FROM reaction_one_role_groups WHERE guild_id = ?",
                  (str(ctx.guild.id),))
        one_role = c.fetchall()
        
        if not regular and not one_role:
            await ctx.send("📭 No reaction role messages found in this server.")
            return
            
        embed = discord.Embed(
            title="🎭 Reaction Role Messages",
            color=discord.Color.blue()
        )
        
        if regular:
            reg_text = ""
            for msg_id, ch_id, title, created in regular[:5]:
                channel = ctx.guild.get_channel(int(ch_id))
                channel_name = f"#{channel.name}" if channel else "Unknown"
                time_str = datetime.fromtimestamp(created).strftime("%Y-%m-%d")
                reg_text += f"• `{msg_id}` in {channel_name} - {title[:30]} ({time_str})\n"
            embed.add_field(name="Multiple Roles Allowed", value=reg_text or "None", inline=False)
            
        if one_role:
            one_text = ""
            for msg_id, group_name in one_role[:5]:
                one_text += f"• `{msg_id}` - {group_name}\n"
            embed.add_field(name="One-Role Only Groups", value=one_text or "None", inline=False)
            
        embed.set_footer(text="Use !rrole delete <message_id> to remove")
        await ctx.send(embed=embed)

    @rrole.command(name='delete')
    @commands.has_permissions(administrator=True)
    async def rrole_delete(self, ctx, message_id: str):
        """Delete a reaction role setup by message ID.
        Usage: !rrole delete 123456789
        """
        if await self.check_duplicate(ctx):
            return
            
        try:
            msg_id = int(message_id)
        except ValueError:
            await ctx.send("❌ Invalid message ID!")
            return
            
        conn = self.get_cached_connection(ctx.guild.id)
        c = conn.cursor()
        
        # Check regular reaction roles
        c.execute(f"DELETE FROM {REACTION_ROLE_ITEMS_TABLE} WHERE message_id = ?", (str(msg_id),))
        c.execute(f"DELETE FROM {REACTION_ROLES_TABLE} WHERE message_id = ?", (str(msg_id),))
        deleted_regular = c.rowcount
        
        # Check one-role groups
        c.execute("SELECT group_id FROM reaction_one_role_groups WHERE message_id = ?", (str(msg_id),))
        group = c.fetchone()
        if group:
            group_id = group[0]
            c.execute("DELETE FROM reaction_one_role_items WHERE group_id = ?", (group_id,))
            c.execute("DELETE FROM reaction_one_role_groups WHERE message_id = ?", (str(msg_id),))
            deleted_one = True
        else:
            deleted_one = False
            
        conn.commit()
        
        if deleted_regular > 0 or deleted_one:
            await ctx.send(f"✅ Deleted reaction role with ID `{message_id}`!")
            
            # Try to delete the actual message
            try:
                for channel in ctx.guild.text_channels:
                    try:
                        msg = await channel.fetch_message(msg_id)
                        await msg.delete()
                        break
                    except:
                        continue
            except:
                pass
        else:
            await ctx.send(f"❌ No reaction role found with ID `{message_id}`!")

    @rrole.command(name='show')
    @commands.has_permissions(administrator=True)
    async def rrole_show(self, ctx, message_id: str):
        """Show details of a specific reaction role message.
        Usage: !rrole show 123456789
        """
        if await self.check_duplicate(ctx):
            return
            
        try:
            msg_id = int(message_id)
        except ValueError:
            await ctx.send("❌ Invalid message ID!")
            return
            
        conn = self.get_cached_connection(ctx.guild.id)
        c = conn.cursor()
        
        # Check regular reaction roles
        c.execute(f"SELECT channel_id, title, created_at FROM {REACTION_ROLES_TABLE} WHERE message_id = ?",
                  (str(msg_id),))
        regular = c.fetchone()
        
        if regular:
            channel_id, title, created_at = regular
            channel = ctx.guild.get_channel(int(channel_id))
            channel_name = channel.mention if channel else "Unknown"
            
            c.execute(f"SELECT emoji, role_id, role_name FROM {REACTION_ROLE_ITEMS_TABLE} WHERE message_id = ?",
                      (str(msg_id),))
            items = c.fetchall()
            
            embed = discord.Embed(
                title="🎭 Reaction Role Details",
                description=f"**Message ID:** `{msg_id}`\n**Channel:** {channel_name}\n**Title:** {title}\n**Created:** <t:{int(created_at)}:R>",
                color=discord.Color.blue()
            )
            
            if items:
                items_text = ""
                for emoji, role_id, role_name in items:
                    role = ctx.guild.get_role(int(role_id))
                    role_mention = role.mention if role else f"@{role_name} (deleted)"
                    items_text += f"{emoji} → {role_mention}\n"
                embed.add_field(name="Emoji-Role Pairs", value=items_text, inline=False)
            else:
                embed.add_field(name="Emoji-Role Pairs", value="No pairs found", inline=False)
                
            await ctx.send(embed=embed)
            return
            
        # Check one-role groups
        c.execute("SELECT group_id, group_name FROM reaction_one_role_groups WHERE message_id = ?", (str(msg_id),))
        group = c.fetchone()
        
        if group:
            group_id, group_name = group
            c.execute("SELECT emoji, role_id, role_name FROM reaction_one_role_items WHERE group_id = ?", (group_id,))
            items = c.fetchall()
            
            embed = discord.Embed(
                title="🎭 One-Role Group Details",
                description=f"**Message ID:** `{msg_id}`\n**Group Name:** {group_name}",
                color=discord.Color.purple()
            )
            
            if items:
                items_text = ""
                for emoji, role_id, role_name in items:
                    role = ctx.guild.get_role(int(role_id))
                    role_mention = role.mention if role else f"@{role_name} (deleted)"
                    items_text += f"{emoji} → {role_mention}\n"
                embed.add_field(name="Emoji-Role Pairs", value=items_text, inline=False)
                embed.set_footer(text="⚠️ Users can only have ONE of these roles at a time!")
            else:
                embed.add_field(name="Emoji-Role Pairs", value="No pairs found", inline=False)
                
            await ctx.send(embed=embed)
            return
            
        await ctx.send(f"❌ No reaction role found with ID `{message_id}`!")

    @rrole.command(name='publish')
    @commands.has_permissions(administrator=True)
    async def rrole_publish(self, ctx, message_id: str = None):
        """Publish a saved setup (if you have one) or send a preview.
        Usage: !rrole publish [message_id]
        """
        if await self.check_duplicate(ctx):
            return
            
        user_id = ctx.author.id
        
        if message_id:
            # Try to republish an existing one
            try:
                msg_id = int(message_id)
            except ValueError:
                await ctx.send("❌ Invalid message ID!")
                return
                
            conn = self.get_cached_connection(ctx.guild.id)
            c = conn.cursor()
            
            # Check regular
            c.execute(f"SELECT channel_id, title FROM {REACTION_ROLES_TABLE} WHERE message_id = ?", (str(msg_id),))
            regular = c.fetchone()
            
            if regular:
                channel_id, title = regular
                channel = ctx.guild.get_channel(int(channel_id))
                
                c.execute(f"SELECT emoji, role_id, role_name FROM {REACTION_ROLE_ITEMS_TABLE} WHERE message_id = ?",
                          (str(msg_id),))
                items = c.fetchall()
                
                if not items:
                    await ctx.send("❌ That reaction role has no emoji-role pairs!")
                    return
                    
                setup = {
                    'channel': channel,
                    'message': title,
                    'items': [{'emoji': e, 'role_id': r_id, 'role_name': r_name} for e, r_id, r_name in items],
                    'type': 'multi'
                }
                
                await self.send_reaction_role(ctx.author, setup, ctx.guild)
                return
                
            # Check one-role
            c.execute("SELECT group_id, group_name FROM reaction_one_role_groups WHERE message_id = ?", (str(msg_id),))
            group = c.fetchone()
            
            if group:
                group_id, group_name = group
                c.execute("SELECT emoji, role_id, role_name FROM reaction_one_role_items WHERE group_id = ?", (group_id,))
                items = c.fetchall()
                
                if not items:
                    await ctx.send("❌ That reaction role has no emoji-role pairs!")
                    return
                    
                # Find channel from original message
                for channel in ctx.guild.text_channels:
                    try:
                        msg = await channel.fetch_message(msg_id)
                        if msg:
                            target_channel = channel
                            break
                    except:
                        continue
                else:
                    target_channel = ctx.channel
                    
                setup = {
                    'channel': target_channel,
                    'message': group_name,
                    'items': [{'emoji': e, 'role_id': r_id, 'role_name': r_name} for e, r_id, r_name in items],
                    'type': 'one'
                }
                
                await self.send_reaction_role(ctx.author, setup, ctx.guild)
                return
                
            await ctx.send(f"❌ No reaction role found with ID `{message_id}`!")
            
        elif user_id in self.reaction_role_setup:
            # Preview current setup
            setup = self.reaction_role_setup[user_id]
            if setup['items'] and setup['message']:
                await self.send_reaction_role(ctx.author, setup, ctx.guild)
                del self.reaction_role_setup[user_id]
                self.delete_reaction_setup(user_id)
            else:
                await ctx.send("❌ Your setup is incomplete! Please complete all steps first.")
        else:
            await ctx.send("❌ No active setup found. Start with `!rrole` or `!onerole` first.")

    # ===== ONE-ROLE COMMAND =====

    @commands.command(name='onerole')
    @commands.has_permissions(administrator=True)
    async def onerole(self, ctx):
        """Start the one-role-only reaction role setup (users can only have ONE role)"""
        if await self.check_duplicate(ctx):
            return
            
        user_id = ctx.author.id

        self.reaction_role_setup[user_id] = {
            'step': 'channel',
            'channel': None,
            'items': [],
            'message': '',
            'type': 'one',
            'guild_id': ctx.guild.id
        }
        self.save_reaction_setup(user_id, ctx.guild.id, self.reaction_role_setup[user_id])

        embed = discord.Embed(
            title="🎭 One-Role-Only Reaction Role Setup",
            description=(
                "Let's create a reaction role where users can only have **ONE** of these roles!\n\n"
                "First, where would you like this sent?\n"
                "Please provide a **channel mention**, **channel ID**, or **channel name**."
            ),
            color=discord.Color.purple()
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(ReactionRoles(bot))
