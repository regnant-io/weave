# Weave Quick Start Guide

## 🚀 Current Status

All services are running with full capabilities enabled!

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8001
- **API Docs**: http://localhost:8001/docs
- **SearXNG**: http://localhost:8888

## 📦 Services Running

```bash
docker compose ps
```

Expected output:
- ✅ `weave-backend-1` - FastAPI backend
- ✅ `weave-frontend-1` - Next.js frontend
- ✅ `weave-searxng-1` - Web search metasearch engine
- ✅ `weave-browserless-1` - Headless Chrome for web scraping
- ✅ `weave-render-1` - Chart/3D/presentation rendering
- ✅ `weave-minio-1` - Object storage
- ✅ `weave-qdrant-1` - Vector database
- ✅ `weave-clickhouse-1` - Analytics warehouse
- ✅ `weave-gotenberg-1` - PDF generation

## 🛠️ Available Tools (43 total)

### Core Research
- `run_analysis` - Execute Python data analysis
- `search_library` - Search Tanzanian academic sources
- `check_citation` - Check for predatory journals

### Web Search (✅ Enabled)
- `web_search` - Search the live web
- `fetch_url` - Read specific web pages
- `deep_research` - Iterative research with multiple sources

### Visualizations (✅ Enabled)
- `generate_visual` - Create Vega-Lite charts
- `generate_deck` - Build presentations
- `create_3d_experience` - Interactive Babylon.js scenes
- `generate_3d` - Three.js 3D visualizations
- `create_diagram` - Structured diagrams
- `create_simulation` - Interactive simulations
- `create_animation` - Animated explanations

### Memory & Collaboration
- `remember` / `recall` / `forget` - Cross-chat project memory
- `ask_user` - Interactive questions
- `canvas_*` - Shared document editing

### Developer Workspace (✅ Enabled)
- `workspace_write/read/edit/list/move/delete` - File operations
- `workspace_exec` - Run commands (npm, pip, tests)
- `workspace_verify` - Syntax checking
- `workspace_package` - Export as tarball

### Data Warehouse
- `query_warehouse` - SQL queries over datasets

## 🔧 Common Commands

### Start everything
```powershell
docker compose --profile deep up -d
```

### Stop everything
```powershell
docker compose down
```

### View logs
```powershell
# All services
docker compose logs -f

# Specific service
docker compose logs -f backend
docker compose logs -f searxng
```

### Restart a service
```powershell
docker compose restart backend
docker compose restart frontend
```

### Check service health
```powershell
Invoke-RestMethod -Uri "http://localhost:8001/health" | ConvertTo-Json
```

### Access containers
```powershell
# Backend shell
docker compose exec backend /bin/bash

# Run tests
docker compose exec backend pytest
```

## 🎯 Demo Login (Has Admin Access)

**Phone:** `+255700000001`  
**Password:** `weave-demo-123`  
**Email:** `demo@weave.tz`  
**Trust Tier:** `institutional` (grants admin access)

This user can access:
- All frontend features
- Admin dashboard: http://localhost:8001/api/v1/admin/
- See `CREDENTIALS.md` for full admin documentation

## 🔍 Troubleshooting

### Backend not starting?
```powershell
# Check logs
docker compose logs backend

# Rebuild
docker compose build backend
docker compose up -d backend
```

### Services not detected?
1. Check `.env` file exists with service URLs
2. Verify services are running: `docker compose ps`
3. Restart backend: `docker compose restart backend`
4. Check health: `Invoke-RestMethod http://localhost:8001/health`

### SearXNG not responding?
```powershell
# Check if it's running
docker compose logs searxng

# Restart it
docker compose restart searxng
```

### Clear everything and start fresh
```powershell
docker compose down -v  # -v removes volumes
docker compose --profile deep up --build -d
```

## 📝 Configuration Files

- `.env` - Environment variables (service URLs, API keys)
- `docker-compose.yml` - Service definitions
- `backend/app/config.py` - Backend settings
- `searxng/settings.yml` - SearXNG configuration

## 🔐 Security Notes

- **Workspace execution** (`workspace_exec`) runs containers on your host - disable with `WEAVE_WORKSPACE_ENABLED=false` if exposing to untrusted users
- **Docker socket** is mounted for workspace - privilege escalation risk
- **SearXNG** fetches untrusted web content - SSRF protections are in place
- **SMS OTP** logs to console in dev mode (set `WEAVE_SMS_PROVIDER` for production)

## 📊 Resource Requirements

Minimal (no deep profile):
- CPU: 2 cores
- RAM: 2GB
- Disk: 5GB

Full (deep profile):
- CPU: 4+ cores
- RAM: 8GB+ (Chromium/Babylon.js are heavy)
- Disk: 20GB+

## 🎓 Next Steps

1. Open http://localhost:3000
2. Login with demo credentials
3. Create a project
4. Upload a dataset (CSV/XLSX/JSON)
5. Ask the AI to analyze it - watch it use `run_analysis`
6. Ask about Tanzanian research - watch it use `search_library`
7. Ask to search the web - watch it use `web_search` and `deep_research`
8. Ask for a visualization - watch it use `generate_visual`
9. Build something - watch it use `workspace_*` tools

All 43 tools are now available to the orchestrator! 🎉
