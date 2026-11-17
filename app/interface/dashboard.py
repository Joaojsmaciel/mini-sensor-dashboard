"""Janela principal do MINI SENSOR DASHBOARD."""

from __future__ import annotations

import math
import time
from enum import Enum
from typing import List, Optional

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from interface import styles
from interface.components import (
    Card,
    GaugeWidget,
    InfoRow,
    LedIndicator,
    StatTile,
    StatusBadge,
    VibrationIndicator,
    make_app_icon,
    make_divider,
)
from interface.styles import make_font, qcolor
from models.sensor_data import SensorReading
from services.data_processor import DataProcessor
from services.serial_service import PortInfo, SerialWorker, list_serial_ports
from utils import configuration as cfg


# ===========================================================================
# Estados da comunicação
# ===========================================================================
class CommState(Enum):
    DISCONNECTED = ("DESCONECTADO", styles.TEXT_DIM)
    CONNECTING = ("CONECTANDO…", styles.WARNING)
    WAITING = ("AGUARDANDO DADOS", styles.WARNING)
    RECEIVING = ("RECEBENDO DADOS", styles.SUCCESS)
    NO_DATA = ("SEM DADOS", styles.WARNING)
    LOST = ("CONEXÃO PERDIDA", styles.DANGER)
    FAILED = ("FALHA AO CONECTAR", styles.DANGER)

    @property
    def label(self) -> str:
        return self.value[0]

    @property
    def color(self) -> str:
        return self.value[1]

    @property
    def port_open(self) -> bool:
        return self in (CommState.CONNECTING, CommState.WAITING, CommState.RECEIVING, CommState.NO_DATA)


def format_duration(seconds: Optional[float]) -> str:
    if seconds is None or seconds < 0:
        return "—"
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours:d}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes:d}m {secs:02d}s"
    return f"{secs:d}s"


def format_temperature(value: Optional[float]) -> str:
    return f"{value:.1f} °C" if value is not None else "--"


# ===========================================================================
# Cards
# ===========================================================================
class TemperatureCard(Card):
    def __init__(self, parent=None) -> None:
        super().__init__("Temperatura", "DS18B20 · D2", parent)
        self.gauge = GaugeWidget(cfg.GAUGE_MIN_C, cfg.GAUGE_MAX_C,
                                 cfg.TEMPERATURE_WARNING_C, cfg.TEMPERATURE_CRITICAL_C)

        self.min_tile = StatTile("Mínima")
        self.max_tile = StatTile("Máxima")
        self.mean_tile = StatTile("Média")
        self.state_tile = StatTile("Estado do sensor")

        stats = QGridLayout()
        stats.setSpacing(10)
        stats.addWidget(self.min_tile, 0, 0)
        stats.addWidget(self.max_tile, 0, 1)
        stats.addWidget(self.mean_tile, 1, 0)
        stats.addWidget(self.state_tile, 1, 1)
        stats_holder = QWidget()
        stats_holder.setLayout(stats)
        stats_holder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        self._content = QBoxLayout(QBoxLayout.Direction.TopToBottom)
        self._content.setSpacing(16)
        self._content.addWidget(self.gauge, 1)
        self._content.addWidget(stats_holder, 0)
        self.body.addLayout(self._content, 1)

    def resizeEvent(self, event) -> None:  # noqa: N802
        # Card largo e baixo: gauge ao lado das estatísticas; estreito: empilhado.
        wide = self.width() > 640 and self.width() > self.height() * 1.6
        direction = QBoxLayout.Direction.LeftToRight if wide else QBoxLayout.Direction.TopToBottom
        if self._content.direction() != direction:
            self._content.setDirection(direction)
        super().resizeEvent(event)


