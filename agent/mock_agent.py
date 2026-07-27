"""
Mock Agent — 模拟机器人 Agent

在 Windows 上开发测试用，不需要 ROS 环境。
模拟：
- 机器人状态上报（移动轨迹、电量变化）
- 传感器数据生成（测试图像、随机点云、模拟 IMU）
- 指令接收和确认
- 重量话题 HTTP 流服务端
"""

from __future__ import annotations

import base64
import logging
import math
import random
import threading
import time
from typing import Any, Dict, List, Optional

import numpy as np

from agent.base_agent import AgentConfig, AgentState, BaseAgent
from protocol.messages import (
    CmdAction,
    CmdData,
    EventData,
    EventLevel,
    FleetBinaryEnvelopeData,
    FleetData,
    Position,
    RobotMode,
    StatusData,
    Velocity,
)

__all__ = ["MockAgent"]

logger = logging.getLogger(__name__)


def _mock_primitive_field(name: str, msg_type: str) -> Dict[str, Any]:
    return {
        "name": name,
        "type": msg_type,
        "base_type": msg_type,
        "kind": "primitive",
        "is_array": False,
        "array_len": None,
        "fields": [],
    }


def _mock_vector3_field(name: str) -> Dict[str, Any]:
    fields: List[Dict[str, Any]] = [
        _mock_primitive_field(axis, "float64") for axis in ("x", "y", "z")
    ]
    return {
        "name": name,
        "type": "geometry_msgs/Vector3",
        "base_type": "geometry_msgs/Vector3",
        "kind": "message",
        "is_array": False,
        "array_len": None,
        "fields": fields,
    }


