# BOT DINVELAS M1/M5

Bot de automação para IQ Option com motor de reversão V15, Canal Keltner,
Pivôs/Fractais, padrões de candlestick avançados e estratégia Respiro.

---

## Início Rápido

1. Instale as dependências:
   ```bash
   pip install configobj iqoptionapi
   ```

2. Edite o `config.txt` com suas credenciais e parâmetros de estratégia.

3. Edite o `Ativos.txt` com os ativos que deseja operar (ver formato abaixo).

4. Execute o bot:
   ```bash
   python BOTDINVELAS_M1M5.py
   ```

---

## Configuração (config.txt)

Todos os parâmetros de estratégia estão externalizados no `config.txt`.
**Não é necessário editar o código Python** para ajustar filtros ou thresholds.

### Seções disponíveis

#### `[LOGIN]`
```ini
[LOGIN]
email = seu@email.com
senha = suasenha
```

#### `[AJUSTES]`
```ini
[AJUSTES]
tipo = digital          # tipo padrão: digital ou binarias
purchase_buffer_seconds = 1
```

#### `[MARKET]` — Segurança e Universo de Ativos M5
```ini
[MARKET]
# OTC em conta real: true = permite (padrão v13+), false = bloqueia.
allow_otc_live = true

# --- Universo de ativos para M5 ---
# Gerenciado automaticamente pelo perfil de mercado selecionado no menu.
# Você também pode forçar manualmente se não quiser usar o menu de perfil.
m5_allow_otc         = true
m5_allow_open_market = true
```

> 📝 Para M5, o menu de inicialização apresenta perfis **OTC / OPEN / MISTO**
> que definem automaticamente `m5_allow_otc` e `m5_allow_open_market` além de
> carregar os thresholds ATR/ADX/slope/janela calibrados para aquele mercado.
> Você não precisa editar esses flags manualmente entre execuções.

> 📝 **Para M1**, o mercado é selecionado interativamente no menu de inicialização.
> Os flags `m5_allow_otc` e `m5_allow_open_market` são exclusivos do M5.

#### `[SLEEP]`
```ini
[SLEEP]
idle_sleep_m1    = 0.20
idle_sleep_m5    = 1.50
pending_sleep_m1 = 0.25
pending_sleep_m5 = 1.10
```

#### `[RISK]`
```ini
[RISK]
amount_mode        = fixed     # fixed ou percent
amount_fixed       = 1.0       # valor fixo por operação
amount_percent     = 1.0       # percentual do saldo (se mode=percent)
amount_recalc_each = true      # recalcular percentual a cada entrada
amount_min         = 0.01
stop_loss_pct      = 0.0       # 0 = desativado
stop_win_pct       = 0.0
max_entries        = 0         # 0 = ilimitado
```

---

### Configuração por Timeframe — `[M1]` e `[M5]`

Cada timeframe tem sua própria seção com parâmetros independentes.
Altere em `[M1]` para ajustar M1 sem afetar M5, e vice-versa.

#### Modo de Entrada
```ini
[M1]
# reversal    = Motor V15 (reversão por score RSI+BB+Wick+Keltner)
# continuation = Estratégia Respiro (impulso → pullback → continuação)
entry_mode = reversal
```

#### Filtros de Regime
```ini
[M1]
enable_atr_filter   = true
atr_period          = 14
atr_adaptive_window = 30
atr_adaptive_factor = 0.45
atr_max_thr         = 0.00014
atr_min_ratio       = 0.000002  # volatilidade mínima M1

enable_trend_filter = true
adx_period          = 14
adx_min             = 3         # ADX mínimo M1 (mais baixo = mais entradas)
bb_period           = 20
bb_std              = 2.0
bb_width_min        = 0.00003   # BB width mínimo M1
slope_lookback      = 8
slope_min           = 0.000003  # slope EMA mínimo M1
entry_window_seconds = 30       # janela de entrada (s a partir do início da vela)
```

```ini
[M5]
adx_min             = 18.0      # ADX mínimo M5 (mais alto = mais seletivo)
bb_width_min        = 0.00070
slope_min           = 0.00012
entry_window_seconds = 25
```

