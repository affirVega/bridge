from datetime import datetime
from PIL.Image import Image
import sqlite3
import json
import nextcord
from nextcord.ext import commands
import pickle
import asyncio
import uuid
import io
import random

class Coordinator:
    '''
    Координатор соединяет платформы, пересылая сообщения между ними, поддерживая отправку, изменение, удаление и поиск сообщений.
    '''
    name: str
    platforms: list['Platform']

    def __init__(self, name: str):
        self.name = name
        self.platforms = []

    def start(self):
        for platform in self.platforms:
            platform.start()

    def add_platform(self, platform: 'Platform'):
        self.platforms.append(platform)

    def send(self, exclude_platform: 'Platform', message: 'Message'):
        for platform in self.platforms:
            if platform == exclude_platform: continue
            platform.send(message)
        
        # TODO добавить сохранение сообщения в базу

    def edit(self, exclude_platform: 'Platform', message: 'Message', new_message: 'Message'):
        for platform in self.platforms:
            if platform == exclude_platform: continue
            platform.edit(message, new_message)
        
        # TODO добавить изменение сообщения из базы

    def delete(self, exclude_platform: 'Platform', message: 'Message'):
        for platform in self.platforms:
            if platform == exclude_platform: continue
            platform.delete(message)
        
        # TODO добавить удаление сообщения из базы

    def find(self, exclude_platform: 'Platform', message_id: int):
        # TODO добавить поиск сообщения по базе для пересылки
        return None
    

class Platform:
    coordinator: Coordinator

    def __init__(self):
        pass
    
    def start(self):
        pass

    def send(self, message: 'Message'):
        pass

    def edit(self, message: 'Message', new_message: 'Message'):
        pass

    def delete(self, message: 'Message'):
        pass


class DiscordPlatform(Platform):
    def __init__(self, coordinator: Coordinator, settings: dict[str, object]):
        intents = nextcord.Intents.all()
        self.bot = commands.Bot(intents=intents)
        self.token = settings['token']
        self.guild_id = settings['guild_id']
        self.chat_id = settings['chat_id']

        coordinator.add_platform(self)

        @self.bot.event
        async def on_ready():
            print('on_ready')
            pass

        @self.bot.event
        async def on_close():
            print('on_close')
            pass

        @self.bot.event
        async def on_message(message: nextcord.Message):
            '''
            <Message id=1272539206752665692 channel=<TextChannel id=1258178824726642789 name='робокоты' position=6 nsfw=False news=False category_id=1254431449591840818> type=<MessageType.default: 0>  author=<Member id=252454308149198854 name='affirvega' global_name='Феся' bot=False nick=None  guild=<Guild id=1254431449029935114 name='Кошачий подвал' shard_id=0 chunked=True member_count=15>>  flags=<MessageFlags value=0>>
            []
            []
            None

            <Message id=1272540082250842122 channel=<TextChannel id=1258178824726642789 name='робокоты' position=6 nsfw=False news=False category_id=1254431449591840818> type=<MessageType.default: 0> author=<Member id=252454308149198854 name='affirvega' global_name='Феся' bot=False nick=None guild=<Guild id=1254431449029935114 name='Кошачий подвал' shard_id=0 chunked=True member_count=15>> flags=<MessageFlags value=0>>
            []
            [<StickerItem id=1269371793366450197 name='Гладь' format=StickerFormatType.png>]
            None
            
            <Message id=1272540272143761448 channel=<TextChannel id=1258178824726642789 name='робокоты' position=6 nsfw=False news=False category_id=1254431449591840818> type=<MessageType.default: 0> author=<Member id=252454308149198854 name='affirvega' global_name='Феся' bot=False nick=None guild=<Guild id=1254431449029935114 name='Кошачий подвал' shard_id=0 chunked=True member_count=15>> flags=<MessageFlags value=0>>
            [<Attachment id=1272540271778988194 filename='1209052830380597309.png' url='https://cdn.discordapp.com/attachments/1258178824726642789/1272540271778988194/1209052830380597309.png?ex=66bb58fb&is=66ba077b&hm=4326849fac61e3a663e81771ded5ff80cf490fd6939534b3dca616cf6d2f61c8&'>]
            []
            None

            <Message id=1272540356143087788 channel=<TextChannel id=1258178824726642789 name='робокоты' position=6 nsfw=False news=False category_id=1254431449591840818> type=<MessageType.reply: 19> author=<Member id=252454308149198854 name='affirvega' global_name='Феся' bot=False nick=None guild=<Guild id=1254431449029935114 name='Кошачий подвал' shard_id=0 chunked=True member_count=15>> flags=<MessageFlags value=0>>
            []
            []
            <MessageReference message_id=1272540082250842122 channel_id=1258178824726642789 guild_id=1254431449029935114>
            '''
            if message.guild.id == self.guild_id and message.channel.id == self.chat_id:

                m_message = Message()
                m_message.id = uuid.uuid4()
                m_message.platform_ids[self] = (self.guild_id, self.chat_id, message.id)
                m_message.text = message.content
                for attachment in message.attachments:
                    print(attachment.content_type)
                    buffer = io.BytesIO()
                    if attachment.filename.split('.')[-1] in ['png', 'jpeg', 'jpg', 'webp']:
                        attachment.save(buffer)
                        image = Image()
                        image.frombytes(bytes(buffer))
                        m_message.images.append(image)

                        with open(f'debug{attachment.id%1000}.img', 'wb') as f:
                            image.save(f)
                    else:
                        # TODO добавить как файл
                        pass
                # m_message.voice_message # TODO ?????
                for sticker in message.stickers:
                    data = await sticker.fetch()
                    data = data.read()
                    image = Image()
                    image.frombytes(data)
                    m_message.stickers.append(image)

                    with open(f'sticker{attachment.id%1000}.img', 'wb') as f:
                        image.save(f)
                
                with open('debug.msg', 'w') as f:
                    json.dump(m_message, f)
                print(message)
                print(message.attachments)
                print(message.stickers)
                print(message.reference)

    
    def start(self):
        print('run task')
        self.task = asyncio.create_task(self.bot.start(self.token))

    def send(self, message: 'Message'):
        pass

    def edit(self, message: 'Message', new_message: 'Message'):
        pass

    def delete(self, message: 'Message'):
        pass


class Message:
    timestamp: datetime
    id: int
    platform_ids: dict[Platform, tuple[int, int, int]]
    forwarded_text: str
    text: str
    images: list[Image]
    stickers: list[Image]
    files: list[bytearray]
    voice_message: bytearray
    reply_to: 'Message'
    author_name: str
    author_platform: Platform
    author_id: int
    author_pfp: Image

    def __init__(self):
        self.timestamp = datetime(1970, 1, 1, 0, 0, 0, 0)
        self.platform_ids = dict()
        self.images = []
        self.stickers = []
        self.files = []
        


async def empty_worker():
    while True:
        await asyncio.sleep(0)


if __name__ == '__main__':
    with open('config.json', 'r', encoding="utf8") as f:
        config = json.load(f)
    coordinators: list[Coordinator] = []
    for coordinator_config in config:
        coordinator = Coordinator(coordinator_config.get('name', ''))
        for platform_config in coordinator_config.get('platforms', []):
            match platform_config.get('platform', ''):
                case 'discord':
                    platform = DiscordPlatform(coordinator, platform_config)
        coordinators.append(coordinator)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    async def run_coordinators():
        for coordinator in coordinators:
            coordinator.start()

    loop.create_task(run_coordinators())
    loop.run_forever()
    