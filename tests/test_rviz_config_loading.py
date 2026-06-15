from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read_repo_file(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_main_window_loads_default_rviz_config_after_widget_creation():
    source = _read_repo_file("qt_frontend/main_window.py")

    assert "self._current_rviz_config_path" in source
    assert "lib.load_config.argtypes = [ctypes.c_void_p, ctypes.c_char_p]" in source
    assert 'Path(__file__).resolve().parent / "config" / "default.rviz"' in source
    assert "lib.load_config(rviz_ptr, str(config_path).encode(\"utf-8\"))" in source
    assert "self._current_rviz_config_path = path" in source


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


def test_main_window_prompts_to_save_dirty_rviz_config_on_close():
    source = _read_repo_file("qt_frontend/main_window.py")
    close_source = source[source.index("def closeEvent("):]

    assert "self._rviz_config_has_changes()" in close_source
    assert "self._current_rviz_config_path" in close_source
    assert "当前 RViz 配置文件" in close_source
    assert "QMessageBox.Save" in close_source
    assert "QMessageBox.Discard" in close_source
    assert "QMessageBox.Cancel" in close_source
    assert "event.ignore()" in close_source
    assert "self._save_rviz_config(config_path)" in close_source
    assert "self._save_rviz_config_from_dialog()" in close_source


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


def test_native_tracks_rviz_config_dirty_state():
    header = _read_repo_file("qt_frontend/native/rviz_widget.h")
    source = _read_repo_file("qt_frontend/native/rviz_widget.cpp")

    assert "int has_config_changes(void* widget_ptr);" in header
    assert "bool config_dirty;" in source
    assert "QString config_snapshot;" in source
    assert "current_display_config_snapshot" in source
    assert "mark_config_dirty" in source
    assert "inst->config_dirty = true;" in source
    assert "instance->config_dirty = false;" in source
    assert "int has_config_changes(void* widget_ptr)" in source
    assert "current_display_config_snapshot(instance) != instance->config_snapshot" in source


def test_native_embeds_render_panel_not_full_visualization_frame():
    source = _read_repo_file("qt_frontend/native/rviz_widget.cpp")

    assert "g_instances[instance->render_panel] = instance;" in source
    assert "return static_cast<void*>(instance->render_panel);" in source
    assert "g_instances[instance->frame] = instance;" not in source
    assert "return static_cast<void*>(instance->frame);" not in source


def test_native_docks_rviz_image_panels_in_bottom_host_after_config_change_settles():
    source = _read_repo_file("qt_frontend/native/rviz_widget.cpp")
    extractor_source = source[
        source.index("void DockExtractor::onConfigChanged()"):source.index(
            "static bool g_ros_init_done"
        )
    ]
    move_source = source[
        source.index("static void move_image_panels_to_layout("):source.index(
            "void DockExtractor::moveImagePanels()"
        )
    ]

    assert "QTimer::singleShot(0, DockExtractor::instance(), SLOT(moveImagePanels()))" in (
        extractor_source
    )
    assert "QMainWindow* dock_host;" in source
    assert "findChildren<rviz::PanelDockWidget*>" in move_source
    assert 'title == "Camera" || title == "Image"' in move_source
    assert "dw->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);" in (
        move_source
    )
    assert "dw->setAllowedAreas(Qt::AllDockWidgetAreas);" in move_source
    assert "dw->setFeatures(dw->features()" in move_source
    assert "QDockWidget::DockWidgetFloatable" in move_source
    assert "QDockWidget::DockWidgetMovable" in move_source
    assert "inst->dock_host->addDockWidget(Qt::BottomDockWidgetArea, dw);" in (
        move_source
    )
    assert "inst->dock_host->show();" in move_source
    assert "setWidget(nullptr)" not in move_source
    assert "QVBoxLayout" not in move_source
