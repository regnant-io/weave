#!/bin/bash
# Quick fix script for the Kamatera deployment issue

echo "🔧 Fixing Weave deployment..."

# Go to app directory
cd /opt/weave

# Pull latest changes with the fix
echo "📥 Pulling latest deployment script..."
git pull origin master

# Create directories if they don't exist
echo "📁 Creating necessary directories..."
mkdir -p /opt/weave/backend
mkdir -p /opt/weave/frontend

# Re-run just the env file creation part
echo "⚙️  Creating backend .env file..."
cat > /opt/weave/backend/.env << 'EOF'
# Database
DATABASE_URL=postgresql://weave:weave_secure_pass@postgres:5432/weave
POSTGRES_USER=weave
POSTGRES_PASSWORD=weave_secure_pass
POSTGRES_DB=weave

# Security
JWT_SECRET=$(openssl rand -hex 32)
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=10080

# Ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
LLM_MODEL=llama3.2:3b
EMBEDDING_MODEL=nomic-embed-text

# ClickHouse (for analytics)
CLICKHOUSE_URL=http://clickhouse:8123
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=

# MinIO (S3-compatible storage)
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=weave

# Qdrant (vector database)
QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=

# External services (optional but recommended for production)
BROWSERLESS_URL=http://browserless:3000
RENDER_SERVICE_URL=http://render:8080
GOTENBERG_URL=http://gotenberg:3000

# SearXNG (private search)
SEARXNG_URL=http://searxng:8080

# Application
ENVIRONMENT=production
API_PREFIX=/api/v1
CORS_ORIGINS=http://localhost:3000,https://*.ngrok-free.app
ADMIN_PHONE=+255700000000
ADMIN_EMAIL=admin@weave.local
RATE_LIMIT_PER_MINUTE=60

# OTP (for phone verification)
OTP_SECRET=$(openssl rand -hex 16)
OTP_EXPIRE_SECONDS=300

# Sandbox
SANDBOX_BACKEND=host
SANDBOX_TIMEOUT=30
EOF

echo "⚙️  Creating frontend .env.local file..."
cat > /opt/weave/frontend/.env.local << 'EOF'
WEAVE_API_BASE=http://backend:8000
NEXT_PUBLIC_API_BASE=http://localhost:8000
NEXT_TELEMETRY_DISABLED=1
EOF

echo "✅ Environment files created"

# Continue with the rest of the deployment
echo ""
echo "🚀 Continuing deployment..."
echo ""

# Install Ollama if not already installed
if ! command -v ollama &> /dev/null; then
    echo "🤖 Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    systemctl enable ollama
    systemctl start ollama
fi

# Wait for Ollama
sleep 5

# Pull models
echo "📥 Pulling Ollama models..."
ollama pull llama3.2:3b
ollama pull nomic-embed-text

# Build and start services
echo "🏗️  Building Docker images..."
cd /opt/weave
docker-compose build

echo "🚀 Starting all services..."
docker-compose --profile deep up -d

# Wait for services
sleep 30

# Check status
echo ""
echo "📊 Service Status:"
docker-compose ps

# Start ngrok
echo ""
echo "🌐 Starting ngrok tunnel..."
pkill ngrok 2>/dev/null || true
nohup ngrok http 3000 --log=stdout > /opt/weave/ngrok.log 2>&1 &
sleep 5

# Get ngrok URL
NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | grep -o 'https://[^"]*ngrok-free.app' | head -1)

echo ""
echo "=========================================="
echo "✅ Deployment Fixed and Complete!"
echo "=========================================="
echo ""
echo "📍 Access Your Application:"
echo "  Frontend (ngrok):    $NGROK_URL"
echo "  Frontend (local):    http://localhost:3000"
echo "  Backend API:         http://localhost:8000"
echo "  Backend Docs:        http://localhost:8000/docs"
echo ""
echo "📝 View Logs:"
echo "  docker-compose logs -f"
echo ""
echo "🎉 Weave is now running!"
