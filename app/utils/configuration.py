"""Configurações centrais da aplicação.

Todos os parâmetros ajustáveis ficam aqui para que nenhum módulo dependa de
valores "mágicos" espalhados pelo código.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Identidade
# ---------------------------------------------------------------------------
APP_NAME = "MINI SENSOR DASHBOARD"
APP_SUBTITLE = "Telemetria local · Arduino USB"
APP_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Comunicação serial: Modbus RTU, 8N1 (deve corresponder ao firmware)
# ---------------------------------------------------------------------------
BAUD_RATE = 115200
MODBUS_SLAVE_ID = 1              # endereço do Arduino no barramento
MODBUS_POLL_INTERVAL_S = 0.1     # uma consulta a cada 100 ms (~10 leituras/s)
MODBUS_RESPONSE_TIMEOUT_S = 0.15 # sem resposta neste tempo -> consulta perdida
DATA_TIMEOUT_S = 3.0             # sem leituras válidas por este tempo -> "SEM DADOS"
CONNECT_SLOW_WARNING_S = 8.0     # aviso se a abertura da porta demorar mais que isso
PORT_SCAN_INTERVAL_MS = 2000     # atualização automática da lista de portas

# Fabricantes USB comuns em placas Arduino e clones (usado só para destacar
# a porta provável na lista; a seleção continua manual).
ARDUINO_USB_VIDS = {
    0x2341,  # Arduino LLC
    0x2A03,  # Arduino SRL
    0x1A86,  # QinHeng CH340 (clones)
    0x0403,  # FTDI
    0x10C4,  # Silicon Labs CP210x
}

# ---------------------------------------------------------------------------
# Protocolo (mapa de registradores no firmware e em models/sensor_data.py)
# ---------------------------------------------------------------------------
TEMPERATURE_MIN_VALID_C = -55.0  # faixa física do DS18B20
TEMPERATURE_MAX_VALID_C = 125.0

# ---------------------------------------------------------------------------
# Históricos
# ---------------------------------------------------------------------------
TEMPERATURE_HISTORY_S = 300      # gráfico de temperatura: últimos 5 minutos
VIBRATION_HISTORY_S = 60         # gráfico digital de vibração: último minuto
RATE_WINDOW_S = 5.0              # janela para calcular a taxa de mensagens

# ---------------------------------------------------------------------------
# Indicadores de temperatura (gauge)
# ---------------------------------------------------------------------------
GAUGE_MIN_C = 0.0
GAUGE_MAX_C = 60.0
TEMPERATURE_WARNING_C = 35.0     # acima disso o gauge fica âmbar
TEMPERATURE_CRITICAL_C = 45.0    # acima disso o gauge fica vermelho

# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------
UI_REFRESH_MS = 200              # atualização dos gráficos
STATUS_REFRESH_MS = 500          # atualização de tempos, taxas e timeouts
WINDOW_MIN_WIDTH = 480
WINDOW_MIN_HEIGHT = 520
WINDOW_DEFAULT_SIZE = (1360, 860)
LAYOUT_WIDE_MIN_WIDTH = 1240     # 3 colunas a partir desta largura
LAYOUT_MEDIUM_MIN_WIDTH = 780    # 2 colunas a partir desta largura
