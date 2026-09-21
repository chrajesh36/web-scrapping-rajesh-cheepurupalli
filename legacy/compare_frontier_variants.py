"""Compare bot-detection signals across the 3 Frontier evasion-level runs.

Reads the filtered Excel files produced by frontier_plans_variants.py and
prints a side-by-side comparison table plus a summary Excel workbook.

Usage:
    python compare_frontier_variants.py
"""

from __future__ import annotations

import os
from collections import Counter

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "frontier")

def _find_latest(prefix: str) -> str:
    """Find the most recent timestamped (unfiltered) xlsx for a given prefix."""
    candidates = sorted(
        [f for f in os.listdir(LOGS_DIR)
         if f.startswith(prefix) and f.endswith(".xlsx") and "filtered" not in f],
        reverse=True,
    )
    if candidates:
        return os.path.join(LOGS_DIR, candidates[0])
    return os.path.join(LOGS_DIR, f"{prefix}_filtered.xlsx")


LEVEL_FILES = {
    "Level 1 (Naked Bot)": _find_latest("frontier_level1_naked_bot"),
    "Level 2 (Basic Evasion)": _find_latest("frontier_level2_basic_evasion"),
    "Level 3 (Stealth Mode)": _find_latest("frontier_level3_stealth"),
}

HEADER_FILL = PatternFill(start_color="2B579A", end_color="2B579A", fill_type="solid")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
GOOD_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
WARN_FILL = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
BAD_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")


def load_api_calls(path: str) -> list[dict]:
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb["API Calls"]
    headers = [cell.value for cell in ws[1]]
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        rows.append(dict(zip(headers, row)))
    return rows


def load_bot_signals(path: str) -> list[dict]:
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb["Bot Detection Signals"]
    headers = [cell.value for cell in ws[1]]
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0]:
            rows.append(dict(zip(headers, row)))
    return rows


def load_cookies(path: str) -> list[dict]:
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb["Cookie Timeline"]
    headers = [cell.value for cell in ws[1]]
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0]:
            rows.append(dict(zip(headers, row)))
    return rows


def analyze_level(calls: list[dict], signals: list[dict], cookies: list[dict]) -> dict:
    metrics: dict = {}
    metrics["total_important_calls"] = len(calls)

    high_calls = [c for c in calls if c.get("Signal Level") == "High"]
    medium_calls = [c for c in calls if c.get("Signal Level") == "Medium"]
    metrics["high_signal_count"] = len(high_calls)
    metrics["medium_signal_count"] = len(medium_calls)

    sensor_calls = [
        c for c in calls
        if c.get("Signal Type") and "sensor" in str(c.get("Signal Type", "")).lower()
    ]
    metrics["akamai_sensor_submissions"] = len(sensor_calls)

    status_403 = [c for c in calls if c.get("Status") == 403]
    metrics["http_403_count"] = len(status_403)

    px_calls = [
        c for c in calls
        if "perimeter" in str(c.get("Host", "")).lower()
        or "px" in str(c.get("Bot/Fraud Vendor Match", "")).lower()
    ]
    px_403 = [c for c in px_calls if c.get("Status") == 403]
    metrics["perimeterx_calls"] = len(px_calls)
    metrics["perimeterx_403s"] = len(px_403)

    abck_cookies = [c for c in cookies if c.get("Cookie Name") == "_abck"]
    metrics["abck_cookie_sets"] = len(abck_cookies)
    abck_values = [str(c.get("Value", "")) for c in abck_cookies]
    has_minus1 = any("~-1~" in v for v in abck_values)
    has_zero = any("~0~" in v for v in abck_values)
    if has_zero:
        metrics["abck_validation"] = "VALIDATED (0)"
    elif has_minus1:
        metrics["abck_validation"] = "FAILED (-1)"
    else:
        metrics["abck_validation"] = "Unknown"

    vendors: set[str] = set()
    vendor_counts: Counter = Counter()
    for c in calls:
        v = c.get("Bot/Fraud Vendor Match")
        if v and str(v).strip():
            for part in str(v).split(","):
                vendors.add(part.strip())
                vendor_counts[part.strip()] += 1
    metrics["unique_vendors_detected"] = sorted(vendors)
    metrics["vendor_counts"] = dict(vendor_counts.most_common(10))

    signal_types: Counter = Counter()
    for c in calls:
        st = c.get("Signal Type")
        if st and str(st).strip():
            signal_types[str(st)] += 1
    metrics["signal_types"] = dict(signal_types.most_common(10))

    feedbacks: Counter = Counter()
    for c in calls:
        fb = c.get("Detection Feedback")
        if fb and str(fb).strip():
            feedbacks[str(fb)] += 1
    metrics["detection_feedbacks"] = dict(feedbacks.most_common(10))

    sensor_scripts = [
        c for c in calls
        if c.get("Type") == "script" and c.get("Signal Level") in ("High", "Medium")
    ]
    metrics["sensor_script_loads"] = len(sensor_scripts)

    return metrics


