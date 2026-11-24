/*
 * ============================================================================
 *  MINI SENSOR DASHBOARD - Firmware
 * ============================================================================
 *  Placas suportadas : Arduino Uno / Arduino Leonardo
 *  Comunicação       : Modbus RTU (escravo) pela USB Serial, 115200 8N1
 *
 *  Pinagem (NÃO ALTERAR - deve corresponder ao guia de montagem):
 *    DS18B20  S (sinal) -> D2   | V -> 5V | G -> GND
 *    SW-420   SIG       -> D7   | VCC -> 5V | GND -> GND | NC -> não conectar
 *
 *  Protocolo: Modbus RTU, endereço do escravo 1. A placa não envia nada por
 *  conta própria; o dashboard (mestre) consulta os registradores a cada 100 ms.
 *    Funções 0x04 (Read Input Registers) e 0x03 (Read Holding Registers),
 *    ambas lendo a mesma tabela, somente leitura. Exceções: 01 função ilegal,
 *    02 endereço ilegal, 03 valor ilegal. CRC errado ou outro endereço: sem
 *    resposta. Fim de frame por silêncio de 1,75 ms (valor da norma > 19200).
 *
 *  Mapa de registradores (base 0, 16 bits, big-endian):
 *    0  TEMPERATURA       int16, centésimos de °C (2860 = 28,60 °C);
 *                         0x8000 = sem leitura válida (sensor ausente, erro de
 *                         CRC, fora da faixa). Nunca é enviado valor inventado.
 *    1  VIBRAÇÃO          0 = normal, 1 = vibração detectada
 *    2  UPTIME_ALTO       16 bits altos de millis()
 *    3  UPTIME_BAIXO      16 bits baixos de millis()
 *    4  STATUS            bit 0 = DS18B20 detectado no barramento
 *    5  VERSÃO_PROTOCOLO  1
 *
 *  Nada além de respostas Modbus pode ser escrito na Serial: qualquer texto
 *  corromperia os frames. Por isso não há mais mensagens de depuração; o
 *  estado do sensor fica no registrador STATUS.
 *
 *  Temporização (sem delay() bloqueante no loop):
 *    - SW-420 amostrado a cada 20 ms; vibração mantida por 300 ms, para que
 *      todo pulso apareça em pelo menos duas consultas do dashboard.
 *    - DS18B20 com conversão assíncrona: solicitação a cada 1000 ms e leitura
 *      quando a conversão de 12 bits termina (~750 ms depois).
 *    - Requisições Modbus atendidas em toda volta do loop.
 *
 *  Bibliotecas necessárias (Arduino IDE > Gerenciador de Bibliotecas):
 *    - OneWire            (Paul Stoffregen)
 *    - DallasTemperature  (Miles Burton)
 * ============================================================================
 */

#include <OneWire.h>
#include <DallasTemperature.h>

// ----------------------------------------------------------------------------
//  Configuração de hardware (pinagem fixa do projeto)
// ----------------------------------------------------------------------------
const uint8_t PIN_DS18B20 = 2;   // DS18B20 S  -> D2
const uint8_t PIN_SW420   = 7;   // SW-420 SIG -> D7

// ----------------------------------------------------------------------------
//  Polaridade do SW-420
//  Na maioria dos módulos SW-420 a saída fica em LOW quando está parado e vai
//  para HIGH quando há vibração. Se no seu módulo for o contrário (o dashboard
//  mostra "VIBRAÇÃO DETECTADA" com o sensor parado), troque para LOW.
// ----------------------------------------------------------------------------
const uint8_t SW420_ACTIVE_LEVEL = HIGH;

// ----------------------------------------------------------------------------
//  Temporização
// ----------------------------------------------------------------------------
const unsigned long BAUD_RATE                 = 115200;
const unsigned long TEMP_INTERVAL_MS          = 1000;  // nova leitura a cada 1 s
const unsigned long VIBRATION_SAMPLE_MS       = 20;    // amostragem do SW-420
const unsigned long VIBRATION_HOLD_MS         = 300;   // mantém "vibração" visível
const unsigned long SENSOR_RETRY_INTERVAL_MS  = 5000;  // nova busca se DS18B20 sumir
const unsigned long LEONARDO_USB_WAIT_MS      = 3000;  // espera máx. pela USB nativa
const uint8_t       TEMP_RESOLUTION_BITS      = 12;    // 0,0625 °C
const uint8_t       MAX_CONSECUTIVE_FAILURES  = 3;     // depois disso, refaz a busca

