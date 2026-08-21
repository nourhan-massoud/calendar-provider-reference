"""Same caller path as CalendarController.connect — no if provider == ..."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.helpers.calendar.factory import get_provider
from app.models.Calendar import Calendar


def connect(provider: str, user_id: int, role: str = "player", organizer_id: int = 0):
    """Mirrors CalendarController.connect: factory + one start_connect call."""
    # Polymorphism: one start_connect() call; Google/Outlook/iCal each run their own implementation.
    prov = get_provider(provider, user_id)
    if not prov:
        raise ValueError(f"Unsupported provider: {provider}")

    # Strategy step 3 — context: run whichever algorithm Factory selected, via the same method.
    intent_type, url, role, organizer_id, state = prov.start_connect(
        role=role,
        organizer_id=organizer_id,
        user_id=user_id,
    )
    return {
        "provider": provider,
        "type": intent_type,
        "url": url,
        "state": state,
        "role": role,
        "organizer_id": organizer_id,
    }


def main() -> None:
    Calendar.reset()
    user_id = 1

    # Same two lines for every vendor. The class behind `prov` changes;
    # the caller does not.
    for name in ("google", "outlook", "apple"):
        result = connect(name, user_id)
        print(name, result["type"], result["url"].split("?")[0])


if __name__ == "__main__":
    main()
