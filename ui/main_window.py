from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                                 QPushButton, QLabel, QStackedWidget, QFrame, QStatusBar,
                                 QMessageBox, QApplication, QListWidget, QListWidgetItem)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt6.QtGui import QIcon, QFont, QAction

from ui.pages.device_page import DevicePage
from ui.pages.monitor_page import MonitorPage
from ui.pages.data_page import DataPage
from ui.pages.log_page import LogPage
from ui.pages.mqtt_debug_page import MqttDebugPage
from ui.pages.dashboard_page import DashboardPage
from ui.pages.visualization_page import VisualizationPage
from ui.pages.settings_page import SettingsPage
from device.device_manager import device_manager, DeviceRuntimeStatus
from core.security.auth import auth_manager
from core.data_types import CollectResult
from utils.logger import log_manager
from utils.watchdog import watchdog
from config.config_manager import config_manager


class MainWindow(QMainWindow):
    log_signal = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("设备数据采集")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)
        self._init_ui()
        self._init_connections()
        self._init_timers()
        self._apply_font_size()
        watchdog.feed()
        log_manager.info("系统", "主界面初始化完成")

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        nav_frame = QFrame()
        nav_frame.setFixedWidth(200)
        nav_frame.setStyleSheet("""
            QFrame#nav_frame {
                background-color: #2c3e50;
                border-right: 1px solid #1a252f;
            }
        """)
        nav_frame.setObjectName("nav_frame")
        nav_layout = QVBoxLayout(nav_frame)
        nav_layout.setContentsMargins(0, 10, 0, 10)
        nav_layout.setSpacing(2)

        title_label = QLabel("  IIoT 网关")
        title_label.setStyleSheet("color: white; font-size: 18px; font-weight: bold; padding: 10px;")
        nav_layout.addWidget(title_label)
        self._title_label = title_label

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #4a6a8a;")
        nav_layout.addWidget(line)

        self._nav_list = QListWidget()
        self._nav_list.setStyleSheet("""
            QListWidget {
                background-color: transparent;
                border: none;
                color: #bdc3c7;
                font-size: 14px;
                padding: 5px;
            }
            QListWidget::item {
                padding: 12px 15px;
                border-radius: 5px;
                margin: 2px 5px;
            }
            QListWidget::item:hover {
                background-color: #34495e;
                color: white;
            }
            QListWidget::item:selected {
                background-color: #3498db;
                color: white;
            }
        """)
        nav_items = [
            ("  设备管理", 0, "view_data"),
            ("  可视化大屏", 1, "view_data"),
            ("  数据可视化", 2, "view_data"),
            ("  实时监控", 3, "view_data"),
            ("  数据查询", 4, "view_data"),
            ("  日志调试", 5, "debug_tools"),
            ("  MQTT调试", 6, "debug_tools"),
            ("  系统设置", 7, "system_settings"),
        ]
        for text, idx, permission in nav_items:
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, idx)
            item.setSizeHint(QSize(0, 45))
            item.setHidden(not auth_manager.has_permission(permission))
            self._nav_list.addItem(item)

        self._nav_list.setCurrentRow(0)
        nav_layout.addWidget(self._nav_list)
        nav_layout.addStretch()

        info_label = QLabel("  v1.0.0")
        info_label.setStyleSheet("color: #7f8c8d; font-size: 11px; padding: 10px;")
        nav_layout.addWidget(info_label)
        self._info_label = info_label

        self._content_stack = QStackedWidget()
        self._content_stack.addWidget(DevicePage())
        self._dashboard_page = DashboardPage()
        self._content_stack.addWidget(self._dashboard_page)
        self._visualization_page = VisualizationPage()
        self._content_stack.addWidget(self._visualization_page)
        self._content_stack.addWidget(MonitorPage())
        self._content_stack.addWidget(DataPage())
        self._content_stack.addWidget(LogPage())
        self._content_stack.addWidget(MqttDebugPage())
        self._settings_page = SettingsPage()
        self._content_stack.addWidget(self._settings_page)

        main_layout.addWidget(nav_frame)
        main_layout.addWidget(self._content_stack, 1)

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_label = QLabel("系统就绪")
        self._status_bar.addWidget(self._status_label)
        self._status_bar.addPermanentWidget(QLabel("  |  "))

    def _init_connections(self):
        self._nav_list.currentRowChanged.connect(self._content_stack.setCurrentIndex)
        device_manager.set_status_callback(self._on_device_status)
        device_manager.set_data_callback(self._on_data_received)
        self.log_signal.connect(self._on_new_log)
        self._settings_page.font_size_changed.connect(self._apply_font_size)

    def _init_timers(self):
        self._watchdog_timer = QTimer()
        self._watchdog_timer.timeout.connect(watchdog.feed)
        self._watchdog_timer.start(3000)

    def _on_device_status(self, device_id: str, status: DeviceRuntimeStatus):
        status_text = {
            DeviceRuntimeStatus.ONLINE: "在线",
            DeviceRuntimeStatus.OFFLINE: "离线",
            DeviceRuntimeStatus.COLLECTING: "采集中",
            DeviceRuntimeStatus.ERROR: "异常",
            DeviceRuntimeStatus.DISABLED: "已禁用"
        }.get(status, "未知")
        self._status_label.setText(f"设备[{device_id}]: {status_text}")

    def _on_data_received(self, result: CollectResult):
        if result.success and result.value is not None:
            try:
                self._dashboard_page.feed_data(
                    result.device_id, result.point_name,
                    float(result.value),
                    result.filtered_value,
                    result.timestamp
                )
                self._visualization_page.feed_data(
                    result.device_id, result.point_name,
                    float(result.value),
                    result.filtered_value,
                    result.timestamp
                )
            except Exception:
                pass

    def _on_new_log(self, entry):
        pass

    def _apply_font_size(self):
        fs = config_manager.app_config.font_size
        app = QApplication.instance()
        if app:
            app.setFont(QFont("Microsoft YaHei", fs))
        self._title_label.setStyleSheet(
            f"color: white; font-size: {fs + 6}px; font-weight: bold; padding: 10px;"
        )
        self._nav_list.setStyleSheet(f"""
            QListWidget {{
                background-color: transparent;
                border: none;
                color: #bdc3c7;
                font-size: {fs + 2}px;
                padding: 5px;
            }}
            QListWidget::item {{
                padding: 12px 15px;
                border-radius: 5px;
                margin: 2px 5px;
            }}
            QListWidget::item:hover {{
                background-color: #34495e;
                color: white;
            }}
            QListWidget::item:selected {{
                background-color: #3498db;
                color: white;
            }}
        """)
        self._info_label.setStyleSheet(
            f"color: #7f8c8d; font-size: {fs - 1}px; padding: 10px;"
        )

    def closeEvent(self, event):
        reply = QMessageBox.question(
            self, "确认退出", "确定要退出程序吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            device_manager.stop_all()
            log_manager.info("系统", "程序退出")
            event.accept()
        else:
            event.ignore()
