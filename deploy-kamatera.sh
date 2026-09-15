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
: "${NGROK_AUTHTOKEN:?Set NGROK_AUTHTOKEN before running this script}"
ngrok config add-authtoken "$NGROK_AUTHTOKEN"

# Setup app directory
APP_DIR="/opt/weave"
echo "📁 Setting up $APP_DIR..."
sudo mkdir -p $APP_DIR
sudo chown -R $USER:$USER $APP_DIR

# Clone repository
echo "📥 Cloning repository..."
cd $APP_DIR
REPO_URL="${WEAVE_REPOSITORY_URL:-https://github.com/regnant-io/weave.git}"
if [ -d ".git" ]; then
    echo "Repository exists, pulling latest..."
    git pull --ff-only
else
    git clone "$REPO_URL" .
fi

# Verify clone
if [ ! -f "docker-compose.yml" ]; then
    echo "❌ Error: docker-compose.yml not found"
    echo "Repository may be incomplete. Check: $REPO_URL"
    exit 1
fi

echo "✅ Repository ready"

# Create the root Compose environment.  Compose does not automatically pass a
# backend/.env file into the backend container, so the old script generated
# secrets that the running service never read.
echo "⚙️  Configuring backend..."
WEAVE_SECRET="$(openssl rand -hex 32)"
POSTGRES_SECRET="$(openssl rand -hex 24)"
cat > $APP_DIR/.env << EOF
WEAVE_ENVIRONMENT=production
WEAVE_DEBUG=false
WEAVE_SECRET_KEY=$WEAVE_SECRET
WEAVE_DATABASE_URL=postgresql+psycopg://weave:$POSTGRES_SECRET@postgres:5432/weave
POSTGRES_PASSWORD=$POSTGRES_SECRET
WEAVE_REDIS_URL=redis://redis:6379/0
WEAVE_CORS_ORIGINS=["http://localhost:3000"]
WEAVE_OLLAMA_HOST=http://host.docker.internal:11434
WEAVE_OLLAMA_MODEL=llama3.2:3b
WEAVE_OLLAMA_USE_EMBEDDINGS=true
WEAVE_OLLAMA_EMBED_MODEL=nomic-embed-text
WEAVE_SEARXNG_URL=http://searxng:8080
WEAVE_BROWSERLESS_URL=http://browserless:3000
WEAVE_RENDER_URL=http://render:3100
WEAVE_GOTENBERG_URL=http://gotenberg:3000
WEAVE_CLICKHOUSE_URL=http://clickhouse:8123
WEAVE_ANALYSIS_EXECUTION_ENABLED=false
WEAVE_WORKSPACE_ENABLED=false
EOF
chmod 600 $APP_DIR/.env

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
sudo docker-compose -f docker-compose.yml build

# Start services
echo "🚀 Starting services..."
sudo docker-compose -f docker-compose.yml --profile deep up -d

# Wait for startup
echo "⏳ Waiting for services..."
sleep 30

# Check status
echo ""
echo "📊 Service status:"
sudo docker-compose -f docker-compose.yml ps

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
- View logs: cd $APP_DIR && sudo docker-compose -f docker-compose.yml logs -f
- Restart: cd $APP_DIR && sudo docker-compose -f docker-compose.yml restart
- Stop: cd $APP_DIR && sudo docker-compose -f docker-compose.yml down
- Get ngrok URL: curl -s http://localhost:4040/api/tunnels | grep -o 'https://[^"]*ngrok-free.app' | head -1
EOF

echo ""
echo "=========================================="
echo "✅ Deployment Complete!"
echo "=========================================="
echo ""
echo "🌐 Frontend: $NGROK_URL"
echo "🔧 Backend API (server loopback): http://127.0.0.1:8001"
echo "⚠️  Live voice/canvas sockets require a TLS reverse proxy; see DEPLOY.md"
echo "📚 API docs are disabled in production"
echo ""
echo "📝 Logs: sudo docker-compose -f docker-compose.yml logs -f"
echo "📄 Info: cat $APP_DIR/deployment-info.txt"
echo ""
echo "🎉 Weave is running!"
