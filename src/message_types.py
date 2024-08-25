from dataclasses import dataclass, field
import enum
import io
from typing import Optional
from PIL import Image
import requests


class Platform(enum.Enum):
    Discord = 0
    Telegram = 1
    Vk = 2


@dataclass
class Chat:
    platform: Platform
    id: int
    server_id: Optional[int] = None

    def __hash__(self):
        return hash((self.platform, self.id, self.server_id))


@dataclass
class IAttachment:
    name: Optional[str] = None

    def uncache(self):
        ...


@dataclass
class IPicture(IAttachment):
    def get_image(self) -> Image.Image:
        ...


@dataclass
class UrlPicture(IPicture):
    url: str = None
    _cached_image: Optional[Image.Image] = field(default=None, init=False, repr=False)

    def get_image(self) -> Optional[Image.Image]:
        if self._cached_image:
            return self._cached_image
        try:
            return self._download_image()
        except Exception:
            return None
    
    def _download_image(self) -> Image.Image:
        buffer = io.BytesIO(requests.get(self.url).content)
        self._cached_image = Image.open(buffer)
        return self._cached_image
    
    def uncache(self):
        del self._cached_image
        self._cached_image = None


@dataclass
class Sticker:
    picture: IPicture


@dataclass
class IFile(IAttachment):

    def get_file(self) -> Optional[bytes]:
        ...


@dataclass
class UrlFile(IFile):
    url: str = None
    _cached_data: Optional[bytes] = field(default=None, init=False, repr=False)

    def get_file(self) -> Optional[bytes]:
        if self._cached_data:
            return self._cached_data
        try:
            return self._download_file()
        except Exception:
            return None
    
    def _download_file(self) -> bytes:
        self._cached_data = requests.get(self.url).content
        return self._cached_data
    
    def uncache(self):
        del self._cached_data
        self._cached_data = None


@dataclass
class Author:
    platform: Platform
    id: int
    name: str
    username: str
    pfp: Optional[IPicture]


@dataclass
class MessageID:
    chat: Chat
    id: int

    def __hash__(self):
        return hash((self.chat, self.id))


@dataclass
class Message:
    original_id: MessageID
    author: Author
    text: str
    reply_to: Optional['Message'] = None
    relay_ids: list[MessageID] = field(default_factory=list)
    forwarded: list['Message'] = field(default_factory=list)
    attachments: list[IAttachment] = field(default_factory=list)

    def get_message_id(self, chat: Chat) -> Optional[int]:
        if chat == self.original_id.chat:
            return self.original_id.id
        for relay_id in self.relay_ids:
            if relay_id.chat == chat:
                return relay_id.id
        return None

    def __hash__(self):
        return hash(self.original_id)