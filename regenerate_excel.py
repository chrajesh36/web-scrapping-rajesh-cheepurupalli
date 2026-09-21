"""Re-export an already-captured api_calls_*.xlsx with the latest
api_logger.py logic (highlighting, signal columns, legend, etc.) without
re-running the browser automation against the live site.

Reads the existing "API Calls" and "Cookie Timeline" sheets regardless of
their column layout version, rebuilds ApiCallRecord / CookieSnapshotRow
objects, and calls ApiLogger.save_to_excel() to produce the newest format.
"""

from __future__ import annotations

import sys

import openpyxl

from api_logger import ApiCallRecord, ApiLogger, CookieSnapshotRow

# The core fields of ApiCallRecord, in the order expected by the dataclass.
_RECORD_FIELDS = [
    "index", "timestamp", "phase", "method", "resource_type", "host", "url",
    "request_headers", "request_cookies", "request_payload",
    "status", "status_text", "response_headers", "response_set_cookie",
    "response_body", "duration_ms",
]

# Map known header labels (from various layout versions) to field names.
_HEADER_TO_FIELD = {
    "#": "index",
    "Timestamp": "timestamp",
    "Phase": "phase",
    "Method": "method",
    "Type": "resource_type",
    "Host": "host",
    "URL": "url",
    "Request Headers": "request_headers",
    "Request Cookies": "request_cookies",
    "Request Payload": "request_payload",
    "Status": "status",
    "Status Text": "status_text",
    "Response Headers": "response_headers",
    "Response Set-Cookie": "response_set_cookie",
    "Response Body": "response_body",
    "Duration (ms)": "duration_ms",
}


def regenerate(src_path: str, dst_path: str) -> None:
    wb = openpyxl.load_workbook(src_path, data_only=True)
    logger = ApiLogger()

    calls_ws = wb["API Calls"]
    headers = [cell.value for cell in calls_ws[1]]

    # Build a mapping: field_name -> column index (0-based)
    col_map: dict[str, int] = {}
    for col_idx, header in enumerate(headers):
        field = _HEADER_TO_FIELD.get(header)
        if field:
            col_map[field] = col_idx

    for row in calls_ws.iter_rows(min_row=2, values_only=True):
        idx_col = col_map.get("index", 0)
        if row[idx_col] is None:
            continue
        kwargs = {}
        for field in _RECORD_FIELDS:
            ci = col_map.get(field)
            if ci is not None and ci < len(row):
                val = row[ci]
                kwargs[field] = val if val is not None else ""
            else:
                kwargs[field] = ""
        logger.records.append(ApiCallRecord(**kwargs))

    if "Cookie Timeline" in wb.sheetnames:
        cookie_ws = wb["Cookie Timeline"]
        for row in cookie_ws.iter_rows(min_row=2, values_only=True):
            if row[0] is None:
                continue
            label, name, value, domain, path, http_only, secure, same_site, vendor_guess = row[:9]
            logger.cookie_snapshots.append(
                CookieSnapshotRow(
                    label=label or "", name=name or "", value=value or "",
                    domain=domain or "", path=path or "",
                    http_only=bool(http_only), secure=bool(secure),
                    same_site=same_site or "", vendor_guess=vendor_guess or "",
                )
            )

    logger.save_to_excel(dst_path)


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "logs/api_calls_20260807_115452.xlsx"
    dst = sys.argv[2] if len(sys.argv) > 2 else src
    regenerate(src, dst)
