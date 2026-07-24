# 可配置模式命令按钮实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将模式控制区改为 4 个可持久化配置的 ROS1 命令按钮，复用现有机器人话题发现结果，递归生成消息参数表单，并将每次点击可靠地下发给当时全部在线机器人。

**架构：** `protocol/` 新增定向消息结构查询协议，机器人 Agent 负责解析本地 ROS 消息类并将严格校验后的 JSON 参数发布为真实 ROS 消息。Qt 前端提取共享话题目录，使用独立配置仓库、递归 schema 表单和批次确认模型；`MainWindow` 只协调在线机器人集合、MQTT 发送和信号连接。顶部工具栏“全部急停”和单机器人速度控制保持原行为。

**技术栈：** Python 3.8、ROS Noetic `rospy` / `genpy`、PyQt5、paho-mqtt 2.x、YAML、pytest、ruff。

---

## 术语与执行约定

- **slot**：模式控制区固定位置，只有 `slot_1`、`slot_2`、`slot_3`、`slot_4`。slot ID 是本地配置键，不进入 ROS 消息。
- **话题发现**：复用现有 `station/discover` 请求和 `discover_resp` 响应。ROS1 Agent 通过 `rospy.get_published_topics("/")` 返回 `topic + msg_type`；本计划不新增第二套话题发现协议。
- **共享话题目录（RobotTopicCatalog）**：前端内存中的单一缓存，按 robot ID 保存已发现的 topic/type。`TopicConfigPanel` 与命令按钮设置窗口读取同一实例，避免复制 `TopicConfigPanel._available_topics_by_robot`。
- **代表机器人**：在线机器人 ID 排序后的第一台。项目按同构机器人集群处理，仅向代表机器人查询消息字段结构；最终每台目标机器人仍独立校验并发布。
- **schema**：Agent 从 ROS 消息类 `__slots__`、`_slot_types` 解析出的递归字段树。schema 只描述类型，不包含可执行代码。
- **结构化表单**：根据 schema 生成的 Qt 控件。基础类型使用专用输入控件，嵌套消息递归分组，数组使用受校验的 JSON 数组编辑器。
- **JSON 高级编辑**：直接编辑完整 `data` object。它与结构化表单共享同一份参数，切换时双向同步并校验。
- **未经在线校验**：手工输入的 msg_type 未成功取得 schema。允许保存 object 类型 JSON，但界面必须显示该状态；执行成败以 Agent 本地消息类为准。
- **exec_id**：一次按钮点击生成的 12 位十六进制 ID。同一批发往多台机器人的命令共用该 ID，前端以 `(exec_id, robot_id)` 汇总确认。
- **cmd_ack**：现有机器人确认消息，包含 `exec_id`、`result` 和 `message`。5 秒没有确认记为超时，不自动重发。
- **严格转换**：`dict_to_ros_msg(data, msg_type, strict=True)` 遇到未知字段、数组形状错误或基础值无法转换时抛出带字段路径的 `ValueError`。默认 `strict=False`，保持 Bridge 与编队链路现有兼容行为。
- **资源边界**：schema 最大递归深度 12、最多 512 个字段、JSON 编码后最大 256 KiB；单条按钮 `data` JSON 最大 256 KiB。ROS1 Agent 最多缓存 32 个 custom Publisher，前端最多保留最近 20 个已完成命令批次；超限请求必须明确失败，缓存淘汰必须释放对应资源。
- **正式入口**：`./qt_frontend/scripts/start.sh` 启动 `python3 qt_frontend/main.py`，由 `qt_frontend.main_window.MainWindow` 接线。
- **备用入口**：`qt_frontend/panels_setup.py` 由 C++ 嵌入路径调用，当前本身没有 MQTT 客户端或命令接线。本计划保持 `CommandPanel()` 无参构造兼容，使备用入口仍可渲染，但不为该备用入口新增话题发现、schema 查询或命令发送；若发布流程改用该入口，需先单独补齐 MQTT 生命周期。
- **运行态保护**：执行每个任务前检查 `git status --short`，不覆盖用户对 `qt_frontend/config/transmit_config.yaml`、机器人配置或工作日志的既有修改。只暂存当前任务列出的文件，永不暂存 `.agents/`、`.codex/`、`.claude/skills/`。

## 设计依据

- 已批准规格：`docs/superpowers/specs/2026-07-24-configurable-command-buttons-design.md`
- 协议权威文档：`docs/protocol.md`
- 当前命令入口：`qt_frontend/panels/command_panel.py` 的 `command_sent` 与 `qt_frontend/main_window.py::_on_command()`
- 当前话题发现入口：`agent/base_agent.py::_handle_discover()` 与 `qt_frontend/panels/topic_config_panel.py::on_discover_response()`
- 当前通用 ROS 转换：`agent/dict_to_ros_msg.py::dict_to_ros_msg()`

## 文件职责

- 修改 `protocol/messages.py`：增加 schema query/response 消息类型、数据类和工厂方法。
- 修改 `protocol/topics.py`：增加目标机器人 schema query/response topic、QoS 和严格解析。
- 创建 `agent/message_schema.py`：动态加载 ROS 消息类并生成有界递归 schema。
- 修改 `agent/dict_to_ros_msg.py`：增加默认关闭的严格转换模式与字段路径错误。
- 修改 `agent/base_agent.py`：订阅、校验和响应 schema query。
- 修改 `agent/ros1_agent.py`：提供真实 schema，严格构造 custom ROS 消息并缓存 Publisher。
- 修改 `agent/mock_agent.py`：提供无 ROS schema 示例并校验 custom 参数结构。
- 创建 `qt_frontend/topic_catalog.py`：保存并广播复用的机器人话题发现结果。
- 创建 `qt_frontend/command_button_config.py`：定义 4 个 slot 的模型、校验和原子 YAML 存储。
- 创建 `qt_frontend/message_schema.py`：生成 schema 默认参数并校验 JSON 数据，保持零 Qt 依赖。
- 创建 `qt_frontend/command_batch.py`：跟踪一批多机器人命令的成功、失败和超时。
- 创建 `qt_frontend/panels/message_form.py`：将递归 schema 渲染成 Qt 表单并回读类型化数据。
- 创建 `qt_frontend/panels/command_button_dialog.py`：编辑 4 个 slot，协调话题选择、schema 请求、表单/JSON 同步和整批保存。
- 修改 `qt_frontend/panels/command_panel.py`：保留单机器人速度区，替换模式区为 4 个全体命令按钮并展示批次结果。
- 修改 `qt_frontend/panels/robot_list_panel.py`：在状态、发现和心跳超时导致在线集合变化时发出统一 signal。
- 修改 `qt_frontend/panels/topic_config_panel.py`：从共享话题目录读取发现结果。
- 修改 `qt_frontend/panels/__init__.py`：导出新增对话框或表单中需要公开的类型。
- 修改 `qt_frontend/mqtt_client.py`：发送 schema query、订阅响应并发出 Qt signal。
- 修改 `qt_frontend/main_window.py`：创建共享目录，连接 schema、批量发送和确认信号。
- 创建 `qt_frontend/config/command_buttons.yaml`：提供版本 1、4 个 null slot 的默认配置。
- 修改 `docs/protocol.md`：在对应协议实现任务中同步记录 schema query/response 和 custom 命令真实 ROS 消息语义，最终任务只复核一致性。
- 创建 `docs/work-log-2026-07-24.md`：按实际执行结果记录功能、验证和未覆盖风险。
- 修改或创建对应 `tests/test_*.py`：每个模块使用聚焦测试，Qt 测试统一 offscreen。

## 任务依赖顺序

1. 任务 1 定义协议符号，供 Agent 与 Qt MQTT 客户端共同使用。
2. 任务 2 生成 schema；任务 3 使用同一 ROS 类型加载和转换基础。
3. 任务 4 打通 schema MQTT 请求/响应，但尚不改界面。
4. 任务 5 和任务 6 分别建立共享话题目录与本地配置，可独立测试。
5. 任务 7 建立纯 schema 数据逻辑和 Qt 表单，任务 8 才组装设置对话框。
6. 任务 9 建立批次模型并替换模式区，任务 10 最后接入正式主入口。
7. 任务 1 和任务 3 随协议实现同步更新权威文档；任务 11 复核协议文档、编写工作日志并执行全量验证。

### 任务 1：定义消息结构查询协议

**文件：**
- 修改：`protocol/messages.py:23-38, 148-163, 380-445`
- 修改：`protocol/topics.py:26-66, 107-137, 265-296`
- 修改：`docs/protocol.md`
- 测试：`tests/test_protocol_messages.py`
- 测试：`tests/test_protocol_topics.py`

- [ ] **步骤 1：编写协议消息与 topic 失败测试**

在 `tests/test_protocol_messages.py` 增加：

```python
def test_message_schema_query_and_response_round_trip(factory):
    query = MessageSchemaQueryData(
        request_id="req-1",
        msg_type="geometry_msgs/Twist",
    )
    query_message = factory.message_schema_query(query, dst="robot_001")
    response = MessageSchemaResponseData(
        request_id="req-1",
        msg_type="geometry_msgs/Twist",
        result="ok",
        schema={"type": "geometry_msgs/Twist", "kind": "message", "fields": []},
    )
    response_message = factory.message_schema_response(response)

    assert query_message.type == MessageType.MESSAGE_SCHEMA_QUERY
    assert query_message.dst == "robot_001"
    assert response_message.type == MessageType.MESSAGE_SCHEMA_RESPONSE
    assert response_message.data["request_id"] == "req-1"
```

在 `tests/test_protocol_topics.py` 增加：

