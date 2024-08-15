from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import os
from typing import Optional
from PIL import Image
from nextcord.ext import commands
import sqlite3
import json
import nextcord
import pickle
import asyncio
import uuid
import io
import random
import dotenv

dotenv.load_dotenv()

def save_img_randomname(name: str, img: Image.Image):
    return
    with open(f'{name} {uuid.uuid4()}.jpg', 'wb') as f:
        img.convert("L").save(f)


async def image_from_discord_asset(asset: nextcord.Asset | nextcord.Attachment):
    buffer = io.BytesIO()
    await asset.save(buffer)
    image = Image.open(buffer)
    return image


def make_nextcord_file(image: Image.Image, sticker: bool = False):
    if sticker:
        buffer = io.BytesIO()
        image.resize((160, 160)).convert("RGBA").save(buffer, "webp")
        buffer.seek(0)
        return nextcord.File(buffer, filename='sticker.webp')
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, 'jpeg', quality=50, optimize=True)
    buffer.seek(0)
    return nextcord.File(buffer, filename='image.jpeg')


def format_message_content(message: 'MessageBarebone', reference_text=None, attachments_text=None):
    content = f'{message.author.display_name}: {message.content or ''}'
    if message.forwarded:
        content = f'Переслано: {message.forwarded}\n{content}'
    if reference_text:
        content = f'{reference_text}\n{content}'
    if message.reply_to:
        pass # мяу
    if attachments_text:
        content = f'{content}\nФайлы: {attachments_text}'
    return content
    


authors = {}
async def author_from_discord_message(msg: nextcord.Message) -> 'Author':
    if (Platform.Discord, msg.author.id) in authors:
        return authors[(Platform.Discord, msg.author.id)]
    author_pfp = await image_from_discord_asset(msg.author.display_avatar)
    author = Author(Platform.Discord, msg.author.display_name or msg.author.global_name, msg.author.name, msg.author.id, author_pfp)
    authors[(Platform.Discord, author.id)] = author
    return author


class Platform(Enum):
    Discord = 0
    Telegram = 1
    Vk = 2
            

@dataclass
class Chat:
    platform: Platform
    name: Optional[str]
    server_id: Optional[int]
    chat_id: int


@dataclass
class Author:
    platform: Platform
    display_name: str
    username: str
    id: int
    profile_picture: Optional[Image.Image]


@dataclass
class Attachment:
    filename: str
    link: Optional[str]
    data: Optional[bytes | bytearray]


@dataclass
class MessageBarebone:
    uid: str
    timestamp: datetime
    chat: Chat
    message_id: int
    author: Author
    forwarded: Optional[str]
    content: Optional[str]
    reply_to: Optional['MessageBarebone']

    def get_key(self):
        return (self.chat.platform, self.chat.server_id, self.chat.chat_id, self.message_id)


@dataclass
class Message(MessageBarebone):
    attachments: list[Attachment] = field(default_factory=list)
    pictures: list[Image.Image] = field(default_factory=list)
    stickers: list[Image.Image] = field(default_factory=list)
    # TODO voice_message: ???

    def to_barebone(self):
        return MessageBarebone(uid=self.uid, timestamp=self.timestamp, chat=self.chat, 
                               message_id=self.message_id, author=self.author, 
                               forwarded=self.forwarded, content=self.content, 
                               reply_to=self.reply_to)


