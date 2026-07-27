# Weave Deployment Guide for Kamatera Cloud

This guide will help you deploy Weave on a Kamatera cloud server with all services including Ollama, Docker, and ngrok tunneling.

## Prerequisites

- A Kamatera cloud instance (Ubuntu 20.04/22.04 recommended)
- Minimum 8GB RAM, 4 CPU cores, 50GB disk (16GB RAM recommended for heavy usage)
- Root or sudo access
- ngrok auth token (already configured in script)

## Quick Deployment

### 1. Connect to Your Kamatera Server

```bash
ssh root@your-server-ip
```

### 2. Download the Deployment Script

```bash
curl -o deploy-kamatera.sh https://raw.githubusercontent.com/[your-repo]/weave/master/deploy-kamatera.sh
chmod +x deploy-kamatera.sh
```

Or if you have the code locally:

```bash
# Upload the script
scp deploy-kamatera.sh root@your-server-ip:/root/

# Connect and run
ssh root@your-server-ip
chmod +x deploy-kamatera.sh
```

### 3. Run the Deployment Script

```bash
./deploy-kamatera.sh
```

The script will:
- ✅ Update system packages
- ✅ Install Docker & Docker Compose
- ✅ Install ngrok and configure with auth token
- ✅ Install Ollama and pull required models (llama3.2:3b, nomic-embed-text)
- ✅ Clone the Weave repository
- ✅ Create configuration files (.env)
- ✅ Build Docker images
- ✅ Start all services (backend, frontend, PostgreSQL, Qdrant, ClickHouse, MinIO, etc.)
- ✅ Start ngrok tunnel to expose frontend

### 4. Access Your Application

After deployment completes, you'll see:

```
Frontend (ngrok):    https://xxxx-xxx-xxx-xxx.ngrok-free.app
Frontend (local):    http://localhost:3000
Backend API:         http://localhost:8000
```

Visit the ngrok URL to access Weave from anywhere!

## Manual Setup (Alternative)

If you prefer to set up manually or customize the installation:

### 1. Install Docker

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
```

### 2. Install Docker Compose

```bash
DOCKER_COMPOSE_VERSION=$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep 'tag_name' | cut -d\" -f4)
sudo curl -L "https://github.com/docker/compose/releases/download/${DOCKER_COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

### 3. Install Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

### 4. Install ngrok

```bash
curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | sudo tee /etc/apt/sources.list.d/ngrok.list
sudo apt-get update
sudo apt-get install ngrok
ngrok config add-authtoken 3H4wuqzRY3EcfGMJwif0rPscF4I_6h93bQynFGPkb7yRgSpc3
```

### 5. Clone and Configure

```bash
git clone https://gitlab.com/daudi.abinallah/weave.git
cd weave
cp backend/.env.example backend/.env
cp frontend/.env.local.example frontend/.env.local
# Edit .env files as needed
```

### 6. Start Services

```bash
docker-compose --profile deep up -d
ngrok http 3000 &
```

## Service Management

### View Logs

```bash
# All services
cd /opt/weave && docker-compose logs -f

# Specific service
docker-compose logs -f backend
docker-compose logs -f frontend

# ngrok logs
tail -f /opt/weave/ngrok.log
```

### Restart Services

```bash
cd /opt/weave
docker-compose restart

# Restart specific service
docker-compose restart backend
```

### Stop Services

```bash
cd /opt/weave
docker-compose down

# Stop ngrok
pkill ngrok
```

### Update Application

```bash
cd /opt/weave
git pull origin master
docker-compose build
docker-compose up -d
```

## Configuration

### Backend Environment Variables

Located at `/opt/weave/backend/.env`:

- `DATABASE_URL`: PostgreSQL connection string
- `OLLAMA_BASE_URL`: Ollama API endpoint
- `LLM_MODEL`: Language model to use (default: llama3.2:3b)
- `CORS_ORIGINS`: Allowed origins (add your ngrok URL here)

### Frontend Environment Variables

