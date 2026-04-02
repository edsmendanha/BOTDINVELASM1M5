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

#### `[MARKET]` — Segurança
```ini
[MARKET]
# SEGURANÇA: impede operações ao vivo em OTC quando a conta for REAL
# Recomendado manter false para conta real
allow_otc_live = false
```

> ⚠️ **Importante:** Quando `allow_otc_live = false` (padrão), o bot **aborta
> automaticamente** se você tentar operar em conta REAL + OTC. Operações reais
> devem usar apenas Mercado Aberto (ativos `-OP`).

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
v15_score_min           = 55    # score mínimo para entrada (0–145)
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
- Score máximo: ~145 pts
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

**Para testes em DEMO:** pode usar OTC à vontade.

**Para operar real:** use apenas Mercado Aberto (ativos com sufixo `-OP`).

**Se precisar habilitar OTC em real (não recomendado):**
```ini
[MARKET]
allow_otc_live = true
```

---

## Arquivo Ativos.txt

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

[BINARIA M5]
EURUSD-OP
```

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
- 🗂️ M15 — estrutura reservada no config.txt, lógica a implementar futuramente

---

## Versão

`2026-04-02-config-extern-v6`
