import discord
from discord.ext import commands, tasks
import logging
import os
import re
import random
import asyncio
import sys
import uuid
import socket
import json
import pickle
from datetime import datetime, timedelta
from dotenv import load_dotenv
from profanity_filter import ProfanityFilter
from jojo_references import get_random_jojo_quote, get_jojo_stand, JOJO_CHARACTERS
from scanner import scan_message
from keep_alive import keep_alive
from discord import ui, ButtonStyle
from music_player import MusicPlayer

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('discord')

# Track bot instance to prevent duplication
INSTANCE_ID = str(uuid.uuid4())
logger.info(f"Bot instance started with ID: {INSTANCE_ID}")

# Implement a lock file system to prevent multiple bot instances
BOT_LOCK_FILE = "bot.lock"

def check_lock_file():
    """Check if another bot instance is already running"""
    try:
        if os.path.exists(BOT_LOCK_FILE):
            # Check if the lock file is stale (older than 30 seconds)
            lock_age = time.time() - os.path.getmtime(BOT_LOCK_FILE)
            
            if lock_age < 30:  # If lock file is fresh (less than 30 seconds old)
                logger.warning(f"Another bot instance appears to be running (lock file age: {lock_age:.1f} seconds)")
                logger.warning("Only one bot instance should run at a time. Exiting...")
                print("ERROR: Another bot instance is already running!")
                print("Please stop all other instances before starting a new one.")
                sys.exit(1)
            else:
                logger.info(f"Found stale lock file (age: {lock_age:.1f} seconds). Replacing it.")
        
        # Create/update the lock file with current instance info
        with open(BOT_LOCK_FILE, "w") as f:
            f.write(f"{INSTANCE_ID},{time.time()}")
            
    except Exception as e:
        logger.error(f"Error checking lock file: {e}")
        # Continue anyway since this isn't critical

# Make sure we have the time module
import time

# Check for other running instances
check_lock_file()

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Initialize profanity filter
profanity_filter = ProfanityFilter()

# Setup bot intents
intents = discord.Intents.all()
bot = commands.Bot(
    command_prefix='!', 
    intents=intents,
    help_command=None,  # Disable default help command
    allowed_mentions=discord.AllowedMentions(
        users=False,  # Don't ping users by default
        everyone=False,  # Don't ping @everyone or @here
        roles=False,  # Don't ping roles
        replied_user=False  # Don't ping when replying
    )
)

# User warning system
# {user_id: {'count': int, 'last_warning': datetime}}

# Ticket system data structure
ticket_data = {
    "counter": 0,  # For generating ticket numbers
    "tickets": {},  # To store active tickets {channel_id: {"user_id": user_id, "claimed_by": claimed_by, "number": ticket_number, "created_at": timestamp}}
    "user_tickets": {}  # To track user's active tickets {user_id: channel_id}
}

# Add the ticket setups to the persistent views so that buttons work across bot restarts
def setup_persistent_views(bot):
    """Set up persistent views for buttons that need to work across bot restarts"""
    bot.add_view(VerifyButton())
    bot.add_view(TicketView())
    bot.add_view(TicketControlView())

# Load protected user IDs and channel restrictions from environment
PROTECTED_USER_ID = os.getenv("PROTECTED_USER_ID", "758954115765239820")  # Owner ID
BOT_USER_ID = "1370707409433264180"  # Bot ID
PROTECTED_USER_IDS = [PROTECTED_USER_ID, BOT_USER_ID]  # List of all protected users
RESTRICTED_CHANNEL_IDS_STR = os.getenv("RESTRICTED_CHANNEL_IDS", "1370710306619129976,1370805706223255654")
RESTRICTED_CHANNEL_IDS = [int(channel_id) for channel_id in RESTRICTED_CHANNEL_IDS_STR.split(",") if channel_id]
ADMIN_ONLY_CHANNEL_IDS = [1370805706223255654]  # Admin-only channels
ADMIN_ONLY_CATEGORY_IDS = [1370808706207322214]  # Admin-only categories
WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", "1370648731434745926"))

user_warnings = {}
# Timeout durations in minutes for each offense level
timeout_durations = [1, 2, 3, 4, 5]

# Role name for special commands
GAMER_ROLE = "Gamer"

# Role IDs for verification system
VERIFIED_ROLE_ID = 1370699624368574486  # Role name: "verified"
UNVERIFIED_ROLE_ID = 1370711895342059560  # Role name: "unverified"
WELCOME_CHANNEL_ID = 1370701226546565221  # Channel: verify

# Function to get role either by ID or name
def get_role_safe(guild, role_id, role_name):
    """Get a role by ID or name, safely handling None values"""
    role = None
    # Try by ID first
    if role_id is not None:
        role = guild.get_role(role_id)
    
    # If not found, try by name (exact match)
    if not role:
        role = discord.utils.get(guild.roles, name=role_name)
        
    # If still not found, try by lowercase name
    if not role:
        role = discord.utils.get(guild.roles, name=role_name.lower())
        
    # If still not found, try by uppercase name
    if not role:
        role = discord.utils.get(guild.roles, name=role_name.upper())
    
    # If still not found, try a case-insensitive search
    if not role:
        for guild_role in guild.roles:
            if guild_role.name.lower() == role_name.lower():
                role = guild_role
                break
        
    return role

# Anti-raid system
# Tracks recent actions to detect raid attempts
class AntiRaidSystem:
    def __init__(self):
        # Store recent joins: {server_id: [(member_id, join_time)]}
        self.recent_joins = {}
        
        # Store recent actions: {server_id: {action_type: [(user_id, timestamp)]}}
        self.recent_actions = {}
        
        # Raid detection thresholds
        self.join_threshold = 5  # Number of joins in short period to trigger alert
        self.join_timeframe = 10  # Timeframe in seconds to monitor joins
        
        # Message spam thresholds
        self.message_threshold = 8  # Messages from same user in timeframe
        self.message_timeframe = 5  # Timeframe in seconds
        
        # Channel creation/deletion thresholds
        self.channel_action_threshold = 3  # Number of channel creations/deletions
        self.channel_action_timeframe = 20  # In seconds
        
        # Role action thresholds
        self.role_action_threshold = 3  # Number of role creations/deletions
        self.role_action_timeframe = 30  # In seconds
        
        # Permissions threshold
        self.permission_changes_threshold = 5  # Number of permission changes
        self.permission_timeframe = 15  # In seconds
        
        # Ban/kick threshold
        self.ban_kick_threshold = 4  # Number of bans/kicks
        self.ban_kick_timeframe = 10  # In seconds
        
        # Raid status
        self.raid_mode = {}  # {server_id: bool}

    def add_join(self, server_id, member_id):
        """Add a member join event to tracking"""
        now = datetime.now()
        
        if server_id not in self.recent_joins:
            self.recent_joins[server_id] = []
        
        # Add the new join
        self.recent_joins[server_id].append((member_id, now))
        
        # Clean old entries
        self.recent_joins[server_id] = [
            (m_id, timestamp) for m_id, timestamp in self.recent_joins[server_id]
            if (now - timestamp).total_seconds() < self.join_timeframe
        ]
        
        # Check if raid threshold is met
        return len(self.recent_joins[server_id]) >= self.join_threshold
    
    def add_action(self, server_id, action_type, user_id):
        """Add an action event to tracking and check thresholds"""
        now = datetime.now()
        
        if server_id not in self.recent_actions:
            self.recent_actions[server_id] = {}
        
        if action_type not in self.recent_actions[server_id]:
            self.recent_actions[server_id][action_type] = []
        
        # Add the action
        self.recent_actions[server_id][action_type].append((user_id, now))
        
        # Clean old entries based on action type
        if action_type == 'message':
            timeframe = self.message_timeframe
            threshold = self.message_threshold
        elif action_type in ['channel_create', 'channel_delete']:
            timeframe = self.channel_action_timeframe
            threshold = self.channel_action_threshold
        elif action_type in ['role_create', 'role_delete', 'role_update']:
            timeframe = self.role_action_timeframe
            threshold = self.role_action_threshold
        elif action_type in ['ban', 'kick']:
            timeframe = self.ban_kick_timeframe
            threshold = self.ban_kick_threshold
        elif action_type == 'permission_update':
            timeframe = self.permission_timeframe
            threshold = self.permission_changes_threshold
        else:
            timeframe = 30  # Default timeframe
            threshold = 10  # Default threshold
        
        # Clean old entries
        self.recent_actions[server_id][action_type] = [
            (u_id, timestamp) for u_id, timestamp in self.recent_actions[server_id][action_type]
            if (now - timestamp).total_seconds() < timeframe
        ]
        
        # Check if user-specific threshold is met (for message spam)
        if action_type == 'message':
            user_actions = [
                u_id for u_id, _ in self.recent_actions[server_id][action_type]
                if u_id == user_id
            ]
            return len(user_actions) >= threshold
        
        # Check if general threshold is met
        return len(self.recent_actions[server_id][action_type]) >= threshold
    
    def enable_raid_mode(self, server_id):
        """Enable raid mode for a server"""
        self.raid_mode[server_id] = True
    
    def disable_raid_mode(self, server_id):
        """Disable raid mode for a server"""
        self.raid_mode[server_id] = False
    
    def is_raid_mode_enabled(self, server_id):
        """Check if raid mode is enabled for a server"""
        return self.raid_mode.get(server_id, False)

# Server Backup System
class ServerBackupSystem:
    def __init__(self):
        self.backup_folder = "server_backups"
        self.backup_index = {}
        self.max_backups = 10  # Maximum number of backups to keep
        
        # Create backup folder if it doesn't exist
        if not os.path.exists(self.backup_folder):
            os.makedirs(self.backup_folder)
            
        # Load backup index if exists
        index_path = os.path.join(self.backup_folder, "backup_index.json")
        if os.path.exists(index_path):
            try:
                with open(index_path, 'r') as f:
                    self.backup_index = json.load(f)
            except Exception as e:
                logger.error(f"Error loading backup index: {e}")
                self.backup_index = {}
                
    def _save_index(self):
        """Save the backup index to disk"""
        index_path = os.path.join(self.backup_folder, "backup_index.json")
        try:
            with open(index_path, 'w') as f:
                json.dump(self.backup_index, f)
        except Exception as e:
            logger.error(f"Error saving backup index: {e}")
    
    async def create_backup(self, guild):
        """Create a backup of a guild's configuration"""
        try:
            # Generate a unique backup ID
            backup_id = len(self.backup_index) + 1
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            
            # Collect server data
            backup_data = {
                "id": backup_id,
                "timestamp": timestamp,
                "guild_id": guild.id,
                "guild_name": guild.name,
                "channels": [],
                "roles": [],
                "emojis": [],
                "member_count": guild.member_count,
            }
            
            # Backup roles (excluding @everyone)
            for role in guild.roles:
                if role.name != "@everyone":
                    role_data = {
                        "id": role.id,
                        "name": role.name,
                        "color": role.color.value,
                        "permissions": role.permissions.value,
                        "position": role.position,
                        "mentionable": role.mentionable,
                        "hoist": role.hoist
                    }
                    backup_data["roles"].append(role_data)
            
            # Backup categories and channels
            categories = {c.id: {"id": c.id, "name": c.name, "position": c.position} for c in guild.categories}
            
            for channel in guild.channels:
                # Skip voice channels for now (can be added later)
                if isinstance(channel, discord.VoiceChannel):
                    continue
                
                channel_data = {
                    "id": channel.id,
                    "name": channel.name,
                    "type": str(channel.type),
                    "position": channel.position,
                    "category_id": channel.category_id,
                    "permissions": []
                }
                
                # Backup channel permissions
                for target, overwrite in channel.overwrites.items():
                    # Only backup role permissions, not user-specific ones
                    if isinstance(target, discord.Role):
                        perm_data = {
                            "id": target.id,
                            "target_type": "role",
                            "allow": overwrite.pair()[0].value,
                            "deny": overwrite.pair()[1].value
                        }
                        channel_data["permissions"].append(perm_data)
                
                backup_data["channels"].append(channel_data)
            
            # Save backup to file
            backup_path = os.path.join(self.backup_folder, f"{guild.id}_{backup_id}_{timestamp}.json")
            with open(backup_path, 'w') as f:
                json.dump(backup_data, f, indent=4)
                
            # Update index
            if str(guild.id) not in self.backup_index:
                self.backup_index[str(guild.id)] = []
                
            self.backup_index[str(guild.id)].append({
                "id": backup_id,
                "timestamp": timestamp,
                "path": backup_path
            })
            
            # Limit number of backups
            if len(self.backup_index[str(guild.id)]) > self.max_backups:
                # Remove oldest backup
                oldest = self.backup_index[str(guild.id)].pop(0)
                if os.path.exists(oldest["path"]):
                    os.remove(oldest["path"])
            
            # Save index
            self._save_index()
            
            return backup_id, timestamp
        except Exception as e:
            logger.error(f"Error creating backup: {e}")
            return None, None
    
    async def list_backups(self, guild_id):
        """List all backups for a guild"""
        guild_id_str = str(guild_id)
        if guild_id_str not in self.backup_index:
            return []
        
        return sorted(self.backup_index[guild_id_str], key=lambda x: x["id"])
    
    async def restore_backup(self, guild, backup_id):
        """Restore a backup to a guild"""
        guild_id_str = str(guild.id)
        
        if guild_id_str not in self.backup_index:
            return False, "No backups found for this server"
        
        # Find the backup with the given ID
        backup_info = None
        for backup in self.backup_index[guild_id_str]:
            if backup["id"] == backup_id:
                backup_info = backup
                break
                
        if not backup_info:
            return False, f"Backup #{backup_id} not found"
            
        # Load backup data
        try:
            with open(backup_info["path"], 'r') as f:
                backup_data = json.load(f)
                
            # Restore roles (careful not to duplicate)
            existing_roles = {role.name: role for role in guild.roles}
            for role_data in backup_data["roles"]:
                if role_data["name"] not in existing_roles:
                    # Create missing role
                    try:
                        await guild.create_role(
                            name=role_data["name"],
                            color=discord.Color(role_data["color"]),
                            permissions=discord.Permissions(role_data["permissions"]),
                            hoist=role_data["hoist"],
                            mentionable=role_data["mentionable"]
                        )
                    except Exception as e:
                        logger.error(f"Error restoring role {role_data['name']}: {e}")
            
            # Restore missing channels
            existing_channels = {channel.name: channel for channel in guild.channels}
            for channel_data in backup_data["channels"]:
                if channel_data["name"] not in existing_channels:
                    try:
                        # Create channel
                        if channel_data["type"] == "text":
                            await guild.create_text_channel(
                                name=channel_data["name"],
                                category=discord.utils.get(guild.categories, id=channel_data["category_id"])
                            )
                        elif channel_data["type"] == "category":
                            await guild.create_category(name=channel_data["name"])
                    except Exception as e:
                        logger.error(f"Error restoring channel {channel_data['name']}: {e}")
                        
            return True, f"Restored backup #{backup_id} from {backup_info['timestamp']}"
        except Exception as e:
            logger.error(f"Error restoring backup: {e}")
            return False, f"Error restoring backup: {str(e)}"

# Initialize server backup system
server_backup = ServerBackupSystem()

# Initialize anti-raid system
anti_raid = AntiRaidSystem()

# JoJo Game data structure
jojo_game = {
    "players": {},  # {user_id: {"part": int, "exp": int, "level": int, "stand": str, "items": [], "wins": int, "losses": int, "daily_streak": int, "last_daily": str, "last_game": str}}
    "parts": {
        1: {"name": "Phantom Blood", "exp_req": 0, "description": "The beginning of the Joestar legacy."},
        2: {"name": "Battle Tendency", "exp_req": 100, "description": "The battle against the Pillar Men."},
        3: {"name": "Stardust Crusaders", "exp_req": 250, "description": "The journey to defeat DIO."},
        4: {"name": "Diamond is Unbreakable", "exp_req": 500, "description": "The hunt for a serial killer in Morioh."},
        5: {"name": "Golden Wind", "exp_req": 1000, "description": "The rise within the Italian mafia."},
        6: {"name": "Stone Ocean", "exp_req": 2000, "description": "The fight to save a bloodline."},
        7: {"name": "Steel Ball Run", "exp_req": 4000, "description": "The race across America."},
        8: {"name": "JoJolion", "exp_req": 8000, "description": "The mystery of Morioh."}
    },
    "items": {
        "arrow": {"name": "Stand Arrow", "description": "Awakens or evolves your Stand", "price": 750},
        "hamon": {"name": "Hamon Training", "description": "Increases your EXP gain", "price": 500},
        "mask": {"name": "Stone Mask", "description": "Grants a chance for double rewards", "price": 1000},
        "requiem": {"name": "Requiem Arrow", "description": "Evolves your Stand to Requiem form", "price": 5000},
        "rokakaka": {"name": "Rokakaka Fruit", "description": "Resets your Stand for a new one", "price": 300},
        "spin": {"name": "Spin Technique", "description": "Chance to stun opponents in battles", "price": 1200},
        "pluck": {"name": "Pluck Sword", "description": "Deals extra damage in battles", "price": 900},
        "stand_disc": {"name": "Stand Disc", "description": "Temporarily use another player's Stand", "price": 2500}
    },
    "locations": [
        "Joestar Mansion", "Morioh", "Cairo", "Green Dolphin Prison", "Naples", 
        "Rome", "DIO's Mansion", "Polnareff Land", "Angelo Rock", "Savage Garden",
        "Passione Hideout", "Jotaro's Marine Lab", "Kame Yu Department Store"
    ],
    "enemies": [
        {"name": "Zombie Horde", "difficulty": 1, "exp": 25, "part": 1},
        {"name": "Pillar Man", "difficulty": 3, "exp": 75, "part": 2},
        {"name": "DIO", "difficulty": 5, "exp": 150, "part": 3},
        {"name": "Yoshikage Kira", "difficulty": 4, "exp": 120, "part": 4},
        {"name": "Diavolo", "difficulty": 5, "exp": 200, "part": 5},
        {"name": "Pucci", "difficulty": 5, "exp": 200, "part": 6},
        {"name": "Funny Valentine", "difficulty": 5, "exp": 250, "part": 7},
        {"name": "Wonder of U", "difficulty": 5, "exp": 250, "part": 8}
    ],
    "stand_tiers": ["E", "D", "C", "B", "A", "S"],
    "daily_bonus": 100,  # EXP for daily rewards
    "level_exp_req": [
        0, 100, 250, 450, 700, 1000, 1350, 1750, 2200, 2700,  # Levels 1-10
        3250, 3850, 4500, 5200, 6000, 6900, 7900, 9000, 10200, 11500  # Levels 11-20
    ],
    "rank_roles": {
        "Stand Novice": {"level": 1, "color": 0x7B9DB9},  # Light blue
        "Stand User": {"level": 5, "color": 0x4682B4},  # Steel blue
        "Stand Master": {"level": 10, "color": 0x29ABDF},  # Bright blue
        "Ripple Warrior": {"level": 15, "color": 0xFAD02C},  # Yellow
        "JoJo Champion": {"level": 20, "color": 0xE5C100}   # Gold
    },
    "seasonal_events": [
        {"name": "Stardust Crusade", "start_date": "2025-06-01", "end_date": "2025-06-30", 
         "description": "Join the journey to Egypt! Double EXP from all activities.", 
         "bonuses": {"exp_multiplier": 2.0, "special_enemy": "Vanilla Ice"}},
        
        {"name": "Morioh Summer", "start_date": "2025-08-01", "end_date": "2025-08-31", 
         "description": "Summer in Morioh! Special items in the shop and unique Stand abilities.", 
         "bonuses": {"shop_discount": 0.25, "special_item": "Bow and Arrow"}},
        
        {"name": "Golden Wind Autumn", "start_date": "2025-10-01", "end_date": "2025-10-31", 
         "description": "The leaves are falling in Italy. Team battles available and bonus rewards.", 
         "bonuses": {"daily_bonus": 200, "special_mode": "Team Battles"}}
    ],
    "games": [
        {"name": "stand_battle", "cooldown": 1800, "exp": 45, "description": "Battle with your Stand"},
        {"name": "hamon_training", "cooldown": 900, "exp": 20, "description": "Train your Hamon breathing"},
        {"name": "stand_arrow", "cooldown": 3600, "exp": 60, "description": "Test your luck with the Stand Arrow"},
        {"name": "steel_ball_run", "cooldown": 7200, "exp": 150, "description": "Compete in a race across America"},
        {"name": "bizarre_quiz", "cooldown": 1200, "exp": 30, "description": "Test your JoJo knowledge"}
    ]
}

