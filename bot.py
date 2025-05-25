import discord
from discord.ext import commands
import yt_dlp as youtube_dl
import asyncio
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import re
import os
from dotenv import load_dotenv

# --- Muat Environment Variables dari .env file ---
load_dotenv()

# --- Konfigurasi Awal & Kredensial ---
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
SPOTIPY_CLIENT_ID = os.getenv('SPOTIPY_CLIENT_ID')
SPOTIPY_CLIENT_SECRET = os.getenv('SPOTIPY_CLIENT_SECRET')
BOT_PREFIX = '$' # Kamu bisa ganti prefix ini
WATERMARK_TEXT = "Bot Music by @paatih" # Watermark kamu

# Validasi apakah kredensial sudah di-load
if not TOKEN:
    print("ERROR: DISCORD_BOT_TOKEN tidak ditemukan. Pastikan ada di file .env")
    exit()
if not SPOTIPY_CLIENT_ID or not SPOTIPY_CLIENT_SECRET:
    print("WARNING: SPOTIPY_CLIENT_ID atau SPOTIPY_CLIENT_SECRET tidak ditemukan. Fitur Spotify mungkin tidak berfungsi.")

# --- Intents Discord ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True

# Membuat custom help command agar bisa menyisipkan watermark
class CustomHelpCommand(commands.DefaultHelpCommand):
    def __init__(self, **options):
        super().__init__(**options)
        self.no_category = "Perintah Lainnya"
        self.command_attrs['help'] = "Menampilkan pesan bantuan ini."

    def get_ending_note(self):
        return f"{super().get_ending_note()}\n{WATERMARK_TEXT}"

    async def send_bot_help(self, mapping):
        embed = discord.Embed(title="📜 Daftar Perintah Bot Musik 📜", description=f"Gunakan `{BOT_PREFIX}[nama_perintah]` untuk menjalankan perintah.", color=discord.Color.purple())
        embed.set_thumbnail(url=bot.user.avatar.url if bot.user.avatar else None)

        for cog, commands_list in mapping.items():
            filtered_commands = await self.filter_commands(commands_list, sort=True)
            if filtered_commands:
                command_signatures = [self.get_command_signature(c) for c in filtered_commands]
                if command_signatures:
                    cog_name = getattr(cog, "qualified_name", "Tanpa Kategori")
                    # Jika kategori bawaan, sesuaikan namanya
                    if cog_name == "No Category": cog_name = self.no_category

                    embed.add_field(name=f"**🎶 {cog_name}**", value="\n".join(f"`{sig}` - {cmd.help or 'Tidak ada deskripsi.'}" for sig, cmd in zip(command_signatures, filtered_commands) if cmd.help), inline=False)


        embed.set_footer(text=self.get_ending_note())
        await self.get_destination().send(embed=embed)

    async def send_command_help(self, command):
        embed = discord.Embed(title=f"Bantuan untuk Perintah: `{self.get_command_signature(command)}`", color=discord.Color.dark_blue())
        embed.add_field(name="Deskripsi:", value=command.help or "Tidak ada deskripsi.", inline=False)
        if command.aliases:
            embed.add_field(name="Alias (Perintah Alternatif):", value=", ".join(f"`{alias}`" for alias in command.aliases), inline=False)
        embed.set_footer(text=self.get_ending_note())
        await self.get_destination().send(embed=embed)


bot = commands.Bot(command_prefix=BOT_PREFIX, intents=intents, help_command=CustomHelpCommand())

# --- Setup Spotipy (Spotify API Client) ---
sp = None
if SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET:
    try:
        auth_manager = SpotifyClientCredentials(client_id=SPOTIPY_CLIENT_ID, client_secret=SPOTIPY_CLIENT_SECRET)
        sp = spotipy.Spotify(auth_manager=auth_manager)
        print("Berhasil terhubung ke Spotify API.")
    except Exception as e:
        print(f"Gagal menghubungkan ke Spotify API: {e}.")
else:
    print("Kredensial Spotify tidak lengkap, fitur Spotify dinonaktifkan.")


# --- Opsi untuk yt-dlp & FFmpeg ---
YDL_OPTS = {
    'format': 'bestaudio/best',
    'outtmpl': 'downloads/%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
}

FFMPEG_OPTS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

music_queue = {}
current_song = {}

