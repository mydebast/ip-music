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
            BOT_PREFIX = '!!' 
            WATERMARK_TEXT = "Bot Music by @paatih" 

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

            # --- Global States for Music Bot ---
            music_queue = {} 
            current_song = {} 
            now_playing_message = {} 
            autoplay_enabled = {} 
            song_history = {} 

            # --- Custom Help Command ---
            class CustomHelpCommand(commands.DefaultHelpCommand):
                def __init__(self, **options):
                    super().__init__(**options)
                    self.no_category = "Perintah Lainnya"
                    self.command_attrs['help'] = "Menampilkan pesan bantuan ini."

                def get_ending_note(self):
                    return f"Gunakan `{self.context.bot.command_prefix}[nama_perintah] [argumen]` untuk detail.\n{WATERMARK_TEXT}"

                async def send_bot_help(self, mapping):
                    embed = discord.Embed(title="📜 Daftar Perintah Bot Musik 📜", description=f"Gunakan `{self.context.bot.command_prefix}[nama_perintah]` untuk menjalankan perintah.", color=discord.Color.purple())
                    if bot.user and bot.user.avatar: 
                        embed.set_thumbnail(url=bot.user.avatar.url)

                    for cog, commands_list in mapping.items():
                        filtered_commands = await self.filter_commands(commands_list, sort=True)
                        if filtered_commands:
                            command_signatures = [self.get_command_signature(c) for c in filtered_commands]
                            if command_signatures:
                                cog_name = getattr(cog, "qualified_name", "Tanpa Kategori")
                                if cog_name == "No Category": cog_name = self.no_category

                                command_details = []
                                for sig, cmd in zip(command_signatures, filtered_commands):
                                    if cmd.help: 
                                         command_details.append(f"`{sig}` - {cmd.help}")

                                if command_details: 
                                    embed.add_field(name=f"**🎶 {cog_name}**", value="\n".join(command_details), inline=False)

                    embed.set_footer(text=self.get_ending_note())
                    await self.get_destination().send(embed=embed)

                async def send_command_help(self, command):
                    embed = discord.Embed(title=f"Bantuan untuk Perintah: `{self.get_command_signature(command)}`", color=discord.Color.dark_blue())
                    embed.add_field(name="Deskripsi:", value=command.help or "Tidak ada deskripsi.", inline=False)
                    if command.aliases:
                        embed.add_field(name="Alias:", value=", ".join(f"`{self.context.bot.command_prefix}{alias}`" for alias in command.aliases), inline=False)
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
                'format': 'bestaudio/best', 'outtmpl': 'downloads/%(extractor)s-%(id)s-%(title)s.%(ext)s',
                'restrictfilenames': True, 'noplaylist': True, 'nocheckcertificate': True, 'ignoreerrors': False,
                'logtostderr': False, 'quiet': True, 'no_warnings': True, 'default_search': 'ytsearch',
                'source_address': '0.0.0.0',
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192',}],
            }
            FFMPEG_OPTS = {
                'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 
                'options': '-vn -loglevel error' # Menambahkan loglevel error
            }


            # --- Class YTDLSource ---
            class YTDLSource(discord.PCMVolumeTransformer):
                def __init__(self, source, *, data, volume=0.5):
                    super().__init__(source, volume)
                    self.data = data
                    self.title = data.get('title', 'Judul Tidak Diketahui')
                    self.url = data.get('webpage_url', '') 
                    self.duration = data.get('duration')
                    self.uploader = data.get('uploader', 'Tidak Diketahui')
                    self.thumbnail = data.get('thumbnail')
                    self.original_query_info = data.get('original_query_info')

                @classmethod
                async def from_url(cls, item_data_or_query, *, loop=None, stream=False, ydl_opts_override=None):
                    loop = loop or asyncio.get_event_loop()
                    final_ydl_opts = YDL_OPTS.copy()
                    if ydl_opts_override: final_ydl_opts.update(ydl_opts_override)

                    query_to_search = ""
                    if isinstance(item_data_or_query, dict):
                        query_to_search = item_data_or_query.get('query_for_yt_dlp', str(item_data_or_query))
                    else:
                        query_to_search = str(item_data_or_query)

                    original_info_for_player = item_data_or_query

                    if not re.match(r'http[s]?://', query_to_search): 
                        final_ydl_opts['default_search'] = 'ytsearch1'
                    elif 'default_search' in final_ydl_opts: 
                        del final_ydl_opts['default_search']

                    try:
                        with youtube_dl.YoutubeDL(final_ydl_opts) as ydl: 
                            data = await loop.run_in_executor(None, lambda: ydl.extract_info(query_to_search, download=not stream))
                    except Exception as e: 
                        print(f"Error yt-dlp untuk '{query_to_search}': {e}")
                        raise 

                    if 'entries' in data: data = data['entries'][0]
                    data['original_query_info'] = original_info_for_player
                    filename = data['url'] if stream else ydl.prepare_filename(data)
                    return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTS), data=data)

            # --- Music Player View (Tombol-Tombol) ---
            class MusicPlayerView(discord.ui.View):
                def __init__(self, *, timeout=None, ctx_bot, guild_id, original_interaction_user_id=None):
                    super().__init__(timeout=timeout)
                    self.ctx_bot = ctx_bot
                    self.guild_id = guild_id
                    self.original_interaction_user_id = original_interaction_user_id
                    self.update_buttons_state()

                def update_buttons_state(self):
                    vc = self.ctx_bot.get_guild(self.guild_id).voice_client if self.ctx_bot.get_guild(self.guild_id) else None
                    is_playing_or_paused = vc and (vc.is_playing() or vc.is_paused())

                    pause_resume_button = discord.utils.get(self.children, custom_id="pause_resume")
                    if pause_resume_button:
                        if vc and vc.is_paused(): pause_resume_button.emoji, pause_resume_button.label = "▶️", "Resume"
                        else: pause_resume_button.emoji, pause_resume_button.label = "⏸️", "Pause"
                        pause_resume_button.disabled = not is_playing_or_paused

                    autoplay_button = discord.utils.get(self.children, custom_id="autoplay")
                    if autoplay_button:
                        if autoplay_enabled.get(self.guild_id, False): autoplay_button.style, autoplay_button.label = discord.ButtonStyle.green, "Autoplay: ON"
                        else: autoplay_button.style, autoplay_button.label = discord.ButtonStyle.grey, "Autoplay: OFF"

                    replay_button = discord.utils.get(self.children, custom_id="replay")
                    skip_button = discord.utils.get(self.children, custom_id="skip")
                    stop_button = discord.utils.get(self.children, custom_id="stop_playback")

                    if replay_button: replay_button.disabled = not (is_playing_or_paused and song_history.get(self.guild_id))
                    if skip_button: skip_button.disabled = not is_playing_or_paused
                    if stop_button: stop_button.disabled = not vc

                async def interaction_check(self, interaction: discord.Interaction) -> bool:
                    vc = interaction.guild.voice_client
                    if self.original_interaction_user_id and self.original_interaction_user_id == interaction.user.id:
                        return True
                    if not interaction.user.voice or not vc or interaction.user.voice.channel != vc.channel:
                        await interaction.response.send_message("Kamu harus berada di voice channel yang sama dengan bot!", ephemeral=True, delete_after=10)
                        return False
                    return True

                @discord.ui.button(label="Replay", style=discord.ButtonStyle.secondary, emoji="⏪", custom_id="replay", row=0)
                async def replay_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                    guild_id = interaction.guild_id; vc = interaction.guild.voice_client
                    last_song_data = song_history.get(guild_id)
                    if vc and last_song_data:
                        current_q_item_for_history = current_song.get(guild_id, {}).get('original_query_info')
                        if vc.is_playing() and current_q_item_for_history:
                             music_queue.setdefault(guild_id, []).insert(0, current_q_item_for_history)
                        music_queue.setdefault(guild_id, []).insert(0, last_song_data)
                        if vc.is_playing() or vc.is_paused(): vc.stop()
                        else: await play_next(interaction)
                        await interaction.response.send_message("⏪ Memutar ulang lagu...", ephemeral=True, delete_after=5)
                    else: await interaction.response.send_message("Tidak ada lagu untuk diputar ulang.", ephemeral=True, delete_after=10)
                    self.update_buttons_state()
                    if interaction.message: 
                        try: await interaction.message.edit(view=self)
                        except discord.NotFound: pass 

                @discord.ui.button(label="Pause", style=discord.ButtonStyle.primary, emoji="⏸️", custom_id="pause_resume", row=0)
                async def pause_resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                    vc = interaction.guild.voice_client
                    if vc:
                        if vc.is_paused(): vc.resume()
                        elif vc.is_playing(): vc.pause()
                        else: return await interaction.response.send_message("Tidak ada musik yang diputar.", ephemeral=True, delete_after=10)
                        self.update_buttons_state(); await interaction.response.edit_message(view=self)
                    else: await interaction.response.send_message("Bot tidak di voice channel.", ephemeral=True, delete_after=10)

                @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary, emoji="⏩", custom_id="skip", row=0)
                async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                    vc = interaction.guild.voice_client
                    if not vc or not (vc.is_playing() or vc.is_paused()):
                        return await interaction.response.send_message("Tidak ada musik untuk dilewati.", ephemeral=True, delete_after=10)
                    skipped_song_title = current_song.get(interaction.guild_id, {}).get('title', 'Lagu saat ini')
                    await interaction.response.send_message(f"⏭️ **{skipped_song_title}** dilewati!", ephemeral=False, delete_after=10)
                    vc.stop() 

                @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="⏹️", custom_id="stop_playback", row=0)
                async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                    guild_id = interaction.guild_id; vc = interaction.guild.voice_client
                    if not vc: return await interaction.response.send_message("Bot tidak di voice channel.", ephemeral=True, delete_after=10)
                    if guild_id in music_queue: music_queue[guild_id].clear()
                    current_song.pop(guild_id, None); song_history.pop(guild_id, None); autoplay_enabled.pop(guild_id, None)

                    if vc.is_playing() or vc.is_paused(): vc.stop()
                    await asyncio.sleep(0.5) # Jeda sebelum disconnect
                    await vc.disconnect()

                    embed_stopped = discord.Embed(title="⏹️ Pemutaran Dihentikan", description="Bot keluar dari voice channel. Antrian dibersihkan.", color=discord.Color.red()); embed_stopped.set_footer(text=WATERMARK_TEXT)
                    try: await interaction.message.edit(embed=embed_stopped, view=None) 
                    except discord.NotFound: await interaction.channel.send(embed=embed_stopped) 
                    if guild_id in now_playing_message: now_playing_message.pop(guild_id, None)
                    self.stop()

                @discord.ui.button(label="Autoplay: OFF", style=discord.ButtonStyle.grey, emoji="🔁", custom_id="autoplay", row=0)
                async def autoplay_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                    guild_id = interaction.guild_id
                    autoplay_enabled[guild_id] = not autoplay_enabled.get(guild_id, False)
                    self.update_buttons_state(); await interaction.response.edit_message(view=self)
                    message_content = "✅ Autoplay diaktifkan!" if autoplay_enabled[guild_id] else "❌ Autoplay dinonaktifkan!"
                    try: 
                        await interaction.followup.send(message_content, ephemeral=True)
                    except discord.HTTPException: 
                         await interaction.channel.send(message_content, delete_after=5)

            # --- Fungsi Helper & Event ---
            async def play_next(ctx_or_interaction):
                if isinstance(ctx_or_interaction, discord.Interaction):
                    guild = ctx_or_interaction.guild; text_channel = ctx_or_interaction.channel
                    original_user_id = ctx_or_interaction.user.id
                else: 
                    guild = ctx_or_interaction.guild; text_channel = ctx_or_interaction.channel
                    original_user_id = ctx_or_interaction.author.id
                if not guild: return
                guild_id = guild.id; vc = guild.voice_client

                if now_playing_message.get(guild_id):
                    try: await now_playing_message[guild_id].edit(view=None)
                    except: pass
                    now_playing_message.pop(guild_id, None)
                if not vc: current_song.pop(guild_id, None); return

                item_to_play_data = None
                if music_queue.get(guild_id):
                    item_to_play_data = music_queue[guild_id].pop(0)
                elif autoplay_enabled.get(guild_id, False) and song_history.get(guild_id):
                    last_played_item = song_history.get(guild_id)
                    query_autoplay = f"{last_played_item.get('artist','')} {last_played_item.get('title','')} mix" if isinstance(last_played_item, dict) else f"{str(last_played_item)} related"
                    if query_autoplay.strip().lower() not in ["mix", "related", " unknown artist - judul tidak diketahui mix", " -  mix", "  related"]: 
                        embed_auto = discord.Embed(title="Автовоспроизведение 🔁", description=f"Mencari terkait: **{query_autoplay.replace(' mix','').replace(' related','')}**...", color=discord.Color.blue()); embed_auto.set_footer(text=WATERMARK_TEXT)
                        if text_channel: await text_channel.send(embed=embed_auto, delete_after=10)
                        item_to_play_data = query_autoplay
                    else:
                         current_song.pop(guild_id, None)
                         if text_channel: 
                             embed_q_empty = discord.Embed(title="Antrian Habis", description="Autoplay gagal mencari acuan lagu.", color=discord.Color.gold()); embed_q_empty.set_footer(text=WATERMARK_TEXT)
                             await text_channel.send(embed=embed_q_empty)
                         return
                else:
                    current_song.pop(guild_id, None)
                    embed_q_empty = discord.Embed(title="Antrian Habis", description="Tidak ada lagi lagu di antrian.", color=discord.Color.gold()); embed_q_empty.set_footer(text=WATERMARK_TEXT)
                    if text_channel: await text_channel.send(embed=embed_q_empty)
                    return

                if not item_to_play_data: return

                display_title, original_url_for_display, item_thumbnail = "Lagu Diproses...", "", None
                if isinstance(item_to_play_data, dict):
                    display_title = f"{item_to_play_data.get('artist','')} - {item_to_play_data.get('title','Judul Tidak Ada')}".strip(" - ")
                    if item_to_play_data.get('spotify_url'): original_url_for_display = f" ([Spotify]({item_to_play_data['spotify_url']}))"
                    item_thumbnail = item_to_play_data.get('thumbnail')

                try:
                    player = await YTDLSource.from_url(item_to_play_data, loop=bot.loop, stream=True)
                    if display_title == "Lagu Diproses...": display_title = player.title
                    if not original_url_for_display and player.url: original_url_for_display = f" ([Link]({player.url}))"
                    if not item_thumbnail: item_thumbnail = player.thumbnail

                    vc.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(check_after_play(ctx_or_interaction, e), bot.loop).result())
                    current_song[guild_id] = {"title": display_title, "thumbnail": item_thumbnail, "url_display": original_url_for_display, "duration": player.duration, "uploader": player.uploader, "original_query_info": player.original_query_info}
                    song_history[guild_id] = player.original_query_info

                    embed = discord.Embed(title="🎧 Memutar Sekarang", description=f"**[{display_title}]({player.url or '#'})**{original_url_for_display}", color=discord.Color.green())
                    if item_thumbnail: embed.set_thumbnail(url=item_thumbnail)
                    if player.duration: embed.add_field(name="Durasi", value=f"{int(player.duration//60)}:{int(player.duration%60):02d}", inline=True)
                    if player.uploader: embed.add_field(name="Oleh", value=player.uploader, inline=True)
                    embed.set_footer(text=WATERMARK_TEXT)

                    view = MusicPlayerView(ctx_bot=bot, guild_id=guild_id, original_interaction_user_id=original_user_id)
                    if text_channel: 
                        msg = await text_channel.send(embed=embed, view=view)
                        now_playing_message[guild_id] = msg
                except Exception as e:
                    err_title = display_title if display_title!="Lagu Diproses..." else str(item_to_play_data)
                    print(f"Gagal putar '{err_title}': {e}")
                    if text_channel:
                        embed_err = discord.Embed(title="⚠️ Gagal Putar", description=f"**{err_title}**\nError: `{type(e).__name__}`", color=discord.Color.red()); embed_err.set_footer(text=WATERMARK_TEXT)
                        await text_channel.send(embed=embed_err)
                    await play_next(ctx_or_interaction)

            async def check_after_play(ctx_or_interaction, error):
                channel_to_send = None
                if isinstance(ctx_or_interaction, discord.Interaction): channel_to_send = ctx_or_interaction.channel
                elif hasattr(ctx_or_interaction, 'channel'): channel_to_send = ctx_or_interaction.channel
                if error:
                    print(f'Error setelah lagu: {error}')
                    if channel_to_send:
                        embed_err_after = discord.Embed(title="⚠️ Error Pemutaran", description=f"Terjadi error saat lagu selesai: `{error}`.", color=discord.Color.orange()); embed_err_after.set_footer(text=WATERMARK_TEXT)
                        await channel_to_send.send(embed=embed_err_after)
                await play_next(ctx_or_interaction)

            @bot.event
            async def on_ready():
                print(f'Bot {bot.user.name} (ID: {bot.user.id}) online!')
                print(f'Prefix: {BOT_PREFIX}')
                print(f'Spotify API: {"Ya" if sp else "Tidak"}')
                print('------')
                await bot.change_presence(activity=discord.Game(name=f"{WATERMARK_TEXT} | {BOT_PREFIX}help"))

            # --- Perintah Play ---
            @bot.command(name='play', aliases=['p', 'mainkan'], help='Putar musik dari YouTube/Spotify URL/pencarian.')
            async def play(ctx, *, query: str):
                if not ctx.author.voice:
                    embed_err_vc = discord.Embed(description="⚠️ Kamu harus ada di voice channel dulu!", color=discord.Color.orange()); embed_err_vc.set_footer(text=WATERMARK_TEXT)
                    await ctx.send(embed=embed_err_vc); return

                vc = ctx.voice_client
                if not vc: 
                    try: vc = await ctx.author.voice.channel.connect()
                    except Exception as e:
                        embed_err_join_vc = discord.Embed(title="⚠️ Gagal Masuk VC", description=f"Tidak bisa masuk: `{e}`", color=discord.Color.red()); embed_err_join_vc.set_footer(text=WATERMARK_TEXT)
                        await ctx.send(embed=embed_err_join_vc); return
                    else: 
                        embed_join = discord.Embed(description=f"➡️ Masuk ke **{ctx.author.voice.channel.name}**.", color=discord.Color.light_grey()); embed_join.set_footer(text=WATERMARK_TEXT)
                        await ctx.send(embed=embed_join)

                elif vc.channel != ctx.author.voice.channel: 
                    embed_err_same_vc = discord.Embed(description="⚠️ Kamu harus di voice channel yang sama.", color=discord.Color.orange()); embed_err_same_vc.set_footer(text=WATERMARK_TEXT)
                    await ctx.send(embed=embed_err_same_vc); return

                guild_id = ctx.guild.id
                if guild_id not in music_queue: music_queue[guild_id] = []

                async with ctx.typing():
                    loading_embed = discord.Embed(title="🔍 Mencari Info...", description="Mohon tunggu...", color=discord.Color.gold()); loading_embed.set_footer(text=WATERMARK_TEXT)
                    status_message = await ctx.send(embed=loading_embed)

                    items_to_add_to_bot_queue = [] 
                    source_name_for_summary, source_thumbnail_for_summary = "", None 

                    try:
                        spotify_track_match = re.match(r'https?://open\.spotify\.com/(intl-\w+/)?track/([a-zA-Z0-9]+)', query)
                        spotify_album_match = re.match(r'https?://open\.spotify\.com/(intl-\w+/)?album/([a-zA-Z0-9]+)', query)
                        spotify_playlist_match = re.match(r'https?://open\.spotify\.com/(intl-\w+/)?playlist/([a-zA-Z0-9]+)', query)

                        if sp and (spotify_track_match or spotify_album_match or spotify_playlist_match):
                            if spotify_track_match:
                                track_id = spotify_track_match.group(2); track_info_spotify = sp.track(track_id)
                                source_name_for_summary = "Lagu Spotify"
                                source_thumbnail_for_summary = track_info_spotify['album']['images'][0]['url'] if track_info_spotify['album']['images'] else None
                                items_to_add_to_bot_queue.append({'title': track_info_spotify['name'], 'artist': track_info_spotify['artists'][0]['name'], 'query_for_yt_dlp': f"{track_info_spotify['artists'][0]['name']} - {track_info_spotify['name']} audio", 'spotify_url': query, 'thumbnail': source_thumbnail_for_summary})
                            elif spotify_album_match:
                                album_id = spotify_album_match.group(2); album_info_spotify = sp.album(album_id)
                                source_name_for_summary = f"Album: **{album_info_spotify['name']}**"; source_thumbnail_for_summary = album_info_spotify['images'][0]['url'] if album_info_spotify['images'] else None
                                for item in sp.album_tracks(album_id)['items']: items_to_add_to_bot_queue.append({'title': item['name'], 'artist': item['artists'][0]['name'], 'query_for_yt_dlp': f"{item['artists'][0]['name']} - {item['name']} audio", 'spotify_url': item.get('external_urls',{}).get('spotify'), 'thumbnail': source_thumbnail_for_summary})
                            elif spotify_playlist_match:
                                playlist_id = spotify_playlist_match.group(2); playlist_info_spotify = sp.playlist(playlist_id)
                                source_name_for_summary = f"Playlist: **{playlist_info_spotify['name']}**"; source_thumbnail_for_summary = playlist_info_spotify['images'][0]['url'] if playlist_info_spotify['images'] else None
                                offset = 0
                                while True:
                                    results = sp.playlist_items(playlist_id, fields='items(track(name,artists(name),external_urls(spotify),album(images))),next', limit=100, offset=offset)
                                    for item_wrapper in results['items']:
                                        item = item_wrapper.get('track')
                                        if item and item.get('name') and item.get('artists'):
                                            thumb = item.get('album', {}).get('images'); thumb_url = thumb[0]['url'] if thumb else source_thumbnail_for_summary
                                            items_to_add_to_bot_queue.append({'title': item['name'], 'artist': item['artists'][0]['name'], 'query_for_yt_dlp': f"{item['artists'][0]['name']} - {item['name']} audio", 'spotify_url': item.get('external_urls',{}).get('spotify'), 'thumbnail': thumb_url})
                                    if results['next']: offset += 100
                                    else: break
                            if not items_to_add_to_bot_queue and (spotify_album_match or spotify_playlist_match) : 
                                 embed_empty = discord.Embed(title="🤔 Info Spotify", description=f"Tidak ada lagu dari {source_name_for_summary or 'link Spotify'}.", color=discord.Color.gold()); embed_empty.set_footer(text=WATERMARK_TEXT)
                                 await status_message.edit(embed=embed_empty); return
                        else: items_to_add_to_bot_queue.append(query)
                        await status_message.delete()
                    except Exception as e: 
                        await status_message.delete()
                        error_text = f"Gagal memproses permintaan: `{type(e).__name__}`."; fallback_to_query = False
                        if sp and (spotify_track_match or spotify_album_match or spotify_playlist_match):
                            error_text = f"Gagal mengambil info dari Spotify: `{type(e).__name__}`.\nMencoba sebagai pencarian biasa..."
                            print(f"Error Spotify processing: {e}"); items_to_add_to_bot_queue = [query]; fallback_to_query = True 
                        else: print(f"Error processing query '{query}': {e}")
                        embed_err_fetch = discord.Embed(title="⚠️ Error Pemrosesan", description=error_text, color=discord.Color.orange()); embed_err_fetch.set_footer(text=WATERMARK_TEXT)
                        await ctx.send(embed=embed_err_fetch)
                        if not fallback_to_query: return

                    if not items_to_add_to_bot_queue:
                        embed_no_items_final = discord.Embed(description="Tidak ada lagu untuk diproses.", color=discord.Color.light_grey()); embed_no_items_final.set_footer(text=WATERMARK_TEXT)
                        await ctx.send(embed=embed_no_items_final); return

                    is_currently_playing_or_paused = vc.is_playing() or vc.is_paused()
                    queue_was_empty_before_adding = not music_queue.get(guild_id)

                    songs_added_for_summary_message_list = []
                    first_item_played_this_call = False

                    if not is_currently_playing_or_paused and queue_was_empty_before_adding and items_to_add_to_bot_queue:
                        item_to_play_now = items_to_add_to_bot_queue.pop(0)
                        music_queue[guild_id].insert(0, item_to_play_now) 
                        await play_next(ctx) 
                        first_item_played_this_call = True
                        if not items_to_add_to_bot_queue: return 

                    for item_data in items_to_add_to_bot_queue:
                        music_queue[guild_id].append(item_data)
                        title = item_data.get('title', 'Lagu') if isinstance(item_data, dict) else str(item_data)
                        artist = item_data.get('artist', '') if isinstance(item_data, dict) else ''
                        songs_added_for_summary_message_list.append(f"{artist} - {title}".strip(" - ") if artist else title)

                    if songs_added_for_summary_message_list:
                        embed_summary = discord.Embed(color=discord.Color.blurple()); embed_summary.set_footer(text=WATERMARK_TEXT)
                        if source_thumbnail_for_summary: embed_summary.set_thumbnail(url=source_thumbnail_for_summary)
                        num_actually_queued = len(songs_added_for_summary_message_list)
                        title_text = f"➕ {num_actually_queued} Lagu Ditambahkan"
                        if source_name_for_summary and source_name_for_summary != "Lagu Spotify": title_text += f" dari {source_name_for_summary}"
                        description_text = "\n".join(f"`{i+1}.` {title}" for i, title in enumerate(songs_added_for_summary_message_list[:10]))
                        if num_actually_queued > 10: description_text += f"\n...dan {num_actually_queued - 10} lagu lainnya."
                        embed_summary.title = title_text; embed_summary.description = description_text
                        await ctx.send(embed=embed_summary)

                    if queue_was_empty_before_adding and not first_item_played_this_call and music_queue[guild_id] and not (vc.is_playing() or vc.is_paused()):
                        await play_next(ctx)


            # --- Perintah Lainnya ---
            @bot.command(name='queue', aliases=['q', 'antrian'], help='Tampilkan antrian musik saat ini.')
            async def queue_command(ctx):
                guild_id = ctx.guild.id; embed = discord.Embed(title="🎶 Antrian Musik Kamu 🎶", color=discord.Color.purple()); embed.set_footer(text=WATERMARK_TEXT)
                cs_info = current_song.get(guild_id)
                if cs_info and ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
                    url_link = '#'; match_link = re.search(r'\((.*?)\)', cs_info.get('url_display','')); 
                    if match_link: url_link = match_link.group(1)
                    desc = f"**[{cs_info['title']}]({url_link})** {cs_info.get('url_display','')}"
                    if cs_info.get('thumbnail'): embed.set_thumbnail(url=cs_info['thumbnail'])
                    details = [f"Dur: {int(cs_info['duration']//60)}:{int(cs_info['duration']%60):02d}" if cs_info.get('duration') else "", f"Oleh: {cs_info['uploader']}" if cs_info.get('uploader') else ""]
                    desc += f"\n`{' | '.join(filter(None, details))}`" if any(details) else ""
                    embed.add_field(name="🎧 Sedang Diputar:", value=desc, inline=False)
                else: embed.add_field(name="🎧 Sedang Diputar:", value="Tidak ada.", inline=False)
                q = music_queue.get(guild_id)
                if q:
                    q_text = "\n".join(f"`{i+1}.` {item.get('artist','')} - {item.get('title','Lagu')}".strip(" - ") if isinstance(item, dict) else f"`{i+1}.` {str(item)}" for i, item in enumerate(q[:10]))
                    embed.add_field(name=f"🗒️ Berikutnya ({len(q)} lagu):", value=q_text if q_text else "Kosong.", inline=False)
                    if len(q) > 10: embed.add_field(name="...", value=f"Dan {len(q)-10} lainnya.", inline=False)
                else: embed.add_field(name="🗒️ Berikutnya:", value="Antrian kosong.", inline=False)
                await ctx.send(embed=embed)

            @bot.command(name='skip', aliases=['s', 'lewati'], help='Lewati lagu yang sedang diputar.')
            async def skip(ctx):
                vc = ctx.voice_client
                if not vc or not (vc.is_playing() or vc.is_paused()):
                    embed = discord.Embed(description="⚠️ Tidak ada musik untuk dilewati.", color=discord.Color.orange()); embed.set_footer(text=WATERMARK_TEXT)
                    return await ctx.send(embed=embed)
                if not ctx.author.voice or ctx.author.voice.channel != vc.channel:
                    embed = discord.Embed(description="⚠️ Kamu harus di VC yang sama.", color=discord.Color.orange()); embed.set_footer(text=WATERMARK_TEXT)
                    return await ctx.send(embed=embed)
                skipped_title = current_song.get(ctx.guild.id, {}).get('title', 'Lagu ini')
                # Pesan skip akan dikirim oleh tombol atau jika tidak ada tombol, bisa di sini
                # Untuk konsistensi, biarkan tombol yang mengirim pesan jika ada, atau play_next akan update
                vc.stop() # Memicu play_next yang akan mengirim pesan "Now Playing" baru
                # Jika ingin pesan skip dari command:
                embed_skip_cmd = discord.Embed(title="⏭️ Lagu Dilewati via Perintah", description=f"**{skipped_title}** dilewati oleh {ctx.author.mention}.", color=discord.Color.blue()); embed_skip_cmd.set_footer(text=WATERMARK_TEXT)
                await ctx.send(embed=embed_skip_cmd, delete_after=10)


            @bot.command(name='pause', aliases=['jeda'], help='Jeda musik yang sedang diputar.')
            async def pause(ctx):
                vc = ctx.voice_client
                if vc and vc.is_playing():
                    vc.pause()
                    embed = discord.Embed(description=f"⏸️ Musik dijeda. `{BOT_PREFIX}resume` atau tombol untuk lanjut.", color=discord.Color.blue()); embed.set_footer(text=WATERMARK_TEXT)
                    await ctx.send(embed=embed)
                    msg = now_playing_message.get(ctx.guild.id)
                    if msg and isinstance(msg.view, MusicPlayerView): msg.view.update_buttons_state(); await msg.edit(view=msg.view)
                else:
                    embed = discord.Embed(description="⚠️ Tidak ada musik yg diputar/sudah dijeda.", color=discord.Color.orange()); embed.set_footer(text=WATERMARK_TEXT)
                    await ctx.send(embed=embed)

            @bot.command(name='resume', aliases=['unpause', 'lanjutkan'], help='Lanjutkan musik yang dijeda.')
            async def resume(ctx):
                vc = ctx.voice_client
                if vc and vc.is_paused():
                    vc.resume()
                    embed = discord.Embed(description="▶️ Musik dilanjutkan!", color=discord.Color.green()); embed.set_footer(text=WATERMARK_TEXT)
                    await ctx.send(embed=embed)
                    msg = now_playing_message.get(ctx.guild.id)
                    if msg and isinstance(msg.view, MusicPlayerView): msg.view.update_buttons_state(); await msg.edit(view=msg.view)
                else:
                    embed = discord.Embed(description="⚠️ Tidak ada musik yang dijeda.", color=discord.Color.orange()); embed.set_footer(text=WATERMARK_TEXT)
                    await ctx.send(embed=embed)

            @bot.command(name='stop', aliases=['berhenti', 'stfu'], help='Hentikan musik, bersihkan antrian & keluar VC.')
            async def stop(ctx):
                vc = ctx.voice_client
                if not vc: 
                    embed = discord.Embed(description="⚠️ Aku tidak di voice channel.", color=discord.Color.orange()); embed.set_footer(text=WATERMARK_TEXT)
                    return await ctx.send(embed=embed)

                guild_id = ctx.guild.id
                if guild_id in music_queue: music_queue[guild_id].clear()
                current_song.pop(guild_id, None); song_history.pop(guild_id, None); autoplay_enabled.pop(guild_id, None)

                msg_np = now_playing_message.pop(guild_id, None) # Ambil dan hapus dari dict
                if msg_np:
                    try:
                        # Buat embed baru untuk pesan "dihentikan" karena embed lama mungkin punya info lagu
                        embed_stopped_info = discord.Embed(title="⏹️ Pemutaran Dihentikan", description="Antrian dibersihkan, bot akan keluar.", color=discord.Color.red())
                        embed_stopped_info.set_footer(text=WATERMARK_TEXT)
                        await msg_np.edit(embed=embed_stopped_info, view=None) 
                    except discord.NotFound:
                        print(f"Pesan Now Playing untuk guild {guild_id} tidak ditemukan saat stop (command).")
                    except discord.HTTPException as e:
                        print(f"HTTP error saat edit pesan Now Playing (stop command): {e}")
                    except Exception as e:
                        print(f"Error umum saat edit pesan Now Playing (stop command): {e}")

                if vc.is_playing() or vc.is_paused(): vc.stop()
                await asyncio.sleep(0.5) # Jeda sebelum disconnect
                await vc.disconnect()

                # Pesan konfirmasi tambahan setelah disconnect
                embed_stop_confirm = discord.Embed(description="⏹️ Musik dihentikan, antrian bersih, bot keluar.", color=discord.Color.red()); embed_stop_confirm.set_footer(text=WATERMARK_TEXT)
                await ctx.send(embed=embed_stop_confirm)


            @bot.command(name='clearqueue', aliases=['cq', 'hapusantrian'], help='Bersihkan semua lagu dari antrian.')
            async def clearqueue(ctx):
                guild_id = ctx.guild.id
                if music_queue.get(guild_id):
                    music_queue[guild_id].clear()
                    embed = discord.Embed(description="🗑️ Antrian musik bersih!", color=discord.Color.blue()); embed.set_footer(text=WATERMARK_TEXT)
                    await ctx.send(embed=embed)
                else:
                    embed = discord.Embed(description="ℹ️ Antrian musik sudah kosong.", color=discord.Color.light_grey()); embed.set_footer(text=WATERMARK_TEXT)
                    await ctx.send(embed=embed)

            @bot.command(name='ping', help='Cek responsivitas bot.')
            async def ping(ctx):
                latency = round(bot.latency * 1000)
                color = discord.Color.green() if latency < 150 else (discord.Color.orange() if latency < 300 else discord.Color.red())
                embed = discord.Embed(title="🏓 Pong!", description=f"Latensiku: **{latency}ms**", color=color); embed.set_footer(text=WATERMARK_TEXT)
                await ctx.send(embed=embed)

            @bot.event
            async def on_command_error(ctx, error):
                embed = discord.Embed(title="🚫 Terjadi Kesalahan", color=discord.Color.dark_red()); embed.set_footer(text=WATERMARK_TEXT)
                prefix = ctx.prefix if hasattr(ctx, 'prefix') else BOT_PREFIX
                if isinstance(error, commands.CommandNotFound): embed.description = f"Perintah `{ctx.invoked_with}` nggak ada. Coba `{prefix}help`."
                elif isinstance(error, commands.MissingRequiredArgument): embed.description = f"Kurang argumen: `{error.param.name}`.\nCek `{prefix}help {ctx.command.name}`."
                elif isinstance(error, commands.CommandInvokeError):
                    original = error.original; print(f"Error '{ctx.command.name}': {original}") 
                    embed.title = f"🔥 Error Internal: `{ctx.command.name}`"; embed.description = f"`{type(original).__name__}`. @paatih tahu (cek console)."
                elif isinstance(error, commands.CheckFailure): embed.description = "Kamu tidak punya izin."
                elif isinstance(error, commands.BadArgument): embed.description = f"Argumen salah. Cek `{prefix}help {ctx.command.name}`."
                else: embed.description = f"Error tidak dikenal: `{error}`"; print(f'Error tidak dikenal: {error}')
                await ctx.send(embed=embed)

            # --- Menjalankan Bot ---
            if __name__ == "__main__":
                if not TOKEN: print("PENTING: DISCORD_BOT_TOKEN belum diisi di .env")
                else:
                    try: bot.run(TOKEN)
                    except discord.errors.LoginFailure: print("GAGAL LOGIN DISCORD: Token bot tidak valid.")
                    except Exception as e: print(f"Error fatal saat menjalankan bot: {e}")
