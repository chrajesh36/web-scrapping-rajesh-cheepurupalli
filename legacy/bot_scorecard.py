"""Extract a real-time bot detection scorecard from captured API logger data.

This module provides provider-agnostic, measurable metrics from the network
traffic captured during automation. Instead of just logging calls, it answers:
  "Was I detected? How badly? What gave me away?"

Usage:
    from bot_scorecard import BotScorecard
    scorecard = BotScorecard(api_logger)
    scorecard.print_report()
    scorecard.save_to_excel("scorecard.xlsx")
"""

from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


@dataclass
class ScorecardMetric:
    name: str
    value: str | int | float
    severity: str  # "critical", "warning", "ok", "info"
    explanation: str


@dataclass
class BotScorecard:
    """Analyze captured traffic and produce a measurable bot detection scorecard."""

    metrics: list[ScorecardMetric] = field(default_factory=list)
    overall_verdict: str = "UNKNOWN"
    detection_score: int = 0  # 0 = undetected, 100 = fully blocked

    @classmethod
    def from_api_logger(cls, api_logger) -> "BotScorecard":
        """Build scorecard from an ApiLogger instance (post-run)."""
        sc = cls()
        records = api_logger.records
        cookies = api_logger.cookie_snapshots

        # ── Metric 1: _abck validation flag ──
        abck_cookies = [c for c in cookies if c.name == "_abck"]
        abck_values = [c.value for c in abck_cookies]
        final_flag = "unknown"
        has_minus1 = any("~-1~" in (v or "") for v in abck_values)
        has_zero = any("~0~" in (v or "") for v in abck_values)

        if has_zero:
            final_flag = "0 (VALIDATED)"
            severity = "ok"
            explanation = "Akamai accepted this session as human. _abck cookie flipped to 0."
        elif has_minus1:
            final_flag = "-1 (FAILED)"
            severity = "critical"
            explanation = (
                "Akamai's behavioral fingerprint detected automation. The _abck cookie "
                "stayed at -1 throughout the session, meaning the JS sensor data never "
                "matched a 'real human' profile. This is THE primary bot detection signal."
            )
            sc.detection_score += 40
        else:
            final_flag = "not present"
            severity = "info"
            explanation = "No _abck cookie found — site may not use Akamai Bot Manager."

        sc.metrics.append(ScorecardMetric(
            "_abck Validation Flag", final_flag, severity, explanation
        ))

        # ── Metric 2: HTTP 403 count and locations ──
        blocked_calls = [r for r in records if r.status == 403]
        block_count = len(blocked_calls)
        block_hosts = list({r.host for r in blocked_calls})

        if block_count == 0:
            severity = "ok"
            explanation = "No hard blocks detected. Server accepted all requests."
        elif block_count <= 2:
            severity = "warning"
            explanation = (
                f"{block_count} request(s) returned 403 Forbidden on: "
                f"{', '.join(block_hosts)}. This indicates selective blocking — "
                "the server is rejecting specific API calls but not the full session."
            )
            sc.detection_score += 15
        else:
            severity = "critical"
            explanation = (
                f"{block_count} requests returned 403 Forbidden. Hosts: "
                f"{', '.join(block_hosts)}. Heavy blocking indicates the session "
                "was flagged early and most backend calls are being rejected."
            )
            sc.detection_score += 30

        sc.metrics.append(ScorecardMetric(
            "HTTP 403 Blocks", block_count, severity, explanation
        ))

        # ── Metric 3: Total calls captured (page render test) ──
        total_calls = len(records)
        if total_calls <= 5:
            severity = "critical"
            explanation = (
                f"Only {total_calls} calls captured. The page almost certainly did NOT "
                "render — the CDN/edge server blocked the request before any JavaScript "
                "could execute. This happens with headless browsers detected by "
                "User-Agent or TLS fingerprinting."
            )
            sc.detection_score += 30
        elif total_calls <= 50:
            severity = "warning"
            explanation = (
                f"{total_calls} calls captured — page partially loaded but many "
                "resources may have been blocked or scripts didn't execute fully."
            )
            sc.detection_score += 10
        else:
            severity = "ok"
            explanation = (
                f"{total_calls} calls captured — page loaded normally with full "
                "JavaScript execution, analytics, and tracking scripts."
            )

        sc.metrics.append(ScorecardMetric(
            "Total Calls Captured", total_calls, severity, explanation
        ))

        # ── Metric 4: _abck rotation frequency ──
        abck_set_cookies = [
            r for r in records
            if "_abck" in (r.response_set_cookie or "").lower()
        ]
        rotation_count = len(abck_set_cookies)

        if rotation_count == 0:
            severity = "info"
            explanation = "No _abck cookie rotations observed in responses."
        elif rotation_count <= 2:
            severity = "ok"
            explanation = (
                f"_abck was set/rotated {rotation_count} time(s) — normal for a "
                "legitimate browsing session."
            )
        elif rotation_count <= 5:
            severity = "warning"
            explanation = (
                f"_abck was set/rotated {rotation_count} times — slightly elevated. "
                "The server may be re-evaluating the session due to suspicious signals."
            )
            sc.detection_score += 5
        else:
            severity = "warning"
            explanation = (
                f"_abck was set/rotated {rotation_count} times — high frequency. "
                "Akamai is aggressively re-evaluating this session, indicating "
                "the behavioral fingerprint keeps failing validation."
            )
            sc.detection_score += 10

        sc.metrics.append(ScorecardMetric(
            "_abck Cookie Rotations", rotation_count, severity, explanation
        ))

        # ── Metric 5: Sensor POST accepted but not validated ──
        sensor_posts = [
            r for r in records
            if r.method == "POST" and r.status == 201
            and "_abck" in (r.response_set_cookie or "").lower()
        ]
        sensor_count = len(sensor_posts)

        if sensor_count > 0 and has_minus1 and not has_zero:
            severity = "critical"
            explanation = (
                f"{sensor_count} sensor POST(s) returned 201 Created (data accepted) "
                "but _abck remained -1 (not validated). This means Akamai received "
                "your browser fingerprint data but it FAILED their validation checks. "
                "The JS environment fingerprint doesn't match a real browser profile."
            )
            sc.detection_score += 15
        elif sensor_count > 0 and has_zero:
            severity = "ok"
            explanation = (
                f"{sensor_count} sensor POST(s) accepted and _abck flipped to 0. "
                "Fingerprint data was accepted AND validated."
            )
        elif sensor_count == 0:
            severity = "info"
            explanation = "No sensor POST submissions detected."

        if sensor_count > 0:
            sc.metrics.append(ScorecardMetric(
                "Sensor POSTs (201 but _abck=-1)", sensor_count, severity, explanation
            ))

        # ── Metric 6: Soft block detection (error messages in content) ──
        soft_block_keywords = [
            "technical difficulties",
            "access denied",
            "please verify you are a human",
            "captcha",
            "challenge",
            "blocked",
            "unusual traffic",
        ]
        soft_blocks = []
        for r in records:
            body = (r.response_body or "").lower()
            for kw in soft_block_keywords:
                if kw in body and r.resource_type in ("document", "xhr", "fetch"):
                    soft_blocks.append((r.url[:80], kw))
                    break

        if soft_blocks:
            severity = "critical"
            explanation = (
                f"Found {len(soft_blocks)} response(s) with soft-block language: "
                + "; ".join(f'"{kw}" in {url}' for url, kw in soft_blocks[:3])
                + ". These are bot detection rejections disguised as error messages."
            )
            sc.detection_score += 20
        else:
            severity = "ok"
            explanation = "No soft-block language detected in response bodies."

        sc.metrics.append(ScorecardMetric(
            "Soft Blocks (error messages)", len(soft_blocks), severity, explanation
        ))

        # ── Metric 7: reCAPTCHA / challenge script loads ──
        recaptcha_calls = [
            r for r in records
            if "recaptcha" in (r.url or "").lower()
            or "hcaptcha" in (r.url or "").lower()
        ]
        captcha_count = len(recaptcha_calls)

        if captcha_count > 0:
            severity = "warning"
            explanation = (
                f"{captcha_count} CAPTCHA-related script(s) loaded. The site is "
                "preparing to challenge this session — either via invisible scoring "
                "or a visible CAPTCHA. This is a secondary detection mechanism."
            )
            sc.detection_score += 5
        else:
            severity = "ok"
            explanation = "No CAPTCHA scripts loaded."

        sc.metrics.append(ScorecardMetric(
            "CAPTCHA Scripts Loaded", captcha_count, severity, explanation
        ))

        # ── Metric 8: Bot detection vendor count ──
        vendor_set: set[str] = set()
        from api_logger import VENDOR_SIGNATURES, _record_vendor_matches
        for r in records:
            for v in _record_vendor_matches(r):
                vendor_set.add(v)
        vendor_list = sorted(vendor_set)

        sc.metrics.append(ScorecardMetric(
            "Bot Detection Vendors Active",
            len(vendor_list),
            "info",
            f"Detected vendors: {', '.join(vendor_list)}" if vendor_list else "No known vendors detected",
        ))

        # ── Metric 9: Sensor POST payload analysis ──
        from api_logger import _is_randomized_sensor_path
        sensor_posts_all = [
            r for r in records
            if r.method == "POST"
            and _is_randomized_sensor_path(r.url or "", r.host or "")
        ]
        if sensor_posts_all:
            payload_sizes = []
            for r in sensor_posts_all:
                payload_str = r.request_payload or ""
                if "bytes>" in payload_str:
                    try:
                        size = int(payload_str.split(",")[0].split()[-1])
                    except (ValueError, IndexError):
                        size = len(payload_str)
                else:
                    size = len(payload_str)
                payload_sizes.append(size)
            avg_size = sum(payload_sizes) // max(len(payload_sizes), 1)
            sc.metrics.append(ScorecardMetric(
                "Sensor POST Count & Avg Payload",
                f"{len(sensor_posts_all)} posts, avg {avg_size} bytes",
                "info",
                f"{len(sensor_posts_all)} sensor POST(s) detected with average "
                f"payload size {avg_size} bytes. Larger payloads (>4 KB) indicate "
                "richer fingerprint data is being collected and submitted.",
            ))

        # ── Metric 10: _abck state transitions ──
        abck_transitions: list[str] = []
        prev_flag = ""
        for c in cookies:
            if c.name == "_abck":
                val = c.value or ""
                parts = val.split("~")
                flag = parts[1] if len(parts) > 1 else ""
                if flag and flag != prev_flag:
                    abck_transitions.append(f"{prev_flag or 'none'} → {flag}")
                    prev_flag = flag

        if abck_transitions:
            final_state = abck_transitions[-1].split("→")[-1].strip()
            if final_state == "0":
                severity = "ok"
                explanation = (
                    f"_abck transitioned through {len(abck_transitions)} state(s): "
                    f"{', '.join(abck_transitions)}. Final state is 0 (validated)."
                )
            else:
                severity = "critical"
                explanation = (
                    f"_abck transitioned through {len(abck_transitions)} state(s): "
                    f"{', '.join(abck_transitions)}. Final state is {final_state} "
                    "(NOT validated). The sensor data was never accepted."
                )
                sc.detection_score += 5

            sc.metrics.append(ScorecardMetric(
                "_abck State Transitions",
                ", ".join(abck_transitions),
                severity,
                explanation,
            ))

        # ── Overall verdict ──
        score = min(sc.detection_score, 100)
        sc.detection_score = score
        if score >= 60:
            sc.overall_verdict = "FULLY DETECTED — bot automation identified"
        elif score >= 30:
            sc.overall_verdict = "PARTIALLY DETECTED — flagged but not fully blocked"
        elif score >= 10:
            sc.overall_verdict = "SUSPICIOUS — some detection signals present"
        else:
            sc.overall_verdict = "LIKELY UNDETECTED — no strong bot signals"

        return sc

    @classmethod
    def from_excel(cls, path: str) -> "BotScorecard":
        """Build scorecard from a previously saved Excel log file."""
        from api_logger import ApiCallRecord, CookieSnapshotRow, ApiLogger, VENDOR_SIGNATURES

        wb = openpyxl.load_workbook(path, read_only=True)
        ws = wb["API Calls"]
        headers = [cell.value for cell in ws[1]]

        logger = ApiLogger()

        header_to_idx = {h: i for i, h in enumerate(headers)}

        for row in ws.iter_rows(min_row=2, values_only=True):
            d = dict(zip(headers, row))
            def s(val):
                return str(val) if val is not None else ""

            logger.records.append(ApiCallRecord(
                index=d.get("#", 0) or 0,
                timestamp=s(d.get("Timestamp")),
                phase=s(d.get("Phase")),
                method=s(d.get("Method")),
                resource_type=s(d.get("Type")),
                host=s(d.get("Host")),
                url=s(d.get("URL")),
                request_headers=s(d.get("Request Headers")),
                request_cookies=s(d.get("Request Cookies")),
                request_payload=s(d.get("Request Payload")),
                status=d.get("Status", 0) or 0,
                status_text=s(d.get("Status Text")),
                response_headers=s(d.get("Response Headers")),
                response_set_cookie=s(d.get("Response Set-Cookie")),
                response_body=s(d.get("Response Body")),
                duration_ms=s(d.get("Duration (ms)")),
            ))

        ws2 = wb["Cookie Timeline"]
        cookie_headers = [cell.value for cell in ws2[1]]
        for row in ws2.iter_rows(min_row=2, values_only=True):
            d = dict(zip(cookie_headers, row))
            if d.get("Label"):
                logger.cookie_snapshots.append(CookieSnapshotRow(
                    label=d.get("Label", ""),
                    name=d.get("Cookie Name", ""),
                    value=d.get("Value", "") or "",
                    domain=d.get("Domain", ""),
                    path=d.get("Path", ""),
                    http_only=d.get("HttpOnly", False),
                    secure=d.get("Secure", False),
                    same_site=d.get("SameSite", ""),
                    vendor_guess=d.get("Vendor Guess", ""),
                ))

        return cls.from_api_logger(logger)

    def print_report(self) -> None:
        """Print a formatted scorecard to stdout."""
        print(f"\n{'='*70}")
        print(f"  BOT DETECTION SCORECARD")
        print(f"{'='*70}")
        print(f"\n  Detection Score: {self.detection_score}/100")
        print(f"  Verdict: {self.overall_verdict}")
        print(f"\n{'-'*70}")

        severity_icons = {
            "critical": "🔴",
            "warning": "🟡",
            "ok": "🟢",
            "info": "ℹ️ ",
        }

        for m in self.metrics:
            icon = severity_icons.get(m.severity, "  ")
            print(f"\n  {icon} {m.name}: {m.value}")
            for line in m.explanation.split("\n"):
                print(f"     {line}")

        print(f"\n{'='*70}\n")

    def save_to_excel(self, path: str) -> None:
        """Save scorecard as a clean Excel sheet."""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Bot Scorecard"

        header_fill = PatternFill(start_color="2B579A", end_color="2B579A", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF", size=12)
        severity_fills = {
            "critical": PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"),
            "warning": PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid"),
            "ok": PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid"),
            "info": PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid"),
        }

        ws.merge_cells("A1:D1")
        title_cell = ws.cell(row=1, column=1, value="BOT DETECTION SCORECARD")
        title_cell.font = Font(bold=True, size=16, color="2B579A")

        ws.cell(row=2, column=1, value="Detection Score:")
        ws.cell(row=2, column=2, value=f"{self.detection_score}/100")
        ws.cell(row=2, column=2).font = Font(bold=True, size=14)
        if self.detection_score >= 60:
            ws.cell(row=2, column=2).fill = severity_fills["critical"]
        elif self.detection_score >= 30:
            ws.cell(row=2, column=2).fill = severity_fills["warning"]
        else:
            ws.cell(row=2, column=2).fill = severity_fills["ok"]

        ws.cell(row=3, column=1, value="Verdict:")
        ws.cell(row=3, column=2, value=self.overall_verdict)
        ws.cell(row=3, column=2).font = Font(bold=True, size=12)

        row = 5
        headers = ["Metric", "Value", "Severity", "Explanation"]
        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=row, column=col_idx, value=h)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")

        for m in self.metrics:
            row += 1
            ws.cell(row=row, column=1, value=m.name).font = Font(bold=True)
            ws.cell(row=row, column=2, value=str(m.value))
            ws.cell(row=row, column=3, value=m.severity.upper())
            ws.cell(row=row, column=4, value=m.explanation)
            ws.cell(row=row, column=4).alignment = Alignment(wrap_text=True)

            fill = severity_fills.get(m.severity)
            if fill:
                for col_idx in range(1, 5):
                    ws.cell(row=row, column=col_idx).fill = fill

        ws.column_dimensions["A"].width = 30
        ws.column_dimensions["B"].width = 20
        ws.column_dimensions["C"].width = 12
        ws.column_dimensions["D"].width = 80

        wb.save(path)
        print(f"Scorecard saved to: {path}")


