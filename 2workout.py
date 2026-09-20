import discord
from discord.ext import commands
import sqlite3
import time
import asyncio
import os
from datetime import datetime
from typing import Optional

# ===== CONFIGURATION =====
DB_FOLDER = r"C:\Users\Kelly\Desktop\discord database"
MAIN_DB_PATH = os.path.join(DB_FOLDER, "asaiya_bot.db")

# Only allowed server ID
ALLOWED_SERVER_ID = 1484565350879330416

# Timer states for treadmill tracking
treadmill_sessions = {}  # {user_id: {"active": bool, "start_time": float, "speed": float, "button_msg_id": int, "timer_msg_id": int, "channel_id": int}}


class TreadmillControlView(discord.ui.View):
    """View for treadmill control buttons (static message)"""
    def __init__(self, user_id, speed, cog, timer_message):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.speed = speed
        self.cog = cog
        self.timer_message = timer_message
        self.start_time = None
        self.active = True
        self.update_task = None

    @discord.ui.button(label="▶ Start", style=discord.ButtonStyle.green, custom_id="treadmill_start")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This timer is not for you!", ephemeral=True)
            return

        if self.start_time is not None:
            await interaction.response.send_message("⏱️ Timer already started!", ephemeral=True)
            return

        self.start_time = time.time()
        self.active = True

        # Remove start button, add stop button
        self.clear_items()
        self.add_item(self.stop_button)
        
        await interaction.response.edit_message(view=self)
        
        # Start updating timer
        self.update_task = asyncio.create_task(self.update_timer())

    @discord.ui.button(label="⏹ Stop", style=discord.ButtonStyle.red, custom_id="treadmill_stop")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This timer is not for you!", ephemeral=True)
            return

        if not self.active or self.start_time is None:
            await interaction.response.send_message("⏱️ Timer not active!", ephemeral=True)
            return

        # Mark as inactive immediately to prevent double-stop
        self.active = False
        
        # Cancel update task
        if self.update_task:
            self.update_task.cancel()

        duration_seconds = int(time.time() - self.start_time)
        minutes = duration_seconds // 60
        seconds = duration_seconds % 60

        # Save to database
        await self.cog.save_cardio_session(interaction.user.id, duration_seconds, self.speed)

        # Update timer message one last time
        embed = discord.Embed(
            title="✅ Treadmill Session Complete",
            description=f"Speed: {self.speed} mph\nDuration: **{minutes}:{seconds:02d}**\n\nTotal: {duration_seconds} seconds",
            color=discord.Color.green()
        )
        await self.timer_message.edit(embed=embed)
        
        # Update button message
        await interaction.response.edit_message(
            content=f"✅ Session complete! {minutes}:{seconds:02d} at {self.speed} mph",
            embed=None,
            view=None
        )
        
        # Clean up session tracking
        if interaction.user.id in treadmill_sessions:
            del treadmill_sessions[interaction.user.id]

    async def update_timer(self):
        """Update timer display every second"""
        while self.active and self.start_time is not None:
            await asyncio.sleep(1)
            if not self.active:
                break
            
            elapsed = int(time.time() - self.start_time)
            minutes = elapsed // 60
            seconds = elapsed % 60
            
            embed = discord.Embed(
                title="🏃 Treadmill Session",
                description=f"Speed: {self.speed} mph\nTime: **{minutes}:{seconds:02d}**\n\nElapsed: {elapsed} seconds",
                color=discord.Color.green()
            )
            try:
                await self.timer_message.edit(embed=embed)
            except:
                break


