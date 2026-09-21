"""数据可视化 - 工业传感器数值展示面板"""

import json
import os
from typing import Optional, Dict

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QComboBox, QPushButton, QFrame, QScrollArea,
                              QGridLayout, QCheckBox, QProgressBar, QSplitter,
                              QListWidget, QListWidgetItem, QFileDialog, QDialog,
                              QMessageBox)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QPixmap

from config.config_manager import config_manager

# ── 白色主题配色 ─────────────────────────────────────────
CLR_CARD_BG  = "#ffffff"
CLR_BORDER   = "#e0e0e0"
CLR_TEXT     = "#333333"
CLR_SUBTEXT  = "#666666"
CLR_MUTED    = "#999999"
CLR_GREEN    = "#27ae60"
CLR_YELLOW   = "#e67e22"
CLR_RED      = "#e74c3c"
CLR_TEAL     = "#16a085"

STATE_STYLES = {
    "normal":  {"bg": CLR_CARD_BG, "border": CLR_BORDER,  "accent": CLR_GREEN,  "text": CLR_TEXT},
    "warning": {"bg": "#fff8e1",   "border": CLR_YELLOW,  "accent": CLR_YELLOW, "text": CLR_TEXT},
    "alarm":   {"bg": "#ffebee",   "border": CLR_RED,     "accent": CLR_RED,    "text": CLR_TEXT},
    "offline": {"bg": CLR_CARD_BG, "border": "#d0d0d0",   "accent": CLR_MUTED,  "text": CLR_SUBTEXT},
}

IMAGES_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                           "visualization_images.json")


def _load_images() -> dict[str, list[str]]:
    if not os.path.exists(IMAGES_FILE):
        return {}
    try:
        with open(IMAGES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if isinstance(v, list)}
    except Exception:
        return {}


