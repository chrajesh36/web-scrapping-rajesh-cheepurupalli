"""Generate a Word (.docx) report summarizing the bot-detection analysis of
the Verizon broadband-plans network capture (logs/api_calls_*.xlsx).

Standalone script — does not re-run the browser automation. Values below
are pulled from analysis of logs/api_calls_20260807_115452.xlsx (792 calls
across 69 hosts).
"""

from __future__ import annotations

import os

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Inches, Pt, RGBColor

OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", "Bot_Detection_Analysis.docx")

NAVY = RGBColor(0x1F, 0x4E, 0x78)
RED = RGBColor(0xC0, 0x00, 0x00)
GRAY = RGBColor(0x59, 0x59, 0x59)

VENDOR_ROW_COLORS = {
    "PerimeterX / HUMAN Security": "D0BFFF",
    "Akamai Bot Manager": "FFD8A8",
    "Cloudflare Bot Management": "99E9F2",
    "Quantum Metric (session replay / behavioral)": "A5D8FF",
    "Adobe Experience Platform": "C3FAE8",
}


def _shade_cell(cell, hex_color: str) -> None:
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), hex_color)
    cell._tc.get_or_add_tcPr().append(shd)


def _set_col_widths(table, widths_in):
    for row in table.rows:
        for cell, w in zip(row.cells, widths_in):
            cell.width = Inches(w)


def add_heading(doc, text, level=1):
    h = doc.add_heading(text, level=level)
    if level == 1:
        for run in h.runs:
            run.font.color.rgb = NAVY
    return h


def add_caption(doc, text):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.italic = True
    run.font.size = Pt(9)
    run.font.color.rgb = GRAY
    return p


def add_bullets(doc, items):
    for item in items:
        doc.add_paragraph(item, style="List Bullet")


def add_table(doc, headers, rows, widths=None, row_shades=None):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Light Grid Accent 1"
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    hdr_cells = table.rows[0].cells
    for i, h in enumerate(headers):
        hdr_cells[i].text = h
        for p in hdr_cells[i].paragraphs:
            for r in p.runs:
                r.bold = True
        _shade_cell(hdr_cells[i], "1F4E78")
        for p in hdr_cells[i].paragraphs:
            for r in p.runs:
                r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

    for ridx, row in enumerate(rows):
        cells = table.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = str(val)
            for p in cells[i].paragraphs:
                p.paragraph_format.space_after = Pt(2)
                for r in p.runs:
                    r.font.size = Pt(9)
        if row_shades and ridx < len(row_shades) and row_shades[ridx]:
            for c in cells:
                _shade_cell(c, row_shades[ridx])

    if widths:
        _set_col_widths(table, widths)
    doc.add_paragraph()
    return table


