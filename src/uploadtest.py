import io
import logging
import os
import time
import nextcord
from nextcord.ext import commands
import sys
from PIL import Image
import base64
import requests

log = logging.getLogger('main')
log.setLevel(logging.DEBUG)
stderrhandler = logging.StreamHandler(sys.stderr)
stderrhandler.setFormatter(logging.Formatter('%(levelname)s: %(name)s at %(asctime)s on line %(lineno)d: %(message)s'))
log.addHandler(stderrhandler)

pfp = base64.decodebytes(b'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\n')
buf = io.BytesIO(pfp)

answer = requests.post(os.environ.get('UPLOAD_SERVER'), files={'file': ('pfp.png', buf)})

print(answer.json())
if not answer.ok:
    print('пизда')
    exit()

# intents = nextcord.Intents.all()
# bot = commands.Bot(intents=intents)

# channels = {}

# @bot.event
# async def on_ready():
#     log.info('on_ready')

# @bot.event
# async def on_close():
#     log.info('on_clise')

# @bot.event
# async def on_message(native_message: nextcord.Message):
#     if native_message.author.bot:
#         return
#     print('Created message')
#     print(native_message)

#     channel = native_message.channel
#     webhooks = await native_message.channel.webhooks()
#     print('List of webhooks:', webhooks)
#     avatar = None
#     webhook = None
#     for wh in webhooks:
#         if wh.name.startswith('bridge'):
#             webhook = wh
#             break
#     if webhook is None:
#         webhook = await channel.create_webhook(name='bridge ' + str(time.time())[-6:], avatar=nextcord.File(buf), reason='Отправка сообщений')
#         print('Created webhook:', webhook)
    
#     message = await webhook.send(content=native_message.content, 
#                                  username=native_message.author.name, 
#                                  delete_after=15,
#                                  wait=True,
#                                  avatar_url=native_message.author.avatar.url)
#     print('Sent message:', 'ID', message.id, '\nАвтор', message.author, '\nКанал', message.channel.id, '\nСодержание', message.content, '\nПолностью', message)
#     await message.edit(content=message.content + '\n> лигма болс')
    

# @bot.event
# async def on_message_edit(_before: nextcord.Message, after: nextcord.Message):
#     print('Edited message')
#     print(_before, after)

# @bot.event
# async def on_message_delete(native_message: nextcord.Message):
#     print('Deleted message')
#     print(native_message)

# import dotenv
# dotenv.load_dotenv()
# import os
# bot.run(os.environ.get('DISCORD_TOKEN'))