# Verification system
UNVERIFIED_ROLE_ID = 1370701226546565221  # ID of the unverified role
VERIFIED_ROLE_ID = 1370699624368574486  # ID of the verified role
VERIFICATION_CHANNEL_ID = None  # This will be set dynamically
WELCOME_CHANNEL_ID = 1370648731434745926  # Channel for greeting new members

@bot.event
async def on_ready():
    """Event triggered when the bot is ready"""
    logger.info(f"Logged in as {bot.user.name} (ID: {bot.user.id})")
    logger.info(f"Connected to {len(bot.guilds)} guilds")
    
    # Set custom status 
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="Stand User Club | !help")
    )
    
    # Register persistent views for button interactions
    setup_persistent_views(bot)
    
    # Find verification channel for global reference
    global VERIFICATION_CHANNEL_ID
    for guild in bot.guilds:
        verification_channel = discord.utils.get(guild.text_channels, name="verification")
        if verification_channel:
            VERIFICATION_CHANNEL_ID = verification_channel.id
            logger.info(f"Verification channel found: {verification_channel.name} (ID: {verification_channel.id})")
            break
    
    # Print the welcome message to console
    print(f"『STAND』 activated: {bot.user.name} is online!")
    print("▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓")
    print(f"✅ Bot is ready! Connected to {len(bot.guilds)} servers.")
    print("Type !help for a list of commands.")
    print("▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓")
    
    # Automatically fix permissions for all servers - only check, don't modify
    logger.info("Setting up permissions for all servers...")
    
    for guild in bot.guilds:
        try:
            # Get the unverified role
            unverified_role = get_role_safe(guild, UNVERIFIED_ROLE_ID, "Unverified")
            
            # Log what we found
            if unverified_role:
                logger.info(f"Found unverified role in {guild.name}: {unverified_role.name} (ID: {unverified_role.id})")
            else:
                logger.warning(f"Could not find unverified role in {guild.name}")
                # Try to find via ID directly (debugging)
                role_id = UNVERIFIED_ROLE_ID
                direct_role = guild.get_role(role_id) if role_id else None
                if direct_role:
                    logger.info(f"Actually found role with direct ID lookup: {direct_role.name}")
                    unverified_role = direct_role
                else:
                    logger.warning(f"Could not find role with ID {role_id}")
                    
                    # Try to find by name directly
                    name_role = discord.utils.get(guild.roles, name="Unverified")
                    if name_role:
                        logger.info(f"Found role by name: {name_role.name} (ID: {name_role.id})")
                        unverified_role = name_role
                    else:
                        logger.warning("Could not find role with name 'Unverified'")
                        # List all roles for debugging
                        for role in guild.roles:
                            logger.info(f"Available role: {role.name} (ID: {role.id})")
                        continue
                
            # Find key channels
            verification_channel = None
            announcement_channel = None
            allowed_channels = []
            
            for channel in guild.text_channels:
                if channel.name == "verification":
                    verification_channel = channel
                    allowed_channels.append(channel)
                elif channel.name == "announcements":
                    announcement_channel = channel
                    allowed_channels.append(channel)
                elif channel.name in ["rules", "welcome", "read-me-first"]:
                    allowed_channels.append(channel)
                    
            # Block all channels for unverified users
            for channel in guild.channels:
                if isinstance(channel, discord.CategoryChannel):
                    await channel.set_permissions(unverified_role, read_messages=False)
                    continue
                
                if channel in allowed_channels:
                    # Allow access to special channels
                    can_send = channel == verification_channel
                    await channel.set_permissions(unverified_role, read_messages=True, send_messages=can_send)
                    logger.info(f"Allowed access to {channel.name} for unverified users")
                else:
                    # Block all other channels
                    await channel.set_permissions(unverified_role, read_messages=False, send_messages=False)
                    logger.info(f"Blocked {channel.name} for unverified users")
                    
            logger.info(f"✅ Permissions set up for {guild.name}")
        except Exception as e:
            logger.error(f"Failed to set up permissions for {guild.name}: {str(e)}")

@bot.event
async def on_member_join(member):
    """Send a welcome message to new members and assign unverified role"""
    # Check for raid conditions
    raid_detected = anti_raid.add_join(member.guild.id, member.id)
    
    if raid_detected and not anti_raid.is_raid_mode_enabled(member.guild.id):
        # Enable raid mode
        anti_raid.enable_raid_mode(member.guild.id)
        
        # Notify administrators
        try:
            # Try to notify in a mod-log channel first
            mod_log = discord.utils.get(member.guild.text_channels, name="mod-logs")
            if mod_log:
                raid_alert = discord.Embed(
                    title="🚨 RAID ALERT 🚨",
                    description=f"Suspicious number of members joining in a short time. Raid mode has been enabled.",
                    color=0xff0000
                )
                raid_alert.add_field(name="Action", value="New joins will be automatically monitored. Consider locking down the server.")
                await mod_log.send(embed=raid_alert)
            
            # Also notify server owner
            owner = member.guild.owner
            if owner:
                await owner.send(f"🚨 **RAID ALERT** 🚨\nSuspicious number of members joining {member.guild.name} in a short time. Raid mode has been enabled.")
        except Exception as e:
            logger.error(f"Failed to send raid alert: {e}")
    
    # Assign unverified role with improved handling
    try:
        unverified_role = get_role_safe(member.guild, UNVERIFIED_ROLE_ID, "unverified")
        if unverified_role:
            try:
                await member.add_roles(unverified_role)
                logger.info(f"Added unverified role to {member.name}")
            except Exception as e:
                logger.error(f"Failed to add unverified role to {member.name} with first method: {e}")
                
                # Try an alternative method
                try:
                    member_obj = await member.guild.fetch_member(member.id)
                    await member_obj.add_roles(unverified_role)
                    logger.info(f"Added unverified role with alternative method")
                except Exception as e2:
                    logger.error(f"Alternative method also failed: {e2}")
        else:
            logger.error(f"Could not find unverified role for user {member.name}, roles: {[r.name for r in member.guild.roles]}")
    except Exception as e:
        logger.error(f"Failed in unverified role assignment for {member.name}: {e}")
    
    # Get a random JoJo quote for the welcome message
    quote = get_random_jojo_quote()
    
    # Send a DM to the member
    try:
        embed = discord.Embed(
            title=f"Welcome to {member.guild.name}!",
            description=f"Yare Yare Daze... Welcome, {member.mention}!\n\n{quote}",
            color=0x8000ff
        )
        embed.add_field(
            name="Verification Required",
            value="Please go to the #verification channel and type `!verify` to access the rest of the server.",
            inline=False
        )
        embed.set_footer(text="Use !help to see available commands once verified")
        
        await member.send(embed=embed)
        
        # Send message to verification channel
        verification_channel = member.guild.get_channel(VERIFICATION_CHANNEL_ID)
        if verification_channel:
            await verification_channel.send(
                f"ゴゴゴゴ A new stand user, {member.mention}, has appeared! Type `!verify` to verify yourself. ゴゴゴゴ",
                delete_after=300  # Delete after 5 minutes
            )
        
        # Send welcome message with GIF to the welcome channel
        welcome_channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
        if welcome_channel:
            john_pork_gif = "https://tenor.com/en-GB/view/john-pork-gif-12990810711391968928"
            welcome_embed = discord.Embed(
                title="NEW ARRIVAL!",
                description=f"Welcome {member.mention} to the server! We hope you enjoy your stay.",
                color=0xF0BE40
            )
            welcome_embed.set_image(url=john_pork_gif)
            await welcome_channel.send(embed=welcome_embed)
            logger.info(f"Sent welcome message to welcome channel for {member.name}")
    
    except discord.Forbidden:
        logger.warning(f"Could not send DM to {member.name}")
    except Exception as e:
        logger.error(f"Error sending welcome message: {e}")

# Use a more robust system to track processed commands
# This includes a timestamp to automatically expire old entries
processed_commands = {}
COMMAND_EXPIRATION = 60  # Commands expire after 60 seconds

# Create a lock file to ensure we're not competing with other instances
INSTANCE_ID = random.randint(1, 10000)
logger.info(f"Bot instance started with ID: {INSTANCE_ID}")

@bot.event
async def on_message(message):
    """Handle message events for profanity filtering and command processing"""
    # Ignore messages from the bot itself
    if message.author == bot.user:
        return
    
    # Check if message contains a ping to any protected user
    for user_id in PROTECTED_USER_IDS:
        if f"<@{user_id}>" in message.content or f"<@!{user_id}>" in message.content:
            # Send warning and delete the message
            try:
                # Determine the warning message based on which protected user was pinged
                if user_id == BOT_USER_ID:
                    warning_text = "Please don't ping the bot. If you need help, use the !help command."
                else:
                    warning_text = "Please don't ping this user. They are busy and will respond when available."
                
                # Delete the message first
                await message.delete()
                
                # Send ephemeral (private) warning to the user who pinged
                try:
                    # Try to use a slash command response if possible (most ephemeral)
                    await message.author.send(f"⚠️ **Warning**: {warning_text}")
                except discord.Forbidden:
                    # If DMs are disabled, send a temporary message in the channel
                    warning_msg = await message.channel.send(f"{message.author.mention}, {warning_text}")
                    # Delete warning message after 5 seconds
                    await asyncio.sleep(5)
                    await warning_msg.delete()
                return
            except Exception as e:
                logger.error(f"Error handling protected user ping: {e}")
    
    # Check if message is in a restricted channel (not allowed to chat)
    if message.guild and message.channel.id in RESTRICTED_CHANNEL_IDS:
        # If it's not a command (regular chat message)
        if not message.content.startswith('!'):
            try:
                await message.delete()
                warning_msg = await message.channel.send(f"{message.author.mention}, chatting is not allowed in this channel.")
                await asyncio.sleep(3)
                await warning_msg.delete()
                return
            except Exception as e:
                logger.error(f"Error handling message in restricted channel: {e}")
    
    # Check if message is in an admin-only channel
    if message.guild and message.channel.id in ADMIN_ONLY_CHANNEL_IDS:
        # Check if user is not an admin
        is_admin = message.author.guild_permissions.administrator if hasattr(message.author, 'guild_permissions') else False
        
        if not is_admin:
            try:
                await message.delete()
                # Send a DM to the user
                try:
                    await message.author.send(f"⚠️ **Warning**: You cannot post in the admin-only channel. This channel is restricted to server administrators.")
                except discord.Forbidden:
                    # If DMs are disabled, send a temporary message in the channel
                    warning_msg = await message.channel.send(f"{message.author.mention}, this is an admin-only channel.")
                    await asyncio.sleep(5)
                    await warning_msg.delete()
                return
            except Exception as e:
                logger.error(f"Error handling admin-only channel message: {e}")
    
    # Check if message is in an admin-only category
    if message.guild and message.channel.category_id in ADMIN_ONLY_CATEGORY_IDS:
        # Check if user is not an admin
        is_admin = message.author.guild_permissions.administrator if hasattr(message.author, 'guild_permissions') else False
        
        if not is_admin:
            try:
                await message.delete()
                # Send a DM to the user
                try:
                    await message.author.send(f"⚠️ **Warning**: You cannot post in this ticket category. Only server administrators can access this area.")
                except discord.Forbidden:
                    # If DMs are disabled, send a temporary message in the channel
                    warning_msg = await message.channel.send(f"{message.author.mention}, this category is restricted to administrators.")
                    await asyncio.sleep(5)
                    await warning_msg.delete()
                return
            except Exception as e:
                logger.error(f"Error handling admin-only category message: {e}")
    
    # Allow welcome channel but only for greeting, no other messages
    if message.guild and message.channel.id == WELCOME_CHANNEL_ID:
        # Check if message contains welcome-related keywords
        welcome_keywords = ["welcome", "greet", "hello", "hi", "hey", "join", "glad", "happy"]
        is_welcome_message = any(keyword in message.content.lower() for keyword in welcome_keywords)
        
        # If not a welcome message or command, delete it
        if not is_welcome_message and not message.content.startswith('!'):
            try:
                await message.delete()
                warning_msg = await message.channel.send(f"{message.author.mention}, only welcome messages are allowed in this channel.")
                await asyncio.sleep(3)
                await warning_msg.delete()
                return
            except Exception as e:
                logger.error(f"Error handling non-welcome message: {e}")
    
    # Check if this is a command
    if message.content.startswith('!') and len(message.content) > 1:
        # Create a unique identifier for this message
        message_id = f"{message.id}_{message.channel.id}_{message.author.id}"
        
        # Check if we've seen this command already
        current_time = datetime.now().timestamp()
        if message_id in processed_commands:
            stored_time = processed_commands[message_id]
            # Only process if it's been more than 60 seconds (in case of restart)
            if current_time - stored_time < COMMAND_EXPIRATION:
                logger.info(f"Skipping duplicate command: {message.content}")
                return
                
        # Clean up expired commands
        expired_keys = [k for k, v in processed_commands.items() 
                        if current_time - v > COMMAND_EXPIRATION]
        for k in expired_keys:
            processed_commands.pop(k, None)
            
        # Add to processed commands with current timestamp
        processed_commands[message_id] = current_time
        logger.info(f"Processing command: {message.content} (Instance {INSTANCE_ID})")
    
    if message.guild:
        # Track message for anti-spam/raid detection (only in guilds, not DMs)
        spam_detected = anti_raid.add_action(message.guild.id, 'message', message.author.id)
        
        # If spam detected and user is not an admin
        if spam_detected and not message.author.guild_permissions.administrator:
            try:
                # Timeout the user
                timeout_duration = 5  # minutes
                timeout_until = datetime.now() + timedelta(minutes=timeout_duration)
                await message.author.timeout(timeout_until, reason="Message spam detected")
                
                # Delete some of their recent messages
                messages_to_delete = []
                async for msg in message.channel.history(limit=30):
                    if msg.author.id == message.author.id:
                        messages_to_delete.append(msg)
                        if len(messages_to_delete) >= 10:  # Delete up to 10 recent messages
                            break
                
                if messages_to_delete:
                    await message.channel.delete_messages(messages_to_delete)
                
                # Notify about spam
                embed = discord.Embed(
                    title="⚠️ Anti-Spam Protection",
                    description=f"{message.author.mention} has been temporarily muted for message spam.",
                    color=0xff9900
                )
                embed.add_field(name="Duration", value=f"{timeout_duration} minutes")
                embed.add_field(name="Action", value="Some recent messages have been deleted.")
                spam_msg = await message.channel.send(embed=embed)
                await asyncio.sleep(10)
                await spam_msg.delete()
                
                # Log this action to mod logs
                mod_log = discord.utils.get(message.guild.text_channels, name="mod-logs")
                if mod_log:
                    log_embed = discord.Embed(
                        title="🛡️ Anti-Spam Action",
                        description=f"User {message.author.mention} was automatically muted for message spam.",
                        color=0xff9900
                    )
                    await mod_log.send(embed=log_embed)
                    
                return  # Skip further processing
            except Exception as e:
                logger.error(f"Error handling message spam: {e}")
    
    # Check for profanity and malicious links
    if message.content and not message.author.bot and message.guild:
        # Check for malicious links (scam, porn, etc.)
        malicious_link_patterns = [
            r'porn', r'xxx', r'sex', r'adult', r'nude', r'naked',  # Porn links
            r'free.?nitro', r'discord.?nitro', r'steam.?gift',      # Common Discord scams
            r'giveaway', r'free.?robux', r'free.?vbucks',           # Common gaming scams
            r'account.?steal', r'password.?hack', r'login.?info',   # Phishing indicators
            r'viruslink', r'malware', r'trojan', r'suspicious.?site' # Explicit malware
        ]
        
        for pattern in malicious_link_patterns:
            if re.search(pattern, message.content.lower()):
                # Handle as a more severe profanity violation (auto timeout)
                await handle_malicious_content(message)
                return
        
        # Check if message contains profanity
        if profanity_filter.contains_profanity(message.content):
            await handle_profanity(message)
            return
    
    # Process commands
    await bot.process_commands(message)