```python
def test_message_schema_topics_and_parser_are_targeted():
    assert station_message_schema_query("r1") == "station/r1/message_schema/query"
    assert station_message_schema_response("r1") == "station/r1/message_schema/response"
    assert parse_station_topic("station/r1/message_schema/query") == {
        "type": "message_schema_query", "robot_id": "r1"
    }
    assert parse_station_topic("station/r1/message_schema/response") == {
        "type": "message_schema_response", "robot_id": "r1"
    }
    assert parse_station_topic("station/r1/message_schema/query/extra") is None
```

- [ ] **步骤 2：运行测试，确认只因新协议符号缺失而失败**

运行：

```bash
python3 -m pytest \
  tests/test_protocol_messages.py::test_message_schema_query_and_response_round_trip \
  tests/test_protocol_topics.py::test_message_schema_topics_and_parser_are_targeted -q
```

预期：收集阶段因 `MessageSchemaQueryData`、`MessageSchemaResponseData` 或 schema topic helper 尚未定义而失败；不得出现 ROS、Qt 或 fixture 错误。

- [ ] **步骤 3：实现消息类型、数据类与工厂方法**

在 `protocol/messages.py` 增加以下稳定接口，并把两个数据类加入 `MessageFactory._make()` 的 dataclass 白名单：

```python
class MessageType(str, Enum):
    # 保留现有成员
    MESSAGE_SCHEMA_QUERY = "message_schema_query"
    MESSAGE_SCHEMA_RESPONSE = "message_schema_response"


@dataclass
class MessageSchemaQueryData:
    request_id: str = ""
    msg_type: str = ""


@dataclass
class MessageSchemaResponseData:
    request_id: str = ""
    msg_type: str = ""
    result: str = "error"
    schema: Dict[str, Any] = field(default_factory=dict)
    error: str = ""


def message_schema_query(
    self,
    query: MessageSchemaQueryData,
    dst: str,
) -> Message:
    return self._make(MessageType.MESSAGE_SCHEMA_QUERY, query, dst=dst)


def message_schema_response(
    self,
    response: MessageSchemaResponseData,
) -> Message:
    return self._make(MessageType.MESSAGE_SCHEMA_RESPONSE, response)
```

- [ ] **步骤 4：实现精确 schema topic 与 QoS**

在 `protocol/topics.py` 增加 `_MESSAGE_SCHEMA = "message_schema"`、两个 helper 和 `TOPIC_QOS` 项；`parse_station_topic()` 只接受精确 4 段：

```python
def station_message_schema_query(robot_id: str) -> str:
    return f"{STATION_PREFIX}/{robot_id}/{_MESSAGE_SCHEMA}/query"


def station_message_schema_response(robot_id: str) -> str:
    return f"{STATION_PREFIX}/{robot_id}/{_MESSAGE_SCHEMA}/response"
```

解析分支返回 `message_schema_query` 或 `message_schema_response`，任何尾随层级返回 `None`。同时收紧现有 config 分支为精确 4 段，避免本任务引入宽松解析分支。

- [ ] **步骤 5：同步更新 schema 权威协议文档**

在 `docs/protocol.md` 的 topic 表加入 `station/{robot_id}/message_schema/query` 和 `station/{robot_id}/message_schema/response`。增加与本任务数据类完全一致的 query/response JSON 示例和字段表，明确 QoS、定向 robot ID、`request_id` 匹配规则，以及 schema JSON 编码后不得超过 256 KiB；此时只记录查询协议，不提前描述任务 3 的 custom 命令变化。

- [ ] **步骤 6：运行协议测试并提交**

运行：

```bash
python3 -m pytest tests/test_protocol_messages.py tests/test_protocol_topics.py -q
ruff check protocol/messages.py protocol/topics.py tests/test_protocol_messages.py tests/test_protocol_topics.py
```

预期：全部通过，现有 discover、topic request、config 和 fleet topic 测试不回归。

```bash
git add protocol/messages.py protocol/topics.py docs/protocol.md \
  tests/test_protocol_messages.py tests/test_protocol_topics.py
git commit -m "feat: 定义消息结构查询协议"
```

### 任务 2：生成有界递归 ROS 消息结构

**文件：**
- 创建：`agent/message_schema.py`
- 创建：`tests/test_message_schema.py`
- 修改：`agent/ros1_agent.py:205-225`
- 修改：`agent/mock_agent.py:148-160`

- [ ] **步骤 1：使用 fake ROS 消息类编写 schema 失败测试**

在 `tests/test_message_schema.py` 定义带 `__slots__`、`_slot_types` 的 `FakeHeader`、`FakePoint`、`FakeCommand`，patch `agent.message_schema._get_message_class`，覆盖基础字段、嵌套字段、动态数组、固定数组、循环和字段总数：

```python
class FakeHeader:
    __slots__ = ["stamp", "frame_id"]
    _slot_types = ["time", "string"]


class FakePoint:
    __slots__ = ["x", "y"]
    _slot_types = ["float64", "float64"]


class FakeCommand:
    __slots__ = ["header", "points", "enabled"]
    _slot_types = ["test_msgs/Header", "test_msgs/Point[]", "bool"]


def test_build_message_schema_recurses_nested_and_array_types(monkeypatch):
    classes = {
        "test_msgs/Header": FakeHeader,
        "test_msgs/Point": FakePoint,
        "test_msgs/Command": FakeCommand,
    }
    monkeypatch.setattr(
        "agent.message_schema._get_message_class",
        lambda msg_type: classes.get(msg_type),
    )

    schema = build_message_schema("test_msgs/Command")

    assert schema["type"] == "test_msgs/Command"
    fields = {field["name"]: field for field in schema["fields"]}
    assert fields["header"]["kind"] == "message"
    assert fields["header"]["fields"][0]["name"] == "stamp"
    assert fields["points"]["is_array"] is True
    assert fields["points"]["base_type"] == "test_msgs/Point"
```

再断言未知类型、循环依赖、深度超过 12、字段超过 512 都抛 `MessageSchemaError`，错误文本包含类型名。

- [ ] **步骤 2：运行测试确认模块缺失**

```bash
python3 -m pytest tests/test_message_schema.py -q
```

预期：因 `agent.message_schema` 尚不存在而在收集阶段失败。

- [ ] **步骤 3：实现 schema 构建器**

`agent/message_schema.py` 必须复用 `agent.dict_to_ros_msg._get_message_class` 与 `_parse_type_str`，公开：

```python
MAX_SCHEMA_DEPTH = 12
MAX_SCHEMA_FIELDS = 512


class MessageSchemaError(ValueError):
    pass


def build_message_schema(
    msg_type: str,
    max_depth: int = MAX_SCHEMA_DEPTH,
    max_fields: int = MAX_SCHEMA_FIELDS,
) -> Dict[str, Any]:
    field_count = 0
    stack: List[str] = []

    def build(type_name: str, depth: int) -> Dict[str, Any]:
        nonlocal field_count
        if depth > max_depth:
            raise MessageSchemaError("schema depth exceeds %d" % max_depth)
        if type_name in stack:
            raise MessageSchemaError("recursive message type: %s" % type_name)
        msg_class = _get_message_class(type_name)
        if msg_class is None:
            raise MessageSchemaError("unknown ROS message type: %s" % type_name)
        names = list(getattr(msg_class, "__slots__", []))
        types = list(getattr(msg_class, "_slot_types", []))
        if len(names) != len(types):
            raise MessageSchemaError("slot metadata mismatch: %s" % type_name)

        stack.append(type_name)
        fields: List[Dict[str, Any]] = []
        try:
            for name, raw_type in zip(names, types):
                field_count += 1
                if field_count > max_fields:
                    raise MessageSchemaError(
                        "schema fields exceed %d" % max_fields
                    )
                base_type, is_array, array_len = _parse_type_str(raw_type)
                if base_type in {"time", "duration"}:
                    kind = base_type
                    nested_fields: List[Dict[str, Any]] = []
                elif "/" in base_type:
                    kind = "message"
                    nested_fields = build(base_type, depth + 1)["fields"]
                else:
                    kind = "primitive"
                    nested_fields = []
                fields.append({
                    "name": name,
                    "type": raw_type,
                    "base_type": base_type,
                    "kind": kind,
                    "is_array": is_array,
                    "array_len": array_len,
                    "fields": nested_fields,
                })
        finally:
            stack.pop()
        return {"type": type_name, "kind": "message", "fields": fields}

    return build(msg_type, 0)
```

每个 field 必须固定包含：`name`、原始 `type`、`base_type`、`kind`、`is_array`、`array_len`、`fields`。`kind` 只允许 `primitive`、`time`、`duration`、`message`；嵌套消息数组仍递归填充 `fields`。递归栈重复类型立即报错，字段计数包含所有层级。

- [ ] **步骤 4：在 ROS1Agent 与 MockAgent 暴露 schema hook**

在 `ROS1Agent` 增加：

```python
def _get_message_schema(self, msg_type: str) -> Dict[str, Any]:
    return build_message_schema(msg_type)
```

在 `MockAgent` 为 `geometry_msgs/Twist` 和 `std_msgs/Bool` 返回固定 schema；其他合法类型返回一个只含 `type/kind/fields` 的空结构，便于无 ROS 流程测试，但响应中必须保留实际 `msg_type`。

- [ ] **步骤 5：运行测试并提交**

```bash
python3 -m pytest tests/test_message_schema.py tests/test_ros1_agent.py -q
ruff check agent/message_schema.py agent/ros1_agent.py agent/mock_agent.py tests/test_message_schema.py
```

