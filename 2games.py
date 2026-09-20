import discord
from discord.ext import commands
import asyncio
import random
import sqlite3
import time
import os
from datetime import datetime
from typing import List, Tuple, Dict, Optional
from PIL import Image, ImageDraw, ImageFont
import io

# ===== CONFIGURATION =====
DB_FOLDER = r"C:\Users\Kelly\Desktop\discord database"
MAIN_DB_PATH = os.path.join(DB_FOLDER, "asaiya_bot.db")

# ============================================================
# CHESS BOARD IMAGE GENERATOR
# ============================================================

class ChessBoardGenerator:
    """Generate beautiful chess board images using PIL"""
    
    # Square colors
    LIGHT_SQUARE = (240, 217, 181)  # Light wood color
    DARK_SQUARE = (181, 136, 99)    # Dark wood color
    
    def __init__(self, square_size: int = 70):
        self.square_size = square_size
        self.board_size = square_size * 8
        self.font = None
        self._load_font()
    
    def _load_font(self):
        """Load a font that supports chess pieces (Unicode symbols)"""
        # Try to find a font that supports chess symbols
        font_paths = [
            "C:/Windows/Fonts/seguiemj.ttf",  # Windows emoji font (supports chess)
            "C:/Windows/Fonts/seguisym.ttf",  # Windows symbol font
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/consola.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Apple Color Emoji.ttc",
        ]
        
        for size in [int(self.square_size * 0.6), self.square_size // 2]:
            for path in font_paths:
                if os.path.exists(path):
                    try:
                        self.font = ImageFont.truetype(path, size)
                        # Test if the font can render chess pieces by checking character width
                        test_bbox = ImageDraw.Draw(Image.new('RGB', (1, 1))).textbbox((0, 0), "♔", font=self.font)
                        if test_bbox[2] > 0:  # Font rendered something
                            print(f"✅ Loaded chess font: {path}")
                            return
                    except:
                        continue
        
        # Fallback to default font
        self.font = ImageFont.load_default()
        print("⚠️ Using default font - chess pieces may not display correctly")
    
    def draw_board(self, board: List[List[Tuple]]) -> Image.Image:
        """Draw the chess board with pieces"""
        img = Image.new('RGB', (self.board_size, self.board_size), self.LIGHT_SQUARE)
        draw = ImageDraw.Draw(img)
        
        # Draw squares
        for row in range(8):
            for col in range(8):
                x1 = col * self.square_size
                y1 = row * self.square_size
                x2 = x1 + self.square_size
                y2 = y1 + self.square_size
                
                if (row + col) % 2 == 1:
                    draw.rectangle([x1, y1, x2, y2], fill=self.DARK_SQUARE)
        
        # Draw pieces
        for row in range(8):
            for col in range(8):
                piece = board[row][col]
                if piece:
                    piece_symbol = piece[1]  # This is the Unicode symbol like ♔, ♕, etc.
                    
                    # Calculate center position
                    x = col * self.square_size + self.square_size // 2
                    y = row * self.square_size + self.square_size // 2
                    
                    # Get text dimensions for centering
                    try:
                        bbox = draw.textbbox((0, 0), piece_symbol, font=self.font)
                        text_width = bbox[2] - bbox[0]
                        text_height = bbox[3] - bbox[1]
                    except:
                        text_width = self.square_size // 2
                        text_height = self.square_size // 2
                    
                    # Draw piece text centered
                    draw.text((x - text_width // 2, y - text_height // 2), 
                             piece_symbol, fill=(0, 0, 0), font=self.font)
        
        return img
    
    def get_board_image_bytes(self, board: List[List[Tuple]]) -> io.BytesIO:
        """Get board image as BytesIO for Discord"""
        img = self.draw_board(board)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return buf


# ============================================================
# CHESS CONSTANTS
# ============================================================

class ChessPiece:
    # White pieces
    WHITE_KING = "♔"
    WHITE_QUEEN = "♕"
    WHITE_ROOK = "♖"
    WHITE_BISHOP = "♗"
    WHITE_KNIGHT = "♘"
    WHITE_PAWN = "♙"
    
    # Black pieces
    BLACK_KING = "♚"
    BLACK_QUEEN = "♛"
    BLACK_ROOK = "♜"
    BLACK_BISHOP = "♝"
    BLACK_KNIGHT = "♞"
    BLACK_PAWN = "♟"
    
    FILES = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']


class ChessGameLogic:
    def __init__(self):
        self.reset()
    
    def reset(self):
        """Reset the chess board to starting position"""
        self.board = [[None for _ in range(8)] for _ in range(8)]
        self.current_turn = 'white'
        self.game_over = False
        self.winner = None
        self.move_history = []
        
        # Place pawns
        for i in range(8):
            self.board[1][i] = ('black', ChessPiece.BLACK_PAWN)
            self.board[6][i] = ('white', ChessPiece.WHITE_PAWN)
        
        # Place other pieces
        back_row = [
            ChessPiece.WHITE_ROOK, ChessPiece.WHITE_KNIGHT, ChessPiece.WHITE_BISHOP,
            ChessPiece.WHITE_QUEEN, ChessPiece.WHITE_KING, ChessPiece.WHITE_BISHOP,
            ChessPiece.WHITE_KNIGHT, ChessPiece.WHITE_ROOK
        ]
        black_back_row = [
            ChessPiece.BLACK_ROOK, ChessPiece.BLACK_KNIGHT, ChessPiece.BLACK_BISHOP,
            ChessPiece.BLACK_QUEEN, ChessPiece.BLACK_KING, ChessPiece.BLACK_BISHOP,
            ChessPiece.BLACK_KNIGHT, ChessPiece.BLACK_ROOK
        ]
        
        for i in range(8):
            self.board[0][i] = ('black', black_back_row[i])
            self.board[7][i] = ('white', back_row[i])
    
    def get_board_display(self) -> str:
        """Get a clean text-based board display using Unicode chess symbols"""
        display = []
        display.append("```")
        display.append("    a   b   c   d   e   f   g   h")
        display.append("  ┌───┬───┬───┬───┬───┬───┬───┬───┐")
        
        for row in range(8):
            row_display = f"{8 - row} │"
            for col in range(8):
                piece = self.board[row][col]
                if piece:
                    symbol = piece[1]
                else:
                    symbol = " "  # Empty square
                row_display += f" {symbol} │"
            display.append(row_display)
            
            if row < 7:
                display.append("  ├───┼───┼───┼───┼───┼───┼───┼───┤")
            else:
                display.append("  └───┴───┴───┴───┴───┴───┴───┴───┘")
        
        display.append("```")
        return '\n'.join(display)
    
    def make_move(self, from_pos: Tuple[int, int], to_pos: Tuple[int, int]) -> bool:
        """Make a move on the board"""
        from_row, from_col = from_pos
        to_row, to_col = to_pos
        
        piece = self.board[from_row][from_col]
        if not piece:
            return False
        
        piece_color, piece_type = piece
        
        # Check if it's the correct player's turn
        if (piece_color == 'white' and self.current_turn != 'white') or \
           (piece_color == 'black' and self.current_turn != 'black'):
            return False
        
        # Check if target square has own piece
        target = self.board[to_row][to_col]
        if target and target[0] == piece_color:
            return False
        
        # Calculate move deltas
        row_diff = to_row - from_row
        col_diff = to_col - from_col
        
        # ===== PAWN MOVEMENT =====
        if piece_type in [ChessPiece.WHITE_PAWN, ChessPiece.BLACK_PAWN]:
            direction = -1 if piece_color == 'white' else 1
            
            # Move forward one
            if col_diff == 0 and row_diff == direction and not target:
                self._execute_move(from_pos, to_pos)
                return True
            
            # Move forward two from starting position
            start_row = 6 if piece_color == 'white' else 1
            if col_diff == 0 and row_diff == direction * 2 and from_row == start_row and not target:
                middle_row = from_row + direction
                if not self.board[middle_row][from_col]:
                    self._execute_move(from_pos, to_pos)
                    return True
            
            # Capture diagonally
            if abs(col_diff) == 1 and row_diff == direction and target:
                self._execute_move(from_pos, to_pos)
                return True
        
        # ===== KNIGHT MOVEMENT =====
        elif piece_type in [ChessPiece.WHITE_KNIGHT, ChessPiece.BLACK_KNIGHT]:
            if (abs(row_diff) == 2 and abs(col_diff) == 1) or (abs(row_diff) == 1 and abs(col_diff) == 2):
                self._execute_move(from_pos, to_pos)
                return True
        
        # ===== KING MOVEMENT =====
        elif piece_type in [ChessPiece.WHITE_KING, ChessPiece.BLACK_KING]:
            if max(abs(row_diff), abs(col_diff)) == 1:
                self._execute_move(from_pos, to_pos)
                return True
        
        # ===== ROOK, BISHOP, QUEEN =====
        else:
            # Check if path is clear
            if self._is_path_clear(from_pos, to_pos):
                self._execute_move(from_pos, to_pos)
                return True
        
        return False
    
    def _is_path_clear(self, from_pos: Tuple[int, int], to_pos: Tuple[int, int]) -> bool:
        """Check if the path between two squares is clear"""
        from_row, from_col = from_pos
        to_row, to_col = to_pos
        
        row_step = 0 if from_row == to_row else (1 if to_row > from_row else -1)
        col_step = 0 if from_col == to_col else (1 if to_col > from_col else -1)
        
        row, col = from_row + row_step, from_col + col_step
        while (row, col) != (to_row, to_col):
            if self.board[row][col]:
                return False
            row += row_step
            col += col_step
        
        return True
    
    def _execute_move(self, from_pos: Tuple[int, int], to_pos: Tuple[int, int]):
        """Execute the move without validation"""
        from_row, from_col = from_pos
        to_row, to_col = to_pos
        
        piece = self.board[from_row][from_col]
        target = self.board[to_row][to_col]
        
        # Record move
        move_str = f"{ChessPiece.FILES[from_col]}{8 - from_row} → {ChessPiece.FILES[to_col]}{8 - to_row}"
        if target:
            move_str += f" (captured {target[1]})"
        self.move_history.append(move_str)
        
        # Move piece
        self.board[to_row][to_col] = piece
        self.board[from_row][from_col] = None
        
        # Pawn promotion (auto-queen)
        if piece[1] in [ChessPiece.WHITE_PAWN, ChessPiece.BLACK_PAWN]:
            if (piece[0] == 'white' and to_row == 0) or (piece[0] == 'black' and to_row == 7):
                queen = ChessPiece.WHITE_QUEEN if piece[0] == 'white' else ChessPiece.BLACK_QUEEN
                self.board[to_row][to_col] = (piece[0], queen)
        
        # Switch turns
        self.current_turn = 'black' if self.current_turn == 'white' else 'white'
    
    def get_embed(self, player1_id: int, player2_id: int, guild, board_generator: ChessBoardGenerator = None) -> Tuple[discord.Embed, Optional[discord.File]]:
        """Get the game embed with board and info"""
        
        player1 = guild.get_member(player1_id)
        player2 = guild.get_member(player2_id)
        
        embed = discord.Embed(
            title="♜ CHESS GAME ♞",
            color=discord.Color.blue()
        )
        
        # If board generator is provided, use image
        if board_generator:
            board_image = board_generator.get_board_image_bytes(self.board)
            file = discord.File(board_image, filename="chess_board.png")
            embed.set_image(url="attachment://chess_board.png")
        else:
            # Fallback to text board
            board_display = self.get_board_display()
            embed.description = board_display
            file = None
        
        turn_emoji = "⚪" if self.current_turn == 'white' else "⚫"
        turn_name = "WHITE" if self.current_turn == 'white' else "BLACK"
        embed.add_field(name="Turn", value=f"{turn_emoji} {turn_name}", inline=True)
        
        embed.add_field(
            name="Players",
            value=f"⚪ White: {player1.mention if player1 else f'<@{player1_id}>'}\n⚫ Black: {player2.mention if player2 else f'<@{player2_id}>'}",
            inline=True
        )
        
        if self.move_history:
            last_moves = "\n".join(self.move_history[-5:])
            embed.add_field(name="Recent Moves", value=f"```{last_moves}```", inline=False)
        
        embed.set_footer(text="Type your move as 'e2 e4' or use !chessmove e2 e4")
        return embed, file


# ============================================================
# SNAKE GAME
# ============================================================

class SnakeGame:
    """Snake game logic with queued moves for lag compensation"""
    
    UP = (0, -1)
    DOWN = (0, 1)
    LEFT = (-1, 0)
    RIGHT = (1, 0)
    
    SNAKE_HEAD = "🟢"
    SNAKE_BODY = "🟩"
    FOOD = "🍎"
    EMPTY = "⬛"
    WALL = "🧱"
    
    def __init__(self, width: int = 15, height: int = 15):
        self.width = width
        self.height = height
        self.reset()
    
    def reset(self):
        start_x = self.width // 2
        start_y = self.height // 2
        self.snake: List[Tuple[int, int]] = [
            (start_x, start_y),
            (start_x - 1, start_y),
            (start_x - 2, start_y)
        ]
        self.direction = self.RIGHT
        self.pending_directions = []
        self.score = 0
        self.game_over = False
        self.food = self._generate_food()
    
    def _generate_food(self) -> Tuple[int, int]:
        while True:
            x = random.randint(1, self.width - 2)
            y = random.randint(1, self.height - 2)
            if (x, y) not in self.snake:
                return (x, y)
    
    def change_direction(self, new_direction: Tuple[int, int]):
        if self.pending_directions:
            last = self.pending_directions[-1] if self.pending_directions else self.direction
            if (new_direction[0] == -last[0] and new_direction[1] == -last[1]):
                return
        elif (new_direction[0] == -self.direction[0] and new_direction[1] == -self.direction[1]):
            return
        self.pending_directions.append(new_direction)
        if len(self.pending_directions) > 3:
            self.pending_directions = self.pending_directions[-3:]
    
    def move(self) -> bool:
        while self.pending_directions:
            self.direction = self.pending_directions.pop(0)
        
        head = self.snake[0]
        new_head = (head[0] + self.direction[0], head[1] + self.direction[1])
        
        if (new_head[0] < 1 or new_head[0] >= self.width - 1 or
            new_head[1] < 1 or new_head[1] >= self.height - 1):
            self.game_over = True
            return False
        
        ate_food = (new_head == self.food)
        self.snake.insert(0, new_head)
        
        if not ate_food:
            self.snake.pop()
        else:
            self.score += 1
            self.food = self._generate_food()
        
        if new_head in self.snake[1:]:
            self.game_over = True
            return False
        
        return True
    
    def get_board_emoji(self) -> str:
        board = []
        for y in range(self.height):
            row = []
            for x in range(self.width):
                if x == 0 or x == self.width - 1 or y == 0 or y == self.height - 1:
                    row.append(self.WALL)
                elif (x, y) == self.snake[0]:
                    row.append(self.SNAKE_HEAD)
                elif (x, y) in self.snake[1:]:
                    row.append(self.SNAKE_BODY)
                elif (x, y) == self.food:
                    row.append(self.FOOD)
                else:
                    row.append(self.EMPTY)
            board.append(''.join(row))
        return '\n'.join(board)
    
    def get_embed(self) -> discord.Embed:
        board = self.get_board_emoji()
        embed = discord.Embed(
            title="🐍 SNAKE GAME",
            description=f"```\n{board}\n```",
            color=discord.Color.green() if not self.game_over else discord.Color.red()
        )
        if self.game_over:
            embed.add_field(name="💀 GAME OVER", value=f"Final Score: **{self.score}**", inline=False)
        else:
            embed.add_field(name="🍎 Score", value=str(self.score), inline=True)
            embed.add_field(name="🎮 Controls", value="⬆️ ⬇️ ⬅️ ➡️", inline=True)
        embed.set_footer(text="Game updates every 0.4 seconds • Click buttons to control")
        return embed


# ============================================================
# MAIN GAMES COG
# ============================================================

class Games(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_snake_games: Dict[int, Dict] = {}
        self.active_chess_queues: Dict[int, Dict] = {}
        self.active_chess_games: Dict[int, Dict] = {}
        self.chess_draw_offers: Dict[int, int] = {}
        self.active_card_games: Dict[int, Dict] = {}  # Card game lobbies
        self.processed_commands = {}
        self.chess_board_generator = ChessBoardGenerator(square_size=70)  # Initialize board generator
        
        self.setup_database()
        
        print(f"✅ Games cog initialized (ID: {id(self)})")
    
    def setup_database(self):
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS snake_leaderboard
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          user_id TEXT,
                          user_name TEXT,
                          guild_id TEXT,
                          score INTEGER,
                          date REAL)''')
            conn.commit()
            conn.close()
            print("✅ Snake leaderboard database initialized")
        except Exception as e:
            print(f"Error setting up snake leaderboard: {e}")
    
    def save_snake_score(self, user_id: int, user_name: str, guild_id: int, score: int):
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("INSERT INTO snake_leaderboard (user_id, user_name, guild_id, score, date) VALUES (?, ?, ?, ?, ?)",
                      (str(user_id), user_name, str(guild_id), score, time.time()))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error saving score: {e}")
            return False
    
    def get_snake_leaderboard(self, guild_id: int, limit: int = 10):
        try:
            conn = sqlite3.connect(MAIN_DB_PATH)
            c = conn.cursor()
            c.execute("""SELECT user_name, score, date FROM snake_leaderboard 
                         WHERE guild_id = ? ORDER BY score DESC LIMIT ?""",
                      (str(guild_id), limit))
            results = c.fetchall()
            conn.close()
            return results
        except Exception as e:
            print(f"Error getting leaderboard: {e}")
            return []
    
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
    
    # ===== XP BETTING HELPERS =====
    
    def get_level_cog(self):
        """Get the Level cog to access XP methods"""
        return self.bot.get_cog('Level')
    
    def can_afford_bet(self, user_id: int, guild_id: int, bet_amount: int) -> bool:
        """Check if user can afford the bet"""
        level_cog = self.get_level_cog()
        if not level_cog:
            return False
        user_xp = level_cog.get_user_xp(user_id, guild_id)
        return user_xp >= bet_amount
    
    def deduct_bet(self, user_id: int, guild_id: int, bet_amount: int) -> bool:
        """Deduct bet amount from user's XP"""
        level_cog = self.get_level_cog()
        if not level_cog:
            return False
        return level_cog.deduct_xp(user_id, guild_id, bet_amount)
    
    def award_winner(self, user_id: int, guild_id: int, amount: int):
        """Award XP to winner"""
        level_cog = self.get_level_cog()
        if level_cog:
            level_cog.add_xp(user_id, guild_id, amount)
    
    def set_game_active(self, user_id: int, guild_id: int, active: bool):
        """Mark user as in game (disables XP gain from messages)"""
        level_cog = self.get_level_cog()
        if level_cog:
            level_cog.set_game_active(user_id, guild_id, active)
    
    # ============================================================
    # CHESS GAME
    # ============================================================
    
    class ChessJoinView(discord.ui.View):
        def __init__(self, cog, channel_id: int):
            super().__init__(timeout=60)
            self.cog = cog
            self.channel_id = channel_id
            self.players = []
        
        @discord.ui.button(label="♜ Join Chess Game", style=discord.ButtonStyle.green, custom_id="chess_join")
        async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id in self.players:
                await interaction.response.send_message("❌ You already joined!", ephemeral=True)
                return
            if len(self.players) >= 2:
                await interaction.response.send_message("❌ Game already has 2 players!", ephemeral=True)
                return
            
            self.players.append(interaction.user.id)
            await interaction.response.send_message(f"✅ {interaction.user.mention} joined! ({len(self.players)}/2 players)", ephemeral=False)
            
            if len(self.players) == 2:
                self.stop()
                await self.cog.start_chess_game(self.channel_id, self.players[0], self.players[1], interaction)
    
    async def start_chess_game(self, channel_id: int, player1_id: int, player2_id: int, interaction: discord.Interaction):
        game = ChessGameLogic()
        embed, file = game.get_embed(player1_id, player2_id, interaction.guild, self.chess_board_generator)
        
        if file:
            message = await interaction.channel.send(embed=embed, file=file)
        else:
            message = await interaction.channel.send(embed=embed)
        
        self.active_chess_games[channel_id] = {
            "game": game,
            "player1": player1_id,
            "player2": player2_id,
            "current_turn": 'white',
            "message_id": message.id
        }
        
        if channel_id in self.active_chess_queues:
            del self.active_chess_queues[channel_id]
    
    @commands.command(name='chesses')
    async def chess_game(self, ctx):
        """Start a chess game lobby for 2 players"""
        if await self.check_duplicate(ctx):
            return
        
        if ctx.channel.id in self.active_chess_games:
            await ctx.send("❌ A chess game is already active in this channel! Use `!chessboard` to see it.")
            return
        
        if ctx.channel.id in self.active_chess_queues:
            await ctx.send("❌ A chess lobby is already open! Use `!chesscancel` to cancel.")
            return
        
        embed = discord.Embed(
            title="♜ CHESS GAME LOBBY ♞",
            description="Click the **Join** button below to participate.\n\n**2 players needed** to start the game.\n\n**How to play:**\n• White moves first\n• Type `e2 e4` to move a piece\n• Use `!chessmove e2 e4` as an alternative",
            color=discord.Color.blue()
        )
        
        view = self.ChessJoinView(self, ctx.channel.id)
        message = await ctx.send(embed=embed, view=view)
        
        self.active_chess_queues[ctx.channel.id] = {
            "players": [],
            "message_id": message.id,
            "view": view
        }
        
        await asyncio.sleep(60)
        if ctx.channel.id in self.active_chess_queues:
            queue_data = self.active_chess_queues.pop(ctx.channel.id)
            timeout_embed = discord.Embed(
                title="♜ CHESS LOBBY CANCELLED",
                description="Game lobby timed out. Not enough players joined.",
                color=discord.Color.orange()
            )
            try:
                await message.edit(embed=timeout_embed, view=None)
            except:
                pass
    
    @commands.command(name='chesscancel')
    async def chess_cancel(self, ctx):
        """Cancel the chess lobby in this channel"""
        if await self.check_duplicate(ctx):
            return
        
        if ctx.channel.id in self.active_chess_queues:
            queue_data = self.active_chess_queues.pop(ctx.channel.id)
            embed = discord.Embed(
                title="♜ CHESS LOBBY CANCELLED",
                description=f"Game lobby cancelled by {ctx.author.mention}",
                color=discord.Color.red()
            )
            try:
                message = await ctx.channel.fetch_message(queue_data["message_id"])
                await message.edit(embed=embed, view=None)
            except:
                pass
            await ctx.send("✅ Chess lobby cancelled.")
        else:
            await ctx.send("ℹ️ No active chess lobby in this channel.")
    
    @commands.command(name='chessmove')
    async def chess_move(self, ctx, *, move: str):
        """Make a move. Usage: !chessmove e2 e4 or just e2 e4"""
        if await self.check_duplicate(ctx):
            return
        
        if ctx.channel.id not in self.active_chess_games:
            await ctx.send("❌ No active chess game in this channel! Use `!chess` to start one.")
            return
        
        game_data = self.active_chess_games[ctx.channel.id]
        game = game_data["game"]
        
        expected_color = 'white' if ctx.author.id == game_data["player1"] else 'black' if ctx.author.id == game_data["player2"] else None
        if not expected_color:
            await ctx.send("❌ You are not a player in this game!")
            return
        if game.current_turn != expected_color:
            await ctx.send(f"❌ It's not your turn! {game.current_turn.upper()} is playing.")
            return
        
        parts = move.lower().split()
        if len(parts) != 2:
            await ctx.send("❌ Invalid format! Use `e2 e4` or `!chessmove e2 e4`")
            return
        
        from_square, to_square = parts
        try:
            from_col = ord(from_square[0]) - ord('a')
            from_row = 8 - int(from_square[1])
            to_col = ord(to_square[0]) - ord('a')
            to_row = 8 - int(to_square[1])
        except (ValueError, IndexError):
            await ctx.send("❌ Invalid square format! Use letters a-h and numbers 1-8 (e.g., e2)")
            return
        
        if not all(0 <= x < 8 for x in [from_row, from_col, to_row, to_col]):
            await ctx.send("❌ Coordinates out of range! Use a1-h8.")
            return
        
        if game.make_move((from_row, from_col), (to_row, to_col)):
            embed, file = game.get_embed(game_data["player1"], game_data["player2"], ctx.guild, self.chess_board_generator)
            
            try:
                message = await ctx.channel.fetch_message(game_data["message_id"])
                if file:
                    await message.edit(embed=embed, attachments=[file])
                else:
                    await message.edit(embed=embed)
            except:
                if file:
                    await ctx.send(embed=embed, file=file)
                else:
                    await ctx.send(embed=embed)
            
            next_player = game_data["player1"] if game.current_turn == 'white' else game_data["player2"]
            await ctx.send(f"✅ {ctx.author.mention} moved! {game.current_turn.upper()}'s turn. <@{next_player}>")
            
            game_data["current_turn"] = game.current_turn
        else:
            await ctx.send("❌ Invalid move! Check the piece movement rules.")
    
    @commands.command(name='chessboard')
    async def chess_board(self, ctx):
        """Show the current chess board"""
        if await self.check_duplicate(ctx):
            return
        
        if ctx.channel.id not in self.active_chess_games:
            await ctx.send("❌ No active chess game in this channel!")
            return
        
        game_data = self.active_chess_games[ctx.channel.id]
        embed, file = game_data["game"].get_embed(game_data["player1"], game_data["player2"], ctx.guild, self.chess_board_generator)
        
        if file:
            await ctx.send(embed=embed, file=file)
        else:
            await ctx.send(embed=embed)
    
    @commands.command(name='draw')
    async def draw_command(self, ctx):
        """Offer or accept a draw in chess"""
        if await self.check_duplicate(ctx):
            return
        
        if ctx.channel.id not in self.active_chess_games:
            await ctx.send("❌ No active chess game in this channel!")
            return
        
        game_data = self.active_chess_games[ctx.channel.id]
        game = game_data["game"]
        
        if game.game_over:
            await ctx.send("❌ The game is already over!")
            return
        
        if ctx.channel.id in self.chess_draw_offers:
            # Accept draw
            offerer = self.chess_draw_offers[ctx.channel.id]
            if ctx.author.id != offerer:
                game.game_over = True
                game.winner = None
                embed, file = game.get_embed(game_data["player1"], game_data["player2"], ctx.guild, self.chess_board_generator)
                await ctx.send("🤝 **Draw accepted!** The game is a draw.")
                if file:
                    await ctx.send(embed=embed, file=file)
                else:
                    await ctx.send(embed=embed)
                del self.chess_draw_offers[ctx.channel.id]
            else:
                await ctx.send("❌ You already offered a draw! Wait for the opponent to accept.")
        else:
            # Offer draw
            self.chess_draw_offers[ctx.channel.id] = ctx.author.id
            await ctx.send(f"🤝 {ctx.author.mention} offers a draw. Type `!draw` to accept.")
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for chess moves without command prefix"""
        if message.author.bot:
            return
        if not message.guild:
            return
        
        # Check if there's an active chess game
        if message.channel.id not in self.active_chess_games:
            return
        
        content = message.content.lower().strip()
        
        # Skip if it's a command
        if content.startswith('!'):
            return
        
        parts = content.split()
        if len(parts) != 2:
            return
        
        from_square, to_square = parts
        
        if not (len(from_square) >= 2 and len(to_square) >= 2):
            return
        
        if from_square[0] not in 'abcdefgh' or to_square[0] not in 'abcdefgh':
            return
        
        try:
            from_rank = int(from_square[1])
            to_rank = int(to_square[1])
            if not (1 <= from_rank <= 8 and 1 <= to_rank <= 8):
                return
        except ValueError:
            return
        
        try:
            await message.delete()
        except:
            pass
        
        ctx = await self.bot.get_context(message)
        await self.chess_move(ctx, move=content)
    
    # ============================================================
    # SNAKE GAME
    # ============================================================
    
    class SnakeView(discord.ui.View):
        def __init__(self, cog, channel_id: int, user_id: int):
            super().__init__(timeout=120)
            self.cog = cog
            self.channel_id = channel_id
            self.user_id = user_id
        
        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ Only the player who started the game can control it!", ephemeral=True)
                return False
            return True
        
        @discord.ui.button(label="⬆️", style=discord.ButtonStyle.secondary)
        async def up_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.channel_id in self.cog.active_snake_games:
                self.cog.active_snake_games[self.channel_id]["game"].change_direction(SnakeGame.UP)
            await interaction.response.defer()
        
        @discord.ui.button(label="⬅️", style=discord.ButtonStyle.secondary)
        async def left_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.channel_id in self.cog.active_snake_games:
                self.cog.active_snake_games[self.channel_id]["game"].change_direction(SnakeGame.LEFT)
            await interaction.response.defer()
        
        @discord.ui.button(label="⬇️", style=discord.ButtonStyle.secondary)
        async def down_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.channel_id in self.cog.active_snake_games:
                self.cog.active_snake_games[self.channel_id]["game"].change_direction(SnakeGame.DOWN)
            await interaction.response.defer()
        
        @discord.ui.button(label="➡️", style=discord.ButtonStyle.secondary)
        async def right_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.channel_id in self.cog.active_snake_games:
                self.cog.active_snake_games[self.channel_id]["game"].change_direction(SnakeGame.RIGHT)
            await interaction.response.defer()
        
        @discord.ui.button(label="❌ Quit", style=discord.ButtonStyle.red)
        async def quit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.channel_id in self.cog.active_snake_games:
                game_data = self.cog.active_snake_games.pop(self.channel_id)
                game_data["task"].cancel()
                embed = discord.Embed(title="🐍 Game Quit", description=f"Game ended by {interaction.user.mention}", color=discord.Color.orange())
                await interaction.response.edit_message(embed=embed, view=None)
            else:
                await interaction.response.defer()
            self.stop()
    
    @commands.command(name='snake')
    async def snake_game(self, ctx):
        """Start a Snake game in the current channel"""
        if await self.check_duplicate(ctx):
            return
        
        if ctx.channel.id in self.active_snake_games:
            await ctx.send("❌ A snake game is already active! Use `!snakequit` to force quit.")
            return
        
        game = SnakeGame()
        view = self.SnakeView(self, ctx.channel.id, ctx.author.id)
        embed = game.get_embed()
        message = await ctx.send(embed=embed, view=view)
        
        async def game_loop():
            try:
                while not game.game_over:
                    await asyncio.sleep(0.4)
                    if ctx.channel.id not in self.active_snake_games:
                        break
                    game.move()
                    try:
                        await message.edit(embed=game.get_embed())
                    except discord.NotFound:
                        break
                    if game.game_over:
                        self.save_snake_score(ctx.author.id, ctx.author.name, ctx.guild.id, game.score)
                        leaderboard = self.get_snake_leaderboard(ctx.guild.id, 5)
                        final_embed = discord.Embed(
                            title="💀 GAME OVER 💀",
                            description=f"**{ctx.author.mention}** scored **{game.score}** points!",
                            color=discord.Color.red()
                        )
                        if leaderboard:
                            lb_text = ""
                            for i, (name, score, date) in enumerate(leaderboard, 1):
                                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "📌"
                                lb_text += f"{medal} **{name}** - {score} points\n"
                            final_embed.add_field(name="🏆 Leaderboard (Top 5)", value=lb_text, inline=False)
                        await message.edit(embed=final_embed, view=None)
                        if ctx.channel.id in self.active_snake_games:
                            del self.active_snake_games[ctx.channel.id]
                        break
            except asyncio.CancelledError:
                pass
        
        task = asyncio.create_task(game_loop())
        self.active_snake_games[ctx.channel.id] = {"game": game, "task": task, "message_id": message.id, "user_id": ctx.author.id}
        
        await asyncio.sleep(120)
        if ctx.channel.id in self.active_snake_games:
            game_data = self.active_snake_games.pop(ctx.channel.id)
            game_data["task"].cancel()
            try:
                await message.edit(embed=discord.Embed(title="⏰ Game Timed Out", color=discord.Color.orange()), view=None)
            except:
                pass
    
    @commands.command(name='snakequit')
    async def snake_quit(self, ctx):
        """Force quit the active Snake game"""
        if await self.check_duplicate(ctx):
            return
        if ctx.channel.id in self.active_snake_games:
            game_data = self.active_snake_games.pop(ctx.channel.id)
            game_data["task"].cancel()
            await ctx.send("✅ Snake game forcefully ended.")
        else:
            await ctx.send("ℹ️ No active snake game in this channel.")
    
    @commands.command(name='snakeleaderboard', aliases=['snakelb'])
    async def snake_leaderboard(self, ctx, limit: int = 10):
        """Show snake game leaderboard"""
        if await self.check_duplicate(ctx):
            return
        limit = min(max(1, limit), 25)
        leaderboard = self.get_snake_leaderboard(ctx.guild.id, limit)
        if not leaderboard:
            await ctx.send("📭 No scores recorded yet! Play `!snake` to be the first!")
            return
        embed = discord.Embed(title="🐍 Snake Leaderboard", color=discord.Color.gold())
        lb_text = ""
        for i, (name, score, date) in enumerate(leaderboard, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            lb_text += f"{medal} **{name}** - {score} points\n"
        embed.add_field(name="🏆 High Scores", value=lb_text, inline=False)
        await ctx.send(embed=embed)
    
    # ============================================================
    # CARD GAMES (Higher/Lower, Blackjack, Poker)
    # ============================================================
    
    class CardGameLobbyView(discord.ui.View):
        def __init__(self, cog, host_id: int, channel_id: int):
            super().__init__(timeout=120)
            self.cog = cog
            self.host_id = host_id
            self.channel_id = channel_id
            self.players = [host_id]
            self.selected_game = None
            self.time_limit = 30
            self.bet_amount = 10
            self.game_started = False
        
        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            return True
        
        def get_embed(self, guild):
            embed = discord.Embed(
                title="🎴 CARD GAME LOBBY 🎴",
                color=discord.Color.blue()
            )
            host = guild.get_member(self.host_id)
            embed.add_field(name="Host", value=host.mention if host else f"<@{self.host_id}>", inline=True)
            embed.add_field(name="Game", value=self.selected_game.title() if self.selected_game else "Not selected", inline=True)
            embed.add_field(name="Bet Amount", value=f"{self.bet_amount} XP", inline=True)
            embed.add_field(name="Time Limit", value=f"{self.time_limit} seconds", inline=True)
            embed.add_field(name="Players", value=f"{len(self.players)} player(s)", inline=False)
            
            player_list = ""
            for i, player_id in enumerate(self.players[:20], 1):
                member = guild.get_member(player_id)
                player_list += f"{i}. {member.mention if member else f'<@{player_id}>'}\n"
            if len(self.players) > 20:
                player_list += f"... and {len(self.players) - 20} more"
            embed.add_field(name="Joined Players", value=player_list or "None", inline=False)
            
            embed.set_footer(text="Host must select game, set bet/time, then click Start!")
            return embed
        
        @discord.ui.button(label="🃏 Higher/Lower", style=discord.ButtonStyle.secondary, row=0)
        async def higher_lower_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != self.host_id:
                await interaction.response.send_message("❌ Only the host can choose the game!", ephemeral=True)
                return
            self.selected_game = "higherlower"
            for child in self.children:
                if isinstance(child, discord.ui.Button) and child.row == 0:
                    child.style = discord.ButtonStyle.secondary
            button.style = discord.ButtonStyle.green
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("✅ Game set to: **Higher or Lower**", ephemeral=True)
        
        @discord.ui.button(label="♠️ Blackjack", style=discord.ButtonStyle.secondary, row=0)
        async def blackjack_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != self.host_id:
                await interaction.response.send_message("❌ Only the host can choose the game!", ephemeral=True)
                return
            self.selected_game = "blackjack"
            for child in self.children:
                if isinstance(child, discord.ui.Button) and child.row == 0:
                    child.style = discord.ButtonStyle.secondary
            button.style = discord.ButtonStyle.green
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("✅ Game set to: **Blackjack**", ephemeral=True)
        
        @discord.ui.button(label="🃠 Poker", style=discord.ButtonStyle.secondary, row=0)
        async def poker_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != self.host_id:
                await interaction.response.send_message("❌ Only the host can choose the game!", ephemeral=True)
                return
            self.selected_game = "poker"
            for child in self.children:
                if isinstance(child, discord.ui.Button) and child.row == 0:
                    child.style = discord.ButtonStyle.secondary
            button.style = discord.ButtonStyle.green
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("✅ Game set to: **Poker**", ephemeral=True)
        
        @discord.ui.button(label="➕ Join Game", style=discord.ButtonStyle.green, row=1)
        async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.game_started:
                await interaction.response.send_message("❌ Game already started!", ephemeral=True)
                return
            if interaction.user.id in self.players:
                await interaction.response.send_message("❌ You already joined!", ephemeral=True)
                return
            
            if not self.cog.can_afford_bet(interaction.user.id, interaction.guild.id, self.bet_amount):
                await interaction.response.send_message(f"❌ You need at least **{self.bet_amount} XP** to join! Use `!leaderboard` to check your XP.", ephemeral=True)
                return
            
            self.players.append(interaction.user.id)
            await interaction.response.send_message(f"✅ {interaction.user.mention} joined! ({len(self.players)} players)", ephemeral=False)
            
            embed = self.get_embed(interaction.guild)
            await interaction.message.edit(embed=embed, view=self)
        
        @discord.ui.button(label="💰 Set Bet", style=discord.ButtonStyle.secondary, row=1)
        async def set_bet_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != self.host_id:
                await interaction.response.send_message("❌ Only the host can set the bet amount!", ephemeral=True)
                return
            
            await interaction.response.send_message("💰 Enter the bet amount (minimum 10 XP):", ephemeral=True)
            
            def check(m):
                return m.author.id == self.host_id and m.channel.id == interaction.channel.id
            
            try:
                msg = await self.cog.bot.wait_for('message', timeout=30.0, check=check)
                try:
                    bet = int(msg.content)
                    if bet < 10:
                        await interaction.followup.send("❌ Minimum bet is 10 XP!", ephemeral=True)
                        return
                    self.bet_amount = bet
                    await interaction.followup.send(f"✅ Bet amount set to **{bet} XP**", ephemeral=True)
                    embed = self.get_embed(interaction.guild)
                    await interaction.message.edit(embed=embed, view=self)
                except ValueError:
                    await interaction.followup.send("❌ Invalid number!", ephemeral=True)
            except asyncio.TimeoutError:
                await interaction.followup.send("⏰ Timed out!", ephemeral=True)
        
        @discord.ui.button(label="⏱️ Set Time", style=discord.ButtonStyle.secondary, row=1)
        async def set_time_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != self.host_id:
                await interaction.response.send_message("❌ Only the host can set the time limit!", ephemeral=True)
                return
            
            await interaction.response.send_message("⏱️ Enter time limit per turn (10-120 seconds):", ephemeral=True)
            
            def check(m):
                return m.author.id == self.host_id and m.channel.id == interaction.channel.id
            
            try:
                msg = await self.cog.bot.wait_for('message', timeout=30.0, check=check)
                try:
                    time_limit = int(msg.content)
                    if time_limit < 10 or time_limit > 120:
                        await interaction.followup.send("❌ Time limit must be between 10 and 120 seconds!", ephemeral=True)
                        return
                    self.time_limit = time_limit
                    await interaction.followup.send(f"✅ Time limit set to **{time_limit} seconds**", ephemeral=True)
                    embed = self.get_embed(interaction.guild)
                    await interaction.message.edit(embed=embed, view=self)
                except ValueError:
                    await interaction.followup.send("❌ Invalid number!", ephemeral=True)
            except asyncio.TimeoutError:
                await interaction.followup.send("⏰ Timed out!", ephemeral=True)
        
        @discord.ui.button(label="▶️ Start Game", style=discord.ButtonStyle.green, row=2)
        async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            # IMPORTANT: Defer first to prevent interaction timeout
            await interaction.response.defer()
            
            if interaction.user.id != self.host_id:
                await interaction.followup.send("❌ Only the host can start the game!", ephemeral=True)
                return
            
            if not self.selected_game:
                await interaction.followup.send("❌ Please select a game first!", ephemeral=True)
                return
            
            if len(self.players) < 2:
                await interaction.followup.send("❌ Need at least 2 players to start!", ephemeral=True)
                return
            
            # Verify all players can afford the bet
            level_cog = self.cog.get_level_cog()
            if level_cog:
                for player_id in self.players:
                    user_xp = level_cog.get_user_xp(player_id, interaction.guild.id)
                    if user_xp < self.bet_amount:
                        await interaction.followup.send(f"❌ <@{player_id}> doesn't have enough XP for the {self.bet_amount} XP bet!", ephemeral=True)
                        return
            
            self.game_started = True
            self.stop()
            await self.cog.start_card_game(interaction, self)
    
    async def start_card_game(self, interaction: discord.Interaction, lobby_view):
        """Start the selected card game"""
        channel_id = interaction.channel.id
        game_type = lobby_view.selected_game
        players = lobby_view.players
        bet_amount = lobby_view.bet_amount
        time_limit = lobby_view.time_limit
        
        # Mark all players as in-game (disable XP gain)
        for player_id in players:
            self.set_game_active(player_id, interaction.guild.id, True)
        
        # Deduct bets from all players
        total_pot = 0
        level_cog = self.get_level_cog()
        if level_cog:
            for player_id in players:
                if level_cog.deduct_xp(player_id, interaction.guild.id, bet_amount):
                    total_pot += bet_amount
        
        # Store game data
        self.active_card_games[channel_id] = {
            "game_type": game_type,
            "players": players,
            "host_id": lobby_view.host_id,
            "bet_amount": bet_amount,
            "total_pot": total_pot,
            "time_limit": time_limit,
            "status": "active",
            "current_turn_index": 0,
            "scores": {p: 0 for p in players},
            "hands": {},
            "current_round": 1,
            "channel_id": channel_id,
            "guild_id": interaction.guild.id
        }
        
        # Send confirmation message
        await interaction.followup.send(
            f"🎴 **{game_type.title()}** game started!\n"
            f"**Bet:** {bet_amount} XP each | **Total Pot:** {total_pot} XP\n"
            f"**Players:** {len(players)}\n\n"
            f"The game will be played in this channel!",
            ephemeral=False
        )
        
        # Start the appropriate game
        if game_type == "higherlower":
            await self.start_higher_lower(interaction, lobby_view)
        elif game_type == "blackjack":
            await self.start_blackjack(interaction, lobby_view)
        elif game_type == "poker":
            await self.start_poker(interaction, lobby_view)
    
    async def start_higher_lower(self, interaction: discord.Interaction, lobby_view):
        """Start Higher or Lower game - Sequential turns in channel"""
        game_data = self.active_card_games[interaction.channel.id]
        
        # Initialize scores for all players
        for player_id in game_data["players"]:
            game_data["scores"][player_id] = 0
        
        # Track whose turn it is
        game_data["current_player_index"] = 0
        game_data["round_number"] = 1
        game_data["game_ended"] = False
        
        await interaction.followup.send(
            f"🎴 **Higher or Lower** game started!\n"
            f"**Bet:** {game_data['bet_amount']} XP each | **Total Pot:** {game_data['total_pot']} XP\n"
            f"**Players:** {len(game_data['players'])}\n\n"
            f"First to **100 points** wins the pot!\n"
            f"Correct guess: **+10 points** | Wrong guess: **-5 points**",
            ephemeral=False
        )
        
        # Start first player's turn
        await self.higher_lower_turn(interaction.channel.id)
    
    async def higher_lower_turn(self, channel_id: int):
        """Process a single player's turn in Higher or Lower using ephemeral messages in channel"""
        game_data = self.active_card_games.get(channel_id)
        if not game_data:
            return
        
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return
        
        # Check if game is still active
        if game_data.get("game_ended"):
            return
        
        current_index = game_data.get("current_player_index", 0)
        
        # If we've gone through all players, start a new round
        if current_index >= len(game_data["players"]):
            game_data["current_player_index"] = 0
            game_data["round_number"] = game_data.get("round_number", 1) + 1
            
            # Announce new round
            await channel.send(f"📢 **Round {game_data['round_number']}** - Starting new round!")
            await self.higher_lower_turn(channel_id)
            return
        
        player_id = game_data["players"][current_index]
        user = channel.guild.get_member(player_id)
        
        if not user:
            # Skip invalid user
            game_data["current_player_index"] = current_index + 1
            await self.higher_lower_turn(channel_id)
            return
        
        # Generate a random card for this player
        cards = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
        current_card = random.randint(1, 13)
        card_name = cards[current_card - 1]
        
        # Store the card for this player's turn
        game_data["current_turn_card"] = current_card
        game_data["current_turn_player"] = player_id
        
        # Send public message announcing turn
        await channel.send(f"🎯 **{user.mention}'s turn!** (Round {game_data['round_number']})")
        
        class HigherLowerTurnView(discord.ui.View):
            def __init__(self, cog, channel_id, player_id, current_card, card_name):
                super().__init__(timeout=game_data["time_limit"])
                self.cog = cog
                self.channel_id = channel_id
                self.player_id = player_id
                self.current_card = current_card
                self.card_name = card_name
                self.responded = False
            
            async def on_timeout(self):
                if not self.responded:
                    game = self.cog.active_card_games.get(self.channel_id)
                    if game and game.get("current_turn_player") == self.player_id and not game.get("game_ended"):
                        # Timeout - deduct points and move to next player
                        game["scores"][self.player_id] = game["scores"].get(self.player_id, 0) - 10
                        
                        channel = self.cog.bot.get_channel(self.channel_id)
                        if channel:
                            await channel.send(
                                f"⏰ **{self.player_name}** took too long! **-10 points**\n"
                                f"Current score: **{game['scores'][self.player_id]}** points"
                            )
                        
                        # Move to next player
                        game["current_player_index"] = game.get("current_player_index", 0) + 1
                        await self.cog.higher_lower_turn(self.channel_id)
            
            @discord.ui.button(label="⬆️ Higher", style=discord.ButtonStyle.green)
            async def higher_button(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                if btn_interaction.user.id != self.player_id:
                    await btn_interaction.response.send_message("❌ It's not your turn!", ephemeral=True)
                    return
                
                if self.responded:
                    await btn_interaction.response.send_message("❌ You already played this turn!", ephemeral=True)
                    return
                
                self.responded = True
                next_card = random.randint(1, 13)
                won = next_card > self.current_card
                points = 10 if won else -5
                
                game = self.cog.active_card_games.get(self.channel_id)
                if game and game.get("current_turn_player") == self.player_id and not game.get("game_ended"):
                    game["scores"][self.player_id] = game["scores"].get(self.player_id, 0) + points
                    new_score = game["scores"][self.player_id]
                    
                    cards_list = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
                    result_text = f"{'✅' if won else '❌'} You guessed **HIGHER**\n"
                    result_text += f"Your card: **{self.card_name}** → Next card: **{cards_list[next_card - 1]}**\n"
                    result_text += f"{'+10' if won else '-5'} points! New score: **{new_score}** points"
                    
                    # Send result to channel (visible to everyone)
                    embed = discord.Embed(
                        title=f"🎴 {btn_interaction.user.display_name}'s Turn",
                        description=result_text,
                        color=discord.Color.green() if won else discord.Color.red()
                    )
                    await btn_interaction.response.send_message(embed=embed)
                    
                    # Move to next player
                    game["current_player_index"] = game.get("current_player_index", 0) + 1
                    
                    # Check for winner
                    await self.cog.check_higher_lower_winner(self.channel_id)
            
            @discord.ui.button(label="⬇️ Lower", style=discord.ButtonStyle.red)
            async def lower_button(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                if btn_interaction.user.id != self.player_id:
                    await btn_interaction.response.send_message("❌ It's not your turn!", ephemeral=True)
                    return
                
                if self.responded:
                    await btn_interaction.response.send_message("❌ You already played this turn!", ephemeral=True)
                    return
                
                self.responded = True
                next_card = random.randint(1, 13)
                won = next_card < self.current_card
                points = 10 if won else -5
                
                game = self.cog.active_card_games.get(self.channel_id)
                if game and game.get("current_turn_player") == self.player_id and not game.get("game_ended"):
                    game["scores"][self.player_id] = game["scores"].get(self.player_id, 0) + points
                    new_score = game["scores"][self.player_id]
                    
                    cards_list = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
                    result_text = f"{'✅' if won else '❌'} You guessed **LOWER**\n"
                    result_text += f"Your card: **{self.card_name}** → Next card: **{cards_list[next_card - 1]}**\n"
                    result_text += f"{'+10' if won else '-5'} points! New score: **{new_score}** points"
                    
                    # Send result to channel (visible to everyone)
                    embed = discord.Embed(
                        title=f"🎴 {btn_interaction.user.display_name}'s Turn",
                        description=result_text,
                        color=discord.Color.green() if won else discord.Color.red()
                    )
                    await btn_interaction.response.send_message(embed=embed)
                    
                    # Move to next player
                    game["current_player_index"] = game.get("current_player_index", 0) + 1
                    
                    # Check for winner
                    await self.cog.check_higher_lower_winner(self.channel_id)
        
        # Create the view
        view = HigherLowerTurnView(self, channel_id, player_id, current_card, card_name)
        view.player_name = user.display_name
        
        # Create ephemeral embed (only visible to the current player)
        embed = discord.Embed(
            title="🎴 Higher or Lower - Your Turn!",
            description=f"**Round {game_data['round_number']}**\n\n"
                        f"Your card: **{card_name}**\n\n"
                        f"Will the next card be **Higher** or **Lower**?\n\n"
                        f"✅ Correct: **+10 points**\n"
                        f"❌ Wrong: **-5 points**\n\n"
                        f"You have **{game_data['time_limit']} seconds** to decide.\n\n"
                        f"Current scores:\n" + "\n".join([f"• <@{pid}>: {score}" for pid, score in game_data["scores"].items()]),
            color=discord.Color.blue()
        )
        
        # Send ephemeral message (only visible to the current player)
        await user.send(embed=embed, view=view)
    
    async def check_higher_lower_winner(self, channel_id: int):
        """Check if anyone has reached 100 points in Higher/Lower"""
        game_data = self.active_card_games.get(channel_id)
        if not game_data:
            return
        
        channel = self.bot.get_channel(channel_id)
        
        # Check for winners
        winner = None
        winner_score = 0
        
        for player_id, score in game_data["scores"].items():
            if score >= 100:
                winner = player_id
                winner_score = score
                break
        
        if winner:
            winner_amount = game_data["total_pot"]
            self.award_winner(winner, game_data["guild_id"], winner_amount)
            
            # Mark all players as no longer in game
            for p_id in game_data["players"]:
                self.set_game_active(p_id, game_data["guild_id"], False)
            
            game_data["game_ended"] = True
            
            if channel:
                winner_user = channel.guild.get_member(winner)
                
                # Build final scoreboard
                scoreboard = "\n".join([f"• <@{pid}>: {score} points" for pid, score in sorted(game_data["scores"].items(), key=lambda x: x[1], reverse=True)])
                
                embed = discord.Embed(
                    title="🎉 GAME OVER! WINNER DETERMINED! 🎉",
                    description=f"**{winner_user.mention if winner_user else f'<@{winner}>'}** wins **{winner_amount} XP**!\n\n"
                                f"**Final Scores:**\n{scoreboard}",
                    color=discord.Color.gold()
                )
                await channel.send(embed=embed)
            
            del self.active_card_games[channel_id]
            return
        
        # No winner yet, continue with next player's turn
        await self.higher_lower_turn(channel_id)
    
    async def start_blackjack(self, interaction: discord.Interaction, lobby_view):
        """Start Blackjack game - Everything in channel"""
        game_data = self.active_card_games[interaction.channel.id]
        
        await interaction.followup.send(
            f"♠️ **Blackjack** game started!\n"
            f"**Bet:** {game_data['bet_amount']} XP each | **Total Pot:** {game_data['total_pot']} XP\n"
            f"**Players:** {len(game_data['players'])}\n\n"
            f"Each player will receive a private message with their hand.",
            ephemeral=False
        )
        
        for player_id in game_data["players"]:
            game_data["hands"][player_id] = []
            game_data["hands"][player_id].append(random.randint(1, 11))
            game_data["hands"][player_id].append(random.randint(1, 11))
        
        await self.blackjack_turn(interaction.channel.id)
    
    async def blackjack_turn(self, channel_id: int):
        """Process a player's turn in Blackjack using ephemeral messages"""
        game_data = self.active_card_games.get(channel_id)
        if not game_data:
            return
        
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return
        
        current_index = game_data.get("current_turn_index", 0)
        if current_index >= len(game_data["players"]):
            await self.determine_blackjack_winner(channel_id)
            return
        
        player_id = game_data["players"][current_index]
        user = channel.guild.get_member(player_id)
        if not user:
            game_data["current_turn_index"] = current_index + 1
            await self.blackjack_turn(channel_id)
            return
        
        hand = game_data["hands"][player_id]
        hand_value = sum(hand)
        
        if hand_value > 21:
            game_data["scores"][player_id] = 0
            game_data["current_turn_index"] = current_index + 1
            await channel.send(f"💥 **{user.display_name} BUSTED!** Hand value: {hand_value}")
            await self.blackjack_turn(channel_id)
            return
        
        cards_display = ", ".join([str(c) for c in hand])
        
        # Announce turn in channel
        await channel.send(f"🎯 **{user.mention}'s turn!** Hand: {cards_display} = {hand_value}")
        
        class BlackjackView(discord.ui.View):
            def __init__(self, cog, channel_id, player_id, hand):
                super().__init__(timeout=game_data["time_limit"])
                self.cog = cog
                self.channel_id = channel_id
                self.player_id = player_id
                self.hand = hand
                self.responded = False
            
            async def on_timeout(self):
                if not self.responded:
                    game = self.cog.active_card_games.get(self.channel_id)
                    if game:
                        # Auto-stand on timeout
                        hand_value = sum(self.hand)
                        game["scores"][self.player_id] = hand_value
                        game["current_turn_index"] = game.get("current_turn_index", 0) + 1
                        channel = self.cog.bot.get_channel(self.channel_id)
                        if channel:
                            await channel.send(f"⏰ **{self.player_name}** took too long! Standing with {hand_value}")
                        await self.cog.blackjack_turn(self.channel_id)
            
            @discord.ui.button(label="🃏 Hit", style=discord.ButtonStyle.green)
            async def hit_button(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                if btn_interaction.user.id != self.player_id:
                    await btn_interaction.response.send_message("❌ It's not your turn!", ephemeral=True)
                    return
                
                if self.responded:
                    await btn_interaction.response.send_message("❌ You already played this turn!", ephemeral=True)
                    return
                
                self.responded = True
                new_card = random.randint(1, 11)
                self.hand.append(new_card)
                hand_value = sum(self.hand)
                
                game = self.cog.active_card_games.get(self.channel_id)
                if game:
                    game["hands"][self.player_id] = self.hand
                
                cards = ", ".join([str(c) for c in self.hand])
                
                if hand_value > 21:
                    game["scores"][self.player_id] = 0
                    game["current_turn_index"] = game.get("current_turn_index", 0) + 1
                    
                    embed = discord.Embed(
                        title="💥 BUST!",
                        description=f"Your hand: {cards} = **{hand_value}**\nYou're out!",
                        color=discord.Color.red()
                    )
                    await btn_interaction.response.send_message(embed=embed, ephemeral=True)
                    
                    channel = self.cog.bot.get_channel(self.channel_id)
                    if channel:
                        await channel.send(f"💥 **{btn_interaction.user.display_name} BUSTED!** Hand: {cards} = {hand_value}")
                    
                    await self.cog.blackjack_turn(self.channel_id)
                else:
                    embed = discord.Embed(
                        title="🃏 Hit!",
                        description=f"Your hand: {cards} = **{hand_value}**\n\nHit or Stand?",
                        color=discord.Color.blue()
                    )
                    await btn_interaction.response.send_message(embed=embed, view=self, ephemeral=True)
                    self.responded = False  # Reset for next action
            
            @discord.ui.button(label="🛑 Stand", style=discord.ButtonStyle.red)
            async def stand_button(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                if btn_interaction.user.id != self.player_id:
                    await btn_interaction.response.send_message("❌ It's not your turn!", ephemeral=True)
                    return
                
                if self.responded:
                    await btn_interaction.response.send_message("❌ You already played this turn!", ephemeral=True)
                    return
                
                self.responded = True
                hand_value = sum(self.hand)
                game = self.cog.active_card_games.get(self.channel_id)
                if game:
                    game["scores"][self.player_id] = hand_value
                    game["current_turn_index"] = game.get("current_turn_index", 0) + 1
                
                cards = ", ".join([str(c) for c in self.hand])
                embed = discord.Embed(
                    title="🛑 Stand",
                    description=f"Your final hand: {cards} = **{hand_value}**",
                    color=discord.Color.blue()
                )
                await btn_interaction.response.send_message(embed=embed, ephemeral=True)
                
                channel = self.cog.bot.get_channel(self.channel_id)
                if channel:
                    await channel.send(f"🛑 **{btn_interaction.user.display_name}** stands with {hand_value}")
                
                await self.cog.blackjack_turn(self.channel_id)
        
        view = BlackjackView(self, channel_id, player_id, hand)
        view.player_name = user.display_name
        
        embed = discord.Embed(
            title="♠️ Blackjack - Your Turn!",
            description=f"Your hand: {cards_display} = **{hand_value}**\n\nHit or Stand?\n\nYou have **{game_data['time_limit']} seconds** to decide.",
            color=discord.Color.blue()
        )
        
        # Send ephemeral message via DM (still DM because Blackjack needs multiple interactions)
        await user.send(embed=embed, view=view)
    
    async def determine_blackjack_winner(self, channel_id: int):
        """Determine the winner of Blackjack"""
        game_data = self.active_card_games.get(channel_id)
        if not game_data:
            return
        
        channel = self.bot.get_channel(channel_id)
        
        # Find the highest score under 22
        best_score = 0
        winner = None
        for player_id, score in game_data["scores"].items():
            if 0 < score <= 21 and score > best_score:
                best_score = score
                winner = player_id
        
        if winner is None:
            if channel:
                await channel.send(f"💀 **No winners!** All players busted. The pot of **{game_data['total_pot']} XP** is lost!")
        else:
            winner_amount = game_data["total_pot"]
            self.award_winner(winner, game_data["guild_id"], winner_amount)
            
            if channel:
                winner_user = channel.guild.get_member(winner)
                await channel.send(
                    f"🎉 **BLACKJACK WINNER!** 🎉\n"
                    f"{winner_user.mention if winner_user else f'<@{winner}>'} wins **{winner_amount} XP** with {best_score} points!\n"
                    f"Final scores: " + ", ".join([f"<@{p}>: {s}" for p, s in game_data["scores"].items()])
                )
        
        for p_id in game_data["players"]:
            self.set_game_active(p_id, game_data["guild_id"], False)
        
        del self.active_card_games[channel_id]
    
    async def start_poker(self, interaction: discord.Interaction, lobby_view):
        """Start Poker game (simplified 5-card draw)"""
        game_data = self.active_card_games[interaction.channel.id]
        
        await interaction.followup.send(
            f"🃠 **Poker** game started!\n"
            f"**Bet:** {game_data['bet_amount']} XP each | **Total Pot:** {game_data['total_pot']} XP\n"
            f"**Players:** {len(game_data['players'])}\n\n"
            f"Each player will receive a private message with their hand.",
            ephemeral=False
        )
        
        suits = ["♠", "♥", "♦", "♣"]
        values = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
        
        for player_id in game_data["players"]:
            deck = [(v, s) for v in values for s in suits]
            random.shuffle(deck)
            game_data["hands"][player_id] = deck[:5]
            
            user = interaction.guild.get_member(player_id)
            if user:
                cards_display = ", ".join([f"{v}{s}" for v, s in game_data["hands"][player_id]])
                embed = discord.Embed(
                    title="🃠 Poker - Your Hand",
                    description=f"Your cards: **{cards_display}**\n\n"
                                f"You can discard up to 3 cards. Click the button below when ready.",
                    color=discord.Color.blue()
                )
                
                class PokerDiscardView(discord.ui.View):
                    def __init__(self, cog, channel_id, player_id, hand):
                        super().__init__(timeout=game_data["time_limit"])
                        self.cog = cog
                        self.channel_id = channel_id
                        self.player_id = player_id
                        self.hand = hand
                        self.selected = [False] * 5
                        self.update_buttons()
                    
                    def update_buttons(self):
                        button_labels = ["card1", "card2", "card3", "card4", "card5"]
                        for i, btn in enumerate(self.discard_buttons):
                            btn.label = f"✅ {self.hand[i][0]}{self.hand[i][1]}" if self.selected[i] else f"⬜ {self.hand[i][0]}{self.hand[i][1]}"
                            btn.style = discord.ButtonStyle.green if self.selected[i] else discord.ButtonStyle.secondary
                    
                    @discord.ui.button(label="⬜", style=discord.ButtonStyle.secondary, row=0)
                    async def card1(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                        if btn_interaction.user.id != self.player_id:
                            await btn_interaction.response.send_message("❌ This game isn't for you!", ephemeral=True)
                            return
                        self.selected[0] = not self.selected[0]
                        self.update_buttons()
                        await btn_interaction.response.edit_message(view=self)
                    
                    @discord.ui.button(label="⬜", style=discord.ButtonStyle.secondary, row=0)
                    async def card2(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                        if btn_interaction.user.id != self.player_id:
                            await btn_interaction.response.send_message("❌ This game isn't for you!", ephemeral=True)
                            return
                        self.selected[1] = not self.selected[1]
                        self.update_buttons()
                        await btn_interaction.response.edit_message(view=self)
                    
                    @discord.ui.button(label="⬜", style=discord.ButtonStyle.secondary, row=0)
                    async def card3(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                        if btn_interaction.user.id != self.player_id:
                            await btn_interaction.response.send_message("❌ This game isn't for you!", ephemeral=True)
                            return
                        self.selected[2] = not self.selected[2]
                        self.update_buttons()
                        await btn_interaction.response.edit_message(view=self)
                    
                    @discord.ui.button(label="⬜", style=discord.ButtonStyle.secondary, row=1)
                    async def card4(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                        if btn_interaction.user.id != self.player_id:
                            await btn_interaction.response.send_message("❌ This game isn't for you!", ephemeral=True)
                            return
                        self.selected[3] = not self.selected[3]
                        self.update_buttons()
                        await btn_interaction.response.edit_message(view=self)
                    
                    @discord.ui.button(label="⬜", style=discord.ButtonStyle.secondary, row=1)
                    async def card5(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                        if btn_interaction.user.id != self.player_id:
                            await btn_interaction.response.send_message("❌ This game isn't for you!", ephemeral=True)
                            return
                        self.selected[4] = not self.selected[4]
                        self.update_buttons()
                        await btn_interaction.response.edit_message(view=self)
                    
                    @discord.ui.button(label="🔄 Discard Selected", style=discord.ButtonStyle.primary, row=2)
                    async def discard_button(self, btn_interaction: discord.Interaction, button: discord.ui.Button):
                        if btn_interaction.user.id != self.player_id:
                            await btn_interaction.response.send_message("❌ This game isn't for you!", ephemeral=True)
                            return
                        
                        to_discard = sum(self.selected)
                        if to_discard > 3:
                            await btn_interaction.response.send_message("❌ You can only discard up to 3 cards!", ephemeral=True)
                            return
                        
                        suits = ["♠", "♥", "♦", "♣"]
                        values = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
                        
                        new_cards = []
                        for _ in range(to_discard):
                            new_cards.append((random.choice(values), random.choice(suits)))
                        
                        new_hand = []
                        new_card_idx = 0
                        for i, (v, s) in enumerate(self.hand):
                            if self.selected[i]:
                                new_hand.append(new_cards[new_card_idx])
                                new_card_idx += 1
                            else:
                                new_hand.append((v, s))
                        
                        game = self.cog.active_card_games.get(self.channel_id)
                        if game:
                            game["hands"][self.player_id] = new_hand
                        
                        final_cards = ", ".join([f"{v}{s}" for v, s in new_hand])
                        embed = discord.Embed(
                            title="🃠 Poker - Final Hand",
                            description=f"Your final hand: **{final_cards}**\n\nWaiting for other players...",
                            color=discord.Color.green()
                        )
                        await btn_interaction.response.send_message(embed=embed, ephemeral=True)
                        
                        game["players_ready"] = game.get("players_ready", []) + [self.player_id]
                        if len(game["players_ready"]) == len(game["players"]):
                            await self.cog.determine_poker_winner(self.channel_id)
                
                view = PokerDiscardView(self, interaction.channel.id, player_id, game_data["hands"][player_id])
                await user.send(embed=embed, view=view)
    
    async def determine_poker_winner(self, channel_id: int):
        """Determine the winner of Poker"""
        game_data = self.active_card_games.get(channel_id)
        if not game_data:
            return
        
        channel = self.bot.get_channel(channel_id)
        
        def hand_rank(hand):
            values = []
            suits = []
            for v, s in hand:
                val_map = {"J": 11, "Q": 12, "K": 13, "A": 14}
                val = val_map.get(v, int(v) if v.isdigit() else 0)
                values.append(val)
                suits.append(s)
            values.sort(reverse=True)
            
            is_flush = len(set(suits)) == 1
            is_straight = all(values[i] - values[i+1] == 1 for i in range(4))
            
            value_counts = {}
            for v in values:
                value_counts[v] = value_counts.get(v, 0) + 1
            counts = sorted(value_counts.values(), reverse=True)
            
            if is_straight and is_flush:
                return 8, values
            if 4 in counts:
                return 7, values
            if 3 in counts and 2 in counts:
                return 6, values
            if is_flush:
                return 5, values
            if is_straight:
                return 4, values
            if 3 in counts:
                return 3, values
            if counts.count(2) == 2:
                return 2, values
            if 2 in counts:
                return 1, values
            return 0, values
        
        best_rank = -1
        best_values = []
        winner = None
        
        for player_id in game_data["players"]:
            rank, values = hand_rank(game_data["hands"][player_id])
            if rank > best_rank or (rank == best_rank and values > best_values):
                best_rank = rank
                best_values = values
                winner = player_id
        
        rank_names = ["High Card", "One Pair", "Two Pair", "Three of a Kind", "Straight", "Flush", "Full House", "Four of a Kind", "Straight Flush"]
        
        if winner:
            winner_amount = game_data["total_pot"]
            self.award_winner(winner, game_data["guild_id"], winner_amount)
            
            if channel:
                winner_user = channel.guild.get_member(winner)
                await channel.send(
                    f"🎉 **POKER WINNER!** 🎉\n"
                    f"{winner_user.mention if winner_user else f'<@{winner}>'} wins **{winner_amount} XP** with a **{rank_names[best_rank]}**!\n"
                )
        
        for p_id in game_data["players"]:
            self.set_game_active(p_id, game_data["guild_id"], False)
        
        del self.active_card_games[channel_id]
    
    @commands.command(name='cards')
    async def cards_game(self, ctx):
        """Start a card game lobby (Higher/Lower, Blackjack, or Poker)"""
        if await self.check_duplicate(ctx):
            return
        
        if ctx.channel.id in self.active_card_games:
            await ctx.send("❌ A card game is already active in this channel! Please wait for it to finish.")
            return
        
        embed = discord.Embed(
            title="🎴 CARD GAME LOBBY 🎴",
            description="Creating game lobby...",
            color=discord.Color.blue()
        )
        
        view = self.CardGameLobbyView(self, ctx.author.id, ctx.channel.id)
        embed = view.get_embed(ctx.guild)
        await ctx.send(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(Games(bot))
