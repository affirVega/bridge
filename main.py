import asyncio
from dataclasses import dataclass, field
import enum
import io
import os
import random
import sys
from typing import Optional
from PIL import Image
import dotenv
import requests
import logging

import nextcord
from aiogram.methods import GetUserProfilePhotos
from nextcord.ext import commands

import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType, VkBotMessageEvent, DotDict as VkDotDict


import aiogram
import vk_api.bot_longpoll

VK_CONVERSATION_ID = 2000000000

log = logging.getLogger('main')
log.setLevel(logging.DEBUG)
stderrhandler = logging.StreamHandler(sys.stderr)
stderrhandler.setFormatter(logging.Formatter('%(levelname)s: %(name)s at %(asctime)s on line %(lineno)d: %(message)s'))
log.addHandler(stderrhandler)

logging.getLogger('nextcord').setLevel(logging.DEBUG)
logging.getLogger('aiogram').setLevel(logging.DEBUG)

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
    _cached_image: Optional[Image.Image] = field(default=None, init=False, repr=False)

    def get_image(self) -> Optional[Image.Image]:
        if self._cached_image:
            return self._cached_image
        try:
            return self._download_image()
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
class Sticker:
    picture: IPicture


@dataclass
class IFile(IAttachment):

    def get_file(self) -> Optional[bytes]:
        ...


@dataclass
class UrlFile(IFile):
    url: str = None
    _cached_data: Optional[bytes] = field(default=None, init=False, repr=False)

    def get_file(self) -> Optional[bytes]:
        if self._cached_data:
            return self._cached_data
        try:
            return self._download_file()
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
    pfp: Optional[IPicture]


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
    
    def stop_all_bots(self):
        log.info('Останавливаем всех ботов')
        for bot in self.bots:
            if bot.is_running():
                bot.stop()
            else:
                log.info(f'Бот {bot.display_name()} уже остановлен')

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
        message.relay_ids.append(message_id)
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
                log.warning(f'Не могу найти бота по чату {relay_chat}')
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
                if m_id is None:
                    log.error(f'send_message от бота {bot.display_name()} вернул None вместо messageid')
                else:
                    self.db_add_message_relay_id(m_id, message)
    
    async def edit_all(self, new_message: Message):
        if new_message is None:
            log.error('Кто-то отправил None message')
            return
        log.debug(f'Редактируем сообщение [{new_message.original_id}] {new_message.author.name}: {new_message.text[:20]}...')
        # relay сохранились в старом сообщении
        old_message = self.db_get_message(new_message.original_id)
        if old_message is None:
            log.warning('Редактирование сообщения, которого нет в базе .-. чё делать')
            return
        for relay_m_id in old_message.relay_ids:
            bot = self.get_bot_by_chat(relay_m_id.chat)
            if not bot:
                log.warning(f'Не могу найти бота по чату {new_message.original_id.chat}')
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
                log.warning(f'Не могу найти бота по чату {relay_m_id.chat}')
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

    def _is_message_from_this_bot(self, native_message: ...) -> bool:
        """
        Возвращает True если сообщение было отправленно этим ботом для защиты от бесконечных циклов пересылок
        """
        ...

    def _message_preview_for_log(self, native_message: ...) -> str:
        """
        Возвращает превью нативного сообщения для логов
        """
        ...
        
    def _message_id_from_native(self, chat: Chat, native_message: ...):
        ...
    
    def get_current_chat_from_native_message(self, native_message: ...) -> Optional[Chat]:
        """
        Возвращает чат из интересующих по нативному сообщению
        """
        ...
    
    async def create_message_from_native(self, native_message: ..., chat: Chat, retrieve_from_db: bool) -> Message:
        """
        Создаёт обобщённое сообщение Message для пересылки из нативного для бота сообщения
        """
        ...
    
    def is_running(self) -> bool:
        """
        Возвращает true если бот запущен
        """
        ...
    
    def start(self):
        """
        Запускает работу бота
        """
        ...

    def stop(self):
        """
        Останавливает работу бота
        """
        ...
    
    async def send_message(self, chat: Chat, message: Message) -> MessageID:
        """
        Отправляет сообщение Message в указанный чат
        """
        ...

    async def edit_message(self, message_id: MessageID, new_message: Message):
        """
        Редактирует сообщение по MessageID и новым сообщением
        """
        ...

    async def delete_message(self, message_id: MessageID):
        """
        Удаляет сообщение по MessageID
        """
        ...
    
    def get_current_chat(self, platform: Platform, server_id: Optional[int], chat_id: int) -> Optional[Chat]:
        """
        Возвращает чат из списка своих чатов, или None если сообщение не из интересующих чатов.
        """
        for chat in self.chats:
            if chat.platform == platform and chat.server_id == server_id and chat.id == chat_id:
                return chat
        return None

    async def _handle_new_message(self, native_message: ...):
        if self._is_message_from_this_bot(native_message):
            return
        log.info('_handle_new_message')
        chat = self.get_current_chat_from_native_message(native_message)
        if not chat:
            log.debug(f'Сообщение не из моего чата: {self._message_preview_for_log(native_message)}')
            return

        message = await self.create_message_from_native(native_message, chat, True)
        self.coordinator.db_add_message(message)
        await self.coordinator.send_all(message)

    async def _handle_edit_message(self, native_message: nextcord.Message):
        if self._is_message_from_this_bot(native_message):
            return
        log.info('_handle_edit_message')
        chat = self.get_current_chat_from_native_message(native_message)
        if not chat:
            log.debug(f'Сообщение не из моего чата: {self._message_preview_for_log(native_message)}')
            return

        message = await self.create_message_from_native(native_message, chat, False)
        # self.coordinator.db_add_message(message)
        await self.coordinator.edit_all(message)

    async def _handle_delete_message(self, native_message: nextcord.Message):
        if self._is_message_from_this_bot(native_message):
            return
        log.info('_handle_delete_message')
        chat = self.get_current_chat_from_native_message(native_message)
        if not chat:
            log.debug(f'Сообщение не из моего чата: {self._message_preview_for_log(native_message)}')
            return
        
        message = self.coordinator.db_get_message(self._message_id_from_native(chat, native_message))
        await self.coordinator.delete_all(message)

    def add_chat(self, chat: Chat):
        if chat not in self.chats:
            self.chats.append(chat)
    
    def remove_chat(self, chat: Chat):
        if chat in self.chats:
            self.chats.remove(chat)
    
    def display_name(self) -> str:
        """
        Имя текущего бота для логов
        """
        return f'{Platform(self.platform).name} {self.id} {self.name}'
    
    def __hash__(self) -> int:
        return super().__hash__()


