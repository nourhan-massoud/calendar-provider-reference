"""Minimal caller example — same entry point as CalendarController.connect."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.helpers.calendar.factory import get_provider
from app.models.Calendar import Calendar


def main() -> None:
    Calendar.reset()
    user_id = 1

    google = get_provider("google", user_id)
    outlook = get_provider("outlook", user_id)
    ical = get_provider("apple", user_id)

    g_type, g_url, g_role, g_org, g_state = google.start_connect(
        role="player", organizer_id=0, user_id=user_id
    )
    o_type, o_url, o_role, o_org, o_state = outlook.start_connect(
        role="player", organizer_id=0, user_id=user_id
    )
    i_type, i_url, i_role, i_org, i_state = ical.start_connect(
        role="player", organizer_id=0, user_id=user_id
    )

    print("Google:", g_type, g_url.split("?")[0])
    print("Outlook:", o_type, o_url.split("?")[0])
    print("iCal:", i_type, i_url)

    # After OAuth, the controller does:
    #   prov = get_provider(provider, user_id, connection_id=connection_id)
    #   prov.create_event(title="...", start="...", end="...", timezone="UTC", class_id=42)


if __name__ == "__main__":
    main()