async def handle_malicious_content(message):
    """Handle messages containing malicious links or content"""
    user_id = message.author.id
    current_time = datetime.now()
    
    # Initialize user in warning system if not exists
    if user_id not in user_warnings:
        user_warnings[user_id] = {'count': 0, 'last_warning': None}
    
    # Set warning count to at least 3 for malicious content (harsher punishment)
    user_warnings[user_id]['count'] = max(3, user_warnings[user_id]['count'] + 2)
    user_warnings[user_id]['last_warning'] = current_time
    
    # Get a higher timeout for malicious content (min 5 minutes)
    warning_level = min(user_warnings[user_id]['count'] - 1, len(timeout_durations) - 1)
    timeout_minutes = max(5, timeout_durations[warning_level])
    
    try:
        # Delete the message immediately
        await message.delete()
        
        # Get a random JoJo character for the warning
        jojo_character = random.choice(JOJO_CHARACTERS)
        
        # Create warning embed with more severe language
        embed = discord.Embed(
            title=f"🚫 Malicious Content Detected - Strike {user_warnings[user_id]['count']}",
            description=f"{jojo_character} says: \"STOP RIGHT THERE! Posting malicious links or content is strictly forbidden, {message.author.mention}!\"",
            color=0xff0000
        )
        
        # Calculate timeout duration - longer for malicious content
        timeout_until = current_time + timedelta(minutes=timeout_minutes)
        
        # Apply timeout to user
        try:
            await message.author.timeout(timeout_until, reason="Malicious content/link violation")
            embed.add_field(
                name="Timeout Applied",
                value=f"You have been timed out for {timeout_minutes} minutes for posting potentially harmful content."
            )
            embed.add_field(
                name="Warning",
                value="Repeated violations may result in a permanent ban from the server.",
                inline=False
            )
        except discord.Forbidden:
            embed.add_field(
                name="Timeout Failed",
                value="Could not apply timeout. The bot may not have the required permissions."
            )
            logger.error(f"Failed to timeout user {message.author.name} - insufficient permissions")
        except Exception as e:
            logger.error(f"Error applying timeout: {e}")
        
        # Send warning message
        warning_message = await message.channel.send(embed=embed)
        
        # Notify moderators
        try:
            mod_channel = discord.utils.get(message.guild.text_channels, name="mod-logs")
            if mod_channel:
                mod_embed = discord.Embed(
                    title="🚨 Malicious Content Alert",
                    description=f"User {message.author.mention} posted potentially harmful content.",
                    color=0xff0000
                )
                mod_embed.add_field(name="Action Taken", value=f"Message deleted and user timed out for {timeout_minutes} minutes.")
                await mod_channel.send(embed=mod_embed)
        except Exception as e:
            logger.error(f"Failed to notify moderators: {e}")
        
        # Delete the warning after 15 seconds (longer than regular profanity)
        await asyncio.sleep(15)
        await warning_message.delete()
        
    except discord.Forbidden:
        logger.error(f"Failed to delete message from {message.author.name} - insufficient permissions")
    except Exception as e:
        logger.error(f"Error handling malicious content: {e}")

async def handle_profanity(message):
    """Handle messages containing profanity"""
    user_id = message.author.id
    current_time = datetime.now()
    
    # Initialize user in warning system if not exists
    if user_id not in user_warnings:
        user_warnings[user_id] = {'count': 0, 'last_warning': None}
    
    # Reset warning count if last warning was more than 24 hours ago
    if (user_warnings[user_id]['last_warning'] and 
        (current_time - user_warnings[user_id]['last_warning']).total_seconds() > 86400):
        user_warnings[user_id]['count'] = 0
    
    # Increment warning count
    user_warnings[user_id]['count'] += 1
    user_warnings[user_id]['last_warning'] = current_time
    
    # Determine timeout duration based on warning count
    warning_level = min(user_warnings[user_id]['count'] - 1, len(timeout_durations) - 1)
    timeout_minutes = timeout_durations[warning_level]
    
    try:
        # Delete the message
        await message.delete()
        
        # Get a random JoJo character to "deliver" the warning
        jojo_character = random.choice(JOJO_CHARACTERS)
        
        # Create warning embed
        embed = discord.Embed(
            title=f"⚠️ Language Warning - Strike {user_warnings[user_id]['count']}",
            description=f"{jojo_character} says: \"Watch your language, {message.author.mention}!\"",
            color=0xff0000
        )
        
        # Apply timeout if this isn't the first warning
        if user_warnings[user_id]['count'] > 1:
            # Calculate timeout duration
            timeout_until = current_time + timedelta(minutes=timeout_minutes)
            
            # Apply timeout to user
            try:
                await message.author.timeout(timeout_until, reason="Profanity filter violation")
                embed.add_field(
                    name="Timeout Applied",
                    value=f"You have been timed out for {timeout_minutes} minutes."
                )
            except discord.Forbidden:
                embed.add_field(
                    name="Timeout Failed",
                    value="Could not apply timeout. The bot may not have the required permissions."
                )
                logger.error(f"Failed to timeout user {message.author.name} - insufficient permissions")
            except Exception as e:
                logger.error(f"Error applying timeout: {e}")
        
        # Send warning message
        warning_message = await message.channel.send(embed=embed)
        # Delete the warning after 10 seconds
        await asyncio.sleep(10)
        await warning_message.delete()
        
    except discord.Forbidden:
        logger.error(f"Failed to delete message from {message.author.name} - insufficient permissions")
    except Exception as e:
        logger.error(f"Error handling profanity: {e}")

# Moderation Commands

@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    """Kick a member from the server"""
    try:
        jojo_quote = get_random_jojo_quote()
        await member.kick(reason=reason)
        
        embed = discord.Embed(
            title="⚡ Member Kicked",
            description=f"{member.mention} has been kicked from the server.",
            color=0xffcc00
        )
        embed.add_field(name="Reason", value=reason)
        embed.add_field(name="JoJo says", value=jojo_quote, inline=False)
        
        await ctx.send(embed=embed)
        logger.info(f"Kicked user {member.name} (ID: {member.id}) for reason: {reason}")
    
    except discord.Forbidden:
        await ctx.send("I don't have permission to kick members.")
    except Exception as e:
        await ctx.send(f"An error occurred: {e}")
        logger.error(f"Error kicking member: {e}")

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="No reason provided"):
    """Ban a member from the server"""
    try:
        jojo_quote = get_random_jojo_quote()
        await member.ban(reason=reason, delete_message_days=1)
        
        embed = discord.Embed(
            title="🔨 Member Banned",
            description=f"{member.mention} has been banished to the Shadow Realm!",
            color=0xff0000
        )
        embed.add_field(name="Reason", value=reason)
        embed.add_field(name="JoJo says", value=jojo_quote, inline=False)
        
        await ctx.send(embed=embed)
        logger.info(f"Banned user {member.name} (ID: {member.id}) for reason: {reason}")
    
    except discord.Forbidden:
        await ctx.send("I don't have permission to ban members.")
    except Exception as e:
        await ctx.send(f"An error occurred: {e}")
        logger.error(f"Error banning member: {e}")

@bot.command(name="mute")
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, duration: int = 5, *, reason="No reason provided"):
    """Timeout a member for a specified duration (in minutes)"""
    if duration < 1:
        await ctx.send("Duration must be at least 1 minute.")
        return
    
    if duration > 60*24*7:  # Discord maximum timeout is 28 days, but let's cap at 1 week
        await ctx.send("Duration cannot exceed 1 week (10080 minutes).")
        return
    
    try:
        # Apply timeout
        timeout_until = datetime.now() + timedelta(minutes=duration)
        await member.timeout(timeout_until, reason=reason)
        
        # Get JoJo quote
        jojo_quote = get_random_jojo_quote()
        
        # Create embed
        embed = discord.Embed(
            title="🔇 Member Muted",
            description=f"{member.mention} has been muted for {duration} minutes.",
            color=0xff9900
        )
        embed.add_field(name="Reason", value=reason)
        embed.add_field(name="Duration", value=f"{duration} minutes")
        embed.add_field(name="JoJo says", value=jojo_quote, inline=False)
        
        await ctx.send(embed=embed)
        logger.info(f"Muted user {member.name} (ID: {member.id}) for {duration} minutes, reason: {reason}")
    
    except discord.Forbidden:
        await ctx.send("I don't have permission to timeout members.")
    except Exception as e:
        await ctx.send(f"An error occurred: {e}")
        logger.error(f"Error muting member: {e}")

@bot.command(name="unmute")
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member, *, reason="No reason provided"):
    """Remove timeout from a member"""
    try:
        # Remove timeout
        await member.timeout(None, reason=reason)
        
        # Get JoJo quote
        jojo_quote = get_random_jojo_quote()
        
        # Create embed
        embed = discord.Embed(
            title="🔊 Member Unmuted",
            description=f"{member.mention} has been unmuted.",
            color=0x00ff00
        )
        embed.add_field(name="Reason", value=reason)
        embed.add_field(name="JoJo says", value=jojo_quote, inline=False)
        
        await ctx.send(embed=embed)
        logger.info(f"Unmuted user {member.name} (ID: {member.id}), reason: {reason}")
    
    except discord.Forbidden:
        await ctx.send("I don't have permission to manage timeouts.")
    except Exception as e:
        await ctx.send(f"An error occurred: {e}")
        logger.error(f"Error unmuting member: {e}")

@bot.command(name="move")
@commands.has_permissions(move_members=True)
async def move(ctx, member: discord.Member, *, channel: discord.VoiceChannel):
    """Move a member to a different voice channel"""
    try:
        if member.voice is None:
            await ctx.send(f"{member.mention} is not in a voice channel.")
            return
        
        await member.move_to(channel)
        
        # Get JoJo quote
        jojo_quote = get_random_jojo_quote()
        
        # Create embed
        embed = discord.Embed(
            title="↪️ Member Moved",
            description=f"{member.mention} has been moved to {channel.mention}.",
            color=0x00ffff
        )
        embed.add_field(name="JoJo says", value=jojo_quote, inline=False)
        
        await ctx.send(embed=embed)
        logger.info(f"Moved user {member.name} (ID: {member.id}) to channel {channel.name}")
    
    except discord.Forbidden:
        await ctx.send("I don't have permission to move members.")
    except Exception as e:
        await ctx.send(f"An error occurred: {e}")
        logger.error(f"Error moving member: {e}")

@bot.command(name="clear", aliases=["purge"])
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    """Clear a specified amount of messages"""
    if amount < 1:
        await ctx.send("Please specify a positive number of messages to delete.")
        return
    
    if amount > 100:
        await ctx.send("Cannot delete more than 100 messages at once.")
        return
    
    try:
        deleted = await ctx.channel.purge(limit=amount + 1)  # +1 to include command
        
        # Send temporary confirmation
        msg = await ctx.send(f"🧹 Deleted {len(deleted) - 1} messages.")
        await asyncio.sleep(3)
        await msg.delete()
        
        logger.info(f"Cleared {len(deleted) - 1} messages in {ctx.channel.name}")
    
    except discord.Forbidden:
        await ctx.send("I don't have permission to delete messages.")
    except discord.HTTPException as e:
        await ctx.send(f"Failed to delete messages: {e}")
        logger.error(f"Error clearing messages: {e}")

@bot.command(name="scan")
async def scan(ctx, *, text=None):
    """Scan and analyze text using a JoJo-themed response"""
    if text is None:
        # Check if replying to a message
        if ctx.message.reference and ctx.message.reference.resolved:
            text = ctx.message.reference.resolved.content
        else:
            await ctx.send("Please provide text to scan or reply to a message.")
            return
    
    if not text:
        await ctx.send("There's no text to scan.")
        return
    
    # Show typing indicator
    async with ctx.typing():
        # Process might take a moment
        await asyncio.sleep(1.5)
        
        # Get scan results
        result = scan_message(text)
        
        # Create stand ability based on text
        stand = get_jojo_stand(text)
        
        # Create response embed
        embed = discord.Embed(
            title="『STAND ANALYSIS』",
            description=f"I've analyzed this message with my Stand power!",
            color=0x9966cc
        )
        
        embed.add_field(name="Text", value=text[:1024] if len(text) <= 1024 else f"{text[:1021]}...", inline=False)
        embed.add_field(name="Analysis", value=result, inline=False)
        embed.add_field(name="Stand Ability", value=stand, inline=False)
        
        await ctx.send(embed=embed)

# Fun Commands

@bot.command(name="hello")
async def hello(ctx):
    """Greet the user with a JoJo reference"""
    quotes = [
        f"Yare Yare Daze... Hello there, {ctx.author.mention}.",
        f"OH MY GOD! It's {ctx.author.mention}!",
        f"NIIIIICE to meet you, {ctx.author.mention}!",
        f"Hello, {ctx.author.mention}. Your next line is 'How did you know what I was going to say?!'",
        f"Ora Ora Ora! {ctx.author.mention} has appeared!"
    ]
    
    await ctx.send(random.choice(quotes))

@bot.command(name="assign")
async def assign(ctx):
    """Assign the Gamer role to the user"""
    role = discord.utils.get(ctx.guild.roles, name=GAMER_ROLE)
    if role:
        if role in ctx.author.roles:
            await ctx.send(f"You already have the {GAMER_ROLE} role, {ctx.author.mention}!")
            return
            
        await ctx.author.add_roles(role)
        
        quotes = [
            f"Your Stand, 「{GAMER_ROLE}」, has awakened within you, {ctx.author.mention}!",
            f"You've gained the power of 「{GAMER_ROLE}」, {ctx.author.mention}!",
            f"The {GAMER_ROLE} role has been passed down to you, {ctx.author.mention}!"
        ]
        
        await ctx.send(random.choice(quotes))
    else:
        await ctx.send("Role doesn't exist. The administrator needs to create it first.")

@bot.command(name="remove")
async def remove(ctx):
    """Remove the Gamer role from the user"""
    role = discord.utils.get(ctx.guild.roles, name=GAMER_ROLE)
    if role:
        if role not in ctx.author.roles:
            await ctx.send(f"You don't have the {GAMER_ROLE} role, {ctx.author.mention}!")
            return
            
        await ctx.author.remove_roles(role)
        
        quotes = [
            f"Your Stand, 「{GAMER_ROLE}」, has left you, {ctx.author.mention}.",
            f"You've lost the power of 「{GAMER_ROLE}」, {ctx.author.mention}.",
            f"The {GAMER_ROLE} role has been taken from you, {ctx.author.mention}."
        ]
        
        await ctx.send(random.choice(quotes))
    else:
        await ctx.send("Role doesn't exist.")

@bot.command(name="dm")
async def dm(ctx, member: discord.Member = None, *, msg=None):
    """Send a DM to a user
    Usage: !dm @user [message]
    If no user is mentioned, sends DM to yourself
    """
    # Delete the original command message for privacy
    try:
        await ctx.message.delete()
    except:
        pass
        
    # If no member is mentioned, default to the command author
    if member is None:
        member = ctx.author
    
    if msg:
        message = f"Message from {ctx.author.name}: {msg}\n\n{get_random_jojo_quote()}"
    else:
        message = f"Message from {ctx.author.name}: {get_random_jojo_quote()}"
    
    # Private confirmation for sender
    confirmation_embed = discord.Embed(
        title="DM Message",
        description=f"Sending a private message to {member.mention}",
        color=0x9966cc
    )
    confirmation_embed.add_field(name="Message Content", value=message[:1000], inline=False)
    
    try:
        await member.send(message)
        confirmation_embed.set_footer(text="✅ Message delivered successfully!")
        
        # Send private confirmation to command author
        try:
            if member != ctx.author:  # Don't send confirmation if DM'ing yourself
                await ctx.author.send(embed=confirmation_embed)
        except discord.Forbidden:
            # If can't DM the author, send an ephemeral message in the channel
            confirmation_msg = await ctx.send(f"✅ DM sent to {member.mention}!", delete_after=5)
    except discord.Forbidden:
        confirmation_embed.set_footer(text="❌ Failed to deliver message - user has DMs disabled")
        confirmation_embed.color = 0xff0000
        try:
            await ctx.author.send(embed=confirmation_embed)
        except:
            # If can't DM the author, send an ephemeral message in the channel
            await ctx.send(f"❌ I couldn't send a DM to {member.mention}. They may have DMs disabled.", delete_after=5)
    except Exception as e:
        try:
            await ctx.author.send(f"Error sending DM: {e}")
        except:
            await ctx.send(f"Error sending DM: {e}", delete_after=5)

@bot.command(name="massdm")
@commands.has_permissions(administrator=True)
async def mass_dm(ctx, target=None, *, message=None):
    """Send a DM to multiple users (Admin only)
    Usage: !massdm <target> <message>
    
    Targets can be:
    - @role - Sends to all members with that role
    - everyone - Sends to all server members
    - online - Sends to all online members
    - A specific @user mention - Sends to just that user
    """
    # Delete the command message for privacy
    try:
        await ctx.message.delete()
    except:
        pass
    
    if not message:
        await ctx.send("❌ You need to provide a message to send. Usage: `!massdm <target> <message>`", delete_after=10)
        return
    
    # Create a status message
    status = await ctx.send("🔄 Processing mass DM command...")
    
    # Parse the target
    members_to_dm = []
    
    if not target:
        await status.edit(content="❌ You need to specify a target. Usage: `!massdm <target> <message>`")
        return
    
    # Check for mentions
    if ctx.message.mentions:
        # DM to mentioned user(s)
        members_to_dm = ctx.message.mentions
        target_desc = f"{len(members_to_dm)} mentioned users"
    
    # Check for 'everyone'
    elif target.lower() == "everyone":
        members_to_dm = ctx.guild.members
        target_desc = "all server members"
    
    # Check for 'online'
    elif target.lower() == "online":
        members_to_dm = [m for m in ctx.guild.members if m.status != discord.Status.offline]
        target_desc = "all online members"
    
    # Check for role mentions
    elif ctx.message.role_mentions:
        role = ctx.message.role_mentions[0]
        members_to_dm = [m for m in ctx.guild.members if role in m.roles]
        target_desc = f"all members with the {role.name} role"
    
    # If target is a role name (without mention)
    else:
        # Try to find role by name
        role = discord.utils.get(ctx.guild.roles, name=target)
        if role:
            members_to_dm = [m for m in ctx.guild.members if role in m.roles]
            target_desc = f"all members with the {role.name} role"
        else:
            await status.edit(content=f"❌ Couldn't find target '{target}'. Please use a valid user mention, role mention, 'everyone', or 'online'.")
            return
    
    # Add JoJo-themed header to the message
    jojo_message = f"**Message from {ctx.author.display_name}**:\n\n{message}\n\n-----\n*This message was sent via the JoJo Discord Bot.*"
    
    # Update status
    await status.edit(content=f"🔄 Sending DM to {target_desc} ({len(members_to_dm)} users)...")
    
    # Count successful and failed DMs
    success_count = 0
    fail_count = 0
    
    # Send the messages
    for member in members_to_dm:
        # Don't DM the bot itself or the sender
        if member.bot or member.id == ctx.author.id:
            continue
            
        try:
            await member.send(jojo_message)
            success_count += 1
            # Add small delay to avoid rate limits
            await asyncio.sleep(0.5)
        except Exception as e:
            fail_count += 1
            logger.error(f"Failed to send DM to {member.name}: {e}")
    
    # Final report
    embed = discord.Embed(
        title="📨 Mass DM Report",
        description=f"Message sent to {target_desc}",
        color=0x00ff00 if fail_count == 0 else 0xffaa00
    )
    
    embed.add_field(name="✅ Successful", value=str(success_count), inline=True)
    embed.add_field(name="❌ Failed", value=str(fail_count), inline=True)
    
    await status.edit(content=None, embed=embed)