@dataclass
class DiscordBot(IBot):
    platform: Platform = field(default=Platform.Discord, init=False)
    settings: dict[str, object] = field(default_factory=dict)
    bot: commands.Bot = field(default=None, init=False)
    task: asyncio.Task = field(default=None, init=False)

    def _is_message_from_this_bot(self, native_message: nextcord.Message):
        return native_message.author == self.bot.user

    def _message_preview_for_log(self, native_message: nextcord.Message):
        return f'{native_message.author.name}: {native_message.content[:20]}'

    def _message_id_from_native(self, chat: Chat, native_message: nextcord.Message):
        return MessageID(chat, native_message.id)

    def __post_init__(self):
        intents = nextcord.Intents.all()
        self.bot = commands.Bot(intents=intents)

        @self.bot.event
        async def on_ready():
            log.info('on_ready')

        @self.bot.event
        async def on_close():
            log.info('on_clise')

        @self.bot.event
        async def on_message(native_message: nextcord.Message):
            await self._handle_new_message(native_message)
        
        @self.bot.event
        async def on_message_edit(_before: nextcord.Message, after: nextcord.Message):
            await self._handle_edit_message(after)
        
        @self.bot.event
        async def on_message_delete(native_message: nextcord.Message):
            await self._handle_delete_message(native_message)

    def get_current_chat_from_native_message(self, message: nextcord.Message):
        return self.get_current_chat(Platform.Discord, message.guild.id, message.channel.id)
    
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

    async def create_message_from_native(self, native_message: nextcord.Message, chat: Chat, retrieve_from_db=True) -> Optional[Message]:
        if native_message is None:
            return None
        if retrieve_from_db:
            message = self.coordinator.db_get_message(MessageID(chat, native_message.id))
            if message:
                return message
        reply_to = None
        if native_message.reference:
            try:
                reference_message = await native_message.channel.fetch_message(native_message.reference.message_id)
                reply_to = await self.create_message_from_native(reference_message, chat)
            except Exception:
                log.warning('Не получилось получить reference сообщение')
        attachments = [] # TODO
        message = Message(MessageID(chat, native_message.id),
                            author=self.get_author(native_message.author),
                            text=native_message.content, reply_to=reply_to,
                            attachments=attachments)
        return message
    
    def is_running(self) -> bool:
        return self.task and self.task.done()
    
    def start(self):
        self.task = asyncio.create_task(self.bot.start(self.settings['token']))
        log.info(f"Бот discord {self.display_name()} запущен")

    def stop(self):
        self.task.cancel()
    
    def format_message(self, chat: Chat, message: Message) -> str:
        return f'{message.author.name}: {message.text}'

    async def send_message(self, chat: Chat, message: Message) -> MessageID:
        reference = None
        if message.reply_to:
            if message.reply_to.original_id.chat == chat:
                log.debug(f"reply original id chat is current chat")
            
            message_id = message.reply_to.get_message_id(chat)
            if message_id:
                reference = nextcord.MessageReference(message_id=message_id, channel_id=chat.id, guild_id=chat.server_id, fail_if_not_exists=True)
        channel = self.bot.get_channel(chat.id)
        content = self.format_message(chat, message)
        sent_message = await channel.send(content, reference=reference)
        return MessageID(chat, sent_message.id)

    async def edit_message(self, message_id: MessageID, new_message: Message):
        channel = self.bot.get_channel(message_id.chat.id)
        content = self.format_message(message_id.chat, new_message)
        await channel.get_partial_message(message_id.id).edit(
            content=content
        )

    async def delete_message(self, message_id: MessageID):
        channel = self.bot.get_channel(message_id.chat.id)
        await channel.get_partial_message(message_id.id).delete()
    
    def __hash__(self) -> int:
        return super().__hash__()