预期：schema 测试和既有 ROS1 Agent 测试全部通过。

```bash
git add agent/message_schema.py agent/ros1_agent.py agent/mock_agent.py tests/test_message_schema.py
git commit -m "feat: 解析ROS消息字段结构"
```

### 任务 3：严格转换并发布真实 Custom ROS 消息

**文件：**
- 修改：`agent/dict_to_ros_msg.py`
- 修改：`agent/ros1_agent.py:71-98, 149-203`
- 修改：`agent/mock_agent.py:105-147`
- 修改：`docs/protocol.md`
- 测试：`tests/test_dict_to_ros_msg.py`
- 测试：`tests/test_ros1_agent.py`
- 测试：`tests/test_agent_topic_config.py`

- [ ] **步骤 1：编写严格转换和 custom 发布失败测试**

在 `tests/test_dict_to_ros_msg.py` 增加：

```python
def test_strict_conversion_rejects_unknown_field_with_path(monkeypatch):
    monkeypatch.setattr(
        "agent.dict_to_ros_msg._get_message_class",
        _mock_get_message_class,
    )
    with pytest.raises(ValueError, match=r"test_msgs/Simple\.unknown"):
        dict_to_ros_msg(
            {"unknown": 1},
            "test_msgs/Simple",
            strict=True,
        )
```

补充非数组传给数组、固定数组长度错误、嵌套字段类型错误和非法数字值测试；原有 `strict=False` 测试必须继续接受未知字段并告警。在 `tests/test_ros1_agent.py` 另加缓存上限测试：依次发布 33 个不同 topic，断言只保留最近 32 个，第一个 Publisher 调用一次 `unregister()`；再次使用缓存 topic 时移动到 LRU 末尾，同 topic 换类型仍先注销旧 Publisher。

在 `tests/test_ros1_agent.py` 增加：

```python
def test_custom_command_publishes_configured_ros_type(monkeypatch):
    mock_rospy = MagicMock()
    publisher = MagicMock()
    mock_rospy.Publisher.return_value = publisher
    monkeypatch.setattr("agent.ros1_agent.rospy", mock_rospy)
    converted = object()
    converter = MagicMock(return_value=converted)
    monkeypatch.setattr("agent.ros1_agent.dict_to_ros_msg", converter)
    agent = object.__new__(ROS1Agent)
    agent._command_publishers = OrderedDict()

    ok, message = ROS1Agent._execute_command(agent, CmdData(
        action="custom",
        params={
            "topic": "/exploration/control",
            "msg_type": "my_pkg/Control",
            "data": {"command": "start"},
        },
    ))

    assert ok is True
    converter.assert_called_once_with(
        {"command": "start"}, "my_pkg/Control", strict=True
    )
    mock_rospy.Publisher.assert_called_once_with(
        "/exploration/control", object, queue_size=1
    )
    publisher.publish.assert_called_once_with(converted)
    assert "my_pkg/Control" in message
```

- [ ] **步骤 2：运行目标测试确认现有行为不满足要求**

```bash
python3 -m pytest \
  tests/test_dict_to_ros_msg.py::test_strict_conversion_rejects_unknown_field_with_path \
  tests/test_ros1_agent.py::test_custom_command_publishes_configured_ros_type -q
```

预期：前者因 `strict` 参数不存在而失败；后者因当前 custom 固定发布 `std_msgs/String` 且读取 `msg` 而失败。

- [ ] **步骤 3：实现默认兼容的严格转换**

将公开签名改为 `dict_to_ros_msg(data: dict, msg_type: str, strict: bool = False, field_path: str = "")`，内部转换签名改为 `_convert_value(val: Any, type_str: str, strict: bool = False, field_path: str = "")`。

所有递归调用透传 `strict` 和完整字段路径。严格模式拒绝未知字段、数组输入形状错误、固定数组长度不符、嵌套消息非 object、`bool` 冒充数字，以及基础类型转换异常；兼容模式保持现有返回原值或限频告警行为。

- [ ] **步骤 4：实现 custom Publisher 缓存和错误确认**

从 `collections` 导入 `OrderedDict`，并在 `ROS1Agent.__init__()` 初始化：

```python
MAX_COMMAND_PUBLISHERS = 32
self._command_publishers: "OrderedDict[str, Tuple[str, object]]" = OrderedDict()
```

新增 `_publish_custom_command(topic, msg_type, data)`：校验 topic 以 `/` 开头、msg_type 符合 `package/Message`、data 是 dict 且 JSON 大小不超过 256 KiB；调用严格转换。缓存使用 `collections.OrderedDict`，键为 topic，值为 `(msg_type, publisher)`。命中相同 topic/type 后调用 `move_to_end()`；同 topic 改类型时先调用旧 publisher 的 `unregister()` 并删除旧项；创建新 Publisher 后若超过 32 项，使用 `popitem(last=False)` 淘汰最久未使用项并调用其 `unregister()`。创建或发布异常必须清理本次无效缓存并返回 `(False, 清晰错误)`，不能退出 Agent；`unregister()` 自身异常只记录限频警告，不得中断当前命令。

`CmdAction.CUSTOM` 只读取 `params.topic`、`params.msg_type`、`params.data`。显式使用 `std_msgs/String` 时参数格式为 `data: {data: "文本"}`，不保留旧的隐式 JSON String 包装。

- [ ] **步骤 5：让 MockAgent 校验相同协议边界**

Mock custom 必须拒绝空 topic、非法 msg_type、非 dict data 和超过 256 KiB 的 data；合法输入返回包含 topic/type 的成功文本，不尝试导入 ROS。

- [ ] **步骤 6：同步更新 custom 权威协议文档**

在 `docs/protocol.md` 将 `action: custom` 的 `params` 权威格式改为 `{topic, msg_type, data}`，加入 JSON 示例和字段约束。明确 Agent 使用 `msg_type` 发布真实 ROS 消息、自定义消息包必须安装并 source 在目标 Agent 环境，地面站仅在本地 Bridge 也要重发该自定义传感器类型时才需要同一消息包；删除或改写仍描述隐式 `std_msgs/String` 包装的旧内容。

- [ ] **步骤 7：运行回归并提交**

```bash
python3 -m pytest \
  tests/test_dict_to_ros_msg.py \
  tests/test_ros1_agent.py \
  tests/test_agent_topic_config.py -q
ruff check agent/dict_to_ros_msg.py agent/ros1_agent.py agent/mock_agent.py \
  tests/test_dict_to_ros_msg.py tests/test_ros1_agent.py tests/test_agent_topic_config.py
```

预期：全部通过；fleet JSON 转换仍使用默认非严格模式。

```bash
git add agent/dict_to_ros_msg.py agent/ros1_agent.py agent/mock_agent.py docs/protocol.md \
  tests/test_dict_to_ros_msg.py tests/test_ros1_agent.py tests/test_agent_topic_config.py
git commit -m "feat: 发布真实自定义ROS消息"
```

### 任务 4：打通 Schema MQTT 查询链路

**文件：**
- 修改：`agent/base_agent.py:620-640, 700-730, 808-825`
- 修改：`qt_frontend/mqtt_client.py:12-45, 107-150, 175-190, 330-370`
- 测试：`tests/test_agent_topic_config.py`
- 测试：`tests/test_mqtt_client.py`

- [ ] **步骤 1：编写 Agent 查询响应失败测试**

在 `tests/test_agent_topic_config.py` 的 `RecordingAgent` 增加 `_get_message_schema()` 固定返回值，并新增测试：构造发往 `station/r1/message_schema/query` 的 `MessageSchemaQueryData`，调用 `_on_message()`，断言发布到 `station/r1/message_schema/response`，响应保留 request ID/type/result/schema。另覆盖目标 robot ID 不匹配、空 request ID、空 msg_type、schema 编码超过 256 KiB 和 hook 抛错。

- [ ] **步骤 2：编写 Qt MQTT 发送与接收失败测试**

在 `tests/test_mqtt_client.py` 增加：

```python
def test_send_message_schema_query_uses_target_topic(client, mock_paho):
    client.connect()
    client.send_message_schema_query("r1", "req-1", "geometry_msgs/Twist")
    topic, payload = mock_paho.publish.call_args.args[:2]
    message = Message.from_json(payload.decode("utf-8"))

    assert topic == "station/r1/message_schema/query"
    assert message.type == "message_schema_query"
    assert message.data == {
        "request_id": "req-1",
        "msg_type": "geometry_msgs/Twist",
    }
```

再模拟 `station/r1/message_schema/response`，断言 `schema_response_received.emit("r1", data)`。

- [ ] **步骤 3：运行测试确认 handler 与 signal 缺失**

```bash
python3 -m pytest \
  tests/test_agent_topic_config.py -k message_schema \
  tests/test_mqtt_client.py -k message_schema -q
```

预期：因 BaseAgent 未订阅/处理 schema query、MqttClient 没有发送方法或 signal 而失败。

- [ ] **步骤 4：实现 BaseAgent 查询处理**

BaseAgent 连接时订阅 `station_message_schema_query(self.config.robot_id)`；分发前同时验证解析出的 robot ID、`Message.dst` 与本机 ID。新增默认 hook：

```python
def _get_message_schema(self, msg_type: str) -> Dict[str, Any]:
    raise ValueError("message schema is not available")
```

`_handle_message_schema_query()` 严格校验 `request_id/msg_type`，调用 hook，使用 `json.dumps(schema, ensure_ascii=False).encode("utf-8")` 检查 256 KiB 边界，任何错误都返回 `result="error"` 和非空 `error`。响应发布 QoS 1。