class Bridger:
    chats: dict['IBot', list[Chat]]
    name: str
    key_to_message: dict[object, MessageBarebone]
    uuid_to_key: dict[str, object]

    def __init__(self, name='Bridger') -> None:
        self.name = name
        self.chats = dict()
        self.key_to_message = dict()
        self.uuid_to_key = dict()
    
    def start(self):
        for bot in self.chats.keys():
            bot.start()

    def add_chat(self, bot: 'IBot', chat: Chat):
        if bot not in self.chats:
            self.chats[bot] = list()
        self.chats[bot].append(chat)

    def send_all(self, exclude_chat: Chat, message: Message):
        self.register_message(message)
        for bot in self.chats.keys():
            for chat in self.chats[bot]:
                if chat == exclude_chat: continue
                asyncio.create_task(bot.send(chat, message))

    def edit_all(self, exclude_chat: Chat, message: MessageBarebone):
        self.update_message(message)
        for bot in self.chats.keys():
            for chat in self.chats[bot]:
                if chat == exclude_chat: continue
                asyncio.create_task(bot.edit(chat, message))

    def delete_all(self, exclude_chat: Chat, message: MessageBarebone):
        for bot in self.chats.keys():
            for chat in self.chats[bot]:
                if chat == exclude_chat: continue
                asyncio.create_task(bot.delete(chat, message))
        self.delete_message(message)

    def find_message(self, local_chat: Chat, local_message_id: int) -> MessageBarebone | None:
        print(f'Запрос {(local_chat.platform, local_chat.server_id, local_chat.chat_id, local_message_id)}')
        message = self.key_to_message.get((local_chat.platform, local_chat.server_id, local_chat.chat_id, local_message_id))
        if message:
            print('Нашли сообщение! :)')
        else:
            print('Сообщение не нашли! :(')
        return message
    
    def find_local_message_id(self, chat: Chat, uid: str) -> int | None:
        keys = self.uuid_to_key.get(uid)
        if not keys:
            return None
        for key in keys:
            if key[0] == chat.platform and key[1] == chat.server_id and key[2] == chat.chat_id:
                return key[3]
        return None
    
    def update_message(self, message: MessageBarebone):
        key = message.get_key()
        if key not in self.key_to_message:
            self.register_message(message)
            return
        self.key_to_message[key].content = message.content
    
    def delete_message(self, message: MessageBarebone):
        keys = self.uuid_to_key.get(message.uid, list())
        for key in keys:
            if key in self.key_to_message:
                self.key_to_message.pop(key)

    def register_message(self, message: MessageBarebone | Message, local_chat: Chat = None, local_message_id: int = None):
        if isinstance(message, Message):
            message = message.to_barebone()
        # register original message chat
        key = message.get_key()
        if key not in self.key_to_message:
            self.key_to_message[key] = message
            if message.uid not in self.uuid_to_key:
                self.uuid_to_key[message.uid] = list()
            self.uuid_to_key[message.uid].append(key)
        if message.reply_to:
            key = message.reply_to.get_key() 
            if key not in self.key_to_message:
                self.key_to_message[key] = message.reply_to
                if message.reply_to.uid not in self.uuid_to_key:
                    self.uuid_to_key[message.reply_to.uid] = list()
                self.uuid_to_key[message.reply_to.uid] = key
        
        # register message in local chat
        if local_chat:
            assert(local_chat is not None, "Надо передать local_message_id")
            assert(local_message_id is not None, "Надо передать local_message_id")
            key = (local_chat.platform, local_chat.server_id, local_chat.chat_id, local_message_id)
            if key not in self.key_to_message:
                self.key_to_message[key] = message
                if message.uid not in self.uuid_to_key:
                    self.uuid_to_key[message.uid] = list()
                self.uuid_to_key[message.uid].append(key)
        
        print('Состояние базы')
        print('---------------------------')
        for key in self.key_to_message.keys():
            msg = self.key_to_message[key]
            print(f'{key} - {msg.author.display_name}: {msg.content}')

        for uid in self.uuid_to_key.keys():
            key = self.uuid_to_key[uid]
            print(f'{uid} - {key}')
        print('---------------------------')


class IBot:
    chats: list[Chat]
    bridger: Bridger
    
    def add_chat(self, chat: Chat):
        pass
    
    def start(self):
        pass

    async def send(self, chat: Chat, message: Message):
        pass

    async def edit(self, chat: Chat, message: MessageBarebone):
        pass

    async def delete(self, chat: Chat, message: MessageBarebone):
        pass