#### Motor de Reversão V15
```ini
[M1]
v15_score_min           = 55    # score mínimo para entrada (0–135)
v15_score_gap_min       = 1     # diferença mínima call vs put
v15_confirm_polls       = 1     # polls de confirmação consecutivos
v15_rsi_period          = 14
v15_rsi_oversold        = 30
v15_rsi_overbought      = 70
v15_bb_period           = 20
v15_bb_std              = 2.0
v15_bb_proximity        = 0.25  # fração da banda para "próximo do extremo"
v15_impulse_lookback    = 5
v15_context_lookback    = 12
v15_wick_ratio          = 0.45  # ratio mínimo de sombra
v15_fallback_near_score = 38    # score mínimo para ativar fallback harami/engolfo
```

#### Canal Keltner
```ini
[M1]
# EMA(hlc3, period) ± RMA(TR, period)*shift
# Bônus de 0–20 pts quando preço toca extremo do canal
keltner_enable = true
keltner_period = 20
keltner_shift  = 1.5
```

#### Pivôs / Fractais (5 barras)
```ini
[M1]
# Detecta topos/fundos estruturais: verifica left=2, right=2 velas ao redor
# Registra proximidade no PATTERNS_CSV (campo pivot_prox)
pivot_enable        = true
pivot_left          = 2
pivot_right         = 2
pivot_proximity_pct = 0.002   # % de distância máxima do pivô para "na zona"
```

#### Estratégia Respiro (Continuação)
```ini
[M1]
# Só funciona quando entry_mode = continuation
respiro_enable               = false    # true para ativar
respiro_impulse_lookback     = 5        # velas para detectar a pernada
respiro_min_impulse          = 0.0010   # variação mínima da pernada
respiro_pullback_max_frac    = 0.618    # retração máxima (0.618 = Fibonacci)
respiro_max_pullback_candles = 3        # máximo de velas no pullback
respiro_trigger              = close_over_high  # gatilho de continuação
respiro_confirm_polls        = 1
```

---

## Modos de Entrada

### 1) Reversão (V15) — padrão
- Motor de score composto: RSI + BB + Wick + Impulso/Contexto + Keltner + Engolfo/Pinça
- Score máximo: 135 pts (25+25+25+25+20+15)
- Sinal disparado quando score ≥ `v15_score_min` com vantagem ≥ `v15_score_gap_min`
- Filtros estruturais M1 (1/3 do micro-range) e M5 (20% extremo do range)

### 2) Continuação (Respiro)
- Detecta: **pernada** (impulso forte) → **respiro** (pullback parcial) → **gatilho**
- Entrada na continuação da tendência após o pullback
- Ative com `entry_mode = continuation` em `[M1]` ou `[M5]` no config.txt
- Requer também `respiro_enable = true`

---

## Padrões de Candlestick

O bot usa os seguintes padrões (implementados com regras objetivas):

| Padrão | Tipo | Uso |
|--------|------|-----|
| Engolfo de Alta (Bullish Engulfing) | Sinal de alta | Bônus de 15pts no score V15 |
| Engolfo de Baixa (Bearish Engulfing) | Sinal de baixa | Bônus de 15pts no score V15 |
| Pinça de Fundo (Tweezer Bottom) | Sinal de alta | Bônus de 10pts no score V15 |
| Pinça de Topo (Tweezer Top) | Sinal de baixa | Bônus de 10pts no score V15 |
| Harami Bullish/Bearish | Reversão | Fallback quando V15 quase passa |
| Hammer | Reversão altista | Fallback quando V15 quase passa |

---

## Segurança: OTC em Conta Real

> ℹ️ **Novo comportamento padrão (v13)**

Por padrão (`allow_otc_live = true`), o bot **permite** operar em OTC com
conta REAL. Para bloquear OTC em conta real, defina `allow_otc_live = false`.

```ini
[MARKET]
# true  = permite OTC em conta real (padrão v13+)
# false = bloqueia OTC em conta real (proteção explícita)
allow_otc_live = true
```

> ⚠️ Ao bloquear (`allow_otc_live = false`), qualquer tentativa de usar OTC
> em conta REAL faz o bot abortar no início com mensagem explicativa.

---

## Perfis de Mercado M5 (OTC / OPEN / MISTO)

A partir da v13, o menu de inicialização M5 apresenta uma seleção de **perfil
de mercado** em vez de ler os flags diretamente do config.txt. Cada perfil
define:

- Quais ativos entram no universo (OTC, -OP ou ambos).
- Thresholds calibrados para o tipo de mercado (ADX, ATR, BB, slope, janela).