- [ ] **步骤 5：实现 MqttClient schema API**

增加 `schema_response_received = pyqtSignal(str, dict)`；连接成功订阅 `station/+/message_schema/response`；`send_message_schema_query(robot_id, request_id, msg_type)` 使用协议数据类和工厂或等价 `Message` 构造；`_dispatch()` 只在 parser 类型为 `message_schema_response` 时发出新 signal。

- [ ] **步骤 6：运行测试并提交**

```bash
python3 -m pytest tests/test_agent_topic_config.py tests/test_mqtt_client.py -q
ruff check agent/base_agent.py qt_frontend/mqtt_client.py \
  tests/test_agent_topic_config.py tests/test_mqtt_client.py
```

预期：全部通过，MQTT 连接订阅数测试同步更新为包含 schema response wildcard。

```bash
git add agent/base_agent.py qt_frontend/mqtt_client.py \
  tests/test_agent_topic_config.py tests/test_mqtt_client.py
git commit -m "feat: 接通消息结构查询链路"
```

### 任务 5：提取共享机器人话题目录

**文件：**
- 创建：`qt_frontend/topic_catalog.py`
- 创建：`tests/test_topic_catalog.py`
- 修改：`qt_frontend/panels/topic_config_panel.py:76-85, 337-362, 610-615, 684-699`
- 测试：`tests/test_panels.py`

- [ ] **步骤 1：编写目录规范化与代表机器人测试**

在 `tests/test_topic_catalog.py` 增加：

```python
def test_catalog_normalizes_discovers_and_returns_defensive_copy(qt_app):
    catalog = RobotTopicCatalog()
    catalog.update_from_discover("r1", {
        "topics": [
            {"topic": "/scan", "msg_type": "sensor_msgs/LaserScan"},
            {"topic": "/cmd", "type": "custom_msgs/Command"},
            {"topic": "", "msg_type": "ignored/Empty"},
        ]
    })

    assert catalog.topics_for("r1") == [
        {"topic": "/cmd", "msg_type": "custom_msgs/Command"},
        {"topic": "/scan", "msg_type": "sensor_msgs/LaserScan"},
    ]
    assert catalog.representative_robot(["r2", "r1"]) == "r1"
```

覆盖去重、更新发出 `topics_changed(robot_id)`、未知机器人返回空 list、调用方修改返回值不污染缓存；另传入 `topics=None`、非 list、非 dict 条目，以及 topic/type 为 `None` 或数字的条目，断言目录为空且不会生成字符串 `"None"` 或数字话题。

- [ ] **步骤 2：运行测试确认模块缺失**

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_topic_catalog.py -q
```

预期：因 `qt_frontend.topic_catalog` 不存在而失败。

- [ ] **步骤 3：实现 RobotTopicCatalog**

公开接口固定为：

```python
class RobotTopicCatalog(QObject):
    topics_changed = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._topics: Dict[str, List[Dict[str, str]]] = {}

    def update_from_discover(
        self, robot_id: str, data: Dict[str, Any]
    ) -> None:
        raw_topics = data.get("topics", [])
        if not isinstance(raw_topics, list):
            raw_topics = []
        normalized = {
            (
                item["topic"].strip(),
                (item.get("msg_type") or item.get("type")).strip(),
            )
            for item in raw_topics
            if isinstance(item, dict)
            and isinstance(item.get("topic"), str)
            and isinstance(item.get("msg_type") or item.get("type"), str)
        }
        self._topics[robot_id] = [
            {"topic": topic, "msg_type": msg_type}
            for topic, msg_type in sorted(normalized)
            if topic and msg_type
        ]
        self.topics_changed.emit(robot_id)

    def topics_for(self, robot_id: str) -> List[Dict[str, str]]:
        return [dict(item) for item in self._topics.get(robot_id, [])]

    def representative_robot(self, robot_ids: List[str]) -> str:
        return sorted(set(robot_ids))[0] if robot_ids else ""
```

目录按 `(topic, msg_type)` 去重并按 topic/type 排序；只接受去除首尾空白后仍非空的字符串。`data.topics` 不是 list、条目不是 dict、字段为 `None`/数字/其他非字符串时跳过，不把异常值强制转成文字。

- [ ] **步骤 4：让 TopicConfigPanel 使用可注入共享目录**

构造签名改为：

```python
def __init__(
    self,
    parent: Optional[QWidget] = None,
    topic_catalog: Optional[RobotTopicCatalog] = None,
) -> None:
```

无注入时创建私有目录，保证现有测试和备用入口可用。`on_discover_response()` 只调用目录更新；目录 signal 触发当前机器人下拉刷新。移除 `_available_topics_by_robot` 直接读取，`should_request_available_topics()` 改为接收 `topics_for(robot_id)` 的 list。

- [ ] **步骤 5：运行面板回归并提交**

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest \
  tests/test_topic_catalog.py tests/test_panels.py -q
ruff check qt_frontend/topic_catalog.py qt_frontend/panels/topic_config_panel.py \
  tests/test_topic_catalog.py tests/test_panels.py
```

预期：全部通过，原有“从机器人拉取话题”交互继续使用 discover 信号。

```bash
git add qt_frontend/topic_catalog.py qt_frontend/panels/topic_config_panel.py \
  tests/test_topic_catalog.py tests/test_panels.py
git commit -m "refactor: 共享机器人话题目录"
```

### 任务 6：实现四槽位配置模型和原子存储

**文件：**
- 创建：`qt_frontend/command_button_config.py`
- 创建：`qt_frontend/config/command_buttons.yaml`
- 创建：`tests/test_command_button_config.py`

- [ ] **步骤 1：编写缺失、有效、损坏和原子保存测试**

在 `tests/test_command_button_config.py` 覆盖：缺失文件返回 4 个 `None`；有效 YAML 往返；slot 键缺失自动补 `None`；版本不是 1、未知 slot、空 label、非法 topic/type、非 dict data、data 超 256 KiB、schema 非 dict、schema 超 256 KiB、非空 schema 根节点结构错误、schema type 与 msg_type 不同、`verified` 却没有有效 schema 均抛 `CommandButtonConfigError`；`unverified` 允许空 schema 或类型匹配的旧缓存；patch `os.replace` 失败时旧文件内容保持不变且临时文件被清理。

核心往返测试：

```python
def test_store_round_trip_preserves_four_slots(tmp_path):
    path = tmp_path / "command_buttons.yaml"
    store = CommandButtonConfigStore(path)
    slots = empty_command_slots()
    slots["slot_1"] = CommandButtonConfig(
        label="开始探索",
        topic="/exploration/control",
        msg_type="my_pkg/Control",
        data={"command": "start"},
        schema={"type": "my_pkg/Control", "kind": "message", "fields": []},
        schema_status="verified",
    )

    store.save(slots)

    assert store.load() == slots
    assert list(slots) == ["slot_1", "slot_2", "slot_3", "slot_4"]
```

- [ ] **步骤 2：运行测试确认模块缺失**

```bash
python3 -m pytest tests/test_command_button_config.py -q
```

预期：收集阶段因配置模块不存在而失败。

- [ ] **步骤 3：实现模型、校验与存储**

公开以下接口：

```python
CONFIG_VERSION = 1
SLOT_IDS = ("slot_1", "slot_2", "slot_3", "slot_4")
MAX_COMMAND_DATA_BYTES = 256 * 1024
MAX_COMMAND_SCHEMA_BYTES = 256 * 1024


class CommandButtonConfigError(ValueError):
    pass


@dataclass
class CommandButtonConfig:
    label: str
    topic: str
    msg_type: str
    data: Dict[str, Any]
    schema: Dict[str, Any] = field(default_factory=dict)
    schema_status: str = "unverified"


def empty_command_slots() -> Dict[str, Optional[CommandButtonConfig]]:
    return {slot_id: None for slot_id in SLOT_IDS}


class CommandButtonConfigStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
```

`CommandButtonConfigStore.load()` 返回 `Dict[str, Optional[CommandButtonConfig]]`：缺失文件直接返回 `empty_command_slots()`；存在文件必须校验 version、slots、每个非空 slot 并补齐缺失的合法 slot。`save(slots)` 返回 `None`：先校验完整 mapping，再用同目录 `tempfile.NamedTemporaryFile(delete=False)`、`yaml.safe_dump()` 写入，调用同一解析函数回读临时文件，最后 `os.replace(temp_path, self._path)`；`finally` 对仍存在的 temp path 调用 `unlink()`。

label 去除首尾空白后长度为 1 至 64；topic 必须以 `/` 开头且长度不超过 255；msg_type 必须恰好包含一个 `/` 且包名和类型名非空；schema_status 只允许 `verified/unverified`。schema 使用与 data 相同的 UTF-8 JSON 编码计数方式限制为 256 KiB；非空 schema 必须具有 `type/kind/fields`，其中 type 等于配置 msg_type、kind 等于 `message`、fields 是 list。`verified` 必须携带非空有效 schema；`unverified` 可以使用空 schema，也可以保留类型匹配的旧 schema 供离线表单使用。`CommandButtonConfig.to_dict()` 和 `from_dict()` 是 YAML 与 dataclass 的唯一转换入口，禁止 store 重复字段解析逻辑。

- [ ] **步骤 4：创建默认配置并运行测试**

`qt_frontend/config/command_buttons.yaml` 内容固定为：

```yaml
version: 1
slots:
  slot_1: null
  slot_2: null
  slot_3: null
  slot_4: null
```

运行：

```bash
python3 -m pytest tests/test_command_button_config.py -q
ruff check qt_frontend/command_button_config.py tests/test_command_button_config.py
```

