"""
PyQt6 UCSystemInfo - System monitoring dashboard.

Displays hardware monitoring panels (CPU, GPU, Memory, HDD, Network, Fan)
with live system metrics. Matches Windows TRCC UCSystemInfoOptions.

Reuses system_info.get_all_metrics() for data collection (same as Tkinter version).

Windows Layout (Form1.cs):
- Grid: 4 columns, startX=44, startY=36, addX=300, addY=199
- Each UCSystemInfoOptionsOne: 266x189 panel with 4 metric rows
"""

from PyQt6.QtWidgets import QWidget, QLabel
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPalette, QBrush, QPixmap, QPainter, QColor, QFont

from .assets import load_pixmap, asset_exists
from .constants import Colors

# Import system info (GUI-independent data layer)
try:
    from ..system_info import get_all_metrics
    SYSINFO_AVAILABLE = True
except ImportError:
    SYSINFO_AVAILABLE = False
    def get_all_metrics():
        return {}


# Panel configuration: category -> [(label, metric_key, suffix), ...]
# Matches Tkinter UCSystemInfoDashboard.PANEL_CONFIG exactly
PANEL_CONFIG = {
    'CPU': [
        ('TEMP', 'cpu_temp', '\u00b0C'),
        ('Usage', 'cpu_percent', '%'),
        ('Clock', 'cpu_freq', 'MHz'),
        ('Power', 'cpu_power', 'W'),
    ],
    'GPU': [
        ('TEMP', 'gpu_temp', '\u00b0C'),
        ('Usage', 'gpu_usage', '%'),
        ('Clock', 'gpu_clock', 'MHz'),
        ('Power', 'gpu_power', 'W'),
    ],
    'Memory': [
        ('TEMP', 'mem_temp', '\u00b0C'),
        ('Usage', 'mem_percent', '%'),
        ('Clock', 'mem_clock', 'MHz'),
        ('Available', 'mem_available', 'MB'),
    ],
    'HDD': [
        ('TEMP', 'disk_temp', '\u00b0C'),
        ('Activity', 'disk_activity', '%'),
        ('Read', 'disk_read', 'MB/s'),
        ('Write', 'disk_write', 'MB/s'),
    ],
    'Network': [
        ('UP rate', 'net_up', 'KB/s'),
        ('DL rate', 'net_down', 'KB/s'),
        ('Total UP', 'net_total_up', 'MB'),
        ('Total DL', 'net_total_down', 'MB'),
    ],
    'Fan': [
        ('CPUFAN', 'fan_cpu', 'RPM'),
        ('GPUFAN', 'fan_gpu', 'RPM'),
        ('SSDFAN', 'fan_ssd', 'RPM'),
        ('FAN2', 'fan_sys2', 'RPM'),
    ],
}

# Category to background image mapping
CATEGORY_IMAGES = {
    'CPU': 'Acpu.png',
    'GPU': 'Agpu.png',
    'Memory': 'Adram.png',
    'HDD': 'Ahdd.png',
    'Network': 'Anet.png',
    'Fan': 'Afan.png',
}

# Category colors for value text (matches Tkinter/Windows)
CATEGORY_COLORS = {
    'CPU': '#32C5FF',
    'GPU': '#44D7B6',
    'Memory': '#6DD401',
    'HDD': '#F7B501',
    'Network': '#FA6401',
    'Fan': '#E02020',
}

# Grid layout (from Windows UCSystemInfoOptions.cs)
PANEL_W = 266
PANEL_H = 189
START_X = 44
START_Y = 36
SPACING_X = 300
SPACING_Y = 199
COLUMNS = 4

# Value label positions within each panel (right-aligned)
VALUE_POSITIONS = [
    (240, 52),   # Row 1: Temp
    (240, 86),   # Row 2: Usage
    (240, 121),  # Row 3: Clock
    (240, 156),  # Row 4: Power
]


