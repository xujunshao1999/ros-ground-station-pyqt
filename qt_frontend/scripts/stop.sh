#!/usr/bin/env bash
# Stop all Qt frontend and bridge processes

pkill -f "qt_frontend/main.py" 2>/dev/null || true
pkill -f "mqtt_ros_bridge.py" 2>/dev/null || true
echo "Stopped."
