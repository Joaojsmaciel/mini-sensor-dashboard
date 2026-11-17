"""Tema visual: paleta de cores, fontes e folha de estilo (QSS).

Tema escuro grafite com destaques em ciano, inspirado em painéis de
telemetria industrial.
"""

from __future__ import annotations

from PyQt6.QtGui import QColor, QFont

# ---------------------------------------------------------------------------
# Paleta
# ---------------------------------------------------------------------------
BACKGROUND = "#14171c"     # fundo grafite
SURFACE = "#1c2027"        # cards
SURFACE_ALT = "#232832"    # blocos internos
SURFACE_HOVER = "#2a303b"
BORDER = "#2b313c"
BORDER_STRONG = "#3a4250"

TEXT = "#e7ecf2"
TEXT_MUTED = "#8a95a5"
TEXT_DIM = "#5b6575"

ACCENT = "#20c4e8"         # ciano principal
ACCENT_HOVER = "#4dd3f0"
ACCENT_PRESSED = "#159ab8"
ACCENT_DARK = "#0b1c22"

SUCCESS = "#2fd18b"
WARNING = "#f6b443"
DANGER = "#ff5d6c"
VIBRATION = "#ff8a3d"      # destaque para eventos de vibração

FONT_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "Inter", "Arial"]
DISPLAY_FONT_FAMILIES = ["Segoe UI Variable Display", "Segoe UI Semibold", "Segoe UI", "Arial"]
MONO_FONT_FAMILIES = ["Cascadia Mono", "Consolas", "Courier New"]


def qcolor(hex_color: str, alpha: int = 255) -> QColor:
    color = QColor(hex_color)
    color.setAlpha(alpha)
    return color


def rgba(hex_color: str, alpha: float) -> str:
    """Converte '#rrggbb' em 'rgba(r, g, b, a)' para uso em QSS."""
    color = QColor(hex_color)
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {int(alpha * 255)})"


def make_font(point_size: float, weight: QFont.Weight = QFont.Weight.Normal,
              display: bool = False, mono: bool = False, letter_spacing: float = 0.0) -> QFont:
    font = QFont()
    families = MONO_FONT_FAMILIES if mono else DISPLAY_FONT_FAMILIES if display else FONT_FAMILIES
    font.setFamilies(families)
    font.setPointSizeF(point_size)
    font.setWeight(weight)
    if letter_spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


STYLESHEET = f"""
QMainWindow, QWidget#Root {{
    background-color: {BACKGROUND};
}}
QWidget {{
    color: {TEXT};
    font-family: "Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif;
    font-size: 10pt;
}}
QScrollArea, QScrollArea > QWidget > QWidget#Content {{
    background: transparent;
    border: none;
}}

/* ---------------- Cabeçalho ---------------- */
QFrame#Header {{
    background-color: {SURFACE};
    border-bottom: 1px solid {BORDER};
}}
QLabel#AppTitle {{
    color: {TEXT};
}}
QLabel#AppSubtitle {{
    color: {TEXT_MUTED};
    font-size: 9pt;
}}
QFrame#UsbPill {{
    background-color: {SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 15px;
}}
QLabel#UsbLabel {{
    color: {TEXT_MUTED};
    font-size: 8.5pt;
    font-weight: 600;
}}
QLabel#Notice {{
    color: {DANGER};
    background-color: {rgba(DANGER, 0.10)};
    border: 1px solid {rgba(DANGER, 0.35)};
    border-radius: 8px;
    padding: 8px 12px;
}}

/* ---------------- Cards ---------------- */
QFrame#Card {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 16px;
}}
QLabel#CardTitle {{
    color: {TEXT_MUTED};
}}
QFrame#StatTile {{
    background-color: {SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QLabel#StatTitle {{
    color: {TEXT_MUTED};
    font-size: 8.5pt;
}}
QLabel#InfoKey {{
    color: {TEXT_MUTED};
}}
QFrame#Divider {{
    background-color: {BORDER};
    max-height: 1px;
    min-height: 1px;
    border: none;
}}
QLabel#Placeholder {{
    color: {TEXT_DIM};
    font-size: 11pt;
    background: transparent;
}}

/* ---------------- Controles ---------------- */
QComboBox {{
    background-color: {SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 12px;
    min-height: 22px;
    color: {TEXT};
}}
QComboBox:hover {{
    border-color: {BORDER_STRONG};
}}
QComboBox:focus {{
    border-color: {ACCENT};
}}
QComboBox:disabled {{
    color: {TEXT_DIM};
}}
QComboBox::drop-down {{
    border: none;
    width: 26px;
}}
QComboBox QAbstractItemView {{
    background-color: {SURFACE_ALT};
    border: 1px solid {BORDER_STRONG};
    selection-background-color: {rgba(ACCENT, 0.25)};
    selection-color: {TEXT};
    outline: none;
    padding: 4px;
}}

QPushButton {{
    border-radius: 8px;
    padding: 7px 18px;
    min-height: 22px;
    font-weight: 600;
}}
QPushButton#Primary {{
    background-color: {ACCENT};
    color: {ACCENT_DARK};
    border: 1px solid {ACCENT};
}}
QPushButton#Primary:hover {{
    background-color: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QPushButton#Primary:pressed {{
    background-color: {ACCENT_PRESSED};
}}
QPushButton#Secondary {{
    background-color: transparent;
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
}}
QPushButton#Secondary:hover {{
    background-color: {SURFACE_HOVER};
}}
QPushButton#Danger {{
    background-color: transparent;
    color: {DANGER};
    border: 1px solid {rgba(DANGER, 0.45)};
}}
QPushButton#Danger:hover {{
    background-color: {rgba(DANGER, 0.12)};
}}
QPushButton#Icon {{
    background-color: {SURFACE_ALT};
    border: 1px solid {BORDER};
    color: {TEXT_MUTED};
    padding: 6px 10px;
    font-size: 11pt;
}}
QPushButton#Icon:hover {{
    color: {TEXT};
    border-color: {BORDER_STRONG};
}}
QPushButton:disabled, QPushButton#Primary:disabled, QPushButton#Danger:disabled {{
    background-color: {SURFACE_ALT};
    color: {TEXT_DIM};
    border: 1px solid {BORDER};
}}

QToolTip {{
    background-color: {SURFACE_ALT};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    padding: 6px 8px;
    border-radius: 6px;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px 2px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_STRONG};
    border-radius: 3px;
    min-height: 40px;
}}
QScrollBar::handle:vertical:hover {{
    background: {TEXT_DIM};
}}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
    height: 0;
}}
"""