class SystemInfoPanel(QWidget):
    """Single hardware monitoring panel (matches Windows UCSystemInfoOptionsOne).

    Background is a pre-rendered PNG (Acpu.png etc.).
    Values are overlaid as QLabels at correct positions.
    White border when selected.
    """

    clicked = pyqtSignal(str)  # category name

    def __init__(self, category: str, metrics: list, parent=None):
        super().__init__(parent)
        self.setFixedSize(PANEL_W, PANEL_H)

        self._category = category
        self._metrics = metrics
        self._selected = False
        self._color = CATEGORY_COLORS.get(category, '#888888')
        self._value_labels = []

        # Load background image
        img_name = CATEGORY_IMAGES.get(category, 'Acpu.png')
        self._bg_pixmap = load_pixmap(img_name, PANEL_W, PANEL_H)
        if not self._bg_pixmap.isNull():
            palette = self.palette()
            palette.setBrush(QPalette.ColorRole.Window, QBrush(self._bg_pixmap))
            self.setPalette(palette)
            self.setAutoFillBackground(True)

        # Create value labels
        value_font = QFont('Arial', 10)
        for i, (label_text, metric_key, suffix) in enumerate(metrics):
            if i < len(VALUE_POSITIONS):
                x, y = VALUE_POSITIONS[i]
                lbl = QLabel('--', self)
                lbl.setFont(value_font)
                lbl.setStyleSheet(
                    f"color: {self._color}; background: transparent;"
                )
                lbl.setAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                # Position: right-aligned, so place label ending at x
                lbl_w = 100
                lbl.setGeometry(x - lbl_w, y, lbl_w, 20)
                self._value_labels.append(lbl)

    def update_values(self, metrics_data: dict):
        """Update displayed values from metrics dict."""
        for i, (label_text, metric_key, suffix) in enumerate(self._metrics):
            if i < len(self._value_labels):
                value = metrics_data.get(metric_key)
                if value is not None:
                    if isinstance(value, float):
                        if value >= 1000:
                            text = f"{int(value)}{suffix}"
                        else:
                            text = f"{value:.0f}{suffix}"
                    else:
                        text = f"{value}{suffix}"
                    self._value_labels[i].setText(text)
                else:
                    self._value_labels[i].setText('--')

    def set_selected(self, selected: bool):
        """Set selection state (white border when selected)."""
        self._selected = selected
        self.update()

    def paintEvent(self, event):
        """Draw selection border over background."""
        super().paintEvent(event)
        if self._selected:
            painter = QPainter(self)
            painter.setPen(QColor('white'))
            painter.drawRect(0, 0, self.width() - 1, self.height() - 1)
            painter.end()

    def mousePressEvent(self, event):
        self.clicked.emit(self._category)


class UCSystemInfo(QWidget):
    """System monitoring dashboard showing all hardware panels.

    Windows UCSystemInfoOptions layout:
    - Grid: 4 columns, starting at (44, 36), spacing (300, 199)
    - Panels: CPU, GPU, Memory, HDD, Network, Fan
    - "+" button to add more panels
    - Empty gray placeholder slots

    Matches 1274x800 content area (same as FormCZTV).
    """

    panel_clicked = pyqtSignal(str)  # category name

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(1274, 800)

        self._panels: dict[str, SystemInfoPanel] = {}
        self._selected = 'CPU'
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._update_metrics)

        self._setup_ui()

    def _setup_ui(self):
        """Create the dashboard with hardware panels in grid layout."""
        # Dark background
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(Colors.WINDOW_BG))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        categories = list(PANEL_CONFIG.keys())
        for i, category in enumerate(categories):
            row = i // COLUMNS
            col = i % COLUMNS
            x = START_X + col * SPACING_X
            y = START_Y + row * SPACING_Y

            panel = SystemInfoPanel(category, PANEL_CONFIG[category], self)
            panel.setGeometry(x, y, PANEL_W, PANEL_H)
            panel.clicked.connect(self._on_panel_clicked)
            self._panels[category] = panel

        # "+" button (row 1, col 2 = position after 6 panels)
        add_x = START_X + 2 * SPACING_X
        add_y = START_Y + 1 * SPACING_Y
        add_pixmap = load_pixmap('A\u589e\u52a0\u6570\u7ec4.png', PANEL_W, PANEL_H)
        if not add_pixmap.isNull():
            add_btn = QLabel(self)
            add_btn.setPixmap(add_pixmap)
            add_btn.setGeometry(add_x, add_y, PANEL_W, PANEL_H)
        else:
            add_btn = QLabel("+", self)
            add_btn.setAlignment(Qt.AlignmentFlag.AlignCenter)
            add_btn.setStyleSheet(
                "color: #666; font-size: 48px; background-color: #2D2D2D;"
            )
            add_btn.setGeometry(add_x, add_y, PANEL_W, PANEL_H)

        # Empty placeholder slots
        slot_positions = [
            (3, 1),  # row 1, col 3
        ]
        for col in range(4):
            slot_positions.append((col, 2))

        for (slot_col, slot_row) in slot_positions:
            slot_x = START_X + slot_col * SPACING_X
            slot_y = START_Y + slot_row * SPACING_Y
            slot = QWidget(self)
            slot.setGeometry(slot_x, slot_y, PANEL_W, PANEL_H)
            slot.setStyleSheet("background-color: #2A2A2A;")

        # Select CPU by default
        self._select_panel('CPU')

    def _on_panel_clicked(self, category: str):
        self._select_panel(category)

    def _select_panel(self, category: str):
        """Select a panel (highlight with white border)."""
        for panel in self._panels.values():
            panel.set_selected(False)
        if category in self._panels:
            self._panels[category].set_selected(True)
            self._selected = category
        self.panel_clicked.emit(category)

    def start_updates(self):
        """Start periodic metric updates (1s interval)."""
        self._update_metrics()
        self._update_timer.start(1000)

    def stop_updates(self):
        """Stop periodic metric updates."""
        self._update_timer.stop()

    def _update_metrics(self):
        """Update all panels with current system metrics."""
        if not SYSINFO_AVAILABLE:
            return
        try:
            metrics = get_all_metrics()
            for panel in self._panels.values():
                panel.update_values(metrics)
        except Exception as e:
            print(f"[!] Error updating metrics: {e}")