def _find_latest_runs(logs_dir: str) -> dict[str, dict[str, str]]:
    """Scan logs/ and return {provider: {level_label: filepath}}."""
    import glob

    providers: dict[str, dict[str, str]] = {}

    # Verizon runs: logs/level{1..5}_*_TIMESTAMP.xlsx
    verizon_runs: dict[str, str] = {}
    verizon_levels = [
        (1, "Level 1 (Naked Bot)"),
        (2, "Level 2 (Basic Evasion)"),
        (3, "Level 3 (Stealth)"),
        (4, "Level 4 (Patchright)"),
        (5, "Level 5 (nodriver)"),
    ]
    for level_num, label in verizon_levels:
        pattern = os.path.join(logs_dir, f"level{level_num}_*_2*.xlsx")
        hits = sorted([
            f for f in glob.glob(pattern)
            if "filtered" not in f and "comparison" not in f and "scorecard" not in f
        ])
        if hits:
            verizon_runs[label] = hits[-1]
    if verizon_runs:
        providers["Verizon"] = verizon_runs

    # Frontier runs: logs/frontier/frontier_level{1..5}_*_TIMESTAMP.xlsx
    frontier_runs: dict[str, str] = {}
    frontier_dir = os.path.join(logs_dir, "frontier")
    frontier_levels = [
        (1, "Level 1 (Naked Bot)"),
        (2, "Level 2 (Basic Evasion)"),
        (3, "Level 3 (Stealth)"),
        (4, "Level 4 (Patchright)"),
        (5, "Level 5 (nodriver)"),
        (6, "Level 6 (Stealth Max)"),
    ]
    for level_num, label in frontier_levels:
        pattern = os.path.join(frontier_dir, f"frontier_level{level_num}_*_2*.xlsx")
        hits = sorted([
            f for f in glob.glob(pattern)
            if "filtered" not in f and "comparison" not in f and "scorecard" not in f
        ])
        if hits:
            frontier_runs[label] = hits[-1]
    if frontier_runs:
        providers["Frontier"] = frontier_runs

    return providers


