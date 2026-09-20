import discord
from discord.ext import commands
import asyncio
import random
import time
import re
import os
from datetime import datetime

# ===== CONFIGURATION =====
BOT_ROLE = "AsaiyaBot"
KICK_ROLE = "AsaiyaKick"
BAN_ROLE = "AsaiyaBan"


def parse_time_input(time_str):
    """Parse time formats like 5m, 10 minutes, 1 hour, 2 days"""
    time_str = time_str.lower().strip()

    multipliers = {
        's': 1, 'sec': 1, 'secs': 1, 'second': 1, 'seconds': 1,
        'm': 60, 'min': 60, 'mins': 60, 'minute': 60, 'minutes': 60,
        'h': 3600, 'hr': 3600, 'hrs': 3600, 'hour': 3600, 'hours': 3600,
        'd': 86400, 'day': 86400, 'days': 86400
    }

    match = re.match(r'^(\d+)\s*([a-zA-Z]+)$', time_str)
    if not match:
        return None

    value, unit = match.groups()
    for key, multiplier in multipliers.items():
        if unit.startswith(key):
            return int(value) * multiplier

    return None


class Giveaway(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ===== HELPERS =====

    def has_staff_role(self, ctx):
        """Check if user has a staff role"""
        if not isinstance(ctx.author, discord.Member):
            return False
        return any(role.name in [BOT_ROLE, KICK_ROLE, BAN_ROLE] for role in ctx.author.roles)

    async def create_giveaway(self, ctx, item, amount, end_time):
        """Create a giveaway embed and store it"""

        class GiveawayView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=None)
                self.entries = set()

            @discord.ui.button(label="🎉 Enter Giveaway", style=discord.ButtonStyle.blurple,
                               custom_id=f"enter_giveaway")
            async def enter_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id in self.entries:
                    await interaction.response.send_message("❌ You're already entered!", ephemeral=True)
                    return
                self.entries.add(interaction.user.id)
                await interaction.response.send_message("✅ You've entered the giveaway!", ephemeral=True)

        embed = discord.Embed(
            title="🎉 GIVEAWAY",
            description=f"**Prize:** {item}",
            color=discord.Color.gold()
        )
        embed.add_field(name="Amount", value=amount, inline=True)
        embed.add_field(name="Hosted by", value=ctx.author.mention, inline=True)
        embed.add_field(name="Ends", value=f"<t:{int(end_time)}:R>", inline=False)
        embed.set_footer(text="Click the button to enter!")

        view = GiveawayView()
        giveaway_msg = await ctx.send(embed=embed, view=view)

        # Store giveaway data
        self.bot.active_giveaways[giveaway_msg.id] = {
            'channel_id': ctx.channel.id,
            'message_id': giveaway_msg.id,
            'host_id': ctx.author.id,
            'item': item,
            'amount': amount,
            'end_time': end_time,
            'entries': view.entries,
            'prize': f"{item} ({amount})"
        }

        await ctx.send(f"✅ Giveaway started! It will end <t:{int(end_time)}:R>")

    # ===== COMMANDS =====

    @commands.group(name='ga', invoke_without_command=True)
    async def ga(self, ctx, item: str = None, amount: str = None, duration: str = None):
        """Start a quick giveaway or view giveaway commands.
        Usage: !ga [item] [amount] [time]
        Example: !ga Icecream 3x 5m
        """
        if not self.has_staff_role(ctx):
            await ctx.send("❌ Only staff members can use this command!")
            return

        # If no arguments, show help
        if not item:
            embed = discord.Embed(
                title="🎉 Giveaway Commands",
                color=discord.Color.gold()
            )
            embed.add_field(
                name="Quick Start",
                value="`!ga [item] [amount] [time]`\nExample: `!ga Icecream 3x 5m`",
                inline=False
            )
            embed.add_field(
                name="Other Commands",
                value=(
                    "`!ga start` - Interactive setup\n"
                    "`!ga end [msg_id]` - End a giveaway early\n"
                    "`!ga re [msg_id]` - Reroll a winner\n"
                    "`!ga list` - List active giveaways"
                ),
                inline=False
            )
            await ctx.send(embed=embed)
            return

        # One-line giveaway
        if not amount:
            amount = "1x"

        if not duration:
            await ctx.send("❌ Please specify a duration! Example: `!ga Icecream 3x 5m`")
            return

        seconds = parse_time_input(duration)
        if seconds is None:
            await ctx.send("❌ Invalid time format. Examples: `5m`, `1h`, `2d`")
            return

        end_time = time.time() + seconds
        await self.create_giveaway(ctx, item, amount, end_time)

    @ga.command(name='start')
    async def ga_start(self, ctx):
        """Start a giveaway interactively"""
        if not self.has_staff_role(ctx):
            await ctx.send("❌ Only staff members can use this command!")
            return

        status_msg = await ctx.send("📝 **Giveaway Setup**\nPlease enter the **item name**:")

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            # Get item name
            msg1 = await self.bot.wait_for('message', timeout=60.0, check=check)
            item = msg1.content
            await msg1.delete()

            await status_msg.edit(
                content=f"📝 **Giveaway Setup**\n✅ Item: **{item}**\n\nNow enter the **amount** (e.g., 1x, 2x, 5x):"
            )

            # Get amount
            msg2 = await self.bot.wait_for('message', timeout=60.0, check=check)
            amount = msg2.content.strip() or "1x"
            await msg2.delete()

            await status_msg.edit(
                content=(
                    f"📝 **Giveaway Setup**\n"
                    f"✅ Item: **{item}**\n"
                    f"✅ Amount: **{amount}**\n\n"
                    f"Finally, enter the **duration** (e.g., 5m, 1h, 2d):"
                )
            )

            # Get duration
            msg3 = await self.bot.wait_for('message', timeout=60.0, check=check)
            time_input = msg3.content
            await msg3.delete()

            seconds = parse_time_input(time_input)
            if seconds is None:
                await status_msg.edit(
                    content="❌ **Invalid time format!**\nExamples: `5m`, `1h`, `2d`\n\nPlease try `!ga start` again."
                )
                return

            end_time = time.time() + seconds
            await status_msg.delete()
            await self.create_giveaway(ctx, item, amount, end_time)

        except asyncio.TimeoutError:
            await status_msg.edit(content="⏰ **Timed out.** Giveaway setup cancelled.")

    @ga.command(name='end')
    async def ga_end(self, ctx, message_id: str = None):
        """End a giveaway early. Usage: !ga end [message_id]"""
        if not self.has_staff_role(ctx):
            await ctx.send("❌ Only staff members can use this command!")
            return

        if not message_id:
            await ctx.send("❌ Please provide a message ID! Usage: `!ga end 123456789`")
            return

        try:
            msg_id = int(message_id)
        except ValueError:
            await ctx.send("❌ Invalid message ID!")
            return

        if msg_id not in self.bot.active_giveaways:
            await ctx.send("❌ Giveaway not found or already ended!")
            return

        giveaway_data = self.bot.active_giveaways.pop(msg_id)

        # Use the finish_giveaway method from tasks cog
        tasks_cog = self.bot.cogs.get('Tasks')
        if tasks_cog:
            await tasks_cog.finish_giveaway(msg_id, giveaway_data)

        await ctx.send("✅ Giveaway ended early!")

    @ga.command(name='re')
    async def ga_reroll(self, ctx, message_id: str = None):
        """Reroll a winner for a completed giveaway. Usage: !ga re [message_id]"""
        if not self.has_staff_role(ctx):
            await ctx.send("❌ Only staff members can use this command!")
            return

        if not message_id:
            await ctx.send("❌ Please provide a message ID! Usage: `!ga re 123456789`")
            return

        try:
            msg_id = int(message_id)
        except ValueError:
            await ctx.send("❌ Invalid message ID!")
            return

        # ── Check saved entries from ended giveaways ──────────────────────
        if not hasattr(self.bot, 'ended_giveaways'):
            self.bot.ended_giveaways = {}

        saved = self.bot.ended_giveaways.get(msg_id)

        if saved and saved['entries']:
            entries = list(saved['entries'])
            winner_count = saved.get('winner_count', 1)
            winner_count = min(winner_count, len(entries))
            winners = random.sample(entries, winner_count)
            winner_mentions = [f"<@{w}>" for w in winners]

            await ctx.send(
                f"🎉 New winner(s): {', '.join(winner_mentions)}\n"
                f"Prize: **{saved.get('prize', 'Unknown')}** · "
                f"{len(entries)} total entr{'y' if len(entries) == 1 else 'ies'}"
            )
            return

        # ── Fallback: entries not saved ────────────────────────────────────
        try:
            msg = await ctx.channel.fetch_message(msg_id)
        except:
            await ctx.send("❌ Could not find that message in this channel!")
            return

        if not msg.embeds:
            await ctx.send("❌ That message is not a giveaway!")
            return

        await ctx.send(
            "⚠️ Entry data for this giveaway was not saved "
            "(it may have ended before this fix was applied).\n"
            "Reroll is not possible without the original entry list."
        )

    @ga.command(name='list')
    async def ga_list(self, ctx):
        """List all active giveaways in this server"""
        # Find giveaways in this server's channels
        guild_channel_ids = [ch.id for ch in ctx.guild.text_channels]
        guild_giveaways = [
            data for data in self.bot.active_giveaways.values()
            if data['channel_id'] in guild_channel_ids
        ]

        if not guild_giveaways:
            await ctx.send("📭 No active giveaways in this server.")
            return

        embed = discord.Embed(
            title="🎉 Active Giveaways",
            description=f"Found **{len(guild_giveaways)}** active giveaway(s)",
            color=discord.Color.gold()
        )

        for giveaway in guild_giveaways:
            channel = self.bot.get_channel(giveaway['channel_id'])
            channel_name = channel.mention if channel else "Unknown"
            time_left = int(giveaway['end_time'] - time.time())

            if time_left > 0:
                embed.add_field(
                    name=f"**{giveaway['prize']}**",
                    value=(
                        f"Channel: {channel_name}\n"
                        f"Entries: {len(giveaway['entries'])}\n"
                        f"Ends: <t:{int(giveaway['end_time'])}:R>\n"
                        f"Message ID: `{giveaway['message_id']}`"
                    ),
                    inline=False
                )

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Giveaway(bot))