class VibrationCard(Card):
    def __init__(self, parent=None) -> None:
        super().__init__("Vibração", "SW-420 · D7", parent)
        self.indicator = VibrationIndicator()

        self.state_label = QLabel("SEM DADOS")
        self.state_label.setFont(make_font(17, QFont.Weight.Bold, display=True, letter_spacing=0.5))
        self.state_label.setMinimumWidth(10)
        self.detail_label = QLabel("Aguardando conexão")
        self.detail_label.setStyleSheet(f"color: {styles.TEXT_MUTED};")
        self.events_tile = StatTile("Eventos de vibração")
        self.events_tile.set_value("0")

        text_column = QVBoxLayout()
        text_column.setSpacing(6)
        text_column.addStretch(1)
        text_column.addWidget(self.state_label)
        text_column.addWidget(self.detail_label)
        text_column.addSpacing(8)
        text_column.addWidget(self.events_tile)
        text_column.addStretch(1)

        top = QHBoxLayout()
        top.setSpacing(18)
        top.addWidget(self.indicator, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addLayout(text_column, 1)
        self.body.addLayout(top)

        history_title = QLabel(f"Histórico digital · últimos {cfg.VIBRATION_HISTORY_S} s")
        history_title.setStyleSheet(f"color: {styles.TEXT_MUTED}; font-size: 8.5pt;")
        self.body.addWidget(history_title)

        self.plot = pg.PlotWidget()
        self.plot.setMinimumHeight(90)
        self.plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        style_plot(self.plot)
        plot_item = self.plot.getPlotItem()
        plot_item.setXRange(-cfg.VIBRATION_HISTORY_S, 0, padding=0)
        plot_item.setYRange(-0.15, 1.35, padding=0)
        left = plot_item.getAxis("left")
        left.setTicks([[(0, "0"), (1, "1")]])
        left.setWidth(28)
        plot_item.getAxis("bottom").setLabel("s")
        self.curve = plot_item.plot(
            pen=pg.mkPen(styles.VIBRATION, width=2),
            fillLevel=0,
            brush=pg.mkBrush(qcolor(styles.VIBRATION, 55)),
        )
        self.body.addWidget(self.plot, 1)


class TemperatureChartCard(Card):
    def __init__(self, parent=None) -> None:
        super().__init__(f"Temperatura · últimos {cfg.TEMPERATURE_HISTORY_S // 60} minutos", "", parent)
        self.badge.setVisible(True)

        self.plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(orientation="bottom")})
        self.plot.setMinimumHeight(200)
        style_plot(self.plot)
        plot_item = self.plot.getPlotItem()
        plot_item.getAxis("left").setLabel("Temperatura", units="°C")
        plot_item.getAxis("left").enableAutoSIPrefix(False)
        plot_item.getAxis("left").setWidth(56)
        plot_item.getAxis("bottom").setLabel("Horário")

        self.glow = plot_item.plot(pen=pg.mkPen(qcolor(styles.ACCENT, 45), width=7), connect="finite")
        self.curve = plot_item.plot(pen=pg.mkPen(styles.ACCENT, width=2.2), connect="finite")
        self.last_point = pg.ScatterPlotItem(size=10, pen=pg.mkPen(styles.TEXT, width=1.5),
                                             brush=pg.mkBrush(styles.ACCENT))
        plot_item.addItem(self.last_point)

        self.placeholder = QLabel("Sem dados do sensor de temperatura")
        self.placeholder.setObjectName("Placeholder")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        stack_holder = QWidget()
        stack = QStackedLayout(stack_holder)
        stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        stack.addWidget(self.placeholder)
        stack.addWidget(self.plot)
        self.placeholder.raise_()
        self.body.addWidget(stack_holder, 1)


