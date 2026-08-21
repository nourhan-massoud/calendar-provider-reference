from app.helpers.calendar.factory import get_provider
from app.helpers.calendar.google_provider import GoogleProvider
from app.helpers.calendar.ical_provider import ICalProvider
from app.helpers.calendar.outlook_provider import OutlookProvider
from app.helpers.calendar.base import CalendarProviderBase


def test_google_resolves_to_google_provider():
    provider = get_provider("google", user_id=10)
    assert isinstance(provider, GoogleProvider)
    assert isinstance(provider, CalendarProviderBase)


def test_outlook_resolves_to_outlook_provider():
    provider = get_provider("outlook", user_id=10)
    assert isinstance(provider, OutlookProvider)
    assert isinstance(provider, CalendarProviderBase)


def test_ical_resolves_to_ical_provider():
    provider = get_provider("ical", user_id=10)
    assert isinstance(provider, ICalProvider)


def test_apple_alias_resolves_to_ical_provider():
    provider = get_provider("apple", user_id=10)
    assert isinstance(provider, ICalProvider)


def test_unsupported_provider_returns_none():
    assert get_provider("yahoo", user_id=10) is None
