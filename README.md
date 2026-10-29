# Trabalho 01 — Gestão de Ambiente Inteligente · Fonte A + Painel Web

Firmware ESP8266 HW-364A + DHT22/AM2302 + OLED; Gateway Python;
interface Web do cliente com botões e gráfico, usando TCP + Protocol Buffers; gRPC de controle via bridge; UDP, multicast e SQLite.



## 1. Descrição Geral

- A placa física usa **`SOURCE_ID = "FONTE_A"`**, **`SOURCE_CONTROLLABLE = true`**, tipo **`termohigrometro_ctrl`** em `firmware/Fonte_DHT22_OLED/Config.h`.
- Preserva leitura DHT22, duas telas do OLED (sensor/rede), Wi-Fi, anúncio UDP multicast/Protobuf, telemetria UDP e controle remoto UDP/Protobuf na porta `50031`.
- Gateway fixa interface de envio multicast com o IPv4 informado em `--advertise-ip`; mantém pacotes a cada 5 s, mas reduz log de `WHO_IS_THERE` para **uma vez por minuto**, registra novos dispositivos/mudanças e imprime **resumo de estados por minuto**.
- Gateway preserva endpoint gRPC anunciado pelo bridge mesmo após novos anúncios da NodeMCU. Estados `DISABLED` e `FAILURE` continuam visíveis quando cessa a telemetria, desde que haja anúncios recentes.
- O **cliente Web** roda em `127.0.0.1:8080`, é responsivo e possui status de fontes, dashboard, série temporal, consultas analíticas, ativar, desativar, intervalo, limiar e falha simulada. Atualização automática a cada 5 s. Código JavaScript/CSS/HTML puro, sem necessidade de instalar Node.js ou framework Web.
- O CLI `python -m client.cliente` continua disponível.

### Importante

**O ESP8266 NÃO implementa servidor gRPC nativo.** O caminho real do controle nesta configuração é:

`Navegador --HTTP local--> Cliente Web Python --TCP/Protobuf--> Gateway --gRPC/HTTP2/Protobuf--> Bridge no PC --UDP/Protobuf--> NodeMCU/Fonte A`.

Esse *adaptador* é uma decisão de engenharia devido ao ESP8266 não dispor de implementação gRPC HTTP/2 prática neste firmware. **É uma diferença em relação ao requisito literal da fonte controlável expondo serviço gRPC em seu processo**; documente e confirme com o professor, ou use uma fonte Python com servidor gRPC nativo para comprovar esse requisito (`simuladores/fonte_virtual.py`). O cliente Web **não** substitui a ligação TCP/Protobuf com o Gateway.

A especificação pede **pelo menos três tipos diferentes de fontes**. A placa A é um termohigrômetro real, e as fontes simuladas B (CO₂) e D (ruído) fornecem os outros dois tipos para a demonstração. Execute-as como processos separados. Alterar apenas a Fonte C para A **não basta** para atender a esse requisito.

## 2. Rede/portas

| Porta | Origem -> destino | Protocolo |
|---|---|---|
| 50000 | Gateway -> Fontes | UDP multicast (`239.255.42.99`) |
| 50001 | Fonte / Bridge -> Gateway | UDP Protobuf (descoberta) |
| 50002 | Fonte -> Gateway | UDP Protobuf (telemetria) |
| 50010 | Cliente Web/CLI -> Gateway | TCP com frame 4-byte length + Protobuf |
| 50051 | Gateway -> Bridge no PC (Fonte A) | gRPC HTTP/2 + Protobuf |
| 50031 | Bridge -> NodeMCU Fonte A | UDP + Protobuf (controle/ACK) |
| 8080 | Navegador -> Cliente Web local | HTTP de loopback (somente `127.0.0.1`) |

As portas 50001, 50002 e 50031 precisam estar liberadas no firewall de **entrada** nas máquinas/destinatários correspondentes. Na rede do teste: Gateway/bridge **192.168.25.4**, NodeMCU **192.168.25.171**. O IP da placa pode mudar após reinicialização; confira no OLED/Serial.

