from app.helpers.calendar.google_provider import GoogleProvider
from app.helpers.calendar.ical_provider import ICalProvider
from app.helpers.calendar.outlook_provider import OutlookProvider

def get_provider(provider_name, user_id, connection_id=None):
    mapping = {
        "google":  GoogleProvider,
        "apple":   ICalProvider,
        "ical":    ICalProvider,
        "outlook": OutlookProvider,
    }
    key = (provider_name or "").lower()
    cls = mapping.get(key)
    return cls(user_id, connection_id=connection_id) if cls else None
