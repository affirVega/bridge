from worker_types import *

import asyncio
import aiogram
from aiogram.methods import GetUserProfilePhotos

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


