#!/bin/bash
set -e

echo "🔄 Rebuilding frontend with ALL fixes..."

cd /opt/weave

# Pull latest code
echo "📥 Pulling latest code..."
git fetch origin
git reset --hard origin/master

# Stop frontend
echo "🛑 Stopping frontend..."
sudo docker-compose stop frontend

# Remove old frontend container and image
echo "🗑️  Removing old frontend container and image..."
sudo docker-compose rm -f frontend
sudo docker rmi weave-frontend 2>/dev/null || true

# Clear Docker build cache
echo "🧹 Clearing Docker build cache..."
sudo docker builder prune -f

# Rebuild frontend from scratch
echo "🏗️  Building frontend (this takes a few minutes)..."
sudo docker-compose build --no-cache --pull frontend

# Start frontend
echo "🚀 Starting frontend..."
sudo docker-compose up -d frontend

# Wait for it to start
echo "⏳ Waiting for frontend to start..."
sleep 10

# Show logs
echo "📋 Frontend logs:"
sudo docker-compose logs --tail=50 frontend

echo ""
echo "✅ Frontend rebuilt successfully!"
echo ""
echo "🌐 Access your site and hard refresh (Ctrl+Shift+R or Cmd+Shift+R)"
echo "📱 On iPad: Close Safari completely and reopen"
