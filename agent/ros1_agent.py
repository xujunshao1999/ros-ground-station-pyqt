from __future__ import annotations

# ROS 1 Agent — 连接 ROS 1 和 MQTT 的桥接代理
#
# 在 Linux 环境中运行，将 ROS 1 话题数据转发到 MQTT，
# 并将 MQTT 控制指令翻译为 ROS 话题发布。
#
# 依赖：rospy（ROS 1 Noetic / Melodic）
import io
import json
import logging
import math
import threading
import time
from typing import Dict, List, Optional

try:
    import rospy
    from geometry_msgs.msg import Twist
    from std_msgs.msg import String
except ImportError:
    rospy = None  # 延迟到运行时报错

from agent.base_agent import AgentConfig, BaseAgent
from agent.dict_to_ros_msg import dict_to_ros_msg
from agent.frame_utils import namespace_message_frames
from agent.ros_msg_converter import ros_msg_to_dict
from protocol.binary_payloads import is_ros_message_binary_supported
from protocol.messages import (
    CmdAction,
    CmdData,
    FleetData,
    Position,
    RobotMode,
    StatusData,
    Velocity,
)

logger = logging.getLogger(__name__)

__all__ = ["ROS1Agent"]


class ROS1Agent(BaseAgent):
    """ROS 1 Agent

    桥接 ROS 1 话题和 MQTT 通信：
    - 订阅 ROS 话题 → 转发到 MQTT
    - 接收 MQTT 控制指令 → 发布到 ROS 话题
    - 上报机器人状态（位置、电量、模式等）
    """

    def __init__(self, config: Optional[AgentConfig] = None):
        if rospy is None:
            raise ImportError(
                "rospy is not available. "
                "Please install ROS 1 and source the setup script: "
                "source /opt/ros/noetic/setup.bash"
            )
        super().__init__(config)

        # ROS 订阅句柄
        self._ros_subscribers: Dict[str, object] = {}  # {topic: rospy.Subscriber}
        self._fleet_subscribers: Dict[str, object] = {}

        # ROS 发布器
        self._cmd_vel_pub: Optional[rospy.Publisher] = None
        self._fleet_publishers: Dict[tuple, object] = {}

        # 状态数据
        self._position = Position(x=0.0, y=0.0, theta=0.0)
        self._velocity = Velocity(linear=0.0, angular=0.0)
        self._battery = 100.0
        self._mode = RobotMode.STOP

        # 传感器数据缓存 {topic: latest_data_dict}
        self._sensor_data: Dict[str, dict] = {}
        self._sensor_lock = threading.Lock()

    # ============================================================
    # BaseAgent 抽象方法实现
    # ============================================================

    def _get_status_data(self) -> StatusData:
        """从 ROS 获取当前状态"""
        with self._sensor_lock:
            odom = self._sensor_data.get("/odom")
            if odom and "pose" in odom:
                # 新通用序列化器保留完整嵌套结构: pose.pose.{position, orientation}
                pose_data = odom.get("pose", {})
                # geometry_msgs/PoseWithCovariance: pose 字段是 geometry_msgs/Pose
                inner_pose = pose_data.get("pose", pose_data)
                pos = inner_pose.get("position", {})
                ori = inner_pose.get("orientation", {})
                # 兼容新旧两种格式
                qx = ori.get("x", ori.get("qx", 0.0))
                qy = ori.get("y", ori.get("qy", 0.0))
                qz = ori.get("z", ori.get("qz", 0.0))
                qw = ori.get("w", ori.get("qw", 1.0))
                yaw = math.atan2(
                    2.0 * (qw * qz + qx * qy),
                    1.0 - 2.0 * (qy * qy + qz * qz)
                )
                self._position = Position(
                    x=float(pos.get("x", 0.0)),
                    y=float(pos.get("y", 0.0)),
                    theta=yaw,
                )
            twist = self._sensor_data.get("/cmd_vel")
            if twist:
                # geometry_msgs/Twist: linear 和 angular 都是 geometry_msgs/Vector3
                linear = twist.get("linear", {})
                angular = twist.get("angular", {})
                self._velocity = Velocity(
                    linear=float(linear.get("x", 0.0)),
                    angular=float(angular.get("z", 0.0)),
                )

        return StatusData(
            battery=round(self._battery, 1),
            position=self._position,
            velocity=self._velocity,
            mode=self._mode,
            ros_version="1",
            uptime=int(rospy.get_rostime().to_sec()) if not rospy.is_shutdown() else 0,
            ip=self._get_local_ip(),
        )

    def _execute_command(self, cmd: CmdData) -> tuple[bool, str]:
        """将 MQTT 指令翻译为 ROS 操作"""
        action = cmd.action
        params = cmd.params or {}

        if action == CmdAction.VELOCITY:
            linear = params.get("linear", 0.0)
            angular = params.get("angular", 0.0)

            if self._cmd_vel_pub and not rospy.is_shutdown():
                twist = Twist()
                twist.linear.x = linear
                twist.angular.z = angular
                self._cmd_vel_pub.publish(twist)

            self._velocity = Velocity(linear=linear, angular=angular)
            self._mode = RobotMode.MANUAL if (linear != 0 or angular != 0) else RobotMode.STOP
            logger.info(f"[ROS1Agent] cmd_vel: linear={linear}, angular={angular}")
            return True, f"Velocity set: linear={linear}, angular={angular}"

        elif action == CmdAction.MODE:
            mode_str = params.get("mode", "stop")
            try:
                self._mode = RobotMode(mode_str)
                if mode_str == RobotMode.STOP:
                    # 停车：发布零速度
                    if self._cmd_vel_pub and not rospy.is_shutdown():
                        self._cmd_vel_pub.publish(Twist())
                    self._velocity = Velocity(linear=0.0, angular=0.0)
                logger.info(f"[ROS1Agent] Mode set: {mode_str}")
                return True, f"Mode set: {mode_str}"
            except ValueError:
                return False, f"Unknown mode: {mode_str}"

        elif action == CmdAction.NAV_GOAL:
            target = params.get("target", "home")
            # TODO: 对接 move_base 或 nav2 的导航目标
            self._mode = RobotMode.AUTO
            logger.info(f"[ROS1Agent] Nav goal: {target} (move_base not yet integrated)")
            return True, f"Navigating to {target} (pending move_base integration)"

        elif action == CmdAction.CUSTOM:
            topic = params.get("topic", "")
            msg_data = params.get("msg", {})
            if topic:
                # 发布自定义 ROS 消息（String 类型）
                pub = rospy.Publisher(topic, String, queue_size=1)
                pub.publish(json.dumps(msg_data))
                logger.info(f"[ROS1Agent] Custom publish to {topic}")
                return True, f"Published to {topic}"
            return False, "Missing 'topic' in custom command params"

        else:
            logger.warning(f"[ROS1Agent] Unknown command: {action}")
            return False, f"Unknown command: {action}"

    def _get_available_topics(self) -> List[dict]:
        """获取 ROS 中活跃的话题列表"""
        if rospy.is_shutdown():
            return []

        topics = []
        try:
            # 获取当前 ROS 系统中所有活跃话题
            published_topics = rospy.get_published_topics("/")
            for topic_name, msg_type in published_topics:
                topics.append({
                    "topic": topic_name,
                    "msg_type": msg_type,
                    "description": f"ROS topic ({msg_type})",
                })
        except Exception as e:
            logger.warning(f"[ROS1Agent] Failed to get topic list: {e}")
            # 回退：返回常见话题
            topics = [
                {"topic": "/cmd_vel", "msg_type": "geometry_msgs/Twist", "description": "速度指令"},
                {"topic": "/odom", "msg_type": "nav_msgs/Odometry", "description": "里程计"},
            ]

        return topics

    def _on_topic_subscribed(self, topic: str, msg_type: str, options: dict) -> None:
        """地面站请求订阅某话题 → 创建 ROS 订阅"""
        if topic in self._ros_subscribers:
            return  # 已经订阅了

        freq = options.get("freq_limit", self.config.default_freq_limit)

        # 获取 ROS 消息类
        msg_class = self._get_ros_msg_class(msg_type)
        if msg_class is None:
            logger.error(f"[ROS1Agent] Unknown message type: {msg_type}")
            return

        # 创建限频 ROS 订阅
        # rospy 没有原生限频，用 throttle 实现
        last_pub_time = {"t": 0.0}
        min_interval = 1.0 / freq if freq > 0 else 0.0
        transport = options.get("transport", "mqtt_json")

        def callback(
            msg,
            t=topic,
            mt=msg_type,
            tr=transport,
            lpt=last_pub_time,
            mi=min_interval,
        ):
            now = time.time()
            if t != "/tf_static" and mi > 0 and (now - lpt["t"]) < mi:
                return  # 限频：跳过
            lpt["t"] = now

            if tr == "http_stream" and mt == "sensor_msgs/PointCloud2":
                raw_payload = self._serialize_ros_message(msg)
                if raw_payload is not None:
                    self.publish_heavy_snapshot_data(
                        t,
                        mt,
                        raw_payload,
                        seq=self._message_seq(msg),
                        stamp=self._message_stamp(msg),
                        frame_id=self._message_frame_id(msg),
                    )
                    return

            if tr == "mqtt_binary" and is_ros_message_binary_supported(t, mt):
                raw_payload = self._serialize_ros_message(msg)
                if raw_payload is not None:
                    self.publish_sensor_binary_data(
                        t,
                        mt,
                        raw_payload,
                        seq=self._message_seq(msg),
                        bypass_rate_limit=(t == "/tf_static"),
                        retain=(t == "/tf_static"),
                    )
                    return

            data = ros_msg_to_dict(msg)
            if t == "/tf_static":
                data = self._merge_tf_static_data(data)
                self.publish_sensor_data(
                    t,
                    mt,
                    data,
                    bypass_rate_limit=True,
                    retain=True,
                )
                return

            with self._sensor_lock:
                self._sensor_data[t] = data
            self.publish_sensor_data(t, mt, data)

        try:
            sub = rospy.Subscriber(topic, msg_class, callback)
            self._ros_subscribers[topic] = sub
            logger.info(f"[ROS1Agent] Subscribed to ROS topic: {topic} ({msg_type}) @ {freq}Hz")
            if topic == "/tf_static":
                self._publish_latched_tf_static(msg_class, msg_type)
        except Exception as e:
            logger.error(f"[ROS1Agent] Failed to subscribe {topic}: {e}")

    @staticmethod
    def _serialize_ros_message(msg) -> Optional[bytes]:
        try:
            buff = io.BytesIO()
            msg.serialize(buff)
            return buff.getvalue()
        except Exception as e:
            logger.warning("[ROS1Agent] Failed to serialize ROS message: %s", e)
            return None

    @staticmethod
    def _message_seq(msg) -> Optional[int]:
        header = getattr(msg, "header", None)
        if header is None:
            transforms = getattr(msg, "transforms", None)
            if transforms:
                header = getattr(transforms[0], "header", None)
        seq = getattr(header, "seq", None)
        try:
            return int(seq) if seq is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _message_stamp(msg) -> dict:
        header = getattr(msg, "header", None)
        stamp = getattr(header, "stamp", None)
        if stamp is None:
            return {}
        return {
            "secs": int(getattr(stamp, "secs", 0)),
            "nsecs": int(getattr(stamp, "nsecs", 0)),
        }

    @staticmethod
    def _message_frame_id(msg) -> str:
        header = getattr(msg, "header", None)
        return str(getattr(header, "frame_id", "") or "")

    def _publish_latched_tf_static(self, msg_class: type, msg_type: str) -> None:
        """Fetch and publish the current latched /tf_static message once."""
        try:
            msg = rospy.wait_for_message("/tf_static", msg_class, timeout=2.0)
        except Exception as e:
            logger.warning(f"[ROS1Agent] Failed to fetch latched /tf_static: {e}")
            return

        data = self._merge_tf_static_data(ros_msg_to_dict(msg))
        self.publish_sensor_data(
            "/tf_static",
            msg_type,
            data,
            bypass_rate_limit=True,
            retain=True,
        )

    def _merge_tf_static_data(self, data: dict) -> dict:
        """Merge /tf_static transforms by child frame and return full cache."""
        if not isinstance(data, dict):
            data = {}
        new_transforms = data.get("transforms", [])
        if not isinstance(new_transforms, list):
            new_transforms = []

        with self._sensor_lock:
            cached = self._sensor_data.get("/tf_static", {})
            cached_transforms = cached.get("transforms", [])
            if not isinstance(cached_transforms, list):
                cached_transforms = []

            merged = {}
            for transform in cached_transforms + new_transforms:
                if not isinstance(transform, dict):
                    continue
                child_frame_id = transform.get("child_frame_id", "")
                if child_frame_id:
                    merged[child_frame_id] = transform

            merged_data = dict(data)
            merged_data["transforms"] = list(merged.values())
            self._sensor_data["/tf_static"] = merged_data
            return merged_data

    def _on_topic_unsubscribed(self, topic: str) -> None:
        """地面站取消订阅 → 注销 ROS 订阅"""
        sub = self._ros_subscribers.pop(topic, None)
        if sub:
            sub.unregister()
        with self._sensor_lock:
            self._sensor_data.pop(topic, None)
        logger.info(f"[ROS1Agent] Unsubscribed from ROS topic: {topic}")

    # ============================================================
    # 机器人间通信
    # ============================================================

    def _on_fleet_message(self, src_id: str, data: FleetData) -> None:
        """处理其他机器人发来的 fleet 数据，发布到 ROS 话题"""
        try:
            if data.data_type == "ros_topic":
                self._publish_fleet_ros_topic(src_id, data)

            payload = {
                "src_id": src_id,
                "data_type": data.data_type,
                "payload": data.payload,
                "ttl": data.ttl,
                "timestamp": time.time(),
            }
            pub = rospy.Publisher("/fleet/incoming", String, queue_size=10)
            pub.publish(json.dumps(payload))
            logger.info(f"[ROS1Agent] Published fleet data from {src_id} to /fleet/incoming")
        except Exception as e:
            logger.error(f"[ROS1Agent] Failed to publish fleet data to ROS: {e}")

    def _publish_fleet_ros_topic(self, src_id: str, data: FleetData) -> None:
        if not data.dst_topic or not data.msg_type or not isinstance(data.payload, dict):
            logger.warning(
                "[ROS1Agent] Invalid fleet ros_topic from %s: dst_topic=%s msg_type=%s",
                src_id,
                data.dst_topic,
                data.msg_type,
            )
            return

        payload = dict(data.payload)
        if data.frame_policy == "namespace":
            namespace_message_frames(payload, src_id)

        ros_msg = dict_to_ros_msg(payload, data.msg_type)
        key = (data.dst_topic, data.msg_type)
        pub = self._fleet_publishers.get(key)
        if pub is None:
            pub = rospy.Publisher(data.dst_topic, type(ros_msg), queue_size=10)
            self._fleet_publishers[key] = pub
        pub.publish(ros_msg)
        logger.info(
            "[ROS1Agent] Published fleet ROS topic from %s to %s (%s)",
            src_id,
            data.dst_topic,
            data.msg_type,
        )

    def _apply_fleet_rules(self, fleet_rules: List[dict]) -> None:
        """根据 fleet_rules 订阅本机 ROS topic，并转发给目标机器人。"""
        for topic, sub in list(self._fleet_subscribers.items()):
            try:
                sub.unregister()
            except Exception:
                pass
            logger.info(f"[ROS1Agent] Fleet rule unsubscribed from: {topic}")
        self._fleet_subscribers.clear()

        for rule in fleet_rules:
            if not rule.get("enabled", True):
                continue

            src_topic = rule.get("src_topic", "")
            msg_type = rule.get("msg_type", "")
            targets = list(rule.get("targets", []))
            if not src_topic or not msg_type or not targets:
                continue

            msg_class = self._get_ros_msg_class(msg_type)
            if msg_class is None:
                logger.error(f"[ROS1Agent] Unknown fleet message type: {msg_type}")
                continue

            callback = self._make_fleet_forward_callback(
                src_topic=src_topic,
                msg_type=msg_type,
                targets=targets,
                frame_policy=rule.get("frame_policy", "preserve"),
                freq_limit=float(rule.get("freq_limit", 0.0)),
            )
            try:
                self._fleet_subscribers[src_topic] = rospy.Subscriber(
                    src_topic,
                    msg_class,
                    callback,
                )
                logger.info(
                    "[ROS1Agent] Fleet rule subscribed to ROS topic: %s (%s)",
                    src_topic,
                    msg_type,
                )
            except Exception as e:
                logger.error(
                    "[ROS1Agent] Failed to subscribe fleet topic %s: %s",
                    src_topic,
                    e,
                )

    def _make_fleet_forward_callback(
        self,
        src_topic: str,
        msg_type: str,
        targets: List[dict],
        frame_policy: str,
        freq_limit: float = 0.0,
    ):
        last_pub_time = {"t": 0.0}
        min_interval = 1.0 / freq_limit if freq_limit > 0 else 0.0

        def callback(msg):
            now = time.time()
            if min_interval > 0 and (now - last_pub_time["t"]) < min_interval:
                return
            last_pub_time["t"] = now

            payload = ros_msg_to_dict(msg)
            for target in targets:
                target_id = target.get("robot_id", "")
                dst_topic = target.get("dst_topic", "")
                if not target_id or not dst_topic:
                    continue
                self.send_to_robot(
                    target_id,
                    FleetData(
                        data_type="ros_topic",
                        src_topic=src_topic,
                        dst_topic=dst_topic,
                        msg_type=msg_type,
                        frame_policy=frame_policy,
                        payload=payload,
                        stamp=now,
                        ttl=1.0,
                    ),
                )

        return callback

    # ============================================================
    # ROS 消息类型映射
    # ============================================================

    @staticmethod
    def _get_ros_msg_class(msg_type: str):
        """根据消息类型字符串获取 ROS 消息类"""
        try:
            parts = msg_type.split("/")
            if len(parts) == 2:
                module_name = parts[0]
                class_name = parts[1]
                import importlib
                mod = importlib.import_module(f"{module_name}.msg")
                return getattr(mod, class_name, None)
        except (ImportError, AttributeError) as e:
            logger.debug(f"[ROS1Agent] Cannot load msg class {msg_type}: {e}")
        return None

    # ============================================================
    # 生命周期
    # ============================================================

    def start(self) -> None:
        """启动 ROS 1 Agent"""
        logger.info(f"[ROS1Agent] Starting {self.config.robot_id}...")

        # 初始化 ROS 节点
        node_name = f"ground_station_agent_{self.config.robot_id}"
        rospy.init_node(node_name, anonymous=True)
        logger.info(f"[ROS1Agent] ROS node initialized: {node_name}")

        # 创建默认 ROS 发布器（cmd_vel）
        self._cmd_vel_pub = rospy.Publisher("/cmd_vel", Twist, queue_size=10)

        # 启动 HTTP 流服务端
        self._start_stream_server()

        # 调用父类 start（MQTT 连接 + 状态上报）
        super().start()

    def stop(self) -> None:
        """停止 ROS 1 Agent"""
        # 注销所有 ROS 订阅
        for topic, sub in list(self._ros_subscribers.items()):
            try:
                sub.unregister()
            except Exception:
                pass
        self._ros_subscribers.clear()

        for topic, sub in list(self._fleet_subscribers.items()):
            try:
                sub.unregister()
            except Exception:
                pass
        self._fleet_subscribers.clear()
        self._fleet_publishers.clear()

        # 停止 HTTP 流服务端
        self._stop_stream_server()

        # 调用父类 stop
        super().stop()

        logger.info("[ROS1Agent] Stopped")

    # ============================================================
    # 工具方法
    # ============================================================
