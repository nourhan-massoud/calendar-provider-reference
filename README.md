# Calendar Provider Reference

A sanitized reference implementation of a multi-provider calendar integration.

The folder layout, class names, factory, and provider method signatures are kept together so the architecture is easy to follow.

There are **no real credentials** in this repository. OAuth values come from environment placeholders.

## Problem

Google Calendar, Microsoft Outlook, and iCal / Apple Calendar do not share one API. Without a provider layer, every feature grows `if provider == "google"` branches.

## Why one abstraction

The application does:

```python
from app.helpers.calendar.factory import get_provider

prov = get_provider(provider, user_id)
intent, url, role, organizer_id, state = prov.start_connect(...)
```

It does not import Google or Microsoft clients.

## Architecture

Project layout:

```text
app/helpers/calendar/     # providers
app/models/Calendar.py    # in-memory persistence
app/helpers/Util.py
app/config.py             # env-based current_app.config
```

```mermaid
flowchart TD
    App[Application]
    Factory[get_provider]
    Base[CalendarProviderBase]
    Google[GoogleProvider]
    Outlook[OutlookProvider]
    ICal[ICalProvider]
    GAPI[Google Calendar API]
    Graph[Microsoft Graph]
    ICS[ICS feed]

    App --> Factory
    Factory --> Base
    Base --> Google
    Base --> Outlook
    Base --> ICal
    Google --> GAPI
    Outlook --> Graph
    ICal --> ICS
```

```text
CalendarProviderBase
    start_connect()
    build_auth_url()    # OAuth providers
    exchange_code()     # OAuth providers
    revoke()
    create_event()      # Google / Outlook
    update_event()
    delete_event()
       │
       ├── GoogleProvider
       ├── OutlookProvider
       └── ICalProvider     # feed URL only; no OAuth / no push events
```

iCal is not forced to implement `exchange_code`. Those methods stay `NotImplementedError` on the base class.

`Calendar.py` stores connections and ICS tokens in memory for the demo.

Config is a `current_app.config` dict loaded from `.env`:

```python
from app.config import current_app as app
```

Keys include `GOOGLE_CLIENT_ID`, `MS_CLIENT_ID`, and `APP_BASE_URL`. Values are placeholders only.

## Factory

```python
mapping = {
    "google":  GoogleProvider,
    "apple":   ICalProvider,
    "ical":    ICalProvider,
    "outlook": OutlookProvider,
}
```

`get_provider("yahoo", user_id)` returns `None`.

## Polymorphism / strategy

`GoogleProvider` and `OutlookProvider` both implement `create_event(**payload)`. The caller does not care which class it received.

iCal's `start_connect` returns `("feed_url", url, ...)`. Google/Outlook return `("oauth_redirect", url, ...)`.

## Adapter

- **GoogleProvider** wraps Google OAuth (`Flow`, `Credentials`) and Calendar API v3 (`events().insert/patch/delete`).
- **OutlookProvider** wraps Microsoft identity and Graph (`/me/events`).

A shared payload (`title`, `start`, `end`, `timezone`, `class_id`, …) is mapped to each vendor's JSON inside the provider.

## How to add another provider

1. Add `app/helpers/calendar/new_provider.py` subclassing `CalendarProviderBase`.
2. Register it in `factory.py`.
3. Keep vendor API details inside that file.

## Environment setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env.example` has placeholders only. Never commit real OAuth client secrets.

## Example usage

```bash
python examples/basic_usage.py
```

```python
from app.helpers.calendar.factory import get_provider

prov = get_provider(provider, user_id)
if not prov:
    raise ValueError(f"Unsupported provider: {provider}")

intent_type, url, role, organizer_id, state = prov.start_connect(
    role=role, organizer_id=organizer_id, user_id=user_id
)
```

`provider` is only a string (`"google"` / `"outlook"` / `"ical"`). After `get_provider`, the caller never branches on that name.

## Tests

```bash
pytest
```

External Google / Microsoft HTTP calls are mocked.

## License

MIT. See [LICENSE](LICENSE).
