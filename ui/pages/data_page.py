import time
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                              QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
                              QDateTimeEdit, QSpinBox, QFileDialog, QMessageBox, QLineEdit)
from PyQt6.QtCore import Qt, QDateTime
from PyQt6.QtGui import QColor

from core.storage.database import db
from config.config_manager import config_manager

PAGE_SIZE = 100


class DataPage(QWidget):
    def __init__(self):
        super().__init__()
        self._page = 0
        self._total_count = 0
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("设备:"))
        self._device_combo = QComboBox()
        self._device_combo.addItem("全部")
        for device_id in config_manager.devices:
            self._device_combo.addItem(f"{config_manager.devices[device_id].name} ({device_id})", device_id)
        filter_layout.addWidget(self._device_combo)

        filter_layout.addWidget(QLabel("采集点:"))
        self._point_edit = QLineEdit()
        self._point_edit.setPlaceholderText("为空查询所有")
        filter_layout.addWidget(self._point_edit)

        filter_layout.addWidget(QLabel("状态:"))
        self._status_combo = QComboBox()
        self._status_combo.addItems(["全部", "成功", "失败"])
        filter_layout.addWidget(self._status_combo)

        filter_layout.addWidget(QLabel("报警:"))
        self._alarm_combo = QComboBox()
        self._alarm_combo.addItems(["全部", "仅报警"])
        filter_layout.addWidget(self._alarm_combo)

        filter_layout.addWidget(QLabel("开始:"))
        self._start_time = QDateTimeEdit(QDateTime.currentDateTime().addSecs(-3600))
        self._start_time.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        filter_layout.addWidget(self._start_time)

        filter_layout.addWidget(QLabel("结束:"))
        self._end_time = QDateTimeEdit(QDateTime.currentDateTime())
        self._end_time.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        filter_layout.addWidget(self._end_time)

        self._query_btn = QPushButton("查询")
        self._query_btn.clicked.connect(self._query_data)
        filter_layout.addWidget(self._query_btn)

        self._refresh_btn = QPushButton("刷新")
        self._refresh_btn.clicked.connect(self._refresh_device_combo)
        filter_layout.addWidget(self._refresh_btn)

        self._export_btn = QPushButton("导出CSV")
        self._export_btn.clicked.connect(self._export_csv)
        filter_layout.addWidget(self._export_btn)

        self._clear_btn = QPushButton("清空数据")
        self._clear_btn.clicked.connect(self._clear_old_data)
        self._clear_btn.setStyleSheet("color: #e74c3c;")
        filter_layout.addWidget(self._clear_btn)
        layout.addLayout(filter_layout)

        self._data_table = QTableWidget(0, 7)
        self._data_table.setHorizontalHeaderLabels(
            ["时间", "设备ID", "采集点", "值", "单位", "状态", "报警"]
        )
        header = self._data_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._data_table, 1)

        pag_layout = QHBoxLayout()
        self._prev_btn = QPushButton("上一页")
        self._prev_btn.clicked.connect(self._prev_page)
        self._next_btn = QPushButton("下一页")
        self._next_btn.clicked.connect(self._next_page)
        self._page_label = QLabel("第 1 页")
        self._page_size_label = QLabel("每页:")
        self._page_size_combo = QComboBox()
        self._page_size_combo.addItems(["50", "100", "200", "500"])
        self._page_size_combo.setCurrentText("100")
        self._page_size_combo.currentTextChanged.connect(self._on_page_size_changed)
        pag_layout.addWidget(self._page_label)
        pag_layout.addWidget(self._prev_btn)
        pag_layout.addWidget(self._next_btn)
        pag_layout.addStretch()
        pag_layout.addWidget(self._page_size_label)
        pag_layout.addWidget(self._page_size_combo)
        pag_layout.addWidget(QLabel("条/页"))
        layout.addLayout(pag_layout)

        self._stats_label = QLabel("共 0 条记录")
        self._stats_label.setStyleSheet("padding: 5px; color: #7f8c8d;")
        layout.addWidget(self._stats_label)

    def _refresh_device_combo(self):
        saved_id = self._device_combo.currentData()
        self._device_combo.blockSignals(True)
        try:
            self._device_combo.clear()
            self._device_combo.addItem("全部")
            restored_idx = 0
            for device_id in config_manager.devices:
                device = config_manager.devices[device_id]
                self._device_combo.addItem(f"{device.name} ({device_id})", device_id)
                if device_id == saved_id:
                    restored_idx = self._device_combo.count() - 1
            self._device_combo.setCurrentIndex(restored_idx)
        finally:
            self._device_combo.blockSignals(False)

    def _on_page_size_changed(self):
        self._page = 0
        self._query_data()

    def _prev_page(self):
        if self._page > 0:
            self._page -= 1
            self._query_data()

    def _next_page(self):
        if (self._page + 1) * self._get_page_size() < self._total_count:
            self._page += 1
            self._query_data()

    def _get_page_size(self):
        try:
            return int(self._page_size_combo.currentText())
        except ValueError:
            return PAGE_SIZE

    def _query_data(self):
        self._refresh_device_combo()
        device_id = self._device_combo.currentData()
        point_name = self._point_edit.text().strip() or None
        start_ts = self._start_time.dateTime().toSecsSinceEpoch()
        end_ts = self._end_time.dateTime().toSecsSinceEpoch()
        page_size = self._get_page_size()
        offset = self._page * page_size
        status_filter = self._status_combo.currentText()
        alarm_filter = self._alarm_combo.currentText()

        status_val = None
        if status_filter == "成功":
            status_val = 1
        elif status_filter == "失败":
            status_val = 0

        alarm_val = None
        if alarm_filter == "仅报警":
            alarm_val = 1

        records = db.query_data_filtered(
            device_id=device_id, point_name=point_name,
            start_time=start_ts, end_time=end_ts,
            status=status_val, is_alarm=alarm_val,
            limit=page_size, offset=offset
        )
        self._total_count = db.count_data_filtered(
            device_id=device_id, point_name=point_name,
            start_time=start_ts, end_time=end_ts,
            status=status_val, is_alarm=alarm_val
        )
        self._display_records(records)
        total_pages = max(1, (self._total_count + page_size - 1) // page_size)
        self._page_label.setText(f"第 {self._page + 1} / {total_pages} 页")
        self._prev_btn.setEnabled(self._page > 0)
        self._next_btn.setEnabled((self._page + 1) * page_size < self._total_count)

    def _display_records(self, records):
        self._data_table.setRowCount(0)
        for record in records:
            row = self._data_table.rowCount()
            self._data_table.insertRow(row)
            ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(record['timestamp']))
            self._data_table.setItem(row, 0, QTableWidgetItem(ts))
            self._data_table.setItem(row, 1, QTableWidgetItem(record.get('device_id', '')))
            self._data_table.setItem(row, 2, QTableWidgetItem(record.get('point_name', '')))
            value = record.get('value')
            value_str = f"{value:.4f}" if isinstance(value, float) else str(value) if value is not None else "N/A"
            self._data_table.setItem(row, 3, QTableWidgetItem(value_str))
            self._data_table.setItem(row, 4, QTableWidgetItem(record.get('unit', '')))
            status_text = "成功" if record.get('success') else "失败"
            status_item = QTableWidgetItem(status_text)
            if not record.get('success'):
                status_item.setForeground(QColor("#e74c3c"))
            self._data_table.setItem(row, 5, status_item)
            is_alarm_val = record.get('is_alarm')
            alarm_text = "⚠ 报警" if is_alarm_val else ""
            alarm_item = QTableWidgetItem(alarm_text)
            if is_alarm_val:
                alarm_item.setForeground(QColor("#e74c3c"))
            self._data_table.setItem(row, 6, alarm_item)

        stats = db.get_statistics(
            device_id=self._device_combo.currentData(),
            start_time=self._start_time.dateTime().toSecsSinceEpoch(),
            end_time=self._end_time.dateTime().toSecsSinceEpoch()
        )
        self._stats_label.setText(
            f"共 {self._total_count} 条记录 | "
            f"成功率: {stats['success_rate']:.1f}% | "
            f"成功: {stats['success_count']} | 失败: {stats['fail_count']}"
        )

    def _export_csv(self):
        filepath, _ = QFileDialog.getSaveFileName(self, "导出CSV", "data_export.csv", "CSV文件 (*.csv)")
        if filepath:
            start_ts = self._start_time.dateTime().toSecsSinceEpoch()
            end_ts = self._end_time.dateTime().toSecsSinceEpoch()
            try:
                db.export_csv(filepath,
                              device_id=self._device_combo.currentData(),
                              start_time=start_ts,
                              end_time=end_ts)
                QMessageBox.information(self, "成功", f"数据已导出到 {filepath}")
            except Exception as e:
                QMessageBox.warning(self, "错误", f"导出失败: {e}")

    def _clear_old_data(self):
        reply = QMessageBox.question(
            self, "确认清空",
            "确定要清空当前筛选条件下的所有数据吗？\n此操作不可恢复！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            end_ts = self._end_time.dateTime().toSecsSinceEpoch()
            db.delete_old_data(end_ts)
            self._page = 0
            self._query_data()
            QMessageBox.information(self, "成功", "数据已清空")


