"""In-memory storage for OAuth connections and ICS feed tokens."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Optional


class Calendar:
    _connections: dict[int, dict] = {}
    _oauth_states: dict[str, dict] = {}
    _links: list[dict] = []
    _ics: list[dict] = []
    _next_id = 1

    @classmethod
    def reset(cls) -> None:
        cls._connections = {}
        cls._oauth_states = {}
        cls._links = []
        cls._ics = []
        cls._next_id = 1

    def insert_oauth_state(
        self,
        state: str,
        user_id: int,
        provider: str,
        role: str = "",
        organizer_id: int = 0,
        return_origin: str = "",
    ):
        expires_at = datetime.utcnow() + timedelta(minutes=10)
        self._oauth_states[state] = {
            "state": state,
            "user_id": user_id,
            "provider": provider.lower(),
            "role": role,
            "organizer_id": organizer_id or 0,
            "return_origin": return_origin or "",
            "expires_at": expires_at,
        }
        return True

    def get_oauth_state(self, state: str):
        return self._oauth_states.get(state)

    def upsert_connection(
        self,
        user_id: int,
        provider: str,
        access_tok: str,
        refresh_tok: str,
        email: str = None,
        external_uid: str = None,
    ):
        provider = provider.lower()
        existing = self.get_connection(user_id, provider)
        if existing:
            existing["access_token"] = access_tok
            existing["refresh_token"] = refresh_tok
            existing["email"] = email
            existing["external_uid"] = external_uid
            existing["revoked_at"] = None
            return existing["id"]

        connection_id = Calendar._next_id
        Calendar._next_id += 1
        Calendar._connections[connection_id] = {
            "id": connection_id,
            "user_id": user_id,
            "provider": provider,
            "access_token": access_tok,
            "refresh_token": refresh_tok,
            "email": email,
            "external_uid": external_uid,
            "revoked_at": None,
        }
        return connection_id

    def get_connection_by_id(self, connection_id: int):
        row = Calendar._connections.get(int(connection_id))
        if not row or row.get("revoked_at") is not None:
            return None
        return row

    def update_connection_tokens_by_id(self, connection_id: int, *, access_tok: str, refresh_tok: str):
        row = Calendar._connections.get(int(connection_id))
        if row is None:
            return False
        row["access_token"] = access_tok
        row["refresh_token"] = refresh_tok
        row["revoked_at"] = None
        return True

    def get_connection(self, user_id: int, provider: str):
        key = provider.lower()
        for row in Calendar._connections.values():
            if (
                row["user_id"] == user_id
                and row["provider"] == key
                and row.get("revoked_at") is None
            ):
                return row
        return None

    def mark_connection_revoked(self, user_id: int, provider: str):
        row = self.get_connection(user_id, provider)
        if not row:
            return
        row["revoked_at"] = datetime.utcnow()
        row["access_token"] = None
        row["refresh_token"] = None

    def mark_connection_revoked_by_id(self, connection_id: int):
        row = Calendar._connections.get(int(connection_id))
        if not row or row.get("revoked_at") is not None:
            return True
        row["revoked_at"] = datetime.utcnow()
        row["access_token"] = None
        row["refresh_token"] = None
        return True

    def has_active_connection(self, user_id: int, provider: str) -> bool:
        return self.get_connection(user_id, provider) is not None

    def provider_link_add(self, user_id: int, provider: str, role: str, organizer_id: int, connection_id: int):
        Calendar._links.append(
            {
                "user_id": user_id,
                "provider": provider.lower(),
                "role": (role or "").lower(),
                "organizer_id": int(organizer_id or 0),
                "connection_id": connection_id,
                "revoked_at": None,
            }
        )
        return True

    def provider_link_exists_active(self, user_id: int, provider: str, role: str, organizer_id: int) -> bool:
        provider = provider.lower()
        role = (role or "").lower()
        organizer_id = int(organizer_id or 0)
        for link in Calendar._links:
            if (
                link["user_id"] == user_id
                and link["provider"] == provider
                and link["role"] == role
                and link["organizer_id"] == organizer_id
                and link.get("revoked_at") is None
            ):
                conn = self.get_connection_by_id(link["connection_id"])
                if conn:
                    return True
        return False

    def provider_link_revoke(self, user_id: int, provider: str, role: str, organizer_id: int) -> bool:
        now = datetime.utcnow()
        for link in Calendar._links:
            if (
                link["user_id"] == user_id
                and link["provider"] == provider.lower()
                and link["role"] == role.lower()
                and link["organizer_id"] == int(organizer_id)
                and link.get("revoked_at") is None
            ):
                link["revoked_at"] = now
        return True

    def provider_link_revoke_by_connection(self, connection_id: int):
        now = datetime.utcnow()
        for link in Calendar._links:
            if link["connection_id"] == int(connection_id) and link.get("revoked_at") is None:
                link["revoked_at"] = now
        return True

    def ics_get_or_create_token(self, user_id: int, role: str, organizer_id: int = None):
        if not user_id or not role:
            return None
        role = role.lower()
        org_id = int(organizer_id or 0)
        for row in Calendar._ics:
            if (
                row["user_id"] == int(user_id)
                and row["role"] == role
                and int(row.get("organizer_id") or 0) == org_id
                and row.get("revoked_at") is None
            ):
                return row["token"]
        token = secrets.token_urlsafe(48)
        Calendar._ics.append(
            {
                "user_id": int(user_id),
                "role": role,
                "organizer_id": org_id,
                "token": token,
                "revoked_at": None,
            }
        )
        return token

    def has_active_ics_connection(self, user_id: int, role: str = None, organizer_id: int = None) -> bool:
        for row in Calendar._ics:
            if row["user_id"] != int(user_id) or row.get("revoked_at") is not None:
                continue
            if role not in (None, "") and row["role"] != role.lower():
                continue
            if organizer_id not in (None, "") and int(row.get("organizer_id") or 0) != int(organizer_id):
                continue
            return True
        return False

    def ics_revoke(self, user_id: int, role: str = None, organizer_id: Optional[int] = None) -> bool:
        kept = []
        for row in Calendar._ics:
            if row["user_id"] != int(user_id):
                kept.append(row)
                continue
            if role not in (None, "") and row["role"] != role.lower():
                kept.append(row)
                continue
            if organizer_id is not None and int(row.get("organizer_id") or 0) != int(organizer_id):
                kept.append(row)
                continue
        Calendar._ics = kept
        return True
