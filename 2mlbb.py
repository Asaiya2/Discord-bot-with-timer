import discord
from discord.ext import commands
import sqlite3
import time
import os
import asyncio
from datetime import datetime

# ===== CONFIGURATION =====
DB_FOLDER = r"C:\Users\Kelly\Desktop\discord database"
MAIN_DB_PATH = os.path.join(DB_FOLDER, "asaiya_bot.db")
MLBB_DB_PATH = os.path.join(DB_FOLDER, "mlbb_profiles.db")

BOT_ROLE  = "AsaiyaBot"
KICK_ROLE = "AsaiyaKick"
BAN_ROLE  = "AsaiyaBan"

VERIFICATION_CHANNEL_NAME = "role-verification"
VERIFY_LOG_CHANNEL_NAME   = "verification-logs"

# MLBB Server ID
MLBB_SERVER_ID = 1485978412219891834

# Only this user can run !mlbbserver
MLBB_OWNER_ID = 1299719492598763636

# Lane title (role name prefix) → internal key
LANE_TITLES = {
    "guardian": "roam",
    "slayer":   "jungler",
    "deadeye":  "gold",
    "archmage": "mid",
    "warrior":  "exp",
}

# Internal key → display title
LANE_DISPLAY = {
    "roam":    "Guardian",
    "jungler": "Slayer",
    "gold":    "Deadeye",
    "mid":     "Archmage",
    "exp":     "Warrior",
}

# Roman numerals for levels 1–9
ROMAN = {
    1: "I", 2: "II", 3: "III", 4: "IV", 5: "V",
    6: "VI", 7: "VII", 8: "VIII", 9: "IX",
}
ROMAN_REVERSE = {v: k for k, v in ROMAN.items()}

# Role colors per level
LEVEL_COLORS = {
    9: 0xFF0000,
    8: 0xFF6600,
    7: 0xFFD700,
    6: 0x00CC44,
    5: 0x00CCFF,
    4: 0x4444FF,
    3: 0x9900FF,
    2: 0xFF66CC,
    1: 0xAAAAAA,
}

VALID_LANES = list(LANE_DISPLAY.keys())


# ===== MLBB PROFILE DATABASE =====
def init_mlbb_db():
    """Initialize MLBB profiles database"""
    try:
        os.makedirs(DB_FOLDER, exist_ok=True)
        conn = sqlite3.connect(MLBB_DB_PATH)
        c = conn.cursor()

        c.execute('''
            CREATE TABLE IF NOT EXISTS mlbb_profiles (
                user_id TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                mlbb_name TEXT NOT NULL,
                mlbb_id TEXT,
                server_id TEXT,
                highest_rank TEXT,
                main_role TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (user_id, guild_id)
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS mlbb_verified_users (
                user_id TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                lane TEXT NOT NULL,
                level INTEGER NOT NULL,
                verified_at REAL NOT NULL,
                verified_by TEXT,
                PRIMARY KEY (user_id, guild_id, lane)
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS mlbb_role_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                lane TEXT NOT NULL,
                level INTEGER NOT NULL,
                action TEXT NOT NULL,
                staff_id TEXT,
                created_at REAL NOT NULL
            )
        ''')

        conn.commit()
        conn.close()
        print(f"✅ MLBB database initialized at {MLBB_DB_PATH}")
        return True
    except Exception as e:
        print(f"❌ Error initializing MLBB database: {e}")
        return False


def get_mlbb_profile(user_id, guild_id):
    """Get MLBB profile for a user"""
    try:
        if not os.path.exists(MLBB_DB_PATH):
            init_mlbb_db()
        
        conn = sqlite3.connect(MLBB_DB_PATH)
        c = conn.cursor()
        c.execute('''SELECT mlbb_name, mlbb_id, server_id, highest_rank, main_role, created_at, updated_at
                     FROM mlbb_profiles WHERE user_id = ? AND guild_id = ?''',
                  (str(user_id), str(guild_id)))
        result = c.fetchone()
        conn.close()
        return result if result else None
    except Exception as e:
        print(f"Error getting MLBB profile: {e}")
        return None


