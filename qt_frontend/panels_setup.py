"""Called from C++ main() to build Python panels into the C++ QSplitter."""
from __future__ import annotations

import ctypes
import logging
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QLabel,
    QMainWindow,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from qt_frontend.panels import (
    CommandPanel,
    DataSenderPanel,
    EventPanel,
    FleetCommPanel,
    RobotListPanel,
    SensorSummaryPanel,
    TopicConfigPanel,
    TrafficMonitor,
)

logger = logging.getLogger(__name__)

# Will be set by setup()
_main_window = None
_rviz_container_ptr = None
_rviz_lib = None


def _init_rviz_lib():
    global _rviz_lib
    if _rviz_lib is not None:
        return
    lib_path = str(Path(__file__).resolve().parent / "native" / "build" / "librviz_widget.so")
    _rviz_lib = ctypes.CDLL(lib_path)
    _rviz_lib.load_config.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    _rviz_lib.load_config.restype = ctypes.c_int
    _rviz_lib.set_fixed_frame.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    _rviz_lib.set_fixed_frame.restype = None
    _rviz_lib.get_display_panel.argtypes = [ctypes.c_void_p]
    _rviz_lib.get_display_panel.restype = ctypes.c_void_p
    _rviz_lib.set_dock_layout.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    _rviz_lib.set_dock_layout.restype = None
    _rviz_lib.set_dock_host.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    _rviz_lib.set_dock_host.restype = None


class RvizPanelWrapper:
    """Lightweight wrapper for RViz C++ calls — no visual widget."""
    def __init__(self, container_ptr: int):
        self._widget_ptr = container_ptr

    def load_config(self, path: str) -> bool:
        if _rviz_lib is None:
            return False
        return _rviz_lib.load_config(self._widget_ptr, path.encode("utf-8")) == 0

    def set_fixed_frame(self, frame: str) -> None:
        if _rviz_lib is not None:
            _rviz_lib.set_fixed_frame(self._widget_ptr, frame.encode("utf-8"))

    def get_display_panel(self):
        if _rviz_lib is None:
            return None
        ptr = _rviz_lib.get_display_panel(self._widget_ptr)
        if not ptr:
            return None
        import sip
        return sip.wrapinstance(int(ptr), QWidget)

    def set_dock_layout(self, layout) -> None:
        if _rviz_lib is None:
            return
        import sip
        lptr = sip.unwrapinstance(layout)
        _rviz_lib.set_dock_layout(self._widget_ptr, ctypes.c_void_p(lptr))

    def set_dock_host(self, host) -> None:
        if _rviz_lib is None:
            return
        import sip
        hptr = sip.unwrapinstance(host)
        _rviz_lib.set_dock_host(self._widget_ptr, ctypes.c_void_p(hptr))


class MainWindow(QWidget):
    """Panel container — wraps a C++ QMainWindow."""
    def __init__(self, main_window_ptr: int):
        super().__init__()
        import sip
        self._cpp_win = sip.wrapinstance(main_window_ptr, type(
            __import__('PyQt5.QtWidgets', fromlist=['QMainWindow']).QMainWindow
        ))
        self._cpp_win.setWindowTitle("ROS Ground Station")
        self._cpp_win.resize(1600, 900)


def setup(cpp_splitter_ptr: int, rviz_container_ptr: int):
    """Called from C++ main(). Builds Python panels into the C++ splitter.

    Args:
        cpp_splitter_ptr: void* to the C++ QSplitter
        rviz_container_ptr: void* to the RViz container in center pane
    """
    global _rviz_container_ptr
    _rviz_container_ptr = rviz_container_ptr

    import sip

    _init_rviz_lib()

    # Wrap C++ splitter
    cpp_splitter = sip.wrapinstance(int(cpp_splitter_ptr), QSplitter)

    # --- Left panels ---
    robot_list = RobotListPanel()
    command = CommandPanel()
    event_panel = EventPanel()

    robot_list.robot_selected.connect(command.on_robot_selected)
    robot_list.robot_deselected.connect(lambda: command.on_robot_selected(""))

    left_tabs = QTabWidget()
    robot_tab = QWidget()
    rl = QVBoxLayout(robot_tab)
    rl.setContentsMargins(0, 0, 0, 0)
    rl.addWidget(robot_list)
    rl.addWidget(command)
    left_tabs.addTab(robot_tab, "机器人")

    config_tab = QWidget()
    cl = QVBoxLayout(config_tab)
    cl.setContentsMargins(0, 0, 0, 0)
    config_sub = QTabWidget()
    config_sub.addTab(TopicConfigPanel(), "传输")
    config_sub.addTab(FleetCommPanel(), "编队")
    cl.addWidget(config_sub)
    left_tabs.addTab(config_tab, "配置")
    left_tabs.addTab(event_panel, "事件")

    # Add left panels to C++ splitter's left placeholder (index 0)
    left_placeholder = cpp_splitter.widget(0)
    if left_placeholder and left_placeholder.layout():
        left_placeholder.layout().addWidget(left_tabs)

    # --- Right panels ---
    right_tabs = QTabWidget()

    # Display tab — RViz native DisplaysPanel
    rviz_wrapper = RvizPanelWrapper(rviz_container_ptr)
    rviz_wrapper.load_config(
        str(Path(__file__).resolve().parent / "config" / "default.rviz")
    )
    rviz_wrapper.set_fixed_frame("map")

    display_container = QWidget()
    dl = QVBoxLayout(display_container)
    dl.setContentsMargins(0, 0, 0, 0)
    display_splitter = QSplitter(Qt.Vertical)
    display_panel_holder = QWidget()
    display_panel_layout = QVBoxLayout(display_panel_holder)
    display_panel_layout.setContentsMargins(0, 0, 0, 0)
    image_panel_container = QWidget()
    image_panel_layout = QVBoxLayout(image_panel_container)
    image_panel_layout.setContentsMargins(0, 0, 0, 0)
    image_dock_host = QMainWindow()
    image_dock_host.setDockOptions(
        QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks
    )
    image_panel_layout.addWidget(image_dock_host)
    image_panel_container.setMinimumHeight(160)
    image_panel_container.setMaximumHeight(280)
    image_panel_container.hide()
    native_display = rviz_wrapper.get_display_panel()
    if native_display:
        display_panel_layout.addWidget(native_display)
    else:
        display_panel_layout.addWidget(QLabel("Display panel not available"))
    display_splitter.addWidget(display_panel_holder)
    display_splitter.addWidget(image_panel_container)
    display_splitter.setStretchFactor(0, 1)
    display_splitter.setStretchFactor(1, 0)
    dl.addWidget(display_splitter)
    rviz_wrapper.set_dock_host(image_dock_host)
    right_tabs.addTab(display_container, "Display")

    right_tabs.addTab(SensorSummaryPanel(), "摘要")
    right_tabs.addTab(DataSenderPanel(), "发送")
    right_tabs.addTab(TrafficMonitor(), "流量")

    # Add right panels to C++ splitter's right placeholder (index 2)
    right_placeholder = cpp_splitter.widget(2)
    if right_placeholder and right_placeholder.layout():
        right_placeholder.layout().addWidget(right_tabs)