预期：全部通过。

- [ ] **步骤 5：提交配置基础**

```bash
git add qt_frontend/command_button_config.py \
  qt_frontend/config/command_buttons.yaml tests/test_command_button_config.py
git commit -m "feat: 持久化命令按钮配置"
```

### 任务 7：实现 Schema 数据校验和递归 Qt 表单

**文件：**
- 创建：`qt_frontend/message_schema.py`
- 创建：`qt_frontend/panels/message_form.py`
- 创建：`tests/test_message_schema_form.py`

- [ ] **步骤 1：编写纯数据默认值与校验失败测试**

在 `tests/test_message_schema_form.py` 先测试零 Qt 函数：

```python
@pytest.fixture
def sample_schema():
    return {
        "type": "test_msgs/Command",
        "kind": "message",
        "fields": [
            {
                "name": "enabled", "type": "bool", "base_type": "bool",
                "kind": "primitive", "is_array": False,
                "array_len": None, "fields": [],
            },
            {
                "name": "name", "type": "string", "base_type": "string",
                "kind": "primitive", "is_array": False,
                "array_len": None, "fields": [],
            },
            {
                "name": "pose", "type": "test_msgs/Pose",
                "base_type": "test_msgs/Pose", "kind": "message",
                "is_array": False, "array_len": None,
                "fields": [
                    {
                        "name": "x", "type": "float64",
                        "base_type": "float64", "kind": "primitive",
                        "is_array": False, "array_len": None, "fields": [],
                    },
                    {
                        "name": "count", "type": "int32",
                        "base_type": "int32", "kind": "primitive",
                        "is_array": False, "array_len": None, "fields": [],
                    },
                ],
            },
            {
                "name": "tags", "type": "string[]", "base_type": "string",
                "kind": "primitive", "is_array": True,
                "array_len": None, "fields": [],
            },
        ],
    }


def test_default_data_and_validation_follow_nested_schema(sample_schema):
    data = default_data_for_schema(sample_schema)
    assert data == {
        "enabled": False,
        "name": "",
        "pose": {"x": 0.0, "count": 0},
        "tags": [],
    }
    assert validate_message_data(sample_schema, data) == []
    assert validate_message_data(sample_schema, {"pose": {"x": "bad"}}) == [
        "pose.x: 需要浮点数"
    ]
```

覆盖未知字段、bool/整数区分、固定数组长度、嵌套 object、time/duration `{secs,nsecs}`、根节点非 object。允许缺失字段，因为 ROS 消息对象会保留默认值。

- [ ] **步骤 2：编写 Qt 表单往返失败测试**

使用 `qt_app` fixture 创建 `MessageFormWidget`，`set_schema(schema, initial_data)` 后按字段路径取得控件并修改；断言 `data()` 返回 bool、int、float、string、嵌套 object 和数组的正确 Python 类型。数组 JSON 无效时 `validation_errors()` 必须包含字段路径。

- [ ] **步骤 3：运行测试确认两个模块缺失**

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_message_schema_form.py -q
```

预期：因 `qt_frontend.message_schema` 或 `message_form` 不存在而失败。

- [ ] **步骤 4：实现零 Qt schema 数据函数**

`qt_frontend/message_schema.py` 公开 `default_data_for_schema(schema: Dict[str, Any]) -> Dict[str, Any]` 和 `validate_message_data(schema: Dict[str, Any], data: object) -> List[str]`。前者按 field 的 `kind/base_type/is_array` 递归生成默认值，后者递归返回稳定排序的中文字段路径错误。

错误按字段遍历顺序稳定输出中文路径；未知字段必须报错。数组元素递归校验 `base_type/kind/fields`，固定数组校验长度。

- [ ] **步骤 5：实现 MessageFormWidget**

公开 `MessageFormWidget.data_changed` signal，以及 `set_schema(schema, data)`、`data()`、`validation_errors()`、`field_widget(path)` 四个测试接口。`field_widget()` 从内部 `Dict[str, QWidget]` 路径映射取值，未知路径返回 `None`。

字符串用 `QLineEdit`，bool 用 `QCheckBox`，数字用带 validator 的 `QLineEdit` 以避免 `QSpinBox` 的 32 位范围限制，time/duration 用 `secs/nsecs` 子字段，嵌套消息用默认展开的可折叠 `QGroupBox`，数组用 `QPlainTextEdit` 编辑 JSON array。所有控件使用稳定最小高度，长字段名换行或提供 tooltip，不根据 viewport 缩放字体。

- [ ] **步骤 6：运行测试并提交**

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_message_schema_form.py -q
ruff check qt_frontend/message_schema.py qt_frontend/panels/message_form.py \
  tests/test_message_schema_form.py
```

预期：全部通过，offscreen 环境无显示服务器依赖。

```bash
git add qt_frontend/message_schema.py qt_frontend/panels/message_form.py \
  tests/test_message_schema_form.py
git commit -m "feat: 生成递归消息参数表单"
```

### 任务 8：实现四槽位设置对话框

**文件：**
- 创建：`qt_frontend/panels/command_button_dialog.py`
- 修改：`qt_frontend/panels/__init__.py`
- 创建：`tests/test_command_button_dialog.py`

- [ ] **步骤 1：编写话题复用、schema 防乱序和双模式同步测试**

测试构造共享 `RobotTopicCatalog`、临时 `CommandButtonConfigStore` 和在线机器人 `['r2', 'r1']`。覆盖：

1. 左侧恰好 4 个 slot；在 slot 之间来回切换时分别保留显示文字、topic、msg_type、当前标签页以及尚未通过语法校验的原始 JSON 文本。
2. 话题下拉来自 `catalog.topics_for('r1')`，选 topic 自动填 msg_type。
3. 修改 msg_type 发出 `schema_query_requested('r1', request_id, msg_type)`。
4. 同时为两个 slot 发起请求时，响应只更新请求所属 slot；robot ID、request ID、msg_type 或该 slot 当前类型不匹配时不覆盖任何 schema。
5. 合法响应设置目标 slot 的 `schema_status='verified'` 并生成表单；打开已有缓存的 slot 时仍向在线代表机器人刷新一次 schema。
6. form → JSON 与 JSON → form 保持相同 data。
7. 非 object JSON、字段错误或任一 slot 无效时不调用 store.save。
8. 无在线机器人时允许手工 JSON 保存为 `unverified`。
9. 有代表机器人但共享目录为空时发出一次 `discover_requested`，discover 响应更新目录后刷新话题下拉。
10. schema 请求 5 秒没有响应，或匹配响应返回 `result='error'` 时，清理 pending、标记目标 slot 为 `unverified`、显示具体错误；存在旧 schema 时保留旧表单和缓存，不存在时切到 JSON。超时后到达的响应，以及同一 slot 新请求之前的旧响应，都不得覆盖当前状态。
11. 点击“清除此位置”只重置当前 draft 为未配置；保存全部设置后该 slot 持久化为 `None`，取消对话框则不修改磁盘配置。

代表测试：

```python
def build_dialog(qt_app, tmp_path, online_robot_ids):
    catalog = RobotTopicCatalog()
    catalog.update_from_discover("r1", {
        "topics": [{"topic": "/cmd", "msg_type": "my_pkg/First"}],
    })
    store = CommandButtonConfigStore(tmp_path / "command_buttons.yaml")
    requests = []
    dialog = CommandButtonSettingsDialog(
        store=store,
        topic_catalog=catalog,
        online_robot_ids=online_robot_ids,
    )
    dialog.schema_query_requested.connect(
        lambda robot_id, request_id, msg_type: requests.append(
            (robot_id, request_id, msg_type)
        )
    )
    return dialog, requests


def test_dialog_ignores_stale_schema_response(qt_app, tmp_path):
    dialog, requests = build_dialog(qt_app, tmp_path, ["r1"])
    dialog.set_message_type("my_pkg/First")
    old_request = requests[-1][1]
    dialog.set_message_type("my_pkg/Second")

    dialog.on_schema_response("r1", {
        "request_id": old_request,
        "msg_type": "my_pkg/First",
        "result": "ok",
        "schema": {"type": "my_pkg/First", "kind": "message", "fields": []},
    })

    assert dialog.current_message_type() == "my_pkg/Second"
    assert dialog.current_schema() == {}
```

另增加 `test_switching_slots_preserves_independent_raw_drafts`、`test_concurrent_schema_responses_update_their_own_slots`、`test_schema_timeout_keeps_cached_schema_unverified`、`test_late_response_after_timeout_is_ignored`、`test_opening_cached_slot_refreshes_schema_once`、`test_robot_coming_online_refreshes_selected_slot` 和 `test_clear_current_slot_persists_none`。测试使用可调用的 `dialog.expire_schema_request(request_id)` 测试接口触发超时，不等待真实 5 秒。

- [ ] **步骤 2：运行测试确认对话框缺失**

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_command_button_dialog.py -q
```

预期：收集阶段因 `CommandButtonSettingsDialog` 不存在而失败。

- [ ] **步骤 3：实现对话框固定接口和布局**

公开 `discover_requested = pyqtSignal()` 与 `schema_query_requested = pyqtSignal(str, str, str)`。构造参数固定为 `store: CommandButtonConfigStore`、`topic_catalog: RobotTopicCatalog`、`online_robot_ids: List[str]` 和可选 `parent`。测试接口固定为 `select_slot(slot_id)`、`set_message_type(msg_type)`、`current_message_type()`、`set_online_robot_ids(robot_ids)`、`on_schema_response(robot_id, data)`、`expire_schema_request(request_id)`、`current_schema()` 与 `saved_slots()`；最后两者返回防御性深拷贝。

在模块内定义以下私有状态类型：

```python
@dataclass
class _SlotDraft:
    label: str = ""
    topic: str = ""
    msg_type: str = ""
    json_text: str = "{}"
    schema: Dict[str, Any] = field(default_factory=dict)
    schema_status: str = "unverified"
    schema_error: str = ""
    active_tab: int = 1


