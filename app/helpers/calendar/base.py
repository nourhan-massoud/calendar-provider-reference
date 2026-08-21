"""
Abstract base class for every calendar provider.
"""
from abc import ABC, abstractmethod


class CalendarProviderBase(ABC):
    def __init__(self, user_id: int, connection_id: int = None):
        self.user_id = user_id
        self.connection_id = connection_id

    @abstractmethod
    def start_connect(self, role=None, organizer_id=None):
        raise NotImplementedError

    def build_auth_url(self):
        raise NotImplementedError

    def exchange_code(self, code: str):
        raise NotImplementedError

    @abstractmethod
    def revoke(self, role=None, organizer_id=None, connection_id: int = None):
        raise NotImplementedError
