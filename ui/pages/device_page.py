import json
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                              QTableWidget, QTableWidgetItem, QHeaderView, QDialog,
                              QFormLayout, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
                              QCheckBox, QGroupBox, QFileDialog, QMessageBox, QTabWidget,
                              QSplitter, QTextEdit, QListWidget)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont

from config.config_manager import config_manager, DeviceConfig, SerialConfig, EthernetConfig, \
    ProtocolConfig, CollectConfig, CollectPoint, MqttConfig, DataFilterConfig, DataAggregateConfig
from device.device_manager import device_manager, DeviceRuntimeStatus
from core.communication.serial_client import SerialClient
from core.security.auth import auth_manager


def _parse_addr(text: str) -> int:
    text = text.strip()
    if not text:
        return 0
    if ' ' in text:
        text = text.split()[0]
    if text.lower().startswith('0x'):
        return int(text, 16)
    return int(text)


class DevicePage(QWidget):
    def __init__(self):
        super().__init__()
        self._init_ui()
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh_status)
        self._refresh_timer.start(2000)
        self._current_device_id = None
        self._refresh_device_list()

    def _require_permission(self, permission: str) -> bool:
        if auth_manager.has_permission(permission):
            return True
        QMessageBox.warning(self, "无权限", "当前用户没有执行此操作的权限")
        return False

    def _init_ui(self):
        layout = QHBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(5, 5, 5, 5)

        btn_layout = QHBoxLayout()
        self._add_btn = QPushButton("添加设备")
        self._add_btn.clicked.connect(self._add_device)
        self._remove_btn = QPushButton("删除设备")
        self._remove_btn.clicked.connect(self._remove_device)
        self._import_btn = QPushButton("导入")
        self._import_btn.clicked.connect(self._import_config)
        self._export_btn = QPushButton("导出")
        self._export_btn.clicked.connect(self._export_config)
        btn_layout.addWidget(self._add_btn)
        btn_layout.addWidget(self._remove_btn)
        btn_layout.addWidget(self._import_btn)
        btn_layout.addWidget(self._export_btn)
        left_layout.addLayout(btn_layout)

        self._group_filter = QComboBox()
        self._group_filter.addItem("全部")
        self._group_filter.currentTextChanged.connect(self._refresh_device_list)
        left_layout.addWidget(self._group_filter)

        self._device_list = QListWidget()
        self._device_list.currentRowChanged.connect(self._on_device_selected)
        left_layout.addWidget(self._device_list, 1)

        self._start_btn = QPushButton("启动选中设备")
        self._start_btn.clicked.connect(self._start_device)
        self._stop_btn = QPushButton("停止选中设备")
        self._stop_btn.clicked.connect(self._stop_device)
        left_layout.addWidget(self._start_btn)
        left_layout.addWidget(self._stop_btn)

        self._force_upload_btn = QPushButton("全量上传MQTT")
        self._force_upload_btn.clicked.connect(self._force_upload_all)
        self._force_upload_btn.setStyleSheet(
            "QPushButton { background-color: #e67e22; color: white; padding: 6px 12px; }"
        )
        left_layout.addWidget(self._force_upload_btn)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5, 5, 5, 5)

        self._status_label = QLabel("请选择一个设备")
        self._status_label.setStyleSheet("font-size: 14px; font-weight: bold; padding: 10px;")
        right_layout.addWidget(self._status_label)

        self._tab_widget = QTabWidget()
        self._tab_widget.addTab(self._create_basic_tab(), "基本信息")
        self._tab_widget.addTab(self._create_comm_tab(), "通信配置")
        self._tab_widget.addTab(self._create_collect_tab(), "采集配置")
        self._tab_widget.addTab(self._create_mqtt_tab(), "MQTT配置")
        self._tab_widget.addTab(self._create_points_tab(), "采集点配置")
        right_layout.addWidget(self._tab_widget, 1)

        self._save_btn = QPushButton("保存配置")
        self._save_btn.clicked.connect(self._save_config)
        self._save_btn.setStyleSheet("QPushButton { background-color: #27ae60; color: white; padding: 8px 20px; }")
        right_layout.addWidget(self._save_btn)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([300, 700])
        layout.addWidget(splitter)

    def _create_basic_tab(self):
        widget = QWidget()
        layout = QFormLayout(widget)
        self._edit_device_id = QLineEdit()
        self._edit_device_id.setPlaceholderText("设备唯一标识")
        self._edit_name = QLineEdit()
        self._edit_name.setPlaceholderText("设备名称")
        self._edit_desc = QLineEdit()
        self._edit_desc.setPlaceholderText("设备描述")
        self._edit_group = QLineEdit()
        self._edit_group.setPlaceholderText("分组（如：车间1/产线A）")
        self._edit_group.setText("default")
        self._combo_type = QComboBox()
        self._combo_type.addItems(["通用设备", "PLC", "传感器", "执行器", "变频器", "电表"])
        self._check_enabled = QCheckBox("启用设备")
        self._check_enabled.setChecked(True)
        layout.addRow("设备ID:", self._edit_device_id)
        layout.addRow("设备名称:", self._edit_name)
        layout.addRow("描述:", self._edit_desc)
        layout.addRow("分组:", self._edit_group)
        layout.addRow("设备类型:", self._combo_type)
        layout.addRow("", self._check_enabled)
        return widget

    def _create_comm_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        proto_group = QGroupBox("协议选择")
        proto_layout = QFormLayout()
        self._combo_proto = QComboBox()
        self._combo_proto.addItems(["modbus_rtu", "modbus_tcp", "modbus_rtu_over_tcp", "custom"])
        self._spin_slave = QSpinBox()
        self._spin_slave.setRange(1, 247)
        self._spin_slave.setValue(1)
        proto_layout.addRow("协议类型:", self._combo_proto)
        proto_layout.addRow("从站ID:", self._spin_slave)
        proto_group.setLayout(proto_layout)
        layout.addWidget(proto_group)

        serial_group = QGroupBox("串口配置")
        serial_layout = QFormLayout()
        self._combo_port = QComboBox()
        self._combo_port.setEditable(True)
        self._refresh_ports_btn = QPushButton("刷新")
        self._refresh_ports_btn.clicked.connect(self._refresh_ports)
        port_layout = QHBoxLayout()
        port_layout.addWidget(self._combo_port)
        port_layout.addWidget(self._refresh_ports_btn)
        serial_layout.addRow("串口号:", port_layout)
        self._combo_baudrate = QComboBox()
        self._combo_baudrate.addItems(["300", "1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"])
        self._combo_baudrate.setCurrentText("9600")
        self._combo_bits = QComboBox()
        self._combo_bits.addItems(["5", "6", "7", "8"])
        self._combo_bits.setCurrentText("8")
        self._combo_parity = QComboBox()
        self._combo_parity.addItems(["N", "E", "O", "M", "S"])
        self._combo_stopbits = QComboBox()
        self._combo_stopbits.addItems(["1", "1.5", "2"])
        serial_layout.addRow("波特率:", self._combo_baudrate)
        serial_layout.addRow("数据位:", self._combo_bits)
        serial_layout.addRow("校验位:", self._combo_parity)
        serial_layout.addRow("停止位:", self._combo_stopbits)
        serial_group.setLayout(serial_layout)
        layout.addWidget(serial_group)

        eth_group = QGroupBox("以太网配置")
        eth_layout = QFormLayout()
        self._combo_eth_mode = QComboBox()
        self._combo_eth_mode.addItems(["tcp_client", "tcp_server", "udp"])
        self._edit_eth_host = QLineEdit("192.168.1.100")
        self._spin_eth_port = QSpinBox()
        self._spin_eth_port.setRange(1, 65535)
        self._spin_eth_port.setValue(502)
        eth_layout.addRow("工作模式:", self._combo_eth_mode)
        eth_layout.addRow("IP地址:", self._edit_eth_host)
        eth_layout.addRow("端口号:", self._spin_eth_port)
        eth_group.setLayout(eth_layout)
        layout.addWidget(eth_group)

        layout.addStretch()
        return widget

    def _create_collect_tab(self):
        widget = QWidget()
        layout = QFormLayout(widget)
        self._combo_collect_mode = QComboBox()
        self._combo_collect_mode.addItems(["定时采集(timer)", "触发采集(trigger)", "手动采集(manual)", "及采及入(continuous)"])
        self._mode_values = {
            "定时采集(timer)": "timer",
            "触发采集(trigger)": "trigger",
            "手动采集(manual)": "manual",
            "及采及入(continuous)": "continuous",
        }
        self._mode_labels = {v: k for k, v in self._mode_values.items()}
        self._spin_interval = QSpinBox()
        self._spin_interval.setRange(100, 3600000)
        self._spin_interval.setValue(100)
        self._spin_interval.setSuffix(" ms")
        self._spin_retry = QSpinBox()
        self._spin_retry.setRange(0, 10)
        self._spin_retry.setValue(3)
        self._spin_timeout = QSpinBox()
        self._spin_timeout.setRange(100, 60000)
        self._spin_timeout.setValue(500)
        self._spin_timeout.setSuffix(" ms")
        layout.addRow("采集模式:", self._combo_collect_mode)
        layout.addRow("采集间隔:", self._spin_interval)
        layout.addRow("重试次数:", self._spin_retry)
        layout.addRow("超时时间:", self._spin_timeout)
        return widget

    def _create_mqtt_tab(self):
        widget = QWidget()
        layout = QFormLayout(widget)
        self._edit_mqtt_host = QLineEdit("127.0.0.1")
        self._spin_mqtt_port = QSpinBox()
        self._spin_mqtt_port.setRange(1, 65535)
        self._spin_mqtt_port.setValue(1883)
        self._edit_mqtt_user = QLineEdit()
        self._edit_mqtt_pass = QLineEdit()
        self._edit_mqtt_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit_mqtt_topic = QLineEdit("factory/line1")
        self._combo_mqtt_qos = QComboBox()
        self._combo_mqtt_qos.addItems(["0", "1", "2"])
        self._combo_mqtt_qos.setCurrentText("1")
        layout.addRow("服务器地址:", self._edit_mqtt_host)
        layout.addRow("端口:", self._spin_mqtt_port)
        layout.addRow("用户名:", self._edit_mqtt_user)
        layout.addRow("密码:", self._edit_mqtt_pass)
        layout.addRow("主题前缀:", self._edit_mqtt_topic)
        layout.addRow("QoS:", self._combo_mqtt_qos)
        return widget

    def _create_points_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self._points_table = QTableWidget(0, 14)
        self._points_table.setHorizontalHeaderLabels(
            ["名称", "描述", "寄存器类型", "地址", "数据类型", "字节序",
             "倍率", "偏移", "单位", "报警上限", "报警下限", "读取数", "启用", "从机地址"]
        )
        header = self._points_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.resizeSection(0, 200)
        header.resizeSection(1, 120)
        header.resizeSection(2, 110)
        header.resizeSection(3, 80)
        header.resizeSection(4, 100)
        header.resizeSection(5, 80)
        header.resizeSection(6, 60)
        header.resizeSection(7, 60)
        header.resizeSection(8, 60)
        header.resizeSection(9, 80)
        header.resizeSection(10, 80)
        header.resizeSection(11, 60)
        header.resizeSection(12, 50)
        header.resizeSection(13, 70)
        layout.addWidget(self._points_table)

        btn_layout = QHBoxLayout()
        add_pt_btn = QPushButton("添加采集点")
        add_pt_btn.clicked.connect(self._add_point)
        del_pt_btn = QPushButton("删除选中")
        del_pt_btn.clicked.connect(self._delete_point)
        import_pt_btn = QPushButton("导入采集点")
        import_pt_btn.clicked.connect(self._import_points)
        export_pt_btn = QPushButton("导出采集点")
        export_pt_btn.clicked.connect(self._export_points)
        btn_layout.addWidget(add_pt_btn)
        btn_layout.addWidget(del_pt_btn)
        btn_layout.addWidget(import_pt_btn)
        btn_layout.addWidget(export_pt_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        return widget

    def _refresh_device_list(self):
        saved_id = self._current_device_id
        saved_group = self._group_filter.currentText()
        self._group_filter.blockSignals(True)
        self._device_list.blockSignals(True)
        try:
            self._device_list.clear()
            self._group_filter.clear()
            self._group_filter.addItem("全部")
            groups = config_manager.get_all_groups()
            for g in groups:
                self._group_filter.addItem(g)
        finally:
            self._group_filter.blockSignals(False)
            self._device_list.blockSignals(False)
        if saved_group:
            self._group_filter.blockSignals(True)
            idx = self._group_filter.findText(saved_group)
            if idx >= 0:
                self._group_filter.setCurrentIndex(idx)
            self._group_filter.blockSignals(False)
        selected_group = self._group_filter.currentText()
        restored_row = -1
        for device_id in config_manager.devices:
            device = config_manager.devices[device_id]
            if selected_group != "全部" and device.group != selected_group:
                continue
            status = device_manager._runtime_status.get(device_id, DeviceRuntimeStatus.OFFLINE)
            icon = "●" if status == DeviceRuntimeStatus.COLLECTING else "○"
            self._device_list.addItem(f"{icon} {device.name} ({device_id})")
            if device_id == saved_id:
                restored_row = self._device_list.count() - 1
        if restored_row >= 0:
            self._device_list.blockSignals(True)
            self._device_list.setCurrentRow(restored_row)
            self._device_list.blockSignals(False)
            self._current_device_id = saved_id

    def _refresh_ports(self):
        self._combo_port.clear()
        ports = SerialClient.scan_ports()
        for port_info in ports:
            self._combo_port.addItem(port_info['device'], port_info['device'])
        if not ports:
            self._combo_port.addItem("COM1")

    def _on_device_selected(self):
        self._current_device_id = None
        if not self._device_list.currentItem():
            return
        item_text = self._device_list.currentItem().text()
        for device_id in config_manager.devices:
            if device_id in item_text:
                self._current_device_id = device_id
                self._load_device_config(device_id)
                break

    def _load_device_config(self, device_id: str):
        device = config_manager.get_device(device_id)
        if not device:
            return
        self._edit_device_id.setText(device.device_id)
        self._edit_device_id.setReadOnly(True)
        self._edit_name.setText(device.name)
        self._edit_desc.setText(device.description)
        self._edit_group.setText(device.group)
        self._combo_type.setCurrentText(device.device_type)
        self._check_enabled.setChecked(device.enabled)
        self._combo_proto.setCurrentText(device.protocol.protocol_type)
        self._spin_slave.setValue(device.protocol.slave_id)
        self._combo_port.setCurrentText(device.serial.port)
        self._combo_baudrate.setCurrentText(str(device.serial.baudrate))
        self._combo_bits.setCurrentText(str(device.serial.bytesize))
        self._combo_parity.setCurrentText(device.serial.parity)
        self._combo_stopbits.setCurrentText(str(device.serial.stopbits))
        self._combo_eth_mode.setCurrentText(device.ethernet.mode)
        self._edit_eth_host.setText(device.ethernet.host)
        self._spin_eth_port.setValue(device.ethernet.port)
        self._combo_collect_mode.setCurrentText(self._mode_labels.get(device.collect.mode, "定时采集(timer)"))
        self._spin_interval.setValue(device.collect.interval_ms)
        self._spin_retry.setValue(device.collect.retry_times)
        self._spin_timeout.setValue(device.collect.timeout_ms)
        self._edit_mqtt_host.setText(device.mqtt.host)
        self._spin_mqtt_port.setValue(device.mqtt.port)
        self._edit_mqtt_user.setText(device.mqtt.username)
        self._edit_mqtt_pass.setText(device.mqtt.password)
        self._edit_mqtt_topic.setText(device.mqtt.topic_prefix)
        self._combo_mqtt_qos.setCurrentText(str(device.mqtt.qos))
        self._load_points_table(device)
        status = device_manager._runtime_status.get(device_id, DeviceRuntimeStatus.OFFLINE)
        status_text = {
            DeviceRuntimeStatus.COLLECTING: "采集中",
            DeviceRuntimeStatus.ONLINE: "在线",
            DeviceRuntimeStatus.OFFLINE: "离线",
            DeviceRuntimeStatus.ERROR: "异常",
            DeviceRuntimeStatus.DISABLED: "已禁用"
        }.get(status, "未知")
        self._status_label.setText(f"设备: {device.name} (ID: {device_id}) - 状态: {status_text}")

    def _load_points_table(self, device):
        self._points_table.setRowCount(0)
        register_types = ['coil', 'discrete_input', 'input_register', 'holding_register']
        data_types = ['int8', 'uint8', 'int16', 'uint16', 'int16_ab', 'uint16_ab',
                      'int32', 'uint32', 'float32', 'float32_abcd', 'float32_cdab',
                      'int64', 'uint64', 'float64', 'bool', 'bit', 'string', 'hex_string']
        byte_orders = ['big_endian', 'little_endian', 'big_endian_swap']
        for point in device.collect.points:
            row = self._points_table.rowCount()
            self._points_table.insertRow(row)
            self._points_table.setItem(row, 0, QTableWidgetItem(point.name))
            self._points_table.setItem(row, 1, QTableWidgetItem(point.description))

            reg_combo = QComboBox()
            reg_combo.addItems(register_types)
            reg_combo.setCurrentText(point.register_type)
            self._points_table.setCellWidget(row, 2, reg_combo)

            addr_item = QTableWidgetItem()
            addr_item.setData(Qt.ItemDataRole.DisplayRole, f"{point.register_address} (0x{point.register_address:X})")
            self._points_table.setItem(row, 3, addr_item)

            dtype_combo = QComboBox()
            dtype_combo.addItems(data_types)
            dtype_combo.setCurrentText(point.data_type)
            self._points_table.setCellWidget(row, 4, dtype_combo)

            order_combo = QComboBox()
            order_combo.addItems(byte_orders)
            order_combo.setCurrentText(point.byte_order)
            self._points_table.setCellWidget(row, 5, order_combo)

            self._points_table.setItem(row, 6, QTableWidgetItem(str(point.scale)))
            self._points_table.setItem(row, 7, QTableWidgetItem(str(point.offset)))
            self._points_table.setItem(row, 8, QTableWidgetItem(point.unit))

            ah_text = str(point.alarm_high) if point.alarm_high is not None else ""
            self._points_table.setItem(row, 9, QTableWidgetItem(ah_text))
            al_text = str(point.alarm_low) if point.alarm_low is not None else ""
            self._points_table.setItem(row, 10, QTableWidgetItem(al_text))
            self._points_table.setItem(row, 11, QTableWidgetItem(str(point.read_count)))

            enabled_item = QTableWidgetItem("是" if point.enabled else "否")
            enabled_item.setFlags(enabled_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._points_table.setItem(row, 12, enabled_item)

            slave_item = QTableWidgetItem(str(point.slave_id) if point.slave_id else "")
            self._points_table.setItem(row, 13, slave_item)
            self._points_table.cellDoubleClicked.connect(self._toggle_point_enabled)

    def _add_device(self):
        if not self._require_permission("modify_config"):
            return
        existing_ids = list(config_manager.devices.keys())
        max_num = 0
        for did in existing_ids:
            try:
                num = int(did.split("_")[-1])
                max_num = max(max_num, num)
            except ValueError:
                pass
        device_id = f"device_{max_num + 1:03d}"
        device = DeviceConfig(device_id=device_id, name="新设备")
        if device_manager.add_device(device):
            self._current_device_id = device_id
            self._refresh_device_list()
            self._load_device_config(device_id)
            QMessageBox.information(self, "成功", f"设备 {device_id} 已添加")
        else:
            QMessageBox.warning(self, "错误", f"设备 {device_id} 添加失败，可能已存在")

    def _remove_device(self):
        if not self._require_permission("modify_config"):
            return
        if not self._current_device_id:
            QMessageBox.warning(self, "提示", "请先选择要删除的设备")
            return
        reply = QMessageBox.question(self, "确认删除",
                                       f"确定要删除设备 {self._current_device_id} 吗？",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            if device_manager.remove_device(self._current_device_id):
                self._current_device_id = None
                self._refresh_device_list()
            else:
                QMessageBox.warning(self, "错误", "删除设备失败")

    def _start_device(self):
        if self._current_device_id:
            if device_manager.start_device(self._current_device_id):
                QMessageBox.information(self, "成功", "设备已启动")
            else:
                QMessageBox.warning(self, "失败", "设备启动失败，请检查配置")
            self._refresh_device_list()

    def _stop_device(self):
        if self._current_device_id:
            device_manager.stop_device(self._current_device_id)
            self._refresh_device_list()

    def _force_upload_all(self):
        if not self._current_device_id:
            QMessageBox.warning(self, "提示", "请先选择一个设备")
            return
        success = device_manager.force_upload_all_points(self._current_device_id)
        if success:
            QMessageBox.information(self, "成功", "全量上传MQTT成功")
        else:
            QMessageBox.warning(self, "失败", "全量上传MQTT失败，请检查MQTT连接")

    def _save_config(self):
        if not self._require_permission("modify_config"):
            return
        if not self._current_device_id:
            QMessageBox.warning(self, "提示", "请先选择一个设备")
            return
        device = config_manager.get_device(self._current_device_id)
        if not device:
            return
        device.name = self._edit_name.text()
        device.description = self._edit_desc.text()
        device.group = self._edit_group.text()
        device.device_type = self._combo_type.currentText()
        device.enabled = self._check_enabled.isChecked()
        device.protocol.protocol_type = self._combo_proto.currentText()
        device.protocol.slave_id = self._spin_slave.value()
        device.serial.port = self._combo_port.currentText()
        device.serial.baudrate = int(self._combo_baudrate.currentText())
        device.serial.bytesize = int(self._combo_bits.currentText())
        device.serial.parity = self._combo_parity.currentText()
        device.serial.stopbits = float(self._combo_stopbits.currentText())
        device.ethernet.mode = self._combo_eth_mode.currentText()
        device.ethernet.host = self._edit_eth_host.text()
        device.ethernet.port = self._spin_eth_port.value()
        device.collect.mode = self._mode_values.get(self._combo_collect_mode.currentText(), "timer")
        device.collect.interval_ms = self._spin_interval.value()
        device.collect.retry_times = self._spin_retry.value()
        device.collect.timeout_ms = self._spin_timeout.value()
        device.mqtt.host = self._edit_mqtt_host.text()
        device.mqtt.port = self._spin_mqtt_port.value()
        device.mqtt.username = self._edit_mqtt_user.text()
        device.mqtt.password = self._edit_mqtt_pass.text()
        device.mqtt.topic_prefix = self._edit_mqtt_topic.text()
        device.mqtt.qos = int(self._combo_mqtt_qos.currentText())

        device.collect.points = []
        for row in range(self._points_table.rowCount()):
            name = self._points_table.item(row, 0).text() if self._points_table.item(row, 0) else ""
            desc = self._points_table.item(row, 1).text() if self._points_table.item(row, 1) else ""

            reg_widget = self._points_table.cellWidget(row, 2)
            reg_type = reg_widget.currentText() if isinstance(reg_widget, QComboBox) else "holding_register"

            addr_text = self._points_table.item(row, 3).text() if self._points_table.item(row, 3) else "0"
            try:
                addr = _parse_addr(addr_text)
            except ValueError:
                addr = 0

            dtype_widget = self._points_table.cellWidget(row, 4)
            data_type = dtype_widget.currentText() if isinstance(dtype_widget, QComboBox) else "uint16"

            order_widget = self._points_table.cellWidget(row, 5)
            byte_order = order_widget.currentText() if isinstance(order_widget, QComboBox) else "big_endian"

            try:
                scale = float(self._points_table.item(row, 6).text()) if self._points_table.item(row, 6) else 1.0
            except ValueError:
                scale = 1.0
            try:
                offset = float(self._points_table.item(row, 7).text()) if self._points_table.item(row, 7) else 0.0
            except ValueError:
                offset = 0.0

            unit = self._points_table.item(row, 8).text() if self._points_table.item(row, 8) else ""

            ah_text = self._points_table.item(row, 9).text() if self._points_table.item(row, 9) else ""
            alarm_high = float(ah_text) if ah_text.strip() else None
            al_text = self._points_table.item(row, 10).text() if self._points_table.item(row, 10) else ""
            alarm_low = float(al_text) if al_text.strip() else None

            rc_text = self._points_table.item(row, 11).text() if self._points_table.item(row, 11) else "0"
            try:
                read_count = int(rc_text)
            except ValueError:
                read_count = 0

            enabled_item = self._points_table.item(row, 12)
            enabled = True
            if enabled_item:
                enabled = enabled_item.text() == "是"

            slave_text = self._points_table.item(row, 13).text() if self._points_table.item(row, 13) else "0"
            try:
                slave_id = _parse_addr(slave_text)
            except ValueError:
                slave_id = 0

            point = CollectPoint(
                name=name, description=desc, register_type=reg_type,
                register_address=addr, data_type=data_type, byte_order=byte_order,
                scale=scale, offset=offset, unit=unit,
                alarm_high=alarm_high, alarm_low=alarm_low, read_count=read_count,
                enabled=enabled, slave_id=slave_id
            )
            device.collect.points.append(point)

        if device_manager.update_device(device):
            self._refresh_device_list()
            QMessageBox.information(self, "成功", "设备配置已保存")
        else:
            QMessageBox.warning(self, "失败", "设备配置保存失败")

    def _add_point(self):
        if not self._require_permission("modify_config"):
            return
        row = self._points_table.rowCount()
        self._points_table.insertRow(row)
        self._points_table.setItem(row, 0, QTableWidgetItem(f"point_{row + 1}"))
        self._points_table.setItem(row, 1, QTableWidgetItem(""))

        reg_combo = QComboBox()
        reg_combo.addItems(['coil', 'discrete_input', 'input_register', 'holding_register'])
        self._points_table.setCellWidget(row, 2, reg_combo)

        addr_item = QTableWidgetItem()
        addr_item.setData(Qt.ItemDataRole.DisplayRole, f"{row} (0x{row:X})")
        self._points_table.setItem(row, 3, addr_item)

        dtype_combo = QComboBox()
        dtype_combo.addItems(['int8', 'uint8', 'int16', 'uint16', 'int16_ab', 'uint16_ab',
                              'int32', 'uint32', 'float32', 'float32_abcd', 'float32_cdab',
                              'int64', 'uint64', 'float64', 'bool', 'bit', 'string', 'hex_string'])
        self._points_table.setCellWidget(row, 4, dtype_combo)

        order_combo = QComboBox()
        order_combo.addItems(['big_endian', 'little_endian', 'big_endian_swap'])
        self._points_table.setCellWidget(row, 5, order_combo)

        self._points_table.setItem(row, 6, QTableWidgetItem("1.0"))
        self._points_table.setItem(row, 7, QTableWidgetItem("0.0"))
        self._points_table.setItem(row, 8, QTableWidgetItem(""))
        self._points_table.setItem(row, 9, QTableWidgetItem(""))
        self._points_table.setItem(row, 10, QTableWidgetItem(""))
        self._points_table.setItem(row, 11, QTableWidgetItem("0"))
        enabled_item = QTableWidgetItem("是")
        enabled_item.setFlags(enabled_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._points_table.setItem(row, 12, enabled_item)
        self._points_table.setItem(row, 13, QTableWidgetItem(""))

    def _toggle_point_enabled(self, row, col):
        if not self._require_permission("modify_config"):
            self._load_device_config(self._current_device_id)
            return
        if col != 12:
            return
        item = self._points_table.item(row, col)
        if item:
            item.setText("否" if item.text() == "是" else "是")

    def _delete_point(self):
        if not self._require_permission("modify_config"):
            return
        current_row = self._points_table.currentRow()
        if current_row >= 0:
            self._points_table.removeRow(current_row)

    def _import_points(self):
        if not self._require_permission("modify_config"):
            return
        filepath, _ = QFileDialog.getOpenFileName(self, "导入采集点", "", "JSON文件 (*.json)")
        if filepath:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    points_data = json.load(f)
                register_types = ['coil', 'discrete_input', 'input_register', 'holding_register']
                data_types = ['int8', 'uint8', 'int16', 'uint16', 'int16_ab', 'uint16_ab',
                              'int32', 'uint32', 'float32', 'float32_abcd', 'float32_cdab',
                              'int64', 'uint64', 'float64', 'bool', 'bit', 'string', 'hex_string']
                byte_orders = ['big_endian', 'little_endian', 'big_endian_swap']
                for pt in points_data:
                    row = self._points_table.rowCount()
                    self._points_table.insertRow(row)
                    self._points_table.setItem(row, 0, QTableWidgetItem(pt.get('name', '')))
                    self._points_table.setItem(row, 1, QTableWidgetItem(pt.get('description', '')))

                    reg_combo = QComboBox()
                    reg_combo.addItems(register_types)
                    reg_combo.setCurrentText(pt.get('register_type', 'holding_register'))
                    self._points_table.setCellWidget(row, 2, reg_combo)

                    addr_item = QTableWidgetItem()
                    addr_item.setData(Qt.ItemDataRole.DisplayRole, f"{pt.get('register_address', 0)} (0x{pt.get('register_address', 0):X})")
                    self._points_table.setItem(row, 3, addr_item)

                    dtype_combo = QComboBox()
                    dtype_combo.addItems(data_types)
                    dtype_combo.setCurrentText(pt.get('data_type', 'uint16'))
                    self._points_table.setCellWidget(row, 4, dtype_combo)

                    order_combo = QComboBox()
                    order_combo.addItems(byte_orders)
                    order_combo.setCurrentText(pt.get('byte_order', 'big_endian'))
                    self._points_table.setCellWidget(row, 5, order_combo)

                    self._points_table.setItem(row, 6, QTableWidgetItem(str(pt.get('scale', 1.0))))
                    self._points_table.setItem(row, 7, QTableWidgetItem(str(pt.get('offset', 0.0))))
                    self._points_table.setItem(row, 8, QTableWidgetItem(pt.get('unit', '')))
                    self._points_table.setItem(row, 9, QTableWidgetItem(str(pt.get('alarm_high', ''))))
                    self._points_table.setItem(row, 10, QTableWidgetItem(str(pt.get('alarm_low', ''))))
                    self._points_table.setItem(row, 11, QTableWidgetItem(str(pt.get('read_count', 0))))
                    enabled_item = QTableWidgetItem("是" if pt.get('enabled', True) else "否")
                    enabled_item.setFlags(enabled_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self._points_table.setItem(row, 12, enabled_item)
                    self._points_table.setItem(row, 13, QTableWidgetItem(str(pt.get('slave_id', ''))))
                QMessageBox.information(self, "成功", f"已导入 {len(points_data)} 个采集点")
            except Exception as e:
                QMessageBox.warning(self, "错误", f"导入失败: {e}")

    def _export_points(self):
        filepath, _ = QFileDialog.getSaveFileName(self, "导出采集点", "points.json", "JSON文件 (*.json)")
        if filepath:
            points = []
            for row in range(self._points_table.rowCount()):
                reg_widget = self._points_table.cellWidget(row, 2)
                reg_type = reg_widget.currentText() if isinstance(reg_widget, QComboBox) else "holding_register"

                addr_text = self._points_table.item(row, 3).text() if self._points_table.item(row, 3) else "0"
                try:
                    addr = _parse_addr(addr_text)
                except ValueError:
                    addr = 0

                dtype_widget = self._points_table.cellWidget(row, 4)
                data_type = dtype_widget.currentText() if isinstance(dtype_widget, QComboBox) else "uint16"

                order_widget = self._points_table.cellWidget(row, 5)
                byte_order = order_widget.currentText() if isinstance(order_widget, QComboBox) else "big_endian"

                try:
                    scale = float(self._points_table.item(row, 6).text()) if self._points_table.item(row, 6) else 1.0
                except ValueError:
                    scale = 1.0
                try:
                    offset = float(self._points_table.item(row, 7).text()) if self._points_table.item(row, 7) else 0.0
                except ValueError:
                    offset = 0.0

                unit = self._points_table.item(row, 8).text() if self._points_table.item(row, 8) else ""
                ah_text = self._points_table.item(row, 9).text() if self._points_table.item(row, 9) else ""
                al_text = self._points_table.item(row, 10).text() if self._points_table.item(row, 10) else ""
                rc_text = self._points_table.item(row, 11).text() if self._points_table.item(row, 11) else "0"
                enabled_item = self._points_table.item(row, 12)
                enabled = enabled_item.text() == "是" if enabled_item else True

                slave_text = self._points_table.item(row, 13).text() if self._points_table.item(row, 13) else "0"
                try:
                    slave_id = _parse_addr(slave_text)
                except ValueError:
                    slave_id = 0

                pt = {
                    'name': self._points_table.item(row, 0).text() if self._points_table.item(row, 0) else "",
                    'description': self._points_table.item(row, 1).text() if self._points_table.item(row, 1) else "",
                    'register_type': reg_type,
                    'register_address': addr,
                    'data_type': data_type,
                    'byte_order': byte_order,
                    'scale': scale,
                    'offset': offset,
                    'unit': unit,
                    'alarm_high': float(ah_text) if ah_text.strip() else None,
                    'alarm_low': float(al_text) if al_text.strip() else None,
                    'read_count': int(rc_text) if rc_text.strip() else 0,
                    'enabled': enabled,
                    'slave_id': slave_id
                }
                points.append(pt)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(points, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "成功", f"已导出 {len(points)} 个采集点")

    def _import_config(self):
        if not self._require_permission("modify_config"):
            return
        filepath, _ = QFileDialog.getOpenFileName(self, "导入设备配置", "", "JSON文件 (*.json)")
        if filepath:
            try:
                device = config_manager.import_device_template(filepath)
                if device:
                    device_manager.add_device(device)
                    self._refresh_device_list()
                    QMessageBox.information(self, "成功", f"设备 {device.device_id} 已导入")
            except Exception as e:
                QMessageBox.warning(self, "错误", f"导入失败: {e}")

    def _export_config(self):
        if not self._current_device_id:
            QMessageBox.warning(self, "提示", "请先选择一个设备")
            return
        filepath, _ = QFileDialog.getSaveFileName(self, f"导出设备配置", f"{self._current_device_id}.json",
                                                    "JSON文件 (*.json)")
        if filepath:
            config_manager.export_device_template(self._current_device_id, filepath)
            QMessageBox.information(self, "成功", "设备配置已导出")

    def _refresh_status(self):
        if self._current_device_id and self._current_device_id in config_manager.devices:
            device = config_manager.devices[self._current_device_id]
            status = device_manager._runtime_status.get(
                self._current_device_id, DeviceRuntimeStatus.OFFLINE)
            status_text = {
                DeviceRuntimeStatus.COLLECTING: "采集中",
                DeviceRuntimeStatus.ONLINE: "在线",
                DeviceRuntimeStatus.OFFLINE: "离线",
                DeviceRuntimeStatus.ERROR: "异常",
                DeviceRuntimeStatus.DISABLED: "已禁用"
            }.get(status, "未知")
            self._status_label.setText(
                f"设备: {device.name} (ID: {self._current_device_id}) - 状态: {status_text}")
        for i in range(self._device_list.count()):
            item = self._device_list.item(i)
            if not item:
                continue
            text = item.text()
            for device_id in config_manager.devices:
                if device_id in text:
                    status = device_manager._runtime_status.get(
                        device_id, DeviceRuntimeStatus.OFFLINE)
                    icon = "●" if status == DeviceRuntimeStatus.COLLECTING else "○"
                    new_text = f"{icon}{text[1:]}"
                    if new_text != text:
                        item.setText(new_text)
                    break
