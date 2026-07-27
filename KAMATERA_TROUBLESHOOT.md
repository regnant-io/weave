# Kamatera Deployment Troubleshooting

## Current Issue: "no configuration file provided: not found"

This means Docker Compose can't find `docker-compose.yml`. Let's diagnose and fix it.

## Step 1: Check Current Location

Run this on your Kamatera server:

```bash
pwd
ls -la
```

## Step 2: Navigate to Correct Directory

```bash
cd /opt/weave
pwd
ls -la
```

You should see `docker-compose.yml` in the output.

## Step 3: Verify Repository Contents

```bash
cd /opt/weave
git status
git log --oneline -5
```

## Step 4: Re-pull Latest Code

```bash
cd /opt/weave
git pull origin master
```

## Step 5: Manually Create Environment Files

If the directories still don't exist:

```bash
cd /opt/weave
mkdir -p backend frontend

# Create backend .env
cat > backend/.env << 'EOF'
DATABASE_URL=postgresql://weave:weave_secure_pass@postgres:5432/weave
POSTGRES_USER=weave
POSTGRES_PASSWORD=weave_secure_pass
POSTGRES_DB=weave
JWT_SECRET=$(openssl rand -hex 32)
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=10080
OLLAMA_BASE_URL=http://host.docker.internal:11434
LLM_MODEL=llama3.2:3b
EMBEDDING_MODEL=nomic-embed-text
CLICKHOUSE_URL=http://clickhouse:8123
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=weave
QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=
BROWSERLESS_URL=http://browserless:3000
RENDER_SERVICE_URL=http://render:8080
GOTENBERG_URL=http://gotenberg:3000
SEARXNG_URL=http://searxng:8080
ENVIRONMENT=production
API_PREFIX=/api/v1
CORS_ORIGINS=http://localhost:3000,https://*.ngrok-free.app
ADMIN_PHONE=+255700000000
ADMIN_EMAIL=admin@weave.local
RATE_LIMIT_PER_MINUTE=60
OTP_SECRET=$(openssl rand -hex 16)
OTP_EXPIRE_SECONDS=300
SANDBOX_BACKEND=host
SANDBOX_TIMEOUT=30
EOF

# Create frontend .env.local
cat > frontend/.env.local << 'EOF'
WEAVE_API_BASE=http://backend:8000
NEXT_PUBLIC_API_BASE=http://localhost:8000
NEXT_TELEMETRY_DISABLED=1
EOF
```

## Step 6: Build Docker Images

```bash
cd /opt/weave
sudo docker-compose build
```

If this fails, check:

1. **Docker is running:**
   ```bash
   sudo systemctl status docker
   ```

2. **Docker Compose version:**
   ```bash
   docker-compose --version
   ```

3. **Disk space:**
   ```bash
   df -h
   ```

## Step 7: Start Services

```bash
cd /opt/weave
sudo docker-compose --profile deep up -d
```

## Step 8: Check Service Status

```bash
cd /opt/weave
sudo docker-compose ps
sudo docker-compose logs -f
```

## Step 9: Start ngrok

```bash
# Kill any existing ngrok
pkill ngrok

# Start new tunnel
nohup ngrok http 3000 --log=stdout > /opt/weave/ngrok.log 2>&1 &

# Wait a moment
sleep 5

# Get URL
curl -s http://localhost:4040/api/tunnels | grep -o 'https://[^"]*ngrok-free.app' | head -1
```

## Common Issues and Solutions

### Issue: "docker-compose: command not found"

```bash
# Check installation
which docker-compose

# If not found, reinstall
sudo curl -L "https://github.com/docker/compose/releases/download/v2.24.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

### Issue: "permission denied"

Add your user to docker group:
```bash
sudo usermod -aG docker $USER
newgrp docker
```

Or use `sudo` before docker commands.

### Issue: Port already in use

Check what's using the ports:
```bash
sudo netstat -tulpn | grep -E '3000|8000|5432'

# Kill conflicting processes if needed
sudo kill <PID>
```

### Issue: Out of disk space

```bash
# Check space
df -h

# Clean up Docker
sudo docker system prune -a --volumes
```

### Issue: Ollama not responding

```bash
# Check status
sudo systemctl status ollama

# Restart
sudo systemctl restart ollama

# Test
curl http://localhost:11434/api/tags
```

## Quick Commands Reference

```bash
# View all logs
cd /opt/weave && sudo docker-compose logs -f

# View specific service
sudo docker-compose logs -f backend
sudo docker-compose logs -f frontend

# Restart a service
sudo docker-compose restart backend

# Stop all services
sudo docker-compose down

# Start all services
sudo docker-compose --profile deep up -d

# Rebuild and restart
sudo docker-compose build && sudo docker-compose --profile deep up -d

# Check ngrok URL
curl -s http://localhost:4040/api/tunnels | jq '.tunnels[0].public_url'
# Or without jq:
curl -s http://localhost:4040/api/tunnels | grep -o 'https://[^"]*ngrok-free.app' | head -1
```

## Still Having Issues?

1. Check the repository was cloned correctly:
   ```bash
   cd /opt/weave
   ls -la
   # Should see: docker-compose.yml, backend/, frontend/, etc.
   ```

2. Verify files were pushed to GitLab:
   Visit https://gitlab.com/daudi.abinallah/weave

3. Check server resources:
   ```bash
   free -h    # Memory
   df -h      # Disk space
   top        # CPU usage
   ```

4. Review full logs:
   ```bash
   journalctl -xeu docker.service
   sudo docker-compose logs --tail=100
   ```
