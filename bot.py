import asyncio
import os
from collections import deque

import discord
from discord.ext import commands
from dotenv import load_dotenv
from yt_dlp import YoutubeDL

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("Missing DISCORD_TOKEN in environment.")

BOT_NAME = os.getenv("BOT_NAME", "Dip")
PREFIX = os.getenv("BOT_PREFIX", "!")

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)
_synced = False
GUILD_ID = 1203534396091662416

# Audio config
FFMPEG_OPTIONS = {
    "before_options": (
        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
        "-reconnect_on_network_error 1 -rw_timeout 5000000"
    ),
    "options": (
        "-vn -b:a 160k -vbr on -application audio -compression_level 10 "
        "-ar 48000 -ac 2 -af aresample=async=1:first_pts=0"
    ),
}
YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
    "js_runtimes": ["node"],
}
ytdl = YoutubeDL(YTDL_OPTIONS)

queues = {}
voice_clients = {}
idle_tasks = {}
IDLE_TIMEOUT_SECONDS = 300


@bot.event
async def on_ready():
    global _synced
    if not _synced:
        guild = discord.Object(id=GUILD_ID)
        await bot.tree.sync(guild=guild)
        _synced = True
    print(f"{BOT_NAME} online as {bot.user}")


@bot.tree.command(
    name="ping",
    description="Check if the bot is alive.",
    guild=discord.Object(id=GUILD_ID),
)
async def ping_slash(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!")


def _is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


async def _extract_song(query: str) -> dict:
    search = query if _is_url(query) else f"ytsearch1:{query}"
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search, download=False))
    if "entries" in data:
        data = data["entries"][0]
    return {
        "title": data.get("title") or "Unknown title",
        "webpage_url": data.get("webpage_url") or query,
        "stream_url": data.get("url"),
    }


async def _play_next(guild_id: int):
    voice = voice_clients.get(guild_id)
    queue = queues.get(guild_id)
    if not voice:
        return
    if not queue or len(queue) == 0:
        _start_idle_timer(guild_id)
        return
    if voice.is_playing() or voice.is_paused():
        return
    song = queue.popleft()
    _cancel_idle_timer(guild_id)
    source = discord.FFmpegOpusAudio(song["stream_url"], **FFMPEG_OPTIONS)

    def _after_play(error):
        if error:
            print(f"Playback error: {error}")
        asyncio.run_coroutine_threadsafe(_play_next(guild_id), bot.loop)

    voice.play(source, after=_after_play)
    _cancel_idle_timer(guild_id)


async def _ensure_voice(interaction: discord.Interaction) -> discord.VoiceClient | None:
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("This command only works in a server.")
        return None
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message("Join a voice channel first.")
        return None
    channel = interaction.user.voice.channel
    voice = voice_clients.get(interaction.guild_id)
    if voice and voice.is_connected():
        if voice.channel != channel:
            await voice.move_to(channel)
        _cancel_idle_timer(interaction.guild_id)
        return voice
    voice = await channel.connect()
    voice_clients[interaction.guild_id] = voice
    _cancel_idle_timer(interaction.guild_id)
    queue = queues.get(interaction.guild_id)
    if not queue and not voice.is_playing():
        _start_idle_timer(interaction.guild_id)
    return voice


def _cancel_idle_timer(guild_id: int):
    task = idle_tasks.pop(guild_id, None)
    if task and not task.done():
        task.cancel()


def _start_idle_timer(guild_id: int):
    _cancel_idle_timer(guild_id)

    async def _idle_disconnect():
        try:
            await asyncio.sleep(IDLE_TIMEOUT_SECONDS)
            voice = voice_clients.get(guild_id)
            queue = queues.get(guild_id)
            if not voice or not voice.is_connected():
                return
            if voice.is_playing() or voice.is_paused():
                return
            if queue:
                return
            await voice.disconnect()
            voice_clients.pop(guild_id, None)
            queues.pop(guild_id, None)
        except asyncio.CancelledError:
            return

    idle_tasks[guild_id] = bot.loop.create_task(_idle_disconnect())


