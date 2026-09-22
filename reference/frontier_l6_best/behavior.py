"""Realistic human behavior simulation for browser automation.

Provides Bezier curve mouse movement, log-normal typing cadence,
and natural scroll patterns to evade behavioral telemetry detection
by systems like Akamai Bot Manager and Quantum Metric.

Works with both Playwright/Patchright (sync) and nodriver (async) APIs.
"""

from __future__ import annotations

import math
import random
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # avoid circular imports; callers pass page objects dynamically


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------

def _comb(n: int, k: int) -> int:
    return math.factorial(n) // (math.factorial(k) * math.factorial(n - k))


def _bezier_point(t: float, points: list[tuple[float, float]]) -> tuple[float, float]:
    """Point on a cubic Bezier curve at parameter *t* ∈ [0, 1]."""
    n = len(points) - 1
    x = sum(_comb(n, i) * (1 - t) ** (n - i) * t ** i * p[0] for i, p in enumerate(points))
    y = sum(_comb(n, i) * (1 - t) ** (n - i) * t ** i * p[1] for i, p in enumerate(points))
    return x, y


def _ease_in_out(t: float) -> float:
    """Smooth ease-in-out (Hermite interpolation)."""
    return 3 * t ** 2 - 2 * t ** 3


# ---------------------------------------------------------------------------
# Playwright / Patchright (sync) helpers
# ---------------------------------------------------------------------------

def bezier_mouse_move(page, start_x: float, start_y: float,
                      end_x: float, end_y: float, steps: int = 25) -> None:
    """Move mouse along a cubic Bezier curve with overshoot and jitter."""
    dx, dy = end_x - start_x, end_y - start_y

    cp1 = (
        start_x + dx * random.uniform(0.2, 0.4) + random.uniform(-30, 30),
        start_y + dy * random.uniform(0.1, 0.3) + random.uniform(-30, 30),
    )
    cp2 = (
        start_x + dx * random.uniform(0.6, 0.8) + random.uniform(-20, 20),
        start_y + dy * random.uniform(0.7, 0.9) + random.uniform(-20, 20),
    )
    overshoot = (
        end_x + random.uniform(-3, 3),
        end_y + random.uniform(-3, 3),
    )
    points = [(start_x, start_y), cp1, cp2, overshoot]

    for i in range(steps):
        t = _ease_in_out(i / max(steps - 1, 1))
        x, y = _bezier_point(t, points)
        x += random.uniform(-1.5, 1.5)
        y += random.uniform(-1.5, 1.5)
        page.mouse.move(x, y)
        time.sleep(random.uniform(0.005, 0.02))

    page.mouse.move(end_x, end_y)


def bezier_click(page, locator, timeout: int = 10_000) -> None:
    """Click an element via Bezier curve mouse travel."""
    try:
        box = locator.bounding_box(timeout=timeout)
        if box:
            cur_x = page.evaluate("() => window._bhvX || window.innerWidth/2")
            cur_y = page.evaluate("() => window._bhvY || window.innerHeight/2")
            tx = box["x"] + box["width"] * random.uniform(0.25, 0.75)
            ty = box["y"] + box["height"] * random.uniform(0.25, 0.75)

            bezier_mouse_move(page, cur_x, cur_y, tx, ty)
            time.sleep(random.uniform(0.04, 0.12))
            page.mouse.click(tx, ty)
            page.evaluate(f"() => {{ window._bhvX={tx}; window._bhvY={ty}; }}")
            return
    except Exception:
        pass
    locator.click(timeout=timeout)


def lognormal_delay() -> float:
    """Single keystroke delay (seconds) sampled from a log-normal.

    Tuned so the median is ~110 ms and 95th percentile ~250 ms, matching
    empirical distributions measured in typing-cadence studies.
    """
    return max(0.03, random.lognormvariate(math.log(0.11), 0.35))


def lognormal_type(page, locator, text: str) -> None:
    """Type *text* character-by-character with realistic timing."""
    for char in text:
        locator.type(char, delay=0)
        delay = lognormal_delay()
        if random.random() < 0.05:
            delay += random.expovariate(1.0 / 0.5)
        if char == " ":
            delay += random.uniform(0.05, 0.15)
        page.wait_for_timeout(int(delay * 1000))


def natural_scroll(page, direction: str = "down", distance: int = 300) -> None:
    """Scroll with a natural fast-start / slow-stop deceleration curve."""
    total = 0
    velocity = distance * random.uniform(0.3, 0.5)
    friction = random.uniform(0.85, 0.92)
    sign = -1 if direction == "up" else 1

    while total < distance:
        step = max(10, int(velocity))
        step = min(step, distance - total)
        page.mouse.wheel(0, sign * step)
        total += step
        velocity *= friction
        time.sleep(random.uniform(0.01, 0.04))

    if random.random() < 0.2:
        time.sleep(random.uniform(0.3, 0.8))
        page.mouse.wheel(0, -sign * random.randint(30, 80))


def reading_pause(min_s: float = 1.0, max_s: float = 3.0) -> None:
    time.sleep(random.uniform(min_s, max_s))


