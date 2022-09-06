import discord
from discord.ext import commands,tasks
import youtube_dl
import asyncio
from youtubesearchpython import *
from time import gmtime
from time import strftime
import asyncpraw
import random
import os
import math
from bs4 import BeautifulSoup
import requests

from dotenv import load_dotenv
load_dotenv()

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36"
}

params = {
  "q": "Nasdaq composite",
  "hl": "en"
}

status = ['with Python','in the Gym','with your moma']

reddit = asyncpraw.Reddit(client_id=os.environ.get("ID"),
                          client_secret=os.environ.get("SECRET"),
                          username=os.environ.get("USER"),
                          password=os.environ.get("PASSWORD"),
                          user_agent="m")

millnames = ['', 'K views', 'M views', 'B views', ' Trillion views']

youtube_dl.utils.bug_reports_message = lambda: ''
guild_queues = {}

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address':
    '0.0.0.0'  # bind to ipv4 since ipv6 addresses cause issues sometimes
}

ydl_opts = {'format': 'bestaudio'}

FFMPEG_OPTIONS = {
    'before_options':
    '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

help_command = commands.DefaultHelpCommand(no_category='Commands')


def millify(n):
    n = float(n)
    millidx = max(
        0,
        min(
            len(millnames) - 1,
            int(math.floor(0 if n == 0 else math.log10(abs(n)) / 3))))

    return '{:.0f}{}'.format(n / 10**(3 * millidx), millnames[millidx])


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)

        self.data = data

        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            # take first item from a playlist
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS),
                   data=data)


client = commands.Bot(command_prefix='?', intents=discord.Intents().all())


async def manage_song_info(ctx,url, queue):
    link, thumbnail, title, duration, views,is_playlist = None, None, None, None, None,False
    if "https://" in url:
        if "list" in url:
            is_playlist=True

            playlistVideos = Playlist.getVideos(url)
            for song in playlistVideos['videos']:
                queue.append(song['link'].split("&", 1)[0])
            
            await ctx.send(str(len(playlistVideos['videos']))+" tracks loaded!")
                

            song = playlistVideos['videos'][0]['title']
            videosSearch = VideosSearch(song, limit=1)
            link = videosSearch.result()['result'][0]['link']
            thumbnail = videosSearch.result(
            )['result'][0]['thumbnails'][0]['url']
            title = videosSearch.result()['result'][0]['title']
            duration = videosSearch.result()['result'][0]['duration']
            views = videosSearch.result()['result'][0]['viewCount']['short']
        else:
            videoInfo = Video.getInfo(url, mode=ResultMode.json)
            link = videoInfo['link']
            thumbnail = videoInfo['thumbnails'][0]['url']
            title = videoInfo['title']
            duration = videoInfo['duration']['secondsText']
            views = videoInfo['viewCount']['text']
    else:
        videosSearch = VideosSearch(url, limit=1)
        link = videosSearch.result()['result'][0]['link']
        thumbnail = videosSearch.result()['result'][0]['thumbnails'][0]['url']
        title = videosSearch.result()['result'][0]['title']
        duration = videosSearch.result()['result'][0]['duration']
        views = videosSearch.result()['result'][0]['viewCount']['short']

    return link, thumbnail, title, duration, views,is_playlist

async def handle_queue(ctx,link,queue):
    link, thumbnail, title,duration, views,_ = await manage_song_info(ctx,link, queue)
    if ":" not in str(duration):
        duration=strftime("%H:%M:%S", gmtime(int(duration))) 
    if views.isnumeric():
        views=millify(views)
    voice = discord.utils.get(client.voice_clients, guild=ctx.guild)
    channel = ctx.author.voice.channel
    if voice and channel and voice.channel != channel:
        await voice.move_to(channel)
    elif not voice and channel:
        voice = await channel.connect()
    if not voice.is_playing():
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=False)
            URL = info['formats'][0]['url']
        voice.play(discord.FFmpegPCMAudio(URL, **FFMPEG_OPTIONS))
        embed = discord.Embed(
            title=f'Music Controller | {ctx.author.voice.channel.name}',
            colour=discord.Color.dark_purple())
        embed.description = f'Now Playing:\n**`{title}`**\n\n'
        embed.add_field(name='Requested By', value=ctx.author)
        embed.set_thumbnail(url=thumbnail)
        embed.add_field(name='Video URL',value=f'[Click Here!]({link})')
        embed.add_field(name='Duration',value=duration)
        embed.add_field(name='Views', value=views)
        await ctx.send(embed=embed)
        while voice.is_playing():
            await asyncio.sleep(.1)
        if bool(guild_queues):
            if len(guild_queues[ctx.guild.id]) > 0:
                next_song = guild_queues[ctx.guild.id].pop(0)
                await handle_queue(ctx, next_song,queue)
            else:
                await voice.disconnect()


@client.event
async def on_ready():
    change_status.start()
    print('Bot is online!')