| Perfil | Seção config.txt | Ativos | ADX_min | ATR_min_ratio | BB_min | slope_min |
|--------|-----------------|--------|---------|--------------|--------|-----------|
| **OTC**   | `[PROFILE_OTC]`   | apenas OTC   | 10.0 | 0.000010 | 0.00045 | 0.000015 |
| **OPEN**  | `[PROFILE_OPEN]`  | apenas -OP   | 14.0 | 0.000020 | 0.00060 | 0.000030 |
| **MISTO** | `[PROFILE_MISTO]` | OTC + -OP   | 10.0 | 0.000010 | 0.00045 | 0.000015 |

### Como funciona no menu

```
🌍 PERFIL DE MERCADO M5
======================================================================
  1) OTC   — apenas ativos OTC (24/7)
  2) OPEN  — apenas Mercado Aberto (ativos -OP)
  3) MISTO — OTC + Mercado Aberto (pool misto)
```

Ao selecionar um perfil, o bot carrega automaticamente todos os thresholds
da seção correspondente (`[PROFILE_OTC]`, `[PROFILE_OPEN]`, `[PROFILE_MISTO]`)
no `config.txt`, sem necessidade de editar manualmente os parâmetros.

### Personalizar um perfil

Para ajustar os thresholds de um perfil, edite a seção correspondente:

```ini
[PROFILE_OTC]
m5_allow_otc         = true
m5_allow_open_market = false
adx_min              = 10.0
atr_min_ratio        = 0.000010
bb_width_min         = 0.00045
slope_min            = 0.000015
entry_window_seconds = 25
```

---

## Seleção Inicial de Ativos por Ranking (M5 + Pool Dinâmico)

Quando o pool dinâmico M5 está ativo (`pool_dynamic_enable = true`), o bot
**não** toma os primeiros N ativos do `Ativos.txt` em ordem — em vez disso,
executa um ranking de todos os candidatos elegíveis no universo e seleciona
o pool inicial pelos **melhor pontuados**.

### Algoritmo de ranking

Para cada candidato elegível (aberto, tipo de mercado correto, no Ativos.txt):

1. **Payout** — obtido via `API.get_all_profit()` (digital preferido, binary
   fallback). Fallback para 80% quando a API não retorna o valor.
2. **Regime M5** — score normalizado baseado em:
   - `ATR_ratio / ATR_MIN_M5` (volatilidade)
   - `ADX / ADX_MIN_M5` (força de tendência)
   - `BB_width / BB_WIDTH_MIN_M5` (expansão de Bollinger)
3. **Score final** = `0.4 × regime_norm + 0.6 × payout`
4. Seleciona os top `pool_size` ativos (determinístico, sem aleatoriedade).

### Log de seleção

O ranking completo é exibido no console e gravado em
`logs/pool_rebalance_m5.log`:

```
📊 [STARTUP RANKING M5] Avaliando 128 candidatos (pool_size=2)...
  Pos  Ativo                  Score  Detalhes
  ---  --------------------  -------  -------
    1  USDINR-OTC             0.846  score=0.846 payout=82% atr=2.10x adx=12.5(1.25x) bbw=1.80x ✅
    2  USDCHF-OTC             0.831  score=0.831 payout=80% atr=1.90x adx=11.2(1.12x) bbw=1.65x ✅
    3  AUDCAD-OTC             0.812  score=0.812 payout=80% atr=1.75x ...
  ...

  🎯 Pool inicial selecionado: USDINR-OTC, USDCHF-OTC
```

> 📝 O pool dinâmico M5 continua usando sua lógica de rebalanceamento
> periódico normal após a seleção inicial. O ranking de startup apenas
> determina quais ativos compõem o **primeiro** pool.

---

## Arquivo Ativos.txt

O arquivo `Ativos.txt` define o universo de ativos que o bot pode operar.
Os ativos podem ser OTC (`-OTC`), mercado aberto (`-OP`) ou sem sufixo
(incluídos em qualquer modo).

O pool misto M5 (padrão) aceita qualquer combinação de ativos listada:

```
[DIGITAL M1]
EURUSD-OP
EURJPY-OP
EURGBP-OP

[BINARIA M1]
EURUSD-OP
EURJPY-OP

[DIGITAL M5]
EURUSD-OP
EURJPY-OP
AUDCAD-OTC
USDZAR-OTC

[BINARIA M5]
EURUSD-OP
AUDCAD-OTC
```