def print_comparison(all_metrics: dict[str, dict]) -> None:
    print("\n" + "=" * 90)
    print("   FRONTIER — ANTI-BOT EVASION COMPARISON — SIDE BY SIDE")
    print("=" * 90)

    levels = list(all_metrics.keys())

    metric_labels = [
        ("total_important_calls", "Total API Calls Captured"),
        ("high_signal_count", "High-Signal Calls"),
        ("medium_signal_count", "Medium-Signal Calls"),
        ("akamai_sensor_submissions", "Akamai Sensor Submissions"),
        ("sensor_script_loads", "Sensor Script Loads"),
        ("http_403_count", "HTTP 403 Blocks"),
        ("perimeterx_calls", "PerimeterX Calls"),
        ("perimeterx_403s", "PerimeterX 403s"),
        ("abck_cookie_sets", "_abck Cookie Rotations"),
        ("abck_validation", "_abck Final Validation"),
    ]

    col_width = 25
    label_width = 30

    header = f"{'Metric':<{label_width}}"
    for level in levels:
        short = level.split("(")[1].rstrip(")")
        header += f"{short:>{col_width}}"
    print(f"\n{header}")
    print("-" * (label_width + col_width * len(levels)))

    for key, label in metric_labels:
        row = f"{label:<{label_width}}"
        for level in levels:
            val = all_metrics[level].get(key, "N/A")
            row += f"{str(val):>{col_width}}"
        print(row)

    print(f"\n{'Vendor Call Counts:':<{label_width}}")
    for level in levels:
        short = level.split("(")[1].rstrip(")")
        vc = all_metrics[level].get("vendor_counts", {})
        print(f"  {short}:")
        for vendor, count in vc.items():
            print(f"    {vendor}: {count}")

    print(f"\n{'Top Detection Feedbacks:':<{label_width}}")
    for level in levels:
        short = level.split("(")[1].rstrip(")")
        feedbacks = all_metrics[level].get("detection_feedbacks", {})
        print(f"  {short}:")
        for fb, count in list(feedbacks.items())[:5]:
            print(f"    {fb}: {count}")

    print("\n" + "=" * 90)

    print("\n  VERDICT:")
    l1 = all_metrics.get(levels[0], {})
    l2 = all_metrics.get(levels[1], {})
    l3 = all_metrics.get(levels[2], {})

    if l3.get("high_signal_count", 999) < l1.get("high_signal_count", 0):
        print("  ✓ Stealth mode triggers FEWER high-signal detections than naked bot")
    else:
        print("  ✗ Stealth mode does NOT reduce high-signal detections vs naked bot")

    if l3.get("http_403_count", 999) <= l1.get("http_403_count", 0):
        print("  ✓ Stealth mode has fewer/equal 403 blocks")
    else:
        print("  ✗ Stealth mode has MORE 403 blocks")

    abck3 = l3.get("abck_validation", "")
    abck1 = l1.get("abck_validation", "")
    if "VALIDATED" in abck3 and "FAILED" in abck1:
        print("  ✓ Stealth mode achieved _abck validation (bot passed as human)")
    elif "FAILED" in abck3:
        print("  ✗ Stealth mode still fails _abck validation")
    else:
        print(f"  ~ _abck status: L1={abck1}, L3={abck3}")

    print()