class MockAgent(BaseAgent):
    """模拟 Agent

    生成虚拟机器人数据，用于在没有 ROS 的 Windows 环境下测试通信链路。
    """

    def __init__(self, config: Optional[AgentConfig] = None):
        super().__init__(config)

        # 模拟状态（多线程共享，需加锁保护）
        self._state_lock = threading.Lock()
        self._position = Position(x=0.0, y=0.0, theta=0.0)
        self._velocity = Velocity(linear=0.0, angular=0.0)
        self._battery = 100.0
        self._mode = RobotMode.STOP
        self._uptime = 0
        self._target_velocity = Velocity(linear=0.0, angular=0.0)

        # 状态上报线程
        self._status_thread: Optional[threading.Thread] = None

        # 传感器数据线程 {topic: thread}
        self._sensor_threads: dict[str, threading.Thread] = {}
        self._sensor_running: dict[str, bool] = {}

        # 模拟事件生成
        self._last_event_time: float = 0.0
        self._event_events: list[dict] = [
            {
                "level": EventLevel.INFO,
                "code": "battery_normal",
                "message": "Battery level normal",
                "weight": 3,
            },
            {
                "level": EventLevel.WARNING,
                "code": "battery_low",
                "message": "Battery level low",
                "weight": 1,
            },
            {
                "level": EventLevel.INFO,
                "code": "system_ok",
                "message": "System health check passed",
                "weight": 4,
            },
            {
                "level": EventLevel.WARNING,
                "code": "network_latency",
                "message": "Network latency high",
                "weight": 1,
            },
            {
                "level": EventLevel.ERROR,
                "code": "motor_stall",
                "message": "Motor stall detected",
                "weight": 1,
            },
            {
                "level": EventLevel.INFO,
                "code": "mode_change",
                "message": "Operation mode changed",
                "weight": 2,
            },
            {
                "level": EventLevel.INFO,
                "code": "sensor_ok",
                "message": "All sensors calibrated",
                "weight": 2,
            },
            {
                "level": EventLevel.WARNING,
                "code": "temp_high",
                "message": "CPU temperature high",
                "weight": 1,
            },
        ]

    # ============================================================
    # BaseAgent 抽象方法实现
    # ============================================================

    def _get_status_data(self) -> StatusData:
        """生成模拟状态数据"""
        with self._state_lock:
            self._update_simulation()
            return StatusData(
                battery=round(self._battery, 1),
                position=self._position,
                velocity=self._velocity,
                mode=self._mode,
                ros_version="mock",
                uptime=self._uptime,
                ip=self._get_local_ip(),
            )

    def _execute_command(self, cmd: CmdData) -> tuple[bool, str]:
        """执行模拟指令"""
        action = cmd.action
        params = cmd.params or {}

        if action == CmdAction.VELOCITY:
            linear = params.get("linear", 0.0)
            angular = params.get("angular", 0.0)
            with self._state_lock:
                self._target_velocity = Velocity(linear=linear, angular=angular)
                self._mode = RobotMode.MANUAL if (linear != 0 or angular != 0) else RobotMode.STOP
            logger.info(f"[MockAgent] Set velocity: linear={linear}, angular={angular}")
            return True, f"Velocity set: linear={linear}, angular={angular}"

        elif action == CmdAction.MODE:
            mode_str = params.get("mode", "stop")
            try:
                with self._state_lock:
                    self._mode = RobotMode(mode_str)
                    if mode_str == RobotMode.STOP:
                        self._target_velocity = Velocity(linear=0.0, angular=0.0)
                        self._velocity = Velocity(linear=0.0, angular=0.0)
                logger.info(f"[MockAgent] Set mode: {mode_str}")
                return True, f"Mode set: {mode_str}"
            except ValueError:
                return False, f"Unknown mode: {mode_str}"

        elif action == CmdAction.NAV_GOAL:
            target = params.get("target", "home")
            with self._state_lock:
                self._mode = RobotMode.AUTO
                self._target_velocity = Velocity(linear=0.5, angular=0.0)
            logger.info(f"[MockAgent] Navigating to: {target}")
            return True, f"Navigating to {target}"

        elif action == CmdAction.CUSTOM:
            logger.info(f"[MockAgent] Custom command: {params}")
            return True, "Custom command executed"

        else:
            logger.warning(f"[MockAgent] Unknown command: {action}")
            return False, f"Unknown command: {action}"

    def _get_available_topics(self) -> list[dict]:
        """返回模拟的可用话题列表"""
        return [
            {"topic": "/imu/data", "msg_type": "sensor_msgs/Imu", "description": "IMU 数据"},
            {"topic": "/gps/fix", "msg_type": "sensor_msgs/NavSatFix", "description": "GPS 位置"},
            {"topic": "/odom", "msg_type": "nav_msgs/Odometry", "description": "里程计"},
            {"topic": "/cmd_vel", "msg_type": "geometry_msgs/Twist", "description": "速度指令"},
            {
                "topic": "/camera/image_raw/compressed",
                "msg_type": "sensor_msgs/CompressedImage",
                "description": "压缩图像",
            },
            {"topic": "/scan", "msg_type": "sensor_msgs/LaserScan", "description": "激光雷达"},
            {
                "topic": "/lidar/points",
                "msg_type": "sensor_msgs/PointCloud2",
                "description": "3D 点云",
            },
        ]

    def _get_message_schema(self, msg_type: str) -> Dict[str, Any]:
        """在无 ROS 环境返回常见类型的稳定示例结构。"""
        if msg_type == "geometry_msgs/Twist":
            return {
                "type": msg_type,
                "kind": "message",
                "fields": [
                    _mock_vector3_field("linear"),
                    _mock_vector3_field("angular"),
                ],
            }
        if msg_type == "std_msgs/Bool":
            return {
                "type": msg_type,
                "kind": "message",
                "fields": [_mock_primitive_field("data", "bool")],
            }
        return {"type": msg_type, "kind": "message", "fields": []}

    def _on_topic_subscribed(self, topic: str, msg_type: str, options: dict) -> None:
        """话题被订阅时，启动数据生成线程"""
        if topic in self._sensor_threads:
            return  # 已经在运行

        self._sensor_running[topic] = True
        freq = options.get("freq_limit", 5.0)

        thread = threading.Thread(
            target=self._sensor_data_loop,
            args=(topic, msg_type, freq, options),
            daemon=True,
            name=f"sensor_{topic}",
        )
        self._sensor_threads[topic] = thread
        thread.start()
        logger.info(f"[MockAgent] Started sensor thread for {topic} at {freq}Hz")

    def _on_topic_unsubscribed(self, topic: str) -> None:
        """话题被取消订阅时，停止数据生成线程"""
        self._sensor_running[topic] = False
        thread = self._sensor_threads.pop(topic, None)
        if thread:
            thread.join(timeout=2.0)
        logger.info(f"[MockAgent] Stopped sensor thread for {topic}")

    # ============================================================
    # 生命周期
    # ============================================================

    def start(self) -> None:
        """启动 Mock Agent"""
        logger.info(f"[MockAgent] Starting {self.config.robot_id}...")

        # 启动 HTTP 流服务端（重量话题用）
        self._start_stream_server()

        # 启动状态上报线程
        self._running = True
        self._status_thread = threading.Thread(
            target=self._status_loop,
            daemon=True,
            name="status_reporter",
        )

        # 调用父类 start（MQTT 连接）
        super().start()

    def stop(self) -> None:
        """停止 Mock Agent"""
        # 停止传感器线程
        for topic in list(self._sensor_running.keys()):
            self._sensor_running[topic] = False
        for thread in self._sensor_threads.values():
            thread.join(timeout=2.0)
        self._sensor_threads.clear()

        # 停止状态线程
        self._running = False
        if self._status_thread:
            self._status_thread.join(timeout=2.0)

        # 停止 HTTP 流服务端
        self._stop_stream_server()

        super().stop()

    # ============================================================
    # 状态模拟
    # ============================================================

    def _update_simulation(self) -> None:
        """更新模拟状态（移动轨迹、电量变化等）"""
        dt = self.config.status_interval

        # 速度渐变（模拟惯性）
        alpha = 0.3  # 平滑系数
        self._velocity = Velocity(
            linear=self._velocity.linear
            + alpha * (self._target_velocity.linear - self._velocity.linear),
            angular=self._velocity.angular
            + alpha * (self._target_velocity.angular - self._velocity.angular),
        )

        # 更新位置
        self._position.x += self._velocity.linear * math.cos(self._position.theta) * dt
        self._position.y += self._velocity.linear * math.sin(self._position.theta) * dt
        self._position.theta += self._velocity.angular * dt

        # 角度归一化
        self._position.theta = math.atan2(
            math.sin(self._position.theta), math.cos(self._position.theta)
        )

        # 电量缓慢下降
        if self._battery > 0:
            drain = 0.05 * dt  # 每秒消耗约 0.05%
            if self._velocity.linear > 0:
                drain *= 2  # 运动时消耗加倍
            self._battery = max(0, self._battery - drain)

        # 运行时间
        self._uptime += int(dt)

    # ============================================================
    # 状态上报循环
    # ============================================================

    def _status_loop(self) -> None:
        """状态上报循环（独立线程）"""
        while self._running:
            if self.state in (AgentState.CONNECTED, AgentState.RUNNING):
                self._check_and_publish_status()
                self._generate_mock_events()
            time.sleep(self.config.status_interval)

    def _generate_mock_events(self) -> None:
        """模拟事件生成（每 10 秒随机生成一个事件）"""
        now = time.time()
        if now - self._last_event_time < 10.0:
            return
        self._last_event_time = now

        # 按权重选择事件
        total_weight = sum(e["weight"] for e in self._event_events)
        r = random.uniform(0, total_weight)
        cumulative = 0
        chosen = None
        for e in self._event_events:
            cumulative += e["weight"]
            if r <= cumulative:
                chosen = e
                break
        if not chosen:
            return

        with self._state_lock:
            details = {
                "battery": round(self._battery, 1),
                "uptime": self._uptime,
            }
        event_data = EventData(
            level=chosen["level"],
            code=chosen["code"],
            message=chosen["message"],
            details=details,
        )
        self.publish_event(event_data)
        logger.debug(f"[MockAgent] Event: [{chosen['level']}] {chosen['code']}")

    def _start_status_loop(self) -> None:
        """重写父类方法，启动状态上报线程"""
        if self._status_thread is None or not self._status_thread.is_alive():
            self._status_thread = threading.Thread(
                target=self._status_loop,
                daemon=True,
                name="status_reporter",
            )
            self._status_thread.start()

    # ============================================================
    # 传感器数据生成
    # ============================================================

    def _sensor_data_loop(self, topic: str, msg_type: str, freq: float, options: dict) -> None:
        """传感器数据生成循环

        Args:
            topic: ROS 话题名
            msg_type: 消息类型
            freq: 发送频率（Hz）
            options: 订阅选项
        """
        interval = 1.0 / freq if freq > 0 else 0.1

        while self._sensor_running.get(topic, False):
            try:
                data = self._generate_sensor_data(topic, msg_type, options)
                if data:
                    self.publish_sensor_data(topic, msg_type, data)
            except Exception as e:
                logger.error(f"[MockAgent] Sensor data generation error ({topic}): {e}")

            time.sleep(interval)

    def _generate_sensor_data(self, topic: str, msg_type: str, options: dict) -> Optional[dict]:
        """生成模拟传感器数据

        Args:
            topic: ROS 话题名
            msg_type: 消息类型
            options: 订阅选项

        Returns:
            数据字典，或 None
        """
        now = time.time()

        # IMU 数据
        if "Imu" in msg_type:
            return {
                "_msg_type": msg_type,
                "orientation": {
                    "x": math.sin(now * 0.1) * 0.1,
                    "y": math.cos(now * 0.1) * 0.1,
                    "z": math.sin(now * 0.05) * 0.3,
                    "w": 0.95,
                },
                "angular_velocity": {
                    "x": random.gauss(0, 0.01),
                    "y": random.gauss(0, 0.01),
                    "z": self._velocity.angular + random.gauss(0, 0.005),
                },
                "linear_acceleration": {
                    "x": self._velocity.linear * 0.1 + random.gauss(0, 0.05),
                    "y": random.gauss(0, 0.05),
                    "z": 9.81 + random.gauss(0, 0.01),
                },
                "timestamp": now,
            }

        # GPS 数据
        if "NavSatFix" in msg_type:
            return {
                "_msg_type": msg_type,
                "latitude": 39.9042 + self._position.x * 0.00001,
                "longitude": 116.4074 + self._position.y * 0.00001,
                "altitude": 50.0 + random.gauss(0, 0.5),
                "status": {"status": 0, "service": 1},
                "timestamp": now,
            }

        # 里程计
        if "Odometry" in msg_type:
            return {
                "_msg_type": msg_type,
                "position": {"x": self._position.x, "y": self._position.y, "z": 0.0},
                "orientation": {"theta": self._position.theta},
                "linear": self._velocity.linear,
                "angular": self._velocity.angular,
                "timestamp": now,
            }

        # Twist（速度指令反馈）
        if "Twist" in msg_type:
            return {
                "_msg_type": msg_type,
                "linear": {"x": self._velocity.linear, "y": 0.0, "z": 0.0},
                "angular": {"x": 0.0, "y": 0.0, "z": self._velocity.angular},
                "timestamp": now,
            }

        # 压缩图像
        if "CompressedImage" in msg_type:
            return self._generate_mock_image(msg_type, options)

        # LaserScan
        if "LaserScan" in msg_type:
            return self._generate_mock_laserscan(msg_type)

        # PointCloud2
        if "PointCloud2" in msg_type:
            return self._generate_mock_pointcloud(msg_type, options)

        # 默认
        return {
            "_msg_type": msg_type,
            "data": "mock",
            "timestamp": now,
        }

    def _generate_mock_image(self, msg_type: str, options: dict) -> dict:
        """生成模拟图像（OpenCV 绘制测试图案）"""
        try:
            import cv2

            width = 320
            height = 240
            quality = options.get("compression", {}).get("quality", 80)
            resize = options.get("compression", {}).get("resize")

            if resize:
                width, height = resize[0], resize[1]

            # 生成测试图案：渐变色 + 时间戳文字
            img = np.zeros((height, width, 3), dtype=np.uint8)

            # 渐变背景
            for i in range(height):
                hue = int((i / height) * 180) % 180
                img[i, :] = [hue, 255, 200]

            # 添加一些"运动物体"
            t = time.time()
            cx = int(width / 2 + width / 4 * math.sin(t * 0.5))
            cy = int(height / 2 + height / 4 * math.cos(t * 0.3))
            cv2.circle(img, (cx, cy), 20, (0, 255, 0), -1)

            # 时间戳文字
            cv2.putText(
                img,
                f"Mock {self.config.robot_id} t={t:.1f}",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                1,
            )

            # JPEG 压缩
            encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality]
            _, encoded = cv2.imencode(".jpg", img, encode_params)
            b64_data = base64.b64encode(encoded.tobytes()).decode("ascii")

            return {
                "_msg_type": msg_type,
                "format": "jpeg",
                "quality": quality,
                "width": width,
                "height": height,
                "base64": b64_data,
                "timestamp": time.time(),
            }

        except ImportError:
            # 没有 OpenCV，返回空图像信息
            return {
                "_msg_type": msg_type,
                "format": "none",
                "width": 0,
                "height": 0,
                "base64": "",
                "timestamp": time.time(),
            }

    def _generate_mock_laserscan(self, msg_type: str) -> dict:
        """生成模拟激光雷达数据"""
        num_readings = 360
        ranges = []

        for i in range(num_readings):
            angle = i * 2 * math.pi / num_readings
            # 模拟一个房间环境：大部分距离 5m，有一些障碍物
            dist = 5.0 + random.gauss(0, 0.05)
            # 添加一些"障碍物"
            if 1.0 < angle < 1.5:
                dist = 1.5 + random.gauss(0, 0.02)
            elif 3.0 < angle < 3.3:
                dist = 2.0 + random.gauss(0, 0.02)
            elif 4.5 < angle < 4.8:
                dist = 0.8 + random.gauss(0, 0.02)
            ranges.append(round(dist, 3))

        return {
            "_msg_type": msg_type,
            "angle_min": 0.0,
            "angle_max": 2 * math.pi,
            "angle_increment": 2 * math.pi / num_readings,
            "range_min": 0.1,
            "range_max": 10.0,
            "ranges": ranges,
            "timestamp": time.time(),
        }

    def _generate_mock_pointcloud(self, msg_type: str, options: dict) -> dict:
        """生成模拟点云数据"""
        voxel_size = options.get("compression", {}).get("voxel_size", 0.1)

        # 生成一个简单的 3D 场景：地面 + 一些物体
        points = []

        # 地面平面（5m x 5m）
        for x in np.linspace(-2.5, 2.5, 50):
            for y in np.linspace(-2.5, 2.5, 50):
                points.append([x, y, 0.0 + random.gauss(0, 0.01)])

        # 一个"箱子"
        for x in np.linspace(0.5, 1.5, 20):
            for y in np.linspace(0.5, 1.5, 20):
                for z in np.linspace(0, 1.0, 10):
                    points.append([x, y, z + random.gauss(0, 0.005)])

        # 一个"柱子"
        for z in np.linspace(0, 2.0, 40):
            for angle in np.linspace(0, 2 * math.pi, 16):
                r = 0.2
                x = -1.0 + r * math.cos(angle)
                y = 0.0 + r * math.sin(angle)
                points.append([x, y, z + random.gauss(0, 0.005)])

        points_array = np.array(points, dtype=np.float32)

        return {
            "_msg_type": msg_type,
            "points": points_array,
            "voxel_size": voxel_size,
            "timestamp": time.time(),
        }

    def _get_ros_version(self) -> str:
        return "mock"

    # ============================================================
    # 机器人间通信
    # ============================================================

    def _on_fleet_message(self, src_id: str, data: FleetData) -> None:
        """处理其他机器人发来的 fleet 数据"""
        logger.info(
            f"[MockAgent] Fleet data from {src_id}: type={data.data_type}, payload={data.payload}"
        )

    def _on_fleet_binary_message(
        self,
        src_id: str,
        envelope: FleetBinaryEnvelopeData,
        body: bytes,
    ) -> None:
        """无 ROS 环境只记录 binary 摘要，不解析 ROS 消息。"""
        logger.info(
            "[MockAgent] Fleet binary from %s: type=%s, dst=%s, size=%d",
            src_id,
            envelope.msg_type,
            envelope.dst_topic,
            len(body),
        )
