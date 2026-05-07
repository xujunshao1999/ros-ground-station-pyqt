#!/usr/bin/env bash
# Stop all Qt frontend, bridge, and ROS processes

pkill -f "qt_frontend/main.py" 2>/dev/null || true
pkill -f "mqtt_ros_bridge.py" 2>/dev/null || true
pkill -f "agent.main" 2>/dev/null || true
pkill -f "roscore" 2>/dev/null || true
pkill -f "rosmaster" 2>/dev/null || true
echo "Stopped."
