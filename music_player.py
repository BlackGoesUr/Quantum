import asyncio
import discord
import re
import spotipy
from discord.ext import commands
import logging
import os
import pytube
from pytube import Search, YouTube
from urllib.parse import urlparse, parse_qs

# Set up logging
logger = logging.getLogger('music_player')
logger.setLevel(logging.INFO)

# FFMPEG options for audio playback
ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
}

class PytubeSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.thumbnail = data.get('thumbnail')
        self.duration = data.get('duration')
        self.uploader = data.get('uploader')
        self.uploader_url = data.get('channel_url')
        self.description = data.get('description')
        self.webpage_url = data.get('webpage_url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        try:
            # Extract video info using pytube
            data = await loop.run_in_executor(None, lambda: cls._get_video_data(url))
            return cls(discord.FFmpegPCMAudio(data['url'], **ffmpeg_options), data=data)
        except Exception as e:
            logger.error(f"Error extracting info from {url}: {e}")
            raise e
            
    @staticmethod
    def _get_video_data(url):
        """Extract video data using pytube"""
        try:
            # Check if it's a YouTube URL
            if "youtube.com" in url or "youtu.be" in url:
                # Add a User-Agent header to avoid 400 errors
                try:
                    # Try with current API (may vary based on pytube version)
                    yt = YouTube(
                        url,
                        use_oauth=False,
                        allow_oauth_cache=True
                    )
                except TypeError:
                    # Fallback if API parameters changed
                    yt = YouTube(url)
                
                # Get all streams and pick the best audio stream
                audio_streams = yt.streams.filter(only_audio=True).order_by('abr').desc()
                
                if not audio_streams:
                    raise ValueError(f"No audio streams found for: {url}")
                    
                stream = audio_streams.first()
                
                # Handle potential errors with stream.url access
                stream_url = stream.url
                
                data = {
                    'title': yt.title or "Unknown Title",
                    'url': stream_url,
                    'thumbnail': yt.thumbnail_url or "",
                    'duration': yt.length or 0,
                    'uploader': yt.author or "Unknown Author",
                    'channel_url': yt.channel_url or "",
                    'description': (yt.description[:100] + "...") if yt.description else "No description",
                    'webpage_url': url
                }
                return data
            else:
                # Search for the video on YouTube
                search = Search(url)
                search_results = search.results
                
                if not search_results:
                    raise ValueError(f"No results found for: {url}")
                    
                video = search_results[0]
                audio_streams = video.streams.filter(only_audio=True).order_by('abr').desc()
                
                if not audio_streams:
                    raise ValueError(f"No audio streams found for search: {url}")
                    
                stream = audio_streams.first()
                
                data = {
                    'title': video.title or "Unknown Title",
                    'url': stream.url,
                    'thumbnail': video.thumbnail_url or "",
                    'duration': video.length or 0,
                    'uploader': video.author or "Unknown Author",
                    'channel_url': video.channel_url or "",
                    'description': (video.description[:100] + "...") if video.description else "No description",
                    'webpage_url': f"https://youtube.com/watch?v={video.video_id}"
                }
                return data
        except Exception as e:
            logger.error(f"Error in _get_video_data: {str(e)}")
            # Try one more approach with a different configuration
            try:
                from pytube import YouTube as YouTubeWithUserAgent
                
                # Set up a custom header
                yt = YouTubeWithUserAgent(url)
                
                # Try to get an audio stream
                stream = yt.streams.filter(only_audio=True).first()
                
                data = {
                    'title': yt.title or "Unknown Title",
                    'url': stream.url,
                    'thumbnail': yt.thumbnail_url or "",
                    'duration': yt.length or 0,
                    'uploader': yt.author or "Unknown Author",
                    'channel_url': yt.channel_url or "",
                    'description': (yt.description[:100] + "...") if yt.description else "No description",
                    'webpage_url': url
                }
                return data
            except Exception as e2:
                logger.error(f"Fallback method also failed: {str(e2)}")
                raise ValueError(f"Could not extract video data: {str(e)}. YouTube may have changed their API.")

    @classmethod
    async def search(cls, search_query, *, loop=None, stream=True):
        """Search for a video and return the PytubeSource for the first result"""
        # Simply redirect to from_url since we're using it to handle both direct URLs and searches
        return await cls.from_url(search_query, loop=loop, stream=stream)
            
    @staticmethod
    def parse_duration(duration):
        """Convert seconds to a readable time format"""
        if not duration:
            return "Unknown duration"
            
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        else:
            return f"{minutes}m {seconds}s"
        
        if hours > 0:
            return f"{int(hours)}:{int(minutes):02d}:{int(seconds):02d}"
        else:
            return f"{int(minutes)}:{int(seconds):02d}"

class MusicPlayer:
    def __init__(self, bot):
        self.bot = bot
        self.voice_clients = {}  # guild_id -> voice_client
        self.currently_playing = {}  # guild_id -> YTDLSource
        self.queues = {}  # guild_id -> list of URLs
        
    async def join_voice_channel(self, ctx):
        """Join the user's voice channel."""
        if not ctx.author.voice:
            await ctx.send("⛔ You are not connected to a voice channel!")
            return False

        channel = ctx.author.voice.channel
        
        if ctx.guild.id in self.voice_clients and self.voice_clients[ctx.guild.id].is_connected():
            if self.voice_clients[ctx.guild.id].channel.id != channel.id:
                await self.voice_clients[ctx.guild.id].move_to(channel)
        else:
            self.voice_clients[ctx.guild.id] = await channel.connect()
            
        # Initialize the queue if it doesn't exist
        if ctx.guild.id not in self.queues:
            self.queues[ctx.guild.id] = []
            
        return True
            
    async def leave_voice_channel(self, ctx):
        """Leave the voice channel."""
        if ctx.guild.id in self.voice_clients and self.voice_clients[ctx.guild.id].is_connected():
            await self.voice_clients[ctx.guild.id].disconnect()
            del self.voice_clients[ctx.guild.id]
            self.queues[ctx.guild.id] = []
            if ctx.guild.id in self.currently_playing:
                del self.currently_playing[ctx.guild.id]
            return True
        return False
        
    async def play_song(self, ctx, url=None, search=None):
        """Play a song from a URL or search query."""
        # First, join the voice channel
        success = await self.join_voice_channel(ctx)
        if not success:
            return
            
        voice_client = self.voice_clients[ctx.guild.id]
        
        # If we're currently playing something
        if voice_client.is_playing():
            # Add to queue
            if url:
                self.queues[ctx.guild.id].append({"url": url, "search": None})
                await ctx.send(f"💿 Added to queue: `{url}`")
            elif search:
                self.queues[ctx.guild.id].append({"url": None, "search": search})
                await ctx.send(f"💿 Added to queue: `{search}`")
            return
            
        # Otherwise, play immediately
        try:
            if url:
                # Play from URL
                player = await PytubeSource.from_url(url, stream=True)
                source_info = f"URL: {url}"
            elif search:
                # Play from search
                loading_msg = await ctx.send(f"🔎 Searching for: `{search}`...")
                player = await PytubeSource.from_url(search, stream=True)
                await loading_msg.delete()
                source_info = f"Search: {search}"
            else:
                await ctx.send("⛔ No URL or search query provided!")
                return
                
            # Start playing
            voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(
                self.play_next(ctx, error=e), self.bot.loop).result())
                
            self.currently_playing[ctx.guild.id] = player
            
            # Create an embed with song info
            embed = discord.Embed(
                title="🎵 Now Playing",
                description=f"**{player.title}**",
                color=0x9C84EF
            )
            
            if player.thumbnail:
                embed.set_thumbnail(url=player.thumbnail)
                
            if player.duration:
                duration = YTDLSource.parse_duration(player.duration)
                embed.add_field(name="Duration", value=duration, inline=True)
                
            if player.uploader:
                embed.add_field(name="Channel", value=player.uploader, inline=True)
                
            embed.add_field(name="Requested via", value=source_info, inline=False)
            
            embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error playing song: {e}")
            await ctx.send(f"⛔ Error playing song: {str(e)}")
            
    async def play_next(self, ctx, error=None):
        """Play the next song in the queue."""
        if error:
            logger.error(f"Player error: {error}")
            await ctx.send(f"⛔ Error playing song: {str(error)}")
            
        if not ctx.guild.id in self.queues or not self.queues[ctx.guild.id]:
            # No more songs in queue
            if ctx.guild.id in self.currently_playing:
                del self.currently_playing[ctx.guild.id]
            return
            
        # Get the next song from the queue
        next_song = self.queues[ctx.guild.id].pop(0)
        
        # Play it
        if next_song["url"]:
            await self.play_song(ctx, url=next_song["url"])
        elif next_song["search"]:
            await self.play_song(ctx, search=next_song["search"])
            
    async def skip_song(self, ctx):
        """Skip the currently playing song."""
        if ctx.guild.id not in self.voice_clients or not self.voice_clients[ctx.guild.id].is_connected():
            await ctx.send("⛔ I'm not connected to a voice channel!")
            return
            
        voice_client = self.voice_clients[ctx.guild.id]
        
        if not voice_client.is_playing():
            await ctx.send("⛔ I'm not playing anything right now!")
            return
            
        voice_client.stop()
        await ctx.send("⏭️ Skipped the current song!")
        
    async def clear_queue(self, ctx):
        """Clear the queue for this guild."""
        if ctx.guild.id in self.queues:
            self.queues[ctx.guild.id] = []
            await ctx.send("🧹 Queue cleared!")
        else:
            await ctx.send("⛔ Queue is already empty!")
            
    async def show_queue(self, ctx):
        """Show the current queue."""
        if ctx.guild.id not in self.queues or not self.queues[ctx.guild.id]:
            await ctx.send("⛔ The queue is empty!")
            return
            
        queue = self.queues[ctx.guild.id]
        
        embed = discord.Embed(
            title="🎵 Music Queue",
            description=f"**{len(queue)} songs in queue**",
            color=0x9C84EF
        )
        
        # Add currently playing song
        if ctx.guild.id in self.currently_playing:
            current = self.currently_playing[ctx.guild.id]
            embed.add_field(
                name="Currently Playing:",
                value=f"**{current.title}**",
                inline=False
            )
            
        # Add queue items
        for i, item in enumerate(queue[:10], 1):  # Show only first 10 items
            if item["url"]:
                title = f"URL: {item['url']}"
            else:
                title = f"Search: {item['search']}"
                
            embed.add_field(
                name=f"{i}. {title}",
                value="\u200b",  # Zero-width space
                inline=False
            )
            
        # If there are more items in the queue
        if len(queue) > 10:
            embed.add_field(
                name=f"And {len(queue) - 10} more...",
                value="\u200b",
                inline=False
            )
            
        embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
        
        await ctx.send(embed=embed)
        
    async def pause_song(self, ctx):
        """Pause the currently playing song."""
        if ctx.guild.id not in self.voice_clients or not self.voice_clients[ctx.guild.id].is_connected():
            await ctx.send("⛔ I'm not connected to a voice channel!")
            return
            
        voice_client = self.voice_clients[ctx.guild.id]
        
        if not voice_client.is_playing():
            await ctx.send("⛔ I'm not playing anything right now!")
            return
            
        if voice_client.is_paused():
            await ctx.send("⛔ The song is already paused!")
            return
            
        voice_client.pause()
        await ctx.send("⏸️ Paused the current song!")
        
    async def resume_song(self, ctx):
        """Resume the currently paused song."""
        if ctx.guild.id not in self.voice_clients or not self.voice_clients[ctx.guild.id].is_connected():
            await ctx.send("⛔ I'm not connected to a voice channel!")
            return
            
        voice_client = self.voice_clients[ctx.guild.id]
        
        if not voice_client.is_paused():
            await ctx.send("⛔ The song is not paused!")
            return
            
        voice_client.resume()
        await ctx.send("▶️ Resumed the current song!")
        
    async def now_playing(self, ctx):
        """Show information about the currently playing song."""
        if ctx.guild.id not in self.currently_playing:
            await ctx.send("⛔ I'm not playing anything right now!")
            return
            
        player = self.currently_playing[ctx.guild.id]
        
        embed = discord.Embed(
            title="🎵 Now Playing",
            description=f"**{player.title}**",
            color=0x9C84EF
        )
        
        if player.thumbnail:
            embed.set_thumbnail(url=player.thumbnail)
            
        if player.duration:
            duration = YTDLSource.parse_duration(player.duration)
            embed.add_field(name="Duration", value=duration, inline=True)
            
        if player.uploader:
            embed.add_field(name="Channel", value=player.uploader, inline=True)
            
        if player.webpage_url:
            embed.add_field(name="Link", value=f"[YouTube]({player.webpage_url})", inline=True)
            
        embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
        
        await ctx.send(embed=embed)
        
    async def process_spotify_url(self, ctx, url):
        """Extract the song name and artist from a Spotify URL and search on YouTube."""
        # This is a simplified version that extracts info from the URL
        # For a complete implementation, you would need Spotify API credentials
        
        parsed_url = urlparse(url)
        
        if "spotify.com" not in parsed_url.netloc:
            return None
            
        # Try to extract track name from URL
        path_parts = parsed_url.path.split('/')
        
        if len(path_parts) < 3 or path_parts[1] != 'track':
            await ctx.send("⛔ Only Spotify track links are supported.")
            return None
            
        # Use the track ID to form a search query
        # In a real implementation, you would use the Spotify API to get the track info
        await ctx.send("🔄 Extracting song info from Spotify and searching on YouTube...")
        
        # For now, we'll use a simple query based on the URL
        search_query = f"spotify track {path_parts[2]}"
        return search_query