def _save_images(data: dict[str, list[str]]):
    try:
        with open(IMAGES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _level_for_point(value, alarm_high, alarm_low) -> str:
    if value is None:
        return "offline"
    if alarm_high is not None and value > alarm_high:
        return "alarm"
    if alarm_low is not None and value < alarm_low:
        return "alarm"
    if alarm_high is not None and value > alarm_high * 0.85:
        return "warning"
    if alarm_low is not None and value < alarm_low * 1.15:
        return "warning"
    return "normal"


class ImageViewer(QDialog):
    """图片全屏查看弹窗"""

    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("图片查看")
        self.setMinimumSize(600, 400)
        layout = QVBoxLayout(self)
        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            scaled = pixmap.scaled(900, 600, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            self._label.setPixmap(scaled)
        else:
            self._label.setText("无法加载图片")


class ImageCard(QFrame):
    """图片卡片"""

    def __init__(self, image_path: str, on_remove=None):
        super().__init__()
        self._image_path = image_path
        self._on_remove = on_remove
        self._init_ui()

    def _init_ui(self):
        self.setMinimumSize(260, 210)
        self.setMaximumSize(400, 280)
        self.setObjectName("image_card")
        self.setStyleSheet(f"""
            #image_card {{
                background-color: {CLR_CARD_BG};
                border: 1px solid {CLR_BORDER};
                border-radius: 6px;
            }}
        """)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # 图片缩略图
        self._thumb = QLabel()
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setStyleSheet("border: none; background: transparent;")
        pixmap = QPixmap(self._image_path)
        if not pixmap.isNull():
            scaled = pixmap.scaled(240, 160, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            self._thumb.setPixmap(scaled)
        else:
            self._thumb.setText("图片加载失败")
        layout.addWidget(self._thumb, 1)

        # 底部：文件名 + 删除按钮
        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        name = QLabel(os.path.basename(self._image_path))
        name.setFont(QFont("Microsoft YaHei", 9))
        name.setStyleSheet(f"color: {CLR_SUBTEXT}; border: none;")
        name.setWordWrap(False)
        bottom.addWidget(name, 1)

        remove_btn = QPushButton("✕")
        remove_btn.setFixedSize(22, 22)
        remove_btn.setToolTip("删除图片")
        remove_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {CLR_MUTED}; border: none;
                font-size: 14px; font-weight: bold;
            }}
            QPushButton:hover {{ color: {CLR_RED}; }}
        """)
        remove_btn.clicked.connect(self._on_remove_clicked)
        bottom.addWidget(remove_btn)
        layout.addLayout(bottom)

    def mousePressEvent(self, event):
        viewer = ImageViewer(self._image_path, self.window())
        viewer.exec()

    def _on_remove_clicked(self):
        if self._on_remove:
            self._on_remove(self._image_path)


class SensorCard(QFrame):
    """工业传感器数值卡片"""

    def __init__(self, point_name: str, description: str, unit: str,
                 alarm_high=None, alarm_low=None):
        super().__init__()
        self._point_name = point_name
        self._description = description or point_name
        self._unit = unit
        self._alarm_high = alarm_high
        self._alarm_low = alarm_low
        self._raw_val = None
        self._flt_val = None
        self._level = "offline"
        self._init_ui()

    def _init_ui(self):
        self.setMinimumSize(260, 210)
        self.setObjectName("sensor_card")
        self.setStyleSheet(f"""
            #sensor_card {{
                background-color: {CLR_CARD_BG};
                border: 1px solid {CLR_BORDER};
                border-radius: 6px;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        inner = QHBoxLayout()
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)

        self._accent_bar = QFrame()
        self._accent_bar.setFixedWidth(4)
        self._accent_bar.setStyleSheet(f"background: {CLR_MUTED}; border: none; border-radius: 2px;")
        inner.addWidget(self._accent_bar)

        card = QVBoxLayout()
        card.setContentsMargins(15, 11, 15, 11)
        card.setSpacing(0)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self._dot = QLabel("●")
        self._dot.setFixedWidth(16)
        self._dot.setFont(QFont("Arial", 10))
        self._dot.setStyleSheet(f"color: {CLR_MUTED};")
        title_row.addWidget(self._dot)
        self._title = QLabel(self._description)
        self._title.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        self._title.setStyleSheet(f"color: {CLR_TEXT};")
        title_row.addWidget(self._title, 1)
        card.addLayout(title_row)

        card.addSpacing(12)

        self._main_value = QLabel("--")
        self._main_value.setFont(QFont("Consolas", 42, QFont.Weight.Bold))
        self._main_value.setStyleSheet(f"color: {CLR_SUBTEXT};")
        card.addWidget(self._main_value)

        self._unit_label = QLabel(self._unit)
        self._unit_label.setFont(QFont("Microsoft YaHei", 10))
        self._unit_label.setStyleSheet(f"color: {CLR_MUTED};")
        card.addWidget(self._unit_label)

        card.addSpacing(8)

        sub_row = QHBoxLayout()
        sub_row.setSpacing(20)

        flt_block = QVBoxLayout()
        flt_block.setSpacing(1)
        flt_hdr = QLabel("滤波值")
        flt_hdr.setFont(QFont("Microsoft YaHei", 8))
        flt_hdr.setStyleSheet(f"color: {CLR_MUTED};")
        flt_block.addWidget(flt_hdr)
        self._flt_label = QLabel("--")
        self._flt_label.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
        flt_block.addWidget(self._flt_label)
        sub_row.addLayout(flt_block)

        diff_block = QVBoxLayout()
        diff_block.setSpacing(1)
        diff_hdr = QLabel("差值")
        diff_hdr.setFont(QFont("Microsoft YaHei", 8))
        diff_hdr.setStyleSheet(f"color: {CLR_MUTED};")
        diff_block.addWidget(diff_hdr)
        self._diff_label = QLabel("--")
        self._diff_label.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
        diff_block.addWidget(self._diff_label)
        sub_row.addLayout(diff_block)

        sub_row.addStretch()
        card.addLayout(sub_row)

        card.addSpacing(8)

        range_row = QHBoxLayout()
        range_row.setSpacing(6)
        lo_text = f"{self._alarm_low:.1f}" if self._alarm_low is not None else "Lo"
        hi_text = f"{self._alarm_high:.1f}" if self._alarm_high is not None else "Hi"
        self._range_lo = QLabel(lo_text)
        self._range_lo.setFont(QFont("Consolas", 8))
        self._range_lo.setStyleSheet(f"color: {CLR_MUTED};")
        range_row.addWidget(self._range_lo)

        self._range_bar = QProgressBar()
        self._range_bar.setTextVisible(False)
        self._range_bar.setFixedHeight(5)
        self._range_bar.setRange(0, 100)
        self._range_bar.setValue(0)
        self._range_bar.setStyleSheet("""
            QProgressBar { background: #f0f0f0; border: none; border-radius: 2px; }
        """)
        range_row.addWidget(self._range_bar, 1)

        self._range_hi = QLabel(hi_text)
        self._range_hi.setFont(QFont("Consolas", 8))
        self._range_hi.setStyleSheet(f"color: {CLR_MUTED};")
        range_row.addWidget(self._range_hi)
        card.addLayout(range_row)

        inner.addLayout(card, 1)
        root.addLayout(inner)

    def update_value(self, raw_val, filtered_val=None):
        self._raw_val = raw_val
        self._flt_val = filtered_val
        self._level = _level_for_point(raw_val, self._alarm_high, self._alarm_low)
        s = STATE_STYLES[self._level]

        self.setStyleSheet(f"""
            #sensor_card {{
                background-color: {s['bg']};
                border: 1px solid {s['border']};
                border-radius: 6px;
            }}
        """)

        self._accent_bar.setStyleSheet(
            f"background: {s['accent']}; border: none; border-radius: 2px;")

        dot_color = {
            "normal": CLR_GREEN, "warning": CLR_YELLOW,
            "alarm": CLR_RED, "offline": CLR_MUTED,
        }[self._level]
        self._dot.setStyleSheet(f"color: {dot_color};")
        self._title.setStyleSheet(f"color: {s['text']}; font-weight: bold;")

        if raw_val is not None:
            if abs(raw_val) >= 1000:
                display = f"{raw_val:.1f}"
            elif abs(raw_val) >= 10:
                display = f"{raw_val:.2f}"
            else:
                display = f"{raw_val:.3f}"
            self._main_value.setText(display)
        else:
            self._main_value.setText("--")
        self._main_value.setStyleSheet(f"color: {s['accent']};")
        self._unit_label.setStyleSheet(f"color: {CLR_MUTED};")

        if filtered_val is not None:
            self._flt_label.setText(f"{filtered_val:.3f}")
            self._flt_label.setStyleSheet(f"color: {CLR_TEAL};")
        else:
            self._flt_label.setText("--")
            self._flt_label.setStyleSheet(f"color: {CLR_MUTED};")

        if raw_val is not None and filtered_val is not None:
            diff = raw_val - filtered_val
            self._diff_label.setText(f"{diff:+.4f}")
            self._diff_label.setStyleSheet(
                f"color: {CLR_YELLOW};" if abs(diff) > 0.01
                else f"color: {CLR_MUTED};")
        else:
            self._diff_label.setText("--")
            self._diff_label.setStyleSheet(f"color: {CLR_MUTED};")

        if raw_val is not None and self._alarm_high is not None and self._alarm_high > 0:
            pct = min(raw_val / self._alarm_high * 100, 100)
            self._range_bar.setValue(int(pct))
            self._range_bar.setStyleSheet(f"""
                QProgressBar {{ background: #f0f0f0; border: none; border-radius: 2px; }}
                QProgressBar::chunk {{ background: {s['accent']}; border-radius: 2px; }}
            """)
        else:
            self._range_bar.setValue(0)


