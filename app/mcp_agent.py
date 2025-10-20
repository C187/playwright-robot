from __future__ import annotations
import os, json, re, time, contextlib, asyncio
from typing import Any, Dict, List
from openai import OpenAI
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError, Error as PWError
from mcp import ClientSession
from mcp.client.sse import sse_client
from app.robot_utils import core_search, BASE_URL

GOAL = os.getenv("GOAL", "Open https://lacity.gov, search for 311, and report the first result title and URL.")
MCP_URL = os.getenv("MCP_SERVER_URL", "http://localhost:11000/sse")
MODEL = os.getenv("MODEL", "gpt-4o-mini")
HEADFUL = os.getenv("HEADFUL", "0") == "1"
SEARCH_QUERY = os.getenv("SEARCH_QUERY", "311")

ALLOWED_ACTIONS = {"navigate", "click", "type", "wait", "extract_text"}

def log(msg: str): print(f"[agent] {msg}", flush=True)

def extract_json_block(s: str) -> str:
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s); return m.group(1).strip() if m else s

def parse_json_maybe(s: str) -> Any:
    s = extract_json_block(s).strip()
    try: return json.loads(s)
    except Exception:
        m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", s); 
        return json.loads(m.group(1)) if m else (_ for _ in ()).throw(ValueError("no json"))

def normalize_plan(raw: Any) -> List[Dict[str, Any]]:
    steps = raw.get("steps") if isinstance(raw, dict) else raw
    if not isinstance(steps, list):
        raise ValueError("plan is not a list")

    out = []
    for st in steps:
        if not isinstance(st, dict):
            continue

        # Case 1: already structured correctly
        if "action" in st and st["action"] in ALLOWED_ACTIONS:
            out.append(st)
            continue

        # Case 2: shorthand format from the LLM (like {"navigate": "https://..."})
        for key, val in st.items():
            if key in ALLOWED_ACTIONS:
                step = {"action": key}
                if key == "navigate":
                    step["url"] = val
                elif key in ("click", "wait", "extract_text"):
                    step["selector"] = val
                elif key == "type":
                    step["selector"] = val
                    if "text" in st:
                        step["text"] = st["text"]
                # Preserve any extra keys
                for k2, v2 in st.items():
                    if k2 not in step:
                        step[k2] = v2
                out.append(step)
                break

    if not out:
        raise ValueError("no valid steps after normalization")
    return out


def fallback_execute(page) -> Dict[str, Any]:
    title, href, mode = core_search(page, SEARCH_QUERY)
    if not title:
        raise RuntimeError(f"no results for '{SEARCH_QUERY}'")
    return {"first_result": {"title": title, "url": href}, "_mode": f"fallback_core_{mode}"}

def normalize_call_tool_result(res) -> dict:
    try:
        out_text, out_json = [], {}
        parts = getattr(res, "content", None)
        if isinstance(parts, list):
            for part in parts:
                t = getattr(part, "type", None)
                if t == "text": out_text.append(getattr(part, "text", "") or "")
                elif t == "json":
                    pj = getattr(part, "json", None)
                    if isinstance(pj, dict): out_json.update(pj)
                    elif pj is not None: out_json.setdefault("value", pj)
        out = {}
        if out_text: out["text"] = "\n".join(t for t in out_text if t)
        if out_json: out["json"] = out_json
        return out or {"raw": str(res)}
    except Exception:
        return {"raw": str(res)}

async def mcp_snapshot() -> Dict[str, Any]:
    try:
        async with sse_client(url=MCP_URL) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                for tool_name in ("snapshot", "get_accessibility_tree", "a11y_tree"):
                    try:
                        res = await session.call_tool(tool_name, {}); return normalize_call_tool_result(res)
                    except Exception:
                        continue
                tools_resp = await session.list_tools()
                tools = [t.name for t in getattr(tools_resp, "tools", [])]
                return {"note": "no_snapshot_tool_found", "tools": tools}
    except Exception as e:
        return {"note": "mcp_connect_error", "error": str(e), "url": MCP_URL}

