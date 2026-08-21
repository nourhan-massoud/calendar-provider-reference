import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class _FlaskAppStandIn:
    """Stand-in for Flask's current_app.

    Production providers do: from flask import current_app as app
    This reference does:     from app.config import current_app as app

    Config *keys* match backend-studios. Values come from the environment.
    """

    config = {}


current_app = _FlaskAppStandIn()


def _base_url() -> str:
    base = os.getenv("APP_BASE_URL", "http://localhost:8000/")
    if not base.endswith("/"):
        base += "/"
    return base


def load_config() -> None:
    base = _base_url()
    current_app.config.update(
        {
            "GOOGLE_CLIENT_ID": os.getenv("GOOGLE_CLIENT_ID", "your-google-client-id"),
            "GOOGLE_CLIENT_SECRET": os.getenv("GOOGLE_CLIENT_SECRET", "your-google-client-secret"),
            "GOOGLE_SCOPES": [
                "https://www.googleapis.com/auth/calendar.events",
                "https://www.googleapis.com/auth/userinfo.email",
                "openid",
            ],
            "MS_CLIENT_ID": os.getenv("MS_CLIENT_ID")
            or os.getenv("MICROSOFT_CLIENT_ID", "your-microsoft-client-id"),
            "MS_CLIENT_SECRET": os.getenv("MS_CLIENT_SECRET")
            or os.getenv("MICROSOFT_CLIENT_SECRET", "your-microsoft-client-secret"),
            "MS_TENANT": os.getenv("MS_TENANT", "common"),
            "MS_SCOPES": [
                "offline_access",
                "openid",
                "profile",
                "email",
                "User.Read",
                "Calendars.ReadWrite",
            ],
            "MS_AUTH_URI": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
            "MS_TOKEN_URI": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            "MS_GRAPH_BASE": "https://graph.microsoft.com/v1.0",
            "CLASSFIT_URL": os.getenv("CLASSFIT_URL", base),
            "BACKEND_BASE_URL": os.getenv("BACKEND_BASE_URL", base),
            "WIDGET_CALENDAR_CALLBACK_URL": os.getenv(
                "WIDGET_CALENDAR_CALLBACK_URL",
                base + "widget/google-callback.html",
            ),
        }
    )


load_config()