class DiscordBot(IBot):

    def __init__(self, bridger: Bridger, settings: dict[str, object]) -> None:
        self.bridger = bridger
        self.settings = settings
        self.chats = list()
        
        intents = nextcord.Intents.all()
        self.bot = commands.Bot(intents=intents)
        self.token = settings['token']

        @self.bot.event
        async def on_ready():
            print('on_ready')

        @self.bot.event
        async def on_close():
            print('on_close')

        @self.bot.event
        async def on_message(native_message: nextcord.Message):
            if native_message.author.id == self.bot.user.id:
                return
            found_chat: Optional[Chat] = None
            for chat in self.chats:
                if (chat.server_id is None or chat.server_id == native_message.guild.id) and chat.chat_id == native_message.channel.id:
                    found_chat = chat
                    break
            
            if not found_chat:
                print('Сообщение не из моего чата')
                return
            
            # print('Сообщение из чата', found_chat)
            # print('message', native_message)
            # print('attachments', native_message.attachments)
            # print('stickers', native_message.stickers)
            # print('reply_to', native_message.reference)
            # print()

            uid = uuid.uuid4()
            timestamp = native_message.created_at
            chat = found_chat
            message_id = native_message.id
            
            author = await author_from_discord_message(native_message)
            forwarded = None
            content = native_message.content
            reply_to = None
            if native_message.reference is not None:
                reference_message = native_message.reference.cached_message
                if reference_message is None:
                    reference_message = await native_message.channel.fetch_message(native_message.reference.message_id)
                reply_message_id = reference_message.id

                reply_to = self.bridger.find_message(chat, reply_message_id)
                
                if reply_to is None:
                    print('При создании сообщения не нашли референс в базе, создаём новый...')
                    reply_to = MessageBarebone(uuid.uuid4(), reference_message.created_at, chat, reference_message.id, 
                                                 await author_from_discord_message(reference_message), forwarded=None, 
                                                 content=reference_message.content, reply_to=None)
                    # if reference_message.author.id != self.bot.user.id:
                    #     print('Сообщение в ответ не на бота, поэтому добавляем в базу как новое локальное в этом чате')
                    #     # если в базе не нашли сообщение и создали объект message и native_message ссылается не на сообщение бота, то создаём новое в базе
                    #     bridger.register_message(reply_to)
            attachments = []
            pictures = []
            stickers = []
            for attachment in native_message.attachments:
                if attachment.content_type.startswith('image'):
                    image = await image_from_discord_asset(attachment)
                    pictures.append(image)
                    save_img_randomname('img', image)
                else:
                    # data = await attachment.read(use_cached=True)
                    attachments.append(Attachment(attachment.filename, link=attachment.url, data=None))
            for sticker in native_message.stickers:
                image = await image_from_discord_asset(sticker)
                stickers.append(image)
                save_img_randomname('sticker', image)

            message = Message(
                uid, timestamp, chat, message_id, author, forwarded, content, reply_to, attachments, pictures, stickers
            )
            print('Создали нативное сообщение', message)
            
            self.bridger.send_all(chat, message)
        
        @self.bot.event
        async def on_message_edit(before: nextcord.Message, after: nextcord.Message):
            if before.author.id == self.bot.user.id:
                print('Изменилось сообщение меня, игнорирую')
                return
            print(before.content, after.content)
            if before.content == after.content:
                print('Контень сообщения не изменился')
                return
            found_chat: Optional[Chat] = None
            for chat in self.chats:
                if (chat.server_id is None or chat.server_id == before.guild.id) and chat.chat_id == before.channel.id:
                    found_chat = chat
                    break
            
            if not found_chat:
                print('Сообщение не из моего чата')
                return
            
            message = self.bridger.find_message(chat, before.id)
            if not message:
                message = MessageBarebone(uid=uuid.uuid4(), timestamp=before.created_at, chat=chat,
                                          message_id=before.id, author=author_from_discord_message(before),
                                          forwarded=None, content=None, reply_to=None)
            message.content = after.content
            message.content = format_message_content(message)
            
            self.bridger.edit_all(chat, message)
        
        @self.bot.event
        async def on_message_delete(native_message: nextcord.Message):
            if native_message.author.id == self.bot.user.id:
                print('Удалилось моё сообщение, игнорирую')
                return
            found_chat: Optional[Chat] = None
            for chat in self.chats:
                if (chat.server_id is None or chat.server_id == native_message.guild.id) and chat.chat_id == native_message.channel.id:
                    found_chat = chat
                    break
            
            if not found_chat:
                print('Сообщение не из моего чата')
                return
            
            message = self.bridger.find_message(chat, native_message.id)
            if not message:
                message = MessageBarebone(uid=uuid.uuid4(), timestamp=native_message.created_at, chat=chat,
                                          message_id=native_message.id, author=author_from_discord_message(native_message),
                                          forwarded=None, content=native_message.content, reply_to=None)
            
            self.bridger.delete_all(chat, message)

    def add_chat(self, chat: Chat):
        self.chats.append(chat)
        self.bridger.add_chat(self, chat)
    
    def start(self):
        self.task = asyncio.create_task(self.bot.start(self.token))

    async def send(self, chat: Chat, message: MessageBarebone):
        files = []
        print('создаём файлы')
        for sticker in message.stickers:
            if len(files) >= 10: break
            files.append(make_nextcord_file(sticker, True))
        for picture in message.pictures:
            if len(files) >= 10: break
            files.append(make_nextcord_file(picture))
        attachments_text = ''
        for attachment in message.attachments:
            attachments_text += f'{attachment.link}\n'

        message_reference: nextcord.MessageReference = None
        reference_text: str = None
        if message.reply_to:
            if message.reply_to.chat == chat:
                print('Реплай в моём чате, отвечу на сообщение тут')
                message_reference = nextcord.MessageReference(message_id=message.reply_to.message_id, 
                                                              channel_id=message.reply_to.chat.chat_id, 
                                                              guild_id=message.reply_to.chat.server_id, 
                                                              fail_if_not_exists=True)
            else:
                print('Реплай в другом чате был')
                # TODO попытаться найти это сообщение в локальном чате и на него ответить
                message_id = self.bridger.find_local_message_id(chat, message.reply_to.uid)
                if message_id is not None:
                    message_reference = nextcord.MessageReference(message_id=message_id, 
                                                              channel_id=chat.chat_id, 
                                                              guild_id=chat.server_id, 
                                                              fail_if_not_exists=True)
                else:
                    print('По uid обратно не нашли, делаем реплай в виде текста')
                    max_length = 100
                    reply_content = message.reply_to.content
                    if len(reply_content) > max_length:
                        reply_content = message.reply_to.content[:max_length] + '...'
                    reference_text = f'В ответ на {message.reply_to.author.display_name}: {reply_content}'
        
        print('начинаем отправлять сообщение')
        content = format_message_content(message, reference_text, attachments_text)
        sent_message = await self.bot.get_channel(chat.chat_id).send(
            content, files=files, reference=message_reference, mention_author=True, 
        )
        print('отправили')
        print('регистрируем отправленное сообщение')
        self.bridger.register_message(message, chat, sent_message.id)

    async def edit(self, chat: Chat, message: MessageBarebone):
        message_id = self.bridger.find_local_message_id(chat, message.uid)
        if not message_id:
            print('Не нашли message id для редактирования')
            return
        await self.bot.get_channel(chat.chat_id).get_partial_message(message_id).edit(content=message.content)
        

    async def delete(self, chat: Chat, message: MessageBarebone):
        message_id = self.bridger.find_local_message_id(chat, message.uid)
        if not message_id:
            print('Не нашли message id для удаления')
            return
        await self.bot.get_channel(chat.chat_id).get_partial_message(message_id).delete()