# --- Class YTDLSource ---
class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title', 'Judul Tidak Diketahui')
        self.url = data.get('webpage_url', '')
        self.duration = data.get('duration')
        self.uploader = data.get('uploader', 'Tidak Diketahui')
        self.thumbnail = data.get('thumbnail') # Tambahkan thumbnail

    @classmethod
    async def from_url(cls, url_or_search, *, loop=None, stream=False, ydl_opts_override=None):
        loop = loop or asyncio.get_event_loop()
        final_ydl_opts = YDL_OPTS.copy()
        if ydl_opts_override:
            final_ydl_opts.update(ydl_opts_override)

        if not re.match(r'http[s]?://', url_or_search):
            final_ydl_opts['default_search'] = 'ytsearch1' # Ambil 1 hasil terbaik untuk pencarian
        elif 'default_search' in final_ydl_opts: # Hapus default_search jika ini adalah URL
            del final_ydl_opts['default_search']
        
        try:
            with youtube_dl.YoutubeDL(final_ydl_opts) as ydl:
                data = await loop.run_in_executor(None, lambda: ydl.extract_info(url_or_search, download=not stream))
        except Exception as e:
            print(f"Error yt-dlp untuk '{url_or_search}': {e}")
            raise
        if 'entries' in data:
            data = data['entries'][0]
        filename = data['url'] if stream else ydl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTS), data=data)

# --- Fungsi Helper & Event ---
async def play_next(ctx):
    guild_id = ctx.guild.id
    if guild_id in music_queue and music_queue[guild_id]:
        next_item = music_queue[guild_id].pop(0)
        display_title, query_to_play_with_yt_dlp, original_url_for_display, item_thumbnail = "Lagu Berikutnya", "", "", None

        if isinstance(next_item, dict):
            display_title = f"{next_item.get('artist', '')} - {next_item.get('title', 'Judul Tidak Ada')}".strip(" - ")
            query_to_play_with_yt_dlp = next_item['query_for_yt_dlp']
            if 'spotify_url' in next_item and next_item['spotify_url']:
                original_url_for_display = f" ([Spotify]({next_item['spotify_url']}))"
            item_thumbnail = next_item.get('thumbnail')
        else:
            query_to_play_with_yt_dlp = next_item
        
        try:
            player = await YTDLSource.from_url(query_to_play_with_yt_dlp, loop=bot.loop, stream=True)
            if not display_title or display_title == "Lagu Berikutnya": display_title = player.title
            if not original_url_for_display and player.url: original_url_for_display = f" ([Link Asli]({player.url}))"
            if not item_thumbnail: item_thumbnail = player.thumbnail


            ctx.voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(check_after_play(ctx, e), bot.loop).result())
            current_song[guild_id] = {"title": display_title, "thumbnail": item_thumbnail, "url_display": original_url_for_display, "duration": player.duration, "uploader": player.uploader}
            
            embed = discord.Embed(title="🎧 Memutar Sekarang", description=f"**[{display_title}]({player.url if player.url else '#'})**{original_url_for_display}", color=discord.Color.green())
            if item_thumbnail: embed.set_thumbnail(url=item_thumbnail)
            if player.duration: embed.add_field(name="Durasi", value=f"{int(player.duration // 60)}:{int(player.duration % 60):02d}", inline=True)
            if player.uploader: embed.add_field(name="Uploader/Artis", value=player.uploader, inline=True)
            embed.set_footer(text=WATERMARK_TEXT)
            await ctx.send(embed=embed)
        except Exception as e:
            error_title = display_title if display_title != "Lagu Berikutnya" else query_to_play_with_yt_dlp
            print(f"Error saat memutar '{error_title}': {e}")
            embed = discord.Embed(title="⚠️ Gagal Memutar Lagu", description=f"Maaf, gagal memutar: **{error_title}**.\nMungkin link rusak atau lagu tidak tersedia.\nError: `{type(e).__name__}`", color=discord.Color.red())
            embed.set_footer(text=WATERMARK_TEXT)
            await ctx.send(embed=embed)
            await play_next(ctx)
    else:
        current_song.pop(guild_id, None)
        embed = discord.Embed(title="Antrian Habis", description="Tidak ada lagi lagu di antrian.", color=discord.Color.gold())
        embed.set_footer(text=WATERMARK_TEXT)
        await ctx.send(embed=embed)