def print_comparison_table(scorecards: dict[str, BotScorecard]) -> None:
    """Print all scorecards as a single side-by-side table."""
    if not scorecards:
        return

    labels = list(scorecards.keys())
    col_w = max(22, max(len(l) for l in labels) + 2)
    label_w = 36

    severity_icons = {"critical": "🔴", "warning": "🟡", "ok": "🟢", "info": "ℹ️ "}

    # Header
    header = f"{'Metric':<{label_w}}"
    for label in labels:
        header += f"{label:>{col_w}}"
    print(header)
    print("─" * (label_w + col_w * len(labels)))

    # Detection score row
    row = f"{'Detection Score':<{label_w}}"
    for label in labels:
        sc = scorecards[label]
        row += f"{str(sc.detection_score) + '/100':>{col_w}}"
    print(row)

    # Verdict row
    row = f"{'Verdict':<{label_w}}"
    for label in labels:
        sc = scorecards[label]
        short = sc.overall_verdict.split("—")[0].strip()
        row += f"{short:>{col_w}}"
    print(row)
    print("─" * (label_w + col_w * len(labels)))

    # Metric rows — gather all metric names across all scorecards
    all_metric_names: list[str] = []
    for sc in scorecards.values():
        for m in sc.metrics:
            if m.name not in all_metric_names:
                all_metric_names.append(m.name)

    for metric_name in all_metric_names:
        row = f"{'  ' + metric_name:<{label_w}}"
        for label in labels:
            sc = scorecards[label]
            found = [m for m in sc.metrics if m.name == metric_name]
            if found:
                m = found[0]
                icon = severity_icons.get(m.severity, "  ")
                val_str = str(m.value)
                if len(val_str) > col_w - 4:
                    val_str = val_str[:col_w - 6] + ".."
                cell = f"{icon} {val_str}"
                row += f"{cell:>{col_w}}"
            else:
                row += f"{'—':>{col_w}}"
        print(row)

    print()


