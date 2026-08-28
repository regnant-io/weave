# Weave Admin Credentials

## 🔐 Demo User (Has Admin Access)

The seeded demo user has **institutional trust tier**, which grants admin access:

**Phone:** `+255700000001`  
**Password:** `weave-demo-123`  
**Email:** `demo@weave.tz`  
**Role:** `both` (student + researcher)  
**Trust Tier:** `institutional` ← **This grants admin access**  
**Institution:** University of Dar es Salaam

## 🛡️ Admin Access Rules

From `backend/app/deps.py`:

```python
def get_admin_user(user: User = Depends(get_current_user)) -> User:
    """Admin/ops scope. Gated to the 'admin' role or institutional trust tier."""
    if user.role != "admin" and user.trust_tier != "institutional":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin access required")
    return user
```

**Admin access is granted if EITHER:**
- `role == "admin"` OR
- `trust_tier == "institutional"`

The demo user has `trust_tier="institutional"`, so it **has admin access**.

## 📍 Admin Endpoints

Available at: http://localhost:8001/api/v1/admin/

### GET /admin/stats
System statistics - user count, projects, datasets, messages, sources, etc.

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8001/api/v1/admin/stats
```

### GET /admin/audit
Sandbox execution audit log (last 50 runs)

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8001/api/v1/admin/audit
```

### GET /admin/sources
List all ingested sources in the library

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8001/api/v1/admin/sources
```

### POST /admin/ingest
Ingest a new URL into the source library

```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/paper.pdf"}' \
  http://localhost:8001/api/v1/admin/ingest
```

### GET /admin/crawl/seeds
List crawler seeds (domains to monitor)

### POST /admin/crawl/seeds
Add a new crawl seed

### PUT /admin/crawl/seeds/:id
Update crawl seed status (enable/disable)

## 🔑 How to Get Bearer Token

### Option 1: Login via API
```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"phone": "+255700000001", "password": "weave-demo-123"}' \
  http://localhost:8001/api/v1/auth/login
```

Response:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user": {
    "id": "...",
    "phone": "+255700000001",
    "role": "both",
    "trust_tier": "institutional"
  }
}
```

### Option 2: Login via Frontend
1. Open http://localhost:3000
2. Click "Login"
3. Enter phone: `+255700000001`
4. Enter password: `weave-demo-123`
5. Open browser DevTools → Application → Cookies
6. Find `weave_token` cookie - that's your bearer token

### Option 3: PowerShell Script
```powershell
$response = Invoke-RestMethod -Method Post `
  -Uri "http://localhost:8001/api/v1/auth/login" `
  -ContentType "application/json" `
  -Body '{"phone": "+255700000001", "password": "weave-demo-123"}'

$token = $response.access_token
Write-Host "Bearer Token: $token"

# Use it:
$headers = @{ Authorization = "Bearer $token" }
Invoke-RestMethod -Uri "http://localhost:8001/api/v1/admin/stats" -Headers $headers
```

## 👥 Creating Additional Admin Users

There are two ways to grant admin access:

### Method 1: Set role to "admin"
```python
user.role = "admin"
```

### Method 2: Set trust_tier to "institutional"
```python
user.trust_tier = "institutional"
user.institution_id = <institution_id>
```

### Trust Tiers
- `anonymous` - Lowest, rate-limited
- `verified` - Phone verified (most users)
- `institutional` - Affiliated with institution, **grants admin access**

### Roles
- `student` - Socratic teaching mode
- `researcher` - Direct analytical mode
- `both` - Can switch between modes
- `admin` - **Grants admin access** (currently unused in seed)

## 🔒 Security Notes

- Admin endpoints are protected by `get_admin_user()` dependency
- JWT tokens expire (check `JWT_EXPIRY_HOURS` in config)
- Tokens are httpOnly cookies in the frontend
- SMS OTP verification in production (logs to console in dev)
- Rate limits apply even to admin users

## 📝 Database Access

If you need direct database access:

```bash
# SQLite (default)
docker compose exec backend sqlite3 /app/var/weave.db

# List users
SELECT phone, role, trust_tier FROM users;

# Make user admin
UPDATE users SET role='admin' WHERE phone='+255700000001';
```

Or with Python:
```bash
docker compose exec backend python
>>> from app.db import SessionLocal
>>> from app.models import User
>>> db = SessionLocal()
>>> user = db.query(User).filter(User.phone=="+255700000001").first()
>>> print(f"Role: {user.role}, Trust: {user.trust_tier}")
>>> user.role = "admin"
>>> db.commit()
```

## 🎯 Quick Admin Check

Verify admin access works:

```powershell
# Login
$auth = Invoke-RestMethod -Method Post `
  -Uri "http://localhost:8001/api/v1/auth/login" `
  -ContentType "application/json" `
  -Body '{"phone": "+255700000001", "password": "weave-demo-123"}'

# Test admin endpoint
$headers = @{ Authorization = "Bearer $($auth.access_token)" }
$stats = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/admin/stats" -Headers $headers
$stats | ConvertTo-Json
```

Expected output: System statistics JSON (not 403 Forbidden)
