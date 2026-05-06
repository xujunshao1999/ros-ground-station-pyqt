#!/usr/bin/env bash
# ============================================================
# Mosquitto MQTT Broker 启动脚本 (Linux/macOS)
# ROS 地面站项目
# ============================================================

set -e

echo "[ROS Ground Station] Starting MQTT Broker..."

# 检查 mosquitto 是否安装
if command -v mosquitto &> /dev/null; then
    MOSQUITTO_PATH=$(command -v mosquitto)
else
    echo "[ERROR] Mosquitto not found!"
    echo ""
    echo "Please install Mosquitto:"
    echo "  Ubuntu/Debian: sudo apt install mosquitto"
    echo "  macOS: brew install mosquitto"
    echo ""
    echo "Or use the Python fallback broker:"
    echo "  pip install amqtt"
    echo "  python broker/start_pybroker.py"
    exit 1
fi

echo "[ROS Ground Station] Found Mosquitto: $MOSQUITTO_PATH"
echo "[ROS Ground Station] Config: broker/mosquitto.conf"
echo "[ROS Ground Station] Press Ctrl+C to stop"
echo ""

# Linux 下可能需要 sudo 运行（默认使用 1883 端口）
mosquitto -c broker/mosquitto.conf -v