@dataclass
class VkBot(IBot):
    platform: Platform = field(default=Platform.Vk, init=False)
    settings: dict[str, object] = field(default_factory=dict)
    longpoll: VkBotLongPoll = field(default=None, init=False)
    task: asyncio.Task = field(default=None, init=False)

    def __post_init__(self):
        self.vk_api = vk_api.VkApi(token=self.settings['token'])
        self.api = self.vk_api.get_api()
        data = self.api.groups.get_by_id()
        group_id = data[0]['id']
        self.longpoll = VkBotLongPoll(self.vk_api, group_id=group_id, wait=-5) # -5 потому что longpoll.check добавляет 10 к запросу

    def _is_message_from_this_bot(self, native_message: dict) -> bool:
        return False

    def _message_preview_for_log(self, native_message: dict) -> str:
        return native_message['text'][:20]

    def _message_id_from_native(self, chat: Chat, native_message: dict):
        conversation_message_id = native_message['conversation_message_id']
        get_by_id_response = self.api.messages.get_by_conversation_message_id(peer_id=VK_CONVERSATION_ID+chat.id, 
            conversation_message_ids=str(conversation_message_id), 
            extended=False)
        message_data = get_by_id_response['items'][0]
        message_id = message_data['id']
        return MessageID(chat, message_id)

    def get_current_chat_from_native_message(self, message: VkDotDict):
        return Chat(Platform.Vk, message.peer_id - VK_CONVERSATION_ID, None)
    
    async def get_author(self, user_id: int):
        author = self.coordinator.get_author(Platform.Vk, user_id)
        if author:
            return author
        pfp = None
        response_data = self.api.users.get(user_ids=[user_id], fields=['photo_max_orig', 'screen_name'])
        user_data = (response_data)[0]
        name = f'{user_data['first_name']} {user_data['last_name']}'
        if user_data['photo_max_orig']:
            pfp = UrlPicture(f'pfp of {name}', user_data['photo_max_orig'])
        author = Author(Platform.Vk, id=user_id, 
                        name=name, username=user_data['screen_name'], pfp=pfp)
        return author

    async def create_message_from_native(self, native_message: VkDotDict, chat: Chat, retrieve_from_db=True) -> Optional[Message]:
        if native_message is None:
            return None
        
        message_id = self._message_id_from_native(chat, native_message)
        if retrieve_from_db:
            message = self.coordinator.db_get_message(message_id)
            if message:
                return message
        reply_to = None
        if 'reply_message' in native_message:
            try:
                reply_to = await self.create_message_from_native(native_message.get('reply_message'), chat)
            except Exception:
                log.warning('Не получилось получить reference сообщение')
        attachments = [] # TODO
        message = Message(message_id,
                            author=await self.get_author(native_message['from_id']),
                            text=native_message['text'], reply_to=reply_to,
                            attachments=attachments)
        return message
    
    def is_running(self) -> bool:
        return self.task and self.task.done()
    
    async def _run_polling(self):
        while not asyncio.current_task().cancelled():
            await asyncio.sleep(0)
            try:
                for event in self.longpoll.check():
                    await asyncio.sleep(0)
                    log.debug(event)
                    if isinstance(event, VkBotMessageEvent):
                        if event.type == VkBotEventType.MESSAGE_NEW:
                            await self._handle_new_message(event.message)
                        elif event.type == VkBotEventType.MESSAGE_REPLY:
                            await self._handle_new_message(event.message)
                    if asyncio.current_task().cancelled():
                        return
            except Exception as e:
                log.error(e)
    
    def start(self):
        self.task = asyncio.create_task(self._run_polling())
        log.info(f"Бот vk {self.display_name()} запущен")

    def stop(self):
        self.task.cancel()
    
    def format_message(self, chat: Chat, message: Message) -> str:
        return f'{message.author.name}: {message.text}'

    async def send_message(self, chat: Chat, message: Message) -> MessageID:
        reply_to = None
        if message.reply_to:
            if message.reply_to.original_id.chat == chat:
                log.debug(f"reply original id chat is current chat")
            reply_to = message.reply_to.get_message_id(chat)
            
        attachment_str = '' # TODO
        text = self.format_message(chat, message)

        conversation_message_id = self.api.messages.send(
            chat_id=chat.id,
            message=text,
            attachment=attachment_str,
            reply_to=reply_to,
            random_id=random.randint(0, 1<<31)) 

        return MessageID(chat, conversation_message_id)

    async def edit_message(self, message_id: MessageID, new_message: Message):
        attachment_str = '' # TODO
        text = self.format_message(message_id.chat, new_message)
        self.api.messages.edit(
            peer_id=message_id.chat.id + VK_CONVERSATION_ID,
            message=text,
            attachment=attachment_str,
            keep_forward_messages=1,
            message_id=message_id.id
        )

    async def delete_message(self, message_id: MessageID):
        self.api.messages.delete(
            peer_id=message_id.chat.id + VK_CONVERSATION_ID,
            message_ids=str(message_id.id),
            delete_for_all=1
        )
    
    def __hash__(self) -> int:
        return super().__hash__()
    

