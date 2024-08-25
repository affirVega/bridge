from worker_types import *

import asyncio
import nextcord
from nextcord.ext import commands

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