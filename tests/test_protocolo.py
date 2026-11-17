"""Testes do protocolo e do processamento de dados (sem hardware).

Executar na raiz do projeto:
    .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from models.sensor_data import ProtocolError, parse_sensor_line  # noqa: E402
from services.data_processor import DataProcessor  # noqa: E402


class ParseSensorLineTests(unittest.TestCase):
    def test_valid_message_from_spec(self):
        reading = parse_sensor_line('{"temperature":28.6,"vibration":1,"timestamp":1200}', 10.0)
        self.assertEqual(reading.temperature, 28.6)
        self.assertEqual(reading.vibration, 1)
        self.assertEqual(reading.device_timestamp_ms, 1200)
        self.assertEqual(reading.received_at, 10.0)
        self.assertTrue(reading.vibration_detected)

    def test_firmware_format_with_two_decimals_and_crlf(self):
        reading = parse_sensor_line('{"temperature":24.06,"vibration":0,"timestamp":4294967295}\r\n', 0)
        self.assertAlmostEqual(reading.temperature, 24.06)
        self.assertEqual(reading.device_timestamp_ms, 4294967295)

    def test_null_temperature_means_sensor_failure(self):
        reading = parse_sensor_line('{"temperature":null,"vibration":0,"timestamp":5}', 0)
        self.assertIsNone(reading.temperature)
        self.assertFalse(reading.temperature_valid)

    def test_invalid_messages_are_rejected(self):
        invalid = [
            "",
            "garbage",
            '{"temperature":28.6,"vibration":1',                       # cortada
            '{"temperature":28.6,"vibration":1,"timestamp":12}{"te',   # duas mensagens coladas
            '{"vibration":1,"timestamp":12}',                          # campo ausente
            '{"temperature":"28","vibration":1,"timestamp":12}',      # tipo errado
            '{"temperature":-127,"vibration":0,"timestamp":12}',      # DEVICE_DISCONNECTED_C
            '{"temperature":130,"vibration":0,"timestamp":12}',       # fora da faixa
            '{"temperature":25,"vibration":2,"timestamp":12}',        # vibração inválida
            '{"temperature":25,"vibration":true,"timestamp":12}',     # bool não é 0/1
            '{"temperature":25,"vibration":0,"timestamp":-1}',        # timestamp negativo
            '{"temperature":25,"vibration":0,"timestamp":1.5}',       # timestamp fracionário
            '[1,2,3]',
        ]
        for line in invalid:
            with self.subTest(line=line):
                with self.assertRaises(ProtocolError):
                    parse_sensor_line(line, 0)


class DataProcessorTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.processor = DataProcessor(temperature_history_s=300, vibration_history_s=60,
                                       rate_window_s=5, clock=lambda: self.now)

    def feed(self, temperature, vibration, timestamp, at):
        temp = "null" if temperature is None else temperature
        line = f'{{"temperature":{temp},"vibration":{vibration},"timestamp":{timestamp}}}'
        return self.processor.process(parse_sensor_line(line, at))

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
        # o firmware repete null a cada 200 ms enquanto a falha dura
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
        line = '{"temperature":25,"vibration":0,"timestamp":1}'
        # relógio de parede "volta" 1 h, mas o monotônico segue normal
        self.processor.process(parse_sensor_line(line, self.now - 3600, 50.0))
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
        self.processor.register_invalid_message("JSON malformado")
        self.feed(None, 0, 0, self.now)
        self.assertEqual(self.processor.total_read_errors, 2)
        self.processor.reset()
        self.assertEqual(self.processor.total_read_errors, 0)
        self.assertIsNone(self.processor.stats.mean)
        # limpar o histórico não apaga a leitura ao vivo (evita "DESCONECTADO" falso)
        self.assertIsNotNone(self.processor.last_reading)


if __name__ == "__main__":
    unittest.main()
