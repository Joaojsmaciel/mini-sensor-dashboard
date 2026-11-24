"""Mestre Modbus RTU mínimo: CRC16, requisição de leitura e validação da resposta.

Implementa só o que o dashboard usa (funções 0x03 e 0x04) sobre qualquer objeto
com a interface do ``serial.Serial`` (``write``, ``read``, ``reset_input_buffer``
e ``timeout``), o que permite testá-lo sem hardware.
"""

from __future__ import annotations

import struct
import time
from typing import List, Protocol

READ_HOLDING_REGISTERS = 0x03
READ_INPUT_REGISTERS = 0x04
MAX_READ_REGISTERS = 125

EXCEPTION_NAMES = {
    0x01: "função ilegal",
    0x02: "endereço de registrador ilegal",
    0x03: "valor ilegal",
    0x04: "falha no escravo",
}


class ModbusError(Exception):
    """Base dos erros de comunicação Modbus."""


class ModbusTimeout(ModbusError):
    """O escravo não respondeu dentro do prazo."""


class ModbusFrameError(ModbusError):
    """Resposta recebida, mas corrompida ou fora do protocolo."""


class ModbusExceptionResponse(ModbusError):
    """O escravo respondeu com um código de exceção Modbus."""

    def __init__(self, function: int, code: int) -> None:
        self.function = function
        self.code = code
        name = EXCEPTION_NAMES.get(code, "código desconhecido")
        super().__init__(f"exceção Modbus {code:02d} ({name}) na função 0x{function:02X}")


class SerialLike(Protocol):
    timeout: float

    def write(self, data: bytes) -> int: ...
    def read(self, size: int) -> bytes: ...
    def reset_input_buffer(self) -> None: ...


def crc16(data: bytes) -> int:
    """CRC-16/MODBUS (polinômio 0xA001 refletido, valor inicial 0xFFFF)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def with_crc(payload: bytes) -> bytes:
    """Acrescenta o CRC ao frame, byte baixo primeiro."""
    return payload + struct.pack("<H", crc16(payload))


def build_read_request(slave: int, function: int, address: int, count: int) -> bytes:
    if function not in (READ_HOLDING_REGISTERS, READ_INPUT_REGISTERS):
        raise ValueError(f"função não suportada: 0x{function:02X}")
    if not 1 <= count <= MAX_READ_REGISTERS:
        raise ValueError(f"quantidade de registradores inválida: {count}")
    return with_crc(struct.pack(">BBHH", slave, function, address, count))


def hex_bytes(data: bytes, limit: int = 24) -> str:
    text = data[:limit].hex(" ")
    return text + (" ..." if len(data) > limit else "")


def _looks_like_text(data: bytes) -> bool:
    # O firmware antigo enviava linhas JSON: "{", letras, dígitos e '\n'.
    return len(data) >= 2 and all(32 <= b < 127 or b in (10, 13) for b in data)


def parse_read_response(frame: bytes, slave: int, function: int, count: int) -> List[int]:
    """Valida a resposta completa e devolve os valores dos registradores."""
    if len(frame) < 5:
        raise ModbusFrameError(f"resposta truncada ({len(frame)} bytes)")
    if crc16(frame[:-2]) != struct.unpack("<H", frame[-2:])[0]:
        if _looks_like_text(frame):
            raise ModbusFrameError(
                "dados em texto recebidos: firmware antigo (JSON)? Carregue o firmware novo")
        raise ModbusFrameError(f"CRC incorreto: {hex_bytes(frame)}")
    if frame[0] != slave:
        raise ModbusFrameError(f"resposta do escravo {frame[0]}, esperado {slave}")
    if frame[1] == function | 0x80:
        raise ModbusExceptionResponse(function, frame[2])
    if frame[1] != function:
        raise ModbusFrameError(f"função 0x{frame[1]:02X} na resposta, esperado 0x{function:02X}")
    expected_bytes = 2 * count
    if frame[2] != expected_bytes or len(frame) != 5 + expected_bytes:
        raise ModbusFrameError(f"tamanho de resposta inesperado ({len(frame)} bytes)")
    return list(struct.unpack(f">{count}H", frame[3:3 + expected_bytes]))


def _read_exact(connection: SerialLike, size: int, deadline: float, received: bytearray) -> bool:
    """Lê até ``size`` bytes em ``received`` antes do prazo. True se completou."""
    while len(received) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        connection.timeout = remaining
        chunk = connection.read(size - len(received))
        if not chunk:
            return False
        received.extend(chunk)
    return True


def read_registers(connection: SerialLike, slave: int, address: int, count: int,
                   timeout_s: float, function: int = READ_INPUT_REGISTERS) -> List[int]:
    """Envia uma requisição de leitura e espera a resposta completa.

    Lança :class:`ModbusTimeout`, :class:`ModbusFrameError` ou
    :class:`ModbusExceptionResponse`. Exceções do PySerial (cabo removido)
    propagam sem alteração.
    """
    # Descarta restos de uma resposta atrasada para não dessincronizar os frames.
    connection.reset_input_buffer()
    connection.write(build_read_request(slave, function, address, count))
    deadline = time.monotonic() + timeout_s

    received = bytearray()
    # Cabeçalho: endereço, função e (byte count | código de exceção).
    if not _read_exact(connection, 3, deadline, received):
        if received:
            raise _incomplete(received)
        raise ModbusTimeout("sem resposta do Arduino")
    if received[1] & 0x80:
        total = 5
    elif received[1] == function and received[2] == 2 * count:
        total = 5 + 2 * count
    else:
        # Cabeçalho incoerente: lê o que chegar até o prazo, para o diagnóstico.
        total = 5 + 2 * count
    if not _read_exact(connection, total, deadline, received):
        raise _incomplete(received)
    return parse_read_response(bytes(received), slave, function, count)


def _incomplete(received: bytearray) -> ModbusFrameError:
    if _looks_like_text(bytes(received)):
        return ModbusFrameError(
            "dados em texto recebidos: firmware antigo (JSON)? Carregue o firmware novo")
    return ModbusFrameError(f"resposta truncada ({len(received)} bytes): {hex_bytes(bytes(received))}")
