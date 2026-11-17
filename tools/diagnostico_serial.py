"""Diagnóstico da comunicação serial, sem interface gráfica.

Mostra cada linha recebida do Arduino e se ela é válida pelo protocolo.
Útil para investigar "dados corrompidos" ou "dashboard não conecta".

Uso (na raiz do projeto, com o ambiente .venv já criado pelo run.bat):
    .venv\\Scripts\\python.exe tools\\diagnostico_serial.py            -> lista as portas
    .venv\\Scripts\\python.exe tools\\diagnostico_serial.py COM3       -> monitora a COM3
    .venv\\Scripts\\python.exe tools\\diagnostico_serial.py COM3 -s 20 -> monitora por 20 s

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

from models.sensor_data import ProtocolError, parse_sensor_line  # noqa: E402
from utils.configuration import BAUD_RATE  # noqa: E402


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


def monitor(port: str, baud: int, seconds: float) -> int:
    print(f"Abrindo {port} a {baud} baud... (Ctrl+C para sair)")
    try:
        connection = serial.Serial(port, baud, timeout=0.5)
    except serial.SerialException as exc:
        print(f"[ERRO] {exc}")
        return 1

    connection.dtr = True
    ok = invalid = 0
    started = time.time()
    try:
        while seconds <= 0 or time.time() - started < seconds:
            raw = connection.readline()
            if not raw:
                continue
            elapsed = time.time() - started
            text = raw.decode("ascii", errors="replace").rstrip("\r\n")
            try:
                reading = parse_sensor_line(text, time.time())
            except ProtocolError as exc:
                invalid += 1
                print(f"{elapsed:8.2f}s  INVALIDA  ({exc}): {text!r}")
                continue
            ok += 1
            temp = f"{reading.temperature:.2f} C" if reading.temperature is not None else "FALHA"
            print(f"{elapsed:8.2f}s  OK  temp={temp:<9} vib={reading.vibration}  t={reading.device_timestamp_ms} ms")
    except KeyboardInterrupt:
        pass
    except serial.SerialException as exc:
        print(f"[ERRO] Comunicação perdida: {exc}")
    finally:
        connection.close()

    total = ok + invalid
    print(f"\nResumo: {total} linhas, {ok} válidas, {invalid} inválidas.")
    print("Obs.: a primeira linha após abrir a porta pode vir cortada; isso é normal.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico serial do Mini Sensor Dashboard")
    parser.add_argument("port", nargs="?", help="porta COM, ex.: COM3")
    parser.add_argument("-b", "--baud", type=int, default=BAUD_RATE)
    parser.add_argument("-s", "--seconds", type=float, default=0, help="duração (0 = até Ctrl+C)")
    args = parser.parse_args()
    if not args.port:
        show_ports()
        return 0
    return monitor(args.port, args.baud, args.seconds)


if __name__ == "__main__":
    sys.exit(main())