## 3. Windows: instalação e início em quatro janelas

Abra **PowerShell** na pasta raiz deste projeto (a pasta que contém `gateway/`, `client/` e `firmware/`). Use Python **3.12 convencional**: o Python 3.13 *free-threaded* gerou erro compilando `grpcio` no ambiente anterior.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements.txt
```

Não é necessário `grpcio-tools` para rodar: as classes Protobuf e bindings estão incluídos.

**Terminal 1: Gateway**

```powershell
.\.venv\Scripts\python.exe -m gateway.gateway --advertise-ip 192.168.25.4
```

**Terminal 2: gRPC Bridge da Fonte A física** (com o IP atual da placa, exibido na segunda tela do OLED):

```powershell
.\.venv\Scripts\python.exe -m fonte_a_bridge.bridge --source-id FONTE_A --node-ip 192.168.25.171 --advertise-ip 192.168.25.4 --gateway-ip 192.168.25.4
```

O parâmetro `--gateway-ip` faz anúncios diretos do bridge ao Gateway, úteis quando ambos rodam no mesmo PC, além do suporte à descoberta multicast.

**Terminal 3: Painel Web do cliente**

```powershell
.\.venv\Scripts\python.exe -m client.gui --host 127.0.0.1 --web-port 8080
```

Abra **http://127.0.0.1:8080** no navegador. O painel mostra o Gateway, as fontes, as leituras e gráficos; o usuário pode clicar em **Ativar / Desativar / Simular falha / Recuperar / Aplicar intervalo / Aplicar limiar**. Se o bridge não estiver anunciado, o controle fica bloqueado e uma mensagem explica o motivo.

**Terminal 4 (opcional): CLI para validar o mesmo contrato TCP**

```powershell
.\.venv\Scripts\python.exe -m client.cliente --host 127.0.0.1
```

Digite `list`, `interval FONTE_A 5000`, `threshold FONTE_A 28`, `off FONTE_A` e `on FONTE_A` para comparação.

### Executar simuladores para completar os três tipos

Cada processo virtual roda em terminal próprio:

```powershell
.\.venv\Scripts\python.exe -m simuladores.fonte_virtual --id FONTE_B --kind co2 --advertise-ip 192.168.25.4
.\.venv\Scripts\python.exe -m simuladores.fonte_virtual --id FONTE_D --kind noise --advertise-ip 192.168.25.4
```

Também é possível usar **Fonte A 100% virtual** (gRPC dentro do processo-fonte), mas **não** ao mesmo tempo que a Fonte A física/bridge com o mesmo identificador e porta 50051:

```powershell
.\.venv\Scripts\python.exe -m simuladores.fonte_virtual --id FONTE_A --kind temperature --control --grpc-port 50051 --advertise-ip 192.168.25.4
```

## 4. Firmware: gravação da ESP8266 como Fonte A

1. Feche a Arduino IDE e extraia o novo projeto em pasta diferente da antiga. **Não misture arquivos de versões diferentes.**
2. Abra `firmware/Fonte_DHT22_OLED/Fonte_DHT22_OLED.ino`.
3. Crie `firmware/Fonte_DHT22_OLED/Secrets.h` baseado em `Secrets.example.h`, configurando seu SSID e senha Wi-Fi locais. **Não coloque senhas em repositórios públicos**; a senha anterior não foi colocada neste pacote.
4. Em `Config.h` confira `SOURCE_ID = "FONTE_A"`, `SOURCE_CONTROLLABLE = true` e `SOURCE_KIND = "termohigrometro_ctrl"`. Já vêm configurados.
5. Bibliotecas Arduino: **Adafruit SSD1306 oficial**, **Adafruit GFX Library**, **DHT sensor library**, **Adafruit Unified Sensor**. Placa NodeMCU 1.0 ESP-12E.
6. Ligue DHT22 **VCC=3V3, DATA=D2/GPIO4, GND=GND**; OLED interno **SDA=D5/GPIO14**, **SCL=D6/GPIO12** (verifique revisão). Grave.
7. OLED alterna a cada 5 s temperatura/umidade com status Wi-Fi/IP/Gateway. Monitore Serial a **115200 baud**. Procure `TRABALHO 01 - FONTE_A`, `Gateway encontrado ...`, `UDP Protobuf enviado...`.
8. Inicie Gateway **e** Bridge com o IP da ESP e abra o painel. Aguarde anúncio de `FONTE_A` com `gRPC=192.168.25.4:50051`.

**Comandos do controle:** ativar/desativar telemetria, trocar intervalo (**2000 a 3600000 ms**), alterar limiar de temperatura (**-40 a 80°C validado no painel**) e simular/recuperar falha. Na simulação de falha a ESP interrompe anúncios/telemetria, mas mantém socket de controle UDP para a recuperação. O bridge continua anunciando o estado ao Gateway.

## 5. Consultas do painel

- Lista de fontes e estados, mostrando indicação clara se há gRPC disponível.
- Gráficos de temperatura, umidade, CO₂ e ruído com até 100 amostras históricas.
- Média, mínimo, máximo e desvio padrão por janela temporal e fonte, calculados pelo Gateway sobre SQLite (4 consultas distintas).
- Indicadores com os últimos dados da Fonte A e contagem de fontes online.
- Controles de intervalos, limiares, ativação e falha simulada de fontes controláveis.

**SQLite:** caminho padrão `dados/telemetria.sqlite3`. Para não misturar registros anteriores com a Fonte A, considere gerar outro banco de teste (`--db dados/demonstracao_A.sqlite3`).

## 6. Diagnóstico

- **`FONTE_A` aparece sem gRPC**: o MCU foi descoberto, mas falta iniciar `fonte_a_bridge.bridge` com `--node-ip` correto. O Gateway preserva o endpoint gRPC após recebê-lo do bridge.
- **`GW: OK` no OLED não comprova entrega do UDP**; verifique linhas `UDP FONTE_A` no Gateway.
- **Client connected mas sem leituras:** `list` pode retornar fontes sem telemetria. Confira `50002/UDP`, Firewall e Wi-Fi.
- **Bridge timeout/ESP nao respondeu:** verifique IP NodeMCU, `Config.h` com `SOURCE_CONTROLLABLE=true` e rede/firewall UDP `50031`.
- **`Connection refused` no painel:** inicie o Gateway primeiro e use a porta TCP correta.
- **Painel não abre:** teste `http://127.0.0.1:8080`, sem HTTPS, e se a porta já está em uso utilize `--web-port 8081`.
- **`ModuleNotFoundError: grpc`**: instale o `requirements.txt` na `.venv` do Python 3.12.
- **Firewall no Windows**, executado como administrador, para permitir NodeMCU:

```powershell
New-NetFirewallRule -DisplayName 'Trabalho01 - NodeMCU UDP' -Direction Inbound -Action Allow -Protocol UDP -LocalPort 50001,50002 -RemoteAddress 192.168.25.0/24 -Profile Any
```

Não execute esta regra se ela já existir. Não é necessário abrir a porta web 8080 na rede: o painel escuta somente loopback local.

## 7. Testes

A partir da raiz do projeto, após instalar `pytest` opcionalmente:

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest -q
```

Os testes cobrem Protobuf, Gateway/SQLite/TCP, gRPC, bridge UDP e endpoints/validação do painel Web. A gravação/compilação real em placa ESP8266 deve ser verificada na Arduino IDE e os comandos testados no equipamento físico.

## 8. Segurança

O painel é restrito a `127.0.0.1` e não possui autenticação porque é uma ferramenta local para o trabalho. **Não exponha esse painel nem a porta gRPC 50051 à Internet**. O controle UDP não dispõe de autenticação criptográfica, e gRPC utiliza canal inseguro na LAN de laboratório; para produção, implementar autenticação e TLS, ACL de clientes e assinatura dos comandos. Não publique seu `Secrets.h`.
