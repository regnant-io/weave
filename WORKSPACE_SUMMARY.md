# Workspace Image - Quick Summary

## What It Does

The workspace image is a **Docker container** where the AI **builds real software** - not just generates code, but:

- ✅ Installs npm/pip packages
- ✅ Downloads assets and 3D models
- ✅ Runs tests
- ✅ Builds applications
- ✅ Packages results as downloadable tarballs

## Why Two Sandboxes?

Weave has **two separate sandboxes** that must NEVER be combined:

### 1️⃣ Analysis Sandbox (Data Protection)
- **Purpose:** Run Python on user's **private datasets**
- **Restrictions:** NO network, NO file I/O, import allowlist
- **Why:** Prevents AI from exfiltrating research data

### 2️⃣ Developer Workspace (Software Building)
- **Purpose:** Build applications, games, tools
- **Capabilities:** Network, persistence, arbitrary packages
- **Why:** Real development needs dependencies and internet

**Critical:** If the data sandbox had network access, the AI could steal datasets. If the dev workspace had dataset access, same risk. They **must** stay separate.

## What's Inside the Image

```dockerfile
Base: Node 20 (Debian Bookworm)
Size: ~445MB

Pre-installed:
  - Node 20 + npm
  - Python 3 + pip
  - Git, curl, build tools
  - TypeScript, esbuild, vite
  - pytest, black, ruff, pillow
  - ImageMagick, ffmpeg
  - Chromium dependencies
```

**Why pre-install?** Avoids 90-second cold-start delays when AI first runs `npm install`.

## Security Model

Every container runs with:

```bash
--user 1000:1000              # Non-root
--cap-drop ALL                # No privileges
--security-opt no-new-privileges
--memory 2048m                # RAM limit
--cpus 2                      # CPU limit
--pids-limit 512              # Process limit
--network bridge              # Internet (configurable)
-v /workspace                 # Only workspace is writable
```

**Cannot:**
- ❌ Become root
- ❌ Access other containers/host
- ❌ Spawn unlimited processes
- ❌ Use unbounded memory
- ❌ Read/write outside workspace

## Available Tools (10 Total)

| Tool | Fast? | Needs Docker? |
|------|-------|---------------|
| `workspace_list` | ⚡ <10ms | No |
| `workspace_write` | ⚡ <10ms | No |
| `workspace_read` | ⚡ <10ms | No |
| `workspace_edit` | ⚡ <10ms | No |
| `workspace_delete` | ⚡ <10ms | No |
| `workspace_move` | ⚡ <10ms | No |
| `workspace_glob` | ⚡ ~50ms | No |
| `workspace_grep` | ⚡ 100-500ms | No |
| `workspace_exec` | 🐢 10-60s | **Yes** |
| `workspace_package` | ⚡ 1-5s | No |

Only `workspace_exec` (running commands) needs Docker. Everything else is instant file operations.

## Real Example: Build a React App

```javascript
// What the AI does:
1. workspace_write("package.json", '{...}')          // 10ms
2. workspace_write("src/App.jsx", '...')             // 10ms
3. workspace_exec("npm install")                     // 30s (downloads React)
4. workspace_exec("npm run build")                   // 15s (bundles app)
5. workspace_exec("npm test")                        // 5s (runs tests)
6. workspace_package("my-app", "dist")              // 2s (creates .tar.gz)

// User downloads working React app!
```

## Your System Status

**Image:** ✅ Built (`weave-workspace:latest`, 445MB)  
**Docker:** ✅ Available  
**Status:** ⚠️ **Workspace execution currently disabled**

### Why Disabled?

Backend needs Docker socket access to start containers:

```yaml
# docker-compose.yml
backend:
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock
```

On Windows/Docker Desktop, this may have permission issues.

### What Still Works (Even Disabled)

**8 of 10 tools work without Docker:**
- Write/read/edit files ✅
- List directory ✅
- Search/grep ✅
- Delete/move ✅

**What doesn't work:**
- Can't run `npm install` ❌
- Can't run tests ❌
- Can't run builds ❌

**Result:** AI can generate complete source code, but can't install dependencies or verify it builds.

## Configuration

### Enable/Disable

```bash
# .env
WEAVE_WORKSPACE_ENABLED=true   # Set false to disable entirely
```

### Resource Limits

```bash
WEAVE_WORKSPACE_MEMORY_MB=2048     # 2GB RAM
WEAVE_WORKSPACE_CPUS=2             # 2 cores
WEAVE_WORKSPACE_PIDS_LIMIT=512     # Max processes
```

### Timeouts

```bash
WEAVE_WORKSPACE_EXEC_TIMEOUT=180       # 3 minutes default
WEAVE_WORKSPACE_EXEC_MAX_TIMEOUT=600   # 10 minutes max
```

### Check Status

```powershell
# Via API
curl http://localhost:8001/api/v1/workspace/status

# Via health endpoint
curl http://localhost:8001/health | jq .capabilities.workspace
```

## When to Disable

Set `WEAVE_WORKSPACE_ENABLED=false` if:

- 🚨 Exposing to **untrusted users**
- 🚨 Running on shared infrastructure
- 🚨 Don't want AI installing packages
- 🚨 Docker unavailable/restricted

**What happens:**
- Workspace tools report "unavailable"
- AI knows it can't build software
- File operations still work (8 tools)
- Clear error messages to users

## Performance

| Operation | Time |
|-----------|------|
| Write file | <10ms |
| Read file | <10ms |
| List 500 files | ~50ms |
| `npm install` | 10-60s (network) |
| Build | 5-30s (CPU) |
| Tests | 1-10s |

**Storage:**
- Small project: ~5-50MB
- After `npm install`: ~100-500MB
- Growth is per-project, isolated

## Key Differences from Analysis Sandbox

| | Analysis | Workspace |
|---|----------|-----------|
| **Purpose** | Analyze datasets | Build software |
| **Network** | ❌ | ✅ |
| **Persistence** | ❌ | ✅ |
| **File I/O** | ❌ | ✅ |
| **Dataset access** | ✅ | ❌ |
| **Imports** | Allowlist | Any |
| **Trust model** | Protect data | Isolate execution |

**They protect different assets and must stay separate.**

## Related Docs

- `WORKSPACE_IMAGE_EXPLAINED.md` - Full technical deep-dive (6000+ words)
- `TOOL_AVAILABILITY_ANALYSIS.md` - How tools are conditionally enabled
- `QUICK_START.md` - Getting started guide

---

**Bottom line:** The workspace image turns the AI into a real developer who can build, test, and ship working software - not just generate code files. It's one of Weave's most powerful capabilities, carefully designed to be both capable and secure.
