# MQTT 二进制传感器传输实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让 `mqtt_binary` 对二维激光 `/scan` 和二维栅格地图 `/map` 真正使用 MQTT 二进制 payload，而不是继续传输大 JSON 数组。

**架构：** 保留现有 `robot/<id>/sensor/<name>` 作为控制面 envelope topic，新增 `robot/<id>/sensor/<name>/bin` 作为数据面二进制 topic。Agent 发布 JSON envelope 后发布二进制 payload；Bridge 缓存 envelope，收到 `/bin` 后按 encoding 解码回 ROS 字段并发布到本地 ROS topic。旧 JSON payload 路径保持兼容。

**技术栈：** Python 3.8、pytest、MQTT topic helpers、`struct`、`zlib`、现有 `dict_to_ros_msg` / `ros_msg_to_dict`。

---

## 文件职责

- 创建：`protocol/binary_payloads.py`，集中定义二进制 encoding、envelope 构造、LaserScan 与 OccupancyGrid 编解码。
- 修改：`protocol/topics.py`，增加 `robot_sensor_binary()` 和 wildcard 解析支持。
- 修改：`agent/topic_handler.py`，为 `mqtt_binary` 增加二进制处理入口。
- 修改：`agent/base_agent.py`，保留运行态 `transport`，按 transport 发布 JSON 或 envelope + `/bin`。
- 修改：`bridge/mqtt_ros_bridge.py`，订阅并分发 `/bin`，根据缓存 envelope 解码二进制 payload。
- 修改：`qt_frontend/mqtt_client.py`，忽略或摘要 `/bin` payload，避免前端 JSON 解析大二进制。
- 测试：`tests/test_binary_payloads.py`、`tests/test_agent_topic_config.py`、`tests/test_mqtt_ros_bridge.py`、`tests/test_mqtt_client.py`。

## 任务 1：协议编码与解码

**文件：**
- 创建：`protocol/binary_payloads.py`
- 创建：`tests/test_binary_payloads.py`

- [ ] **步骤 1：编写失败的测试**

```python
def test_laser_scan_binary_roundtrip():
    source = {
        "header": {"seq": 7, "stamp": {"secs": 1, "nsecs": 2}, "frame_id": "base_scan"},
        "angle_min": 0.0,
        "angle_max": 1.0,
        "angle_increment": 0.5,
        "time_increment": 0.0,
        "scan_time": 0.1,
        "range_min": 0.12,
        "range_max": 3.5,
        "ranges": [1.0, 2.0],
        "intensities": [0.5, 0.25],
        "_msg_type": "sensor_msgs/LaserScan",
    }
    envelope, payload = encode_sensor_binary("/scan", "sensor_msgs/LaserScan", source, 3)
    restored = decode_sensor_binary(envelope, payload)
    assert envelope["encoding"] == "laser_scan_v1"
    assert restored["ranges"] == pytest.approx([1.0, 2.0])
    assert restored["intensities"] == pytest.approx([0.5, 0.25])
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 -m pytest tests/test_binary_payloads.py -q`
预期：FAIL，报错 `ModuleNotFoundError: No module named 'protocol.binary_payloads'`。

- [ ] **步骤 3：实现最少协议代码**

实现 `BinaryEnvelopeData` 约定字段：`topic`、`msg_type`、`encoding`、`seq`、`payload_format`、`payload_size`、`compression`、`meta`。LaserScan 使用小端 `float32` 编码 `ranges` 和 `intensities`，OccupancyGrid 使用 `int8[]` 并默认 `zlib` 压缩。

- [ ] **步骤 4：运行测试验证通过**

运行：`python3 -m pytest tests/test_binary_payloads.py -q`
预期：PASS。

## 任务 2：Agent 端按 transport 发布二进制

**文件：**
- 修改：`protocol/topics.py`
- 修改：`agent/base_agent.py`
- 修改：`agent/topic_handler.py`
- 修改：`tests/test_agent_topic_config.py`

- [ ] **步骤 1：编写失败的测试**