@dataclass
class TelegramBot(IBot):
    platform: Platform = field(default=Platform.Telegram, init=False)
    settings: dict[str, object] = field(default_factory=dict)
    bot: aiogram.Bot = field(default=None, init=False)
    task: asyncio.Task = field(default=None, init=False)

    def _is_message_from_this_bot(self, native_message: aiogram.types.Message) -> bool:
        return native_message.from_user.id == self.bot.id

    def _message_preview_for_log(self, native_message: aiogram.types.Message) -> str:
        return f'{native_message.from_user.full_name}: {native_message.text[:20]}'

    def _message_id_from_native(self, chat: Chat, native_message: aiogram.types.Message):
        return MessageID(chat, native_message.message_id)

    def __post_init__(self):
        self.bot = aiogram.Bot(token=self.settings['token'])

        self.dp = aiogram.Dispatcher()

        @self.dp.message()
        async def on_message(native_message: aiogram.types.Message):
            await self._handle_new_message(native_message)
        
        @self.dp.edited_message()
        async def on_message_edit(edited_message: aiogram.types.Message):
            await self._handle_edit_message(edited_message)

    def get_current_chat_from_native_message(self, message: aiogram.types.Message):
        return self.get_current_chat(Platform.Telegram, None, message.chat.id)
    
    def get_author(self, user: aiogram.types.User):
        author = self.coordinator.get_author(Platform.Telegram, user.id)
        if author: 
            return author
        pfp = None
        profile_photos: GetUserProfilePhotos = user.get_profile_photos(limit=1)
        print(profile_photos)
        # if len(profile_photos.photos) >= 1:
        #     pfp = UrlPicture(f'pfp of {user.full_name}', profile_photos.photos[0])
        author = Author(Platform.Telegram, id=user.id, 
                        name=user.full_name, 
                        username=user.username, pfp=pfp)
        return author

    async def create_message_from_native(self, native_message: aiogram.types.Message, chat: Chat, retrieve_from_db=True) -> Optional[Message]:
        if native_message is None:
            return None
        message_id = self._message_id_from_native(chat, native_message)
        if retrieve_from_db:
            message = self.coordinator.db_get_message(message_id)
            if message:
                return message
        reply_to = None
        if native_message.reply_to_message:
            try:
                reply_to = await self.create_message_from_native(native_message.reply_to_message, chat)
            except Exception:
                log.warning('Не получилось получить reference сообщение')
        attachments = [] # TODO
        message = Message(message_id,
                            author=self.get_author(native_message.from_user),
                            text=native_message.text, reply_to=reply_to,
                            attachments=attachments)
        return message
    
    def is_running(self) -> bool:
        return self.task and self.task.done()
    
    def start(self):
        self.task = asyncio.create_task(self.dp.start_polling(self.bot))
        log.info(f"Бот telegram {self.display_name()} запущен")

    def stop(self):
        asyncio.create_task(self.dp.stop_polling())
        # self.task.cancel()

    def format_message(self, chat: Chat, message: Message) -> str:
        return f'{message.author.name}: {message.text}'
    
    async def send_message(self, chat: Chat, message: Message) -> MessageID:
        message_id = None
        if message.reply_to:
            if message.reply_to.original_id.chat == chat:
                log.debug(f"reply original id chat is current chat")
            
            message_id = message.reply_to.get_message_id(chat)
        content=self.format_message(chat, message)
        sent_message = await self.bot.send_message(chat_id=chat.id, text=content, reply_to_message_id=message_id)
        return MessageID(chat, sent_message.message_id)

    async def edit_message(self, message_id: MessageID, new_message: Message):
        content = self.format_message(message_id.chat, new_message)
        await self.bot.edit_message_text(text=content, chat_id=message_id.chat.id, message_id=message_id.id)

    async def delete_message(self, message_id: MessageID):
        await self.bot.delete_message(message_id.chat.id, message_id.id)
    
    def __hash__(self) -> int:
        return super().__hash__()


