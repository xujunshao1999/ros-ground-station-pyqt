"""
Agent 启动入口

用法：
    # 默认启动 Mock Agent
    python -m agent.main

    # 指定配置文件
    python -m agent.main --config agent/config.yaml

    # 指定机器人 ID
    python -m agent.main --robot-id robot_002

    # 指定 Broker 地址
    python -m agent.main --broker-host 192.168.1.100 --broker-port 1883

    # 使用 ROS 1 Agent（需要 ROS 环境）
    python -m agent.main --agent-type ros1
"""

import argparse
import logging
import sys
import os
from pathlib import Path

# 确保项目根目录在 path 中
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.base_agent import AgentConfig


def main():
    parser = argparse.ArgumentParser(description="ROS Ground Station Agent")
    parser.add_argument(
        "--config",
        default="agent/config.yaml",
        help="配置文件路径 (default: agent/config.yaml)",
    )
    parser.add_argument(
        "--robot-id",
        default=None,
        help="机器人 ID (覆盖配置文件)",
    )
    parser.add_argument(
        "--broker-host",
        default=None,
        help="MQTT Broker 地址 (覆盖配置文件)",
    )
    parser.add_argument(
        "--broker-port",
        type=int,
        default=None,
        help="MQTT Broker 端口 (覆盖配置文件)",
    )
    parser.add_argument(
        "--agent-type",
        choices=["mock", "ros1", "ros2"],
        default="mock",
        help="Agent 类型 (default: mock)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="日志级别 (default: INFO)",
    )

    args = parser.parse_args()

    # 配置日志
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # 加载并校验配置（优先级：命令行 > 环境变量 > YAML > 默认值）
    config = AgentConfig.from_yaml(args.config)
    if args.robot_id:
        config.robot_id = args.robot_id
    elif os.environ.get("ROBOT_ID"):
        config.robot_id = os.environ["ROBOT_ID"]
    if args.broker_host:
        config.broker_host = args.broker_host
    elif os.environ.get("BROKER_HOST"):
        config.broker_host = os.environ["BROKER_HOST"]
    if args.broker_port:
        config.broker_port = args.broker_port
    elif os.environ.get("BROKER_PORT"):
        config.broker_port = int(os.environ["BROKER_PORT"])

    logger = logging.getLogger("agent.main")
    logger.info(f"Robot ID: {config.robot_id}")
    logger.info(f"Broker: {config.broker_host}:{config.broker_port}")
    logger.info(f"Agent type: {args.agent_type}")

    # 创建 Agent
    if args.agent_type == "mock":
        from agent.mock_agent import MockAgent

        agent = MockAgent(config)
    elif args.agent_type == "ros1":
        try:
            from agent.ros1_agent import ROS1Agent

            agent = ROS1Agent(config)
        except ImportError:
            logger.error("ROS 1 Agent requires rospy. Use --agent-type mock for development.")
            sys.exit(1)
    elif args.agent_type == "ros2":
        try:
            from agent.ros2_agent import ROS2Agent

            agent = ROS2Agent(config)
        except ImportError:
            logger.error("ROS 2 Agent requires rclpy. Use --agent-type mock for development.")
            sys.exit(1)
    else:
        logger.error(f"Unknown agent type: {args.agent_type}")
        sys.exit(1)

    # 启动
    try:
        agent.start()
    except KeyboardInterrupt:
        logger.info("Interrupted, shutting down...")
        agent.stop()


if __name__ == "__main__":
    main()