@dataclass(frozen=True)
class _SchemaRequestContext:
    robot_id: str
    slot_id: str
    msg_type: str
```

对话框启动时将 store 的 4 个值深拷贝成 `Dict[str, Optional[_SlotDraft]]`，再把选中的 slot 加载进编辑器。切换前 `_capture_current_draft()` 必须保存所有文本和当前标签页：表单模式先把 `MessageFormWidget.data()` 序列化到 `json_text`，JSON 模式直接保存原始编辑器文本，即使它当前语法无效也不能丢失。加载目标 draft 时恢复原始文本；只有 JSON 可解析且与 schema 相容时才同步表单。不得用一个全局 `data/schema/json_text` 代表全部 slot。

左侧用固定宽度 `QListWidget` 显示 4 个位置；右侧包含显示字样、可编辑话题 combo、可编辑 msg_type combo、校验状态、`QTabWidget` 中的 `MessageFormWidget` 与 `QPlainTextEdit`。右侧提供“清除此位置”命令按钮，底部保留取消和保存全部设置；清空只重置当前内存 draft 和编辑器，只有“保存全部设置”成功后才写磁盘。不要把对话框放进卡片式嵌套容器。

构造完成后若存在代表机器人但 `topic_catalog.topics_for(robot_id)` 为空，使用 `QTimer.singleShot(0, self.discover_requested.emit)` 请求现有 discover；目录的 `topics_changed` signal 到达后只刷新相同代表机器人的下拉选项，不清除用户已经手工输入的 topic/type。

- [ ] **步骤 4：实现 schema 请求与 JSON 同步**

使用 `_pending_schema_requests: Dict[str, _SchemaRequestContext]` 和 `_latest_schema_request_by_slot: Dict[str, str]` 跟踪请求；`_SchemaRequestContext` 固定保存 `robot_id/slot_id/msg_type`。每次 msg_type 编辑完成后先捕获当前 draft；若原 schema 的 type 与新 msg_type 不同，立即清空 schema、标记 `unverified` 并保留原始 JSON。然后令 `request_id = uuid.uuid4().hex[:12]`，把同一 slot 的旧 request 从 pending 移除，再记录新 request 并发出 query；使用 `QTimer.singleShot(5000, lambda rid=request_id: self.expire_schema_request(rid))` 设置超时。每个非空缓存 slot 在本次对话框第一次被选中时，即使 `schema_status='verified'`，也按同一流程向在线代表机器人刷新一次；使用 `_refreshed_slots: Set[str]` 防止来回切换重复查询。`set_online_robot_ids()` 保存排序去重后的新集合；代表机器人由无变有时，清除当前 slot 的 refreshed 标记并立即触发一次刷新，使对话框打开期间上线的机器人也可提供 schema。

`on_schema_response()` 先以 request ID 查 pending，再同时核对 robot ID、响应 msg_type、上下文 msg_type、目标 draft 当前 msg_type 和 `_latest_schema_request_by_slot`；全部匹配才消费响应。成功响应还要验证 schema 根结构、大小和 type，更新请求所属 draft、清空 `schema_error`；仅当它是当前 slot 时刷新可见表单。匹配的 error 响应与 `expire_schema_request()` 都消费 pending，把该 draft 标为 `unverified` 并把 Agent error 或“消息结构查询超时”写入 `schema_error`：存在类型匹配的旧 schema 时保留它并继续允许结构化表单，不存在时清空 schema 并切到 JSON。加载该 slot 时状态 label 显示保存于 draft 的错误；迟到响应因 pending 已删除而忽略。`schema_error` 仅是本次对话框的瞬时状态，不写入 YAML。

切换到 JSON 前序列化 form data；切回 form 前解析 JSON、要求 object、调用 `validate_message_data()`，失败则恢复 JSON tab 并在状态 label 展示第一条字段路径错误。没有代表机器人时不创建 pending，保留类型匹配的缓存 schema 但标记 unverified；没有缓存才清空 schema 并切到 JSON。

- [ ] **步骤 5：实现整批校验和保存**

保存前先捕获当前 draft。明确执行过“清除此位置”或所有字段均为空的 draft 转为 `None`；其他有任意输入的 draft 必须先解析其原始 JSON、要求顶层 object，再形成完整 `CommandButtonConfig`。逐槽位构造并验证全部配置后才调用一次 `store.save(slots)`；失败时自动选中对应 slot、保持原始文本和对话框打开。保存成功才 `accept()`；取消不调用 store。

- [ ] **步骤 6：运行测试并提交**

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest \
  tests/test_command_button_dialog.py tests/test_message_schema_form.py -q
ruff check qt_frontend/panels/command_button_dialog.py \
  qt_frontend/panels/__init__.py tests/test_command_button_dialog.py
```

预期：全部通过。

```bash
git add qt_frontend/panels/command_button_dialog.py \
  qt_frontend/panels/__init__.py tests/test_command_button_dialog.py
git commit -m "feat: 添加命令按钮设置窗口"
```

### 任务 9：替换模式区并汇总批量确认

**文件：**
- 创建：`qt_frontend/command_batch.py`
- 创建：`tests/test_command_batch.py`
- 修改：`qt_frontend/panels/command_panel.py:17-148, 174-290`
- 测试：`tests/test_panels.py`

- [ ] **步骤 1：编写纯批次状态机失败测试**

在 `tests/test_command_batch.py` 覆盖 start、成功、失败、重复 ack、未知机器人、未知 exec ID、部分完成、超时和历史淘汰：完成 21 个批次后只保留最近 20 个结果，仍在等待确认的活动批次不得因上限被淘汰。

```python
def test_batch_tracker_summarizes_partial_failure_and_timeout():
    tracker = CommandBatchTracker(timeout_seconds=5.0)
    tracker.start("exec-1", ["r1", "r2", "r3"], now=10.0)
    tracker.ack("exec-1", "r1", "ok", "done")
    tracker.ack("exec-1", "r2", "error", "missing message package")
    tracker.expire(now=15.1)

    result = tracker.result("exec-1")
    assert result.counts() == {"success": 1, "failed": 1, "timeout": 1}
    assert result.details["r2"].message == "missing message package"
```

- [ ] **步骤 2：编写 CommandPanel 新模式区失败测试**

在 `tests/test_panels.py::TestCommandPanel` 增加：模式区恰好 4 个配置按钮；默认全为“未配置”且禁用；不再存在面板急停按钮；在线数 label 更新；有效 slot 显示 label 并启用；点击生成 exec ID 并发出 `batch_command_requested(exec_id, params)`，params 精确包含 `topic/msg_type/data`；配置对象点击后深拷贝；速度方向按钮仍只发给选中机器人。再连续启动 `exec-old` 与 `exec-new`，让旧批次后完成，断言结果 label 和详情仍展示新批次，两个 tracker 结果各自保持正确；设置窗口存活时调用 `on_robot_list_changed()`，断言新在线列表转发到对话框，关闭后引用清空。

- [ ] **步骤 3：运行测试确认批次模块和新 UI 缺失**

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest \
  tests/test_command_batch.py tests/test_panels.py::TestCommandPanel -q
```

预期：批次模块收集失败，面板测试因仍显示固定模式/急停按钮而失败。

- [ ] **步骤 4：实现 CommandBatchTracker**

使用 dataclass `RobotCommandResult`、`CommandBatchResult`；`CommandBatchTracker(timeout_seconds: float = 5.0, max_completed: int = 20)` 公开 `start(exec_id: str, robot_ids: List[str], now: float) -> None`、`ack(exec_id: str, robot_id: str, result: str, message: str) -> bool`、`expire(now: float) -> List[str]`、`result(exec_id: str) -> Optional[CommandBatchResult]`。`CommandBatchResult.counts()` 固定返回 `{"success": int, "failed": int, "timeout": int}`。模块不依赖 Qt。重复 ack 只接受第一条终态；`expire()` 仅把尚未完成且已到 deadline 的机器人标为 timeout，并返回刚完成的 exec ID 列表。内部用完成顺序 deque 记录终态批次，每当批次完成时淘汰超过 `max_completed` 的最旧完成批次；活动批次不计入该上限，重复完成通知不重复入队。

- [ ] **步骤 5：重建模式控制组**

`CommandPanel` 构造增加可选 `config_store/topic_catalog`，无参时使用默认配置路径和私有目录。保留目标机器人 combo、速度档位和方向控制。模式组标题行显示“模式控制”、齿轮图标按钮与“发送目标：全部在线机器人（当前 N 台）”；下方固定 2×2 按钮网格和结果 label。

新增 signals 与 slots：

```python
batch_command_requested = pyqtSignal(str, dict)
discover_requested = pyqtSignal()
schema_query_requested = pyqtSignal(str, str, str)
```

实现 `begin_command_batch(exec_id, robot_ids)`、`reject_command_batch(exec_id, message)` 和 `on_schema_response(robot_id, data)`。点击配置按钮生成 exec ID 并对 `topic/msg_type/data` 做 `copy.deepcopy()` 后 emit。`begin_command_batch()` 启动 tracker、把 `_visible_exec_id` 设置为该 exec ID，并使用 `QTimer.singleShot(5000, lambda batch_id=exec_id: self._expire_batch(batch_id))` 到期；`reject_command_batch()` 也只更新它收到的最新点击 ID。`on_cmd_ack()` 与 `_expire_batch()` 始终更新 tracker，但只有目标 ID 等于 `_visible_exec_id` 时才刷新可见结果。结果 label 显示计数并包含 `<a href="details">查看详情</a>`，`linkActivated` 只根据 `_visible_exec_id` 打开 `QMessageBox`，列出该批次每台失败/超时机器人；同一详情文本也设置为 label tooltip。旧批次迟到 ack 只更新旧批次内部结果，不得覆盖新批次 label、tooltip 或详情。

读取配置失败时 4 个按钮回退未配置并显示警告；不能加载半有效 slot。齿轮打开任务 8 的对话框，转发 discover/schema signals，并在对话框存活期间保存 `_settings_dialog` 引用；现有 `on_robot_list_changed(robot_ids)` 除更新目标 combo 和在线数外，还调用 `_settings_dialog.set_online_robot_ids(robot_ids)`。对话框关闭后在 `finally` 清空引用，成功保存后重新加载配置。

- [ ] **步骤 6：运行面板与批次测试并提交**

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest \
  tests/test_command_batch.py tests/test_panels.py -q
ruff check qt_frontend/command_batch.py qt_frontend/panels/command_panel.py \
  tests/test_command_batch.py tests/test_panels.py
```

