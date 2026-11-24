"""Diagnóstico da comunicação Modbus RTU, sem interface gráfica.

Consulta o Arduino a cada 100 ms, como o dashboard, e mostra cada resposta e se
ela é válida pelo protocolo. Útil para investigar "dados corrompidos",
"SEM DADOS" ou "dashboard não conecta". O Monitor Serial da Arduino IDE não
serve para isso: o Modbus é binário e o Arduino só responde quando consultado.

Uso (na raiz do projeto, com o ambiente .venv já criado pelo run.bat):
    .venv\\Scripts\\python.exe tools\\diagnostico_serial.py            -> lista as portas
    .venv\\Scripts\\python.exe tools\\diagnostico_serial.py COM3       -> consulta a COM3
    .venv\\Scripts\\python.exe tools\\diagnostico_serial.py COM3 -s 20 -> consulta por 20 s

Feche o dashboard e o Monitor Serial da Arduino IDE antes de usar: apenas um
programa pode abrir a porta COM por vez.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import serial  # noqa: E402
from serial.tools import list_ports  # noqa: E402

from models.sensor_data import REGISTER_COUNT, ProtocolError, decode_registers  # noqa: E402
from services.modbus_rtu import ModbusError, ModbusTimeout, read_registers  # noqa: E402
from utils.configuration import (  # noqa: E402
    BAUD_RATE,
    MODBUS_POLL_INTERVAL_S,
    MODBUS_RESPONSE_TIMEOUT_S,
    MODBUS_SLAVE_ID,
)


def show_ports() -> None:
    ports = list(list_ports.comports())
    if not ports:
        print("Nenhuma porta COM encontrada. Verifique o cabo USB e o driver.")
        return
    print("Portas encontradas:")
    for port in ports:
        vid = f"{port.vid:04X}" if port.vid is not None else "----"
        pid = f"{port.pid:04X}" if port.pid is not None else "----"
        print(f"  {port.device:<8} VID:PID={vid}:{pid}  {port.description}")


def monitor(port: str, baud: int, slave: int, seconds: float) -> int:
    print(f"Abrindo {port} a {baud} baud 8N1, escravo Modbus {slave}... (Ctrl+C para sair)")
    try:
        connection = serial.Serial(port, baud, timeout=MODBUS_RESPONSE_TIMEOUT_S, write_timeout=1)
    except serial.SerialException as exc:
        print(f"[ERRO] {exc}")
        return 1

    connection.dtr = True
    ok = timeouts = invalid = 0
    started = time.monotonic()
    next_poll = started
    try:
        while seconds <= 0 or time.monotonic() - started < seconds:
            elapsed = time.monotonic() - started
            try:
                registers = read_registers(connection, slave, 0, REGISTER_COUNT,
                                           MODBUS_RESPONSE_TIMEOUT_S)
                reading = decode_registers(registers, time.time())
            except ModbusTimeout:
                timeouts += 1
                print(f"{elapsed:8.2f}s  SEM RESPOSTA (timeout)")
            except (ModbusError, ProtocolError) as exc:
                invalid += 1
                print(f"{elapsed:8.2f}s  INVALIDA  ({exc})")
            else:
                ok += 1
                temp = f"{reading.temperature:.2f} C" if reading.temperature is not None else "FALHA"
                sensor = "detectado" if reading.sensor_present else "ausente"
                print(f"{elapsed:8.2f}s  OK  temp={temp:<8} vib={reading.vibration}  "
                      f"t={reading.device_timestamp_ms} ms  DS18B20={sensor}")
            next_poll = max(next_poll + MODBUS_POLL_INTERVAL_S, time.monotonic())
            time.sleep(next_poll - time.monotonic())
    except KeyboardInterrupt:
        pass
    except serial.SerialException as exc:
        print(f"[ERRO] Comunicação perdida: {exc}")
    finally:
        connection.close()

    total = ok + timeouts + invalid
    print(f"\nResumo: {total} consultas, {ok} válidas, {timeouts} sem resposta, {invalid} inválidas.")
    print("Obs.: no Uno, as consultas dos primeiros ~2 s ficam sem resposta porque a placa"
          " reinicia ao abrir a porta; isso é normal.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico Modbus RTU do Mini Sensor Dashboard")
    parser.add_argument("port", nargs="?", help="porta COM, ex.: COM3")
    parser.add_argument("-b", "--baud", type=int, default=BAUD_RATE)
    parser.add_argument("-i", "--slave-id", type=int, default=MODBUS_SLAVE_ID,
                        help="endereço do escravo Modbus")
    parser.add_argument("-s", "--seconds", type=float, default=0, help="duração (0 = até Ctrl+C)")
    args = parser.parse_args()
    if not args.port:
        show_ports()
        return 0
    return monitor(args.port, args.baud, args.slave_id, args.seconds)


if __name__ == "__main__":
    sys.exit(main())
