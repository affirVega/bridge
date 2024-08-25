from worker_types import *

import asyncio
import vk_api
import vk_api.bot_longpoll
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType, VkBotMessageEvent, DotDict as VkDotDict
import random

VK_CONVERSATION_ID = 2000000000

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