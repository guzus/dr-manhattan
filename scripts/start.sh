#!/bin/bash

# Polymarket Trading Bot Startup Script

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Polymarket Trading Bot ===${NC}"
echo ""

# Check if .env exists
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}Warning: .env file not found. Copying from config/.env.example${NC}"
    cp config/.env.example .env
    echo "Please edit .env file with your API keys before running."
    exit 1
fi

# Function to start development mode
start_dev() {
    echo -e "${GREEN}Starting in development mode...${NC}"

    # Start PostgreSQL with Docker
    echo "Starting PostgreSQL..."
    docker-compose -f docker/docker-compose.yml up -d postgres

    # Wait for DB
    echo "Waiting for database..."
    sleep 5

    # Start backend
    echo "Starting backend API..."
    cd /home/lee/decipher/agent_trading
    python -m uvicorn dashboard.backend.main:app --host 0.0.0.0 --port 8000 --reload &
    BACKEND_PID=$!

    # Start frontend
    echo "Starting frontend..."
    cd dashboard/frontend
    npm install
    npm run dev &
    FRONTEND_PID=$!

    echo ""
    echo -e "${GREEN}Services started!${NC}"
    echo "Backend API: http://localhost:8000"
    echo "Frontend Dashboard: http://localhost:3001"
    echo ""
    echo "Press Ctrl+C to stop all services"

    # Wait for interrupt
    trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; docker-compose -f docker/docker-compose.yml down; exit" SIGINT SIGTERM
    wait
}

# Function to start with Docker Compose
start_docker() {
    echo -e "${GREEN}Starting with Docker Compose...${NC}"
    docker-compose -f docker/docker-compose.yml up --build
}

# Function to run single trading cycle
run_cycle() {
    echo -e "${GREEN}Running single trading cycle...${NC}"
    python main.py
}

# Parse arguments
case "${1:-dev}" in
    dev)
        start_dev
        ;;
    docker)
        start_docker
        ;;
    cycle)
        run_cycle
        ;;
    *)
        echo "Usage: $0 {dev|docker|cycle}"
        echo ""
        echo "  dev     - Start in development mode (default)"
        echo "  docker  - Start with Docker Compose"
        echo "  cycle   - Run single trading cycle"
        exit 1
        ;;
esac
