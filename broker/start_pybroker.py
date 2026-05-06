#!/usr/bin/env python3
"""
纯 Python MQTT Broker 启动脚本（amqtt）
用于没有安装 Mosquitto 的开发环境

功能：
- 在 1883 端口启动 MQTT Broker
- 支持 MQTT v3.1.1
- 开发阶段替代 Mosquitto

注意：amqtt 性能有限，仅用于开发测试
      生产环境请使用 Mosquitto
"""

import asyncio
import logging
import sys
import os

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from amqtt.broker import Broker
except ImportError:
    print("[ERROR] amqtt not installed. Run: pip install amqtt")
    sys.exit(1)


# Broker 配置
BROKER_CONFIG = {
    "listeners": {
        "default": {
            "type": "tcp",
            "bind": "0.0.0.0:1883",
        },
    },
    "sys_interval": 10,
    "auth": {
        "allow-anonymous": True,
    },
}


async def start_broker():
    """启动 MQTT Broker"""
    # 配置日志
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    # amqtt 日志
    broker_logger = logging.getLogger("amqtt.broker")
    broker_logger.setLevel(logging.INFO)
    broker_logger.addHandler(handler)

    # 启动 Broker
    broker = Broker(BROKER_CONFIG)

    print("=" * 50)
    print("  ROS Ground Station - Python MQTT Broker")
    print("=" * 50)
    print(f"  Host: 0.0.0.0")
    print(f"  Port: 1883")
    print(f"  Auth: anonymous allowed")
    print(f"  Note: For production, use Mosquitto instead")
    print("=" * 50)
    print()

    await broker.start()

    # 保持运行
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        await broker.shutdown()


def main():
    try:
        asyncio.run(start_broker())
    except KeyboardInterrupt:
        print("\n[Broker] Stopped.")


if __name__ == "__main__":
    main()