def warmup_browse(page, duration_s: float = 15.0) -> None:
    """Browse the current page naturally for *duration_s* seconds.

    Scrolls, moves the mouse randomly, and pauses — establishing a
    behavioral baseline that looks human to session-replay tools.
    """
    start = time.time()
    while time.time() - start < duration_s:
        action = random.choice(["scroll", "move", "pause"])
        if action == "scroll":
            natural_scroll(page, "down", random.randint(200, 500))
            reading_pause(1.0, 2.5)
        elif action == "move":
            vw = page.evaluate("() => window.innerWidth")
            vh = page.evaluate("() => window.innerHeight")
            cx = page.evaluate("() => window._bhvX || window.innerWidth/2")
            cy = page.evaluate("() => window._bhvY || window.innerHeight/2")
            tx = random.uniform(100, max(vw - 100, 200))
            ty = random.uniform(100, max(vh - 100, 200))
            bezier_mouse_move(page, cx, cy, tx, ty, steps=15)
            page.evaluate(f"() => {{ window._bhvX={tx}; window._bhvY={ty}; }}")
            reading_pause(0.5, 1.5)
        else:
            reading_pause(1.5, 3.0)

    if random.random() < 0.5:
        natural_scroll(page, "up", random.randint(300, 600))
        reading_pause(0.5, 1.0)


# ---------------------------------------------------------------------------
# nodriver (async) equivalents
# ---------------------------------------------------------------------------

async def async_bezier_mouse_move(tab, start_x: float, start_y: float,
                                  end_x: float, end_y: float,
                                  steps: int = 25) -> None:
    """Async Bezier mouse-move for nodriver Tab."""
    import asyncio
    dx, dy = end_x - start_x, end_y - start_y
    cp1 = (start_x + dx * random.uniform(0.2, 0.4) + random.uniform(-30, 30),
           start_y + dy * random.uniform(0.1, 0.3) + random.uniform(-30, 30))
    cp2 = (start_x + dx * random.uniform(0.6, 0.8) + random.uniform(-20, 20),
           start_y + dy * random.uniform(0.7, 0.9) + random.uniform(-20, 20))
    overshoot = (end_x + random.uniform(-3, 3), end_y + random.uniform(-3, 3))
    points = [(start_x, start_y), cp1, cp2, overshoot]

    for i in range(steps):
        t = _ease_in_out(i / max(steps - 1, 1))
        x, y = _bezier_point(t, points)
        x += random.uniform(-1.5, 1.5)
        y += random.uniform(-1.5, 1.5)
        await tab.mouse_move(x, y)
        await asyncio.sleep(random.uniform(0.005, 0.02))

    await tab.mouse_move(end_x, end_y)


async def async_bezier_click(tab, element) -> None:
    """Click a nodriver Element via Bezier mouse travel."""
    import asyncio
    pos = await element.get_position()
    if pos:
        tx = pos.x + random.uniform(-5, 5)
        ty = pos.y + random.uniform(-5, 5)
        cx = await tab.evaluate("window._bhvX || window.innerWidth/2")
        cy = await tab.evaluate("window._bhvY || window.innerHeight/2")
        await async_bezier_mouse_move(tab, cx, cy, tx, ty)
        await asyncio.sleep(random.uniform(0.04, 0.12))
        await element.mouse_click()
        await tab.evaluate(f"window._bhvX={tx}; window._bhvY={ty};")
    else:
        await element.click()


async def async_lognormal_type(tab, element, text: str) -> None:
    """Type into a nodriver Element with log-normal timing."""
    import asyncio
    await element.clear_input()
    for char in text:
        await element.send_keys(char)
        delay = lognormal_delay()
        if random.random() < 0.05:
            delay += random.expovariate(1.0 / 0.5)
        if char == " ":
            delay += random.uniform(0.05, 0.15)
        await asyncio.sleep(delay)


async def async_natural_scroll(tab, direction: str = "down",
                               distance: int = 300) -> None:
    """Async natural scroll for nodriver."""
    import asyncio
    await tab.scroll_down(distance) if direction == "down" else await tab.scroll_up(distance)
    await asyncio.sleep(random.uniform(0.3, 0.8))


async def async_warmup_browse(tab, duration_s: float = 15.0) -> None:
    """Async warm-up browsing for nodriver."""
    import asyncio
    start = time.time()
    while time.time() - start < duration_s:
        action = random.choice(["scroll", "move", "pause"])
        if action == "scroll":
            await tab.scroll_down(random.randint(200, 500))
            await asyncio.sleep(random.uniform(1.0, 2.5))
        elif action == "move":
            vw = await tab.evaluate("window.innerWidth")
            vh = await tab.evaluate("window.innerHeight")
            cx = await tab.evaluate("window._bhvX || window.innerWidth/2")
            cy = await tab.evaluate("window._bhvY || window.innerHeight/2")
            tx = random.uniform(100, max(vw - 100, 200))
            ty = random.uniform(100, max(vh - 100, 200))
            await async_bezier_mouse_move(tab, cx, cy, tx, ty, steps=15)
            await tab.evaluate(f"window._bhvX={tx}; window._bhvY={ty};")
            await asyncio.sleep(random.uniform(0.5, 1.5))
        else:
            await asyncio.sleep(random.uniform(1.5, 3.0))

    if random.random() < 0.5:
        await tab.scroll_up(random.randint(300, 600))
        await asyncio.sleep(random.uniform(0.5, 1.0))
