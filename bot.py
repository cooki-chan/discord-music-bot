import discord
from discord import app_commands
from discord.ext import tasks
from pytube import YouTube as yt, Search, Playlist
import re
import random
from queue import Queue
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from requests import exceptions
import yt_dlp

#THINGS THAT NEED TO BE SET BEFORE RUN!!!!
guildList = [] #GUILDS THAT USE THIS BOT
soundLoc = "" #WHERE YOU WANT TO SAVE YOUR MUSIC
clientKey = '' #BOT KEY
guilds = []
for i in guildList:
    guilds.append(discord.Object(id=i))

#Spotify API
clientID = "" #SPOTIFY CLIENT ID
secretID = "" #SPOTIFY SECRET 
auth_manager = SpotifyClientCredentials(client_id=clientID, client_secret=secretID)
sp = spotipy.Spotify(auth_manager=auth_manager)

#Discord API
client = discord.Client(intents=discord.Intents.all())
tree = app_commands.CommandTree(client)

@client.event
async def on_ready():
    for i in guildList:
        await tree.sync(guild=discord.Object(i))
    print('We have logged in as {0.user}'.format(client))
    activity = discord.Activity(name="/play frfr", type=discord.ActivityType.playing)
    await client.change_presence(activity=activity)

#Script Global Variables
mainQ = Queue()
downloadQ = Queue()
voice = None
currentSong = None
lastChannel = None


#---------------------- DISCORD COMMANDS -------------------------------------------------------------------------------------------------------------------
#TODO Make a shuffle command

#Play Song
@tree.command(name = "play", description = "A yt/spotify playlist, yt vid, or a general search! spotify and search may be a bit inaccurate...", guilds=guilds)
async def play(ctx, search: str):
    if await checkConditions(ctx, True): return

    audio = []
    nameOf = ""
    await ctx.response.defer(ephemeral=True) #defer since this takes a while depending on the choice

    #Youtube Video
    if re.search("watch\?v=[0-9A-Za-z_-]{11}", search):
        track = yt(search)

        audio.append(track)
        nameOf = track.title
        try:
            track.check_availability()
        except Exception:
            await ctx.followup.send(embed=errorEmbed("That link doesn't work, please try again."), ephemeral=True)
            return

    #Youtube Playlist
    elif re.search("list=[0-9A-Za-z_-]{34}", search):
        list = Playlist(search)
        nameOf = list.title

        #Check Existance
        try:
            list[0]
        except Exception:
            await ctx.followup.send(embed=errorEmbed("I don't have access to that playlist, please try again."), ephemeral=True)
            return    
        
        #Add to audio list
        index = 0
        for i in list.videos:
            if i.length >= 3600: #Length Limit
                await ctx.channel.send(embed=errorEmbed(f"Sorry! The song {i.title} is too long to play D: It has been skipped"), ephemeral=True)
                pass

            if index <= 1: #load first song
                audio.append(i)
                print("[play] added " + i.title)
            else: #Put all others to be added in background
                downloadQ.put(i)
                print("[play] preloaded " + i.title)
            index+=1
            
    #Spotify Playlist
    elif re.search("open.spotify.com/playlist", search):

        #Check Playlist Existance 
        try:
            playlist = sp.playlist(search)
            nameOf = playlist["name"]
        except exceptions.HTTPError: 
            await ctx.followup.send(embed=errorEmbed("Something is wrong with that link, please try again."), ephemeral=True)
            return

        #Get vid from YT since spotify doesn't allow for track download
        index = 0
        for i in playlist['tracks']['items']:
            if i['track']["duration_ms"] >= 3600000: #Length Limit
                await ctx.channel.send(embed=errorEmbed(f"Sorry! The song {i.title} is too long to play D: It has been skipped"), ephemeral=True)
                pass

            if index <= 1: #load first song
                track = Search(i['track']['name'] + " by " + i["track"]["artists"][0]["name"]).results[0]
                audio.append(track)
                print("[play] added " + i['track']['name'])
            else: #Put all others to be added in background
                downloadQ.put(i['track']['name'] + " by " + i["track"]["artists"][0]["name"])
                print("[play] preloaded " + i['track']['name'])
            
            index+=1

    #Spotify Album
    elif re.search("open.spotify.com/album", search):
        try:
            album = sp.album(search)
            nameOf = album["name"]
        except exceptions.HTTPError: 
            await ctx.followup.send(embed=errorEmbed("Something is wrong with that link, please try again."), ephemeral=True)
            return

        index = 0
        for i in album['tracks']['items']: #load first song
            if index <= 1:
                track = Search(i["name"] + " " + i["artists"][0]["name"]).results[0]
                audio.append(track)
                print("[play] added " + i['name'])
            else: #Put all others to be added in background
                downloadQ.put(i["name"] + " " + i["artists"][0]["name"])
                print("[play] preloaded " + i['name'])
            
            index+=1
    
    #Spotify Track
    elif re.search("open.spotify.com/track", search):
        try:
            track = sp.track(search)
            nameOf = track["name"]
        except exceptions.HTTPError: 
            await ctx.followup.send(embed=errorEmbed("Something is wrong with that link, please try again."), ephemeral=True)
            return

        track = Search(track["name"] + " " + track["artists"][0]["name"]).results[0]
        audio.append(track)

    #General Search (No other results)
    else:
        #Check Existance of Song
        try:
            track = Search(search).results[0]
            audio.append(track)
            nameOf = track.title
        except IndexError:
            await ctx.followup.send(embed=errorEmbed("Sorry! Your search query yielded no results"), ephemeral=True)
            return
        
    #Track Adding to Queue
    for i in audio:
        mainQ.put(i)
        print("[play] added " + i.title + " to queue")

    #Start up bot / Join vc if dead
    global voice
    vc = ctx.user.voice.channel
    if voice == None:
        voice = await vc.connect()
        main.start()
    
    #Start up blackground loading queue if needed
    if downloadQ.qsize() == 0:
        load.start()
    
    await ctx.followup.send(embed=successEmbed(f"{nameOf} has been added!"), ephemeral=True)