> 📝 Quando `m5_allow_otc=true` e `m5_allow_open_market=true` (padrão), o bot
> inclui no pool M5 **qualquer** ativo da lista — tanto `-OTC` quanto `-OP`.
> Quando um ativo é **excluído** por um desses flags, o bot registra a razão
> em `logs/blocked_reasons_*.log` com o prefixo `market_filter_skip`, por exemplo:
> - `market_filter_skip [m5_allow_otc=false]` → ativo OTC ignorado porque OTC está desativado
> - `market_filter_skip [m5_allow_open_market=false]` → ativo -OP ignorado porque mercado aberto está desativado

### Símbolos de Índice (JXY, EXY, BXY, CXY, AXY, DXY)

Esses seis símbolos não possuem sufixo `-OP` na IQ Option, mas são tratados
internamente como **ativos de mercado aberto** (equivalentes a `-OP`):

| Símbolo | Descrição |
|---------|-----------|
| `DXY`   | Dollar Index (USD) |
| `EXY`   | Euro Index (EUR) |
| `JXY`   | Yen Index (JPY) |
| `BXY`   | Pound Index (GBP) |
| `AXY`   | Australian Dollar Index (AUD) |
| `CXY`   | Canadian Dollar Index (CAD) |

**Regras de elegibilidade:**

| Perfil | Elegível? |
|--------|-----------|
| **OPEN** (`m5_allow_open_market=true`) | ✅ Sim |
| **MISTO** (`m5_allow_otc=true` + `m5_allow_open_market=true`) | ✅ Sim |
| **OTC-only** (`m5_allow_open_market=false`) | ❌ Não (bloqueado com razão `m5_allow_open_market=false(index)`) |

Liste-os normalmente no `Ativos.txt` sem nenhum sufixo:

```
[DIGITAL M5]
JXY
EXY
BXY
CXY
AXY
DXY
```

---

## Watchdog de Conexão — Modo SAFE/HOLD e Reconexão Automática

O bot inclui um **watchdog de conexão** que detecta estados de degradação da
conexão com a IQ Option e entra automaticamente em modo **SAFE/HOLD** para
evitar operações com dados inconsistentes.

### Sinais de degradação detectados

| Sinal | Ação |
|-------|------|
| Warnings `"late 30 sec"` repetidos (3×) | Entra em SAFE/HOLD |
| API retorna `None` onde `dict` era esperado (`NoneType subscriptable`) | Entra em SAFE/HOLD imediatamente |
| `WebSocketConnectionClosedException` | Entra em SAFE/HOLD + força re-check imediato |
| `check_connect()` falha | Entra em SAFE/HOLD + inicia reconexão |

### Comportamento em SAFE/HOLD

- Novas decisões de trading são **suspensas**.
- Estados `arm`/`sniper` pendentes são **limpos** (sinais stale não são executados).
- O log registra claramente o motivo: `🔴 [WATCHDOG] SAFE/HOLD ativado — <razão>`.
- O bot continua executando o loop, aguardando reconexão.

### Reconexão com backoff exponencial

O processo de reconexão usa backoff exponencial (5s → 10s → 20s → … → 120s)
com até 10 tentativas, em vez do backoff fixo anterior (5 tentativas × 5s):

```
⚠️  Conexão perdida. Tentando reconectar...
🔄 Reconectando... (1/10) aguardando 5s
🔄 Reconectando... (2/10) aguardando 10s
...
✅ Reconectado (tentativa 3).
🟢 [WATCHDOG] SAFE/HOLD desativado — conexão restaurada. Aguardando candle novo por ativo.
```

### Retomada após reconexão

Após sair de SAFE/HOLD, o bot **aguarda pelo menos 1 candle novo** por ativo
rastreado antes de retomar análises. Isso garante que o sinal seguinte seja
baseado em dados frescos, e não em dados anteriores à queda de conexão.

---

O Pool Dinâmico M5 é ativado na seção `[M5]` do `config.txt` e permite que
o bot troque automaticamente os ativos do pool durante a operação, priorizando
aqueles com melhor qualidade operacional.

> ⚠️ **M1 não é afetado.** Apenas M5 usa o pool dinâmico.

### Parâmetros de Rebalanceamento

| Chave | Padrão | Descrição |
|-------|--------|-----------|
| `pool_dynamic_enable` | `false` | Ativa o pool dinâmico. |
| `pool_rebalance_minutes` | `15` | Intervalo entre rebalanceamentos (min). |
| `pool_dead_minutes` | `10` | Minutos sem atividade para declarar pool "morto" (troca agressiva). |
| `pool_swap_max_normal` | `1` | Máximo de trocas por rebalance normal. |
| `pool_swap_max_dead` | `2` | Máximo de trocas por rebalance quando pool está "morto". |
| `pool_asset_cooldown_minutes` | `30` | Cooldown antes de um ativo removido poder voltar. |