// Faixa física de medição do DS18B20 (datasheet).
const float TEMP_MIN_VALID_C = -55.0;
const float TEMP_MAX_VALID_C = 125.0;
// Valor de power-on reset do DS18B20: aparece quando o registrador é lido
// sem uma conversão válida (ex.: logo após energizar ou queda de alimentação).
const float TEMP_POWER_ON_RESET_C = 85.0;

// ----------------------------------------------------------------------------
//  Modbus RTU
// ----------------------------------------------------------------------------
const uint8_t       MODBUS_SLAVE_ID           = 1;
const unsigned long MODBUS_FRAME_GAP_US       = 1750;  // t3,5 fixo para baud > 19200
const uint8_t       MODBUS_RX_BUFFER_SIZE     = 32;    // requisição de leitura: 8 bytes
const uint16_t      MODBUS_MAX_READ_REGISTERS = 125;   // limite da norma (0x03/0x04)

const uint8_t MODBUS_FC_READ_HOLDING   = 0x03;
const uint8_t MODBUS_FC_READ_INPUT     = 0x04;
const uint8_t MODBUS_EX_ILLEGAL_FUNCTION = 0x01;
const uint8_t MODBUS_EX_ILLEGAL_ADDRESS  = 0x02;
const uint8_t MODBUS_EX_ILLEGAL_VALUE    = 0x03;

enum RegisterAddress : uint16_t {
  REG_TEMPERATURE      = 0,
  REG_VIBRATION        = 1,
  REG_UPTIME_HIGH      = 2,
  REG_UPTIME_LOW       = 3,
  REG_STATUS           = 4,
  REG_PROTOCOL_VERSION = 5,
  REGISTER_COUNT       = 6
};

const uint16_t TEMPERATURE_INVALID   = 0x8000;  // int16 mínimo: "sem leitura"
const uint16_t STATUS_SENSOR_PRESENT = 0x0001;
const uint16_t PROTOCOL_VERSION      = 1;

// ----------------------------------------------------------------------------
//  Objetos e estado
// ----------------------------------------------------------------------------
OneWire oneWire(PIN_DS18B20);
DallasTemperature sensors(&oneWire);
DeviceAddress sensorAddress;

bool          sensorPresent          = false;
bool          conversionPending      = false;
bool          firstReadAfterDetect   = true;
uint8_t       consecutiveFailures    = 0;
unsigned long conversionTimeMs       = 750;
unsigned long lastTempRequestMs      = 0;
unsigned long lastSensorSearchMs     = 0;

bool          temperatureValid       = false;
float         temperatureC           = 0.0;

unsigned long lastVibrationSampleMs  = 0;
unsigned long lastVibrationActiveMs  = 0;
bool          vibrationEverActive    = false;
bool          vibrationState         = false;

uint8_t       modbusRx[MODBUS_RX_BUFFER_SIZE];
uint8_t       modbusRxLength         = 0;
bool          modbusRxOverflow       = false;
unsigned long modbusLastByteUs       = 0;

// ----------------------------------------------------------------------------
//  DS18B20
// ----------------------------------------------------------------------------

// Procura o primeiro DS18B20 no barramento OneWire e configura a conversão
// assíncrona. Retorna true se um sensor válido foi encontrado.
bool detectTemperatureSensor() {
  sensors.begin();
  sensors.setWaitForConversion(false);  // requestTemperatures() não bloqueia

  if (sensors.getDeviceCount() == 0 || !sensors.getAddress(sensorAddress, 0)) {
    return false;
  }
  // Confere se o dispositivo encontrado é realmente da família DS18B20 (0x28).
  if (sensorAddress[0] != DS18B20MODEL) {
    return false;
  }

  sensors.setResolution(sensorAddress, TEMP_RESOLUTION_BITS);
  conversionTimeMs = sensors.millisToWaitForConversion(TEMP_RESOLUTION_BITS);
  firstReadAfterDetect = true;
  consecutiveFailures  = 0;
  return true;
}

void markTemperatureFailure() {
  temperatureValid = false;
  if (++consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
    // Provável desconexão: volta ao modo de busca periódica.
    sensorPresent = false;
    conversionPending = false;
    lastSensorSearchMs = millis();
  }
}