新增测试：订阅 `/scan` 且 `transport=mqtt_binary` 时，`publish_sensor_data()` 应发布两条 MQTT 消息：`robot/<id>/sensor/scan` 的 envelope JSON 和 `robot/<id>/sensor/scan/bin` 的 bytes；`transport=mqtt_json` 时保持单条旧 JSON。

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 -m pytest tests/test_agent_topic_config.py::test_publish_sensor_data_uses_mqtt_binary_transport_for_scan -q`
预期：FAIL，当前只发布单条 JSON。

- [ ] **步骤 3：实现最少代码**

在 `_subscription_runtime_info()` 中保存 `transport`；在 `_runtime_subscription_changed()` 中比较 `transport`；在 `publish_sensor_data()` 中当 `transport == "mqtt_binary"` 且协议支持该 `msg_type` 时发布 envelope 与 binary topic，否则回退旧 JSON。

- [ ] **步骤 4：运行测试验证通过**

运行：`python3 -m pytest tests/test_agent_topic_config.py::test_publish_sensor_data_uses_mqtt_binary_transport_for_scan tests/test_agent_topic_config.py::test_publish_sensor_data_keeps_json_transport_single_payload -q`
预期：PASS。

## 任务 3：Bridge 端解码二进制并保持旧 JSON 兼容

**文件：**
- 修改：`bridge/mqtt_ros_bridge.py`
- 修改：`tests/test_mqtt_ros_bridge.py`

- [ ] **步骤 1：编写失败的测试**

新增测试：先向 `_handle_sensor_data()` 传入 binary envelope，再向 `_handle_sensor_binary()` 传入 payload，Bridge 应调用 typed publisher 发布还原后的 ROS msg；旧 JSON sensor payload 测试继续通过。

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 -m pytest tests/test_mqtt_ros_bridge.py::TestSensorData::test_binary_laser_scan_roundtrip_publishes_ros_message -q`
预期：FAIL，缺少 `_handle_sensor_binary()` 或不会识别 envelope。

- [ ] **步骤 3：实现最少代码**

订阅 `robot/+/sensor/+/bin`；MQTT 分发优先识别 `/bin`；Bridge 缓存 envelope keyed by `(robot_id, sensor_name, seq)`；收到 binary payload 后调用 `decode_sensor_binary()`，再复用现有 JSON sensor 发布路径。

- [ ] **步骤 4：运行测试验证通过**

运行：`python3 -m pytest tests/test_mqtt_ros_bridge.py::TestSensorData::test_binary_laser_scan_roundtrip_publishes_ros_message tests/test_mqtt_ros_bridge.py::TestSensorData -q`
预期：PASS。

## 任务 4：Qt MQTT 客户端保护二进制 payload

**文件：**
- 修改：`qt_frontend/mqtt_client.py`
- 修改：`tests/test_mqtt_client.py`

- [ ] **步骤 1：编写失败的测试**

新增测试：收到 `robot/robot_001/sensor/scan/bin` 时，不调用 `json.loads()`，只发出轻量摘要或直接忽略，不触发错误信号。

- [ ] **步骤 2：运行测试验证失败**

运行：`python3 -m pytest tests/test_mqtt_client.py::TestOnMessageStatus::test_binary_sensor_payload_is_not_json_decoded -q`
预期：FAIL，当前通配路径可能尝试按 JSON 解析。

- [ ] **步骤 3：实现最少代码**

在 `_on_message()` 中优先判断 topic 是否以 `/bin` 结尾。二进制 payload 不进入 `Message.from_json()` 或 `json.loads()`；流量面板需要时只接收 topic、size、transport 摘要。

- [ ] **步骤 4：运行测试验证通过**

运行：`python3 -m pytest tests/test_mqtt_client.py::TestOnMessageStatus::test_binary_sensor_payload_is_not_json_decoded -q`
预期：PASS。

## 任务 5：集成验证

**文件：**
- 修改：`docs/work-log-2026-06-17.md`

- [ ] **步骤 1：运行聚焦测试**

运行：
`python3 -m pytest tests/test_binary_payloads.py tests/test_agent_topic_config.py tests/test_mqtt_ros_bridge.py tests/test_mqtt_client.py -q`
预期：PASS。

- [ ] **步骤 2：运行 lint**

运行：`ruff check protocol agent bridge qt_frontend tests`
预期：0 errors。

- [ ] **步骤 3：运行态采样**

在 turtlebot_001 容器运行时，订阅：
`timeout 12 mosquitto_sub -h localhost -t robot/turtlebot_001/sensor/scan/bin -C 2 > /tmp/mqtt_scan_bin_samples`
预期：采样文件首字节不再是 `{`，`wc -c` 显示二进制 payload 明显小于旧 JSON scan 样本。

- [ ] **步骤 4：记录工作日志**

在 `docs/work-log-2026-06-17.md` 记录协议变化、验证命令、结果和未验证风险。
