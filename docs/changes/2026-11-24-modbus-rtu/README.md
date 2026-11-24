# Mudança: protocolo JSON por linha → Modbus RTU

**Data:** 2026-11-24 · **Status:** implementada, aguardando teste com hardware

## Decisões do usuário (2026-11-24)
- Variante: **Modbus RTU sobre o mesmo cabo USB/COM** (sem hardware novo; Modbus TCP descartado).
- O protocolo JSON é **substituído totalmente** (sem modo de compatibilidade).
- **Implementação própria**, sem bibliotecas Modbus: `requirements.txt`, instalador e pacote offline não mudam.

## Contrato
- 115200 baud, 8N1; PC = mestre, Arduino = escravo **1**; polling de 6 registradores a cada 100 ms, timeout de 150 ms.
- Funções 0x04 e 0x03 (mesma tabela, somente leitura); exceções 01/02/03; CRC errado ou outro endereço → sem resposta; fim de frame por 1,75 ms de silêncio.
- Registradores: 0 temperatura (int16, c°C, `0x8000` = inválida) · 1 vibração · 2–3 uptime (alto/baixo) · 4 status (bit 0 = DS18B20 detectado) · 5 versão do protocolo (1).
- Detalhes: [README](../../../README.md#protocolo-modbus-rtu) e [GUIA_TESTES §5](../../GUIA_TESTES.md#5-referência-do-protocolo).

## Impactos
- `DEBUG_MODE` do firmware removido (texto na serial corromperia os frames); o diagnóstico usa o registrador STATUS e `tools/diagnostico_serial.py`.
- Sem envio imediato na borda de vibração: a latência passa a ser de até ~100 ms. O hold de 300 ms garante pelo menos 2 consultas por pulso.
- A taxa exibida passa de ~5 para ~10 msg/s.
- O Monitor Serial da IDE não mostra mais as leituras.
- Dashboard novo com firmware antigo: aparece o erro "firmware antigo (JSON)?".

## Arquivos
`arduino/sensor_monitor/sensor_monitor.ino`, `app/services/modbus_rtu.py` (novo), `app/services/serial_service.py`, `app/models/sensor_data.py`, `app/utils/configuration.py`, `tools/diagnostico_serial.py`, `tests/test_protocolo.py`, `README.md`, `docs/GUIA_INSTALACAO.md`, `docs/GUIA_TESTES.md`.

## Verificação
| Verificação | Resultado |
|---|---|
| `arduino-cli compile` para `arduino:avr:uno` e `arduino:avr:leonardo` (`--warnings all`) | OK, sem avisos no sketch (Uno 7170 B / Leonardo 9256 B de flash) |
| `python -m unittest discover -s tests` | 26 testes OK: vetores de CRC, mestre contra escravo simulado, exceções, CRC/truncamento, firmware antigo, decodificação e DataProcessor |
| `SerialWorker._poll_once` com PyQt6/pyserial substituídos por stubs + `py_compile` de `app/` e `tools/` | OK |
| **Teste com Arduino real (GUIA_TESTES §2 e §3)** | **Não executado:** sem hardware nesta sessão |
