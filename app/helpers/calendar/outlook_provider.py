import secrets
import requests
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

from app.config import current_app as app

from app.models.Calendar import Calendar
from app.helpers.calendar.base import CalendarProviderBase
from app.helpers.Util import fully_decode
from app.helpers.Util import expand_times

class OutlookProvider(CalendarProviderBase):
    provider_name = "outlook"

    def __init__(self, user_id: int, connection_id: int = None):
        super().__init__(user_id, connection_id=connection_id)
        self.access_token = None
        self.refresh_token = None
        self._cached_expires_at: Optional[datetime] = None

        cal = Calendar()
        row = cal.get_connection_by_id(connection_id) if connection_id else cal.get_connection(user_id, "outlook")
        if row:
            self.access_token  = row.get("access_token")
            self.refresh_token = row.get("refresh_token")
            if connection_id:
                self.connection_id = row["id"]

    # ---------- Connect (OAuth) ----------
    def start_connect(self, role: str = None, organizer_id: int = None, user_id: int = None, return_origin: str = ""):
        role_in = (role or "player").strip().lower()
        org_in = int(organizer_id or 0)
        cal = Calendar()

        if role_in == "instructor" and not org_in:
            raise ValueError("Missing organizer for instructor")

        if cal.provider_link_exists_active(self.user_id, self.provider_name, role_in, org_in):
            raise ValueError("Already connected for this organizer")

        # Validate and preserve the complete HTTPS return URL before storing.
        from app.helpers.Util import normalize_origin
        return_origin = normalize_origin(return_origin) or ""

        # Begin OAuth: build auth URL, persist state (10 minutes), single return
        auth_url, state = self.build_auth_url(role_in)
        ok = Calendar().insert_oauth_state(
            state=state,
            user_id=self.user_id,
            provider=self.provider_name,
            role=role_in,
            organizer_id=org_in,
            return_origin=return_origin
        )
        if not ok:
            raise RuntimeError("Database error while storing OAuth state")

        return "oauth_redirect", auth_url, role_in, org_in, state

    def build_auth_url(self, role: str = ""):
        state = secrets.token_urlsafe(16)
        tenant = app.config.get("MS_TENANT", "common")
        base   = app.config["MS_AUTH_URI"].format(tenant=tenant)
        redirect_uri = self._redirect_uri(role)

        scopes = " ".join(app.config.get("MS_SCOPES", [
            "offline_access", "openid", "profile", "email", "Calendars.ReadWrite"
        ]))

        params = {
            "client_id": app.config["MS_CLIENT_ID"],
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": scopes,
            "state": state,
            # make Microsoft show the account picker even if a session exists
            "prompt": "select_account",
        }
        from urllib.parse import urlencode
        return f"{base}?{urlencode(params)}", state

    def exchange_code(self, code: str, role: str = ""):
        token = self._token_exchange(grant_type="authorization_code", code=code, role=role)
        access  = token["access_token"]
        refresh = token.get("refresh_token", "")
        expires = datetime.utcnow() + timedelta(seconds=token.get("expires_in", 3600))

        me = self._graph_get("/me", access)
        email = me.get("mail") or me.get("userPrincipalName")
        ms_uid = me.get("id")  # external_uid

        connection_id = Calendar().upsert_connection(
            user_id=self.user_id,
            provider="outlook",
            access_tok=access,
            refresh_tok=refresh,
            email=email,
            external_uid=ms_uid
        )
        self.access_token = access
        self.refresh_token = refresh
        self._cached_expires_at = expires
        self.connection_id = connection_id
        return {"connection_id": connection_id, "email": email}

    # ---------- Token helpers ----------
    def _token_url(self):
        tenant = app.config.get("MS_TENANT", "common")
        return app.config["MS_TOKEN_URI"].format(tenant=tenant)

    def _redirect_uri(self, role: str = ""):
        # Player / widget uses the registered callback page; others land on /myclasses.
        if (role or "").strip().lower() == "player":
            return app.config["WIDGET_CALENDAR_CALLBACK_URL"]
        return f"{app.config['CLASSFIT_URL']}myclasses"

    def _token_exchange(self, *, grant_type: str, code: str = None, refresh_token: str = None, role: str = ""):
        redirect_uri = self._redirect_uri(role)
        data = {
            "client_id": app.config["MS_CLIENT_ID"],
            "client_secret": app.config["MS_CLIENT_SECRET"],
            "grant_type": grant_type,
            "redirect_uri": redirect_uri,
            "scope": " ".join(app.config.get("MS_SCOPES", []))
        }
        if grant_type == "authorization_code":
            data["code"] = code
        elif grant_type == "refresh_token":
            data["refresh_token"] = refresh_token
        else:
            raise ValueError("Unsupported grant_type")

        r = requests.post(self._token_url(), data=data, timeout=20)
        if r.status_code != 200:
            raise ValueError(f"Outlook token exchange failed: HTTP {r.status_code}")
        return r.json()
    
    def _ensure_access_token(self) -> str:
        if self.access_token:
            return self.access_token
        if not self.refresh_token:
            raise RuntimeError("No active Outlook connection")

        tok = self._token_exchange(grant_type="refresh_token", refresh_token=self.refresh_token)
        self.access_token = tok.get("access_token")
        self.refresh_token = tok.get("refresh_token", self.refresh_token)
        self._cached_expires_at = datetime.utcnow() + timedelta(seconds=tok.get("expires_in", 3600))

        if not self.connection_id:
            raise RuntimeError("Missing connection_id while updating tokens")

        Calendar().update_connection_tokens_by_id(
            self.connection_id,
            access_tok=self.access_token,
            refresh_tok=self.refresh_token
        )
        return self.access_token

    # ---------- Graph helpers ----------
    def _graph_headers(self, token: str):
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _graph_get(self, path: str, token: Optional[str] = None):
        token = token or self._ensure_access_token()
        url = app.config["MS_GRAPH_BASE"] + path
        r = requests.get(url, headers=self._graph_headers(token), timeout=20)
        if r.status_code == 401 and self.refresh_token:
            self.access_token = None
            token = self._ensure_access_token()
            r = requests.get(url, headers=self._graph_headers(token), timeout=20)
        if r.status_code >= 400:
            raise RuntimeError(f"Graph GET {path} failed: HTTP {r.status_code}")
        return r.json()

    def _graph_write(self, method: str, path: str, json_body: dict = None):
        # Build request each time so we always use fresh headers after refresh
        url = app.config["MS_GRAPH_BASE"] + path

        def attempt():
            token = self._ensure_access_token()
            headers = self._graph_headers(token)
            if method == "GET":
                return requests.get(url, headers=headers, timeout=20)
            if method == "POST":
                return requests.post(url, headers=headers, json=json_body, timeout=20)
            if method == "PATCH":
                return requests.patch(url, headers=headers, json=json_body, timeout=20)
            if method == "DELETE":
                return requests.delete(url, headers=headers, timeout=20)
            raise RuntimeError(f"Unsupported method: {method}")

        r = attempt()
        if r.status_code == 401 and self.refresh_token:
            # Force refresh and retry with brand-new headers
            self.access_token = None
            r = attempt()

        if method == "DELETE":
            if r.status_code in (404, 410):
                return True
            if r.status_code not in (200, 202, 204):
                raise RuntimeError(f"Graph DELETE {path} failed: HTTP {r.status_code}")
            return True

        if r.status_code >= 400:
            raise RuntimeError(f"Graph {method} {path} failed: HTTP {r.status_code}")
        return r.json()


    # ---------- Events (per connection) ----------
    def build_event_body(self, payload):
        start_str, end_str, tz = expand_times(payload)
        title     = fully_decode(payload.get("title", "") or "")
        location  = fully_decode(payload.get("location", "") or "")
        class_id  = payload.get("class_id")
        class_url = app.config["CLASSFIT_URL"] + "class/" + str(class_id)

        body = {
            "subject": title,
            "body": {"contentType": "HTML",
                    "content": f"Link: {class_url}"},
            "start": {"dateTime": start_str, "timeZone": tz},
            "end":   {"dateTime": end_str,   "timeZone": tz},
            "location": {"displayName": location} if location else None,
            "isOnlineMeeting": False,
            "allowNewTimeProposals": False,
        }
        return {k: v for k, v in body.items() if v is not None}

    def create_event(self, **payload):
        body = self.build_event_body(payload)
        created = self._graph_write("POST", "/me/events", body)
        return created["id"], created.get("@odata.etag")

    def create_events_batch(self, items: list):
        created_events = []
        url = app.config["MS_GRAPH_BASE"] + "/$batch"

        for start in range(0, len(items), 20):
            chunk = items[start:start + 20]
            requests_payload = []
            item_by_request_id = {}

            # Microsoft Graph accepts up to 20 operations in one $batch request.
            for idx, item in enumerate(chunk):
                request_id = str(idx)
                item_by_request_id[request_id] = item
                requests_payload.append({
                    "id": request_id,
                    "method": "POST",
                    "url": "/me/events",
                    "headers": {"Content-Type": "application/json"},
                    "body": item["body"],
                })

            def attempt():
                token = self._ensure_access_token()
                return requests.post(
                    url,
                    headers=self._graph_headers(token),
                    json={"requests": requests_payload},
                    timeout=30,
                )

            response = attempt()
            if response.status_code == 401 and self.refresh_token:
                self.access_token = None
                response = attempt()

            if response.status_code >= 400:
                raise RuntimeError(f"Graph batch create events failed: HTTP {response.status_code}")

            for result in response.json().get("responses", []):
                request_id = str(result.get("id"))
                status = int(result.get("status", 0) or 0)
                if status < 200 or status >= 300:
                    print(f"Graph batch create event failed: {result}")
                    continue

                item = item_by_request_id.get(request_id)
                body = result.get("body") or {}
                if not item or not body.get("id"):
                    continue

                created_events.append({
                    "class_id": item["class_id"],
                    "provider_event_id": body["id"],
                    "etag": body.get("@odata.etag"),
                })

        return created_events

    def update_event(self, **payload):
        event_id = payload.get("provider_event_id")
        if not event_id:
            raise ValueError("Missing provider event id")

        start_str, end_str, tz = expand_times(payload)
        title    = fully_decode(payload.get("title", "") or "")
        location = fully_decode(payload.get("location", "") or "")
        class_url = app.config["CLASSFIT_URL"] + "class/" + str(payload.get("class_id"))

        patch = {
            "subject": title,
            "body": {"contentType": "HTML", "content": "Link: " + class_url},
            "start": {"dateTime": start_str, "timeZone": tz},
            "end":   {"dateTime": end_str,   "timeZone": tz},
            "location": {"displayName": location} if location else None,
        }
        patch = {k: v for k, v in patch.items() if v is not None}
        encoded_event_id = quote(str(event_id), safe="")
        updated = self._graph_write("PATCH", f"/me/events/{encoded_event_id}", patch)
        return updated["id"], updated.get("@odata.etag")

    def delete_event(self, provider_event_id: str):
        if not provider_event_id:
            raise ValueError("Missing provider event id")
        encoded_event_id = quote(str(provider_event_id), safe="")
        self._graph_write("DELETE", f"/me/events/{encoded_event_id}")
        return True

    def delete_events_batch(self, event_ids: list):
        if not event_ids:
            return True

        failures = []
        url = app.config["MS_GRAPH_BASE"] + "/$batch"

        for start in range(0, len(event_ids), 10):
            chunk = event_ids[start:start + 10]
            requests_payload = []
            event_by_request_id = {}

            for idx, event_id in enumerate(chunk):
                request_id = str(idx)
                event_by_request_id[request_id] = event_id
                encoded_event_id = quote(str(event_id), safe="")
                requests_payload.append({
                    "id": request_id,
                    "method": "DELETE",
                    "url": f"/me/events/{encoded_event_id}",
                })

            def attempt():
                token = self._ensure_access_token()
                return requests.post(
                    url,
                    headers=self._graph_headers(token),
                    json={"requests": requests_payload},
                    timeout=30,
                )

            response = attempt()
            if response.status_code == 401 and self.refresh_token:
                self.access_token = None
                response = attempt()

            if response.status_code >= 400:
                raise RuntimeError(f"Graph batch delete events failed: HTTP {response.status_code}")

            for result in response.json().get("responses", []):
                request_id = str(result.get("id"))
                status = int(result.get("status", 0) or 0)
                event_id = event_by_request_id.get(request_id)
                if status in (404, 410):
                    continue
                if status < 200 or status >= 300:
                    failures.append(str(event_id))

        if failures:
            raise RuntimeError(f"Graph batch delete failed for {len(failures)} Outlook event(s)")
        return True

    def has_active(self, role=None, organizer_id=None):
        if role == "instructor" and organizer_id is not None:
            return Calendar().provider_link_exists_active(self.user_id, "outlook", "instructor", int(organizer_id))
        return Calendar().has_active_connection(self.user_id, "outlook")

    def revoke(self, role: str = None, organizer_id: int = None, connection_id: int = None):
        cal = Calendar()

        if connection_id:
            cal.mark_connection_revoked_by_id(connection_id)
            cal.provider_link_revoke_by_connection(connection_id)
            return True

        if role == "instructor" and organizer_id is not None:
            cal.provider_link_revoke(self.user_id, "outlook", "instructor", int(organizer_id))
            return True

        cal.mark_connection_revoked(self.user_id, "outlook")
        return True
