from worker_types import *

import asyncio
import vk_api
import vk_api.bot_longpoll
from vk_api import VkUpload
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType, VkBotMessageEvent, DotDict as VkDotDict
import random

VK_CONVERSATION_ID = 2000000000

@dataclass
class VkBot(IBot):
    platform: Platform = field(default=Platform.Vk, init=False)
    settings: dict[str, object] = field(default_factory=dict)
    longpoll: VkBotLongPoll = field(default=None, init=False)
    task: asyncio.Task = field(default=None, init=False)
    upload: VkUpload = field(default=None, init=False)

    def __post_init__(self):
        self.vk_api = vk_api.VkApi(token=self.settings['token'])
        self.api = self.vk_api.get_api()
        data = self.api.groups.get_by_id()
        group_id = data[0]['id']
        self.upload = VkUpload(self.api)
        self.longpoll = VkBotLongPoll(self.vk_api, group_id=group_id, wait=0) # потому что longpoll.check добавляет 10 к запросу

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
        self.coordinator.add_author(author)
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
                reply_data = self.api.messages.get_by_conversation_message_id(peer_id=VK_CONVERSATION_ID+chat.id, 
                    conversation_message_ids=str(native_message['reply_message']['conversation_message_id']), extended=False)
                reply_to = await self.create_message_from_native(reply_data['items'][0], chat)
            except Exception:
                log.warning('Не получилось получить reference сообщение')
        attachments = []

        for attachment in native_message.get('attachments', []):
            type = attachment['type']
            if type == 'photo':
                photo = attachment['photo']
                sizes = photo['sizes']
                url = sizes[-1]['url']
                attachments.append(UrlPicture('img.jpg', url))
            elif type == 'doc':
                doc = attachment['doc']
                title = doc['title']
                size = doc['size']
                url = doc['url']
                if size > MAX_FILE_SIZE:
                    attachments.append(UrlLink(title, url))
                else:
                    attachments.append(UrlFile(title, url))
            elif type == 'sticker':
                sticker = attachment['sticker']
                images = sticker['images']
                images_with_background = sticker['images_with_background']
                url = images[-1]['url']
                attachments.append(Sticker('sticker.png', UrlPicture('sticker.png', url)))

        message = Message(message_id,
                            author=await self.get_author(native_message['from_id']),
                            text=native_message['text'], reply_to=reply_to,
                            attachments=attachments)
        return message
    
    def is_running(self) -> bool:
        return self.task and self.task.done()
    
    async def _run_polling(self):
        while not asyncio.current_task().cancelled():
            await asyncio.sleep(1)
            try:
                for event in self.longpoll.check():
                    await asyncio.sleep(1)
                    log.debug(event)
                    if isinstance(event, VkBotMessageEvent):
                        if event.type == VkBotEventType.MESSAGE_NEW:
                            await self._handle_new_message(event.message)
                        elif event.type == VkBotEventType.MESSAGE_REPLY:
                            await self._handle_new_message(event.message)
                        elif event.type == VkBotEventType.MESSAGE_EDIT:
                            pass # TODO не поддерживается??
                    if asyncio.current_task().cancelled():
                        return
            except Exception as e:
                log.error(e)
    
    def start(self):
        self.task = asyncio.create_task(self._run_polling())
        log.info(f"Бот vk {self.display_name()} запущен")

    def stop(self):
        self.task.cancel()
    
    def format_message(self, message: Message, include_reply = False) -> str:
        prefix = message.original_id.chat.prefix or Platform(message.original_id.chat.platform).name
        name = message.author.name or message.author.username
        content = f'[{prefix}] {name}: {message.text}'
        if include_reply and message.reply_to:
            reply_prefix = message.reply_to.original_id.chat.prefix or Platform(message.reply_to.original_id.chat.platform)
            reply_name = message.reply_to.author.name or message.reply_to.author.username
            reply_content = message.reply_to.text.replace('\n', '\n> ')
            content = f'{content}\n\n> В ответ на [{reply_prefix}] {reply_name}: {reply_content}'

        return content

    async def send_message(self, chat: Chat, message: Message) -> MessageID:
        reply_to = None
        if message.reply_to:
            if message.reply_to.original_id.chat == chat:
                log.debug(f"reply original id chat is current chat")
            reply_to = message.reply_to.get_message_id(chat)
        message.set_data(chat, 'reply', reply_to)
            
        attachment_str = ''
        links = ''
        text = self.format_message(message, reply_to==None)

        photos: list[io.BytesIO] = []
        files: list[io.BytesIO] = []
        sticker: Optional[io.BytesIO] = None
        for attachment in message.attachments:
            if isinstance(attachment, IPicture):
                image = attachment.get_image()
                buffer = io.BytesIO()
                image.save(buffer, format='webp')
                buffer.seek(0)
                photos.append(buffer)
            elif isinstance(attachment, Sticker):
                image = attachment.picture.get_image()
                buffer = io.BytesIO()
                image.resize((160, 160)).save(buffer, format='webp')
                buffer.seek(0)
                # TODO сделать обход невозможности отправить граффити
                photos.append(buffer)
            elif isinstance(attachment, IFile):
                file_data = attachment.get_file()
                buffer = io.BytesIO(file_data)
                buffer.seek(0)
                buffer.name = attachment.name or 'file.dat'
                files.append(buffer)
            elif isinstance(attachment, UrlLink):
                links += f'{attachment.name}: {attachment.url} '
        
        if len(photos) >= 1:
            uploaded = self.upload_message_pictures(photos)
            log.info(f'picture: {uploaded}')
            for photo in uploaded:
                photo_key = f'photo{photo["owner_id"]}_{photo["id"]}_{photo["access_key"]},'
                attachment_str += photo_key
        
        if len(files) >= 1:
            uploaded = self.upload_message_document(documents=files, peer_id=chat.id + VK_CONVERSATION_ID)
            log.info(f'file: {uploaded}')
            for doc_data in uploaded:
                doc = doc_data['doc']
                doc_key = f'doc{doc["owner_id"]}_{doc["id"]},'
                attachment_str += doc_key
            # for title, file in files:
            #     uploaded = self.upload.document(doc=file, title=title, group_id=self.longpoll.group_id, message_peer_id=chat.id + VK_CONVERSATION_ID, doc_type='doc')
            #     log.info(f'file: {uploaded}')
            #     doc_key = f'doc{uploaded["owner_id"]}_{uploaded["id"]}_{uploaded["access_key"]},'
            #     attachment_str += doc_key
        
        attachment_str = attachment_str.removeprefix(',')
        
        # if sticker:
        #     uploaded = self.upload.graffiti(sticker, chat.id + VK_CONVERSATION_ID, self.longpoll.group_id)
        #     log.info('file: ' + uploaded)

        conversation_message_id = self.api.messages.send(
            chat_id=chat.id,
            message=text,
            attachment=attachment_str,
            reply_to=reply_to,
            random_id=random.randint(0, 1<<31)) 

        return MessageID(chat, conversation_message_id)

    async def edit_message(self, message_id: MessageID, new_message: Message):
        attachment_str = '' # TODO
        old_message = self.coordinator.db_get_message(message_id)
        reply = old_message.get_data(message_id.chat, 'reply')
        new_message.reply_to = old_message.reply_to

        text = self.format_message(new_message, reply==None)
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
    
    def upload_message_pictures(self, pictures: list[io.BytesIO]):
        url = self.api.photos.getMessagesUploadServer(group_id=self.longpoll.group_id)['upload_url']

        with vk_api.upload.FilesOpener(pictures) as photo_files:
            response = self.upload.http.post(url, files=photo_files)

        return self.api.photos.saveMessagesPhoto(**response.json())
    
    def upload_message_document(self, peer_id: int, documents: list[io.BytesIO], type: str = 'doc'):
        values = {
            'group_id': self.longpoll.group_id,
            'peer_id': peer_id,
            'type': type
        }

        method = self.api.docs.getMessagesUploadServer

        url = method(**values)['upload_url']

        foobar = []
        for doc in documents:
            with vk_api.upload.FilesOpener(doc, 'file') as files:
                response = self.vk_api.http.post(url, files=files).json()

            response.update({
                'title': doc.name,
                'tags': ''
            })

            foobar.append(self.api.docs.save(**response))
        
        return foobar
    
    def __hash__(self) -> int:
        return super().__hash__()