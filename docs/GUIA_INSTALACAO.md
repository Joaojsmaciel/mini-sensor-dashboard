# Guia de instalação e inicialização

Procedimento completo, da protoboard até o dashboard funcionando.
Sistema: **Windows 10/11**. Não precisa de internet depois da instalação, nem de Wi-Fi ou nuvem.

---

## Atalho: instalação automática (recomendado para um PC novo)

Dê dois cliques em **`instalar_dependencias.bat`** na pasta do projeto. Ele faz sozinho os passos 4 e 8 deste guia:

| Etapa | O que instala | Observação |
|---|---|---|
| 1 | **Python 3.12.10** (python.org) | Só se não houver Python 3.12+; instala para o usuário atual, sem precisar de administrador |
| 2 | Ambiente `.venv` com **PyQt6, PyQtGraph, PySerial e NumPy** | Versões fixas de `requirements.txt` |
| 3 | **Arduino IDE 2.3.6**, core **Arduino AVR Boards 1.8.8**, bibliotecas **OneWire 2.3.8** e **DallasTemperature 4.0.6** | A IDE só é instalada se ainda não existir |
| 4 | Verificação | Testes automáticos e compilação do firmware para Uno e Leonardo |

No fim aparece **INSTALAÇÃO CONCLUÍDA SEM PENDÊNCIAS** ou uma lista do que falta resolver. Um log fica salvo em `logs\`.

Opções (pelo Prompt de Comando, na pasta do projeto):
- `instalar_dependencias.bat -SemArduino`: só o dashboard, para um PC que não vai gravar o firmware;
- `instalar_dependencias.bat -SemVerificacao`: pula os testes e a compilação.

O instalador **não** instala o driver CH340, necessário em alguns clones. Se o Gerenciador de Dispositivos mostrar "dispositivo desconhecido", instale-o pelo site oficial da WCH.

### PC sem internet (pacote offline)
1. Em um PC **com internet** onde o projeto já funciona, execute **`preparar_pacote_offline.bat`**.
   - Ele cria a pasta `dependencias\` (~345 MB, ou ~195 MB com a opção `-SemArduinoIDE`), com o instalador do Python, os pacotes Python, o instalador da Arduino IDE, o core AVR e as bibliotecas.
2. Copie a pasta **inteira** do projeto, incluindo `dependencias\`, para o outro PC (pen drive, rede etc.).
3. No outro PC, execute **`instalar_dependencias.bat`**. Ele detecta a pasta `dependencias\` e instala tudo **sem internet**.

> No modo offline é usado sempre o Python **3.12**, porque os pacotes baixados são compilados para essa versão. Se o PC tiver apenas outra versão, o 3.12 é instalado ao lado dela.

---

## Passo 1: montar o circuito
Siga o [GUIA_MONTAGEM.md](GUIA_MONTAGEM.md) com o USB **desconectado**.

## Passo 2: conferir as conexões
Use o checklist da seção 5 do guia de montagem. Confira principalmente:
- **D2** → S do DS18B20 e **D7** → SIG do SW-420;
- **5V** no trilho + e **GND** no trilho −;
- no DS18B20 **sem módulo**, o resistor de 4,7 kΩ entre DQ e VDD.

## Passo 3: conectar o Arduino ao computador
1. Ligue o cabo USB ao Arduino e ao PC. Use um cabo **de dados**: alguns cabos micro-USB só carregam e não transmitem dados.
2. O LED **ON** do Arduino acende. Na primeira vez, o Windows instala o driver automaticamente.
3. Clones com chip **CH340** podem exigir o driver do fabricante (WCH). Procure por "CH340 driver" no site oficial do fabricante do chip.

## Passo 4: instalar a Arduino IDE e as bibliotecas
1. Instale a **Arduino IDE 2.x** a partir de <https://www.arduino.cc/en/software>, caso ainda não tenha.
2. Abra a IDE e entre no **Gerenciador de Bibliotecas**: menu lateral (ícone de livros) ou `Ctrl+Shift+I`.
3. Pesquise **DallasTemperature** (autor: *Miles Burton*) e clique em **Instalar**.
   - Quando a IDE perguntar sobre dependências, escolha **Instalar tudo**. Isso instala também a **OneWire** (autor: *Paul Stoffregen*).
4. Se a OneWire não for instalada automaticamente, pesquise **OneWire** e instale-a separadamente.

> Versões testadas na compilação deste projeto: OneWire 2.3.8 e DallasTemperature 4.0.6, com o pacote Arduino AVR Boards 1.8.8.

## Passo 5: abrir o firmware na Arduino IDE
1. **Arquivo → Abrir…**
2. Selecione `mini-dashboard\arduino\sensor_monitor\sensor_monitor.ino`.

A pasta `sensor_monitor` tem o mesmo nome do arquivo `.ino` porque a Arduino IDE exige isso.

## Passo 6: carregar o firmware
1. **Ferramentas → Placa → Arduino AVR Boards →** selecione **Arduino Uno** ou **Arduino Leonardo**, conforme a sua placa.
2. **Ferramentas → Porta →** selecione a porta do Arduino (veja o Passo 7).
3. Clique em **Carregar** (seta →). Aguarde a mensagem **"Carregamento concluído"**.
4. **Antes de carregar:** desconecte o dashboard (botão *Desconectar*) se ele estiver aberto. A gravação precisa da porta COM livre.

**Leonardo:** se o upload falhar com "porta não encontrada", clique em *Carregar* e, assim que aparecer "Carregando…", aperte uma vez o botão **RESET** da placa.

### Ajuste opcional: polaridade do SW-420
No início do `sensor_monitor.ino`:
```cpp
const uint8_t SW420_ACTIVE_LEVEL = HIGH;
```
A maioria dos módulos coloca a saída em **HIGH** durante a vibração. Se o dashboard mostrar **VIBRAÇÃO DETECTADA** com o sensor parado, troque para `LOW` e carregue o firmware de novo.

## Passo 7: identificar a porta COM
Use uma das formas abaixo:
- **Arduino IDE:** *Ferramentas → Porta* mostra, por exemplo, `COM5 (Arduino Uno)`.
- **Gerenciador de Dispositivos** (`Win+X` → Gerenciador de Dispositivos) → **Portas (COM e LPT)**: aparece "Arduino Uno (COM5)", "Arduino Leonardo (COM6)" ou "USB-SERIAL CH340 (COM7)".
- **Dashboard:** a lista de portas marca com ★ as prováveis placas Arduino.

> Truque: se houver várias portas, desconecte o Arduino e veja qual porta desaparece da lista.

## Passo 8: instalar as dependências do Python
> Se você usou o `instalar_dependencias.bat`, este passo já está feito.

1. Instale o **Python 3.12** (ou superior) a partir de <https://www.python.org/downloads/>. Versões 3.10 e 3.11 **não** servem, porque o NumPy 2.5.5 exige 3.12.
   - Na primeira tela do instalador, marque **"Add python.exe to PATH"**.
2. Não é necessário instalar nada manualmente: o `run.bat` faz isso. Na primeira execução ele:
   - cria um ambiente virtual isolado na pasta `.venv`;
   - instala as versões fixas de `requirements.txt` (PyQt6, PyQtGraph, PySerial, NumPy).

   Isso exige internet **apenas na primeira vez** e leva alguns minutos.

<details>
<summary>Instalação manual (alternativa ao run.bat)</summary>

```bat
cd "%USERPROFILE%\OneDrive\Documents\mini-dashboard"   (ajuste para o local da pasta)
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app\main.py
```
</details>

## Passo 9: executar o dashboard
Dê dois cliques em **`run.bat`** na pasta do projeto.
- Uma janela de console abre e mostra o progresso. **Mantenha-a aberta**, pois mensagens de erro aparecem nela.
- A janela **MINI SENSOR DASHBOARD** abre em seguida.

## Passo 10: conectar à porta COM
1. No cabeçalho, escolha a porta do Arduino na lista. Use o botão **⟳** para atualizar a lista.
2. Clique em **Conectar**.
3. O estado muda para **CONECTANDO…**, depois **AGUARDANDO DADOS** e por fim **RECEBENDO DADOS** (LED USB verde piscando).
   - No **Uno**, a placa reinicia ao abrir a porta, por isso os dados chegam após cerca de 2 s. Isso é normal.
4. Feche o **Monitor Serial** da Arduino IDE se estiver aberto: só um programa pode usar a porta por vez.

## Passo 11: testar os sensores
- **Temperatura:** segure o DS18B20 entre os dedos. O valor sobe gradualmente em 10 a 30 s.
- **Vibração:** dê leves batidas na mesa ou no módulo SW-420. O card mostra **VIBRAÇÃO DETECTADA**, o contador de eventos aumenta e o gráfico digital registra um pulso.

A bateria completa de testes está em [GUIA_TESTES.md](GUIA_TESTES.md).

---

## Desinstalar ou reinstalar
- Para reinstalar as dependências do zero, apague a pasta `.venv` e execute o `run.bat` novamente.
- O projeto não grava nada fora da própria pasta.
