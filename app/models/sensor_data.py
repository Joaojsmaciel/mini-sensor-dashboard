"""Modelo de dados e decodificação dos registradores Modbus lidos do Arduino.

Mapa de registradores (base 0, 16 bits; deve corresponder ao firmware):
    0  TEMPERATURA       int16, centésimos de °C; 0x8000 = sem leitura válida
    1  VIBRAÇÃO          0 = normal, 1 = vibração detectada
    2  UPTIME_ALTO       16 bits altos de millis()
    3  UPTIME_BAIXO      16 bits baixos de millis()
    4  STATUS            bit 0 = DS18B20 detectado no barramento
    5  VERSÃO_PROTOCOLO  1

Qualquer valor fora do esperado torna a leitura inválida.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from utils.configuration import TEMPERATURE_MAX_VALID_C, TEMPERATURE_MIN_VALID_C

REG_TEMPERATURE = 0
REG_VIBRATION = 1
REG_UPTIME_HIGH = 2
REG_UPTIME_LOW = 3
REG_STATUS = 4
REG_PROTOCOL_VERSION = 5
REGISTER_COUNT = 6

TEMPERATURE_INVALID = 0x8000
STATUS_SENSOR_PRESENT = 0x0001
PROTOCOL_VERSION = 1


class ProtocolError(ValueError):
    """Registradores recebidos não seguem o protocolo esperado."""


@dataclass(frozen=True)
class SensorReading:
    """Uma leitura válida obtida do Arduino."""

    temperature: Optional[float]   # °C, ou None se o sensor falhou
    vibration: int                 # 0 ou 1
    device_timestamp_ms: int       # millis() do Arduino
    received_at: float             # time.time() do PC (eixo de horário do gráfico)
    received_monotonic: float      # time.monotonic() (timeouts e taxas; imune a ajuste de relógio)
    sensor_present: bool = True    # DS18B20 detectado no barramento (registrador STATUS)

    @property
    def temperature_valid(self) -> bool:
        return self.temperature is not None

    @property
    def vibration_detected(self) -> bool:
        return self.vibration == 1


def decode_registers(registers: Sequence[int], received_at: float,
                     received_monotonic: Optional[float] = None) -> SensorReading:
    """Valida os registradores lidos e os converte em :class:`SensorReading`.

    ``received_monotonic`` assume ``received_at`` quando omitido (útil em testes).
    Lança :class:`ProtocolError` com uma descrição curta do problema.
    """
    if len(registers) != REGISTER_COUNT:
        raise ProtocolError(f"esperados {REGISTER_COUNT} registradores, recebidos {len(registers)}")
    if any(not isinstance(value, int) or not 0 <= value <= 0xFFFF for value in registers):
        raise ProtocolError("registrador fora de 16 bits")

    version = registers[REG_PROTOCOL_VERSION]
    if version != PROTOCOL_VERSION:
        raise ProtocolError(
            f"firmware incompatível (protocolo v{version}, esperado v{PROTOCOL_VERSION})")

    raw_temperature = registers[REG_TEMPERATURE]
    temperature: Optional[float] = None
    if raw_temperature != TEMPERATURE_INVALID:
        signed = raw_temperature - 0x10000 if raw_temperature & 0x8000 else raw_temperature
        temperature = signed / 100.0
        if not TEMPERATURE_MIN_VALID_C <= temperature <= TEMPERATURE_MAX_VALID_C:
            raise ProtocolError(f"temperatura fora da faixa ({temperature:.2f} °C)")

    vibration = registers[REG_VIBRATION]
    if vibration not in (0, 1):
        raise ProtocolError("vibração deve ser 0 ou 1")

    status = registers[REG_STATUS]
    if status & ~STATUS_SENSOR_PRESENT:
        raise ProtocolError(f"bits de status desconhecidos (0x{status:04X})")

    return SensorReading(
        temperature=temperature,
        vibration=vibration,
        device_timestamp_ms=(registers[REG_UPTIME_HIGH] << 16) | registers[REG_UPTIME_LOW],
        received_at=received_at,
        received_monotonic=received_at if received_monotonic is None else received_monotonic,
        sensor_present=bool(status & STATUS_SENSOR_PRESENT),
    )
