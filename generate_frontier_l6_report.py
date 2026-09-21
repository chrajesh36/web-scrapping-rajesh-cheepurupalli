"""Generate a Word document report: Frontier Bot Evasion — Levels 3–6.

Focuses on code, architecture, and results for Level 6 (Stealth Max),
with comparison against Levels 3–5.
"""

from __future__ import annotations

import os
from datetime import datetime

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor
from docx.oxml.ns import qn

REPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "frontier")


def set_cell_shading(element, color_hex: str) -> None:
    """Apply background shading to a table cell or paragraph."""
    el = element._element
    if hasattr(el, "get_or_add_tcPr"):
        props = el.get_or_add_tcPr()
    else:
        props = el.get_or_add_pPr()
    shd = props.makeelement(qn("w:shd"), {
        qn("w:val"): "clear",
        qn("w:color"): "auto",
        qn("w:fill"): color_hex,
    })
    props.append(shd)


def add_heading(doc, text, level=1):
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.color.rgb = RGBColor(0x1F, 0x4E, 0x78)
    return h


def add_code_block(doc, code: str, font_size: int = 7):
    for line in code.split("\n"):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = Pt(10)
        run = p.add_run(line)
        run.font.name = "Consolas"
        run.font.size = Pt(font_size)
        run.font.color.rgb = RGBColor(0x1A, 0x1A, 0x2E)
        set_cell_shading(p, "F5F5F5")


def make_table(doc, headers, rows, col_widths=None):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Light Grid Accent 1"

    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = h
        for p in cell.paragraphs:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in p.runs:
                run.bold = True

    for r_idx, row_data in enumerate(rows):
        for c_idx, val in enumerate(row_data):
            cell = table.rows[r_idx + 1].cells[c_idx]
            cell.text = str(val)

    return table


