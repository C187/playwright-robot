# Playwright Robot (Python) — Core + AI/MCP

Automates a browser with Playwright to perform a fixed, single task on **lacity.gov** — running a site search (default `"311"`) and printing the first organic result (title and URL).  
Includes an optional AI-driven agent that plans steps dynamically through **MCP** (Model Context Protocol) with a safe fallback to the deterministic core flow.

---

## Features
- **Core:** deterministic Playwright automation; robust selectors; retries; clear final result.  
- **AI + MCP (optional):** connects to a local Playwright MCP server, requests a structured JSON plan from an LLM, executes it, and falls back to core helpers on invalid plans.  
- **Reliability:** timeouts, retries, cookie-banner dismissal, direct search fallback, headful/headless toggle.  
- **Security:** API key read from environment; never hardcoded.

---

## Repository Layout
```
app/
  core_robot.py      - Core: deterministic search + console output
  mcp_agent.py       - Optional: AI/MCP agent with fallback to core helpers
  robot_utils.py     - Shared helpers: retries, selectors, result extraction
requirements.txt
.env.example          - Sample environment variables
```

---

## Prerequisites
- Python 3.10+
- Node.js 18+ (for the MCP server)

---

## Quick Start

1. **Create and activate a virtual environment**
   ```
   python -m venv .venv
   source .venv/bin/activate
   ```

2. **Install dependencies**
   ```
   pip install -r requirements.txt
   python -m playwright install chromium
   ```

3. **(Optional) Enable headful mode**
   ```
   export HEADFUL=1
   ```

---

## Run the Core (deterministic)
```
python -m app.core_robot
```

**Example output:**
```
[robot] goto homepage
[robot] search mode: ui
Success! Query='311' | First result: MyLA311 | City of Los Angeles | URL: https://lacity.gov/...
```

---

## Run the AI/MCP Agent (optional)

1. **Start the MCP server**
   ```
   npx --yes @playwright/mcp@latest --port 11000
   ```

2. **Set environment variables and run**
   ```
   export OPENAI_API_KEY="..."          # Required for live AI planning
   export MCP_SERVER_URL="http://localhost:11000/sse"
   python -m app.mcp_agent
   ```

**Output includes a mode flag:**
- `"_mode": "ai_plan"` → executed the LLM’s plan  
- `"_mode": "fallback_core_ui"` or `"_mode": "fallback_core_direct"` → used deterministic helpers

---

## Obtaining an OpenAI API Key

To use the **AI/MCP agent**, you need an OpenAI API key.

1. Go to [https://platform.openai.com/api-keys](https://platform.openai.com/api-keys).  
2. Sign in or create a free account. 
3. If you have a free account you must setup billing. 
4. Click **“Create new secret key.”**  
5. Copy the key (starts with `sk-...`).  
6. Set it in your environment before running:
   ```
   export OPENAI_API_KEY="sk-yourkeyhere"
   ```

Without this key, the MCP agent will still run but will fall back to deterministic (non-AI) mode.

---

## Environment Variables

| Variable | Description | Default |
|-----------|-------------|----------|
| `SEARCH_QUERY` | Search term for the site | `311` |
| `HEADFUL` | Set to `1` to see browser actions | `0` |
| `OPENAI_API_KEY` | Required for AI mode | *(none)* |
| `MCP_SERVER_URL` | MCP endpoint | `http://localhost:11000/sse` |
| `MODEL` | LLM model name | `gpt-4o-mini` |
| `GOAL` | Natural language goal for AI agent | optional |

---

## License
MIT
