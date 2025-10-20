from __future__ import annotations
from playwright.sync_api import TimeoutError as PWTimeoutError
from tenacity import retry, stop_after_attempt, wait_fixed
import re, contextlib

BASE_URL = "https://lacity.gov/"

def log(msg: str): print(f"[robot] {msg}", flush=True)

@retry(stop=stop_after_attempt(2), wait=wait_fixed(0.8))
def wait_click(page, selector=None, *, role=None, name=None, timeout=6000):
    if role:
        el = page.get_by_role(role, name=name) if name else page.get_by_role(role)
        el.first.wait_for(timeout=timeout)
        el.first.click(timeout=timeout)
    else:
        page.wait_for_selector(selector, timeout=timeout)
        page.click(selector, timeout=timeout)

@retry(stop=stop_after_attempt(2), wait=wait_fixed(0.8))
def wait_fill(page, selector=None, text="", *, role=None, name=None, timeout=6000):
    if role:
        el = page.get_by_role(role, name=name) if name else page.get_by_role(role)
        el.first.wait_for(timeout=timeout)
        el.first.fill(text, timeout=timeout)
    else:
        page.wait_for_selector(selector, timeout=timeout)
        page.fill(selector, text, timeout=timeout)

def dismiss_banners(page):
    for sel in [
        "button:has-text('Accept')",
        "button:has-text('I Agree')",
        "[aria-label*='Accept']",
        "#onetrust-accept-btn-handler",
        "[data-testid='cookie-accept']",
    ]:
        with contextlib.suppress(Exception):
            if page.locator(sel).first.is_visible():
                page.locator(sel).first.click(timeout=1500)

def wait_for_results_page(page):
    with contextlib.suppress(Exception):
        page.wait_for_url(re.compile(r".*lacity\.gov/.+search.*"), timeout=20000)
    with contextlib.suppress(Exception):
        page.wait_for_load_state("domcontentloaded", timeout=20000)

def find_first_result(page):
    selectors = [
        "main article h3 a",
        "main .search-results a",
        "article h2 a",
        "main a.search-result__link",
        "main li a[href]:not([href^='#'])",
    ]
    for sel in selectors:
        try:
            page.wait_for_selector(sel, timeout=8000)
            loc = page.locator(sel).first
            if loc and loc.is_visible():
                return loc
        except Exception:
            continue
    return None

def core_search(page, query: str):
    """Search via UI when possible; fall back to direct /search/all-city?keys=... .
       Returns (title, url, mode)."""
    dismiss_banners(page)
    used = "ui"

    # Try to open + type into a real input
    with contextlib.suppress(Exception):
        wait_click(page, role="button", name=re.compile(r"^search$", re.I))

    typed = False
    for sel in [
        "form[role='search'] input[type='search']",
        "form[role='search'] input[name='keys']",
        "form[role='search'] input[name='q']",
        "input[type='search']",
        "input[name='keys']",
        "input[name='q']",
        "input[aria-label*='Search' i]",
    ]:
        try:
            page.wait_for_selector(sel, timeout=2000)
            page.fill(sel, query, timeout=2000)
            typed = True
            break
        except Exception:
            continue

    if typed:
        page.keyboard.press("Enter")
    else:
        # Deterministic direct route to results (avoid /search root to skip tab page)
        used = "direct"
        page.goto(f"{BASE_URL}search/all-city?keys={query}", timeout=15000, wait_until="domcontentloaded")

    # Wait for results page state
    with contextlib.suppress(Exception):
        page.wait_for_url(re.compile(r"lacity\.gov/.+search", re.I), timeout=10000)
    with contextlib.suppress(Exception):
        page.wait_for_load_state("domcontentloaded", timeout=8000)

    # Ensure a results container is present (Drupal + Google CSE patterns)
    for sel in ["div.gsc-results", ".search-results", "main"]:
        with contextlib.suppress(Exception):
            page.wait_for_selector(sel, timeout=4000)
            break

    def first_organic():
        candidates = [
            "div.gsc-results .gsc-webResult a.gs-title",
            "div.gsc-results .gs-title a",
            ".search-results .search-result h3 a",
            "main article h3 a",
            "main h3 a[href]",
        ]
        for sel in candidates:
            locs = page.locator(sel)
            n = min(locs.count(), 20)
            for i in range(n):
                a = locs.nth(i)
                text = (a.inner_text() or "").strip()
                href = (a.get_attribute("href") or "").strip()
                if not text or not href:
                    continue
                # Filter out navigational/tabs & anything under /search
                if "/search" in href.lower():
                    continue
                if re.search(r"\bAll LA City Websites\b", text, re.I):
                    continue
                return text, href
        # last resort: any non-/search link in main
        locs = page.locator("main a[href]:not([href^='#'])")
        n = min(locs.count(), 40)
        for i in range(n):
            a = locs.nth(i)
            text = (a.inner_text() or "").strip()
            href = (a.get_attribute("href") or "").strip()
            if text and href and "/search" not in href.lower() and not re.search(r"\bAll LA City Websites\b", text, re.I):
                return text, href
        return None

    picked = first_organic()
    if not picked:
        with contextlib.suppress(Exception):
            page.screenshot(path="core_search_last.png", full_page=True)
        return None, None, used

    title, url = picked
    if url.startswith("/"):
        url = BASE_URL.rstrip("/") + url
    return title, url, used