// Lê o resultado da conversão e valida o valor antes de aceitá-lo.
void readTemperatureResult() {
  float value = sensors.getTempC(sensorAddress);

  bool disconnected = (value == DEVICE_DISCONNECTED_C);
  bool outOfRange   = (value < TEMP_MIN_VALID_C || value > TEMP_MAX_VALID_C);
  // 85,00 °C exatos é o valor de reset do DS18B20 (ex.: após uma queda de
  // alimentação). Só é aceito se a temperatura já vinha subindo para perto
  // disso; na primeira leitura, após falha ou em salto brusco, é descartado.
  bool powerOnReset = (value == TEMP_POWER_ON_RESET_C) &&
                      (firstReadAfterDetect || !temperatureValid ||
                       fabs(temperatureC - TEMP_POWER_ON_RESET_C) > 10.0);

  firstReadAfterDetect = false;

  if (disconnected || outOfRange || powerOnReset) {
    markTemperatureFailure();
    return;
  }

  temperatureC        = value;
  temperatureValid    = true;
  consecutiveFailures = 0;
}

// Máquina de estados não bloqueante do DS18B20.
void updateTemperature(unsigned long now) {
  if (!sensorPresent) {
    temperatureValid = false;
    if (now - lastSensorSearchMs >= SENSOR_RETRY_INTERVAL_MS) {
      lastSensorSearchMs = now;
      sensorPresent = detectTemperatureSensor();
      if (sensorPresent) {
        // Força uma nova solicitação imediata.
        lastTempRequestMs = now - TEMP_INTERVAL_MS;
      }
    }
    return;
  }

  // Resultado pronto?
  if (conversionPending && (now - lastTempRequestMs >= conversionTimeMs)) {
    conversionPending = false;
    readTemperatureResult();
  }

  // Hora de iniciar uma nova conversão (a cada 1 s)?
  if (sensorPresent && !conversionPending && (now - lastTempRequestMs >= TEMP_INTERVAL_MS)) {
    lastTempRequestMs = now;
    if (sensors.requestTemperaturesByAddress(sensorAddress)) {
      conversionPending = true;
    } else {
      markTemperatureFailure();
    }
  }
}

// ----------------------------------------------------------------------------
//  SW-420
// ----------------------------------------------------------------------------

// Os pulsos do comparador do SW-420 podem durar poucos milissegundos. Por isso
// o pino é lido em TODA volta do loop (operação de ~5 µs) e qualquer pulso é
// memorizado; o estado "vibração" é avaliado a cada 20 ms e mantido por
// VIBRATION_HOLD_MS (3 vezes o intervalo de consulta do dashboard), garantindo
// que todo pulso apareça em pelo menos duas consultas do PC.
void updateVibration(unsigned long now) {
  if (digitalRead(PIN_SW420) == SW420_ACTIVE_LEVEL) {
    lastVibrationActiveMs = now;
    vibrationEverActive   = true;
  }

  if (now - lastVibrationSampleMs < VIBRATION_SAMPLE_MS) {
    return;
  }
  lastVibrationSampleMs = now;

  vibrationState = vibrationEverActive && (now - lastVibrationActiveMs < VIBRATION_HOLD_MS);
}

// ----------------------------------------------------------------------------
//  Modbus RTU (escravo)
// ----------------------------------------------------------------------------

// CRC-16/MODBUS: polinômio 0xA001 (refletido), valor inicial 0xFFFF.
uint16_t modbusCrc16(const uint8_t *data, uint8_t length) {
  uint16_t crc = 0xFFFF;
  for (uint8_t i = 0; i < length; i++) {
    crc ^= data[i];
    for (uint8_t bit = 0; bit < 8; bit++) {
      crc = (crc & 0x0001) ? (crc >> 1) ^ 0xA001 : (crc >> 1);
    }
  }
  return crc;
}

// Envia um frame acrescentando o CRC (byte baixo primeiro, como manda a norma).
void modbusSend(uint8_t *frame, uint8_t length) {
  uint16_t crc = modbusCrc16(frame, length);
  frame[length]     = crc & 0xFF;
  frame[length + 1] = crc >> 8;
  Serial.write(frame, length + 2);
}

void modbusSendException(uint8_t function, uint8_t code) {
  uint8_t frame[5] = { MODBUS_SLAVE_ID, (uint8_t)(function | 0x80), code };
  modbusSend(frame, 3);
}

// Valor de cada registrador. O uptime é capturado uma vez por requisição para
// que as duas metades de 16 bits sejam sempre do mesmo instante.
uint16_t modbusRegister(uint16_t address, unsigned long uptimeMs) {
  switch (address) {
    case REG_TEMPERATURE:
      if (!temperatureValid) return TEMPERATURE_INVALID;
      // Faixa válida (-55..125 °C) cabe folgada em int16 com 2 casas.
      return (uint16_t)(int16_t)lround(temperatureC * 100.0);
    case REG_VIBRATION:        return vibrationState ? 1 : 0;
    case REG_UPTIME_HIGH:      return (uint16_t)(uptimeMs >> 16);
    case REG_UPTIME_LOW:       return (uint16_t)(uptimeMs & 0xFFFF);
    case REG_STATUS:           return sensorPresent ? STATUS_SENSOR_PRESENT : 0;
    case REG_PROTOCOL_VERSION: return PROTOCOL_VERSION;
    default:                   return 0;
  }
}

