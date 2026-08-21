from datetime import datetime, timedelta
from urllib.parse import unquote, unquote_plus, urlparse


def fully_decode(string: str) -> str:
    """
    Repeatedly unquote until no %xx left,
    then convert + to space as well.
    """
    if string is None:
        return ""

    prev = None
    cur = string
    while cur != prev:
        prev = cur
        cur = unquote(cur)

    return unquote_plus(cur)


def ics_escape(s: str):
    if not s:
        return ""
    return s.replace("\\", "\\\\").replace(";", r"\;").replace(",", r"\,").replace("\n", r"\n")


def normalize_origin(raw):
    """Validate and preserve the complete return URL supplied by the frontend.
    Returns None unless it is HTTPS (HTTP is allowed only for localhost).
    """
    if not raw or not isinstance(raw, str):
        return None
    return_url = raw.strip()
    try:
        p = urlparse(return_url)
    except Exception:
        return None
    if not p.scheme or not p.hostname:
        return None
    scheme = p.scheme.lower()
    host = p.hostname.lower()
    if scheme != "https" and host not in ("localhost", "127.0.0.1"):
        return None
    return return_url


def expand_times(payload):
    """
    Normalize times:
    - If payload provides start/end/timezone -> use them.
    - Else fallback to gm_utc_datetime + gm_end_time with 'UTC'.
    Returns (start_str, end_str, tz_name) in ISO 'YYYY-mm-ddTHH:MM:SS'.
    """
    tz = fully_decode(payload.get("timezone") or payload.get("TimeZone") or "")
    start = fully_decode(payload.get("start") or "")
    end = fully_decode(payload.get("end") or "")
    if start and end and tz:
        return start, end, tz

    start_dt = datetime.strptime(fully_decode(payload["gm_utc_datetime"]), "%Y-%m-%dT%H:%M:%S")
    end_dt = start_dt + timedelta(minutes=int(payload["gm_end_time"]))
    fmt = "%Y-%m-%dT%H:%M:%S"
    return start_dt.strftime(fmt), end_dt.strftime(fmt), "UTC"
