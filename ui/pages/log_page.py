from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                              QTextEdit, QComboBox, QLineEdit, QCheckBox, QFileDialog,
                              QMessageBox)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QTextCharFormat, QFont

from utils.logger import log_manager, LogLevel


class LogPage(QWidget):
    COLORS = {
        "DEBUG": QColor("#7f8c8d"),
        "INFO": QColor("#2c3e50"),
        "WARN": QColor("#f39c12"),
        "ERROR": QColor("#e74c3c"),
        "FATAL": QColor("#c0392b"),
    }

    def __init__(self):
        super().__init__()
        self._init_ui()
        log_manager.add_callback(self._on_log_entry)
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._flush_logs)
        self._refresh_timer.start(500)
        self._pending_logs = []

    def _init_ui(self):
        layout = QVBoxLayout(self)

        control_layout = QHBoxLayout()
        control_layout.addWidget(QLabel("日志级别:"))
        self._level_combo = QComboBox()
        self._level_combo.addItems(["DEBUG", "INFO", "WARN", "ERROR", "FATAL"])
        self._level_combo.setCurrentText("INFO")
        self._level_combo.currentTextChanged.connect(self._apply_filter)
        control_layout.addWidget(self._level_combo)

        control_layout.addWidget(QLabel("关键词:"))
        self._keyword_edit = QLineEdit()
        self._keyword_edit.setPlaceholderText("输入关键词过滤...")
        self._keyword_edit.textChanged.connect(self._apply_filter)
        control_layout.addWidget(self._keyword_edit)

        control_layout.addWidget(QLabel("模块:"))
        self._module_edit = QLineEdit()
        self._module_edit.setPlaceholderText("模块名过滤...")
        self._module_edit.textChanged.connect(self._apply_filter)
        control_layout.addWidget(self._module_edit)

        self._pause_btn = QPushButton("暂停")
        self._pause_btn.setCheckable(True)
        self._pause_btn.toggled.connect(self._toggle_pause)
        control_layout.addWidget(self._pause_btn)

        self._clear_btn = QPushButton("清除")
        self._clear_btn.clicked.connect(self._clear_logs)
        control_layout.addWidget(self._clear_btn)

        self._export_btn = QPushButton("导出日志")
        self._export_btn.clicked.connect(self._export_logs)
        control_layout.addWidget(self._export_btn)

        self._auto_scroll_check = QCheckBox("自动滚动")
        self._auto_scroll_check.setChecked(True)
        control_layout.addWidget(self._auto_scroll_check)

        layout.addLayout(control_layout)

        self._log_display = QTextEdit()
        self._log_display.setReadOnly(True)
        self._log_display.setFont(QFont("Consolas", 10))
        self._log_display.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #333;
                padding: 5px;
            }
        """)
        layout.addWidget(self._log_display, 1)

    def _on_log_entry(self, entry):
        self._pending_logs.append(entry)

    def _flush_logs(self):
        if not self._pending_logs:
            return
        try:
            for entry in self._pending_logs:
                color = self.COLORS.get(entry.level, QColor("#d4d4d4"))
                fmt = QTextCharFormat()
                fmt.setForeground(color)
                self._log_display.mergeCurrentCharFormat(fmt)
                self._log_display.append(str(entry))
            self._pending_logs.clear()
            if self._auto_scroll_check.isChecked():
                scrollbar = self._log_display.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())
        except (RuntimeError, KeyboardInterrupt):
            pass

    def _apply_filter(self):
        level = self._level_combo.currentText() if self._level_combo.currentText() else None
        module = self._module_edit.text().strip() or None
        keyword = self._keyword_edit.text().strip() or None
        log_manager.set_filter(level=level, module=module, keyword=keyword)

    def _toggle_pause(self, checked):
        if checked:
            log_manager.pause()
            self._pause_btn.setText("恢复")
        else:
            log_manager.resume()
            self._pause_btn.setText("暂停")

    def _clear_logs(self):
        self._log_display.clear()
        log_manager.clear_buffer()

    def _export_logs(self):
        filepath, _ = QFileDialog.getSaveFileName(self, "导出日志", "gateway_logs.txt", "文本文件 (*.txt);;日志文件 (*.log)")
        if filepath:
            try:
                log_text = self._log_display.toPlainText()
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(log_text)
                QMessageBox.information(self, "成功", f"日志已导出到 {filepath}")
            except Exception as e:
                QMessageBox.warning(self, "错误", f"导出失败: {e}")