def build() -> None:
    doc = Document()

    for section in doc.sections:
        section.left_margin = Inches(0.9)
        section.right_margin = Inches(0.9)

    title = doc.add_heading("Bot Detection Analysis", level=0)
    for run in title.runs:
        run.font.color.rgb = NAVY
    sub = doc.add_paragraph()
    run = sub.add_run("Verizon Broadband Plans — Automated Session Network Capture")
    run.bold = True
    run.font.size = Pt(13)
    add_caption(
        doc,
        "Source: network capture from the automated Playwright run (verizon_plans.py) \u00b7 "
        "792 calls across 69 hosts \u00b7 logs/api_calls_20260807_115452.xlsx \u00b7 Generated Aug 7, 2026",
    )
    doc.add_paragraph()

    # Headline finding callout
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(6)
    run = p.add_run("Headline finding:  ")
    run.bold = True
    run.font.color.rgb = RED
    run2 = p.add_run(
        "Akamai Bot Manager's _abck cookie carries a sensor-validation flag that stayed at \u201c-1\u201d "
        "(not validated) for the entire session, and a PerimeterX-style device-fingerprint beacon to "
        "sv.verizon.com was rejected with HTTP 403 on its very first call \u2014 before any scripted "
        "interaction took place."
    )
    run2.font.color.rgb = RED

    # Summary stats table (as a simple 5-col table since python-docx canvas Stat isn't available)
    add_table(
        doc,
        ["Total calls", "Distinct hosts", "Vendors found", "Akamai sensor calls", "Blocked fingerprint calls"],
        [["792", "69", "4", "27 (4 load + 23 submit)", "1 (HTTP 403)"]],
    )

    doc.add_page_break()

    # Methodology section
    add_heading(doc, "Methodology \u2014 Why Three Separate Views Are Needed", level=1)
    doc.add_paragraph(
        "Bot-mitigation evidence lives at three different layers of a browser session, and each layer "
        "needs its own lens to see clearly. Collapsing them into a single list would hide the very "
        "patterns that reveal bot detection is happening \u2014 each sheet below answers a question the "
        "other two structurally cannot."
    )

    add_heading(doc, "API Calls \u2014 raw, per-request ground truth", level=2)
    p = doc.add_paragraph()
    p.add_run("What it captures: ").bold = True
    p.add_run(
        "every single network request/response \u2014 full URL, headers, request/response payload, status, "
        "and duration, tagged with the automation phase that triggered it."
    )
    p = doc.add_paragraph()
    p.add_run("Why it needs its own inspection pass: ").bold = True
    p.add_run(
        "bot-mitigation vendors intentionally hide in plain sight. Their scripts are served from "
        "randomized, unbranded URLs and return heavily obfuscated JavaScript specifically so they don't "
        "stand out in a request list \u2014 an aggregated view or a cookie list would never surface this; "
        "only reading individual request/response bodies does."
    )
    add_bullets(
        doc,
        [
            "Example: the path \u201c/QfNarR/B/w/jjsGZutEvwQD/.../VyIB\u201d on www.verizon.com looked like "
            "meaningless noise until its response body was opened and found to contain obfuscated JS "
            "(\u201c(function(){if(typeof Array.prototype.entries...\u201d). That's Akamai Bot Manager's sensor "
            "script \u2014 invisible unless the raw call is inspected.",
            "Example: the exact query parameters on the blocked sv.verizon.com call "
            "(sv_px_domain_data, sv_session, sv_cid, sv_tzOffset) \u2014 which reveal exactly what "
            "device/session data was being fingerprinted \u2014 only exist in the raw URL of that one row.",
        ],
    )

    add_heading(doc, "Bot Detection Signals \u2014 aggregated, cross-cutting summary", level=2)
    p = doc.add_paragraph()
    p.add_run("What it captures: ").bold = True
    p.add_run(
        "the same 792 raw rows rolled up by vendor-signature match \u2014 call count, hosts touched, and any "
        "error responses, per vendor."
    )
    p = doc.add_paragraph()
    p.add_run("Why it needs its own inspection pass: ").bold = True
    p.add_run(
        "no one can scan 792 individual rows and mentally tally how many calls came from Akamai vs. "
        "Quantum Metric vs. Adobe. Aggregation is required to answer volume and scope questions \u2014 how "
        "aggressive is each vendor, is it isolated to one host or spread across many, does it correlate "
        "with errors \u2014 and to decide where the row-level API Calls inspection should focus next."
    )
    add_bullets(
        doc,
        [
            "Example: this sheet is what shows, in one line, that Akamai matched 302 of 792 calls across "
            "8 hosts while PerimeterX matched only 1 call and it happened to 403 \u2014 a comparison that "
            "would take extensive manual filtering of the API Calls sheet to reproduce by hand.",
        ],
    )

    add_heading(doc, "Cookie Timeline \u2014 point-in-time cookie-jar snapshots", level=2)
    p = doc.add_paragraph()
    p.add_run("What it captures: ").bold = True
    p.add_run(
        "the entire browser cookie jar (every cookie, not just the ones seen in a particular request's "
        "headers) captured at 4 fixed checkpoints in the flow."
    )
    p = doc.add_paragraph()
    p.add_run("Why it needs its own inspection pass: ").bold = True
    p.add_run(
        "for two structural reasons neither of the other sheets can cover."
    )
    add_bullets(
        doc,
        [
            "Not every bot-mitigation cookie is visible in network traffic at all. Some are written "
            "client-side via document.cookie from JavaScript (a common Akamai/Quantum Metric "
            "implementation pattern) and never appear as a Set-Cookie response header, so the API Calls "
            "sheet's cookie columns would simply miss them. A full cookie-jar snapshot is the only way to "
            "see the complete picture.",
            "Cookies like Akamai's _abck encode state as a tilde-delimited value that changes on every "
            "request. Determining whether that state persists, resets, or flips over a session requires "
            "comparing the SAME cookie across multiple points in time \u2014 exactly what the checkpoint-based "
            "timeline is built for.",
        ],
    )
    p = doc.add_paragraph()
    p.add_run("Example: ").bold = True
    p.add_run(
        "the most important finding in this whole analysis \u2014 that _abck's sensor-validation segment "
        "stayed at \u201c-1\u201d through all 4 checkpoints (landing page \u2192 get started \u2192 offers page \u2192 after "
        "reviewing all plans) \u2014 could only be established by diffing the same cookie's value at four "
        "different times. Any single API Calls row only ever shows one snapshot of that cookie, never "
        "its trend."
    )

    p = doc.add_paragraph()
    run = p.add_run(
        "In short: API Calls answers \u201cwhat exactly happened,\u201d Bot Detection Signals answers \u201chow much "
        "of it happened and where,\u201d and Cookie Timeline answers \u201cdid detection state change over the "
        "course of the session.\u201d None of the three can be reconstructed from either of the other two, so "
        "each requires its own dedicated inspection pass."
    )
    run.italic = True

    doc.add_page_break()

    # Section 1
    add_heading(doc, "1. Bot Detection Services Identified", level=1)
    doc.add_paragraph("Ranked by strength of evidence found in this session's traffic.")

    add_heading(doc, "Akamai Bot Manager \u2014 Confirmed", level=2)
    add_bullets(
        doc,
        [
            "_abck, bm_sz, ak_bmsc cookies set on the very first page load.",
            "Obfuscated sensor script served from a randomized first-party path "
            "(e.g. /QfNarR/B/w/jjsGZutEvwQD/.../VyIB).",
            "27 sensor calls (4 script loads + 23 data submissions), spread across every phase of the "
            "session \u2014 including each individual plan-review step.",
            "_abck validation flag stayed at \u201c-1\u201d (unvalidated) at all 4 cookie-jar checkpoints taken.",
        ],
    )

    add_heading(doc, "PerimeterX / HUMAN-style identity service \u2014 Detected, blocked", level=2)
    add_bullets(
        doc,
        [
            "First-party proxy endpoint sv.verizon.com/internal/id-event called with vendor=trackIdentity "
            "and an encrypted sv_px_domain_data fingerprint blob \u2014 the \u201c_px\u201d naming convention is "
            "characteristic of PerimeterX/HUMAN Security.",
            "Fired immediately on landing-page load, before the address was even typed.",
            "Returned HTTP 403 every time it was called in this session \u2014 could indicate active "
            "rejection of the automated session, or a broken/deprecated endpoint; can't fully distinguish "
            "from this data alone.",
        ],
    )

    add_heading(doc, "Quantum Metric \u2014 Confirmed, behavioral", level=2)
    add_bullets(
        doc,
        [
            "95 calls \u2014 SDK loaded from cdn.quantummetric.com/network-interceptor/quantum-verizon.js, "
            "telemetry streamed to ingestusipv4.quantummetric.com.",
            "Session/user tracked via QuantumMetricSessionID and QuantumMetricUserID cookies, present from "
            "first load.",
            "Primarily a UX session-replay tool, but the \u201cnetwork-interceptor\u201d SDK explicitly hooks "
            "page XHR/fetch calls too \u2014 this class of telemetry is commonly reused as a fraud/bot signal "
            "source.",
        ],
    )

    add_heading(doc, "Adobe Experience Platform \u2014 Supporting signal", level=2)
    add_bullets(
        doc,
        [
            "51 calls to sanalytics.verizon.com (Adobe Alloy/Edge) and adobedc.demdex.net (Adobe Audience "
            "Manager identity).",
            "Resolves a persistent visitor ID (ECID) plus a demdex cookie \u2014 identity/personalization "
            "focused, not a dedicated bot-mitigation product.",
        ],
    )

    p = doc.add_paragraph()
    run = p.add_run("Not observed on verizon.com: ")
    run.bold = True
    p.add_run(
        "DataDome, Cloudflare Bot Management, Imperva/Incapsula, Kasada, Arkose Labs/FunCaptcha, and Google "
        "reCAPTCHA/hCaptcha did not appear anywhere on Verizon's own domains in this session. Cloudflare "
        "signals did appear (53 calls) but only on third-party ad-tech domains \u2014 LinkedIn Ads, Qualtrics, "
        "and Quantum Metric's own CDN \u2014 not on verizon.com itself."
    )

    doc.add_page_break()

    # Section 2
    add_heading(doc, "2. What Activity Happened, and When", level=1)

    add_heading(doc, "Calls by resource type", level=2)
    add_table(
        doc,
        ["Resource type", "Call count", "Share of total"],
        [
            ["script", "349", "44%"],
            ["fetch", "212", "27%"],
            ["xhr", "133", "17%"],
            ["ping", "52", "7%"],
            ["document", "46", "6%"],
        ],
        widths=[2, 1.5, 1.5],
    )
    add_caption(
        doc,
        "Source: API Calls sheet, resource_type column \u00b7 792 calls total. Scripts dominate \u2014 this is "
        "where SDK loaders (Akamai sensor, Quantum Metric, Adobe Launch) live, and would have been invisible "
        "if capture were limited to xhr/fetch only.",
    )

    add_heading(doc, "Akamai sensor submissions, by automation phase", level=2)
    add_table(
        doc,
        ["Phase", "Sensor calls"],
        [
            ["Landing page (initial load)", "7"],
            ["Address typing", "1"],
            ["Autocomplete suggestions", "1"],
            ["Get started click", "0"],
            ["Business/residential modal", "2"],
            ["Offers page loading", "6"],
            ["Plan review 1 of 5", "2"],
            ["Plan review 2 of 5", "2"],
            ["Plan review 3 of 5", "2"],
            ["Plan review 4 of 5", "2"],
            ["Plan review 5 of 5", "2"],
        ],
        widths=[3.5, 1.5],
    )
    add_caption(
        doc,
        "Source: API Calls sheet, Phase column, URLs matching the randomized /QfNarR/... pattern. Fires "
        "continuously \u2014 including once for every individual plan viewed \u2014 not just on initial load.",
    )

    add_heading(doc, "Vendor-matched call volume", level=2)
    add_table(
        doc,
        ["Vendor", "Matched network calls"],
        [
            ["Akamai Bot Manager", "302"],
            ["Quantum Metric", "95"],
            ["Cloudflare (3rd-party only)", "53"],
            ["Adobe Experience Platform", "51"],
            ["PerimeterX-style identity", "1"],
        ],
        widths=[3.5, 1.5],
        row_shades=[VENDOR_ROW_COLORS["Akamai Bot Manager"], VENDOR_ROW_COLORS["Quantum Metric (session replay / behavioral)"], VENDOR_ROW_COLORS["Cloudflare Bot Management"], VENDOR_ROW_COLORS["Adobe Experience Platform"], VENDOR_ROW_COLORS["PerimeterX / HUMAN Security"]],
    )
    add_caption(
        doc,
        "Source: Bot Detection Signals sheet. Not mutually exclusive \u2014 a single call can match more than "
        "one vendor signature, so counts don't sum to 792.",
    )

    doc.add_page_break()

    # Section 3
    add_heading(doc, "3. Which of Our Data Likely Feeds Bot Detection", level=1)
    add_table(
        doc,
        ["Data category", "Specific fields observed", "Collected by", "Example from this session"],
        [
            [
                "Device / browser fingerprint",
                "User-Agent, sec-ch-ua / sec-ch-ua-mobile / sec-ch-ua-platform, screen width/height, "
                "viewport size, timezone offset, IANA timezone",
                "Adobe Alloy (sanalytics), sv.verizon.com identity beacon",
                "1440\u00d7900 \u00b7 macOS \u00b7 America/Chicago \u00b7 GMT-0500",
            ],
            [
                "Deep browser/device entropy (canvas, WebGL, fonts, hardware, timing)",
                "Not directly readable \u2014 encoded inside an obfuscated JS-collected payload",
                "Akamai Bot Manager sensor script",
                "Payload is intentionally obfuscated at the network layer; only inferred from the sensor "
                "script's presence",
            ],
            [
                "Session / identity cookies",
                "_abck, bm_sz, ak_bmsc \u00b7 QuantumMetricSessionID, QuantumMetricUserID \u00b7 demdex / AMCV (ECID)",
                "Akamai, Quantum Metric, Adobe",
                "_abck = <hash>~-1~<hash>~-1~-1~<ts>~... (persisted across all 4 checkpoints)",
            ],
            [
                "Page & navigation context",
                "Current URL, referrer, page title, SEO keywords, first-visit flag, entry page/flow name",
                "sv.verizon.com trackIdentity beacon, Adobe Alloy",
                "sv_referrer=(empty) \u00b7 sv_url=verizon.com/home/internet/ \u00b7 sv_first=true",
            ],
            [
                "Behavioral / interaction telemetry",
                "Mouse movement, clicks, scroll position, DOM mutations, and the page's own network "
                "activity (session replay)",
                "Quantum Metric \u201cnetwork-interceptor\u201d SDK",
                "Opaque binary POST bodies (~1\u20132 KB per beacon) to ingestusipv4.quantummetric.com",
            ],
            [
                "Opaque encrypted device fingerprint",
                "A single long encrypted/encoded blob, query param sv_px_domain_data",
                "PerimeterX/HUMAN-style trackIdentity endpoint",
                'sv_px_domain_data="iHjobdQ1L1QHmw5y..." (truncated, encrypted)',
            ],
        ],
        widths=[1.6, 2.4, 1.7, 2.0],
    )

    add_heading(doc, "Cookies tagging this session", level=2)
    add_table(
        doc,
        ["Cookie", "Vendor", "Sample value (truncated)", "Present at all 4 checkpoints?"],
        [
            ["_abck", "Akamai Bot Manager", "998A17BB...~-1~YAAQ3DYv...", "Yes"],
            ["bm_sz", "Akamai Bot Manager", "8253DCAA2D02C0...~YAAQ3DYv...", "Yes"],
            ["ak_bmsc", "Akamai Bot Manager", "B5D89BDFD4030...~00000000...", "Yes"],
            ["QuantumMetricSessionID", "Quantum Metric", "3c83ab22fedb44178cf09a4923805b8c", "Yes"],
            ["QuantumMetricUserID", "Quantum Metric", "45335be67bb6caf6e65b2b13c2528cbb", "Yes"],
            ["demdex", "Adobe Experience Platform", "12553034279938536060289100789141318440", "Yes"],
        ],
        widths=[1.8, 2.0, 2.8, 1.6],
        row_shades=[
            VENDOR_ROW_COLORS["Akamai Bot Manager"], VENDOR_ROW_COLORS["Akamai Bot Manager"], VENDOR_ROW_COLORS["Akamai Bot Manager"],
            VENDOR_ROW_COLORS["Quantum Metric (session replay / behavioral)"], VENDOR_ROW_COLORS["Quantum Metric (session replay / behavioral)"],
            VENDOR_ROW_COLORS["Adobe Experience Platform"],
        ],
    )
    add_caption(
        doc,
        "Source: Cookie Timeline sheet, snapshotted at landing page load, after \u201cGet started\u201d, after the "
        "offers page loaded, and after all 5 plans were reviewed.",
    )

    doc.add_paragraph()
    add_heading(doc, "Caveats", level=2)
    p = doc.add_paragraph(
        "This is inferred from client-side network traffic only \u2014 vendor identification is "
        "confidence-based pattern matching (cookie names, header markers, URL/query conventions), not "
        "confirmed against any vendor's private documentation. No JS call-stack/initiator data or TLS "
        "fingerprint was available to attribute individual calls to specific source scripts with certainty. "
        "There was no non-automated baseline session to compare against, so it's not possible to say with "
        "certainty whether the single 403 reflects bot-specific rejection versus a broken endpoint that "
        "fails for all traffic."
    )
    for run in p.runs:
        run.italic = True
        run.font.size = Pt(9)
        run.font.color.rgb = GRAY

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    doc.save(OUT_PATH)
    print(f"Saved report to {OUT_PATH}")


if __name__ == "__main__":
    build()
