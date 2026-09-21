"""Generate a Word document report for the Frontier bot-detection comparison."""

from __future__ import annotations

import os
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")


def add_heading(doc: Document, text: str, level: int = 1) -> None:
    doc.add_heading(text, level=level)


def add_para(doc: Document, text: str, bold: bool = False) -> None:
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = bold


def add_table_row(table, cells: list[str], bold: bool = False) -> None:
    row = table.add_row()
    for i, val in enumerate(cells):
        cell = row.cells[i]
        cell.text = val
        if bold:
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.bold = True


def main() -> None:
    doc = Document()

    style = doc.styles["Normal"]
    style.font.size = Pt(11)
    style.font.name = "Calibri"

    doc.add_heading("Frontier Bot Detection Analysis Report", 0)
    doc.add_paragraph(
        "Anti-Bot Evasion Comparison — Three Levels of Automation Stealth"
    )
    doc.add_paragraph("")

    # ── Executive Summary ──
    add_heading(doc, "1. Executive Summary", 1)
    add_para(doc, (
        "This report presents the results of a three-level bot detection evasion experiment "
        "conducted against frontier.com (now a Verizon company). Three automation variants were "
        "tested — a naked headless bot, a basic evasion setup, and a full stealth mode — to "
        "compare how Frontier's anti-bot infrastructure responds to each."
    ))
    add_para(doc, (
        "Key finding: Frontier's bot detection is extremely aggressive. The naked headless bot "
        "(Level 1) was completely blocked from even rendering page content — only 2 network calls "
        "were captured, both returning HTTP 403. Levels 2 and 3 (headed browser) captured ~235 calls "
        "each, but all three levels failed Akamai's _abck cookie validation."
    ))

    # ── Test Setup ──
    add_heading(doc, "2. Test Setup", 1)

    table = doc.add_table(rows=1, cols=4)
    table.style = "Medium Shading 1 Accent 1"
    hdr = table.rows[0].cells
    hdr[0].text = "Property"
    hdr[1].text = "Level 1 (Naked Bot)"
    hdr[2].text = "Level 2 (Basic)"
    hdr[3].text = "Level 3 (Stealth)"

    setup_rows = [
        ["Browser Mode", "Headless", "Headed", "Headed"],
        ["User-Agent", "Default Playwright\n(HeadlessChrome)", "Custom Chrome 126", "Custom Chrome 128"],
        ["Slow Motion", "None (0ms)", "150ms", "None"],
        ["Typing Delay", "0ms (instant)", "40ms", "60-220ms (random)"],
        ["Viewport", "800×600", "1440×900", "Random (1920×1080 etc.)"],
        ["Stealth Patches", "None", "None", "playwright-stealth\n(webdriver, plugins, etc.)"],
        ["Human-like Delays", "No", "No", "Yes (1.5-4s between actions)"],
        ["Mouse Simulation", "No", "No", "Yes (smooth movement)"],
    ]
    for row_data in setup_rows:
        add_table_row(table, row_data)

    add_para(doc, "")
    add_para(doc, (
        "Target URL: https://frontier.com/shop/internet\n"
        "Test Address: 2727 LBJ Freeway, Dallas, TX 75234\n"
        "Flow: Landing page → address entry → Check availability → /buy page → plans"
    ))

    # ── Results ──
    add_heading(doc, "3. Results — Side-by-Side Comparison", 1)

    results_table = doc.add_table(rows=1, cols=4)
    results_table.style = "Medium Shading 1 Accent 1"
    hdr2 = results_table.rows[0].cells
    hdr2[0].text = "Metric"
    hdr2[1].text = "Naked Bot"
    hdr2[2].text = "Basic Evasion"
    hdr2[3].text = "Stealth Mode"

    results_rows = [
        ["Total API Calls Captured", "2", "234", "237"],
        ["HTTP 403 Blocks", "2", "1", "2"],
        ["_abck Cookie Rotations", "5", "6", "5"],
        ["_abck Validation", "FAILED (-1)", "FAILED (-1)", "FAILED (-1)"],
        ["Akamai Bot Manager Calls", "2", "66", "70"],
        ["Cloudflare Calls", "0", "18", "21"],
        ["Google reCAPTCHA Calls", "0", "7", "5"],
        ["Adobe Analytics Calls", "0", "3", "3"],
        ["Page Rendered?", "NO (blocked)", "YES (partial)", "YES (partial)"],
        ["Plans Shown?", "NO", "NO", "NO"],
    ]
    for row_data in results_rows:
        add_table_row(table=results_table, cells=row_data)

    # ── Key Findings ──
    add_heading(doc, "4. Key Findings", 1)

    add_heading(doc, "4.1 Level 1 — Complete Block in Headless Mode", 2)
    add_para(doc, (
        "The naked headless bot was immediately detected and blocked by Frontier's infrastructure. "
        "Only 2 network calls were captured — both the initial page load and the fallback /buy page "
        "returned HTTP 403 (Forbidden). The browser received no page content to render, meaning "
        "Frontier's edge CDN (Akamai) rejects headless browsers at the network level before any "
        "JavaScript even executes."
    ))
    add_para(doc, (
        "This is significantly more aggressive than Verizon's approach, where the headless bot "
        "was able to load the page and submit an address (just couldn't navigate to plans). "
        "Frontier's 403 at the CDN level is a pre-emptive block based on the User-Agent header "
        "and/or TLS fingerprinting."
    ))

    add_heading(doc, "4.2 Level 2 & 3 — Headed Browser Gets Through, But Still Flagged", 2)
    add_para(doc, (
        "Both Level 2 (basic evasion) and Level 3 (stealth mode) successfully loaded the page "
        "in a headed browser. They captured 234 and 237 network calls respectively, indicating "
        "Frontier's JavaScript executed normally, loading analytics (Adobe, Google), ad trackers "
        "(DoubleClick, Snapchat, TikTok, Facebook), and bot detection scripts."
    ))
    add_para(doc, (
        "However, the _abck cookie remained at -1 (failed validation) for all three levels, "
        "meaning Akamai's behavioral fingerprinting still identified the browser as automated "
        "despite stealth patches. The bot detection operates at a deeper level than "
        "navigator.webdriver patching can address."
    ))

    add_heading(doc, "4.3 Stealth Mode — Marginal Improvement", 2)
    add_para(doc, (
        "Stealth mode (Level 3) showed only marginal differences from basic evasion:\n"
        "• Slightly more Akamai calls (70 vs 66) — stealth browsing triggered more sensor evaluations\n"
        "• More Cloudflare calls (21 vs 18) — longer session led to more CDN interactions\n"
        "• Fewer reCAPTCHA calls (5 vs 7) — slightly less suspicious to Google\n"
        "• Same number of 403 blocks and failed _abck validation\n\n"
        "The human-like delays and mouse simulation did not materially change the outcome."
    ))

    # ── Bot Detection Services ──
    add_heading(doc, "5. Bot Detection Services Identified on Frontier", 1)

    vendor_table = doc.add_table(rows=1, cols=3)
    vendor_table.style = "Medium Shading 1 Accent 1"
    vhdr = vendor_table.rows[0].cells
    vhdr[0].text = "Service"
    vhdr[1].text = "Role"
    vhdr[2].text = "Signals Observed"

    vendor_rows = [
        [
            "Akamai Bot Manager",
            "Primary bot detection & CDN edge protection",
            "_abck cookie (always -1), bm_sz cookie, ak_bmsc cookie, "
            "403 blocks at CDN level for headless browsers",
        ],
        [
            "Cloudflare Bot Management",
            "Secondary CDN/WAF layer",
            "18-21 calls per session, JS challenge scripts",
        ],
        [
            "Google reCAPTCHA",
            "CAPTCHA challenge for suspicious sessions",
            "5-7 reCAPTCHA script loads per session "
            "(may present invisible or visible CAPTCHA)",
        ],
        [
            "Adobe Experience Platform",
            "Analytics & identity stitching",
            "Adobe DTM scripts loaded, edge analytics calls",
        ],
        [
            "New Relic",
            "Application monitoring & performance",
            "JS agent loaded, bam.nr-data.net beacon calls",
        ],
        [
            "CookieLaw (OneTrust)",
            "Cookie consent management",
            "cdn.cookielaw.org script loads",
        ],
    ]
    for row_data in vendor_rows:
        add_table_row(vendor_table, row_data)

    # ── Frontier vs Verizon ──
    add_heading(doc, "6. Frontier vs Verizon — Bot Detection Comparison", 1)

    compare_table = doc.add_table(rows=1, cols=3)
    compare_table.style = "Medium Shading 1 Accent 1"
    chdr = compare_table.rows[0].cells
    chdr[0].text = "Aspect"
    chdr[1].text = "Verizon"
    chdr[2].text = "Frontier"

    compare_rows = [
        ["Headless bot blocking", "Allows page load, blocks plans", "403 at CDN level — no page at all"],
        ["Primary bot detection", "Akamai Bot Manager", "Akamai Bot Manager"],
        ["Secondary bot detection", "PerimeterX / HUMAN Security", "Cloudflare Bot Management"],
        ["CAPTCHA", "None observed", "Google reCAPTCHA loaded"],
        ["Session replay", "Quantum Metric", "None observed"],
        ["_abck validation", "Always FAILED (-1)", "Always FAILED (-1)"],
        ["Ad trackers", "Moderate", "Heavy (TikTok, Snapchat, Facebook, DoubleClick)"],
        ["Aggressiveness", "Medium — allows browsing, flags silently", "High — blocks headless immediately"],
    ]
    for row_data in compare_rows:
        add_table_row(compare_table, row_data)

    add_para(doc, "")
    add_para(doc, (
        "Despite Frontier now being a Verizon company, their bot detection stacks differ:\n"
        "• Frontier uses Cloudflare + Akamai dual-layer, while Verizon uses PerimeterX + Akamai\n"
        "• Frontier is more aggressive (CDN-level 403 blocks)\n"
        "• Frontier loads Google reCAPTCHA as a fallback challenge mechanism\n"
        "• Verizon uses Quantum Metric for behavioral analytics, Frontier does not"
    ))

    # ── Conclusion ──
    add_heading(doc, "7. Conclusion", 1)
    add_para(doc, (
        "Frontier's bot detection infrastructure is more aggressive than Verizon's, featuring "
        "CDN-level headless browser blocking, dual Akamai + Cloudflare protection, and Google "
        "reCAPTCHA as a challenge mechanism. The three-level evasion experiment demonstrates that:\n\n"
        "1. Headless browsers are completely blocked at the network level\n"
        "2. Headed browsers with or without stealth patches fail Akamai's _abck validation\n"
        "3. Stealth mode (playwright-stealth) provides negligible benefit against modern fingerprinting\n"
        "4. Frontier's dual CDN approach (Akamai + Cloudflare) creates layered defense\n\n"
        "To successfully automate Frontier browsing, one would need to solve Akamai's behavioral "
        "fingerprinting at the JavaScript engine level, which is beyond what browser patching or "
        "timing adjustments can achieve."
    ))

    # ── Files Reference ──
    add_heading(doc, "8. Output Files", 1)
    add_para(doc, (
        "All Excel files are in the logs/frontier/ directory:\n"
        "• frontier_level1_naked_bot_*.xlsx — Full Level 1 traffic (2 calls)\n"
        "• frontier_level2_basic_evasion_*.xlsx — Full Level 2 traffic (234 calls)\n"
        "• frontier_level3_stealth_*.xlsx — Full Level 3 traffic (237 calls)\n"
        "• frontier_*_filtered.xlsx — High+Medium signal calls only\n"
        "• frontier_comparison_summary.xlsx — Side-by-side comparison workbook"
    ))

    os.makedirs(REPORTS_DIR, exist_ok=True)
    output_path = os.path.join(REPORTS_DIR, "Frontier_Bot_Detection_Analysis.docx")
    doc.save(output_path)
    print(f"Report saved to: {output_path}")


if __name__ == "__main__":
    main()
