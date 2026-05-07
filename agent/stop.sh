#!/usr/bin/env bash
# Stop all running Agent processes

pkill -f "agent.main" 2>/dev/null || true
echo "Agents stopped."
