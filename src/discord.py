from datetime import datetime
import time
import nextcord.types
import nextcord.types.guild
from worker_types import *
from collections import namedtuple

import asyncio
import nextcord
from nextcord.ext import commands

EMBED_REPLY_MARK = '~'

@dataclass
class DiscordBot(IBot):
    platform: Platform = field(default=Platform.Discord, init=False)
    settings: dict[str, object] = field(default_factory=dict)
    bot: commands.Bot = field(default=None, init=False)
    task: asyncio.Task = field(default=None, init=False)

    def _is_message_from_this_bot(self, native_message: nextcord.Message):
        if native_message.author.bot and native_message.author.discriminator == '0000':
            return True # TODO is a webhook probably?
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
        self.coordinator.add_author(author)
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
        for att in native_message.attachments:
            log.info(att.content_type)
            log.info(f'{att.filename} - {att.description}. {att.height}:{att.width}')
            if att.content_type is None:
                att.content_type = ''
            if att.content_type.startswith('image'):
                image = UrlPicture(att.filename, att.url)
                attachments.append(image)
            elif att.content_type.startswith('video'):
                link = UrlLink(att.filename, att.url)
                attachments.append(link)
            elif att.size <= MAX_FILE_SIZE:
                file = UrlFile(att.filename, att.url)
                attachments.append(file)
            else:
                file = UrlLink(att.filename, att.url)
                attachments.append(file)
        for native_sticker in native_message.stickers:
            picture = UrlPicture(None, native_sticker.url)
            sticker = Sticker(native_sticker.name, picture)
            attachments.append(sticker)
        
        message = Message(MessageID(chat, native_message.id),
                            author=self.get_author(native_message.author),
                            text=native_message.content, reply_to=reply_to,
                            attachments=attachments)
        return message
    
    def is_running(self) -> bool:
        return self.task and self.task.done()

    def is_webhook_mode(self) -> bool:
        return self.settings.get('webhook', False)
    
    def is_embed_mode(self) -> bool:
        return self.settings.get('embed', False)

    async def get_webhook(self, channel: nextcord.TextChannel, name: str = 'bridge-bot', webhook_avatar: bytes = None) -> nextcord.Webhook:
        if not isinstance(channel, nextcord.TextChannel):
            return None
        
        webhooks = await channel.webhooks()
        webhook = None
        for wh in webhooks:
            if wh.name.startswith(name):
                webhook = wh
                break
        if webhook is None:
            webhook = await channel.create_webhook(name=name + ' ' + str(time.time())[-5:], 
                                   avatar=webhook_avatar, 
                                   reason='Created for bridge bot to send webhooks')
        return webhook
    
    def start(self):
        self.task = asyncio.create_task(self.bot.start(self.settings['token']))
        log.info(f"Бот discord {self.display_name()} запущен")

    def stop(self):
        self.task.cancel()

    @dataclass
    class FormattedMessage:
        nick: str = None
        webhook_nick: str = None
        text: str = None
        default_text: str = None
        footer: str = None
    
    def format_message(self, message: Message, links: str = None) -> FormattedMessage:
        prefix = message.original_id.chat.prefix or Platform(message.original_id.chat.platform).name
        name = message.author.name or message.author.username
        nick = name
        text = message.text
        if links:
            text = f'{text}\nСсылки: {links}'
        footer = f'-# Сообщение из чата: {prefix}'
        webhook_nick = f'[{prefix}] {name}'
        default_text = f'{webhook_nick}: {text}'
        return self.FormattedMessage(nick, webhook_nick, text, default_text, footer)
    
    def get_pfp_url(self, author: Author) -> Optional[str]:
        if author.pfp_url:
            return author.pfp_url
        if author.pfp and isinstance(author.pfp, UrlPicture):
            return author.pfp.url
        if author.pfp:
            if uploader := self.settings.get('uploader', None):
                buffer = io.BytesIO()
                author.pfp.get_image().save(buffer, 'png')
                buffer.seek(0)
                url = uploader.upload(buffer)
                author.pfp_url = url
                return url
            else:
                log.warn('Без uploader в discord иногда могут не показываться аватарки, потому что discord требует их по публичной ссылке')
                return None
        return None

    async def send_message(self, chat: Chat, message: Message) -> MessageID:
        reference = None
        if message.reply_to:
            if message.reply_to.original_id.chat == chat:
                log.debug(f"reply original id chat is current chat")
            
            message_id = message.reply_to.get_message_id(chat)
            if message_id:
                reference = nextcord.MessageReference(message_id=message_id, channel_id=chat.id, guild_id=chat.server_id, fail_if_not_exists=True)
        
        links = ''
        files = []
        for attachment in message.attachments:
            if isinstance(attachment, IPicture):
                image = attachment.get_image()
                buffer = io.BytesIO()
                image.save(buffer, format='webp')
                buffer.seek(0)
                file = nextcord.File(fp=buffer, filename=(attachment.name or 'image') + '.webp')
                files.append(file)
            elif isinstance(attachment, Sticker):
                image = attachment.picture.get_image()
                buffer = io.BytesIO()
                image.resize((160, 160)).save(buffer, format='webp')
                buffer.seek(0)
                file = nextcord.File(fp=buffer, filename=(attachment.name or 'image') + '.webp')
                files.append(file)
            elif isinstance(attachment, IFile):
                file_data = attachment.get_file()
                buffer = io.BytesIO(file_data)
                buffer.seek(0)
                file = nextcord.File(fp=buffer, filename=(attachment.name or 'file.dat'))
                files.append(file)
            elif isinstance(attachment, UrlLink):
                links += f'{attachment.name}: {attachment.url} '

        formatted = self.format_message(message, links)

        channel = self.bot.get_channel(chat.id)
        wait_count = 0
        while channel is None:
            log.warn(f'Канал вернул None, ждём 5 секунд, попытка {wait_count+1}')
            await asyncio.sleep(5)
            channel = self.bot.get_channel(chat.id)
            wait_count += 1
            if wait_count >= 5:
                log.error(f'Попытались получить канал {wait_count} раз, выходим')
                return
            
        if self.is_webhook_mode():
            webhook = await self.get_webhook(channel)
            if webhook is None:
                log.error('Не получилось достать вебхук, фолбечим на обычное редактирование')
            else:
                uploader = self.settings.get('uploader', None)
                url = self.get_pfp_url(message.author)
                if url is None and uploader is None:
                    log.warn('uploader для дискорд бота с вебхуком не установлен, без него некоторые аватарки не получится отобразить')
                if self.is_embed_mode() and message.reply_to:
                    formatted_reply = self.format_message(message.reply_to)

                    embed = nextcord.Embed(type='rich', color=0x000000)
                    embed.set_author(name= EMBED_REPLY_MARK + 'В ответ на ' +formatted_reply.nick, icon_url=self.get_pfp_url(message.reply_to.author))
                    embed.description = formatted_reply.text
                    embed.set_footer(text=formatted_reply.footer)

                    mention_member = channel.guild.get_member(message.reply_to.author.id)
                    if message.reply_to.author.platform == Platform.Discord and mention_member:
                        mention = f'\n||{mention_member.mention}||'
                    else:
                        mention = ''
                    
                    sent_message: nextcord.WebhookMessage = await webhook.send(content=formatted.text + mention, 
                                                                               username=formatted.webhook_nick,
                                                                               avatar_url=url, embed=embed, 
                                                                               files=files, wait=True)
                    message.set_data(chat, 'webhook', sent_message)
                    return MessageID(chat, sent_message.id)
                else:
                    sent_message: nextcord.WebhookMessage = await webhook.send(content=formatted.text, username=formatted.webhook_nick,
                                                                            avatar_url=url, files=files, wait=True)
                    message.set_data(chat, 'webhook', sent_message)
                    return MessageID(chat, sent_message.id)
        
        embed = None
        if self.is_embed_mode():
            embed = nextcord.Embed(type='rich', color=0x000000)
            embed.set_author(name=formatted.nick, icon_url=self.get_pfp_url(message.author))
            embed.description = formatted.text
            embed.set_footer(text=formatted.footer)

            sent_message = await channel.send(embed=embed, reference=reference, files=files)
            return MessageID(chat, sent_message.id)

        else:
            sent_message = await channel.send(formatted.default_text, reference=reference, files=files)
            return MessageID(chat, sent_message.id)

    async def edit_message(self, message_id: MessageID, new_message: Message):
        old_message = self.coordinator.db_get_message(message_id)

        links = ''
        for attachment in old_message.attachments:
            if isinstance(attachment, UrlLink):
                links += f'{attachment.name}: {attachment.url} '

        channel = self.bot.get_channel(message_id.chat.id)
        native_message = await channel.fetch_message(message_id.id)
        
        formatted = self.format_message(new_message, links)

        if self.is_webhook_mode():
            webhook_message: nextcord.WebhookMessage = old_message.get_data(message_id.chat, 'webhook', dict())
            if webhook_message:
                await webhook_message.edit(content=formatted.text)
                return
            else:
                log.error('Не получилось достать webhook сообщение,')
        else:
            if len(native_message.embeds) > 0:
                embed = native_message.embeds[0]
                embed.description = formatted.text

                await native_message.edit(embed=embed)
                return
            await native_message.edit(content=formatted.default_text)

    async def delete_message(self, message_id: MessageID):
        channel = self.bot.get_channel(message_id.chat.id)
        await channel.get_partial_message(message_id.id).delete()
    
    def __hash__(self) -> int:
        return super().__hash__()