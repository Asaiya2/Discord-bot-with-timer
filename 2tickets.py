import discord
from discord.ext import commands
import sqlite3
import time
import re
import asyncio
import random
from datetime import datetime
import os

# ===== TICKET CONFIGURATION =====
DB_FOLDER = r"C:\Users\Kelly\Desktop\discord database"
MAIN_DB_PATH = os.path.join(DB_FOLDER, "asaiya_bot.db")

# Archive Category Settings
MAX_TICKETS_PER_ARCHIVE = 45          # Max channels per archive category
ARCHIVE_BASE_NAME = "Asaiya-Done"     # Base name for archive categories
OVERFLOW_PREFIX = " "                  # Space between base and number for overflow (creates "Asaiya-Done 2", "Asaiya-Done 3", etc.)

KEYWORD_CATEGORIES = {
    'bug': 'bug-ticket',
    'error': 'bug-ticket',
    'glitch': 'bug-ticket',
    'broken': 'bug-ticket',
    'crash': 'bug-ticket',
    
    'buy': 'buy-ticket',
    'payment': 'buy-ticket',
    'purchase': 'buy-ticket',
    'pay': 'buy-ticket',
    'robux': 'buy-ticket',
    'bobux': 'buy-ticket',
    
    'hack': 'report-ticket',
    'stolen': 'report-ticket',
    'scam': 'report-ticket',
    'report': 'report-ticket',
    
    'verify': 'verify-ticket',
    'verification': 'verify-ticket',
    'roblox': 'verify-ticket'
}

DEFAULT_CATEGORY = "Asaiya Ticket"

