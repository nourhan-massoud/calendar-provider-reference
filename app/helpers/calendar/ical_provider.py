from app.config import current_app as app

from app.models.Calendar import Calendar
from app.helpers.calendar.base import CalendarProviderBase

class ICalProvider(CalendarProviderBase):
    def start_connect(
        self, role: str, organizer_id: int, user_id: int = None, return_origin: str = ""
    ):
        # Normalize role and organizer_id
        role = (role or "").strip().lower()
        org_id = int(organizer_id or 0)

        # Validate role/organizer_id
        if role not in ("player", "instructor", "admin"):
            raise ValueError("role must be player, instructor or admin")
        if role in ("instructor", "admin") and not org_id:
            raise ValueError("organizer id is required for instructor/admin role")

        token = Calendar().ics_get_or_create_token(self.user_id, role, org_id)
        if not token:
            raise RuntimeError("Error generating ICS token")

        feed_url = f"{app.config['BACKEND_BASE_URL']}studios/calendar/ics/{token}.ics"
        return "feed_url", feed_url, role, org_id, None
    
    def has_active(self, role: str = None, organizer_id: int = None) -> bool:
        # Pass-through to DB helper (supports filtering by role/organizer)
        return Calendar().has_active_ics_connection(self.user_id, role=role, organizer_id=organizer_id)
    
    def revoke(self, role: str = None, organizer_id: int = None, connection_id: int = None):
        """
        Revoke the iCal connection by deleting (revoking) the token.
        connection_id is accepted for API compatibility; it is unused for iCal.
        """
        # Normalize inputs
        role = (role or "").strip().lower() or None
        org_id = None if organizer_id in (None, "", "null") else int(organizer_id)

        Calendar().ics_revoke(self.user_id, role=role, organizer_id=org_id)
        return True
