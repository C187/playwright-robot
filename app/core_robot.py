from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError, Error as PWError
import os, sys, contextlib
from app.robot_utils import log, core_search, BASE_URL

TARGET_URL = os.getenv("TARGET_URL", BASE_URL)
SEARCH_QUERY = os.getenv("SEARCH_QUERY", "311")
HEADFUL = os.getenv("HEADFUL", "0") == "1"

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not HEADFUL, args=["--no-sandbox"])
        ctx = browser.new_context()
        page = ctx.new_page()
        try:
            log("goto homepage")
            page.goto(TARGET_URL, timeout=20000, wait_until="domcontentloaded")

            title, href, mode = core_search(page, SEARCH_QUERY)
            log(f"search mode: {mode}")
            if not title:
                print(f"Failure: no results found for '{SEARCH_QUERY}'")
                return 1

            print(f"Success! Query='{SEARCH_QUERY}' | First result: {title} | URL: {href}")
            return 0

        except PWTimeoutError as e:
            print(f"Failure: timeout: {e}")
            return 2
        except KeyboardInterrupt:
            log("Interrupted; shutting down cleanly")
            return 130
        except (PWError, Exception) as e:
            print(f"Failure: unexpected error: {e}")
            return 3
        finally:
            with contextlib.suppress(Exception):
                ctx.close()
            with contextlib.suppress(Exception):
                browser.close()

if __name__ == "__main__":
    sys.exit(run())