# Store active tickets in memory
active_tickets = {}
ticket_counters = {}
ticket_ratings = {}  # Store ratings for surprise stats


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="Create Ticket", style=discord.ButtonStyle.green, custom_id="create_ticket")
    async def create_ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_ticket_creation(interaction)
    
    async def handle_ticket_creation(self, interaction):
        user_id = str(interaction.user.id)
        guild_id = str(interaction.guild_id)
        
        # Check if user already has an open ticket
        cog = interaction.client.get_cog('Tickets')
        if await cog.has_open_ticket(interaction.user, interaction.guild):
            await interaction.response.send_message(
                "❌ You already have an open ticket! Please wait for it to be resolved.",
                ephemeral=True
            )
            return
        
        await interaction.response.send_message(
            "📝 Please describe what you need help with in **one sentence**:\n"
            "(Example: 'I found a bug', 'I need help buying robux', 'My account was hacked')",
            ephemeral=True
        )
        
        def check(m):
            return m.author.id == interaction.user.id and m.channel.id == interaction.channel.id
        
        try:
            msg = await interaction.client.wait_for('message', timeout=120.0, check=check)
            request_text = msg.content
            
            try:
                await msg.delete()
            except:
                pass
            
            # Determine category
            category_name = self.determine_category(request_text)
            
            # Get or create category
            category = discord.utils.get(interaction.guild.categories, name=category_name)
            if not category:
                category = discord.utils.get(interaction.guild.categories, name=DEFAULT_CATEGORY)
                if not category:
                    await interaction.followup.send("❌ Ticket system not fully configured!", ephemeral=True)
                    return
            
            # Generate channel name
            channel_name = re.sub(r'[^a-z0-9-]', '', interaction.user.name.lower())[:20]
            
            # Get ticket number
            if guild_id not in ticket_counters:
                ticket_counters[guild_id] = 0
            ticket_counters[guild_id] += 1
            ticket_num = ticket_counters[guild_id]
            
            # Get roles
            request_role = discord.utils.get(interaction.guild.roles, name="asaiya-request")
            support_role = discord.utils.get(interaction.guild.roles, name="asaiya-support")
            
            if not request_role or not support_role:
                await interaction.followup.send("❌ Ticket roles not found! Run `!setserver` first.", ephemeral=True)
                return
            
            # Set up permissions
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    attach_files=True,
                    embed_links=True
                )
            }
            
            # Create ticket channel
            ticket_channel = await interaction.guild.create_text_channel(
                f"{channel_name}-{ticket_num}",
                category=category,
                overwrites=overwrites,
                reason=f"Ticket created by {interaction.user}"
            )
            
            # Assign request role
            await interaction.user.add_roles(request_role, reason="Ticket created")
            
            # Track active ticket
            cog = interaction.client.get_cog('Tickets')
            await cog.add_active_ticket(interaction.guild.id, interaction.user.id, ticket_channel.id)
            
            # Send welcome message
            welcome_embed = discord.Embed(
                title="🎫 Ticket Created",
                description=f"Hello {interaction.user.mention}! Support will be with you shortly.",
                color=discord.Color.green()
            )
            welcome_embed.add_field(name="Your Request", value=request_text, inline=False)
            welcome_embed.add_field(name="Commands", 
                                   value="`!rename <new name>` - Rename this channel\n`!close` - Close this ticket",
                                   inline=False)
            await ticket_channel.send(embed=welcome_embed)
            
            # Send staff alert
            await self.send_staff_alert(interaction, ticket_channel, interaction.user, request_text)
            
            await interaction.followup.send(f"✅ Ticket created! Check {ticket_channel.mention}", ephemeral=True)
            
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timed out. Please click the button again.", ephemeral=True)
    
    def determine_category(self, text):
        text_lower = text.lower()
        found_keywords = []
        
        for keyword, category in KEYWORD_CATEGORIES.items():
            if keyword in text_lower:
                found_keywords.append(keyword)
        
        if len(found_keywords) == 1:
            return KEYWORD_CATEGORIES[found_keywords[0]]
        
        return DEFAULT_CATEGORY
    
    async def send_staff_alert(self, interaction, ticket_channel, user, request_text):
        staff_category = discord.utils.get(interaction.guild.categories, name="Staff Team")
        if not staff_category:
            return
        
        alert_channel = discord.utils.get(staff_category.channels, name="ticket-alerts")
        if not alert_channel:
            return
        
        embed = discord.Embed(
            title="🎫 **NEW TICKET**",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Ticket Request", value=user.mention, inline=True)
        embed.add_field(name="About", value=request_text[:50], inline=True)
        embed.add_field(name="Category", value=ticket_channel.category.name, inline=True)
        embed.add_field(name="Created", value=f"<t:{int(time.time())}:R>", inline=False)
        
        class ClaimView(discord.ui.View):
            def __init__(self, ticket_channel, user):
                super().__init__(timeout=None)
                self.ticket_channel = ticket_channel
                self.user = user
                self.claimed = False
                self.claimer = None
            
            @discord.ui.button(label="🔔 Claim Ticket", style=discord.ButtonStyle.primary, custom_id="claim_ticket")
            async def claim_button(self, claim_interaction: discord.Interaction, button: discord.ui.Button):
                if self.claimed:
                    await claim_interaction.response.send_message("❌ This ticket has already been claimed!", ephemeral=True)
                    return
                
                support_role = discord.utils.get(claim_interaction.guild.roles, name="asaiya-support")
                if not support_role or support_role not in claim_interaction.user.roles:
                    await claim_interaction.response.send_message("❌ You are not Ticket Support.", ephemeral=True)
                    return
                
                self.claimed = True
                self.claimer = claim_interaction.user
                
                await self.ticket_channel.set_permissions(
                    claim_interaction.user,
                    read_messages=True,
                    send_messages=True,
                    attach_files=True,
                    embed_links=True
                )
                
                embed = claim_interaction.message.embeds[0]
                embed.color = discord.Color.green()
                embed.add_field(name="Claimed by", value=claim_interaction.user.mention, inline=False)
                
                await claim_interaction.message.edit(embed=embed, view=None)
                await self.ticket_channel.send(f"✅ {claim_interaction.user.mention} has claimed this ticket!")
                await claim_interaction.response.send_message(f"✅ You claimed ticket #{self.ticket_channel.name}", ephemeral=True)
        
        await alert_channel.send(embed=embed, view=ClaimView(ticket_channel, user))


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.DB_FOLDER = DB_FOLDER
        self.active_tickets = {}  # Format: {guild_id: {user_id: channel_id}}
        self.ticket_ratings = {}  # Store ratings in memory
        self.processed_commands = {}  # Track processed commands to prevent duplicates
        self.setup_database()
        print(f"✅ Tickets cog initialized (ID: {id(self)})")
    
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
        """Initialize ticket tables in main database"""
        main_db = sqlite3.connect(os.path.join(self.DB_FOLDER, "asaiya_bot.db"))
        c = main_db.cursor()
        
        c.execute('''CREATE TABLE IF NOT EXISTS active_tickets
                     (guild_id TEXT,
                      user_id TEXT,
                      channel_id TEXT,
                      created_at REAL,
                      PRIMARY KEY (guild_id, user_id))''')
        
        # Add table for ticket ratings
        c.execute('''CREATE TABLE IF NOT EXISTS ticket_ratings
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      channel_id TEXT,
                      ticket_name TEXT,
                      rating INTEGER,
                      support_name TEXT,
                      support_id TEXT,
                      user_id TEXT,
                      created_at REAL)''')
        
        main_db.commit()
        main_db.close()
        print("✅ Tickets database initialized")
    
    async def has_open_ticket(self, user, guild):
        """Check if user has an open ticket"""
        guild_id = str(guild.id)
        user_id = str(user.id)
        
        # Check memory first
        if guild_id in self.active_tickets and user_id in self.active_tickets[guild_id]:
            channel_id = self.active_tickets[guild_id][user_id]
            channel = guild.get_channel(channel_id)
            if channel:
                return True
            else:
                # Clean up invalid channel
                del self.active_tickets[guild_id][user_id]
        
        # Check database
        main_db = sqlite3.connect(os.path.join(self.DB_FOLDER, "asaiya_bot.db"))
        c = main_db.cursor()
        c.execute("SELECT channel_id FROM active_tickets WHERE guild_id = ? AND user_id = ?",
                  (guild_id, user_id))
        result = c.fetchone()
        main_db.close()
        
        if result:
            channel_id = int(result[0])
            channel = guild.get_channel(channel_id)
            if channel:
                # Add back to memory
                if guild_id not in self.active_tickets:
                    self.active_tickets[guild_id] = {}
                self.active_tickets[guild_id][user_id] = channel_id
                return True
        
        return False
    
    async def add_active_ticket(self, guild_id, user_id, channel_id):
        """Add active ticket to memory and database"""
        guild_id = str(guild_id)
        user_id = str(user_id)
        channel_id = int(channel_id)
        
        # Add to memory
        if guild_id not in self.active_tickets:
            self.active_tickets[guild_id] = {}
        self.active_tickets[guild_id][user_id] = channel_id
        
        # Add to database
        main_db = sqlite3.connect(os.path.join(self.DB_FOLDER, "asaiya_bot.db"))
        c = main_db.cursor()
        c.execute("INSERT OR REPLACE INTO active_tickets (guild_id, user_id, channel_id, created_at) VALUES (?, ?, ?, ?)",
                  (guild_id, user_id, str(channel_id), time.time()))
        main_db.commit()
        main_db.close()
    
    async def remove_active_ticket(self, guild_id, user_id=None, channel_id=None):
        """Remove active ticket from memory and database"""
        guild_id = str(guild_id)
        
        # Remove from memory
        if guild_id in self.active_tickets:
            if user_id and user_id in self.active_tickets[guild_id]:
                del self.active_tickets[guild_id][user_id]
            elif channel_id:
                for uid, cid in list(self.active_tickets[guild_id].items()):
                    if cid == channel_id:
                        del self.active_tickets[guild_id][uid]
                        user_id = uid
                        break
        
        # Remove from database
        main_db = sqlite3.connect(os.path.join(self.DB_FOLDER, "asaiya_bot.db"))
        c = main_db.cursor()
        if user_id:
            c.execute("DELETE FROM active_tickets WHERE guild_id = ? AND user_id = ?",
                      (guild_id, user_id))
        elif channel_id:
            c.execute("DELETE FROM active_tickets WHERE guild_id = ? AND channel_id = ?",
                      (guild_id, str(channel_id)))
        main_db.commit()
        main_db.close()
    
    async def save_rating(self, channel_id, ticket_name, rating, support_name, support_id, user_id):
        """Save a ticket rating to database"""
        try:
            main_db = sqlite3.connect(os.path.join(self.DB_FOLDER, "asaiya_bot.db"))
            c = main_db.cursor()
            c.execute('''INSERT INTO ticket_ratings 
                         (channel_id, ticket_name, rating, support_name, support_id, user_id, created_at)
                         VALUES (?, ?, ?, ?, ?, ?, ?)''',
                      (str(channel_id), ticket_name, rating, support_name, str(support_id), str(user_id), time.time()))
            main_db.commit()
            main_db.close()
            
            # Also store in memory for quick access
            key = f"{channel_id}"
            self.ticket_ratings[key] = {
                'rating': rating,
                'support': support_name,
                'support_id': support_id,
                'user_id': user_id,
                'ticket': ticket_name,
                'timestamp': time.time()
            }
            return True
        except Exception as e:
            print(f"Error saving rating: {e}")
            return False
    
    async def get_rating_stats(self, guild_id=None):
        """Get rating statistics, optionally filtered by guild"""
        try:
            main_db = sqlite3.connect(os.path.join(self.DB_FOLDER, "asaiya_bot.db"))
            c = main_db.cursor()
            
            if guild_id:
                # Get channels in this guild
                c.execute('''SELECT rating, support_name, support_id, COUNT(*) as count
                             FROM ticket_ratings 
                             WHERE channel_id IN (SELECT channel_id FROM active_tickets WHERE guild_id = ?)
                             GROUP BY support_id, rating''', (str(guild_id),))
            else:
                # Global stats
                c.execute('''SELECT rating, support_name, support_id, COUNT(*) as count
                             FROM ticket_ratings 
                             GROUP BY support_id, rating''')
            
            results = c.fetchall()
            main_db.close()
            return results
        except Exception as e:
            print(f"Error getting rating stats: {e}")
            return []
    
    # ===== ARCHIVE CATEGORY MANAGEMENT =====
    async def get_log_channel(self, guild):
        """Get the log channel for a guild"""
        try:
            conn = self.get_cached_connection(guild.id)
            if not conn:
                return None
            c = conn.cursor()
            c.execute("SELECT log_channel_id FROM log_channels")
            result = c.fetchone()
            if result and result[0]:
                return guild.get_channel(int(result[0]))
        except:
            pass
        return None
    
    def get_cached_connection(self, guild_id):
        """Get cached database connection"""
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
    
    def get_server_db_path(self, guild_id):
        """Get database path for a specific server"""
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
    
    async def find_archive_category(self, guild):
        """
        Find the appropriate archive category for closing a ticket.
        Checks categories sequentially: Asaiya-Done, then Asaiya-Done 2, Asaiya-Done 3, etc.
        Returns the category to use.
        """
        # First, verify that the original Asaiya-Done category exists (created by setserver)
        original_category = discord.utils.get(guild.categories, name=ARCHIVE_BASE_NAME)
        if not original_category:
            # Category doesn't exist, tell user to run setserver
            raise Exception(f"Archive category '{ARCHIVE_BASE_NAME}' not found. Please run `!setserver` and choose the Ticket template first.")
        
        # Get all archive categories
        archive_categories = []
        
        # Add the original category first
        archive_categories.append(original_category)
        
        # Add overflow categories (Asaiya-Done 2, Asaiya-Done 3, etc.)
        for category in guild.categories:
            if category.name.startswith(f"{ARCHIVE_BASE_NAME}{OVERFLOW_PREFIX}") and category.name != ARCHIVE_BASE_NAME:
                # Extract the number to sort properly
                try:
                    # Get the number part (e.g., "Asaiya-Done 2" -> 2)
                    num_part = category.name.replace(f"{ARCHIVE_BASE_NAME}{OVERFLOW_PREFIX}", "")
                    if num_part.isdigit():
                        archive_categories.append((int(num_part), category))
                except:
                    pass
        
        # Sort overflow categories by number
        if len(archive_categories) > 1:
            # Sort the non-original ones by number
            overflow_sorted = sorted([(0, original_category)] + [(num, cat) for num, cat in archive_categories[1:]], key=lambda x: x[0])
            archive_categories = [cat for _, cat in overflow_sorted]
        
        # Check each category sequentially
        for category in archive_categories:
            # Count text channels in this category (only count channels that are actual ticket channels)
            channel_count = len([ch for ch in category.channels if isinstance(ch, discord.TextChannel)])
            
            if channel_count < MAX_TICKETS_PER_ARCHIVE:
                # This category has space
                return category
        
        # If we got here, all existing categories are full
        # Determine the next number for the new category
        next_number = 2  # Start with 2 (since original is 1)
        existing_numbers = set()
        
        for category in guild.categories:
            if category.name.startswith(f"{ARCHIVE_BASE_NAME}{OVERFLOW_PREFIX}"):
                try:
                    num_part = category.name.replace(f"{ARCHIVE_BASE_NAME}{OVERFLOW_PREFIX}", "")
                    if num_part.isdigit():
                        existing_numbers.add(int(num_part))
                except:
                    pass
        
        while next_number in existing_numbers:
            next_number += 1
        
        # Create the new category with the same permissions as the original
        new_category_name = f"{ARCHIVE_BASE_NAME}{OVERFLOW_PREFIX}{next_number}"
        
        # Copy permissions from original category
        overwrites = {}
        for target, overwrite in original_category.overwrites.items():
            overwrites[target] = overwrite
        
        new_category = await guild.create_category(new_category_name, overwrites=overwrites)
        
        # Log the creation
        log_channel = await self.get_log_channel(guild)
        if log_channel:
            await log_channel.send(f"📁 Category **{ARCHIVE_BASE_NAME}** is full ({MAX_TICKETS_PER_ARCHIVE}/{MAX_TICKETS_PER_ARCHIVE}). Created **{new_category_name}** to archive new tickets.")
        
        return new_category
    
    # ===== TICKET COMMANDS =====

    @commands.command(name='ticket')
    @commands.has_permissions(administrator=True)
    async def ticket_panel(self, ctx):
        """Create the ticket panel with button"""
        if await self.check_duplicate(ctx):
            return
            
        embed = discord.Embed(
            title="🎫 Support Ticket",
            description="Need help? Click the button below to create a ticket!",
            color=discord.Color.blue()
        )
        embed.add_field(name="How it works", 
                       value="1. Click the button\n2. Tell us what you need\n3. A support staff will help you!", 
                       inline=False)
        
        await ctx.send(embed=embed, view=TicketView())

    @commands.command(name='close')
    async def close_ticket(self, ctx):
        """Close the current ticket"""
        if await self.check_duplicate(ctx):
            return
            
        # Check if this is a ticket channel
        if not ctx.channel.category or not any(cat in ctx.channel.category.name.lower() for cat in ["ticket", "bug", "buy", "report", "verify"]):
            await ctx.send("❌ This command can only be used in ticket channels!")
            return
        
        # Check permissions
        request_role = discord.utils.get(ctx.guild.roles, name="asaiya-request")
        support_role = discord.utils.get(ctx.guild.roles, name="asaiya-support")
        
        has_permission = False
        is_creator = False
        
        if request_role and request_role in ctx.author.roles:
            has_permission = True
            is_creator = True
        if support_role and support_role in ctx.author.roles:
            has_permission = True
        
        if not has_permission:
            await ctx.send("❌ You don't have permission to close this ticket!")
            return
        
        # Find the ticket creator and claiming support
        ticket_creator = None
        claiming_support = None
        
        # Look for the person with request role
        for member in ctx.channel.members:
            if request_role and request_role in member.roles:
                ticket_creator = member
                break
        
        # Look for who claimed the ticket (from channel history)
        async for msg in ctx.channel.history(limit=50):
            if "claimed this ticket" in msg.content:
                # Extract the mention
                match = re.search(r'<@!?(\d+)>', msg.content)
                if match:
                    support_id = int(match.group(1))
                    claiming_support = ctx.guild.get_member(support_id)
                break
        
        # Confirmation
        confirm_msg = await ctx.send("⚠️ Are you sure you want to close this ticket? Type `yes` to confirm.")
        
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() == 'yes'
        
        try:
            await self.bot.wait_for('message', timeout=30.0, check=check)
            await confirm_msg.delete()
            
            # Store ticket info before closing (for rating)
            ticket_name = ctx.channel.name
            ticket_id = ctx.channel.id
            
            # Remove request role from user
            if request_role and ticket_creator:
                try:
                    await ticket_creator.remove_roles(request_role, reason="Ticket closed")
                except:
                    pass
            
            # Remove from active tickets
            if ticket_creator:
                await self.remove_active_ticket(ctx.guild.id, user_id=str(ticket_creator.id))
            else:
                await self.remove_active_ticket(ctx.guild.id, channel_id=ctx.channel.id)
            
            # ===== FIND THE APPROPRIATE ARCHIVE CATEGORY =====
            try:
                archive_category = await self.find_archive_category(ctx.guild)
            except Exception as e:
                await ctx.send(f"❌ {str(e)}")
                return
            
            # Move channel to archive category
            await ctx.channel.edit(category=archive_category)
            
            # Make channel invisible to everyone
            await ctx.channel.set_permissions(ctx.guild.default_role, read_messages=False)
            
            # Get the category name for the response
            category_name = archive_category.name
            if category_name == ARCHIVE_BASE_NAME:
                await ctx.send(f"✅ Ticket closed. Archived to {category_name}")
            else:
                await ctx.send(f"✅ Ticket closed. Archived to {category_name}")
            
            # SURPRISE: Send rating DM to the ticket creator (not the support staff)
            if ticket_creator and is_creator:
                await self.send_rating_surprise(ctx, ticket_creator, claiming_support, ticket_name, ticket_id)
            
        except asyncio.TimeoutError:
            await confirm_msg.edit(content="❌ Timed out. Ticket not closed.")

    async def send_rating_surprise(self, ctx, ticket_creator, claiming_support, ticket_name, ticket_id):
        """Send a surprise rating DM to the ticket creator"""
        # Wait a bit before sending
        await asyncio.sleep(3)
        
        try:
            # Create rating buttons
            class RatingView(discord.ui.View):
                def __init__(self, cog, support, ticket_name, ticket_id):
                    super().__init__(timeout=300)  # 5 minutes to respond
                    self.cog = cog
                    self.support = support
                    self.ticket_name = ticket_name
                    self.ticket_id = ticket_id
                
                @discord.ui.button(label="⭐", style=discord.ButtonStyle.grey, custom_id=f"rate_1_{int(time.time())}")
                async def rate_1(self, interaction: discord.Interaction, button: discord.ui.Button):
                    await self.submit_rating(interaction, 1)
                
                @discord.ui.button(label="⭐⭐", style=discord.ButtonStyle.grey, custom_id=f"rate_2_{int(time.time())}")
                async def rate_2(self, interaction: discord.Interaction, button: discord.ui.Button):
                    await self.submit_rating(interaction, 2)
                
                @discord.ui.button(label="⭐⭐⭐", style=discord.ButtonStyle.grey, custom_id=f"rate_3_{int(time.time())}")
                async def rate_3(self, interaction: discord.Interaction, button: discord.ui.Button):
                    await self.submit_rating(interaction, 3)
                
                @discord.ui.button(label="⭐⭐⭐⭐", style=discord.ButtonStyle.grey, custom_id=f"rate_4_{int(time.time())}")
                async def rate_4(self, interaction: discord.Interaction, button: discord.ui.Button):
                    await self.submit_rating(interaction, 4)
                
                @discord.ui.button(label="⭐⭐⭐⭐⭐", style=discord.ButtonStyle.grey, custom_id=f"rate_5_{int(time.time())}")
                async def rate_5(self, interaction: discord.Interaction, button: discord.ui.Button):
                    await self.submit_rating(interaction, 5)
                
                async def submit_rating(self, interaction: discord.Interaction, rating: int):
                    # Save the rating
                    support_name = self.support.name if self.support else "Unknown"
                    support_id = self.support.id if self.support else 0
                    
                    success = await self.cog.save_rating(
                        channel_id=self.ticket_id,
                        ticket_name=self.ticket_name,
                        rating=rating,
                        support_name=support_name,
                        support_id=support_id,
                        user_id=interaction.user.id
                    )
                    
                    if success:
                        stars = "⭐" * rating
                        await interaction.response.edit_message(
                            content=f"Thank you for your feedback! You rated this support {stars} ({rating}/5)\n\n*Your rating is anonymous - staff won't know who rated what*",
                            view=None
                        )
                        
                        # Send anonymous notification to staff logs
                        staff_category = discord.utils.get(ctx.guild.categories, name="Staff Team")
                        if staff_category:
                            logs_channel = discord.utils.get(staff_category.channels, name="ticket-logs")
                            if logs_channel:
                                embed = discord.Embed(
                                    title="📊 Ticket Rating Received",
                                    description=f"**Ticket:** {self.ticket_name}\n**Rating:** {stars} ({rating}/5)\n**Support:** {support_name}",
                                    color=discord.Color.gold() if rating >= 4 else discord.Color.orange() if rating == 3 else discord.Color.red(),
                                    timestamp=datetime.utcnow()
                                )
                                embed.set_footer(text="Rating is anonymous - user identity not shown")
                                await logs_channel.send(embed=embed)
                    else:
                        await interaction.response.edit_message(
                            content="❌ Failed to save rating. Please try again later.",
                            view=None
                        )
            
            # Create rating embed
            embed = discord.Embed(
                title="🎫 Ticket Closed",
                description="How would you rate the support you received?",
                color=discord.Color.blue()
            )
            
            if claiming_support:
                embed.add_field(name="Support Staff", value=claiming_support.name, inline=True)
            embed.add_field(name="Ticket", value=ticket_name, inline=True)
            embed.set_footer(text="Your feedback is anonymous - staff won't know who rated what")
            
            await ticket_creator.send(embed=embed, view=RatingView(self, claiming_support, ticket_name, ticket_id))
            print(f"✅ Sent rating DM to {ticket_creator.name} for ticket {ticket_name}")
            
        except discord.Forbidden:
            # User has DMs disabled - silently ignore
            print(f"⚠️ Could not send rating DM to {ticket_creator.name} (DMs disabled)")
        except Exception as e:
            print(f"Error sending rating DM: {e}")

    # ===== RATING STATS COMMAND =====
    @commands.command(name='ratingstats')
    @commands.has_permissions(administrator=True)
    async def rating_stats(self, ctx):
        """Show surprise rating statistics (staff don't know this exists for individual ratings)"""
        if await self.check_duplicate(ctx):
            return
            
        await ctx.message.delete()
        
        # Get stats from database
        results = await self.get_rating_stats(ctx.guild.id)
        
        if not results:
            # Also check memory cache
            if not self.ticket_ratings:
                await ctx.send("📊 No ratings recorded yet in this server.")
                return
        
        # Process results
        support_stats = {}
        total_ratings = 0
        total_score = 0
        rating_distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        
        for rating, support_name, support_id, count in results:
            if support_id not in support_stats:
                support_stats[support_id] = {
                    'name': support_name,
                    'total': 0,
                    'count': 0,
                    'distribution': {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
                }
            
            support_stats[support_id]['total'] += rating * count
            support_stats[support_id]['count'] += count
            support_stats[support_id]['distribution'][rating] = count
            
            total_ratings += count
            total_score += rating * count
            rating_distribution[rating] += count
        
        # Add memory cache ratings that might not be in DB yet
        for data in self.ticket_ratings.values():
            if data.get('guild_id') == ctx.guild.id:
                rating = data['rating']
                support_id = data.get('support_id', 0)
                support_name = data['support']
                
                if support_id not in support_stats:
                    support_stats[support_id] = {
                        'name': support_name,
                        'total': 0,
                        'count': 0,
                        'distribution': {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
                    }
                
                # Avoid double-counting (simple check)
                if f"mem_{data['timestamp']}" not in str(ctx.message.id):
                    support_stats[support_id]['total'] += rating
                    support_stats[support_id]['count'] += 1
                    support_stats[support_id]['distribution'][rating] += 1
                    total_ratings += 1
                    total_score += rating
                    rating_distribution[rating] += 1
        
        if total_ratings == 0:
            await ctx.send("📊 No ratings recorded yet in this server.")
            return
        
        avg_total = total_score / total_ratings
        
        # Create main embed
        embed = discord.Embed(
            title="📊 Surprise Rating Statistics",
            description=f"**Total Ratings:** {total_ratings}\n**Overall Average:** {avg_total:.2f}/5",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow()
        )
        
        # Add rating distribution
        dist_text = ""
        for stars in range(5, 0, -1):
            count = rating_distribution[stars]
            percentage = (count / total_ratings) * 100
            bar_length = int((count / total_ratings) * 20)
            bar = "█" * bar_length + "░" * (20 - bar_length)
            dist_text += f"{stars}⭐ {bar} {count} ({percentage:.1f}%)\n"
        
        embed.add_field(name="Rating Distribution", value=f"```{dist_text}```", inline=False)
        
        # Add per-support stats
        if support_stats:
            stats_text = ""
            for support_id, stats in sorted(support_stats.items(), key=lambda x: x[1]['total']/x[1]['count'] if x[1]['count']>0 else 0, reverse=True):
                if stats['count'] > 0:
                    avg = stats['total'] / stats['count']
                    stars = "⭐" * round(avg)
                    stats_text += f"• **{stats['name']}**: {avg:.2f}/5 {stars} ({stats['count']} ratings)\n"
            
            if stats_text:
                embed.add_field(name="Support Staff Averages", value=stats_text, inline=False)
        
        embed.set_footer(text="👥 Staff don't know individual ratings • Only you see this")
        await ctx.send(embed=embed)

    @commands.command(name='ratingdetail')
    @commands.has_permissions(administrator=True)
    async def rating_detail(self, ctx, support: discord.Member = None):
        """Show detailed ratings for a specific support member"""
        if await self.check_duplicate(ctx):
            return
            
        await ctx.message.delete()
        
        target = support or ctx.author
        support_id = str(target.id)
        
        # Get stats from database
        results = await self.get_rating_stats(ctx.guild.id)
        
        # Filter for this support member
        support_ratings = []
        total = 0
        count = 0
        distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        
        for rating, support_name, s_id, cnt in results:
            if str(s_id) == support_id:
                total += rating * cnt
                count += cnt
                distribution[rating] = cnt
                support_ratings.append((rating, cnt))
        
        # Add memory cache
        for data in self.ticket_ratings.values():
            if str(data.get('support_id')) == support_id:
                rating = data['rating']
                total += rating
                count += 1
                distribution[rating] += 1
        
        if count == 0:
            await ctx.send(f"📊 No ratings found for {target.mention} yet.")
            return
        
        avg = total / count
        
        embed = discord.Embed(
            title=f"📊 Rating Details for {target.display_name}",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(name="Total Ratings", value=str(count), inline=True)
        embed.add_field(name="Average Rating", value=f"{avg:.2f}/5", inline=True)
        
        # Distribution
        dist_text = ""
        for stars in range(5, 0, -1):
            cnt = distribution[stars]
            percentage = (cnt / count) * 100
            dist_text += f"{stars}⭐: {cnt} ({percentage:.1f}%)\n"
        
        embed.add_field(name="Distribution", value=dist_text, inline=False)
        
        # Star representation
        stars_display = "⭐" * round(avg) + "☆" * (5 - round(avg))
        embed.add_field(name="Rating", value=f"{stars_display} ({avg:.2f}/5)", inline=False)
        
        embed.set_footer(text="Only you can see these details")
        await ctx.send(embed=embed)

    # ===== EXISTING TICKET COMMANDS =====

    @commands.command(name='rename')
    async def rename_ticket(self, ctx, *, new_name: str):
        """Rename the current ticket channel"""
        if await self.check_duplicate(ctx):
            return
            
        # Check if this is a ticket channel
        if not ctx.channel.category or not any(cat in ctx.channel.category.name.lower() for cat in ["ticket", "bug", "buy", "report", "verify"]):
            await ctx.send("❌ This command can only be used in ticket channels!")
            return
        
        # Check permissions
        request_role = discord.utils.get(ctx.guild.roles, name="asaiya-request")
        support_role = discord.utils.get(ctx.guild.roles, name="asaiya-support")
        
        has_permission = False
        if request_role and request_role in ctx.author.roles:
            has_permission = True
        if support_role and support_role in ctx.author.roles:
            has_permission = True
        
        if not has_permission:
            await ctx.send("❌ You don't have permission to rename this ticket!")
            return
        
        # Generate safe channel name
        words = new_name.lower().split()[:5]
        channel_name = '-'.join(words)
        channel_name = re.sub(r'[^a-z0-9-]', '', channel_name)[:30]
        
        try:
            await ctx.channel.edit(name=channel_name, reason=f"Renamed by {ctx.author}")
            await ctx.send(f"✅ Channel renamed to **{channel_name}**")
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")

    @commands.command(name='ticketadd')
    async def ticket_add(self, ctx, *, name: str):
        """Add a user to the current ticket"""
        if await self.check_duplicate(ctx):
            return
            
        # Check if this is a ticket channel
        if not ctx.channel.category or not any(cat in ctx.channel.category.name.lower() for cat in ["ticket", "bug", "buy", "report", "verify"]):
            await ctx.send("❌ This command can only be used in ticket channels!")
            return
        
        # Check if user has support role
        support_role = discord.utils.get(ctx.guild.roles, name="asaiya-support")
        if not support_role or support_role not in ctx.author.roles:
            await ctx.send("❌ Only support staff can add users to tickets!")
            return
        
        # Search for member
        matching_members = []
        name_lower = name.lower()
        
        for member in ctx.guild.members:
            if member.bot:
                continue
            if (name_lower in member.name.lower() or 
                (member.nick and name_lower in member.nick.lower())):
                matching_members.append(member)
        
        if not matching_members:
            await ctx.send(f"❌ No members found with name containing '{name}'")
            return
        
        if len(matching_members) == 1:
            member = matching_members[0]
            try:
                await ctx.channel.set_permissions(
                    member,
                    read_messages=True,
                    send_messages=True,
                    attach_files=True,
                    embed_links=True
                )
                await ctx.send(f"✅ Added {member.mention} to this ticket.")
            except Exception as e:
                await ctx.send(f"❌ Error: {str(e)}")
            return
        
        # Multiple matches - show list
        member_list = "\n".join([f"{i+1}. {m.name}" for i, m in enumerate(matching_members[:10])])
        await ctx.send(f"Multiple members found:\n{member_list}\n\nPlease be more specific.")

    @commands.command(name='remove')
    async def ticket_remove(self, ctx, member: discord.Member):
        """Remove a user from the current ticket"""
        if await self.check_duplicate(ctx):
            return
            
        # Check if this is a ticket channel
        if not ctx.channel.category or not any(cat in ctx.channel.category.name.lower() for cat in ["ticket", "bug", "buy", "report", "verify"]):
            await ctx.send("❌ This command can only be used in ticket channels!")
            return
        
        # Check if user has support role
        support_role = discord.utils.get(ctx.guild.roles, name="asaiya-support")
        if not support_role or support_role not in ctx.author.roles:
            await ctx.send("❌ Only support staff can remove users from tickets!")
            return
        
        # Don't remove the ticket creator
        request_role = discord.utils.get(ctx.guild.roles, name="asaiya-request")
        if request_role and request_role in member.roles:
            await ctx.send("❌ Cannot remove the ticket creator!")
            return
        
        try:
            await ctx.channel.set_permissions(member, overwrite=None)
            await ctx.send(f"✅ Removed {member.mention} from this ticket.")
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)}")

    @commands.command(name='transfer')
    async def transfer_ticket(self, ctx):
        """Transfer ticket to another support staff"""
        if await self.check_duplicate(ctx):
            return
            
        # Check if this is a ticket channel
        if not ctx.channel.category or not any(cat in ctx.channel.category.name.lower() for cat in ["ticket", "bug", "buy", "report", "verify"]):
            await ctx.send("❌ This command can only be used in ticket channels!")
            return
        
        # Check if user has support role
        support_role = discord.utils.get(ctx.guild.roles, name="asaiya-support")
        if not support_role or support_role not in ctx.author.roles:
            await ctx.send("❌ Only support staff can transfer tickets!")
            return
        
        # Get all support members
        support_members = []
        for member in ctx.guild.members:
            if support_role in member.roles and member != ctx.author:
                support_members.append(member)
        
        if not support_members:
            await ctx.send("❌ No other support staff available to transfer to.")
            return
        
        # Create selection list
        member_list = "\n".join([f"{i+1}. {m.name}" for i, m in enumerate(support_members[:10])])
        await ctx.send(f"Available support staff:\n{member_list}\n\nReply with the number to transfer to:")
        
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        
        try:
            msg = await self.bot.wait_for('message', timeout=30.0, check=check)
            
            try:
                choice = int(msg.content)
                if 1 <= choice <= len(support_members):
                    target = support_members[choice - 1]
                    
                    # Remove current support's permissions
                    await ctx.channel.set_permissions(ctx.author, overwrite=None)
                    
                    # Add new support's permissions
                    await ctx.channel.set_permissions(
                        target,
                        read_messages=True,
                        send_messages=True,
                        attach_files=True,
                        embed_links=True
                    )
                    
                    await ctx.send(f"✅ Ticket transferred to {target.mention}")
                    
                    # DM the new support
                    try:
                        embed = discord.Embed(
                            title="🎫 Ticket Transferred to You",
                            description=f"You have been transferred a ticket in **{ctx.guild.name}**",
                            color=discord.Color.blue()
                        )
                        embed.add_field(name="Ticket Channel", value=ctx.channel.mention)
                        embed.add_field(name="Transferred by", value=ctx.author.mention)
                        await target.send(embed=embed)
                    except:
                        pass
                    
                else:
                    await ctx.send("❌ Invalid number.")
            except ValueError:
                await ctx.send("❌ Please enter a number.")
                
        except asyncio.TimeoutError:
            await ctx.send("⏰ Timed out. Transfer cancelled.")

    @commands.command(name='tickethelp')
    async def ticket_help(self, ctx):
        """Show available commands in ticket channels"""
        if await self.check_duplicate(ctx):
            return
            
        # Check if this is a ticket channel
        if not ctx.channel.category or not any(cat in ctx.channel.category.name.lower() for cat in ["ticket", "bug", "buy", "report", "verify"]):
            await ctx.send("❌ This command can only be used in ticket channels!")
            return
        
        request_role = discord.utils.get(ctx.guild.roles, name="asaiya-request")
        support_role = discord.utils.get(ctx.guild.roles, name="asaiya-support")
        
        has_request = request_role and request_role in ctx.author.roles
        has_support = support_role and support_role in ctx.author.roles
        
        embed = discord.Embed(
            title="🎫 Ticket Commands",
            color=discord.Color.blue()
        )
        
        if has_support:
            embed.description = "👋 **Support Staff Commands:**"
            embed.add_field(name="Commands", value=(
                "`!close` - Close this ticket\n"
                "`!rename <name>` - Rename this ticket\n"
                "`!transfer` - Transfer to another support\n"
                "`!ticketadd <name>` - Add a user\n"
                "`!remove @user` - Remove a user"
            ), inline=False)
            embed.color = discord.Color.green()
        elif has_request:
            embed.description = "📝 **Ticket Creator Commands:**"
            embed.add_field(name="Commands", value=(
                "`!close` - Close your ticket\n"
                "`!rename <name>` - Rename this ticket"
            ), inline=False)
            embed.color = discord.Color.orange()
        else:
            embed.description = "👤 **Participant Commands:**"
            embed.add_field(name="Commands", value=(
                "`!close` - Close this ticket (if allowed)\n"
                "`!rename <name>` - Rename this ticket (if allowed)"
            ), inline=False)
            embed.color = discord.Color.purple()
        
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Tickets(bot))
