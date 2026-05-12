# REASONIX.md — ros-ground-station

## Stack

- **Language** — Python 3.8+ (ROS Noetic compat)
- **GUI** — PyQt5 desktop app with embedded RViz via C++ glue (`ctypes.CDLL`)
- **Messaging** — MQTT via paho-mqtt + Mosquitto broker
- **Container** — Docker compose running ROS Noetic containers (Gazebo + gmapping)
- **Testing** — pytest (no QTest/Xvfb), ruff linting

## Layout

| Directory | Purpose |
|-----------|---------|
| `protocol/` | Shared message protocol — zero ROS deps, Agent + Station both use it |
| `agent/` | Robot-side ROS↔MQTT bridge (base/mock/ros1) with rate limiting & topic tiers |
| `bridge/` | Station-side MQTT↔ROS bridge — auto type detection & dict→ROS conversion |
| `qt_frontend/` | PyQt5 desktop app — panels, MQTT client, embedded RViz via C++ glue |
| `broker/` | Mosquitto config (port 1883, anon) + Python fallback broker |
| `docker/` | Dockerfiles for ROS Noetic, station backend, mock agent |
| `tests/` | pytest suite — protocol, converter, bridge, clients, panels |

## Commands

```bash
pip install -e ".[qt,dev]"                           # install with Qt + dev deps
python -m pytest tests/ -v                            # run tests
ruff check .                                          # lint
cd qt_frontend/native && mkdir -p build && cd build   # build RViz C++ glue lib
  && cmake .. && make -j$(nproc)
./qt_frontend/scripts/start.sh                        # start full ground station
docker compose up -d robot-turtlebot-001              # start Turtlebot3 simulation
```

## Conventions

- **Imports** — `from __future__ import annotations` is the **first** import in every `.py` file.
- **Typing** — Use `Optional[X]` / `List[X]` / `Dict[K, V]` (not `X | None` / `list[X]`) — Python 3.8 compat.
- **Paths** — Use `pathlib.Path` exclusively, never string concatenation.
- **Commits** — Format: `<type>: <中文简短描述>`. Types: `feat`, `fix`, `refactor`, `docs`, `test`.
  Append `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`.
- **Lint** — ruff with line-length=100, rules E/F/I/W.

## Watch out for

- **Two isolated roscore instances** — container runs its own roscore, host runs another. They communicate ONLY via MQTT, never directly.
- **RViz glue must be compiled first** — `librviz_widget.so` is NOT committed; build it before running `start.sh`.
- **OccupancyGrid (/map) not flowing** — Bridge registers the publisher but published map data never arrives on ROS. Root cause is a threading/timing issue with large messages in the Bridge MQTT callback. `bytes()` negative-value bug was already fixed.
- **`/tf_static` latched topic** — Agent subscriber doesn't receive Turtlebot3's latched static transforms. Workaround: `station.launch` publishes static TF for `base_scan`/`imu_link` via `static_transform_publisher`.
- **21 tests failing** — `test_dict_to_ros_msg.py` (15 fail: `genpy.message.get_message_class` import path mismatch), `test_protocol_registry.py` (4 fail: PointCloud2 tier changed HEAVY→MEDIUM but tests not updated), `test_mqtt_client.py` (1 fail).
