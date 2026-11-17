"""Processamento das leituras: estatísticas, históricos, eventos e taxas.

Este módulo não depende de Qt, o que permite testá-lo isoladamente.
Somente dados realmente recebidos do Arduino entram nos históricos; falhas do
sensor viram lacunas (NaN) no gráfico, nunca valores estimados.

Dois relógios são usados de propósito:
- ``received_at`` (time.time) posiciona os pontos no eixo de horário do gráfico;
- ``received_monotonic`` (time.monotonic) mede timeouts e taxas, e não é
  afetado por ajustes do relógio do Windows (NTP, fuso, horário de verão).
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, List, Optional, Tuple

from models.sensor_data import SensorReading
from utils.configuration import RATE_WINDOW_S, TEMPERATURE_HISTORY_S, VIBRATION_HISTORY_S

# millis() do Arduino volta a zero após 2^32 ms (~49,7 dias). Um timestamp que
# "volta" a partir de valores próximos desse limite é overflow, não reinício.
MILLIS_WRAP = 2 ** 32
MILLIS_WRAP_MARGIN_MS = 600_000


@dataclass
class TemperatureStats:
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    total: float = 0.0
    count: int = 0

    def add(self, value: float) -> None:
        self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)
        self.total += value
        self.count += 1

    @property
    def mean(self) -> Optional[float]:
        return self.total / self.count if self.count else None


@dataclass(frozen=True)
class ProcessResult:
    vibration_event: bool   # True quando uma nova vibração começou
    sensor_failure: bool    # True quando o DS18B20 passou de válido para falha
    board_restarted: bool   # True quando o timestamp do Arduino voltou atrás


class DataProcessor:
    def __init__(
        self,
        temperature_history_s: float = TEMPERATURE_HISTORY_S,
        vibration_history_s: float = VIBRATION_HISTORY_S,
        rate_window_s: float = RATE_WINDOW_S,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._temperature_history_s = temperature_history_s
        self._vibration_history_s = vibration_history_s
        self._rate_window_s = rate_window_s
        self._clock = clock
        self._monotonic = monotonic
        self.last_reading: Optional[SensorReading] = None
        self._previous_vibration = 0
        self._previous_temperature_valid = True
        self.reset()

    # ------------------------------------------------------------------ estado
    def reset(self) -> None:
        """Apaga históricos, estatísticas e contadores.

        A última leitura e o estado das bordas são preservados: limpar o
        histórico não pode fazer o painel "esquecer" que está recebendo dados.
        """
        self.stats = TemperatureStats()
        self._temperature: Deque[Tuple[float, float]] = deque()
        self._vibration: Deque[Tuple[float, int]] = deque()
        self._receive_times: Deque[float] = deque()
        self.vibration_events = 0
        self.valid_messages = 0
        self.invalid_messages = 0
        self.sensor_read_errors = 0       # ocorrências de falha (válido -> null)
        self.board_restarts = 0
        self.last_invalid_reason: Optional[str] = None

    def mark_connection_start(self) -> None:
        """Chamado a cada nova conexão: a próxima vibração/falha conta como nova."""
        self._previous_vibration = 0
        self._previous_temperature_valid = True
        self.last_reading = None
        self._receive_times.clear()

    # --------------------------------------------------------------- entradas
    def process(self, reading: SensorReading) -> ProcessResult:
        t = reading.received_at
        previous = self.last_reading
        board_restarted = (
            previous is not None
            and reading.device_timestamp_ms < previous.device_timestamp_ms
            and previous.device_timestamp_ms < MILLIS_WRAP - MILLIS_WRAP_MARGIN_MS
        )
        if board_restarted:
            self.board_restarts += 1

        self.valid_messages += 1
        self._receive_times.append(reading.received_monotonic)

        sensor_failure = False
        if reading.temperature_valid:
            self.stats.add(reading.temperature)  # type: ignore[arg-type]
            self._temperature.append((t, reading.temperature))  # type: ignore[arg-type]
        else:
            # O firmware repete null a cada 200 ms enquanto a falha persiste:
            # conta-se uma ocorrência por transição válido -> falha.
            sensor_failure = self._previous_temperature_valid
            if sensor_failure:
                self.sensor_read_errors += 1
            self._temperature.append((t, math.nan))  # lacuna no gráfico
        self._previous_temperature_valid = reading.temperature_valid

        self._vibration.append((t, reading.vibration))
        vibration_event = reading.vibration == 1 and self._previous_vibration == 0
        if vibration_event:
            self.vibration_events += 1
        self._previous_vibration = reading.vibration

        self.last_reading = reading
        self._trim(t)
        return ProcessResult(vibration_event=vibration_event, sensor_failure=sensor_failure,
                             board_restarted=board_restarted)

    def register_invalid_message(self, reason: str) -> None:
        self.invalid_messages += 1
        self.last_invalid_reason = reason

    # ---------------------------------------------------------------- consultas
    @property
    def total_read_errors(self) -> int:
        return self.invalid_messages + self.sensor_read_errors

    def seconds_since_last_message(self, now_monotonic: Optional[float] = None) -> Optional[float]:
        if self.last_reading is None:
            return None
        now = self._monotonic() if now_monotonic is None else now_monotonic
        return now - self.last_reading.received_monotonic

    def message_rate(self, now_monotonic: Optional[float] = None) -> float:
        """Mensagens por segundo na janela recente."""
        now = self._monotonic() if now_monotonic is None else now_monotonic
        cutoff = now - self._rate_window_s
        while self._receive_times and self._receive_times[0] < cutoff:
            self._receive_times.popleft()
        if not self._receive_times:
            return 0.0
        span = max(now - self._receive_times[0], 1.0)
        span = min(span, self._rate_window_s)
        return len(self._receive_times) / span

    def temperature_series(self, now: Optional[float] = None) -> Tuple[List[float], List[float]]:
        """(tempos epoch, temperaturas) dos últimos minutos; NaN = falha do sensor."""
        self._trim(self._clock() if now is None else now)
        xs = [t for t, _ in self._temperature]
        ys = [v for _, v in self._temperature]
        return xs, ys

    def vibration_series(self, now: Optional[float] = None) -> Tuple[List[float], List[int]]:
        """(segundos relativos a agora, estados 0/1) do último minuto."""
        now = self._clock() if now is None else now
        self._trim(now)
        xs = [t - now for t, _ in self._vibration]
        ys = [v for _, v in self._vibration]
        return xs, ys

    # --------------------------------------------------------------- internos
    def _trim(self, now: float) -> None:
        temp_cutoff = now - self._temperature_history_s
        while self._temperature and self._temperature[0][0] < temp_cutoff:
            self._temperature.popleft()
        vib_cutoff = now - self._vibration_history_s
        while self._vibration and self._vibration[0][0] < vib_cutoff:
            self._vibration.popleft()