// Trata um frame completo. Só responde a requisições endereçadas a este
// escravo e com CRC correto (exigência da norma).
void modbusHandleFrame(const uint8_t *frame, uint8_t length) {
  if (length < 4) return;
  uint16_t receivedCrc = frame[length - 2] | ((uint16_t)frame[length - 1] << 8);
  if (modbusCrc16(frame, length - 2) != receivedCrc) return;
  if (frame[0] != MODBUS_SLAVE_ID) return;  // outro escravo ou broadcast

  uint8_t function = frame[1];
  if (function != MODBUS_FC_READ_INPUT && function != MODBUS_FC_READ_HOLDING) {
    modbusSendException(function, MODBUS_EX_ILLEGAL_FUNCTION);
    return;
  }
  if (length != 8) {
    modbusSendException(function, MODBUS_EX_ILLEGAL_VALUE);
    return;
  }

  uint16_t start    = ((uint16_t)frame[2] << 8) | frame[3];
  uint16_t quantity = ((uint16_t)frame[4] << 8) | frame[5];
  if (quantity == 0 || quantity > MODBUS_MAX_READ_REGISTERS) {
    modbusSendException(function, MODBUS_EX_ILLEGAL_VALUE);
    return;
  }
  if ((uint32_t)start + quantity > REGISTER_COUNT) {
    modbusSendException(function, MODBUS_EX_ILLEGAL_ADDRESS);
    return;
  }

  uint8_t response[3 + 2 * REGISTER_COUNT + 2];
  response[0] = MODBUS_SLAVE_ID;
  response[1] = function;
  response[2] = (uint8_t)(quantity * 2);
  unsigned long uptimeMs = millis();
  for (uint16_t i = 0; i < quantity; i++) {
    uint16_t value = modbusRegister(start + i, uptimeMs);
    response[3 + 2 * i] = value >> 8;
    response[4 + 2 * i] = value & 0xFF;
  }
  modbusSend(response, 3 + 2 * quantity);
}

// Recebe bytes sem bloquear e delimita o frame pelo silêncio de t3,5.
void pollModbus() {
  while (Serial.available() > 0) {
    uint8_t value = (uint8_t)Serial.read();
    if (modbusRxLength < MODBUS_RX_BUFFER_SIZE) {
      modbusRx[modbusRxLength++] = value;
    } else {
      modbusRxOverflow = true;  // frame grande demais: será descartado
    }
    modbusLastByteUs = micros();
  }

  if (modbusRxLength == 0) return;
  if (micros() - modbusLastByteUs < MODBUS_FRAME_GAP_US) return;

  if (!modbusRxOverflow) {
    modbusHandleFrame(modbusRx, modbusRxLength);
  }
  modbusRxLength   = 0;
  modbusRxOverflow = false;
}

// ----------------------------------------------------------------------------
//  Arduino
// ----------------------------------------------------------------------------
void setup() {
  pinMode(PIN_SW420, INPUT);  // o módulo SW-420 já possui saída com pull-up

  Serial.begin(BAUD_RATE);

  // Leonardo usa USB nativa: aguarda o PC abrir a porta por até 3 s, sem
  // travar a placa caso nenhum programa esteja conectado. No Uno, !Serial é
  // sempre falso e esta espera é ignorada.
  unsigned long waitStart = millis();
  while (!Serial && (millis() - waitStart < LEONARDO_USB_WAIT_MS)) {
    // aguardando enumeração USB
  }

  sensorPresent = detectTemperatureSensor();
  unsigned long now = millis();
  lastSensorSearchMs    = now;
  lastTempRequestMs     = now - TEMP_INTERVAL_MS;  // primeira leitura imediata
  lastVibrationSampleMs = now;

  // Descarta bytes recebidos durante a inicialização (ex.: consultas enviadas
  // enquanto o Uno reiniciava), que formariam um frame incompleto.
  while (Serial.available() > 0) {
    Serial.read();
  }
}

void loop() {
  unsigned long now = millis();

  updateTemperature(now);
  updateVibration(now);
  pollModbus();
}