@bot.command(name="poll")
async def poll(ctx, *, question):
    """Create a poll with reactions"""
    embed = discord.Embed(
        title="📊 New Poll",
        description=question,
        color=0x7289da
    )
    embed.set_footer(text=f"Poll created by {ctx.author.display_name}")
    
    poll_message = await ctx.send(embed=embed)
    await poll_message.add_reaction("👍")
    await poll_message.add_reaction("👎")
    await poll_message.add_reaction("🤷")

@bot.command(name="secret")
@commands.has_role(GAMER_ROLE)
async def secret(ctx):
    """Secret command for users with the Gamer role"""
    embed = discord.Embed(
        title="🌟 Secret JoJo Club",
        description="Welcome to the secret club, fellow Stand user!",
        color=0xffd700
    )
    embed.add_field(
        name="Special Message",
        value="You have accessed the secret command! Your Stand power is truly impressive.",
        inline=False
    )
    embed.add_field(
        name="JoJo Quote",
        value=get_random_jojo_quote(),
        inline=False
    )
    
    await ctx.send(embed=embed)

@secret.error
async def secret_error(ctx, error):
    """Error handler for the secret command"""
    if isinstance(error, commands.MissingRole):
        await ctx.send(f"You need the `{GAMER_ROLE}` role to use this command. Try using `!assign` to get it!")

@bot.command(name="jojo")
async def jojo(ctx):
    """Get a random JoJo quote"""
    quote = get_random_jojo_quote()
    
    embed = discord.Embed(
        title="JoJo Quote",
        description=quote,
        color=0x9966cc
    )
    
    await ctx.send(embed=embed)

@bot.command(name="stand")
async def stand(ctx, *, name=None):
    """Generate a Stand ability for a name"""
    if name is None:
        name = ctx.author.display_name
    
    stand_ability = get_jojo_stand(name)
    
    embed = discord.Embed(
        title=f"Stand Ability for {name}",
        description=stand_ability,
        color=0xffd700
    )
    
    await ctx.send(embed=embed)

# JoJo Game commands

@bot.command(name="profile")
async def profile(ctx):
    """Display your JoJo game profile"""
    user_id = str(ctx.author.id)
    
    # Check if user exists in the game
    if user_id not in jojo_game["players"]:
        # Create new player
        jojo_game["players"][user_id] = {
            "part": 1,
            "exp": 0,
            "stand": get_jojo_stand(ctx.author.display_name).split("\n")[0].strip("『』")
        }
    
    player = jojo_game["players"][user_id]
    part_info = jojo_game["parts"][player["part"]]
    
    # Calculate progress to next part
    next_part = player["part"] + 1
    progress = ""
    if next_part in jojo_game["parts"]:
        next_part_req = jojo_game["parts"][next_part]["exp_req"]
        current_exp = player["exp"]
        progress = f"{current_exp}/{next_part_req} EXP to Part {next_part}"
    else:
        progress = "Maximum part reached!"
    
    # Create embed
    embed = discord.Embed(
        title=f"{ctx.author.display_name}'s Bizarre Adventure",
        description=f"Your journey through the JoJo universe!",
        color=0x9966cc
    )
    
    embed.add_field(name="Current Part", value=f"Part {player['part']}: {part_info['name']}", inline=False)
    embed.add_field(name="Description", value=part_info['description'], inline=False)
    embed.add_field(name="Experience", value=f"{player['exp']} EXP", inline=True)
    embed.add_field(name="Progress", value=progress, inline=True)
    embed.add_field(name="Stand", value=f"『{player['stand']}』", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name="adventure")
@commands.cooldown(1, 3600, commands.BucketType.user)  # Once per hour
async def adventure(ctx):
    """Go on a JoJo adventure to earn EXP"""
    user_id = str(ctx.author.id)
    
    # Check if user exists in the game
    if user_id not in jojo_game["players"]:
        await ctx.invoke(bot.get_command("profile"))
    
    player = jojo_game["players"][user_id]
    
    # Generate adventure story based on player's current part
    part = player["part"]
    part_info = jojo_game["parts"][part]
    
    # Adventure outcomes
    outcomes = [
        {"exp": 10, "desc": "You encountered a minor enemy Stand user and defeated them easily."},
        {"exp": 25, "desc": "You helped a local in town and they rewarded you."},
        {"exp": 50, "desc": "You discovered a mysterious artifact with Stand powers."},
        {"exp": 75, "desc": "You defeated a powerful enemy Stand user after a tough battle."},
        {"exp": 100, "desc": "You've completed an important mission critical to the story!"}
    ]
    
    # Weight outcomes based on current part (higher parts = better chance of better outcomes)
    weights = [5, 4, 3, 2, 1]
    if part > 3:
        weights = [3, 3, 4, 5, 5]  # Better odds in later parts
    
    # Select outcome
    outcome = random.choices(outcomes, weights=weights, k=1)[0]
    
    # Add experience
    player["exp"] += outcome["exp"]
    
    # Check for part advancement
    advanced = False
    next_part = part + 1
    if next_part in jojo_game["parts"] and player["exp"] >= jojo_game["parts"][next_part]["exp_req"]:
        player["part"] = next_part
        advanced = True
    
    # Create embed
    embed = discord.Embed(
        title=f"Adventure in Part {part}: {part_info['name']}",
        description=outcome["desc"],
        color=0x9966cc
    )
    
    embed.add_field(name="Experience Gained", value=f"+{outcome['exp']} EXP", inline=False)
    embed.add_field(name="Total Experience", value=f"{player['exp']} EXP", inline=False)
    
    if advanced:
        embed.add_field(
            name="Part Advanced!",
            value=f"You've advanced to Part {next_part}: {jojo_game['parts'][next_part]['name']}!",
            inline=False
        )
    
    await ctx.send(embed=embed)