@client.command(name='play',aliases=['p'],help='This command plays song by given url or name of song')
async def play(ctx, *, song):
    voice_state = ctx.author.voice
    if voice_state is None:
        await ctx.send("You need to be in voice channel!")
    else:
        try:
            queue = guild_queues[ctx.guild.id]
        except KeyError:
            guild_queues[ctx.guild.id] = []
            queue = guild_queues[ctx.guild.id]

        link, thumbnail, title, _, _,is_playlist = await manage_song_info(ctx,song, queue)
        if is_playlist==False:
            queue.append(link)
        voice = discord.utils.get(client.voice_clients, guild=ctx.guild)
        if voice and len(queue) > 0:
            embed = discord.Embed(
                title=f'Music Controller | {ctx.author.voice.channel.name}',
                colour=discord.Color.dark_purple())
            embed.description = f'Added to queue:\n**`{title}`**\n\n'
            embed.add_field(name='Requested By', value=ctx.author)
            embed.set_thumbnail(url=thumbnail)
            embed.add_field(name='Video URL',
                            value=f'[Click Here!]({link})')
            await ctx.send(embed=embed, delete_after=12)
        else:
            current_song = queue.pop(0)
            await handle_queue(ctx, current_song,queue)


@client.command(name='ping', help='Shows the latency')
async def ping(ctx):
    await ctx.send(f'**Pong!** Latency: {round(client.latency * 1000)}ms')


@client.command(name='meme', help='Shows some jim meme')
async def meme(ctx):
    all_subs = []
    subbredit = await reddit.subreddit("GymMemes")

    top = subbredit.top()

    async for submission in top:
        all_subs.append(submission)

    random_sub = random.choice(all_subs)

    

    em = discord.Embed(title=random_sub.title)
    if random_sub.is_video:
        await ctx.send(random_sub.url)
    else:
        em.set_image(url=random_sub.url)
        await ctx.send(embed=em)

@client.command(name='stackoverflow',aliases=['stack'],help='Shows stackoverflow answers in google')
async def stackoverflow(ctx,*,question):
    URL = "https://google.com/search?q="+question
    page = requests.get(URL, headers=headers, params=params)
    docs=BeautifulSoup(page.text,"html.parser")
    tags=docs.find_all("a",href=True)
    found=False
    all_answers=[]
    all_votes=[]
    for tag in tags:
        if "https://stackoverflow.com"  in tag['href']:
            link=tag['href']
            found=True
            page = requests.get(tag['href'], headers=headers, params=params)
            docs=BeautifulSoup(page.text,"html.parser")
            
            upvotes=docs.find_all("div",{"itemprop": "upvoteCount"})
            answers=docs.find_all("pre")
            
            #remove question
            del upvotes[0]
            del answers[0]

            for count,vote in enumerate(upvotes):
                vote=int(vote.text.strip())
                all_votes.append(vote)
                all_answers.append([link,vote,answers[count].text.strip()])

    

    if found==False:
        await ctx.send("Nothing found!")
    else:
        link,upvote,answer=all_answers[all_votes.index(max(all_votes))]
        embed = discord.Embed(
        title=f'Search Controller ',
            colour=discord.Color.orange())
        embed.description = f'Upvotes: **`{upvote}`**\n\n'
        embed.add_field(name='Searched By', value=ctx.author)
        embed.set_thumbnail(url="https://wizardsourcer.com/wp-content/uploads/2019/03/Stackoverflow.png")
        embed.add_field(name='Link ',value=f'[Click Here!]({link})')
        embed.add_field(name='Answer', value=answer)
        await ctx.send(embed=embed)

@client.command(name='skip',aliases=['sk'],help='This command skips the song')
async def skip(ctx):
    voice_state = ctx.author.voice
    if voice_state is None:
        await ctx.send("You need to be in voice channel!")
    else:
        server = ctx.message.guild
        voice_channel = server.voice_client
        embed = discord.Embed(title=f'Skipped song by : {ctx.author}',
                              colour=discord.Color.blurple())
        voice_channel.stop()
        await ctx.send(embed=embed)


@client.command(name='stop',aliases=['s'],help='This command makes the bot to leave the voice channel')
async def stop(ctx):
    voice_state = ctx.author.voice
    if voice_state is None:
        await ctx.send("You need to be in voice channel!")
    else:
        voice = discord.utils.get(client.voice_clients, guild=ctx.guild)
        channel = ctx.author.voice.channel
        if voice and channel:
            voice_client = ctx.message.guild.voice_client
            del guild_queues[ctx.guild.id]
            await voice_client.disconnect()
            await ctx.send("OK Bye " + str(ctx.author) + "!")

@tasks.loop(seconds=43200)
async def change_status():
    await client.change_presence(activity=discord.Game(status[random.randint(0,len(status)-1)]))


client.run(os.getenv('TOKEN'))