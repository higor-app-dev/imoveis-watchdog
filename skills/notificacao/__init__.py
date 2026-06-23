"""notificacao — Sistema de notificação multicanal."""

from .notificacao import (
    Notifier,
    NotifierChannel,
    ConsoleChannel,
    FileChannel,
    TelegramChannel,
    criar_notifier,
)

__all__ = [
    "Notifier",
    "NotifierChannel",
    "ConsoleChannel",
    "FileChannel",
    "TelegramChannel",
    "criar_notifier",
]
