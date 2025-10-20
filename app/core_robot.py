from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError, Error as PWError
from tenacity import retry, stop_after_attempt, wait_fixed
import sys, os, re, contextlib

# Configurable via environment variables
TARGET_URL = os.getenv("TARGET_URL", "https://lacity.gov/")
SEARCH_QUERY = os.getenv("SEARCH_QUERY", "311")
HEADFUL = os.getenv("HEADFUL", "0") == "1"  # Set HEADFUL=1 to watch the browser

class RobotFailure(Exception): ...
def log(msg): print(f"[robot] {msg}", flush=True)

# Safe click with retry logic
@retry(stop=stop_after_attempt(2), wait=wait_fixed(0.8))
def wait_click(page, selector=None, *, role=None, name=None, timeout=6000):
    if role:
        el = page.get_by_role(role, name=name) if name else page.get_by_role(role)
        el.first.wait_for(timeout=timeout)
        el.first.click(timeout=timeout)
    else:
        page.wait_for_selector(selector, timeout=timeout)
        page.click(selector, timeout=timeout)

# Safe fill with retry logic
@retry(stop=stop_after_attempt(2), wait=wait_fixed(0.8))
def wait_fill(page, selector=None, text="", *, role=None, name=None, timeout=6000):
    if role:
        el = page.get_by_role(role, name=name) if name else page.get_by_role(role)
        el.first.wait_for(timeout=timeout)
        el.first.fill(text, timeout=timeout)
    else:
        page.wait_for_selector(selector, timeout=timeout)
        page.fill(selector, text, timeout=timeout)

# Remove cookie/consent banners that block screen clicks
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

# Wait for results page to load
def wait_for_results_page(page):
    with contextlib.suppress(Exception):
        page.wait_for_url(re.compile(r".*lacity\.gov/.+search.*"), timeout=20000)
    with contextlib.suppress(Exception):
        page.wait_for_load_state("domcontentloaded", timeout=20000)

# Try a list of known selectors to get first visible result link
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

def run():
    with sync_playwright() as p:
        # headless unless HEADFUL=1
        browser = p.chromium.launch(headless=not HEADFUL, args=["--no-sandbox"])
        ctx = browser.new_context()
        page = ctx.new_page()

        try:
            log("goto homepage")
            page.goto(TARGET_URL, timeout=20000, wait_until="domcontentloaded")
            dismiss_banners(page)

            log("open search UI (best-effort)")
            with contextlib.suppress(Exception):
                wait_click(page, role="button", name="Search")

            # Try typing into role-based search bar first
            typed = False
            try:
                wait_fill(page, role="textbox", name="Search", text=SEARCH_QUERY)
                typed = True
            except Exception:
                # Fallback to CSS selectors if role isn't found
                for sel in ["input[type='search']", "input[name='q']", "input[aria-label='Search']"]:
                    try:
                        wait_fill(page, selector=sel, text=SEARCH_QUERY)
                        typed = True
                        break
                    except Exception:
                        continue

            # Press Enter or fallback to /search endpoint
            if typed:
                page.keyboard.press("Enter")
                wait_for_results_page(page)
            else:
                log("fallback /search")
                for qparam in ["q", "query", "search"]:
                    with contextlib.suppress(Exception):
                        page.goto(f"https://lacity.gov/search?{qparam}={SEARCH_QUERY}", timeout=20000)
                        break
                wait_for_results_page(page)

            log("locate first result")
            first_link = find_first_result(page)
            if not first_link:
                print(f"Failure: no results found for '{SEARCH_QUERY}'")
                return 1

            # Extract result label + URL
            title = (first_link.inner_text() or "").strip()
            href = first_link.get_attribute("href") or ""
            if href.startswith("/"):
                href = "https://lacity.gov" + href

            print(f"Success! Query='{SEARCH_QUERY}' | First result: {title} | URL: {href}")
            return 0

        except PWTimeoutError as e:
            print(f"Failure: timeout: {e}"); return 2
        except KeyboardInterrupt:
            log("Interrupted; shutting down cleanly"); return 130
        except (PWError, Exception) as e:
            print(f"Failure: unexpected error: {e}"); return 3
        finally:
            with contextlib.suppress(Exception): ctx.close()
            with contextlib.suppress(Exception): browser.close()

if __name__ == "__main__":
    sys.exit(run())