async def check_after_play(ctx, error):
    if error:
        print(f'Error setelah lagu selesai: {error}')
        embed = discord.Embed(title="⚠️ Error Pemutaran", description=f"Terjadi error saat lagu selesai: `{error}`.\nMencoba memutar lagu berikutnya jika ada.", color=discord.Color.orange())
        embed.set_footer(text=WATERMARK_TEXT)
        await ctx.send(embed=embed)
    await play_next(ctx)

@bot.event
async def on_ready():
    print(f'Bot {bot.user.name} (ID: {bot.user.id}) sudah online!')
    print(f'Prefix perintah: {BOT_PREFIX}')
    print(f'Terhubung ke Spotify API: {"Ya" if sp else "Tidak"}')
    print('------')
    activity_text = f"{WATERMARK_TEXT} | {BOT_PREFIX}help"
    await bot.change_presence(activity=discord.Game(name=activity_text))

# --- Perintah-Perintah Bot ---
@bot.command(name='join', aliases=['j', 'masuk'], help='Panggil bot untuk masuk ke voice channel kamu.')
async def join(ctx):
    if not ctx.author.voice:
        embed = discord.Embed(description=f"⚠️ {ctx.author.mention}, kamu harus ada di voice channel dulu.", color=discord.Color.orange())
        await ctx.send(embed=embed)
        return
    channel = ctx.author.voice.channel
    if ctx.voice_client and ctx.voice_client.channel == channel:
        embed = discord.Embed(description=f"✅ Aku sudah di voice channel **{channel.name}** bersamamu.", color=discord.Color.blue())
        await ctx.send(embed=embed)
        return
    if ctx.voice_client: await ctx.voice_client.move_to(channel)
    else: await channel.connect()
    embed = discord.Embed(description=f"➡️ Oke, aku masuk ke voice channel: **{channel.name}**!", color=discord.Color.green())
    await ctx.send(embed=embed)

@bot.command(name='leave', aliases=['dc', 'disconnect', 'keluar'], help='Bot keluar dari voice channel.')
async def leave(ctx):
    if not ctx.voice_client:
        embed = discord.Embed(description="⚠️ Aku tidak sedang berada di voice channel.", color=discord.Color.orange())
        await ctx.send(embed=embed)
        return
    guild_id = ctx.guild.id
    if guild_id in music_queue: music_queue[guild_id].clear()
    current_song.pop(guild_id, None)
    await ctx.voice_client.disconnect()
    embed = discord.Embed(description="👋 Dadah! Sampai jumpa lagi.", color=discord.Color.blue())
    embed.set_footer(text=WATERMARK_TEXT)
    await ctx.send(embed=embed)

