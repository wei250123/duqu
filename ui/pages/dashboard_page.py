"""可视化大屏 - 实时传感器数据展示与滑动滤波对比"""

import time
from collections import deque
from typing import Optional

import numpy as np
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
                              QPushButton, QCheckBox, QFrame, QSplitter,
                              QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
                              QHeaderView, QSpinBox)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QColor

import matplotlib
matplotlib.use('QtAgg')
import matplotlib.font_manager as fm
from matplotlib import rcParams
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from config.config_manager import config_manager
from core.processor.pipeline import filter_bank as global_filter_bank
from utils.logger import log_manager

_CHINESE_FONT = None
for _font_name in ['Microsoft YaHei', 'SimHei', 'SimSun', 'Noto Sans CJK SC']:
    _available = [f.name for f in fm.fontManager.ttflist]
    if _font_name in _available:
        _CHINESE_FONT = _font_name
        break

if _CHINESE_FONT:
    rcParams['font.sans-serif'] = [_CHINESE_FONT, 'DejaVu Sans']
    rcParams['axes.unicode_minus'] = False
    fm._load_fontmanager(try_read_cache=False)

MAX_HISTORY = 120

LINE_COLORS = [
    '#00c864', '#ff8c00', '#00a0ff',
    '#ff5050', '#c864ff', '#ffc800',
    '#00d2b4', '#ff78b4',
]

FILTER_TYPE_LABELS = {
    "sma": "滑动平均(SMA)",
    "ema": "指数平滑(EMA)",
    "median": "中值滤波(Median)",
}