coordinator: Optional[Coordinator] = None
async def main():
    global coordinator
    coordinator = Coordinator()

    discord_bot = DiscordBot(0, 'Чёрный кот', coordinator, settings = {
        'token': os.environ.get('DISCORD_TOKEN')
    })

    vk_bot = VkBot(1, 'Феся бот', coordinator, settings={
        'token': os.environ.get('VK_TOKEN')
    })

    telegram_bot = TelegramBot(2, 'Тг бот', coordinator, settings={
        'token': os.environ.get('TG_TOKEN')
    })
    
    bridge = Bridge(0)

    coordinator.add_bridge(bridge)
    
    chat1 = Chat(Platform.Discord, id=1258178824726642789, server_id=1254431449029935114)
    coordinator.add_chat_to_bridge(bridge, chat1)
    coordinator.link_bot_chat(discord_bot, chat1)
    
    chat2 = Chat(Platform.Discord, id=1272671241056026747, server_id=1254431449029935114)
    coordinator.add_chat_to_bridge(bridge, chat2)
    coordinator.link_bot_chat(discord_bot, chat2)
    
    chat3 = Chat(Platform.Vk, id=4)
    coordinator.add_chat_to_bridge(bridge, chat3)
    coordinator.link_bot_chat(vk_bot, chat3)

    chat4 = Chat(Platform.Telegram, id=-4502798177)
    coordinator.add_chat_to_bridge(bridge, chat4)
    coordinator.link_bot_chat(telegram_bot, chat4)

    coordinator.start_all_bots()


if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    try:
        loop.create_task(main())
        loop.run_forever()
    except KeyboardInterrupt:
        print('Ctrl+C нажата. Останавливаю...')
    finally:
        print('finally начало...')
        if coordinator is not None:
            coordinator.stop_all_bots()
        loop.stop()
        loop.close()