@adventure.error
async def adventure_error(ctx, error):
    """Handle errors for the adventure command"""
    if isinstance(error, commands.CommandOnCooldown):
        minutes = int(error.retry_after // 60)
        seconds = int(error.retry_after % 60)
        await ctx.send(f"Your Stand needs to rest! Try again in {minutes}m {seconds}s.")

@bot.command(name="leaderboard")
async def leaderboard(ctx):
    """Display the JoJo game leaderboard"""
    if not jojo_game["players"]:
        await ctx.send("No players have started their JoJo adventure yet!")
        return
    
    # Sort players by experience
    sorted_players = sorted(
        jojo_game["players"].items(),
        key=lambda x: (x[1]["part"], x[1]["exp"]),
        reverse=True
    )
    
    # Get top 10 players
    top_players = sorted_players[:10]
    
    # Create embed
    embed = discord.Embed(
        title="JoJo's Bizarre Adventure Leaderboard",
        description="The top Stand users in this server!",
        color=0xffd700
    )
    
    # Add players to the leaderboard
    for i, (user_id, player) in enumerate(top_players, 1):
        try:
            user = await bot.fetch_user(int(user_id))
            username = user.display_name
        except:
            username = f"User {user_id}"
        
        embed.add_field(
            name=f"{i}. {username}",
            value=f"Part {player['part']}: {jojo_game['parts'][player['part']]['name']}\n"
                  f"EXP: {player['exp']}\nStand: 『{player['stand']}』",
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command(name="verify")
async def verify(ctx):
    """Verify a user to grant access to the server"""
    # Check if command is being used in verification channel
    if VERIFICATION_CHANNEL_ID and ctx.channel.id != VERIFICATION_CHANNEL_ID:
        # Only reply if in DMs or verification channel
        if not ctx.guild:
            await ctx.send("Please use this command in the #verification channel of the server.")
        return
    
    # Check if user has unverified role
    unverified_role = ctx.guild.get_role(UNVERIFIED_ROLE_ID)
    verified_role = ctx.guild.get_role(VERIFIED_ROLE_ID)
    
    if unverified_role and unverified_role in ctx.author.roles:
        try:
            # Remove unverified role
            await ctx.author.remove_roles(unverified_role)
            
            # Add verified role
            if verified_role:
                await ctx.author.add_roles(verified_role)
                logger.info(f"Added verified role to {ctx.author.name}")
            
            # JoJo-themed verification message
            stand = get_jojo_stand(ctx.author.name).split("\n")[0].strip("『』")
            
            embed = discord.Embed(
                title="Verification Complete!",
                description=f"Your Stand 『{stand}』 has awakened, {ctx.author.mention}!",
                color=0x00ff00
            )
            embed.add_field(
                name="Access Granted",
                value="You now have access to the rest of the server. Enjoy your bizarre adventure!",
                inline=False
            )
            embed.add_field(
                name="JoJo Game",
                value="Use `!profile` to start your JoJo journey and `!help` to see all available commands!",
                inline=False
            )
            
            await ctx.send(embed=embed)
            
            # Also send a message to the general channel if it exists
            general_channel = discord.utils.get(ctx.guild.text_channels, name="general")
            if general_channel:
                await general_channel.send(f"ゴゴゴゴ A new Stand user, {ctx.author.mention}, has joined the adventure! ゴゴゴゴ")
            
            # Add them to the game system with bonus EXP for verifying
            user_id = str(ctx.author.id)
            if user_id not in jojo_game["players"]:
                jojo_game["players"][user_id] = {
                    "part": 1,
                    "exp": 50,  # Bonus EXP for verifying
                    "stand": get_jojo_stand(ctx.author.name).split("\n")[0].strip("『』"),
                    "items": [],
                    "wins": 0,
                    "losses": 0,
                    "daily_streak": 0,
                    "last_daily": ""
                }
            
            logger.info(f"User {ctx.author.name} has been verified")
        except Exception as e:
            await ctx.send("There was an error during verification. Please contact a server admin.")
            logger.error(f"Error verifying user {ctx.author.name}: {e}")
    else:
        # If user is already verified
        await ctx.send("You are already verified or don't need verification!")
        # Delete the message after 5 seconds
        await asyncio.sleep(5)
        try:
            await ctx.message.delete()
        except:
            pass

# Help Command 
@bot.command(name='help')
async def custom_help(ctx, command=None):
    """Display a styled help message with command categories"""
    # List of commands to exclude from help menu
    excluded_commands = [
        # Music commands (hidden)
        "play", "leave", "skip", "queue", "clearqueue", "pause", "resume", "np", "nowplaying",
        # Moderation commands (shown only in !admin)
        "kick", "ban", "mute", "unmute", "clear", "move", "raid_mode", "fix_permissions", 
        "setup_roles", "verify_setup", "setup_permissions", "admin", "ticket_setup",
        "mass_dm", "verify", "setup_rework"
    ]
    
    if command:
        # Check if the command is "jojo" or "jojogame"
        if command.lower() in ["jojo", "jojogame"]:
            # Create dedicated JoJo game help embed
            embed = discord.Embed(
                title="JoJo's Bizarre Adventure Game",
                description="Experience your own JoJo adventure with these commands!",
                color=0x9966cc
            )
            
            embed.add_field(
                name="🎮 Game Progress",
                value="`profile` - View your current progress and statistics\n"
                      "`daily` - Collect daily rewards\n"
                      "`adventure` - Go on an adventure to earn exp\n"
                      "`leaderboard` - View top players",
                inline=False
            )
            
            embed.add_field(
                name="⚔️ Battle System",
                value="`battle` - Battle other Stand users\n"
                      "`stand` - View your current Stand\n"
                      "`jojo` - Get a random JoJo quote",
                inline=False
            )
            
            embed.add_field(
                name="🛒 Economy",
                value="`shop` - Browse available items\n"
                      "`buy` - Purchase items from the shop\n"
                      "`inventory` - View your owned items",
                inline=False
            )
            
            embed.set_footer(text="Type !help for general commands")
            
            await ctx.send(embed=embed)
            return
        
        # Display help for a specific command
        cmd = bot.get_command(command)
        if cmd:
            embed = discord.Embed(
                title=f"Command: !{cmd.name}",
                description=cmd.help or "No description available.",
                color=0x7289da
            )
            # Add usage if it's a moderation command
            if cmd.name in ['kick', 'ban']:
                embed.add_field(name="Usage", value=f"!{cmd.name} <member> [reason]", inline=False)
            elif cmd.name == 'mute':
                embed.add_field(name="Usage", value=f"!mute <member> [duration in minutes] [reason]", inline=False)
            elif cmd.name == 'move':
                embed.add_field(name="Usage", value=f"!move <member> <voice channel>", inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"Command `{command}` not found.")
        return
    
    # Main help embed
    embed = discord.Embed(
        title="Bot Help",
        description="Use `!help <command>` for more information on a specific command.",
        color=0x2b2d31
    )
    
    # JoJo Game Commands (simplified, directing to detailed help)
    embed.add_field(
        name="⭐ JoJo Game",
        value="Use `!help jojo` for detailed game commands",
        inline=False
    )
    
    # Fun Commands
    embed.add_field(
        name="😄 Fun Commands",
        value="`scan` - Analyze text with Stand power\n`hello` - Get a JoJo greeting\n`poll` - Create a poll\n"
              "`dice` - Roll dice with JoJo style\n`rps` - Play Rock, Paper, Scissors\n`8ball` - Ask the magic 8-ball\n"
              "`coinflip` - Flip a coin\n`quiz` - Take a JoJo quiz\n`trivia` - Get JoJo trivia\n"
              "`dm` - Get a DM from the bot",
        inline=False
    )
    
    # Server Info Commands
    embed.add_field(
        name="ℹ️ Server Info",
        value="`ticket` - Create a support ticket\n`verify` - Verify yourself as a user\n"
              "`profile` - View your profile\n`info` - Get server info\n",
        inline=False
    )
    
    # Note about admin commands
    embed.add_field(
        name="🔒 Admin Commands",
        value="Admin commands are hidden from this help menu.\nUse `!admin` if you have administrator permissions.",
        inline=False
    )
    # Final note
    embed.set_footer(text="QuantumX Bot | Made with JoJo's Bizarre Adventure theme")
    
    # General Commands
    embed.add_field(
        name="🌐 General",
        value="`ping` - Check bot's response time\n`help` - Show this help menu\n`verify` - Verify yourself in the server",
        inline=False
    )
    
    # Add footer
    embed.set_footer(text=f"Requested by {ctx.author.display_name}")
    
    await ctx.send(embed=embed)

@bot.command(name='admin')
async def admin_help(ctx):
    """Display moderation and admin commands (Admin only)"""
    # Check if user has administrator permissions
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ You need administrator permissions to use this command.")
        return
        
    embed = discord.Embed(
        title="🛡️ Admin Commands",
        description="Moderation and server management commands for administrators.",
        color=0xFF0000
    )
    
    # Moderation Commands
    embed.add_field(
        name="👮 Moderation",
        value="`kick` - Kick a user from the server\n"
              "`ban` - Ban a user from the server\n"
              "`mute` - Timeout a user for a period\n"
              "`unmute` - Remove timeout from a user\n"
              "`clear` - Delete multiple messages",
        inline=False
    )
    
    # Server Management
    embed.add_field(
        name="⚙️ Server Management",
        value="`raid_mode` - Enable/disable raid protection\n"
              "`verify_setup` - Set up the verification system\n"
              "`setup_permissions` - Fix permissions for unverified users\n"
              "`ticket_setup` - Set up the ticket system\n"
              "`serverbackup` - Create a backup of server configuration\n"
              "`listbackups` - List available server backups\n"
              "`backuprestore <number>` - Restore a server backup",
        inline=False
    )
    
    # Communication
    embed.add_field(
        name="📢 Communication",
        value="`massdm` - Send a DM to multiple users\n"
              "`move` - Move a user to a different voice channel",
        inline=False
    )
    
    embed.set_footer(text="These commands are restricted to server administrators.")
    
    await ctx.send(embed=embed)

@bot.command(name="ticket_setup")
@commands.has_permissions(administrator=True)
async def ticket_setup(ctx):
    """Set up a ticket message with create button"""
    guild = ctx.guild
    
    # Delete the command message to keep the channel clean
    try:
        await ctx.message.delete()
    except Exception as e:
        logger.error(f"Failed to delete command message: {e}")
    
    # Send initial status message
    status_msg = await ctx.send("🔄 Setting up ticket system...")
    
    # Check if there's already a tickets category
    tickets_category = None
    for category in guild.categories:
        if category.name.lower() == "tickets":
            tickets_category = category
            break
    
    # Create category if it doesn't exist
    if not tickets_category:
        try:
            tickets_category = await guild.create_category(
                name="Tickets",
                reason="Created by JoJo bot for ticket system"
            )
            await status_msg.edit(content="✅ Created Tickets category\n🔄 Setting up ticket message...")
        except Exception as e:
            await status_msg.edit(content=f"❌ Failed to create Tickets category: {e}")
            return
    else:
        await status_msg.edit(content="✅ Found existing Tickets category\n🔄 Setting up ticket message...")
    
    # Create embed for ticket message
    embed = discord.Embed(
        title="🎫 Support Tickets",
        description=(
            "Need help or have a question? Create a support ticket by clicking the button below!\n\n"
            "A private channel will be created where you can chat with server staff.\n\n"
            "**「STAND PROUD」 and reach out to us with any concerns!**"
        ),
        color=0x9c84ef
    )
    
    # Add JoJo-themed footer
    embed.set_footer(text="Your bizarre ticket experience awaits...")
    
    # Send the message with button
    try:
        ticket_msg = await ctx.channel.send(embed=embed, view=TicketView())
        await status_msg.edit(content=f"✅ Ticket system successfully set up!")
        
        # Log setup
        logger.info(f"Ticket system set up in {guild.name} by {ctx.author.name}")
    except Exception as e:
        await status_msg.edit(content=f"❌ Failed to set up ticket message: {e}")
        logger.error(f"Error setting up ticket system: {e}")

@bot.command(name='jojogame', aliases=['jg'])
async def jojogame_help(ctx):
    """Show JoJo game commands"""
    # Create dedicated JoJo game help embed
    embed = discord.Embed(
        title="JoJo's Bizarre Adventure Game",
        description="Experience your own JoJo adventure with these commands!",
        color=0x9966cc
    )
    
    embed.add_field(
        name="🎮 Game Progress",
        value="`profile` - View your current progress and statistics\n"
              "`daily` - Collect daily rewards\n"
              "`adventure` - Go on an adventure to earn exp\n"
              "`leaderboard` - View top players",
        inline=False
    )
    
    embed.add_field(
        name="⚔️ Battle System",
        value="`battle` - Battle other Stand users\n"
              "`stand` - View your current Stand\n"
              "`jojo` - Get a random JoJo quote",
        inline=False
    )
    
    embed.add_field(
        name="🛒 Economy",
        value="`shop` - Browse available items\n"
              "`buy` - Purchase items from the shop\n"
              "`inventory` - View your owned items",
        inline=False
    )
    
    embed.set_footer(text="Type !help for general commands")
    
    await ctx.send(embed=embed)

@bot.command(name="daily")
@commands.cooldown(1, 86400, commands.BucketType.user)  # Once per day
async def daily_reward(ctx):
    """Claim your daily EXP bonus"""
    user_id = str(ctx.author.id)
    
    # Initialize player if they don't exist
    if user_id not in jojo_game["players"]:
        jojo_game["players"][user_id] = {
            "part": 1,
            "exp": 0,
            "stand": get_jojo_stand(ctx.author.name).split("\n")[0].strip("『』"),
            "items": [],
            "wins": 0,
            "losses": 0,
            "daily_streak": 0,
            "last_daily": ""
        }
    
    player = jojo_game["players"][user_id]
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Check if player already claimed today
    if player.get("last_daily") == today:
        embed = discord.Embed(
            title="Daily Reward Already Claimed",
            description="You've already claimed your daily reward today. Come back tomorrow!",
            color=0xff9900
        )
        await ctx.send(embed=embed)
        return
    
    # Calculate streak
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    if player.get("last_daily") == yesterday:
        player["daily_streak"] += 1
    else:
        player["daily_streak"] = 1
    
    # Calculate bonus based on streak
    base_bonus = jojo_game["daily_bonus"]
    streak_multiplier = min(player["daily_streak"] / 10, 1)  # Max 2x bonus at 10-day streak
    streak_bonus = int(base_bonus * streak_multiplier)
    total_bonus = base_bonus + streak_bonus
    
    # Update player data
    player["exp"] += total_bonus
    player["last_daily"] = today
    
    # Check if player leveled up
    old_part = player["part"]
    for part_num in sorted(jojo_game["parts"].keys(), reverse=True):
        part_info = jojo_game["parts"][part_num]
        if player["exp"] >= part_info["exp_req"]:
            player["part"] = part_num
            break
    
    # Create response embed
    embed = discord.Embed(
        title="Daily Reward Claimed!",
        description=f"You've received {total_bonus} EXP!",
        color=0x00ff00
    )
    
    # Add streak info
    embed.add_field(
        name="Current Streak",
        value=f"{player['daily_streak']} day{'s' if player['daily_streak'] != 1 else ''}"
    )
    
    # Add bonus info if applicable
    if streak_bonus > 0:
        embed.add_field(
            name="Streak Bonus",
            value=f"+{streak_bonus} EXP"
        )
    
    # Add level up message if applicable
    if player["part"] > old_part:
        embed.add_field(
            name="Level Up!",
            value=f"You've advanced to Part {player['part']}: {jojo_game['parts'][player['part']]['name']}!",
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command(name="shop")
@commands.cooldown(1, 5, commands.BucketType.user)
async def shop(ctx):
    """Browse the item shop"""
    embed = discord.Embed(
        title="JoJo's Bizarre Shop",
        description="Spend your hard-earned EXP on these items!",
        color=0xF9A825
    )
    
    for item_id, item_info in jojo_game["items"].items():
        embed.add_field(
            name=f"{item_info['name']} ({item_info['price']} EXP)",
            value=f"{item_info['description']}\nUse `!buy {item_id}` to purchase",
            inline=True
        )
    
    embed.set_footer(text="Items can change your Stand abilities or give you special bonuses!")
    await ctx.send(embed=embed)

@bot.command(name="inventory")
@commands.cooldown(1, 5, commands.BucketType.user)
async def inventory(ctx):
    """View your owned items"""
    user_id = str(ctx.author.id)
    
    # Check if player exists
    if user_id not in jojo_game["players"]:
        await ctx.send("You don't have a JoJo game profile yet! Use `!profile` to start your adventure.")
        return
    
    player = jojo_game["players"][user_id]
    items = player.get("items", [])
    
    if not items:
        embed = discord.Embed(
            title="Your Inventory",
            description="You don't have any items yet. Use `!shop` to browse available items.",
            color=0xFFB74D
        )
    else:
        embed = discord.Embed(
            title="Your Inventory",
            description=f"You have {len(items)} item(s):",
            color=0xFFB74D
        )
        
        # Count items and group by type
        item_counts = {}
        for item in items:
            if item in item_counts:
                item_counts[item] += 1
            else:
                item_counts[item] = 1
        
        # Add items to embed
        for item_id, count in item_counts.items():
            if item_id in jojo_game["items"]:
                item_info = jojo_game["items"][item_id]
                embed.add_field(
                    name=f"{item_info['name']} x{count}",
                    value=item_info['description'],
                    inline=True
                )
    
    await ctx.send(embed=embed)

@bot.command(name="buy")
@commands.cooldown(1, 10, commands.BucketType.user)
async def buy_item(ctx, item_id: str = None):
    """Purchase an item from the shop"""
    if not item_id:
        await ctx.send("Please specify an item to buy. Use `!shop` to see available items.")
        return
    
    # Convert to lowercase for case-insensitive matching
    item_id = item_id.lower()
    
    # Check if item exists
    if item_id not in jojo_game["items"]:
        await ctx.send(f"Item '{item_id}' not found in the shop. Use `!shop` to see available items.")
        return
    
    user_id = str(ctx.author.id)
    
    # Initialize player if they don't exist
    if user_id not in jojo_game["players"]:
        jojo_game["players"][user_id] = {
            "part": 1,
            "exp": 0,
            "stand": get_jojo_stand(ctx.author.name).split("\n")[0].strip("『』"),
            "items": [],
            "wins": 0,
            "losses": 0,
            "daily_streak": 0,
            "last_daily": ""
        }
    
    player = jojo_game["players"][user_id]
    item = jojo_game["items"][item_id]
    
    # Check if player has enough EXP
    if player["exp"] < item["price"]:
        await ctx.send(f"You don't have enough EXP to buy {item['name']}. You need {item['price']} EXP, but you only have {player['exp']} EXP.")
        return
    
    # Process the purchase
    player["exp"] -= item["price"]
    player["items"].append(item_id)
    
    # Apply item effects
    effect_description = ""
    
    if item_id == "arrow":
        # Evolve stand to a higher tier
        stand_name = player["stand"]
        current_tier = random.choice(jojo_game["stand_tiers"])
        new_tier_index = min(jojo_game["stand_tiers"].index(current_tier) + 1, len(jojo_game["stand_tiers"]) - 1)
        new_tier = jojo_game["stand_tiers"][new_tier_index]
        player["stand"] = f"{stand_name} {new_tier}"
        effect_description = f"Your Stand has evolved to tier {new_tier}!"
        
    elif item_id == "rokakaka":
        # Reset stand for a new one
        player["stand"] = get_jojo_stand(ctx.author.name + str(random.randint(1, 1000))).split("\n")[0].strip("『』")
        effect_description = f"You've obtained a new Stand: {player['stand']}!"
        
    elif item_id == "requiem":
        # Evolve to Requiem form
        if "Requiem" not in player["stand"]:
            player["stand"] = f"{player['stand']} Requiem"
            effect_description = "Your Stand has achieved its Requiem form!"
        else:
            effect_description = "Your Stand is already in Requiem form, but it grows stronger!"
    
    # Create response embed
    embed = discord.Embed(
        title=f"Item Purchased: {item['name']}",
        description=f"You spent {item['price']} EXP and now have {player['exp']} EXP remaining.",
        color=0x4CAF50
    )
    
    embed.add_field(
        name="Effect",
        value=effect_description or item["description"],
        inline=False
    )
    
    await ctx.send(embed=embed)

@bot.command(name="battle")
@commands.cooldown(1, 30, commands.BucketType.user)
async def battle(ctx, opponent: discord.Member = None):
    """Battle another user with your Stand"""
    if opponent is None:
        await ctx.send("You need to specify an opponent to battle! Usage: `!battle @user`")
        return
    
    if opponent.id == ctx.author.id:
        await ctx.send("You can't battle yourself!")
        return
    
    if opponent.bot:
        await ctx.send("You can't battle a bot!")
        return
    
    user_id = str(ctx.author.id)
    opponent_id = str(opponent.id)
    
    # Initialize players if they don't exist
    if user_id not in jojo_game["players"]:
        jojo_game["players"][user_id] = {
            "part": 1,
            "exp": 0,
            "stand": get_jojo_stand(ctx.author.name).split("\n")[0].strip("『』"),
            "items": [],
            "wins": 0,
            "losses": 0,
            "daily_streak": 0,
            "last_daily": ""
        }
    
    if opponent_id not in jojo_game["players"]:
        jojo_game["players"][opponent_id] = {
            "part": 1,
            "exp": 0,
            "stand": get_jojo_stand(opponent.name).split("\n")[0].strip("『』"),
            "items": [],
            "wins": 0,
            "losses": 0,
            "daily_streak": 0,
            "last_daily": ""
        }
    
    player = jojo_game["players"][user_id]
    opponent_player = jojo_game["players"][opponent_id]
    
    # Calculate power levels based on part, stand tier, and if Requiem
    def calculate_power(p):
        base_power = p["part"] * 10
        
        # Add stand tier bonus
        stand = p["stand"]
        for tier in jojo_game["stand_tiers"]:
            if tier in stand:
                tier_index = jojo_game["stand_tiers"].index(tier)
                base_power += (tier_index + 1) * 5
                break
        
        # Add Requiem bonus
        if "Requiem" in stand:
            base_power *= 1.5
            
        # Add random factor (±20%)
        random_factor = random.uniform(0.8, 1.2)
        return base_power * random_factor
    
    player_power = calculate_power(player)
    opponent_power = calculate_power(opponent_player)
    
    # Determine winner
    player_wins = player_power > opponent_power
    
    # Award EXP
    exp_gained = 50 if player_wins else 20
    player["exp"] += exp_gained
    
    # Update win/loss records
    if player_wins:
        player["wins"] += 1
        opponent_player["losses"] += 1
    else:
        player["losses"] += 1
        opponent_player["wins"] += 1
    
    # Create battle embed
    embed = discord.Embed(
        title="⚔️ Stand Battle ⚔️",
        description=f"{ctx.author.mention}'s 『{player['stand']}』 VS {opponent.mention}'s 『{opponent_player['stand']}』",
        color=0xE91E63
    )
    
    # Battle location
    location = random.choice(jojo_game["locations"])
    embed.add_field(
        name="Battle Location",
        value=location,
        inline=False
    )
    
    # Battle results with power ratings
    embed.add_field(
        name="Power Levels",
        value=f"{ctx.author.display_name}: {player_power:.1f}\n{opponent.display_name}: {opponent_power:.1f}",
        inline=True
    )
    
    # Winner announcement
    winner = ctx.author if player_wins else opponent
    embed.add_field(
        name="Winner",
        value=f"{winner.mention}'s Stand was victorious!",
        inline=True
    )
    
    # Reward
    embed.add_field(
        name="Reward",
        value=f"{ctx.author.display_name} gained {exp_gained} EXP",
        inline=False
    )
    
    # Check if player leveled up
    old_part = player["part"]
    for part_num in sorted(jojo_game["parts"].keys(), reverse=True):
        part_info = jojo_game["parts"][part_num]
        if player["exp"] >= part_info["exp_req"]:
            player["part"] = part_num
            break
    
    # Add level up message if applicable
    if player["part"] > old_part:
        embed.add_field(
            name="Level Up!",
            value=f"{ctx.author.mention} advanced to Part {player['part']}: {jojo_game['parts'][player['part']]['name']}!",
            inline=False
        )
    
    await ctx.send(embed=embed)

# Error handling for moderation commands
@kick.error
@ban.error
@mute.error
@unmute.error
@move.error
@clear.error
async def moderation_error(ctx, error):
    """Error handler for moderation commands"""
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You don't have permission to use this command!")
    elif isinstance(error, commands.MissingRequiredArgument):
        if ctx.command.name == "kick" or ctx.command.name == "ban":
            await ctx.send(f"Usage: !{ctx.command.name} <member> [reason]")
        elif ctx.command.name == "mute":
            await ctx.send("Usage: !mute <member> [duration in minutes] [reason]")
        elif ctx.command.name == "move":
            await ctx.send("Usage: !move <member> <voice channel>")
        else:
            await ctx.send(f"Missing required argument for !{ctx.command.name}")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("I couldn't find that member or channel. Please check and try again.")
    else:
        await ctx.send(f"An error occurred: {error}")
        logger.error(f"Error in {ctx.command.name} command: {error}")

# Anti-Nuke Events
@bot.event
async def on_guild_channel_create(channel):
    """Monitor channel creation for potential nuking"""
    if not channel.guild:
        return
        
    # Track channel creation
    nuke_detected = anti_raid.add_action(channel.guild.id, 'channel_create', channel.guild.me.id)
    
    if nuke_detected:
        # Get audit log to see who created the channel
        try:
            async for entry in channel.guild.audit_logs(action=discord.AuditLogAction.channel_create, limit=1):
                if entry.user.id != bot.user.id and not entry.user.id == channel.guild.owner_id:
                    # Someone is creating multiple channels rapidly (possible nuke)
                    
                    # Notify admins
                    mod_log = discord.utils.get(channel.guild.text_channels, name="mod-logs")
                    if mod_log:
                        embed = discord.Embed(
                            title="🚨 NUKE ALERT - Multiple Channels Created",
                            description=f"User {entry.user.mention} is creating multiple channels rapidly!",
                            color=0xff0000
                        )
                        embed.add_field(name="Action", value="Consider revoking their admin permissions immediately!")
                        await mod_log.send(embed=embed)
                    
                    # DM the owner
                    if channel.guild.owner:
                        await channel.guild.owner.send(
                            f"🚨 **NUKE ALERT** 🚨\nUser {entry.user.name} is creating multiple channels rapidly in {channel.guild.name}! "
                            f"They may be attempting to nuke the server. Consider revoking their permissions immediately!"
                        )
                    break
        except Exception as e:
            logger.error(f"Error checking audit logs for channel creation: {e}")

@bot.event
async def on_guild_channel_delete(channel):
    """Monitor channel deletion for potential nuking"""
    if not hasattr(channel, 'guild') or not channel.guild:
        return
        
    # Track channel deletion
    nuke_detected = anti_raid.add_action(channel.guild.id, 'channel_delete', channel.guild.me.id)
    
    if nuke_detected:
        # Get audit log to see who deleted the channel
        try:
            async for entry in channel.guild.audit_logs(action=discord.AuditLogAction.channel_delete, limit=1):
                if entry.user.id != bot.user.id and not entry.user.id == channel.guild.owner_id:
                    # Someone is deleting multiple channels rapidly (possible nuke)
                    
                    # Notify admins via DM if possible
                    if channel.guild.owner:
                        await channel.guild.owner.send(
                            f"🚨 **NUKE ALERT** 🚨\nUser {entry.user.name} is deleting multiple channels rapidly in {channel.guild.name}! "
                            f"They may be attempting to nuke the server. Consider revoking their permissions immediately!"
                        )
                    break
        except Exception as e:
            logger.error(f"Error checking audit logs for channel deletion: {e}")

@bot.event
async def on_guild_role_create(role):
    """Monitor role creation for potential nuking"""
    # Track role creation
    nuke_detected = anti_raid.add_action(role.guild.id, 'role_create', role.guild.me.id)
    
    if nuke_detected:
        # Get audit log to see who created the role
        try:
            async for entry in role.guild.audit_logs(action=discord.AuditLogAction.role_create, limit=1):
                if entry.user.id != bot.user.id and not entry.user.id == role.guild.owner_id:
                    # Someone is creating multiple roles rapidly (possible nuke)
                    
                    # Notify admins
                    mod_log = discord.utils.get(role.guild.text_channels, name="mod-logs")
                    if mod_log:
                        embed = discord.Embed(
                            title="🚨 NUKE ALERT - Multiple Roles Created",
                            description=f"User {entry.user.mention} is creating multiple roles rapidly!",
                            color=0xff0000
                        )
                        embed.add_field(name="Action", value="Consider revoking their admin permissions immediately!")
                        await mod_log.send(embed=embed)
                    break
        except Exception as e:
            logger.error(f"Error checking audit logs for role creation: {e}")

@bot.event
async def on_guild_role_delete(role):
    """Monitor role deletion for potential nuking"""
    # Track role deletion
    nuke_detected = anti_raid.add_action(role.guild.id, 'role_delete', role.guild.me.id)
    
    if nuke_detected:
        # Get audit log to see who deleted the role
        try:
            async for entry in role.guild.audit_logs(action=discord.AuditLogAction.role_delete, limit=1):
                if entry.user.id != bot.user.id and not entry.user.id == role.guild.owner_id:
                    # Someone is deleting multiple roles rapidly (possible nuke)
                    
                    # Notify admins
                    mod_log = discord.utils.get(role.guild.text_channels, name="mod-logs")
                    if mod_log:
                        embed = discord.Embed(
                            title="🚨 NUKE ALERT - Multiple Roles Deleted",
                            description=f"User {entry.user.mention} is deleting multiple roles rapidly!",
                            color=0xff0000
                        )
                        embed.add_field(name="Action", value="Consider revoking their admin permissions immediately!")
                        await mod_log.send(embed=embed)
                    break
        except Exception as e:
            logger.error(f"Error checking audit logs for role deletion: {e}")

# Anti-Raid commands
@bot.command(name="raidmode")
@commands.has_permissions(administrator=True)
async def raid_mode(ctx, mode: str = None):
    """Enable/disable raid mode or check status"""
    if mode is None:
        # Check current status
        status = anti_raid.is_raid_mode_enabled(ctx.guild.id)
        await ctx.send(f"Raid mode is currently {'enabled' if status else 'disabled'}.")
        return
        
    if mode.lower() in ['on', 'enable', 'true', 'yes']:
        anti_raid.enable_raid_mode(ctx.guild.id)
        embed = discord.Embed(
            title="🔒 Raid Mode Enabled",
            description="The server is now in raid protection mode.",
            color=0xff9900
        )
        embed.add_field(
            name="Effects",
            value="• New joins will be more strictly monitored\n"
                 "• Message spam detection is heightened\n"
                 "• Suspicious activities will trigger alerts"
        )
        await ctx.send(embed=embed)
    
    elif mode.lower() in ['off', 'disable', 'false', 'no']:
        anti_raid.disable_raid_mode(ctx.guild.id)
        embed = discord.Embed(
            title="🔓 Raid Mode Disabled",
            description="The server has returned to normal operation.",
            color=0x00ff00
        )
        await ctx.send(embed=embed)
    
    else:
        await ctx.send("Invalid option. Use `!raidmode on` or `!raidmode off`.")
        
@bot.command(name="setuproles")
@commands.has_permissions(administrator=True)
async def setup_roles(ctx):
    """Set up proper channel permissions for verified/unverified roles"""
    guild = ctx.guild
    unverified_role = guild.get_role(UNVERIFIED_ROLE_ID)
    verified_role = guild.get_role(VERIFIED_ROLE_ID)
    
    if not unverified_role:
        await ctx.send(f"❌ Could not find unverified role with ID {UNVERIFIED_ROLE_ID}")
        return
        
    if not verified_role:
        await ctx.send(f"❌ Could not find verified role with ID {VERIFIED_ROLE_ID}")
        return
    
    status_message = await ctx.send("🔄 Setting up channel permissions. This may take a moment...")
    
    # Default channels that unverified users can access
    allowed_channels = ["verification", "announcements", "rules", "welcome", "read-me-first"]
    
    # First, apply channel permissions to @everyone role to ensure baseline permissions
    everyone_role = guild.default_role
    for channel in guild.channels:
        try:
            if isinstance(channel, discord.CategoryChannel):
                # For categories, set read permissions to none
                await channel.set_permissions(everyone_role, read_messages=None)
                continue
                
            # By default, don't override @everyone permissions to avoid inheritance issues
            await channel.set_permissions(everyone_role, overwrite=None)
        except Exception as e:
            logger.error(f"Failed to reset @everyone permissions for {channel.name}: {e}")
    
    # Apply specific permissions to all channels
    channels_updated = 0
    
    for channel in guild.channels:
        try:
            # Skip categories for now - we'll handle them after individual channels
            if isinstance(channel, discord.CategoryChannel):
                continue
                
            # Block all channels for unverified users by default
            await channel.set_permissions(unverified_role, read_messages=False, send_messages=False)
            logger.info(f"Blocked {channel.name} for unverified users")
            
            # But allow verified users to access all channels (except admin ones)
            if not any(word in channel.name.lower() for word in ["admin", "mod", "staff", "log"]):
                await channel.set_permissions(verified_role, read_messages=True, send_messages=True)
                logger.info(f"Allowed {channel.name} for verified users")
            
            # For exceptional channels, we need to override these permissions
            if channel.name.lower() in (ch.lower() for ch in allowed_channels):
                can_send = channel.name.lower() == "verification"
                await channel.set_permissions(unverified_role, read_messages=True, send_messages=can_send)
                logger.info(f"Special access set for {channel.name}: read=True, send={can_send}")
                
            channels_updated += 1
        except Exception as e:
            logger.error(f"Failed to update permissions for {channel.name}: {e}")
    
    # Now handle categories
    for category in guild.categories:
        try:
            # Block categories for unverified users by default
            await category.set_permissions(unverified_role, read_messages=False)
            
            # Allow verified users to see all non-admin categories
            if not any(word in category.name.lower() for word in ["admin", "mod", "staff", "log"]):
                await category.set_permissions(verified_role, read_messages=True)
        except Exception as e:
            logger.error(f"Failed to update permissions for category {category.name}: {e}")
    
    # Update status message
    embed = discord.Embed(
        title="✅ Channel Permissions Updated",
        description=f"Updated permissions for {channels_updated} channels.",
        color=0x00ff00
    )
    embed.add_field(
        name="Verification System",
        value=f"• Unverified users can only access: {', '.join(allowed_channels)}\n"
              f"• Unverified users can only send messages in: verification\n"
              f"• Verified users have access to all regular channels"
    )
    await status_message.edit(content=None, embed=embed)
    
@bot.command(name="fixperms", aliases=["fixpermissions", "lockdown"])
@commands.has_permissions(administrator=True)
async def fix_permissions(ctx):
    """Emergency command to fix permissions and lock down server to unverified users"""
    status = await ctx.send("🔒 Emergency lockdown in progress...")
    
    guild = ctx.guild
    unverified_role = guild.get_role(UNVERIFIED_ROLE_ID)
    
    if not unverified_role:
        await ctx.send(f"❌ Could not find unverified role with ID {UNVERIFIED_ROLE_ID}")
        return
    
    verification_channel = None
    announcement_channel = None
    success_count = 0
    fail_count = 0
    
    # Find key channels
    for channel in guild.channels:
        if channel.name == "verification":
            verification_channel = channel
        elif channel.name == "announcements":
            announcement_channel = channel
    
    # Block EVERY channel from unverified users
    for channel in guild.channels:
        try:
            # Skip categories
            if isinstance(channel, discord.CategoryChannel):
                continue
                
            if channel == verification_channel:
                # Allow unverified users to see and send messages in verification
                await channel.set_permissions(unverified_role, read_messages=True, send_messages=True)
                await ctx.send(f"✅ Set verification channel permissions: {channel.name}")
            elif channel == announcement_channel:
                # Allow unverified users to see but not send messages in announcements
                await channel.set_permissions(unverified_role, read_messages=True, send_messages=False)
                await ctx.send(f"✅ Set announcement channel permissions: {channel.name}")
            else:
                # Block unverified users from all other channels
                await channel.set_permissions(unverified_role, read_messages=False, send_messages=False)
            
            success_count += 1
        except Exception as e:
            await ctx.send(f"❌ Failed to update {channel.name}: {str(e)}")
            fail_count += 1
    
    # Now handle categories
    for category in guild.categories:
        try:
            # Block all categories for unverified
            await category.set_permissions(unverified_role, read_messages=False)
            success_count += 1
        except Exception as e:
            await ctx.send(f"❌ Failed to update category {category.name}: {str(e)}")
            fail_count += 1
    
    # Create a final status embed
    embed = discord.Embed(
        title="🔒 Emergency Permission Lockdown Complete",
        description=f"Updated {success_count} channels/categories. Failed: {fail_count}",
        color=0xff3300
    )
    
    embed.add_field(
        name="Status",
        value="Unverified users can now ONLY access:\n• Verification channel\n• Announcements channel (read only)"
    )
    
    embed.add_field(
        name="Next Steps",
        value="1. Test with an unverified user to ensure they can only see verification\n"
              "2. Use `!setuproles` if you want to customize additional channel access for unverified users"
    )
    
    await status.edit(content=None, embed=embed)

# Fun games and minigames
@bot.command(name="dice")
async def roll_dice(ctx, sides: int = 6, number: int = 1):
    """Roll dice with custom sides and number of dice"""
    if sides < 2:
        await ctx.send("Dice must have at least 2 sides!")
        return
    
    if number < 1 or number > 10:
        await ctx.send("You can roll between 1 and 10 dice at once!")
        return
    
    # Roll the dice
    rolls = [random.randint(1, sides) for _ in range(number)]
    total = sum(rolls)
    
    # Create a response embed
    embed = discord.Embed(
        title="🎲 Dice Roll",
        description=f"{ctx.author.mention} rolled {number} {sides}-sided dice!",
        color=0x4CAF50
    )
    
    # Add roll results
    result_str = " + ".join([str(roll) for roll in rolls])
    if len(rolls) > 1:
        result_str += f" = {total}"
        
    embed.add_field(
        name="Results",
        value=result_str,
        inline=False
    )
    
    # Add a JoJo-themed response based on the roll
    if len(rolls) == 1:  # Single die
        if rolls[0] == sides:  # Max roll
            embed.add_field(name="JoJo Says", value="「STAR PLATINUM」! A perfect roll!")
        elif rolls[0] == 1:  # Min roll
            embed.add_field(name="JoJo Says", value="Yare yare daze... better luck next time.")
        elif rolls[0] > sides // 2:  # Above average
            embed.add_field(name="JoJo Says", value="NICE!")
    else:  # Multiple dice
        if total >= sides * number * 0.8:  # Great roll
            embed.add_field(name="JoJo Says", value="OH MY GOD! What an amazing roll!")
        elif total <= sides * number * 0.2:  # Bad roll
            embed.add_field(name="JoJo Says", value="HOLY SHEET! That's unfortunate...")
            
    await ctx.send(embed=embed)

@bot.command(name="8ball")
async def magic_8ball(ctx, *, question: str = None):
    """Ask the Magic 8-Ball a question"""
    if not question:
        await ctx.send("You need to ask a question! Try `!8ball Will I win the lottery?`")
        return
        
    # List of possible responses (JoJo-themed)
    responses = [
        "YES YES YES YES!",
        "No! No! No! No!",
        "Yare yare daze... it seems likely.",
        "MUDA MUDA MUDA! (Useless to ask me that)",
        "ORA ORA ORA! (The answer is yes!)",
        "It's an enemy Stand attack! (No)",
        "Impossible! Impossible! Impossible! Impossible!",
        "The World's time stop says... maybe.",
        "WRYYYYYYYY! (Definitely yes!)",
        "Your next line will be 'So the answer is yes?'",
        "Even Speedwagon is afraid of the answer...",
        "Oh ho! You're approaching the truth!",
        "Not scientifically possible!",
        "Good grief... the answer is yes.",
        "NIGERUNDAYO! (Run away from this question)",
        "I, Dio, say yes!",
        "Kono Giorno Giovanna have a dream that says no.",
        "RETIRED (That's a no)",
        "I'll allow it!",
        "The arrow chooses... yes."
    ]
    
    # Get a random response
    response = random.choice(responses)
    
    # Create the embed
    embed = discord.Embed(
        title="🎱 Magic 8-Ball",
        color=0x673AB7
    )
    
    embed.add_field(
        name=f"{ctx.author.display_name} asks:",
        value=question,
        inline=False
    )
    
    embed.add_field(
        name="The 8-Ball says:",
        value=response,
        inline=False
    )
    
    await ctx.send(embed=embed)

@bot.command(name="rps")
async def rock_paper_scissors(ctx, choice: str = None):
    """Play Rock, Paper, Scissors with the bot"""
    # Valid choices
    valid_choices = ["rock", "paper", "scissors", "r", "p", "s"]
    
    # Check if the user provided a valid choice
    if not choice or choice.lower() not in valid_choices:
        await ctx.send("You need to choose `rock`, `paper`, or `scissors`! (or `r`, `p`, `s`)")
        return
    
    # Convert shorthand to full name
    if choice.lower() == "r":
        choice = "rock"
    elif choice.lower() == "p":
        choice = "paper"
    elif choice.lower() == "s":
        choice = "scissors"
    
    # Bot's choice
    bot_choice = random.choice(["rock", "paper", "scissors"])
    
    # Determine the winner
    if choice.lower() == bot_choice:
        result = "It's a tie!"
        color = 0xFFC107  # Yellow for tie
    elif (choice.lower() == "rock" and bot_choice == "scissors") or \
         (choice.lower() == "paper" and bot_choice == "rock") or \
         (choice.lower() == "scissors" and bot_choice == "paper"):
        result = f"**{ctx.author.display_name} wins!**"
        color = 0x4CAF50  # Green for win
    else:
        result = "**Bot wins!**"
        color = 0xF44336  # Red for loss
    
    # JoJo-themed responses
    jojo_responses = {
        "win": [
            "NICE! Very nice!",
            "Your next line is 'I knew I would win!'",
            "OH MY GOD! You actually won!",
            "Even Speedwagon is impressed!"
        ],
        "lose": [
            "MUDA MUDA MUDA! Better luck next time!",
            "You fell for it, fool! Thunder Cross Split Attack!",
            "Yare yare daze... you lost.",
            "WRYYYY! The bot is victorious!"
        ],
        "tie": [
            "This must be the work of an enemy Stand!",
            "NANI?! A tie?!",
            "Oh ho! You're approaching my level!",
            "An equal match... but next time, the bot will win!"
        ]
    }
    
    # Get the appropriate JoJo response
    if "wins" in result and ctx.author.display_name in result:
        jojo_response = random.choice(jojo_responses["win"])
    elif "Bot wins" in result:
        jojo_response = random.choice(jojo_responses["lose"])
    else:
        jojo_response = random.choice(jojo_responses["tie"])
    
    # Create the embed
    embed = discord.Embed(
        title="✊ Rock, Paper, Scissors",
        description=result,
        color=color
    )
    
    # Add choices
    embed.add_field(
        name=f"{ctx.author.display_name} chose:",
        value=choice.capitalize(),
        inline=True
    )
    
    embed.add_field(
        name="Bot chose:",
        value=bot_choice.capitalize(),
        inline=True
    )
    
    # Add JoJo response
    embed.add_field(
        name="JoJo Says:",
        value=jojo_response,
        inline=False
    )
    
    await ctx.send(embed=embed)

@bot.command(name="coinflip", aliases=["flip", "coin"])
async def coin_flip(ctx):
    """Flip a coin"""
    # Get result
    result = random.choice(["Heads", "Tails"])
    
    # JoJo-themed responses
    jojo_heads = [
        "The coin shows **HEADS**! As predicted by Joseph Joestar!",
        "**HEADS**! ORAORAORAORAORAORA!",
        "**HEADS**! Koichi really flips? No dignity.",
        "The World stops time, and the coin lands on **HEADS**!"
    ]
    
    jojo_tails = [
        "The coin shows **TAILS**! Even Speedwagon is surprised!",
        "**TAILS**! MUDAMUDAMUDAMUDAMUDA!",
        "**TAILS**! This must be the work of an enemy Stand!",
        "King Crimson skips past the flip, revealing **TAILS**!"
    ]
    
    # Choose response based on result
    description = random.choice(jojo_heads if result == "Heads" else jojo_tails)
    
    # Create the embed
    embed = discord.Embed(
        title="🪙 Coin Flip",
        description=description,
        color=0xFFD700 if result == "Heads" else 0xC0C0C0
    )
    
    embed.set_footer(text=f"Requested by {ctx.author.display_name}")
    
    await ctx.send(embed=embed)

@bot.command(name="quiz")
@commands.cooldown(1, 30, commands.BucketType.user)
async def jojo_quiz(ctx):
    """Take a quiz about JoJo's Bizarre Adventure"""
    # Quiz questions and answers
    questions = [
        {
            "question": "Who is the protagonist of Part 1: Phantom Blood?",
            "options": ["Jonathan Joestar", "Joseph Joestar", "Jotaro Kujo", "Giorno Giovanna"],
            "answer": 0
        },
        {
            "question": "Which of these is NOT a Stand from the series?",
            "options": ["Star Platinum", "Killer Queen", "Golden Wind", "Crazy Diamond"],
            "answer": 2  # Golden Wind is Giorno's Part, not a Stand (Gold Experience is his Stand)
        },
        {
            "question": "What is Dio Brando's signature catchphrase?",
            "options": ["Ora Ora Ora!", "Yare Yare Daze", "WRYYYY!", "Arrivederci"],
            "answer": 2
        },
        {
            "question": "Which JoJo uses Hamon as their primary fighting technique?",
            "options": ["Josuke Higashikata", "Joseph Joestar", "Jolyne Cujoh", "Giorno Giovanna"],
            "answer": 1
        },
        {
            "question": "What is the name of Jotaro Kujo's Stand?",
            "options": ["The World", "Crazy Diamond", "Star Platinum", "Gold Experience"],
            "answer": 2
        }
    ]
    
    # Select a random question
    question_data = random.choice(questions)
    
    # Create the embed
    embed = discord.Embed(
        title="JoJo's Bizarre Quiz",
        description=question_data["question"],
        color=0x9C27B0
    )
    
    # Add options
    options_text = ""
    for i, option in enumerate(question_data["options"]):
        options_text += f"{i+1}. {option}\n"
    
    embed.add_field(
        name="Options:",
        value=options_text,
        inline=False
    )
    
    embed.add_field(
        name="How to Answer:",
        value="Type the number of your answer (1-4)",
        inline=False
    )
    
    embed.set_footer(text="You have 15 seconds to answer!")
    
    # Send the question
    question_message = await ctx.send(embed=embed)
    
    # Set up a check for the correct user's response
    def check(message):
        return message.author == ctx.author and message.channel == ctx.channel and \
               message.content in ["1", "2", "3", "4"]
    
    try:
        # Wait for an answer
        user_answer = await bot.wait_for('message', timeout=15.0, check=check)
        
        # Check if the answer is correct
        correct_answer_index = question_data["answer"]
        correct_answer = question_data["options"][correct_answer_index]
        user_answer_index = int(user_answer.content) - 1
        
        # Award EXP for correct answers
        user_id = str(ctx.author.id)
        
        # Initialize player if they don't exist
        if user_id not in jojo_game["players"]:
            jojo_game["players"][user_id] = {
                "part": 1,
                "exp": 0,
                "stand": get_jojo_stand(ctx.author.name).split("\n")[0].strip("『』"),
                "items": [],
                "wins": 0,
                "losses": 0,
                "daily_streak": 0,
                "last_daily": ""
            }
        
        # Result embed
        if user_answer_index == correct_answer_index:
            # Correct answer
            exp_gain = random.randint(10, 25)
            jojo_game["players"][user_id]["exp"] += exp_gain
            
            result_embed = discord.Embed(
                title="✅ Correct!",
                description=f"The answer is indeed **{correct_answer}**!",
                color=0x4CAF50
            )
            
            result_embed.add_field(
                name="Reward",
                value=f"You earned {exp_gain} EXP!",
                inline=False
            )
        else:
            # Wrong answer
            result_embed = discord.Embed(
                title="❌ Wrong!",
                description=f"The correct answer was **{correct_answer}**.",
                color=0xF44336
            )
            
            result_embed.add_field(
                name="Your Answer",
                value=question_data["options"][user_answer_index],
                inline=False
            )
        
        await ctx.send(embed=result_embed)
        
    except asyncio.TimeoutError:
        # Time's up
        timeout_embed = discord.Embed(
            title="⏱️ Time's Up!",
            description=f"The correct answer was **{question_data['options'][question_data['answer']]}**.",
            color=0xFF9800
        )
        
        await ctx.send(embed=timeout_embed)

@bot.command(name="trivia")
@commands.cooldown(1, 30, commands.BucketType.user)
async def jojo_trivia(ctx):
    """Get a random JoJo trivia fact"""
    trivia_facts = [
        "The character Dio Brando is named after actor Marlon Brando and musician Ronnie James Dio.",
        "Araki actually forgot about Hamon after Part 2, which is why Stands were introduced.",
        "Josuke's hairstyle was inspired by Prince's hairstyle from 1984-1985.",
        "The character Avdol in Part 3 was originally meant to stay dead after his first 'death'.",
        "Giorno Giovanna is technically both a Joestar and a Brando, as he is DIO's son using Jonathan's body.",
        "The Stand 'King Crimson' is named after the English progressive rock band of the same name.",
        "In Japanese, Part 4's title is actually 'Diamond is Unbreakable', not 'Diamond is Not Crash'.",
        "In the original Japanese manga, Killer Queen's bomb activation sound is 'Click' not 'Klik'.",
        "Araki has stated that his favorite JoJo is Joseph Joestar.",
        "The character Jotaro Kujo was inspired by Clint Eastwood.",
        "The pose where characters stand with their legs apart and leaning back is called the 'Contrapposto'.",
        "Star Platinum and The World are the same type of Stand.",
        "Weather Report's real name is Domenico Pucci, making him Enrico Pucci's younger twin brother.",
        "Koichi is the only character to appear in Parts 4, 5, and 8 (if you count his Part 8 counterpart).",
        "The song 'Roundabout' by Yes is used as the ending theme for Parts 1 and 2 of the anime."
    ]
    
    # Select a random trivia fact
    fact = random.choice(trivia_facts)
    
    # Create the embed
    embed = discord.Embed(
        title="JoJo's Bizarre Trivia",
        description=f"**Did you know?**\n{fact}",
        color=0xFFC107
    )
    
    embed.set_footer(text="Use !trivia for more JoJo facts!")
    
    await ctx.send(embed=embed)

# Verification button UI
class VerifyButton(ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # This view is persistent, so no timeout
    
    @ui.button(label="Verify Me", style=ButtonStyle.success, custom_id="verify_button")
    async def verify_button(self, interaction: discord.Interaction, button: ui.Button):
        """Verify a user when they click the button"""
        # Check if user has unverified role
        member = interaction.user
        guild = interaction.guild
        
        if guild is None:
            await interaction.response.send_message("Error: Could not identify the guild.", ephemeral=True)
            return
            
        # Get the roles
        unverified_role = get_role_safe(guild, UNVERIFIED_ROLE_ID, "Unverified")
        verified_role = get_role_safe(guild, VERIFIED_ROLE_ID, "Verified")
        
        if not unverified_role:
            await interaction.response.send_message(f"Error: Unverified role not found. Please contact an admin. (ID: {UNVERIFIED_ROLE_ID})", ephemeral=True)
            return
            
        if not verified_role:
            await interaction.response.send_message(f"Error: Verified role not found. Please contact an admin. (ID: {VERIFIED_ROLE_ID})", ephemeral=True)
            return
        
        # Check if user already has verified role
        try:
            has_verified = False
            has_unverified = False
            
            # Use a safe method to check roles to handle Member vs User type issues
            if hasattr(member, 'roles'):
                for role in member.roles:
                    if hasattr(role, 'id') and hasattr(verified_role, 'id'):
                        if role.id == verified_role.id:
                            has_verified = True
                    if hasattr(role, 'id') and hasattr(unverified_role, 'id'):
                        if role.id == unverified_role.id:
                            has_unverified = True
            
            if has_verified:
                # User is already verified
                await interaction.response.send_message("You are already verified!", ephemeral=True)
                return
            
            # Remove unverified role if they have it
            if has_unverified:
                try:
                    await member.remove_roles(unverified_role)
                    logger.info(f"Removed unverified role from {member.name}")
                except Exception as e:
                    logger.error(f"Error removing unverified role: {e}")
                    # Try a different method as fallback
                    try:
                        await guild.get_member(member.id).remove_roles(unverified_role)
                        logger.info(f"Removed unverified role with alternate method")
                    except Exception as e2:
                        logger.error(f"Failed alternate method too: {e2}")
            
            # Add verified role
            try:
                await member.add_roles(verified_role)
                logger.info(f"Added verified role to {member.name}")
            except Exception as e:
                logger.error(f"Error adding verified role: {e}")
                # Try a different method as fallback
                try:
                    await guild.get_member(member.id).add_roles(verified_role)
                    logger.info(f"Added verified role with alternate method")
                except Exception as e2:
                    logger.error(f"Failed alternate method too: {e2}")
            
            # Send confirmation message
            stand = get_jojo_stand(member.name).split("\n")[0].strip("『』")
            
            embed = discord.Embed(
                title="Verification Complete!",
                description=f"Your Stand 『{stand}』 has awakened, {member.mention}!",
                color=0x00ff00
            )
            embed.add_field(
                name="Access Granted",
                value="You now have access to the rest of the server. Enjoy your bizarre adventure!",
                inline=False
            )
            embed.add_field(
                name="JoJo Game",
                value="Use `!profile` to start your JoJo journey and `!help` to see all available commands!",
                inline=False
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
            # Also send a message to the general channel
            general_channel = discord.utils.get(guild.text_channels, name="general")
            if general_channel:
                await general_channel.send(f"ゴゴゴゴ A new Stand user, {member.mention}, has joined the adventure! ゴゴゴゴ")
            
            # Add them to the game system with bonus EXP for verifying
            user_id = str(member.id)
            if user_id not in jojo_game["players"]:
                jojo_game["players"][user_id] = {
                    "part": 1,
                    "exp": 50,  # Bonus EXP for verifying
                    "stand": get_jojo_stand(member.name).split("\n")[0].strip("『』"),
                    "items": [],
                    "wins": 0,
                    "losses": 0,
                    "daily_streak": 0,
                    "last_daily": ""
                }
            
            logger.info(f"User {member.name} has been verified via button")
        except Exception as e:
            await interaction.response.send_message("There was an error during verification. Please contact a server admin.", ephemeral=True)
            logger.error(f"Error verifying user {member.name} via button: {e}")

# Ticket System UI
class TicketView(ui.View):
    """View for the ticket creation button"""
    def __init__(self):
        super().__init__(timeout=None)  # No timeout for persistent view
    
    @ui.button(label="📩 Create Ticket", style=ButtonStyle.primary, custom_id="create_ticket")
    async def create_ticket(self, interaction: discord.Interaction, button: ui.Button):
        """Create a ticket channel when a user clicks the button"""
        user = interaction.user
        guild = interaction.guild
        
        if not guild:
            await interaction.response.send_message("Error: Could not identify the server.", ephemeral=True)
            return
        
        # Check if user already has an open ticket
        if str(user.id) in ticket_data["user_tickets"]:
            # Get the channel
            try:
                channel_id = ticket_data["user_tickets"][str(user.id)]
                channel = guild.get_channel(channel_id)
                
                if channel:
                    await interaction.response.send_message(
                        f"You already have an open ticket in {channel.mention}. Please use that one instead.",
                        ephemeral=True
                    )
                    return
                else:
                    # Channel no longer exists, clean up
                    if str(channel_id) in ticket_data["tickets"]:
                        del ticket_data["tickets"][str(channel_id)]
                    del ticket_data["user_tickets"][str(user.id)]
            except Exception as e:
                logger.error(f"Error checking existing ticket: {e}")
                # Clean up in case of error
                if str(user.id) in ticket_data["user_tickets"]:
                    del ticket_data["user_tickets"][str(user.id)]
        
        # Increment the ticket counter
        ticket_data["counter"] += 1
        ticket_number = ticket_data["counter"]
        
        # Find or create tickets category
        category = None
        for cat in guild.categories:
            if cat.name.lower() == "tickets":
                category = cat
                break
        
        if not category:
            try:
                # Create the category
                category = await guild.create_category("Tickets")
                logger.info(f"Created Tickets category in {guild.name}")
            except Exception as e:
                logger.error(f"Error creating ticket category: {e}")
                await interaction.response.send_message("Error creating ticket. Please contact an admin.", ephemeral=True)
                return
        
        # Create ticket channel
        try:
            # Create a unique JoJo-themed name for the channel
            channel_name = f"ticket-{ticket_number}-{user.name.lower().replace(' ', '-')}"
            # Ensure name is valid for Discord
            channel_name = re.sub(r'[^a-z0-9-]', '', channel_name)[:32]
            
            # Create the channel with proper permissions
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                user: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_messages=True,
                    attach_files=True,
                    read_message_history=True
                )
            }
            
            # Add admin role permissions if available
            admin_role = None
            for role in guild.roles:
                if role.permissions.administrator:
                    admin_role = role
                    overwrites[admin_role] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_messages=True,
                        attach_files=True,
                        read_message_history=True,
                        manage_messages=True
                    )
                    break
            
            # Create the channel
            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"Ticket for {user.name} | ID: {user.id} | Ticket #{ticket_number}"
            )
            
            # Store ticket data
            ticket_data["tickets"][str(channel.id)] = {
                "user_id": str(user.id),
                "claimed_by": None,
                "number": ticket_number,
                "created_at": datetime.now().isoformat()
            }
            
            # Link user to their ticket
            ticket_data["user_tickets"][str(user.id)] = channel.id
            
            # Send confirmation message
            await interaction.response.send_message(
                f"Your ticket has been created in {channel.mention}!",
                ephemeral=True
            )
            
            # Send initial message in the ticket channel with buttons
            embed = discord.Embed(
                title=f"Ticket #{ticket_number}",
                description=(
                    f"Welcome {user.mention}! Thanks for creating a ticket.\n\n"
                    f"Please describe your issue or concern and a staff member will assist you shortly.\n\n"
                    f"**Stand Proud! Your support experience will be bizarre, but helpful!**"
                ),
                color=0x9c84ef
            )
            embed.set_footer(text=f"Ticket created by {user.name} • {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Send with ticket controls
            await channel.send(
                content=f"{user.mention} {admin_role.mention if admin_role else ''}", 
                embed=embed, 
                view=TicketControlView()
            )
            
            # Log ticket creation
            logger.info(f"Ticket #{ticket_number} created by {user.name} ({user.id})")
            
        except Exception as e:
            logger.error(f"Error creating ticket channel: {e}")
            await interaction.response.send_message(f"An error occurred while creating your ticket. Please contact an admin. Error: {e}", ephemeral=True)

class TicketControlView(ui.View):
    """View for ticket management buttons (claim, close)"""
    def __init__(self):
        super().__init__(timeout=None)  # No timeout for persistent view
    
    @ui.button(label="🔒 Close Ticket", style=ButtonStyle.danger, custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: ui.Button):
        """Close a ticket"""
        channel = interaction.channel
        user = interaction.user
        guild = interaction.guild
        
        # Check if this is a ticket channel
        if not channel or not str(channel.id) in ticket_data["tickets"]:
            await interaction.response.send_message("This is not a ticket channel!", ephemeral=True)
            return
        
        # Check if user is admin or ticket creator
        is_admin = user.guild_permissions.administrator if hasattr(user, "guild_permissions") else False
        is_ticket_creator = str(user.id) == ticket_data["tickets"][str(channel.id)]["user_id"]
        
        if not (is_admin or is_ticket_creator):
            await interaction.response.send_message("You don't have permission to close this ticket!", ephemeral=True)
            return
        
        try:
            # Get ticket data
            ticket_info = ticket_data["tickets"][str(channel.id)]
            ticket_creator_id = ticket_info["user_id"]
            ticket_number = ticket_info["number"]
            
            # Ask for confirmation
            embed = discord.Embed(
                title="Close Ticket",
                description="Are you sure you want to close this ticket? This action cannot be undone.",
                color=0xff5555
            )
            
            # Send confirmation message with buttons
            await interaction.response.send_message(embed=embed, view=TicketCloseConfirmView(), ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error in close_ticket: {e}")
            await interaction.response.send_message(f"An error occurred while closing the ticket. Error: {e}", ephemeral=True)
    
    @ui.button(label="🙋 Claim Ticket", style=ButtonStyle.success, custom_id="claim_ticket")
    async def claim_ticket(self, interaction: discord.Interaction, button: ui.Button):
        """Claim a ticket to help the user"""
        channel = interaction.channel
        user = interaction.user
        
        # Check if this is a ticket channel
        if not channel or not str(channel.id) in ticket_data["tickets"]:
            await interaction.response.send_message("This is not a ticket channel!", ephemeral=True)
            return
        
        # Check if user is admin
        is_admin = user.guild_permissions.administrator if hasattr(user, "guild_permissions") else False
        
        if not is_admin:
            await interaction.response.send_message("Only administrators can claim tickets!", ephemeral=True)
            return
        
        try:
            # Get ticket data
            ticket_info = ticket_data["tickets"][str(channel.id)]
            
            # Check if ticket is already claimed
            if ticket_info["claimed_by"]:
                if ticket_info["claimed_by"] == str(user.id):
                    await interaction.response.send_message("You have already claimed this ticket!", ephemeral=True)
                else:
                    claimed_by_user = interaction.guild.get_member(int(ticket_info["claimed_by"]))
                    claimed_by_name = claimed_by_user.name if claimed_by_user else "Another admin"
                    await interaction.response.send_message(f"This ticket is already claimed by {claimed_by_name}!", ephemeral=True)
                return
            
            # Claim the ticket
            ticket_info["claimed_by"] = str(user.id)
            
            # Update button to show claimed status
            self.children[1].disabled = True
            self.children[1].label = f"🙋 Claimed by {user.name}"
            
            # Send confirmation message
            embed = discord.Embed(
                title="Ticket Claimed",
                description=f"{user.mention} has claimed this ticket and will be assisting you.",
                color=0x77dd77
            )
            
            await interaction.response.edit_message(view=self)
            await channel.send(embed=embed)
            
            # Log ticket claim
            logger.info(f"Ticket #{ticket_info['number']} claimed by {user.name} ({user.id})")
            
        except Exception as e:
            logger.error(f"Error in claim_ticket: {e}")
            await interaction.response.send_message(f"An error occurred while claiming the ticket. Error: {e}", ephemeral=True)

class TicketCloseConfirmView(ui.View):
    """View for confirming ticket closure"""
    def __init__(self):
        super().__init__(timeout=60)  # 60 second timeout
    
    @ui.button(label="✅ Confirm Close", style=ButtonStyle.danger, custom_id="confirm_close")
    async def confirm_close(self, interaction: discord.Interaction, button: ui.Button):
        """Confirm ticket closure"""
        channel = interaction.channel
        
        try:
            # Get ticket data
            ticket_info = ticket_data["tickets"][str(channel.id)]
            ticket_creator_id = ticket_info["user_id"]
            ticket_number = ticket_info["number"]
            
            # Send closing message
            embed = discord.Embed(
                title="Ticket Closing",
                description="This ticket will be closed in 5 seconds...",
                color=0xff5555
            )
            
            # Send the confirmation message
            await interaction.response.edit_message(embed=embed, view=None)
            
            # Send channel message
            await channel.send(embed=discord.Embed(
                title="Ticket Closed",
                description=f"Ticket #{ticket_number} has been closed by {interaction.user.mention}.",
                color=0xff5555
            ))
            
            # Wait 5 seconds before deleting
            await asyncio.sleep(5)
            
            # Clean up ticket data
            if str(channel.id) in ticket_data["tickets"]:
                del ticket_data["tickets"][str(channel.id)]
            
            if str(ticket_creator_id) in ticket_data["user_tickets"]:
                del ticket_data["user_tickets"][str(ticket_creator_id)]
            
            # Delete the channel
            await channel.delete(reason=f"Ticket #{ticket_number} closed by {interaction.user.name}")
            
            # Log ticket closure
            logger.info(f"Ticket #{ticket_number} closed by {interaction.user.name} ({interaction.user.id})")
            
        except Exception as e:
            logger.error(f"Error in confirm_close: {e}")
            try:
                await interaction.followup.send(f"An error occurred while closing the ticket. Error: {e}", ephemeral=True)
            except:
                pass
    
    @ui.button(label="❌ Cancel", style=ButtonStyle.secondary, custom_id="cancel_close")
    async def cancel_close(self, interaction: discord.Interaction, button: ui.Button):
        """Cancel ticket closure"""
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="Ticket Closure Cancelled",
                description="The ticket will remain open.",
                color=0x77dd77
            ),
            view=None
        )

@bot.command(name="serverbackup")
@commands.has_permissions(administrator=True)
async def server_backup_cmd(ctx):
    """Create a backup of the server configuration (Admin only)"""
    await ctx.message.add_reaction("⏳")  # Processing emoji
    
    try:
        # Create a backup
        backup_id, timestamp = await server_backup.create_backup(ctx.guild)
        
        if backup_id:
            embed = discord.Embed(
                title="🔄 Server Backup Created",
                description=f"Backup #{backup_id} created successfully!",
                color=0x00ff00
            )
            embed.add_field(name="Timestamp", value=timestamp, inline=False)
            embed.add_field(name="Guild", value=ctx.guild.name, inline=False)
            embed.add_field(
                name="Usage",
                value=f"To restore this backup, use the command:\n`!backuprestore {backup_id}`",
                inline=False
            )
            embed.set_footer(text="『STAND』The World! Time has been frozen and the server state saved!")
            
            await ctx.message.remove_reaction("⏳", ctx.bot.user)
            await ctx.message.add_reaction("✅")
            await ctx.send(embed=embed)
        else:
            await ctx.message.remove_reaction("⏳", ctx.bot.user)
            await ctx.message.add_reaction("❌")
            await ctx.send("Failed to create server backup. Check logs for details.")
    except Exception as e:
        await ctx.message.remove_reaction("⏳", ctx.bot.user)
        await ctx.message.add_reaction("❌")
        await ctx.send(f"Error creating backup: {str(e)}")

@bot.command(name="listbackups")
@commands.has_permissions(administrator=True)
async def list_backups_cmd(ctx):
    """List all server backups (Admin only)"""
    try:
        # Get backups
        backups = await server_backup.list_backups(ctx.guild.id)
        
        if not backups:
            await ctx.send("No backups found for this server.")
            return
            
        embed = discord.Embed(
            title="📋 Server Backups",
            description=f"Found {len(backups)} backup(s) for {ctx.guild.name}",
            color=0x9966cc
        )
        
        for backup in backups:
            embed.add_field(
                name=f"Backup #{backup['id']}",
                value=f"Created: {backup['timestamp']}\nCommand: `!backuprestore {backup['id']}`",
                inline=True
            )
            
        embed.set_footer(text="『STAND』Killer Queen has already touched those backups!")
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"Error listing backups: {str(e)}")