预期：全部通过，原速度控制测试不回归。

```bash
git add qt_frontend/command_batch.py qt_frontend/panels/command_panel.py \
  tests/test_command_batch.py tests/test_panels.py
git commit -m "feat: 替换可配置模式命令区"
```

### 任务 10：接入正式主窗口并批量下发全部在线机器人

**文件：**
- 修改：`qt_frontend/panels/robot_list_panel.py:31-39, 106-125, 230-292`
- 修改：`qt_frontend/main_window.py:42-115, 296-328, 598-623, 721-746`
- 修改：`qt_frontend/mqtt_client.py:116-124`
- 测试：`tests/test_panels.py`
- 测试：`tests/test_main_window.py`
- 测试：`tests/test_mqtt_client.py`

- [ ] **步骤 1：编写共享目录接线与批量发送失败测试**

先在 `tests/test_panels.py` 覆盖 `RobotListPanel.online_robots_changed`：首个状态发出 `['r1']`，同一在线集合的后续状态不重复 emit，心跳超时后发出 `[]`。

在 `tests/test_main_window.py` 构造禁用定时初始化的 MainWindow，断言 `_topic_config` 与 `_command` 引用同一 `RobotTopicCatalog`。调用 `_on_discover('r1', topics)` 后两者都能读取相同目录。

批量发送测试用 fake MQTT client：

```python
@pytest.fixture
def command_window(qt_app, monkeypatch):
    monkeypatch.setattr(QTimer, "singleShot", lambda *args, **kwargs: None)
    monkeypatch.setattr(MainWindow, "_check_ros", lambda self: None)
    return MainWindow({})


def test_custom_batch_sends_same_exec_id_to_all_online_robots(command_window):
    window = command_window
    window._robot_list.on_status_received("r2", {"battery": 90})
    window._robot_list.on_status_received("r1", {"battery": 80})
    sent = []
    window._mqtt_client = SimpleNamespace(
        is_connected=True,
        send_cmd=lambda robot_id, data: sent.append((robot_id, data)),
    )

    window._on_batch_command("exec-1", {
        "topic": "/exploration/control",
        "msg_type": "my_pkg/Control",
        "data": {"command": "start"},
    })

    assert [robot_id for robot_id, _ in sent] == ["r1", "r2"]
    assert {item["exec_id"] for _, item in sent} == {"exec-1"}
    assert all(item["action"] == "custom" for _, item in sent)
```

再覆盖无在线机器人、MQTT 未连接时不调用 send_cmd 且 panel 收到 reject；`begin_command_batch()` 必须在第一条 send 前调用。

- [ ] **步骤 2：运行测试确认主窗口尚未接线**

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest \
  tests/test_main_window.py -k "command or catalog or schema" -q
```

预期：因共享目录属性、schema 信号或 `_on_batch_command` 不存在而失败。

- [ ] **步骤 3：创建共享实例并连接发现结果**

`RobotListPanel` 增加 `online_robots_changed = pyqtSignal(list)`、`self._last_online_robot_ids: List[str]` 和 `_emit_online_robots_changed_if_needed()`。`on_status_received()`、`on_discover_response()` 与 `_check_heartbeats()` 完成状态更新后调用该 helper；helper 对排序后的在线 ID 与上次值比较，仅在集合变化时 emit 新 list。

`MainWindow.__init__()` 在 `_init_panels()` 前创建 `self._topic_catalog`。构造 `TopicConfigPanel(topic_catalog=self._topic_catalog)` 和 `CommandPanel(topic_catalog=self._topic_catalog)`。连接 `online_robots_changed` 到新的 `_on_online_robots_changed(robot_ids)`，由该方法统一调用 CommandPanel、TopicConfigPanel、FleetCommPanel、DataSenderPanel、SensorSummaryPanel 并更新顶部在线数。`_on_robot_status()` 和 `_on_discover()` 删除重复的面板列表刷新，只保留单机器人数据处理；`_on_discover()` 在更新 RobotListPanel 前调用目录更新。删除 MQTT discover signal 到 `TopicConfigPanel.on_discover_response` 的重复连接，保留 FleetCommPanel 现有连接。

- [ ] **步骤 4：连接 schema 与批量命令**

在 `_init_mqtt()` 连接：

```python
sig.schema_response_received.connect(self._command.on_schema_response)
self._command.discover_requested.connect(self._mqtt_client.send_discover)
self._command.schema_query_requested.connect(
    self._mqtt_client.send_message_schema_query
)
self._command.batch_command_requested.connect(self._on_batch_command)
```

`_on_batch_command(exec_id, params)` 先检查 MQTT 连接和在线列表，按 robot ID 排序，调用 `self._command.begin_command_batch(exec_id, robots)`，再逐台发送：

```python
{
    "action": "custom",
    "params": copy.deepcopy(params),
    "exec_id": exec_id,
}
```

现有 `_on_command(robot_id, action, params)` 保留给速度控制；顶部 `_on_emergency()` 不改为新批次，继续发送零速度和 stop 双指令。

- [ ] **步骤 5：确认 MqttClient 保留 exec_id 原样**

在 `tests/test_mqtt_client.py` 增加 send_cmd payload 往返断言，确保调用方给出的 `exec_id` 不被覆盖或丢失。`send_cmd()` 无需自行生成 ID。

- [ ] **步骤 6：运行正式入口回归并提交**

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest \
  tests/test_panels.py tests/test_main_window.py tests/test_mqtt_client.py -q
python3 -m py_compile \
  qt_frontend/main_window.py qt_frontend/mqtt_client.py \
  qt_frontend/panels/command_panel.py
ruff check qt_frontend/panels/robot_list_panel.py qt_frontend/main_window.py \
  qt_frontend/mqtt_client.py tests/test_panels.py tests/test_main_window.py \
  tests/test_mqtt_client.py
```

预期：全部通过。`qt_frontend/panels_setup.py` 未修改；无参 `CommandPanel()` 测试证明备用入口仍可构造，但其既有无 MQTT 限制保持不变。

```bash
git add qt_frontend/panels/robot_list_panel.py qt_frontend/main_window.py \
  qt_frontend/mqtt_client.py tests/test_panels.py tests/test_main_window.py \
  tests/test_mqtt_client.py
git commit -m "feat: 向全部在线机器人发送命令"
```

### 任务 11：复核协议文档、编写工作日志并完成分层验证

**文件：**
- 核对：`docs/protocol.md`
- 创建：`docs/work-log-2026-07-24.md`
- 核对：本计划列出的全部 Python、YAML 和测试文件

- [ ] **步骤 1：复核协议权威文档**

对照任务 1 和任务 3 的最终代码与测试，确认 `docs/protocol.md` 已包含：

```text
station/{robot_id}/message_schema/query
station/{robot_id}/message_schema/response
```

逐项核对 query/response JSON 示例、字段表、QoS、256 KiB schema 边界、request ID 防乱序规则，以及 `custom` 的 `{topic, msg_type, data}` 格式和真实 ROS 消息语义。使用 `rg -n "message_schema|action.*custom|msg_type|std_msgs/String" docs/protocol.md` 检查新旧描述；如果实现期间字段名发生变化，必须在提交实现任务时同步修正文档并重跑协议测试，不能把权威文档差异留到工作日志提交。

- [ ] **步骤 2：运行聚焦测试**

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest \
  tests/test_protocol_messages.py \
  tests/test_protocol_topics.py \
  tests/test_message_schema.py \
  tests/test_dict_to_ros_msg.py \
  tests/test_agent_topic_config.py \
  tests/test_ros1_agent.py \
  tests/test_mqtt_client.py \
  tests/test_topic_catalog.py \
  tests/test_command_button_config.py \
  tests/test_message_schema_form.py \
  tests/test_command_button_dialog.py \
  tests/test_command_batch.py \
  tests/test_panels.py \
  tests/test_main_window.py -q
```

预期：全部通过，输出中 0 failed、0 errors。

- [ ] **步骤 3：运行完整 pytest**

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/ -v
```

预期：全部通过。若存在与本任务无关的历史失败，记录完整测试名和失败证据，不得把聚焦测试通过描述为全量通过。

- [ ] **步骤 4：运行 lint、编译与 diff 校验**

仅对本计划新增或实质修改的手写 Python 文件运行：

