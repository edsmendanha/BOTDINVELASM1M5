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
# SEGURANÇA: impede operações ao vivo em OTC quando a conta for REAL
# Recomendado manter false para conta real
allow_otc_live = false

# --- Universo de ativos para M5 ---
# Controla quais mercados o bot usa ao montar o pool de ativos no M5.
# As duas flags são independentes e podem ser combinadas livremente.
#
# m5_allow_otc = true           → inclui ativos OTC  (ex: AUDCAD-OTC)
# m5_allow_open_market = true   → inclui ativos de mercado aberto (ex: EURUSD-OP)
#
# Combinações possíveis:
#   otc=true  + open_market=true  → pool MISTO OTC + mercado aberto (padrão)
#   otc=true  + open_market=false → apenas OTC
#   otc=false + open_market=true  → apenas mercado aberto
m5_allow_otc         = true
m5_allow_open_market = true
```

> ⚠️ **Importante:** Quando `allow_otc_live = false` (padrão), o bot **aborta
> automaticamente** se você tentar operar em conta REAL + OTC. Operações reais
> devem usar apenas Mercado Aberto (ativos `-OP`). Isso se aplica também ao M5
> quando `m5_allow_otc = true`.

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

> ⚠️ **IMPORTANTE**

Por padrão (`allow_otc_live = false`), o bot **bloqueia automaticamente**
qualquer tentativa de operar em OTC usando conta REAL.

Isso protege de operações acidentais em ativos OTC com dinheiro real.

**Para testes em DEMO:** pode usar OTC à vontade (incluindo pool misto M5).

**Para operar real:** use apenas Mercado Aberto (ativos com sufixo `-OP`).
Configure `m5_allow_otc = false` e `m5_allow_open_market = true` para garantir
que o M5 não tente entrar em OTC em conta real.

**Se precisar habilitar OTC em real (não recomendado):**
```ini
[MARKET]
allow_otc_live = true
```

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

---

## Pool Dinâmico M5 (`pool_dynamic_enable = true`)

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
- ✅ Filtros de regime ATR/ADX/BBW/Slope (M1: regra 2-de-4)
- ✅ Filtros estruturais M1 (1/3 micro-range) e M5 (extremo 20% do range)
- ✅ Multi-ativo com re-ranking por regime (M1)
- ✅ Prioridade digital com fallback para binária
- ✅ Parâmetros externalizados no config.txt (seções M1 e M5 separadas)
- ✅ Canal Keltner como score adicional
- ✅ Pivôs/Fractais (5 barras) para contexto estrutural
- ✅ Padrões Engolfo Bullish/Bearish e Pinça Top/Bottom
- ✅ Estratégia Respiro (continuação: impulso → pullback → entrada)
- ✅ Restrição de OTC em conta real
- ✅ Pool Dinâmico M5: janela móvel de scoring, Donchian dead-market, escalonamento por universo, remoção imediata de asset_closed, novos pesos (pending_timeout, latency_guard, win/loss trade), freeze_skip throttle
- ✅ M5 pool misto: suporte configurável a OTC + mercado aberto via `m5_allow_otc` / `m5_allow_open_market`; sniper M5 ativo por padrão
- 🗂️ M15 — estrutura reservada no config.txt, lógica a implementar futuramente

---

## Versão

`2026-04-05-m5-open-market-v9`
