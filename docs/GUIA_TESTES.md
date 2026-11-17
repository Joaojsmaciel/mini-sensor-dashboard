# Guia de testes e diagnóstico

## 1. Testes automáticos (sem hardware)

Validam o protocolo JSON e o processamento: estatísticas, eventos, históricos, taxa e erros.

```bat
cd mini-dashboard
.venv\Scripts\python.exe -m unittest discover -s tests -v
```
Resultado esperado: `Ran 12 tests ... OK`. O `.venv` é criado pelo `run.bat` na primeira execução.

## 2. Teste da comunicação serial (sem interface gráfica)

A ferramenta `tools\diagnostico_serial.py` mostra cada linha recebida e se ela é válida.
**Feche o dashboard e o Monitor Serial da IDE antes de usá-la.**

```bat
.venv\Scripts\python.exe tools\diagnostico_serial.py          :: lista as portas
.venv\Scripts\python.exe tools\diagnostico_serial.py COM5     :: monitora a COM5 (Ctrl+C para sair)
```
Saída esperada (cerca de 5 linhas por segundo):
```
    2.31s  OK  temp=24.56 C   vib=0  t=2201 ms
    2.51s  OK  temp=24.56 C   vib=0  t=2401 ms
    2.63s  OK  temp=24.56 C   vib=1  t=2523 ms   <- batida na mesa
```
A primeira linha depois de abrir a porta pode vir cortada; isso é normal e o dashboard a descarta.

Também é possível usar o **Monitor Serial** da Arduino IDE (115200 baud). Ele deve mostrar apenas linhas JSON:
```
{"temperature":24.56,"vibration":0,"timestamp":2201}
```

## 3. Roteiro de testes funcionais (com hardware)

| # | Ação | Resultado esperado |
|---|---|---|
| 1 | Abrir o dashboard sem conectar | Estado **DESCONECTADO**; temperatura `--.-`; vibração **SEM DADOS**; nenhum valor numérico inventado |
| 2 | Selecionar a porta e clicar em **Conectar** | **CONECTANDO…** → **AGUARDANDO DADOS** → **RECEBENDO DADOS** em até ~3 s; LED USB verde piscando |
| 3 | Observar o painel de informações | Taxa ≈ **5 msg/s**; "Arduino ligado há" aumentando; mensagens válidas crescendo |
| 4 | Segurar o DS18B20 entre os dedos por 30 s | Temperatura sobe; a **máxima** é atualizada; o gráfico mostra a curva subindo |
| 5 | Soltar o sensor | Temperatura cai lentamente; a **média** muda |
| 6 | Dar uma batida leve na mesa | **VIBRAÇÃO DETECTADA** com animação; **eventos +1**; pulso no gráfico digital |
| 7 | Ficar parado por 5 s | Volta para **NORMAL**; "Último evento há Xs" contando |
| 8 | Retirar o jumper **J5** (D2) com o sistema ligado | Em até ~2 s: estado do sensor **FALHA DE LEITURA**, gauge `--.-`, contador "falhas do DS18B20" sobe, lacuna no gráfico |
| 9 | Recolocar o J5 | A temperatura volta em até ~7 s (após 3 falhas seguidas, o firmware procura o sensor de novo a cada 5 s) |
| 10 | Clicar em **Desconectar** | **DESCONECTADO**; valores ao vivo somem; estatísticas e históricos permanecem |
| 11 | Conectar de novo | Volta a **RECEBENDO DADOS** (reconexão manual) |
| 12 | Remover o cabo USB com o sistema conectado | Aviso vermelho: **CONEXÃO PERDIDA** com instrução para reconectar |
| 13 | Reconectar o cabo, escolher a porta e clicar em **Conectar** | Volta a funcionar sem reiniciar o programa |
| 14 | Abrir o Monitor Serial da IDE e tentar conectar o dashboard | Aviso: **porta em uso por outro programa** |
| 15 | Redimensionar a janela (larga → estreita) | O layout passa de 3 colunas para 2 e depois 1, com rolagem vertical |
| 16 | Clicar em **Limpar histórico e estatísticas** | Mínima, máxima, média, contadores e gráficos são zerados |

