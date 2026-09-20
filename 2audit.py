# cogs/audit.py
import discord
from discord.ext import commands
import time
import asyncio
import traceback
from datetime import datetime
import sqlite3
import os

# ===== CONFIGURATION =====
AUDIT_SERVER_ID = 1484265140215087235
AUDIT_CHANNEL_ID = 1488617564987981865

DB_FOLDER = r"C:\Users\Kelly\Desktop\discord database"
MAIN_DB_PATH = os.path.join(DB_FOLDER, "asaiya_bot.db")


class Audit(commands.Cog):
    """Comprehensive audit logging for all commands"""
    
    def __init__(self, bot):
        self.bot = bot
        self.audit_channel = None
        self.processed_commands = {}  # Prevent duplicate audit entries
        self.setup_database()
        print("✅ Audit cog initialized")
    
    def setup_database(self):
        """Create audit log table for permanent storage"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            
            c.execute('''
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    command TEXT,
                    user_id TEXT,
                    user_name TEXT,
                    user_mention TEXT,
                    guild_id TEXT,
                    guild_name TEXT,
                    channel_id TEXT,
                    channel_name TEXT,
                    user_permissions TEXT,
                    user_roles TEXT,
                    arguments TEXT,
                    success BOOLEAN,
                    error TEXT,
                    duration REAL,
                    ip_address TEXT,
                    message_id TEXT,
                    jump_url TEXT
                )
            ''')
            
            conn.commit()
            conn.close()
            print("✅ Audit database initialized")
        except Exception as e:
            print(f"❌ Error setting up audit database: {e}")
    
    async def get_audit_channel(self):
        """Get the audit channel (cached)"""
        if self.audit_channel:
            return self.audit_channel
        
        guild = self.bot.get_guild(AUDIT_SERVER_ID)
        if not guild:
            print(f"⚠️ Audit server {AUDIT_SERVER_ID} not found")
            return None
        
        self.audit_channel = guild.get_channel(AUDIT_CHANNEL_ID)
        if not self.audit_channel:
            print(f"⚠️ Audit channel {AUDIT_CHANNEL_ID} not found")
        
        return self.audit_channel
    
    def get_user_permissions(self, ctx):
        """Get detailed user permissions as a string"""
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return "DM (No server permissions)"
        
        perms = []
        
        # Admin/Mod permissions
        if ctx.author.guild_permissions.administrator:
            perms.append("ADMINISTRATOR")
        if ctx.author.guild_permissions.ban_members:
            perms.append("BAN_MEMBERS")
        if ctx.author.guild_permissions.kick_members:
            perms.append("KICK_MEMBERS")
        if ctx.author.guild_permissions.manage_guild:
            perms.append("MANAGE_GUILD")
        if ctx.author.guild_permissions.manage_channels:
            perms.append("MANAGE_CHANNELS")
        if ctx.author.guild_permissions.manage_roles:
            perms.append("MANAGE_ROLES")
        if ctx.author.guild_permissions.manage_messages:
            perms.append("MANAGE_MESSAGES")
        if ctx.author.guild_permissions.moderate_members:
            perms.append("MODERATE_MEMBERS")
        
        # Check for bot-specific roles
        bot_role = discord.utils.get(ctx.author.roles, name="AsaiyaBot")
        if bot_role:
            perms.append("ASAIYA_BOT_ROLE")
        
        kick_role = discord.utils.get(ctx.author.roles, name="AsaiyaKick")
        if kick_role:
            perms.append("ASAIYA_KICK_ROLE")
        
        ban_role = discord.utils.get(ctx.author.roles, name="AsaiyaBan")
        if ban_role:
            perms.append("ASAIYA_BAN_ROLE")
        
        support_role = discord.utils.get(ctx.author.roles, name="asaiya-support")
        if support_role:
            perms.append("SUPPORT_ROLE")
        
        if not perms:
            perms.append("MEMBER")
        
        return ", ".join(perms)
    
    def get_user_roles(self, ctx):
        """Get user's role names as a string"""
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return "DM (No roles)"
        
        roles = [role.name for role in ctx.author.roles if role.name != "@everyone"]
        if not roles:
            return "No roles"
        
        return ", ".join(roles[:10])  # Limit to 10 roles
    
    def get_command_args(self, ctx):
        """Get command arguments as string"""
        if not ctx.args:
            return "None"
        
        # Filter out ctx and self
        args = []
        for arg in ctx.args[2:]:  # Skip [ctx, self/cog]
            if isinstance(arg, (discord.Member, discord.User)):
                args.append(f"@{arg.name} ({arg.id})")
            elif isinstance(arg, discord.Role):
                args.append(f"@{arg.name} ({arg.id})")
            elif isinstance(arg, discord.TextChannel):
                args.append(f"#{arg.name} ({arg.id})")
            else:
                args.append(str(arg))
        
        # Add kwargs
        if ctx.kwargs:
            for k, v in ctx.kwargs.items():
                if isinstance(v, (discord.Member, discord.User)):
                    args.append(f"{k}=@{v.name}")
                else:
                    args.append(f"{k}={v}")
        
        return " ".join(args) if args else "None"
    
    def calculate_command_risk(self, ctx):
        """Calculate risk level of command based on permissions and command name"""
        high_risk_commands = [
            'nuke', 'kick', 'ban', 'clear', 'slock', 'sunlock', 'sprotect',
            'fprotect', 'remake', 'resetdays', 'fullcmdtest', 'delbackup',
            'cdelkey', 'skey', 'idsetglobal'
        ]
        
        medium_risk_commands = [
            'warn', 'timeout', 'lock', 'unlock', 'protect', 'mprotect',
            'addlevel', 'addre', 'addxp', 'setlevel', 'noexp'
        ]
        
        cmd = ctx.command.name if ctx.command else "unknown"
        
        if cmd in high_risk_commands:
            return "🔴 HIGH"
        elif cmd in medium_risk_commands:
            return "🟡 MEDIUM"
        elif "admin" in cmd.lower() or "mod" in cmd.lower():
            return "🟡 MEDIUM"
        else:
            return "🟢 LOW"
    
    @commands.Cog.listener()
    async def on_command(self, ctx):
        """Listener that fires BEFORE command execution"""
        # Store command start time
        ctx.audit_start_time = time.time()
        
        # Create a unique ID to track this command execution
        ctx.audit_id = f"{ctx.message.id}_{ctx.author.id}_{int(time.time())}"
    
    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        """Listener that fires AFTER successful command execution"""
        await self.log_command(ctx, success=True, error=None)
    
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """Listener that fires when command fails"""
        # Ignore CommandNotFound errors (too noisy)
        if isinstance(error, commands.CommandNotFound):
            return
        
        # Don't log duplicate errors
        if hasattr(ctx, 'audit_logged') and ctx.audit_logged:
            return
        
        error_str = str(error)
        
        # Clean up error message
        if isinstance(error, commands.MissingPermissions):
            error_str = f"Missing Permissions: {', '.join(error.missing_permissions)}"
        elif isinstance(error, commands.BadArgument):
            error_str = f"Bad Argument: {error}"
        elif isinstance(error, commands.MissingRequiredArgument):
            error_str = f"Missing Required Argument: {error.param.name}"
        elif isinstance(error, commands.CommandOnCooldown):
            error_str = f"On Cooldown: {round(error.retry_after, 1)}s remaining"
        elif isinstance(error, commands.CheckFailure):
            error_str = "Check Failure (permissions/channel restriction)"
        
        await self.log_command(ctx, success=False, error=error_str)
    
    async def log_command(self, ctx, success: bool, error: str = None):
        """Log command execution to database and Discord channel"""
        
        # Prevent duplicate logging
        if hasattr(ctx, 'audit_logged') and ctx.audit_logged:
            return
        
        ctx.audit_logged = True
        
        # Calculate duration
        duration = 0
        if hasattr(ctx, 'audit_start_time'):
            duration = time.time() - ctx.audit_start_time
        
        # Get command info
        command_name = ctx.command.name if ctx.command else "unknown"
        command_qualified = ctx.command.qualified_name if ctx.command else "unknown"
        
        # Get user info
        user = ctx.author
        user_id = user.id
        user_name = f"{user.name}#{user.discriminator}" if user.discriminator != "0" else user.name
        user_mention = user.mention
        
        # Get guild info
        guild_id = ctx.guild.id if ctx.guild else None
        guild_name = ctx.guild.name if ctx.guild else "DM"
        
        # Get channel info
        channel_id = ctx.channel.id
        channel_name = f"#{ctx.channel.name}" if isinstance(ctx.channel, discord.TextChannel) else "DM"
        
        # Get permissions
        user_permissions = self.get_user_permissions(ctx)
        user_roles = self.get_user_roles(ctx)
        
        # Get arguments
        args = self.get_command_args(ctx)
        
        # Get jump URL (only works for guild messages)
        jump_url = f"https://discord.com/channels/{guild_id}/{channel_id}/{ctx.message.id}" if ctx.guild else None
        
        # Calculate risk
        risk = self.calculate_command_risk(ctx)
        
        # Save to database
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''
                INSERT INTO audit_logs (
                    timestamp, command, user_id, user_name, user_mention,
                    guild_id, guild_name, channel_id, channel_name,
                    user_permissions, user_roles, arguments,
                    success, error, duration, message_id, jump_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                time.time(), command_qualified, str(user_id), user_name, user_mention,
                str(guild_id) if guild_id else None, guild_name, str(channel_id), channel_name,
                user_permissions, user_roles, args,
                1 if success else 0, error, duration,
                str(ctx.message.id), jump_url
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"❌ Error saving audit log to database: {e}")
        
        # Send to Discord audit channel
        await self.send_audit_message(ctx, command_name, command_qualified, success, error, duration, user_permissions, user_roles, args, risk)
    
    async def send_audit_message(self, ctx, command_name, command_qualified, success, error, duration, user_permissions, user_roles, args, risk):
        """Send formatted audit message to the audit channel"""
        
        audit_channel = await self.get_audit_channel()
        if not audit_channel:
            return
        
        # Determine embed color
        if success:
            color = discord.Color.green()
            status = "✅ SUCCESS"
        else:
            color = discord.Color.red()
            status = "❌ FAILED"
        
        # Special colors for high risk commands
        if risk == "🔴 HIGH":
            color = discord.Color.dark_red()
        elif risk == "🟡 MEDIUM":
            color = discord.Color.orange()
        
        # Create embed
        embed = discord.Embed(
            title=f"📋 Command Audit: `{command_qualified}`",
            color=color,
            timestamp=datetime.utcnow()
        )
        
        # User Information
        user_info = f"**User:** {ctx.author.mention}\n"
        user_info += f"**ID:** `{ctx.author.id}`\n"
        user_info += f"**Name:** `{ctx.author}`"
        embed.add_field(name="👤 User", value=user_info, inline=True)
        
        # Command Information
        cmd_info = f"**Command:** `{command_qualified}`\n"
        cmd_info += f"**Status:** {status}\n"
        cmd_info += f"**Risk:** {risk}\n"
        cmd_info += f"**Duration:** `{duration:.3f}s`"
        embed.add_field(name="⚙️ Command", value=cmd_info, inline=True)
        
        # Location Information
        if ctx.guild:
            location = f"**Server:** {ctx.guild.name}\n"
            location += f"**Server ID:** `{ctx.guild.id}`\n"
            location += f"**Channel:** {ctx.channel.mention}\n"
            location += f"**Channel ID:** `{ctx.channel.id}`"
        else:
            location = f"**Location:** DM\n"
            location += f"**Channel ID:** `{ctx.channel.id}`"
        embed.add_field(name="📍 Location", value=location, inline=True)
        
        # Permissions & Roles
        embed.add_field(name="🔑 Permissions", value=f"```{user_permissions}```", inline=False)
        embed.add_field(name="🎭 Roles", value=f"```{user_roles[:500]}```", inline=False)
        
        # Arguments
        if args and args != "None":
            embed.add_field(name="📝 Arguments", value=f"```{args[:500]}```", inline=False)
        
        # Error (if failed)
        if error:
            embed.add_field(name="⚠️ Error", value=f"```{error[:500]}```", inline=False)
        
        # Jump URL
        if ctx.guild:
            embed.add_field(name="🔗 Message Link", value=f"[Click to view]({ctx.message.jump_url})", inline=False)
        
        # Footer with additional info
        footer_info = f"Message ID: {ctx.message.id}"
        if ctx.guild:
            footer_info += f" | Channel: #{ctx.channel.name}"
        embed.set_footer(text=footer_info)
        
        # Send to audit channel
        try:
            await audit_channel.send(embed=embed)
        except Exception as e:
            print(f"❌ Failed to send audit message: {e}")
    
    @commands.command(name='audit')
    @commands.is_owner()
    async def audit_command(self, ctx, limit: int = 10):
        """View recent audit logs (owner only)"""
        
        if ctx.author.id not in [1299719492598763636, 1476790704914305134]:
            await ctx.send("❌ Only the bot owner can use this command.")
            return
        
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''
                SELECT timestamp, command, user_name, guild_name, success, error, duration
                FROM audit_logs
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (limit,))
            results = c.fetchall()
            conn.close()
            
            if not results:
                await ctx.send("📭 No audit logs found.")
                return
            
            embed = discord.Embed(
                title="📋 Recent Audit Logs",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            for ts, cmd, user, guild, success, error, duration in results:
                time_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                status = "✅" if success else "❌"
                error_snip = f" - {error[:30]}..." if error and not success else ""
                
                embed.add_field(
                    name=f"{status} {cmd}",
                    value=f"`{time_str}` | {user} | {guild or 'DM'}{error_snip}\n*duration: {duration:.2f}s*",
                    inline=False
                )
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")
    
    @commands.command(name='auditstats')
    @commands.is_owner()
    async def audit_stats(self, ctx):
        """Show audit statistics (owner only)"""
        
        if ctx.author.id not in [1299719492598763636, 1476790704914305134]:
            await ctx.send("❌ Only the bot owner can use this command.")
            return
        
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            
            # Total commands
            c.execute("SELECT COUNT(*) FROM audit_logs")
            total = c.fetchone()[0]
            
            # Success/failure counts
            c.execute("SELECT COUNT(*) FROM audit_logs WHERE success = 1")
            success = c.fetchone()[0]
            
            c.execute("SELECT COUNT(*) FROM audit_logs WHERE success = 0")
            failure = c.fetchone()[0]
            
            # Top commands
            c.execute('''
                SELECT command, COUNT(*) as count
                FROM audit_logs
                GROUP BY command
                ORDER BY count DESC
                LIMIT 5
            ''')
            top_commands = c.fetchall()
            
            # Top users
            c.execute('''
                SELECT user_name, COUNT(*) as count
                FROM audit_logs
                GROUP BY user_name
                ORDER BY count DESC
                LIMIT 5
            ''')
            top_users = c.fetchall()
            
            # Top servers
            c.execute('''
                SELECT guild_name, COUNT(*) as count
                FROM audit_logs
                WHERE guild_name IS NOT NULL
                GROUP BY guild_name
                ORDER BY count DESC
                LIMIT 5
            ''')
            top_servers = c.fetchall()
            
            # Average duration
            c.execute("SELECT AVG(duration) FROM audit_logs WHERE duration > 0")
            avg_duration = c.fetchone()[0] or 0
            
            conn.close()
            
            embed = discord.Embed(
                title="📊 Audit Statistics",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(name="Total Commands", value=str(total), inline=True)
            embed.add_field(name="Success Rate", value=f"{success}/{total} ({success/total*100:.1f}%)", inline=True)
            embed.add_field(name="Avg Duration", value=f"{avg_duration:.2f}s", inline=True)
            
            if top_commands:
                cmd_list = "\n".join([f"• `{cmd}`: {count}" for cmd, count in top_commands])
                embed.add_field(name="Top Commands", value=cmd_list, inline=False)
            
            if top_users:
                user_list = "\n".join([f"• {name}: {count}" for name, count in top_users])
                embed.add_field(name="Top Users", value=user_list, inline=False)
            
            if top_servers:
                server_list = "\n".join([f"• {name or 'Unknown'}: {count}" for name, count in top_servers])
                embed.add_field(name="Top Servers", value=server_list, inline=False)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")


async def setup(bot):
    await bot.add_cog(Audit(bot))
