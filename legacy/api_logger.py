"""Capture backend API calls made by a Playwright page and export to Excel.

Attach this to any Playwright `Page` to record every network call the site
makes: method, URL, request headers/cookies, request payload, response
status, response headers/set-cookie, response body, timing, and which
automation "phase" was executing when the call fired.

This module is tuned to also support **bot-detection analysis**:
    - Captures `document` and `script` resource types (not just xhr/fetch),
      since bot-mitigation SDKs are usually loaded as <script> tags and
      session-tagging cookies are usually set on the main document response.
    - Extracts Cookie / Set-Cookie explicitly instead of leaving them buried
      inside a raw headers blob.
    - Reports binary POST payload sizes instead of silently showing "".
    - Auto-generates a "Bot Detection Signals" sheet that flags known
      bot-mitigation / fraud / behavioral-analytics vendors by matching
      hostnames, headers, cookies, and body content against known
      signatures, and separately flags any non-2xx/3xx response.
    - Supports periodic cookie-jar snapshots (`snapshot_cookies`) written to
      a "Cookie Timeline" sheet, since bot-mitigation vendors identify
      sessions primarily via cookies (e.g. PerimeterX `_px*`, Akamai
      `_abck`/`bm_sz`/`ak_bmsc`, DataDome, Cloudflare `__cf_bm`).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# Resource types captured. xhr/fetch are the actual backend "API calls";
# document/script/ping are included specifically because bot-mitigation
# vendors ship as <script> SDKs, tag sessions via cookies set on the main
# document response, and sometimes report telemetry via sendBeacon (ping).
# Static assets (image/font/stylesheet/media) stay excluded as noise.
API_RESOURCE_TYPES = {"xhr", "fetch", "document", "script", "ping", "websocket"}

MAX_CELL_CHARS = 30_000

# XML 1.0 only allows: Tab, LF, CR, U+0020-U+D7FF, U+E000-U+FFFD, and
# U+10000-U+10FFFF. Anything else (C0 controls, lone surrogates
# U+D800-U+DFFF, and the U+FFFE/U+FFFF noncharacters) breaks openpyxl's
# generated XML even though openpyxl itself only checks for a subset of
# these. Script/document response bodies are especially likely to contain
# such bytes, so strip everything outside the valid range rather than
# trying to enumerate every invalid one.
_ILLEGAL_CHARS_RE = re.compile(
    "[^\u0009\u000A\u000D\u0020-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]"
)
_TEXTUAL_CONTENT_TYPES = ("json", "text", "xml", "javascript", "html", "csv")

# Known bot-mitigation / fraud / behavioral-analytics vendor signatures.
# Matched (case-insensitively) against host, URL, headers, and cookie names.
VENDOR_SIGNATURES = {
    "PerimeterX / HUMAN Security": ["_px", "perimeterx", "px-cdn", "pxhd", "pxvid", "px_domain_data"],
    "Akamai Bot Manager": ["akamai", "_abck", "bm_sz", "ak_bmsc", "akamai-grn"],
    "DataDome": ["datadome"],
    "Cloudflare Bot Management": ["cf-ray", "cf_clearance", "__cf_bm", "cloudflare"],
    "Imperva / Incapsula": ["incap_ses", "visid_incap", "incapsula"],
    "Kasada": ["kasada", "x-kpsdk"],
    "Arkose Labs": ["arkose", "funcaptcha"],
    "Google reCAPTCHA": ["recaptcha", "g-recaptcha"],
    "hCaptcha": ["hcaptcha"],
    "Quantum Metric (session replay / behavioral)": ["quantummetric"],
    "Adobe Experience Platform (analytics/personalization)": ["sanalytics", "demdex", "alloy", "adobedc"],
}

# Cookie-name substrings worth flagging even outside VENDOR_SIGNATURES scan.
KNOWN_BOT_COOKIE_HINTS = [
    "_px", "pxvid", "pxhd", "_abck", "bm_sz", "ak_bmsc", "datadome",
    "__cf_bm", "cf_clearance", "incap_ses", "visid_incap", "qmid",
    "quantummetricsessionid",
]

# One pastel fill color per vendor, reused consistently across the "API
# Calls", "Bot Detection Signals", and "Cookie Timeline" sheets so a color
# always means the same vendor everywhere in the workbook. Red/pink tones
# are intentionally avoided here since red is reserved for errors /
# critical flags (see ERROR_FILL_COLOR / CRITICAL_FILL_COLOR below).
VENDOR_COLORS = {
    "PerimeterX / HUMAN Security": "D0BFFF",
    "Akamai Bot Manager": "FFD8A8",
    "DataDome": "FFEC99",
    "Cloudflare Bot Management": "99E9F2",
    "Imperva / Incapsula": "EEBEFA",
    "Kasada": "D8F5A2",
    "Arkose Labs": "BAC8FF",
    "Google reCAPTCHA": "96F2D7",
    "hCaptcha": "B2F2BB",
    "Quantum Metric (session replay / behavioral)": "A5D8FF",
    "Adobe Experience Platform (analytics/personalization)": "C3FAE8",
}

ERROR_FILL_COLOR = "FFC7CE"  # HTTP 4xx/5xx response
CRITICAL_FILL_COLOR = "FF8787"  # e.g. Akamai sensor-validation flag stuck at -1


def _record_vendor_matches(record: "ApiCallRecord") -> list[str]:
    """Which known vendors' signatures this call's host/url/headers/cookies match."""
    blob = " ".join(
        [
            record.host, record.url, record.request_headers,
            record.request_cookies, record.response_headers,
            record.response_set_cookie,
        ]
    ).lower()
    return [
        vendor
        for vendor, sigs in VENDOR_SIGNATURES.items()
        if _matches_any(blob, [s.lower() for s in sigs])
    ]


def _cookie_note(name: str, value: str) -> str:
    """Human-readable annotation for a cookie snapshot row, when we know one."""
    name_lower = (name or "").lower()
    if name_lower == "_abck":
        parts = (value or "").split("~")
        flag = parts[1] if len(parts) > 1 else ""
        if flag == "-1":
            return "Sensor validation NOT passed (flag=-1) — Akamai has not validated a trusted sensor payload for this session"
        if flag == "0":
            return "Sensor validation passed (flag=0)"
        if flag:
            return f"Sensor validation flag={flag}"
    if name_lower in ("bm_sz", "ak_bmsc"):
        return "Akamai sensor/session telemetry cookie (opaque)"
    if name_lower in ("quantummetricsessionid", "quantummetricuserid", "qmid"):
        return "Quantum Metric session/user tracking ID"
    if name_lower == "demdex":
        return "Adobe Audience Manager cross-site visitor ID"
    return ""


_KNOWN_PATH_PREFIXES = {
    "www.verizon.com": (
        "home", "inhome", "soe", "5g", "content", "etc.clientlibs",
        "sales", "digital", "foryourhome",
    ),
    "frontier.com": (
        "shop", "buy", "why-frontier", "resources", "helpcenter",
        "api", "content", "assets", "static",
    ),
}

_SENSOR_HOSTS = {"www.verizon.com", "frontier.com", "www.frontier.com"}


def _is_randomized_sensor_path(url: str, host: str) -> bool:
    """Detect Akamai's randomized first-party sensor endpoint pattern.

    These paths have 4+ segments, don't start with known application
    prefixes, and contain at least one long random-looking segment (>7
    chars). The path pattern rotates per session — e.g. /QfNarR/B/w/...
    or /pLyzf2eie/cwKW1cy/J8lDDXP/... — so we identify them structurally.

    Now supports both Verizon and Frontier hosts.
    """
    normalized_host = host.replace("www.", "") if host.startswith("www.") else host
    check_host = host if host in _SENSOR_HOSTS else None
    if not check_host:
        for sh in _SENSOR_HOSTS:
            if normalized_host == sh.replace("www.", ""):
                check_host = sh
                break
    if not check_host:
        return False

    try:
        path = url.split(host + "/", 1)[-1].split("?")[0]
    except IndexError:
        return False
    segments = path.split("/")
    if len(segments) < 4:
        return False

    known = _KNOWN_PATH_PREFIXES.get(host) or _KNOWN_PATH_PREFIXES.get(normalized_host, ())
    if known and path.lower().startswith(known):
        return False

    return any(len(s) > 7 for s in segments)


def _extract_abck_flag(cookies_str: str) -> str:
    """Parse the _abck validation flag from a request cookie header string."""
    if "_abck=" not in cookies_str:
        return ""
    for part in cookies_str.split(";"):
        part = part.strip()
        if part.startswith("_abck="):
            val = part[6:]
            fields = val.split("~")
            return fields[1] if len(fields) > 1 else ""
    return ""


def _assess_bot_signal(record: "ApiCallRecord") -> tuple[str, str, str]:
    """Classify a single network call's role in bot detection.

    Returns (signal_type, signal_level, detection_feedback).
    """
    signal_type = "None"
    signal_level = "None"
    feedbacks: list[str] = []

    host = (record.host or "").lower()
    url = record.url or ""
    method = record.method or ""
    status = record.status
    req_cookies = record.request_cookies or ""
    resp_set_cookie = record.response_set_cookie or ""

    # --- Rule 1 & 2: Akamai randomized sensor endpoint ---
    if _is_randomized_sensor_path(url, record.host or ""):
        if method == "GET":
            signal_type = "Akamai sensor script load"
            signal_level = "High"
            feedbacks.append("Obfuscated JS sensor served from randomized first-party path")
        else:
            signal_type = "Akamai sensor data submission"
            signal_level = "High"
            if status == 201:
                feedbacks.append("201 Created — sensor data accepted")
            elif status == 202:
                feedbacks.append("202 Accepted — async sensor processing (queued)")
            elif status == 200:
                feedbacks.append("200 OK — sensor data processed")
            else:
                feedbacks.append(f"Status {status}")

    # --- Rule 3: PerimeterX / HUMAN-style identity beacon ---
    elif host == "sv.verizon.com":
        if "trackidentity" in url.lower():
            signal_type = "Device fingerprint beacon"
            signal_level = "High"
            if status == 403:
                feedbacks.append("HTTP 403 — actively blocked/rejected by server")
            elif status == 200:
                feedbacks.append("200 OK — fingerprint accepted")
            else:
                feedbacks.append(f"Status {status}")
        elif "tptracking" in url.lower():
            signal_type = "Tracking script loader (sv.verizon.com)"
            signal_level = "High"
            feedbacks.append("Third-party tracking JS loader via PerimeterX-style proxy")
        elif "citecapture" in url.lower():
            signal_type = "Page-view capture event"
            signal_level = "Medium"
            feedbacks.append("Site/cite-capture viewpage event")
        else:
            signal_type = "PerimeterX-style tracking"
            signal_level = "Medium"

    # --- Rule 4: Quantum Metric ---
    elif "quantummetric" in host:
        if "ingest" in host:
            signal_type = "Behavioral telemetry (session replay ingest)"
            signal_level = "High"
            feedbacks.append("Session replay / interaction data streamed to QM ingest")
        else:
            signal_type = "Behavioral SDK load (Quantum Metric CDN)"
            signal_level = "Medium"
            feedbacks.append("QM SDK or network-interceptor script loaded")

    # --- Rule 5: Adobe identity / analytics ---
    elif host in ("sanalytics.verizon.com", "adobedc.demdex.net"):
        signal_type = "Identity resolution (Adobe)"
        signal_level = "Medium"
        if "demdex" in host:
            feedbacks.append("Adobe Audience Manager cross-site identity sync")
        else:
            feedbacks.append("Adobe Alloy/Edge analytics + identity")

    # --- Rule 8: Other vendor matches → Low ---
    else:
        vendors = _record_vendor_matches(record)
        if vendors:
            signal_type = f"Vendor-matched traffic ({vendors[0]})"
            signal_level = "Low"
        # Known ad-tech that could feed signals indirectly
        elif any(k in host for k in ("evolv.ai", "newrelic", "liveperson")):
            signal_type = "Analytics/optimization (indirect signal source)"
            signal_level = "Low"

    # --- Rule 6: Request carries _abck cookie ---
    abck_flag = _extract_abck_flag(req_cookies)
    if abck_flag:
        flag_desc = "unvalidated" if abck_flag == "-1" else ("validated" if abck_flag == "0" else f"flag={abck_flag}")
        feedbacks.append(f"Request carries _abck ({flag_desc})")
        if signal_level == "None":
            signal_level = "Medium"
            signal_type = signal_type if signal_type != "None" else "Bot-cookie-carrying request"

    # --- Rule 7: Response sets bot-detection cookies ---
    set_cookie_lower = resp_set_cookie.lower()
    for cookie_name in ("_abck", "bm_sz", "ak_bmsc"):
        if cookie_name in set_cookie_lower:
            feedbacks.append(f"Server set/rotated cookie: {cookie_name}")
            if signal_level in ("None", "Low"):
                signal_level = "Medium"
                if signal_type == "None" or signal_type.startswith("Vendor-matched"):
                    signal_type = "Bot-cookie-setting response"

    # --- HTTP error as feedback ---
    if isinstance(status, int) and status >= 400 and not any("403" in f or "blocked" in f for f in feedbacks):
        feedbacks.append(f"HTTP {status} — possible rejection")

    feedback_str = "; ".join(feedbacks) if feedbacks else "No observable feedback"
    return signal_type, signal_level, feedback_str


def _pretty(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = json.loads(value)
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return value


def _sanitize(value: str) -> str:
    if not value:
        return value
    return _ILLEGAL_CHARS_RE.sub("", value)


def _truncate(value: str) -> str:
    if value and len(value) > MAX_CELL_CHARS:
        return value[:MAX_CELL_CHARS] + f"\n...[truncated, {len(value)} total chars]"
    return value


def _clean(value: str) -> str:
    return _truncate(_sanitize(value or ""))


def _matches_any(text: str, needles: list[str]) -> bool:
    text = (text or "").lower()
    return any(n in text for n in needles)


@dataclass
class ApiCallRecord:
    index: int
    timestamp: str
    phase: str
    method: str
    resource_type: str
    host: str
    url: str
    request_headers: str
    request_cookies: str
    request_payload: str
    status: int
    status_text: str
    response_headers: str
    response_set_cookie: str
    response_body: str
    duration_ms: str


@dataclass
class CookieSnapshotRow:
    label: str
    name: str
    value: str
    domain: str
    path: str
    http_only: bool
    secure: bool
    same_site: str
    vendor_guess: str


@dataclass
class SensorEvent:
    """One sensor POST submission and the _abck state before/after."""
    timestamp: str
    phase: str
    url: str
    method: str
    payload_size: int
    status: int
    abck_before: str
    abck_after: str
    abck_flag_before: str
    abck_flag_after: str
    flipped: bool


class ApiLogger:
    """Listens on a Playwright page and records every network call."""

    def __init__(self, resource_types: set[str] | None = None):
        self.resource_types = resource_types or API_RESOURCE_TYPES
        self.records: list[ApiCallRecord] = []
        self.cookie_snapshots: list[CookieSnapshotRow] = []
        self.sensor_events: list[SensorEvent] = []
        self._start_times: dict[int, float] = {}
        self._counter = 0
        self.current_phase = "startup"
        self._last_abck: str = ""
        self._last_abck_flag: str = ""

    def set_phase(self, phase: str) -> None:
        """Tag subsequent captured calls with the current automation step."""
        self.current_phase = phase

    def attach(self, page) -> None:
        page.on("request", self._on_request)
        page.on("response", self._on_response)

    def _track_abck_from_cookies(self, cookie_str: str) -> tuple[str, str]:
        """Extract current _abck value and flag from a cookie string."""
        if "_abck=" not in cookie_str:
            return self._last_abck, self._last_abck_flag
        for part in cookie_str.split(";"):
            part = part.strip()
            if part.startswith("_abck="):
                val = part[6:]
                fields = val.split("~")
                flag = fields[1] if len(fields) > 1 else ""
                self._last_abck = val[:80]
                self._last_abck_flag = flag
                return val[:80], flag
        return self._last_abck, self._last_abck_flag

    def _track_sensor_event(self, request, response) -> None:
        """Record sensor POST with _abck state before and after."""
        url = request.url or ""
        host = urlparse(url).netloc
        if not (_is_randomized_sensor_path(url, host) and request.method == "POST"):
            return

        req_cookies = ""
        try:
            req_cookies = dict(request.headers).get("cookie", "")
        except Exception:
            pass
        abck_before, flag_before = self._track_abck_from_cookies(req_cookies)

        resp_set_cookie = ""
        try:
            header_pairs = response.headers_array()
            resp_set_cookie = "\n".join(
                h["value"] for h in header_pairs if h["name"].lower() == "set-cookie"
            )
        except Exception:
            try:
                resp_set_cookie = dict(response.headers).get("set-cookie", "")
            except Exception:
                pass

        abck_after, flag_after = abck_before, flag_before
        if "_abck=" in resp_set_cookie:
            for line in resp_set_cookie.split("\n"):
                if "_abck=" in line:
                    val = line.split("_abck=", 1)[1].split(";")[0]
                    fields = val.split("~")
                    flag_after = fields[1] if len(fields) > 1 else ""
                    abck_after = val[:80]
                    self._last_abck = abck_after
                    self._last_abck_flag = flag_after
                    break

        payload_size = 0
        try:
            buf = request.post_data_buffer
            if buf:
                payload_size = len(buf)
        except Exception:
            try:
                pd = request.post_data
                if pd:
                    payload_size = len(pd)
            except Exception:
                pass

        self.sensor_events.append(SensorEvent(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            phase=self.current_phase,
            url=url[:200],
            method=request.method,
            payload_size=payload_size,
            status=response.status,
            abck_before=abck_before,
            abck_after=abck_after,
            abck_flag_before=flag_before,
            abck_flag_after=flag_after,
            flipped=(flag_before == "-1" and flag_after == "0"),
        ))

    def _on_request(self, request) -> None:
        if request.resource_type in self.resource_types:
            self._start_times[id(request)] = time.time()

    def _extract_request_payload(self, request) -> str:
        try:
            text_payload = request.post_data
        except Exception:
            text_payload = None
        if text_payload:
            return _pretty(text_payload)

        try:
            buffer = request.post_data_buffer
        except Exception:
            buffer = None
        if buffer:
            return f"<binary/non-text payload, {len(buffer)} bytes>"
        return ""

    def _on_response(self, response) -> None:
        request = response.request
        if request.resource_type not in self.resource_types:
            return

        started = self._start_times.pop(id(request), None)
        duration_ms = f"{(time.time() - started) * 1000:.0f}" if started else ""

        try:
            req_headers_dict = dict(request.headers)
        except Exception:
            req_headers_dict = {}
        req_cookies = req_headers_dict.get("cookie", "")
        try:
            req_headers = json.dumps(req_headers_dict, indent=2)
        except Exception:
            req_headers = ""

        req_payload = self._extract_request_payload(request)

        try:
            resp_headers_dict = dict(response.headers)
        except Exception:
            resp_headers_dict = {}
        try:
            resp_headers = json.dumps(resp_headers_dict, indent=2)
        except Exception:
            resp_headers = ""

        set_cookie = ""
        try:
            header_pairs = response.headers_array()
            set_cookies = [h["value"] for h in header_pairs if h["name"].lower() == "set-cookie"]
            set_cookie = "\n".join(set_cookies)
        except Exception:
            set_cookie = resp_headers_dict.get("set-cookie", "")

        content_type = resp_headers_dict.get("content-type", "").lower()
        if content_type and not any(t in content_type for t in _TEXTUAL_CONTENT_TYPES):
            resp_body = f"<binary content, content-type: {content_type}>"
        else:
            try:
                resp_body = response.text()
            except Exception:
                resp_body = "<binary or unavailable>"

        self._track_sensor_event(request, response)

        self._counter += 1
        parsed_url = urlparse(request.url)

        self.records.append(
            ApiCallRecord(
                index=self._counter,
                timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                phase=self.current_phase,
                method=request.method,
                resource_type=request.resource_type,
                host=parsed_url.netloc,
                url=_clean(request.url),
                request_headers=_clean(req_headers),
                request_cookies=_clean(req_cookies),
                request_payload=_clean(req_payload),
                status=response.status,
                status_text=_clean(response.status_text),
                response_headers=_clean(resp_headers),
                response_set_cookie=_clean(set_cookie),
                response_body=_clean(_pretty(resp_body)),
                duration_ms=duration_ms,
            )
        )

    def snapshot_cookies(self, context, label: str) -> None:
        """Record the full cookie jar at a named checkpoint in the flow."""
        try:
            cookies = context.cookies()
        except Exception:
            cookies = []
        for c in cookies:
            name_lower = (c.get("name") or "").lower()
            vendor_guess = ""
            for vendor, sigs in VENDOR_SIGNATURES.items():
                if _matches_any(name_lower, [s.lower() for s in sigs]):
                    vendor_guess = vendor
                    break
            if not vendor_guess and _matches_any(name_lower, KNOWN_BOT_COOKIE_HINTS):
                vendor_guess = "Unclassified bot/fraud-signal cookie"

            self.cookie_snapshots.append(
                CookieSnapshotRow(
                    label=label,
                    name=c.get("name", ""),
                    value=_clean(str(c.get("value", ""))),
                    domain=c.get("domain", ""),
                    path=c.get("path", ""),
                    http_only=c.get("httpOnly", False),
                    secure=c.get("secure", False),
                    same_site=c.get("sameSite", ""),
                    vendor_guess=vendor_guess,
                )
            )

    # ------------------------------------------------------------------
    # Excel export
    # ------------------------------------------------------------------

    def _style_header(self, ws, headers: list[str]) -> None:
        header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(vertical="center", horizontal="center")
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}1"

    def _write_api_calls_sheet(self, wb: Workbook) -> None:
        ws = wb.active
        ws.title = "API Calls"
        headers = [
            "#", "Timestamp", "Phase", "Method", "Type", "Host",
            "Bot/Fraud Vendor Match", "Signal Type", "Signal Level",
            "Detection Feedback", "URL",
            "Request Headers", "Request Cookies", "Request Payload",
            "Status", "Status Text", "Response Headers", "Response Set-Cookie",
            "Response Body", "Duration (ms)",
        ]
        ws.append(headers)
        self._style_header(ws, headers)

        error_fill = PatternFill(start_color=ERROR_FILL_COLOR, end_color=ERROR_FILL_COLOR, fill_type="solid")
        vendor_fills = {
            vendor: PatternFill(start_color=color, end_color=color, fill_type="solid")
            for vendor, color in VENDOR_COLORS.items()
        }
        high_signal_font = Font(bold=True)
        wrap_alignment = Alignment(wrap_text=True, vertical="top")

        for record in self.records:
            vendor_matches = _record_vendor_matches(record)
            signal_type, signal_level, detection_feedback = _assess_bot_signal(record)
            ws.append([
                record.index, record.timestamp, record.phase, record.method,
                record.resource_type, record.host, ", ".join(vendor_matches),
                signal_type, signal_level, detection_feedback, record.url,
                record.request_headers, record.request_cookies, record.request_payload,
                record.status, record.status_text, record.response_headers,
                record.response_set_cookie, record.response_body, record.duration_ms,
            ])
            row_idx = ws.max_row
            is_error = isinstance(record.status, int) and record.status >= 400
            if is_error:
                fill = error_fill
            elif vendor_matches:
                fill = vendor_fills.get(vendor_matches[0])
            else:
                fill = None
            if fill:
                for col_idx in range(1, len(headers) + 1):
                    ws.cell(row=row_idx, column=col_idx).fill = fill
            if signal_level == "High":
                for col_idx in (8, 9, 10):  # Signal Type, Level, Feedback
                    ws.cell(row=row_idx, column=col_idx).font = high_signal_font

        for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
            for cell in row:
                cell.alignment = wrap_alignment

        column_widths = {
            "A": 5, "B": 14, "C": 16, "D": 8, "E": 10, "F": 22, "G": 26,
            "H": 28, "I": 12, "J": 48, "K": 42,
            "L": 35, "M": 30, "N": 40, "O": 8, "P": 12, "Q": 35, "R": 30,
            "S": 50, "T": 12,
        }
        for col_letter, width in column_widths.items():
            ws.column_dimensions[col_letter].width = width

    def _write_cookie_timeline_sheet(self, wb: Workbook) -> None:
        ws = wb.create_sheet("Cookie Timeline")
        headers = ["Label", "Cookie Name", "Value", "Domain", "Path",
                   "HttpOnly", "Secure", "SameSite", "Vendor Guess", "Notes"]
        ws.append(headers)
        self._style_header(ws, headers)

        flagged_fill = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
        critical_fill = PatternFill(start_color=CRITICAL_FILL_COLOR, end_color=CRITICAL_FILL_COLOR, fill_type="solid")
        wrap_alignment = Alignment(wrap_text=True, vertical="top")
        bold_font = Font(bold=True)

        for row in self.cookie_snapshots:
            note = _cookie_note(row.name, row.value)
            ws.append([
                row.label, row.name, row.value, row.domain, row.path,
                row.http_only, row.secure, row.same_site, row.vendor_guess, note,
            ])
            is_critical = "NOT passed" in note
            if is_critical:
                fill = critical_fill
            elif row.vendor_guess:
                fill = flagged_fill
            else:
                fill = None
            if fill:
                for col_idx in range(1, len(headers) + 1):
                    cell = ws.cell(row=ws.max_row, column=col_idx)
                    cell.fill = fill
                    if is_critical:
                        cell.font = bold_font

        for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
            for cell in row:
                cell.alignment = wrap_alignment

        widths = {"A": 20, "B": 28, "C": 40, "D": 24, "E": 10,
                  "F": 10, "G": 10, "H": 10, "I": 34, "J": 55}
        for col_letter, width in widths.items():
            ws.column_dimensions[col_letter].width = width

    def _write_bot_signals_sheet(self, wb: Workbook) -> None:
        ws = wb.create_sheet("Bot Detection Signals")
        headers = ["Vendor / Signal", "Matched On", "Call Count", "Hosts",
                   "Error Responses (4xx/5xx)", "Sample URL"]
        ws.append(headers)
        self._style_header(ws, headers)

        wrap_alignment = Alignment(wrap_text=True, vertical="top")
        error_fill = PatternFill(start_color=ERROR_FILL_COLOR, end_color=ERROR_FILL_COLOR, fill_type="solid")
        vendor_fills = {
            vendor: PatternFill(start_color=color, end_color=color, fill_type="solid")
            for vendor, color in VENDOR_COLORS.items()
        }

        for vendor, sigs in VENDOR_SIGNATURES.items():
            matches = [r for r in self.records if vendor in _record_vendor_matches(r)]

            # Also check cookie-jar snapshots for this vendor.
            cookie_hits = [c for c in self.cookie_snapshots if c.vendor_guess == vendor]

            if not matches and not cookie_hits:
                continue

            hosts = sorted({m.host for m in matches}) or sorted({"(cookie only)"})
            error_records = [m for m in matches if isinstance(m.status, int) and m.status >= 400]
            error_summary = "; ".join(
                f"{m.status} {m.url[:80]}" for m in error_records[:5]
            )
            if len(error_records) > 5:
                error_summary += f" ... (+{len(error_records) - 5} more)"

            sample_url = matches[0].url[:200] if matches else (cookie_hits[0].name if cookie_hits else "")

            ws.append([
                vendor,
                ", ".join(sigs),
                len(matches) + (len(cookie_hits) if not matches else 0),
                ", ".join(hosts),
                error_summary,
                sample_url,
            ])
            # Base row fill is this vendor's color (matches "API Calls" sheet);
            # errors get the stronger red fill instead so they still stand out.
            fill = error_fill if error_records else vendor_fills.get(vendor)
            if fill:
                for col_idx in range(1, len(headers) + 1):
                    ws.cell(row=ws.max_row, column=col_idx).fill = fill

        # Also list any non-2xx/3xx response regardless of vendor match.
        ws.append([])
        ws.append(["All non-2xx/3xx responses (any host)"])
        ws.append(["Host", "Status", "URL", "Phase"])
        header_row = ws.max_row
        for col_idx in range(1, 5):
            ws.cell(row=header_row, column=col_idx).font = Font(bold=True)

        for record in self.records:
            if isinstance(record.status, int) and record.status >= 400:
                ws.append([record.host, record.status, record.url, record.phase])
                for col_idx in range(1, 5):
                    ws.cell(row=ws.max_row, column=col_idx).fill = error_fill

        # Color legend, so the fills used across this sheet, "API Calls", and
        # "Cookie Timeline" are self-explanatory without needing this chat.
        ws.append([])
        ws.append(["Color Legend"])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
        ws.append(["Fill color shown on", "Meaning"])
        legend_header_row = ws.max_row
        for col_idx in (1, 2):
            ws.cell(row=legend_header_row, column=col_idx).font = Font(bold=True)
        for vendor, fill_color in VENDOR_COLORS.items():
            ws.append([vendor, "Rows in 'API Calls' / this sheet matching this vendor's signature"])
            ws.cell(row=ws.max_row, column=1).fill = PatternFill(
                start_color=fill_color, end_color=fill_color, fill_type="solid"
            )
        ws.append(["(red)", "HTTP 4xx/5xx error response"])
        ws.cell(row=ws.max_row, column=1).fill = error_fill
        ws.append(["(darker red, bold)", "Cookie Timeline only: Akamai _abck sensor-validation flag stuck at -1 (not validated)"])
        ws.cell(row=ws.max_row, column=1).fill = PatternFill(
            start_color=CRITICAL_FILL_COLOR, end_color=CRITICAL_FILL_COLOR, fill_type="solid"
        )
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True)

        for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
            for cell in row:
                cell.alignment = wrap_alignment

        widths = {"A": 40, "B": 45, "C": 12, "D": 30, "E": 60, "F": 60}
        for col_letter, width in widths.items():
            ws.column_dimensions[col_letter].width = width

    def _write_sensor_tracker_sheet(self, wb: Workbook) -> None:
        """Sheet tracking every Akamai sensor POST and _abck state changes."""
        if not self.sensor_events:
            return
        ws = wb.create_sheet("Sensor Tracker")
        headers = [
            "Timestamp", "Phase", "URL", "Method", "Payload Size",
            "Status", "_abck Flag Before", "_abck Flag After", "Flipped?",
            "_abck Value Before", "_abck Value After",
        ]
        ws.append(headers)
        self._style_header(ws, headers)

        ok_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
        fail_fill = PatternFill(start_color=CRITICAL_FILL_COLOR,
                                end_color=CRITICAL_FILL_COLOR, fill_type="solid")
        wrap = Alignment(wrap_text=True, vertical="top")

        for ev in self.sensor_events:
            ws.append([
                ev.timestamp, ev.phase, ev.url, ev.method, ev.payload_size,
                ev.status, ev.abck_flag_before, ev.abck_flag_after,
                "YES ✓" if ev.flipped else "NO",
                ev.abck_before, ev.abck_after,
            ])
            fill = ok_fill if ev.flipped else fail_fill
            for col_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=ws.max_row, column=col_idx)
                cell.fill = fill
                cell.alignment = wrap
            if ev.flipped:
                ws.cell(row=ws.max_row, column=9).font = Font(bold=True, color="006100")
            else:
                ws.cell(row=ws.max_row, column=9).font = Font(bold=True, color="9C0006")

        widths = {"A": 18, "B": 20, "C": 50, "D": 8, "E": 14,
                  "F": 8, "G": 16, "H": 16, "I": 10, "J": 40, "K": 40}
        for col_letter, width in widths.items():
            ws.column_dimensions[col_letter].width = width

    def save_to_excel(self, path: str) -> None:
        wb = Workbook()
        self._write_api_calls_sheet(wb)
        self._write_bot_signals_sheet(wb)
        self._write_cookie_timeline_sheet(wb)
        self._write_sensor_tracker_sheet(wb)
        wb.save(path)
        sensor_note = ""
        if self.sensor_events:
            flipped = sum(1 for e in self.sensor_events if e.flipped)
            sensor_note = f", {len(self.sensor_events)} sensor POST(s) ({flipped} flipped _abck)"
        print(
            f"\nLogged {len(self.records)} network call(s), "
            f"{len(self.cookie_snapshots)} cookie snapshot row(s){sensor_note} to {path}"
        )
