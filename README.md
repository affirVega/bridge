# Bridger - мост между Discord, Telegram, VK

Запуск описан ниже

```bash
git clone https://github.com/affirvega/bridge
cd bridge

python3 -m venv .venv
source .venv/bin/activate
# на windows команда для cmd и powershell:
# .venv\Scripts\activate.bat
# .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

cp .env.example .env
nano .env # отредактируйте .env тут

python3 src/main.py
```

Чисто локальный проект по синхронизации чатов друг с другом.

Текущий функционал проекта (после переписывания xD)

|                      | discord | vk | telegram |
|----------------------|---------|----|----------|
| Прием событий        |         |    |          |
| - новое сообщение    | 🟢      | 🟢 | 🟢       |
| - редактирование     | 🟢      | 🔴 | 🟢       |
| - удаление           | 🟢      | 🔴 | 🔴       |
| Отправка в свои чаты |         |    |          |
| - новое сообщение    | 🟢      | 🟢 | 🟢       |
| - ответ на сообщение | 🟢      | 🟢 | 🟢       |
| - редактирование     | 🟢      | 🟢 | 🟢       |
| - удаление           | 🟢      | 🟢 | 🟢       |
| Отправка вложений    |         |    |          |
| - Фотография         | 🟢      | 🟢 | 🟢       |
| - Документ           | 🟢      | 🟢 | 🟢       |
| - Стикер             | 🟢      | 🟡 | 🟢       |
| Конфигурация         |         |    |          |

<sub>Вконтакте бот не получает событий редактирования и удаления, бот телеграм не получает события удаления.</sub>

Остаётся доделать:
- форматирование сообщений вк
- заргузка из конфига
- апи/консольное управление
- веб морду

Из того что планируется

- [ ] vk пересылка через юзербота
- [ ] Каждый канал может создавать и(или) отправлять сообщения (inout)
- [ ] Полная пересылка из любой соцсети в любую соцсеть
- [ ] Веб морда с разграничением по количеству чатов
- [ ] Документация по проекту и возможность для дополнения другими соцсетями
- [ ] База данных PostgreSQL, MySQL или SQLite
- [ ] Логирование

Я до этого пользовался matterbridge, вк-дискорд прекрасно пересылаются и вебхуки работают, но стикеры откправляются как
огромные картинки. В телеграм режим markdown сломан совсем