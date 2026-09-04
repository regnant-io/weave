# The Workspace Image: Developer Sandbox Explained

## What It Is

The **workspace image** (`weave-workspace:latest`) is a Docker container where the AI **builds real software** for users - installing dependencies, running tests, downloading assets, and packaging results.

## 🚨 Critical Design: Two Separate Sandboxes

Weave has **TWO different sandboxes** that must NEVER be merged:

### 1. Analysis Sandbox (`services/sandbox`) - Data Protection
**Purpose:** Run model-written Python against user's **private datasets**

**Restrictions:**
- ❌ **NO network** - Cannot fetch external data
- ❌ **NO file I/O** - Cannot use `open()` or file paths
- ❌ **Import allowlist** - Only pandas/numpy/scipy/matplotlib
- ❌ **Destroyed after each run** - Workspace wiped between executions
- ✅ Read-only dataset access via `weave_io.load_dataset()`
- ✅ Output via `weave_io.save_output()` only

**Why:** Prevents model from exfiltrating sensitive research data

### 2. Developer Workspace (`services/workspace`) - Software Building
**Purpose:** Build complete applications, games, visualizations

**Capabilities:**
- ✅ **Network enabled** - Can `npm install`, `pip install`, download assets
- ✅ **Persistent filesystem** - Changes survive across turns/chats
- ✅ **Arbitrary executables** - Can run any tool in the container
- ✅ **Real development workflow** - Install, build, test, package
- ✅ Read/write any file in project workspace
- ❌ **No access to user datasets** - Completely isolated from data

**Why:** Software development **requires** dependencies, builds, and the internet

## The Trade-off

> "Giving the second capability to the first would silently remove the protection around the user's data, so they stay separate."

If the analysis sandbox had network + persistence, a model could:
1. Read sensitive dataset via `load_dataset()`
2. POST it to an external server
3. User's private research data is leaked

## The Workspace Image

### Base Image
```dockerfile
FROM node:20-bookworm-slim
```

**Why Node as base:**
- Most modern dev tooling (bundlers, frameworks) runs on Node
- Includes npm/npx out of the box
- Debian Bookworm has good package availability

### What's Inside

#### Languages & Runtimes
- **Node 20** - JavaScript/TypeScript runtime
- **Python 3** with pip - Python projects
- **Git** - Clone repos, manage versions

#### Build Tools (Pre-installed for speed)
```bash
# Global npm packages (avoid cold-start delays)
typescript@5      # TS compiler
tsx@4            # TypeScript execution
esbuild@0.24     # Super-fast bundler
vite@5           # Frontend build tool
serve@14         # Static file server

# Python packages
requests         # HTTP client
pytest           # Testing
black, ruff      # Linting/formatting
pillow           # Image processing
```

#### Media Processing
- **ImageMagick** - Image manipulation
- **ffmpeg** - Video/audio processing

#### Headless Browser Dependencies
Chromium libraries for:
- Screenshot generation
- Smoke-testing generated apps
- PDF rendering

All without needing a full browser install.

### Security Configuration

Every container runs with hardened settings:

```bash
docker run --rm -i \
  --user 1000:1000 \              # Non-root (uid 1000 = 'node' user)
  --security-opt no-new-privileges \  # Cannot elevate privileges
  --cap-drop ALL \                # No Linux capabilities
  --memory 2048m \                # Hard memory limit
  --cpus 2 \                      # CPU quota
  --pids-limit 512 \              # Process limit (prevents fork bombs)
  --network bridge \              # Internet access (configurable)
  -v /host/path:/workspace \      # Only workspace is writable
  weave-workspace:latest bash -lc "npm install"
```

**What this prevents:**
- ❌ Cannot become root
- ❌ Cannot access other containers/host
- ❌ Cannot bind privileged ports (<1024)
- ❌ Cannot spawn unlimited processes
- ❌ Cannot consume unbounded memory
- ❌ Cannot read/write outside `/workspace`

### Container Lifecycle

```
User request → Backend starts container → Command executes → Container destroyed
              ↑                                              ↓
              └──────────── Only /workspace survives ────────┘
```

**Key:**
- Containers are `--rm` (removed on exit)
- Only the bind-mounted `/workspace` persists
- Each project gets its own directory on the host
- Directory survives across turns, chats, and backend restarts

## How It Works

### 1. Building the Image

