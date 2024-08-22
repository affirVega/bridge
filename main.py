import asyncio
from dataclasses import dataclass, field
import enum
import io
import os
import sys
from typing import Optional
import uuid
from PIL import Image
import dotenv
import requests
import logging
from logging import DEBUG, INFO, WARN, ERROR, CRITICAL
import nextcord
from nextcord.ext import commands

log = logging.getLogger('main')
log.setLevel(DEBUG)
stderrhandler = logging.StreamHandler(sys.stderr)
stderrhandler.setFormatter(logging.Formatter('%(levelname)s: %(name)s at %(asctime)s on line %(lineno)d: %(message)s'))
log.addHandler(stderrhandler)

logging.getLogger('nextcord').setLevel(logging.ERROR)
logging.getLogger('vkbottle').setLevel(logging.DEBUG)

dotenv.load_dotenv()


def tryexcept_get(function, _default=None, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except Exception or RuntimeError or RuntimeWarning:
        pass
    return _default


class Platform(enum.Enum):
    Discord = 0
    Telegram = 1
    Vk = 2


@dataclass
class Chat:
    platform: Platform
    id: int
    server_id: Optional[int] = None

    def __hash__(self):
        return hash((self.platform, self.id, self.server_id))


@dataclass
class IAttachment:
    name: Optional[str] = None

    def uncache(self):
        ...


@dataclass
class IPicture(IAttachment):
    def get_image(self) -> Image.Image:
        ...


@dataclass
class UrlPicture(IPicture):
    url: str = None
    _cached_image: Image.Image = field(default=None, init=False, repr=False)

    def get_image(self) -> Optional[Image.Image]:
        if self._cached_image:
            return self._cached_image
        try:
            return self._download_image(self)
        except Exception:
            return None
    
    def _download_image(self) -> Image.Image:
        buffer = io.BytesIO(requests.get(self.url).content)
        self._cached_image = Image.open(buffer)
        return self._cached_image
    
    def uncache(self):
        del self._cached_image
        self._cached_image = None


@dataclass
class Sticker(UrlPicture):
    pass


@dataclass
class IFile(IAttachment):

    def get_file(self) -> Optional[bytes]:
        ...


@dataclass
class UrlFile(IFile):
    url: str = None
    _cached_data: bytes = field(default=None, init=False, repr=False)

    def get_file(self) -> Optional[bytes]:
        if self._cached_data:
            return self._cached_data
        try:
            return self._download_file(self)
        except Exception:
            return None
    
    def _download_file(self) -> bytes:
        self._cached_data = requests.get(self.url).content
        return self._cached_data
    
    def uncache(self):
        del self._cached_data
        self._cached_data = None


@dataclass
class Author:
    platform: Platform
    id: int
    name: str
    username: str
    pfp: IPicture


@dataclass
class MessageID:
    chat: Chat
    id: int

    def __hash__(self):
        return hash((self.chat, self.id))


@dataclass
class Message:
    original_id: MessageID
    author: Author
    text: str
    reply_to: Optional['Message'] = None
    relay_ids: list[MessageID] = field(default_factory=list)
    forwarded: list['Message'] = field(default_factory=list)
    attachments: list[IAttachment] = field(default_factory=list)

    def get_message_id(self, chat: Chat) -> Optional[int]:
        if chat == self.original_id.chat:
            return self.original_id.id
        for relay_id in self.relay_ids:
            if relay_id.chat == chat:
                return relay_id.id
        return None

    def __hash__(self):
        return hash(self.original_id)


@dataclass
class Coordinator:
    bridges: list['Bridge'] = field(default_factory=list)
    bots: list['IBot'] = field(default_factory=list)
    chats: list['Chat'] = field(default_factory=list)
    authors: list[Author] = field(default_factory=list)
    
    chat_to_bot: dict[Chat, 'IBot'] = field(default_factory=dict)

    message_db: list[Message] = field(default_factory=list)
    m_id_to_message: dict[MessageID, Message] = field(default_factory=dict)

    def _save(self):
        pass

    def _load(self, db):
        pass

    def add_author(self, author: Author):
        if author not in self.authors:
            self.authors.append(author)
            log.info(f'Добавили автора {author.name}')

    def get_author(self, platform: Platform, id: int) -> Optional[Author]:
        for author in self.authors:
            if author.id == id and author.platform == platform:
                return author
        return None
    
    def start_all_bots(self):
        log.info('Запускаем всех ботов')
        for bot in self.bots:
            if bot.is_running():
                log.info(f'Бот {bot.display_name()} уже запущен')
            else:
                bot.start()

    def db_add_message(self, message: Message):
        if message in self.message_db:
            return
        self.message_db.append(message)
        for m_id in [message.original_id] + message.relay_ids:
            if m_id not in self.m_id_to_message:
                self.m_id_to_message[m_id] = message
                
        log.info(f'Добавили сообщение {message.original_id}')
        
        if message.reply_to:
            self.db_add_message(message.reply_to)
        
        for fwd in message.forwarded:
            self.db_add_message(fwd)
    
    def db_get_message(self, message_id: MessageID) -> Optional[Message]:
        return self.m_id_to_message.get(message_id)

    def db_add_message_relay_id(self, message_id: MessageID, message: Message):
        self.m_id_to_message[message_id] = message
        log.debug(f'Связали сообщение {message.author.name} {message.text[:20]}... с relay id {message_id}')

    def add_bridge(self, bridge: 'Bridge'):
        if bridge not in self.bridges:
            self.bridges.append(bridge)
            log.info(f'Добавили мост {bridge.id}')
    
    def add_chat_to_bridge(self, bridge: 'Bridge', chat: Chat):
        if bridge not in self.bridges:
            log.error('Попытались добавить чат к недобавленному мосту')
            raise ValueError('Попытались добавить чат к недобавленному мосту', bridge, chat)
        if chat not in self.chats:
            self.chats.append(chat)
        bridge.add_chat(chat)
        log.info(f'Добавили чат {chat} в мост {bridge.id}')
    
    def link_bot_chat(self, bot: 'IBot', chat: Chat):
        if chat not in self.chats:
            log.error('Попытались слинковать бота к недобавленному чату')
            raise ValueError('Попытались слинковать бота к недобавленному чату', bot, chat)
        self.add_bot(bot)
        bot.add_chat(chat)
        if chat not in self.chat_to_bot:
            self.chat_to_bot[chat] = bot
        log.info(f'Связали {bot.display_name()} и чат {chat}')
    
    def add_bot(self, bot: 'IBot'):
        if bot not in self.bots:
            self.bots.append(bot)
            log.info(f'Добавили бота {bot.display_name()}')

    def get_bridges(self) -> list['Bridge']:
        return self.bridges
    
    def get_bot_by_chat(self, chat: Chat) -> Optional['IBot']:
        return self.chat_to_bot.get(chat, None)

    def find_relay_bots_chats(self, chat: Chat) -> dict['IBot', list[Chat]]:
        chat_bridges = [b for b in self.get_bridges() if chat in b.chats]
        total_chats = list()
        for bridge in chat_bridges:
            total_chats += bridge.chats
        
        # remove chat message came from
        total_chats.remove(chat)

        relay_chat_to_bot: dict['IBot', list[Chat]] = dict()
        for relay_chat in total_chats:
            bot = self.get_bot_by_chat(relay_chat)
            if not isinstance(bot, IBot):
                log.warn(f'Не могу найти бота по чату {relay_chat}')
                continue
            if bot not in relay_chat_to_bot:
                relay_chat_to_bot[bot] = list()
            relay_chat_to_bot[bot].append(relay_chat)
        
        return relay_chat_to_bot

    async def send_all(self, message: Message):
        if message is None:
            log.error('Кто-то отправил None message')
            return
        log.debug(f'Отправляем сообщение [{message.original_id}] {message.author.name}: {message.text[:20]}...')
        bots_chats = self.find_relay_bots_chats(message.original_id.chat)
        for bot in bots_chats:
            chats = bots_chats[bot]
            for chat in chats:
                m_id = await bot.send_message(chat, message)
                self.db_add_message_relay_id(m_id, message)
                
    
    async def edit_all(self, new_message: Message):
        if new_message is None:
            log.error('Кто-то отправил None message')
            return
        log.debug(f'Редактируем сообщение [{new_message.original_id}] {new_message.author.name}: {new_message.text[:20]}...')
        for relay_m_id in new_message.relay_ids:
            bot = self.get_bot_by_chat(relay_m_id.chat)
            if not bot:
                log.warn(f'Не могу найти бота по чату {new_message.original_id.chat}')
                continue
            await bot.edit_message(relay_m_id, new_message)
    
    async def delete_all(self, message: Message):
        if message is None:
            log.error('Кто-то отправил None message')
            return
        log.debug(f'Удаляем сообщение [{message.original_id}] {message.author.name}: {message.text[:20]}...')
        for relay_m_id in message.relay_ids:
            bot = self.get_bot_by_chat(relay_m_id.chat)
            if not bot:
                log.warn(f'Не могу найти бота по чату {relay_m_id.chat}')
                continue
            await bot.delete_message(relay_m_id)


@dataclass
class Bridge:
    id: int
    chats: list[Chat] = field(default_factory=list)

    def add_chat(self, chat: Chat):
        if chat not in self.chats:
            self.chats.append(chat)
    
    def remove_chat(self, chat: Chat):
        if chat in self.chats:
            self.chats.remove(chat)


@dataclass
class IBot:
    id: int
    name: str
    coordinator: Coordinator
    platform: Platform = field(default=None, init=False)
    chats: list[Chat] = field(default_factory=list)

    def log(self, level: int, message: str):
        ...

    def add_chat(self, chat: Chat):
        if chat not in self.chats:
            self.chats.append(chat)
    
    def remove_chat(self, chat: Chat):
        if chat in self.chats:
            self.chats.remove(chat)
    
    def get_current_chat(self, platform: Platform, server_id: int, chat_id: int):
        for chat in self.chats:
            if chat.platform == platform and chat.server_id == server_id and chat.id == chat_id:
                return chat
        return None
    
    def is_running(self) -> bool:
        ...
    
    def start(self):
        ...

    def stop(self):
        ...
    
    def send_message(self, chat: Chat, message: Message) -> MessageID:
        ...

    def edit_message(self, message_id: MessageID, new_message: Message):
        ...

    def delete_message(self, message_id: MessageID):
        ...
    
    def display_name(self) -> str:
        return f'{Platform(self.platform).name} {self.id} {self.name}'
    
    def __hash__(self) -> int:
        return super().__hash__()


@dataclass
class DiscordBot(IBot):
    platform: Platform = field(default=Platform.Discord, init=False)
    listtings: dict[str, object] = field(default_factory=dict)
    bot: commands.Bot = field(default=None, init=False)
    task: asyncio.Task = field(default=None, init=False)

    def get_current_chat_from_native_message(self, message: nextcord.Message):
        return self.get_current_chat(Platform.Discord, message.guild.id, message.channel.id)

    def log(self, level: int, message: str):
        log.log(level, str(f'{self.id} {self.name} bot: f{message}'))
    
    def get_author(self, user: nextcord.User):
        author = self.coordinator.get_author(Platform.Discord, user.id)
        if author: 
            return author
        pfp = None
        if user.avatar:
            pfp = UrlPicture(f'pfp of {user.name}', user.avatar.url)
        author = Author(Platform.Discord, id=user.id, 
                        name=user.display_name or user.global_name or user.name, 
                        username=user.name, pfp=pfp)
        return author

    def __post_init__(self):
        intents = nextcord.Intents.all()
        self.bot = commands.Bot(intents=intents)

        @self.bot.event
        async def on_ready():
            self.log(INFO, 'on_ready')

        @self.bot.event
        async def on_close():
            self.log(INFO, 'on_clise')

        @self.bot.event
        async def on_message(native_message: nextcord.Message):
            if native_message.author == self.bot.user:
                return
            self.log(INFO, 'on_message')
            chat = self.get_current_chat_from_native_message(native_message)
            if not chat:
                self.log(DEBUG, f'Сообщение не из моего чата: {native_message.author.name}: {native_message.content[:20]}')
                return

            message = await self.create_message_from_native(native_message, chat)
            self.coordinator.db_add_message(message)
            await self.coordinator.send_all(message)
        
        @self.bot.event
        async def on_message_edit(before: nextcord.Message, after: nextcord.Message):
            if before.author == self.bot.user:
                return
            self.log(INFO, 'on_message_edit')
            chat = self.get_current_chat_from_native_message(before)
            if not chat:
                self.log(DEBUG, f'Сообщение не из моего чата: {before.author.name}: {before.content[:20]}')
                return
            
            # TODO

        @self.bot.event
        async def on_message_delete(native_message: nextcord.Message):
            if native_message.author == self.bot.user:
                return
            self.log(INFO, 'on_message_delete')
            chat = self.get_current_chat_from_native_message(native_message)
            if not chat:
                self.log(DEBUG, f'Сообщение не из моего чата: {native_message.author.name}: {native_message.content[:20]}')
                return
            
            # TODO

    async def create_message_from_native(self, native_message: nextcord.Message, chat: Chat) -> Message:
        if native_message is None:
            return None
        message = self.coordinator.db_get_message(MessageID(chat, native_message.id))
        if message:
            return message
        reply_to = None
        if native_message.reference:
            try:
                reference_message = await native_message.channel.fetch_message(native_message.reference.message_id)
                reply_to = await self.create_message_from_native(reference_message, chat)
            except Exception:
                pass
        attachments = [] # TODO
        message = Message(MessageID(chat, native_message.id),
                            author=self.get_author(native_message.author),
                            text=native_message.content, reply_to=reply_to,
                            attachments=attachments)
        return message
    
    def is_running(self) -> bool:
        return self.task and self.task.done()
    
    def start(self):
        self.task = asyncio.create_task(self.bot.start(self.listtings['token']))
        self.log(INFO, f"Бот discord {self.display_name()} запущен")

    def stop(self):
        self.task.cancel()
    
    async def send_message(self, chat: Chat, message: Message) -> MessageID:
        reference = None
        if message.reply_to:
            if message.reply_to.original_id.chat == chat:
                self.log(DEBUG, f"reply original id chat is current chat")
            
            message_id = message.reply_to.get_message_id(chat)
            if message_id:
                reference = nextcord.MessageReference(message_id=message_id, channel_id=chat.id, guild_id=chat.server_id, fail_if_not_exists=True)
        sent_message = await self.bot.get_channel(chat.id).send(f'{message.author.name}: {message.text}', reference=reference)
        return MessageID(chat, sent_message.id)

    async def edit_message(self, message_id: MessageID, new_message: Message):
        ...

    async def delete_message(self, message_id: MessageID):
        ...
    
    def __hash__(self) -> int:
        return super().__hash__()


async def main():
    coordinator = Coordinator()

    discord_bot = DiscordBot(0, 'Чёрный кот', coordinator)
    discord_bot.listtings = {
        'token': os.environ.get('DISCORD_TOKEN')
    }
    
    bridge = Bridge(0)

    coordinator.add_bridge(bridge)
    chat1 = Chat(Platform.Discord, id=1258178824726642789, server_id=1254431449029935114)
    chat2 = Chat(Platform.Discord, id=1272671241056026747, server_id=1254431449029935114)
    # chat3 = Chat()
    coordinator.add_chat_to_bridge(bridge, chat1)
    coordinator.add_chat_to_bridge(bridge, chat2)
    # coordinator.add_chat_to_bridge(bridge, chat3)

    coordinator.link_bot_chat(discord_bot, chat1)
    coordinator.link_bot_chat(discord_bot, chat2)

    coordinator.start_all_bots()

loop = asyncio.new_event_loop()
try:
    loop.create_task(main())
    loop.run_forever()
except KeyboardInterrupt:
    print('Ctrl+C нажата. Останавливаю...')
finally:
    loop.stop()
    loop.close()