class InfoCard(Card):
    def __init__(self, parent=None) -> None:
        super().__init__("Informações do sistema", None, parent)
        self.port_row = InfoRow("Porta COM")
        self.comm_row = InfoRow("Estado da comunicação")
        self.rate_row = InfoRow("Taxa de recebimento")
        self.app_uptime_row = InfoRow("Tempo de funcionamento")
        self.connected_row = InfoRow("Tempo conectado")
        self.board_uptime_row = InfoRow("Arduino ligado há")
        self.valid_row = InfoRow("Mensagens válidas")
        self.errors_row = InfoRow("Erros de leitura")
        self.invalid_row = InfoRow("   · mensagens inválidas")
        self.sensor_errors_row = InfoRow("   · falhas do DS18B20")
        self.last_error_row = InfoRow("Último erro")

        groups = [
            [self.port_row, self.comm_row, self.rate_row],
            [self.app_uptime_row, self.connected_row, self.board_uptime_row],
            [self.valid_row, self.errors_row, self.invalid_row, self.sensor_errors_row, self.last_error_row],
        ]
        column = QVBoxLayout()
        column.setSpacing(0)
        for index, group in enumerate(groups):
            if index:
                column.addSpacing(6)
                column.addWidget(make_divider())
                column.addSpacing(6)
            for row in group:
                column.addWidget(row)
        column.addStretch(1)
        self.body.addLayout(column, 1)

        self.clear_button = QPushButton("Limpar histórico e estatísticas")
        self.clear_button.setObjectName("Secondary")
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.body.addWidget(self.clear_button)


def style_plot(plot: pg.PlotWidget) -> None:
    """Aplica o visual do tema escuro a um gráfico do PyQtGraph."""
    plot.setBackground(styles.SURFACE)
    plot.setAntialiasing(True)
    plot.setMenuEnabled(False)
    plot.setMouseEnabled(x=False, y=False)
    plot_item = plot.getPlotItem()
    plot_item.hideButtons()
    plot_item.showGrid(x=True, y=True, alpha=0.10)
    plot_item.getViewBox().setDefaultPadding(0)
    axis_pen = pg.mkPen(styles.BORDER_STRONG)
    text_pen = pg.mkPen(styles.TEXT_MUTED)
    tick_font = make_font(8.5)
    for name in ("left", "bottom"):
        axis = plot_item.getAxis(name)
        axis.setPen(axis_pen)
        axis.setTextPen(text_pen)
        axis.setTickFont(tick_font)
        axis.label.setFont(tick_font)
    plot_item.getAxis("left").setStyle(tickTextOffset=6)
    plot_item.getAxis("bottom").setStyle(tickTextOffset=6)