def main():
    doc = Document()

    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)

    # ═══════════════════════════════════════════════════════════════════
    # TITLE
    # ═══════════════════════════════════════════════════════════════════
    title = doc.add_heading("Frontier — Advanced Bot Evasion Report", level=0)
    for run in title.runs:
        run.font.color.rgb = RGBColor(0x1F, 0x4E, 0x78)
    doc.add_paragraph(
        f"Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}\n"
        "Target: frontier.com/shop/internet\n"
        "Test Address: 2727 LBJ Freeway, Dallas, TX 75234"
    )

    # ═══════════════════════════════════════════════════════════════════
    # 1. EXECUTIVE SUMMARY
    # ═══════════════════════════════════════════════════════════════════
    add_heading(doc, "1. Executive Summary")
    doc.add_paragraph(
        "This report documents the progressive evolution of our Frontier broadband-plans "
        "automation across four evasion levels (L3–L6), culminating in Level 6 (Stealth Max) "
        "which achieved what no previous level could: flipping Akamai's _abck cookie from "
        "-1 (bot) to 0 (validated human)."
    )
    doc.add_paragraph(
        "Level 6 is the first implementation to pass Akamai Bot Manager's full 5-layer "
        "validation on Frontier. It combines a zero-artifact browser driver (nodriver), "
        "multi-page session warming, Bezier curve mouse movement, log-normal typing cadence, "
        "and sensor-cycle patience into a single cohesive approach."
    )

    make_table(doc,
        ["Metric", "L3 Stealth", "L4 Patchright", "L5 nodriver", "L6 Stealth Max"],
        [
            ["Detection Score", "85/100", "85/100", "50/100", "5/100"],
            ["Verdict", "FULLY DETECTED", "FULLY DETECTED", "PARTIALLY DETECTED", "LIKELY UNDETECTED"],
            ["_abck Flag", "-1 (FAILED)", "-1 (FAILED)", "-1 (FAILED)", "0 (VALIDATED) ✓"],
            ["HTTP 403 Blocks", "2", "1", "0", "0"],
            ["Soft Blocks", "5", "4", "0", "0"],
            ["Total API Calls", "238", "235", "505", "557"],
            ["Sensor POSTs", "3", "3", "10", "14"],
            ["Plans Clicked", "0", "0", "1", "1"],
        ],
    )

    # ═══════════════════════════════════════════════════════════════════
    # 2. FRAMEWORKS & TOOLS
    # ═══════════════════════════════════════════════════════════════════
    add_heading(doc, "2. Frameworks and Tools Used")

    add_heading(doc, "2.1 Level 3 — Playwright + playwright-stealth", level=2)
    doc.add_paragraph(
        "Framework: Playwright (playwright >= 1.48.0) with playwright-stealth >= 2.0.0\n"
        "Browser: Bundled Chromium (shipped with Playwright)\n"
        "Script: frontier_plans_variants.py --level 3"
    )
    doc.add_paragraph(
        "Playwright is Microsoft's cross-browser automation library. It drives Chromium "
        "via the Chrome DevTools Protocol (CDP). The playwright-stealth plugin patches "
        "JavaScript globals (navigator.webdriver, chrome.runtime, Permissions API, WebGL "
        "renderer) to hide automation markers. However, it cannot modify the TLS fingerprint "
        "or CDP handshake sequence, both of which Akamai detects."
    )
    p = doc.add_paragraph()
    p.add_run("Key limitation: ").bold = True
    p.add_run(
        "Playwright's bundled Chromium has a distinctive JA4 TLS hash that does not match "
        "any real Chrome release. Akamai cross-validates TLS fingerprint against the User-Agent "
        "string — mismatch = instant flag."
    )

    add_heading(doc, "2.2 Level 4 — Patchright", level=2)
    doc.add_paragraph(
        "Framework: Patchright (patchright >= 1.0.0) — community fork of Playwright\n"
        "Browser: System-installed Google Chrome (not bundled Chromium)\n"
        "Script: frontier_patchright.py"
    )
    doc.add_paragraph(
        "Patchright is a drop-in Playwright replacement. The only code change is the import:\n"
        "  from patchright.sync_api import sync_playwright\n"
        "instead of:\n"
        "  from playwright.sync_api import sync_playwright\n\n"
        "Patchright patches the CDP startup sequence and drives the system-installed Chrome "
        "binary, so the TLS/JA4 fingerprint matches a real browser. All Playwright selectors "
        "and APIs work unchanged."
    )
    p = doc.add_paragraph()
    p.add_run("Key improvement: ").bold = True
    p.add_run("Real Chrome TLS fingerprint. ")
    p.add_run("Remaining gap: ").bold = True
    p.add_run("CDP handshake sequence is still detectable by advanced bot managers.")

    add_heading(doc, "2.3 Level 5 — nodriver", level=2)
    doc.add_paragraph(
        "Framework: nodriver (nodriver >= 0.38.0) — raw CDP connection\n"
        "Browser: System-installed Google Chrome\n"
        "Script: frontier_nodriver.py"
    )
    doc.add_paragraph(
        "nodriver connects to Chrome using raw DevTools Protocol — there is no Playwright "
        "layer. The entire CDP handshake sequence that bot detectors look for is absent. "
        "This gives zero automation fingerprint at the protocol level.\n\n"
        "The API is fully async (Python asyncio) and different from Playwright:\n"
        "  • tab = await browser.get(url)\n"
        "  • elem = await tab.find('text')\n"
        "  • await elem.click()\n"
        "  • await elem.send_keys('text')\n\n"
        "Network interception uses CDP events (Network.RequestWillBeSent, "
        "Network.ResponseReceived) instead of Playwright's page.on('request'/'response')."
    )
    p = doc.add_paragraph()
    p.add_run("Key improvement: ").bold = True
    p.add_run("Zero CDP automation artifacts. Eliminated all 403 blocks and soft blocks. ")
    p.add_run("Remaining gap: ").bold = True
    p.add_run("_abck stayed at -1 — insufficient behavioral evidence for Akamai to validate.")

    add_heading(doc, "2.4 Level 6 — Stealth Max (nodriver + full behavioral suite)", level=2)
    doc.add_paragraph(
        "Framework: nodriver (raw CDP) + custom behavior.py library\n"
        "Browser: System-installed Google Chrome\n"
        "Script: frontier_level6_stealth_max.py"
    )
    doc.add_paragraph(
        "Level 6 combines every anti-detection technique into a single approach. It uses "
        "nodriver as the foundation and adds multi-page session warming, extended behavioral "
        "warm-up with diverse interaction types, and sensor-cycle patience."
    )
    p = doc.add_paragraph()
    p.add_run("Result: ").bold = True
    p.add_run(
        "_abck flipped from -1 to 0 — Akamai validated the session as human for the "
        "first time across all test runs."
    )

    # ═══════════════════════════════════════════════════════════════════
    # 3. LEVEL 6 ARCHITECTURE
    # ═══════════════════════════════════════════════════════════════════
    add_heading(doc, "3. Level 6 — Architecture and Design")

    add_heading(doc, "3.1 Five-Layer Anti-Detection Strategy", level=2)
    doc.add_paragraph(
        "Akamai Bot Manager validates sessions across five simultaneous layers. "
        "Level 6 addresses all five:"
    )
    make_table(doc,
        ["Layer", "What Akamai Checks", "Level 6 Solution"],
        [
            ["1. TLS/Protocol", "JA4 TLS hash vs User-Agent; CDP handshake pattern",
             "nodriver — raw CDP, no Playwright; system Chrome for real TLS"],
            ["2. IP Reputation", "ASN type (datacenter vs residential); geo-match",
             "--proxy flag ready for residential proxy routing"],
            ["3. Sensor Payload", "Canvas hash, WebGL, AudioContext, navigator props",
             "Real Chrome generates authentic sensor data natively"],
            ["4. Behavioral", "Mouse trajectories, keystroke timing, scroll velocity",
             "Bezier curves, log-normal typing, natural scroll, nav hovers"],
            ["5. Session/Cookie", "Cookie lifecycle, multi-page browsing pattern",
             "Visit /why-frontier first; 50s warm-up; wait for 3+ sensor cycles"],
        ],
    )

    add_heading(doc, "3.2 Execution Flow", level=2)
    doc.add_paragraph("Level 6 executes in four distinct phases:\n")

    phases = [
        ("Phase 1: Warm-up Page (non-protected)",
         "Opens frontier.com/why-frontier — a non-protected informational page. "
         "This lets Akamai establish cookies (_abck, bm_sz) and begin scoring the "
         "session WITHOUT the protection pressure of the target page. "
         "Performs 25 seconds of rich behavioral warm-up: scrolling, mouse movement, "
         "nav-link hovering, reading pauses. Waits for at least 3 sensor POST "
         "submissions before proceeding."),
        ("Phase 2: Target Page with Extended Warm-up",
         "Navigates to frontier.com/shop/internet — the protected plans page. "
         "Performs another 25 seconds of warm-up browsing on this page. "
         "Waits for cumulative 6+ sensor POSTs. By this point, Akamai has ~50 seconds "
         "of behavioral telemetry across two pages."),
        ("Phase 3: Address Entry",
         "Types the address using log-normal keystroke timing (median 110ms, with "
         "Poisson thinking pauses). Selects autocomplete suggestion. Clicks "
         "'Check availability'. All interactions use Bezier curve mouse movement."),
        ("Phase 4: Plans Browsing",
         "After address submission, the _abck cookie flips from -1 to 0. "
         "The script clicks plan cards to capture pricing data. "
         "By this point, 14 sensor POSTs have fired."),
    ]
    for title_text, desc in phases:
        p = doc.add_paragraph()
        p.add_run(title_text + "\n").bold = True
        p.add_run(desc)

    add_heading(doc, "3.3 The _abck Flip — When and Why It Happened", level=2)
    doc.add_paragraph(
        "The _abck cookie tracks Akamai's trust assessment of a session. "
        "Flag -1 means 'not validated' (suspected bot). Flag 0 means 'validated' (trusted human)."
    )
    make_table(doc,
        ["Checkpoint", "_abck Flag", "Sensor POSTs", "Elapsed Time"],
        [
            ["01_warmup_page_loaded", "-1", "0", "~5s"],
            ["02_after_warmup_browsing", "-1", "3", "~30s"],
            ["03_target_page_loaded", "-1", "3", "~35s"],
            ["04_after_target_browsing", "-1", "6", "~60s"],
            ["05_after_check_availability", "-1", "~8", "~65s"],
            ["06_after_buy_page_load", "-1", "~10", "~70s"],
            ["08_after_plans_loaded", "0 ✓", "~12", "~80s"],
            ["09_after_browsing_plans", "0 ✓", "14", "~90s"],
        ],
    )
    doc.add_paragraph(
        "The flip happened between checkpoints 06 and 08 — after the address was submitted "
        "and the plans page loaded. At that point, Akamai had:\n"
        "• 50+ seconds of behavioral telemetry across two pages\n"
        "• 10+ sensor POST submissions with rich fingerprint data\n"
        "• Clean TLS fingerprint matching a real Chrome browser\n"
        "• Natural mouse/scroll/typing patterns matching human distributions\n"
        "• Multi-page browsing pattern (informational page → target page)\n\n"
        "All five layers aligned, and Akamai's trust score exceeded the validation threshold."
    )

    # ═══════════════════════════════════════════════════════════════════
    # 4. BEHAVIOR.PY — BEHAVIORAL SIMULATION LIBRARY
    # ═══════════════════════════════════════════════════════════════════
    add_heading(doc, "4. behavior.py — Behavioral Simulation Library")

    add_heading(doc, "4.1 Bezier Curve Mouse Movement", level=2)
    doc.add_paragraph(
        "Real human mouse movement follows cubic Bezier curves with overshoot and "
        "micro-corrections. Our implementation generates a 4-point Bezier path with "
        "randomized control points and applies Hermite ease-in-out interpolation."
    )
    add_code_block(doc, """\
async def async_bezier_mouse_move(tab, start_x, start_y, end_x, end_y, steps=25):
    dx, dy = end_x - start_x, end_y - start_y
    # Randomized control points for natural curvature
    cp1 = (start_x + dx * uniform(0.2, 0.4) + uniform(-30, 30),
           start_y + dy * uniform(0.1, 0.3) + uniform(-30, 30))
    cp2 = (start_x + dx * uniform(0.6, 0.8) + uniform(-20, 20),
           start_y + dy * uniform(0.7, 0.9) + uniform(-20, 20))
    # Slight overshoot past target (1-3px)
    overshoot = (end_x + uniform(-3, 3), end_y + uniform(-3, 3))
    points = [(start_x, start_y), cp1, cp2, overshoot]

    for i in range(steps):
        t = ease_in_out(i / (steps - 1))  # Hermite interpolation
        x, y = bezier_point(t, points)
        x += uniform(-1.5, 1.5)  # micro-jitter
        y += uniform(-1.5, 1.5)
        await tab.mouse_move(x, y)
        await sleep(uniform(0.005, 0.02))  # variable inter-step delay""")

    add_heading(doc, "4.2 Log-Normal Typing Cadence", level=2)
    doc.add_paragraph(
        "Human keystroke timing follows a log-normal distribution (not uniform random). "
        "Our implementation uses median ~110ms with a 95th percentile of ~250ms. "
        "5% of keystrokes include a Poisson-distributed 'thinking pause', and word "
        "boundaries (spaces) get an extra 50–150ms delay."
    )
    add_code_block(doc, """\
def lognormal_delay() -> float:
    # Median ~110ms, 95th percentile ~250ms
    return max(0.03, random.lognormvariate(math.log(0.11), 0.35))

async def async_lognormal_type(tab, element, text):
    await element.clear_input()
    for char in text:
        await element.send_keys(char)
        delay = lognormal_delay()
        if random.random() < 0.05:          # 5% thinking pause
            delay += random.expovariate(1.0 / 0.5)  # mean 500ms extra
        if char == " ":                      # word boundary pause
            delay += random.uniform(0.05, 0.15)
        await asyncio.sleep(delay)""")

    add_heading(doc, "4.3 Rich Warm-up Browsing", level=2)
    doc.add_paragraph(
        "Level 6 uses an extended warm-up function that generates diverse behavioral "
        "signals using weighted random actions:"
    )
    make_table(doc,
        ["Action", "Weight", "Description"],
        [
            ["scroll", "30%", "Scroll down 150–500px with variable speed"],
            ["move", "25%", "Bezier mouse movement to random position"],
            ["hover_nav", "20%", "Move to a random <nav> or <header> link and hover"],
            ["pause", "15%", "Reading pause (1–2.5 seconds)"],
            ["scroll_up", "10%", "Scroll back up 100–300px (re-reading behavior)"],
        ],
    )

    add_heading(doc, "4.4 Sensor-Cycle Patience", level=2)
    doc.add_paragraph(
        "A critical design element unique to Level 6: the script waits for a minimum "
        "number of Akamai sensor POST submissions before taking meaningful actions. "
        "The CdpNetworkLogger counts sensor POSTs in real-time by detecting Akamai's "
        "randomized first-party sensor endpoints."
    )
    add_code_block(doc, """\
async def wait_for_sensor_cycles(cdp_logger, min_posts=3, timeout_s=30.0):
    start = time.time()
    while cdp_logger.sensor_post_count < min_posts:
        if time.time() - start > timeout_s:
            break
        await asyncio.sleep(0.5)
    return cdp_logger.sensor_post_count

# Usage in main flow:
sensor_count = await wait_for_sensor_cycles(cdp_logger, min_posts=3, timeout_s=15)
# ... more browsing ...
sensor_count = await wait_for_sensor_cycles(cdp_logger, min_posts=6, timeout_s=15)""")

    # ═══════════════════════════════════════════════════════════════════
    # 5. CDP NETWORK INTERCEPTION (nodriver)
    # ═══════════════════════════════════════════════════════════════════
    add_heading(doc, "5. CDP Network Interception (nodriver)")

    doc.add_paragraph(
        "Since nodriver uses raw CDP instead of Playwright's API, network interception "
        "is implemented via CDP event handlers. The CdpNetworkLogger hooks into "
        "Network.RequestWillBeSent and Network.ResponseReceived events, and populates "
        "the same ApiCallRecord structure used by Playwright-based levels."
    )
    add_code_block(doc, """\
class CdpNetworkLogger:
    def __init__(self, api_logger: ApiLogger):
        self.api_logger = api_logger
        self._pending = {}
        self.sensor_post_count = 0

    async def enable(self, tab):
        tab.add_handler(net.RequestWillBeSent, self._on_request)
        tab.add_handler(net.ResponseReceived, self._on_response)
        await tab.send(net.enable())

    def _on_request(self, event):
        req = event.request
        # Store pending request with timestamp, phase, headers, cookies, payload
        self._pending[str(event.request_id)] = { ... }

    def _on_response(self, event):
        pending = self._pending.pop(str(event.request_id), None)
        # Track sensor POSTs for patience logic
        if method == "POST" and _is_randomized_sensor_path(url, host):
            self.sensor_post_count += 1
        # Append to api_logger.records as ApiCallRecord""")

    doc.add_paragraph(
        "Cookie snapshots use CDP's Storage.getCookies() instead of Playwright's "
        "context.cookies(), enabling the same _abck tracking across all levels."
    )

    # ═══════════════════════════════════════════════════════════════════
    # 6. SENSOR TRACKER
    # ═══════════════════════════════════════════════════════════════════
    add_heading(doc, "6. Sensor POST Interceptor and _abck State Tracker")

    doc.add_paragraph(
        "Added to api_logger.py: a SensorEvent dataclass and interceptor that records "
        "every Akamai sensor POST with _abck state before and after the submission. "
        "This is exported as a 'Sensor Tracker' sheet in the Excel log."
    )
    add_code_block(doc, """\
@dataclass
class SensorEvent:
    timestamp: str
    phase: str
    url: str
    method: str
    payload_size: int
    status: int
    abck_before: str      # _abck value from request cookies
    abck_after: str       # _abck value from response Set-Cookie
    abck_flag_before: str # extracted flag (-1 or 0)
    abck_flag_after: str
    flipped: bool         # True if flag changed from -1 to 0""")

    doc.add_paragraph(
        "The sensor tracker also detects Akamai's randomized first-party endpoint pattern. "
        "These paths have 4+ segments with at least one random-looking segment (>7 chars) "
        "and don't match known application path prefixes."
    )

    # ═══════════════════════════════════════════════════════════════════
    # 7. FULL LEVEL 6 CODE
    # ═══════════════════════════════════════════════════════════════════
    add_heading(doc, "7. Level 6 Full Source Code")

    add_heading(doc, "7.1 frontier_level6_stealth_max.py (main script)", level=2)
    with open("frontier_level6_stealth_max.py") as f:
        add_code_block(doc, f.read(), font_size=6)

    add_heading(doc, "7.2 behavior.py (behavioral simulation library)", level=2)
    with open("behavior.py") as f:
        add_code_block(doc, f.read(), font_size=6)

    # ═══════════════════════════════════════════════════════════════════
    # 8. L3 CODE (for comparison)
    # ═══════════════════════════════════════════════════════════════════
    add_heading(doc, "8. Level 3 Source Code (for comparison)")
    doc.add_paragraph(
        "Level 3 uses Playwright + playwright-stealth. Key differences from Level 6:\n"
        "• Uses bundled Chromium (detectable TLS fingerprint)\n"
        "• Uniform random delays instead of log-normal distribution\n"
        "• No session warming or sensor-cycle patience\n"
        "• Playwright CDP handshake is detectable"
    )
    add_heading(doc, "8.1 frontier_plans_variants.py --level 3", level=2)
    with open("frontier_plans_variants.py") as f:
        add_code_block(doc, f.read(), font_size=6)

    # ═══════════════════════════════════════════════════════════════════
    # 9. L4 & L5 CODE
    # ═══════════════════════════════════════════════════════════════════
    add_heading(doc, "9. Level 4 Source Code (Patchright)")
    with open("frontier_patchright.py") as f:
        add_code_block(doc, f.read(), font_size=6)

    add_heading(doc, "10. Level 5 Source Code (nodriver)")
    with open("frontier_nodriver.py") as f:
        add_code_block(doc, f.read(), font_size=6)

    # ═══════════════════════════════════════════════════════════════════
    # 11. WHY EACH LEVEL FAILED / SUCCEEDED
    # ═══════════════════════════════════════════════════════════════════
    add_heading(doc, "11. Why Each Level Failed or Succeeded")

    make_table(doc,
        ["Level", "Framework", "What It Fixed", "Why It Still Failed"],
        [
            ["L3", "Playwright +\nplaywright-stealth",
             "JS automation markers\n(navigator.webdriver, etc.)",
             "TLS fingerprint mismatch (JA4 hash)\n"
             "CDP handshake detected\n"
             "Uniform random behavior (not human-like)"],
            ["L4", "Patchright",
             "TLS fingerprint\n(drives system Chrome)",
             "CDP handshake still partially detectable\n"
             "Insufficient behavioral evidence\n"
             "No session warming"],
            ["L5", "nodriver\n(raw CDP)",
             "CDP handshake eliminated\n"
             "Zero automation artifacts\n"
             "0 HTTP 403 blocks",
             "_abck stayed -1: only 15s warm-up\n"
             "on single page; not enough sensor\n"
             "cycles for Akamai validation"],
            ["L6", "nodriver +\nbehavior.py +\nmulti-page warming",
             "ALL FIVE LAYERS:\n"
             "✓ Clean TLS\n"
             "✓ No CDP artifacts\n"
             "✓ Rich behavioral data\n"
             "✓ Multi-page session\n"
             "✓ Sensor patience",
             "SUCCEEDED\n"
             "_abck = 0 (validated)\n"
             "Detection score: 5/100"],
        ],
    )

    # ═══════════════════════════════════════════════════════════════════
    # 12. BOT DETECTION SERVICES IDENTIFIED
    # ═══════════════════════════════════════════════════════════════════
    add_heading(doc, "12. Bot Detection Services Identified on Frontier")

    make_table(doc,
        ["Service", "Detection Method", "Signals Observed"],
        [
            ["Akamai Bot Manager",
             "TLS fingerprint, CDP detection,\nsensor payload validation,\n_abck cookie lifecycle",
             "_abck cookie (flag -1 or 0)\nbm_sz / ak_bmsc cookies\nRandomized sensor POST endpoints\n201 responses on sensor submissions"],
            ["Cloudflare Bot Management",
             "HTTP challenge, browser fingerprint",
             "cf-ray headers\n__cf_bm cookies\nCAPTCHA script loading"],
            ["Quantum Metric",
             "Session replay, behavioral analysis",
             "quantummetric ingest calls\nSession replay data streaming"],
            ["Adobe Experience Platform",
             "Analytics, identity resolution",
             "sanalytics.* / demdex.net calls\nAlloy/Edge analytics events"],
        ],
    )

    # ═══════════════════════════════════════════════════════════════════
    # 13. RECOMMENDATIONS
    # ═══════════════════════════════════════════════════════════════════
    add_heading(doc, "13. Recommendations for Further Improvement")

    items = [
        ("Add residential proxy support",
         "Use the --proxy flag with a residential proxy service (BrightData, Oxylabs) "
         "to improve IP reputation score. Match proxy geo to the target address."),
        ("Session cookie persistence",
         "Save validated _abck cookies to disk and reload them on subsequent runs "
         "to skip the warm-up phase for faster execution."),
        ("Adaptive warm-up duration",
         "Monitor _abck flag in real-time and shorten the warm-up once validation "
         "is achieved, reducing total execution time."),
        ("CAPTCHA handling",
         "Three CAPTCHA scripts were loaded even in Level 6. If invisible CAPTCHA "
         "scoring tightens, consider integrating a CAPTCHA solver service."),
    ]
    for title_text, desc in items:
        p = doc.add_paragraph()
        p.add_run(title_text + ": ").bold = True
        p.add_run(desc)

    # ═══════════════════════════════════════════════════════════════════
    # Save
    # ═══════════════════════════════════════════════════════════════════
    os.makedirs(REPORT_DIR, exist_ok=True)
    output_path = os.path.join(REPORT_DIR, "frontier_bot_evasion_report_L3_to_L6.docx")
    doc.save(output_path)
    print(f"\nReport saved to: {output_path}")


if __name__ == "__main__":
    main()
