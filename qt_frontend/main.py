from __future__ import annotations

import sys
from pathlib import Path

import yaml
from PyQt5.QtWidgets import QApplication

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from qt_frontend.main_window import MainWindow


def main() -> None:
    config_path = Path(__file__).resolve().parent / "config" / "config.yaml"
    config: dict = {}
    if config_path.exists():
        with open(config_path, "r") as f:
            config = yaml.safe_load(f) or {}

    app = QApplication(sys.argv)
    app.setApplicationName("ROS Ground Station")
    app.setOrganizationName("ros-ground-station")

    window = MainWindow(config)
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
