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
    """Deterministic search path used by both core and agent fallback."""
    dismiss_banners(page)
    try:
        wait_click(page, role="button", name="Search")
    except Exception:
        pass
    typed = False
    try:
        wait_fill(page, role="textbox", name="Search", text=query); typed = True
    except Exception:
        for sel in ["input[type='search']", "input[name='q']", "input[aria-label='Search']"]:
            try:
                wait_fill(page, selector=sel, text=query); typed = True; break
            except Exception:
                continue
    if typed:
        page.keyboard.press("Enter"); wait_for_results_page(page)
    else:
        # fallback direct search
        for qparam in ["q", "query", "search"]:
            with contextlib.suppress(Exception):
                page.goto(f"{BASE_URL}search?{qparam}={query}", timeout=20000)
                break
        wait_for_results_page(page)
    first = find_first_result(page)
    if not first:
        return None, None
    title = (first.inner_text() or "").strip()
    href = first.get_attribute("href") or ""
    if href and href.startswith("/"): href = BASE_URL.rstrip("/") + href
    return title, href