async def process_and_play_or_queue(ctx, item_to_process, play_immediately_if_empty=True, source_message=""):
    guild_id = ctx.guild.id
    display_title, query_for_yt_dlp, original_url_for_display, item_thumbnail = "", "", "", None

    if isinstance(item_to_process, dict):
        display_title = f"{item_to_process.get('artist', '')} - {item_to_process.get('title', 'Judul Tdk Ada')}".strip(" - ")
        query_for_yt_dlp = item_to_process['query_for_yt_dlp']
        if 'spotify_url' in item_to_process and item_to_process['spotify_url']:
            original_url_for_display = f" ([Spotify]({item_to_process['spotify_url']}))"
        item_thumbnail = item_to_process.get('thumbnail')
    else:
        query_for_yt_dlp = item_to_process

    if play_immediately_if_empty and (not ctx.voice_client or not ctx.voice_client.is_playing()) and not (ctx.voice_client and ctx.voice_client.is_paused()):
        try:
            player = await YTDLSource.from_url(query_for_yt_dlp, loop=bot.loop, stream=True)
            if not display_title: display_title = player.title
            if not original_url_for_display and player.url: original_url_for_display = f" ([Link Asli]({player.url}))"
            if not item_thumbnail: item_thumbnail = player.thumbnail

            ctx.voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(check_after_play(ctx, e), bot.loop).result())
            current_song[guild_id] = {"title": display_title, "thumbnail": item_thumbnail, "url_display": original_url_for_display, "duration": player.duration, "uploader": player.uploader}
            
            embed = discord.Embed(title="🎧 Memutar Sekarang", description=f"**[{display_title}]({player.url if player.url else '#'})**{original_url_for_display}{source_message}", color=discord.Color.green())
            if item_thumbnail: embed.set_thumbnail(url=item_thumbnail)
            if player.duration: embed.add_field(name="Durasi", value=f"{int(player.duration // 60)}:{int(player.duration % 60):02d}", inline=True)
            if player.uploader: embed.add_field(name="Uploader/Artis", value=player.uploader, inline=True)
            embed.set_footer(text=WATERMARK_TEXT)
            await ctx.send(embed=embed)
        except Exception as e:
            embed = discord.Embed(title="⚠️ Gagal Memutar", description=f"Gagal memutar **{display_title if display_title else query_for_yt_dlp}**: `{type(e).__name__}`.", color=discord.Color.red())
            embed.set_footer(text=WATERMARK_TEXT)
            await ctx.send(embed=embed)
            print(f"Error di process_and_play_or_queue (play): {e}")
    else:
        title_for_queue, url_for_queue, thumb_for_queue = display_title, original_url_for_display, item_thumbnail
        # Jika item string dan bukan URL, coba ambil info untuk tampilan antrian
        if isinstance(item_to_process, str) and not re.match(r'http[s]?://', item_to_process):
            try: # Coba ambil info tanpa streaming
                temp_info = await YTDLSource.from_url(item_to_process, loop=bot.loop, stream=False)
                title_for_queue = temp_info.title
                if temp_info.url: url_for_queue = f" ([Link Asli]({temp_info.url}))"
                thumb_for_queue = temp_info.thumbnail
            except: title_for_queue = item_to_process # Jika gagal, pakai query asli
        elif isinstance(item_to_process, str): # Jika URL
             title_for_queue = item_to_process # Tampilkan URL jika tidak ada info awal
        
        # Pastikan item_to_process yang disimpan adalah dict jika berasal dari Spotify, atau string jika query biasa
        music_queue[guild_id].append(item_to_process)
        
        embed = discord.Embed(title="➕ Ditambahkan ke Antrian", description=f"**{title_for_queue}**{url_for_queue}{source_message}", color=discord.Color.blurple())
        if thumb_for_queue: embed.set_thumbnail(url=thumb_for_queue)
        embed.set_footer(text=WATERMARK_TEXT)
        await ctx.send(embed=embed)