```bash
ruff check \
  protocol/messages.py protocol/topics.py \
  agent/message_schema.py agent/dict_to_ros_msg.py agent/base_agent.py \
  agent/ros1_agent.py agent/mock_agent.py \
  qt_frontend/topic_catalog.py qt_frontend/command_button_config.py \
  qt_frontend/message_schema.py qt_frontend/command_batch.py \
  qt_frontend/mqtt_client.py qt_frontend/main_window.py \
  qt_frontend/panels/robot_list_panel.py qt_frontend/panels/topic_config_panel.py \
  qt_frontend/panels/message_form.py \
  qt_frontend/panels/command_button_dialog.py \
  qt_frontend/panels/command_panel.py qt_frontend/panels/__init__.py \
  tests/test_protocol_messages.py tests/test_protocol_topics.py \
  tests/test_message_schema.py tests/test_dict_to_ros_msg.py \
  tests/test_agent_topic_config.py tests/test_ros1_agent.py \
  tests/test_mqtt_client.py tests/test_topic_catalog.py \
  tests/test_command_button_config.py tests/test_message_schema_form.py \
  tests/test_command_button_dialog.py tests/test_command_batch.py \
  tests/test_panels.py tests/test_main_window.py

python3 -m py_compile \
  protocol/messages.py protocol/topics.py \
  agent/message_schema.py agent/dict_to_ros_msg.py agent/base_agent.py \
  agent/ros1_agent.py agent/mock_agent.py \
  qt_frontend/topic_catalog.py qt_frontend/command_button_config.py \
  qt_frontend/message_schema.py qt_frontend/command_batch.py \
  qt_frontend/mqtt_client.py qt_frontend/main_window.py \
  qt_frontend/panels/robot_list_panel.py qt_frontend/panels/topic_config_panel.py \
  qt_frontend/panels/message_form.py \
  qt_frontend/panels/command_button_dialog.py \
  qt_frontend/panels/command_panel.py

git diff --check
```

预期：三条命令退出码均为 0。

- [ ] **步骤 5：执行真实 ROS Noetic 自定义消息验证**

在至少一台已 source 自定义消息工作空间的机器人环境启动 ROS1 Agent 与 MQTT；使用一个包含嵌套字段和数组的实际自定义类型：

```bash
rostopic type /实际命令话题
rostopic echo -n 1 /实际命令话题
```

从地面站完成 schema 加载、结构化表单发送和 JSON 高级模式发送，观察 `rostopic echo` 字段与输入一致。随后让一台目标机器人不 source 该消息包，确认该机器人返回失败、其他机器人成功、前端汇总不回滚。实际话题和消息类型必须取运行环境已有定义，不把设计文档示例当作固定名称。

- [ ] **步骤 6：进行 Qt 视觉与交互检查**

使用 `./qt_frontend/scripts/start.sh` 启动正式入口，检查 1280×720 和 1600×900：4 个按钮稳定为 2×2、不与在线数或齿轮重叠、长 label 使用省略号并有 tooltip、设置对话框在窄屏可滚动、4 个 slot 来回切换和表单/JSON 切换都不丢值、“清除此位置”不会误清其他 slot、schema 加载/错误/超时状态可见、顶部全部急停始终可见。保存一张截图并在工作日志记录路径；若环境无法启动 RViz，使用 `QT_QPA_PLATFORM=offscreen` 截取设置对话框并明确 RViz 未验证。

- [ ] **步骤 7：编写当日工作日志**

创建 `docs/work-log-2026-07-24.md`，按“今日概览、问题背景、协议与 Agent、前端配置体验、批量发送与确认、测试与验证、当前状态”组织。首次出现 schema、Agent、payload、cmd_ack 时用自然语言解释。只记录实际执行的命令、通过数量、ROS/MQTT/Qt 现象和未覆盖风险，不把本计划中的预期结果写成已完成事实。

- [ ] **步骤 8：提交文档与最终验证记录**

```bash
git add docs/work-log-2026-07-24.md
git commit -m "docs: 记录可配置命令按钮实现"
```

提交后重新运行：

```bash
git status --short
git log --oneline -12
```

预期：只剩任务开始前已有的用户文件或本地工具目录；本计划文件、实现文件、测试和文档均已提交。

## 新对话干跑审查

### 任务独立性

- 任务 1 只增加零 ROS/Qt 依赖协议并同步更新对应权威文档，完成后协议测试可独立通过且文档与代码一致。
- 任务 2 只依赖任务 1 之外的现有 `dict_to_ros_msg` 类型加载 helper；fake class 测试不要求 ROS。
- 任务 3 在已有转换器上增加默认关闭参数，先保证所有旧调用行为不变，再切换 custom 命令、增加有界 Publisher LRU 并同步更新对应权威文档。
- 任务 4 依赖任务 1 的协议和任务 2 的 Agent hook；MQTT 两端可用 RecordingAgent 与 fake paho 独立验证。
- 任务 5 只重构 discover 数据所有权，不依赖 schema 协议，完成后现有话题配置仍可运行。
- 任务 6 是独立纯 Python/YAML 模块，不依赖 Qt、MQTT 或 ROS，并在任何 Qt 控件读取缓存前验证 data/schema 大小和 schema 根结构。
- 任务 7 依赖任务 2 定义的 schema 形状，但测试使用固定 dict，不依赖真实 Agent。
- 任务 8 依赖任务 5、6、7，所有信号目标在前序任务已定义；每个 slot 的 `_SlotDraft` 与按 request ID 跟踪的 schema 状态都在该任务内部定义，不依赖主窗口时序。
- 任务 9 依赖任务 6、8，新批次状态机不依赖 MQTT；`_visible_exec_id` 只控制渲染，旧批次仍可独立完成，面板 emit 后即使尚未接主窗口也不会破坏构造。
- 任务 10 最后接入正式入口，所有 signal、store、catalog 和 tracker 均已存在。
- 任务 11 只在实现和聚焦测试完成后复核任务 1、3 已同步更新的权威文档，并编写事实性工作日志。

### 预期失败来源

- 每个首次失败测试均指向计划中尚未创建的模块、符号、signal 或明确的旧行为差异。
- ROS schema 和发布测试 patch 动态消息类与 `rospy.Publisher`，不会因开发机缺 roscore 提前失败。
- Qt 测试显式设置 `QT_QPA_PLATFORM=offscreen` 并复用现有 `qt_app` fixture，不依赖桌面会话。
- 原子保存测试使用 `tmp_path`，不会写入真实 `qt_frontend/config/command_buttons.yaml`。
- schema 超时测试直接调用 `expire_schema_request()`，不会因真实定时器、事件循环等待或执行顺序而提前失败。
- 主窗口测试禁用 RViz 延迟初始化和 ROS monitor，目标失败不会被 native 库缺失掩盖。

### 符号与数据一致性

- 协议统一使用 `MessageSchemaQueryData`、`MessageSchemaResponseData`、`message_schema_query`、`message_schema_response`。
- MQTT topic 统一使用 `station/{robot_id}/message_schema/query|response`，parser 类型与 MessageType 值一致。
- custom 参数全链路统一为 `params.topic`、`params.msg_type`、`params.data`，不再混用旧 `params.msg`。
- schema field 固定使用 `name/type/base_type/kind/is_array/array_len/fields`，Agent、纯校验、Qt 表单和缓存采用同一结构。
- slot 固定使用 `slot_1` 至 `slot_4`；未配置值为 YAML `null` 和 Python `None`。
- 设置窗口草稿固定使用 `_SlotDraft`，schema pending 固定使用 `_SchemaRequestContext`、`_pending_schema_requests` 与 `_latest_schema_request_by_slot`；错误和超时不会复用另一个 slot 的状态。
- 同批命令全体共享 `exec_id`，前端内部以 robot ID 区分 ack；MqttClient 不重写 ID。
- CommandPanel 仅渲染 `_visible_exec_id`，Tracker 最多保留最近 20 个已完成批次；ROS1 Agent 的 `_command_publishers` 使用最多 32 项的 LRU。

### 入口与环境覆盖

- 正式入口 `qt_frontend/main.py`、MainWindow、MqttClient、RobotListPanel、TopicConfigPanel 和 CommandPanel 均在任务 10 覆盖；心跳超时会同步刷新“全部在线机器人”数量和发送目标。
- 备用 `panels_setup.py` 仅依赖无参 `CommandPanel()` 兼容性；它已有的无 MQTT 限制被明确保留，没有伪装成完整功能。
- Mock Agent 通过仅证明协议和 UI 流程；真实 ROS 自定义消息、Publisher 类型和多机器人部分失败必须执行任务 11 的 ROS Noetic 验证或列为未验证风险。
- Docker、运行态配置和 RViz native 库不是纯单元测试前置条件，不得为通过测试而覆盖用户容器或配置。

## 规格覆盖自检

- 固定 4 个位置、默认未配置、可清空但无新增删除排序：任务 6、8、9。
- 话题发现复用与类型自动填充：任务 5、8、10。
- 自定义消息递归 schema：任务 1、2、4。
- 递归表单、JSON 高级模式、分槽位草稿、schema 超时与在线刷新：任务 7、8。
- 全部在线机器人逐台发送：任务 9、10。
- 成功、失败、超时、批次隔离、有限历史与详情：任务 9、10。
- 本地原子持久化和损坏回退：任务 6、9。
- 真实 ROS 自定义类型发布：任务 3。
- 顶部急停保留、模式区删除重复急停：任务 9、10。
- 协议文档：任务 1、3，最终一致性复核在任务 11；工作日志和环境风险：任务 11。