def save_mlbb_profile(user_id, guild_id, mlbb_name, mlbb_id, server_id, highest_rank, main_role):
    """Save or update MLBB profile"""
    try:
        if not os.path.exists(MLBB_DB_PATH):
            init_mlbb_db()
        
        conn = sqlite3.connect(MLBB_DB_PATH)
        c = conn.cursor()
        now = time.time()
        
        c.execute("SELECT 1 FROM mlbb_profiles WHERE user_id = ? AND guild_id = ?",
                  (str(user_id), str(guild_id)))
        exists = c.fetchone()
        
        if exists:
            c.execute('''UPDATE mlbb_profiles 
                         SET mlbb_name = ?, mlbb_id = ?, server_id = ?, highest_rank = ?, main_role = ?, updated_at = ?
                         WHERE user_id = ? AND guild_id = ?''',
                      (mlbb_name, mlbb_id, server_id, highest_rank, main_role, now, str(user_id), str(guild_id)))
        else:
            c.execute('''INSERT INTO mlbb_profiles 
                         (user_id, guild_id, mlbb_name, mlbb_id, server_id, highest_rank, main_role, created_at, updated_at)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                      (str(user_id), str(guild_id), mlbb_name, mlbb_id, server_id, highest_rank, main_role, now, now))
        
        conn.commit()
        conn.close()
        print(f"✅ Saved MLBB profile for user {user_id} in guild {guild_id}")
        return True
    except Exception as e:
        print(f"❌ Error saving MLBB profile: {e}")
        return False


def delete_mlbb_profile(user_id, guild_id):
    """Delete MLBB profile for a user"""
    try:
        conn = sqlite3.connect(MLBB_DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM mlbb_profiles WHERE user_id = ? AND guild_id = ?",
                  (str(user_id), str(guild_id)))
        deleted = c.rowcount
        conn.commit()
        conn.close()
        return deleted > 0
    except Exception as e:
        print(f"Error deleting MLBB profile: {e}")
        return False


def get_all_mlbb_profiles(guild_id):
    """Get all MLBB profiles in a guild"""
    try:
        conn = sqlite3.connect(MLBB_DB_PATH)
        c = conn.cursor()
        c.execute('''SELECT user_id, mlbb_name, mlbb_id, server_id, highest_rank, main_role
                     FROM mlbb_profiles WHERE guild_id = ? ORDER BY mlbb_name''',
                  (str(guild_id),))
        results = c.fetchall()
        conn.close()
        return results
    except Exception as e:
        print(f"Error getting all MLBB profiles: {e}")
        return []


# ===== MLBB PROFILE EDIT VIEW (DM) =====
class MLBBEditView(discord.ui.View):
    """View for editing MLBB profile in DM"""
    def __init__(self, cog, user_id, guild_id):
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = user_id
        self.guild_id = guild_id
        self.profile = get_mlbb_profile(user_id, guild_id)

    @discord.ui.button(label="1️⃣ MLBB Name", style=discord.ButtonStyle.blurple, row=0)
    async def edit_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not for you!", ephemeral=True)
            return
        await self.cog.start_mlbb_edit_dm(interaction, self.user_id, self.guild_id, "name")

    @discord.ui.button(label="2️⃣ MLBB ID + Server", style=discord.ButtonStyle.blurple, row=0)
    async def edit_id(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not for you!", ephemeral=True)
            return
        await self.cog.start_mlbb_edit_dm(interaction, self.user_id, self.guild_id, "id")

    @discord.ui.button(label="3️⃣ Highest Rank", style=discord.ButtonStyle.blurple, row=1)
    async def edit_rank(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not for you!", ephemeral=True)
            return
        await self.cog.start_mlbb_edit_dm(interaction, self.user_id, self.guild_id, "rank")

    @discord.ui.button(label="4️⃣ Main Role", style=discord.ButtonStyle.blurple, row=1)
    async def edit_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not for you!", ephemeral=True)
            return
        await self.cog.start_mlbb_edit_dm(interaction, self.user_id, self.guild_id, "role")

    @discord.ui.button(label="✅ Done", style=discord.ButtonStyle.green, row=2)
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not for you!", ephemeral=True)
            return
        
        # Get the guild
        guild = self.cog.bot.get_guild(self.guild_id)
        guild_name = guild.name if guild else "the server"
        
        # Create success message
        embed = discord.Embed(
            title="✅ MLBB Profile Updated!",
            description=f"Your MLBB profile for **{guild_name}** has been saved!",
            color=discord.Color.green()
        )
        
        # Get updated profile
        profile = get_mlbb_profile(self.user_id, self.guild_id)
        if profile:
            mlbb_name, mlbb_id, server_id, highest_rank, main_role, _, _ = profile
            embed.add_field(name="MLBB Name", value=mlbb_name, inline=True)
            if mlbb_id and server_id:
                embed.add_field(name="ID + Server", value=f"{mlbb_id} ({server_id})", inline=True)
            embed.add_field(name="Highest Rank", value=highest_rank, inline=True)
            embed.add_field(name="Main Role", value=main_role, inline=True)
        
        embed.set_footer(text="Anyone can view your profile with !mlid @username")
        
        # Disable all buttons
        for item in self.children:
            item.disabled = True
        
        # Edit the message with new embed and disabled buttons
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()


# ===== MLBB PROFILE CREATION VIEW (DM Confirmation) =====
class MLBBConfirmView(discord.ui.View):
    def __init__(self, cog, user_id, guild_id, data):
        super().__init__(timeout=60)
        self.cog = cog
        self.user_id = user_id
        self.guild_id = guild_id
        self.data = data

    @discord.ui.button(label="✅ Save Profile", style=discord.ButtonStyle.green)
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Acknowledge the interaction immediately
        await interaction.response.defer()
        
        if interaction.user.id != self.user_id:
            await interaction.followup.send("❌ This is not for you!", ephemeral=True)
            return
        
        # Save to database
        success = save_mlbb_profile(self.user_id, self.guild_id, **self.data)
        
        # Get the guild
        guild = self.cog.bot.get_guild(self.guild_id)
        guild_name = guild.name if guild else "the server"
        
        if success:
            embed = discord.Embed(
                title="✅ MLBB Profile Created!",
                description=f"Your MLBB profile for **{guild_name}** has been saved!",
                color=discord.Color.green()
            )
            embed.add_field(name="MLBB Name", value=self.data['mlbb_name'], inline=True)
            if self.data.get('mlbb_id') and self.data.get('server_id'):
                embed.add_field(name="ID + Server", value=f"{self.data['mlbb_id']} ({self.data['server_id']})", inline=True)
            embed.add_field(name="Highest Rank", value=self.data['highest_rank'], inline=True)
            embed.add_field(name="Main Role", value=self.data['main_role'], inline=True)
            embed.set_footer(text="Anyone can view your profile with !mlid @username")
            
            # Disable all buttons
            for item in self.children:
                item.disabled = True
            
            # Edit the original message with the new embed and disabled buttons
            await interaction.edit_original_response(embed=embed, view=self)
            self.stop()
        else:
            await interaction.followup.send("❌ Error saving profile. Please try again later.", ephemeral=True)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Acknowledge the interaction immediately
        await interaction.response.defer()
        
        if interaction.user.id != self.user_id:
            await interaction.followup.send("❌ This is not for you!", ephemeral=True)
            return
        
        # Disable all buttons
        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(content="❌ MLBB profile creation cancelled.", view=self)
        self.stop()


# ===== MLBB COG =====
class MLBB(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        init_mlbb_db()
        self.pending_mlbb_setup = {}
        self.processed_commands = {}
        print("✅ MLBB cog initialized")

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

    # ===== PERMISSION HELPERS =====
    def has_staff_role(self, member: discord.Member) -> bool:
        return any(role.name in [BOT_ROLE, KICK_ROLE, BAN_ROLE] for role in member.roles)

    # ===== MLBB PROFILE COMMANDS =====
    @commands.command(name='mlbbid')
    async def mlbbid(self, ctx):
        """Create or edit your MLBB profile (process happens in DMs)"""
        if await self.check_duplicate(ctx):
            return
        
        if ctx.guild.id != MLBB_SERVER_ID:
            await ctx.send("❌ This command is only available in the MLBB server.")
            return
        
        user_id = ctx.author.id
        guild_id = ctx.guild.id
        existing_profile = get_mlbb_profile(user_id, guild_id)
        
        try:
            if existing_profile:
                embed = discord.Embed(
                    title="📝 Edit Your MLBB Profile",
                    description="You already have an MLBB profile. What would you like to change?",
                    color=discord.Color.blue()
                )
                mlbb_name, mlbb_id, server_id, highest_rank, main_role, _, _ = existing_profile
                embed.add_field(name="Current Profile", value=f"**Name:** {mlbb_name}\n**ID:** {mlbb_id} ({server_id})\n**Rank:** {highest_rank}\n**Role:** {main_role}", inline=False)
                
                view = MLBBEditView(self, user_id, guild_id)
                await ctx.author.send(embed=embed, view=view)
            else:
                await self.start_mlbb_creation_dm(ctx.author, guild_id)
            
            await ctx.send(f"📬 I've sent you a DM to set up your MLBB profile! Check your DMs.")
            
        except discord.Forbidden:
            await ctx.send("❌ I couldn't DM you. Please enable DMs and try again.")

    async def start_mlbb_creation_dm(self, user, guild_id):
        user_id = user.id
        
        if user_id in self.pending_mlbb_setup:
            await user.send("⚠️ You already have an active setup. Please complete it first.")
            return
        
        self.pending_mlbb_setup[user_id] = {
            "step": 1,
            "data": {},
            "guild_id": guild_id
        }
        
        embed = discord.Embed(
            title="📝 Create Your MLBB Profile",
            description="Let's set up your MLBB profile!\n\n**Step 1/5**\nEnter your MLBB account name:",
            color=discord.Color.blue()
        )
        await user.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message):
        """Handle MLBB profile creation messages in DMs"""
        if not isinstance(message.channel, discord.DMChannel):
            return
        
        if message.author.bot:
            return
        
        user_id = message.author.id
        
        if user_id not in self.pending_mlbb_setup:
            return
        
        setup = self.pending_mlbb_setup[user_id]
        guild_id = setup["guild_id"]
        guild = self.bot.get_guild(guild_id)
        
        if not guild:
            await message.channel.send("❌ Server not found. Please run `!mlbbid` again.")
            del self.pending_mlbb_setup[user_id]
            return
        
        if setup["step"] == 1:
            if not message.content.strip():
                await message.channel.send("❌ Please enter a valid MLBB account name.")
                return
            
            setup["data"]["mlbb_name"] = message.content.strip()[:50]
            setup["step"] = 2
            
            embed = discord.Embed(
                title="📝 Step 2/5",
                description="Enter your MLBB ID and Server ID.\n\nFormat: `1234567890 3556`\n*(ID first, then Server ID, separated by space)*\n\nType `skip` if you want to leave this empty.",
                color=discord.Color.blue()
            )
            await message.channel.send(embed=embed)
            
        elif setup["step"] == 2:
            content = message.content.strip()
            if content.lower() == "skip":
                setup["data"]["mlbb_id"] = None
                setup["data"]["server_id"] = None
            else:
                parts = content.split()
                if len(parts) >= 2:
                    setup["data"]["mlbb_id"] = parts[0]
                    setup["data"]["server_id"] = parts[1]
                else:
                    setup["data"]["mlbb_id"] = content
                    setup["data"]["server_id"] = None
            setup["step"] = 3
            
            embed = discord.Embed(
                title="📝 Step 3/5",
                description="Enter your highest rank in MLBB.\n\nExample: `Mythical Glory 120 Stars`, `Legend`, `Epic`, etc.",
                color=discord.Color.blue()
            )
            await message.channel.send(embed=embed)
            
        elif setup["step"] == 3:
            if not message.content.strip():
                await message.channel.send("❌ Please enter your highest rank.")
                return
            
            setup["data"]["highest_rank"] = message.content.strip()[:50]
            setup["step"] = 4
            
            embed = discord.Embed(
                title="📝 Step 4/5",
                description="Enter your main role.\n\nOptions: `Roam`, `Jungler`, `Gold`, `Mid`, `Exp`\n*(You can also type your own if not listed)*",
                color=discord.Color.blue()
            )
            await message.channel.send(embed=embed)
            
        elif setup["step"] == 4:
            if not message.content.strip():
                await message.channel.send("❌ Please enter your main role.")
                return
            
            setup["data"]["main_role"] = message.content.strip()[:50]
            setup["step"] = 5
            
            data = setup["data"]
            embed = discord.Embed(
                title="📝 Step 5/5 - Confirm Your Profile",
                description="Please confirm your MLBB profile details:",
                color=discord.Color.gold()
            )
            embed.add_field(name="MLBB Name", value=data['mlbb_name'], inline=True)
            if data.get('mlbb_id') and data.get('server_id'):
                embed.add_field(name="ID + Server", value=f"{data['mlbb_id']} ({data['server_id']})", inline=True)
            else:
                embed.add_field(name="ID + Server", value="*Not provided*", inline=True)
            embed.add_field(name="Highest Rank", value=data['highest_rank'], inline=True)
            embed.add_field(name="Main Role", value=data['main_role'], inline=True)
            
            view = MLBBConfirmView(self, user_id, guild_id, data)
            await message.channel.send(embed=embed, view=view)
            del self.pending_mlbb_setup[user_id]

    async def start_mlbb_edit_dm(self, interaction, user_id, guild_id, field):
        """Start editing a specific field in DM"""
        profile = get_mlbb_profile(user_id, guild_id)
        if not profile:
            await interaction.response.send_message("❌ Profile not found!", ephemeral=True)
            return
        
        mlbb_name, mlbb_id, server_id, highest_rank, main_role, _, _ = profile
        
        field_prompts = {
            "name": ("MLBB Name", f"Current: {mlbb_name}\n\nEnter new MLBB name:"),
            "id": ("MLBB ID + Server", f"Current: {mlbb_id} ({server_id})\n\nEnter new ID and Server (format: `ID ServerID`) or type `skip`:"),
            "rank": ("Highest Rank", f"Current: {highest_rank}\n\nEnter new highest rank:"),
            "role": ("Main Role", f"Current: {main_role}\n\nEnter new main role:")
        }
        
        title, prompt = field_prompts[field]
        
        embed = discord.Embed(
            title=f"✏️ Edit {title}",
            description=prompt,
            color=discord.Color.blue()
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
        
        def check(m):
            return m.author.id == user_id and isinstance(m.channel, discord.DMChannel)
        
        try:
            msg = await self.bot.wait_for('message', timeout=60.0, check=check)
            new_value = msg.content.strip()
            
            if field == "name":
                mlbb_name = new_value
            elif field == "id":
                if new_value.lower() == "skip":
                    mlbb_id = None
                    server_id = None
                else:
                    parts = new_value.split()
                    mlbb_id = parts[0]
                    server_id = parts[1] if len(parts) > 1 else None
            elif field == "rank":
                highest_rank = new_value
            elif field == "role":
                main_role = new_value
            
            if save_mlbb_profile(user_id, guild_id, mlbb_name, mlbb_id, server_id, highest_rank, main_role):
                guild = self.bot.get_guild(guild_id)
                guild_name = guild.name if guild else "the server"
                
                embed = discord.Embed(
                    title="✅ Profile Updated!",
                    description=f"Your {title} has been updated.\n\nYour MLBB profile for **{guild_name}** has been saved!",
                    color=discord.Color.green()
                )
                embed.set_footer(text="Anyone can view your profile with !mlid @username")
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send("❌ Error updating profile.")
                
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timed out. Edit cancelled.")

    # ===== MLID COMMANDS =====
    @commands.command(name='mlid')
    async def mlid(self, ctx, *, target: discord.Member = None):
        """View MLBB profile. Use !mlid @user to view someone else's."""
        if await self.check_duplicate(ctx):
            return
        
        if ctx.guild.id != MLBB_SERVER_ID:
            await ctx.send("❌ This command is only available in the MLBB server.")
            return
        
        if target is None:
            target = ctx.author
        
        if target != ctx.author and not self.has_staff_role(ctx.author):
            await ctx.send("❌ You can only view your own MLBB profile. Staff can view anyone.")
            return
        
        profile = get_mlbb_profile(target.id, ctx.guild.id)
        
        if not profile:
            await ctx.send(f"❌ {target.mention} does not have an MLBB profile yet. Use `!mlbbid` to create one.")
            return
        
        mlbb_name, mlbb_id, server_id, highest_rank, main_role, created_at, updated_at = profile
        
        embed = discord.Embed(
            title=f"🎮 MLBB Profile: {target.display_name}",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=target.avatar.url if target.avatar else target.default_avatar.url)
        
        embed.add_field(name="MLBB Name", value=mlbb_name, inline=True)
        
        if mlbb_id and server_id:
            embed.add_field(name="ID + Server", value=f"{mlbb_id} ({server_id})", inline=True)
        
        embed.add_field(name="Highest Rank", value=highest_rank, inline=True)
        embed.add_field(name="Main Role", value=main_role, inline=True)
        
        embed.set_footer(text=f"Profile created: {datetime.fromtimestamp(created_at).strftime('%Y-%m-%d')}")
        
        await ctx.send(embed=embed)

    @commands.command(name='mlidlist')
    @commands.has_permissions(administrator=True)
    async def mlid_list(self, ctx):
        """List all MLBB profiles in this server (staff only)"""
        if await self.check_duplicate(ctx):
            return
        
        if ctx.guild.id != MLBB_SERVER_ID:
            await ctx.send("❌ This command is only available in the MLBB server.")
            return
        
        if not self.has_staff_role(ctx.author):
            await ctx.send("❌ Only staff can use this command.")
            return
        
        profiles = get_all_mlbb_profiles(ctx.guild.id)
        
        if not profiles:
            await ctx.send("📭 No MLBB profiles found in this server.")
            return
        
        embed = discord.Embed(
            title="📋 MLBB Profiles",
            description=f"Total: {len(profiles)} profile(s)",
            color=discord.Color.blue()
        )
        
        for user_id, mlbb_name, mlbb_id, server_id, highest_rank, main_role in profiles:
            member = ctx.guild.get_member(int(user_id))
            member_name = member.display_name if member else f"Unknown ({user_id})"
            
            id_display = f"{mlbb_id} ({server_id})" if mlbb_id and server_id else "Not set"
            embed.add_field(
                name=f"{member_name}",
                value=f"**MLBB:** {mlbb_name}\n**ID:** {id_display}\n**Rank:** {highest_rank}\n**Role:** {main_role}",
                inline=False
            )
        
        await ctx.send(embed=embed)

    @commands.command(name='mliddelete')
    @commands.has_permissions(administrator=True)
    async def mlid_delete(self, ctx, user: discord.Member):
        """Delete a user's MLBB profile (staff only)"""
        if await self.check_duplicate(ctx):
            return
        
        if ctx.guild.id != MLBB_SERVER_ID:
            await ctx.send("❌ This command is only available in the MLBB server.")
            return
        
        if not self.has_staff_role(ctx.author):
            await ctx.send("❌ Only staff can use this command.")
            return
        
        profile = get_mlbb_profile(user.id, ctx.guild.id)
        if not profile:
            await ctx.send(f"❌ {user.mention} does not have an MLBB profile.")
            return
        
        await ctx.send(f"⚠️ Are you sure you want to delete {user.mention}'s MLBB profile? Type `CONFIRM` to proceed.")
        
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        
        try:
            msg = await self.bot.wait_for('message', timeout=30.0, check=check)
            if msg.content.strip().upper() == "CONFIRM":
                await msg.delete()
                if delete_mlbb_profile(user.id, ctx.guild.id):
                    await ctx.send(f"✅ Deleted MLBB profile for {user.mention}")
                else:
                    await ctx.send("❌ Error deleting profile.")
            else:
                await ctx.send("❌ Deletion cancelled.")
        except asyncio.TimeoutError:
            await ctx.send("⏰ Timed out. Deletion cancelled.")

    # ===== MLBB LANE SYSTEM (Existing) =====
    
    # ===== DATABASE HELPERS =====
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

    def get_cached_connection(self, guild_id):
        """Get cached database connection"""
        current_time = time.time()

        if hasattr(self.bot, 'db_connections') and len(self.bot.db_connections) > 10:
            for gid, last_used in list(self.bot.last_db_use.items()):
                if current_time - last_used > 300:
                    try:
                        if gid in self.bot.db_connections:
                            self.bot.db_connections[gid].close()
                            del self.bot.db_connections[gid]
                        del self.bot.last_db_use[gid]
                    except:
                        pass

        if hasattr(self.bot, 'db_connections') and guild_id in self.bot.db_connections:
            try:
                self.bot.db_connections[guild_id].execute("SELECT 1")
                if hasattr(self.bot, 'last_db_use'):
                    self.bot.last_db_use[guild_id] = current_time
                return self.bot.db_connections[guild_id]
            except:
                try:
                    self.bot.db_connections[guild_id].close()
                except:
                    pass
                if guild_id in self.bot.db_connections:
                    del self.bot.db_connections[guild_id]

        db_path = self.get_server_db_path(guild_id)
        if not db_path or not os.path.exists(db_path):
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

    # ===== EXISTING MLBB METHODS =====
    def db_get_user_lanes(self, user_id: int, guild_id: int):
        conn = sqlite3.connect(MLBB_DB_PATH)
        c = conn.cursor()
        c.execute(
            "SELECT lane, level FROM mlbb_verified_users WHERE user_id = ? AND guild_id = ?",
            (str(user_id), str(guild_id))
        )
        rows = c.fetchall()
        conn.close()
        return rows

    def db_get_user_lane(self, user_id: int, guild_id: int, lane: str):
        conn = sqlite3.connect(MLBB_DB_PATH)
        c = conn.cursor()
        c.execute(
            "SELECT level FROM mlbb_verified_users WHERE user_id = ? AND guild_id = ? AND lane = ?",
            (str(user_id), str(guild_id), lane)
        )
        row = c.fetchone()
        conn.close()
        return row[0] if row else None

    def db_set_user_lane(self, user_id: int, guild_id: int, lane: str, level: int, staff_id=None):
        conn = sqlite3.connect(MLBB_DB_PATH)
        c = conn.cursor()
        c.execute(
            '''INSERT OR REPLACE INTO mlbb_verified_users
               (user_id, guild_id, lane, level, verified_at, verified_by)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (str(user_id), str(guild_id), lane, level, time.time(),
             str(staff_id) if staff_id else None)
        )
        c.execute(
            '''INSERT INTO mlbb_role_logs
               (user_id, guild_id, lane, level, action, staff_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (str(user_id), str(guild_id), lane, level, "assign",
             str(staff_id) if staff_id else "auto", time.time())
        )
        conn.commit()
        conn.close()

    def db_remove_user_lane(self, user_id: int, guild_id: int, lane: str):
        conn = sqlite3.connect(MLBB_DB_PATH)
        c = conn.cursor()
        c.execute(
            "DELETE FROM mlbb_verified_users WHERE user_id = ? AND guild_id = ? AND lane = ?",
            (str(user_id), str(guild_id), lane)
        )
        conn.commit()
        conn.close()

    def parse_role_name(self, role_name: str):
        """Parse 'Guardian V' → ('roam', 5)"""
        parts = role_name.strip().split()
        if len(parts) != 2:
            return None, None

        title = parts[0].lower()
        roman = parts[1].upper()

        lane = LANE_TITLES.get(title)
        if not lane:
            return None, None

        level = ROMAN_REVERSE.get(roman)
        if not level:
            return None, None

        return lane, level

    # ===== EVENT: AUTO MEMBER ROLE ON JOIN =====
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Assign @Member role to every new member automatically."""
        if member.guild.id != MLBB_SERVER_ID:
            return
        member_role = discord.utils.get(member.guild.roles, name="Member")
        if member_role:
            try:
                await member.add_roles(member_role, reason="Auto Member role on join")
            except discord.Forbidden:
                print(f"⚠️ Could not assign Member role to {member}")

    # ===== EVENT: IMAGES ONLY IN #role-verification =====
    @commands.Cog.listener()
    async def on_message_mlbb(self, message: discord.Message):
        """In #role-verification: Delete any message that has no image attachment."""
        if message.author.bot or not message.guild:
            return
        if message.guild.id != MLBB_SERVER_ID:
            return
        if message.channel.name != VERIFICATION_CHANNEL_NAME:
            return

        if self.has_staff_role(message.author):
            return

        has_image = any(
            att.content_type and att.content_type.startswith("image/")
            for att in message.attachments
        )

        if not has_image:
            try:
                await message.delete()
                await message.channel.send(
                    f"⚠️ {message.author.mention} Only image screenshots are allowed here!",
                    delete_after=5
                )
            except discord.Forbidden:
                pass

    # ===== EVENT: DETECT MLBB ROLE ASSIGNED =====
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """When staff manually adds an MLBB level role, update database."""
        if after.guild.id != MLBB_SERVER_ID:
            return
            
        added_roles = [r for r in after.roles if r not in before.roles]

        for role in added_roles:
            lane, level = self.parse_role_name(role.name)
            if not lane or not level:
                continue

            guild = after.guild
            user_id = after.id
            guild_id = guild.id

            current_level = self.db_get_user_lane(user_id, guild_id, lane)

            # Remove old role for this lane if it exists and is different
            if current_level and current_level != level:
                old_role_name = get_role_name(lane, current_level)
                old_role = discord.utils.get(guild.roles, name=old_role_name)
                if old_role and old_role in after.roles:
                    try:
                        await after.remove_roles(old_role, reason="MLBB lane level upgrade")
                    except Exception as e:
                        print(f"⚠️ Could not remove old role {old_role_name}: {e}")

            # Update database
            self.db_set_user_lane(user_id, guild_id, lane, level)

            # Delete proof image from #role-verification
            verify_channel = discord.utils.get(
                guild.text_channels, name=VERIFICATION_CHANNEL_NAME
            )
            if verify_channel:
                try:
                    async for msg in verify_channel.history(limit=100):
                        if msg.author.id == user_id:
                            has_image = any(
                                att.content_type and att.content_type.startswith("image/")
                                for att in msg.attachments
                            )
                            if has_image:
                                await msg.delete()
                                break
                except Exception as e:
                    print(f"⚠️ Could not delete proof image: {e}")

            # Log to #verification-logs
            log_channel = discord.utils.get(
                guild.text_channels, name=VERIFY_LOG_CHANNEL_NAME
            )
            if log_channel:
                action_text = (
                    f"⬆️ Upgraded from **{LANE_DISPLAY[lane]} {ROMAN[current_level]}** → **{role.name}**"
                    if current_level and current_level != level
                    else f"✅ Assigned **{role.name}** (new lane)"
                )
                embed = discord.Embed(
                    title="📋 MLBB Role Assigned",
                    color=LEVEL_COLORS.get(level, 0xAAAAAA),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="User", value=after.mention, inline=True)
                embed.add_field(name="Lane", value=LANE_DISPLAY[lane], inline=True)
                embed.add_field(name="Level", value=str(level), inline=True)
                embed.add_field(name="Action", value=action_text, inline=False)
                embed.set_footer(text=f"User ID: {user_id}")
                try:
                    await log_channel.send(embed=embed)
                except Exception as e:
                    print(f"⚠️ Could not send verification log: {e}")

    # ===== EXISTING COMMANDS =====
    @commands.command(name="mlbb-status")
    async def mlbb_status(self, ctx, member: discord.Member = None):
        """Show verified lanes and levels for a user."""
        if ctx.guild.id != MLBB_SERVER_ID:
            await ctx.send("❌ This command is only available in the MLBB server.")
            return
            
        target = member or ctx.author

        lanes = self.db_get_user_lanes(target.id, ctx.guild.id)
        lane_map = {lane: level for lane, level in lanes}

        embed = discord.Embed(
            title=f"🎮 MLBB Status — {target.display_name}",
            color=discord.Color.blue()
        )

        for lane_key, title in LANE_DISPLAY.items():
            if lane_key in lane_map:
                lvl = lane_map[lane_key]
                embed.add_field(
                    name=f"✅ {title}",
                    value=f"Level {lvl} ({ROMAN[lvl]})",
                    inline=True
                )
            else:
                embed.add_field(
                    name=f"⬜ {title}",
                    value="Not verified",
                    inline=True
                )

        embed.set_thumbnail(url=target.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name="mlbb-roles")
    async def mlbb_roles(self, ctx):
        """Show all available MLBB level roles."""
        if ctx.guild.id != MLBB_SERVER_ID:
            await ctx.send("❌ This command is only available in the MLBB server.")
            return
            
        embed = discord.Embed(
            title="🏆 MLBB Available Roles",
            description="All lane level roles you can earn by submitting proof in #role-verification",
            color=discord.Color.gold()
        )

        for level in range(9, 0, -1):
            role_list = " | ".join(
                [f"`{title} {ROMAN[level]}`" for title in LANE_DISPLAY.values()]
            )
            embed.add_field(
                name=f"Level {level}",
                value=role_list,
                inline=False
            )

        await ctx.send(embed=embed)

    @commands.command(name="mlbbserver")
    async def mlbb_server(self, ctx):
        """Creates all MLBB server categories, channels, and roles."""
        if ctx.author.id != MLBB_OWNER_ID:
            await ctx.send("❌ You don't have permission to use this command.")
            return

        guild = ctx.guild
        status = await ctx.send("⚙️ Setting up MLBB server... please wait.")
        created = []
        skipped = []

        async def get_or_create_role(name, color=discord.Color.default(), hoist=False, mentionable=False):
            existing = discord.utils.get(guild.roles, name=name)
            if existing:
                skipped.append(f"Role: `{name}`")
                return existing
            role = await guild.create_role(name=name, color=color, hoist=hoist, mentionable=mentionable)
            created.append(f"Role: `{name}`")
            return role

        async def get_or_create_category(name, overwrites=None):
            existing = discord.utils.get(guild.categories, name=name)
            if existing:
                skipped.append(f"Category: `{name}`")
                return existing
            cat = await guild.create_category(name=name, overwrites=overwrites or {})
            created.append(f"Category: `{name}`")
            return cat

        async def get_or_create_channel(name, category, overwrites=None, slowmode=3, topic=None):
            existing = discord.utils.get(guild.text_channels, name=name)
            if existing:
                skipped.append(f"Channel: `#{name}`")
                return existing
            ch = await guild.create_text_channel(
                name=name,
                category=category,
                overwrites=overwrites or {},
                slowmode_delay=slowmode,
                topic=topic
            )
            created.append(f"Channel: `#{name}`")
            return ch

        # STEP 1 — ROLES
        await status.edit(content="⚙️ Creating roles...")

        role_admin = await get_or_create_role("Server Administrator")
        role_mod = await get_or_create_role("Server Moderator")
        role_chanmod = await get_or_create_role("Channel Moderator")
        role_cc = await get_or_create_role("Content Creator")
        role_member = await get_or_create_role("Member")

        await get_or_create_role("WORST FAMILLIA", hoist=True)
        await get_or_create_role("Asaiya DC Bot")

        for lane_role in ["Roamer", "Core", "Mage", "Fighter", "Marksman"]:
            await get_or_create_role(lane_role)

        for level in range(9, 0, -1):
            color = discord.Color(LEVEL_COLORS[level])
            for title in LANE_DISPLAY.values():
                await get_or_create_role(f"{title} {ROMAN[level]}", color=color, mentionable=True)

        # STEP 2 — PERMISSION SETS
        await status.edit(content="⚙️ Building permission sets...")

        everyone = guild.default_role

        def read_only_overwrites():
            ow = {everyone: discord.PermissionOverwrite(read_messages=True, send_messages=False)}
            for r in [role_admin, role_mod, role_chanmod, role_cc]:
                ow[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            return ow

        def member_overwrites():
            return {
                everyone: discord.PermissionOverwrite(read_messages=False, send_messages=False),
                role_member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                role_admin: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                role_mod: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                role_chanmod: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            }

        def staff_only_overwrites():
            ow = {everyone: discord.PermissionOverwrite(read_messages=False, send_messages=False)}
            for r in [role_admin, role_mod, role_chanmod]:
                ow[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            return ow

        def howto_overwrites():
            return {
                everyone: discord.PermissionOverwrite(read_messages=False, send_messages=False),
                role_member: discord.PermissionOverwrite(read_messages=True, send_messages=False),
                role_admin: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                role_mod: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                role_chanmod: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            }

        def verification_overwrites():
            return {
                everyone: discord.PermissionOverwrite(read_messages=False, send_messages=False),
                role_member: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
                role_admin: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                role_mod: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                role_chanmod: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            }

        # STEP 3 — CATEGORIES & CHANNELS
        await status.edit(content="⚙️ Creating categories and channels...")

        cat_info = await get_or_create_category("📋 INFORMATION", read_only_overwrites())
        await get_or_create_channel("rules", cat_info, read_only_overwrites(), slowmode=0)
        await get_or_create_channel("announcements", cat_info, read_only_overwrites(), slowmode=0)
        await get_or_create_channel("server-updates", cat_info, read_only_overwrites(), slowmode=0)
        await get_or_create_channel("role-info", cat_info, read_only_overwrites(), slowmode=0)

        cat_cc = await get_or_create_category("🎬 CONTENT CREATOR", read_only_overwrites())
        await get_or_create_channel("tiktok-youtube-videos", cat_cc, read_only_overwrites(), slowmode=3)
        await get_or_create_channel("tiktok-youtube-livestreams", cat_cc, read_only_overwrites(), slowmode=3)

        cat_verify = await get_or_create_category("✅ VERIFICATION")
        await get_or_create_channel("how-to-verify", cat_verify, overwrites=howto_overwrites(), slowmode=0, topic="Read this before submitting your proof!")
        await get_or_create_channel("role-verification", cat_verify, overwrites=verification_overwrites(), slowmode=3, topic="📸 Post your MLBB screenshot here. Images only!")

        cat_general = await get_or_create_category("💬 GENERAL", member_overwrites())
        await get_or_create_channel("general", cat_general, member_overwrites(), slowmode=3)
        await get_or_create_channel("off-topic", cat_general, member_overwrites(), slowmode=3)
        await get_or_create_channel("asaiya-bot", cat_general, member_overwrites(), slowmode=3, topic="Use bot commands here!")
        await get_or_create_channel("asaiya-hub", cat_general, member_overwrites(), slowmode=3, topic="🎵 Music commands and hub — use !play here!")

        cat_mlbb = await get_or_create_category("🎮 MLBB", member_overwrites())
        await get_or_create_channel("mlbb-discussion", cat_mlbb, member_overwrites(), slowmode=3)
        await get_or_create_channel("tips-and-guides", cat_mlbb, member_overwrites(), slowmode=3)
        await get_or_create_channel("clips-and-highlights", cat_mlbb, member_overwrites(), slowmode=3)
        await get_or_create_channel("lfg-roam", cat_mlbb, member_overwrites(), slowmode=3)
        await get_or_create_channel("lfg-gold", cat_mlbb, member_overwrites(), slowmode=3)
        await get_or_create_channel("lfg-exp", cat_mlbb, member_overwrites(), slowmode=3)
        await get_or_create_channel("lfg-mid", cat_mlbb, member_overwrites(), slowmode=3)
        await get_or_create_channel("lfg-jungle", cat_mlbb, member_overwrites(), slowmode=3)

        cat_staff = await get_or_create_category("🔒 STAFF ONLY", staff_only_overwrites())
        await get_or_create_channel("staff-chat", cat_staff, staff_only_overwrites(), slowmode=0)
        await get_or_create_channel("mod-actions", cat_staff, staff_only_overwrites(), slowmode=0)
        await get_or_create_channel("verification-logs", cat_staff, staff_only_overwrites(), slowmode=0)
        await get_or_create_channel("bot-logs", cat_staff, staff_only_overwrites(), slowmode=0)

        # STEP 4 — SUMMARY EMBED
        embed = discord.Embed(
            title="✅ MLBB Server Setup Complete",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )

        if created:
            embed.add_field(
                name=f"✅ Created ({len(created)})",
                value="\n".join(created[:20]) + ("\n*...and more*" if len(created) > 20 else ""),
                inline=False
            )
        if skipped:
            embed.add_field(
                name=f"⏭️ Already existed — skipped ({len(skipped)})",
                value="\n".join(skipped[:20]) + ("\n*...and more*" if len(skipped) > 20 else ""),
                inline=False
            )

        embed.set_footer(text=f"Run by {ctx.author} • {ctx.guild.name}")
        await status.delete()
        await ctx.send(embed=embed)


def get_role_name(lane: str, level: int) -> str:
    """Returns display name e.g. 'Guardian V'"""
    title = LANE_DISPLAY.get(lane.lower())
    roman = ROMAN.get(level)
    if not title or not roman:
        return None
    return f"{title} {roman}"


async def setup(bot):
    await bot.add_cog(MLBB(bot))
