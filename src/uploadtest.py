import vk_api
from vk_api import VkUpload
from vk_api.bot_longpoll import VkBotLongPoll 
import dotenv
import requests
import os
from vk_api.upload import FilesOpener

dotenv.load_dotenv()

settings = {
    'token': os.environ.get('VK_TOKEN')
}

vk = vk_api.VkApi(token=settings['token'])
api = vk.get_api()
data = api.groups.get_by_id()
group_id = data[0]['id']
print('group_id', group_id)
upload = VkUpload(api)
longpoll = VkBotLongPoll(vk, group_id=group_id, wait=0) # потому что longpoll.check добавляет 10 к запросу

peer_id = 2000000004
with open('D:\\Feskow\\Downloads\\Wings.png', 'rb') as f:

    info = None
    url = api.photos.getMessagesUploadServer(group_id=group_id)['upload_url']

    with FilesOpener(f) as photo_files:
        response = requests.post(url, files=photo_files)

    j = response.json()
    params = {
        'server': j['server'],
        'hash': j['hash'],
        'photo': j['photo'],
        'v': '5.199',
        'access_token': settings['token']
    }
    print(params)

    # info = api.photos.saveMessagesPhoto(**params)
    info = requests.post(url='https://api.vk.com/method/photos.saveMessagesPhoto', params=params, headers={'Cookie': ''})
    print(info.text)
    print(info)

# upload = vk_api.VkUpload(vk)
# photo = upload.photo_messages('D:\\Feskow\\Downloads\\Wings.png', peer_id)
# owner_id = photo[0]['owner_id']
# photo_id = photo[0]['id']
# access_key = photo[0]['access_key']
# attachment = f'photo{owner_id}_{photo_id}_{access_key}'
# vk.messages.send(peer_id=peer_id, random_id=0, attachment=attachment)