@bot.command(name='play', aliases=['p', 'mainkan'], help='Putar musik dari YouTube/Spotify URL/pencarian. Contoh: !p [judul/URL]')
async def play(ctx, *, query: str):
    if not ctx.author.voice:
        await ctx.send(embed=discord.Embed(description="⚠️ Kamu harus ada di voice channel dulu!", color=discord.Color.orange()))
        return
    if ctx.voice_client is None:
        await ctx.author.voice.channel.connect()
        await ctx.send(embed=discord.Embed(description=f"➡️ Masuk ke **{ctx.author.voice.channel.name}**.", color=discord.Color.light_grey()))
    elif ctx.voice_client.channel != ctx.author.voice.channel:
        await ctx.send(embed=discord.Embed(description="⚠️ Kamu harus di voice channel yang sama denganku.", color=discord.Color.orange()))
        return

    guild_id = ctx.guild.id
    if guild_id not in music_queue: music_queue[guild_id] = []

    async with ctx.typing():
        spotify_track_match = re.match(r'https?://open\.spotify\.com/(intl-\w+/)?track/([a-zA-Z0-9]+)', query)
        spotify_album_match = re.match(r'https?://open\.spotify\.com/(intl-\w+/)?album/([a-zA-Z0-9]+)', query)
        spotify_playlist_match = re.match(r'https?://open\.spotify\.com/(intl-\w+/)?playlist/([a-zA-Z0-9]+)', query)
        items_to_process_list = []
        source_message = "" # Untuk menandai jika dari album/playlist

        if sp and (spotify_track_match or spotify_album_match or spotify_playlist_match):
            try:
                if spotify_track_match:
                    track_id = spotify_track_match.group(2)
                    track_info_spotify = sp.track(track_id)
                    track_title = track_info_spotify['name']
                    track_artist = track_info_spotify['artists'][0]['name']
                    items_to_process_list.append({'title': track_title, 'artist': track_artist, 'query_for_yt_dlp': f"{track_artist} - {track_title} audio", 'spotify_url': query, 'thumbnail': track_info_spotify['album']['images'][0]['url'] if track_info_spotify['album']['images'] else None})
                
                elif spotify_album_match:
                    album_id = spotify_album_match.group(2)
                    album_info = sp.album(album_id)
                    album_name = album_info['name']
                    album_thumb = album_info['images'][0]['url'] if album_info['images'] else None
                    results = sp.album_tracks(album_id)
                    for item in results['items']:
                        items_to_process_list.append({'title': item['name'], 'artist': item['artists'][0]['name'], 'query_for_yt_dlp': f"{item['artists'][0]['name']} - {item['name']} audio", 'spotify_url': item.get('external_urls',{}).get('spotify'), 'thumbnail': album_thumb})
                    if items_to_process_list: source_message = f"\nDari Album Spotify: **{album_name}**"
                
                elif spotify_playlist_match:
                    playlist_id = spotify_playlist_match.group(2)
                    playlist_info = sp.playlist(playlist_id)
                    playlist_name = playlist_info['name']
                    playlist_thumb = playlist_info['images'][0]['url'] if playlist_info['images'] else None
                    results = sp.playlist_items(playlist_id, fields='items(track(name,artists(name),external_urls(spotify),album(images)))')
                    for item_wrapper in results['items']:
                        item = item_wrapper.get('track')
                        if item and item.get('name') and item.get('artists'):
                            thumb = item['album']['images'][0]['url'] if item['album']['images'] else playlist_thumb
                            items_to_process_list.append({'title': item['name'], 'artist': item['artists'][0]['name'], 'query_for_yt_dlp': f"{item['artists'][0]['name']} - {item['name']} audio", 'spotify_url': item.get('external_urls',{}).get('spotify'), 'thumbnail': thumb})
                    if items_to_process_list: source_message = f"\nDari Playlist Spotify: **{playlist_name}**"
                
                if not items_to_process_list and (spotify_album_match or spotify_playlist_match) : # Jika album/playlist tapi kosong
                     await ctx.send(embed=discord.Embed(title="🤔 Info Spotify", description=f"Tidak ada lagu yang bisa diambil dari link Spotify tersebut.", color=discord.Color.gold(), footer=WATERMARK_TEXT))
                     return

            except Exception as e:
                await ctx.send(embed=discord.Embed(title="⚠️ Error Spotify", description=f"Gagal ambil info dari Spotify: `{type(e).__name__}`.\nMencoba sebagai pencarian biasa...", color=discord.Color.orange(), footer=WATERMARK_TEXT))
                print(f"Error Spotify processing: {e}")
                items_to_process_list.append(query) # Fallback
        else:
            items_to_process_list.append(query)

        if not items_to_process_list:
            await ctx.send(embed=discord.Embed(description="Tidak ada lagu yang bisa diproses.", color=discord.Color.light_grey(), footer=WATERMARK_TEXT))
            return

        first_item = items_to_process_list.pop(0)
        await process_and_play_or_queue(ctx, first_item, play_immediately_if_empty=True, source_message=source_message if len(items_to_process_list) == 0 else "") # Hanya tampilkan source_message jika ini satu-satunya item

        # Tambahkan sisa item ke antrian (jika dari album/playlist)
        if items_to_process_list: # Jika ada sisa dari album/playlist
            num_added = 0
            for item in items_to_process_list:
                await process_and_play_or_queue(ctx, item, play_immediately_if_empty=False, source_message="") # Tidak perlu source msg per item
                num_added +=1
            if num_added > 0 and source_message: # Kirim konfirmasi umum untuk album/playlist
                 embed_multi = discord.Embed(title="➕ Beberapa Lagu Ditambahkan", description=f"Berhasil menambahkan **{num_added+1}** lagu ke antrian {source_message}.", color=discord.Color.dark_purple())
                 embed_multi.set_footer(text=WATERMARK_TEXT)
                 await ctx.send(embed=embed_multi)


