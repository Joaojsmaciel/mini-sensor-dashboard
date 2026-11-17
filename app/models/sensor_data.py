"""Modelo de dados e validação do protocolo JSON enviado pelo Arduino.

Formato esperado (uma mensagem por linha):
    {"temperature":28.6,"vibration":1,"timestamp":1200}

``temperature`` pode ser ``null`` quando o firmware não conseguiu ler o
DS18B20. Qualquer outro desvio do formato torna a mensagem inválida.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Optional

from utils.configuration import TEMPERATURE_MAX_VALID_C, TEMPERATURE_MIN_VALID_C

REQUIRED_FIELDS = ("temperature", "vibration", "timestamp")


class ProtocolError(ValueError):
    """Mensagem recebida não segue o protocolo esperado."""


@dataclass(frozen=True)
class SensorReading:
    """Uma mensagem válida recebida do Arduino."""

    temperature: Optional[float]   # °C, ou None se o sensor falhou
    vibration: int                 # 0 ou 1
    device_timestamp_ms: int       # millis() do Arduino
    received_at: float             # time.time() do PC (eixo de horário do gráfico)
    received_monotonic: float      # time.monotonic() (timeouts e taxas; imune a ajuste de relógio)

    @property
    def temperature_valid(self) -> bool:
        return self.temperature is not None

    @property
    def vibration_detected(self) -> bool:
        return self.vibration == 1


def _is_number(value: object) -> bool:
    # bool é subclasse de int em Python; true/false não são números válidos aqui.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def parse_sensor_line(line: str, received_at: float,
                      received_monotonic: Optional[float] = None) -> SensorReading:
    """Valida uma linha de texto e a converte em :class:`SensorReading`.

    ``received_monotonic`` assume ``received_at`` quando omitido (útil em testes).
    Lança :class:`ProtocolError` com uma descrição curta do problema.
    """
    text = line.strip()
    if not text:
        raise ProtocolError("linha vazia")
    if not (text.startswith("{") and text.endswith("}")):
        raise ProtocolError("não é um objeto JSON completo")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"JSON malformado ({exc.msg})") from None

    if not isinstance(payload, dict):
        raise ProtocolError("JSON não é um objeto")

    missing = [field for field in REQUIRED_FIELDS if field not in payload]
    if missing:
        raise ProtocolError(f"campos ausentes: {', '.join(missing)}")

    temperature = payload["temperature"]
    if temperature is not None:
        if not _is_number(temperature) or not math.isfinite(float(temperature)):
            raise ProtocolError("temperature não numérica")
        temperature = float(temperature)
        if not TEMPERATURE_MIN_VALID_C <= temperature <= TEMPERATURE_MAX_VALID_C:
            raise ProtocolError(f"temperature fora da faixa ({temperature:.2f} °C)")

    vibration = payload["vibration"]
    if not _is_number(vibration) or vibration not in (0, 1):
        raise ProtocolError("vibration deve ser 0 ou 1")

    timestamp = payload["timestamp"]
    if not _is_number(timestamp) or timestamp < 0 or float(timestamp) != int(timestamp):
        raise ProtocolError("timestamp inválido")

    return SensorReading(
        temperature=temperature,
        vibration=int(vibration),
        device_timestamp_ms=int(timestamp),
        received_at=received_at,
        received_monotonic=received_at if received_monotonic is None else received_monotonic,
    )