```powershell
# Build once (takes a few minutes first time)
docker compose --profile build-images build workspace-image

# Or manually
docker build -t weave-workspace:latest ./workspace-image
```

**What happens:**
- Downloads Node 20 base (~200MB)
- Installs system packages (~100MB)
- Pre-installs npm/pip tools (~150MB)
- **Total: ~450MB** (reasonable for a dev environment)

### 2. File Operations (No Container Needed)

File operations run **directly on the host** in `backend/var/workspaces/{project_id}/`:

```python
# Fast - no Docker overhead
workspace_write(path="src/main.js", content="...")   # Write to disk
workspace_read(path="src/main.js")                   # Read from disk
workspace_edit(path="src/main.js", find="...", replace="...")  # Edit in place
workspace_list()                                      # List directory
```

**Path traversal protection:** `_resolve()` ensures paths can't escape via:
- `../../../etc/passwd`
- Symlinks pointing outside
- Windows drive letters
- Absolute paths

### 3. Command Execution (Starts Container)

Only `workspace_exec` spins up a container:

```python
# Starts a throwaway container
workspace_exec(command="npm install")
workspace_exec(command="npm run build")
workspace_exec(command="pytest tests/")
```

**What the backend does:**
```python
docker run --rm -i \
  --workdir /workspace \
  -v /host/projects/abc123:/workspace \  # Bind mount project dir
  --user 1000:1000 --cap-drop ALL \
  weave-workspace:latest bash -lc "npm install"
```

**Result:**
- Command runs inside container
- Can install packages, download files
- Changes written to `/workspace` persist on host
- Container removed after completion
- Project directory remains intact

### 4. Auto-Verification

After every `workspace_write` or `workspace_edit`, the file is **automatically** checked:

```python
# Built-in verification (user doesn't call this)
verify_result = verify_file(path="src/main.js")

if not verify_result["valid"]:
    return {
        "status": "ok",
        "path": "src/main.js",
        "verified": False,
        "verify_error": "line 42: unexpected token '}'",
        "hint": "The file you just wrote does not parse. Read it back and fix it."
    }
```

**Checkers:**
- **Python:** `ast.parse()` - catches syntax errors
- **JSON:** `json.loads()` - validates structure
- **JavaScript/TypeScript:** `node --check` - uses Node's parser
- **Others:** Structural balance (braces, brackets, quotes)

**Why:** Catches truncated or malformed output before the user sees it.

## Available Tools

The AI orchestrator has **10 workspace tools**:

| Tool | Purpose | Needs Container? |
|------|---------|------------------|
| `workspace_list` | List directory tree | No |
| `workspace_write` | Create/overwrite file | No |
| `workspace_read` | Read file (optionally line range) | No |
| `workspace_edit` | Replace exact string in file | No |
| `workspace_delete` | Delete file/directory | No |
| `workspace_move` | Rename/move file | No |
| `workspace_glob` | Find files by pattern | No |
| `workspace_grep` | Search text with regex | No |
| `workspace_exec` | **Run shell command** | **Yes** |
| `workspace_verify` | Check file parses | Sometimes |
| `workspace_package` | Create .tar.gz download | No |

Only `workspace_exec` needs Docker. Everything else is **instant**.

## Real-World Workflows

### Example 1: Build a React App

```
User: "Build me a React todo app"

workspace_write(path="package.json", content='{...}')
workspace_write(path="src/App.jsx", content='...')
workspace_write(path="src/index.html", content='...')
workspace_exec(command="npm install")                    # Downloads React
workspace_exec(command="npm run build")                  # Bundles app
workspace_exec(command="npm test")                       # Runs tests
workspace_package(name="todo-app", path="dist")         # Creates artifact

Result: User downloads working React app as .tar.gz
```

### Example 2: Build a 3D Game Scene

```
User: "Make me a 3D maze game"

workspace_write(path="index.html", content='<!DOCTYPE html>...')
workspace_write(path="game.js", content='// Babylon.js code')
workspace_exec(command="curl -o models/maze.glb https://...")  # Download 3D model
workspace_verify(path="game.js")                         # Check syntax
workspace_exec(command="node game.js --validate")       # Smoke test
workspace_package(name="maze-game")                     # Package for download

Result: Self-contained HTML game with inlined assets
```

### Example 3: Python Data Pipeline