# ===========================================================================
# Janela principal
# ===========================================================================
class DashboardWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(cfg.APP_NAME)
        self.setWindowIcon(make_app_icon())
        self.setMinimumSize(cfg.WINDOW_MIN_WIDTH, cfg.WINDOW_MIN_HEIGHT)
        self.resize(*cfg.WINDOW_DEFAULT_SIZE)

        self.processor = DataProcessor()
        self.worker: Optional[SerialWorker] = None
        self._stopping = False  # Desconectar clicado, aguardando a thread encerrar
        self.state = CommState.DISCONNECTED
        self.connected_port: Optional[str] = None
        self.connection_started_at: Optional[float] = None
        self.app_started_at = time.monotonic()
        self.last_vibration_event_at: Optional[float] = None
        self._ports: Optional[List[PortInfo]] = None  # None = recarregar a lista
        self._layout_mode: Optional[str] = None
        self._has_new_data = False

        self._build_ui()
        self._connect_signals()
        self.refresh_ports()
        self._set_state(CommState.DISCONNECTED)
        self._render_sensors()
        self._update_status_panel()

        self.chart_timer = QTimer(self)
        self.chart_timer.timeout.connect(self._update_charts)
        self.chart_timer.start(cfg.UI_REFRESH_MS)

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._on_status_tick)
        self.status_timer.start(cfg.STATUS_REFRESH_MS)

        self.port_timer = QTimer(self)
        self.port_timer.timeout.connect(self._on_port_scan_tick)
        self.port_timer.start(cfg.PORT_SCAN_INTERVAL_MS)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_header())

        # Aviso de erro fica fora da área de rolagem: sempre visível.
        self.notice = QLabel()
        self.notice.setObjectName("Notice")
        self.notice.setWordWrap(True)
        self.notice.hide()
        notice_holder = QWidget()
        notice_layout = QVBoxLayout(notice_holder)
        notice_layout.setContentsMargins(20, 12, 20, 0)
        notice_layout.addWidget(self.notice)
        root_layout.addWidget(notice_holder)
        self.notice_holder = notice_holder
        notice_holder.hide()

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("Content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 16, 20, 20)
        content_layout.setSpacing(14)

        self.temperature_card = TemperatureCard()
        self.vibration_card = VibrationCard()
        self.chart_card = TemperatureChartCard()
        self.info_card = InfoCard()

        self.grid = QGridLayout()
        self.grid.setSpacing(16)
        content_layout.addLayout(self.grid, 1)
        self.scroll.setWidget(content)
        root_layout.addWidget(self.scroll, 1)
        self.setCentralWidget(root)
        self._apply_layout(self._layout_for_width(cfg.WINDOW_DEFAULT_SIZE[0]))

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        self.header_layout = QGridLayout(header)
        self.header_layout.setContentsMargins(22, 14, 22, 14)
        self.header_layout.setHorizontalSpacing(18)
        self.header_layout.setVerticalSpacing(12)

        # Identidade
        brand = QWidget()
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(make_app_icon().pixmap(36, 36))
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel(cfg.APP_NAME)
        title.setObjectName("AppTitle")
        title.setFont(make_font(14, QFont.Weight.Bold, display=True, letter_spacing=2.2))
        subtitle = QLabel(f"{cfg.APP_SUBTITLE}  ·  v{cfg.APP_VERSION}")
        subtitle.setObjectName("AppSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        brand_layout.addWidget(logo)
        brand_layout.addLayout(titles)
        brand_layout.addStretch(1)
        self.brand = brand

        # Indicador USB + estado
        usb_pill = QFrame()
        usb_pill.setObjectName("UsbPill")
        usb_layout = QHBoxLayout(usb_pill)
        usb_layout.setContentsMargins(8, 3, 12, 3)
        usb_layout.setSpacing(4)
        self.usb_led = LedIndicator(10)
        usb_label = QLabel("USB")
        usb_label.setObjectName("UsbLabel")
        usb_layout.addWidget(self.usb_led)
        usb_layout.addWidget(usb_label)
        self.state_badge = StatusBadge()

        # Controles de conexão
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(230)
        self.port_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.port_combo.setToolTip("Porta COM do Arduino (★ = provável placa Arduino)")
        self.refresh_button = QPushButton("⟳")
        self.refresh_button.setObjectName("Icon")
        self.refresh_button.setToolTip("Atualizar lista de portas")
        self.connect_button = QPushButton("Conectar")
        self.connect_button.setObjectName("Primary")
        self.disconnect_button = QPushButton("Desconectar")
        self.disconnect_button.setObjectName("Danger")
        for button in (self.refresh_button, self.connect_button, self.disconnect_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)

        def group(*widgets, stretch_first: bool = False) -> QWidget:
            holder = QWidget()
            layout = QHBoxLayout(holder)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(10)
            for index, widget in enumerate(widgets):
                layout.addWidget(widget, 1 if (stretch_first and index == 0) else 0)
            return holder

        # Grupos reorganizados conforme a largura da janela (ver _apply_layout).
        self.status_group = group(usb_pill, self.state_badge)
        self.port_group = group(self.port_combo, self.refresh_button, stretch_first=True)
        self.button_group = group(self.connect_button, self.disconnect_button)
        return header

    def _connect_signals(self) -> None:
        self.connect_button.clicked.connect(self.connect_serial)
        self.disconnect_button.clicked.connect(self.disconnect_serial)
        self.refresh_button.clicked.connect(self.refresh_ports)
        self.info_card.clear_button.clicked.connect(self.clear_history)

    # ------------------------------------------------------------- layout
    def _layout_for_width(self, width: int) -> str:
        if width >= cfg.LAYOUT_WIDE_MIN_WIDTH:
            return "wide"
        if width >= cfg.LAYOUT_MEDIUM_MIN_WIDTH:
            return "medium"
        return "narrow"

    def _apply_layout(self, mode: str) -> None:
        if mode == self._layout_mode:
            return
        self._layout_mode = mode
        cards = (self.temperature_card, self.vibration_card, self.info_card, self.chart_card)
        for card in cards:
            self.grid.removeWidget(card)
        for i in range(4):
            self.grid.setColumnStretch(i, 0)
            self.grid.setRowStretch(i, 0)

        if mode == "wide":
            self.grid.addWidget(self.temperature_card, 0, 0)
            self.grid.addWidget(self.vibration_card, 0, 1)
            self.grid.addWidget(self.info_card, 0, 2, 2, 1)
            self.grid.addWidget(self.chart_card, 1, 0, 1, 2)
            for column, stretch in enumerate((10, 10, 7)):
                self.grid.setColumnStretch(column, stretch)
            self.grid.setRowStretch(0, 11)
            self.grid.setRowStretch(1, 9)
        elif mode == "medium":
            self.grid.addWidget(self.temperature_card, 0, 0)
            self.grid.addWidget(self.vibration_card, 0, 1)
            self.grid.addWidget(self.chart_card, 1, 0, 1, 2)
            self.grid.addWidget(self.info_card, 2, 0, 1, 2)
            self.grid.setColumnStretch(0, 1)
            self.grid.setColumnStretch(1, 1)
            self.grid.setRowStretch(1, 1)
        else:
            for row, card in enumerate((self.temperature_card, self.vibration_card,
                                        self.chart_card, self.info_card)):
                self.grid.addWidget(card, row, 0)
            self.grid.setColumnStretch(0, 1)

        # Cabeçalho: 1 linha (largo), 2 linhas (médio) ou 4 linhas (estreito).
        header = self.header_layout
        groups = (self.brand, self.status_group, self.port_group, self.button_group)
        for widget in groups:
            header.removeWidget(widget)
        for column in range(5):
            header.setColumnStretch(column, 0)
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        if mode == "wide":
            header.addWidget(self.brand, 0, 0)
            header.addWidget(self.status_group, 0, 2, right)
            header.addWidget(self.port_group, 0, 3)
            header.addWidget(self.button_group, 0, 4)
            header.setColumnStretch(1, 1)
            self.port_combo.setMinimumWidth(240)
        elif mode == "medium":
            header.addWidget(self.brand, 0, 0, 1, 2)
            header.addWidget(self.status_group, 0, 2, right)
            header.addWidget(self.port_group, 1, 0, 1, 2)
            header.addWidget(self.button_group, 1, 2)
            header.setColumnStretch(1, 1)
            self.port_combo.setMinimumWidth(200)
        else:
            header.addWidget(self.brand, 0, 0, 1, 3)
            header.addWidget(self.status_group, 1, 0, 1, 3, Qt.AlignmentFlag.AlignLeft)
            header.addWidget(self.port_group, 2, 0, 1, 3)
            header.addWidget(self.button_group, 3, 0, 1, 3, Qt.AlignmentFlag.AlignLeft)
            header.setColumnStretch(0, 1)
            self.port_combo.setMinimumWidth(120)

        # Em layouts empilhados os cards precisam de altura mínima para rolar.
        stacked = mode != "wide"
        self.temperature_card.setMinimumHeight(430 if mode == "narrow" else 400 if stacked else 0)
        self.vibration_card.setMinimumHeight(400 if stacked else 0)
        self.chart_card.setMinimumHeight(340 if stacked else 0)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_layout(self._layout_for_width(self.width()))

    # ------------------------------------------------------------- portas
    def refresh_ports(self) -> None:
        if self.state.port_open:
            return
        try:
            ports = list_serial_ports()
        except Exception as exc:  # falha rara do driver de enumeração
            self._show_notice(f"Não foi possível listar as portas COM: {exc}")
            ports = []
        if self._ports is not None and [p.device for p in ports] == [p.device for p in self._ports]:
            return
        previous = self.port_combo.currentData()
        self._ports = ports
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        if ports:
            for port in ports:
                self.port_combo.addItem(port.label, port.device)
            index = self.port_combo.findData(previous) if previous else -1
            self.port_combo.setCurrentIndex(index if index >= 0 else 0)
        else:
            self.port_combo.addItem("Nenhuma porta COM encontrada", None)
        self.port_combo.blockSignals(False)
        self._update_controls()

    def _on_port_scan_tick(self) -> None:
        if not self.state.port_open:
            self.refresh_ports()

    # ------------------------------------------------------------ conexão
    def connect_serial(self) -> None:
        port = self.port_combo.currentData()
        if not port or self.worker is not None:
            return
        self._hide_notice()
        self.processor.mark_connection_start()
        self.connected_port = port
        self.connection_started_at = time.monotonic()
        self._set_state(CommState.CONNECTING)

        worker = SerialWorker(port, cfg.BAUD_RATE)
        worker.connection_opened.connect(self._on_connection_opened)
        worker.connection_failed.connect(self._on_connection_failed)
        worker.connection_closed.connect(self._on_connection_closed)
        worker.reading_received.connect(self._on_reading)
        worker.invalid_message.connect(self._on_invalid_message)
        worker.finished.connect(worker.deleteLater)
        self.worker = worker
        self._update_controls()
        worker.start()

    def disconnect_serial(self) -> None:
        if self.worker is not None:
            self._stopping = True
            self._update_controls()
            self.worker.stop()

    def _release_worker(self) -> None:
        if self.worker is not None:
            self.worker.wait(2000)
            self.worker = None
        self._stopping = False

    def _on_connection_opened(self, port: str) -> None:
        self.connection_started_at = time.monotonic()
        self._set_state(CommState.WAITING)

    def _on_connection_failed(self, message: str) -> None:
        self._release_worker()
        self.connection_started_at = None
        self._set_state(CommState.FAILED)
        self._show_notice(f"Não foi possível abrir {self.connected_port}: {message}")
        self.refresh_ports()

    def _on_connection_closed(self, user_requested: bool, reason: str) -> None:
        self._release_worker()
        self.connection_started_at = None
        if user_requested:
            self._set_state(CommState.DISCONNECTED)
            self._hide_notice()
        else:
            self._set_state(CommState.LOST)
            self._show_notice(f"{reason} Reconecte o cabo USB, selecione a porta e clique em Conectar.")
        self._ports = None  # força recarregar a lista (a porta pode ter mudado)
        self.refresh_ports()

    # -------------------------------------------------------------- dados
    def _on_reading(self, reading: SensorReading) -> None:
        if self.worker is None:
            return  # mensagem tardia de uma conexão já encerrada
        result = self.processor.process(reading)
        if result.vibration_event:
            self.last_vibration_event_at = reading.received_monotonic
        self._has_new_data = True
        if self.state != CommState.RECEIVING:
            self._set_state(CommState.RECEIVING)
        self.usb_led.pulse()
        self._render_sensors()

    def _on_invalid_message(self, reason: str) -> None:
        self.processor.register_invalid_message(reason)

    def clear_history(self) -> None:
        self.processor.reset()
        self.last_vibration_event_at = None
        self._has_new_data = True
        self._render_sensors()
        self._update_charts(force=True)
        self._update_status_panel()

    # ------------------------------------------------------------- estado
    def _set_state(self, state: CommState) -> None:
        self.state = state
        self.state_badge.set_status(state.label, state.color)
        self.usb_led.set_color(state.color)
        self._update_controls()
        self._render_sensors()

    def _update_controls(self) -> None:
        port_open = self.state.port_open
        has_port = self.port_combo.currentData() is not None
        self.connect_button.setEnabled(not port_open and self.worker is None and has_port)
        self.disconnect_button.setEnabled(port_open and self.worker is not None and not self._stopping)
        self.port_combo.setEnabled(not port_open)
        self.refresh_button.setEnabled(not port_open)

    def _show_notice(self, text: str) -> None:
        self.notice.setText(text)
        self.notice.show()
        self.notice_holder.show()

    def _hide_notice(self) -> None:
        self.notice_holder.hide()

    def _fresh_reading(self) -> Optional[SensorReading]:
        """Última leitura, apenas se a comunicação estiver ativa e recente."""
        if self.state != CommState.RECEIVING:
            return None
        return self.processor.last_reading

    def _render_sensors(self) -> None:
        if not hasattr(self, "temperature_card"):
            return
        reading = self._fresh_reading()
        temp_card = self.temperature_card
        vib_card = self.vibration_card

        # ---- Temperatura
        if reading is None:
            temp_card.gauge.set_value(None)
            if self.state in (CommState.WAITING, CommState.CONNECTING):
                temp_card.state_tile.set_value("AGUARDANDO", styles.WARNING)
            elif self.state == CommState.NO_DATA:
                temp_card.state_tile.set_value("SEM DADOS", styles.WARNING)
            else:
                temp_card.state_tile.set_value("DESCONECTADO", styles.TEXT_DIM)
        elif reading.temperature_valid:
            temp_card.gauge.set_value(reading.temperature)
            temp_card.state_tile.set_value("OK", styles.SUCCESS)
        else:
            temp_card.gauge.set_value(None)
            temp_card.state_tile.set_value("FALHA DE LEITURA", styles.DANGER)

        stats = self.processor.stats
        temp_card.min_tile.set_value(format_temperature(stats.minimum))
        temp_card.max_tile.set_value(format_temperature(stats.maximum))
        temp_card.mean_tile.set_value(format_temperature(stats.mean))

        # ---- Vibração
        if reading is None:
            vib_card.indicator.set_state(None)
            if self.state in (CommState.WAITING, CommState.CONNECTING):
                vib_card.state_label.setText("AGUARDANDO")
                vib_card.state_label.setStyleSheet(f"color: {styles.WARNING};")
            else:
                vib_card.state_label.setText("SEM DADOS")
                vib_card.state_label.setStyleSheet(f"color: {styles.TEXT_DIM};")
        elif reading.vibration_detected:
            vib_card.indicator.set_state(True)
            vib_card.state_label.setText("VIBRAÇÃO DETECTADA")
            vib_card.state_label.setStyleSheet(f"color: {styles.VIBRATION};")
        else:
            vib_card.indicator.set_state(False)
            vib_card.state_label.setText("NORMAL")
            vib_card.state_label.setStyleSheet(f"color: {styles.SUCCESS};")

        vib_card.events_tile.set_value(f"{self.processor.vibration_events}")
        self._update_vibration_detail()

        # ---- Selo do gráfico
        if reading is not None and reading.temperature_valid:
            self.chart_card.badge.set_status(f"ATUAL {reading.temperature:.2f} °C", styles.ACCENT)
        elif reading is not None:
            self.chart_card.badge.set_status("FALHA DE LEITURA", styles.DANGER)
        else:
            self.chart_card.badge.set_status("SEM DADOS", styles.TEXT_DIM)

    def _update_vibration_detail(self) -> None:
        detail = self.vibration_card.detail_label
        if self.last_vibration_event_at is not None:
            ago = time.monotonic() - self.last_vibration_event_at
            detail.setText(f"Último evento há {format_duration(ago)}")
        elif self.state == CommState.RECEIVING:
            detail.setText("Nenhum evento registrado")
        elif self.state.port_open:
            detail.setText("Aguardando dados do Arduino")
        else:
            detail.setText("Conecte-se a uma porta COM")

    # ------------------------------------------------------------- timers
    def _on_status_tick(self) -> None:
        now = time.monotonic()
        if self.state == CommState.RECEIVING:
            since_last = self.processor.seconds_since_last_message(now)
            if since_last is not None and since_last > cfg.DATA_TIMEOUT_S:
                self._set_state(CommState.NO_DATA)
        elif self.state == CommState.WAITING and self.connection_started_at is not None:
            # O Uno reinicia ao abrir a porta (~2 s); considera uma margem extra.
            if now - self.connection_started_at > cfg.DATA_TIMEOUT_S + 3:
                self._set_state(CommState.NO_DATA)
        elif self.state == CommState.CONNECTING and self.connection_started_at is not None:
            # Alguns drivers (ex.: portas COM Bluetooth) demoram a abrir a porta.
            if now - self.connection_started_at > cfg.CONNECT_SLOW_WARNING_S and self.notice_holder.isHidden():
                self._show_notice(f"A abertura de {self.connected_port} está demorando. Confirme se é a porta "
                                  "do Arduino (portas Bluetooth podem travar ao abrir).")
        self._update_vibration_detail()
        self._update_status_panel()

    def _update_status_panel(self) -> None:
        info = self.info_card
        now = time.monotonic()
        processor = self.processor
        info.port_row.set_value(self.connected_port if self.state.port_open and self.connected_port else "—")
        info.comm_row.set_value(self.state.label, self.state.color)

        rate = processor.message_rate(now) if self.state.port_open else 0.0
        info.rate_row.set_value(f"{rate:.1f} msg/s" if self.state.port_open else "—")
        info.app_uptime_row.set_value(format_duration(now - self.app_started_at))
        info.connected_row.set_value(
            format_duration(now - self.connection_started_at)
            if self.state.port_open and self.connection_started_at is not None else "—")
        reading = processor.last_reading
        info.board_uptime_row.set_value(
            format_duration(reading.device_timestamp_ms / 1000) if reading and self.state.port_open else "—")

        info.valid_row.set_value(f"{processor.valid_messages}")
        total_errors = processor.total_read_errors
        info.errors_row.set_value(f"{total_errors}", styles.DANGER if total_errors else styles.TEXT)
        info.invalid_row.set_value(f"{processor.invalid_messages}",
                                   styles.WARNING if processor.invalid_messages else styles.TEXT_MUTED)
        info.sensor_errors_row.set_value(f"{processor.sensor_read_errors}",
                                         styles.WARNING if processor.sensor_read_errors else styles.TEXT_MUTED)
        reason = processor.last_invalid_reason
        if processor.sensor_read_errors and (reading is not None and not reading.temperature_valid):
            reason = "DS18B20 sem leitura válida"
        short = reason if not reason or len(reason) <= 30 else reason[:29] + "…"
        info.last_error_row.set_value(short or "—", styles.WARNING if reason else styles.TEXT_MUTED,
                                      tooltip=reason or "")

    def _update_charts(self, force: bool = False) -> None:
        now = time.time()
        # ---- Temperatura
        xs, ys = self.processor.temperature_series(now)
        chart = self.chart_card
        plot_item = chart.plot.getPlotItem()
        plot_item.setXRange(now - cfg.TEMPERATURE_HISTORY_S, now, padding=0)
        finite = [v for v in ys if not math.isnan(v)]
        if self._has_new_data or force:
            if xs:
                x_array = np.asarray(xs, dtype=float)
                y_array = np.asarray(ys, dtype=float)
                chart.curve.setData(x_array, y_array, connect="finite")
                chart.glow.setData(x_array, y_array, connect="finite")
            else:
                chart.curve.setData([], [])
                chart.glow.setData([], [])
            last_valid = next(((x, y) for x, y in zip(reversed(xs), reversed(ys)) if not math.isnan(y)), None)
            chart.last_point.setData([last_valid[0]] if last_valid else [], [last_valid[1]] if last_valid else [])
            if finite:
                low, high = min(finite), max(finite)
                padding = max(0.4, (high - low) * 0.18)
                if high - low < 1.0:
                    center = (high + low) / 2
                    low, high = center - 0.5, center + 0.5
                plot_item.setYRange(low - padding, high + padding, padding=0)
            else:
                plot_item.setYRange(cfg.GAUGE_MIN_C, cfg.GAUGE_MAX_C, padding=0)
        chart.placeholder.setVisible(not finite)

        # ---- Vibração (sinal digital em degraus)
        vxs, vys = self.processor.vibration_series(now)
        if vxs:
            step_x: List[float] = []
            step_y: List[float] = []
            for i, (x, y) in enumerate(zip(vxs, vys)):
                if i:
                    step_x.append(x)
                    step_y.append(step_y[-1])
                step_x.append(x)
                step_y.append(float(y))
            if self.state == CommState.RECEIVING:
                step_x.append(0.0)  # o último estado continua válido até agora
                step_y.append(step_y[-1])
            self.vibration_card.curve.setData(step_x, step_y)
        else:
            self.vibration_card.curve.setData([], [])
        self._has_new_data = False

    # -------------------------------------------------------------- saída
    def closeEvent(self, event) -> None:  # noqa: N802
        for timer in (self.chart_timer, self.status_timer, self.port_timer):
            timer.stop()
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait(2000)
        super().closeEvent(event)