class DashboardPage(QWidget):
    def __init__(self):
        super().__init__()
        self._device_id: Optional[str] = None
        self._point_names: list[str] = []
        self._point_units: dict[str, str] = {}
        self._point_descriptions: dict[str, str] = {}
        self._data_buffers: dict[str, deque[tuple[float, float, float]]] = {}
        self._lines: dict[str, tuple] = {}
        self._color_idx = 0
        self._paused = False
        self._pending_data: list[tuple[str, float, Optional[float]]] = []
        self._init_ui()
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._flush_data)
        self._refresh_timer.start(100)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        control_layout = QHBoxLayout()
        control_layout.addWidget(QLabel("设备:"))
        self._device_combo = QComboBox()
        self._device_combo.setMinimumWidth(180)
        self._refresh_devices()
        self._device_combo.currentIndexChanged.connect(self._on_device_changed)
        control_layout.addWidget(self._device_combo)

        control_layout.addWidget(QLabel("窗口大小:"))
        self._window_spin = QSpinBox()
        self._window_spin.setRange(2, 50)
        self._window_spin.setValue(10)
        self._window_spin.valueChanged.connect(self._on_window_changed)
        control_layout.addWidget(self._window_spin)

        control_layout.addWidget(QLabel("滤波类型:"))
        self._filter_type_combo = QComboBox()
        self._filter_type_combo.addItems([
            "滑动平均(SMA)", "指数平滑(EMA)", "中值滤波(Median)"
        ])
        self._filter_type_combo.currentIndexChanged.connect(self._on_filter_type_changed)
        control_layout.addWidget(self._filter_type_combo)

        self._show_raw_cb = QCheckBox("原始值")
        self._show_raw_cb.setChecked(True)
        self._show_raw_cb.toggled.connect(self._on_show_raw_changed)
        control_layout.addWidget(self._show_raw_cb)

        self._show_filtered_cb = QCheckBox("滤波值")
        self._show_filtered_cb.setChecked(True)
        self._show_filtered_cb.toggled.connect(self._on_show_filtered_changed)
        control_layout.addWidget(self._show_filtered_cb)

        control_layout.addStretch()

        self._pause_btn = QPushButton("暂停")
        self._pause_btn.setCheckable(True)
        self._pause_btn.toggled.connect(self._toggle_pause)
        control_layout.addWidget(self._pause_btn)

        self._clear_btn = QPushButton("清除")
        self._clear_btn.clicked.connect(self._clear_chart)
        control_layout.addWidget(self._clear_btn)

        layout.addLayout(control_layout)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_frame = QFrame()
        left_frame.setFrameStyle(QFrame.Shape.StyledPanel)
        left_layout = QVBoxLayout(left_frame)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.addWidget(QLabel("采集点选择"))
        self._point_list = QListWidget()
        self._point_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self._point_list.itemSelectionChanged.connect(self._on_point_selection_changed)
        left_layout.addWidget(self._point_list)

        self._select_all_btn = QPushButton("全选/反选")
        self._select_all_btn.clicked.connect(self._toggle_select_all)
        left_layout.addWidget(self._select_all_btn)

        splitter.addWidget(left_frame)

        right_frame = QFrame()
        right_frame.setFrameStyle(QFrame.Shape.StyledPanel)
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(4, 4, 4, 4)

        self._figure = Figure(facecolor='white')
        self._canvas = FigureCanvas(self._figure)
        self._ax = self._figure.add_subplot(111)
        self._setup_ax_style()
        right_layout.addWidget(self._canvas, 3)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels([
            "采集点", "原始值", "滤波值", "差值", "单位"
        ])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setMaximumHeight(160)
        self._table.setStyleSheet("""
            QTableWidget {
                background-color: white;
                color: #333333;
                gridline-color: #e0e0e0;
                font-size: 12px;
            }
            QTableWidget::item { padding: 2px 6px; }
            QHeaderView::section {
                background-color: #f5f5f5;
                color: #666666;
                padding: 4px;
                border: none;
                border-bottom: 1px solid #e0e0e0;
            }
        """)
        right_layout.addWidget(self._table)

        splitter.addWidget(right_frame)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        layout.addWidget(splitter, 1)

    def _setup_ax_style(self):
        self._ax.set_facecolor('#fafafa')
        self._ax.tick_params(colors='#555555')
        for spine_name, spine in self._ax.spines.items():
            spine.set_color('#cccccc')
        self._ax.set_xlabel('时间 (秒)', color='#555555')
        self._ax.set_ylabel('数值', color='#555555')
        self._ax.grid(True, alpha=0.3, color='#e0e0e0')

    def _refresh_devices(self):
        self._device_combo.blockSignals(True)
        self._device_combo.clear()
        self._device_combo.addItem("-- 选择设备 --", None)
        for device_id in config_manager.devices:
            self._device_combo.addItem(
                f"{device_id} ({config_manager.devices[device_id].name})", device_id)
        self._device_combo.blockSignals(False)

    def _on_device_changed(self):
        self._device_id = self._device_combo.currentData()
        self._data_buffers.clear()
        self._point_names.clear()
        self._point_units.clear()
        self._point_descriptions.clear()
        self._lines.clear()
        self._pending_data.clear()
        self._ax.clear()
        self._setup_ax_style()
        self._table.setRowCount(0)
        self._point_list.clear()
        self._canvas.draw_idle()
        if not self._device_id:
            return
        device = config_manager.get_device(self._device_id)
        if not device:
            return
        for point in device.collect.points:
            display_label = point.name
            if point.description:
                display_label = f"{point.name}  [{point.description}]"
            item = QListWidgetItem(display_label)
            item.setData(Qt.ItemDataRole.UserRole, point.name)
            item.setSelected(True)
            self._point_list.addItem(item)
            self._point_units[point.name] = point.unit
            self._point_descriptions[point.name] = point.description
        self._on_point_selection_changed()

    def _on_point_selection_changed(self):
        self._point_names = []
        for item in self._point_list.selectedItems():
            self._point_names.append(item.data(Qt.ItemDataRole.UserRole))
        self._rebuild_lines()

    def _toggle_select_all(self):
        all_selected = all(
            self._point_list.item(i).isSelected()
            for i in range(self._point_list.count())
        )
        for i in range(self._point_list.count()):
            self._point_list.item(i).setSelected(not all_selected)

    def _rebuild_lines(self):
        self._ax.clear()
        self._setup_ax_style()
        self._lines.clear()
        self._color_idx = 0
        for name in self._point_names:
            color = LINE_COLORS[self._color_idx % len(LINE_COLORS)]
            self._color_idx += 1
            desc = self._point_descriptions.get(name, name)
            display_name = desc if desc else name
            raw_line, = self._ax.plot([], [], linestyle='--', linewidth=1,
                                      color=color, alpha=0.6,
                                      label=f'{display_name}(原始)')
            flt_line, = self._ax.plot([], [], linewidth=2.5,
                                      color=color, alpha=1.0,
                                      label=f'{display_name}(滤波)')
            self._lines[name] = (raw_line, flt_line)
        if self._point_names:
            self._ax.legend(fontsize=8, loc='upper left',
                            facecolor='#ffffffcc', edgecolor='#cccccc',
                            labelcolor='#333333', ncol=1)
        self._update_chart_title()
        self._on_show_raw_changed(self._show_raw_cb.isChecked())
        self._on_show_filtered_changed(self._show_filtered_cb.isChecked())
        self._replay_buffered_data()
        self._canvas.draw_idle()

    def _update_chart_title(self):
        filter_type = global_filter_bank.config.get("filter_type", "sma")
        window_size = global_filter_bank.config.get("window_size", 10)
        type_label = FILTER_TYPE_LABELS.get(filter_type, filter_type)
        self._ax.set_title(
            f'实时数据 · {type_label} (窗口={window_size})',
            color='#333333', fontsize=13, pad=10
        )

    def _replay_buffered_data(self):
        """将缓冲区中已有数据填入新创建的曲线，避免重建后曲线空白。"""
        if not self._device_id:
            return
        for name in self._point_names:
            lines_tuple = self._lines.get(name)
            if not lines_tuple:
                continue
            key = f"{self._device_id}:{name}"
            buf = self._data_buffers.get(key)
            if not buf or len(buf) < 1:
                continue
            raw_line, flt_line = lines_tuple
            data = list(buf)
            if len(data) > 1:
                t0 = data[0][0]
                display_times = [t[0] - t0 for t in data]
            else:
                display_times = [0]
            raw_vals = [t[1] for t in data]
            flt_vals = [t[2] if t[2] is not None else t[1] for t in data]
            raw_line.set_data(display_times, raw_vals)
            flt_line.set_data(display_times, flt_vals)
        self._ax.relim()
        self._ax.autoscale_view()

    def _on_show_raw_changed(self, checked):
        for _, (raw_line, _) in self._lines.items():
            raw_line.set_visible(checked)
        self._canvas.draw_idle()

    def _on_show_filtered_changed(self, checked):
        for _, (_, flt_line) in self._lines.items():
            flt_line.set_visible(checked)
        self._canvas.draw_idle()

    def _on_window_changed(self, value):
        global_filter_bank.update_config(window_size=value)
        self._update_chart_title()
        self._canvas.draw_idle()

    def _on_filter_type_changed(self, idx):
        type_map = {0: "sma", 1: "ema", 2: "median"}
        new_type = type_map.get(idx, "sma")
        global_filter_bank.update_config(filter_type=new_type)
        self._update_chart_title()
        self._canvas.draw_idle()

    def _toggle_pause(self, checked):
        self._paused = checked
        self._pause_btn.setText("继续" if checked else "暂停")

    def _clear_chart(self):
        self._data_buffers.clear()
        self._pending_data.clear()
        self._rebuild_lines()

    def feed_data(self, device_id: str, point_name: str, value: float,
                  filtered_value: Optional[float] = None,
                  timestamp: Optional[float] = None):
        if device_id != self._device_id:
            return
        if point_name not in self._point_names:
            return
        if timestamp is None:
            timestamp = time.time()
        key = f"{device_id}:{point_name}"
        if key not in self._data_buffers:
            self._data_buffers[key] = deque(maxlen=MAX_HISTORY)
        self._data_buffers[key].append((timestamp, value, filtered_value))
        self._pending_data.append((point_name, value, filtered_value))

    def _flush_data(self):
        if self._paused or not self._pending_data:
            return
        items = self._pending_data
        self._pending_data = []
        seen: dict[str, tuple[float, Optional[float]]] = {}
        for point_name, value, filtered_value in items:
            seen[point_name] = (value, filtered_value)
        self._update_curves()
        self._update_table(seen)

    def _update_curves(self):
        if not self._device_id:
            return
        need_redraw = False
        for name in self._point_names:
            lines_tuple = self._lines.get(name)
            if not lines_tuple:
                continue
            key = f"{self._device_id}:{name}"
            buf = self._data_buffers.get(key)
            if not buf or len(buf) < 1:
                continue
            raw_line, flt_line = lines_tuple
            data = list(buf)
            if len(data) > 1:
                t0 = data[0][0]
                display_times = [t[0] - t0 for t in data]
            else:
                display_times = [0]
            raw_vals = [t[1] for t in data]
            flt_vals = [t[2] if t[2] is not None else t[1] for t in data]
            raw_line.set_data(display_times, raw_vals)
            flt_line.set_data(display_times, flt_vals)
            need_redraw = True
        if need_redraw:
            self._ax.relim()
            self._ax.autoscale_view()
            self._canvas.draw_idle()

    def _update_table(self, seen: dict[str, tuple[float, Optional[float]]]):
        self._table.setRowCount(0)
        for name in self._point_names:
            if name not in seen:
                continue
            raw_val, flt_val = seen[name]
            row = self._table.rowCount()
            self._table.insertRow(row)

            display_name = self._point_descriptions.get(name) or name
            name_item = QTableWidgetItem(display_name)
            self._table.setItem(row, 0, name_item)

            raw_str = f"{raw_val:.4f}" if raw_val is not None else "--"
            raw_item = QTableWidgetItem(raw_str)
            raw_item.setForeground(QColor("#e74c3c"))
            self._table.setItem(row, 1, raw_item)

            flt_str = f"{flt_val:.4f}" if flt_val is not None else "--"
            flt_item = QTableWidgetItem(flt_str)
            flt_item.setForeground(QColor("#27ae60"))
            self._table.setItem(row, 2, flt_item)

            if raw_val is not None and flt_val is not None:
                diff = raw_val - flt_val
                diff_item = QTableWidgetItem(f"{diff:+.4f}")
                diff_item.setForeground(
                    QColor("#e67e22") if abs(diff) > 0.01 else QColor("#999999"))
            else:
                diff_item = QTableWidgetItem("--")
            self._table.setItem(row, 3, diff_item)

            unit_item = QTableWidgetItem(self._point_units.get(name, ""))
            self._table.setItem(row, 4, unit_item)