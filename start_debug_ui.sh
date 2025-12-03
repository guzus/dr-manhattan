#!/bin/bash

# Dr Manhattan Debug Dashboard Launcher
# Starts both backend API and frontend servers

set -e

echo "Starting Dr Manhattan Debug Dashboard..."
echo ""

echo "Starting Backend API on port 8000..."
uv run python api/server.py &
BACKEND_PID=$!

echo "Waiting for backend to start..."
sleep 3

echo "Starting Frontend on port 3000..."
cd frontend
npm run dev &
FRONTEND_PID=$!

echo ""
echo "Dashboard started successfully!"
echo ""
echo "Backend API: http://localhost:8000"
echo "Frontend UI: http://localhost:3000"
echo "API Docs:    http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop both servers"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT

wait
