import time
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
                              QTableWidgetItem, QHeaderView, QComboBox, QPushButton,
                              QGroupBox, QGridLayout, QMessageBox)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont

from device.device_manager import device_manager, DeviceRuntimeStatus
from core.data_types import CollectResult
from core.collector.collector import collector_manager
from config.config_manager import config_manager


class MonitorPage(QWidget):
    _MODE_LABELS = {
        "timer": "定时采集",
        "trigger": "触发采集",
        "manual": "手动采集",
        "continuous": "及采及入",
    }

    def __init__(self):
        super().__init__()
        self._init_ui()
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh_monitor)
        self._refresh_timer.start(1000)
        self._device_list_timer = QTimer()
        self._device_list_timer.timeout.connect(self._refresh_device_list)
        self._device_list_timer.start(3000)

    def _init_ui(self):
        layout = QVBoxLayout(self)

        top_layout = QHBoxLayout()
        self._device_combo = QComboBox()
        self._device_combo.setMinimumWidth(200)
        self._device_combo.currentTextChanged.connect(self._on_device_changed)
        top_layout.addWidget(QLabel("选择设备:"))
        top_layout.addWidget(self._device_combo)

        self._start_btn = QPushButton("启动采集")
        self._start_btn.clicked.connect(self._start_device)
        self._start_btn.setStyleSheet("QPushButton { background-color: #27ae60; color: white; padding: 4px 12px; }")
        top_layout.addWidget(self._start_btn)

        self._stop_btn = QPushButton("停止采集")
        self._stop_btn.clicked.connect(self._stop_device)
        self._stop_btn.setStyleSheet("QPushButton { background-color: #c0392b; color: white; padding: 4px 12px; }")
        top_layout.addWidget(self._stop_btn)

        self._trigger_btn = QPushButton("手动采集一次")
        self._trigger_btn.clicked.connect(self._manual_trigger)
        top_layout.addWidget(self._trigger_btn)

        top_layout.addSpacing(16)
        top_layout.addWidget(QLabel("采集模式:"))
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["定时采集", "及采及入"])
        self._mode_combo.setMinimumWidth(100)
        self._mode_combo.currentTextChanged.connect(self._on_mode_changed)
        top_layout.addWidget(self._mode_combo)

        top_layout.addStretch()
        layout.addLayout(top_layout)

        info_group = QGroupBox("设备信息")
        info_layout = QGridLayout()
        self._info_labels = {}
        info_items = [
            ("设备ID", "device_id"), ("设备名称", "device_name"),
            ("设备类型", "device_type"), ("分组", "group"),
            ("协议类型", "protocol"), ("接口类型", "interface"),
            ("连接参数", "conn_param"),
        ]
        for i, (text, key) in enumerate(info_items):
            info_layout.addWidget(QLabel(f"{text}:"), i // 4 * 2, (i % 4) * 2)
            label = QLabel("--")
            label.setStyleSheet("font-weight: bold; color: #2c3e50;")
            info_layout.addWidget(label, i // 4 * 2, (i % 4) * 2 + 1)
            self._info_labels[key] = label
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        status_group = QGroupBox("运行状态")
        status_layout = QGridLayout()
        self._status_labels = {}
        labels_info = [
            ("运行状态", "runtime"), ("通信成功率", "comm_rate"),
            ("上传成功率", "upload_rate"), ("最后通信时间", "last_comm"),
            ("总采集次数", "total_count"), ("成功次数", "success_count"),
            ("失败次数", "fail_count"), ("采集点数", "points_count"),
            ("报警数", "alarm_count"), ("MQTT状态", "mqtt_state"),
        ]
        for i, (text, key) in enumerate(labels_info):
            status_layout.addWidget(QLabel(f"{text}:"), i // 5 * 2, (i % 5) * 2)
            label = QLabel("--")
            label.setStyleSheet("font-weight: bold; color: #2980b9;")
            status_layout.addWidget(label, i // 5 * 2, (i % 5) * 2 + 1)
            self._status_labels[key] = label
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        self._data_table = QTableWidget(0, 7)
        self._data_table.setHorizontalHeaderLabels(
            ["采集点名称", "描述", "当前值", "单位", "更新时间", "状态", "报警"]
        )
        header = self._data_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        header.resizeSection(0, 120)
        self._data_table.verticalHeader().setVisible(False)
        layout.addWidget(self._data_table, 1)

        alarm_group = QGroupBox("近期报警")
        alarm_layout = QVBoxLayout()
        self._alarm_label = QLabel("无报警")
        self._alarm_label.setWordWrap(True)
        self._alarm_label.setStyleSheet("color: #e74c3c; font-size: 12px;")
        self._alarm_clear_btn = QPushButton("清除报警记录")
        self._alarm_clear_btn.clicked.connect(self._clear_alarms)
        alarm_layout.addWidget(self._alarm_label)
        alarm_layout.addWidget(self._alarm_clear_btn)
        alarm_group.setLayout(alarm_layout)
        layout.addWidget(alarm_group)

    def _on_device_changed(self):
        if self._device_combo.signalsBlocked():
            return
        self._refresh_monitor()
        self._sync_mode_combo()

    def _sync_mode_combo(self):
        device_id = self._device_combo.currentData()
        if not device_id:
            return
        current_mode = collector_manager.get_device_mode(device_id)
        label = self._MODE_LABELS.get(current_mode, "定时采集")
        self._mode_combo.blockSignals(True)
        self._mode_combo.setCurrentText(label)
        self._mode_combo.blockSignals(False)

    def _on_mode_changed(self, text: str):
        device_id = self._device_combo.currentData()
        if not device_id or self._mode_combo.signalsBlocked():
            return
        mode_map = {"定时采集": "timer", "及采及入": "continuous"}
        mode = mode_map.get(text, "timer")
        collector_manager.switch_device_mode(device_id, mode)

    def _refresh_device_list(self):
        saved_id = self._device_combo.currentData()
        self._device_combo.blockSignals(True)
        try:
            self._device_combo.clear()
            self._device_combo.addItem("-- 请选择 --")
            restored_idx = 0
            for device_id in config_manager.devices:
                device = config_manager.devices[device_id]
                self._device_combo.addItem(f"{device.name} ({device_id})", device_id)
                if device_id == saved_id:
                    restored_idx = self._device_combo.count() - 1
            self._device_combo.setCurrentIndex(restored_idx)
        finally:
            self._device_combo.blockSignals(False)
        self._refresh_monitor()
        self._sync_mode_combo()

    def _refresh_monitor(self):
        device_id = self._device_combo.currentData()
        if not device_id:
            self._clear_display()
            return
        self._update_device_info(device_id)
        self._update_status(device_id)
        self._update_data_table(device_id)
        self._update_alarms()

    def _clear_display(self):
        for key in self._info_labels:
            self._info_labels[key].setText("--")
        for key in self._status_labels:
            self._status_labels[key].setText("--")
        self._data_table.setRowCount(0)
        self._alarm_label.setText("无报警")
        
    def _update_device_info(self, device_id: str):
        device = config_manager.get_device(device_id)
        if not device:
            return
        self._info_labels["device_id"].setText(device.device_id)
        self._info_labels["device_name"].setText(device.name)
        self._info_labels["device_type"].setText(device.device_type)
        self._info_labels["group"].setText(device.group)
        self._info_labels["protocol"].setText(device.protocol.protocol_type.upper())

        is_serial = device.protocol.protocol_type in ('modbus_rtu', 'custom')
        is_eth = device.protocol.protocol_type in ('modbus_tcp',)
        if is_serial:
            self._info_labels["interface"].setText(f"串口 {device.serial.port}")
            self._info_labels["conn_param"].setText(
                f"{device.serial.baudrate}/{device.serial.bytesize}"
                f"{device.serial.parity}{device.serial.stopbits}"
            )
        elif is_eth:
            self._info_labels["interface"].setText(f"以太网 ({device.ethernet.mode})")
            self._info_labels["conn_param"].setText(f"{device.ethernet.host}:{device.ethernet.port}")
        else:
            self._info_labels["interface"].setText("--")
            self._info_labels["conn_param"].setText("--")

    def _update_status(self, device_id: str):
        status = device_manager.get_device_status(device_id)
        from core.collector.collector import collector_manager
        collector_stats = collector_manager.get_device_stats(device_id)

        runtime = status.get("runtime_status", "offline")
        runtime_colors = {
            "collecting": "#27ae60", "online": "#2980b9",
            "offline": "#7f8c8d", "error": "#e74c3c", "paused": "#f39c12",
            "disabled": "#95a5a6"
        }
        self._status_labels["runtime"].setText(runtime)
        self._status_labels["runtime"].setStyleSheet(
            f"font-weight: bold; color: {runtime_colors.get(runtime, '#7f8c8d')};"
        )

        self._status_labels["comm_rate"].setText(f"{status.get('comm_success_rate', 0):.1f}%")
        self._status_labels["upload_rate"].setText(f"{status.get('upload_success_rate', 0):.1f}%")

        last_comm = status.get("last_comm_time", 0) or 0
        if last_comm > 0:
            self._status_labels["last_comm"].setText(
                time.strftime('%H:%M:%S', time.localtime(last_comm)))
        else:
            self._status_labels["last_comm"].setText("--")

        self._status_labels["total_count"].setText(str(collector_stats.get("total", 0)))
        self._status_labels["success_count"].setText(
            f"{collector_stats.get('success', 0)} ({status.get('comm_success_rate', 0):.1f}%")
        self._status_labels["fail_count"].setText(str(collector_stats.get("fail", 0)))

        device = config_manager.get_device(device_id)
        point_count = len(device.collect.points) if device else 0
        self._status_labels["points_count"].setText(str(point_count))

        mqtt_state = status.get("mqtt_state", "disconnected")
        mqtt_colors = {"connected": "#27ae60", "disconnected": "#7f8c8d", "connecting": "#f39c12"}
        self._status_labels["mqtt_state"].setText(mqtt_state)
        self._status_labels["mqtt_state"].setStyleSheet(
            f"font-weight: bold; color: {mqtt_colors.get(mqtt_state, '#7f8c8d')};"
        )

    def _update_data_table(self, device_id: str):
        device = config_manager.get_device(device_id)
        if not device:
            self._data_table.setRowCount(0)
            return

        latest = device_manager.get_device_latest_data(device_id)
        points = device.collect.points

        self._data_table.setRowCount(0)
        for point in points:
            row = self._data_table.rowCount()
            self._data_table.insertRow(row)

            name_item = QTableWidgetItem(point.name)
            if not point.enabled:
                name_item.setForeground(QColor("#bdc3c7"))
            self._data_table.setItem(row, 0, name_item)

            self._data_table.setItem(row, 1, QTableWidgetItem(point.description))

            live_data = latest.get(point.name)
            if live_data and live_data.success and live_data.value is not None:
                value_str = f"{live_data.value:.4f}" if isinstance(live_data.value, float) else str(live_data.value)
                value_item = QTableWidgetItem(value_str)
                if live_data.is_alarm:
                    value_item.setBackground(QColor("#e74c3c"))
                    value_item.setForeground(QColor("white"))
                self._data_table.setItem(row, 2, value_item)

                self._data_table.setItem(row, 3, QTableWidgetItem(point.unit or live_data.unit))

                ts = time.strftime('%H:%M:%S', time.localtime(live_data.timestamp))
                self._data_table.setItem(row, 4, QTableWidgetItem(ts))

                status_item = QTableWidgetItem("正常")
                status_item.setForeground(QColor("#27ae60"))
                self._data_table.setItem(row, 5, status_item)

                alarm_text = "⚠ 报警" if live_data.is_alarm else ""
                alarm_item = QTableWidgetItem(alarm_text)
                if live_data.is_alarm:
                    alarm_item.setForeground(QColor("#e74c3c"))
                self._data_table.setItem(row, 6, alarm_item)
            elif live_data and not live_data.success:
                self._data_table.setItem(row, 2, QTableWidgetItem("采集失败"))
                value_item = self._data_table.item(row, 2)
                if value_item:
                    value_item.setForeground(QColor("#e74c3c"))
                self._data_table.setItem(row, 3, QTableWidgetItem(point.unit))
                self._data_table.setItem(row, 4, QTableWidgetItem("--"))
                status_item = QTableWidgetItem("失败")
                status_item.setForeground(QColor("#e74c3c"))
                self._data_table.setItem(row, 5, status_item)
                self._data_table.setItem(row, 6, QTableWidgetItem(""))
            else:
                placeholder = QTableWidgetItem("等待采集")
                placeholder.setForeground(QColor("#bdc3c7"))
                self._data_table.setItem(row, 2, placeholder)
                self._data_table.setItem(row, 3, QTableWidgetItem(point.unit))
                self._data_table.setItem(row, 4, QTableWidgetItem("--"))
                status_text = "已配置" if point.enabled else "已禁用"
                status_item = QTableWidgetItem(status_text)
                if not point.enabled:
                    status_item.setForeground(QColor("#bdc3c7"))
                else:
                    status_item.setForeground(QColor("#f39c12"))
                self._data_table.setItem(row, 5, status_item)
                self._data_table.setItem(row, 6, QTableWidgetItem(""))

    def _update_alarms(self):
        alarms = device_manager.get_alarms(20)
        if alarms:
            lines = []
            for a in alarms[-15:]:
                ts = time.strftime('%H:%M:%S', time.localtime(a['timestamp']))
                alarm_type = "上限" if a.get('type') == 'high' else "下限"
                lines.append(
                    f"[{ts}] {a['point_name']} = {a['value']}{a.get('unit', '')}  "
                    f"触发{alarm_type}报警(阈值: {a.get('threshold', '--')})"
                )
            self._alarm_label.setText("\n".join(lines))
            self._status_labels["alarm_count"].setText(str(len(alarms)))
        else:
            self._alarm_label.setText("无报警")
            self._status_labels["alarm_count"].setText("0")

    def _start_device(self):
        device_id = self._device_combo.currentData()
        if not device_id:
            QMessageBox.warning(self, "提示", "请先选择设备")
            return
        if device_manager.start_device(device_id):
            QMessageBox.information(self, "成功", f"设备 {device_id} 已启动")
        else:
            QMessageBox.warning(self, "失败", "设备启动失败，请检查配置")
        self._refresh_monitor()

    def _stop_device(self):
        device_id = self._device_combo.currentData()
        if not device_id:
            QMessageBox.warning(self, "提示", "请先选择设备")
            return
        device_manager.stop_device(device_id)
        QMessageBox.information(self, "成功", f"设备 {device_id} 已停止")
        self._refresh_monitor()

    def _manual_trigger(self):
        device_id = self._device_combo.currentData()
        if not device_id:
            QMessageBox.warning(self, "提示", "请先选择设备")
            return
        results = device_manager.trigger_device_once(device_id)
        QMessageBox.information(self, "采集结果",
                                f"成功: {sum(1 for r in results if r.success)} / "
                                f"失败: {sum(1 for r in results if not r.success)} / "
                                f"总计: {len(results)}")
        self._refresh_monitor()

    def _clear_alarms(self):
        device_manager.clear_alarms()
        self._alarm_label.setText("无报警")
        self._status_labels["alarm_count"].setText("0")