#Skips the current song TODO Make amount of soungs skipped 
@tree.command(name = "skip", description = "next.", guilds=guilds)
async def skip(ctx):
    if await checkConditions(ctx, False): return

    await ctx.response.defer()
    voice.pause() #Cut off the song at that exact moment
    if mainQ.empty():
        await endBot()
        await ctx.followup.send(embed = defaultEmbed(":fast_forward: Disconnecting...", "That was the last song!"))
    else:
        track = mainQ.get()
        await playSong(track, ctx.channel)
        await ctx.followup.send(embed = defaultEmbed(":fast_forward: Song has been skipped!", "Playing next song..."))

@tree.command(name = "queue", description = "what's next?", guilds=guilds)
async def queue(ctx):
    if await checkConditions(ctx, False): return

    await ctx.response.defer()
    embedVar = discord.Embed(title="Song Queue! :notes: :notes: :notes:", description="", color=0x1999ff)
    index = 1
    if voice != None:
        embedVar.add_field(name=f"Current Song: {currentSong.title}", value=f"Duration: {int(currentSong.length/60)}:{currentSong.length%60}", inline=False)
    for i in mainQ.queue: 
        if index <= 10:
            embedVar.add_field(name=f"{index}: {i.title}", value=f"Duration: {int(i.length/60)}:{i.length%60}", inline=False)
        index+=1
    
    if index > 10:
        embedVar.add_field(name=f"and {(index - 20) + downloadQ.qsize()} other songs :sparkles:", value=f":p", inline=False)

    if index == 1 and currentSong == None:
        await ctx.followup.send(embed = defaultEmbed("No songs in queue", "Use /play to add one :D"))
        return

    await ctx.followup.send(embed = embedVar)

@tree.command(name = "stop", description = "end me D:", guilds=guilds)
async def stop(ctx):
    if await checkConditions(ctx, False): return
    await ctx.response.send_message(embed = defaultEmbed("Bot has been stopped.", "Hope you enjoyed my songs!"))
    await endBot()

@tree.command(name = "pause", description = "pause", guilds=guilds)
async def pause(ctx):
    if await checkConditions(ctx, False): return

    if voice.is_paused():
        await ctx.response.send_message(embed=errorEmbed(("Bot is already paused! Use /resume to continue!")))
    else:
        voice.pause()
        await ctx.response.send_message(embed=defaultEmbed("Paused", "Paused"))

@tree.command(name = "resume", description = "resume", guilds=guilds)
async def resume(ctx):
    if await checkConditions(ctx, False): return

    if voice.is_paused():
        voice.resume()
        await ctx.response.send_message(embed=defaultEmbed("Resumed", ":D"))
    else:
        await ctx.response.send_message(embed=errorEmbed(("Bot is already playing! Use /pause to stop!")))

@tree.command(name = "playing", description = "what's playing?", guilds=guilds)
async def now(ctx):
    if currentSong == None:
        await ctx.response.send_message(embed=defaultEmbed("There is no song playing!", "Use /play to play one!"))
    else:
        await ctx.response.send_message(embed=defaultEmbed("Current Song", currentSong.title))

