# Local development access

Weave seeds one convenience account only when `WEAVE_ENVIRONMENT` is neither
`staging` nor `production`:

- Phone: `+255700000001`
- Password: `weave-demo-123`
- Role: `admin`
- Trust tier: `institutional`

The `admin` role grants access to `/api/v1/admin/*`. An institutional trust tier
does not grant administrative access. Trust controls capability eligibility;
role controls authorization.

Staging and production do not create this public account. Startup also refuses
to run in a deployed environment if an older database still contains the known
demo phone number. Provision production administrators through a controlled
operator workflow and store their credentials outside the repository. The
supported command is:

```bash
docker-compose -f docker-compose.yml exec backend \
  python -m app.cli create-admin --phone '+255700000000'
```

For local login:

```powershell
$login = Invoke-RestMethod -Method Post `
  -Uri "http://localhost:8001/api/v1/auth/login" `
  -ContentType "application/json" `
  -Body '{"phone":"+255700000001","password":"weave-demo-123"}'

$headers = @{ Authorization = "Bearer $($login.access_token)" }
Invoke-RestMethod -Uri "http://localhost:8001/api/v1/admin/stats" -Headers $headers
```

Never reuse these development credentials outside a local instance.
