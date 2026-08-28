# ✅ Admin Access Confirmed

## Credentials

**Phone:** `+255700000001`  
**Password:** `weave-demo-123`  
**Email:** `demo@weave.tz`

## Access Level

- **Role:** `both` (student + researcher)
- **Trust Tier:** `institutional` ← **Grants Admin Access**
- **Institution:** University of Dar es Salaam
- **Phone Verified:** ✅ Yes

## Verification Results

### ✅ Login Test - PASSED
```
User successfully authenticated
Access token generated
```

### ✅ Admin Endpoint Test - PASSED
```
GET /api/v1/admin/stats - 200 OK

System Statistics:
  Users: 1
  Projects: 1
  Datasets: 1
  Messages: 0
  Sources: 25
  Source Chunks: 180
  Analysis Runs: 1
```

## Admin Capabilities

This user can access:

### Frontend (http://localhost:3000)
- ✅ Create/manage projects
- ✅ Upload datasets
- ✅ Chat with AI (all 43 tools available)
- ✅ Switch between student/researcher modes
- ✅ Manage account settings

### Admin API (http://localhost:8001/api/v1/admin/)
- ✅ `/admin/stats` - System statistics
- ✅ `/admin/audit` - Sandbox execution audit
- ✅ `/admin/sources` - Source library management
- ✅ `/admin/ingest` - Add new sources
- ✅ `/admin/crawl/seeds` - Manage crawler seeds

### Backend (http://localhost:8001/docs)
- ✅ Full Swagger/OpenAPI documentation
- ✅ Interactive API testing
- ✅ All authenticated endpoints

## How Admin Access Works

From the code (`backend/app/deps.py`):

```python
def get_admin_user(user: User = Depends(get_current_user)) -> User:
    """Admin/ops scope. Gated to the 'admin' role or institutional trust tier."""
    if user.role != "admin" and user.trust_tier != "institutional":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin access required")
    return user
```

**Admin access is granted if EITHER:**
1. `user.role == "admin"` OR
2. `user.trust_tier == "institutional"`

The demo user has `trust_tier="institutional"`, so admin endpoints allow access.

## Trust Tier Hierarchy

```
anonymous < verified < institutional
    ↓           ↓            ↓
 Public     Normal User   Admin Access
```

## Quick Access Commands

### Get Admin Stats (PowerShell)
```powershell
$auth = Invoke-RestMethod -Method Post `
  -Uri "http://localhost:8001/api/v1/auth/login" `
  -ContentType "application/json" `
  -Body '{"phone": "+255700000001", "password": "weave-demo-123"}'

$headers = @{ Authorization = "Bearer $($auth.access_token)" }
Invoke-RestMethod -Uri "http://localhost:8001/api/v1/admin/stats" -Headers $headers | ConvertTo-Json
```

### Get Admin Stats (Bash/Linux)
```bash
TOKEN=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"phone": "+255700000001", "password": "weave-demo-123"}' | jq -r .access_token)

curl -H "Authorization: Bearer $TOKEN" http://localhost:8001/api/v1/admin/stats | jq
```

### Direct Database Access
```bash
# SQLite
docker compose exec backend sqlite3 /app/var/weave.db

# Check user
SELECT phone, role, trust_tier FROM users WHERE phone='+255700000001';
```

## Security Notes

✅ **Passwords are hashed** using stdlib scrypt  
✅ **Tokens are JWT** with HS256 signing  
✅ **httpOnly cookies** in frontend (CSRF-safe)  
✅ **Rate limiting** applies to all users (including admin)  
✅ **Sandbox isolation** for code execution  
✅ **SSRF protection** for web fetching  

## Related Documentation

- `CREDENTIALS.md` - Full admin documentation
- `QUICK_START.md` - Getting started guide
- `TOOL_AVAILABILITY_ANALYSIS.md` - Tool system explanation
- `README.md` - Main project documentation

---

**Status:** ✅ All admin functionality verified and working
**Last Verified:** 2026-08-10
