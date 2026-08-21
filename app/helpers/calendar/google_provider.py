import secrets
import requests
from typing import Union

from app.config import current_app as app
from google.auth.transport.requests import Request as GRequest
from google.auth.transport import requests as g_requests
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from app.helpers.Util import fully_decode
from app.helpers.Util import expand_times

from app.models.Calendar import Calendar
from app.helpers.calendar.base import CalendarProviderBase

class GoogleProvider(CalendarProviderBase):
    provider_name = "google"
    required_calendar_scope = "https://www.googleapis.com/auth/calendar.events"

    def __init__(self, user_id: int, connection_id: int = None):
        super().__init__(user_id=user_id, connection_id=connection_id)
        self.access_token = None
        self.refresh_token = None
        cal = Calendar()
        if connection_id:
            row = cal.get_connection_by_id(connection_id)
        else:
            row = cal.get_connection(user_id, "google")
        if row:
            self.access_token  = row.get("access_token")
            self.refresh_token = row.get("refresh_token")

    def start_connect(self, role: str, organizer_id: int, user_id: int, return_origin: str = ""):
        # if this is ins view without specific organizer, it will raise an error
        if not organizer_id and role == "instructor":
            raise ValueError("Missing organizer for instructor")

        if Calendar().provider_link_exists_active(self.user_id, self.provider_name, role, organizer_id):
            raise ValueError("Already connected for this organizer")

        # Validate and preserve the complete HTTPS return URL before storing.
        from app.helpers.Util import normalize_origin
        return_origin = normalize_origin(return_origin) or ""

        # Begin OAuth: build auth URL, persist state (10 minutes), single return
        auth_url, state = self.build_auth_url(role)
        Calendar().insert_oauth_state(state,user_id,"google",role,organizer_id,return_origin)

        return "oauth_redirect", auth_url, role, organizer_id, state

    def _ensure_credentials(self):
        if not self.access_token:
            raise RuntimeError("No active Google connection")

        creds = Credentials(
            token=self.access_token,
            refresh_token=self.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=app.config["GOOGLE_CLIENT_ID"],
            client_secret=app.config["GOOGLE_CLIENT_SECRET"],
            scopes=app.config["GOOGLE_SCOPES"],
        )
        try:
            if creds.expired and creds.refresh_token:
                creds.refresh(GRequest())
        except RefreshError:
            Calendar().mark_connection_revoked(self.user_id, "google")
            raise RuntimeError("Google connection expired — please connect again")

        if (creds.token != self.access_token or (creds.refresh_token and creds.refresh_token != self.refresh_token)):
            if not self.connection_id:
                # Avoid updating an unknown row; fail loudly
                raise RuntimeError("Missing connection_id while updating tokens")
            Calendar().update_connection_tokens_by_id(  # safe now
                self.connection_id, access_tok=creds.token,
                refresh_tok=creds.refresh_token or ""
            )
            self.access_token  = creds.token
            self.refresh_token = creds.refresh_token

        return creds

    def _service(self):
        if not self.connection_id:
            raise RuntimeError("GoogleProvider requires connection_id for API operations")
    
        creds = self._ensure_credentials()
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return service

    def _flow(self, state: Union[str, None] = None, role: str = ""):
        try:
            # Define the OAuth2 client configuration using Google's expected format
            cfg = {
                "web": {
                    "client_id": app.config["GOOGLE_CLIENT_ID"],
                    "client_secret": app.config["GOOGLE_CLIENT_SECRET"],
                    "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",  # v2
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
            # Player / widget uses the registered Google callback page per environment.
            if (role or "").strip().lower() == "player":
                redirect_uri = app.config["WIDGET_CALENDAR_CALLBACK_URL"]
            else:
                redirect_uri = f"{app.config['CLASSFIT_URL']}myclasses"
            return Flow.from_client_config(
                cfg,
                scopes=app.config["GOOGLE_SCOPES"],
                redirect_uri=redirect_uri,
                state=state
            )
        except Exception as e:
            raise ValueError(f"Failed to create OAuth2 flow: {str(e)}")

    # -------- Step-1 --------
    def build_auth_url(self, role: str = ""):
        try:
            state = secrets.token_urlsafe(16)

            # Create the authorization URL for the OAuth2 flow
            url, _ = self._flow(state, role).authorization_url(
                access_type="offline",
                prompt="consent select_account",
                include_granted_scopes="true",
                state=state,
            )
            return url, state
        except Exception as e:
            raise ValueError(f"Failed to build auth URL: {str(e)}")

    # -------- Step-2 --------
    def exchange_code(self, code, role: str = ""):
        try:
            flow = self._flow(None, role)
            # Google may return scopes in a different order or include legacy ones from a prior consent.
            # Disable oauthlib's strict scope equality check just for this token exchange.
            flow.oauth2session.scope = None
            flow.fetch_token(code=code)
            creds = flow.credentials

            if self.required_calendar_scope not in (creds.granted_scopes or []):
                
                raise ValueError(
                    "Google Calendar permission is required. "
                    "Please select Calendar access and try connecting again."
                )

            # Extract user identity from the returned id_token
            info = id_token.verify_oauth2_token(
                creds.id_token,  # JWT issued by Google
                g_requests.Request(),  # HTTP transport for validation
                app.config["GOOGLE_CLIENT_ID"],
                clock_skew_in_seconds=60
            )
            email  = info.get("email")
            sub_id = info.get("sub")  # Google-wide unique user ID

            # Insert the connection details in our DB
            connection_id = Calendar().upsert_connection(self.user_id,"google",
                creds.token, creds.refresh_token or "", email, sub_id)
            return {"connection_id": connection_id, "email": email}

        except Exception as e:
            if "Google Calendar permission is required" in str(e):
                raise ValueError(str(e))
            if "Scope has changed" in str(e):
                raise ValueError("Google Calendar permissions changed. Please try connecting again.")
            raise ValueError(f"Failed to exchange code: {str(e)}")

    def revoke(self, role: str = None, organizer_id: int = None, connection_id: int = None):
        cal = Calendar()

        if connection_id:
            row = cal.get_connection_by_id(connection_id)
            if not row:
                raise ValueError("Invalid connection_id")

            if row and (row.get("refresh_token") or row.get("access_token")):
                token_to_revoke = row.get("refresh_token") or row.get("access_token")
                try:
                    requests.post(
                        "https://oauth2.googleapis.com/revoke",
                        data={"token": token_to_revoke},
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        timeout=10
                    )
                except Exception:
                    pass

            cal.mark_connection_revoked_by_id(connection_id)
            cal.provider_link_revoke_by_connection(connection_id)
            return True

        if role == "instructor" and organizer_id:
            cal.provider_link_revoke(self.user_id, "google", "instructor", int(organizer_id))
            return True

        row = cal.get_connection(self.user_id, "google")
        if not row:
            return True

        token_to_revoke = row.get("refresh_token") or row.get("access_token") or ""
        if token_to_revoke:
            try:
                requests.post(
                    "https://oauth2.googleapis.com/revoke",
                    data={"token": token_to_revoke},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=10
                )
            except Exception:
                pass

        cal.mark_connection_revoked(self.user_id, "google")
        return True

    def build_event_body(self, payload):
        """Build a Google Calendar API event body from a class payload."""
        start_str, end_str, tz_name = expand_times(payload)
        class_url = app.config["CLASSFIT_URL"] + "class/" + str(payload["class_id"])
        return {
            "summary": fully_decode(payload.get("title") or ""),
            "start": {"dateTime": start_str, "timeZone": tz_name},
            "end":   {"dateTime": end_str,   "timeZone": tz_name},
            "location": fully_decode(payload.get("location") or ""),
            "source": {"title": "Calendar App", "url": class_url},
            "guestsCanSeeOtherGuests": False,
            "anyoneCanAddSelf": False,
            "guestsCanInviteOthers": False,
            "reminders": {"useDefault": False},
        }

    def service(self):
        """Public accessor for the Google API service client."""
        return self._service()

    def create_event(self, **payload):
        try:
            body = self.build_event_body(payload)
            created = self._service().events().insert(calendarId="primary", body=body).execute()
            return created["id"], created.get("etag")
        except Exception as e:
            raise ValueError(f"Failed to create event: {str(e)}")

    def create_events_batch(self, items: list):
        created_events = []
        service = self._service()

        for start in range(0, len(items), 50):
            chunk = items[start:start + 50]
            item_by_request_id = {}

            def callback(request_id, response, exception):
                if exception:
                    print(f"Google batch create event failed: {exception}")
                    return
                try:
                    item = item_by_request_id.get(request_id)
                    if not item:
                        return
                    created_events.append({
                        "class_id": item["class_id"],
                        "provider_event_id": response["id"],
                        "etag": response.get("etag"),
                    })
                except Exception as ex:
                    print(f"Error reading Google batch response for {request_id}: {ex}")

            batch = service.new_batch_http_request(callback=callback)
            for i, item in enumerate(chunk):
                request_id = str(i)
                item_by_request_id[request_id] = item
                batch.add(
                    service.events().insert(calendarId="primary", body=item["body"]),
                    request_id=request_id,
                )
            batch.execute()
        return created_events

    def update_event(self, **payload):
        try:
            provider_event_id = payload.get("provider_event_id")
            if not provider_event_id:
                raise ValueError("Missing provider_event_id")

            body = self.build_event_body(payload)
            updated = self._service().events().patch(
                calendarId="primary", eventId=provider_event_id, body=body
            ).execute()
            return updated["id"], updated.get("etag")
        except Exception as e:
            raise ValueError(f"Failed to update event: {str(e)}")

    def delete_event(self, provider_event_id: str):
        """
        Delete an existing event from Google Calendar using its provider_event_id.
        """
        try:
            if not provider_event_id:
                raise ValueError("Missing provider_event_id")

            service = self._service()
            service.events().delete(
                calendarId="primary",
                eventId=provider_event_id
            ).execute()
        except Exception as e:
            raise ValueError(f"Failed to delete event: {str(e)}")

        return True

    def delete_events_batch(self, event_ids: list):
        if not event_ids:
            return True

        failures = []
        service = self._service()

        for start in range(0, len(event_ids), 50):
            chunk = event_ids[start:start + 50]

            def callback(request_id, response, exception):
                if exception:
                    eid = chunk[int(request_id)]
                    status = getattr(getattr(exception, "resp", None), "status", None)
                    if status in (404, 410):
                        return
                    print(f"Google batch delete event failed for {eid}: {exception}")
                    failures.append(str(eid))

            batch = service.new_batch_http_request(callback=callback)
            for i, eid in enumerate(chunk):
                batch.add(
                    service.events().delete(calendarId="primary", eventId=eid),
                    request_id=str(i),
                )
            batch.execute()

        if failures:
            raise RuntimeError(f"Google batch delete failed for {len(failures)} event(s)")
        return True
