from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

from app.helpers.calendar.base import CalendarProviderBase
from app.helpers.calendar.factory import get_provider
from app.helpers.calendar.google_provider import GoogleProvider
from app.helpers.calendar.outlook_provider import OutlookProvider
from app.models.Calendar import Calendar


def sample_payload(**overrides: Any) -> dict[str, Any]:
    data = {
        "title": "Morning yoga",
        "start": "2026-08-21T09:00:00",
        "end": "2026-08-21T10:00:00",
        "timezone": "UTC",
        "location": "Studio 1",
        "class_id": 42,
    }
    data.update(overrides)
    return data


class FakeResponse:
    def __init__(self, status_code: int, payload: Optional[dict[str, Any]] = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeExecute:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def execute(self) -> Any:
        return self._payload


class FakeGoogleEvents:
    def insert(self, calendarId: str, body: dict[str, Any]) -> FakeExecute:
        assert calendarId == "primary"
        assert body["summary"] == "Morning yoga"
        return FakeExecute({"id": "google-event-1", "etag": "g-etag-1"})

    def patch(self, calendarId: str, eventId: str, body: dict[str, Any]) -> FakeExecute:
        assert eventId == "google-event-1"
        return FakeExecute({"id": eventId, "etag": "g-etag-2"})

    def delete(self, calendarId: str, eventId: str) -> FakeExecute:
        assert eventId == "google-event-1"
        return FakeExecute(None)


class FakeGoogleService:
    def events(self) -> FakeGoogleEvents:
        return FakeGoogleEvents()


def test_callers_use_base_type():
    for name in ("google", "outlook", "ical"):
        provider = get_provider(name, user_id=10)
        assert isinstance(provider, CalendarProviderBase)
        assert callable(provider.start_connect)
        assert callable(provider.revoke)


def test_ical_start_connect_returns_feed_url():
    provider = get_provider("ical", user_id=10)
    intent, url, role, org_id, state = provider.start_connect(
        role="player", organizer_id=0, user_id=10
    )
    assert intent == "feed_url"
    assert "/studios/calendar/ics/" in url
    assert url.endswith(".ics")
    assert state is None
    assert role == "player"


def test_ical_revoke_issues_new_token():
    provider = get_provider("ical", user_id=10)
    _, first, _, _, _ = provider.start_connect(role="player", organizer_id=0, user_id=10)
    provider.revoke(role="player", organizer_id=0)
    _, second, _, _, _ = provider.start_connect(role="player", organizer_id=0, user_id=10)
    assert first != second


def test_google_start_connect_builds_oauth_url():
    provider = get_provider("google", user_id=10)
    intent, url, role, org_id, state = provider.start_connect(
        role="player", organizer_id=0, user_id=10
    )
    assert intent == "oauth_redirect"
    assert "accounts.google.com" in url
    assert Calendar().get_oauth_state(state)["provider"] == "google"


def test_outlook_start_connect_builds_oauth_url():
    provider = get_provider("outlook", user_id=10)
    intent, url, role, org_id, state = provider.start_connect(
        role="player", organizer_id=0, user_id=10
    )
    assert intent == "oauth_redirect"
    assert "login.microsoftonline.com" in url
    assert "client_id=your-microsoft-client-id" in url
    assert Calendar().get_oauth_state(state)["provider"] == "outlook"


def test_google_create_update_delete_event():
    connection_id = Calendar().upsert_connection(
        user_id=10,
        provider="google",
        access_tok="demo-access-token",
        refresh_tok="demo-refresh-token",
        email="user@example.com",
    )
    provider = get_provider("google", user_id=10, connection_id=connection_id)
    assert isinstance(provider, GoogleProvider)

    with patch.object(GoogleProvider, "_service", return_value=FakeGoogleService()):
        event_id, etag = provider.create_event(**sample_payload())
        assert event_id == "google-event-1"
        updated_id, updated_etag = provider.update_event(
            **sample_payload(provider_event_id=event_id)
        )
        assert updated_id == event_id
        assert updated_etag == "g-etag-2"
        assert provider.delete_event(event_id) is True


def test_google_exchange_code_persists_connection():
    provider = get_provider("google", user_id=10)
    fake_creds = SimpleNamespace(
        granted_scopes=["https://www.googleapis.com/auth/calendar.events"],
        id_token="unused-jwt",
        token="google-access",
        refresh_token="google-refresh",
    )
    fake_flow = MagicMock()
    fake_flow.oauth2session = SimpleNamespace(scope=["openid"])
    fake_flow.credentials = fake_creds

    with patch.object(GoogleProvider, "_flow", return_value=fake_flow), patch(
        "app.helpers.calendar.google_provider.id_token.verify_oauth2_token",
        return_value={"email": "user@example.com", "sub": "google-sub"},
    ):
        result = provider.exchange_code("demo-auth-code", role="player")

    fake_flow.fetch_token.assert_called_once_with(code="demo-auth-code")
    assert result["email"] == "user@example.com"
    stored = Calendar().get_connection_by_id(result["connection_id"])
    assert stored["access_token"] == "google-access"
    assert stored["external_uid"] == "google-sub"


def test_outlook_create_update_delete_event():
    connection_id = Calendar().upsert_connection(
        user_id=10,
        provider="outlook",
        access_tok="demo-access-token",
        refresh_tok="demo-refresh-token",
        email="user@example.com",
    )
    provider = get_provider("outlook", user_id=10, connection_id=connection_id)
    assert isinstance(provider, OutlookProvider)

    def fake_post(url, **kwargs):
        if url.endswith("/me/events"):
            return FakeResponse(201, {"id": "outlook-event-1", "@odata.etag": "etag-1"})
        return FakeResponse(200, {"id": "outlook-event-1"})

    def fake_patch(url, **kwargs):
        return FakeResponse(200, {"id": "outlook-event-1", "@odata.etag": "etag-2"})

    def fake_delete(url, **kwargs):
        return FakeResponse(204)

    with patch("app.helpers.calendar.outlook_provider.requests.post", side_effect=fake_post), patch(
        "app.helpers.calendar.outlook_provider.requests.patch", side_effect=fake_patch
    ), patch("app.helpers.calendar.outlook_provider.requests.delete", side_effect=fake_delete):
        event_id, etag = provider.create_event(**sample_payload())
        assert event_id == "outlook-event-1"
        updated_id, updated_etag = provider.update_event(
            **sample_payload(provider_event_id=event_id)
        )
        assert updated_etag == "etag-2"
        assert provider.delete_event(event_id) is True


def test_outlook_exchange_code_uses_token_endpoint():
    provider = get_provider("outlook", user_id=10)

    def fake_post(url, **kwargs):
        if "oauth2/v2.0/token" in url:
            return FakeResponse(
                200,
                {
                    "access_token": "outlook-access",
                    "refresh_token": "outlook-refresh",
                    "expires_in": 3600,
                },
            )
        return FakeResponse(200, {})

    def fake_get(url, **kwargs):
        return FakeResponse(200, {"id": "ms-user-1", "mail": "user@example.com"})

    with patch("app.helpers.calendar.outlook_provider.requests.post", side_effect=fake_post), patch(
        "app.helpers.calendar.outlook_provider.requests.get", side_effect=fake_get
    ):
        result = provider.exchange_code("demo-auth-code", role="player")

    assert result["email"] == "user@example.com"
    stored = Calendar().get_connection_by_id(result["connection_id"])
    assert stored["provider"] == "outlook"
    assert stored["access_token"] == "outlook-access"


def test_google_update_requires_provider_event_id():
    connection_id = Calendar().upsert_connection(
        10, "google", "demo-access-token", "demo-refresh-token"
    )
    provider = get_provider("google", user_id=10, connection_id=connection_id)
    with patch.object(GoogleProvider, "_service", return_value=FakeGoogleService()):
        with pytest.raises(ValueError, match="provider_event_id"):
            provider.update_event(**sample_payload())
