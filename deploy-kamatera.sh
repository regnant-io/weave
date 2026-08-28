#!/bin/bash
set -e

echo "=========================================="
echo "Weave - Kamatera Cloud Deployment"
echo "=========================================="
echo ""

# Update system
echo "📦 Updating system..."
sudo apt-get update -qq
sudo apt-get upgrade -y -qq

# Install essentials
echo "📦 Installing essentials..."
sudo apt-get install -y -qq apt-transport-https ca-certificates curl gnupg lsb-release git unzip wget

# Install Docker
echo "🐳 Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker $USER
    echo "✅ Docker installed"
else
    echo "✅ Docker already installed"
fi

# Install Docker Compose
echo "🐳 Installing Docker Compose..."
if ! command -v docker-compose &> /dev/null; then
    sudo curl -L "https://github.com/docker/compose/releases/download/v2.24.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    echo "✅ Docker Compose installed"
else
    echo "✅ Docker Compose already installed"
fi

# Start Docker
sudo systemctl enable docker
sudo systemctl start docker

# Install ngrok
echo "🌐 Installing ngrok..."
if ! command -v ngrok &> /dev/null; then
    curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
    echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | sudo tee /etc/apt/sources.list.d/ngrok.list
    sudo apt-get update -qq
    sudo apt-get install -y ngrok
    echo "✅ ngrok installed"
else
    echo "✅ ngrok already installed"
fi

# Configure ngrok
echo "🔑 Configuring ngrok..."
ngrok config add-authtoken 3H4wuqzRY3EcfGMJwif0rPscF4I_6h93bQynFGPkb7yRgSpc3

# Setup app directory
APP_DIR="/opt/weave"
echo "📁 Setting up $APP_DIR..."
sudo mkdir -p $APP_DIR
sudo chown -R $USER:$USER $APP_DIR

# Clone repository
echo "📥 Cloning repository..."
cd $APP_DIR
if [ -d ".git" ]; then
    echo "Repository exists, pulling latest..."
    git fetch origin
    git reset --hard origin/master
else
    git clone https://gitlab.com/daudi.abinallah/weave.git .
fi

# Verify clone
if [ ! -f "docker-compose.yml" ]; then
    echo "❌ Error: docker-compose.yml not found"
    echo "Repository may be incomplete. Check: https://gitlab.com/daudi.abinallah/weave"
    exit 1
fi

echo "✅ Repository ready"

# Create backend directory and .env
echo "⚙️  Configuring backend..."
mkdir -p $APP_DIR/backend
cat > $APP_DIR/backend/.env << 'EOF'
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

# Create frontend directory and .env
echo "⚙️  Configuring frontend..."
mkdir -p $APP_DIR/frontend
cat > $APP_DIR/frontend/.env.local << 'EOF'
WEAVE_API_BASE=http://backend:8000
NEXT_PUBLIC_API_BASE=http://localhost:8000
NEXT_TELEMETRY_DISABLED=1
EOF

# Install Ollama
echo "🤖 Installing Ollama..."
if ! command -v ollama &> /dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
    sudo systemctl enable ollama
    sudo systemctl start ollama
    echo "✅ Ollama installed"
else
    echo "✅ Ollama already installed"
fi

# Wait for Ollama
sleep 5

# Pull models
echo "📥 Pulling AI models (this takes a while)..."
ollama pull llama3.2:3b
ollama pull nomic-embed-text
echo "✅ Models ready"

# Build images
echo "🏗️  Building Docker images..."
cd $APP_DIR
sudo docker-compose build

# Start services
echo "🚀 Starting services..."
sudo docker-compose --profile deep up -d

# Wait for startup
echo "⏳ Waiting for services..."
sleep 30

# Check status
echo ""
echo "📊 Service status:"
sudo docker-compose ps

# Start ngrok
echo ""
echo "🌐 Starting ngrok tunnel..."
pkill ngrok 2>/dev/null || true
nohup ngrok http 3000 --log=stdout > $APP_DIR/ngrok.log 2>&1 &
sleep 5

# Get URL
NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | grep -o 'https://[^"]*ngrok-free.app' | head -1)

# Save deployment info
cat > $APP_DIR/deployment-info.txt << EOF
Deployment: $(date)
Ngrok URL: $NGROK_URL
Server IP: $(curl -s ifconfig.me)
Directory: $APP_DIR

Commands:
- View logs: cd $APP_DIR && sudo docker-compose logs -f
- Restart: cd $APP_DIR && sudo docker-compose restart
- Stop: cd $APP_DIR && sudo docker-compose down
- Get ngrok URL: curl -s http://localhost:4040/api/tunnels | grep -o 'https://[^"]*ngrok-free.app' | head -1
EOF

echo ""
echo "=========================================="
echo "✅ Deployment Complete!"
echo "=========================================="
echo ""
echo "🌐 Frontend: $NGROK_URL"
echo "🔧 Backend API: http://localhost:8000"
echo "📚 API Docs: http://localhost:8000/docs"
echo ""
echo "📝 Logs: sudo docker-compose logs -f"
echo "📄 Info: cat $APP_DIR/deployment-info.txt"
echo ""
echo "🎉 Weave is running!"