```
User: "Build a data cleaning pipeline"

workspace_write(path="clean.py", content='import pandas...')
workspace_write(path="requirements.txt", content='pandas\nnumpy')
workspace_write(path="tests/test_clean.py", content='def test_...')
workspace_exec(command="pip install -r requirements.txt")
workspace_exec(command="pytest tests/")                 # Run tests
workspace_verify(path="clean.py")                       # AST check
workspace_package(name="pipeline")

Result: Tested Python package
```

## Configuration

### Environment Variables (`.env` or `docker-compose.yml`)

```bash
# Enable/disable workspace
WEAVE_WORKSPACE_ENABLED=true    # Set false to disable entirely

# Container image
WEAVE_WORKSPACE_IMAGE=weave-workspace:latest

# Resource limits
WEAVE_WORKSPACE_MEMORY_MB=2048  # Max RAM per container
WEAVE_WORKSPACE_CPUS=2          # CPU quota
WEAVE_WORKSPACE_PIDS_LIMIT=512  # Max processes

# Timeouts
WEAVE_WORKSPACE_EXEC_TIMEOUT=180      # Default command timeout (seconds)
WEAVE_WORKSPACE_EXEC_MAX_TIMEOUT=600  # Maximum allowed timeout

# Network
WEAVE_WORKSPACE_NETWORK=true          # Enable internet access
WEAVE_WORKSPACE_NETWORK_MODE=bridge   # Docker network mode

# Storage
WEAVE_WORKSPACE_ROOT=/app/var/workspaces  # Host directory for projects
WEAVE_WORKSPACE_PACKAGE_MAX_BYTES=100000000  # 100MB tar.gz limit

# Output
WEAVE_WORKSPACE_OUTPUT_CHARS=12000    # Truncate long logs
```

### Checking Availability

```bash
# API endpoint
curl http://localhost:8001/api/v1/workspace/status

# Returns:
{
  "enabled": true,
  "docker_available": true,
  "image": "weave-workspace:latest",
  "workspace_root": "/app/var/workspaces"
}
```

### Rebuilding the Image

If you modify the Dockerfile:

```powershell
# Rebuild
docker compose --profile build-images build workspace-image

# Force rebuild from scratch
docker compose --profile build-images build --no-cache workspace-image
```

## Security Considerations

### ✅ Safe By Design

1. **Non-root execution** - Cannot escalate privileges
2. **Capability drop** - All Linux capabilities removed
3. **Resource limits** - Cannot DoS the host
4. **Path validation** - Cannot escape workspace
5. **Container isolation** - Cannot access other projects/containers
6. **Ephemeral containers** - Removed after every exec

### ⚠️ Trust Requirements

The workspace is gated to **verified users** (`trust_tier >= "verified"`):

```python
"requires_services": ("workspace",),
"trust_required": "verified"
```

**Why:**
- Can run arbitrary shell commands
- Has network access
- Could install malicious packages
- Could attempt to fingerprint/probe the host

### 🔒 When to Disable

Set `WEAVE_WORKSPACE_ENABLED=false` if:
- Exposing Weave to **untrusted users**
- Running on a shared host with sensitive neighbors
- Don't want AI installing packages
- Docker is unavailable

**What happens:**
- Workspace tools report `"status": "unavailable"`
- Tools are **not advertised** to the model
- AI knows it can't build software
- User gets clear error messages

## Performance

### Benchmarks (Intel i5, 16GB RAM)

| Operation | Time | Notes |
|-----------|------|-------|
| `workspace_write` | <10ms | Direct disk write |
| `workspace_read` | <10ms | Direct disk read |
| `workspace_list` (500 files) | ~50ms | Directory walk |
| `workspace_grep` | 100-500ms | Depends on file count |
| **`workspace_exec("npm install")`** | 10-60s | Network + package install |
| `workspace_exec("npm run build")` | 5-30s | CPU-bound |
| `workspace_exec("pytest")` | 1-10s | Depends on tests |
| `workspace_package` | 1-5s | tar.gz compression |

**Optimization:** Pre-installed tools (`typescript`, `esbuild`) skip install time.

### Resource Usage

**Idle:** 0 (no containers running between commands)

**During exec:**
- CPU: Up to quota (default 2 cores)
- RAM: Up to limit (default 2GB)
- Disk I/O: Host filesystem speed

**Storage growth:**
- ~5-50MB per small project (source only)
- ~100-500MB after `npm install` (with node_modules)
- Cleared with `workspace_reset()` or manually

