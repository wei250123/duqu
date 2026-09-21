import json
import random
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                              QTextEdit, QComboBox, QLineEdit, QCheckBox, QMessageBox,
                              QFrame)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

from config.config_manager import config_manager
from core.mqtt.mqtt_client import mqtt_manager
from utils.logger import log_manager


class MqttDebugPage(QWidget):
    TOPIC_COLORS = {}

    def __init__(self):
        super().__init__()
        self._subscribed_topics = set()
        self._pending_messages = []
        self._paused = False
        self._init_ui()
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._flush_messages)
        self._refresh_timer.start(200)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── 设备选择行 ──
        dev_row = QHBoxLayout()
        dev_row.addWidget(QLabel("设备:"))
        self._device_combo = QComboBox()
        self._device_combo.setMinimumWidth(150)
        self._refresh_devices()
        dev_row.addWidget(self._device_combo)
        dev_row.addStretch()
        layout.addLayout(dev_row)

        # ── 订阅区域 ──
        sub_frame = QFrame()
        sub_frame.setObjectName("sub_frame")
        sub_frame.setStyleSheet("""
            #sub_frame {
                background-color: #ffffff;
                border: 1px solid #e0e0e0;
                border-radius: 4px;
            }
        """)
        sub_layout = QVBoxLayout(sub_frame)
        sub_layout.setContentsMargins(10, 8, 10, 8)
        sub_layout.setSpacing(6)

        sub_header = QHBoxLayout()
        sub_lbl = QLabel("订阅管理")
        sub_lbl.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        sub_lbl.setStyleSheet("color: #333333;")
        sub_header.addWidget(sub_lbl)
        sub_header.addStretch()
        sub_layout.addLayout(sub_header)

        sub_ctrl = QHBoxLayout()
        sub_ctrl.addWidget(QLabel("主题:"))
        self._topic_edit = QLineEdit()
        self._topic_edit.setPlaceholderText("MQTT主题，如 factory/line1/+/telemetry")
        self._topic_edit.setMinimumWidth(280)
        self._topic_edit.returnPressed.connect(self._subscribe)
        sub_ctrl.addWidget(self._topic_edit)

        self._subscribe_btn = QPushButton("订阅")
        self._subscribe_btn.clicked.connect(self._subscribe)
        self._subscribe_btn.setStyleSheet(
            "QPushButton { background-color: #27ae60; color: white; padding: 4px 14px; "
            "border: none; border-radius: 3px; font-weight: bold; }"
            "QPushButton:hover { background-color: #219a52; }"
        )
        sub_ctrl.addWidget(self._subscribe_btn)

        self._unsubscribe_btn = QPushButton("取消订阅")
        self._unsubscribe_btn.clicked.connect(self._unsubscribe)
        self._unsubscribe_btn.setStyleSheet(
            "QPushButton { background-color: #c0392b; color: white; padding: 4px 14px; "
            "border: none; border-radius: 3px; font-weight: bold; }"
            "QPushButton:hover { background-color: #a93226; }"
        )
        sub_ctrl.addWidget(self._unsubscribe_btn)
        sub_layout.addLayout(sub_ctrl)

        self._sub_label = QLabel("当前未订阅任何主题")
        self._sub_label.setStyleSheet("color: #999999; font-size: 11px; padding: 2px 0;")
        sub_layout.addWidget(self._sub_label)
        layout.addWidget(sub_frame)

        # ── 发送区域 ──
        send_frame = QFrame()
        send_frame.setObjectName("send_frame")
        send_frame.setStyleSheet("""
            #send_frame {
                background-color: #ffffff;
                border: 1px solid #e0e0e0;
                border-radius: 4px;
            }
        """)
        send_layout = QVBoxLayout(send_frame)
        send_layout.setContentsMargins(10, 8, 10, 8)
        send_layout.setSpacing(6)

        send_header = QHBoxLayout()
        send_lbl = QLabel("发送消息")
        send_lbl.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        send_lbl.setStyleSheet("color: #333333;")
        send_header.addWidget(send_lbl)
        send_header.addStretch()
        send_layout.addLayout(send_header)

        send_topic_row = QHBoxLayout()
        send_topic_row.addWidget(QLabel("发布主题:"))
        self._send_topic = QLineEdit()
        self._send_topic.setPlaceholderText("目标主题，如 factory/line1/command")
        self._send_topic.setMinimumWidth(300)
        send_topic_row.addWidget(self._send_topic)

        send_topic_row.addWidget(QLabel("QoS:"))
        self._send_qos = QComboBox()
        self._send_qos.addItems(["0", "1", "2"])
        self._send_qos.setCurrentText("1")
        self._send_qos.setFixedWidth(50)
        send_topic_row.addWidget(self._send_qos)

        self._send_retain = QCheckBox("保留")
        send_topic_row.addWidget(self._send_retain)
        send_layout.addLayout(send_topic_row)

        payload_row = QHBoxLayout()
        payload_row.addWidget(QLabel("消息内容:"))
        self._send_payload = QTextEdit()
        self._send_payload.setPlaceholderText('输入消息内容，支持文本或JSON格式。\n如: {"cmd": "start", "value": 100}')
        self._send_payload.setMaximumHeight(80)
        self._send_payload.setFont(QFont("Consolas", 10))
        self._send_payload.setStyleSheet("""
            QTextEdit {
                background-color: #fafafa;
                color: #333333;
                border: 1px solid #e0e0e0;
                border-radius: 3px;
                padding: 4px;
            }
        """)
        payload_row.addWidget(self._send_payload)
        send_layout.addLayout(payload_row)

        send_btn_row = QHBoxLayout()
        self._format_json_btn = QPushButton("JSON格式化")
        self._format_json_btn.clicked.connect(self._format_json)
        self._format_json_btn.setStyleSheet(
            "QPushButton { background-color: #f0f0f0; color: #555555; padding: 4px 12px; "
            "border: 1px solid #d0d0d0; border-radius: 3px; }"
            "QPushButton:hover { background-color: #e0e0e0; }"
        )
        send_btn_row.addWidget(self._format_json_btn)

        send_btn_row.addStretch()

        self._send_btn = QPushButton("发送消息")
        self._send_btn.clicked.connect(self._send_message)
        self._send_btn.setStyleSheet(
            "QPushButton { background-color: #2980b9; color: white; padding: 6px 20px; "
            "border: none; border-radius: 3px; font-weight: bold; font-size: 13px; }"
            "QPushButton:hover { background-color: #2472a4; }"
        )
        send_btn_row.addWidget(self._send_btn)
        send_layout.addLayout(send_btn_row)
        layout.addWidget(send_frame)

        # ── 消息显示区域 ──
        display_row = QHBoxLayout()
        display_label = QLabel("接收消息")
        display_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        display_label.setStyleSheet("color: #333333;")
        display_row.addWidget(display_label)
        display_row.addStretch()

        self._pause_btn = QPushButton("暂停")
        self._pause_btn.setCheckable(True)
        self._pause_btn.toggled.connect(self._toggle_pause)
        self._pause_btn.setStyleSheet(
            "QPushButton { padding: 3px 12px; border: 1px solid #d0d0d0; border-radius: 3px; "
            "background: #f5f5f5; color: #555555; }"
            "QPushButton:checked { background: #e74c3c; color: white; border-color: #e74c3c; }"
        )
        display_row.addWidget(self._pause_btn)

        self._clear_btn = QPushButton("清除")
        self._clear_btn.clicked.connect(self._clear_messages)
        self._clear_btn.setStyleSheet(
            "QPushButton { padding: 3px 12px; border: 1px solid #d0d0d0; border-radius: 3px; "
            "background: #f5f5f5; color: #555555; }"
            "QPushButton:hover { background: #e0e0e0; }"
        )
        display_row.addWidget(self._clear_btn)

        self._auto_scroll_check = QCheckBox("自动滚动")
        self._auto_scroll_check.setChecked(True)
        display_row.addWidget(self._auto_scroll_check)
        layout.addLayout(display_row)

        self._msg_display = QTextEdit()
        self._msg_display.setReadOnly(True)
        self._msg_display.setFont(QFont("Consolas", 10))
        self._msg_display.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                padding: 5px;
            }
        """)
        layout.addWidget(self._msg_display, 1)

    def _refresh_devices(self):
        self._device_combo.clear()
        self._device_combo.addItem("-- 选择设备 --", None)
        for device_id in config_manager.devices:
            self._device_combo.addItem(device_id, device_id)

    # ── 订阅功能 ──

    def _subscribe(self):
        topic = self._topic_edit.text().strip()
        if not topic:
            QMessageBox.warning(self, "提示", "请输入订阅主题")
            return
        device_id = self._device_combo.currentData()
        client = mqtt_manager._clients.get(device_id) if device_id else None
        if not client or not client.is_connected:
            QMessageBox.warning(self, "提示", "请先选择在线设备并确保MQTT已连接")
            return
        client.set_message_callback(self._on_message)
        success = client.subscribe(topic)
        if success:
            self._subscribed_topics.add(topic)
            self._update_sub_label()
            self._msg_display.append(
                f'<span style="color:#27ae60;">[订阅成功] {topic}</span>')
        else:
            QMessageBox.warning(self, "失败", f"订阅 {topic} 失败")

    def _unsubscribe(self):
        topic = self._topic_edit.text().strip()
        if not topic:
            QMessageBox.warning(self, "提示", "请输入要取消的订阅主题")
            return
        device_id = self._device_combo.currentData()
        client = mqtt_manager._clients.get(device_id) if device_id else None
        if not client:
            return
        client.unsubscribe(topic)
        self._subscribed_topics.discard(topic)
        self._update_sub_label()
        self._msg_display.append(
            f'<span style="color:#c0392b;">[取消订阅] {topic}</span>')

    def _update_sub_label(self):
        if self._subscribed_topics:
            self._sub_label.setText(f"已订阅: {', '.join(sorted(self._subscribed_topics))}")
        else:
            self._sub_label.setText("当前未订阅任何主题")

    def _on_message(self, topic: str, payload: str):
        self._pending_messages.append((topic, payload))

    def _flush_messages(self):
        if self._paused or not self._pending_messages:
            return
        messages = self._pending_messages
        self._pending_messages = []
        for topic, payload in messages:
            display = self._format_message(topic, payload)
            self._msg_display.append(display)
        if self._auto_scroll_check.isChecked():
            self._msg_display.verticalScrollBar().setValue(
                self._msg_display.verticalScrollBar().maximum())

    def _format_message(self, topic: str, payload: str) -> str:
        if topic not in self.TOPIC_COLORS:
            hue = random.randint(0, 360)
            self.TOPIC_COLORS[topic] = f"hsl({hue}, 70%, 65%)"
        color = self.TOPIC_COLORS[topic]
        try:
            parsed = json.loads(payload)
            formatted = json.dumps(parsed, ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, TypeError):
            formatted = payload if len(payload) <= 500 else payload[:500] + "..."
        return (
            f'<div style="margin-bottom:8px; border-left:3px solid {color}; padding-left:8px;">'
            f'<span style="color:{color}; font-weight:bold;">{topic}</span><br>'
            f'<span style="color:#abb2bf; white-space:pre-wrap;">{formatted}</span>'
            f'</div>'
        )

    # ── 发送功能 ──

    def _send_message(self):
        topic = self._send_topic.text().strip()
        if not topic:
            QMessageBox.warning(self, "提示", "请输入发布主题")
            return
        payload = self._send_payload.toPlainText().strip()
        if not payload:
            QMessageBox.warning(self, "提示", "请输入消息内容")
            return
        device_id = self._device_combo.currentData()
        client = mqtt_manager._clients.get(device_id) if device_id else None
        if not client or not client.is_connected:
            QMessageBox.warning(self, "提示", "请先选择在线设备并确保MQTT已连接")
            return
        try:
            qos = int(self._send_qos.currentText())
        except ValueError:
            qos = 1
        retain = self._send_retain.isChecked()
        success = client.publish(topic, payload, qos=qos, retain=retain)
        if success:
            self._msg_display.append(
                f'<span style="color:#2980b9;">[发送成功] {topic}</span>'
                f'<br><span style="color:#abb2bf; white-space:pre-wrap;">'
                f'{payload[:500]}{"..." if len(payload) > 500 else ""}</span>')
            self._send_payload.clear()
        else:
            self._msg_display.append(
                f'<span style="color:#e74c3c;">[发送失败] {topic}</span>')

    def _format_json(self):
        text = self._send_payload.toPlainText().strip()
        if not text:
            return
        try:
            parsed = json.loads(text)
            formatted = json.dumps(parsed, ensure_ascii=False, indent=2)
            self._send_payload.setPlainText(formatted)
        except (json.JSONDecodeError, TypeError):
            QMessageBox.warning(self, "JSON格式化", "输入内容不是有效的JSON格式")

    def _toggle_pause(self, checked):
        self._paused = checked
        self._pause_btn.setText("继续" if checked else "暂停")

    def _clear_messages(self):
        self._msg_display.clear()