@bot.command(name="backuprestore")
@commands.has_permissions(administrator=True)
async def backup_restore_cmd(ctx, backup_id: int = None):
    """Restore a server backup (Admin only)"""
    if backup_id is None:
        await ctx.send("Please specify a backup ID to restore. Use `!listbackups` to see available backups.")
        return
        
    # Confirm restoration
    confirmation_embed = discord.Embed(
        title="⚠️ Confirm Backup Restoration",
        description=f"Are you sure you want to restore backup #{backup_id}?\n\nThis will make changes to your server configuration.",
        color=0xff9900
    )
    confirmation_embed.set_footer(text="Respond with 'yes' to confirm or 'no' to cancel.")
    
    await ctx.send(embed=confirmation_embed)
    
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in ["yes", "no"]
        
    try:
        msg = await bot.wait_for("message", check=check, timeout=30.0)
        
        if msg.content.lower() == "no":
            await ctx.send("Backup restoration cancelled.")
            return
            
        # User confirmed, proceed with restoration
        await ctx.message.add_reaction("⏳")  # Processing emoji
        
        success, message = await server_backup.restore_backup(ctx.guild, backup_id)
        
        if success:
            embed = discord.Embed(
                title="🔄 Server Backup Restored",
                description=f"Backup #{backup_id} restored successfully!",
                color=0x00ff00
            )
            embed.add_field(name="Details", value=message, inline=False)
            embed.set_footer(text="『STAND』Crazy Diamond has restored the server!")
            
            await ctx.message.remove_reaction("⏳", ctx.bot.user)
            await ctx.message.add_reaction("✅")
            await ctx.send(embed=embed)
        else:
            await ctx.message.remove_reaction("⏳", ctx.bot.user)
            await ctx.message.add_reaction("❌")
            await ctx.send(f"Failed to restore backup: {message}")
    except asyncio.TimeoutError:
        await ctx.send("Restoration cancelled - you didn't respond in time.")
    except Exception as e:
        await ctx.send(f"Error restoring backup: {str(e)}")

