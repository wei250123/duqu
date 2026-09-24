from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                              QGroupBox, QFormLayout, QLineEdit, QSpinBox, QComboBox,
                              QCheckBox, QFileDialog, QMessageBox, QTabWidget)
from PyQt6.QtCore import Qt, pyqtSignal

from config.config_manager import config_manager, AppConfig, LogConfig
from core.security.auth import auth_manager, Role
from core.security.encryption import data_encryptor
from utils.logger import log_manager, LogLevel
from utils.watchdog import watchdog


class SettingsPage(QWidget):
    font_size_changed = pyqtSignal(int)
    def __init__(self):
        super().__init__()
        self._init_ui()
        self._load_settings()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        self._tabs = QTabWidget()

        self._tabs.addTab(self._create_general_tab(), "通用设置")
        self._tabs.addTab(self._create_log_tab(), "日志设置")
        self._tabs.addTab(self._create_security_tab(), "安全设置")
        self._tabs.addTab(self._create_about_tab(), "关于")

        layout.addWidget(self._tabs, 1)

        btn_layout = QHBoxLayout()
        self._save_btn = QPushButton("保存设置")
        self._save_btn.clicked.connect(self._save_settings)
        self._save_btn.setStyleSheet("QPushButton { background-color: #27ae60; color: white; padding: 8px 20px; }")
        self._restore_btn = QPushButton("恢复默认")
        self._restore_btn.clicked.connect(self._restore_defaults)
        self._export_btn = QPushButton("导出配置")
        self._export_btn.clicked.connect(self._export_settings)
        self._import_btn = QPushButton("导入配置")
        self._import_btn.clicked.connect(self._import_settings)
        btn_layout.addWidget(self._save_btn)
        btn_layout.addWidget(self._restore_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self._export_btn)
        btn_layout.addWidget(self._import_btn)
        layout.addLayout(btn_layout)

    def _create_general_tab(self):
        widget = QWidget()
        layout = QFormLayout(widget)

        self._combo_lang = QComboBox()
        self._combo_lang.addItems(["zh_CN", "en_US"])
        layout.addRow("语言:", self._combo_lang)

        self._combo_theme = QComboBox()
        self._combo_theme.addItems(["light", "dark"])
        layout.addRow("主题:", self._combo_theme)

        self._spin_font_size = QSpinBox()
        self._spin_font_size.setRange(8, 30)
        self._spin_font_size.setSuffix(" pt")
        self._spin_font_size.setValue(12)
        layout.addRow("字体大小:", self._spin_font_size)

        self._check_batch_publish = QCheckBox("批量发送MQTT(关闭后逐条发送)")
        self._check_batch_publish.setChecked(True)
        layout.addRow("", self._check_batch_publish)

        self._check_enable_filter = QCheckBox("启用数据过滤(关闭后全部上传)")
        self._check_enable_filter.setChecked(False)
        layout.addRow("", self._check_enable_filter)

        self._check_auto_start = QCheckBox("启动时自动采集")
        layout.addRow("", self._check_auto_start)

        self._check_min_tray = QCheckBox("最小化到托盘")
        layout.addRow("", self._check_min_tray)

        self._spin_upload_rate = QSpinBox()
        self._spin_upload_rate.setRange(0, 10000)
        self._spin_upload_rate.setSuffix(" 条/秒 (0=不限)")
        layout.addRow("上传速率限制:", self._spin_upload_rate)

        self._check_watchdog = QCheckBox("启用看门狗")
        self._check_watchdog.stateChanged.connect(self._on_watchdog_toggle)
        layout.addRow("", self._check_watchdog)

        self._spin_watchdog_timeout = QSpinBox()
        self._spin_watchdog_timeout.setRange(10, 300)
        self._spin_watchdog_timeout.setSuffix(" 秒")
        layout.addRow("看门狗超时:", self._spin_watchdog_timeout)

        return widget

    def _create_log_tab(self):
        widget = QWidget()
        layout = QFormLayout(widget)

        self._combo_log_level = QComboBox()
        self._combo_log_level.addItems(["DEBUG", "INFO", "WARN", "ERROR", "FATAL"])
        self._combo_log_level.setCurrentText("INFO")
        self._combo_log_level.currentTextChanged.connect(self._on_log_level_changed)
        layout.addRow("日志级别:", self._combo_log_level)

        self._spin_log_size = QSpinBox()
        self._spin_log_size.setRange(1, 1000)
        self._spin_log_size.setSuffix(" MB")
        self._spin_log_size.setValue(10)
        layout.addRow("日志文件大小:", self._spin_log_size)

        self._spin_log_backup = QSpinBox()
        self._spin_log_backup.setRange(1, 365)
        self._spin_log_backup.setValue(30)
        layout.addRow("日志保留天数:", self._spin_log_backup)

        return widget

    def _create_security_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        pwd_group = QGroupBox("启动密码")
        pwd_layout = QFormLayout()
        self._edit_startup_pwd = QLineEdit()
        self._edit_startup_pwd.setPlaceholderText("留空则无需密码")
        self._edit_startup_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit_startup_pwd_confirm = QLineEdit()
        self._edit_startup_pwd_confirm.setPlaceholderText("再次输入确认")
        self._edit_startup_pwd_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        pwd_layout.addRow("新密码:", self._edit_startup_pwd)
        pwd_layout.addRow("确认密码:", self._edit_startup_pwd_confirm)
        pwd_group.setLayout(pwd_layout)
        layout.addWidget(pwd_group)

        encrypt_group = QGroupBox("数据加密")
        encrypt_layout = QFormLayout()
        self._check_encrypt = QCheckBox("启用数据传输加密")
        self._check_encrypt.stateChanged.connect(self._on_encrypt_toggle)
        encrypt_layout.addRow("", self._check_encrypt)
        encrypt_group.setLayout(encrypt_layout)
        layout.addWidget(encrypt_group)

        layout.addStretch()
        return widget

    def _create_about_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("工业设备数据采集与MQTT上传网关")
        title.setStyleSheet("font-size: 20px; font-weight: bold; padding: 20px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        version = QLabel("版本: v1.0.0")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)

        desc = QLabel("支持串口和以太网通信 | Modbus RTU/TCP | MQTT上传\n"
                       "SQLite本地存储 | 断网缓存 | 自动重连 | 看门狗保护")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet("color: #7f8c8d; padding: 10px;")
        layout.addWidget(desc)

        layout.addStretch()
        return widget

    def _load_settings(self):
        cfg = config_manager.app_config
        self._combo_lang.setCurrentText(cfg.language)
        self._combo_theme.setCurrentText(cfg.theme)
        self._spin_font_size.setValue(cfg.font_size)
        self._check_batch_publish.setChecked(cfg.batch_publish)
        self._check_enable_filter.setChecked(cfg.enable_filter)
        self._check_auto_start.setChecked(cfg.auto_start_collect)
        self._check_min_tray.setChecked(cfg.min_to_tray)
        self._spin_upload_rate.setValue(cfg.max_upload_rate)
        self._combo_log_level.setCurrentText(cfg.log.level)
        self._spin_log_size.setValue(cfg.log.max_file_size_mb)
        self._spin_log_backup.setValue(cfg.log.save_days)
        self._check_watchdog.setChecked(watchdog._enabled)
        self._spin_watchdog_timeout.setValue(int(watchdog._heartbeat_timeout))
        self._check_encrypt.setChecked(data_encryptor._enabled)

    def _require_admin(self) -> bool:
        if auth_manager.is_logged_in() and auth_manager.has_permission('system_settings'):
            return True
        QMessageBox.warning(self, "无权限", "只有管理员可以修改系统设置")
        return False

    def _save_settings(self):
        if not self._require_admin():
            return
        cfg = config_manager.app_config
        cfg.language = self._combo_lang.currentText()
        cfg.theme = self._combo_theme.currentText()
        cfg.font_size = self._spin_font_size.value()
        cfg.batch_publish = self._check_batch_publish.isChecked()
        cfg.enable_filter = self._check_enable_filter.isChecked()
        cfg.auto_start_collect = self._check_auto_start.isChecked()
        cfg.min_to_tray = self._check_min_tray.isChecked()
        cfg.max_upload_rate = self._spin_upload_rate.value()
        cfg.log.level = self._combo_log_level.currentText()
        cfg.log.max_file_size_mb = self._spin_log_size.value()
        cfg.log.save_days = self._spin_log_backup.value()

        pwd = self._edit_startup_pwd.text()
        if pwd:
            if pwd != self._edit_startup_pwd_confirm.text():
                QMessageBox.warning(self, "错误", "两次输入的密码不一致")
                return
            success, message = auth_manager.set_startup_password(pwd)
            if not success:
                QMessageBox.warning(self, "错误", message)
                return
        elif self._edit_startup_pwd.text() == "":
            auth_manager.set_startup_password("")

        if self._check_encrypt.isChecked():
            data_encryptor.enable()
        else:
            data_encryptor.disable()

        config_manager.save_app_config()
        self.font_size_changed.emit(cfg.font_size)
        QMessageBox.information(self, "成功", "设置已保存")

    def _restore_defaults(self):
        if not self._require_admin():
            return
        reply = QMessageBox.question(self, "确认恢复", "确定要恢复所有默认设置吗？",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            config_manager.restore_defaults()
            self._load_settings()
            self.font_size_changed.emit(config_manager.app_config.font_size)
            QMessageBox.information(self, "成功", "已恢复默认设置")

    def _export_settings(self):
        if not self._require_admin():
            return
        filepath, _ = QFileDialog.getSaveFileName(self, "导出配置", "config_backup.json", "JSON文件 (*.json)")
        if filepath:
            config_manager.export_config(filepath)
            QMessageBox.information(self, "成功", f"配置已导出到 {filepath}")

    def _import_settings(self):
        if not self._require_admin():
            return
        filepath, _ = QFileDialog.getOpenFileName(self, "导入配置", "", "JSON文件 (*.json)")
        if filepath:
            try:
                config_manager.import_config(filepath)
                self._load_settings()
                QMessageBox.information(self, "成功", "配置已导入")
            except Exception as e:
                QMessageBox.warning(self, "错误", f"导入失败: {e}")

    def _on_log_level_changed(self, level_text):
        level_map = {"DEBUG": LogLevel.DEBUG, "INFO": LogLevel.INFO, "WARN": LogLevel.WARN,
                     "ERROR": LogLevel.ERROR, "FATAL": LogLevel.FATAL}
        if level_text in level_map:
            log_manager.set_level(level_map[level_text])

    def _on_watchdog_toggle(self, state):
        if state == Qt.CheckState.Checked.value:
            watchdog.enable(heartbeat_timeout=self._spin_watchdog_timeout.value())
        else:
            watchdog.disable()

    def _on_encrypt_toggle(self, state):
        pass