def write_comparison_excel(all_metrics: dict[str, dict], output_path: str) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Summary Comparison"

    levels = list(all_metrics.keys())

    headers = ["Metric"] + levels
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")

    metric_rows = [
        ("Total Important Calls (High+Medium)", "total_important_calls"),
        ("High-Signal Calls", "high_signal_count"),
        ("Medium-Signal Calls", "medium_signal_count"),
        ("Akamai Sensor Submissions", "akamai_sensor_submissions"),
        ("Sensor Script Loads", "sensor_script_loads"),
        ("HTTP 403 Blocks", "http_403_count"),
        ("PerimeterX Calls", "perimeterx_calls"),
        ("PerimeterX 403 Responses", "perimeterx_403s"),
        ("_abck Cookie Rotations", "abck_cookie_sets"),
        ("_abck Final Validation", "abck_validation"),
        ("Unique Vendors", "unique_vendors_detected"),
    ]

    for row_idx, (label, key) in enumerate(metric_rows, 2):
        ws.cell(row=row_idx, column=1, value=label).font = Font(bold=True)
        for col_idx, level in enumerate(levels, 2):
            val = all_metrics[level].get(key, "N/A")
            if isinstance(val, list):
                val = ", ".join(val) if val else "none"
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.alignment = Alignment(horizontal="center")

    for row_idx in range(2, 2 + len(metric_rows)):
        label = ws.cell(row=row_idx, column=1).value
        if "Validation" in str(label):
            for col_idx in range(2, 2 + len(levels)):
                val = str(ws.cell(row=row_idx, column=col_idx).value)
                if "VALIDATED" in val:
                    ws.cell(row=row_idx, column=col_idx).fill = GOOD_FILL
                elif "FAILED" in val:
                    ws.cell(row=row_idx, column=col_idx).fill = BAD_FILL
        elif "Vendors" not in str(label):
            vals = []
            for col_idx in range(2, 2 + len(levels)):
                v = ws.cell(row=row_idx, column=col_idx).value
                try:
                    vals.append((col_idx, int(v)))
                except (ValueError, TypeError):
                    vals.append((col_idx, 0))
            if vals:
                sorted_vals = sorted(vals, key=lambda x: x[1])
                best_col = sorted_vals[0][0]
                worst_col = sorted_vals[-1][0]
                if sorted_vals[0][1] != sorted_vals[-1][1]:
                    ws.cell(row=row_idx, column=best_col).fill = GOOD_FILL
                    ws.cell(row=row_idx, column=worst_col).fill = BAD_FILL
                    for col, _ in sorted_vals[1:-1]:
                        ws.cell(row=row_idx, column=col).fill = WARN_FILL

    for col_idx in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 30 if col_idx == 1 else 25

    # Sheet 2: Detection Feedbacks
    ws2 = wb.create_sheet("Detection Feedbacks")
    ws2.cell(row=1, column=1, value="Detection Feedback").font = HEADER_FONT
    ws2.cell(row=1, column=1).fill = HEADER_FILL
    for col_idx, level in enumerate(levels, 2):
        short = level.split("(")[1].rstrip(")")
        cell = ws2.cell(row=1, column=col_idx, value=short)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL

    all_feedbacks: set[str] = set()
    for level in levels:
        all_feedbacks.update(all_metrics[level].get("detection_feedbacks", {}).keys())

    for row_idx, fb in enumerate(sorted(all_feedbacks), 2):
        ws2.cell(row=row_idx, column=1, value=fb)
        for col_idx, level in enumerate(levels, 2):
            count = all_metrics[level].get("detection_feedbacks", {}).get(fb, 0)
            ws2.cell(row=row_idx, column=col_idx, value=count).alignment = Alignment(
                horizontal="center"
            )

    for col_idx in range(1, len(levels) + 2):
        ws2.column_dimensions[get_column_letter(col_idx)].width = 40 if col_idx == 1 else 20

    # Sheet 3: Signal Types
    ws3 = wb.create_sheet("Signal Types")
    ws3.cell(row=1, column=1, value="Signal Type").font = HEADER_FONT
    ws3.cell(row=1, column=1).fill = HEADER_FILL
    for col_idx, level in enumerate(levels, 2):
        short = level.split("(")[1].rstrip(")")
        cell = ws3.cell(row=1, column=col_idx, value=short)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL

    all_signal_types: set[str] = set()
    for level in levels:
        all_signal_types.update(all_metrics[level].get("signal_types", {}).keys())

    for row_idx, st in enumerate(sorted(all_signal_types), 2):
        ws3.cell(row=row_idx, column=1, value=st)
        for col_idx, level in enumerate(levels, 2):
            count = all_metrics[level].get("signal_types", {}).get(st, 0)
            ws3.cell(row=row_idx, column=col_idx, value=count).alignment = Alignment(
                horizontal="center"
            )

    for col_idx in range(1, len(levels) + 2):
        ws3.column_dimensions[get_column_letter(col_idx)].width = 40 if col_idx == 1 else 20

    wb.save(output_path)
    print(f"\nComparison Excel saved to: {output_path}")


def main() -> None:
    missing = [name for name, path in LEVEL_FILES.items() if not os.path.exists(path)]
    if missing:
        print(f"ERROR: Missing filtered Excel file(s) for: {missing}")
        print("Run `python frontier_plans_variants.py --level N` first for each level.")
        return

    all_metrics: dict[str, dict] = {}

    for level_name, path in LEVEL_FILES.items():
        print(f"Loading {level_name} from {os.path.basename(path)}...")
        calls = load_api_calls(path)
        signals = load_bot_signals(path)
        cookies = load_cookies(path)
        all_metrics[level_name] = analyze_level(calls, signals, cookies)

    print_comparison(all_metrics)

    output_path = os.path.join(LOGS_DIR, "frontier_comparison_summary.xlsx")
    write_comparison_excel(all_metrics, output_path)


if __name__ == "__main__":
    main()
