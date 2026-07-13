#!/usr/bin/env bash
set -euo pipefail

# 构建 Qt 前端嵌入 RViz 所需的 librviz_widget.so。
# 默认使用 ROS Noetic 标准安装路径；非标准环境可通过 ROS_SETUP 覆盖。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
NATIVE_DIR="$PROJECT_ROOT/qt_frontend/native"
BUILD_DIR="$PROJECT_ROOT/qt_frontend/native/build"
ROS_SETUP="${ROS_SETUP:-/opt/ros/noetic/setup.bash}"
JOBS="${JOBS:-$(nproc)}"

if [ ! -f "$ROS_SETUP" ]; then
    echo "[rviz-widget] ROS setup not found: $ROS_SETUP" >&2
    echo "[rviz-widget] Set ROS_SETUP=/path/to/setup.bash for non-standard ROS installs." >&2
    exit 1
fi

source "$ROS_SETUP"

if [ ! -f "$NATIVE_DIR/CMakeLists.txt" ]; then
    echo "[rviz-widget] CMakeLists.txt not found: $NATIVE_DIR" >&2
    exit 1
fi

mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

echo "[rviz-widget] Configuring in $BUILD_DIR"
cmake ..

echo "[rviz-widget] Building with $JOBS job(s)"
make -j"$JOBS"

if [ ! -f "$BUILD_DIR/librviz_widget.so" ]; then
    echo "[rviz-widget] Build finished but librviz_widget.so was not found." >&2
    exit 1
fi

echo "[rviz-widget] Built: $BUILD_DIR/librviz_widget.so"
