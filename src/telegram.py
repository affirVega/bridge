from datetime import datetime
import os
import uuid

import aiogram.filters
import aiogram.utils.markdown as mdutils
from aiogram.utils.text_decorations import markdown_decoration as md
from aiogram.enums.parse_mode import ParseMode
from worker_types import *

import asyncio
import aiogram
from aiogram.methods import GetUserProfilePhotos
from aiogram_media_group import media_group_handler

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
    
    async def _handle_new_media_group_message(self, native_messages: list[aiogram.types.Message]):
        if self._is_message_from_this_bot(native_messages[0]):
            return
        log.info('_handle_new_message')
        chat = self.get_current_chat_from_native_message(native_messages[0])
        if not chat:
            log.debug(f'Сообщение не из моего чата: {self._message_preview_for_log(native_messages[0])}')
            return

        message = await self.create_message_from_native_media_group(native_messages, chat, True)
        self.coordinator.db_add_message(message)
        await self.coordinator.send_all(message)

    def __post_init__(self):
        self.bot = aiogram.Bot(token=self.settings['token'])

        self.dp = aiogram.Dispatcher()

        @self.dp.message(aiogram.F.media_group_id == None)
        async def on_message(native_message: aiogram.types.Message):
            await self._handle_new_message(native_message)

        @self.dp.message(aiogram.F.media_group_id)
        @media_group_handler
        async def on_message(native_messages: list[aiogram.types.Message]):
            await self._handle_new_media_group_message(native_messages)
        
        @self.dp.edited_message()
        async def on_message_edit(edited_message: aiogram.types.Message):
            await self._handle_edit_message(edited_message)

    def get_current_chat_from_native_message(self, message: aiogram.types.Message):
        return self.get_current_chat(Platform.Telegram, None, message.chat.id)
    
    async def get_author(self, user: aiogram.types.User):
        author = self.coordinator.get_author(Platform.Telegram, user.id)
        if author: 
            return author
        pfp = None
        user_profile_photo: aiogram.types.UserProfilePhotos = await self.bot.get_user_profile_photos(user.id, limit=1)
        if len(user_profile_photo.photos) > 0 and len(user_profile_photo.photos[0]) > 0:
            file = await self.bot.get_file(user_profile_photo.photos[0][-1].file_id)
            buf = io.BytesIO()
            await self.bot.download_file(file.file_path, buf)
            pfp = TempImage('pfp.png', Image.open(buf))
        else:
            log.debug('У пользователя нет фото в профиле.')
        # if len(profile_photos.photos) >= 1:
        #     pfp = UrlPicture(f'pfp of {user.full_name}', profile_photos.photos[0])
        author = Author(Platform.Telegram, id=user.id, 
                        name=user.full_name, 
                        username=user.username, pfp=pfp)
        self.coordinator.add_author(author)
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
        
        attachments = await self.get_attachments_from_natives([native_message])

        message = Message(message_id,
                            author=await self.get_author(native_message.from_user),
                            text=native_message.text or '', reply_to=reply_to,
                            attachments=attachments)
        return message

    async def get_attachments_from_natives(self, native_messages: list[aiogram.types.Message]):
        attachments = []
        for native in native_messages:
            if native.document:
                if native.document.file_size <= MAX_FILE_SIZE:
                    buf = io.BytesIO()
                    await self.bot.download(file=native.document.file_id, destination=buf)
                    buf.seek(0)
                    file = TempFile(native.document.file_name, cached_data=buf.read())
                    attachments.append(file)
                else:
                    # TODO как-то оповестить что файл не отправлен
                    log.warning("Файл слишком большой")
                    attachments.append(UrlLink('Файл слишком большой и не был загружен', ''))
            
            if native.photo:
                buf = io.BytesIO()
                await self.bot.download(native.photo[-1].file_id, buf)
                buf.seek(0)
                img = TempImage(cached_image=Image.open(buf))
                attachments.append(img)
            
            if native.sticker:
                if native.sticker.is_animated:
                    attachments.append(UrlLink('Ошибка: анимированные стикеры не поддерживаются', ''))
                elif native.sticker.is_video:
                    attachments.append(UrlLink('Ошибка: видео стикеры не поддерживаются', ''))
                else:
                    buf = io.BytesIO()
                    await self.bot.download(native.sticker.file_id, buf)
                    buf.seek(0)
                    img = TempImage(cached_image=Image.open(buf))
                    attachments.append(Sticker(native.sticker.emoji, img))
        return attachments
    
    async def create_message_from_native_media_group(self, native_messages: list[aiogram.types.Message], chat: Chat, retrieve_from_db=True) -> Optional[Message]:
        message = await self.create_message_from_native(native_messages[0], chat, retrieve_from_db)
        if not isinstance(message, Message):
            return
        
        attachments = await self.get_attachments_from_natives(native_messages[1:])

        message.attachments += attachments
        return message
    
    def is_running(self) -> bool:
        return self.task and self.task.done()
    
    def start(self):
        self.task = asyncio.create_task(self.dp.start_polling(self.bot))
        log.info(f"Бот telegram {self.display_name()} запущен")

    def stop(self):
        asyncio.create_task(self.dp.stop_polling())
        # self.task.cancel()

    def format_message(self, message: Message, links: str = None, include_reply: bool = False) -> str:
        prefix = message.original_id.chat.prefix or Platform(message.original_id.chat.platform).name
        author = message.author.name or message.author.username
        text = message.text
        result = md.quote(f'[{prefix}] {author}: {text}')
        if include_reply and message.reply_to:
            reply_chat = message.reply_to.original_id.chat
            prefix = reply_chat.prefix or Platform(reply_chat.platform).name
            author = message.reply_to.author.name or message.reply_to.author.username
            text = message.reply_to.text
            reply_result =  md.expandable_blockquote(f'В ответ на [{prefix}] {author}:\n{text}')
            result = f'{reply_result}\n{result}'
        if links:
            result = f'{result}\nПрикреплённые ссылки: {links}'
        return result
        
    
    async def send_message(self, chat: Chat, message: Message) -> MessageID:
        reply_message_id = None
        if message.reply_to:
            if message.reply_to.original_id.chat == chat:
                log.debug(f"reply original id chat is current chat")
            
            reply_message_id = message.reply_to.get_message_id(chat)
        
        links = ''
        pictures: list[aiogram.types.InputMediaPhoto] = []
        documents: list[aiogram.types.InputMediaDocument] = []
        sticker: aiogram.types.InputMediaPhoto = None
        audios = []
        videos = []
        for attachment in message.attachments:
            if isinstance(attachment, IPicture):
                image = attachment.get_image()
                buffer = io.BytesIO()
                image.convert('RGB').save(buffer, format='jpeg')
                buffer.seek(0)
                file_data = aiogram.types.input_file.BufferedInputFile(buffer.read(), attachment.name or 'image.jpeg')
                file = aiogram.types.InputMediaPhoto(media=file_data, caption=(attachment.name + '.jpg' or 'image.jpeg'))
                pictures.append(file)
            elif isinstance(attachment, Sticker):
                image = attachment.picture.get_image()
                buffer = io.BytesIO()
                image.resize((160, 160)).save(buffer, format='webp')
                buffer.seek(0)
                sticker = aiogram.types.input_file.BufferedInputFile(buffer.read(), attachment.name or 'image.webp')
            elif isinstance(attachment, IFile):
                file_data = attachment.get_file()
                buffer = io.BytesIO(file_data)
                buffer.seek(0)
                file_data = aiogram.types.input_file.BufferedInputFile(buffer.read(), attachment.name or 'file.dat')
                file = aiogram.types.InputMediaDocument(media=file_data, filename=(attachment.name or 'file.dat'))
                documents.append(file)
            elif isinstance(attachment, UrlLink):
                links += f'[{attachment.name}]({attachment.url}) '
        
        content = self.format_message(message, links, include_reply=(reply_message_id is None))
        message.data['links'] = links
        message.data['reply_message_id'] = reply_message_id

        first_sent_message = None
        ids = []

        if len(pictures) == 0 and len(documents) == 0:
            if message.text is not None or message.text != '' or sticker:
                first_sent_message = await self.bot.send_message(chat_id=chat.id, text=content or '', reply_to_message_id=reply_message_id,
                                                                 parse_mode=ParseMode.MARKDOWN_V2)
                content = message.author.name + ':'
                ids.append(first_sent_message.message_id)
        
        if sticker:
            sent_message = await self.bot.send_sticker(chat_id=chat.id, sticker=sticker, reply_to_message_id=reply_message_id)
            ids.append(sent_message.message_id)
        
        caption = content or ''

        if len(pictures) >= 2:
            pictures[0].caption = caption
            sent_messages = await self.bot.send_media_group(chat_id=chat.id, media=pictures, reply_to_message_id=reply_message_id, request_timeout=120)
            for sm in sent_messages:
                ids.append(sm.message_id)
            if first_sent_message is None:
                first_sent_message = sent_messages[0]
        elif len(pictures) == 1:
            sent_message = await self.bot.send_photo(chat_id=chat.id, photo=pictures[0].media, caption=caption, reply_to_message_id=reply_message_id, request_timeout=120)
            ids.append(sent_message.message_id)
            if first_sent_message is None:
                first_sent_message = sent_message
        
        if len(documents) >= 2:
            documents[0].caption = caption
            sent_messages = await self.bot.send_media_group(chat_id=chat.id, media=documents, reply_to_message_id=reply_message_id, request_timeout=120)
            for sm in sent_messages:
                ids.append(sm.message_id)
            if first_sent_message is None:
                first_sent_message = sent_messages[0]
        elif len(documents) == 1:
            sent_message = await self.bot.send_document(chat_id=chat.id, document=documents[0].media, caption=caption, reply_to_message_id=reply_message_id, request_timeout=120)
            ids.append(sent_message.message_id)
            if first_sent_message is None:
                first_sent_message = sent_message

        return [MessageID(chat, mid) for mid in ids] 

    async def edit_message(self, message_id: MessageID, new_message: Message):
        old_message = self.coordinator.db_get_message(message_id)

        if old_message and old_message.text == new_message.text:
            log.debug('Телеграм не разрешает редактировать сообщение одинаковым текстом')
            return

        links = old_message.data.get('links', None)
        reply_message_id = old_message.data.get('reply_message_id', None)
        content = self.format_message(new_message, links, include_reply=(reply_message_id is None))
        await self.bot.edit_message_text(text=content, chat_id=message_id.chat.id, message_id=message_id.id, parse_mode=ParseMode.MARKDOWN_V2)

    async def delete_message(self, message_id: MessageID):
        await self.bot.delete_message(message_id.chat.id, message_id.id)

        # old_message = self.coordinator.db_get_message(message_id)
        # if old_message and (ids := old_message.data.get('ids', None)):
        #     for id in ids:
        #         await self.bot.delete_message(message_id.chat.id, id)

    
    def __hash__(self) -> int:
        return super().__hash__()