Located at `/opt/weave/frontend/.env.local`:

- `WEAVE_API_BASE`: Backend API URL (for SSR)
- `NEXT_PUBLIC_API_BASE`: Backend API URL (for client)

## Troubleshooting

### Services Not Starting

```bash
# Check Docker logs
docker-compose logs

# Check disk space
df -h

# Check memory
free -h

# Restart Docker
sudo systemctl restart docker
```

### Ollama Not Responding

```bash
# Check Ollama status
sudo systemctl status ollama

# Restart Ollama
sudo systemctl restart ollama

# Test Ollama
curl http://localhost:11434/api/tags
```

### ngrok Tunnel Issues

```bash
# Check ngrok status
curl http://localhost:4040/api/tunnels

# Restart ngrok
pkill ngrok
nohup ngrok http 3000 --log=stdout > /opt/weave/ngrok.log 2>&1 &

# Get new URL
curl -s http://localhost:4040/api/tunnels | grep -o 'https://[^"]*ngrok-free.app' | head -1
```

### Database Connection Issues

```bash
# Check PostgreSQL logs
docker-compose logs postgres

# Access PostgreSQL
docker-compose exec postgres psql -U weave -d weave

# Reset database
docker-compose down -v
docker-compose up -d
```

## Security Recommendations

1. **Change Default Passwords**: Update all passwords in `.env` files
2. **Configure Firewall**: Only expose necessary ports
   ```bash
   sudo ufw allow 22/tcp    # SSH
   sudo ufw allow 80/tcp    # HTTP
   sudo ufw allow 443/tcp   # HTTPS
   sudo ufw enable
   ```
3. **Use HTTPS**: Configure SSL certificate for production
4. **Backup Data**: Regular backups of PostgreSQL, MinIO, and Qdrant data
5. **Update ngrok Auth Token**: Use your own ngrok token for production

## Resource Requirements

### Minimum Configuration
- **CPU**: 4 cores
- **RAM**: 8GB
- **Disk**: 50GB SSD
- **Network**: 100 Mbps

### Recommended Configuration
- **CPU**: 8 cores
- **RAM**: 16GB
- **Disk**: 100GB SSD
- **Network**: 1 Gbps

### Heavy Load Configuration (with all services)
- **CPU**: 16 cores
- **RAM**: 32GB
- **Disk**: 200GB SSD
- **Network**: 1 Gbps

## Service Ports

- **3000**: Frontend (Next.js)
- **8000**: Backend (FastAPI)
- **5432**: PostgreSQL
- **6333**: Qdrant
- **8123**: ClickHouse
- **9000**: MinIO API
- **9001**: MinIO Console
- **11434**: Ollama
- **3001**: Browserless
- **8080**: Render Service / SearXNG
- **4040**: ngrok Web Interface

## Monitoring

### Check Service Health

```bash
# All services
docker-compose ps

# Backend health
curl http://localhost:8000/health

# Frontend health
curl http://localhost:3000

# Ollama health
curl http://localhost:11434/api/tags
```

### System Resources

```bash
# CPU and Memory usage
docker stats

# Disk usage
docker system df

# Logs size
du -sh /var/lib/docker/containers
```

## Backup and Restore

### Backup

```bash
# Backup PostgreSQL
docker-compose exec postgres pg_dump -U weave weave > backup.sql

# Backup MinIO data
docker-compose exec minio mc mirror /data /backup

# Backup Qdrant data
docker-compose exec qdrant tar -czf /backup/qdrant.tar.gz /qdrant/storage
```

### Restore

```bash
# Restore PostgreSQL
docker-compose exec -T postgres psql -U weave weave < backup.sql

# Restore MinIO data
docker-compose exec minio mc mirror /backup /data
```

## Support

For issues or questions:
- Check logs: `docker-compose logs -f`
- Review `/opt/weave/deployment-info.txt` for deployment details
- Contact: admin@weave.local

## License

See [LICENSE](LICENSE) file in the repository.