## Troubleshooting

### Image Not Found

```
Error: workspace execution unavailable (Docker image not found)
```

**Fix:**
```powershell
docker compose --profile build-images build workspace-image
```

### Docker Not Available

```
Error: workspace execution unavailable (Docker not installed)
```

**Fix:**
1. Install Docker Desktop (Windows/Mac)
2. Enable Docker daemon
3. Restart backend: `docker compose restart backend`
4. Check: `curl http://localhost:8001/api/v1/workspace/status`

### Permission Errors in Container

```
Error: EACCES permission denied, mkdir '/workspace/node_modules'
```

**Why:** UID mismatch between host and container.

**Fix:** Container runs as UID 1000 (`node` user). Ensure workspace dir is writable:
```powershell
# On host (if needed)
docker compose exec backend chown -R 1000:1000 /app/var/workspaces
```

### Command Timeout

```
status: "timeout", error: "command exceeded 180s limit"
```

**Fix:** Pass larger timeout:
```python
workspace_exec(command="npm install", timeout=600)  # 10 minutes
```

### Out of Memory

```
Error: container killed (OOMKilled)
```

**Fix:** Increase limit in `.env`:
```bash
WEAVE_WORKSPACE_MEMORY_MB=4096  # 4GB
```

## Comparison with Analysis Sandbox

| Feature | Analysis Sandbox | Developer Workspace |
|---------|------------------|---------------------|
| **Purpose** | Analyze user datasets | Build software |
| **Network** | ❌ Blocked | ✅ Enabled |
| **Persistence** | ❌ Destroyed after run | ✅ Survives across turns |
| **File I/O** | ❌ No `open()` | ✅ Full read/write |
| **Imports** | Allowlist only | ✅ Install anything |
| **Dataset access** | ✅ Via `weave_io` | ❌ None |
| **Runtime** | Subprocess | Docker container |
| **Trust required** | `verified` | `verified` |
| **Security focus** | Protect data | Isolate execution |

**Key insight:** They protect different things:
- Analysis sandbox protects **user data** from exfiltration
- Developer workspace protects **host system** from malicious code

## Related Documentation

- `TOOL_AVAILABILITY_ANALYSIS.md` - How tools are conditionally enabled
- `QUICK_START.md` - Getting started with Weave
- `backend/app/services/workspace/service.py` - Implementation
- `backend/app/services/sandbox/runner.py` - Analysis sandbox (comparison)

---

**The workspace image enables the AI to be a real developer, not just a code generator. It can install dependencies, run tests, verify builds, and deliver working software - not just text files.**

## ✅ Current Status (Your System)

**Image Built:** ✅ `weave-workspace:latest` (445MB, ID: 17913c9781ad)  
**Docker Available:** ✅ Docker daemon is running  
**Status:** ⚠️ **Workspace execution is DISABLED**

### Why Disabled?

The workspace service is likely disabled because it requires explicit Docker socket access. Check your `docker-compose.yml` backend service:

```yaml
backend:
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock  # Required for workspace
```

On Windows/Docker Desktop, the socket path might need adjustment.

### Enable It

1. **Check configuration:**
   ```powershell
   docker compose config | Select-String -Pattern "docker.sock"
   ```

2. **Verify environment variable:**
   ```powershell
   docker compose exec backend printenv | Select-String -Pattern "WORKSPACE"
   ```

3. **Force refresh:**
   ```powershell
   # Restart backend to re-probe Docker
   docker compose restart backend
   
   # Test again
   curl http://localhost:8001/api/v1/workspace/status
   ```

4. **If still disabled:** The backend container may not have permission to access the Docker socket. This is a common security restriction on Windows/Docker Desktop.

### Workaround: File-Only Mode

Even with exec disabled, **8 of 10 workspace tools still work:**

✅ Available (no Docker needed):
- `workspace_write` - Create files
- `workspace_read` - Read files
- `workspace_edit` - Edit files
- `workspace_list` - List directory
- `workspace_delete` - Delete files
- `workspace_move` - Rename/move
- `workspace_glob` - Find files by pattern
- `workspace_grep` - Search with regex

❌ Unavailable (needs Docker):
- `workspace_exec` - Run commands (npm install, tests, builds)
- `workspace_package` - Create tar.gz (uses tar command)

The AI can still **write complete applications**, just can't install dependencies or run tests automatically.
