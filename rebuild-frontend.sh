#!/bin/bash
set -e

echo "🔄 Rebuilding frontend with ALL fixes..."

cd /opt/weave

# Pull latest code
echo "📥 Pulling latest code..."
git pull --ff-only

# Rebuild frontend from scratch
echo "🏗️  Building frontend (this takes a few minutes)..."
sudo docker-compose -f docker-compose.yml build --no-cache --pull frontend

# Start frontend
echo "🚀 Starting frontend..."
sudo docker-compose -f docker-compose.yml up -d --no-deps frontend

# Wait for it to start
echo "⏳ Waiting for frontend to start..."
sleep 10

# Show logs
echo "📋 Frontend logs:"
sudo docker-compose -f docker-compose.yml logs --tail=50 frontend

echo ""
echo "✅ Frontend rebuilt successfully!"
echo ""
echo "🌐 Access your site and hard refresh (Ctrl+Shift+R or Cmd+Shift+R)"
echo "📱 On iPad: Close Safari completely and reopen"
