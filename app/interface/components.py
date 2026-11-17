"""Componentes visuais reutilizáveis do dashboard.

Todos os componentes desenhados à mão (gauge, LEDs, indicador de vibração)
usam QPainter, para manter a aparência consistente e independente do tema do
sistema operacional.
"""

from __future__ import annotations

import math
import time
from typing import Optional

from PyQt6.QtCore import (
    QEasingCurve,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from interface import styles
from interface.styles import make_font, qcolor, rgba


# ===========================================================================
# Estrutura
# ===========================================================================
class StatusBadge(QLabel):
    """Pílula colorida com um texto curto de estado."""

    def __init__(self, text: str = "", color: str = styles.TEXT_DIM, parent=None) -> None:
        super().__init__(parent)
        self.setFont(make_font(8, QFont.Weight.DemiBold, letter_spacing=0.8))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._text = None
        self._color = None
        self.set_status(text, color)

    def set_status(self, text: str, color: str) -> None:
        if text == self._text and color == self._color:
            return
        self._text, self._color = text, color
        self.setText(text)
        self.setStyleSheet(
            f"color: {color}; background-color: {rgba(color, 0.13)};"
            f"border: 1px solid {rgba(color, 0.35)}; border-radius: 10px; padding: 3px 10px;"
        )


class Card(QFrame):
    """Painel com cantos arredondados, título e um selo opcional."""

    def __init__(self, title: str, badge_text: Optional[str] = None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 18)
        outer.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(10)
        accent = QFrame()
        accent.setFixedSize(3, 14)
        accent.setStyleSheet(f"background-color: {styles.ACCENT}; border-radius: 1px;")
        self.title_label = QLabel(title.upper())
        self.title_label.setObjectName("CardTitle")
        self.title_label.setFont(make_font(8.5, QFont.Weight.DemiBold, letter_spacing=1.4))
        header.addWidget(accent)
        header.addWidget(self.title_label)
        header.addStretch(1)
        self.badge = StatusBadge(badge_text or "", styles.TEXT_MUTED)
        self.badge.setVisible(badge_text is not None)
        header.addWidget(self.badge)
        outer.addLayout(header)

        self.body = QVBoxLayout()
        self.body.setSpacing(14)
        outer.addLayout(self.body, 1)


class StatTile(QFrame):
    """Bloco com um título pequeno e um valor em destaque."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("StatTile")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("StatTitle")
        self.value_label = QLabel("--")
        self.value_label.setFont(make_font(15, QFont.Weight.DemiBold, display=True))
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)

    def set_value(self, text: str, color: str = styles.TEXT) -> None:
        self.value_label.setText(text)
        self.value_label.setStyleSheet(f"color: {color};")


class InfoRow(QWidget):
    """Linha 'chave ........ valor' usada no painel de informações."""

    def __init__(self, key: str, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(12)
        self.key_label = QLabel(key)
        self.key_label.setObjectName("InfoKey")
        self.value_label = QLabel("—")
        self.value_label.setFont(make_font(10, QFont.Weight.DemiBold))
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.key_label)
        layout.addStretch(1)
        layout.addWidget(self.value_label)

    def set_value(self, text: str, color: str = styles.TEXT, tooltip: str = "") -> None:
        self.value_label.setText(text)
        self.value_label.setStyleSheet(f"color: {color};")
        self.value_label.setToolTip(tooltip)


def make_divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFrameShape(QFrame.Shape.NoFrame)
    return line


# ===========================================================================
# LED de estado
# ===========================================================================
class LedIndicator(QWidget):
    """LED circular com brilho; ``pulse()`` acende rapidamente a cada mensagem."""

    def __init__(self, diameter: int = 12, parent=None) -> None:
        super().__init__(parent)
        self._diameter = diameter
        self._color = QColor(styles.TEXT_DIM)
        self._pulse = 0.0
        self.setFixedSize(diameter * 2, diameter * 2)
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(450)
        self._animation.setStartValue(1.0)
        self._animation.setEndValue(0.0)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._on_pulse)

    def set_color(self, hex_color: str) -> None:
        color = QColor(hex_color)
        if color != self._color:
            self._color = color
            self.update()

    def pulse(self) -> None:
        self._animation.stop()
        self._animation.start()

    def _on_pulse(self, value) -> None:
        self._pulse = float(value)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.width() / 2, self.height() / 2)
        radius = self._diameter / 2

        glow = QRadialGradient(center, radius * 2)
        glow_color = QColor(self._color)
        glow_color.setAlpha(int(70 + 110 * self._pulse))
        glow.setColorAt(0.0, glow_color)
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(center, radius * 2, radius * 2)

        core = QColor(self._color).lighter(int(100 + 40 * self._pulse))
        painter.setBrush(core)
        painter.drawEllipse(center, radius * 0.75, radius * 0.75)


# ===========================================================================
# Gauge de temperatura
# ===========================================================================
class GaugeWidget(QWidget):
    """Gauge em arco de 270°.

    O número central sempre mostra o valor real recebido; apenas o arco é
    animado entre leituras, para não exibir valores intermediários.
    """

    START_ANGLE = 225.0
    SPAN_ANGLE = 270.0

    def __init__(self, minimum: float, maximum: float, warning: float, critical: float,
                 unit: str = "°C", parent=None) -> None:
        super().__init__(parent)
        self.minimum, self.maximum = minimum, maximum
        self.warning, self.critical = warning, critical
        self.unit = unit
        self._value: Optional[float] = None
        self._arc_value: Optional[float] = None
        self.setMinimumSize(190, 170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._animation = QVariantAnimation(self)
        self._animation.setDuration(500)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._on_animation)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(260, 230)

    def set_value(self, value: Optional[float]) -> None:
        if value == self._value:
            return
        self._value = value
        self._animation.stop()
        if value is None:
            self._arc_value = None
            self.update()
            return
        start = self._arc_value if self._arc_value is not None else self.minimum
        self._animation.setStartValue(float(start))
        self._animation.setEndValue(float(value))
        self._animation.start()

    def _on_animation(self, value) -> None:
        self._arc_value = float(value)
        self.update()

    def _fraction(self, value: float) -> float:
        span = self.maximum - self.minimum
        return max(0.0, min(1.0, (value - self.minimum) / span)) if span else 0.0

    def _color_for(self, value: Optional[float]) -> QColor:
        if value is None:
            return QColor(styles.TEXT_DIM)
        if value >= self.critical:
            return QColor(styles.DANGER)
        if value >= self.warning:
            return QColor(styles.WARNING)
        return QColor(styles.ACCENT)

    def _zone_name(self, value: Optional[float]) -> str:
        if value is None:
            return "SEM LEITURA"
        if value >= self.critical:
            return "CRÍTICA"
        if value >= self.warning:
            return "ELEVADA"
        return "NORMAL"

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w, h = self.width(), self.height()
        # Extensão do desenho em relação a r (incluindo o brilho do arco):
        # largura ~2,12r e altura ~1,84r (arco de 270° aberto embaixo).
        r = max(40.0, min((w - 8) / 2.12, (h - 8) / 1.84))
        thickness = r * 0.10
        cx = w / 2
        cy = (h - 1.84 * r) / 2 + 1.06 * r
        arc_r = r - thickness / 2
        arc_rect = QRectF(cx - arc_r, cy - arc_r, arc_r * 2, arc_r * 2)

        def angle_for(value: float) -> float:
            return self.START_ANGLE - self.SPAN_ANGLE * self._fraction(value)

        def point(angle_deg: float, radius: float) -> QPointF:
            rad = math.radians(angle_deg)
            return QPointF(cx + radius * math.cos(rad), cy - radius * math.sin(rad))

        # Trilho
        track_pen = QPen(qcolor(styles.SURFACE_ALT), thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.drawArc(arc_rect, int(self.START_ANGLE * 16), int(-self.SPAN_ANGLE * 16))

        # Faixas de alerta (âmbar e vermelho) em um anel fino interno
        zone_r = arc_r - thickness * 1.05
        zone_rect = QRectF(cx - zone_r, cy - zone_r, zone_r * 2, zone_r * 2)
        for start, end, color in ((self.warning, self.critical, styles.WARNING),
                                  (self.critical, self.maximum, styles.DANGER)):
            a0, a1 = angle_for(start), angle_for(end)
            painter.setPen(QPen(qcolor(color, 150), max(2.0, thickness * 0.22), Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.FlatCap))
            painter.drawArc(zone_rect, int(a0 * 16), int((a1 - a0) * 16))

        # Marcas da escala
        tick_outer = zone_r - thickness * 0.45
        label_font = make_font(max(6.5, r * 0.062), QFont.Weight.Normal)
        painter.setFont(label_font)
        step = 5.0
        steps = int(round((self.maximum - self.minimum) / step))
        for i in range(steps + 1):
            value = self.minimum + i * step
            major = (i % 2 == 0)
            angle = angle_for(value)
            length = thickness * (0.75 if major else 0.4)
            painter.setPen(QPen(qcolor(styles.TEXT_MUTED if major else styles.TEXT_DIM), 1.4 if major else 1.0))
            painter.drawLine(point(angle, tick_outer), point(angle, tick_outer - length))
            if major:
                label_pos = point(angle, tick_outer - length - r * 0.11)
                text_rect = QRectF(label_pos.x() - 20, label_pos.y() - 9, 40, 18)
                painter.setPen(qcolor(styles.TEXT_DIM))
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, f"{value:.0f}")

        # Arco do valor (animado) com brilho
        if self._arc_value is not None:
            color = self._color_for(self._value)
            span = -self.SPAN_ANGLE * self._fraction(self._arc_value)
            glow = QColor(color)
            glow.setAlpha(45)
            painter.setPen(QPen(glow, thickness * 2.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(arc_rect, int(self.START_ANGLE * 16), int(span * 16))
            painter.setPen(QPen(color, thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(arc_rect, int(self.START_ANGLE * 16), int(span * 16))
            tip = point(self.START_ANGLE + span, arc_r)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(qcolor(styles.TEXT))
            painter.drawEllipse(tip, thickness * 0.30, thickness * 0.30)

        # Textos centrais (sempre o valor real, sem interpolação)
        value_text = f"{self._value:.1f}" if self._value is not None else "--.-"
        value_font = make_font(10, QFont.Weight.DemiBold, display=True)
        value_font.setPixelSize(max(18, int(r * 0.40)))
        painter.setFont(value_font)
        painter.setPen(qcolor(styles.TEXT if self._value is not None else styles.TEXT_DIM))
        value_rect = QRectF(cx - r, cy - r * 0.34, r * 2, r * 0.46)
        painter.drawText(value_rect, Qt.AlignmentFlag.AlignCenter, value_text)

        unit_font = make_font(10, QFont.Weight.Normal)
        unit_font.setPixelSize(max(10, int(r * 0.13)))
        painter.setFont(unit_font)
        painter.setPen(qcolor(styles.TEXT_MUTED))
        painter.drawText(QRectF(cx - r, cy + r * 0.12, r * 2, r * 0.18), Qt.AlignmentFlag.AlignCenter, self.unit)

        zone_font = make_font(8, QFont.Weight.DemiBold, letter_spacing=1.2)
        zone_font.setPixelSize(max(9, int(r * 0.085)))
        painter.setFont(zone_font)
        painter.setPen(self._color_for(self._value))
        painter.drawText(QRectF(cx - r, cy + r * 0.48, r * 2, r * 0.2), Qt.AlignmentFlag.AlignCenter,
                         self._zone_name(self._value))


# ===========================================================================
# Indicador de vibração
# ===========================================================================
class VibrationIndicator(QWidget):
    """Círculo animado: ondas se expandindo durante a vibração.

    Estados: None (sem dados), False (normal), True (vibração detectada).
    A animação roda apenas enquanto há vibração, sem custo de CPU em repouso.
    """

    RING_PERIOD_S = 1.1

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._state: Optional[bool] = None
        self._phase = 0.0
        self._last_tick = time.monotonic()
        self.setMinimumSize(120, 120)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(132, 132)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def set_state(self, state: Optional[bool]) -> None:
        if state == self._state:
            return
        self._state = state
        if state:
            self._last_tick = time.monotonic()
            self._timer.start()
        else:
            self._timer.stop()
            self._phase = 0.0
        self.update()

    def _tick(self) -> None:
        now = time.monotonic()
        self._phase = (self._phase + (now - self._last_tick) / self.RING_PERIOD_S) % 1.0
        self._last_tick = now
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        center = QPointF(self.width() / 2, self.height() / 2)
        outer = side / 2 - 3
        core = outer * 0.46

        if self._state is True:
            base = QColor(styles.VIBRATION)
            for i in range(3):
                phase = (self._phase + i / 3) % 1.0
                radius = core + phase * (outer - core)
                ring = QColor(base)
                ring.setAlpha(int(200 * (1 - phase) ** 1.5))
                painter.setPen(QPen(ring, 2.2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(center, radius, radius)
            gradient = QRadialGradient(center, core)
            gradient.setColorAt(0.0, base.lighter(125))
            gradient.setColorAt(1.0, base.darker(130))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(gradient))
            painter.drawEllipse(center, core, core)
            self._draw_wave(painter, center, core, QColor("#ffffff"), amplitude=0.55)
        elif self._state is False:
            color = QColor(styles.SUCCESS)
            painter.setPen(QPen(qcolor(styles.SUCCESS, 45), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, outer * 0.78, outer * 0.78)
            painter.setPen(QPen(color, 2.4))
            painter.setBrush(qcolor(styles.SUCCESS, 30))
            painter.drawEllipse(center, core, core)
            self._draw_wave(painter, center, core, color, amplitude=0.0)
        else:
            pen = QPen(qcolor(styles.TEXT_DIM), 2.0, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, core, core)
            self._draw_wave(painter, center, core, QColor(styles.TEXT_DIM), amplitude=0.0)

    @staticmethod
    def _draw_wave(painter: QPainter, center: QPointF, core: float, color: QColor, amplitude: float) -> None:
        """Ícone de forma de onda: zigue-zague (vibração) ou linha reta (repouso)."""
        width = core * 1.1
        path = QPainterPath()
        x0 = center.x() - width / 2
        points = [0.0, 0.0, -0.5, 0.9, -1.0, 0.7, -0.35, 0.0, 0.0] if amplitude else [0.0] * 9
        for i, factor in enumerate(points):
            x = x0 + width * i / (len(points) - 1)
            y = center.y() - factor * core * amplitude
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        painter.setPen(QPen(color, 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)


# ===========================================================================
# Ícone da aplicação
# ===========================================================================
def make_app_icon() -> QIcon:
    size = 256
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(qcolor(styles.SURFACE))
    painter.drawRoundedRect(QRectF(8, 8, size - 16, size - 16), 56, 56)
    rect = QRectF(52, 60, size - 104, size - 104)
    painter.setPen(QPen(qcolor(styles.SURFACE_ALT), 22, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawArc(rect, 225 * 16, -270 * 16)
    painter.setPen(QPen(qcolor(styles.ACCENT), 22, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawArc(rect, 225 * 16, -170 * 16)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(qcolor(styles.VIBRATION))
    painter.drawEllipse(QPointF(size / 2, size / 2 + 4), 18, 18)
    painter.end()
    return QIcon(pixmap)