Depois de 5 minutos conectado, o gráfico de temperatura mostra exatamente a janela dos últimos 5 minutos e descarta os pontos mais antigos.

---

## 4. Diagnóstico de problemas

### 4.1 A temperatura não aparece (`--.-` / FALHA DE LEITURA)
| Causa provável | Verificação | Solução |
|---|---|---|
| Fio de sinal fora do **D2** | Siga o fio amarelo (J5) | Ligue S/DQ exatamente no **D2** |
| Jumper e pino em colunas diferentes | Confira as colunas da protoboard | Mesma coluna, mesma metade (a–e) |
| Falta o **resistor de pull-up** (sensor sem módulo) | Há um resistor de 4,7 kΩ entre DQ e VDD? | Instale o resistor (ver guia de montagem) |
| V/G sem alimentação | Meça 5 V entre o trilho + e o trilho − | Revise J1, J2, J3 e J4 |
| Pernas do TO-92 invertidas | O sensor esquenta? | **Desligue já** e reposicione (face plana: GND · DQ · VDD) |
| Firmware não carregado | Monitor Serial vazio? | Carregue o `sensor_monitor.ino` |

O estado **SEM DADOS** (em vez de *FALHA DE LEITURA*) indica que o problema é a **comunicação** e não o sensor. Veja a seção 4.5.

### 4.2 O DS18B20 retorna valor inválido
O firmware **descarta** valores inválidos e envia `"temperature":null`. Por isso o dashboard mostra *FALHA DE LEITURA* em vez de um número falso.

| Valor bruto | Significado | O que fazer |
|---|---|---|
| **−127 °C** | Sensor não respondeu (`DEVICE_DISCONNECTED_C`) | Mau contato no sinal ou falta de pull-up |
| **85 °C** logo ao ligar | Valor de reset: a conversão não terminou ou houve queda de alimentação | É ignorado automaticamente; se persistir, verifique a alimentação de 5 V |
| Oscila entre válido e falha | Mau contato intermitente ou cabo longo | Troque o jumper, firme os pinos; em cabos longos use pull-up de 4,7 kΩ bem próximo ao Arduino |
| Leitura muito acima do ambiente | Sensor aquecendo por estar invertido | Desligue e corrija a pinagem |

### 4.3 O SW-420 não detecta vibração
| Causa provável | Verificação | Solução |
|---|---|---|
| Sensibilidade baixa | O LED **DO** do módulo reage às batidas? | Gire o **trimpot azul** devagar até o LED DO ficar no limiar (reagindo a toques leves) |
| Polaridade invertida | O dashboard mostra vibração com tudo parado, ou nunca mostra | Troque `SW420_ACTIVE_LEVEL` para `LOW` no firmware e carregue de novo |
| SIG fora do **D7** | Siga o fio verde (J8) | Ligue SIG/DO exatamente no **D7** |
| Fio no **NC** em vez do SIG | Confira o nome impresso | Use o pino **SIG/DO** |
| Módulo sem alimentação | O LED **PWR** do SW-420 está aceso? | Revise J6 e J7 |

O SW-420 detecta **choques e vibrações**, não inclinação nem movimentos lentos. O firmware mantém o estado "vibração" por 300 ms após cada pulso para que pulsos curtos fiquem visíveis.

### 4.4 O Arduino não aparece na lista de portas COM
| Causa provável | Solução |
|---|---|
| Cabo só de carga | Troque por um cabo USB de **dados** |
| Driver CH340 ausente (clones) | Instale o driver CH340 (Gerenciador de Dispositivos mostra "dispositivo desconhecido") |
| Porta USB do PC com problema | Teste outra porta USB, de preferência direto no PC e sem hub |
| Leonardo travado por firmware anterior | Aperte RESET duas vezes rapidamente e carregue o firmware em seguida |
| Lista desatualizada | Clique em **⟳** (a lista também se atualiza sozinha a cada 2 s quando desconectado) |

