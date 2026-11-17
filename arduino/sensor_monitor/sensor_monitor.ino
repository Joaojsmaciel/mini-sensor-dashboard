/*
 * ============================================================================
 *  MINI SENSOR DASHBOARD - Firmware
 * ============================================================================
 *  Placas suportadas : Arduino Uno / Arduino Leonardo
 *  Comunicação       : USB Serial a 115200 baud
 *
 *  Pinagem (NÃO ALTERAR - deve corresponder ao guia de montagem):
 *    DS18B20  S (sinal) -> D2   | V -> 5V | G -> GND
 *    SW-420   SIG       -> D7   | VCC -> 5V | GND -> GND | NC -> não conectar
 *
 *  Protocolo de saída (uma mensagem JSON por linha, terminada em '\n'):
 *    {"temperature":28.60,"vibration":1,"timestamp":1200}
 *
 *    temperature : temperatura em °C (2 casas decimais) ou null quando a
 *                  leitura do DS18B20 falhou (sensor ausente, erro de CRC,
 *                  valor fora da faixa). Nunca é enviado um valor inventado.
 *    vibration   : 0 = normal, 1 = vibração detectada
 *    timestamp   : millis() desde a inicialização da placa
 *
 *  Temporização (sem delay() bloqueante no loop):
 *    - SW-420 amostrado a cada 20 ms.
 *    - DS18B20 com conversão assíncrona: solicitação a cada 1000 ms e leitura
 *      quando a conversão de 12 bits termina (~750 ms depois).
 *    - Mensagem enviada a cada 200 ms e imediatamente quando uma vibração
 *      começa (borda de subida), para baixa latência no dashboard.
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
const unsigned long SEND_INTERVAL_MS          = 200;   // frequência das mensagens
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
//  Depuração
//  Mantenha em 0 durante o uso normal. Com 1, mensagens de diagnóstico são
//  enviadas em linhas iniciadas por '#', que o dashboard ignora; elas nunca são
//  misturadas dentro de uma linha JSON.
// ----------------------------------------------------------------------------
#define DEBUG_MODE 0

#if DEBUG_MODE
  #define DEBUG_PRINTLN(msg) do { Serial.print(F("# ")); Serial.println(msg); } while (0)
#else
  #define DEBUG_PRINTLN(msg) do { } while (0)
#endif

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

unsigned long lastSendMs             = 0;

// ----------------------------------------------------------------------------
//  DS18B20
// ----------------------------------------------------------------------------

// Procura o primeiro DS18B20 no barramento OneWire e configura a conversão
// assíncrona. Retorna true se um sensor válido foi encontrado.
bool detectTemperatureSensor() {
  sensors.begin();
  sensors.setWaitForConversion(false);  // requestTemperatures() não bloqueia

  if (sensors.getDeviceCount() == 0 || !sensors.getAddress(sensorAddress, 0)) {
    DEBUG_PRINTLN(F("DS18B20 nao encontrado"));
    return false;
  }
  // Confere se o dispositivo encontrado é realmente da família DS18B20 (0x28).
  if (sensorAddress[0] != DS18B20MODEL) {
    DEBUG_PRINTLN(F("Dispositivo OneWire nao e um DS18B20"));
    return false;
  }

  sensors.setResolution(sensorAddress, TEMP_RESOLUTION_BITS);
  conversionTimeMs = sensors.millisToWaitForConversion(TEMP_RESOLUTION_BITS);
  firstReadAfterDetect = true;
  consecutiveFailures  = 0;
  DEBUG_PRINTLN(F("DS18B20 encontrado"));
  return true;
}

void markTemperatureFailure() {
  temperatureValid = false;
  if (++consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
    // Provável desconexão: volta ao modo de busca periódica.
    sensorPresent = false;
    conversionPending = false;
    lastSensorSearchMs = millis();
    DEBUG_PRINTLN(F("DS18B20 perdido, nova busca agendada"));
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
// VIBRATION_HOLD_MS, garantindo que todo pulso apareça em pelo menos uma
// mensagem enviada ao PC.
// Retorna true quando uma nova vibração começa (borda de subida).
bool updateVibration(unsigned long now) {
  if (digitalRead(PIN_SW420) == SW420_ACTIVE_LEVEL) {
    lastVibrationActiveMs = now;
    vibrationEverActive   = true;
  }

  if (now - lastVibrationSampleMs < VIBRATION_SAMPLE_MS) {
    return false;
  }
  lastVibrationSampleMs = now;

  bool previous  = vibrationState;
  vibrationState = vibrationEverActive && (now - lastVibrationActiveMs < VIBRATION_HOLD_MS);
  return vibrationState && !previous;
}

// ----------------------------------------------------------------------------
//  Transmissão
// ----------------------------------------------------------------------------

// Envia exatamente uma linha JSON. Nada mais é impresso entre o '{' e o '\n'.
void sendMessage(unsigned long now) {
  Serial.print(F("{\"temperature\":"));
  if (temperatureValid) {
    Serial.print(temperatureC, 2);
  } else {
    Serial.print(F("null"));
  }
  Serial.print(F(",\"vibration\":"));
  Serial.print(vibrationState ? 1 : 0);
  Serial.print(F(",\"timestamp\":"));
  Serial.print(now);
  Serial.print(F("}\n"));
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
  lastSendMs            = now;
}

void loop() {
  unsigned long now = millis();

  updateTemperature(now);
  bool vibrationStarted = updateVibration(now);

  if (vibrationStarted || (now - lastSendMs >= SEND_INTERVAL_MS)) {
    lastSendMs = now;
    sendMessage(now);
  }
}