class VisualizationPage(QWidget):
    """数据可视化 - 工业展示面板"""

    def __init__(self):
        super().__init__()
        self._device_id: Optional[str] = None
        self._cards: Dict[str, SensorCard] = {}
        self._point_configs: Dict[str, dict] = {}
        self._selected_points: set[str] = set()
        self._paused = False
        self._pending: dict[str, tuple] = {}
        self._images: dict[str, list[str]] = _load_images()
        self._init_ui()
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._flush)
        self._refresh_timer.start(150)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        # ── 顶栏 ──
        top_bar = QHBoxLayout()
        top_bar.setSpacing(12)

        header = QLabel("数据可视化")
        header.setFont(QFont("Microsoft YaHei", 15, QFont.Weight.Bold))
        top_bar.addWidget(header)

        top_bar.addSpacing(14)

        dev_lbl = QLabel("设备")
        top_bar.addWidget(dev_lbl)
        self._device_combo = QComboBox()
        self._device_combo.setMinimumWidth(200)
        self._refresh_devices()
        self._device_combo.currentIndexChanged.connect(self._on_device_changed)
        top_bar.addWidget(self._device_combo)

        self._show_filtered_cb = QCheckBox("显示滤波值")
        self._show_filtered_cb.setChecked(True)
        top_bar.addWidget(self._show_filtered_cb)

        self._add_image_btn = QPushButton("添加图片")
        self._add_image_btn.clicked.connect(self._add_image)
        self._add_image_btn.setEnabled(False)
        top_bar.addWidget(self._add_image_btn)

        top_bar.addStretch()

        self._pause_btn = QPushButton("暂停")
        self._pause_btn.setCheckable(True)
        self._pause_btn.toggled.connect(self._toggle_pause)
        top_bar.addWidget(self._pause_btn)
        layout.addLayout(top_bar)

        # ── 主体分栏 ──
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_frame = QFrame()
        left_frame.setFrameStyle(QFrame.Shape.StyledPanel)
        left_layout = QVBoxLayout(left_frame)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(6)

        left_header = QLabel("采集点选择")
        left_header.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        left_layout.addWidget(left_header)

        self._point_list = QListWidget()
        self._point_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self._point_list.itemSelectionChanged.connect(self._on_point_selection_changed)
        left_layout.addWidget(self._point_list)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        sel_all = QPushButton("全选")
        sel_all.clicked.connect(lambda: self._set_all_selected(True))
        btn_row.addWidget(sel_all)
        sel_none = QPushButton("取消全选")
        sel_none.clicked.connect(lambda: self._set_all_selected(False))
        btn_row.addWidget(sel_none)
        left_layout.addLayout(btn_row)

        splitter.addWidget(left_frame)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._grid_container = QWidget()
        self._grid = QGridLayout(self._grid_container)
        self._grid.setSpacing(12)
        self._grid.setContentsMargins(4, 0, 0, 0)
        scroll.setWidget(self._grid_container)
        splitter.addWidget(scroll)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([200, 800])
        layout.addWidget(splitter, 1)

    def _current_images(self) -> list[str]:
        if not self._device_id:
            return []
        if self._device_id not in self._images:
            self._images[self._device_id] = []
        return self._images[self._device_id]

    def _add_image(self):
        if not self._device_id:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if not paths:
            return
        images = self._current_images()
        for p in paths:
            if p not in images:
                images.append(p)
        _save_images(self._images)
        self._rebuild_cards()

    def _remove_image(self, image_path: str):
        images = self._current_images()
        if image_path in images:
            images.remove(image_path)
        _save_images(self._images)
        self._rebuild_cards()

    def _refresh_devices(self):
        self._device_combo.blockSignals(True)
        self._device_combo.clear()
        self._device_combo.addItem("-- 选择设备 --", None)
        for device_id in config_manager.devices:
            d = config_manager.devices[device_id]
            self._device_combo.addItem(f"{d.name}  ({device_id})", device_id)
        self._device_combo.blockSignals(False)

    def _on_device_changed(self):
        self._device_id = self._device_combo.currentData()
        self._cards.clear()
        self._point_configs.clear()
        self._selected_points.clear()
        self._pending.clear()
        self._clear_grid()
        self._point_list.clear()
        self._add_image_btn.setEnabled(bool(self._device_id))
        if not self._device_id:
            return
        device = config_manager.get_device(self._device_id)
        if not device:
            return
        for point in device.collect.points:
            display = f"{point.name}"
            if point.description:
                display = f"{point.name}  [{point.description}]"
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, point.name)
            item.setSelected(False)
            self._point_list.addItem(item)
            self._point_configs[point.name] = {
                "description": point.description,
                "unit": point.unit,
                "alarm_high": point.alarm_high,
                "alarm_low": point.alarm_low,
            }
        self._rebuild_cards()

    def _on_point_selection_changed(self):
        self._selected_points = set()
        for item in self._point_list.selectedItems():
            self._selected_points.add(item.data(Qt.ItemDataRole.UserRole))
        self._rebuild_cards()

    def _set_all_selected(self, select: bool):
        self._point_list.blockSignals(True)
        for i in range(self._point_list.count()):
            self._point_list.item(i).setSelected(select)
        self._point_list.blockSignals(False)
        self._on_point_selection_changed()

    def _rebuild_cards(self):
        self._clear_grid()
        self._cards.clear()
        cols = 3
        row = 0

        # 传感器卡片
        ordered = sorted(self._selected_points)
        for i, name in enumerate(ordered):
            cfg = self._point_configs.get(name, {})
            card = SensorCard(
                name,
                cfg.get("description", name),
                cfg.get("unit", ""),
                cfg.get("alarm_high"),
                cfg.get("alarm_low"),
            )
            self._cards[name] = card
            self._grid.addWidget(card, i // cols, i % cols)
            row = (i // cols) + 1

        # 图片卡片
        images = self._current_images()
        for i, path in enumerate(images):
            if not os.path.isfile(path):
                continue
            img_card = ImageCard(path, on_remove=self._remove_image)
            self._grid.addWidget(img_card, row + i // cols, i % cols)

        for c in range(cols):
            self._grid.setColumnStretch(c, 1)

    def _clear_grid(self):
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _toggle_pause(self, checked):
        self._paused = checked
        self._pause_btn.setText("继续" if checked else "暂停")

    def feed_data(self, device_id: str, point_name: str, value: float,
                  filtered_value: Optional[float] = None,
                  timestamp: Optional[float] = None):
        if device_id != self._device_id:
            return
        if point_name not in self._cards:
            return
        self._pending[point_name] = (value, filtered_value)

    def _flush(self):
        if self._paused or not self._pending:
            return
        items = self._pending
        self._pending = {}
        show_flt = self._show_filtered_cb.isChecked()
        for point_name, (raw, flt) in items.items():
            card = self._cards.get(point_name)
            if card:
                card.update_value(raw, flt if show_flt else None)