### Escalonamento por Universo

Quando `pool_swap_scale_with_universe = true`, o número de trocas cresce
proporcionalmente ao número de candidatos disponíveis além do pool atual.
Isso garante rotação mais ampla quando há ~20 ativos abertos.

| Chave | Padrão | Descrição |
|-------|--------|-----------|
| `pool_swap_scale_with_universe` | `true` | Ativa o escalonamento por universo. |
| `pool_swap_universe_divisor` | `8` | 1 troca extra a cada N candidatos elegíveis. |
| `pool_swap_max_abs` | `4` | Cap absoluto de trocas por ciclo. |

**Exemplo:** com 16 candidatos elegíveis e `divisor=8`, `n_swap` sobe em +2.

### Janela de Scoring

| Chave | Padrão | Descrição |
|-------|--------|-----------|
| `pool_score_window_minutes` | `60` | Janela móvel (min) para scoring. Eventos mais antigos são ignorados. `0` = sem janela (acumulado). |

### Pesos do Score

O score de cada ativo é calculado como soma ponderada de eventos dentro da
janela. Score mais alto = ativo melhor = menor chance de ser removido.

| Chave | Padrão | Evento |
|-------|--------|--------|
| `pool_score_w_confirmed` | `3.0` | Sinal confirmado (bônus) |
| `pool_score_w_win_trade` | `5.0` | Trade vencedor (bônus) |
| `pool_score_w_detected` | `0.5` | Ao menos 1 detected (bônus pequeno) |
| `pool_score_w_expired_rejected` | `1.0` | Sinal expirado/rejeitado (penalidade) |
| `pool_score_w_missed` | `1.5` | `missed_early_entry` (penalidade) |
| `pool_score_w_blocked` | `0.5` | Bloqueio por filtro de regime (penalidade) |
| `pool_score_w_pending_timeout` | `2.0` | `pending_timeout` (penalidade) |
| `pool_score_w_latency_guard` | `1.0` | `latency_guard` (penalidade) |
| `pool_score_w_asset_closed` | `3.0` | Ativo fechado (penalidade + remoção imediata) |
| `pool_score_w_loss_trade` | `1.0` | Trade perdedor (penalidade) |

### Detecção de Mercado Morto via Donchian

O bot calcula o **Donchian range ratio** = `(max_high - min_low) / mid_price`
dos últimos `dead_market_donchian_period` candles M5 para cada ativo no pool.
Ativos com range muito comprimido recebem penalidade extra no score.

| Chave | Padrão | Descrição |
|-------|--------|-----------|
| `dead_market_donchian_period` | `10` | Janela em candles M5. `0` = desabilitado. |
| `dead_market_range_ratio_thr` | `0.002` | Ratio mínimo. Abaixo → penalidade. |
| `dead_market_penalty` | `5.0` | Pontos subtraídos do score no rebalance. |

### Comportamento do asset_closed

Quando um ativo no pool M5 dinâmico é detectado como fechado (`asset_closed`),
ele é **removido imediatamente** do pool e entra em cooldown. Isso evita que
o bot fique "parado" tentando operar em ativo inacessível.

### Log pool_rebalance_m5.log

O arquivo `logs/pool_rebalance_m5.log` mostra:
- Universo total aberto (`universo=N`)
- Candidatos elegíveis (`elegíveis=N`)
- Score detalhado por ativo com breakdown por motivo
- Ativos removidos e adicionados com justificativa

---

## Logs e CSVs

Os arquivos de log ficam na pasta `logs/`:

| Arquivo | Conteúdo |
|---------|----------|
| `trades_log_*.csv` | Histórico de operações (resultado, profit, latência, estratégia) |
| `patterns_log_*.csv` | Sinais detectados com score completo (RSI, BB, Wick, Keltner, Engolfo, Pivô) |
| `latency_log_*.csv` | Medições de latência de compra |
| `blocked_reasons_*.log` | Razões de bloqueio de entrada |
| `runtime_errors_*.log` | Erros em tempo de execução |

### Novos campos em PATTERNS_CSV (v6+)

