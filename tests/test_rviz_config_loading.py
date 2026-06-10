from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read_repo_file(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_main_window_loads_default_rviz_config_after_widget_creation():
    source = _read_repo_file("qt_frontend/main_window.py")

    assert "lib.load_config.argtypes = [ctypes.c_void_p, ctypes.c_char_p]" in source
    assert 'Path(__file__).resolve().parent / "config" / "default.rviz"' in source
    assert "lib.load_config(rviz_ptr, str(config_path).encode(\"utf-8\"))" in source


def test_main_window_exposes_rviz_config_load_and_save_controls():
    source = _read_repo_file("qt_frontend/main_window.py")

    assert 'QAction("加载 RViz 配置..."' in source
    assert 'QAction("保存 RViz 配置..."' in source
    assert 'QPushButton("加载 RViz")' in source
    assert 'QPushButton("保存 RViz")' in source
    assert "_load_rviz_config_from_dialog" in source
    assert "_save_rviz_config_from_dialog" in source
    assert "QFileDialog.getOpenFileName" in source
    assert "QFileDialog.getSaveFileName" in source


def test_native_load_config_uses_yaml_visualization_manager_not_frame_loader():
    source = _read_repo_file("qt_frontend/native/rviz_widget.cpp")
    load_config_source = source[
        source.index("int load_config("):source.index("void set_fixed_frame")
    ]

    assert "YamlConfigReader reader;" in load_config_source
    assert 'config.mapGetChild("Visualization Manager")' in load_config_source
    assert "manager->load(manager_config)" in load_config_source
    assert "restore_interaction_state(instance)" in load_config_source
    assert "loadDisplayConfig" not in load_config_source
    assert "(void)config_path" not in load_config_source


def test_native_save_config_writes_visualization_manager_only():
    header = _read_repo_file("qt_frontend/native/rviz_widget.h")
    source = _read_repo_file("qt_frontend/native/rviz_widget.cpp")
    save_config_source = source[
        source.index("int save_config("):source.index("void set_fixed_frame")
    ]

    assert "int save_config(void* widget_ptr, const char* config_path);" in header
    assert "YamlConfigWriter writer;" in save_config_source
    assert 'config.mapMakeChild("Visualization Manager")' in save_config_source
    assert "manager->save(manager_config)" in save_config_source
    assert "saveDisplayConfig" not in save_config_source