def ask_llm_for_plan(snapshot: Dict[str, Any], goal: str) -> List[Dict[str, Any]]:
    if not os.getenv("OPENAI_API_KEY"): raise RuntimeError("no api key")
    client = OpenAI()
    system = (
        "Return ONLY a JSON array of steps, or {\"steps\":[...]}. "
        "Each step MUST include an 'action' field. "
        "Use stable Playwright selectors and prefer role+name or text queries over CSS. "
        "Avoid using 'input[name=q]' unless it exists in the snapshot. "
        "Allowed actions: navigate{url}, click{selector|text|role+name}, type{selector,text}, wait{selector}, extract_text{selector,key}."
    )
    user = json.dumps({"goal": goal, "page": snapshot}, ensure_ascii=False)
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role":"system","content":system},{"role":"user","content":user}],
        temperature=0
    )
    content = resp.choices[0].message.content or "[]"
    raw = parse_json_maybe(content)
    log(f"LLM raw content: {content[:400]}")  # show first 400 chars
    return normalize_plan(raw)

def exec_step(page, step: Dict[str, Any], results: Dict[str, Any]) -> None:
    a = step.get("action")
    if a == "navigate":
        page.goto(step["url"], timeout=20000, wait_until="domcontentloaded")
    elif a == "click":
        if "selector" in step:
            page.wait_for_selector(step["selector"], timeout=8000); page.click(step["selector"], timeout=8000)
        elif "text" in step:
            page.get_by_text(step["text"]).first.click(timeout=8000)
        elif "role" in step:
            page.get_by_role(step["role"], name=step.get("name")).first.click(timeout=8000)
        else:
            raise ValueError("click requires selector|text|role")
    elif a == "type":
        page.wait_for_selector(step["selector"], timeout=8000)
        page.fill(step["selector"], step["text"], timeout=8000)
        if "search" in step["selector"]: page.keyboard.press("Enter")
    elif a == "wait":
        page.wait_for_selector(step["selector"], timeout=12000)
    elif a == "extract_text":
        page.wait_for_selector(step["selector"], timeout=12000)
        loc = page.locator(step["selector"]).first
        title = (loc.inner_text() or "").strip()
        href = loc.get_attribute("href") or ""
        if href and href.startswith("/"): href = BASE_URL + href.lstrip("/")
        results[step.get("key", "value")] = {"title": title, "url": href}
    else:
        raise ValueError(f"unknown action: {a}")

def main() -> int:
    try:
        snapshot = asyncio.run(mcp_snapshot())
        log(f"snapshot status: {snapshot.get('note','ok')}")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not HEADFUL, args=["--no-sandbox"])
            ctx = browser.new_context()
            page = ctx.new_page()
            results: Dict[str, Any] = {}
            try:
                try:
                    plan = ask_llm_for_plan(snapshot, GOAL)
                    log(f"AI plan accepted ({len(plan)} steps)")
                    for step in plan:
                        exec_step(page, step, results)
                    results["_mode"] = "ai_plan"
                except Exception as e:
                    log(f"Falling back to core helpers ({e.__class__.__name__}: {e})")
                    results = fallback_execute(page)
                    results["_mode"] = "fallback_core"
                print("Success! Results:", json.dumps(results, ensure_ascii=False))
                return 0
            finally:
                with contextlib.suppress(Exception): ctx.close()
                with contextlib.suppress(Exception): browser.close()
    except PWTimeoutError as e:
        print(f"Failure: timeout: {e}"); return 2
    except KeyboardInterrupt:
        print("Failure: interrupted"); return 130
    except (PWError, Exception) as e:
        print(f"Failure: unexpected error: {e}"); return 3

if __name__ == "__main__":
    raise SystemExit(main())