@bot.command(name="lock")
@commands.has_permissions(manage_channels=True)
async def lock_channel(ctx, *, reason=None):
    """Lock the current channel (Admins only)"""
    channel = ctx.channel
    
    # Get the default role (@everyone) for the guild
    default_role = ctx.guild.default_role
    
    # Set permissions to deny sending messages for the default role
    overwrite = channel.overwrites_for(default_role)
    
    # Check if already locked
    if overwrite.send_messages is False:
        await ctx.send("This channel is already locked! 🔒")
        return
    
    # Update overwrites to deny send_messages
    overwrite.update(send_messages=False)
    await channel.set_permissions(default_role, overwrite=overwrite)
    
    # Create animated lock sequence with JoJo-themed response
    lock_animation = [
        "```\n⚙️ Activating Stand...\n```",
        "```\n⚙️ 「STAR PLATINUM」 Ability Charging... [▯▯▯▯▯▯▯▯▯▯] 0%\n```",
        "```\n⚙️ 「STAR PLATINUM」 Ability Charging... [▮▯▯▯▯▯▯▯▯▯] 10%\n```",
        "```\n⚙️ 「STAR PLATINUM」 Ability Charging... [▮▮▮▯▯▯▯▯▯▯] 30%\n```",
        "```\n⚙️ 「STAR PLATINUM」 Ability Charging... [▮▮▮▮▮▯▯▯▯▯] 50%\n```",
        "```\n⚙️ 「STAR PLATINUM」 Ability Charging... [▮▮▮▮▮▮▮▯▯▯] 70%\n```",
        "```\n⚙️ 「STAR PLATINUM」 Ability Charging... [▮▮▮▮▮▮▮▮▮▯] 90%\n```",
        "```\n⚙️ 「STAR PLATINUM」 Ability Ready! [▮▮▮▮▮▮▮▮▮▮] 100%\n```",
        "```\n🌟 STAR PLATINUM: ZA WARUDO! ⏱️\n```",
        "```\n\n     ⏱️ T I M E  H A S  S T O P P E D ⏱️\n```"
    ]
    
    # Send initial message and start animation
    lock_msg = await ctx.send(lock_animation[0])
    
    # Animate through each step
    for i in range(1, len(lock_animation)):
        await asyncio.sleep(0.7)  # Delay between animation frames
        await lock_msg.edit(content=lock_animation[i])
    
    await asyncio.sleep(1)  # Pause before final message
    
    # Create a success embed with JoJo-themed response
    embed = discord.Embed(
        title="🔒 Channel Locked",
        description=f"This channel has been locked by {ctx.author.mention}.",
        color=0xFF5733
    )
    
    if reason:
        embed.add_field(name="Reason", value=reason, inline=False)
    
    embed.add_field(
        name="Status", 
        value="🔒 **LOCKED**: Only administrators can send messages.", 
        inline=False
    )
    
    embed.set_footer(text="『STAND』Star Platinum has stopped time in this channel!")
    
    # Delete animation message and send final embed
    await lock_msg.delete()
    await ctx.send(embed=embed)

