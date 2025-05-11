# JoJo's Bizarre Discord Bot

A JoJo-themed Discord moderation bot with anti-swearing, message scanning, and moderation commands.

## Features

### Moderation Commands
- `!ban` - Ban a user from the server
- `!kick` - Kick a user from the server
- `!mute` - Timeout a user for a specified duration
- `!unmute` - Remove a timeout from a user
- `!move` - Move a user to a different voice channel
- `!clear` - Delete a specified number of messages

### Anti-Swearing System
- Automatically detects profanity and inappropriate language
- Sophisticated filter that catches bypass attempts
- Progressive timeout system (1-5 minutes) for repeat offenders
- JoJo-themed warnings

### Message Analysis
- `!scan` - Analyze a message with JoJo-themed responses
- Detects sentiment, questions, and other message characteristics

### Fun Commands
- `!hello` - Get a JoJo-themed greeting
- `!jojo` - Get a random JoJo quote
- `!stand` - Generate a Stand ability for yourself or a name
- `!poll` - Create a simple poll with reactions
- `!dm` - Get a DM from the bot with a JoJo quote
- `!assign` - Assign yourself the Gamer role
- `!remove` - Remove the Gamer role from yourself
- `!secret` - Secret command for users with the Gamer role

## Setup

1. Create a Discord bot in the [Discord Developer Portal](https://discord.com/developers/applications)
2. Enable the necessary intents (Message Content, Server Members, etc.)
3. Clone this repository
4. Create a `.env` file with your Discord bot token:
   ```
   DISCORD_TOKEN=your_token_here
   ```
5. Install the requirements:
   ```
   pip install -r requirements.txt
   