@tree.command(name = "debug", description = "are you sure u want to touch?", guilds=guilds)
async def debug(ctx):
    embedVar = discord.Embed(title="Debug", description="", color=0x000000)
    embedVar.add_field(name=f"Main Loop", value=str(main.is_running()), inline=False)
    embedVar.add_field(name=f"Backload Loop", value=str(load.is_running()), inline=False)
    if voice != None:
        embedVar.add_field(name=f"Channel", value=voice.channel.name + " | " + str(voice.channel.id), inline=False)
        embedVar.add_field(name=f"Playing Anything?", value=f"main says: {str(main.is_running())} | voice says: {voice.is_playing()}, paused? {voice.is_paused()}", inline=False)
        
    else:
        embedVar.add_field(name=f"Channel", value="Currently not Defined", inline=False)

    if currentSong != None:
        embedVar.add_field(name=f"Current Song", value=currentSong.title + " | " + currentSong.vid_info["videoDetails"]["videoId"], inline=False)
    else:
        embedVar.add_field(name=f"Current Song", value=f"Currently Not Defined", inline=False)

    embedVar.add_field(name=f"Main Queue Length", value=str(mainQ.qsize()), inline=False)
    embedVar.add_field(name=f"Backload Queue Length", value=str(downloadQ.qsize()), inline=False)
    await ctx.response.send_message(embed = embedVar, ephemeral=True)


#---------------------- LOOPS (NOT COMMANDS) --------------------------------------------------------------------------------------------------------------

#Main Player Loop
@tasks.loop(seconds=0.5)
async def main():
    global voice
    global currentSong

    #If not playing anything (Next if statment assumes voice is defined)
    if voice == None:
        main.stop()
        return

    #If not playing anything and not paused (Not playing anything)
    if not voice.is_playing() and not voice.is_paused():

        #No song left in queue
        if mainQ.empty():
            await endBot()
            await lastChannel.send(embed=defaultEmbed(":pause_button:  All songs have been played!", "Disconnecting..."))

        #There are songs next in queue
        else:
            await playSong(mainQ.get(), lastChannel)
    
    #Leave vc if nobody else is in vc (save resources)
    if len(voice.channel.members) == 1:
        await endBot()
        await lastChannel.send(embed=defaultEmbed(":pause_button:  I was left all alone D:", "Disconnecting..."))

    #Start up blackground loading queue if needed
    if downloadQ.qsize() != 0 and not load.is_running():
        load.start()

#Background Song Loader
@tasks.loop(seconds=1)
async def load():
    if downloadQ.empty():
        load.stop()
        return

    query = downloadQ.get()
    if type(query) == str:
        track = Search(query).results[0]
        mainQ.put(track)
        print("[load] added " + query)
    else:
        mainQ.put(query)
        print("[load] added " + query.title)

#---------------------- HELPER FUNCTIONS (NOT COMMANDS) ----------------------------------------------------------------------------------------------------

#Checks to make sure all commands have the values they need
async def checkConditions(ctx, isMain):
    global lastChannel
    lastChannel = ctx.channel

    error = False
    embedVar = discord.Embed(title="", description="", color=0xff0000)

    
    if ctx.user.voice == None:
        embedVar.add_field(name="Error:", value="Join a vc to use this command!", inline=False)
        error = True
    elif voice != None and ctx.user.voice.channel != voice.channel:
        embedVar.add_field(name="Error:", value="You are in the wrong vc, please try again!", inline=False)
        error = True
    elif not isMain: #If main is used without a queue, then it would error without this
        if voice == None:
            embedVar.add_field(name="Error:", value="Nothing is playing!", inline=False)
            error = True

    if error:
        await ctx.response.send_message(embed=embedVar, ephemeral=True)
    return error

#Plays the track given (YT Track)
async def playSong(track, channel):
    global currentSong
    global voice

    #yt_dlp options
    tag = random.randint(1, 1000000)
    ydl_opts = {"listformats":False, "outtmpl":"music/out" + str(tag) + ".mp3", 'format': 'bestaudio/best'}
    
    yt_dlp.YoutubeDL(ydl_opts).download([f'https://www.youtube.com/watch?v={track.vid_info["videoDetails"]["videoId"]}'])
    voice.play(discord.FFmpegPCMAudio(executable="ffmpeg.exe", source=soundLoc + f"out{tag}.mp3"))
    currentSong = track

    await channel.send(embed = defaultEmbed(f":arrow_forward:  Now Playing: {track.title}", f"Duration: {int(track.length/60)}:{track.length%60}"))

#Kills the audio player and resets everything
async def endBot():
    global voice
    global currentSong
    global mainQ
    global downloadQ

    await voice.disconnect()
    mainQ = Queue()
    downloadQ = Queue()
    voice = None
    main.stop()
    load.stop()
    currentSong = None    

#Red Error Message
def errorEmbed(msg):
    embedVar = discord.Embed(title="", description="", color=0xff0000)
    embedVar.add_field(name=":interrobang:  Error:", value=msg, inline=False)
    return embedVar

#Green Success Message
def successEmbed(msg):
    embedVar = discord.Embed(title="", description="", color=0x00ff00)
    embedVar.add_field(name=":white_check_mark:  Success!", value=msg, inline=False)
    return embedVar

#Blue General Message
def defaultEmbed(title, msg: str):
    embedVar = discord.Embed(title="", description="", color=0x1999ff)
    embedVar.add_field(name=title, value=msg, inline=False)
    return embedVar

client.run(clientKey)