@bot.command(name='queue', aliases=['q', 'antrian'], help='Tampilkan antrian musik saat ini.')
async def queue_command(ctx):
    guild_id = ctx.guild.id
    embed = discord.Embed(title="🎶 Antrian Musik Kamu 🎶", color=discord.Color.purple())
    embed.set_footer(text=WATERMARK_TEXT)

    if guild_id in current_song and current_song[guild_id] and ctx.voice_client and \
       (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
        song_info = current_song[guild_id]
        now_playing_desc = f"**[{song_info['title']}]({song_info['url_display'].split('(')[1].split(')')[0] if song_info['url_display'] else '#'})** {song_info['url_display'] if 'spotify' not in song_info['url_display'].lower() else ''}"
        if song_info.get('thumbnail'): embed.set_thumbnail(url=song_info['thumbnail'])
        details = []
        if song_info.get('duration'): details.append(f"Dur: {int(song_info['duration'] // 60)}:{int(song_info['duration'] % 60):02d}")
        if song_info.get('uploader'): details.append(f"Oleh: {song_info['uploader']}")
        if details: now_playing_desc += f"\n`{' | '.join(details)}`"
        embed.add_field(name="🎧 Sedang Diputar:", value=now_playing_desc, inline=False)
    else:
        embed.add_field(name="🎧 Sedang Diputar:", value="Tidak ada lagu yang sedang diputar.", inline=False)

    if guild_id in music_queue and music_queue[guild_id]:
        queue_list_text = ""
        for i, item in enumerate(music_queue[guild_id][:10]): # Maks 10 lagu
            item_display, url_display = "", ""
            if isinstance(item, dict):
                item_display = f"{item.get('artist', '')} - {item.get('title', 'Judul Tdk Ada')}".strip(" - ")
                if 'spotify_url' in item and item['spotify_url']: url_display = f"([Spotify]({item['spotify_url']}))"
            elif isinstance(item, str): item_display = item
            queue_list_text += f"`{i+1}.` {item_display} {url_display}\n"
        
        embed.add_field(name=f"🗒️ Berikutnya ({len(music_queue[guild_id])} lagu):", value=queue_list_text if queue_list_text else "Antrian kosong.", inline=False)
        if len(music_queue[guild_id]) > 10:
            embed.add_field(name="...", value=f"Dan {len(music_queue[guild_id]) - 10} lagu lainnya.", inline=False)
    else:
        embed.add_field(name="🗒️ Berikutnya:", value="Antrian musik kosong.", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='skip', aliases=['s', 'lewati'], help='Lewati lagu yang sedang diputar.')
async def skip(ctx):
    if not ctx.voice_client or not (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
        return await ctx.send(embed=discord.Embed(description="⚠️ Tidak ada musik untuk dilewati.", color=discord.Color.orange(), footer=WATERMARK_TEXT))
    if not ctx.author.voice or ctx.author.voice.channel != ctx.voice_client.channel:
        return await ctx.send(embed=discord.Embed(description="⚠️ Kamu harus di VC yang sama denganku.", color=discord.Color.orange(), footer=WATERMARK_TEXT))
    
    ctx.voice_client.stop() # Memicu play_next
    await ctx.send(embed=discord.Embed(title="⏭️ Lagu Dilewati", description=f"Dilewati oleh {ctx.author.mention}.", color=discord.Color.blue(), footer=WATERMARK_TEXT))


@bot.command(name='pause', aliases=['jeda'], help='Jeda musik yang sedang diputar.')
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send(embed=discord.Embed(description="⏸️ Musik dijeda. Gunakan `!resume` untuk melanjutkan.", color=discord.Color.blue(), footer=WATERMARK_TEXT))
    else:
        await ctx.send(embed=discord.Embed(description="⚠️ Tidak ada musik yang sedang diputar atau sudah dijeda.", color=discord.Color.orange(), footer=WATERMARK_TEXT))

@bot.command(name='resume', aliases=['unpause', 'lanjutkan'], help='Lanjutkan musik yang dijeda.')
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send(embed=discord.Embed(description="▶️ Musik dilanjutkan!", color=discord.Color.green(), footer=WATERMARK_TEXT))
    else:
        await ctx.send(embed=discord.Embed(description="⚠️ Tidak ada musik yang dijeda.", color=discord.Color.orange(), footer=WATERMARK_TEXT))

@bot.command(name='stop', aliases=['berhenti', 'stfu'], help='Hentikan musik dan bersihkan antrian.')
async def stop(ctx):
    if not ctx.voice_client: return await ctx.send(embed=discord.Embed(description="⚠️ Aku tidak sedang di voice channel.", color=discord.Color.orange(), footer=WATERMARK_TEXT))
    guild_id = ctx.guild.id
    if guild_id in music_queue: music_queue[guild_id].clear()
    current_song.pop(guild_id, None)
    if ctx.voice_client.is_playing() or ctx.voice_client.is_paused(): ctx.voice_client.stop()
    await ctx.send(embed=discord.Embed(description="⏹️ Musik dihentikan dan antrian dibersihkan.", color=discord.Color.red(), footer=WATERMARK_TEXT))

@bot.command(name='clearqueue', aliases=['cq', 'hapusantrian'], help='Bersihkan semua lagu dari antrian.')
async def clearqueue(ctx):
    guild_id = ctx.guild.id
    if guild_id in music_queue and music_queue[guild_id]:
        music_queue[guild_id].clear()
        await ctx.send(embed=discord.Embed(description="🗑️ Antrian musik berhasil dibersihkan!", color=discord.Color.blue(), footer=WATERMARK_TEXT))
    else:
        await ctx.send(embed=discord.Embed(description="ℹ️ Antrian musik sudah kosong.", color=discord.Color.light_grey(), footer=WATERMARK_TEXT))

@bot.command(name='ping', help='Cek responsivitas bot.')
async def ping(ctx):
    latency = round(bot.latency * 1000)
    color = discord.Color.green() if latency < 150 else (discord.Color.orange() if latency < 300 else discord.Color.red())
    await ctx.send(embed=discord.Embed(title="🏓 Pong!", description=f"Latensiku saat ini: **{latency}ms**", color=color, footer=WATERMARK_TEXT))

# --- Error Handling Global ---
@bot.event
async def on_command_error(ctx, error):
    embed = discord.Embed(title="🚫 Terjadi Kesalahan", color=discord.Color.dark_red())
    embed.set_footer(text=WATERMARK_TEXT)
    if isinstance(error, commands.CommandNotFound):
        embed.description = f"Perintah itu nggak ada, bro. Coba `{BOT_PREFIX}help`."
    elif isinstance(error, commands.MissingRequiredArgument):
        embed.description = f"Ada yang kurang dari perintahmu: `{error.param.name}`.\nCek `{BOT_PREFIX}help {ctx.command.name}` untuk detail."
    elif isinstance(error, commands.CommandInvokeError):
        original_error = error.original
        print(f"Error saat menjalankan '{ctx.command.name}': {original_error}") # Untuk logging di console
        embed.title = f"🔥 Error Internal pada Perintah `{ctx.command.name}`"
        embed.description = f"Waduh, ada masalah internal nih: `{type(original_error).__name__}`.\nPengembang (itu kamu, @paatih!) sudah diberitahu (lewat console)."
    elif isinstance(error, commands.CheckFailure):
        embed.description = "Kamu tidak punya izin untuk menjalankan perintah ini."
    elif isinstance(error, commands.BadArgument):
        embed.description = f"Argumen yang kamu berikan salah. Cek `{BOT_PREFIX}help {ctx.command.name}`."
    else:
        embed.description = f"Terjadi error yang tidak dikenal: `{error}`"
        print(f'Error tidak dikenal: {error}') # Untuk logging di console
    await ctx.send(embed=embed)

# --- Menjalankan Bot ---
if __name__ == "__main__":
    if not TOKEN or not SPOTIPY_CLIENT_ID or not SPOTIPY_CLIENT_SECRET:
        print("--- !!! PENTING !!! ---")
        print("Pastikan file '.env' sudah ada di folder yang sama dengan 'bot.py' dan berisi:")
        if not TOKEN: print("- DISCORD_BOT_TOKEN")
        if not SPOTIPY_CLIENT_ID: print("- SPOTIPY_CLIENT_ID")
        if not SPOTIPY_CLIENT_SECRET: print("- SPOTIPY_CLIENT_SECRET")
        print("-------------------------")
    else:
        try:
            bot.run(TOKEN)
        except discord.errors.LoginFailure:
            print("GAGAL LOGIN DISCORD: Token bot tidak valid. Cek DISCORD_BOT_TOKEN di file .env.")
        except Exception as e:
            print(f"Error fatal saat menjalankan bot: {e}")