from dataclasses import dataclass, field
from typing import Optional
import logging
import typing

from message_types import *

log = logging.getLogger('main')

MAX_FILE_SIZE=1024*1024*5

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
                m_id = None
                try:
                    m_id = await bot.send_message(chat, message)
                except Exception as e:
                    log.error(f'Отправка сообщения от бота {bot.display_name()} выкинула исключение {e}')
                    continue
                if m_id is None:
                    log.error(f'send_message от бота {bot.display_name()} вернул None вместо messageid')
                elif isinstance(m_id, list):
                    for i in m_id:
                        self.db_add_message_relay_id(i, message)
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
            
            try:
                await bot.edit_message(relay_m_id, new_message)
            except Exception as e:
                log.error(f'Редактирование сообщения от бота {bot.display_name()} выкинуло исключение {e}')
                continue
            
    
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
            try:
                await bot.delete_message(relay_m_id)
            except Exception as e:
                log.error(f'Удаление сообщения от бота {bot.display_name()} выкинуло исключение {e}')
                continue


@dataclass
class Bridge:
    id: str
    chats: list[Chat] = field(default_factory=list)

    def add_chat(self, chat: Chat):
        if chat not in self.chats:
            self.chats.append(chat)
    
    def remove_chat(self, chat: Chat):
        if chat in self.chats:
            self.chats.remove(chat)


@dataclass
class IBot:
    id: str
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

    async def _handle_edit_message(self, native_message: ...):
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

    async def _handle_delete_message(self, native_message: ...):
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
class IUploader:
    
    def upload(self, data: bytes) -> str:
        '''
        Можно выложить файл и получить строку
        '''
        ...
    

@dataclass
class ImgPushUploader(IUploader):
    upload_url: str

    def upload(self, data: bytes | typing.BinaryIO) -> Optional[str]:
        buf = None
        if hasattr(data, 'read'):
            buf = data
        else:
            buf = io.BytesIO(data)
        answer = requests.post(self.upload_url, files={'file': ('pfp.png', buf)})
        log.info(answer.text)
        if answer.ok:
            return self.upload_url + '/' + answer.json()['filename']
        return None