class Workout(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Track processed commands to prevent duplicates
        self.processed_commands = {}
        # Track pending interactive sessions
        self.pending_addfood = {}  # {user_id: {"step": int, "data": dict}}
        self.pending_logfood = {}  # {user_id: {"step": int, "data": dict}}
        self.pending_logworkout = {}  # {user_id: {"step": int, "data": dict}}
        
        # Setup database
        self.setup_database()
        
        print(f"✅ Workout cog initialized (ID: {id(self)})")

    # ===== DUPLICATE PREVENTION =====
    async def check_duplicate(self, ctx):
        """Check if this command was already processed"""
        key = f"{ctx.author.id}:{ctx.command.name}"
        current_time = time.time()
        
        if key in self.processed_commands:
            if current_time - self.processed_commands[key] < 3:
                print(f"⚠️ Prevented dual execution: {ctx.command.name} by {ctx.author}")
                return True
        
        self.processed_commands[key] = current_time
        
        if len(self.processed_commands) > 100:
            to_delete = [k for k, t in self.processed_commands.items() if current_time - t > 10]
            for k in to_delete:
                del self.processed_commands[k]
        
        return False

    # ===== DATABASE SETUP =====
    def setup_database(self):
        """Initialize workout database tables"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            
            # Food library
            c.execute('''CREATE TABLE IF NOT EXISTS workout_user_foods
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          user_id TEXT,
                          food_name TEXT,
                          calories INTEGER,
                          protein REAL,
                          created_at REAL,
                          UNIQUE(user_id, food_name))''')
            
            # Daily food log
            c.execute('''CREATE TABLE IF NOT EXISTS workout_daily_food_log
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          user_id TEXT,
                          day_number INTEGER,
                          food_name TEXT,
                          servings REAL,
                          calories INTEGER,
                          protein REAL,
                          logged_at REAL)''')
            
            # Daily strength workout log - TEXT fields for flexibility
            c.execute('''CREATE TABLE IF NOT EXISTS workout_daily_workout_log
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          user_id TEXT,
                          day_number INTEGER,
                          exercise TEXT,
                          weight TEXT,
                          sets TEXT,
                          reps TEXT,
                          notes TEXT,
                          logged_at REAL)''')
            
            # Daily cardio log - duration in seconds
            c.execute('''CREATE TABLE IF NOT EXISTS workout_daily_cardio_log
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          user_id TEXT,
                          day_number INTEGER,
                          type TEXT DEFAULT 'treadmill',
                          duration_seconds INTEGER,
                          speed REAL,
                          logged_at REAL)''')
            
            # User progress tracking
            c.execute('''CREATE TABLE IF NOT EXISTS workout_user_progress
                         (user_id TEXT PRIMARY KEY,
                          current_day INTEGER DEFAULT 0,
                          last_completed_day INTEGER DEFAULT 0,
                          started_at REAL,
                          last_updated REAL)''')
            
            # Add last_completed_day column if it doesn't exist (for existing databases)
            try:
                c.execute("ALTER TABLE workout_user_progress ADD COLUMN last_completed_day INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # Column already exists
            
            conn.commit()
            conn.close()
            print("✅ Workout database initialized")
        except Exception as e:
            print(f"❌ Error setting up workout database: {e}")

    # ===== DATABASE HELPERS =====
    def get_current_day(self, user_id):
        """Get current active day number for user (0 if not started)"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT current_day FROM workout_user_progress WHERE user_id = ?", (str(user_id),))
            result = c.fetchone()
            conn.close()
            return result[0] if result else 0
        except:
            return 0

    def get_last_completed_day(self, user_id):
        """Get the last completed day number"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT last_completed_day FROM workout_user_progress WHERE user_id = ?", (str(user_id),))
            result = c.fetchone()
            conn.close()
            return result[0] if result else 0
        except:
            return 0

    def get_all_days(self, user_id):
        """Get all completed day numbers for user"""
        last_completed = self.get_last_completed_day(user_id)
        if last_completed == 0:
            return []
        return list(range(1, last_completed + 1))

    def start_new_day(self, user_id):
        """Start a new day for user"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            
            last_completed = self.get_last_completed_day(user_id)
            new_day = last_completed + 1
            
            c.execute('''INSERT OR REPLACE INTO workout_user_progress
                         (user_id, current_day, last_completed_day, started_at, last_updated)
                         VALUES (?, ?, ?, COALESCE((SELECT started_at FROM workout_user_progress WHERE user_id = ?), ?), ?)''',
                      (str(user_id), new_day, last_completed, str(user_id), time.time(), time.time()))
            conn.commit()
            conn.close()
            return new_day
        except Exception as e:
            print(f"Error starting new day: {e}")
            return 0

    def end_current_day(self, user_id):
        """End current day, update last_completed_day"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            
            # Get current day before ending
            c.execute("SELECT current_day FROM workout_user_progress WHERE user_id = ?", (str(user_id),))
            result = c.fetchone()
            current_day = result[0] if result else 0
            
            if current_day > 0:
                # Update last_completed_day to current day
                c.execute('''UPDATE workout_user_progress 
                             SET current_day = 0, 
                                 last_completed_day = ?,
                                 last_updated = ?
                             WHERE user_id = ?''',
                          (current_day, time.time(), str(user_id)))
                conn.commit()
                conn.close()
                return True
            conn.close()
            return False
        except Exception as e:
            print(f"Error ending day: {e}")
            return False

    def save_food_log(self, user_id, day_number, food_name, servings, calories, protein):
        """Save a food log entry"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''INSERT INTO workout_daily_food_log
                         (user_id, day_number, food_name, servings, calories, protein, logged_at)
                         VALUES (?, ?, ?, ?, ?, ?, ?)''',
                      (str(user_id), day_number, food_name, servings, calories, protein, time.time()))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error saving food log: {e}")
            return False

    def save_workout_log(self, user_id, day_number, exercise, weight, sets, reps, notes):
        """Save a strength workout log"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''INSERT INTO workout_daily_workout_log
                         (user_id, day_number, exercise, weight, sets, reps, notes, logged_at)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                      (str(user_id), day_number, exercise, str(weight), sets, reps, notes, time.time()))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error saving workout log: {e}")
            return False

    async def save_cardio_session(self, user_id, duration_seconds, speed):
        """Save a cardio session (duration in seconds)"""
        day_number = self.get_current_day(user_id)
        if day_number == 0:
            return False
        
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''INSERT INTO workout_daily_cardio_log
                         (user_id, day_number, type, duration_seconds, speed, logged_at)
                         VALUES (?, ?, ?, ?, ?, ?)''',
                      (str(user_id), day_number, 'treadmill', duration_seconds, speed, time.time()))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error saving cardio session: {e}")
            return False

    def add_food_to_library(self, user_id, food_name, calories, protein):
        """Add a food to user's library"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''INSERT OR REPLACE INTO workout_user_foods
                         (user_id, food_name, calories, protein, created_at)
                         VALUES (?, ?, ?, ?, ?)''',
                      (str(user_id), food_name.lower(), calories, protein, time.time()))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error adding food: {e}")
            return False

    def get_food_from_library(self, user_id, food_name):
        """Get food details from library"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT calories, protein FROM workout_user_foods WHERE user_id = ? AND food_name = ?",
                      (str(user_id), food_name.lower()))
            result = c.fetchone()
            conn.close()
            return result if result else None
        except:
            return None

    def get_user_foods(self, user_id):
        """Get all foods in user's library"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("SELECT food_name, calories, protein FROM workout_user_foods WHERE user_id = ? ORDER BY food_name",
                      (str(user_id),))
            results = c.fetchall()
            conn.close()
            return results
        except:
            return []

    def get_day_summary(self, user_id, day_number):
        """Get complete summary for a specific day"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            
            # Get food logs
            c.execute('''SELECT food_name, servings, calories, protein 
                         FROM workout_daily_food_log 
                         WHERE user_id = ? AND day_number = ?''',
                      (str(user_id), day_number))
            foods = c.fetchall()
            
            # Aggregate food totals
            food_totals = {}
            total_calories = 0
            total_protein = 0
            for food_name, servings, calories, protein in foods:
                if food_name not in food_totals:
                    food_totals[food_name] = {"servings": 0, "calories": 0, "protein": 0}
                food_totals[food_name]["servings"] += servings
                food_totals[food_name]["calories"] += calories
                food_totals[food_name]["protein"] += protein
                total_calories += calories
                total_protein += protein
            
            # Get strength workouts
            c.execute('''SELECT exercise, weight, sets, reps, notes 
                         FROM workout_daily_workout_log 
                         WHERE user_id = ? AND day_number = ?
                         ORDER BY logged_at''',
                      (str(user_id), day_number))
            workouts = c.fetchall()
            
            # Get cardio (duration in seconds)
            c.execute('''SELECT type, duration_seconds, speed 
                         FROM workout_daily_cardio_log 
                         WHERE user_id = ? AND day_number = ?''',
                      (str(user_id), day_number))
            cardio = c.fetchall()
            
            # Calculate total cardio minutes from seconds
            total_cardio_minutes = sum(c[1] for c in cardio) // 60
            
            conn.close()
            
            return {
                "food_totals": food_totals,
                "total_calories": total_calories,
                "total_protein": total_protein,
                "workouts": workouts,
                "cardio": cardio,
                "total_cardio_minutes": total_cardio_minutes,
                "has_data": bool(foods or workouts or cardio)
            }
        except Exception as e:
            print(f"Error getting day summary: {e}")
            return None

    def delete_all_user_data(self, user_id):
        """Delete all workout data for a user"""
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM workout_user_foods WHERE user_id = ?", (str(user_id),))
            c.execute("DELETE FROM workout_daily_food_log WHERE user_id = ?", (str(user_id),))
            c.execute("DELETE FROM workout_daily_workout_log WHERE user_id = ?", (str(user_id),))
            c.execute("DELETE FROM workout_daily_cardio_log WHERE user_id = ?", (str(user_id),))
            c.execute("DELETE FROM workout_user_progress WHERE user_id = ?", (str(user_id),))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error deleting user data: {e}")
            return False

    async def create_day_channel(self, guild, day_number, summary):
        """Create a channel for the completed day"""
        # Calculate month number (1-based, 30 days per month)
        month_number = ((day_number - 1) // 30) + 1
        category_name = f"Month {month_number}"
        
        # Get or create category
        category = discord.utils.get(guild.categories, name=category_name)
        if not category:
            category = await guild.create_category(category_name)
        
        # Create channel name
        channel_name = f"day-{day_number}"
        
        # Check if channel already exists
        existing = discord.utils.get(category.channels, name=channel_name)
        if existing:
            return existing
        
        # Create channel
        channel = await guild.create_text_channel(channel_name, category=category)
        
        # Build summary embed
        embed = discord.Embed(
            title=f"📅 Day {day_number} Summary",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        
        # Add workouts section
        workout_text = ""
        for cardio in summary["cardio"]:
            cardio_type, duration_seconds, speed = cardio
            minutes = duration_seconds // 60
            seconds = duration_seconds % 60
            workout_text += f"• Treadmill\n   time: {minutes}:{seconds:02d} ({duration_seconds} seconds)\n   speed: {speed} mph\n"
        for workout in summary["workouts"]:
            exercise, weight, sets, reps, notes = workout
            notes_display = notes if notes else "None"
            weight_display = weight if weight else "bodyweight"
            workout_text += f"• {exercise}\n   Weight: {weight_display}\n   Sets: {sets}\n   Reps: {reps}\n   Notes: {notes_display}\n"
        
        if workout_text:
            embed.add_field(name="🏋️ Workouts", value=workout_text, inline=False)
        else:
            embed.add_field(name="🏋️ Workouts", value="*No workouts logged*", inline=False)
        
        # Add food section
        food_text = ""
        for food_name, data in summary["food_totals"].items():
            food_text += f"• {food_name}: {data['servings']} serving(s) ({data['calories']} cal, {data['protein']}g protein)\n"
        
        if food_text:
            embed.add_field(name="🍽️ Food Log", value=food_text, inline=False)
        else:
            embed.add_field(name="🍽️ Food Log", value="*No food logged*", inline=False)
        
        # Add totals
        embed.add_field(
            name="📊 Totals",
            value=f"• Calories: {summary['total_calories']}\n• Protein: {summary['total_protein']}g\n• Cardio: {summary['total_cardio_minutes']} minutes",
            inline=False
        )
        
        # Check if it was a lazy day
        if not summary["has_data"]:
            embed.description = "⚠️ **Lazy Day** - No workouts or food logged!"
            embed.color = discord.Color.orange()
        
        await channel.send(embed=embed)
        return channel

    # ===== INTERACTIVE WIZARDS =====
    async def interactive_addfood(self, ctx):
        """Interactive wizard for adding food"""
        user_id = ctx.author.id
        
        def check(m):
            return m.author.id == user_id and m.channel.id == ctx.channel.id
        
        try:
            # Step 1: Get food name
            await ctx.send("🍽️ What's the name of the food?")
            name_msg = await self.bot.wait_for('message', timeout=60.0, check=check)
            food_name = name_msg.content.strip().lower()
            await name_msg.delete()
            
            # Step 2: Get calories
            await ctx.send(f"📊 How many calories per serving for **{food_name}**?")
            cal_msg = await self.bot.wait_for('message', timeout=60.0, check=check)
            try:
                calories = int(cal_msg.content.strip())
            except ValueError:
                await ctx.send("❌ Invalid number. Please use a number.")
                await cal_msg.delete()
                return
            await cal_msg.delete()
            
            # Step 3: Get protein
            await ctx.send(f"💪 How many grams of protein per serving for **{food_name}**?")
            protein_msg = await self.bot.wait_for('message', timeout=60.0, check=check)
            try:
                protein = float(protein_msg.content.strip())
            except ValueError:
                await ctx.send("❌ Invalid number. Please use a number.")
                await protein_msg.delete()
                return
            await protein_msg.delete()
            
            # Save to library
            if self.add_food_to_library(user_id, food_name, calories, protein):
                await ctx.send(f"✅ Saved **{food_name}** with {calories} calories and {protein}g protein per serving!")
            else:
                await ctx.send("❌ Error saving food. Please try again.")
                
        except asyncio.TimeoutError:
            await ctx.send("⏰ Timed out. Please try again.")

    async def interactive_logfood(self, ctx):
        """Interactive wizard for logging food"""
        user_id = ctx.author.id
        day_number = self.get_current_day(user_id)
        
        if day_number == 0:
            await ctx.send("❌ You haven't started today yet! Use `!start today` to begin.")
            return
        
        def check(m):
            return m.author.id == user_id and m.channel.id == ctx.channel.id
        
        try:
            # Step 1: Get food name
            await ctx.send("🍽️ What have you eaten today?")
            name_msg = await self.bot.wait_for('message', timeout=60.0, check=check)
            food_name = name_msg.content.strip().lower()
            await name_msg.delete()
            
            # Check if food exists in library
            food_data = self.get_food_from_library(user_id, food_name)
            if not food_data:
                await ctx.send(f"❌ Food **{food_name}** not found in your library! Use `!addfood` to add it first.")
                return
            
            calories_per_serving, protein_per_serving = food_data
            
            # Step 2: Get servings
            await ctx.send(f"📊 How many servings of **{food_name}**? (1 serving = {calories_per_serving} cal, {protein_per_serving}g protein)")
            servings_msg = await self.bot.wait_for('message', timeout=60.0, check=check)
            try:
                servings = float(servings_msg.content.strip())
            except ValueError:
                await ctx.send("❌ Invalid number. Please use a number.")
                await servings_msg.delete()
                return
            await servings_msg.delete()
            
            # Calculate totals
            total_calories = int(calories_per_serving * servings)
            total_protein = protein_per_serving * servings
            
            # Save to database
            if self.save_food_log(user_id, day_number, food_name, servings, total_calories, total_protein):
                await ctx.send(f"✅ Logged {servings} serving(s) of **{food_name}** ({total_calories} cal, {total_protein}g protein) for Day {day_number}!")
            else:
                await ctx.send("❌ Error saving food log. Please try again.")
                
        except asyncio.TimeoutError:
            await ctx.send("⏰ Timed out. Please try again.")

    async def interactive_logworkout(self, ctx):
        """Interactive wizard for logging strength workout"""
        user_id = ctx.author.id
        day_number = self.get_current_day(user_id)
        
        if day_number == 0:
            await ctx.send("❌ You haven't started today yet! Use `!start today` to begin.")
            return
        
        def check(m):
            return m.author.id == user_id and m.channel.id == ctx.channel.id
        
        try:
            # Step 1: Get exercise name
            await ctx.send("💪 What workout did you do?")
            name_msg = await self.bot.wait_for('message', timeout=60.0, check=check)
            exercise = name_msg.content.strip()
            await name_msg.delete()
            
            # Step 2: Get weight
            await ctx.send(f"🏋️ What weight did you use for **{exercise}**? (in lbs, or 'bodyweight' for no weight)")
            weight_msg = await self.bot.wait_for('message', timeout=60.0, check=check)
            weight = weight_msg.content.strip()
            await weight_msg.delete()
            
            # Step 3: Get sets
            await ctx.send(f"📊 How many sets of **{exercise}** did you do? (e.g., '3', '3-4', 'until failure')")
            sets_msg = await self.bot.wait_for('message', timeout=60.0, check=check)
            sets = sets_msg.content.strip()
            await sets_msg.delete()
            
            # Step 4: Get reps
            await ctx.send(f"🔄 How many reps per set? (e.g., '8', '8-10', 'until failure')")
            reps_msg = await self.bot.wait_for('message', timeout=60.0, check=check)
            reps = reps_msg.content.strip()
            await reps_msg.delete()
            
            # Step 5: Get notes (save everything, no filtering)
            await ctx.send(f"📝 Any notes? (Type 'skip' for none)")
            notes_msg = await self.bot.wait_for('message', timeout=60.0, check=check)
            notes = notes_msg.content.strip()
            await notes_msg.delete()
            
            # Handle skip
            if notes.lower() == "skip":
                notes = "None"
            
            # Save to database
            if self.save_workout_log(user_id, day_number, exercise, weight, sets, reps, notes):
                await ctx.send(f"✅ Saved workout: **{exercise}** ({weight}, {sets} sets × {reps} reps) for Day {day_number}!")
                if notes != "None":
                    await ctx.send(f"📝 Note saved: {notes}")
            else:
                await ctx.send("❌ Error saving workout. Please try again.")
                
        except asyncio.TimeoutError:
            await ctx.send("⏰ Timed out. Please try again.")

    # ===== COMMANDS =====
    @commands.command(name='start')
    @commands.guild_only()
    async def start_today(self, ctx):
        """Start tracking today's workout and food"""
        if await self.check_duplicate(ctx):
            return
            
        # Check if in allowed server
        if ctx.guild.id != ALLOWED_SERVER_ID:
            await ctx.send("❌ This command is only available in the designated workout server.")
            return
        
        user_id = ctx.author.id
        current_day = self.get_current_day(user_id)
        
        if current_day > 0:
            await ctx.send(f"⚠️ You're currently on **Day {current_day}** and have yet to end today. Use `!end today` to finish the day first.")
            return
        
        # Start new day
        new_day = self.start_new_day(user_id)
        if new_day > 0:
            await ctx.send(f"✅ Started **Day {new_day}**! Use `!logfood`, `!logworkout`, or `!treadmill` to track your progress.")
        else:
            await ctx.send("❌ Error starting day. Please try again.")

    @commands.command(name='end')
    @commands.guild_only()
    async def end_today(self, ctx):
        """End today's tracking and save all data"""
        if await self.check_duplicate(ctx):
            return
            
        # Check if in allowed server
        if ctx.guild.id != ALLOWED_SERVER_ID:
            await ctx.send("❌ This command is only available in the designated workout server.")
            return
        
        user_id = ctx.author.id
        current_day = self.get_current_day(user_id)
        
        if current_day == 0:
            await ctx.send("❌ You haven't started today yet! Use `!start today` to begin.")
            return
        
        # Get summary to check if anything was logged
        summary = self.get_day_summary(user_id, current_day)
        
        if not summary or not summary["has_data"]:
            await ctx.send(f"📝 You didn't log anything for Day {current_day}. This will be saved as a **Lazy Day**.")
        
        # Create channel with summary
        if summary:
            channel = await self.create_day_channel(ctx.guild, current_day, summary)
            if channel:
                await ctx.send(f"✅ Day {current_day} complete! Created {channel.mention} with your summary.")
            else:
                await ctx.send(f"✅ Day {current_day} complete! Summary saved.")
        
        # End the day
        self.end_current_day(user_id)
        
        next_day = current_day + 1
        await ctx.send(f"Use `!start today` to begin Day {next_day}!")

    @commands.command(name='today')
    @commands.guild_only()
    async def show_today(self, ctx):
        """Show current day's progress"""
        if await self.check_duplicate(ctx):
            return
            
        # Check if in allowed server
        if ctx.guild.id != ALLOWED_SERVER_ID:
            await ctx.send("❌ This command is only available in the designated workout server.")
            return
        
        user_id = ctx.author.id
        current_day = self.get_current_day(user_id)
        
        if current_day == 0:
            await ctx.send("❌ You haven't started today yet! Use `!start today` to begin.")
            return
        
        summary = self.get_day_summary(user_id, current_day)
        
        if not summary:
            await ctx.send(f"📝 No data logged for Day {current_day} yet.")
            return
        
        embed = discord.Embed(
            title=f"📅 Day {current_day} Progress (Not Ended Yet)",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        
        # Workouts section
        workout_text = ""
        for cardio in summary["cardio"]:
            cardio_type, duration_seconds, speed = cardio
            minutes = duration_seconds // 60
            seconds = duration_seconds % 60
            workout_text += f"• Treadmill\n   time: {minutes}:{seconds:02d} ({duration_seconds} seconds)\n   speed: {speed} mph\n"
        for workout in summary["workouts"]:
            exercise, weight, sets, reps, notes = workout
            notes_display = notes if notes else "None"
            weight_display = weight if weight else "bodyweight"
            workout_text += f"• {exercise}\n   Weight: {weight_display}\n   Sets: {sets}\n   Reps: {reps}\n   Notes: {notes_display}\n"
        
        if workout_text:
            embed.add_field(name="🏋️ Workouts Logged", value=workout_text, inline=False)
        else:
            embed.add_field(name="🏋️ Workouts Logged", value="*No workouts logged yet*", inline=False)
        
        # Food section
        food_text = ""
        for food_name, data in summary["food_totals"].items():
            food_text += f"• {food_name}: {data['servings']} serving(s) ({data['calories']} cal, {data['protein']}g protein)\n"
        
        if food_text:
            embed.add_field(name="🍽️ Food Logged", value=food_text, inline=False)
        else:
            embed.add_field(name="🍽️ Food Logged", value="*No food logged yet*", inline=False)
        
        # Totals
        embed.add_field(
            name="📊 Current Totals",
            value=f"• Calories: {summary['total_calories']}\n• Protein: {summary['total_protein']}g\n• Cardio: {summary['total_cardio_minutes']} minutes",
            inline=False
        )
        
        embed.set_footer(text="Use !end today to finish this day")
        await ctx.send(embed=embed)

    @commands.command(name='day')
    @commands.guild_only()
    async def show_day(self, ctx, day_number: int = None):
        """Show summary for a specific day. If no number, shows latest completed day."""
        if await self.check_duplicate(ctx):
            return
            
        # Check if in allowed server
        if ctx.guild.id != ALLOWED_SERVER_ID:
            await ctx.send("❌ This command is only available in the designated workout server.")
            return
        
        user_id = ctx.author.id
        
        if day_number is None:
            # Show latest completed day
            last_completed = self.get_last_completed_day(user_id)
            if last_completed == 0:
                await ctx.send("📭 No completed days yet. Use `!start today` to begin!")
                return
            day_number = last_completed
        
        summary = self.get_day_summary(user_id, day_number)
        
        if not summary:
            await ctx.send(f"📭 Day {day_number} not found or no data logged.")
            return
        
        embed = discord.Embed(
            title=f"📅 Day {day_number} Summary",
            color=discord.Color.blue()
        )
        
        # Workouts section
        workout_text = ""
        for cardio in summary["cardio"]:
            cardio_type, duration_seconds, speed = cardio
            minutes = duration_seconds // 60
            seconds = duration_seconds % 60
            workout_text += f"• Treadmill\n   time: {minutes}:{seconds:02d} ({duration_seconds} seconds)\n   speed: {speed} mph\n"
        for workout in summary["workouts"]:
            exercise, weight, sets, reps, notes = workout
            notes_display = notes if notes else "None"
            weight_display = weight if weight else "bodyweight"
            workout_text += f"• {exercise}\n   Weight: {weight_display}\n   Sets: {sets}\n   Reps: {reps}\n   Notes: {notes_display}\n"
        
        if workout_text:
            embed.add_field(name="🏋️ Workouts", value=workout_text, inline=False)
        elif not summary["has_data"]:
            embed.add_field(name="🏋️ Workouts", value="⚠️ *Lazy Day - No workouts*", inline=False)
        else:
            embed.add_field(name="🏋️ Workouts", value="*No workouts logged*", inline=False)
        
        # Food section
        food_text = ""
        for food_name, data in summary["food_totals"].items():
            food_text += f"• {food_name}: {data['servings']} serving(s) ({data['calories']} cal, {data['protein']}g protein)\n"
        
        if food_text:
            embed.add_field(name="🍽️ Food Log", value=food_text, inline=False)
        elif not summary["has_data"]:
            embed.add_field(name="🍽️ Food Log", value="⚠️ *Lazy Day - No food*", inline=False)
        else:
            embed.add_field(name="🍽️ Food Log", value="*No food logged*", inline=False)
        
        # Totals
        embed.add_field(
            name="📊 Totals",
            value=f"• Calories: {summary['total_calories']}\n• Protein: {summary['total_protein']}g\n• Cardio: {summary['total_cardio_minutes']} minutes",
            inline=False
        )
        
        if not summary["has_data"]:
            embed.color = discord.Color.orange()
        
        await ctx.send(embed=embed)

    @commands.command(name='days')
    @commands.guild_only()
    async def list_days(self, ctx):
        """List all completed days"""
        if await self.check_duplicate(ctx):
            return
            
        # Check if in allowed server
        if ctx.guild.id != ALLOWED_SERVER_ID:
            await ctx.send("❌ This command is only available in the designated workout server.")
            return
        
        user_id = ctx.author.id
        completed_days = self.get_all_days(user_id)
        
        if not completed_days:
            await ctx.send("📭 No completed days yet. Use `!start today` to begin!")
            return
        
        # Format the list
        day_list = ", ".join([f"Day {d}" for d in completed_days])
        
        embed = discord.Embed(
            title="📅 Completed Days",
            description=f"**{len(completed_days)}** day(s) completed\n\n{day_list}",
            color=discord.Color.blue()
        )
        embed.set_footer(text="Use !day [number] to view a specific day")
        await ctx.send(embed=embed)

    @commands.command(name='resetdays')
    @commands.guild_only()
    async def reset_days(self, ctx):
        """Delete ALL your workout data (food library, logs, everything)"""
        if await self.check_duplicate(ctx):
            return
            
        # Check if in allowed server
        if ctx.guild.id != ALLOWED_SERVER_ID:
            await ctx.send("❌ This command is only available in the designated workout server.")
            return
        
        await ctx.send("⚠️ **WARNING!** This will delete ALL your workout data, food library, and progress. Type `CONFIRM` to reset everything.")
        
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        
        try:
            msg = await self.bot.wait_for('message', timeout=30.0, check=check)
            if msg.content.strip().upper() == "CONFIRM":
                await msg.delete()
                if self.delete_all_user_data(ctx.author.id):
                    await ctx.send("✅ All your workout data has been deleted. You can start fresh with `!start today`!")
                else:
                    await ctx.send("❌ Error deleting data. Please try again.")
            else:
                await ctx.send("❌ Reset cancelled.")
        except asyncio.TimeoutError:
            await ctx.send("⏰ Timed out. Reset cancelled.")

    @commands.command(name='addfood')
    @commands.guild_only()
    async def addfood(self, ctx):
        """Add a food to your library (interactive)"""
        if await self.check_duplicate(ctx):
            return
            
        # Check if in allowed server
        if ctx.guild.id != ALLOWED_SERVER_ID:
            await ctx.send("❌ This command is only available in the designated workout server.")
            return
        
        await self.interactive_addfood(ctx)

    @commands.command(name='logfood')
    @commands.guild_only()
    async def logfood(self, ctx):
        """Log food for today (interactive)"""
        if await self.check_duplicate(ctx):
            return
            
        # Check if in allowed server
        if ctx.guild.id != ALLOWED_SERVER_ID:
            await ctx.send("❌ This command is only available in the designated workout server.")
            return
        
        await self.interactive_logfood(ctx)

    @commands.command(name='log')
    @commands.guild_only()
    async def log_shortcut(self, ctx, food_name: str, amount: float = 1.0):
        """Quick log food. Usage: !log egg 2"""
        if await self.check_duplicate(ctx):
            return
            
        # Check if in allowed server
        if ctx.guild.id != ALLOWED_SERVER_ID:
            await ctx.send("❌ This command is only available in the designated workout server.")
            return
        
        user_id = ctx.author.id
        day_number = self.get_current_day(user_id)
        
        if day_number == 0:
            await ctx.send("❌ You haven't started today yet! Use `!start today` to begin.")
            return
        
        food_data = self.get_food_from_library(user_id, food_name.lower())
        if not food_data:
            await ctx.send(f"❌ Food **{food_name}** not found in your library! Use `!addfood` to add it first.")
            return
        
        calories_per_serving, protein_per_serving = food_data
        total_calories = int(calories_per_serving * amount)
        total_protein = protein_per_serving * amount
        
        if self.save_food_log(user_id, day_number, food_name.lower(), amount, total_calories, total_protein):
            await ctx.send(f"✅ Logged {amount} serving(s) of **{food_name}** ({total_calories} cal, {total_protein}g protein) for Day {day_number}!")
        else:
            await ctx.send("❌ Error saving food log. Please try again.")

    @commands.command(name='myfoods')
    @commands.guild_only()
    async def myfoods(self, ctx):
        """List all foods in your library"""
        if await self.check_duplicate(ctx):
            return
            
        # Check if in allowed server
        if ctx.guild.id != ALLOWED_SERVER_ID:
            await ctx.send("❌ This command is only available in the designated workout server.")
            return
        
        user_id = ctx.author.id
        foods = self.get_user_foods(user_id)
        
        if not foods:
            await ctx.send("📭 Your food library is empty. Use `!addfood` to add some foods!")
            return
        
        embed = discord.Embed(
            title="🍽️ Your Food Library",
            color=discord.Color.blue()
        )
        
        food_list = []
        for food_name, calories, protein in foods:
            food_list.append(f"• **{food_name}**: {calories} cal, {protein}g protein")
        
        # Split into chunks if too many
        chunk_size = 20
        for i in range(0, len(food_list), chunk_size):
            chunk = food_list[i:i+chunk_size]
            embed.add_field(name="Foods" if i == 0 else "Continued", value="\n".join(chunk), inline=False)
        
        embed.set_footer(text=f"{len(foods)} food(s) total")
        await ctx.send(embed=embed)

    @commands.command(name='logworkout')
    @commands.guild_only()
    async def logworkout(self, ctx):
        """Log a strength workout (interactive)"""
        if await self.check_duplicate(ctx):
            return
            
        # Check if in allowed server
        if ctx.guild.id != ALLOWED_SERVER_ID:
            await ctx.send("❌ This command is only available in the designated workout server.")
            return
        
        await self.interactive_logworkout(ctx)

    @commands.command(name='treadmill')
    @commands.guild_only()
    async def treadmill(self, ctx):
        """Start a treadmill session with timer"""
        if await self.check_duplicate(ctx):
            return
            
        # Check if in allowed server
        if ctx.guild.id != ALLOWED_SERVER_ID:
            await ctx.send("❌ This command is only available in the designated workout server.")
            return
        
        user_id = ctx.author.id
        day_number = self.get_current_day(user_id)
        
        if day_number == 0:
            await ctx.send("❌ You haven't started today yet! Use `!start today` to begin.")
            return
        
        # Check if user already has an active session
        if user_id in treadmill_sessions:
            await ctx.send("❌ You already have an active treadmill session! Please stop it first.")
            return
        
        def check(m):
            return m.author.id == user_id and m.channel.id == ctx.channel.id
        
        try:
            await ctx.send("🏃 What speed are you running at? (mph)")
            speed_msg = await self.bot.wait_for('message', timeout=30.0, check=check)
            try:
                speed = float(speed_msg.content.strip())
            except ValueError:
                await ctx.send("❌ Invalid speed. Please use a number.")
                await speed_msg.delete()
                return
            await speed_msg.delete()
            
            # Create timer display message (will be updated)
            timer_embed = discord.Embed(
                title="🏃 Treadmill Session",
                description=f"Speed: {speed} mph\nClick **Start** to begin.",
                color=discord.Color.blue()
            )
            timer_message = await ctx.send(embed=timer_embed)
            
            # Create control view (buttons on separate message)
            view = TreadmillControlView(user_id, speed, self, timer_message)
            control_embed = discord.Embed(
                title="Treadmill Controls",
                description="Click **Start** to begin your session. Timer will update below.",
                color=discord.Color.blue()
            )
            control_message = await ctx.send(embed=control_embed, view=view)
            
            # Store session info
            treadmill_sessions[user_id] = {
                "active": True,
                "control_msg_id": control_message.id,
                "timer_msg_id": timer_message.id,
                "channel_id": ctx.channel.id
            }
            
        except asyncio.TimeoutError:
            await ctx.send("⏰ Timed out. Please try again.")


async def setup(bot):
    await bot.add_cog(Workout(bot))