### 4.5 O dashboard não conecta
| Mensagem / sintoma | Causa | Solução |
|---|---|---|
| "Porta em uso por outro programa" | Monitor Serial, Plotter Serial ou outro programa usando a porta | Feche-os e clique em **Conectar** |
| "Porta não encontrada" | Arduino desconectado ou a porta mudou de número | Reconecte o cabo, clique em ⟳ e escolha a porta nova |
| Fica em **AGUARDANDO DADOS** / **SEM DADOS** | Firmware não carregado, baud diferente ou porta errada (outro dispositivo) | Carregue o firmware; confirme a porta pelo Gerenciador de Dispositivos |
| Conecta, mas a contagem de **mensagens inválidas** só cresce | Outro firmware rodando na placa | Carregue o `sensor_monitor.ino` |
| O `run.bat` diz "Python 3.12 ou superior não foi encontrado" | Python ausente, versão antiga (3.11 ou menor) ou fora do PATH | Execute `instalar_dependencias.bat`, ou instale o Python 3.12 marcando "Add python.exe to PATH" |
| `instalar_dependencias.bat` termina "COM PENDÊNCIAS" | Algum item não pôde ser baixado ou instalado | Leia a lista exibida e o log em `logs\`; corrija e execute de novo (o instalador pula o que já está pronto) |
| "DLL load failed… política de Controle de Aplicativo bloqueou este arquivo" | O **Smart App Control** do Windows bloqueou uma versão nova do PyQt6 | Mantenha as versões fixadas no `requirements.txt` (testadas com o Smart App Control ativo). Se você as alterou, restaure o arquivo, apague `.venv` e rode o `run.bat` |

### 4.6 Dados seriais corrompidos
Sintomas: o contador **mensagens inválidas** cresce e o "Último erro" mostra mensagens como `JSON malformado` ou `bytes inválidos`.

| Causa provável | Solução |
|---|---|
| Baud rate diferente de **115200** | O firmware e o dashboard usam 115200; não altere apenas um dos lados |
| Firmware modificado imprimindo texto extra | Mantenha `DEBUG_MODE 0`. Se usar depuração, as linhas devem começar com `#` (o dashboard as ignora) |
| Cabo USB longo, danificado ou com mau contato | Troque o cabo ou use outra porta USB |
| Hub USB sem alimentação própria | Ligue direto no PC |
| Algumas inválidas logo após conectar | Normal: a primeira linha pode vir cortada e é descartada |

Para ver exatamente o que chega pela porta, use `tools\diagnostico_serial.py` (seção 2): ele mostra cada linha bruta e o motivo da rejeição.

---

## 5. Referência do protocolo

Uma mensagem JSON por linha, terminada em `\n`, a 115200 baud:
```json
{"temperature":28.60,"vibration":1,"timestamp":1200}
```
| Campo | Tipo | Regra |
|---|---|---|
| `temperature` | número (°C) ou `null` | Entre −55 e 125; `null` = falha de leitura do DS18B20 |
| `vibration` | 0 ou 1 | 1 = vibração detectada (mantida por 300 ms após cada pulso) |
| `timestamp` | inteiro ≥ 0 | `millis()` desde que a placa ligou |

Cadência: uma mensagem a cada **200 ms**, mais uma imediata quando uma vibração **começa**. A temperatura é atualizada a cada **1 s**, e o SW-420 é amostrado a cada **20 ms**.

O dashboard rejeita (e conta como erro) qualquer linha fora desse formato: JSON malformado, campos ausentes, tipos errados ou valores fora da faixa.