@bot.tree.command(
    name="join",
    description="Join your voice channel.",
    guild=discord.Object(id=GUILD_ID),
)
async def join_slash(interaction: discord.Interaction):
    voice = await _ensure_voice(interaction)
    if voice:
        await interaction.response.send_message("Joined voice channel.")
        if not voice.is_playing():
            _start_idle_timer(interaction.guild_id)


@bot.tree.command(
    name="leave",
    description="Leave the voice channel and clear the queue.",
    guild=discord.Object(id=GUILD_ID),
)
async def leave_slash(interaction: discord.Interaction):
    voice = voice_clients.get(interaction.guild_id)
    if not voice or not voice.is_connected():
        await interaction.response.send_message("I'm not in a voice channel.")
        return
    _cancel_idle_timer(interaction.guild_id)
    queues.pop(interaction.guild_id, None)
    await voice.disconnect()
    voice_clients.pop(interaction.guild_id, None)
    await interaction.response.send_message("Left voice channel and cleared the queue.")


@bot.tree.command(
    name="play",
    description="Play a song from YouTube or a direct URL.",
    guild=discord.Object(id=GUILD_ID),
)
async def play_slash(interaction: discord.Interaction, query: str):
    voice = await _ensure_voice(interaction)
    if not voice:
        return
    await interaction.response.defer()
    try:
        song = await _extract_song(query)
    except Exception:
        await interaction.followup.send("Couldn't find or load that audio.")
        return
    queue = queues.setdefault(interaction.guild_id, deque())
    queue.append(song)
    await interaction.followup.send(f"Queued: {song['title']}")
    await _play_next(interaction.guild_id)


@bot.tree.command(
    name="queue",
    description="Show the current queue.",
    guild=discord.Object(id=GUILD_ID),
)
async def queue_slash(interaction: discord.Interaction):
    queue = queues.get(interaction.guild_id)
    if not queue:
        await interaction.response.send_message("Queue is empty.")
        return
    items = list(queue)[:10]
    lines = [f"{idx + 1}. {item['title']}" for idx, item in enumerate(items)]
    await interaction.response.send_message("Up next:\n" + "\n".join(lines))


@bot.tree.command(
    name="skip",
    description="Skip the current song.",
    guild=discord.Object(id=GUILD_ID),
)
async def skip_slash(interaction: discord.Interaction):
    voice = voice_clients.get(interaction.guild_id)
    if not voice or not voice.is_connected() or not voice.is_playing():
        await interaction.response.send_message("Nothing is playing.")
        return
    voice.stop()
    _start_idle_timer(interaction.guild_id)
    await interaction.response.send_message("Skipped.")


@bot.tree.command(
    name="stop",
    description="Stop playback and clear the queue.",
    guild=discord.Object(id=GUILD_ID),
)
async def stop_slash(interaction: discord.Interaction):
    voice = voice_clients.get(interaction.guild_id)
    if not voice or not voice.is_connected():
        await interaction.response.send_message("I'm not in a voice channel.")
        return
    _cancel_idle_timer(interaction.guild_id)
    queues.pop(interaction.guild_id, None)
    if voice.is_playing() or voice.is_paused():
        voice.stop()
    _start_idle_timer(interaction.guild_id)
    await interaction.response.send_message("Stopped and cleared the queue.")


@bot.command()
async def ping(ctx):
    await ctx.reply("Pong!")


@bot.command()
async def name(ctx):
    await ctx.reply(f"My name is {BOT_NAME}.")


@bot.command()
async def say(ctx, *, text=None):
    if not text:
        await ctx.reply("Tell me what to say.")
        return
    await ctx.reply(text)


@bot.command(name="help")
async def help_command(ctx):
    await ctx.reply(
        f"Commands: {PREFIX}ping, {PREFIX}help, {PREFIX}name, {PREFIX}say <text>"
    )


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.reply(f"Unknown command. Try {PREFIX}help.")
        return
    await ctx.reply("Something went wrong.")
    raise error


bot.run(TOKEN)
