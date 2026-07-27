#!/bin/bash
set -e

# Weave Deployment Script for Kamatera Cloud
# This script sets up the complete Weave environment with all services

echo "=========================================="
echo "Weave Deployment Script for Kamatera Cloud"
echo "=========================================="
echo ""

# Update system
echo "📦 Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

# Install required packages
echo "📦 Installing required packages..."
sudo apt-get install -y \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    git \
    unzip \
    wget

# Install Docker
echo "🐳 Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    rm get-docker.sh
    echo "✅ Docker installed"
else
    echo "✅ Docker already installed"
fi

# Install Docker Compose
echo "🐳 Installing Docker Compose..."
if ! command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE_VERSION=$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep 'tag_name' | cut -d\" -f4)
    sudo curl -L "https://github.com/docker/compose/releases/download/${DOCKER_COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    echo "✅ Docker Compose installed"
else
    echo "✅ Docker Compose already installed"
fi

# Start Docker service
echo "🔄 Starting Docker service..."
sudo systemctl enable docker
sudo systemctl start docker

# Install ngrok
echo "🌐 Installing ngrok..."
if ! command -v ngrok &> /dev/null; then
    curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
    echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | sudo tee /etc/apt/sources.list.d/ngrok.list
    sudo apt-get update
    sudo apt-get install -y ngrok
    echo "✅ ngrok installed"
else
    echo "✅ ngrok already installed"
fi

# Configure ngrok with auth token
echo "🔑 Configuring ngrok..."
ngrok config add-authtoken 3H4wuqzRY3EcfGMJwif0rPscF4I_6h93bQynFGPkb7yRgSpc3

# Create application directory
APP_DIR="/opt/weave"
echo "📁 Creating application directory at $APP_DIR..."
sudo mkdir -p $APP_DIR
sudo chown -R $USER:$USER $APP_DIR

# Clone repository
echo "📥 Cloning Weave repository..."
cd $APP_DIR
if [ -d ".git" ]; then
    echo "Repository already exists, pulling latest changes..."
    git pull origin master
else
    # Replace with actual GitLab URL once created
    # git clone https://gitlab.com/daudi.abinallah/weave.git .
    echo "⚠️  Repository URL will be added after GitLab project creation"
    echo "For now, you'll need to upload the code manually or use git clone"
fi

# Create .env file for backend
echo "⚙️  Creating backend .env file..."
cat > $APP_DIR/backend/.env << 'EOF'
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

# Create .env file for frontend
echo "⚙️  Creating frontend .env.local file..."
cat > $APP_DIR/frontend/.env.local << 'EOF'
WEAVE_API_BASE=http://backend:8000
NEXT_PUBLIC_API_BASE=http://localhost:8000
NEXT_TELEMETRY_DISABLED=1
EOF

# Install Ollama
echo "🤖 Installing Ollama..."
if ! command -v ollama &> /dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
    echo "✅ Ollama installed"
else
    echo "✅ Ollama already installed"
fi

# Start Ollama service
echo "🔄 Starting Ollama service..."
sudo systemctl enable ollama
sudo systemctl start ollama

# Wait for Ollama to be ready
echo "⏳ Waiting for Ollama to be ready..."
sleep 5

# Pull required models
echo "📥 Pulling Ollama models (this may take a while)..."
ollama pull llama3.2:3b
ollama pull nomic-embed-text

# Build Docker images
echo "🏗️  Building Docker images..."
cd $APP_DIR
sudo docker-compose build

# Start services with all profiles
echo "🚀 Starting all services..."
sudo docker-compose --profile deep up -d

# Wait for services to be ready
echo "⏳ Waiting for services to be healthy..."
sleep 30

# Check service status
echo "📊 Service Status:"
sudo docker-compose ps

# Get the frontend container IP
FRONTEND_PORT=3000

# Start ngrok in the background
echo "🌐 Starting ngrok tunnel..."
nohup ngrok http $FRONTEND_PORT --log=stdout > $APP_DIR/ngrok.log 2>&1 &
sleep 5

# Get ngrok public URL
NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | grep -o 'https://[^"]*ngrok-free.app' | head -1)

echo ""
echo "=========================================="
echo "✅ Deployment Complete!"
echo "=========================================="
echo ""
echo "📍 Service Endpoints:"
echo "  Frontend (ngrok):    $NGROK_URL"
echo "  Frontend (local):    http://localhost:$FRONTEND_PORT"
echo "  Backend API:         http://localhost:8000"
echo "  Backend Docs:        http://localhost:8000/docs"
echo "  MinIO Console:       http://localhost:9001"
echo "  Qdrant Dashboard:    http://localhost:6333/dashboard"
echo "  ClickHouse:          http://localhost:8123"
echo "  Ollama:              http://localhost:11434"
echo ""
echo "📝 Logs:"
echo "  View all logs:       cd $APP_DIR && sudo docker-compose logs -f"
echo "  View backend logs:   cd $APP_DIR && sudo docker-compose logs -f backend"
echo "  View frontend logs:  cd $APP_DIR && sudo docker-compose logs -f frontend"
echo "  View ngrok logs:     tail -f $APP_DIR/ngrok.log"
echo ""
echo "🔧 Management:"
echo "  Stop services:       cd $APP_DIR && sudo docker-compose down"
echo "  Restart services:    cd $APP_DIR && sudo docker-compose restart"
echo "  Update code:         cd $APP_DIR && git pull && sudo docker-compose build && sudo docker-compose up -d"
echo ""
echo "📊 System Resources:"
df -h | grep -E 'Filesystem|/$'
free -h
echo ""
echo "⚠️  Important Notes:"
echo "  1. Update CORS_ORIGINS in backend/.env to include your ngrok URL"
echo "  2. Update NEXT_PUBLIC_API_BASE in frontend/.env.local if needed"
echo "  3. Create an admin account via: sudo docker-compose exec backend python -m app.seed.seed"
echo "  4. Monitor logs for any errors"
echo "  5. ngrok URL changes on restart - check $APP_DIR/ngrok.log for new URL"
echo ""
echo "🔐 Default Credentials:"
echo "  MinIO:  minioadmin / minioadmin"
echo "  Admin user will be created on first run"
echo ""
echo "=========================================="

# Save deployment info
cat > $APP_DIR/deployment-info.txt << EOF
Deployment Date: $(date)
Ngrok URL: $NGROK_URL
Server IP: $(curl -s ifconfig.me)
App Directory: $APP_DIR

To get current ngrok URL:
curl -s http://localhost:4040/api/tunnels | grep -o 'https://[^"]*ngrok-free.app' | head -1

To restart ngrok:
pkill ngrok
nohup ngrok http $FRONTEND_PORT --log=stdout > $APP_DIR/ngrok.log 2>&1 &
EOF

echo "📄 Deployment info saved to: $APP_DIR/deployment-info.txt"
echo ""
echo "🎉 Weave is now running! Visit $NGROK_URL to access the application."
