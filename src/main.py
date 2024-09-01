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

import yaml.loader
import yaml.loader

VK_CONVERSATION_ID = 2000000000

log = logging.getLogger('main')
log.setLevel(logging.DEBUG)
stderrhandler = logging.StreamHandler(sys.stderr)
stderrhandler.setFormatter(logging.Formatter('%(levelname)s: %(name)s at %(asctime)s: %(filename)s on line %(lineno)d: %(message)s'))
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
    from yaml import load as yamlload
    from yaml import Loader as YamlLoader

    if not os.path.exists('config.yaml'):
        log.error('Конфиг config.yaml не найден, создайте конфиг по примеру config.yaml.example')
        exit(0)

    with open('config.yaml', 'r', encoding='utf-8') as f:
        data: dict = yamlload(f, Loader=YamlLoader)
        
    global coordinator
    coordinator = Coordinator()
    
    coordinator_key = list(data.keys())[0]
    bots = data[coordinator_key]['bots']
    bridges = data[coordinator_key]['bridges']
    chats = data[coordinator_key]['chats']

    bot_by_keys = dict()
    bridge_by_key = dict()

    for bot_key in bots:
        bot_data = bots[bot_key]
        name = bot_data['name']
        match bot_data['type']:
            case 'discord':
                if 'uploader' in bot_data:
                    uploader_type, link = bot_data['uploader'].split()
                    bot_data.pop('uploader')
                    if uploader_type == 'imgpush':
                        uploader = ImgPushUploader(link)
                        bot_data['uploader'] = uploader
                bot_instance = DiscordBot(bot_key, name, coordinator, settings=bot_data)
                bot_by_keys[bot_key] = bot_instance
            case 'telegram':
                bot_instance = TelegramBot(bot_key, name, coordinator, settings=bot_data)
                bot_by_keys[bot_key] = bot_instance
            case 'vk':
                bot_instance = VkBot(bot_key, name, coordinator, settings=bot_data)
                bot_by_keys[bot_key] = bot_instance
    
    for bridge_key in bridges:
        bridge = Bridge(bridge_key)
        bridge_by_key[bridge_key] = bridge
        coordinator.add_bridge(bridge)
    
    for chat_data in chats:
        id = chat_data['id']
        server_id = chat_data.get('server_id', None)
        bot_id = chat_data['bot_id']
        prefix = chat_data.get('prefix', '')
        bridge = chat_data.get('bridge', None)
        bridges = chat_data.get('bridges', [])
        if bridge is not None:
            bridges.append(bridge)
        bot = bot_by_keys[bot_id]
        platform = bot.platform

        chat = Chat(platform, id, server_id, prefix=prefix)
        for bridge_key in bridges:
            bridge = bridge_by_key[bridge_key]
            coordinator.add_chat_to_bridge(bridge, chat)
        coordinator.link_bot_chat(bot, chat)

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