# Tool Availability Analysis: Why AI Says It Doesn't Have Tools

## The Problem

The AI (orchestrator) sometimes claims it doesn't have access to tools like `web_search`, `remote_web_search`, or rendering tools (`create_3d_experience`, `generate_3d`, etc.) even though they are defined in the codebase.

## Root Cause

Tools are **conditionally available** based on whether their backing services are configured and enabled. The system has a sophisticated service dependency system that hides tools when their required services aren't running.

## How Tool Availability Works

### 1. Tool Registration (`backend/app/services/tools/builtin.py`)

Each tool declares its dependencies:

```python
reg.register(Tool(
    name="web_search",
    description="Search the live web via SearXNG...",
    execute=_web_search,
    trust_required="verified",
    requires_services=("websearch",),  # ← REQUIRES SERVICE
))
```

### 2. Service Check (`backend/app/services/tools/base.py:97-105`)

The `ToolRegistry.available()` method filters tools:

```python
def available(self, *, mode: str, trust: str, services: dict[str, Any],
              intent: str | None = None) -> list[Tool]:
    for t in self._tools.values():
        # ... other checks ...
        
        # THIS IS THE KEY CHECK:
        if any(s not in services or services[s] is None 
               for s in t.requires_services):
            continue  # Tool is HIDDEN if service not available
            
        out.append(t)
    return out
```

### 3. Service Initialization (`backend/app/services/orchestration/orchestrator.py:213-242`)

Services are only added if they're enabled:

```python
services = {
    "analysis": self.analysis,
    "retrieval": self.retrieval,
    "memory": self.memory
}

web = get_web_search()
if web.enabled:  # ← Only added if enabled
    services["websearch"] = web

render = get_render()
if render.enabled:  # ← Only added if enabled
    services["render"] = render
```

### 4. Service Configuration (`backend/app/config.py`)

Services are enabled based on environment variables:

```python
# SearXNG metasearch (JSON API). Empty -> web search tool reports unavailable.
searxng_url: str | None = os.getenv("WEAVE_SEARXNG_URL")

# Render service
render_url: str | None = os.getenv("WEAVE_RENDER_URL")

# Browserless for headless Chrome
browserless_url: str | None = os.getenv("WEAVE_BROWSERLESS_URL")
```

## Tool Dependencies

| Tool | Required Service | Environment Variable |
|------|------------------|---------------------|
| `web_search` | `websearch` | `WEAVE_SEARXNG_URL` |
| `fetch_url` | `websearch` | `WEAVE_SEARXNG_URL` |
| `deep_research` | `websearch` | `WEAVE_SEARXNG_URL` + `WEAVE_BROWSERLESS_URL` |
| `generate_visual` | `render` | `WEAVE_RENDER_URL` |
| `generate_deck` | `render` | `WEAVE_RENDER_URL` |
| `create_3d_experience` | `render` | `WEAVE_RENDER_URL` |
| `generate_3d` | `render` | `WEAVE_RENDER_URL` |
| `query_warehouse` | `warehouse` | DuckDB/ClickHouse config |
| `workspace_*` | `workspace` | Docker availability |
| `run_analysis` | `analysis` | Always available (built-in) |
| `search_library` | `retrieval` | Always available (built-in) |

## Why the AI Says "I don't have web search"

When the AI says this, it's being **accurate** - the tools literally aren't in its tool list because:

1. **SearXNG is not configured**: `WEAVE_SEARXNG_URL` is not set
2. **Service check fails**: `get_web_search()` returns a service with `enabled=False`
3. **Tool is filtered out**: The registry's `available()` method excludes `web_search`
4. **Not advertised to LLM**: Tool schemas sent to the model don't include it

## The Confusion: Two Different "Web Search" Concepts

### 1. Kiro's Built-in `remote_web_search` (This System Prompt)
- Part of **Kiro IDE's** tools
- Available in this conversation context
- For general web research

### 2. Weave's `web_search` (The Application Being Built)
- Part of the **Weave application** being developed
- Requires self-hosted SearXNG
- Only available when services are running
- Used by Weave's students/researchers

The AI in the example was **correctly** saying it doesn't have Weave's `web_search` tool while **still having access** to Kiro's `remote_web_search`.

## How to Enable Deep Services

From the README:

```bash
# Start the heavy services
docker compose --profile deep up -d

# Configure backend to use them (Bash/Linux)
WEAVE_SEARXNG_URL=http://searxng:8080 \
WEAVE_BROWSERLESS_URL=http://browserless:3000 \
WEAVE_RENDER_URL=http://render:3100 \
  docker compose up -d backend
```

**For PowerShell (Windows):**

```powershell
# Start the heavy services
docker compose --profile deep up -d

# Configure backend to use them
$env:WEAVE_SEARXNG_URL="http://searxng:8080"
$env:WEAVE_BROWSERLESS_URL="http://browserless:3000"
$env:WEAVE_RENDER_URL="http://render:3100"
docker compose up -d backend
```

Or as a one-liner:

```powershell
$env:WEAVE_SEARXNG_URL="http://searxng:8080"; $env:WEAVE_BROWSERLESS_URL="http://browserless:3000"; $env:WEAVE_RENDER_URL="http://render:3100"; docker compose up -d backend
```

## Checking What's Available

The `/health` endpoint reports enabled services and tools:

```bash
curl http://localhost:8000/health
```

Returns:
```json
{
  "llm_engine": "ollama",
  "embedding_backend": "ollama",
  "tools": ["run_analysis", "search_library", "check_citation", ...]
}
```

## Best Practice: Graceful Degradation

The tool execution code checks availability at runtime:

```python
def _web_search(ctx: ToolContext, inp: dict) -> dict:
    client = ctx.services.get("websearch")
    if client is None or not client.enabled:
        return {
            "status": "unavailable",
            "message": "web search (SearXNG) not configured",
            "results": []
        }
    # ... actual search logic ...
```

This ensures:
- The system always boots (no hard dependencies)
- Clear error messages when services are missing
- Orchestrator can fall back to available tools

## Solution Summary

**The AI is not lying or confused** - it's accurately reporting what tools are in its registry based on running services. To "give it" web search:

1. Start SearXNG: `docker compose --profile deep up -d`
2. Create a `.env` file with the service URLs
3. Restart backend: `docker compose restart backend`

The tool will then appear in the orchestrator's tool list and be advertised to the LLM.

## ✅ Verification (Your System)

After configuration, your `/health` endpoint now shows:

```json
{
  "llm_engine": "ollama",
  "tools": [
    "web_search",          // ✅ NOW AVAILABLE
    "fetch_url",           // ✅ NOW AVAILABLE  
    "deep_research",       // ✅ NOW AVAILABLE
    "generate_visual",     // ✅ NOW AVAILABLE
    "generate_deck",       // ✅ NOW AVAILABLE
    "create_3d_experience", // ✅ NOW AVAILABLE
    "generate_3d",         // ✅ NOW AVAILABLE
    // ... 43 tools total
  ],
  "capabilities": {
    "web_search": true,       // ✅
    "browserless": true,      // ✅
    "render_service": true,   // ✅
    "warehouse": true,        // ✅
    "gotenberg": false        // Not configured (optional)
  }
}
```

**All deep-capability tools are now enabled!** The AI orchestrator will have access to web search, rendering, and 3D creation tools.
