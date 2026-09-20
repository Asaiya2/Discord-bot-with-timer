import discord
from discord.ext import commands
import asyncio
import re
import os
from datetime import datetime

# ===== CONFIGURATION =====
BOT_ROLE = "AsaiyaBot"


class CrossServer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ===== HELPERS =====

    def has_bot_role(self, ctx):
        return any(role.name == BOT_ROLE for role in ctx.author.roles) \
               if isinstance(ctx.author, discord.Member) else False

    # ===== COMMANDS =====

    @commands.command(name='botservers')
    @commands.has_permissions(administrator=True)
    async def botservers(self, ctx):
        """List all servers the bot is in with invite links.
        Only works in the owner server.
        Usage: !botservers
        """
        if ctx.guild.id != 1476790704914305134:
            return

        await ctx.defer() if hasattr(ctx, 'defer') else None

        all_guilds = sorted(self.bot.guilds, key=lambda g: g.name.lower())

        if not all_guilds:
            await ctx.send("❌ I'm not in any servers!")
            return

        embeds = []
        current_embed = discord.Embed(
            title=f"🌐 Bot's Servers ({len(all_guilds)} total)",
            description="Here are all the servers I'm currently in:",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )

        field_count = 0
        server_count = 0

        for guild in all_guilds:
            server_count += 1

            # Try to create an invite
            invite_link = "No invite available"
            try:
                for channel in guild.text_channels:
                    if channel.permissions_for(guild.me).create_instant_invite:
                        invite = await channel.create_invite(max_age=86400, max_uses=1,
                                                             reason="Bot servers list command")
                        invite_link = f"[Click to join]({invite.url})"
                        break
            except:
                invite_link = "Cannot create invite"

            server_info = (
                f"**Members:** {guild.member_count}\n"
                f"**ID:** `{guild.id}`\n"
                f"**Invite:** {invite_link}"
            )

            if field_count >= 25:
                embeds.append(current_embed)
                current_embed = discord.Embed(
                    title="🌐 Bot's Servers (Continued)",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                field_count = 0

            current_embed.add_field(
                name=f"{server_count}. {guild.name}",
                value=server_info,
                inline=False
            )
            field_count += 1

        if len(current_embed.fields) > 0:
            embeds.append(current_embed)

        for i, embed in enumerate(embeds):
            embed.set_footer(text=f"Page {i+1}/{len(embeds)} • Requested by {ctx.author}")
            await ctx.send(embed=embed)

        total_members = sum(guild.member_count for guild in all_guilds)
        await ctx.send(f"📊 **Summary:** In **{len(all_guilds)}** servers with **{total_members}** total members.")

    @commands.command(name='talkcross')
    @commands.has_permissions(administrator=True)
    async def talkcross(self, ctx, channel_link: str, *, message: str = None):
        """Send a message to a channel in another server using a Discord channel link.
        Usage: !talkcross https://discord.com/channels/guild_id/channel_id Your message here
        """
        if not self.has_bot_role(ctx):
            return

        # Parse Discord channel link
        pattern = r"(?:https?://)?(?:www\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)"
        match = re.match(pattern, channel_link)

        if not match:
            embed = discord.Embed(
                title="❌ Invalid Channel Link",
                description=(
                    "Please provide a valid Discord channel link.\n"
                    "Example: `https://discord.com/channels/123456789/123456789`"
                ),
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return

        target_guild_id = int(match.group(1))
        target_channel_id = int(match.group(2))

        # If no message provided, ask for it
        if message is None:
            await ctx.send("📝 Please type the message you want to send (or type `cancel`):")

            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel

            try:
                response = await self.bot.wait_for('message', timeout=60.0, check=check)
                if response.content.lower() == 'cancel':
                    await ctx.send("❌ Cross-server message cancelled.")
                    await response.delete()
                    return
                message = response.content
                await response.delete()
            except asyncio.TimeoutError:
                await ctx.send("⏰ Timed out. Cross-server message cancelled.")
                return

        # Get the target guild and channel
        target_guild = self.bot.get_guild(target_guild_id)
        if not target_guild:
            await ctx.send("❌ I'm not in that server!")
            return

        target_channel = target_guild.get_channel(target_channel_id)
        if not target_channel or not isinstance(target_channel, discord.TextChannel):
            await ctx.send("❌ Could not find that text channel in the target server.")
            return

        # Check permissions
        bot_member = target_guild.get_member(self.bot.user.id)
        if not target_channel.permissions_for(bot_member).send_messages:
            await ctx.send(f"❌ I don't have permission to send messages in that channel!")
            return

        # Send the message
        try:
            await target_channel.send(message)

            try:
                await ctx.message.delete()
            except:
                pass

            confirm_embed = discord.Embed(
                title="✅ Message Sent Cross-Server",
                description=f"Message sent to **{target_guild.name}** > #{target_channel.name}",
                color=discord.Color.green()
            )
            confirm_embed.add_field(
                name="Message Preview",
                value=message[:200] + ("..." if len(message) > 200 else ""),
                inline=False
            )
            await ctx.send(embed=confirm_embed)

        except Exception as e:
            await ctx.send(f"❌ Failed to send message: {str(e)}")

    @commands.command(name='talkcrosslist')
    @commands.has_permissions(administrator=True)
    async def talkcrosslist(self, ctx):
        """List all servers the bot is in and send a message to a selected channel"""
        if not self.has_bot_role(ctx):
            return

        all_guilds = list(self.bot.guilds)

        if not all_guilds:
            await ctx.send("❌ I'm not in any servers!")
            return

        await self.show_server_list(ctx, all_guilds, 0)

    async def show_server_list(self, ctx, guilds, page, message=None):
        """Show paginated server list"""
        items_per_page = 5
        start = page * items_per_page
        end = min(start + items_per_page, len(guilds))
        current_page_guilds = guilds[start:end]
        total_pages = (len(guilds) + items_per_page - 1) // items_per_page

        embed = discord.Embed(
            title="🌐 Bot's Servers",
            description=f"Page {page + 1}/{total_pages} • Reply with a number to select a server",
            color=discord.Color.blue()
        )

        for i, guild in enumerate(current_page_guilds, start + 1):
            text_channels = len([ch for ch in guild.text_channels
                                  if ch.permissions_for(guild.me).send_messages])
            embed.add_field(
                name=f"**{i}.** {guild.name}",
                value=f"ID: `{guild.id}`\nMembers: {guild.member_count}\nText Channels: {text_channels}",
                inline=False
            )

        embed.set_footer(text="Reply with a number to select, or use buttons to navigate")

        class PaginationView(discord.ui.View):
            def __init__(self_view):
                super().__init__(timeout=60)

            @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.blurple,
                               disabled=(page == 0))
            async def previous_button(self_view, interaction: discord.Interaction,
                                      button: discord.ui.Button):
                if interaction.user != ctx.author:
                    await interaction.response.send_message("❌ Only the command user can use this.",
                                                            ephemeral=True)
                    return
                await interaction.response.defer()
                await self.show_server_list(ctx, guilds, page - 1, message)
                self_view.stop()

            @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.blurple,
                               disabled=(end >= len(guilds)))
            async def next_button(self_view, interaction: discord.Interaction,
                                  button: discord.ui.Button):
                if interaction.user != ctx.author:
                    await interaction.response.send_message("❌ Only the command user can use this.",
                                                            ephemeral=True)
                    return
                await interaction.response.defer()
                await self.show_server_list(ctx, guilds, page + 1, message)
                self_view.stop()

            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
            async def cancel_button(self_view, interaction: discord.Interaction,
                                    button: discord.ui.Button):
                if interaction.user != ctx.author:
                    await interaction.response.send_message("❌ Only the command user can use this.",
                                                            ephemeral=True)
                    return
                await interaction.response.edit_message(content="❌ Cancelled.", embed=None, view=None)
                self_view.stop()

        view = PaginationView()

        if message:
            await message.edit(embed=embed, view=view)
        else:
            message = await ctx.send(embed=embed, view=view)

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            response = await self.bot.wait_for('message', timeout=30.0, check=check)
            await message.edit(view=None)

            try:
                choice = int(response.content)
                if 1 <= choice <= len(guilds):
                    selected_guild = guilds[choice - 1]
                    await response.delete()
                    await self.show_channel_list(ctx, selected_guild, 0, choice)
                else:
                    await ctx.send(f"❌ Please enter a number between 1 and {len(guilds)}")
            except ValueError:
                await ctx.send("❌ Invalid input. Please enter a number.")

        except asyncio.TimeoutError:
            await message.edit(view=None)
            await ctx.send("⏰ Selection timed out.")

    async def show_channel_list(self, ctx, guild, page, server_number, message=None):
        """Show paginated channel list for a specific server"""
        all_channels = [
            ch for ch in guild.text_channels
            if ch.permissions_for(guild.me).send_messages
        ]

        if not all_channels:
            await ctx.send(f"❌ No accessible text channels in **{guild.name}**")
            return

        items_per_page = 10
        start = page * items_per_page
        end = min(start + items_per_page, len(all_channels))
        current_page_channels = all_channels[start:end]
        total_pages = (len(all_channels) + items_per_page - 1) // items_per_page

        embed = discord.Embed(
            title=f"🌐 Channels in {guild.name}",
            description=f"Page {page + 1}/{total_pages} • Reply with a number to select a channel",
            color=discord.Color.green()
        )

        channel_list = ""
        for i, channel in enumerate(current_page_channels, start + 1):
            channel_list += f"**{i}.** #{channel.name}\n"

        embed.add_field(name="Available Channels", value=channel_list or "No channels", inline=False)
        embed.set_footer(text="Reply with a number, or type 'back' to go back")

        class ChannelPaginationView(discord.ui.View):
            def __init__(self_view):
                super().__init__(timeout=60)

            @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.blurple,
                               disabled=(page == 0))
            async def previous_button(self_view, interaction: discord.Interaction,
                                      button: discord.ui.Button):
                if interaction.user != ctx.author:
                    await interaction.response.send_message("❌ Only the command user can use this.",
                                                            ephemeral=True)
                    return
                await interaction.response.defer()
                await self.show_channel_list(ctx, guild, page - 1, server_number, message)
                self_view.stop()

            @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.blurple,
                               disabled=(end >= len(all_channels)))
            async def next_button(self_view, interaction: discord.Interaction,
                                  button: discord.ui.Button):
                if interaction.user != ctx.author:
                    await interaction.response.send_message("❌ Only the command user can use this.",
                                                            ephemeral=True)
                    return
                await interaction.response.defer()
                await self.show_channel_list(ctx, guild, page + 1, server_number, message)
                self_view.stop()

            @discord.ui.button(label="◀ Back to Servers", style=discord.ButtonStyle.grey)
            async def back_button(self_view, interaction: discord.Interaction,
                                  button: discord.ui.Button):
                if interaction.user != ctx.author:
                    await interaction.response.send_message("❌ Only the command user can use this.",
                                                            ephemeral=True)
                    return
                await interaction.response.defer()
                all_guilds = list(self.bot.guilds)
                await self.show_server_list(ctx, all_guilds, 0)
                self_view.stop()

        view = ChannelPaginationView()

        if message:
            await message.edit(embed=embed, view=view)
        else:
            message = await ctx.send(embed=embed, view=view)

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            response = await self.bot.wait_for('message', timeout=30.0, check=check)
            await message.edit(view=None)

            if response.content.lower() == 'back':
                await response.delete()
                all_guilds = list(self.bot.guilds)
                await self.show_server_list(ctx, all_guilds, 0)
                return

            try:
                choice = int(response.content)
                if 1 <= choice <= len(all_channels):
                    selected_channel = all_channels[choice - 1]
                    await response.delete()

                    await ctx.send(f"📝 Selected: #{selected_channel.name}\nType your message (or `cancel`):")

                    def msg_check(m):
                        return m.author == ctx.author and m.channel == ctx.channel

                    try:
                        msg_response = await self.bot.wait_for('message', timeout=60.0, check=msg_check)

                        if msg_response.content.lower() == 'cancel':
                            await ctx.send("❌ Cancelled.")
                            await msg_response.delete()
                            return

                        message_text = msg_response.content
                        await msg_response.delete()

                        await selected_channel.send(message_text)
                        await ctx.send(f"✅ Message sent to **#{selected_channel.name}** in **{guild.name}**!")

                    except asyncio.TimeoutError:
                        await ctx.send("⏰ Timed out. Cancelled.")
                else:
                    await ctx.send(f"❌ Please enter a number between 1 and {len(all_channels)}")

            except ValueError:
                await ctx.send("❌ Invalid input. Please enter a number or 'back'")

        except asyncio.TimeoutError:
            await message.edit(view=None)
            await ctx.send("⏰ Selection timed out.")

    @commands.command(name='talkdm')
    @commands.has_permissions(administrator=True)
    async def talkdm(self, ctx, user_id: int = None, *, message: str = None):
        """Send a DM to a user by ID.
        Usage: !talkdm 123456789 Hello there!
        """
        if not self.has_bot_role(ctx):
            return

        if user_id is None:
            await ctx.send("❌ Please provide a user ID: `!talkdm 123456789 Hello there!`")
            return

        if message is None:
            await ctx.send("📝 Please type the message you want to DM (or type `cancel`):")

            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel

            try:
                response = await self.bot.wait_for('message', timeout=60.0, check=check)
                if response.content.lower() == 'cancel':
                    await ctx.send("❌ DM cancelled.")
                    await response.delete()
                    return
                message = response.content
                await response.delete()
            except asyncio.TimeoutError:
                await ctx.send("⏰ Timed out. DM cancelled.")
                return

        try:
            user = await self.bot.fetch_user(user_id)
        except discord.NotFound:
            await ctx.send(f"❌ User with ID {user_id} not found.")
            return
        except Exception as e:
            await ctx.send(f"❌ Error fetching user: {str(e)}")
            return

        try:
            embed = discord.Embed(
                title=f"📨 Message from {ctx.author.name}",
                description=message,
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text=f"Sent from {ctx.guild.name}")

            await user.send(embed=embed)

            try:
                await ctx.message.delete()
            except:
                pass

            await ctx.send(f"✅ DM sent to **{user.name}**!")

        except discord.Forbidden:
            await ctx.send("❌ Cannot DM that user. They may have DMs disabled.")
        except Exception as e:
            await ctx.send(f"❌ Failed to send DM: {str(e)}")


async def setup(bot):
    await bot.add_cog(CrossServer(bot))
