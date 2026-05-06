from __future__ import annotations

"""
话题分层处理器

根据话题类型自动选择传输策略：
- 轻量（LIGHT）：MQTT + JSON，适合 IMU、GPS、里程计等小数据
- 中等（MEDIUM）：MQTT + 二进制，适合压缩图像、LaserScan
- 重量（HEAVY）：HTTP 流 + MQTT 信令，适合原始图像、点云

Agent 通过 topic_registry 查询话题类型，自动选择处理策略。
"""

import base64
import io
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from protocol.topic_registry import TopicTier, TopicInfo, default_registry

logger = logging.getLogger(__name__)


@dataclass
class ProcessedData:
    """处理后的数据包"""

    tier: TopicTier
    mqtt_payload: Optional[bytes] = None  # MQTT 发送的 payload
    mqtt_topic: Optional[str] = None  # MQTT topic
    meta: Optional[dict] = None  # 重量话题的元信息（通过 MQTT 发送）
    stream_data: Optional[bytes] = None  # 重量话题的流数据（通过 HTTP 发送）


class TopicHandler:
    """话题分层处理器

    负责根据话题类型选择传输策略，并序列化/压缩数据。
    """

    def __init__(self, registry=None):
        """
        Args:
            registry: 话题类型注册表，默认使用 default_registry
        """
        self.registry = registry or default_registry

    def get_tier(self, msg_type: str) -> TopicTier:
        """获取消息类型的传输层级

        Args:
            msg_type: ROS 消息类型，如 "sensor_msgs/Imu"

        Returns:
            TopicTier 枚举值
        """
        return self.registry.get_tier(msg_type)

    def process_light(self, topic: str, data: dict) -> ProcessedData:
        """处理轻量话题数据

        直接 JSON 序列化，通过 MQTT 发送。

        Args:
            topic: ROS 话题名
            data: 话题数据字典

        Returns:
            ProcessedData，mqtt_payload 为 JSON 字节
        """
        payload = json.dumps(data, ensure_ascii=False, default=self._json_default).encode("utf-8")
        return ProcessedData(
            tier=TopicTier.LIGHT,
            mqtt_payload=payload,
            mqtt_topic=topic,
        )

    def process_medium(
        self,
        topic: str,
        data: dict,
        compression_quality: int = 80,
        resize: Optional[tuple[int, int]] = None,
    ) -> ProcessedData:
        """处理中等话题数据

        图像类：JPEG 压缩后 base64 编码到 JSON
        其他二进制：直接二进制 payload + JSON 元信息

        Args:
            topic: ROS 话题名
            data: 话题数据字典
            compression_quality: JPEG 压缩质量 (1-100)
            resize: 缩放尺寸 (width, height)

        Returns:
            ProcessedData
        """
        msg_type = data.get("_msg_type", "")

        # 检查是否为图像类型
        if self._is_image_type(msg_type):
            return self._process_image(topic, data, compression_quality, resize)

        # 通用中等数据处理：JSON + base64 编码二进制
        payload = json.dumps(data, ensure_ascii=False, default=self._json_default).encode("utf-8")
        return ProcessedData(
            tier=TopicTier.MEDIUM,
            mqtt_payload=payload,
            mqtt_topic=topic,
        )

    def process_heavy(
        self,
        topic: str,
        data: dict,
        voxel_size: float = 0.1,
    ) -> ProcessedData:
        """处理重量话题数据

        MQTT 仅发送元信息（大小、流地址等），实际数据通过 HTTP 流传输。

        Args:
            topic: ROS 话题名
            data: 话题数据字典
            voxel_size: 点云体素降采样大小

        Returns:
            ProcessedData，meta 包含元信息，stream_data 包含实际数据
        """
        msg_type = data.get("_msg_type", "")

        # 提取流数据
        stream_data = b""
        size_bytes = 0
        points = 0

        if self._is_pointcloud_type(msg_type):
            # 点云数据
            stream_data, points = self._process_pointcloud(data, voxel_size)
            size_bytes = len(stream_data)
        elif self._is_image_type(msg_type):
            # 原始图像作为重量数据
            stream_data = self._encode_image_bytes(data)
            size_bytes = len(stream_data)

        meta = {
            "topic": topic,
            "msg_type": msg_type,
            "transport": "http_stream",
            "size_bytes": size_bytes,
        }
        if points > 0:
            meta["points"] = points

        # MQTT 发送元信息
        meta_payload = json.dumps(meta, ensure_ascii=False).encode("utf-8")

        return ProcessedData(
            tier=TopicTier.HEAVY,
            mqtt_payload=meta_payload,
            mqtt_topic=f"{topic}/meta",
            meta=meta,
            stream_data=stream_data,
        )

    def process(self, topic: str, data: dict, **kwargs) -> ProcessedData:
        """自动选择处理策略

        根据消息类型查询 registry，自动调用对应的处理方法。

        Args:
            topic: ROS 话题名
            data: 话题数据（需包含 "_msg_type" 字段）
            **kwargs: 处理参数（quality, resize, voxel_size 等）

        Returns:
            ProcessedData
        """
        msg_type = data.get("_msg_type", "")
        tier = self.get_tier(msg_type)

        if tier == TopicTier.LIGHT:
            return self.process_light(topic, data)
        elif tier == TopicTier.MEDIUM:
            quality = kwargs.get("quality", 80)
            resize = kwargs.get("resize")
            return self.process_medium(topic, data, quality, resize)
        elif tier == TopicTier.HEAVY:
            voxel_size = kwargs.get("voxel_size", 0.1)
            return self.process_heavy(topic, data, voxel_size)
        else:
            # 未知类型，按轻量处理
            logger.warning(f"Unknown msg_type '{msg_type}', treating as LIGHT")
            return self.process_light(topic, data)

    # ---- 内部方法 ----

    def _is_image_type(self, msg_type: str) -> bool:
        """判断是否为图像类型"""
        return any(
            t in msg_type for t in ["Image", "CompressedImage", "image"]
        )

    def _is_pointcloud_type(self, msg_type: str) -> bool:
        """判断是否为点云类型"""
        return "PointCloud" in msg_type

    def _process_image(
        self,
        topic: str,
        data: dict,
        quality: int = 80,
        resize: Optional[tuple[int, int]] = None,
    ) -> ProcessedData:
        """处理图像数据：JPEG 压缩 + base64"""
        try:
            import cv2

            # 从数据中获取图像数组
            img_array = data.get("data")
            if img_array is None:
                # 如果没有原始数据，尝试从 base64 解码
                b64 = data.get("base64")
                if b64:
                    img_array = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)
                    img_array = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

            if img_array is not None and isinstance(img_array, np.ndarray):
                # 缩放
                if resize:
                    img_array = cv2.resize(img_array, resize)

                # JPEG 压缩
                encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality]
                _, encoded = cv2.imencode(".jpg", img_array, encode_params)
                b64_data = base64.b64encode(encoded.tobytes()).decode("ascii")

                # 构建传输数据
                transport_data = {
                    "_msg_type": data.get("_msg_type", ""),
                    "format": "jpeg",
                    "quality": quality,
                    "width": img_array.shape[1],
                    "height": img_array.shape[0],
                    "base64": b64_data,
                }
                if resize:
                    transport_data["resize"] = list(resize)

                payload = json.dumps(transport_data).encode("utf-8")
                return ProcessedData(
                    tier=TopicTier.MEDIUM,
                    mqtt_payload=payload,
                    mqtt_topic=topic,
                )
        except ImportError:
            logger.warning("opencv-python not available, skipping image compression")

        # 无法压缩，按原始 JSON 传输
        return self.process_light(topic, data)

    def _process_pointcloud(
        self, data: dict, voxel_size: float = 0.1
    ) -> tuple[bytes, int]:
        """处理点云数据：体素降采样后二进制编码

        Returns:
            (二进制数据, 点数)
        """
        points_data = data.get("points")
        if points_data is not None and isinstance(points_data, np.ndarray):
            # 体素降采样
            if voxel_size > 0 and len(points_data) > 0:
                points_data = self._voxel_downsample(points_data, voxel_size)

            # 编码为二进制（x, y, z float32）
            binary = points_data.astype(np.float32).tobytes()
            return binary, len(points_data)

        # 没有原始数据，返回空
        return b"", 0

    def _voxel_downsample(
        self, points: np.ndarray, voxel_size: float
    ) -> np.ndarray:
        """体素降采样

        简单实现：将点云空间划分为体素网格，每个体素保留一个点。
        仅处理 x, y, z 三列。

        Args:
            points: N x 3+ 的点云数组
            voxel_size: 体素大小

        Returns:
            降采样后的点云
        """
        if len(points) == 0:
            return points

        # 确保至少有 3 列
        xyz = points[:, :3] if points.ndim > 1 else points.reshape(-1, 3)

        # 计算体素索引
        voxel_indices = np.floor(xyz / voxel_size).astype(np.int32)

        # 去重：每个体素保留第一个点
        _, unique_indices = np.unique(voxel_indices, axis=0, return_index=True)
        return points[unique_indices]

    def _encode_image_bytes(self, data: dict) -> bytes:
        """将图像数据编码为 JPEG 字节"""
        try:
            import cv2

            img_array = data.get("data")
            if img_array is not None and isinstance(img_array, np.ndarray):
                _, encoded = cv2.imencode(".jpg", img_array, [cv2.IMWRITE_JPEG_QUALITY, 85])
                return encoded.tobytes()
        except ImportError:
            pass

        # 回退：JSON 编码
        return json.dumps(data, default=self._json_default).encode("utf-8")

    @staticmethod
    def _json_default(obj: Any) -> Any:
        """JSON 序列化的默认处理器"""
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, bytes):
            return base64.b64encode(obj).decode("ascii")
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