@bot.command(name="unlock")
@commands.has_permissions(manage_channels=True)
async def unlock_channel(ctx):
    """Unlock the current channel (Admins only)"""
    channel = ctx.channel
    
    # Get the default role (@everyone) for the guild
    default_role = ctx.guild.default_role
    
    # Get current permissions
    overwrite = channel.overwrites_for(default_role)
    
    # Check if already unlocked
    if overwrite.send_messages is not False:
        await ctx.send("This channel is already unlocked! 🔓")
        return
    
    # Update overwrites to allow send_messages (None = default)
    overwrite.update(send_messages=None)
    await channel.set_permissions(default_role, overwrite=overwrite)
    
    # Create animated unlock sequence with JoJo-themed response
    unlock_animation = [
        "```\n⏱️ Time is still stopped...\n```",
        "```\n⏱️ Time is starting to flow...\n```",
        "```\n⚡ 「STAR PLATINUM」 Releasing time stop...\n```",
        "```\n⚡ 3...\n```",
        "```\n⚡ 2...\n```", 
        "```\n⚡ 1...\n```",
        "```\n\n    🌊 T I M E  F L O W S  A G A I N 🌊\n```"
    ]
    
    # Send initial message and start animation
    unlock_msg = await ctx.send(unlock_animation[0])
    
    # Animate through each step
    for i in range(1, len(unlock_animation)):
        await asyncio.sleep(0.7)  # Delay between animation frames
        await unlock_msg.edit(content=unlock_animation[i])
    
    await asyncio.sleep(1)  # Pause before final message
    
    # Create a success embed with JoJo-themed response
    embed = discord.Embed(
        title="🔓 Channel Unlocked",
        description=f"This channel has been unlocked by {ctx.author.mention}.",
        color=0x33FF57
    )
    
    embed.add_field(
        name="Status", 
        value="🔓 **UNLOCKED**: Everyone can send messages again.", 
        inline=False
    )
    
    embed.set_footer(text="『STAND』Time has resumed in this channel!")
    
    # Delete animation message and send final embed
    await unlock_msg.delete()
    await ctx.send(embed=embed)

@bot.command(name="verify_setup")
@commands.has_permissions(administrator=True)
async def verify_setup(ctx):
    """Set up a verification message with button"""
    guild = ctx.guild
    global UNVERIFIED_ROLE_ID, VERIFIED_ROLE_ID
    
    # Delete the command message to keep the channel clean
    try:
        await ctx.message.delete()
    except Exception as e:
        logger.error(f"Failed to delete command message: {e}")
    
    # Check for verified and unverified roles
    verified_role = get_role_safe(guild, VERIFIED_ROLE_ID, "Verified")
        
    # Create verified role if it doesn't exist
    if not verified_role:
        try:
            verified_role = await guild.create_role(
                name="Verified",
                color=discord.Color.green(),
                reason="Created by JoJo bot for verification system"
            )
            await ctx.send(f"✅ Created Verified role: {verified_role.mention}")
            # Update the global ID
            VERIFIED_ROLE_ID = verified_role.id
        except Exception as e:
            await ctx.send(f"❌ Failed to create Verified role: {e}")
            return
    
    # Find unverified role by name or ID
    unverified_role = get_role_safe(guild, UNVERIFIED_ROLE_ID, "Unverified")
    
    # Create unverified role if it doesn't exist
    if not unverified_role:
        try:
            unverified_role = await guild.create_role(
                name="Unverified",
                color=discord.Color.dark_gray(),
                reason="Created by JoJo bot for verification system"
            )
            await ctx.send(f"✅ Created Unverified role: {unverified_role.mention}")
            # Update the global ID
            UNVERIFIED_ROLE_ID = unverified_role.id
        except Exception as e:
            await ctx.send(f"❌ Failed to create Unverified role: {e}")
            return
    else:
        UNVERIFIED_ROLE_ID = unverified_role.id
            
    # Create verification embed
    embed = discord.Embed(
        title="Server Verification",
        description="To access the rest of the server, you must verify yourself.\n\n"
                   "Click the button below to verify and gain access to all channels!",
        color=0x7289da
    )
    
    # Add some flair
    embed.add_field(
        name="Why Verify?",
        value="Verification helps us keep the server safe from bots and raiders.",
        inline=False
    )
    
    embed.add_field(
        name="What's Next?",
        value="After verification, you'll gain access to all channels and the JoJo game system!",
        inline=False
    )
    
    # Add a JoJo-themed quote
    embed.add_field(
        name="Stand Proud",
        value=f"\"*{get_random_jojo_quote()}*\"",
        inline=False
    )
    
    embed.set_footer(text="JoJo's Bizarre Discord Bot | Verification System")
    
    # Send the embed with the verify button
    await ctx.send(embed=embed, view=VerifyButton())
    
    # Confirm to admin
    await ctx.send(f"✅ Verification system has been set up with roles: Verified ({verified_role.id}) and Unverified ({unverified_role.id})!", delete_after=10)

# Command to fix channel permissions for unverified users
@bot.command(name="setupperms")
@commands.has_permissions(administrator=True)
async def setup_permissions(ctx):
    """Fix channel permissions to hide channels from unverified users"""
    # Delete the command message to keep the channel clean
    try:
        await ctx.message.delete()
    except Exception as e:
        logger.error(f"Failed to delete command message: {e}")
    
    # Get the guild and send an initial status message
    guild = ctx.guild
    status_msg = await ctx.send("🔄 Setting up verification permissions...")
    
    # Get or create roles
    unverified_role = get_role_safe(guild, UNVERIFIED_ROLE_ID, "Unverified")
    verified_role = get_role_safe(guild, VERIFIED_ROLE_ID, "Verified")
    
    # If unverified role doesn't exist, create it
    if not unverified_role:
        try:
            unverified_role = await guild.create_role(
                name="Unverified",
                color=discord.Color.dark_gray(),
                reason="Created by JoJo bot for verification system"
            )
            await status_msg.edit(content=f"✅ Created Unverified role\n🔄 Setting up permissions...")
            # Update the ID (no need for global here since it's already defined)
            UNVERIFIED_ROLE_ID = unverified_role.id
        except Exception as e:
            await status_msg.edit(content=f"❌ Failed to create Unverified role: {e}")
            return
    
    # If verified role doesn't exist, create it
    if not verified_role:
        try:
            verified_role = await guild.create_role(
                name="Verified",
                color=discord.Color.green(),
                reason="Created by JoJo bot for verification system"
            )
            await status_msg.edit(content=f"✅ Created Verified role\n🔄 Setting up permissions...")
            # Update the ID (no need for global here)
            VERIFIED_ROLE_ID = verified_role.id
        except Exception as e:
            await status_msg.edit(content=f"❌ Failed to create Verified role: {e}")
            return
    
    # Find welcome/verification channel that unverified users should see
    welcome_channel = guild.get_channel(WELCOME_CHANNEL_ID)
    if not welcome_channel:
        # Try to find by name if ID doesn't work
        for channel_name in ["verify", "verification", "welcome", "rules"]:
            channel = discord.utils.get(guild.text_channels, name=channel_name)
            if channel:
                welcome_channel = channel
                await status_msg.edit(content=f"✅ Found welcome channel: #{channel.name}\n🔄 Fixing permissions...")
                break
    
    # Get all channels in the server
    await status_msg.edit(content="🔄 Fixing permissions for all channels...")
    
    # Count for progress tracking
    total_channels = len(guild.channels)
    processed = 0
    successful = 0
    
    for channel in guild.channels:
        # Skip welcome channel
        if welcome_channel and channel.id == welcome_channel.id:
            # Special handling for welcome channel - allow view but not send
            try:
                await channel.set_permissions(
                    unverified_role, 
                    read_messages=True,
                    view_channel=True,
                    send_messages=False
                )
                successful += 1
                logger.info(f"Set special permissions for welcome channel {channel.name}")
            except Exception as e:
                logger.error(f"Failed to set welcome channel permissions: {e}")
                
            processed += 1
            continue
            
        try:
            # Categories need special handling
            if isinstance(channel, discord.CategoryChannel):
                # Make category invisible to unverified users
                await channel.set_permissions(
                    unverified_role,
                    read_messages=False,
                    view_channel=False
                )
                
                # Make category visible to verified users
                await channel.set_permissions(
                    verified_role,
                    read_messages=True,
                    view_channel=True
                )
            else:
                # Handle text and voice channels
                # All channels should be visible but unverified users cannot send messages
                await channel.set_permissions(
                    unverified_role,
                    read_messages=True,
                    view_channel=True,
                    send_messages=False,  # Can see but not send messages
                    connect=False,  # Cannot join voice channels
                    speak=False    # Cannot speak in voice channels
                )
                
                # Make all channels visible to verified users
                await channel.set_permissions(
                    verified_role,
                    read_messages=True,
                    view_channel=True
                )
        except discord.Forbidden:
            await ctx.send(f"⚠️ Bot doesn't have permission to edit channel {channel.name}")
        except Exception as e:
            await ctx.send(f"⚠️ Error setting permissions for {channel.name}: {e}")
        
        # Update progress
        processed += 1
        if processed % 5 == 0 or processed == total_channels:
            progress = int((processed / total_channels) * 100)
            await status_msg.edit(content=f"🔄 Fixing permissions... {progress}% complete")
    
    embed = discord.Embed(
        title="✅ Permission Fix Complete!",
        description="All channels have been updated with the correct permissions:\n\n"
                   f"• **{verified_role.name}**: Can see and use all channels\n"
                   f"• **{unverified_role.name}**: Can see channels but cannot send messages",
        color=0x00ff00
    )
    embed.add_field(
        name="Next Steps",
        value="1. Make sure new users get the Unverified role automatically\n"
              "2. Use `!verify_setup` to create a verification button",
        inline=False
    )
    
    await ctx.send(embed=embed)

# Add cleanup function for when bot exits
def cleanup():
    """Clean up resources when bot exits"""
    try:
        # Remove lock file
        if os.path.exists(BOT_LOCK_FILE):
            lock_info = ""
            try:
                with open(BOT_LOCK_FILE, "r") as f:
                    lock_info = f.read().strip()
            except:
                pass
                
            if INSTANCE_ID in lock_info:
                os.remove(BOT_LOCK_FILE)
                logger.info("Removed lock file on exit")
            else:
                logger.warning(f"Lock file belongs to another instance. Not removing.")
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

# Register the cleanup function to run at exit
import atexit
atexit.register(cleanup)

# Create a MusicPlayer instance
music_player = MusicPlayer(bot)

# Music commands (these won't show up in help)
@bot.command(name="play", help="Play a song from YouTube or Spotify")
async def play(ctx, *, query=None):
    """Play a song from YouTube or Spotify"""
    embed = discord.Embed(
        title="🎵 Music Player Temporarily Unavailable",
        description="The music player functionality is currently under maintenance.",
        color=0xFF5733
    )
    embed.add_field(
        name="Reason", 
        value="YouTube API changes have affected our music player. We're working on a fix!", 
        inline=False
    )
    embed.add_field(
        name="Status", 
        value="🚧 Maintenance Mode", 
        inline=False
    )
    embed.set_footer(text="『STAND』Sticky Fingers has hidden the music player for now!")
    await ctx.send(embed=embed)

@bot.command(name="leave", help="Leave the voice channel")
async def leave(ctx):
    """Leave the voice channel"""
    embed = discord.Embed(
        title="🎵 Music Player Temporarily Unavailable",
        description="The music player functionality is currently under maintenance.",
        color=0xFF5733
    )
    embed.set_footer(text="『STAND』Sticky Fingers has hidden the music player for now!")
    await ctx.send(embed=embed)

@bot.command(name="skip", help="Skip the current song")
async def skip(ctx):
    """Skip the current song"""
    embed = discord.Embed(
        title="🎵 Music Player Temporarily Unavailable",
        description="The music player functionality is currently under maintenance.",
        color=0xFF5733
    )
    embed.set_footer(text="『STAND』Sticky Fingers has hidden the music player for now!")
    await ctx.send(embed=embed)

@bot.command(name="queue", help="Show the music queue")
async def queue(ctx):
    """Show the current queue"""
    embed = discord.Embed(
        title="🎵 Music Player Temporarily Unavailable",
        description="The music player functionality is currently under maintenance.",
        color=0xFF5733
    )
    embed.set_footer(text="『STAND』Sticky Fingers has hidden the music player for now!")
    await ctx.send(embed=embed)

@bot.command(name="clearqueue", aliases=["clear_queue"], help="Clear the music queue")
async def clear_queue(ctx):
    """Clear the music queue"""
    embed = discord.Embed(
        title="🎵 Music Player Temporarily Unavailable",
        description="The music player functionality is currently under maintenance.",
        color=0xFF5733
    )
    embed.set_footer(text="『STAND』Sticky Fingers has hidden the music player for now!")
    await ctx.send(embed=embed)

@bot.command(name="pause", help="Pause the current song")
async def pause(ctx):
    """Pause the current song"""
    embed = discord.Embed(
        title="🎵 Music Player Temporarily Unavailable",
        description="The music player functionality is currently under maintenance.",
        color=0xFF5733
    )
    embed.set_footer(text="『STAND』Sticky Fingers has hidden the music player for now!")
    await ctx.send(embed=embed)

@bot.command(name="resume", help="Resume the paused song")
async def resume(ctx):
    """Resume the paused song"""
    embed = discord.Embed(
        title="🎵 Music Player Temporarily Unavailable",
        description="The music player functionality is currently under maintenance.",
        color=0xFF5733
    )
    embed.set_footer(text="『STAND』Sticky Fingers has hidden the music player for now!")
    await ctx.send(embed=embed)

@bot.command(name="np", aliases=["nowplaying", "now_playing"], help="Show the currently playing song")
async def nowplaying(ctx):
    """Show the currently playing song"""
    embed = discord.Embed(
        title="🎵 Music Player Temporarily Unavailable",
        description="The music player functionality is currently under maintenance.",
        color=0xFF5733
    )
    embed.set_footer(text="『STAND』Sticky Fingers has hidden the music player for now!")
    await ctx.send(embed=embed)

# Start the keep-alive web server
keep_alive()

# Run the bot with our token
if TOKEN:
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        cleanup()  # Ensure cleanup happens even if the bot crashes
else:
    print("ERROR: No Discord token found. Make sure to set the DISCORD_TOKEN in your .env file.")