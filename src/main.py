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

from worker_types import *
from discord import *
from telegram import *
from vk import *

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