bridger: Bridger = None
async def main():
    global bridger
    bridger = Bridger('Тесты')

    if os.path.exists('messagedb.pkl'):
        print('Читаем базу сообщений')
        with open('messagedb.pkl', 'rb') as f:
            bridger.key_to_message = pickle.load(f)
            print(f'Прочитали! {len(bridger.key_to_message.keys())} сообщений в базе')
    else:
        print('База сообщений пуста')
    
    if os.path.exists('uid_msgid.pkl'):
        print('Читаем базу uid_msgid')
        with open('uid_msgid.pkl', 'rb') as f:
            bridger.uuid_to_key = pickle.load(f)
            print(f'Прочитали! {len(bridger.uuid_to_key.keys())} связей в базе')
    else:
        print('База uid_msgid пуста')

    DISCORD_TOKEN=os.environ.get('DISCORD_TOKEN')

    discord = DiscordBot(bridger, {
        'token': DISCORD_TOKEN
    })
    chat = Chat(Platform.Discord, 'робокоты', server_id=1254431449029935114, chat_id=1258178824726642789)
    chat2 = Chat(Platform.Discord, 'робокоты', server_id=1254431449029935114, chat_id=1272671241056026747)
    discord.add_chat(chat)
    discord.add_chat(chat2)
    bridger.start()


loop = asyncio.new_event_loop()
try:
    loop.create_task(main())
    loop.run_forever()
except KeyboardInterrupt:
    print('Ctrl+C pressed. Stopping...')
finally:
    if bridger and bridger.key_to_message:
        print('Сохраняем базу сообщений через pickle')
        with open('messagedb.pkl', 'wb') as f:
            pickle.dump(bridger.key_to_message, f)
            print('Успешно сохранили!')
    
    if bridger and bridger.uuid_to_key:
        print('Сохраняем базу сообщений uid_msgid через pickle')
        with open('uid_msgid.pkl', 'wb') as f:
            pickle.dump(bridger.uuid_to_key, f)
            print('Успешно сохранили!')
    loop.stop()
    loop.close()