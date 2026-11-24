"""Testes do protocolo Modbus RTU e do processamento de dados (sem hardware).

Executar na raiz do projeto:
    .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from models.sensor_data import (  # noqa: E402
    PROTOCOL_VERSION,
    REGISTER_COUNT,
    TEMPERATURE_INVALID,
    ProtocolError,
    decode_registers,
)
from services.data_processor import DataProcessor  # noqa: E402
from services.modbus_rtu import (  # noqa: E402
    READ_HOLDING_REGISTERS,
    READ_INPUT_REGISTERS,
    ModbusExceptionResponse,
    ModbusFrameError,
    ModbusTimeout,
    build_read_request,
    crc16,
    parse_read_response,
    read_registers,
    with_crc,
)


def make_registers(temperature, vibration, timestamp, sensor_present=True):
    """Registradores como o firmware os publica."""
    if temperature is None:
        raw_temp = TEMPERATURE_INVALID
    else:
        raw_temp = round(temperature * 100) & 0xFFFF
    return [raw_temp, vibration, (timestamp >> 16) & 0xFFFF, timestamp & 0xFFFF,
            1 if sensor_present else 0, PROTOCOL_VERSION]


def make_reading(temperature, vibration, timestamp, at, monotonic=None):
    return decode_registers(make_registers(temperature, vibration, timestamp), at, monotonic)


class FakeSlave:
    """Porta serial falsa com um escravo que segue as regras do firmware."""

    def __init__(self, registers, slave_id=1, reply=None):
        self.registers = registers
        self.slave_id = slave_id
        self.reply = reply      # resposta fixa (bytes) para simular falhas
        self.timeout = 0.1
        self.pending = bytearray()
        self.requests = []

    def reset_input_buffer(self):
        self.pending.clear()

    def write(self, data):
        self.requests.append(bytes(data))
        self.pending.extend(self.reply if self.reply is not None else self.answer(bytes(data)))
        return len(data)

    def read(self, size):
        chunk = bytes(self.pending[:size])
        del self.pending[:size]
        return chunk

    def answer(self, frame):
        if len(frame) < 4 or crc16(frame[:-2]) != int.from_bytes(frame[-2:], "little"):
            return b""
        if frame[0] != self.slave_id:
            return b""
        function = frame[1]
        if function not in (READ_INPUT_REGISTERS, READ_HOLDING_REGISTERS):
            return with_crc(bytes([self.slave_id, function | 0x80, 0x01]))
        start = int.from_bytes(frame[2:4], "big")
        count = int.from_bytes(frame[4:6], "big")
        if not 1 <= count <= 125:
            return with_crc(bytes([self.slave_id, function | 0x80, 0x03]))
        if start + count > len(self.registers):
            return with_crc(bytes([self.slave_id, function | 0x80, 0x02]))
        body = b"".join(v.to_bytes(2, "big") for v in self.registers[start:start + count])
        return with_crc(bytes([self.slave_id, function, 2 * count]) + body)


def good_response(registers):
    return FakeSlave(registers).answer(build_read_request(1, READ_INPUT_REGISTERS, 0, len(registers)))


class Crc16Tests(unittest.TestCase):
    def test_reference_vectors(self):
        # Vetores clássicos da especificação Modbus RTU.
        self.assertEqual(with_crc(bytes.fromhex("010300000001")), bytes.fromhex("010300000001840A"))
        self.assertEqual(with_crc(bytes.fromhex("01030000000A")), bytes.fromhex("01030000000AC5CD"))
        self.assertEqual(crc16(b"123456789"), 0x4B37)  # check value do CRC-16/MODBUS

    def test_read_request_frame(self):
        frame = build_read_request(1, READ_INPUT_REGISTERS, 0, REGISTER_COUNT)
        self.assertEqual(frame[:6], bytes.fromhex("010400000006"))
        self.assertEqual(crc16(frame[:-2]), int.from_bytes(frame[-2:], "little"))
        with self.assertRaises(ValueError):
            build_read_request(1, 0x06, 0, 1)
        with self.assertRaises(ValueError):
            build_read_request(1, READ_INPUT_REGISTERS, 0, 126)


class ModbusMasterTests(unittest.TestCase):
    def test_reads_all_registers(self):
        registers = make_registers(28.6, 1, 1200)
        slave = FakeSlave(registers)
        self.assertEqual(read_registers(slave, 1, 0, REGISTER_COUNT, 0.1), registers)
        self.assertEqual(slave.requests[0][1], READ_INPUT_REGISTERS)

    def test_holding_registers_alias(self):
        registers = make_registers(20.0, 0, 5)
        values = read_registers(FakeSlave(registers), 1, 0, REGISTER_COUNT, 0.1,
                                function=READ_HOLDING_REGISTERS)
        self.assertEqual(values, registers)

    def test_partial_read(self):
        registers = make_registers(20.0, 0, 70000)
        self.assertEqual(read_registers(FakeSlave(registers), 1, 2, 2, 0.1), [1, 70000 - 65536])

    def test_illegal_address_exception(self):
        with self.assertRaises(ModbusExceptionResponse) as ctx:
            read_registers(FakeSlave(make_registers(20.0, 0, 5)), 1, 4, 3, 0.1)
        self.assertEqual(ctx.exception.code, 0x02)

    def test_other_slave_does_not_answer(self):
        with self.assertRaises(ModbusTimeout):
            read_registers(FakeSlave(make_registers(20.0, 0, 5), slave_id=2), 1, 0, 6, 0.05)

    def test_corrupted_crc_is_rejected(self):
        good = good_response(make_registers(20.0, 0, 5))
        bad = good[:-1] + bytes([good[-1] ^ 0xFF])
        with self.assertRaisesRegex(ModbusFrameError, "CRC incorreto"):
            read_registers(FakeSlave([], reply=bad), 1, 0, 6, 0.05)

    def test_truncated_response(self):
        good = good_response(make_registers(20.0, 0, 5))
        with self.assertRaisesRegex(ModbusFrameError, "truncada"):
            read_registers(FakeSlave([], reply=good[:9]), 1, 0, 6, 0.05)

    def test_old_json_firmware_is_identified(self):
        line = b'{"temperature":28.60,"vibration":0,"timestamp":1200}\n'
        with self.assertRaisesRegex(ModbusFrameError, "firmware antigo"):
            read_registers(FakeSlave([], reply=line), 1, 0, 6, 0.05)

    def test_parse_rejects_wrong_function_and_size(self):
        with self.assertRaises(ModbusFrameError):
            parse_read_response(with_crc(bytes([1, 0x03, 2, 0, 1])), 1, READ_INPUT_REGISTERS, 1)
        with self.assertRaises(ModbusFrameError):
            parse_read_response(with_crc(bytes([1, 0x04, 2, 0, 1])), 1, READ_INPUT_REGISTERS, 2)


class DecodeRegistersTests(unittest.TestCase):
    def test_valid_reading(self):
        reading = decode_registers(make_registers(28.6, 1, 1200), 10.0)
        self.assertAlmostEqual(reading.temperature, 28.6)
        self.assertEqual(reading.vibration, 1)
        self.assertEqual(reading.device_timestamp_ms, 1200)
        self.assertEqual(reading.received_at, 10.0)
        self.assertTrue(reading.vibration_detected)
        self.assertTrue(reading.sensor_present)

    def test_negative_temperature_and_max_uptime(self):
        reading = decode_registers(make_registers(-10.25, 0, 2 ** 32 - 1), 0)
        self.assertAlmostEqual(reading.temperature, -10.25)
        self.assertEqual(reading.device_timestamp_ms, 4294967295)

    def test_invalid_marker_means_sensor_failure(self):
        reading = decode_registers(make_registers(None, 0, 5, sensor_present=False), 0)
        self.assertIsNone(reading.temperature)
        self.assertFalse(reading.temperature_valid)
        self.assertFalse(reading.sensor_present)

    def test_invalid_registers_are_rejected(self):
        base = make_registers(25.0, 0, 12)
        cases = {
            "poucos registradores": base[:5],
            "temperatura fora da faixa": [13000] + base[1:],
            "-127 °C (DEVICE_DISCONNECTED_C)": [(-12700) & 0xFFFF] + base[1:],
            "vibração 2": base[:1] + [2] + base[2:],
            "status desconhecido": base[:4] + [0x0003, base[5]],
            "versão incompatível": base[:5] + [2],
            "acima de 16 bits": base[:1] + [0x10000] + base[2:],
        }
        for name, registers in cases.items():
            with self.subTest(name):
                with self.assertRaises(ProtocolError):
                    decode_registers(registers, 0)


class DataProcessorTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.processor = DataProcessor(temperature_history_s=300, vibration_history_s=60,
                                       rate_window_s=5, clock=lambda: self.now)

    def feed(self, temperature, vibration, timestamp, at):
        return self.processor.process(make_reading(temperature, vibration, timestamp, at))

    def test_statistics(self):
        for i, value in enumerate([20.0, 22.0, 24.0]):
            self.feed(value, 0, i * 1000, self.now + i)
        stats = self.processor.stats
        self.assertEqual(stats.minimum, 20.0)
        self.assertEqual(stats.maximum, 24.0)
        self.assertAlmostEqual(stats.mean, 22.0)

    def test_sensor_failure_counts_and_creates_gap(self):
        self.feed(25.0, 0, 0, self.now)
        self.feed(None, 0, 200, self.now + 0.2)
        self.assertEqual(self.processor.sensor_read_errors, 1)
        self.assertEqual(self.processor.stats.count, 1)  # falha não entra na média
        _, ys = self.processor.temperature_series(self.now + 0.2)
        self.assertTrue(math.isnan(ys[-1]))

    def test_persistent_failure_counts_once_per_occurrence(self):
        # o firmware repete 0x8000 a cada consulta enquanto a falha dura
        for i in range(10):
            self.feed(None, 0, i * 200, self.now + i * 0.2)
        self.assertEqual(self.processor.sensor_read_errors, 1)
        self.feed(25.0, 0, 2200, self.now + 2.2)
        self.feed(None, 0, 2400, self.now + 2.4)
        self.assertEqual(self.processor.sensor_read_errors, 2)

    def test_millis_overflow_is_not_a_board_restart(self):
        self.feed(25.0, 0, 2 ** 32 - 100, self.now)
        result = self.feed(25.0, 0, 100, self.now + 0.2)
        self.assertFalse(result.board_restarted)

    def test_timeouts_use_monotonic_clock(self):
        # relógio de parede "volta" 1 h, mas o monotônico segue normal
        self.processor.process(make_reading(25.0, 0, 1, self.now - 3600, 50.0))
        self.assertAlmostEqual(self.processor.seconds_since_last_message(54.0), 4.0)

    def test_vibration_events_count_rising_edges(self):
        sequence = [0, 1, 1, 0, 1, 0, 0, 1]
        events = [self.feed(25.0, v, i * 200, self.now + i * 0.2).vibration_event
                  for i, v in enumerate(sequence)]
        self.assertEqual(self.processor.vibration_events, 3)
        self.assertEqual(events, [False, True, False, False, True, False, False, True])

    def test_reconnection_counts_ongoing_vibration_as_new_event(self):
        self.feed(25.0, 1, 0, self.now)
        self.processor.mark_connection_start()
        self.feed(25.0, 1, 200, self.now + 0.2)
        self.assertEqual(self.processor.vibration_events, 2)

    def test_history_window_trims_old_samples(self):
        self.feed(20.0, 0, 0, self.now - 400)    # mais antigo que 5 min
        self.feed(21.0, 0, 1000, self.now - 10)
        xs, ys = self.processor.temperature_series(self.now)
        self.assertEqual(ys, [21.0])
        vxs, _ = self.processor.vibration_series(self.now)
        self.assertEqual(len(vxs), 1)
        self.assertAlmostEqual(vxs[0], -10.0)

    def test_message_rate(self):
        for i in range(25):   # 5 mensagens/s durante 5 s
            self.feed(25.0, 0, i * 200, self.now - 5 + i * 0.2)
        self.assertAlmostEqual(self.processor.message_rate(self.now), 5.0, delta=0.3)
        self.assertEqual(self.processor.message_rate(self.now + 30), 0.0)

    def test_board_restart_detection(self):
        self.feed(25.0, 0, 5000, self.now)
        result = self.feed(25.0, 0, 100, self.now + 1)
        self.assertTrue(result.board_restarted)
        self.assertEqual(self.processor.board_restarts, 1)

    def test_invalid_messages_and_reset(self):
        self.processor.register_invalid_message("CRC incorreto")
        self.feed(None, 0, 0, self.now)
        self.assertEqual(self.processor.total_read_errors, 2)
        self.processor.reset()
        self.assertEqual(self.processor.total_read_errors, 0)
        self.assertIsNone(self.processor.stats.mean)
        # limpar o histórico não apaga a leitura ao vivo (evita "DESCONECTADO" falso)
        self.assertIsNotNone(self.processor.last_reading)


if __name__ == "__main__":
    unittest.main()