- `keltner_pts` — pontos do componente Keltner Channel
- `engulf_pts` — pontos do padrão Engolfo/Pinça
- `strategy` — estratégia usada (`v15`, `respiro`, `fallback`)
- `pivot_prox` — distância percentual ao último pivô estrutural

---

## Estrutura de Evolução (Roadmap)

- ✅ Motor V15 (reversão por score)
- ✅ Filtros de regime ATR/ADX/BBW/Slope (M1 e M5: regra 2-de-4)
- ✅ Filtros estruturais M1 (1/3 micro-range) e M5 (extremo 20% do range)
- ✅ Multi-ativo com re-ranking por regime (M1)
- ✅ Prioridade digital com fallback para binária
- ✅ Parâmetros externalizados no config.txt (seções M1 e M5 separadas)
- ✅ Canal Keltner como score adicional
- ✅ Pivôs/Fractais (5 barras) para contexto estrutural
- ✅ Padrões Engolfo Bullish/Bearish e Pinça Top/Bottom (pesos aumentados: engolfo 20pts, pinça 12pts)
- ✅ Estratégia Respiro (continuação: impulso → pullback → entrada)
- ✅ Pool Dinâmico M5: janela móvel de scoring, Donchian dead-market, escalonamento por universo, remoção imediata de asset_closed, novos pesos (pending_timeout, latency_guard, win/loss trade), freeze_skip throttle
- ✅ M5 pool misto: suporte configurável a OTC + mercado aberto via `m5_allow_otc` / `m5_allow_open_market`; sniper M5 ativo por padrão
- ✅ Perfis de mercado M5 (OTC / OPEN / MISTO): menu interativo carrega thresholds ATR/ADX/slope/janela calibrados por tipo de mercado
- ✅ Seleção inicial de pool M5 por ranking (payout + ATR/ADX health) em vez de ordem do Ativos.txt
- ✅ OTC em conta real habilitado por padrão (`allow_otc_live = true`); mantido como toggle configurável
- ✅ Símbolos de índice sem sufixo (JXY, EXY, BXY, CXY, AXY, DXY) tratados como mercado aberto — elegíveis em OPEN e MISTO, excluídos em OTC-only
- ✅ Watchdog de conexão SAFE/HOLD: detecta late_warnings, NoneType subscriptable, WebSocketConnectionClosedException; backoff exponencial (5s→120s, 10 tentativas); aguarda candle novo por ativo após reconexão; retry automático em `_safe_get_all_open_time` (3 tentativas)
- 🗂️ M15 — estrutura reservada no config.txt, lógica a implementar futuramente

---

## 📊 Assertividade Otimizada (v2026-04-07)

### Ajustes de Filtros M5
- **ADX_MIN_M5**: 18.0 → 8.0 (aceita mercado menos direcional)
- **BB_WIDTH_M5**: 0.00070 → 0.00045 (aceita mais compressão)
- **SLOPE_MIN_M5**: 0.00012 → 0.00006 (aceita mais lateralização)
- **ENTRY_WINDOW_M5**: 25s → 30s (reduz timeouts)

### Regra 2-de-4 (M1 e M5)
Permite até **2 filtros abaixo do mínimo** entre ATR, ADX, BBW e SLOPE.
- **Mais volume** de entradas qualificadas
- **Mantém qualidade** (não aceita todos sinais)

### Pesos de Padrões (Engolfo/Pinça)
- **Engolfo (Bullish/Bearish)**: 15 → 20 pts
- **Pinça (Tweezer Top/Bottom)**: 10 → 12 pts

### Pool Dinâmico Ajustado
- **Rebalance**: 15min → 18min (ativos têm mais tempo para sinais)
- **Dead market**: 10min → 12min (mais tolerância)
- **Cooldown**: 30min → 35min (evita reinclusão rápida)
- **Dead market penalty**: 5.0 → 3.0 (menos agressivo)

### Conexão Robusta
- **Late warning threshold**: 3 → 5 (menos sensível a flutuações)
- **`_safe_get_all_open_time`**: retry automático (3 tentativas com 0.5s entre elas)

### Mercado Aberto vs OTC
- **-op** (minúsculo) = mercado aberto
- **-OTC** (maiúsculo) = OTC
- Bot **nunca troca** entre variantes automaticamente
- Logs `asset_wrong_market_type` indicam quando pediu OTC mas só tem OP (ou vice-versa)

---

## Versão

`2026-04-07-assertividade-otimizada-v15`