def write_comparison_table_excel(
    provider: str,
    scorecards: dict[str, BotScorecard],
    output_path: str,
) -> None:
    """Write a side-by-side scorecard comparison to Excel."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"{provider} Scorecard"

    header_fill = PatternFill(start_color="2B579A", end_color="2B579A", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    severity_fills = {
        "critical": PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"),
        "warning": PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid"),
        "ok": PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid"),
        "info": PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid"),
    }

    labels = list(scorecards.keys())
    num_cols = 1 + len(labels) * 2  # Metric | (Value, Severity) per level

    # Title
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=num_cols)
    title_cell = ws.cell(row=1, column=1, value=f"{provider} — Bot Detection Scorecard Comparison")
    title_cell.font = Font(bold=True, size=14, color="2B579A")

    # Column headers — row 3
    r = 3
    cell = ws.cell(row=r, column=1, value="Metric")
    cell.fill = header_fill
    cell.font = header_font
    col = 2
    for label in labels:
        ws.merge_cells(start_row=r, start_column=col, end_row=r, end_column=col + 1)
        cell = ws.cell(row=r, column=col, value=label)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")
        ws.cell(row=r, column=col + 1).fill = header_fill
        col += 2

    # Sub-headers — row 4
    r = 4
    ws.cell(row=r, column=1, value="").fill = header_fill
    col = 2
    for _ in labels:
        for sub in ("Value", "Severity"):
            cell = ws.cell(row=r, column=col, value=sub)
            cell.fill = header_fill
            cell.font = Font(bold=True, color="FFFFFF", size=10)
            cell.alignment = Alignment(horizontal="center")
            col += 1

    # Score row
    r = 5
    ws.cell(row=r, column=1, value="Detection Score").font = Font(bold=True, size=12)
    col = 2
    for label in labels:
        sc = scorecards[label]
        cell = ws.cell(row=r, column=col, value=f"{sc.detection_score}/100")
        cell.font = Font(bold=True, size=12)
        if sc.detection_score >= 60:
            score_fill = severity_fills["critical"]
        elif sc.detection_score >= 30:
            score_fill = severity_fills["warning"]
        else:
            score_fill = severity_fills["ok"]
        cell.fill = score_fill
        ws.cell(row=r, column=col + 1, value="").fill = score_fill
        col += 2

    # Verdict row
    r = 6
    ws.cell(row=r, column=1, value="Verdict").font = Font(bold=True)
    col = 2
    for label in labels:
        sc = scorecards[label]
        ws.cell(row=r, column=col, value=sc.overall_verdict)
        col += 2

    # Metric rows
    all_metric_names: list[str] = []
    for sc in scorecards.values():
        for m in sc.metrics:
            if m.name not in all_metric_names:
                all_metric_names.append(m.name)

    r = 8
    for metric_name in all_metric_names:
        ws.cell(row=r, column=1, value=metric_name).font = Font(bold=True)
        col = 2
        for label in labels:
            sc = scorecards[label]
            found = [m for m in sc.metrics if m.name == metric_name]
            if found:
                m = found[0]
                val_cell = ws.cell(row=r, column=col, value=str(m.value))
                sev_cell = ws.cell(row=r, column=col + 1, value=m.severity.upper())
                sev_cell.alignment = Alignment(horizontal="center")
                fill = severity_fills.get(m.severity)
                if fill:
                    val_cell.fill = fill
                    sev_cell.fill = fill
            else:
                ws.cell(row=r, column=col, value="—")
            col += 2
        r += 1

    # Explanation sheet
    ws2 = wb.create_sheet("Explanations")
    ws2.cell(row=1, column=1, value="Metric").fill = header_fill
    ws2.cell(row=1, column=1).font = header_font
    ws2.cell(row=1, column=2, value="Level").fill = header_fill
    ws2.cell(row=1, column=2).font = header_font
    ws2.cell(row=1, column=3, value="Explanation").fill = header_fill
    ws2.cell(row=1, column=3).font = header_font
    er = 2
    for label in labels:
        sc = scorecards[label]
        for m in sc.metrics:
            ws2.cell(row=er, column=1, value=m.name).font = Font(bold=True)
            ws2.cell(row=er, column=2, value=label)
            ws2.cell(row=er, column=3, value=m.explanation)
            ws2.cell(row=er, column=3).alignment = Alignment(wrap_text=True)
            fill = severity_fills.get(m.severity)
            if fill:
                for c in range(1, 4):
                    ws2.cell(row=er, column=c).fill = fill
            er += 1

    # Column widths
    ws.column_dimensions["A"].width = 36
    for ci in range(2, num_cols + 1):
        ws.column_dimensions[get_column_letter(ci)].width = 22
    ws2.column_dimensions["A"].width = 34
    ws2.column_dimensions["B"].width = 24
    ws2.column_dimensions["C"].width = 90

    wb.save(output_path)
    print(f"  Scorecard table saved → {output_path}")


def main():
    """Run scorecard on all existing Frontier + Verizon Excel files, show table."""
    logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    providers = _find_latest_runs(logs_dir)

    if not providers:
        print("No run files found in logs/")
        return

    for provider, runs in providers.items():
        print(f"\n{'═'*80}")
        print(f"  {provider.upper()} — BOT DETECTION SCORECARD (all levels)")
        print(f"{'═'*80}\n")

        scorecards: dict[str, BotScorecard] = {}
        for label, path in runs.items():
            basename = os.path.basename(path)
            try:
                sc = BotScorecard.from_excel(path)
                scorecards[label] = sc
                print(f"  ✓ Loaded {label} from {basename}")
            except Exception as e:
                print(f"  ✗ {label}: {e}")

        if scorecards:
            print()
            print_comparison_table(scorecards)

            out_path = os.path.join(
                os.path.dirname(list(runs.values())[0]),
                f"{provider.lower()}_scorecard_comparison.xlsx",
            )
            write_comparison_table_excel(provider, scorecards, out_path)


if __name__ == "__main__":
    main()
