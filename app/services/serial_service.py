"""Comunicação serial em uma thread dedicada.

A thread lê bytes da porta, separa as linhas, valida o JSON e entrega objetos
:class:`SensorReading` para a interface por sinais Qt (conexão enfileirada),
sem nunca bloquear a thread da interface.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import List

import serial
from serial.tools import list_ports
from PyQt6.QtCore import QThread, pyqtSignal

from models.sensor_data import ProtocolError, parse_sensor_line
from utils.configuration import (
    ARDUINO_USB_VIDS,
    BAUD_RATE,
    MAX_LINE_LENGTH,
    SERIAL_READ_TIMEOUT_S,
)


@dataclass(frozen=True)
class PortInfo:
    device: str             # ex.: "COM3"
    description: str        # ex.: "Arduino Uno (COM3)"
    likely_arduino: bool

    @property
    def label(self) -> str:
        description = self.description or "Dispositivo serial"
        # O Windows costuma repetir "(COMx)" na descrição; remove a duplicata.
        description = description.replace(f"({self.device})", "").strip()
        marker = "  ★" if self.likely_arduino else ""
        return f"{self.device} — {description}{marker}"


def list_serial_ports() -> List[PortInfo]:
    """Lista as portas COM disponíveis, com as prováveis placas Arduino primeiro."""
    ports = []
    for port in list_ports.comports():
        text = f"{port.description or ''} {port.manufacturer or ''}".lower()
        likely = (port.vid in ARDUINO_USB_VIDS) or ("arduino" in text) or ("ch340" in text)
        ports.append(PortInfo(port.device, port.description or "", likely))

    def sort_key(p: PortInfo):
        digits = "".join(ch for ch in p.device if ch.isdigit())
        return (not p.likely_arduino, int(digits) if digits else 0, p.device)

    return sorted(ports, key=sort_key)


def describe_serial_error(exc: BaseException) -> str:
    """Traduz exceções do PySerial/Windows em mensagens úteis ao usuário."""
    text = str(exc)
    lowered = text.lower()
    # No Windows o PySerial embute o erro original no texto, por exemplo:
    # "could not open port 'COM3': PermissionError(13, 'Acesso negado.', None, 5)"
    busy_markers = ("permissionerror", "access is denied", "acesso negado")
    missing_markers = ("filenotfounderror", "cannot find the file", "não pode encontrar")
    lost_markers = ("clearcommerror", "readfile failed", "writefile failed",
                    "device does not recognize", "dispositivo não reconhece",
                    "getoverlappedresult failed")

    # Ao remover o cabo, o Windows reporta "ClearCommError failed (PermissionError...)":
    # por isso a perda de comunicação é verificada antes de "porta em uso".
    if any(m in lowered for m in lost_markers):
        return "Comunicação perdida: o Arduino foi desconectado ou reiniciado."
    if isinstance(exc, PermissionError) or any(m in lowered for m in busy_markers):
        return "Porta em uso por outro programa (feche o Monitor Serial da Arduino IDE)."
    if isinstance(exc, FileNotFoundError) or any(m in lowered for m in missing_markers):
        return "Porta não encontrada. O Arduino foi desconectado?"
    return text or exc.__class__.__name__


class SerialWorker(QThread):
    """Thread que mantém a porta aberta e emite as leituras recebidas."""

    connection_opened = pyqtSignal(str)        # porta
    connection_failed = pyqtSignal(str)        # mensagem de erro ao abrir
    connection_closed = pyqtSignal(bool, str)  # (encerrado_pelo_usuário, motivo)
    reading_received = pyqtSignal(object)      # SensorReading
    invalid_message = pyqtSignal(str)          # motivo

    def __init__(self, port: str, baud_rate: int = BAUD_RATE, parent=None) -> None:
        super().__init__(parent)
        self.port = port
        self.baud_rate = baud_rate
        self._stop_event = threading.Event()

    def stop(self) -> None:
        """Solicita o encerramento; a thread fecha a porta em até ~100 ms."""
        self._stop_event.set()

    # ------------------------------------------------------------------ thread
    def run(self) -> None:  # noqa: D401 - executa na thread de background
        try:
            connection = serial.Serial(
                port=self.port,
                baudrate=self.baud_rate,
                timeout=SERIAL_READ_TIMEOUT_S,
                write_timeout=1,
            )
        except (serial.SerialException, OSError, ValueError) as exc:
            self.connection_failed.emit(describe_serial_error(exc))
            return

        self.connection_opened.emit(self.port)
        user_requested = True
        reason = "Desconectado pelo usuário."
        try:
            # Leonardo (USB nativa) só envia dados com DTR ativo; o Uno reinicia
            # ao abrir a porta e começa a transmitir ~2 s depois.
            connection.dtr = True
            connection.reset_input_buffer()
            self._read_loop(connection)
        except (serial.SerialException, OSError) as exc:
            user_requested = False
            reason = describe_serial_error(exc)
        except Exception as exc:  # proteção final: a thread nunca morre em silêncio
            user_requested = False
            reason = f"Erro inesperado na leitura serial: {exc}"
        finally:
            try:
                connection.close()
            except Exception:
                pass
        self.connection_closed.emit(user_requested, reason)

    def _read_loop(self, connection: serial.Serial) -> None:
        buffer = bytearray()
        synced = False  # a primeira linha pode estar cortada ao meio: descartar
        while not self._stop_event.is_set():
            waiting = connection.in_waiting  # lança exceção se o cabo for removido
            chunk = connection.read(waiting or 1)
            if not chunk:
                continue
            received_at = (time.time(), time.monotonic())
            buffer.extend(chunk)

            while True:
                newline = buffer.find(b"\n")
                if newline < 0:
                    break
                raw = bytes(buffer[:newline])
                del buffer[: newline + 1]
                if not synced:
                    synced = True
                    continue
                self._handle_line(raw, received_at)

            if len(buffer) > MAX_LINE_LENGTH:
                self.invalid_message.emit("linha longa demais sem terminador (dados corrompidos)")
                buffer.clear()
                synced = False

    def _handle_line(self, raw: bytes, received_at: tuple) -> None:
        if len(raw) > MAX_LINE_LENGTH:
            self.invalid_message.emit("linha longa demais (dados corrompidos)")
            return
        try:
            text = raw.decode("ascii").strip()
        except UnicodeDecodeError:
            self.invalid_message.emit("bytes inválidos (baud rate diferente de 115200?)")
            return
        if not text or text.startswith("#"):
            return  # linha vazia ou mensagem de depuração do firmware
        try:
            reading = parse_sensor_line(text, *received_at)
        except ProtocolError as exc:
            self.invalid_message.emit(str(exc))
            return
        self.reading_received.emit(reading)
