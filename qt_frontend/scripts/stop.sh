#!/usr/bin/env bash
# Stop Qt frontend and bridge processes only.
# Does NOT touch roscore/rosmaster — those may belong to other ROS programs
# (e.g. turtlebot3, Gazebo).
# To stop agents, use agent/stop.sh.

pkill -f "qt_frontend/main.py" 2>/dev/null || true
pkill -f "mqtt_ros_bridge" 2>/dev/null || true
pkill -f "static_transform_publisher" 2>/dev/null || true
echo "Stopped."
