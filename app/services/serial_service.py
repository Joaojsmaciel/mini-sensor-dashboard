"""Comunicação serial em uma thread dedicada.

A thread é o mestre Modbus RTU: consulta os registradores do Arduino em
intervalos fixos, valida a resposta e entrega objetos :class:`SensorReading`
para a interface por sinais Qt (conexão enfileirada), sem nunca bloquear a
thread da interface.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import List

import serial
from serial.tools import list_ports
from PyQt6.QtCore import QThread, pyqtSignal

from models.sensor_data import REGISTER_COUNT, ProtocolError, decode_registers
from services.modbus_rtu import (
    ModbusExceptionResponse,
    ModbusFrameError,
    ModbusTimeout,
    read_registers,
)
from utils.configuration import (
    ARDUINO_USB_VIDS,
    BAUD_RATE,
    MODBUS_POLL_INTERVAL_S,
    MODBUS_RESPONSE_TIMEOUT_S,
    MODBUS_SLAVE_ID,
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
    """Thread que mantém a porta aberta, consulta o Arduino e emite as leituras."""

    connection_opened = pyqtSignal(str)        # porta
    connection_failed = pyqtSignal(str)        # mensagem de erro ao abrir
    connection_closed = pyqtSignal(bool, str)  # (encerrado_pelo_usuário, motivo)
    reading_received = pyqtSignal(object)      # SensorReading
    invalid_message = pyqtSignal(str)          # motivo

    def __init__(self, port: str, baud_rate: int = BAUD_RATE,
                 slave_id: int = MODBUS_SLAVE_ID, parent=None) -> None:
        super().__init__(parent)
        self.port = port
        self.baud_rate = baud_rate
        self.slave_id = slave_id
        self._stop_event = threading.Event()

    def stop(self) -> None:
        """Solicita o encerramento; a thread fecha a porta em até ~150 ms."""
        self._stop_event.set()

    # ------------------------------------------------------------------ thread
    def run(self) -> None:  # noqa: D401 - executa na thread de background
        try:
            connection = serial.Serial(
                port=self.port,
                baudrate=self.baud_rate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=MODBUS_RESPONSE_TIMEOUT_S,
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
            # ao abrir a porta e só responde ~2 s depois (as consultas desse
            # intervalo ficam sem resposta, o que não conta como erro).
            connection.dtr = True
            connection.reset_input_buffer()
            self._poll_loop(connection)
        except (serial.SerialException, OSError) as exc:
            user_requested = False
            reason = describe_serial_error(exc)
        except Exception as exc:  # proteção final: a thread nunca morre em silêncio
            user_requested = False
            reason = f"Erro inesperado na comunicação Modbus: {exc}"
        finally:
            try:
                connection.close()
            except Exception:
                pass
        self.connection_closed.emit(user_requested, reason)

    def _poll_loop(self, connection: serial.Serial) -> None:
        next_poll = time.monotonic()
        while not self._stop_event.is_set():
            self._poll_once(connection)
            # Cadência fixa; se a consulta atrasou, a próxima sai imediatamente.
            next_poll = max(next_poll + MODBUS_POLL_INTERVAL_S, time.monotonic())
            self._stop_event.wait(next_poll - time.monotonic())

    def _poll_once(self, connection: serial.Serial) -> None:
        # Erros do PySerial (cabo removido) sobem para run() e encerram a conexão.
        try:
            registers = read_registers(connection, self.slave_id, 0, REGISTER_COUNT,
                                       MODBUS_RESPONSE_TIMEOUT_S)
        except ModbusTimeout:
            return  # silêncio é tratado pelo aviso "SEM DADOS" do dashboard
        except (ModbusFrameError, ModbusExceptionResponse) as exc:
            self.invalid_message.emit(str(exc))
            return
        try:
            reading = decode_registers(registers, time.time(), time.monotonic())
        except ProtocolError as exc:
            self.invalid_message.emit(str(exc))
            return
        self.reading_received.emit(reading)
