#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time
import json
import sys
import threading
import csv
import statistics
import traceback
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

from configobj import ConfigObj
from iqoptionapi.stable_api import IQ_Option

BOTDIN_VERSION = "2026-04-06-single-entry-open-market-v15"

# =========================
# ANSI COLOR HELPERS
# =========================
def _ansi_supported() -> bool:
    """Returns True if the terminal likely supports ANSI escape codes."""
    if not sys.stdout.isatty():
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            # Enable VIRTUAL_TERMINAL_PROCESSING (0x0004) on Windows 10+
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            return True
        except Exception:
            return False
    return True

_USE_ANSI: bool = _ansi_supported()

def _c(text: str, code: str) -> str:
    """Wrap *text* with ANSI *code* and reset, if the terminal supports it."""
    if _USE_ANSI:
        return f"\033[{code}m{text}\033[0m"
    return text

def cgreen(text: str) -> str:  return _c(text, "32")
def cred(text: str) -> str:    return _c(text, "31")
def cyellow(text: str) -> str: return _c(text, "33")
def ccyan(text: str) -> str:   return _c(text, "36")
def cbold(text: str) -> str:   return _c(text, "1")

# =========================
# CONFIG
# =========================
config = ConfigObj('config.txt')
email = config['LOGIN']['email']
senha = config['LOGIN']['senha']
tipo_default = config['AJUSTES'].get('tipo', 'binarias').strip().lower()


# =========================
# CONFIG HELPERS
# =========================
def _cfgget(section: str, key: str, default, type_fn=None):
    """Reads a config value safely, returning *default* when absent or invalid."""
    try:
        val = config.get(section, {}).get(key)
        if val is None:
            return default
        val = str(val).strip()
        if not val:
            return default
        return type_fn(val) if type_fn is not None else val
    except Exception:
        return default


def _cfgbool(section: str, key: str, default: bool) -> bool:
    """Reads a boolean config value (true/1/yes/sim → True)."""
    try:
        val = config.get(section, {}).get(key)
        if val is None:
            return default
        return str(val).strip().lower() in ('true', '1', 'yes', 'sim')
    except Exception:
        return default

DEBUG = True

IDLE_SLEEP_S_M1 = 0.20
IDLE_SLEEP_S_M5 = 1.50
PENDING_SLEEP_S_M1 = 0.25
PENDING_SLEEP_S_M5 = 1.10
PENDING_PRINT_THROTTLE_S = 12.0
PENDING_FREEZE_SECONDS_M5: float = 6.0    # Duration of M5 freeze window (seconds); 0 = disabled
PENDING_FREEZE_POLL_SLEEP_M5: float = 0.30 # Fast poll sleep during M5 freeze (seconds)
PENDING_MAX_AGE_SECONDS_M5: float = 45.0  # Max age (s) for M5 pending before dropping; 0 = disabled

RESULT_DELAY_AFTER_EXPIRY_SECONDS = 20

# =========================
# AGENDAMENTO / ATIVO FECHADO
# =========================
ALLOW_CLOSED_ASSET_IF_SCHEDULED = True
WAIT_ASSET_OPEN_IF_SCHEDULED = True
WAIT_ASSET_OPEN_TIMEOUT_SECONDS = 30 * 60  # 30 min
WAIT_ASSET_OPEN_CHECK_EVERY_SECONDS = 8
WAIT_ASSET_OPEN_PRINT_EVERY_SECONDS = 30

# =========================
# PASTAS / PATHS
# =========================
BASE_DIR = Path('.')
LOG_DIR = BASE_DIR / 'logs'
STATE_DIR = BASE_DIR / 'state'
PRESETS_DIR = BASE_DIR / 'presets'
STATE_PATH = STATE_DIR / 'bot_state.json'
FAVORITES_FILE = BASE_DIR / 'favoritos.txt'
ATIVOS_FILE = BASE_DIR / 'Ativos.txt'

INSTANCE_TAG = "unset"

BLOCKED_LOG: Optional[Path] = None
LATENCY_CSV: Optional[Path] = None
TRADES_CSV: Optional[Path] = None
PATTERNS_CSV: Optional[Path] = None
ERRORS_LOG: Optional[Path] = None
POOL_REBALANCE_LOG_M5: Optional[Path] = None
SINAIS_LOG: Optional[Path] = None
SINAIS_CONFIRMADOS_LOG: Optional[Path] = None
# Sinais acionáveis: apenas entradas que o bot DECIDIU executar (antes do envio da ordem).
# Contém: timestamp_confirmação | ativo | direção | TF | ENTRA_EM=HH:MM:SS | padrão
SINAIS_ACIONAVEIS_LOG: Optional[Path] = None


def _mkdirp(p: Path):
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _sanitize_tag(tag: str) -> str:
    tag = (tag or "").strip()
    if not tag:
        return "default"
    tag = tag.replace(" ", "_")
    tag = re.sub(r"[^A-Za-z0-9_\-\.]+", "", tag)
    return tag[:40] if len(tag) > 40 else tag


def _init_paths_with_tag(tag: str):
    global INSTANCE_TAG, BLOCKED_LOG, LATENCY_CSV, TRADES_CSV, PATTERNS_CSV, ERRORS_LOG
    global POOL_REBALANCE_LOG_M5, SINAIS_LOG, SINAIS_CONFIRMADOS_LOG, SINAIS_ACIONAVEIS_LOG

    _mkdirp(LOG_DIR)
    _mkdirp(STATE_DIR)
    _mkdirp(PRESETS_DIR)

    INSTANCE_TAG = _sanitize_tag(tag)
    BLOCKED_LOG = LOG_DIR / f'blocked_reasons_{INSTANCE_TAG}.log'
    LATENCY_CSV = LOG_DIR / f'latency_log_{INSTANCE_TAG}.csv'
    TRADES_CSV = LOG_DIR / f'trades_log_{INSTANCE_TAG}.csv'
    PATTERNS_CSV = LOG_DIR / f'patterns_log_{INSTANCE_TAG}.csv'
    ERRORS_LOG = LOG_DIR / f'runtime_errors_{INSTANCE_TAG}.log'
    POOL_REBALANCE_LOG_M5 = LOG_DIR / 'pool_rebalance_m5.log'
    SINAIS_LOG = LOG_DIR / f'sinais_{INSTANCE_TAG}.txt'
    SINAIS_CONFIRMADOS_LOG = LOG_DIR / f'sinais_confirmados_{INSTANCE_TAG}.txt'
    SINAIS_ACIONAVEIS_LOG = LOG_DIR / f'sinais_acionaveis_{INSTANCE_TAG}.txt'


# =========================
# GLOBAIS
# =========================
API = None
conta = None  # PRACTICE/REAL
tipo = tipo_default  # binary/digital

# Prioridade DIGITAL: True = tenta digital primeiro; cai para binária se fechada
PREFER_DIGITAL = True

# Aliases para abreviações populares → nome real no book da IQ Option
# Chaves normalizadas (maiúsculas, sem espaços, apenas A-Z/0-9/-)
ASSET_ALIASES: Dict[str, str] = {
    "DXY":                   "Dollar Index",
    "DOLLARINDEX":           "Dollar Index",
    "DOLLAR-INDEX":          "Dollar Index",
    "USDINDEX":              "Dollar Index",
    "USD-INDEX":             "Dollar Index",
    "POUNDINDEX":            "BXY",
    "POUND-INDEX":           "BXY",
    "GBPINDEX":              "BXY",
    "GBP-INDEX":             "BXY",
    "CANADIANDOLLARINDEX":   "CXY",
    "CANADIAN-DOLLAR-INDEX": "CXY",
    "CADDOLLARINDEX":        "CXY",
    "CADINDEX":              "CXY",
}

# Index symbols without -OP/-OTC suffix that are treated as OPEN-market candidates.
# These are eligible in OPEN and MIXED profiles when the market is open, but excluded
# in OTC-only profile (same rule as any other -OP asset).
OPEN_MARKET_INDEX_SYMBOLS: frozenset = frozenset({
    "JXY", "EXY", "BXY", "CXY", "AXY", "DXY",
})

PURCHASE_BUFFER_SECONDS = int(config.get('AJUSTES', {}).get('purchase_buffer_seconds', 1))

USE_BUY_THREAD = True
BUY_LATENCY_AVG = 0.9
BUY_LATENCY_ALPHA = 0.4
BUY_LATENCY_MARGIN = 1.0

CANDLES_LOOKBACK = 120
MIN_CANDLES_REQUIRED = 80

ENTRY_MODE = "reversal"
TIMEFRAME_MINUTES = 1
PENDING_EXPIRE_CANDLES = 2

# =====================================================================
# ESTRATÉGIA: PRIORIDADE DIGITAL — AJUSTE FINO AQUI
# =====================================================================
# Todos os parâmetros que impactam volume de entradas estão centralizados
# neste bloco. Altere SOMENTE aqui; o restante do código lê estas variáveis.
#
# Regra de qualidade M1: "2-de-4" — permite até 2 filtros abaixo do mínimo
# entre ATR, ADX, BBW e SLOPE. Aumenta volume sem abrir mão de todo critério.
# Para tornar mais rígido: diminua os valores abaixo (ex.: SLOPE 0.00003 → 0.00005).
# Para tornar mais livre:  aumente ENTRY_WINDOW ou diminua V15_SCORE_MIN ainda mais.
# =====================================================================

ENABLE_ATR_FILTER = True
ATR_PERIOD = 14
ATR_ADAPTIVE_WINDOW = 30
ATR_ADAPTIVE_FACTOR = 0.45        # Fator adaptativo para M1 (menos pressão no thr)
ATR_MAX_THR_M1 = 0.00014          # Cap do threshold ATR adaptativo para M1 (teto dinâmico)
ATR_MAX_THR_M5 = 0.00100          # Cap do threshold ATR adaptativo para M5 (teto dinâmico)
ATR_MIN_RATIO_ABS_M1 = 0.000002   # ← AJUSTE: volatilidade mínima M1 (0.000010 = livre)
ATR_MIN_RATIO_ABS_M5 = 0.000020
ATR_RATIO_QUEUE_M1 = deque(maxlen=ATR_ADAPTIVE_WINDOW)
ATR_RATIO_QUEUE_M5 = deque(maxlen=ATR_ADAPTIVE_WINDOW)

ENABLE_TREND_STRENGTH_FILTER = True
ADX_PERIOD = 14
ADX_MIN_M1 = 3                 # ← AJUSTE: ADX mínimo M1 (10.5 = aceita mercado fraco)
ADX_MIN_M5 = 18.0
BB_PERIOD = 20
BB_STD = 2.0
BB_WIDTH_MIN_M1 = 0.00003         # ← AJUSTE: BB width mínimo M1 (0.00018 = aceita compressão)
BB_WIDTH_MIN_M5 = 0.00070
SLOPE_LOOKBACK = 8
SLOPE_MIN_M1 = 0.000003            # ← AJUSTE: slope EMA mínimo M1 (0.00003 = aceita lateral)
SLOPE_MIN_M5 = 0.00012

ENTRY_WINDOW_SECONDS_M1 = 30      # ← AJUSTE: janela de entrada M1 (18s = menos missed_entry)
ENTRY_WINDOW_SECONDS_M5 = 25

OPEN_TIME_CACHE_TTL_S = 15
_last_open_time_cache: Dict[Tuple[str, Optional[str]], Tuple[bool, float]] = {}

RIGIDEZ_MODE = "normal"  # Estratégia única: "normal" — parâmetros ajustáveis no bloco acima

AMOUNT_MODE = "fixed"
AMOUNT_FIXED = 1.0
AMOUNT_PERCENT = 1.0
AMOUNT_RECALC_EACH = True
AMOUNT_MIN = 0.01

STOP_LOSS_PCT = 0.0
STOP_WIN_PCT = 0.0

# Máximo de entradas aceitas (0 = ilimitado). Bot para ao atingir esse total.
MAX_ENTRIES = 0

BLOCKED_COUNTERS = defaultdict(int)

# Máximo de ativos simultâneos por timeframe (sobrescrito por config.txt e menu)
MAX_ASSETS_M1: int = 2
MAX_ASSETS_M5: int = 4

# =========================
# M5 DYNAMIC POOL MANAGER
# =========================
M5_POOL_DYNAMIC_ENABLE: bool = False
M5_POOL_REBALANCE_MINUTES: float = 15.0
M5_POOL_DEAD_MINUTES: float = 10.0
M5_POOL_SWAP_MAX_NORMAL: int = 1
M5_POOL_SWAP_MAX_DEAD: int = 2
M5_POOL_ASSET_COOLDOWN_MINUTES: float = 30.0
M5_POOL_SCORE_W_CONFIRMED: float = 3.0
M5_POOL_SCORE_W_EXPIRED_REJECTED: float = 1.0
M5_POOL_SCORE_W_MISSED: float = 1.5
M5_POOL_SCORE_W_BLOCKED: float = 0.5
M5_POOL_SCORE_W_DETECTED: float = 0.5
# Extended M5 pool scoring weights
M5_POOL_SCORE_W_PENDING_TIMEOUT: float = 2.0
M5_POOL_SCORE_W_LATENCY_GUARD: float = 1.0
M5_POOL_SCORE_W_ASSET_CLOSED: float = 3.0
M5_POOL_SCORE_W_WIN_TRADE: float = 5.0
M5_POOL_SCORE_W_LOSS_TRADE: float = 1.0
# Sliding window duration for M5 pool scoring (minutes; 0 = cumulative / no window)
M5_POOL_SCORE_WINDOW_MINUTES: float = 60.0

# Dead-market detection via Donchian range (M5 pool)
M5_POOL_DEAD_MARKET_DONCHIAN_PERIOD: int = 10
M5_POOL_DEAD_MARKET_RANGE_RATIO_THR: float = 0.002
M5_POOL_DEAD_MARKET_PENALTY: float = 5.0

# Universe-size-aware swap scaling
M5_POOL_SWAP_SCALE_WITH_UNIVERSE: bool = True
M5_POOL_SWAP_UNIVERSE_DIVISOR: int = 8   # 1 extra swap per N candidates beyond pool
M5_POOL_SWAP_MAX_ABS: int = 4            # absolute cap on swaps per rebalance cycle

# =========================
# GLOBALS POR TIMEFRAME — Keltner, Pivô, Respiro, V15 per-TF
# (sobrescritos em _load_from_config() com valores do config.txt)
# =========================

# Modo de entrada por timeframe (reversal | continuation)
ENTRY_MODE_M1: str = "reversal"
ENTRY_MODE_M5: str = "reversal"

# Canal Keltner por TF
KELTNER_ENABLE_M1: bool = True
KELTNER_PERIOD_M1: int = 20
KELTNER_SHIFT_M1: float = 1.5
KELTNER_ENABLE_M5: bool = True
KELTNER_PERIOD_M5: int = 20
KELTNER_SHIFT_M5: float = 1.5

# Pivô/Fractal por TF
PIVOT_ENABLE_M1: bool = True
PIVOT_LEFT_M1: int = 2
PIVOT_RIGHT_M1: int = 2
PIVOT_PROXIMITY_PCT_M1: float = 0.002
PIVOT_ENABLE_M5: bool = True
PIVOT_LEFT_M5: int = 2
PIVOT_RIGHT_M5: int = 2
PIVOT_PROXIMITY_PCT_M5: float = 0.002

# Respiro (Continuação) por TF
RESPIRO_ENABLE_M1: bool = False
RESPIRO_IMPULSE_LOOKBACK_M1: int = 5
RESPIRO_MIN_IMPULSE_M1: float = 0.0010
RESPIRO_PULLBACK_MAX_FRAC_M1: float = 0.618
RESPIRO_MAX_PULLBACK_CANDLES_M1: int = 3
RESPIRO_TRIGGER_M1: str = "close_over_high"
RESPIRO_CONFIRM_POLLS_M1: int = 1
RESPIRO_ENABLE_M5: bool = False
RESPIRO_IMPULSE_LOOKBACK_M5: int = 5
RESPIRO_MIN_IMPULSE_M5: float = 0.0010
RESPIRO_PULLBACK_MAX_FRAC_M5: float = 0.618
RESPIRO_MAX_PULLBACK_CANDLES_M5: int = 3
RESPIRO_TRIGGER_M5: str = "close_over_high"
RESPIRO_CONFIRM_POLLS_M5: int = 1

# Restrição de OTC em conta real (true = permite por padrão; configure false para bloquear)
ALLOW_OTC_LIVE: bool = True

# M5 market universe flags (configuráveis em [MARKET] no config.txt)
# m5_allow_otc=false → pool M5 exclui ativos OTC (padrão: foco em mercado aberto)
# m5_allow_open_market=true → pool M5 inclui ativos de mercado aberto (-OP)
# Padrão: apenas mercado aberto. Para OTC ou misto, use o menu interativo
# ou ajuste m5_allow_otc=true no config.txt.
M5_ALLOW_OTC: bool = False
M5_ALLOW_OPEN_MARKET: bool = True

# V15 per-timeframe (defaults = valores globais; sobrescritos em _load_from_config)
V15_SCORE_MIN_M1: int = 55
V15_SCORE_MIN_M5: int = 55
V15_SCORE_GAP_MIN_M1: int = 1
V15_SCORE_GAP_MIN_M5: int = 1
V15_CONFIRM_POLLS_M1: int = 1
V15_CONFIRM_POLLS_M5: int = 1

# =========================
# ARM + SNIPER 0–5s (por TF)
# Quando sniper_mode=true:
#   Fase ARM  — arma o sinal na vela fechada com score mínimo elevado (arm_score_min).
#   Fase EXEC — executa SOMENTE nos primeiros SNIPER_WINDOW_SECONDS após a abertura
#               da vela alvo, com filtro anti-fakeout (preço vs open da vela atual).
# =========================
SNIPER_MODE_M1: bool = False
SNIPER_MODE_M5: bool = False
ARM_SCORE_MIN_M1: int = 60    # score mínimo V15 para ARM em M1 (mercado aberto)
ARM_SCORE_MIN_M5: int = 65    # score mínimo V15 para ARM em M5 (mercado aberto)
FALLBACK_ARM_SCORE_MIN_M1: int = 55  # score mínimo para fallback (harami/hammer/engolfo)
FALLBACK_ARM_SCORE_MIN_M5: int = 60
SNIPER_WINDOW_SECONDS: int = 5         # janela rígida de execução padrão (fallback; usar SNIPER_WINDOW_SECONDS_M1/M5)
SNIPER_WINDOW_SECONDS_M1: int = 5
SNIPER_WINDOW_SECONDS_M5: int = 5
SNIPER_ANTIFAKEOUT_EXTREME: bool = False  # fallback; usar SNIPER_ANTIFAKEOUT_EXTREME_M1/M5
SNIPER_ANTIFAKEOUT_EXTREME_M1: bool = False
SNIPER_ANTIFAKEOUT_EXTREME_M5: bool = False

# =========================
# SERVER TIME SYNCHRONIZATION
# =========================
# Mantém um offset entre o timestamp do servidor (IQ Option) e o relógio local.
# get_now_ts() usa time.time() + offset para obter um timestamp de referência
# sem depender de chamadas de rede a cada tick, reduzindo erros de timing no M5.
_SERVER_TIME_OFFSET: float = 0.0       # offset = server_ts - time.time()
_SERVER_TIME_OFFSET_TS: float = 0.0   # wall clock when offset was last updated
_SERVER_TIME_OFFSET_INTERVAL: float = 30.0  # refresh interval in seconds


def _sync_server_time_offset() -> None:
    """Atualiza o offset entre timestamp do servidor e relógio local.

    Chama API.get_server_timestamp(), calcula offset = server_ts - time.time()
    e persiste em _SERVER_TIME_OFFSET. Chamada periodicamente (não a cada tick).
    """
    global _SERVER_TIME_OFFSET, _SERVER_TIME_OFFSET_TS
    try:
        s_ts = float(API.get_server_timestamp())
        _SERVER_TIME_OFFSET = s_ts - time.time()
        _SERVER_TIME_OFFSET_TS = time.time()
    except Exception:
        pass  # mantém offset existente — sem bloquear o loop


def get_now_ts() -> int:
    """Retorna Unix timestamp (segundos) alinhado com o servidor IQ Option.

    Usa relógio local (time.time()) + offset cacheado para evitar chamadas de rede
    a cada tick. O offset é atualizado automaticamente a cada
    _SERVER_TIME_OFFSET_INTERVAL segundos de forma não-bloqueante.
    Fallback transparente para time.time() se o offset ainda não foi inicializado
    (offset inicial = 0.0, equivalente ao relógio local).
    """
    now_wall = time.time()
    if now_wall - _SERVER_TIME_OFFSET_TS > _SERVER_TIME_OFFSET_INTERVAL:
        _sync_server_time_offset()
    return int(now_wall + _SERVER_TIME_OFFSET)


def _load_from_config() -> None:
    """Carrega todos os parâmetros de estratégia do config.txt e sobrescreve os globals.

    Chamada uma vez no início do main. Garante retrocompatibilidade: se uma seção
    ou chave não existir no config.txt, o default hardcoded é preservado.
    """
    global IDLE_SLEEP_S_M1, IDLE_SLEEP_S_M5, PENDING_SLEEP_S_M1, PENDING_SLEEP_S_M5
    global PENDING_FREEZE_SECONDS_M5, PENDING_FREEZE_POLL_SLEEP_M5, PENDING_MAX_AGE_SECONDS_M5
    global AMOUNT_MODE, AMOUNT_FIXED, AMOUNT_PERCENT, AMOUNT_RECALC_EACH, AMOUNT_MIN
    global STOP_LOSS_PCT, STOP_WIN_PCT, MAX_ENTRIES
    global ALLOW_OTC_LIVE, M5_ALLOW_OTC, M5_ALLOW_OPEN_MARKET
    global ENABLE_ATR_FILTER, ATR_PERIOD, ATR_ADAPTIVE_WINDOW, ATR_ADAPTIVE_FACTOR
    global ATR_MIN_RATIO_ABS_M1, ATR_MIN_RATIO_ABS_M5, ATR_MAX_THR_M1, ATR_MAX_THR_M5
    global ATR_RATIO_QUEUE_M1, ATR_RATIO_QUEUE_M5
    global ENABLE_TREND_STRENGTH_FILTER, ADX_PERIOD
    global ADX_MIN_M1, ADX_MIN_M5, BB_PERIOD, BB_STD
    global BB_WIDTH_MIN_M1, BB_WIDTH_MIN_M5, SLOPE_LOOKBACK, SLOPE_MIN_M1, SLOPE_MIN_M5
    global ENTRY_WINDOW_SECONDS_M1, ENTRY_WINDOW_SECONDS_M5
    global V15_SCORE_MIN, V15_SCORE_GAP_MIN, V15_CONFIRM_POLLS
    global V15_RSI_PERIOD, V15_RSI_OVERSOLD, V15_RSI_OVERBOUGHT
    global V15_BB_PERIOD, V15_BB_STD, V15_BB_PROXIMITY
    global V15_IMPULSE_LOOKBACK, V15_CONTEXT_LOOKBACK
    global V15_WICK_RATIO, V15_CANDLES_NEEDED
    global V15_TREND_THRESHOLD, V15_IMPULSE_THRESHOLD
    global V15_IMPULSE_MULTIPLIER, V15_WICK_SCORE_MAX, V15_WICK_SCORE_FACTOR
    global V15_FALLBACK_NEAR_SCORE_M1
    global M5_EXTREME_CANDLES, M5_EXTREME_FRAC, M1_STRUCTURAL_CANDLES
    global V15_SCORE_MIN_M1, V15_SCORE_MIN_M5
    global V15_SCORE_GAP_MIN_M1, V15_SCORE_GAP_MIN_M5
    global V15_CONFIRM_POLLS_M1, V15_CONFIRM_POLLS_M5
    global ENTRY_MODE_M1, ENTRY_MODE_M5
    global KELTNER_ENABLE_M1, KELTNER_PERIOD_M1, KELTNER_SHIFT_M1
    global KELTNER_ENABLE_M5, KELTNER_PERIOD_M5, KELTNER_SHIFT_M5
    global PIVOT_ENABLE_M1, PIVOT_LEFT_M1, PIVOT_RIGHT_M1, PIVOT_PROXIMITY_PCT_M1
    global PIVOT_ENABLE_M5, PIVOT_LEFT_M5, PIVOT_RIGHT_M5, PIVOT_PROXIMITY_PCT_M5
    global RESPIRO_ENABLE_M1, RESPIRO_IMPULSE_LOOKBACK_M1, RESPIRO_MIN_IMPULSE_M1
    global RESPIRO_PULLBACK_MAX_FRAC_M1, RESPIRO_MAX_PULLBACK_CANDLES_M1
    global RESPIRO_TRIGGER_M1, RESPIRO_CONFIRM_POLLS_M1
    global RESPIRO_ENABLE_M5, RESPIRO_IMPULSE_LOOKBACK_M5, RESPIRO_MIN_IMPULSE_M5
    global RESPIRO_PULLBACK_MAX_FRAC_M5, RESPIRO_MAX_PULLBACK_CANDLES_M5
    global RESPIRO_TRIGGER_M5, RESPIRO_CONFIRM_POLLS_M5
    global MAX_ASSETS_M1, MAX_ASSETS_M5
    global M5_POOL_DYNAMIC_ENABLE, M5_POOL_REBALANCE_MINUTES, M5_POOL_DEAD_MINUTES
    global M5_POOL_SWAP_MAX_NORMAL, M5_POOL_SWAP_MAX_DEAD, M5_POOL_ASSET_COOLDOWN_MINUTES
    global M5_POOL_SCORE_W_CONFIRMED, M5_POOL_SCORE_W_EXPIRED_REJECTED
    global M5_POOL_SCORE_W_MISSED, M5_POOL_SCORE_W_BLOCKED, M5_POOL_SCORE_W_DETECTED
    global M5_POOL_SCORE_W_PENDING_TIMEOUT, M5_POOL_SCORE_W_LATENCY_GUARD
    global M5_POOL_SCORE_W_ASSET_CLOSED, M5_POOL_SCORE_W_WIN_TRADE, M5_POOL_SCORE_W_LOSS_TRADE
    global M5_POOL_SCORE_WINDOW_MINUTES
    global M5_POOL_DEAD_MARKET_DONCHIAN_PERIOD, M5_POOL_DEAD_MARKET_RANGE_RATIO_THR
    global M5_POOL_DEAD_MARKET_PENALTY
    global M5_POOL_SWAP_SCALE_WITH_UNIVERSE, M5_POOL_SWAP_UNIVERSE_DIVISOR, M5_POOL_SWAP_MAX_ABS
    global SNIPER_MODE_M1, SNIPER_MODE_M5, ARM_SCORE_MIN_M1, ARM_SCORE_MIN_M5
    global FALLBACK_ARM_SCORE_MIN_M1, FALLBACK_ARM_SCORE_MIN_M5
    global SNIPER_WINDOW_SECONDS, SNIPER_WINDOW_SECONDS_M1, SNIPER_WINDOW_SECONDS_M5
    global SNIPER_ANTIFAKEOUT_EXTREME, SNIPER_ANTIFAKEOUT_EXTREME_M1, SNIPER_ANTIFAKEOUT_EXTREME_M5

    # [MARKET]
    ALLOW_OTC_LIVE = _cfgbool('MARKET', 'allow_otc_live', ALLOW_OTC_LIVE)
    M5_ALLOW_OTC = _cfgbool('MARKET', 'm5_allow_otc', M5_ALLOW_OTC)
    M5_ALLOW_OPEN_MARKET = _cfgbool('MARKET', 'm5_allow_open_market', M5_ALLOW_OPEN_MARKET)

    # [SLEEP]
    IDLE_SLEEP_S_M1 = _cfgget('SLEEP', 'idle_sleep_m1', IDLE_SLEEP_S_M1, float)
    IDLE_SLEEP_S_M5 = _cfgget('SLEEP', 'idle_sleep_m5', IDLE_SLEEP_S_M5, float)
    PENDING_SLEEP_S_M1 = _cfgget('SLEEP', 'pending_sleep_m1', PENDING_SLEEP_S_M1, float)
    PENDING_SLEEP_S_M5 = _cfgget('SLEEP', 'pending_sleep_m5', PENDING_SLEEP_S_M5, float)
    PENDING_FREEZE_POLL_SLEEP_M5 = _cfgget('SLEEP', 'pending_freeze_poll_sleep_m5', PENDING_FREEZE_POLL_SLEEP_M5, float)

    # [RISK]
    AMOUNT_MODE = _cfgget('RISK', 'amount_mode', AMOUNT_MODE)
    AMOUNT_FIXED = _cfgget('RISK', 'amount_fixed', AMOUNT_FIXED, float)
    AMOUNT_PERCENT = _cfgget('RISK', 'amount_percent', AMOUNT_PERCENT, float)
    AMOUNT_RECALC_EACH = _cfgbool('RISK', 'amount_recalc_each', AMOUNT_RECALC_EACH)
    AMOUNT_MIN = _cfgget('RISK', 'amount_min', AMOUNT_MIN, float)
    STOP_LOSS_PCT = _cfgget('RISK', 'stop_loss_pct', STOP_LOSS_PCT, float)
    STOP_WIN_PCT = _cfgget('RISK', 'stop_win_pct', STOP_WIN_PCT, float)
    MAX_ENTRIES = _cfgget('RISK', 'max_entries', MAX_ENTRIES, int)

    def _load_tf(tf_label: str) -> None:
        """Loads [M1] or [M5] section and updates the corresponding globals."""
        sec = tf_label  # e.g. 'M1' or 'M5'
        is_m5 = (sec == 'M5')

        # Entry mode — validate: only 'reversal' and 'continuation' are valid
        _VALID_MODES = ('reversal', 'continuation')
        em = _cfgget(sec, 'entry_mode', 'reversal').strip().lower()
        if em not in _VALID_MODES:
            print(f"⚠️  config.txt [{sec}].entry_mode='{em}' inválido. Usando 'reversal'.")
            em = 'reversal'
        if is_m5:
            globals()['ENTRY_MODE_M5'] = em
        else:
            globals()['ENTRY_MODE_M1'] = em

        # ATR — M1 and M5 both load the full set of ATR parameters.
        # Shared globals (ENABLE_ATR_FILTER, ATR_PERIOD, ATR_ADAPTIVE_WINDOW, ATR_ADAPTIVE_FACTOR)
        # are loaded by both TFs; since _load_tf('M1') runs first and _load_tf('M5') second,
        # M5 values win when they differ. The per-TF caps (ATR_MAX_THR_M1/M5) are independent.
        if is_m5:
            globals()['ATR_MIN_RATIO_ABS_M5'] = _cfgget(sec, 'atr_min_ratio', ATR_MIN_RATIO_ABS_M5, float)
            globals()['ENABLE_ATR_FILTER'] = _cfgbool(sec, 'enable_atr_filter', ENABLE_ATR_FILTER)
            globals()['ATR_PERIOD'] = _cfgget(sec, 'atr_period', ATR_PERIOD, int)
            globals()['ATR_ADAPTIVE_WINDOW'] = _cfgget(sec, 'atr_adaptive_window', ATR_ADAPTIVE_WINDOW, int)
            globals()['ATR_ADAPTIVE_FACTOR'] = _cfgget(sec, 'atr_adaptive_factor', ATR_ADAPTIVE_FACTOR, float)
            globals()['ATR_MAX_THR_M5'] = _cfgget(sec, 'atr_max_thr', ATR_MAX_THR_M5, float)
        else:
            globals()['ENABLE_ATR_FILTER'] = _cfgbool(sec, 'enable_atr_filter', ENABLE_ATR_FILTER)
            globals()['ATR_PERIOD'] = _cfgget(sec, 'atr_period', ATR_PERIOD, int)
            globals()['ATR_ADAPTIVE_WINDOW'] = _cfgget(sec, 'atr_adaptive_window', ATR_ADAPTIVE_WINDOW, int)
            globals()['ATR_ADAPTIVE_FACTOR'] = _cfgget(sec, 'atr_adaptive_factor', ATR_ADAPTIVE_FACTOR, float)
            globals()['ATR_MAX_THR_M1'] = _cfgget(sec, 'atr_max_thr', ATR_MAX_THR_M1, float)
            globals()['ATR_MIN_RATIO_ABS_M1'] = _cfgget(sec, 'atr_min_ratio', ATR_MIN_RATIO_ABS_M1, float)

        # ADX/BB/Slope
        adx_key = 'ADX_MIN_M5' if is_m5 else 'ADX_MIN_M1'
        bb_key = 'BB_WIDTH_MIN_M5' if is_m5 else 'BB_WIDTH_MIN_M1'
        slp_key = 'SLOPE_MIN_M5' if is_m5 else 'SLOPE_MIN_M1'
        ew_key = 'ENTRY_WINDOW_SECONDS_M5' if is_m5 else 'ENTRY_WINDOW_SECONDS_M1'

        globals()['ENABLE_TREND_STRENGTH_FILTER'] = _cfgbool(sec, 'enable_trend_filter', ENABLE_TREND_STRENGTH_FILTER)
        globals()['ADX_PERIOD'] = _cfgget(sec, 'adx_period', ADX_PERIOD, int)
        globals()[adx_key] = _cfgget(sec, 'adx_min', globals()[adx_key], float)
        globals()['BB_PERIOD'] = _cfgget(sec, 'bb_period', BB_PERIOD, int)
        globals()['BB_STD'] = _cfgget(sec, 'bb_std', BB_STD, float)
        globals()[bb_key] = _cfgget(sec, 'bb_width_min', globals()[bb_key], float)
        globals()['SLOPE_LOOKBACK'] = _cfgget(sec, 'slope_lookback', SLOPE_LOOKBACK, int)
        globals()[slp_key] = _cfgget(sec, 'slope_min', globals()[slp_key], float)
        globals()[ew_key] = _cfgget(sec, 'entry_window_seconds', globals()[ew_key], int)

        # V15 per-TF
        sm_key = 'V15_SCORE_MIN_M5' if is_m5 else 'V15_SCORE_MIN_M1'
        sg_key = 'V15_SCORE_GAP_MIN_M5' if is_m5 else 'V15_SCORE_GAP_MIN_M1'
        cp_key = 'V15_CONFIRM_POLLS_M5' if is_m5 else 'V15_CONFIRM_POLLS_M1'
        globals()[sm_key] = _cfgget(sec, 'v15_score_min', globals()[sm_key], int)
        globals()[sg_key] = _cfgget(sec, 'v15_score_gap_min', globals()[sg_key], int)
        globals()[cp_key] = _cfgget(sec, 'v15_confirm_polls', globals()[cp_key], int)

        # V15 shared params — loaded from both [M1] and [M5] sections (M5 loaded last,
        # so M5 values overwrite M1 values for RSI_PERIOD, BB_PERIOD, etc.).
        # These calibration values are typically the same for both TFs; per-TF score/gap/polls
        # use dedicated globals (V15_SCORE_MIN_M1/M5, etc.) and are not overwritten here.
        globals()['V15_RSI_PERIOD'] = _cfgget(sec, 'v15_rsi_period', V15_RSI_PERIOD, int)
        globals()['V15_RSI_OVERSOLD'] = _cfgget(sec, 'v15_rsi_oversold', V15_RSI_OVERSOLD, int)
        globals()['V15_RSI_OVERBOUGHT'] = _cfgget(sec, 'v15_rsi_overbought', V15_RSI_OVERBOUGHT, int)
        globals()['V15_BB_PERIOD'] = _cfgget(sec, 'v15_bb_period', V15_BB_PERIOD, int)
        globals()['V15_BB_STD'] = _cfgget(sec, 'v15_bb_std', V15_BB_STD, float)
        globals()['V15_BB_PROXIMITY'] = _cfgget(sec, 'v15_bb_proximity', V15_BB_PROXIMITY, float)
        globals()['V15_IMPULSE_LOOKBACK'] = _cfgget(sec, 'v15_impulse_lookback', V15_IMPULSE_LOOKBACK, int)
        globals()['V15_CONTEXT_LOOKBACK'] = _cfgget(sec, 'v15_context_lookback', V15_CONTEXT_LOOKBACK, int)
        globals()['V15_WICK_RATIO'] = _cfgget(sec, 'v15_wick_ratio', V15_WICK_RATIO, float)
        globals()['V15_CANDLES_NEEDED'] = _cfgget(sec, 'v15_candles_needed', V15_CANDLES_NEEDED, int)
        globals()['V15_TREND_THRESHOLD'] = _cfgget(sec, 'v15_trend_threshold', V15_TREND_THRESHOLD, float)
        globals()['V15_IMPULSE_THRESHOLD'] = _cfgget(sec, 'v15_impulse_threshold', V15_IMPULSE_THRESHOLD, float)
        globals()['V15_IMPULSE_MULTIPLIER'] = _cfgget(sec, 'v15_impulse_multiplier', V15_IMPULSE_MULTIPLIER, int)
        globals()['V15_WICK_SCORE_MAX'] = _cfgget(sec, 'v15_wick_score_max', V15_WICK_SCORE_MAX, int)
        globals()['V15_WICK_SCORE_FACTOR'] = _cfgget(sec, 'v15_wick_score_factor', V15_WICK_SCORE_FACTOR, int)
        globals()['V15_FALLBACK_NEAR_SCORE_M1'] = _cfgget(sec, 'v15_fallback_near_score', V15_FALLBACK_NEAR_SCORE_M1, int)

        if is_m5:
            globals()['M5_EXTREME_CANDLES'] = _cfgget(sec, 'm5_extreme_candles', M5_EXTREME_CANDLES, int)
            globals()['M5_EXTREME_FRAC'] = _cfgget(sec, 'm5_extreme_frac', M5_EXTREME_FRAC, float)
            globals()['PENDING_FREEZE_SECONDS_M5'] = _cfgget(sec, 'pending_freeze_seconds_m5', PENDING_FREEZE_SECONDS_M5, float)
            globals()['PENDING_MAX_AGE_SECONDS_M5'] = _cfgget(sec, 'pending_max_age_seconds_m5', PENDING_MAX_AGE_SECONDS_M5, float)
            # Dynamic pool manager config
            globals()['M5_POOL_DYNAMIC_ENABLE'] = _cfgbool(sec, 'pool_dynamic_enable', M5_POOL_DYNAMIC_ENABLE)
            globals()['M5_POOL_REBALANCE_MINUTES'] = _cfgget(sec, 'pool_rebalance_minutes', M5_POOL_REBALANCE_MINUTES, float)
            globals()['M5_POOL_DEAD_MINUTES'] = _cfgget(sec, 'pool_dead_minutes', M5_POOL_DEAD_MINUTES, float)
            globals()['M5_POOL_SWAP_MAX_NORMAL'] = _cfgget(sec, 'pool_swap_max_normal', M5_POOL_SWAP_MAX_NORMAL, int)
            globals()['M5_POOL_SWAP_MAX_DEAD'] = _cfgget(sec, 'pool_swap_max_dead', M5_POOL_SWAP_MAX_DEAD, int)
            globals()['M5_POOL_ASSET_COOLDOWN_MINUTES'] = _cfgget(sec, 'pool_asset_cooldown_minutes', M5_POOL_ASSET_COOLDOWN_MINUTES, float)
            globals()['M5_POOL_SCORE_W_CONFIRMED'] = _cfgget(sec, 'pool_score_w_confirmed', M5_POOL_SCORE_W_CONFIRMED, float)
            globals()['M5_POOL_SCORE_W_EXPIRED_REJECTED'] = _cfgget(sec, 'pool_score_w_expired_rejected', M5_POOL_SCORE_W_EXPIRED_REJECTED, float)
            globals()['M5_POOL_SCORE_W_MISSED'] = _cfgget(sec, 'pool_score_w_missed', M5_POOL_SCORE_W_MISSED, float)
            globals()['M5_POOL_SCORE_W_BLOCKED'] = _cfgget(sec, 'pool_score_w_blocked', M5_POOL_SCORE_W_BLOCKED, float)
            globals()['M5_POOL_SCORE_W_DETECTED'] = _cfgget(sec, 'pool_score_w_detected', M5_POOL_SCORE_W_DETECTED, float)
            # Extended scoring weights
            globals()['M5_POOL_SCORE_W_PENDING_TIMEOUT'] = _cfgget(sec, 'pool_score_w_pending_timeout', M5_POOL_SCORE_W_PENDING_TIMEOUT, float)
            globals()['M5_POOL_SCORE_W_LATENCY_GUARD'] = _cfgget(sec, 'pool_score_w_latency_guard', M5_POOL_SCORE_W_LATENCY_GUARD, float)
            globals()['M5_POOL_SCORE_W_ASSET_CLOSED'] = _cfgget(sec, 'pool_score_w_asset_closed', M5_POOL_SCORE_W_ASSET_CLOSED, float)
            globals()['M5_POOL_SCORE_W_WIN_TRADE'] = _cfgget(sec, 'pool_score_w_win_trade', M5_POOL_SCORE_W_WIN_TRADE, float)
            globals()['M5_POOL_SCORE_W_LOSS_TRADE'] = _cfgget(sec, 'pool_score_w_loss_trade', M5_POOL_SCORE_W_LOSS_TRADE, float)
            globals()['M5_POOL_SCORE_WINDOW_MINUTES'] = _cfgget(sec, 'pool_score_window_minutes', M5_POOL_SCORE_WINDOW_MINUTES, float)
            # Dead-market detection (Donchian range)
            globals()['M5_POOL_DEAD_MARKET_DONCHIAN_PERIOD'] = _cfgget(sec, 'dead_market_donchian_period', M5_POOL_DEAD_MARKET_DONCHIAN_PERIOD, int)
            globals()['M5_POOL_DEAD_MARKET_RANGE_RATIO_THR'] = _cfgget(sec, 'dead_market_range_ratio_thr', M5_POOL_DEAD_MARKET_RANGE_RATIO_THR, float)
            globals()['M5_POOL_DEAD_MARKET_PENALTY'] = _cfgget(sec, 'dead_market_penalty', M5_POOL_DEAD_MARKET_PENALTY, float)
            # Universe-size-aware swap scaling
            globals()['M5_POOL_SWAP_SCALE_WITH_UNIVERSE'] = _cfgbool(sec, 'pool_swap_scale_with_universe', M5_POOL_SWAP_SCALE_WITH_UNIVERSE)
            globals()['M5_POOL_SWAP_UNIVERSE_DIVISOR'] = _cfgget(sec, 'pool_swap_universe_divisor', M5_POOL_SWAP_UNIVERSE_DIVISOR, int)
            globals()['M5_POOL_SWAP_MAX_ABS'] = _cfgget(sec, 'pool_swap_max_abs', M5_POOL_SWAP_MAX_ABS, int)
        else:
            globals()['M1_STRUCTURAL_CANDLES'] = _cfgget(sec, 'm1_structural_candles', M1_STRUCTURAL_CANDLES, int)

        # ARM + SNIPER 0–5s — carregado para ambas as TFs
        _sniper_key = 'SNIPER_MODE_M5' if is_m5 else 'SNIPER_MODE_M1'
        _arm_key    = 'ARM_SCORE_MIN_M5' if is_m5 else 'ARM_SCORE_MIN_M1'
        _fb_arm_key = 'FALLBACK_ARM_SCORE_MIN_M5' if is_m5 else 'FALLBACK_ARM_SCORE_MIN_M1'
        _sw_key     = 'SNIPER_WINDOW_SECONDS_M5' if is_m5 else 'SNIPER_WINDOW_SECONDS_M1'
        _afe_key    = 'SNIPER_ANTIFAKEOUT_EXTREME_M5' if is_m5 else 'SNIPER_ANTIFAKEOUT_EXTREME_M1'
        globals()[_sniper_key] = _cfgbool(sec, 'sniper_mode', globals()[_sniper_key])
        globals()[_arm_key]    = _cfgget(sec, 'arm_score_min', globals()[_arm_key], int)
        globals()[_fb_arm_key] = _cfgget(sec, 'fallback_arm_score_min', globals()[_fb_arm_key], int)
        globals()[_sw_key]     = _cfgget(sec, 'sniper_window_seconds', globals()[_sw_key], int)
        globals()[_afe_key]    = _cfgbool(sec, 'sniper_antifakeout_extreme', globals()[_afe_key])

        # Keltner
        ke_key = 'KELTNER_ENABLE_M5' if is_m5 else 'KELTNER_ENABLE_M1'
        kp_key = 'KELTNER_PERIOD_M5' if is_m5 else 'KELTNER_PERIOD_M1'
        ks_key = 'KELTNER_SHIFT_M5' if is_m5 else 'KELTNER_SHIFT_M1'
        globals()[ke_key] = _cfgbool(sec, 'keltner_enable', globals()[ke_key])
        globals()[kp_key] = _cfgget(sec, 'keltner_period', globals()[kp_key], int)
        globals()[ks_key] = _cfgget(sec, 'keltner_shift', globals()[ks_key], float)

        # Pivot
        pe_key = 'PIVOT_ENABLE_M5' if is_m5 else 'PIVOT_ENABLE_M1'
        pl_key = 'PIVOT_LEFT_M5' if is_m5 else 'PIVOT_LEFT_M1'
        pr_key = 'PIVOT_RIGHT_M5' if is_m5 else 'PIVOT_RIGHT_M1'
        pp_key = 'PIVOT_PROXIMITY_PCT_M5' if is_m5 else 'PIVOT_PROXIMITY_PCT_M1'
        globals()[pe_key] = _cfgbool(sec, 'pivot_enable', globals()[pe_key])
        globals()[pl_key] = _cfgget(sec, 'pivot_left', globals()[pl_key], int)
        globals()[pr_key] = _cfgget(sec, 'pivot_right', globals()[pr_key], int)
        globals()[pp_key] = _cfgget(sec, 'pivot_proximity_pct', globals()[pp_key], float)

        # Respiro
        re_key = 'RESPIRO_ENABLE_M5' if is_m5 else 'RESPIRO_ENABLE_M1'
        ril_key = 'RESPIRO_IMPULSE_LOOKBACK_M5' if is_m5 else 'RESPIRO_IMPULSE_LOOKBACK_M1'
        rmi_key = 'RESPIRO_MIN_IMPULSE_M5' if is_m5 else 'RESPIRO_MIN_IMPULSE_M1'
        rpf_key = 'RESPIRO_PULLBACK_MAX_FRAC_M5' if is_m5 else 'RESPIRO_PULLBACK_MAX_FRAC_M1'
        rpc_key = 'RESPIRO_MAX_PULLBACK_CANDLES_M5' if is_m5 else 'RESPIRO_MAX_PULLBACK_CANDLES_M1'
        rt_key = 'RESPIRO_TRIGGER_M5' if is_m5 else 'RESPIRO_TRIGGER_M1'
        rcp_key = 'RESPIRO_CONFIRM_POLLS_M5' if is_m5 else 'RESPIRO_CONFIRM_POLLS_M1'
        globals()[re_key] = _cfgbool(sec, 'respiro_enable', globals()[re_key])
        globals()[ril_key] = _cfgget(sec, 'respiro_impulse_lookback', globals()[ril_key], int)
        globals()[rmi_key] = _cfgget(sec, 'respiro_min_impulse', globals()[rmi_key], float)
        globals()[rpf_key] = _cfgget(sec, 'respiro_pullback_max_frac', globals()[rpf_key], float)
        globals()[rpc_key] = _cfgget(sec, 'respiro_max_pullback_candles', globals()[rpc_key], int)
        globals()[rt_key] = _cfgget(sec, 'respiro_trigger', globals()[rt_key])
        globals()[rcp_key] = _cfgget(sec, 'respiro_confirm_polls', globals()[rcp_key], int)

        # max_assets por TF
        ma_key = 'MAX_ASSETS_M5' if is_m5 else 'MAX_ASSETS_M1'
        globals()[ma_key] = _cfgget(sec, 'max_assets', globals()[ma_key], int)

    _load_tf('M1')
    _load_tf('M5')

    # Re-sync shared V15 global (keep backward compat: V15_SCORE_MIN stays as M1 default)
    globals()['V15_SCORE_MIN'] = globals()['V15_SCORE_MIN_M1']
    globals()['V15_SCORE_GAP_MIN'] = globals()['V15_SCORE_GAP_MIN_M1']
    globals()['V15_CONFIRM_POLLS'] = globals()['V15_CONFIRM_POLLS_M1']

    # Rebuild ATR queues if adaptive window changed
    globals()['ATR_RATIO_QUEUE_M1'] = deque(maxlen=globals()['ATR_ADAPTIVE_WINDOW'])
    globals()['ATR_RATIO_QUEUE_M5'] = deque(maxlen=globals()['ATR_ADAPTIVE_WINDOW'])

pending: Optional[Dict[str, Any]] = None
pending_id_active: Optional[Tuple[str, int, str, int]] = None
pending_lock_until_ts: int = 0
last_pending_print_ts_by_id: Dict[Tuple[str, int, str, int], float] = {}
_last_pending_status_printed_for_id: Optional[Tuple[str, int, str, int]] = None

# =========================
# RESULTADOS
# =========================
EXTRA_WAIT_SECONDS = 12
M1_RESULT_TIMEOUT = 80
M5_RESULT_TIMEOUT = 260

EARLY_LOSS_GUARD_SECONDS = 55
EARLY_LOSS_STABLE_SAMPLES = 4
EARLY_LOSS_SAMPLE_INTERVAL_S = 1.5
EARLY_LOSS_EPS = 0.02

# Número de ciclos de IDLE_SLEEP_S_M5 a aguardar quando pool de ativos está vazio
EMPTY_POOL_SLEEP_MULTIPLIER = 10

# Boot retry: tentativas e intervalo de espera ao buscar ativos na inicialização.
# Quando a API retorna None (instabilidade de websocket), o bot tenta novamente
# até BOOT_MAX_RETRIES vezes antes de iniciar com pool vazio.
BOOT_MAX_RETRIES: int = 10
BOOT_RETRY_SLEEP_S: float = 3.0

# Presets
PRESET_PATH: Optional[Path] = None


# =========================
# CSV
# =========================
def _ensure_csv_headers():
    assert LATENCY_CSV is not None
    assert TRADES_CSV is not None
    assert PATTERNS_CSV is not None

    if not LATENCY_CSV.exists():
        with LATENCY_CSV.open('w', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow(['ts_iso', 'instance_tag', 'delta_s', 'buy_latency_avg_s', 'method'])
    if not TRADES_CSV.exists():
        with TRADES_CSV.open('w', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow([
                'ts_iso', 'instance_tag',
                'ativo', 'tf_min', 'entry_mode', 'rigidez',
                'direcao', 'order_id',
                'result_method', 'result', 'profit',
                'balance_before', 'balance_after',
                'amount_used', 'buy_latency_avg_s',
                'pattern_name', 'pattern_from',
                'secs_left_at_buy',
                'trade_ativo', 'market_type',
                'strategy',
            ])
    if not PATTERNS_CSV.exists():
        with PATTERNS_CSV.open('w', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow([
                'ts_iso', 'instance_tag',
                'ativo', 'tf_min', 'event',
                'pattern_name', 'pattern_mode', 'pattern_from', 'expected_confirm_from',
                'direction_hint', 'confirmed', 'confirm_from',
                'rsi_pts', 'bb_pts', 'wick_pts', 'imp_pts', 'keltner_pts', 'engulf_pts',
                'call_score', 'put_score',
                'strategy', 'pivot_prox',
                'block_reason', 'details'
            ])


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def server_hhmmss() -> str:
    ts = get_now_ts()
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def _log_error(msg: str, exc: Optional[BaseException] = None):
    try:
        if ERRORS_LOG is not None:
            with ERRORS_LOG.open('a', encoding='utf-8') as f:
                f.write(f"{datetime.now().isoformat()} | {INSTANCE_TAG} | {msg}\n")
                if exc is not None:
                    f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
                    f.write("\n")
    except Exception:
        pass
    if DEBUG and exc:
        traceback.print_exc()


def _log_blocked(reason: str, details: Optional[str] = None):
    BLOCKED_COUNTERS[reason] += 1
    try:
        if BLOCKED_LOG is not None:
            with BLOCKED_LOG.open('a', encoding='utf-8') as f:
                ts = datetime.now().isoformat()
                f.write(f"{ts} | {INSTANCE_TAG} | {reason} | {details or ''}\n")
    except Exception:
        pass


def _log_pattern_row(
    ativo: str,
    tf_min: int,
    event: str,
    sig: Optional[Dict[str, Any]],
    confirmed: bool = False,
    confirm_from: Optional[int] = None,
    block_reason: Optional[str] = None,
    details: Optional[str] = None,
):
    """Grava uma linha no PATTERNS_CSV com todos os componentes de score."""
    try:
        if PATTERNS_CSV is None:
            return
        row = [
            now_iso(), INSTANCE_TAG,
            ativo, tf_min, event,
            sig.get("pattern_name", "") if sig else "",
            sig.get("pattern_mode", "") if sig else "",
            sig.get("pattern_from", "") if sig else "",
            sig.get("expected_confirm_from", "") if sig else "",
            sig.get("direction_hint", "") if sig else "",
            "1" if confirmed else "0",
            confirm_from if confirm_from is not None else "",
            sig.get("rsi_pts", "") if sig else "",
            sig.get("bb_pts", "") if sig else "",
            sig.get("wick_pts", "") if sig else "",
            sig.get("imp_pts", "") if sig else "",
            sig.get("keltner_pts", "") if sig else "",
            sig.get("engulf_pts", "") if sig else "",
            sig.get("call_score", "") if sig else "",
            sig.get("put_score", "") if sig else "",
            sig.get("strategy", "") if sig else "",
            sig.get("pivot_prox", "") if sig else "",
            block_reason or "",
            details or "",
        ]
        with PATTERNS_CSV.open('a', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow(row)
    except Exception:
        pass


def _log_sinal(
    ativo: str,
    tf: int,
    event: str,
    sig: Optional[Dict[str, Any]],
    block_reason: Optional[str] = None,
    details: Optional[str] = None,
) -> None:
    """Grava evento de sinal no arquivo sinais_<INSTANCE_TAG>.txt.

    Formato: ts_iso | instance_tag | ativo | tf | event | pattern_name | mode |
             pattern_from | expected_confirm_from | direction | call_score/put_score |
             block_reason | details
    """
    try:
        if SINAIS_LOG is None:
            return
        ts = datetime.now().isoformat()
        direction = sig.get("direction_hint", "") if sig else ""
        pattern_name = sig.get("pattern_name", "") if sig else ""
        mode = sig.get("pattern_mode", "") if sig else ""
        pattern_from = sig.get("pattern_from", "") if sig else ""
        expected_confirm_from = sig.get("expected_confirm_from", "") if sig else ""
        call_score = sig.get("call_score", "") if sig else ""
        put_score = sig.get("put_score", "") if sig else ""
        scores = f"call={call_score}/put={put_score}"
        line = (
            f"{ts} | {INSTANCE_TAG} | {ativo} | M{tf} | {event} | "
            f"{pattern_name} | {mode} | {pattern_from} | {expected_confirm_from} | "
            f"{direction} | {scores} | {block_reason or ''} | {details or ''}"
        )
        with SINAIS_LOG.open('a', encoding='utf-8') as f:
            f.write(line + "\n")
    except Exception:
        pass


def console_event(line: str):
    print(line)


def _log_sinal_confirmado(
    ativo: str,
    tf: int,
    direction: str,
    sig: Optional[Dict[str, Any]],
    entra_em_ts: Optional[int] = None,
) -> None:
    """Grava SOMENTE sinais efetivamente emitidos para compra em sinais_confirmados_<tag>.txt.

    Este arquivo contém APENAS as entradas que o bot efetivamente realizou (ordem aceita).
    Não inclui detected / rejected / pending_timeout.
    Formato: HH:MM:SS | ATIVO | DIRECAO | TF | ENTRA_EM=HH:MM:SS | PADRAO
    """
    try:
        if SINAIS_CONFIRMADOS_LOG is None:
            return
        ts_now = datetime.now().strftime("%H:%M:%S")
        direction_upper = direction.upper()
        tf_label = f"M{tf}"
        if entra_em_ts is not None:
            try:
                entra_hms = datetime.fromtimestamp(int(entra_em_ts)).strftime("%H:%M:%S")
            except Exception as e_ts:
                _log_error(f"_log_sinal_confirmado: entra_em_ts={entra_em_ts} inválido.", e_ts)
                entra_hms = ts_now
        else:
            entra_hms = ts_now
        pattern_name = sig.get("pattern_name", "") if sig else ""
        line = (
            f"{ts_now} | {ativo} | {direction_upper} | {tf_label} | "
            f"ENTRA_EM={entra_hms} | {pattern_name}"
        )
        with SINAIS_CONFIRMADOS_LOG.open('a', encoding='utf-8') as f:
            f.write(line + "\n")
    except Exception:
        pass


def _log_sinal_acionavel(
    ativo: str,
    tf: int,
    direction: str,
    sig: Optional[Dict[str, Any]],
    entra_em_ts: Optional[int] = None,
) -> None:
    """Grava sinais ACIONÁVEIS em sinais_acionaveis_<tag>.txt.

    Este arquivo contém APENAS sinais onde:
      - padrão confirmado
      - janela de entrada válida
      - bot DECIDIU entrar (registrado antes do envio da ordem, independente do resultado)

    É o arquivo de "sinais para publicar": somente entradas realmente agendadas/executadas.
    Formato: HH:MM:SS | ATIVO | DIRECAO | TF | ENTRA_EM=HH:MM:SS | PADRAO
    """
    try:
        if SINAIS_ACIONAVEIS_LOG is None:
            return
        ts_now = datetime.now().strftime("%H:%M:%S")
        direction_upper = direction.upper()
        tf_label = f"M{tf}"
        if entra_em_ts is not None:
            try:
                entra_hms = datetime.fromtimestamp(int(entra_em_ts)).strftime("%H:%M:%S")
            except Exception as e_ts:
                _log_error(f"_log_sinal_acionavel: entra_em_ts={entra_em_ts} inválido.", e_ts)
                entra_hms = ts_now
        else:
            entra_hms = ts_now
        pattern_name = sig.get("pattern_name", "") if sig else ""
        line = (
            f"{ts_now} | {ativo} | {direction_upper} | {tf_label} | "
            f"ENTRA_EM={entra_hms} | {pattern_name}"
        )
        with SINAIS_ACIONAVEIS_LOG.open('a', encoding='utf-8') as f:
            f.write(line + "\n")
    except Exception:
        pass


# =========================
# Display helpers
# =========================
def display_asset_name(asset: str) -> str:
    if not isinstance(asset, str):
        return str(asset)
    s = asset
    s = re.sub(r'-otc\b', '-OTC', s, flags=re.IGNORECASE)
    s = re.sub(r'-op\b', '-OP', s, flags=re.IGNORECASE)
    return s


def fmt_money_signed(v: Optional[float]) -> str:
    if v is None:
        return ""
    try:
        x = float(v)
        sign = "+" if x > 0 else ""
        return f"{sign}{x:.2f}"
    except Exception:
        return ""


def fmt_result_line(label: str, profit: Optional[float], method: Optional[str]) -> str:
    _ = method  # console não mostra método
    label_upper = label.upper()
    if label == "win":
        label_str = cgreen(f"Resultado: {label_upper} ✅")
    elif label == "loss":
        label_str = cred(f"Resultado: {label_upper} ❌")
    else:
        label_str = f"Resultado: {label_upper} ❓"
    partes = [label_str]
    if profit is not None:
        profit_str = fmt_money_signed(profit)
        if float(profit) > 0:
            partes.append(cgreen(f"Profit: {profit_str}"))
        elif float(profit) < 0:
            partes.append(cred(f"Profit: {profit_str}"))
        else:
            partes.append(f"Profit: {profit_str}")
    return " | ".join(partes)


# =========================
# Presets / Auto-tag
# =========================
def _asset_key_for_preset(asset: str) -> str:
    s = str(asset).upper().replace("-", "")
    s = re.sub(r"[^A-Z0-9]+", "", s)
    return s or "ASSET"


def _mode_key_for_preset(mode: str) -> str:
    m = str(mode or "").strip().lower()
    return "REV" if m == "reversal" else ("BRK" if m == "breakout" else "MODE")


def _rigidez_key_for_preset(rigidez: str) -> str:
    r = str(rigidez or "").strip().lower()
    return "RIG" if r == "rigida" else ("NOR" if r == "normal" else "RIGZ")


def _preset_filename(asset: str, tf_min: int, mode: str, rigidez: str) -> str:
    a = _asset_key_for_preset(asset)
    m = _mode_key_for_preset(mode)
    r = _rigidez_key_for_preset(rigidez)
    tf = f"M{int(tf_min)}"
    return f"{a}_{m}_{r}_{tf}.json"


def _auto_tag_from_choices(asset: str, tf_min: int, mode: str, rigidez: str) -> str:
    return _preset_filename(asset, tf_min, mode, rigidez).replace(".json", "")


def build_preset_dict(ativo: Optional[str] = None, ativo_chave: Optional[str] = None,
                      runtime_min: Optional[int] = None) -> Dict[str, Any]:
    account = "demo" if conta == "PRACTICE" else ("real" if conta == "REAL" else "")
    return {
        "created_at": now_iso(),
        "instance_tag": INSTANCE_TAG,
        "account": account,
        "tradetype": str(tipo).lower(),
        "asset": ativo or "",
        "asset_category": ativo_chave or "",
        "tf_min": int(TIMEFRAME_MINUTES),
        "entry_mode": ENTRY_MODE,
        "rigidez": RIGIDEZ_MODE,
        "runtime_min": runtime_min if runtime_min is not None else "",
        "amount_mode": AMOUNT_MODE,
        "amount_fixed": float(AMOUNT_FIXED) if AMOUNT_MODE == "fixed" else "",
        "amount_percent": float(AMOUNT_PERCENT) if AMOUNT_MODE == "percent" else "",
        "amount_recalc_each": bool(AMOUNT_RECALC_EACH),
        "stop_loss_pct": float(STOP_LOSS_PCT),
        "stop_win_pct": float(STOP_WIN_PCT),
        "result_delay_after_expiry_seconds": int(RESULT_DELAY_AFTER_EXPIRY_SECONDS),
        "bot_version": BOTDIN_VERSION,
    }


def write_preset_file(preset_path: Path, preset_data: Dict[str, Any]):
    _mkdirp(PRESETS_DIR)
    try:
        with preset_path.open("w", encoding="utf-8") as f:
            json.dump(preset_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _log_error(f"Falha ao salvar preset em {preset_path}", e)


# =========================
# IQ connect / utils
# =========================
def _patch_websocket_on_close(api_obj) -> None:
    """Corrige incompatibilidade de assinatura do on_close no websocket-client ≥0.58.

    Versões recentes do websocket-client chamam on_close(ws, close_status_code, close_msg)
    (3 args), mas o iqoptionapi define on_close(self) (1 arg), causando TypeError no
    fechamento do socket. Fazemos monkey-patch para aceitar qualquer assinatura.
    """
    try:
        ws_obj = None
        # Tenta diferentes caminhos de acesso ao objeto WebSocketApp interno
        for attr_path in (('api', 'wss'), ('api', 'ws'), ('wss',), ('ws',)):
            obj = api_obj
            for attr in attr_path:
                obj = getattr(obj, attr, None)
                if obj is None:
                    break
            if obj is not None:
                ws_obj = obj
                break
        if ws_obj is None:
            return
        _orig = getattr(ws_obj, 'on_close', None)
        if _orig is None:
            return

        def _safe_on_close(*args, **kwargs):
            try:
                _orig()
            except TypeError as _te:
                # Assinatura nova (3 args): tenta passar ws como primeiro argumento
                _log_error("on_close: TypeError com 0 args; tentando com ws arg.", _te)
                try:
                    _orig(args[0] if args else None)
                except Exception as _e2:
                    _log_error("on_close: falha mesmo com ws arg.", _e2)
            except Exception as _e:
                _log_error("on_close: exceção inesperada no handler.", _e)

        ws_obj.on_close = _safe_on_close
    except Exception:
        pass


def connect():
    global API
    print('BOTDIN_VERSION =', BOTDIN_VERSION)
    print('🔌 Conectando na IQ Option...')
    API = IQ_Option(email, senha)
    ok, reason = API.connect()
    if not ok:
        print('\n❌ Falha na conexão:', reason)
        sys.exit(1)
    _patch_websocket_on_close(API)
    print('✅ Conectado.')


# Configuração de reconexão automática com backoff exponencial
_RECONNECT_MAX_ATTEMPTS: int = 10
_RECONNECT_BACKOFF_BASE_S: float = 5.0   # backoff inicial (dobra a cada tentativa)
_RECONNECT_BACKOFF_MAX_S: float = 120.0  # backoff máximo entre tentativas
# Intervalo mínimo entre verificações de conexão (segundos): evita overhead em loop rápido
_RECONNECT_CHECK_INTERVAL_S: float = 30.0
_last_connect_check_ts: float = 0.0

# ---- Watchdog / SAFE-HOLD mode ----
# Ativado quando a conexão está degradada (warnings "late 30 sec", NoneType subscriptable,
# WebSocketConnectionClosedException). Suprime novas decisões de trading até reconexão.
_SAFE_HOLD_MODE: bool = False
_SAFE_HOLD_TRIGGERED_AT: float = 0.0
# Contadores de sinais de degradação (resetados ao reconectar)
_DEGRADED_LATE_WARNINGS: int = 0
_DEGRADED_LATE_WARNING_THRESHOLD: int = 3   # nº de "late 30 sec" antes de entrar em SAFE_HOLD
_DEGRADED_NONE_ERRORS: int = 0
_DEGRADED_NONE_ERROR_THRESHOLD: int = 1    # primeiro NoneType subscriptable já entra em SAFE_HOLD
# Timestamp da última vez que candles foram vistos (por ativo) após reconexão:
# o bot aguarda pelo menos 1 candle novo antes de retomar após sair de SAFE_HOLD.
_post_reconnect_candle_seen: Dict[str, float] = {}  # ativo → candle "from" timestamp do primeiro candle pós-reconexão
_post_reconnect_resume_ts: float = 0.0  # wall clock quando SAFE_HOLD foi desativado


def _enter_safe_hold(reason: str) -> None:
    """Entra em modo SAFE/HOLD: para novas decisões de trading e loga status claro."""
    global _SAFE_HOLD_MODE, _SAFE_HOLD_TRIGGERED_AT
    if _SAFE_HOLD_MODE:
        return  # já em SAFE_HOLD
    _SAFE_HOLD_MODE = True
    _SAFE_HOLD_TRIGGERED_AT = time.time()
    msg = f"🔴 [WATCHDOG] SAFE/HOLD ativado — {reason}"
    print(cyellow(msg))
    _log_error(msg)


def _exit_safe_hold() -> None:
    """Sai do modo SAFE/HOLD e reseta contadores de degradação."""
    global _SAFE_HOLD_MODE, _DEGRADED_LATE_WARNINGS, _DEGRADED_NONE_ERRORS
    global _post_reconnect_candle_seen, _post_reconnect_resume_ts
    _SAFE_HOLD_MODE = False
    _DEGRADED_LATE_WARNINGS = 0
    _DEGRADED_NONE_ERRORS = 0
    _post_reconnect_candle_seen = {}
    _post_reconnect_resume_ts = time.time()
    msg = "🟢 [WATCHDOG] SAFE/HOLD desativado — conexão restaurada. Aguardando candle novo por ativo."
    print(cgreen(msg))
    _log_error(msg)


def report_late_warning() -> None:
    """Registra aviso de latência ("late 30 sec") do websocket.

    Chamado quando o bot detecta mensagem de aviso de atraso do servidor
    (e.g. 'get_all_init_v2 late 30 sec' ou 'get_digital_underlying_list_data late 30 sec').
    Ao atingir _DEGRADED_LATE_WARNING_THRESHOLD, ativa SAFE/HOLD.
    """
    global _DEGRADED_LATE_WARNINGS
    _DEGRADED_LATE_WARNINGS += 1
    if _DEGRADED_LATE_WARNINGS >= _DEGRADED_LATE_WARNING_THRESHOLD:
        _enter_safe_hold(
            f"late_warnings={_DEGRADED_LATE_WARNINGS} "
            f"(thr={_DEGRADED_LATE_WARNING_THRESHOLD})"
        )


def report_none_subscript_error() -> None:
    """Registra erro de NoneType subscriptable (API retornou None em vez de dict).

    Chamado quando get_all_init_v2 ou get_digital_underlying_list_data retorna None.
    Ativa SAFE/HOLD imediatamente.
    """
    global _DEGRADED_NONE_ERRORS
    _DEGRADED_NONE_ERRORS += 1
    _enter_safe_hold(
        f"NoneType_subscriptable (none_errors={_DEGRADED_NONE_ERRORS})"
    )


def report_websocket_closed() -> None:
    """Registra fechamento abrupto do websocket (WebSocketConnectionClosedException).

    Força entrada imediata em SAFE/HOLD e invalida o intervalo de check de conexão
    para que _ensure_connected() faça a verificação na próxima chamada.
    """
    global _last_connect_check_ts
    _last_connect_check_ts = 0.0  # força re-check imediato
    _enter_safe_hold("WebSocketConnectionClosedException")


def _ensure_connected() -> bool:
    """Verifica a conexão com a IQ Option e reconecta se necessário.

    Para evitar overhead em loops rápidos (M1: ~0.2s/iteração), a verificação
    de check_connect() é executada no máximo a cada _RECONNECT_CHECK_INTERVAL_S
    segundos, exceto quando _SAFE_HOLD_MODE está ativo (verifica imediatamente).

    Retorna True se conectado (ou após reconexão bem-sucedida), False se falhar.
    Usa até _RECONNECT_MAX_ATTEMPTS tentativas com backoff exponencial.
    Em SAFE_HOLD ativo, o caller deve aguardar o retorno True antes de retomar trading.
    """
    global API, _last_connect_check_ts
    now_t = time.time()
    # Em SAFE/HOLD, sempre verifica; fora de SAFE/HOLD, throttle normal
    if not _SAFE_HOLD_MODE and (now_t - _last_connect_check_ts < _RECONNECT_CHECK_INTERVAL_S):
        return True  # still within check interval; skip check_connect() overhead
    _last_connect_check_ts = now_t
    try:
        if API is not None and API.check_connect():
            if _SAFE_HOLD_MODE:
                # Conexão ok mas ainda em SAFE_HOLD → atualizar timestamp e sair
                _last_connect_check_ts = time.time()
                _exit_safe_hold()
            return True
    except Exception:
        pass

    if not _SAFE_HOLD_MODE:
        _enter_safe_hold("check_connect() falhou")

    _log_error("Conexão perdida — tentando reconectar (backoff exponencial)...")
    print(cyellow("⚠️  Conexão perdida. Tentando reconectar..."))
    sleep_s = _RECONNECT_BACKOFF_BASE_S
    for attempt in range(1, _RECONNECT_MAX_ATTEMPTS + 1):
        try:
            ok, reason = API.connect()
            if ok:
                _patch_websocket_on_close(API)
                if conta:
                    try:
                        API.change_balance(conta)
                    except Exception:
                        pass
                # Update check timestamp BEFORE exiting SAFE_HOLD so that
                # _post_reconnect_resume_ts is always >= _last_connect_check_ts.
                _last_connect_check_ts = time.time()
                print(cgreen(f"✅ Reconectado (tentativa {attempt})."))
                _log_error(f"Reconexão bem-sucedida na tentativa {attempt}.")
                _exit_safe_hold()
                return True
        except TypeError as exc:
            # TypeError após _patch_websocket_on_close indica que o patch não funcionou
            # para esta versão do iqoptionapi — registrar como aviso e continuar.
            _log_error(
                f"Reconexão tentativa {attempt}: TypeError inesperado (patch on_close pode "
                f"não ter funcionado nesta versão do iqoptionapi). Continuando.", exc
            )
            print(cyellow(f"⚠️  Reconexão tentativa {attempt}: TypeError websocket. Continuando..."))
        except Exception as exc:
            _log_error(f"Reconexão tentativa {attempt} falhou.", exc)
        print(cyellow(f"🔄 Reconectando... ({attempt}/{_RECONNECT_MAX_ATTEMPTS}) aguardando {sleep_s:.0f}s"))
        time.sleep(sleep_s)
        sleep_s = min(sleep_s * 2, _RECONNECT_BACKOFF_MAX_S)
    _log_error("Reconexão esgotou todas as tentativas.")
    print(cred(f"❌ Não foi possível reconectar após {_RECONNECT_MAX_ATTEMPTS} tentativas."))
    return False


def _safe_get_all_open_time() -> Optional[Dict]:
    """Chama API.get_all_open_time() capturando erros de conexão degradada.

    Detecta NoneType subscriptable (API retornou None) e WebSocketConnectionClosedException,
    reporta ao watchdog e retorna None. O caller deve verificar o retorno e
    aguardar reconexão antes de continuar.
    """
    try:
        result = API.get_all_open_time()
        if result is None:
            report_none_subscript_error()
            return None
        return result
    except TypeError as e:
        # Covers 'NoneType object is not subscriptable' and similar None-related TypeErrors
        if 'subscriptable' in str(e) or 'NoneType' in str(e):
            report_none_subscript_error()
        else:
            _log_error("get_all_open_time: TypeError inesperado.", e)
        return None
    except Exception as e:
        _cls = type(e).__name__
        if 'WebSocketConnectionClosedException' in _cls or 'ConnectionClosed' in _cls:
            report_websocket_closed()
        else:
            _log_error("get_all_open_time: exceção.", e)
        return None


def get_profile_name() -> str:
    try:
        perfil = json.loads(json.dumps(API.get_profile_ansyc()))
        return str(perfil.get('name', '') or '').strip()
    except Exception:
        return ""


def get_available_balance():
    try:
        bal = API.get_balance()
        if isinstance(bal, dict):
            if 'available' in bal:
                return float(bal['available'])
            if 'result' in bal and isinstance(bal['result'], dict) and 'available' in bal['result']:
                return float(bal['result']['available'])
            for v in bal.values():
                if isinstance(v, (int, float)):
                    return float(v)
            return None
        if isinstance(bal, (int, float)):
            return float(bal)
    except Exception:
        return None
    return None


def seconds_left_in_period(minutes: int) -> int:
    try:
        ts = get_now_ts()
        period = minutes * 60
        return int(period - (ts % period))
    except Exception:
        return 0


def _normalize_asset_name(name: str) -> str:
    if not isinstance(name, str):
        return ''
    s = name.upper()
    s = re.sub(r'[^A-Z0-9\-]', '', s)
    return s


def _strip_market_suffix(name_n: str) -> str:
    """Remove sufixos de mercado conhecidos de um nome de ativo normalizado.

    Trata combinações mistas como '-OTC-OP' (ex.: BTCUSD-OTC-op da API),
    além dos sufixos simples '-OTC' e '-OP'. A ordem de verificação garante
    que o sufixo mais longo (combinado) seja removido primeiro.

    Exemplos:
        'BTCUSD-OTC-OP' → 'BTCUSD'
        'EURUSD-OTC'    → 'EURUSD'
        'GBPUSD-OP'     → 'GBPUSD'
        'DXY'           → 'DXY'   (sem sufixo — retornado sem alteração)
    """
    for sfx in ('-OTC-OP', '-OTC', '-OP'):
        if name_n.endswith(sfx):
            return name_n[:-len(sfx)]
    return name_n


def _categories_priority(preferred_tipo):
    preferred = 'digital' if 'digital' in str(preferred_tipo).lower() else 'binary'
    order = []
    for c in (preferred, 'binary' if preferred != 'binary' else 'digital', 'turbo'):
        if c not in order:
            order.append(c)
    return order


def _parse_user_asset_input(raw: str) -> Dict[str, Any]:
    s = (raw or "").strip()
    s2 = re.sub(r'\s+', '', s)
    upper = s2.upper()

    # Detecta sufixo de mercado (case-insensitive graças ao upper()).
    # Verifica primeiro a combinação '-OTC-OP' (ex.: BTCUSD-OTC-op da IQ Option),
    # depois os sufixos simples. OTC tem precedência quando presente na combinação.
    suffix = None
    if upper.endswith("-OTC-OP") or upper.endswith("-OTC"):
        suffix = "OTC"
    elif upper.endswith("-OP"):
        suffix = "OP"

    allow_otc = (suffix == "OTC")
    return {"base": upper, "suffix": suffix, "allow_otc": allow_otc}


def _is_open(open_times: Dict[str, Any], categoria: str, ativo: str) -> bool:
    try:
        info = open_times.get(categoria, {}).get(ativo)
        return isinstance(info, dict) and bool(info.get("open"))
    except Exception:
        return False


def _asset_accepts_tf(info: Dict[str, Any], tf_min: int) -> bool:
    """Verifica se um ativo aceita negociações no timeframe tf_min.

    Args:
        info: dict retornado por API.get_all_open_time()[categoria][ativo].
        tf_min: timeframe em minutos (1=M1, 5=M5). 0 = sem filtro (aceita tudo).

    Suporta campo 'timeframes' como dict {1: True, 5: True} ou list [1, 5, 15].
    Fallback permissivo: se 'timeframes' ausente, assume aceito para não bloquear
    ativos válidos quando a API omite esse campo.
    ← PONTO-CHAVE: se um ativo aparecer indevidamente no pool com tf errado,
       imprima API.get_all_open_time() para inspecionar o campo 'timeframes'.
    """
    if not isinstance(info, dict) or tf_min <= 0:
        return True  # tf_min=0 desativa filtro; info inválida = aceito por segurança
    tfs = info.get("timeframes")
    if tfs is None:
        # API não retornou dados de timeframe → assume aceito (fallback permissivo)
        return True
    if isinstance(tfs, dict):
        return bool(tfs.get(tf_min) or tfs.get(str(tf_min)))
    if isinstance(tfs, (list, tuple, set)):
        return (tf_min in tfs) or (str(tf_min) in tfs)
    return True  # formato desconhecido → aceito por segurança


def _find_open_in_table(open_times: Dict[str, Any], ativo: str) -> Tuple[Optional[str], Optional[str]]:
    for cat in _categories_priority(tipo):
        if _is_open(open_times, cat, ativo):
            return ativo, cat
    return None, None


def find_preferred_variant_with_rules(base: str, allow_otc: bool) -> Tuple[Optional[str], Optional[str]]:
    ot = _safe_get_all_open_time()
    if ot is None:
        return None, None

    base_n = _normalize_asset_name(base)
    # base_stripped: nome sem qualquer sufixo de mercado, para comparação por raiz.
    # Ex.: 'BTCUSD-OTC' → 'BTCUSD', 'BTCUSD-OTC-OP' → 'BTCUSD'.
    base_stripped = _strip_market_suffix(base_n)

    name, cat = _find_open_in_table(ot, base)
    if name:
        return name, cat

    candidates_common: List[Tuple[str, str]] = []
    candidates_op: List[Tuple[str, str]] = []
    candidates_otc: List[Tuple[str, str]] = []

    for categoria in ('binary', 'digital', 'turbo'):
        table = ot.get(categoria, {})
        for name2, info in table.items():
            if not (isinstance(info, dict) and info.get('open')):
                continue

            name2_u = str(name2).upper()
            name2_n = _normalize_asset_name(name2_u)
            name2_stripped = _strip_market_suffix(name2_n)

            # Exact match (normalized)
            if name2_n == base_n:
                return name2, categoria
            # Match by stripped base name (handles -OTC-OP, -OTC, -OP variants)
            # e.g. Ativos.txt 'BTCUSD-OTC' matches API 'BTCUSD-OTC-op'
            if base_stripped and name2_stripped == base_stripped:
                # OTC takes precedence over OP in combined names like 'BTCUSD-OTC-OP'
                if '-OTC' in name2_u:
                    candidates_otc.append((name2, categoria))
                elif '-OP' in name2_u:
                    candidates_op.append((name2, categoria))
                else:
                    candidates_common.append((name2, categoria))
                continue
            # Substring fallback (legacy: base_n is a prefix/infix of name2_n)
            if base_n and (base_n in name2_n):
                if '-OTC' in name2_u:
                    candidates_otc.append((name2, categoria))
                elif '-OP' in name2_u:
                    if name2_n.startswith(base_n):
                        candidates_op.append((name2, categoria))
                else:
                    candidates_common.append((name2, categoria))

    if candidates_common:
        for c in _categories_priority(tipo):
            for n, cat in candidates_common:
                if cat == c:
                    return n, cat
        return candidates_common[0]

    if candidates_op:
        for c in _categories_priority(tipo):
            for n, cat in candidates_op:
                if cat == c:
                    return n, cat
        return candidates_op[0]

    if allow_otc and candidates_otc:
        for c in _categories_priority(tipo):
            for n, cat in candidates_otc:
                if cat == c:
                    return n, cat
        return candidates_otc[0]

    return None, None


def ativo_aberto(ativo, chave_preferida=None) -> bool:
    cache_key = (ativo, chave_preferida)
    nowt = time.time()
    if cache_key in _last_open_time_cache:
        val, ts = _last_open_time_cache[cache_key]
        if nowt - ts <= OPEN_TIME_CACHE_TTL_S:
            return bool(val)
    open_times = _safe_get_all_open_time()
    if not open_times:
        _last_open_time_cache[cache_key] = (False, nowt)
        return False
    try:
        if chave_preferida:
            info = open_times.get(chave_preferida, {}).get(ativo)
            ok = isinstance(info, dict) and info.get('open', False)
            _last_open_time_cache[cache_key] = (ok, nowt)
            return ok
        for k in ('binary', 'digital', 'turbo'):
            info = open_times.get(k, {}).get(ativo)
            if isinstance(info, dict):
                ok = info.get('open', False)
                _last_open_time_cache[cache_key] = (ok, nowt)
                return ok
    except Exception:
        _last_open_time_cache[cache_key] = (False, nowt)
        return False
    _last_open_time_cache[cache_key] = (False, nowt)
    return False


def is_asset_known_anywhere_case_insensitive(ativo: str) -> bool:
    try:
        target_n = _normalize_asset_name(ativo)
        ot = API.get_all_open_time()
        for cat in ('binary', 'digital', 'turbo'):
            table = ot.get(cat, {})
            if not isinstance(table, dict):
                continue
            for k in table.keys():
                if _normalize_asset_name(str(k)) == target_n:
                    return True
    except Exception:
        return False
    return False


def can_purchase_now(ativo, period_minutes=1, chave_preferida=None):
    if not ativo_aberto(ativo, chave_preferida=chave_preferida):
        return False
    return seconds_left_in_period(period_minutes) > PURCHASE_BUFFER_SECONDS


def get_candles_safe(ativo: str, timeframe: int, qnt: int, max_tentativas=6):
    """Busca candles com fallback de múltiplos end_ts e backoff exponencial.

    Tenta primeiro end_ts=agora; se insuficiente, tenta agora-tf e agora+tf para
    contornar edge cases de sincronização do servidor (inspirado em 3EM1_IQ_v9-1).
    Entre falhas consecutivas aplica backoff exponencial (0.5s → 1s → 2s → 4s …)
    para reduzir pressão sobre o websocket em caso de timeout.
    """
    sleep_s = 0.5
    for attempt in range(max_tentativas):
        try:
            base_ts = get_now_ts()
            # Tenta end_ts=agora primeiro; se não vier candles suficientes, tenta offsets alternativos
            for offset in (0, -timeframe, timeframe):
                try:
                    end_ts = base_ts + offset
                    velas = API.get_candles(ativo, timeframe, qnt, end_ts)
                    if velas and len(velas) >= qnt:
                        return velas
                except Exception as e_inner:
                    if offset != 0:
                        _log_error(f"get_candles_safe offset={offset}s falhou.", e_inner)
        except Exception as e:
            _log_error("Erro ao buscar candles.", e)
        if attempt < max_tentativas - 1:
            time.sleep(sleep_s)
            sleep_s = min(sleep_s * 2, 8.0)  # backoff exponencial; permanece em 8s após atingir o teto
        else:
            _log_error(
                f"get_candles_safe: esgotou {max_tentativas} tentativas para "
                f"ativo={ativo} tf={timeframe}s qnt={qnt}. Retornando None."
            )
    return None


# =========================
# Indicadores / filtros
# =========================
def ema_series(values: List[float], period: int) -> List[Optional[float]]:
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period
    out: List[Optional[float]] = [None] * (period - 1) + [ema]
    for i in range(period, len(values)):
        ema = values[i] * k + ema * (1 - k)
        out.append(ema)
    return out


def ema_slope_norm(closes: List[float], period: int, lookback: int) -> Optional[float]:
    if len(closes) < period + lookback + 5:
        return None
    es = ema_series(closes, period)
    if not es or es[-1] is None:
        return None
    idx2 = len(es) - 1
    idx1 = idx2 - lookback
    if idx1 < 0:
        return None
    e2, e1 = es[idx2], es[idx1]
    if e1 is None or e2 is None:
        return None
    base = closes[-1] if closes[-1] != 0 else 1e-12
    return abs(e2 - e1) / base


def calculate_atr_from_candles(velas: List[Dict[str, Any]], periodo=14) -> Optional[float]:
    if not velas or len(velas) < periodo + 1:
        return None
    trs = []
    for i in range(1, len(velas)):
        high = velas[i]['max']
        low = velas[i]['min']
        prev_close = velas[i - 1]['close']
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if len(trs) < periodo:
        return None
    return sum(trs[-periodo:]) / periodo


def adaptive_atr_threshold_update(tf_min: int, atr_ratio: Optional[float]) -> float:
    base = ATR_MIN_RATIO_ABS_M5 if tf_min == 5 else ATR_MIN_RATIO_ABS_M1
    q = ATR_RATIO_QUEUE_M5 if tf_min == 5 else ATR_RATIO_QUEUE_M1
    if atr_ratio is None:
        return base
    try:
        q.append(float(atr_ratio))
        if len(q) < 10:
            return base
        med = statistics.median(list(q))
        dyn = max(base, med * ATR_ADAPTIVE_FACTOR)
        # Cap do threshold adaptativo por TF: evita que suba demais e trave entradas
        if tf_min == 1:
            dyn = min(dyn, ATR_MAX_THR_M1)
        elif tf_min == 5:
            dyn = min(dyn, ATR_MAX_THR_M5)
        return max(base, dyn)
    except Exception:
        return base


def passes_atr_filter(tf_min: int, velas: List[Dict[str, Any]]) -> bool:
    if not ENABLE_ATR_FILTER:
        return True
    atr = calculate_atr_from_candles(velas, periodo=ATR_PERIOD)
    if atr is None:
        return False
    closes = [float(v["close"]) for v in velas]
    mean_close = sum(closes[-ATR_PERIOD:]) / ATR_PERIOD if len(closes) >= ATR_PERIOD else closes[-1]
    if mean_close == 0:
        return False
    ratio = atr / mean_close
    thr = adaptive_atr_threshold_update(tf_min, ratio)
    if ratio < thr:
        _log_blocked("atr_low", f"tf={tf_min} ratio={ratio:.6f} thr={thr:.6f}")
        return False
    return True


def bb_width_norm(closes: List[float], period: int = 20, std_mult: float = 2.0) -> Optional[float]:
    if len(closes) < period:
        return None
    window = closes[-period:]
    mean = sum(window) / period
    var = sum((x - mean) ** 2 for x in window) / period
    sd = var ** 0.5
    upper = mean + std_mult * sd
    lower = mean - std_mult * sd
    mid = mean if mean != 0 else 1e-12
    return (upper - lower) / mid


def adx_from_candles(velas: List[Dict[str, Any]], period: int = 14) -> Optional[float]:
    if not velas or len(velas) < period + 2:
        return None
    highs = [float(v["max"]) for v in velas]
    lows = [float(v["min"]) for v in velas]
    closes = [float(v["close"]) for v in velas]
    plus_dm, minus_dm, tr_list = [], [], []
    for i in range(1, len(velas)):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        pdm = up_move if (up_move > down_move and up_move > 0) else 0.0
        mdm = down_move if (down_move > up_move and down_move > 0) else 0.0
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        plus_dm.append(pdm)
        minus_dm.append(mdm)
        tr_list.append(tr)
    if len(tr_list) < period + 1:
        return None

    def wilder(values: List[float], p: int) -> List[float]:
        first = sum(values[:p])
        out = [first]
        for i in range(p, len(values)):
            out.append(out[-1] - (out[-1] / p) + values[i])
        return out

    tr_s = wilder(tr_list, period)
    pdm_s = wilder(plus_dm, period)
    mdm_s = wilder(minus_dm, period)
    n = min(len(tr_s), len(pdm_s), len(mdm_s))
    tr_s, pdm_s, mdm_s = tr_s[-n:], pdm_s[-n:], mdm_s[-n:]
    dx = []
    for i in range(n):
        trv = tr_s[i]
        if trv == 0:
            dx.append(0.0)
            continue
        pdi = 100.0 * (pdm_s[i] / trv)
        mdi = 100.0 * (mdm_s[i] / trv)
        denom = pdi + mdi
        dx.append(0.0 if denom == 0 else 100.0 * abs(pdi - mdi) / denom)
    adx_s = wilder(dx, period)
    if not adx_s:
        return None
    return float(adx_s[-1] / period)


def passes_trend_strength_filter(tf_min: int, velas: List[Dict[str, Any]]) -> bool:
    if not ENABLE_TREND_STRENGTH_FILTER:
        return True

    closes = [float(v["close"]) for v in velas]
    adx_min = ADX_MIN_M5 if tf_min == 5 else ADX_MIN_M1
    bb_min = BB_WIDTH_MIN_M5 if tf_min == 5 else BB_WIDTH_MIN_M1
    slope_min = SLOPE_MIN_M5 if tf_min == 5 else SLOPE_MIN_M1

    adx = adx_from_candles(velas, period=ADX_PERIOD)
    bbw = bb_width_norm(closes, period=BB_PERIOD, std_mult=BB_STD)
    slope = ema_slope_norm(closes, period=21, lookback=SLOPE_LOOKBACK)

    if tf_min == 1:
        # M1: regra "2-de-4" — exige pelo menos 2 de 4 filtros passando (ATR, ADX, BBW, SLOPE)
        # Estratégia livre: mais entradas sem abrir mão de todo critério de qualidade.
        # ← AJUSTE: mude para "failures > 1" para voltar ao "3-de-4" (mais rígido/menos entradas)
        #           mude para "failures > 3" para modo ultra-livre (pelo menos 1 de 4 basta)
        failures = 0
        # Filtro ATR integrado (para regra 2-de-4, evita dois saltos de função)
        if ENABLE_ATR_FILTER:
            atr = calculate_atr_from_candles(velas, periodo=ATR_PERIOD)
            mean_close = sum(closes[-ATR_PERIOD:]) / ATR_PERIOD if len(closes) >= ATR_PERIOD else (closes[-1] if closes else 0.0)
            if atr is None or mean_close == 0:
                failures += 1
            else:
                ratio = atr / mean_close
                thr = adaptive_atr_threshold_update(tf_min, ratio)
                if ratio < thr:
                    _log_blocked("atr_low", f"tf={tf_min} ratio={ratio:.6f} thr={thr:.6f}")
                    failures += 1
        if adx is None or adx < adx_min:
            _log_blocked("trend_weak_adx", f"tf={tf_min} adx={adx}")
            failures += 1
        if bbw is None or bbw < bb_min:
            _log_blocked("range_squeeze_bbw", f"tf={tf_min} bbw={bbw}")
            failures += 1
        if slope is None or slope < slope_min:
            _log_blocked("ema_flat_slope", f"tf={tf_min} slope={slope:.8f} slope_min={slope_min:.8f}")
            failures += 1
        if failures > 2:
            return False
        return True

    # M5: mantém todos os filtros obrigatórios (comportamento original)
    if adx is None or adx < adx_min:
        _log_blocked("trend_weak_adx", f"tf={tf_min} adx={adx}")
        return False

    if bbw is None or bbw < bb_min:
        _log_blocked("range_squeeze_bbw", f"tf={tf_min} bbw={bbw}")
        return False

    if slope is None or slope < slope_min:
        _log_blocked("ema_flat_slope", f"tf={tf_min} slope={slope:.8f} slope_min={slope_min:.8f}")
        return False

    return True


def passes_all_regime_filters(tf_min: int, velas: List[Dict[str, Any]]) -> bool:
    """Verifica todos os filtros de regime de forma unificada.

    M1: aplica regra "2-de-4" combinando ATR + ADX + BBW + SLOPE internamente
        em passes_trend_strength_filter. Não chama passes_atr_filter separado.
    M5: mantém comportamento original — ATR e trend_strength são filtros rígidos.
    """
    if tf_min == 1:
        # ATR já está integrado na regra 2-de-4 dentro de passes_trend_strength_filter
        return passes_trend_strength_filter(tf_min, velas)
    # M5: todos os filtros são obrigatórios
    return passes_atr_filter(tf_min, velas) and passes_trend_strength_filter(tf_min, velas)


# =========================
# Patterns
# =========================
def _find_candle_by_from(velas: List[Dict[str, Any]], from_ts: int) -> Optional[Dict[str, Any]]:
    for c in velas:
        if int(c.get("from", -1)) == int(from_ts):
            return c
    return None


def _candle_parts(c: Dict[str, Any]) -> Dict[str, float]:
    o = float(c['open'])
    cl = float(c['close'])
    h = float(c['max'])
    l = float(c['min'])
    return {"open": o, "close": cl, "high": h, "low": l}


def is_hammer(c) -> bool:
    p = _candle_parts(c)
    body = abs(p["close"] - p["open"])
    rng = max(1e-12, (p["high"] - p["low"]))
    upper = p["high"] - max(p["open"], p["close"])
    lower = min(p["open"], p["close"]) - p["low"]
    if (body / rng) > 0.35:
        return False
    if lower < 2.0 * max(body, 1e-12):
        return False
    if upper > 0.8 * max(body, 1e-12):
        return False
    return True


def is_harami_bearish(prev_c, cur_c) -> bool:
    p0 = _candle_parts(prev_c)
    p1 = _candle_parts(cur_c)
    if not (p0["close"] > p0["open"] and p1["close"] < p1["open"]):
        return False
    high0, low0 = max(p0["open"], p0["close"]), min(p0["open"], p0["close"])
    high1, low1 = max(p1["open"], p1["close"]), min(p1["open"], p1["close"])
    if not (high1 <= high0 and low1 >= low0):
        return False
    if abs(p1["close"] - p1["open"]) >= 0.8 * abs(p0["close"] - p0["open"]):
        return False
    return True


def is_harami_bullish(prev_c, cur_c) -> bool:
    p0 = _candle_parts(prev_c)
    p1 = _candle_parts(cur_c)
    if not (p0["close"] < p0["open"] and p1["close"] > p1["open"]):
        return False
    high0, low0 = max(p0["open"], p0["close"]), min(p0["open"], p0["close"])
    high1, low1 = max(p1["open"], p1["close"]), min(p1["open"], p1["close"])
    if not (high1 <= high0 and low1 >= low0):
        return False
    if abs(p1["close"] - p1["open"]) >= 0.8 * abs(p0["close"] - p0["open"]):
        return False
    return True


# =========================
# PADRÕES ADICIONAIS (Engolfo e Pinça / Tweezer)
# =========================
def is_engulfing_bullish(prev_c: Dict[str, Any], cur_c: Dict[str, Any]) -> bool:
    """Engolfo de Alta (Bullish Engulfing): vela atual alta e de corpo maior que vela prévia baixa."""
    p0 = _candle_parts(prev_c)
    p1 = _candle_parts(cur_c)
    if not (p0["close"] < p0["open"]):   # prévia deve ser baixa
        return False
    if not (p1["close"] > p1["open"]):   # atual deve ser alta
        return False
    # Corpo atual maior e "engolfa" o corpo anterior
    if not (p1["open"] <= p0["close"] and p1["close"] >= p0["open"]):
        return False
    # Corpo atual deve ser significativamente maior que o anterior
    body0 = abs(p0["close"] - p0["open"])
    body1 = abs(p1["close"] - p1["open"])
    return body1 > body0 * 0.9


def is_engulfing_bearish(prev_c: Dict[str, Any], cur_c: Dict[str, Any]) -> bool:
    """Engolfo de Baixa (Bearish Engulfing): vela atual baixa e de corpo maior que vela prévia alta."""
    p0 = _candle_parts(prev_c)
    p1 = _candle_parts(cur_c)
    if not (p0["close"] > p0["open"]):   # prévia deve ser alta
        return False
    if not (p1["close"] < p1["open"]):   # atual deve ser baixa
        return False
    if not (p1["open"] >= p0["close"] and p1["close"] <= p0["open"]):
        return False
    body0 = abs(p0["close"] - p0["open"])
    body1 = abs(p1["close"] - p1["open"])
    return body1 > body0 * 0.9


def is_tweezer_top(prev_c: Dict[str, Any], cur_c: Dict[str, Any]) -> bool:
    """Pinça de Topo (Tweezer Top): dois topos próximos, sinalizando resistência / reversão baixista."""
    p0 = _candle_parts(prev_c)
    p1 = _candle_parts(cur_c)
    high_diff = abs(p0["high"] - p1["high"])
    avg_high = (p0["high"] + p1["high"]) / 2.0
    if avg_high == 0:
        return False
    # Topos devem ser próximos (dentro de 0.1% do preço)
    if high_diff / avg_high > 0.001:
        return False
    # Vela prévia deve ser de alta, atual de baixa (confirmação)
    return p0["close"] > p0["open"] and p1["close"] < p1["open"]


def is_tweezer_bottom(prev_c: Dict[str, Any], cur_c: Dict[str, Any]) -> bool:
    """Pinça de Fundo (Tweezer Bottom): duas mínimas próximas, sinalizando suporte / reversão altista."""
    p0 = _candle_parts(prev_c)
    p1 = _candle_parts(cur_c)
    low_diff = abs(p0["low"] - p1["low"])
    avg_low = (p0["low"] + p1["low"]) / 2.0
    if avg_low == 0:
        return False
    if low_diff / avg_low > 0.001:
        return False
    return p0["close"] < p0["open"] and p1["close"] > p1["open"]


def _candle_engulf_score(prev_c: Dict[str, Any], cur_c: Dict[str, Any]) -> Tuple[int, Optional[str]]:
    """Retorna pontuação de padrão Engolfo ou Pinça (0–15 pts) e direção."""
    if is_engulfing_bullish(prev_c, cur_c):
        return 15, "call"
    if is_engulfing_bearish(prev_c, cur_c):
        return 15, "put"
    if is_tweezer_bottom(prev_c, cur_c):
        return 10, "call"
    if is_tweezer_top(prev_c, cur_c):
        return 10, "put"
    return 0, None


# =========================
# CANAL KELTNER (EMA(hlc3) ± RMA(TR)*shift)
# =========================
def _rma(values: List[float], period: int) -> List[float]:
    """Running Moving Average (Wilder smoothing) equivalente ao RMA do Pine Script."""
    if len(values) < period:
        return []
    alpha = 1.0 / period
    out: List[float] = []
    first = sum(values[:period]) / period
    out.append(first)
    for i in range(period, len(values)):
        out.append(alpha * values[i] + (1.0 - alpha) * out[-1])
    return out


def keltner_channel(
    velas: List[Dict[str, Any]], period: int = 20, shift: float = 1.5
) -> Optional[Tuple[float, float, float]]:
    """Calcula Canal Keltner: EMA(hlc3, period) ± RMA(TR, period)*shift.

    Returns (upper, middle, lower) ou None se não houver velas suficientes.
    """
    if len(velas) < period + 2:
        return None
    hlc3 = [
        (float(v["max"]) + float(v["min"]) + float(v["close"])) / 3.0
        for v in velas
    ]
    trs: List[float] = []
    for i in range(1, len(velas)):
        h = float(velas[i]["max"])
        l = float(velas[i]["min"])
        pc = float(velas[i - 1]["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))

    ema_mid = ema_series(hlc3, period)
    rma_tr = _rma(trs, period)

    if not ema_mid or ema_mid[-1] is None or not rma_tr:
        return None

    mid = float(ema_mid[-1])
    offset = float(rma_tr[-1]) * shift
    return mid + offset, mid, mid - offset


def _keltner_score(
    velas: List[Dict[str, Any]], period: int = 20, shift: float = 1.5
) -> Tuple[int, Optional[str]]:
    """Pontua posição do preço em relação ao Canal Keltner (0–20 pts).

    - Preço perto/abaixo da banda inferior → call (zona de reversão altista)
    - Preço perto/acima da banda superior → put (zona de reversão baixista)
    """
    result = keltner_channel(velas, period=period, shift=shift)
    if result is None:
        return 0, None
    upper, mid, lower = result
    price = float(velas[-2].get("close", velas[-1].get("close", 0)))
    band_width = max(upper - lower, 1e-12)
    prox = band_width * 0.25  # mesmo critério do BB_PROXIMITY padrão

    dist_lower = price - lower
    dist_upper = upper - price

    if dist_lower < 0:        # abaixo da banda inferior
        return 20, "call"
    if dist_lower <= prox:
        frac = max(0.0, 1.0 - dist_lower / max(prox, 1e-12))
        return int(frac * 20), "call"
    if dist_upper < 0:        # acima da banda superior
        return 20, "put"
    if dist_upper <= prox:
        frac = max(0.0, 1.0 - dist_upper / max(prox, 1e-12))
        return int(frac * 20), "put"
    return 0, None


# =========================
# PIVÔS / FRACTAIS (5 barras — left=2, right=2)
# =========================
def pivot_highs(
    velas: List[Dict[str, Any]], left: int = 2, right: int = 2
) -> List[Tuple[int, float]]:
    """Retorna lista de (índice, high) dos pivôs de topo confirmados.

    Um pivô de topo em velas[i] requer:
      velas[i-left..i-1] e velas[i+1..i+right] com high <= velas[i].high
    Apenas pivôs já confirmados (i < len-right) são retornados.
    """
    result: List[Tuple[int, float]] = []
    n = len(velas)
    for i in range(left, n - right):
        h_raw = velas[i].get("max") if velas[i].get("max") is not None else velas[i].get("high")
        if h_raw is None:
            continue
        h = float(h_raw)
        neighbours_ok = True
        for j in range(i - left, i):
            hj_raw = velas[j].get("max") if velas[j].get("max") is not None else velas[j].get("high")
            if hj_raw is None or float(hj_raw) > h:
                neighbours_ok = False
                break
        if not neighbours_ok:
            continue
        for j in range(i + 1, i + right + 1):
            hj_raw = velas[j].get("max") if velas[j].get("max") is not None else velas[j].get("high")
            if hj_raw is None or float(hj_raw) > h:
                neighbours_ok = False
                break
        if neighbours_ok:
            result.append((i, h))
    return result


def pivot_lows(
    velas: List[Dict[str, Any]], left: int = 2, right: int = 2
) -> List[Tuple[int, float]]:
    """Retorna lista de (índice, low) dos pivôs de fundo confirmados."""
    result: List[Tuple[int, float]] = []
    n = len(velas)
    for i in range(left, n - right):
        l_raw = velas[i].get("min") if velas[i].get("min") is not None else velas[i].get("low")
        if l_raw is None:
            continue
        l = float(l_raw)
        neighbours_ok = True
        for j in range(i - left, i):
            lj_raw = velas[j].get("min") if velas[j].get("min") is not None else velas[j].get("low")
            if lj_raw is None or float(lj_raw) < l:
                neighbours_ok = False
                break
        if not neighbours_ok:
            continue
        for j in range(i + 1, i + right + 1):
            lj_raw = velas[j].get("min") if velas[j].get("min") is not None else velas[j].get("low")
            if lj_raw is None or float(lj_raw) < l:
                neighbours_ok = False
                break
        if neighbours_ok:
            result.append((i, l))
    return result


def _pivot_proximity(
    velas: List[Dict[str, Any]],
    direction: str,
    left: int = 2,
    right: int = 2,
    proximity_pct: float = 0.002,
) -> Tuple[bool, float]:
    """Verifica se o preço candidato está perto do último pivô favorável.

    CALL: próximo ao último pivot_low (suporte estrutural) → True
    PUT:  próximo ao último pivot_high (resistência estrutural) → True

    Returns (is_near, distance_pct)
    """
    price = float(velas[-2].get("close", 0))
    if price == 0:
        return False, 1.0

    if direction == "call":
        pts = pivot_lows(velas[:-1], left=left, right=right)
        if not pts:
            return False, 1.0
        _, piv_val = pts[-1]
        dist_pct = abs(price - piv_val) / max(abs(piv_val), 1e-12)
        return dist_pct <= proximity_pct, dist_pct
    else:
        pts = pivot_highs(velas[:-1], left=left, right=right)
        if not pts:
            return False, 1.0
        _, piv_val = pts[-1]
        dist_pct = abs(price - piv_val) / max(abs(piv_val), 1e-12)
        return dist_pct <= proximity_pct, dist_pct


# =========================
# ESTRATÉGIA RESPIRO (Continuação)
# Lógica: impulso → pullback → gatilho de continuação
# =========================
def _detect_respiro(
    tf_min: int,
    velas: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Detecta padrão Respiro (impulso + pullback + gatilho de continuação).

    Funciona apenas quando ENTRY_MODE da TF é 'continuation'.
    Parâmetros são lidos dos globals RESPIRO_* por TF.

    Returns dict de sinal (mesmo formato de check_patterns) ou None.
    """
    is_m5 = (tf_min == 5)
    respiro_enable = RESPIRO_ENABLE_M5 if is_m5 else RESPIRO_ENABLE_M1
    if not respiro_enable:
        return None

    impulse_lb = RESPIRO_IMPULSE_LOOKBACK_M5 if is_m5 else RESPIRO_IMPULSE_LOOKBACK_M1
    min_impulse = RESPIRO_MIN_IMPULSE_M5 if is_m5 else RESPIRO_MIN_IMPULSE_M1
    pb_max_frac = RESPIRO_PULLBACK_MAX_FRAC_M5 if is_m5 else RESPIRO_PULLBACK_MAX_FRAC_M1
    max_pb_candles = RESPIRO_MAX_PULLBACK_CANDLES_M5 if is_m5 else RESPIRO_MAX_PULLBACK_CANDLES_M1

    min_velas = impulse_lb + max_pb_candles + 3
    if len(velas) < min_velas:
        return None

    period = tf_min * 60
    c_last = velas[-2]          # candidata (última fechada)
    pattern_from = int(c_last.get("from", 0))
    expected_confirm_from = pattern_from + period

    # --- Detectar impulso (últimas impulse_lb velas antes do pullback) ---
    # Janela de análise: exclui vela candidata e última vela em aberto
    analysis_window = velas[-(impulse_lb + max_pb_candles + 2):-1]
    if len(analysis_window) < impulse_lb + 1:
        return None

    closes = [float(v["close"]) for v in analysis_window]
    highs  = [float(v.get("max", v.get("high", 0))) for v in analysis_window]
    lows   = [float(v.get("min", v.get("low", 0))) for v in analysis_window]

    # Detectar pernada de alta: impulse_lb velas de alta dominante
    # Testamos ambas as direções
    for direction in ("call", "put"):
        # Pernada: análise das primeiras impulse_lb velas da janela
        imp_window_closes = closes[:impulse_lb + 1]
        imp_start = imp_window_closes[0]
        imp_end   = imp_window_closes[-1]
        base = abs(imp_start) if abs(imp_start) > 1e-10 else 1e-12
        imp_move = (imp_end - imp_start) / base

        if direction == "call" and imp_move < min_impulse:
            continue
        if direction == "put" and imp_move > -min_impulse:
            continue

        # Pullback: velas após a pernada (restante da janela + vela candidata)
        pb_window = analysis_window[impulse_lb:]
        if not pb_window:
            continue

        pb_closes = [float(v["close"]) for v in pb_window]
        if direction == "call":
            # Pullback de baixa após impulso de alta
            # Verificar que pelo menos metade das velas do pullback são de baixa
            pb_bearish = sum(1 for i in range(1, len(pb_closes)) if pb_closes[i] < pb_closes[i-1])
            pb_ok = pb_bearish >= max(1, len(pb_closes) // 2)
            if not pb_ok:
                continue
            impulse_size = abs(imp_end - imp_start)
            if impulse_size < 1e-10:
                continue
            pb_retrace = (imp_end - pb_closes[-1]) / impulse_size
            if pb_retrace > pb_max_frac or pb_retrace < 0.05:
                continue   # pullback inexistente ou muito profundo
            # Gatilho de CALL: vela candidata fecha acima do máximo do pullback
            pb_high = max(highs[impulse_lb:])
            trigger_price = float(c_last.get("close", 0))
            if trigger_price <= pb_high:
                continue
        else:
            # Pullback de alta após impulso de baixa
            pb_bullish = sum(1 for i in range(1, len(pb_closes)) if pb_closes[i] > pb_closes[i-1])
            pb_ok = pb_bullish >= max(1, len(pb_closes) // 2)
            if not pb_ok:
                continue
            impulse_size = abs(imp_end - imp_start)
            if impulse_size < 1e-10:
                continue
            pb_retrace = abs(pb_closes[-1] - imp_end) / impulse_size
            if pb_retrace > pb_max_frac or pb_retrace < 0.05:
                continue
            # Gatilho de PUT: vela candidata fecha abaixo da mínima do pullback
            pb_low = min(lows[impulse_lb:])
            trigger_price = float(c_last.get("close", 0))
            if trigger_price >= pb_low:
                continue

        # Sinal detectado
        v15_score_min = V15_SCORE_MIN_M5 if is_m5 else V15_SCORE_MIN_M1
        return {
            "pattern_name": f"Respiro_{'CALL' if direction == 'call' else 'PUT'}",
            "direction_hint": direction,
            "requires_confirmation": True,
            "pattern_from": pattern_from,
            "expected_confirm_from": expected_confirm_from,
            "v15_score": v15_score_min,   # score artificial para compatibilidade
            "v15_confirm_count": 0,
            "pattern_mode": "respiro",
            "strategy": "respiro",
            "rsi_pts": 0, "bb_pts": 0, "wick_pts": 0, "imp_pts": 0,
            "keltner_pts": 0, "engulf_pts": 0,
            "call_score": v15_score_min if direction == "call" else 0,
            "put_score": v15_score_min if direction == "put" else 0,
            "pivot_prox": "",
        }

    return None


# =========================
# MOTOR DE REVERSÃO V15
# Score/contexto/sustentação, impulso, wick, RSI, BB.
# Substitui completamente a detecção e confirmação reversal da v14.
# Padrões breakout/harami/hammer preservados como fallback.
# =========================

# --- Parâmetros V15 (defaults; sobrescritos por _load_from_config via config.txt [M1]/[M5]) ---
V15_SCORE_MIN = 55           # Score mínimo para sinal reversal V15 (0–100)
V15_SCORE_GAP_MIN = 1        # Diferença mínima call/put
V15_CONFIRM_POLLS = 1        # Polls de confirmação necessários
V15_RSI_PERIOD = 14          # Período RSI
V15_RSI_OVERSOLD = 30        # RSI abaixo deste valor = oversold → sinal call
V15_RSI_OVERBOUGHT = 70      # RSI acima deste valor = overbought → sinal put
V15_BB_PERIOD = 20           # Período Bollinger Bands
V15_BB_STD = 2.0             # Multiplicador de desvio padrão para BB
V15_BB_PROXIMITY = 0.25      # Fração da largura da banda para "próximo do extremo"
V15_IMPULSE_LOOKBACK = 5     # Número de velas para cálculo de impulso
V15_CONTEXT_LOOKBACK = 12    # Número de velas para contexto de tendência prévia
V15_WICK_RATIO = 0.45        # Wick mínimo (wick/range) para pontuar sombra longa
V15_CANDLES_NEEDED = 40      # Mínimo de velas para o motor V15 funcionar
V15_TREND_THRESHOLD = 0.0008
V15_IMPULSE_THRESHOLD = 0.0006
V15_IMPULSE_MULTIPLIER = 8000
V15_WICK_SCORE_MAX = 25
V15_WICK_SCORE_FACTOR = 35
V15_FALLBACK_NEAR_SCORE_M1 = 38

# =========================
# FILTRO ESTRUTURAL M5 (v15.1)
# Aplicado exclusivamente no timeframe M5 para sinais V15.
# Garante que a vela candidata esteja próxima do extremo recente,
# evitando reversões "no meio do range" (zonas ruidosas).
# Para ajuste futuro: altere M5_EXTREME_CANDLES (janela) e
# M5_EXTREME_FRAC (tolerância — 0.20 = 20% mais baixos/altos).
# =========================
M5_EXTREME_CANDLES = 20   # Quantidade de velas retroativas para definir o range estrutural
M5_EXTREME_FRAC    = 0.20 # Fração do range aceita como "extremo" (20% → tolerância razoável)


def _m5_extreme_filter(direction: str, velas: List[Dict[str, Any]]) -> bool:
    """
    Filtro de localização estrutural exclusivo do M5 (v15.1).

    Verifica se o fechamento da vela candidata (penúltima da lista)
    está no extremo do range das últimas M5_EXTREME_CANDLES velas:
      - CALL: close nos 20% mais BAIXOS do range  → tende a reversão de alta
      - PUT : close nos 20% mais ALTOS  do range  → tende a reversão de baixa

    A tolerância de 20% foi escolhida deliberadamente para NÃO endurecer
    demais o critério no M5 (que já é seletivo por natureza).
    Retorna True se o sinal PASSA o filtro, False se deve ser rejeitado.
    Para ajustar a rigidez: aumente M5_EXTREME_FRAC (mais permissivo)
    ou diminua (mais restritivo).
    """
    # Garante janela suficiente; se não houver velas bastantes, não bloqueia
    window = velas[-(M5_EXTREME_CANDLES + 2):-1]  # inclui candidata e N anteriores
    if len(window) < 3:
        return True

    highs  = [float(v.get("max", v.get("high", v.get("close", 0)))) for v in window]
    lows   = [float(v.get("min", v.get("low",  v.get("close", 0)))) for v in window]
    range_high = max(highs)
    range_low  = min(lows)
    range_size = range_high - range_low

    if range_size < 1e-10:
        return True  # range degenerado → não bloqueia

    candidate_close = float(window[-1].get("close", 0))
    threshold = range_size * M5_EXTREME_FRAC

    if direction == "call":
        # Aceita se fechamento está nos M5_EXTREME_FRAC mais baixos do range
        return candidate_close <= range_low + threshold
    else:  # put
        # Aceita se fechamento está nos M5_EXTREME_FRAC mais altos do range
        return candidate_close >= range_high - threshold


# =========================
# FILTRO ESTRUTURAL M1 (v15.2)
# Aplicado exclusivamente no timeframe M1 para sinais V15.
# Garante que a vela candidata esteja no 1/3 extremo do micro-range,
# evitando reversões no meio do range (zonas ruidosas para M1).
# Para ajuste futuro: altere M1_STRUCTURAL_CANDLES (janela).
# =========================
M1_STRUCTURAL_CANDLES = 5  # Janela de velas para definir o micro-range estrutural M1


def _m1_structural_filter(direction: str, velas: List[Dict[str, Any]]) -> bool:
    """
    Filtro de localização estrutural leve para M1 (v15.2).

    Verifica se o fechamento da vela candidata (penúltima da lista)
    está no 1/3 extremo do micro-range das últimas M1_STRUCTURAL_CANDLES velas:
      - CALL: close no 1/3 inferior do micro-range → favorece reversão de alta
      - PUT : close no 1/3 superior do micro-range → favorece reversão de baixa

    Retorna True se o sinal PASSA o filtro, False se deve ser rejeitado.
    Se não houver velas suficientes, não bloqueia (passa por padrão).
    """
    window = velas[-(M1_STRUCTURAL_CANDLES + 1):-1]
    if len(window) < 3:
        return True  # não bloqueia por falta de dados

    closes = [float(v.get("close", 0)) for v in window]
    high = max(closes)
    low = min(closes)
    rng = high - low

    if rng < 1e-10:
        return True  # range degenerado → não bloqueia

    candidate_close = closes[-1]
    third = rng / 3.0

    if direction == "call":
        # Aceita se fechamento está no 1/3 inferior do micro-range
        return candidate_close <= low + third
    else:  # put
        # Aceita se fechamento está no 1/3 superior do micro-range
        return candidate_close >= high - third


def _v15_rsi(closes: List[float], period: int = 14) -> Optional[float]:
    """Calcula RSI (Relative Strength Index) com suavização Wilder."""
    if len(closes) < period + 2:
        return None
    # Seed com as primeiras 'period' diferenças
    gains, losses = [], []
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    # Wilder smoothing para as velas restantes
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(delta, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-delta, 0.0)) / period
    if abs(avg_loss) < 1e-10:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _v15_bollinger(closes: List[float], period: int = 20,
                   std_mult: float = 2.0) -> Optional[Tuple[float, float, float]]:
    """Retorna (upper, middle, lower) das Bandas de Bollinger."""
    if len(closes) < period:
        return None
    window = closes[-period:]
    mean = sum(window) / period
    var = sum((x - mean) ** 2 for x in window) / period
    sd = var ** 0.5
    return mean + std_mult * sd, mean, mean - std_mult * sd


def _v15_impulse(velas: List[Dict[str, Any]], lookback: int = 5) -> Optional[float]:
    """
    Calcula impulso como variação normalizada dos fechamentos nas últimas
    'lookback' velas. Positivo = alta recente, Negativo = queda recente.
    """
    if len(velas) < lookback + 1:
        return None
    closes = [float(v["close"]) for v in velas[-(lookback + 1):]]
    base = closes[0] if abs(closes[0]) > 1e-10 else 1e-12
    return (closes[-1] - closes[0]) / abs(base)


def _v15_context(velas: List[Dict[str, Any]], lookback: int = 12) -> Optional[str]:
    """
    Retorna contexto de tendência prévia: 'downtrend', 'uptrend' ou 'sideways'.
    Analisa somente velas antes da vela candidata (excluindo as 2 últimas).
    """
    if len(velas) < lookback + 3:
        return None
    # Pega as velas antes das 2 últimas (candidata e in-progress)
    ctx_velas = velas[-(lookback + 2):-2]
    if len(ctx_velas) < 2:
        return None
    closes = [float(v["close"]) for v in ctx_velas]
    half = max(1, len(closes) // 2)
    first_avg = sum(closes[:half]) / half
    second_avg = sum(closes[half:]) / max(1, len(closes) - half)
    base = abs(first_avg) if abs(first_avg) > 1e-10 else 1e-12
    change = (second_avg - first_avg) / base
    if change < -V15_TREND_THRESHOLD:
        return "downtrend"
    if change > V15_TREND_THRESHOLD:
        return "uptrend"
    return "sideways"


def _v15_wick_score(c: Dict[str, Any]) -> Tuple[int, Optional[str]]:
    """
    Pontua a sombra (wick) da vela candidata para sinal de reversão.
      Wick inferior longo → reversão de alta (call).
      Wick superior longo → reversão de baixa (put).
    Retorna (pontos: 0–25, 'call'|'put'|None).
    """
    p = _candle_parts(c)
    rng = max(p["high"] - p["low"], 1e-12)
    lower_wick = min(p["open"], p["close"]) - p["low"]
    upper_wick = p["high"] - max(p["open"], p["close"])
    lower_ratio = lower_wick / rng
    upper_ratio = upper_wick / rng
    if lower_ratio >= V15_WICK_RATIO and lower_ratio > upper_ratio:
        # Sombra inferior dominante → call (suporte rejeitado)
        pts = int(min(V15_WICK_SCORE_MAX, lower_ratio * V15_WICK_SCORE_FACTOR))
        return pts, "call"
    if upper_ratio >= V15_WICK_RATIO and upper_ratio > lower_ratio:
        # Sombra superior dominante → put (resistência rejeitada)
        pts = int(min(V15_WICK_SCORE_MAX, upper_ratio * V15_WICK_SCORE_FACTOR))
        return pts, "put"
    return 0, None


def check_patterns(tf_min: int, velas: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    MOTOR DE REVERSÃO V15 (+ Respiro como modo alternativo)
    ─────────────────────────────────────────────────────────
    Reversal mode detecta sinais por score composto (máximo ~145 pontos):
      • RSI         (0–25 pts): oversold/overbought indica exaustão
      • BB          (0–25 pts): preço próximo das bandas extremas
      • Wick        (0–25 pts): sombra longa indica rejeição de preço
      • Impulso+Ctx (0–25 pts): tendência prévia confirma contexto reversal
      • Keltner     (0–20 pts): bônus quando preço toca extremo do canal Keltner
      • Engolfo/Pinça (0–15 pts): bônus por padrão de vela confirmatório

    Continuation mode (respiro) delega para _detect_respiro().

    Sinal disparado quando score >= V15_SCORE_MIN_M{tf_min} E gap >= V15_SCORE_GAP_MIN_M{tf_min}.
    """
    if not velas or len(velas) < max(V15_CANDLES_NEEDED, 6):
        return None

    # --- Seleciona parâmetros por TF ---
    is_m5 = (tf_min == 5)
    v15_score_min   = V15_SCORE_MIN_M5   if is_m5 else V15_SCORE_MIN_M1
    v15_gap_min     = V15_SCORE_GAP_MIN_M5 if is_m5 else V15_SCORE_GAP_MIN_M1
    entry_mode_tf   = ENTRY_MODE_M5      if is_m5 else ENTRY_MODE_M1
    keltner_enable  = KELTNER_ENABLE_M5  if is_m5 else KELTNER_ENABLE_M1
    keltner_period  = KELTNER_PERIOD_M5  if is_m5 else KELTNER_PERIOD_M1
    keltner_shift   = KELTNER_SHIFT_M5   if is_m5 else KELTNER_SHIFT_M1
    pivot_enable    = PIVOT_ENABLE_M5    if is_m5 else PIVOT_ENABLE_M1
    pivot_left      = PIVOT_LEFT_M5      if is_m5 else PIVOT_LEFT_M1
    pivot_right     = PIVOT_RIGHT_M5     if is_m5 else PIVOT_RIGHT_M1
    pivot_prox_pct  = PIVOT_PROXIMITY_PCT_M5 if is_m5 else PIVOT_PROXIMITY_PCT_M1

    # --- ARM + SNIPER: score elevado e modo de execução diferenciado ---
    sniper_mode_tf           = SNIPER_MODE_M5           if is_m5 else SNIPER_MODE_M1
    arm_score_min_tf         = ARM_SCORE_MIN_M5         if is_m5 else ARM_SCORE_MIN_M1
    fallback_arm_score_min_tf = FALLBACK_ARM_SCORE_MIN_M5 if is_m5 else FALLBACK_ARM_SCORE_MIN_M1
    # Em modo sniper, usa arm_score_min (mais alto) para compensar remoção da confirmação intra-vela
    effective_score_min      = arm_score_min_tf if sniper_mode_tf else v15_score_min
    # Tag de pattern_mode: "arm_sniper" em sniper mode, "v15" caso contrário
    _pattern_mode_tag        = "arm_sniper"     if sniper_mode_tf else "v15"

    # --- Modo Continuação (Respiro) ---
    if entry_mode_tf == "continuation":
        return _detect_respiro(tf_min, velas)

    period = tf_min * 60
    c_last = velas[-2]   # vela candidata (penúltima, já fechada)
    c_prev = velas[-3]   # vela anterior (para fallback harami/engolfo/pinça)
    pattern_from = int(c_last.get("from", 0))
    expected_confirm_from = pattern_from + period
    closes = [float(v["close"]) for v in velas]

    # ── Componente RSI (0–25 pts) ──────────────────────────────────────────
    rsi = _v15_rsi(closes, V15_RSI_PERIOD)
    rsi_pts = 0
    rsi_dir: Optional[str] = None
    if rsi is not None:
        if rsi <= V15_RSI_OVERSOLD:
            rsi_pts, rsi_dir = 25, "call"
        elif rsi <= V15_RSI_OVERSOLD + 10:
            rsi_pts, rsi_dir = 12, "call"
        elif rsi >= V15_RSI_OVERBOUGHT:
            rsi_pts, rsi_dir = 25, "put"
        elif rsi >= V15_RSI_OVERBOUGHT - 10:
            rsi_pts, rsi_dir = 12, "put"

    # ── Componente BB (0–25 pts) ───────────────────────────────────────────
    bb = _v15_bollinger(closes, V15_BB_PERIOD, V15_BB_STD)
    bb_pts = 0
    bb_dir: Optional[str] = None
    if bb is not None:
        upper, _mid, lower = bb
        band_width = max(upper - lower, 1e-12)
        price = float(c_last.get("close", closes[-2]))
        prox_thr = band_width * V15_BB_PROXIMITY
        dist_lower = price - lower
        dist_upper = upper - price
        if dist_lower <= prox_thr and dist_lower >= 0:
            frac = max(0.0, 1.0 - dist_lower / max(prox_thr, 1e-12))
            bb_pts, bb_dir = int(frac * 25), "call"
        elif dist_lower < 0:
            bb_pts, bb_dir = 25, "call"
        elif dist_upper <= prox_thr and dist_upper >= 0:
            frac = max(0.0, 1.0 - dist_upper / max(prox_thr, 1e-12))
            bb_pts, bb_dir = int(frac * 25), "put"
        elif dist_upper < 0:
            bb_pts, bb_dir = 25, "put"

    # ── Componente Wick (0–25 pts) ─────────────────────────────────────────
    wick_pts, wick_dir = _v15_wick_score(c_last)

    # ── Componente Impulso + Contexto (0–25 pts) ───────────────────────────
    impulse = _v15_impulse(velas, V15_IMPULSE_LOOKBACK)
    context = _v15_context(velas, V15_CONTEXT_LOOKBACK)
    imp_pts = 0
    imp_dir: Optional[str] = None
    if impulse is not None and context is not None:
        if context == "downtrend" and impulse < -V15_IMPULSE_THRESHOLD:
            imp_pts = int(min(V15_WICK_SCORE_MAX, abs(impulse) * V15_IMPULSE_MULTIPLIER))
            imp_dir = "call"
        elif context == "uptrend" and impulse > V15_IMPULSE_THRESHOLD:
            imp_pts = int(min(V15_WICK_SCORE_MAX, abs(impulse) * V15_IMPULSE_MULTIPLIER))
            imp_dir = "put"

    # ── Componente Keltner (0–20 pts) bônus ─────────────────────────────────
    keltner_pts = 0
    keltner_dir: Optional[str] = None
    if keltner_enable:
        keltner_pts, keltner_dir = _keltner_score(velas, period=keltner_period, shift=keltner_shift)

    # ── Componente Engolfo/Pinça (0–15 pts) bônus ────────────────────────────
    engulf_pts = 0
    engulf_dir: Optional[str] = None
    if len(velas) >= 3:
        engulf_pts, engulf_dir = _candle_engulf_score(c_prev, c_last)

    # ── Soma de scores por direção ─────────────────────────────────────────
    call_score = (rsi_pts    if rsi_dir    == "call" else 0) + \
                 (bb_pts     if bb_dir     == "call" else 0) + \
                 (wick_pts   if wick_dir   == "call" else 0) + \
                 (imp_pts    if imp_dir    == "call" else 0) + \
                 (keltner_pts if keltner_dir == "call" else 0) + \
                 (engulf_pts if engulf_dir == "call" else 0)
    put_score  = (rsi_pts    if rsi_dir    == "put" else 0) + \
                 (bb_pts     if bb_dir     == "put" else 0) + \
                 (wick_pts   if wick_dir   == "put" else 0) + \
                 (imp_pts    if imp_dir    == "put" else 0) + \
                 (keltner_pts if keltner_dir == "put" else 0) + \
                 (engulf_pts if engulf_dir == "put" else 0)

    # Pivô: verificar proximidade para log e uso como contexto estrutural
    pivot_prox_str = ""
    if pivot_enable and len(velas) >= (pivot_left + pivot_right + 3):
        _best_dir = "call" if call_score >= put_score else "put"
        _near, _dist_pct = _pivot_proximity(velas, _best_dir,
                                             left=pivot_left, right=pivot_right,
                                             proximity_pct=pivot_prox_pct)
        pivot_prox_str = f"{_dist_pct:.5f}"

    # Componentes de score compartilhados por todos os retornos
    _score_components = {
        "rsi_pts": rsi_pts,
        "bb_pts": bb_pts,
        "wick_pts": wick_pts,
        "imp_pts": imp_pts,
        "keltner_pts": keltner_pts,
        "engulf_pts": engulf_pts,
        "call_score": call_score,
        "put_score": put_score,
        "strategy": "v15",
        "pivot_prox": pivot_prox_str,
    }

    # ── Disparo do sinal V15 / ARM ─────────────────────────────────────────
    # Em modo sniper: usa effective_score_min (arm_score_min > v15_score_min) e
    # marca pattern_mode="arm_sniper" para a fase EXEC (0–5s após abertura).
    if call_score >= effective_score_min and (call_score - put_score) >= v15_gap_min:
        if tf_min == 5 and not _m5_extreme_filter("call", velas):
            return None
        elif tf_min == 1 and not _m1_structural_filter("call", velas):
            return None
        return {
            "pattern_name": "ReversalV15_CALL",
            "direction_hint": "call",
            "requires_confirmation": True,
            "pattern_from": pattern_from,
            "expected_confirm_from": expected_confirm_from,
            "v15_score": call_score,
            "v15_confirm_count": 0,
            "pattern_mode": _pattern_mode_tag,
            **_score_components,
        }
    if put_score >= effective_score_min and (put_score - call_score) >= v15_gap_min:
        if tf_min == 5 and not _m5_extreme_filter("put", velas):
            return None
        elif tf_min == 1 and not _m1_structural_filter("put", velas):
            return None
        return {
            "pattern_name": "ReversalV15_PUT",
            "direction_hint": "put",
            "requires_confirmation": True,
            "pattern_from": pattern_from,
            "expected_confirm_from": expected_confirm_from,
            "v15_score": put_score,
            "v15_confirm_count": 0,
            "pattern_mode": _pattern_mode_tag,
            **_score_components,
        }

    # ── Fallback v14: Harami / Hammer / Engolfo / Pinça ───────────────────
    _best_score = max(call_score, put_score)
    # Em modo sniper o fallback também usa score mínimo elevado (fallback_arm_score_min)
    _fallback_score_min = fallback_arm_score_min_tf if sniper_mode_tf else V15_FALLBACK_NEAR_SCORE_M1
    _fallback_m1_ok = (tf_min != 1) or (_best_score >= _fallback_score_min)

    # Fallback em modo sniper: execução via arm_sniper (entrada na abertura da próxima vela)
    _score_components_fb = {**_score_components, "pattern_mode": _pattern_mode_tag, "strategy": "fallback"}

    if is_harami_bearish(c_prev, c_last) or is_engulfing_bearish(c_prev, c_last) or is_tweezer_top(c_prev, c_last):
        if not _fallback_m1_ok:
            return None
        if tf_min == 1 and not _m1_structural_filter("put", velas):
            return None
        pat = "HaramiBearish" if is_harami_bearish(c_prev, c_last) else \
              ("EngolfoBearish" if is_engulfing_bearish(c_prev, c_last) else "TweezerTop")
        return {
            "pattern_name": pat,
            "direction_hint": "put",
            "requires_confirmation": True,
            "pattern_from": pattern_from,
            "expected_confirm_from": expected_confirm_from,
            "v15_score": 0,
            "v15_confirm_count": 0,
            **_score_components_fb,
        }
    if is_harami_bullish(c_prev, c_last) or is_engulfing_bullish(c_prev, c_last) or is_tweezer_bottom(c_prev, c_last):
        if not _fallback_m1_ok:
            return None
        if tf_min == 1 and not _m1_structural_filter("call", velas):
            return None
        pat = "HaramiBullish" if is_harami_bullish(c_prev, c_last) else \
              ("EngolfoBullish" if is_engulfing_bullish(c_prev, c_last) else "TweezerBottom")
        return {
            "pattern_name": pat,
            "direction_hint": "call",
            "requires_confirmation": True,
            "pattern_from": pattern_from,
            "expected_confirm_from": expected_confirm_from,
            "v15_score": 0,
            "v15_confirm_count": 0,
            **_score_components_fb,
        }
    if is_hammer(c_last):
        if not _fallback_m1_ok:
            return None
        if tf_min == 1 and not _m1_structural_filter("call", velas):
            return None
        return {
            "pattern_name": "Hammer",
            "direction_hint": "call",
            "requires_confirmation": True,
            "pattern_from": pattern_from,
            "expected_confirm_from": expected_confirm_from,
            "v15_score": 0,
            "v15_confirm_count": 0,
            **_score_components_fb,
        }

    return None


def confirm_pending(tf_min: int, pending: Dict[str, Any], velas: List[Dict[str, Any]]) -> Tuple[str, Optional[str]]:
    """
    CONFIRMAÇÃO DE REVERSÃO V15
    ───────────────────────────
    Para sinais V15 (pattern_mode='v15'):
      Requer V15_CONFIRM_POLLS polls consecutivos onde o preço confirma
      a direção prevista.

      Para M1: usa margem dinâmica baseada no ATR (preço > fechamento + ATR*0.1
      para call, preço < fechamento - ATR*0.1 para put), reduzindo falsos
      confirmações por ruído/micro-oscilação.

      Para M5: comparação direta com fechamento da vela de sinal.

      NOTA: modifica pending['v15_confirm_count'] diretamente a cada poll
      para rastrear o progresso de sustentação (efeito colateral intencional).

    Para sinais fallback (pattern_mode='fallback': harami/hammer):
      Usa a lógica clássica da v14 — confirmação na vela seguinte
      ao padrão (candle close versus referência).

    Retorna:
      ("confirmed", direction) — sinal confirmado, pode entrar
      ("waiting", None)        — aguardando mais dados/polls
      ("rejected", None)       — sinal inválido, descartar
      ("expired", None)        — fora do prazo de validade
      ("error", None)          — dados insuficientes
    """
    period = tf_min * 60
    pattern_from = int(pending["pattern_from"])
    expected_confirm_from = int(pending["expected_confirm_from"])
    expire_from = pattern_from + (PENDING_EXPIRE_CANDLES * period)
    direction_hint = pending.get("direction_hint", "call")
    pattern_mode = pending.get("pattern_mode", "fallback")

    now_server = get_now_ts()
    if now_server >= expire_from + 2:
        return "expired", None

    # ─── Confirmação ARM + SNIPER (0–Ns): entra na abertura da vela alvo ──
    # Não depende de confirmação intra-vela: executa imediatamente ao abrir a
    # vela alvo (expected_confirm_from), dentro da janela SNIPER_WINDOW_SECONDS.
    # Filtro anti-fakeout: preço atual vs open da vela alvo.
    # Timing usa open_time REAL da vela (candle["from"]) para secs_from_open,
    # tornando a janela robusta mesmo se now_server tiver pequeno drift.
    if pattern_mode == "arm_sniper":
        # Busca a vela alvo (em formação: velas[-1] quando API já a entregou)
        c_target = velas[-1] if velas else None
        latest_candle_from = int(c_target.get("from", -1)) if c_target else -1

        # Se a API ainda não entregou a vela alvo, aguardar próximo tick
        if latest_candle_from < expected_confirm_from:
            # Mas se o relógio já passou de um candle inteiro além do ECF,
            # significa que a vela alvo veio e foi — expired definitivo.
            if now_server >= expected_confirm_from + period:
                return "expired", None
            return "waiting", None

        # Se a vela entregue já é posterior ao alvo (alvo veio e foi)
        if latest_candle_from > expected_confirm_from:
            return "expired", None

        # Vela alvo confirmada pelo feed — calcular secs_from_open com base no
        # open_time REAL da vela (mais robusto que now_server - ECF com drift).
        _sniper_win = SNIPER_WINDOW_SECONDS_M5 if tf_min == 5 else SNIPER_WINDOW_SECONDS_M1
        candle_open_ts = latest_candle_from  # == expected_confirm_from neste ponto
        secs_from_open = now_server - candle_open_ts
        if secs_from_open > _sniper_win:
            _log_blocked(
                "sniper_window_expired",
                f"tf={tf_min} secs_from_open={secs_from_open:.1f} "
                f"window={_sniper_win} ecf={expected_confirm_from} "
                f"candle_open_ts={candle_open_ts} now_server={now_server} "
                f"dir={direction_hint or 'unknown'}"
            )
            return "rejected", None

        open_candle   = float(c_target.get("open", 0))
        current_price = float(c_target.get("close", open_candle))

        if open_candle == 0:
            return "waiting", None

        # Anti-fakeout primário: preço deve confirmar direção vs abertura
        # CALL: preço >= open  |  PUT: preço <= open
        if direction_hint == "call":
            antifakeout_ok = current_price >= open_candle
        else:
            antifakeout_ok = current_price <= open_candle

        if not antifakeout_ok:
            # Ainda dentro da janela — aguardar próximo tick
            return "waiting", None

        # Anti-fakeout opcional (por TF): não violar extremo da vela anterior
        _afe_extreme = SNIPER_ANTIFAKEOUT_EXTREME_M5 if tf_min == 5 else SNIPER_ANTIFAKEOUT_EXTREME_M1
        if _afe_extreme:
            c_pat = _find_candle_by_from(velas, pattern_from)
            if c_pat is not None:
                if direction_hint == "call":
                    if current_price < float(c_pat.get("min", current_price)):
                        return "waiting", None
                else:
                    if current_price > float(c_pat.get("max", current_price)):
                        return "waiting", None

        return "confirmed", direction_hint

    c_pattern = _find_candle_by_from(velas, pattern_from)
    if c_pattern is None:
        return "error", None

    # ─── Confirmação V15: sustentação por múltiplos polls ─────────────────
    if pattern_mode == "v15":
        # Aguarda abertura da janela de confirmação
        if now_server < expected_confirm_from:
            return "waiting", None

        # Referência: fechamento da vela de sinal
        p_ref = float(c_pattern.get("close", 0))
        if p_ref == 0:
            return "error", None

        # Usa a última vela disponível para comparar preço atual
        c_confirm = velas[-1] if velas else None
        if c_confirm is None:
            return "waiting", None

        c_price = float(c_confirm.get("close", c_confirm.get("open", p_ref)))

        # Para M1: usa margem dinâmica proporcional ao ATR (buffer anti-ruído)
        # Para M5: comparação direta com fechamento (comportamento original)
        if tf_min == 1:
            atr = calculate_atr_from_candles(velas, periodo=ATR_PERIOD)
            price_buffer = (atr * 0.1) if atr is not None else 0.0
            confirmed_now = (direction_hint == "call" and c_price > p_ref + price_buffer) or \
                            (direction_hint == "put" and c_price < p_ref - price_buffer)
        else:
            confirmed_now = (direction_hint == "call" and c_price > p_ref) or \
                            (direction_hint == "put" and c_price < p_ref)

        confirm_polls_needed = V15_CONFIRM_POLLS_M5 if tf_min == 5 else V15_CONFIRM_POLLS_M1
        if confirmed_now:
            pending["v15_confirm_count"] = pending.get("v15_confirm_count", 0) + 1
            if pending["v15_confirm_count"] >= confirm_polls_needed:
                return "confirmed", direction_hint
            return "waiting", None
        else:
            pending["v15_confirm_count"] = 0
            if now_server >= expected_confirm_from + period:
                return "rejected", None
            return "waiting", None

    # ─── Confirmação Respiro: mesma lógica de sustentação do V15 ──────────
    if pattern_mode == "respiro":
        if now_server < expected_confirm_from:
            return "waiting", None
        p_ref = float(c_pattern.get("close", 0))
        if p_ref == 0:
            return "error", None
        c_confirm = velas[-1] if velas else None
        if c_confirm is None:
            return "waiting", None
        c_price = float(c_confirm.get("close", c_confirm.get("open", p_ref)))
        confirmed_now = (direction_hint == "call" and c_price > p_ref) or \
                        (direction_hint == "put" and c_price < p_ref)
        confirm_polls_needed = RESPIRO_CONFIRM_POLLS_M5 if tf_min == 5 else RESPIRO_CONFIRM_POLLS_M1
        if confirmed_now:
            pending["v15_confirm_count"] = pending.get("v15_confirm_count", 0) + 1
            if pending["v15_confirm_count"] >= confirm_polls_needed:
                return "confirmed", direction_hint
            return "waiting", None
        else:
            pending["v15_confirm_count"] = 0
            if now_server >= expected_confirm_from + period:
                return "rejected", None
            return "waiting", None

    # ─── Confirmação fallback v14: harami/hammer/engolfo/pinça ───────────
    c_next = _find_candle_by_from(velas, expected_confirm_from)
    if c_next is None:
        return "waiting", None

    patt = pending["pattern_name"]
    rng = float(c_pattern["max"]) - float(c_pattern["min"])
    bull_level = float(c_pattern["min"]) + (rng * 0.40)
    bear_level = float(c_pattern["max"]) - (rng * 0.40)
    if patt == "Hammer":
        ok = float(c_next["close"]) > float(c_pattern["max"])
        return ("confirmed" if ok else "rejected"), ("call" if ok else None)
    if patt in ("HaramiBullish", "EngolfoBullish", "TweezerBottom"):
        ok = (float(c_next["close"]) > float(c_next["open"])) and (float(c_next["close"]) > bull_level)
        return ("confirmed" if ok else "rejected"), ("call" if ok else None)
    if patt in ("HaramiBearish", "EngolfoBearish", "TweezerTop"):
        ok = (float(c_next["close"]) < float(c_next["open"])) and (float(c_next["close"]) < bear_level)
        return ("confirmed" if ok else "rejected"), ("put" if ok else None)
    return "error", None


# =========================
# Timing / amount
# =========================
def within_entry_window(tf_min: int) -> Tuple[bool, int, int]:
    period = tf_min * 60
    window = ENTRY_WINDOW_SECONDS_M5 if tf_min == 5 else ENTRY_WINDOW_SECONDS_M1
    now_s = get_now_ts()
    sec = int(now_s % period)
    return sec <= window, sec, window


def compute_amount(balance: float) -> float:
    if AMOUNT_MODE == "fixed":
        amt = float(AMOUNT_FIXED)
    else:
        amt = (balance * (AMOUNT_PERCENT / 100.0)) if AMOUNT_RECALC_EACH else float(AMOUNT_FIXED)
    if amt < AMOUNT_MIN:
        amt = AMOUNT_MIN
    amt = round(amt, 2)
    if amt > balance:
        amt = round(max(AMOUNT_MIN, balance), 2)
    return amt


# =========================
# Resultado
# =========================
def _try_query_order_methods(order_id):
    methods = [
        'get_order', 'get_order_by_id', 'get_order_history', 'get_positions',
        'get_position', 'get_position_by_id', 'get_positions_history', 'get_order_history_v2'
    ]
    for name in methods:
        try:
            fn = getattr(API, name, None)
            if fn is None:
                continue
            for arg in (order_id, str(order_id), int(order_id) if str(order_id).isdigit() else order_id,):
                try:
                    res = fn(arg) if arg is not None else fn()
                except TypeError:
                    try:
                        res = fn()
                    except Exception:
                        res = None
                except Exception:
                    res = None
                if res:
                    return {'method': name, 'input_arg': arg, 'raw': res}
        except Exception:
            continue
    return None


def _parse_order_query_response(raw):
    def inspect_item(item):
        if isinstance(item, dict):
            keys = {k.lower(): v for k, v in item.items()}
            for k in ('profit', 'payout', 'profit_amount', 'result', 'win', 'amount_win'):
                if k in keys:
                    try:
                        return {'profit': float(keys[k]), 'raw': item}
                    except Exception:
                        pass
            for k in ('status', 'state', 'order_status', 'close_status'):
                if k in keys:
                    val = str(keys[k]).lower()
                    if 'win' in val or 'profit' in val or 'paid' in val:
                        return {'status': 'win', 'raw': item}
                    if 'loss' in val or 'lose' in val or 'lost' in val:
                        return {'status': 'loss', 'raw': item}
                    return {'status': val, 'raw': item}
            for v in item.values():
                parsed = inspect_item(v)
                if parsed:
                    return parsed
        elif isinstance(item, (list, tuple)):
            for it in item:
                parsed = inspect_item(it)
                if parsed:
                    return parsed
        return None

    parsed = inspect_item(raw)
    if not parsed:
        return {'status': 'unknown', 'profit': None, 'raw': raw}

    status = parsed.get('status')
    profit = parsed.get('profit')
    if profit is not None:
        try:
            profit = float(profit)
            if profit > 0:
                status = 'win'
            elif profit < 0:
                status = 'loss'
            else:
                status = 'unknown'
        except Exception:
            pass

    return {'status': status or 'unknown', 'profit': profit,
            'raw': parsed.get('raw') if 'raw' in parsed else raw}


def _early_loss_by_stable_balance(balance_before: float, amount: float,
                                 poll_interval: float = EARLY_LOSS_SAMPLE_INTERVAL_S) -> bool:
    if balance_before is None or amount is None:
        return False
    try:
        balance_before = float(balance_before)
        amount = float(amount)
    except Exception:
        return False
    if amount <= 0:
        return False

    amostras: List[float] = []
    for _ in range(EARLY_LOSS_STABLE_SAMPLES):
        time.sleep(poll_interval)
        bal = get_available_balance()
        if bal is None:
            return False
        amostras.append(float(bal))

    mn = min(amostras)
    mx = max(amostras)
    if (mx - mn) > EARLY_LOSS_EPS:
        return False

    last = amostras[-1]
    if last < balance_before - (amount * 0.30):
        return True

    return False


def check_order_result(order_id, amount, saldo_before=None, timeout_seconds=90, poll_interval=1.5):
    start_check_ts = time.time()
    deadline = start_check_ts + timeout_seconds

    try:
        q = _try_query_order_methods(order_id)
        if q:
            parsed = _parse_order_query_response(q['raw'])
            if parsed.get('status') in ('win', 'loss'):
                bal = get_available_balance()
                return {'result': parsed['status'], 'profit': parsed.get('profit'), 'balance_after': bal,
                        'method': 'order_query', 'raw': q}
    except Exception:
        pass

    if saldo_before is None:
        saldo_before = get_available_balance()
    if saldo_before is None:
        return {'result': 'unknown', 'profit': None, 'balance_after': None, 'method': 'no_balance', 'raw': None}

    expected_post_purchase = saldo_before - (amount or 0.0)
    eps_small = max(0.01, (amount or 0.0) * 0.005)
    profit_threshold = max(0.01, (amount or 0.0) * 0.05)

    purchase_seen = False
    last_bal = saldo_before
    extended_wait_used = False
    early_loss_checked = False

    purchase_detect_deadline = min(time.time() + 8.0, deadline)
    while time.time() <= purchase_detect_deadline:
        time.sleep(0.4)
        bal = get_available_balance()
        if bal is None:
            continue
        if bal <= expected_post_purchase + eps_small:
            purchase_seen = True
            last_bal = bal
            break
        last_bal = bal

    while time.time() <= deadline:
        try:
            q = _try_query_order_methods(order_id)
            if q:
                parsed = _parse_order_query_response(q['raw'])
                if parsed.get('status') in ('win', 'loss'):
                    bal = get_available_balance()
                    return {'result': parsed['status'], 'profit': parsed.get('profit'), 'balance_after': bal,
                            'method': 'order_query', 'raw': q}
        except Exception:
            pass

        time.sleep(poll_interval)
        bal = get_available_balance()
        if bal is None:
            continue

        if purchase_seen and (not early_loss_checked):
            elapsed_check = time.time() - start_check_ts
            if elapsed_check >= EARLY_LOSS_GUARD_SECONDS:
                early_loss_checked = True
                try:
                    if _early_loss_by_stable_balance(saldo_before, amount):
                        bal_now = get_available_balance()
                        profit = (bal_now - saldo_before) if (bal_now is not None) else None
                        return {'result': 'loss', 'profit': profit, 'balance_after': bal_now,
                                'method': 'early_loss_stable_balance', 'raw': None}
                except Exception:
                    pass

        if purchase_seen:
            delta_post = bal - expected_post_purchase
            if delta_post > profit_threshold:
                profit = bal - saldo_before
                return {'result': 'win', 'profit': profit, 'balance_after': bal, 'method': 'balance_poll', 'raw': None}

            if bal < expected_post_purchase - eps_small:
                profit = bal - saldo_before
                return {'result': 'loss', 'profit': profit, 'balance_after': bal, 'method': 'balance_poll', 'raw': None}

            remaining = deadline - time.time()
            if remaining <= 2.0:
                if not extended_wait_used:
                    deadline += EXTRA_WAIT_SECONDS
                    extended_wait_used = True
                    continue
                else:
                    bal_now = get_available_balance() or last_bal
                    profit = bal_now - saldo_before
                    return {'result': 'win' if profit > 0 else ('loss' if profit < 0 else 'unknown'),
                            'profit': profit, 'balance_after': bal_now, 'method': 'timeout_estimated', 'raw': None}
        else:
            delta = bal - saldo_before
            if delta > profit_threshold:
                return {'result': 'win', 'profit': delta, 'balance_after': bal, 'method': 'balance_poll', 'raw': None}
            if delta < - (amount or 0.0) + eps_small:
                purchase_seen = True
                expected_post_purchase = bal
                last_bal = bal
                continue

        last_bal = bal

    profit = last_bal - (saldo_before or 0.0)
    return {'result': 'win' if profit > 0 else ('loss' if profit < 0 else 'unknown'),
            'profit': profit, 'balance_after': last_bal, 'method': 'timeout_estimated', 'raw': None}


# =========================
# Buy
# =========================
def resolve_trade_variant(ativo: str, ativo_chave: str, use_otc: bool = False) -> Tuple[str, str]:
    """Antes de cada entrada, re-verifica qual mercado usar.

    PRIORIZA DIGITAL: verifica se existe variante digital aberta para o ativo.
    Se digital estiver aberto → retorna (nome_digital, 'digital').
    Se digital estiver fechado → retorna a variante binária/original.
    Chama a API a cada invocação (não usa cache) para garantir status atualizado.

    use_otc: passa o modo global de OTC — tem precedência sobre o sufixo do ativo.
    Se use_otc=False (mercado aberto), NUNCA permite variante -OTC mesmo que o
    ativo original não tenha sufixo, evitando troca silenciosa por OTC.
    """
    if not PREFER_DIGITAL:
        return ativo, ativo_chave
    ot = _safe_get_all_open_time()
    if ot is None:
        return ativo, ativo_chave
    try:
        # Normalizar base do ativo: usa _strip_market_suffix para lidar corretamente
        # com sufixos combinados como '-OTC-OP' (ex.: 'BTCUSD-OTC-op' da IQ Option).
        base = _strip_market_suffix(_normalize_asset_name(ativo))
        # use_otc global tem precedência: só permite OTC se explicitamente habilitado
        allow_otc = use_otc
        # Tentar digital primeiro
        digital_table = ot.get('digital', {})
        if isinstance(digital_table, dict):
            for name, info in digital_table.items():
                if not (isinstance(info, dict) and info.get('open')):
                    continue
                # Nunca selecionar OTC se não foi explicitamente configurado
                if 'OTC' in str(name).upper() and not allow_otc:
                    continue
                name_norm = _normalize_asset_name(str(name))
                name_base = _strip_market_suffix(name_norm)
                if name_base == base or name_norm == _normalize_asset_name(ativo):
                    return str(name), 'digital'
        # Digital fechado: verificar se binária ainda está aberta
        if _is_open(ot, ativo_chave, ativo):
            return ativo, ativo_chave
        # Tentar outra variante binária
        new_name, new_cat = find_preferred_variant_with_rules(base, allow_otc=allow_otc)
        if new_name and new_cat:
            return new_name, new_cat
    except Exception as exc:
        _log_error("Erro em resolve_trade_variant", exc)
    return ativo, ativo_chave


def _do_buy_minimal(amount, ativo, direction, expiration, ativo_chave: str = 'binary'):
    """Executa compra usando digital (buy_digital_spot_v2) ou binária (buy) conforme ativo_chave."""
    t0 = time.perf_counter()
    try:
        if ativo_chave == 'digital' and PREFER_DIGITAL:
            status, info = API.buy_digital_spot_v2(ativo, amount, direction, expiration)
        else:
            status, info = API.buy(amount, ativo, direction, expiration)
    except Exception as e:
        status, info = False, e
    t1 = time.perf_counter()
    delta = t1 - t0

    global BUY_LATENCY_AVG
    BUY_LATENCY_AVG = BUY_LATENCY_ALPHA * delta + (1.0 - BUY_LATENCY_ALPHA) * BUY_LATENCY_AVG
    try:
        if LATENCY_CSV is not None:
            with LATENCY_CSV.open('a', newline='', encoding='utf-8') as f:
                csv.writer(f).writerow([now_iso(), INSTANCE_TAG, f"{delta:.6f}", f"{BUY_LATENCY_AVG:.6f}", "buy"])
    except Exception:
        pass

    return status, info


def _buy_worker(direction, ativo, amount, expiration, result_container, event, ativo_chave: str = 'binary'):
    status, info = _do_buy_minimal(amount, ativo, direction, expiration, ativo_chave)
    result_container["res"] = {"success": bool(status), "order_id": info if status else None, "info": info}
    event.set()


# =========================
# Rigidez
# =========================
def _apply_rigidez():
    """Estratégia única: PRIORIDADE DIGITAL — parâmetros ajustáveis no topo do script.

    RIGIDEZ_MODE = "normal" → usa os parâmetros definidos no bloco de ajuste fino acima.
    RIGIDEZ_MODE = "rigida" → aplica multiplicadores M5 (uso avançado / backtesting).
    Perfil M1 único: parâmetros "livres" definidos no bloco centralizados no topo.
    Para experimentar variações, edite diretamente os valores no bloco
    "ESTRATÉGIA: PRIORIDADE DIGITAL — AJUSTE FINO AQUI" no início deste arquivo.
    """
    global ADX_MIN_M1, ADX_MIN_M5, BB_WIDTH_MIN_M1, BB_WIDTH_MIN_M5, SLOPE_MIN_M1, SLOPE_MIN_M5
    global ENTRY_WINDOW_SECONDS_M1, ENTRY_WINDOW_SECONDS_M5
    global ATR_ADAPTIVE_FACTOR
    if RIGIDEZ_MODE != "rigida":
        return  # Estratégia normal: parâmetros já definidos no bloco de ajuste fino
    # Modo rígido M5 (opcional/avançado — raramente usado no fluxo principal)
    ADX_MIN_M5 += 2.0
    BB_WIDTH_MIN_M5 *= 1.20
    SLOPE_MIN_M5 *= 1.25
    ENTRY_WINDOW_SECONDS_M5 = min(ENTRY_WINDOW_SECONDS_M5, 25)
    ATR_ADAPTIVE_FACTOR = max(ATR_ADAPTIVE_FACTOR, 0.85)
    if TIMEFRAME_MINUTES != 1:
        ADX_MIN_M1 += 2.0
        BB_WIDTH_MIN_M1 *= 1.20
        SLOPE_MIN_M1 *= 1.25
        ENTRY_WINDOW_SECONDS_M1 = min(ENTRY_WINDOW_SECONDS_M1, 6)


# =========================
# Menus
# =========================
def ask_yes_no(prompt):
    while True:
        r = input(prompt + " (s/n): ").strip().lower()
        if r in ('s', 'n'):
            return r == 's'


# =========================
# ATIVOS / LISTA DE ATIVOS (Ativos.txt)
# =========================
def load_ativos_por_categoria(tf_min: int) -> Tuple[List[str], List[str]]:
    """Lê Ativos.txt e retorna (lista_digital, lista_binaria) para o timeframe tf_min.

    Formato esperado:
        [DIGITAL M1]
        EURUSD-OP
        EURJPY-OP
        EURGBP-OTC

        [BINARIA M1]
        EURUSD-OP
        ...

    tf_min: 1 para M1, 5 para M5, 15 para M15, etc.
    Linhas vazias e linhas com # são ignoradas.
    -OP e -OTC podem ser misturados em qualquer seção.

    Retorna ([], []) se o arquivo não existir, se ocorrer erro na leitura,
    ou se não houver seções correspondentes ao tf_min informado.
    """
    tf_label = f"M{tf_min}"
    digital_section = f"DIGITAL {tf_label}"
    binaria_section = f"BINARIA {tf_label}"

    digital: List[str] = []
    binaria: List[str] = []
    current_section: Optional[str] = None

    try:
        if ATIVOS_FILE.exists():
            with ATIVOS_FILE.open('r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if line.startswith('[') and line.endswith(']'):
                        section = line[1:-1].upper().strip()
                        if section == digital_section:
                            current_section = 'digital'
                        elif section == binaria_section:
                            current_section = 'binaria'
                        else:
                            current_section = None
                        continue
                    if current_section == 'digital':
                        digital.append(_normalize_asset_name(line))
                    elif current_section == 'binaria':
                        binaria.append(_normalize_asset_name(line))
    except Exception:
        pass

    return digital, binaria


def build_asset_list(use_otc: bool, max_count: int, tf_min: int = 0,
                     allow_open_market: bool = False) -> List[Tuple[str, str]]:
    """Monta lista de (ativo, categoria) baseada exclusivamente no Ativos.txt.

    Lógica:
    1. Lê seções [DIGITAL Mx] e [BINARIA Mx] do Ativos.txt para o timeframe escolhido.
    2. Prioriza ativos da seção DIGITAL que estejam abertos na IQ Option.
    3. Completa slots restantes com ativos da seção BINARIA abertos (fallback).
    4. Nunca inclui ativo que não esteja no Ativos.txt.
    5. Nunca duplica: cada ativo aparece apenas uma vez (digital preferido).

    Retorna lista vazia se nenhum ativo da lista estiver aberto — o chamador
    deve exibir aviso e aguardar.

    Parâmetro tf_min: 1=M1, 5=M5. Se 0, usa M1 como padrão para leitura do arquivo
    (o filtro de timeframe da API ainda é desativado quando tf_min=0).

    Parâmetro allow_open_market: quando True, inclui ativos de mercado aberto (-OP /
    sem sufixo) mesmo que use_otc=True, permitindo pool misto OTC + mercado aberto.
    Quando use_otc=False e allow_open_market=False, nenhum ativo passa (pool vazio).
    """
    ot = _safe_get_all_open_time()
    if ot is None:
        return []

    _tf = tf_min if tf_min > 0 else 1
    digital_lista, binaria_lista = load_ativos_por_categoria(_tf)

    def _has_no_market_suffix(name_u: str) -> bool:
        return '-OTC' not in name_u and '-OP' not in name_u

    def _is_open_market_index(name_u: str) -> bool:
        """Retorna True se name_u é um símbolo de índice sem sufixo tratado como mercado aberto.

        Símbolos como JXY, EXY, BXY, CXY, AXY, DXY não possuem sufixo -OP mas devem
        ser elegíveis apenas nos perfis OPEN e MISTO (nunca no perfil OTC-only).
        A checagem é feita pelo nome raiz (sem sufixo), pois esses ativos aparecem
        exatamente com esses nomes na tabela de ativos da IQ Option.
        """
        # Extrai nome base removendo sufixos conhecidos para comparação
        base = name_u.replace('-OTC', '').replace('-OP', '').strip()
        return base in OPEN_MARKET_INDEX_SYMBOLS

    def _passes_market_filter(name_u: str) -> bool:
        if use_otc and allow_open_market:
            # Pool misto: aceita tudo (OTC, -OP e sem sufixo incluindo índices)
            return True
        elif use_otc:
            # OTC-only: aceita OTC e sem sufixo, MAS exclui índices de mercado aberto
            # _is_open_market_index() strip suffixes internally, so no redundant suffix check needed
            if _is_open_market_index(name_u):
                return False
            return '-OTC' in name_u or _has_no_market_suffix(name_u)
        elif allow_open_market:
            return ('-OP' in name_u or _has_no_market_suffix(name_u)) and '-OTC' not in name_u
        else:
            return False

    # Constrói mapa de ativos abertos: normalized_name → (real_name, categoria)
    # Digital tem prioridade; binária entra apenas se não houver digital equivalente.
    # Dois índices são mantidos:
    #   open_map         — chave = nome normalizado completo (ex.: 'BTCUSD-OTC-OP')
    #   open_map_by_base — chave = nome base sem sufixo  (ex.: 'BTCUSD')
    # O segundo índice permite lookup fuzzy quando o nome no Ativos.txt e o nome
    # real da API diferem apenas no sufixo (ex.: 'BTCUSD-OTC' vs 'BTCUSD-OTC-op').
    open_map: Dict[str, Tuple[str, str]] = {}
    open_map_by_base: Dict[str, Tuple[str, str]] = {}

    digital_table = ot.get('digital', {})
    if isinstance(digital_table, dict):
        for name, info in digital_table.items():
            if not (isinstance(info, dict) and info.get('open')):
                continue
            if tf_min > 0 and not _asset_accepts_tf(info, tf_min):
                continue
            name_u = str(name).upper()
            if not _passes_market_filter(name_u):
                continue
            norm = _normalize_asset_name(name)
            if norm not in open_map:
                open_map[norm] = (name, 'digital')
            base = _strip_market_suffix(norm)
            if base not in open_map_by_base:
                open_map_by_base[base] = (name, 'digital')

    binary_table = ot.get('binary', {})
    if isinstance(binary_table, dict):
        for name, info in binary_table.items():
            if not (isinstance(info, dict) and info.get('open')):
                continue
            if tf_min > 0 and not _asset_accepts_tf(info, tf_min):
                continue
            name_u = str(name).upper()
            if not _passes_market_filter(name_u):
                continue
            norm = _normalize_asset_name(name)
            if norm not in open_map:  # digital já tem prioridade
                open_map[norm] = (name, 'binary')
            base = _strip_market_suffix(norm)
            if base not in open_map_by_base:  # digital já tem prioridade
                open_map_by_base[base] = (name, 'binary')

    result: List[Tuple[str, str]] = []
    used: set = set()

    # Detecta ativos que estão em Ativos.txt mas foram filtrados pelo mercado.
    # Emite log em blocked_reasons quando m5_allow_otc=false ou m5_allow_open_market=false.
    def _market_filter_skip_reason(name_u: str) -> Optional[str]:
        """Retorna razão de skip por filtro de mercado, ou None se não filtrado.

        Casos tratados:
        - Ativo -OTC quando m5_allow_otc=false → "m5_allow_otc=false"
        - Ativo -OP quando m5_allow_open_market=false → "m5_allow_open_market=false"
        - Índice de mercado aberto (JXY, EXY…) em modo OTC-only → "m5_allow_open_market=false(index)"
        - Ativo sem sufixo quando ambos disabled → "m5_allow_otc=false+m5_allow_open_market=false"
        - Pool misto (ambos=true) → None (nada filtrado)
        """
        if use_otc and allow_open_market:
            return None  # pool misto — nada é filtrado por mercado
        if '-OTC' in name_u and not use_otc:
            return "m5_allow_otc=false"
        if '-OP' in name_u and not allow_open_market:
            return "m5_allow_open_market=false"
        # _is_open_market_index() strips suffixes internally, so no redundant check needed
        if _is_open_market_index(name_u) and use_otc and not allow_open_market:
            return "m5_allow_open_market=false(index)"
        if _has_no_market_suffix(name_u) and not use_otc and not allow_open_market:
            return "m5_allow_otc=false+m5_allow_open_market=false"
        return None

    def _lookup_open_map(norm_name: str) -> Optional[Tuple[str, str]]:
        """Busca ativo no open_map com fallback fuzzy por nome base.

        1ª tentativa: lookup exato por nome normalizado completo.
        2ª tentativa (fuzzy): strip de sufixos de ambos os lados e compara raiz.
          Ex.: 'BTCUSD-OTC' (Ativos.txt) → base 'BTCUSD' → encontra 'BTCUSD-OTC-op' (API).

        Retorna (real_name, categoria) ou None se não encontrado.
        """
        entry = open_map.get(norm_name)
        if entry is not None:
            return entry
        # Fallback: comparar por nome base sem sufixo
        base = _strip_market_suffix(norm_name)
        if base:
            entry = open_map_by_base.get(base)
            if entry is not None:
                return entry
        return None

    def _diag_not_found(norm_name: str, source: str) -> None:
        """Loga diagnóstico quando ativo do Ativos.txt não é encontrado no pool aberto.

        Verifica se o ativo existe na tabela de ativos abertos (sem filtro de mercado)
        e informa o motivo pelo qual foi rejeitado: filtro de mercado, fechado, ou
        simplesmente ausente da resposta da API.
        """
        # Busca o ativo na tabela completa (sem filtro de mercado) para diagnóstico
        found_raw: Optional[str] = None
        found_table: Optional[str] = None
        for table_key in ('digital', 'binary'):
            table = ot.get(table_key, {})
            if not isinstance(table, dict):
                continue
            for raw_name, info in table.items():
                raw_norm = _normalize_asset_name(raw_name)
                raw_base = _strip_market_suffix(raw_norm)
                if raw_norm == norm_name or raw_base == _strip_market_suffix(norm_name):
                    found_raw = raw_name
                    found_table = table_key
                    reason = _market_filter_skip_reason(str(raw_name).upper())
                    is_open = isinstance(info, dict) and bool(info.get('open'))
                    if not is_open:
                        _log_blocked(
                            "asset_closed_on_api",
                            f"ativo={display_asset_name(raw_name)} "
                            f"norm={norm_name} src={source} tf={tf_min}",
                        )
                    elif reason:
                        _log_blocked(
                            f"market_filter_skip [{reason}]",
                            f"ativo={display_asset_name(raw_name)} "
                            f"norm={norm_name} src={source} tf={tf_min}",
                        )
                    else:
                        _log_blocked(
                            "asset_open_but_not_matched",
                            f"ativo={display_asset_name(raw_name)} "
                            f"norm_api={raw_norm} norm_list={norm_name} "
                            f"table={table_key} src={source} tf={tf_min}",
                        )
                    break
            if found_raw:
                break
        if found_raw is None:
            _log_blocked(
                "asset_not_in_api_response",
                f"norm={norm_name} src={source} tf={tf_min} "
                f"(ausente em digital+binary da API)",
            )

    # 1ª passagem: ativos da lista DIGITAL do Ativos.txt que estejam abertos
    for norm_name in digital_lista:
        if len(result) >= max_count:
            break
        entry = _lookup_open_map(norm_name)
        if entry is None:
            _diag_not_found(norm_name, source='DIGITAL')
            continue
        real_name, cat = entry
        if real_name.upper() in used:
            continue
        result.append((real_name, cat))
        used.add(real_name.upper())

    # 2ª passagem: completa com ativos da lista BINARIA do Ativos.txt (apenas se faltar)
    for norm_name in binaria_lista:
        if len(result) >= max_count:
            break
        entry = _lookup_open_map(norm_name)
        if entry is None:
            _diag_not_found(norm_name, source='BINARIA')
            continue
        real_name, cat = entry
        if real_name.upper() in used:
            continue
        result.append((real_name, cat))
        used.add(real_name.upper())

    return result


def _donchian_range_ratio_m5(ativo: str, period: int) -> Optional[float]:
    """Calcula Donchian range ratio para detecção de mercado morto no M5.

    Retorna (max_high - min_low) / mid_price nos últimos `period` candles M5.
    Útil para identificar ativos com range muito comprimido ("mercado morto").
    Retorna None quando não há dados suficientes (sem penalidade nesse caso).
    """
    try:
        velas = get_candles_safe(ativo, 5 * 60, period + 3)
        if not velas or len(velas) < period:
            return None
        recent = velas[-period:]
        highs = [float(v['max']) for v in recent]
        lows = [float(v['min']) for v in recent]
        upper = max(highs)
        lower = min(lows)
        mid = (upper + lower) / 2
        if mid == 0:
            return None
        return (upper - lower) / mid
    except Exception:
        return None


def build_candidate_pool(use_otc: bool, limit: int = 200, tf_min: int = 0,
                         allow_open_market: bool = False) -> List[Tuple[str, str]]:
    """Retorna todos os candidatos disponíveis exclusivamente do Ativos.txt.

    Igual a build_asset_list mas com limite generoso para varredura dinâmica.
    Filtra por tf_min quando fornecido — garante que apenas ativos com o
    timeframe correto (M1/M5) entrem no pool de candidatos.
    Só inclui ativos listados no Ativos.txt que estejam abertos no momento.
    allow_open_market: quando True (e use_otc=True), inclui também ativos de
    mercado aberto no pool, resultando em seleção mista OTC + mercado aberto.
    """
    return build_asset_list(use_otc=use_otc, max_count=limit, tf_min=tf_min,
                            allow_open_market=allow_open_market)


def rank_assets_by_regime(
    candidates: List[Tuple[str, str]],
    tf_min: int,
    top_n: int = 4,
) -> List[Tuple[str, str]]:
    """Ranqueia ativos por qualidade de regime (ATR + ADX + BBW) e retorna os top_n.

    Usado no M1 para selecionar dinamicamente os ativos mais promissores a cada
    ciclo de re-ranking, reduzindo tempo gasto em ativos laterais/comprimidos.

    Estratégia de pontuação (normalizado pelo mínimo exigido):
      score = atr_ratio/ATR_MIN + adx/ADX_MIN + bbw/BB_MIN
    Quanto maior o score, melhor o regime do ativo naquele momento.
    """
    scored: List[Tuple[float, str, str]] = []
    for ativo, cat in candidates:
        try:
            period = tf_min * 60
            # Busca poucos candles para ranking rápido (não precisa de lookback completo)
            velas = get_candles_safe(ativo, period, 30)
            if not velas or len(velas) < 20:
                scored.append((0.0, ativo, cat))
                continue

            closes = [float(v["close"]) for v in velas]
            if not closes:
                scored.append((0.0, ativo, cat))
                continue

            atr = calculate_atr_from_candles(velas, periodo=ATR_PERIOD)
            mean_close = (sum(closes[-ATR_PERIOD:]) / ATR_PERIOD
                          if len(closes) >= ATR_PERIOD else closes[-1])
            atr_score = (atr / mean_close / max(ATR_MIN_RATIO_ABS_M1, 1e-12)
                         if (atr and mean_close > 0) else 0.0)

            adx = adx_from_candles(velas, period=ADX_PERIOD) or 0.0
            adx_score = adx / max(ADX_MIN_M1, 1e-3)

            bbw = bb_width_norm(closes, period=BB_PERIOD, std_mult=BB_STD) or 0.0
            bbw_score = bbw / max(BB_WIDTH_MIN_M1, 1e-12)

            score = atr_score + adx_score + bbw_score
            scored.append((score, ativo, cat))
        except Exception:
            scored.append((0.0, ativo, cat))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [(ativo, cat) for _, ativo, cat in scored[:top_n]]


def ask_market_type() -> bool:
    """Pergunta tipo de mercado. Retorna True para OTC, False para Mercado Aberto (-OP)."""
    print("\n" + "=" * 70)
    print("🌍 TIPO DE MERCADO")
    print("=" * 70)
    print("  1) Mercado Aberto  (ativos -OP)")
    print("  2) OTC")
    while True:
        r = input("\n👉 Digite 1 ou 2 [1]: ").strip() or "1"
        if r == "1":
            return False
        if r == "2":
            return True
        print("❌ Opção inválida!")


def _load_market_profile(profile_name: str) -> None:
    """Aplica perfil de mercado (OTC, OPEN ou MISTO) lido do config.txt.

    Atualiza os globals M5_ALLOW_OTC, M5_ALLOW_OPEN_MARKET e os thresholds
    de regime M5 (ADX_MIN_M5, ATR_MIN_RATIO_ABS_M5, BB_WIDTH_MIN_M5,
    SLOPE_MIN_M5, ENTRY_WINDOW_SECONDS_M5) com os valores da seção
    [PROFILE_OTC], [PROFILE_OPEN] ou [PROFILE_MISTO] do config.txt.

    Retorna silenciosamente sem alterar nada se a seção não existir.
    """
    global M5_ALLOW_OTC, M5_ALLOW_OPEN_MARKET
    global ADX_MIN_M5, ATR_MIN_RATIO_ABS_M5, BB_WIDTH_MIN_M5, SLOPE_MIN_M5
    global ENTRY_WINDOW_SECONDS_M5

    key_map = {
        'OTC':   'PROFILE_OTC',
        'OPEN':  'PROFILE_OPEN',
        'MISTO': 'PROFILE_MISTO',
    }
    section = key_map.get(profile_name.upper())
    if section is None or config.get(section) is None:
        return

    M5_ALLOW_OTC = _cfgbool(section, 'm5_allow_otc', M5_ALLOW_OTC)
    M5_ALLOW_OPEN_MARKET = _cfgbool(section, 'm5_allow_open_market', M5_ALLOW_OPEN_MARKET)
    ADX_MIN_M5 = _cfgget(section, 'adx_min', ADX_MIN_M5, float)
    ATR_MIN_RATIO_ABS_M5 = _cfgget(section, 'atr_min_ratio', ATR_MIN_RATIO_ABS_M5, float)
    BB_WIDTH_MIN_M5 = _cfgget(section, 'bb_width_min', BB_WIDTH_MIN_M5, float)
    SLOPE_MIN_M5 = _cfgget(section, 'slope_min', SLOPE_MIN_M5, float)
    ENTRY_WINDOW_SECONDS_M5 = _cfgget(section, 'entry_window_seconds', ENTRY_WINDOW_SECONDS_M5, int)


def ask_market_profile_m5() -> Tuple[bool, bool, str]:
    """Menu interativo de seleção de perfil de mercado para M5.

    Retorna (use_otc, allow_open_market, profile_name) e aplica o perfil
    correspondente carregando os thresholds de [PROFILE_OTC/OPEN/MISTO]
    do config.txt.

    Perfis disponíveis:
      1) OTC   — apenas ativos OTC; thresholds calibrados para OTC.
      2) OPEN  — apenas Mercado Aberto (-OP); thresholds calibrados.
      3) MISTO — OTC + Mercado Aberto; thresholds intermediários (legado).
    """
    print("\n" + "=" * 70)
    print("🌍 PERFIL DE MERCADO M5")
    print("=" * 70)
    print("  1) " + ccyan("OTC")   + "   — apenas ativos OTC (24/7)")
    print("  2) " + cyellow("OPEN") + "  — apenas Mercado Aberto (ativos -OP)")
    print("  3) " + cbold("MISTO") + "  — OTC + Mercado Aberto (pool misto)")
    print()
    print("  Cada perfil carrega thresholds de ATR/ADX/slope/janela")
    print("  calibrados para aquele tipo de mercado.")

    while True:
        r = input("\n👉 Digite 1, 2 ou 3 [1]: ").strip() or "1"
        if r == "1":
            profile = "OTC"
            use_otc, allow_open_market = True, False
            break
        if r == "2":
            profile = "OPEN"
            use_otc, allow_open_market = False, True
            break
        if r == "3":
            profile = "MISTO"
            use_otc, allow_open_market = True, True
            break
        print("❌ Opção inválida! Digite 1, 2 ou 3.")

    _load_market_profile(profile)
    print(f"✅ Perfil {cbold(profile)} aplicado.")
    return use_otc, allow_open_market, profile


def _get_asset_payout(ativo: str, ot: Dict[str, Any]) -> float:
    """Retorna o payout estimado do ativo (0.0–1.0) para fins de ranking.

    Tenta, em ordem:
    1. API.get_all_profit() → profit_percentage (digital preferred).
    2. Fallback: payout padrão de 0.80 (80%) quando não é possível obter.

    Retorna valor entre 0.0 e 1.0 (e.g. 0.82 = 82% payout).
    """
    try:
        profits = API.get_all_profit()
        if isinstance(profits, dict):
            norm = _normalize_asset_name(ativo)
            for cat in ('digital', 'binary', 'turbo'):
                cat_data = profits.get(cat, {})
                if not isinstance(cat_data, dict):
                    continue
                for k, v in cat_data.items():
                    if _normalize_asset_name(k) == norm:
                        if isinstance(v, dict):
                            p = v.get('1min') or v.get('5min') or v.get('profit') or next(iter(v.values()), None)
                        else:
                            p = v
                        try:
                            pf = float(p)
                            if pf > 1.0:
                                pf /= 100.0
                            return max(0.0, min(1.0, pf))
                        except Exception:
                            pass
    except Exception:
        pass
    return 0.80  # Fallback: 80% é o payout típico IQ Option para digital OTC/Open.
                 # Usado quando API.get_all_profit() falha ou não retorna o ativo.


def _startup_rank_m5_pool(
    candidates: List[Tuple[str, str]],
    pool_size: int,
) -> List[Tuple[str, str]]:
    """Seleciona o pool inicial M5 por ranking: payout + saúde ATR/ADX.

    Para cada candidato elegível (aberto, mercado correto):
      - Busca payout (digital preferido, binary fallback).
      - Computa score de regime M5: ATR_ratio/ATR_MIN + ADX/ADX_MIN + BBW/BB_MIN.
      - Score final = 0.4 * regime_score_normalizado + 0.6 * payout_score.
    Seleciona os top `pool_size` ativos pelo score final (determinístico).
    Loga breakdown completo no console e em STARTUP_RANKING_LOG (se configurado).

    Retorna lista de (ativo, categoria) dos top-N selecionados.
    Se candidates estiver vazio, retorna lista vazia (o loop tratará o pool vazio).
    """
    if not candidates:
        return []

    print(f"\n📊 [STARTUP RANKING M5] Avaliando {len(candidates)} candidatos "
          f"(pool_size={pool_size})...")

    ot = _safe_get_all_open_time() or {}

    scored: List[Tuple[float, str, str, str]] = []  # (score, ativo, cat, breakdown)

    for ativo, cat in candidates:
        try:
            velas = get_candles_safe(ativo, 5 * 60, 30)
            has_candles = bool(velas and len(velas) >= 15)

            if has_candles:
                closes = [float(v["close"]) for v in velas]
                atr = calculate_atr_from_candles(velas, periodo=ATR_PERIOD) or 0.0
                mean_close = (sum(closes[-ATR_PERIOD:]) / ATR_PERIOD
                              if len(closes) >= ATR_PERIOD else (closes[-1] if closes else 1.0))
                atr_ratio = atr / mean_close if mean_close > 0 else 0.0
                atr_norm = atr_ratio / max(ATR_MIN_RATIO_ABS_M5, 1e-12)

                adx = adx_from_candles(velas, period=ADX_PERIOD) or 0.0
                adx_norm = adx / max(ADX_MIN_M5, 1e-3)

                bbw = bb_width_norm(closes, period=BB_PERIOD, std_mult=BB_STD) or 0.0
                bbw_norm = bbw / max(BB_WIDTH_MIN_M5, 1e-12)

                regime_score = atr_norm + adx_norm + bbw_norm
            else:
                atr_ratio = adx = bbw = 0.0
                atr_norm = adx_norm = bbw_norm = regime_score = 0.0

            payout = _get_asset_payout(ativo, ot)
            # Regime score: sum of 3 normalized components (ATR, ADX, BBW), each ≥1.0
            # when at or above threshold. Cap at 2.0 to bound contribution and prevent
            # a single outlier asset from dominating purely on regime without payout.
            # Divide by 3.0 to map [0..3] → [0..1] before applying the 2.0 cap.
            regime_norm = min(regime_score / 3.0, 2.0)
            # Score formula: regime contributes 40%, payout contributes 60%.
            # Payout weight is higher because a low payout directly reduces expected
            # value regardless of regime quality, while regime is already pre-filtered
            # by ADX/ATR thresholds during signal generation.
            _REGIME_WEIGHT = 0.4
            _PAYOUT_WEIGHT = 0.6
            final_score = _REGIME_WEIGHT * regime_norm + _PAYOUT_WEIGHT * payout

            breakdown = (
                f"score={final_score:.3f} payout={payout:.0%} "
                f"atr={atr_norm:.2f}x adx={adx:.1f}({adx_norm:.2f}x) "
                f"bbw={bbw_norm:.2f}x regime={regime_norm:.3f}"
            )
            scored.append((final_score, ativo, cat, breakdown))
        except Exception as exc:
            scored.append((0.0, ativo, cat, f"erro={exc}"))

    scored.sort(key=lambda x: x[0], reverse=True)

    print(f"  {'Pos':>3}  {'Ativo':<20} {'Score':>7}  Detalhes")
    print(f"  {'---':>3}  {'-'*20} {'-------':>7}  -------")
    for i, (sc, av, ct, bd) in enumerate(scored):
        marker = " ✅" if i < pool_size else ""
        print(f"  {i+1:>3}  {display_asset_name(av):<20} {sc:>7.3f}  {bd}{marker}")

    selected = [(av, ct) for _, av, ct, _ in scored[:pool_size]]
    selected_names = ", ".join(display_asset_name(a) for a, _ in selected)
    print(f"\n  🎯 Pool inicial selecionado: {selected_names}")

    if POOL_REBALANCE_LOG_M5 is not None:
        try:
            with POOL_REBALANCE_LOG_M5.open('a', encoding='utf-8') as f:
                f.write(f"\n{datetime.now().isoformat()} | {INSTANCE_TAG} | "
                        f"[STARTUP RANKING M5] candidatos={len(candidates)} pool={pool_size}\n")
                for i, (sc, av, ct, bd) in enumerate(scored):
                    mark = " SELECTED" if i < pool_size else ""
                    f.write(f"  {i+1:>3}. {display_asset_name(av)} {bd}{mark}\n")
        except Exception:
            pass

    return selected


def ask_num_assets(tf_min: int = 5) -> int:
    """Pergunta quantos ativos operar simultaneamente, respeitando o cap por TF.

    Limites configuráveis (config.txt [M1].max_assets / [M5].max_assets):
    - M1 → máximo 2 ativos (janela curta; menos é mais preciso)
    - M5 → máximo 4 ativos (janela maior permite monitorar mais ativos)
    """
    max_cap = MAX_ASSETS_M1 if tf_min == 1 else MAX_ASSETS_M5
    suggested = max_cap
    print("\n" + "=" * 70)
    print("📊 NÚMERO DE ATIVOS SIMULTÂNEOS")
    print("=" * 70)
    print(f"  Escolha quantos ativos operar ao mesmo tempo (1 a {max_cap}).")
    if tf_min == 1:
        print(cyellow(f"  💡 M1: máximo {max_cap} ativo(s) — janela de entrada curta."))
    else:
        print(ccyan(f"  💡 M5: máximo {max_cap} ativo(s) — janela de entrada maior."))
    while True:
        r = input(f"\n👉 Digite um número de 1 a {max_cap} [{suggested}]: ").strip() or str(suggested)
        try:
            n = int(r)
            if 1 <= n <= max_cap:
                return n
            print(cyellow(f"❌ Máximo permitido para M{tf_min} é {max_cap} ativo(s). Tente novamente."))
        except Exception:
            print("❌ Digite um número inteiro válido.")


def ask_time_hhmm(prompt):
    while True:
        raw = input(prompt + " (HH:MM): ").strip()
        try:
            hh, mm = map(int, raw.split(':'))
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                return hh, mm
        except Exception:
            pass


def round_up_to_next_period(ts_seconds: int, period_minutes: int) -> int:
    period = period_minutes * 60
    remainder = ts_seconds % period
    if remainder == 0:
        return ts_seconds
    return ts_seconds + (period - remainder)


def ask_timeframe():
    print("\n" + "=" * 70)
    print("⏱️  TIMEFRAME")
    print("=" * 70)
    print("  1) M1")
    print("  2) M5")
    while True:
        r = input("\n👉 Digite 1 ou 2 [1]: ").strip() or "1"
        if r == "1":
            return 1
        if r == "2":
            return 5


def ask_entry_mode():
    print("\n" + "=" * 70)
    print("🧠 MODO DE ENTRADA")
    print("=" * 70)
    print("  1) REVERSÃO     ✅ Motor V15 (RSI+BB+Wick+Keltner — padrão)")
    print("  2) CONTINUAÇÃO  ✅ Respiro (impulso → pullback → entrada na continuação)")
    print()
    print("  Nota: o modo padrão também pode ser definido em config.txt")
    print("        em [M1].entry_mode / [M5].entry_mode")
    while True:
        r = input("\n👉 Digite 1 ou 2 [1]: ").strip() or "1"
        if r == "1":
            return "reversal"
        if r == "2":
            print("  ℹ️  Modo CONTINUAÇÃO (Respiro) selecionado.")
            print("     Ative também respiro_enable = true no config.txt [M1]/[M5].")
            return "continuation"
        print("❌ Opção inválida! Digite 1 ou 2.")


def ask_rigidez():
    print("\n" + "=" * 70)
    print("🧱 RIGIDEZ DAS ENTRADAS")
    print("=" * 70)
    print("  1) Normal")
    print("  2) Rígida")
    while True:
        r = input("\n👉 Digite 1 ou 2 [1]: ").strip() or "1"
        if r == "1":
            return "normal"
        if r == "2":
            return "rigida"


def ask_amount_menu():
    global AMOUNT_MODE, AMOUNT_FIXED, AMOUNT_PERCENT, AMOUNT_RECALC_EACH
    print("\n" + "=" * 70)
    print("💵 VALOR POR OPERAÇÃO")
    print("=" * 70)
    print("  1) Valor FIXO")
    print("  2) Percentual do SALDO")
    while True:
        modo = input("\n👉 Escolha 1 ou 2 [1]: ").strip() or "1"
        if modo not in ("1", "2"):
            print("❌ Opção inválida!")
            continue

        if modo == "1":
            AMOUNT_MODE = "fixed"
            while True:
                raw = input('\n💵 Valor fixo por operação: $').strip().replace(',', '.')
                try:
                    v = float(raw)
                    if v > 0:
                        AMOUNT_FIXED = v
                        break
                except Exception:
                    pass
                print("❌ Digite um número válido > 0")
            break

        AMOUNT_MODE = "percent"
        while True:
            raw = input('\n📊 Percentual do saldo (ex: 1 para 1%): ').strip().replace(',', '.')
            try:
                p = float(raw)
                if p > 0:
                    AMOUNT_PERCENT = p
                    break
            except Exception:
                pass
            print("❌ Digite um número válido > 0")

        AMOUNT_RECALC_EACH = ask_yes_no("👉 Recalcular percentual a cada operação?")
        if not AMOUNT_RECALC_EACH:
            bal_now = get_available_balance() or 0.0
            AMOUNT_FIXED = round(max(AMOUNT_MIN, bal_now * (AMOUNT_PERCENT / 100.0)), 2)
            print(f"✅ {AMOUNT_PERCENT}% do saldo atual = ${AMOUNT_FIXED:.2f} (fixado)")
        break


def ask_stop_loss_win():
    global STOP_LOSS_PCT, STOP_WIN_PCT
    print("\n" + "=" * 70)
    print("🛑 STOP LOSS")
    print("=" * 70)
    while True:
        raw = input('\n👉 Stop Loss em % (0 desativa) [0]: ').strip().replace(',', '.')
        if raw == '':
            STOP_LOSS_PCT = 0.0
            break
        try:
            STOP_LOSS_PCT = float(raw)
            if STOP_LOSS_PCT >= 0:
                break
        except Exception:
            pass
        print("❌ Valor inválido")

    print("\n" + "=" * 70)
    print("🎯 STOP WIN")
    print("=" * 70)
    while True:
        raw = input('\n👉 Stop Win em % (0 desativa) [0]: ').strip().replace(',', '.')
        if raw == '':
            STOP_WIN_PCT = 0.0
            break
        try:
            STOP_WIN_PCT = float(raw)
            if STOP_WIN_PCT >= 0:
                break
        except Exception:
            pass
        print("❌ Valor inválido")


def ask_run_duration() -> int:
    """Pergunta por quantos minutos o bot deve rodar (0 = ilimitado)."""
    print("\n" + "=" * 70)
    print("⏱️  TEMPORIZADOR DE FINALIZAÇÃO")
    print("=" * 70)
    print("  Defina por quantos minutos o bot deve operar.")
    print("  0 = sem limite (bot roda até ser interrompido manualmente).")
    while True:
        raw = input("\n👉 Minutos de operação (0 = ilimitado) [0]: ").strip() or "0"
        try:
            v = int(raw)
            if v >= 0:
                return v
        except Exception:
            pass
        print("❌ Digite um número inteiro >= 0.")


def ask_max_entries() -> int:
    """Pergunta quantas entradas aceitas o bot deve realizar (0 = ilimitado).

    O bot conta APENAS ordens que foram efetivamente aceitas pela IQ Option
    (com order_id confirmado). Para automaticamente ao atingir esse total.
    """
    print("\n" + "=" * 70)
    print("🎯 NÚMERO MÁXIMO DE ENTRADAS")
    print("=" * 70)
    print("  Define quantas ordens aceitas o bot deve executar.")
    print("  0 = ilimitado (opera até Stop Loss/Win ou interrupção manual).")
    print("  Apenas ordens confirmadas (com ID) são contadas.")
    while True:
        raw = input("\n👉 Número de entradas (0 = ilimitado) [0]: ").strip() or "0"
        try:
            v = int(raw)
            if v >= 0:
                return v
        except Exception:
            pass
        print("❌ Digite um número inteiro >= 0.")


# =========================
# Estado
# =========================
def load_state():
    try:
        _mkdirp(STATE_DIR)
        if STATE_PATH.exists():
            with STATE_PATH.open('r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_state(d):
    try:
        _mkdirp(STATE_DIR)
        with STATE_PATH.open('w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def choose_asset_interactive(start_ts: Optional[int]):
    """
    - Se agendado: aceita ativo fechado (se existir na lista da IQ, case-insensitive)
    - No horário: resolve automaticamente a variante aberta (-op etc)
    - OTC: só se você digitar -OTC
    """
    global PRESET_PATH

    scheduled = start_ts is not None
    state = load_state()

    while True:
        raw = input('\n👉 Digite o ativo (ex: EURJPY, EURJPY-OP ou EURJPY-OTC): ').strip()
        if not raw:
            print("❌ Nome inválido.")
            continue

        parsed = _parse_user_asset_input(raw)
        base = parsed["base"]
        suffix = parsed["suffix"]
        allow_otc = parsed["allow_otc"]

        if suffix == "OTC":
            alt_name, alt_ch = find_preferred_variant_with_rules(base, allow_otc=True)
            if alt_name:
                if "-OTC" not in str(alt_name).upper():
                    print(f"❌ Você digitou OTC, mas a alternativa encontrada não é OTC: {alt_name}. Escolha outro ativo.")
                    continue
                if (not ativo_aberto(alt_name, chave_preferida=alt_ch)) and (not scheduled):
                    print(f"❌ Ativo OTC está fechado agora: {alt_name}. (Sem agendamento não pode). Escolha outro.")
                    continue

                print(f"✅ Usando: {alt_name} ({alt_ch})")
                state.update({'last_asset': alt_name, 'last_asset_category': alt_ch, 'tipo': tipo})
                save_state(state)

                auto_tag = _auto_tag_from_choices(alt_name, TIMEFRAME_MINUTES, ENTRY_MODE, RIGIDEZ_MODE)
                _init_paths_with_tag(auto_tag)
                _ensure_csv_headers()

                filename = _preset_filename(alt_name, TIMEFRAME_MINUTES, ENTRY_MODE, RIGIDEZ_MODE)
                PRESET_PATH = PRESETS_DIR / filename
                preset = build_preset_dict(ativo=alt_name, ativo_chave=alt_ch, runtime_min=None)
                write_preset_file(PRESET_PATH, preset)

                return alt_name, alt_ch, {"base": base, "allow_otc": True}

            print(f"❌ Nenhuma variante OTC encontrada/aberta para '{base}'. Escolha outro ativo.")
            continue

        alt_name, alt_ch = find_preferred_variant_with_rules(base, allow_otc=False)
        if alt_name:
            print(f"✅ Usando: {alt_name} ({alt_ch})")
            state.update({'last_asset': alt_name, 'last_asset_category': alt_ch, 'tipo': tipo})
            save_state(state)

            auto_tag = _auto_tag_from_choices(alt_name, TIMEFRAME_MINUTES, ENTRY_MODE, RIGIDEZ_MODE)
            _init_paths_with_tag(auto_tag)
            _ensure_csv_headers()

            filename = _preset_filename(alt_name, TIMEFRAME_MINUTES, ENTRY_MODE, RIGIDEZ_MODE)
            PRESET_PATH = PRESETS_DIR / filename
            preset = build_preset_dict(ativo=alt_name, ativo_chave=alt_ch, runtime_min=None)
            write_preset_file(PRESET_PATH, preset)

            return alt_name, alt_ch, {"base": base, "allow_otc": False}

        if scheduled and ALLOW_CLOSED_ASSET_IF_SCHEDULED:
            if not is_asset_known_anywhere_case_insensitive(base):
                print(f"❌ Ativo '{base}' não existe na tabela do get_all_open_time(). Escolha outro.")
                continue

            preferred_cat = _categories_priority(tipo)[0]
            print(f"✅ Ativo aceito para agendamento (mesmo fechado agora): {base} ({preferred_cat})")

            state.update({'last_asset': base, 'last_asset_category': preferred_cat, 'tipo': tipo})
            save_state(state)

            auto_tag = _auto_tag_from_choices(base, TIMEFRAME_MINUTES, ENTRY_MODE, RIGIDEZ_MODE)
            _init_paths_with_tag(auto_tag)
            _ensure_csv_headers()

            filename = _preset_filename(base, TIMEFRAME_MINUTES, ENTRY_MODE, RIGIDEZ_MODE)
            PRESET_PATH = PRESETS_DIR / filename
            preset = build_preset_dict(ativo=base, ativo_chave=preferred_cat, runtime_min=None)
            write_preset_file(PRESET_PATH, preset)

            return base, preferred_cat, {"base": base, "allow_otc": False}

        print(f"❌ Nenhuma variante aberta encontrada para '{base}'. Tente outro ativo (ou agende o início).")


# =========================
# Guards: aguardar e resolver variante
# =========================
def _fmt_hms(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def resolve_open_asset_variant(base: str, allow_otc: bool) -> Tuple[Optional[str], Optional[str]]:
    return find_preferred_variant_with_rules(base, allow_otc=allow_otc)


def wait_until_asset_open_or_timeout(base: str, allow_otc: bool, timeout_seconds: int) -> Tuple[bool, Optional[str], Optional[str]]:
    t0 = time.time()
    last_print = 0.0
    while True:
        name, cat = resolve_open_asset_variant(base, allow_otc=allow_otc)
        if name and cat and ativo_aberto(name, chave_preferida=cat):
            return True, name, cat

        elapsed = time.time() - t0
        remaining = int(timeout_seconds - elapsed)
        if remaining <= 0:
            return False, None, None

        nowt = time.time()
        if nowt - last_print >= WAIT_ASSET_OPEN_PRINT_EVERY_SECONDS:
            console_event(
                f"⏳ Ativo ainda fechado: {display_asset_name(base)} | "
                f"aguardando abrir... (timeout em {_fmt_hms(remaining)})"
            )
            last_print = nowt

        time.sleep(WAIT_ASSET_OPEN_CHECK_EVERY_SECONDS)


# =========================
# LOOP PRINCIPAL
# =========================
def loop_patterns(ativo: str, ativo_chave: str, tf_min: int, runtime_seconds: Optional[int],
                  start_timestamp: Optional[int], schedule_base: str, schedule_allow_otc: bool):

    global pending, pending_id_active, pending_lock_until_ts, _last_pending_status_printed_for_id

    period = tf_min * 60
    expiration = 1 if tf_min == 1 else 5

    # Aguardar horário agendado
    if start_timestamp is not None and start_timestamp > time.time():
        console_event(f"⏳ Aguardando início agendado: {datetime.fromtimestamp(start_timestamp).strftime('%d/%m/%Y %H:%M:%S')}")
        while time.time() < start_timestamp:
            time.sleep(0.5)

    # Se agendado: resolver variante aberta real (-op etc) e esperar até abrir
    if start_timestamp is not None and WAIT_ASSET_OPEN_IF_SCHEDULED:
        console_event(f"🔎 Resolvendo ativo quando abrir: base={display_asset_name(schedule_base)} (OTC={'sim' if schedule_allow_otc else 'não'})")
        ok, real_asset, real_cat = wait_until_asset_open_or_timeout(
            schedule_base, schedule_allow_otc, WAIT_ASSET_OPEN_TIMEOUT_SECONDS
        )
        if not ok:
            console_event("❌ Ativo não abriu em 30 minutos após o início agendado. Encerrando bot.")
            return

        ativo = real_asset
        ativo_chave = real_cat
        console_event(f"✅ Ativo aberto detectado: {display_asset_name(ativo)} ({ativo_chave}). Iniciando operações...")

    initial_bal = get_available_balance()
    stop_loss_threshold = None
    stop_win_threshold = None
    if initial_bal:
        if STOP_LOSS_PCT > 0:
            stop_loss_threshold = initial_bal * (1.0 - STOP_LOSS_PCT / 100.0)
        if STOP_WIN_PCT > 0:
            stop_win_threshold = initial_bal * (1.0 + STOP_WIN_PCT / 100.0)

    start_exec = time.time()
    stop_ts = None if runtime_seconds is None else start_exec + runtime_seconds

    console_event(
        f"🚀 Loop iniciado | TF=M{tf_min} | Expiração={expiration}min | "
        f"Rigidez={RIGIDEZ_MODE.upper()} | mode={ENTRY_MODE.upper()} | tag={INSTANCE_TAG}"
    )

    last_remaining_minute_printed: Optional[int] = None
    if stop_ts is not None:
        remaining = int(stop_ts - time.time())
        console_event(f"⏳ Tempo restante: {_fmt_hms(remaining)}")
        last_remaining_minute_printed = remaining // 60

    last_idle_candle_id = None

    while True:
        if stop_ts is not None:
            remaining = int(stop_ts - time.time())
            if remaining <= 0:
                console_event("⏱️ Tempo de execução atingido. Encerrando...")
                break
            cur_min = remaining // 60
            if last_remaining_minute_printed is None or cur_min != last_remaining_minute_printed:
                console_event(f"⏳ Tempo restante: {_fmt_hms(remaining)}")
                last_remaining_minute_printed = cur_min

        bal = get_available_balance()
        if stop_loss_threshold and bal is not None and bal <= stop_loss_threshold:
            console_event("🛑 STOP LOSS atingido. Encerrando...")
            break
        if stop_win_threshold and bal is not None and bal >= stop_win_threshold:
            console_event("🎯 STOP WIN atingido. Encerrando...")
            break

        # Reconexão automática com watchdog SAFE/HOLD
        if not _ensure_connected():
            console_event(cred("❌ Não foi possível reconectar. Encerrando bot."))
            break

        # SAFE/HOLD: conexão degradada detectada; aguarda reconexão sem tomar decisões
        if _SAFE_HOLD_MODE:
            time.sleep(5.0)
            continue

        now_server = get_now_ts()
        candle_id = now_server // period

        if pending is None and candle_id != last_idle_candle_id:
            last_idle_candle_id = candle_id
            console_event(f"⏳ Aguardando... (Ativo: {display_asset_name(ativo)} | TF: M{tf_min})")

        if not ativo_aberto(ativo, chave_preferida=ativo_chave):
            _log_blocked("asset_closed", f"tf={tf_min}")
            time.sleep(IDLE_SLEEP_S_M5 if tf_min == 5 else IDLE_SLEEP_S_M1)
            continue

        velas = get_candles_safe(ativo, period, CANDLES_LOOKBACK)
        if not velas or len(velas) < MIN_CANDLES_REQUIRED:
            time.sleep(IDLE_SLEEP_S_M5 if tf_min == 5 else IDLE_SLEEP_S_M1)
            continue

        if not passes_all_regime_filters(tf_min, velas):
            time.sleep(IDLE_SLEEP_S_M5 if tf_min == 5 else IDLE_SLEEP_S_M1)
            continue

        if pending is not None and pending_id_active is not None:
            if _last_pending_status_printed_for_id != pending_id_active:
                _last_pending_status_printed_for_id = pending_id_active
                console_event(f"🕯️ {pending['pattern_name']} pendente (aguardando confirmação)")

            status, direction = confirm_pending(tf_min, pending, velas)

            if status == "waiting":
                time.sleep(PENDING_SLEEP_S_M5 if tf_min == 5 else PENDING_SLEEP_S_M1)
                continue

            if status in ("expired", "rejected", "error"):
                _log_pattern_row(ativo, tf_min, status, pending, block_reason=status)
                pending = None
                pending_id_active = None
                pending_lock_until_ts = now_server + (period * 1)
                time.sleep(0.5)
                continue

            if status == "confirmed" and direction in ("call", "put"):
                patt = pending["pattern_name"]
                _log_pattern_row(ativo, tf_min, "confirmed", pending, confirmed=True)

                ok_win, sec, win = within_entry_window(tf_min)
                if not ok_win:
                    _log_blocked(
                        "missed_early_entry",
                        f"ativo={ativo} tf={tf_min} "
                        f"dir={direction} patt={patt} mode={pending.get('pattern_mode', '?')} "
                        f"pattern_from={pending.get('pattern_from', '')} "
                        f"secs_elapsed={sec} window={win} "
                        f"BUY_LATENCY_AVG={BUY_LATENCY_AVG:.3f}"
                    )
                    pending = None
                    pending_id_active = None
                    pending_lock_until_ts = now_server + (period * 1)
                    continue

                if BUY_LATENCY_AVG + BUY_LATENCY_MARGIN >= (win - sec):
                    _log_blocked("latency_guard", f"tf={tf_min}")
                    pending = None
                    pending_id_active = None
                    pending_lock_until_ts = now_server + (period * 1)
                    continue

                if not can_purchase_now(ativo, period_minutes=tf_min, chave_preferida=ativo_chave):
                    _log_blocked("purchase_buffer", f"tf={tf_min}")
                    pending = None
                    pending_id_active = None
                    pending_lock_until_ts = now_server + (period * 1)
                    continue

                saldo_before = get_available_balance() or 0.0
                # Entrada única e certeira: amount fixo por sinal, sem progressão de stake.
                # Cada sinal gera no máximo UMA ordem. Não há Martingale, Soros ou Recovery.
                amount_to_use = compute_amount(saldo_before)
                secs_left = seconds_left_in_period(tf_min)

                console_event(
                    f"🕯️ [{server_hhmmss()}] Sinal confirmado: {patt} | "
                    f"Entrada: {cgreen('CALL 📈') if direction == 'call' else cred('PUT 📉')} | "
                    f"${amount_to_use:.2f} | secs_left={secs_left}"
                )

                # Log acionável: registra a decisão de entrar ANTES do envio da ordem.
                _log_sinal_acionavel(
                    ativo, tf_min, direction, pending,
                    entra_em_ts=pending.get("expected_confirm_from"),
                )

                result_container = {}
                ev = threading.Event()
                if USE_BUY_THREAD:
                    t = threading.Thread(
                        target=_buy_worker,
                        args=(direction, ativo, amount_to_use, expiration, result_container, ev),
                        daemon=True
                    )
                    t.start()
                    ev.wait(timeout=25.0)
                else:
                    status_b, info_b = _do_buy_minimal(amount_to_use, ativo, direction, expiration)
                    result_container["res"] = {"success": bool(status_b), "order_id": info_b if status_b else None, "info": info_b}

                res = result_container.get("res", {})
                if not res.get("success"):
                    console_event(cyellow(f"⚠️ [{server_hhmmss()}] Falha ao enviar ordem."))
                    pending = None
                    pending_id_active = None
                    pending_lock_until_ts = now_server + (period * 1)
                    continue

                order_id = res.get("order_id")
                console_event(ccyan(f"✅ [{server_hhmmss()}] Ordem aceita | ID: {order_id}"))
                console_event(f"⏳ [{server_hhmmss()}] Aguardando resultado...")

                t0 = time.time()
                min_wait = expiration * 60 + RESULT_DELAY_AFTER_EXPIRY_SECONDS
                while time.time() - t0 < min_wait:
                    time.sleep(0.5)

                timeout = M5_RESULT_TIMEOUT if expiration == 5 else M1_RESULT_TIMEOUT
                timeout = max(35, timeout)

                result = check_order_result(
                    order_id, amount_to_use,
                    saldo_before=saldo_before,
                    timeout_seconds=timeout,
                    poll_interval=2.0 if expiration == 5 else 1.5
                )

                label = result.get("result", "unknown")
                profit = result.get("profit")
                bal_after = result.get("balance_after")
                method = result.get("method")

                if label == "win":
                    console_event(cgreen(f"✅ [{server_hhmmss()}] ") + fmt_result_line(label, profit, method))
                elif label == "loss":
                    console_event(cred(f"❌ [{server_hhmmss()}] ") + fmt_result_line(label, profit, method))
                else:
                    console_event(f"❓ [{server_hhmmss()}] {fmt_result_line(label, profit, method)}")

                try:
                    if TRADES_CSV is not None:
                        with TRADES_CSV.open('a', newline='', encoding='utf-8') as f:
                            csv.writer(f).writerow([
                                now_iso(), INSTANCE_TAG,
                                ativo, tf_min, ENTRY_MODE, RIGIDEZ_MODE,
                                direction, order_id,
                                method, label, float(profit) if profit is not None else "",
                                saldo_before, bal_after if bal_after is not None else "",
                                amount_to_use, f"{BUY_LATENCY_AVG:.6f}",
                                patt, pending.get("pattern_from"),
                                secs_left
                            ])
                except Exception:
                    pass

                pending = None
                pending_id_active = None
                pending_lock_until_ts = now_server + (period * 1)
                time.sleep(0.8)
                continue

        if now_server < pending_lock_until_ts:
            time.sleep(IDLE_SLEEP_S_M5 if tf_min == 5 else IDLE_SLEEP_S_M1)
            continue

        sig = check_patterns(tf_min, velas)
        if not sig:
            time.sleep(IDLE_SLEEP_S_M5 if tf_min == 5 else IDLE_SLEEP_S_M1)
            continue

        patt = sig["pattern_name"]
        patt_from = int(sig["pattern_from"])
        pend_id = (patt, patt_from, ativo, tf_min)

        lastp = last_pending_print_ts_by_id.get(pend_id, 0.0)
        nowt = time.time()
        if nowt - lastp >= PENDING_PRINT_THROTTLE_S:
            console_event(f"🕯️ Sinal detectado: {patt}. Aguardando confirmação...")
            last_pending_print_ts_by_id[pend_id] = nowt
            _log_pattern_row(ativo, tf_min, "detected", sig)

        pending = sig
        pending_id_active = pend_id
        pending_lock_until_ts = int(sig["expected_confirm_from"]) + (period * 1)
        time.sleep(PENDING_SLEEP_S_M5 if tf_min == 5 else PENDING_SLEEP_S_M1)

    print("✅ Loop finalizado.")


# =========================
# LOOP MULTI-ATIVO (M1/M5)
# =========================
def loop_patterns_multi(
    ativos: List[Tuple[str, str]],
    tf_min: int,
    max_ativos: int = 0,
    use_otc: bool = False,
    allow_open_market: bool = False,
    run_minutes: int = 0,
    max_entries: int = 0,
):
    """Orquestra múltiplos ativos em único ciclo (M1 ou M5). Stops globais pelo saldo.

    Gestão dinâmica de ativos:
    - Se um ativo falhar na entrada (buy), é removido imediatamente e o bot
      tenta preencher com outro disponível.
    - A cada novo candle, re-verifica o pool completo (favoritos + book) e
      re-inclui qualquer ativo disponível (sem ban permanente).
    - Se não houver ativos disponíveis, aguarda e continua tentando a cada ciclo.
    - run_minutes > 0: encerra automaticamente após esse número de minutos.
    - max_entries > 0: encerra após atingir esse número de ordens ACEITAS.

    Prioridade Digital:
    - Antes de cada entrada, resolve_trade_variant() re-verifica se o mercado
      DIGITAL está aberto para o ativo. Se sim, usa buy_digital_spot_v2(). Se não,
      usa buy() (binária). Assim o bot sempre prioriza digital e cai para binária.
    """

    period = tf_min * 60
    expiration = tf_min
    # M1: limita automaticamente a no máximo 4 ativos simultâneos para melhor foco
    _m1_max_ativos = 4
    if tf_min == 1:
        _max_ativos = min(max_ativos, _m1_max_ativos) if max_ativos > 0 else _m1_max_ativos
    else:
        _max_ativos = max_ativos if max_ativos > 0 else len(ativos)

    # Temporizador de finalização automática
    end_time: Optional[float] = (time.time() + run_minutes * 60) if run_minutes > 0 else None

    # Contador de entradas aceitas
    entries_accepted: int = 0

    # Lista mutável de ativos ativos
    active_ativos: List[Tuple[str, str]] = list(ativos)

    # Estado por ativo (crescente; chaves antigas inativas não atrapalham)
    per_asset_pending: Dict[str, Optional[Dict[str, Any]]] = {}
    per_asset_pending_id: Dict[str, Any] = {}
    per_asset_lock_until: Dict[str, int] = {}
    per_asset_last_idle_cid: Dict[str, Any] = {}
    per_asset_last_pend_status_id: Dict[str, Any] = {}
    asset_last_pending_print: Dict[Any, float] = {}

    # M5 dynamic pool manager state
    m5_pool_stats: Dict[str, Dict[str, Any]] = {}
    m5_pool_cooldown: Dict[str, float] = {}  # ativo_upper → removed_at timestamp
    _last_m5_rebalance_ts: float = time.time()

    def _init_asset_state(name: str) -> None:
        if name not in per_asset_pending:
            per_asset_pending[name] = None
            per_asset_pending_id[name] = None
            per_asset_lock_until[name] = 0
            per_asset_last_idle_cid[name] = None
            per_asset_last_pend_status_id[name] = None

    for a, _ in active_ativos:
        _init_asset_state(a)

    initial_bal = get_available_balance()
    stop_loss_threshold = None
    stop_win_threshold = None
    if initial_bal:
        if STOP_LOSS_PCT > 0:
            stop_loss_threshold = initial_bal * (1.0 - STOP_LOSS_PCT / 100.0)
        if STOP_WIN_PCT > 0:
            stop_win_threshold = initial_bal * (1.0 + STOP_WIN_PCT / 100.0)

    console_event(
        f"🚀 Loop M{tf_min} multi-ativo | {len(active_ativos)} ativo(s) | "
        f"Modo: REVERSÃO | tag={INSTANCE_TAG}"
    )
    for a, ak in active_ativos:
        cat_label = f"DIGITAL M{tf_min}" if ak == 'digital' else f"BINARIA M{tf_min}"
        console_event(f"  📊 {display_asset_name(a)} [{cat_label}]")
    if max_entries > 0:
        console_event(f"  🎯 Limite de entradas: {max_entries}")

    # Controle do recheck por candle
    last_recheck_cid: int = -1
    # Controle de re-ranking para M1 (a cada 15 minutos)
    M1_RANK_INTERVAL_S = 900  # re-rankeia ativos M1 a cada 15 minutos
    _last_m1_rank_ts: float = 0.0
    # Controle de refresh do pool M5 (sem dynamic pool): a cada 10 minutos
    # recalcula os candidatos e substitui ativos que saíram da lista aberta.
    M5_REFRESH_INTERVAL_S = 600  # refresh M5 pool a cada 10 minutos
    _last_m5_refresh_ts: float = 0.0

    def _refill_pool(now_cid: int) -> None:
        """Re-verifica o pool completo e adiciona ativos disponíveis.

        Para M1: aplica ranking por ATR+ADX+BBW a cada M1_RANK_INTERVAL_S segundos,
        mantendo apenas os ativos com melhor regime de mercado no pool ativo.
        Para M5 (sem dynamic pool): refresca o pool a cada M5_REFRESH_INTERVAL_S
        substituindo ativos que fecharam ou saíram da lista de candidatos abertos.
        """
        nonlocal last_recheck_cid, active_ativos, _last_m1_rank_ts, _last_m5_refresh_ts
        if now_cid == last_recheck_cid:
            return
        last_recheck_cid = now_cid

        try:
            # ← Filtra candidatos por timeframe (M1/M5) e prioridade digital
            candidates = build_candidate_pool(use_otc=use_otc, tf_min=tf_min,
                                              allow_open_market=allow_open_market)
        except Exception as exc:
            _log_error("Falha ao buscar pool de candidatos em _refill_pool.", exc)
            return

        if tf_min == 1:
            # M1: re-ranking periódico — seleciona top _max_ativos por qualidade de regime
            now_t = time.time()
            if now_t - _last_m1_rank_ts >= M1_RANK_INTERVAL_S or not active_ativos:
                _last_m1_rank_ts = now_t
                # Preserva ativos com pending ativo no ranking para não cortar sinais em andamento
                pending_ativos = {a for a, _ in active_ativos
                                  if per_asset_pending.get(a) is not None}
                ranked = rank_assets_by_regime(candidates, tf_min, top_n=_max_ativos + len(pending_ativos))
                ranked_names = {a.upper() for a, _ in ranked}
                # Remove ativos sem ranking (e sem pending) do pool
                removed = [a for a, _ in active_ativos
                           if a.upper() not in ranked_names and a not in pending_ativos]
                if removed:
                    active_ativos = [(a, c) for a, c in active_ativos if a not in removed]
                    console_event(
                        f"🔄 Re-ranking M1: removidos do pool: "
                        + ", ".join(display_asset_name(a) for a in removed)
                    )
                # Adiciona ativos do ranking que ainda não estão no pool
                active_names = {a.upper() for a, _ in active_ativos}
                added = []
                for candidate, cat in ranked:
                    if len(active_ativos) >= _max_ativos:
                        break
                    if candidate.upper() in active_names:
                        continue
                    active_ativos.append((candidate, cat))
                    _init_asset_state(candidate)
                    active_names.add(candidate.upper())
                    added.append((candidate, cat))
                if added:
                    cat_str = ", ".join(
                        f"{display_asset_name(a)} [{'DIGITAL' if c == 'digital' else 'BINARIA'} M{tf_min}]"
                        for a, c in added
                    )
                    console_event(f"➕ Re-ranking M{tf_min}: adicionados ao pool: " + cat_str)
                return

        # M5 sem dynamic pool: refresh periódico para substituir ativos fechados/indisponíveis
        if tf_min == 5 and not M5_POOL_DYNAMIC_ENABLE:
            now_t = time.time()
            if now_t - _last_m5_refresh_ts >= M5_REFRESH_INTERVAL_S or not active_ativos:
                _last_m5_refresh_ts = now_t
                candidate_names = {a.upper() for a, _ in candidates}
                pending_ativos = {a for a, _ in active_ativos
                                  if per_asset_pending.get(a) is not None}
                # Remove ativos que não estão mais disponíveis na lista de candidatos abertos
                removed = [a for a, _ in active_ativos
                           if a.upper() not in candidate_names and a not in pending_ativos]
                if removed:
                    active_ativos = [(a, c) for a, c in active_ativos if a not in removed]
                    console_event(
                        f"🔄 Refresh M5: removidos do pool (fechados/indisponíveis): "
                        + ", ".join(display_asset_name(a) for a in removed)
                    )

        # M5 (ou M1 fora do intervalo de ranking): preenchimento normal sem ranking
        active_names = {a.upper() for a, _ in active_ativos}
        added = []
        for candidate, cat in candidates:
            if len(active_ativos) >= _max_ativos:
                break
            if candidate.upper() in active_names:
                continue
            # M5 dynamic pool: skip assets in cooldown (recently removed by rebalancer)
            if tf_min == 5 and M5_POOL_DYNAMIC_ENABLE:
                _cd_ts = m5_pool_cooldown.get(candidate.upper(), 0.0)
                if (time.time() - _cd_ts) < M5_POOL_ASSET_COOLDOWN_MINUTES * 60:
                    continue
            active_ativos.append((candidate, cat))
            _init_asset_state(candidate)
            active_names.add(candidate.upper())
            added.append((candidate, cat))
        if added:
            cat_str = ", ".join(
                f"{display_asset_name(a)} [{'DIGITAL' if c == 'digital' else 'BINARIA'} M{tf_min}]"
                for a, c in added
            )
            console_event(f"➕ Ativos re-incluídos no pool M{tf_min}: " + cat_str)

    def _replace_asset(failed_ativo: str) -> None:
        """Remove ativo com falha e tenta preencher imediatamente com outro."""
        nonlocal active_ativos
        active_ativos = [(a, c) for a, c in active_ativos if a != failed_ativo]
        console_event(
            f"⚠️  [{display_asset_name(failed_ativo)}] Removido do pool "
            f"(falha de entrada M{tf_min}). Buscando substituto..."
        )
        active_names = {a.upper() for a, _ in active_ativos}
        try:
            # ← Filtra candidatos por timeframe (M1/M5) e prioridade digital
            candidates = build_candidate_pool(use_otc=use_otc, tf_min=tf_min,
                                              allow_open_market=allow_open_market)
        except Exception as exc:
            _log_error("Falha ao buscar pool de candidatos em _replace_asset.", exc)
            return
        for candidate, cat in candidates:
            if len(active_ativos) >= _max_ativos:
                break
            if candidate.upper() in active_names:
                continue
            active_ativos.append((candidate, cat))
            _init_asset_state(candidate)
            active_names.add(candidate.upper())
            cat_label = f"DIGITAL M{tf_min}" if cat == 'digital' else f"BINARIA M{tf_min}"
            console_event(
                f"➕ [{display_asset_name(candidate)}] [{cat_label}] Adicionado como substituto M{tf_min}."
            )
            break

    # -----------------------------------------------------------------------
    # M5 Dynamic Pool Manager helpers
    # -----------------------------------------------------------------------
    def _new_pool_stats() -> Dict[str, Any]:
        return {
            "detected": 0,
            "confirmed": 0,
            "rejected": 0,
            "expired": 0,
            "missed": 0,
            "blocked": 0,
            "pending_timeout": 0,
            "latency_guard": 0,
            "asset_closed": 0,
            "win_trade": 0,
            "loss_trade": 0,
            "freeze_skip": 0,
            "last_detected_ts": 0.0,
            "last_confirmed_ts": 0.0,
            "events": deque(),  # (timestamp, event_type) for sliding-window scoring
        }

    # Valid cumulative counter keys in the pool stats dict (excludes timestamps/deque)
    _M5_POOL_EVENT_KEYS = frozenset({
        "detected", "confirmed", "rejected", "expired", "missed", "blocked",
        "pending_timeout", "latency_guard", "asset_closed", "win_trade",
        "loss_trade", "freeze_skip",
    })

    def _m5_track(event: str, ativo: str) -> None:
        """Record an operational event for a given asset (M5 pool scoring)."""
        s = m5_pool_stats.setdefault(ativo, _new_pool_stats())
        now_t = time.time()
        # Update last-activity timestamps for dead-pool detection
        if event == "detected":
            s["detected"] += 1
            s["last_detected_ts"] = now_t
        elif event == "confirmed":
            s["confirmed"] += 1
            s["last_confirmed_ts"] = now_t
        elif event in _M5_POOL_EVENT_KEYS:
            s[event] += 1  # increment the known cumulative counter
        # Append to sliding-window event queue
        events_q: deque = s["events"]
        events_q.append((now_t, event))

    def _m5_score(ativo: str, donchian_penalty: float = 0.0) -> float:
        """Compute operational health score for an asset (higher = better).

        Uses a sliding window of M5_POOL_SCORE_WINDOW_MINUTES for recent events.
        An optional donchian_penalty is subtracted for dead-market detection.
        """
        s = m5_pool_stats.get(ativo, {})
        if not s:
            return 0.0
        events_q: deque = s.get("events", deque())
        if M5_POOL_SCORE_WINDOW_MINUTES > 0:
            cutoff = time.time() - M5_POOL_SCORE_WINDOW_MINUTES * 60
            w: Dict[str, int] = {}
            for ts, ev in events_q:
                if ts >= cutoff:
                    w[ev] = w.get(ev, 0) + 1
        else:
            # No window: fall back to cumulative counters (only known event keys)
            w = {k: s[k] for k in _M5_POOL_EVENT_KEYS if k in s}

        score = (
            w.get("confirmed", 0) * M5_POOL_SCORE_W_CONFIRMED
            + w.get("win_trade", 0) * M5_POOL_SCORE_W_WIN_TRADE
            + (M5_POOL_SCORE_W_DETECTED if w.get("detected", 0) > 0 else 0.0)
            - (w.get("expired", 0) + w.get("rejected", 0)) * M5_POOL_SCORE_W_EXPIRED_REJECTED
            - w.get("missed", 0) * M5_POOL_SCORE_W_MISSED
            - w.get("blocked", 0) * M5_POOL_SCORE_W_BLOCKED
            - w.get("pending_timeout", 0) * M5_POOL_SCORE_W_PENDING_TIMEOUT
            - w.get("latency_guard", 0) * M5_POOL_SCORE_W_LATENCY_GUARD
            - w.get("asset_closed", 0) * M5_POOL_SCORE_W_ASSET_CLOSED
            - w.get("loss_trade", 0) * M5_POOL_SCORE_W_LOSS_TRADE
            - donchian_penalty
        )
        return score

    def _m5_pool_is_dead() -> bool:
        """Returns True when no asset in the pool had any activity for M5_POOL_DEAD_MINUTES.

        Returns False for an empty pool (nothing to conclude yet) and for assets
        that have never been observed (no stats recorded), to avoid spurious
        dead-market swaps right at startup.
        """
        if not active_ativos:
            return False
        dead_secs = M5_POOL_DEAD_MINUTES * 60
        now_t = time.time()
        has_any_stats = False
        for a, _ in active_ativos:
            s = m5_pool_stats.get(a, {})
            last_act = max(s.get("last_detected_ts", 0.0), s.get("last_confirmed_ts", 0.0))
            if last_act > 0:
                has_any_stats = True
                if (now_t - last_act) <= dead_secs:
                    return False
        # If no asset has ever had any activity recorded, pool is too young to be called dead
        return has_any_stats

    def _log_rebalance(msg: str) -> None:
        """Print rebalance event and append to pool_rebalance_m5.log."""
        print(msg)
        if POOL_REBALANCE_LOG_M5 is not None:
            try:
                with POOL_REBALANCE_LOG_M5.open('a', encoding='utf-8') as f:
                    f.write(f"{datetime.now().isoformat()} | {INSTANCE_TAG} | {msg}\n")
            except Exception:
                pass

    def _rebalance_m5_pool() -> None:
        """Periodic M5 pool rebalance: swap worst-scoring assets for better candidates.

        Melhorias:
        - Registra universo total aberto, candidatos elegíveis e motivos de troca.
        - Escala n_swap baseado no tamanho do universo (mais candidatos = mais trocas).
        - Aplica penalidade Donchian para ativos com mercado comprimido.
        - Score detalhado por motivo no log pool_rebalance_m5.log.
        """
        nonlocal active_ativos, _last_m5_rebalance_ts
        now_t = time.time()
        if (now_t - _last_m5_rebalance_ts) < M5_POOL_REBALANCE_MINUTES * 60:
            return
        _last_m5_rebalance_ts = now_t

        is_dead = _m5_pool_is_dead()
        n_swap = M5_POOL_SWAP_MAX_DEAD if is_dead else M5_POOL_SWAP_MAX_NORMAL
        reason = "dead-market" if is_dead else "interval"

        # Universe of replacement candidates
        try:
            universe = build_candidate_pool(use_otc=use_otc, tf_min=tf_min,
                                            allow_open_market=allow_open_market)
        except Exception as exc:
            _log_error("Falha ao buscar universo em _rebalance_m5_pool.", exc)
            return

        active_names = {a.upper() for a, _ in active_ativos}
        cooldown_secs = M5_POOL_ASSET_COOLDOWN_MINUTES * 60
        candidates = [
            (a, c) for a, c in universe
            if a.upper() not in active_names
            and (now_t - m5_pool_cooldown.get(a.upper(), 0.0)) >= cooldown_secs
        ]

        # Universe-size-aware swap scaling: larger universe → more aggressive swaps
        n_universe_total = len(universe)
        n_in_pool = len(active_ativos)
        n_external = len(candidates)
        if M5_POOL_SWAP_SCALE_WITH_UNIVERSE and n_external > 0 and M5_POOL_SWAP_UNIVERSE_DIVISOR > 0:
            extra = n_external // M5_POOL_SWAP_UNIVERSE_DIVISOR
            n_swap = min(n_swap + extra, M5_POOL_SWAP_MAX_ABS)

        # Candidates for removal: assets without active pending signal, sorted worst first
        # Compute Donchian penalty for pool assets to improve removal scoring
        swappable = [(a, c) for a, c in active_ativos if per_asset_pending.get(a) is None]
        if not swappable:
            _log_rebalance(
                f"[REBALANCE M5] razão={reason} — nenhum ativo disponível para trocar "
                f"(todos com pending ativo). "
                f"universo={n_universe_total} elegíveis={n_external}"
            )
            return

        # Compute Donchian penalty per swappable asset
        donchian_penalties: Dict[str, float] = {}
        for a, _ in swappable:
            ratio = _donchian_range_ratio_m5(a, M5_POOL_DEAD_MARKET_DONCHIAN_PERIOD)
            if ratio is not None and ratio < M5_POOL_DEAD_MARKET_RANGE_RATIO_THR:
                donchian_penalties[a] = M5_POOL_DEAD_MARKET_PENALTY
            else:
                donchian_penalties[a] = 0.0

        scored = sorted(
            swappable,
            key=lambda ac: (_m5_score(ac[0], donchian_penalties.get(ac[0], 0.0)), ac[0])
        )
        to_remove = scored[:n_swap]

        if not candidates:
            # Build score summary for transparency even when no swap is possible
            s_lines = []
            for a, _ in active_ativos:
                dp = donchian_penalties.get(a, 0.0)
                sc = _m5_score(a, dp)
                s = m5_pool_stats.get(a, {})
                s_lines.append(
                    f"  {display_asset_name(a)}: score={sc:.1f} "
                    f"[det={s.get('detected', 0)} conf={s.get('confirmed', 0)} "
                    f"exp={s.get('expired', 0)} rej={s.get('rejected', 0)} "
                    f"miss={s.get('missed', 0)} blk={s.get('blocked', 0)} "
                    f"pto={s.get('pending_timeout', 0)} lat={s.get('latency_guard', 0)} "
                    f"don_pen={dp:.1f}]"
                )
            _log_rebalance(
                f"[REBALANCE M5] razão={reason} — sem candidatos elegíveis no universo "
                f"(universo={n_universe_total} pool={n_in_pool} cooldown={n_universe_total - n_in_pool - n_external}).\n"
                + "\n".join(s_lines) + "\n  Nenhuma troca."
            )
            return

        n_actual = min(n_swap, len(to_remove), len(candidates))
        to_remove = to_remove[:n_actual]
        to_add = candidates[:n_actual]

        # Build detailed score summary for logging
        remove_set = {a for a, _ in to_remove}
        score_lines = []
        for a, _ in active_ativos:
            dp = donchian_penalties.get(a, 0.0)
            sc = _m5_score(a, dp)
            s = m5_pool_stats.get(a, {})
            tag_out = " ← SAINDO" if a in remove_set else ""
            score_lines.append(
                f"  {display_asset_name(a)}: score={sc:.1f} "
                f"[det={s.get('detected', 0)} conf={s.get('confirmed', 0)} "
                f"exp={s.get('expired', 0)} rej={s.get('rejected', 0)} "
                f"miss={s.get('missed', 0)} blk={s.get('blocked', 0)} "
                f"pto={s.get('pending_timeout', 0)} lat={s.get('latency_guard', 0)} "
                f"win={s.get('win_trade', 0)} loss={s.get('loss_trade', 0)} "
                f"don_pen={dp:.1f}]{tag_out}"
            )

        msg = (
            f"[REBALANCE M5] razão={reason} trocas={n_actual} "
            f"universo={n_universe_total} elegíveis={n_external} pool={n_in_pool}\n"
            + "\n".join(score_lines) + "\n"
            + "  Removidos: " + ", ".join(display_asset_name(a) for a, _ in to_remove) + "\n"
            + "  Adicionados: " + ", ".join(display_asset_name(a) for a, _ in to_add)
        )
        _log_rebalance(msg)

        # Apply swaps — remove all at once then add new assets
        for a, _ in to_remove:
            m5_pool_cooldown[a.upper()] = now_t
        active_ativos = [(av, cv) for av, cv in active_ativos if av not in remove_set]

        for a, c in to_add:
            active_ativos.append((a, c))
            _init_asset_state(a)
            if a not in m5_pool_stats:
                m5_pool_stats[a] = _new_pool_stats()

    # M5 pending-first freeze state (persists across loop iterations)
    freeze_active: bool = False
    freeze_end_ts: float = 0.0
    # Throttle freeze_skip logging per asset to avoid log spam on stale pendings
    _freeze_skip_last_logged: Dict[str, float] = {}

    while True:
        # Verificação: limite de entradas aceitas atingido
        if max_entries > 0 and entries_accepted >= max_entries:
            console_event(
                f"🎯 Limite de {max_entries} entradas aceitas atingido. Encerrando bot."
            )
            break

        # Verificação global de stop
        bal = get_available_balance()
        if stop_loss_threshold and bal is not None and bal <= stop_loss_threshold:
            console_event("🛑 STOP LOSS global atingido. Encerrando ciclo...")
            break
        if stop_win_threshold and bal is not None and bal >= stop_win_threshold:
            console_event("🎯 STOP WIN global atingido. Encerrando ciclo...")
            break

        # Verificação de temporizador automático
        if end_time is not None and time.time() >= end_time:
            console_event(
                f"⏹️  Tempo de operação encerrado ({run_minutes} min). "
                "Bot finalizado automaticamente."
            )
            break

        # Reconexão automática com watchdog SAFE/HOLD: verifica e restaura a conexão antes de cada ciclo
        if not _ensure_connected():
            console_event(cred("❌ Não foi possível reconectar. Encerrando bot."))
            break

        # SAFE/HOLD: conexão degradada detectada; limpa estados arm/sniper e aguarda reconexão
        if _SAFE_HOLD_MODE:
            # Limpa pending arm/sniper para não executar sinais stale após reconexão
            for _a in list(per_asset_pending.keys()):
                if per_asset_pending[_a] is not None:
                    _log_blocked(
                        "safe_hold_clear_pending",
                        f"ativo={_a} tf={tf_min} pattern={per_asset_pending[_a].get('pattern_name', '')}"
                    )
                    per_asset_pending[_a] = None
                    per_asset_pending_id[_a] = None
            time.sleep(5.0)
            continue

        now_server = get_now_ts()
        candle_id = now_server // period

        # Recheck completo do pool a cada novo candle (sem ban permanente)
        _refill_pool(candle_id)

        # M5 dynamic pool: periodic rebalance (only when feature is enabled)
        if tf_min == 5 and M5_POOL_DYNAMIC_ENABLE:
            _rebalance_m5_pool()

        if not active_ativos:
            console_event(
                f"⏳ Nenhum ativo da lista Ativos.txt está aberto para o timeframe M{tf_min} "
                "escolhido. Aguardando abertura..."
            )
            idle_sleep = IDLE_SLEEP_S_M5 if tf_min == 5 else IDLE_SLEEP_S_M1
            time.sleep(idle_sleep * EMPTY_POOL_SLEEP_MULTIPLIER)
            continue

        # --- M5 pending-first freeze: focus only on assets with pending signals ---
        if tf_min == 5 and PENDING_FREEZE_SECONDS_M5 > 0:
            # Separate pendings into eligible (entry window still open) and stale.
            # A pending is eligible when now_ts <= expected_confirm_from + entry_window,
            # i.e. there is still time to execute the signal.  For arm_sniper mode the
            # effective window is sniper_window_seconds; for all others it is
            # entry_window_seconds_m5.  Unknown ECF (0) → treated as eligible.
            # Uses get_now_ts() (fresh, offset-corrected) instead of stale loop now_server.
            _now_wall = time.time()
            def _pend_eligible(a: str) -> bool:
                p = per_asset_pending.get(a)
                if p is None:
                    return False
                try:
                    _ecf = int(p.get("expected_confirm_from", 0) or 0)
                except (ValueError, TypeError):
                    return True  # ECF corrompido → tratar como elegível
                if _ecf == 0:
                    return True  # no ECF info → assume eligible
                _pmode = p.get("pattern_mode", "v15")
                _win = SNIPER_WINDOW_SECONDS_M5 if _pmode == "arm_sniper" else ENTRY_WINDOW_SECONDS_M5
                return get_now_ts() <= _ecf + _win

            pending_assets = [(a, c) for a, c in list(active_ativos) if per_asset_pending.get(a) is not None]
            eligible_pending_assets = [(a, c) for a, c in pending_assets if _pend_eligible(a)]

            if eligible_pending_assets and not freeze_active:
                freeze_active = True
                freeze_end_ts = _now_wall + PENDING_FREEZE_SECONDS_M5
                freeze_names = ", ".join(display_asset_name(a) for a, _ in eligible_pending_assets)
                console_event(
                    f"🔒 [FREEZE M5] Foco em pending por {int(PENDING_FREEZE_SECONDS_M5)}s "
                    f"— ativos: {freeze_names}"
                )
            elif pending_assets and not eligible_pending_assets and not freeze_active:
                # All pendings are stale (entry window already closed) — skip freeze.
                # Throttle logging to once per 30s per asset to avoid log spam.
                _skip_now = time.time()
                _throttle_s = 30.0
                _now_log = get_now_ts()
                for a, _ in pending_assets:
                    _last_skip = _freeze_skip_last_logged.get(a, 0.0)
                    if (_skip_now - _last_skip) >= _throttle_s:
                        _p = per_asset_pending.get(a)
                        _ecf_log = int(_p.get("expected_confirm_from", 0)) if _p else 0
                        _pmode_log = (_p.get("pattern_mode", "v15") if _p else "v15")
                        _win_log = SNIPER_WINDOW_SECONDS_M5 if _pmode_log == "arm_sniper" else ENTRY_WINDOW_SECONDS_M5
                        _secs_past_log = _now_log - _ecf_log if _ecf_log else "?"
                        _log_blocked(
                            "freeze_skip",
                            f"ativo={a} tf={tf_min} "
                            f"reason=entry_window_closed "
                            f"ecf={_ecf_log} win={_win_log} now_server={_now_log} "
                            f"secs_past_ecf={_secs_past_log} mode={_pmode_log}"
                        )
                        if M5_POOL_DYNAMIC_ENABLE:
                            _m5_track("freeze_skip", a)
                        _freeze_skip_last_logged[a] = _skip_now
            elif freeze_active:
                if not pending_assets:
                    freeze_active = False
                    console_event("🔓 [FREEZE M5] Encerrado — todos os pending resolvidos")
                elif not eligible_pending_assets:
                    freeze_active = False
                    console_event("🔓 [FREEZE M5] Encerrado — pendings fora do TTL")
                elif _now_wall >= freeze_end_ts:
                    freeze_active = False
                    console_event("🔓 [FREEZE M5] Encerrado — timeout")

        # Collect confirmed signals this cycle for best-signal selection (M5)
        confirmed_this_cycle: List[Any] = []

        for ativo, ativo_chave in list(active_ativos):
            pend = per_asset_pending[ativo]
            pend_id = per_asset_pending_id[ativo]
            lock_until = per_asset_lock_until[ativo]

            # During M5 freeze, skip assets with no pending signal — focus on pending only
            if freeze_active and pend is None:
                continue

            if pend is None and candle_id != per_asset_last_idle_cid[ativo]:
                per_asset_last_idle_cid[ativo] = candle_id
                if max_entries > 0:
                    _entries_label = f" | Entradas: {entries_accepted}/{max_entries}"
                elif entries_accepted > 0:
                    _entries_label = f" | Entradas: {entries_accepted}"
                else:
                    _entries_label = ""
                console_event(
                    f"⏳ Aguardando... (Ativo: {display_asset_name(ativo)} | TF: M{tf_min}{_entries_label})"
                )

            if not ativo_aberto(ativo, chave_preferida=ativo_chave):
                _log_blocked("asset_closed", f"ativo={ativo} tf={tf_min}")
                if tf_min == 5 and M5_POOL_DYNAMIC_ENABLE:
                    _m5_track("asset_closed", ativo)
                    # Remove imediatamente do pool e entra em cooldown
                    active_ativos = [(a, c) for a, c in active_ativos if a != ativo]
                    m5_pool_cooldown[ativo.upper()] = time.time()
                    _log_rebalance(
                        f"[POOL M5] {display_asset_name(ativo)} removido imediatamente "
                        f"(asset_closed). Cooldown={M5_POOL_ASSET_COOLDOWN_MINUTES:.0f}min."
                    )
                continue

            velas = get_candles_safe(ativo, period, CANDLES_LOOKBACK)
            if not velas or len(velas) < MIN_CANDLES_REQUIRED:
                continue

            # Post-reconnect guard: aguarda pelo menos 1 candle novo por ativo após sair de SAFE/HOLD
            if _post_reconnect_resume_ts > 0:
                try:
                    _last_candle_ts = float(velas[-1].get("from", 0)) if velas else 0.0
                except (ValueError, TypeError):
                    _last_candle_ts = 0.0
                _seen_candle_ts = _post_reconnect_candle_seen.get(ativo, 0.0)
                if _seen_candle_ts == 0.0:
                    if _last_candle_ts > _post_reconnect_resume_ts:
                        _post_reconnect_candle_seen[ativo] = _last_candle_ts
                    else:
                        # Candle ainda é anterior ao reconnect — aguardar
                        continue
                # else: candle novo já foi visto para este ativo, pode continuar

            if not passes_all_regime_filters(tf_min, velas):
                if tf_min == 5 and M5_POOL_DYNAMIC_ENABLE:
                    _m5_track("blocked", ativo)
                continue

            if pend is not None and pend_id is not None:
                # M5 pending TTL: drop stale pendings whose entry window has already closed.
                #
                # Para arm_sniper: usa timing baseado em candle (velas[-1]["from"]) para
                # determinar secs_from_open de forma robusta, evitando expiry prematura quando
                # a vela alvo ainda não foi entregue pelo feed. Lógica:
                #   - Se velas[-1]["from"] < ecf: vela alvo não chegou → não expirar
                #     (mas expirar se now_ts já passou de um período inteiro após ecf)
                #   - Se velas[-1]["from"] == ecf: vela alvo aberta → secs_from_open = now - ecf
                #   - Se velas[-1]["from"] > ecf: passamos da vela alvo → expirado
                # Para v15/respiro/fallback: comportamento original (now_server > ecf + win).
                # Fallback: wall-clock age > PENDING_MAX_AGE_SECONDS_M5 (ECF ausente/inválido).
                if tf_min == 5:
                    _now_ttl = get_now_ts()
                    try:
                        _ecf_ttl = int(pend.get("expected_confirm_from", 0) or 0)
                    except (ValueError, TypeError):
                        _ecf_ttl = 0  # ECF corrompido → skip ECF-based check
                    _pmode_ttl = pend.get("pattern_mode", "v15")
                    _win_ttl = SNIPER_WINDOW_SECONDS_M5 if _pmode_ttl == "arm_sniper" else ENTRY_WINDOW_SECONDS_M5
                    _latest_candle_ts = int(velas[-1].get("from", 0)) if velas else 0
                    if _ecf_ttl > 0:
                        if _pmode_ttl == "arm_sniper":
                            # Candle-based expiry: só expira quando confirmado pelo feed
                            if _latest_candle_ts > _ecf_ttl:
                                # Vela alvo ficou para trás — realmente expirado
                                _ecf_expired = True
                                _secs_fo_ttl = _now_ttl - _ecf_ttl
                            elif _latest_candle_ts == _ecf_ttl:
                                # Vela alvo confirmada pelo feed — usar secs_from_open real
                                _secs_fo_ttl = _now_ttl - _latest_candle_ts
                                _ecf_expired = _secs_fo_ttl > _win_ttl
                            else:
                                # Vela alvo ainda não chegou no feed — não expirar ainda
                                # Segurança: se now_ts já passou do período inteiro, expirar
                                _secs_fo_ttl = _now_ttl - _ecf_ttl
                                _ecf_expired = _now_ttl >= _ecf_ttl + period
                        else:
                            _secs_fo_ttl = _now_ttl - _ecf_ttl
                            _ecf_expired = _now_ttl > _ecf_ttl + _win_ttl
                    else:
                        _ecf_expired = False
                        _secs_fo_ttl = 0
                    # Fallback wall-clock guard (only when ECF is unknown/zero)
                    _pend_detected_ts = pend.get("detected_ts") or 0.0
                    _pend_age = (time.time() - _pend_detected_ts) if _pend_detected_ts > 0 else 0.0
                    _age_expired = (
                        _ecf_ttl == 0
                        and PENDING_MAX_AGE_SECONDS_M5 > 0
                        and _pend_age > PENDING_MAX_AGE_SECONDS_M5
                    )
                    if _ecf_expired or _age_expired:
                        _timeout_reason = (
                            f"ecf_window_closed ecf={_ecf_ttl} win={_win_ttl} "
                            f"now={_now_ttl} candle_open_ts={_latest_candle_ts} "
                            f"secs_from_open={_secs_fo_ttl}"
                            if _ecf_expired
                            else f"age_guard secs_elapsed={_pend_age:.1f} max={PENDING_MAX_AGE_SECONDS_M5}"
                        )
                        _log_blocked(
                            "pending_timeout",
                            f"ativo={ativo} tf={tf_min} "
                            f"dir={pend.get('direction_hint', '?')} "
                            f"patt={pend.get('pattern_name', '?')} "
                            f"mode={_pmode_ttl} "
                            f"pattern_from={pend.get('pattern_from', '')} "
                            f"expected_confirm_from={_ecf_ttl} "
                            f"reason={_timeout_reason}"
                        )
                        _log_sinal(ativo, tf_min, "pending_timeout", pend,
                                   block_reason="pending_timeout",
                                   details=_timeout_reason)
                        if M5_POOL_DYNAMIC_ENABLE:
                            _m5_track("pending_timeout", ativo)
                        per_asset_pending[ativo] = None
                        per_asset_pending_id[ativo] = None
                        per_asset_lock_until[ativo] = now_server + period
                        continue

                if per_asset_last_pend_status_id[ativo] != pend_id:
                    per_asset_last_pend_status_id[ativo] = pend_id
                    console_event(
                        f"🕯️ [{display_asset_name(ativo)}] {pend['pattern_name']} pendente "
                        f"(aguardando confirmação)"
                    )

                status, direction = confirm_pending(tf_min, pend, velas)

                if status == "waiting":
                    continue

                if status in ("expired", "rejected", "error"):
                    _log_pattern_row(ativo, tf_min, status, pend, block_reason=status)
                    _log_sinal(ativo, tf_min, status, pend, block_reason=status)
                    if tf_min == 5 and M5_POOL_DYNAMIC_ENABLE:
                        if status == "rejected":
                            _m5_track("rejected", ativo)
                        else:
                            _m5_track("expired", ativo)
                    per_asset_pending[ativo] = None
                    per_asset_pending_id[ativo] = None
                    per_asset_lock_until[ativo] = now_server + period
                    continue

                if status == "confirmed" and direction in ("call", "put"):
                    patt = pend["pattern_name"]
                    _detect_ts_c = pend.get("detected_ts", 0.0)
                    _det_to_conf_c = f"{time.time() - _detect_ts_c:.1f}s" if _detect_ts_c else "?"
                    _log_pattern_row(ativo, tf_min, "confirmed", pend, confirmed=True)
                    _log_sinal(ativo, tf_min, "confirmed", pend)
                    if tf_min == 5 and M5_POOL_DYNAMIC_ENABLE:
                        _m5_track("confirmed", ativo)

                    ok_win, sec, win = within_entry_window(tf_min)
                    if not ok_win:
                        _log_blocked(
                            "missed_early_entry",
                            f"ativo={ativo} tf={tf_min} "
                            f"dir={direction} patt={patt} mode={pend.get('pattern_mode', '?')} "
                            f"pattern_from={pend.get('pattern_from', '')} "
                            f"secs_elapsed={sec} window={win} "
                            f"BUY_LATENCY_AVG={BUY_LATENCY_AVG:.3f}"
                        )
                        _log_sinal(ativo, tf_min, "missed_early_entry", pend,
                                   block_reason="missed_early_entry",
                                   details=f"sec={sec} win={win}")
                        if tf_min == 5 and M5_POOL_DYNAMIC_ENABLE:
                            _m5_track("missed", ativo)
                        per_asset_pending[ativo] = None
                        per_asset_pending_id[ativo] = None
                        per_asset_lock_until[ativo] = now_server + period
                        continue

                    if BUY_LATENCY_AVG + BUY_LATENCY_MARGIN >= (win - sec):
                        _log_blocked("latency_guard", f"ativo={ativo} tf={tf_min}")
                        _log_sinal(ativo, tf_min, "latency_guard", pend, block_reason="latency_guard")
                        if tf_min == 5 and M5_POOL_DYNAMIC_ENABLE:
                            _m5_track("latency_guard", ativo)
                        per_asset_pending[ativo] = None
                        per_asset_pending_id[ativo] = None
                        per_asset_lock_until[ativo] = now_server + period
                        continue

                    if not can_purchase_now(ativo, period_minutes=tf_min, chave_preferida=ativo_chave):
                        _log_blocked("purchase_buffer", f"ativo={ativo} tf={tf_min}")
                        per_asset_pending[ativo] = None
                        per_asset_pending_id[ativo] = None
                        per_asset_lock_until[ativo] = now_server + period
                        continue

                    # Signal is valid — collect for best-signal selection (executed below)
                    _v15_score_c = pend.get("v15_score", 0)
                    confirmed_this_cycle.append(
                        (_v15_score_c, sec, ativo, ativo_chave, direction, pend, _det_to_conf_c)
                    )
                    # Do NOT clear pending here — handled in selection block below

            if now_server < lock_until:
                continue

            sig = check_patterns(tf_min, velas)
            if not sig:
                continue

            patt = sig["pattern_name"]
            patt_from = int(sig["pattern_from"])
            new_pend_id = (patt, patt_from, ativo, tf_min)

            last_p = asset_last_pending_print.get(new_pend_id, 0.0)
            nowt = time.time()
            if nowt - last_p >= PENDING_PRINT_THROTTLE_S:
                console_event(
                    f"🕯️ [{display_asset_name(ativo)}] Sinal detectado: {patt}. "
                    f"Aguardando confirmação..."
                )
                asset_last_pending_print[new_pend_id] = nowt
                _log_pattern_row(ativo, tf_min, "detected", sig)
                _log_sinal(ativo, tf_min, "detected", sig)

            sig["detected_ts"] = time.time()
            per_asset_pending[ativo] = sig
            per_asset_pending_id[ativo] = new_pend_id
            per_asset_lock_until[ativo] = int(sig["expected_confirm_from"]) + period
            if tf_min == 5 and M5_POOL_DYNAMIC_ENABLE:
                _m5_track("detected", ativo)

        # Best-signal selection: when multiple signals are confirmed simultaneously in M5,
        # choose the ONE with the highest V15 score (tiebreak: fewest seconds into candle).
        # For M1 (fast TF) all confirmed signals are allowed (max 2 assets anyway).
        if confirmed_this_cycle:
            if tf_min == 5 and len(confirmed_this_cycle) > 1:
                # Sort: highest v15_score first, then lowest sec_in_candle (closest to open)
                confirmed_this_cycle.sort(key=lambda x: (-x[0], x[1]))
                for _, _, skip_a, _, _, skip_pend, _ in confirmed_this_cycle[1:]:
                    console_event(
                        f"⏭️ [{display_asset_name(skip_a)}] Sinal ignorado — "
                        f"melhor sinal selecionado: {confirmed_this_cycle[0][2]} "
                        f"(score={confirmed_this_cycle[0][0]})"
                    )
                    _log_sinal(skip_a, tf_min, "skipped", skip_pend,
                               block_reason="best_signal_selected",
                               details=f"best={confirmed_this_cycle[0][2]} score={confirmed_this_cycle[0][0]}")
                    if tf_min == 5 and M5_POOL_DYNAMIC_ENABLE:
                        _m5_track("missed", skip_a)
                    per_asset_pending[skip_a] = None
                    per_asset_pending_id[skip_a] = None
                    per_asset_lock_until[skip_a] = now_server + period

            # Execute the selected (best or only) confirmed signal
            _bs_score, _bs_sec, _bs_ativo, _bs_chave, _bs_dir, _bs_pend, _bs_d2c = confirmed_this_cycle[0]
            _bs_patt = _bs_pend["pattern_name"]

            # ARM + SNIPER: re-verificar que a janela de 0–5s não expirou entre a
            # confirmação e este ponto (o loop por ativos pode levar alguns segundos).
            _bs_pend_mode = _bs_pend.get("pattern_mode", "v15")
            _sniper_abort = False
            if _bs_pend_mode == "arm_sniper":
                _ecf_buy = int(_bs_pend.get("expected_confirm_from", 0))
                _secs_in_at_buy = now_server - _ecf_buy
                _sniper_win_buy = SNIPER_WINDOW_SECONDS_M5 if tf_min == 5 else SNIPER_WINDOW_SECONDS_M1
                if _secs_in_at_buy > _sniper_win_buy:
                    _log_blocked(
                        "sniper_window_expired_at_buy",
                        f"ativo={_bs_ativo} tf={tf_min} "
                        f"secs_in={_secs_in_at_buy} window={_sniper_win_buy}",
                    )
                    _log_sinal(
                        _bs_ativo, tf_min, "sniper_window_expired_at_buy", _bs_pend,
                        block_reason="sniper_window_expired_at_buy",
                        details=f"secs_in={_secs_in_at_buy}",
                    )
                    per_asset_pending[_bs_ativo] = None
                    per_asset_pending_id[_bs_ativo] = None
                    per_asset_lock_until[_bs_ativo] = now_server + period
                    _sniper_abort = True

            if not _sniper_abort:
                saldo_before = get_available_balance() or 0.0
                # Entrada única e certeira: amount fixo por sinal, sem progressão de stake.
                # Cada sinal gera no máximo UMA ordem. Não há Martingale, Soros ou Recovery.
                amount_to_use = compute_amount(saldo_before)
                secs_left = seconds_left_in_period(tf_min)

                # Re-verificar digital/binária antes de cada entrada (respeitando modo OTC/mercado)
                # Em modo misto (OTC + mercado aberto): determina o mercado pelo sufixo do ativo
                # para não forçar -OTC em ativos -OP ou vice-versa.
                # Em modo exclusivo (apenas OTC ou apenas open): usa o flag global `use_otc`.
                _asset_otc_mode = use_otc if not allow_open_market else ('-OTC' in _bs_ativo.upper())
                trade_ativo, trade_chave = resolve_trade_variant(_bs_ativo, _bs_chave, use_otc=_asset_otc_mode)
                market_type_label = "DIGITAL" if trade_chave == 'digital' else "BINÁRIA"

                console_event(
                    f"🕯️ [{server_hhmmss()}] [{display_asset_name(_bs_ativo)}] Sinal confirmado: {_bs_patt} | "
                    f"⏱️ det→conf={_bs_d2c} | "
                    f"Entrada: {cgreen('CALL 📈') if _bs_dir == 'call' else cred('PUT 📉')} | "
                    f"${amount_to_use:.2f} | "
                    f"Mercado: {market_type_label} ({display_asset_name(trade_ativo)}) | secs_left={secs_left} | "
                    f"Entradas: {entries_accepted}" + (f"/{max_entries}" if max_entries > 0 else "/∞")
                )

                # Log acionável: registra a decisão de entrar ANTES do envio da ordem.
                # Este log persiste mesmo que a ordem seja rejeitada pela corretora.
                _log_sinal_acionavel(
                    _bs_ativo, tf_min, _bs_dir, _bs_pend,
                    entra_em_ts=_bs_pend.get("expected_confirm_from"),
                )

                _buy_start_ts = time.time()
                result_container: Dict[str, Any] = {}
                ev = threading.Event()
                if USE_BUY_THREAD:
                    t = threading.Thread(
                        target=_buy_worker,
                        args=(_bs_dir, trade_ativo, amount_to_use, expiration, result_container, ev, trade_chave),
                        daemon=True
                    )
                    t.start()
                    ev.wait(timeout=25.0)
                else:
                    status_b, info_b = _do_buy_minimal(amount_to_use, trade_ativo, _bs_dir, expiration, trade_chave)
                    result_container["res"] = {
                        "success": bool(status_b),
                        "order_id": info_b if status_b else None,
                        "info": info_b,
                    }
                _buy_elapsed = f"{time.time() - _buy_start_ts:.2f}s"

                res = result_container.get("res", {})
                if not res.get("success"):
                    if trade_chave == 'digital':
                        console_event(
                            cyellow(f"⚠️ [{server_hhmmss()}] [{display_asset_name(_bs_ativo)}] "
                            f"Falha ao enviar ordem (DIGITAL). Tentando binária como fallback...")
                        )
                    else:
                        console_event(
                            cyellow(f"⚠️ [{server_hhmmss()}] [{display_asset_name(_bs_ativo)}] Falha ao enviar ordem.")
                        )
                    # Se falhou no digital, tentar binária como fallback (respeitando modo OTC/mercado)
                    if trade_chave == 'digital':
                        fb_name, fb_chave = find_preferred_variant_with_rules(
                            _normalize_asset_name(re.sub(r'[-]?(OTC|OP)$', '', _bs_ativo.upper())),
                            allow_otc=_asset_otc_mode
                        )
                        if fb_name and fb_chave and fb_chave != 'digital':
                            # Em modo sniper, verificar se ainda há janela antes do fallback binário
                            _fb_sniper_ok = True
                            if _bs_pend_mode == "arm_sniper":
                                _ecf_fb = int(_bs_pend.get("expected_confirm_from", 0))
                                _secs_fb = now_server - _ecf_fb
                                _sniper_win_fb = SNIPER_WINDOW_SECONDS_M5 if tf_min == 5 else SNIPER_WINDOW_SECONDS_M1
                                if _secs_fb > _sniper_win_fb:
                                    _log_blocked(
                                        "sniper_window_expired_at_fallback_buy",
                                        f"ativo={_bs_ativo} tf={tf_min} secs_fb={_secs_fb}",
                                    )
                                    _fb_sniper_ok = False
                            if _fb_sniper_ok:
                                fb_container: Dict[str, Any] = {}
                                fb_ev = threading.Event()
                                if USE_BUY_THREAD:
                                    fb_t = threading.Thread(
                                        target=_buy_worker,
                                        args=(_bs_dir, fb_name, amount_to_use, expiration, fb_container, fb_ev, fb_chave),
                                        daemon=True
                                    )
                                    fb_t.start()
                                    fb_ev.wait(timeout=25.0)
                                else:
                                    fb_s, fb_i = _do_buy_minimal(amount_to_use, fb_name, _bs_dir, expiration, fb_chave)
                                    fb_container["res"] = {"success": bool(fb_s), "order_id": fb_i if fb_s else None, "info": fb_i}
                                fb_res = fb_container.get("res", {})
                                if fb_res.get("success"):
                                    res = fb_res
                                    trade_ativo = fb_name
                                    trade_chave = fb_chave
                                    market_type_label = "BINÁRIA"
                                    console_event(
                                        ccyan(f"✅ [{server_hhmmss()}] Fallback BINÁRIA aceito: {display_asset_name(fb_name)}")
                                    )
                    if not res.get("success"):
                        per_asset_pending[_bs_ativo] = None
                        per_asset_pending_id[_bs_ativo] = None
                        _replace_asset(_bs_ativo)
                else:
                    # Chegamos aqui apenas quando res.get("success") é True
                    order_id = res.get("order_id")
                    if order_id is not None:
                        entries_accepted += 1
                        # Log compacto apenas de entradas efetivamente emitidas
                        _log_sinal_confirmado(
                            _bs_ativo, tf_min, _bs_dir, _bs_pend,
                            entra_em_ts=_bs_pend.get("expected_confirm_from"),
                        )
                    console_event(
                        ccyan(f"✅ [{server_hhmmss()}] [{display_asset_name(_bs_ativo)}] Ordem aceita ({market_type_label}) | "
                        f"ID: {order_id} | ⏱️ conf→aceita={_buy_elapsed} | "
                        f"Entradas: {entries_accepted}"
                        + (f"/{max_entries}" if max_entries > 0 else "/∞"))
                    )
                    console_event(
                        f"⏳ [{server_hhmmss()}] [{display_asset_name(_bs_ativo)}] Aguardando resultado..."
                    )

                    t0 = time.time()
                    min_wait = expiration * 60 + RESULT_DELAY_AFTER_EXPIRY_SECONDS
                    while time.time() - t0 < min_wait:
                        time.sleep(0.5)

                    timeout = M5_RESULT_TIMEOUT if expiration == 5 else M1_RESULT_TIMEOUT
                    timeout = max(35, timeout)

                    result = check_order_result(
                        order_id, amount_to_use,
                        saldo_before=saldo_before,
                        timeout_seconds=timeout,
                        poll_interval=2.0,
                    )

                    label = result.get("result", "unknown")
                    profit = result.get("profit")
                    bal_after = result.get("balance_after")
                    method = result.get("method")

                    if label == "win":
                        console_event(
                            cgreen(f"✅ [{server_hhmmss()}] [{display_asset_name(_bs_ativo)}] ")
                            + fmt_result_line(label, profit, method)
                        )
                        if tf_min == 5 and M5_POOL_DYNAMIC_ENABLE:
                            _m5_track("win_trade", _bs_ativo)
                    elif label == "loss":
                        console_event(
                            cred(f"❌ [{server_hhmmss()}] [{display_asset_name(_bs_ativo)}] ")
                            + fmt_result_line(label, profit, method)
                        )
                        if tf_min == 5 and M5_POOL_DYNAMIC_ENABLE:
                            _m5_track("loss_trade", _bs_ativo)
                    else:
                        console_event(
                            f"❓ [{server_hhmmss()}] [{display_asset_name(_bs_ativo)}] "
                            f"{fmt_result_line(label, profit, method)}"
                        )

                    try:
                        if TRADES_CSV is not None:
                            with TRADES_CSV.open('a', newline='', encoding='utf-8') as f:
                                csv.writer(f).writerow([
                                    now_iso(), INSTANCE_TAG,
                                    _bs_ativo, tf_min, ENTRY_MODE, RIGIDEZ_MODE,
                                    _bs_dir, order_id,
                                    method, label, float(profit) if profit is not None else "",
                                    saldo_before, bal_after if bal_after is not None else "",
                                    amount_to_use, f"{BUY_LATENCY_AVG:.6f}",
                                    _bs_patt, _bs_pend.get("pattern_from"),
                                    secs_left,
                                    trade_ativo, trade_chave,
                                    _bs_pend.get("strategy", ""),
                                ])
                    except Exception:
                        pass

                    per_asset_pending[_bs_ativo] = None
                    per_asset_pending_id[_bs_ativo] = None
                    per_asset_lock_until[_bs_ativo] = now_server + period

        # Sleep: use fast freeze sleep during M5 freeze, normal idle otherwise
        if freeze_active:
            time.sleep(PENDING_FREEZE_POLL_SLEEP_M5)
        else:
            time.sleep(IDLE_SLEEP_S_M5 if tf_min == 5 else IDLE_SLEEP_S_M1)

    print(f"✅ Loop multi-ativo finalizado. Entradas aceitas: {entries_accepted}")


# =========================
# MAIN
# =========================
if __name__ == '__main__':
    _mkdirp(LOG_DIR)
    _mkdirp(STATE_DIR)
    _mkdirp(PRESETS_DIR)

    # Carregar parâmetros do config.txt (sobrescreve defaults hardcoded)
    _load_from_config()

    connect()

    print("\n" + "=" * 70)
    print(f"🤖 BOT DINVELAS M1/M5  |  v{BOTDIN_VERSION}")
    print("=" * 70)

    # Conta
    print("\n" + "=" * 70)
    print("💼 CONTA")
    print("=" * 70)
    print("  1) " + ccyan("DEMO") + "  (conta prática — sem risco real)")
    print("  2) " + cyellow("REAL") + "  (conta real — opera com dinheiro real)")
    while True:
        escolha = input('\n👉 Selecione o tipo de conta [1]: ').strip() or "1"
        if escolha == "1":
            conta = 'PRACTICE'
            break
        if escolha == "2":
            conta = 'REAL'
            break
        print(cyellow('❌ Opção inválida! Digite 1 (DEMO) ou 2 (REAL).'))
    API.change_balance(conta)
    conta_label = ccyan("DEMO") if conta == 'PRACTICE' else cyellow("REAL")
    print(f"✅ Conta selecionada: {conta_label}")

    # Timeframe (M1 ou M5)
    TIMEFRAME_MINUTES = ask_timeframe()

    # Tipo de mercado
    # M5: seleção interativa de perfil (OTC / OPEN / MISTO) com carregamento de thresholds
    # M1: seleção interativa (OTC ou Mercado Aberto)
    if TIMEFRAME_MINUTES == 5:
        use_otc, allow_open_market, active_profile = ask_market_profile_m5()
        if use_otc and allow_open_market:
            market_label = "OTC + Mercado Aberto (misto)"
        elif use_otc:
            market_label = "OTC"
        else:
            market_label = "Mercado Aberto"
        print(f"\n🌍 M5 Mercado (perfil {active_profile}): {market_label}")
        if not use_otc and not allow_open_market:
            print("\n⚠️  AVISO: nenhum mercado habilitado — verifique [PROFILE_*] no config.txt.")
            sys.exit(1)
    else:
        use_otc = ask_market_type()
        # M1 usa seleção exclusiva: OTC OU mercado aberto, nunca os dois simultaneamente.
        allow_open_market = not use_otc
        market_label = "OTC" if use_otc else "Mercado Aberto"
        active_profile = "OTC" if use_otc else "OPEN"

    # ─── RESTRIÇÃO DE SEGURANÇA: OTC em conta REAL (configurável) ────────
    if conta == 'REAL' and use_otc and not ALLOW_OTC_LIVE:
        print("\n" + "=" * 70)
        print("🚫 ATENÇÃO — OPERAÇÃO BLOQUEADA POR SEGURANÇA")
        print("=" * 70)
        print("  Conta REAL + OTC está DESATIVADO nesta configuração.")
        print("  Operações ao vivo em conta real são permitidas somente em")
        print("  Mercado Aberto (ativos -OP), não em OTC.")
        print()
        print("  Para habilitar OTC em conta real, edite config.txt:")
        print("    [MARKET]")
        print("    allow_otc_live = true")
        if TIMEFRAME_MINUTES == 5:
            print("  Ou selecione o perfil OPEN no próximo início.")
        print("=" * 70)
        sys.exit(1)

    # Número de ativos simultâneos
    max_ativos = ask_num_assets(TIMEFRAME_MINUTES)

    # Número máximo de entradas
    MAX_ENTRIES = ask_max_entries()

    # Stops
    ask_stop_loss_win()

    # Valor por operação
    ask_amount_menu()

    # Temporizador de finalização automática
    run_minutes = ask_run_duration()

    # Modo de entrada (reversal / continuation)
    # O menu interativo sobrescreve os defaults do config.txt para a sessão atual.
    # Isso é intencional: o menu dá controle explícito a cada execução.
    ENTRY_MODE = ask_entry_mode()
    # Aplica modo selecionado para ambas as TFs na sessão atual
    ENTRY_MODE_M1 = ENTRY_MODE
    ENTRY_MODE_M5 = ENTRY_MODE

    # Estratégia única: PRIORIDADE DIGITAL
    RIGIDEZ_MODE = "normal"
    _apply_rigidez()

    # Inicializar paths de log com tag automática (antes do ranking para logar seleção)
    if TIMEFRAME_MINUTES == 5:
        if use_otc and allow_open_market:
            market_tag = "misto"
        elif use_otc:
            market_tag = "otc"
        else:
            market_tag = "op"
    else:
        market_tag = "otc" if use_otc else "op"
    auto_tag = f"m{TIMEFRAME_MINUTES}_{market_tag}_{max_ativos}ativos"
    _init_paths_with_tag(auto_tag)
    _ensure_csv_headers()

    # Montar lista de ativos inicial a partir do Ativos.txt.
    # Tenta até _BOOT_MAX_RETRIES vezes quando a API está instável (retorna None).
    # Distingue entre "API degradada" (open_time=None) e "ativo fechado/filtrado"
    # (API respondeu mas nenhum ativo do Ativos.txt passou pelo filtro de mercado).
    print(f"\n🔍 Buscando ativos do Ativos.txt — seções [DIGITAL M{TIMEFRAME_MINUTES}] e [BINARIA M{TIMEFRAME_MINUTES}]...")
    digital_lista_init, binaria_lista_init = load_ativos_por_categoria(TIMEFRAME_MINUTES)
    tf_label_init = f"M{TIMEFRAME_MINUTES}"
    if not digital_lista_init and not binaria_lista_init:
        print(
            f"⚠️  Nenhuma seção [DIGITAL {tf_label_init}] ou [BINARIA {tf_label_init}] "
            "encontrada no Ativos.txt. Verifique o arquivo."
        )

    _BOOT_MAX_RETRIES = BOOT_MAX_RETRIES
    _BOOT_RETRY_SLEEP = BOOT_RETRY_SLEEP_S
    ativos_lista: List[Tuple[str, str]] = []

    for _boot_attempt in range(_BOOT_MAX_RETRIES):
        # Para M5 com pool dinâmico: seleciona pool inicial por ranking (payout + ATR/ADX).
        # Para M1 e M5 sem pool dinâmico: usa build_asset_list em ordem do Ativos.txt.
        if TIMEFRAME_MINUTES == 5 and M5_POOL_DYNAMIC_ENABLE:
            all_candidates = build_candidate_pool(
                use_otc=use_otc, limit=200, tf_min=TIMEFRAME_MINUTES,
                allow_open_market=allow_open_market,
            )
            ativos_lista = _startup_rank_m5_pool(all_candidates, pool_size=max_ativos)
        else:
            ativos_lista = build_asset_list(
                use_otc=use_otc, max_count=max_ativos, tf_min=TIMEFRAME_MINUTES,
                allow_open_market=allow_open_market,
            )

        if ativos_lista:
            break  # Pool montado com sucesso

        # Verifica se a API respondeu: se não, é instabilidade — tenta de novo
        _ot_probe = _safe_get_all_open_time()
        if _ot_probe is None:
            print(
                cyellow(
                    f"⚠️  API instável (tentativa {_boot_attempt + 1}/{_BOOT_MAX_RETRIES}). "
                    f"Aguardando {_BOOT_RETRY_SLEEP:.0f}s antes de tentar novamente..."
                )
            )
            time.sleep(_BOOT_RETRY_SLEEP)
        else:
            # API respondeu, mas nenhum ativo do Ativos.txt passou pelo filtro de mercado.
            # Não adianta repetir — o pool ficará vazio até o mercado abrir ou o usuário
            # ajustar o Ativos.txt / perfil de mercado. Sai do loop de retentativas.
            break

    if not ativos_lista:
        _ot_final = _safe_get_all_open_time()
        if _ot_final is None:
            print(
                cyellow(
                    f"⚠️  API não respondeu após {_BOOT_MAX_RETRIES} tentativas. "
                    "O bot irá iniciar monitorando o pool — os ativos serão adicionados "
                    "automaticamente quando a API estabilizar."
                )
            )
        else:
            print(
                f"⏳ Nenhum ativo da lista Ativos.txt está aberto para o timeframe "
                f"M{TIMEFRAME_MINUTES} escolhido. Verifique o Ativos.txt e o perfil "
                f"de mercado (OTC/OPEN/MISTO). Detalhes em: "
                f"{BLOCKED_LOG.as_posix() if BLOCKED_LOG else 'logs/blocked_reasons_*.log'}"
            )

    nome = get_profile_name()

    print('\n' + '=' * 70)
    print('📋 RESUMO')
    print('=' * 70)
    if nome:
        print(f'👤 Usuário: {nome}')
    print(f'InstanceTag: {INSTANCE_TAG}')
    print(f'Conta: {"DEMO" if conta == "PRACTICE" else "REAL"} | Mercado: {market_label}')
    otc_live_status = "permitido" if ALLOW_OTC_LIVE else "BLOQUEADO (somente demo)"
    print(f'OTC em conta real: {otc_live_status}')
    if TIMEFRAME_MINUTES == 5:
        _m5_otc_flag = "on" if M5_ALLOW_OTC else "off"
        _m5_op_flag = "on" if M5_ALLOW_OPEN_MARKET else "off"
        print(f'M5 Perfil: {active_profile} | m5_allow_otc={_m5_otc_flag} | m5_allow_open_market={_m5_op_flag}')
    modo_label = "REVERSÃO (V15)" if ENTRY_MODE == "reversal" else "CONTINUAÇÃO (Respiro)"
    print(f'Timeframe: M{TIMEFRAME_MINUTES} | Modo: {modo_label} | Carteira: Ativos.txt')
    print(f'Prioridade: [DIGITAL M{TIMEFRAME_MINUTES}] → [BINARIA M{TIMEFRAME_MINUTES}] (fallback apenas se faltar digital aberta)')
    startup_method = "ranking (payout+ATR/ADX)" if (TIMEFRAME_MINUTES == 5 and M5_POOL_DYNAMIC_ENABLE) else "ordem Ativos.txt"
    print(f'Seleção inicial: {startup_method}')
    print(f'Ativos: {len(ativos_lista)}/{max_ativos}')
    print('Ativos selecionados:')
    for a, ak in ativos_lista:
        categoria_label = f"DIGITAL M{TIMEFRAME_MINUTES}" if ak == 'digital' else f"BINARIA M{TIMEFRAME_MINUTES}"
        print(f'  - {display_asset_name(a)} [{categoria_label}]')
    if AMOUNT_MODE == "fixed":
        print(f'Valor por operação: ${AMOUNT_FIXED:.2f} (fixo)')
    else:
        print(f'Valor por operação: {AMOUNT_PERCENT:.2f}% do saldo')
    print(f'StopLoss: {STOP_LOSS_PCT:.2f}% | StopWin: {STOP_WIN_PCT:.2f}%')
    timer_label = f"{run_minutes} min" if run_minutes > 0 else "ilimitado"
    entries_label = str(MAX_ENTRIES) if MAX_ENTRIES > 0 else "ilimitado"
    print(f'Temporizador: {timer_label} | Entradas máx: {entries_label}')
    _sm1 = V15_SCORE_MIN_M1
    _sm5 = V15_SCORE_MIN_M5
    print(f'V15_SCORE_MIN: M1={_sm1} M5={_sm5} | V15_CONFIRM_POLLS: M1={V15_CONFIRM_POLLS_M1} M5={V15_CONFIRM_POLLS_M5}')
    print(f'ADX_M1={ADX_MIN_M1:.1f} ADX_M5={ADX_MIN_M5:.1f} | BB_M1={BB_WIDTH_MIN_M1:.5f} BB_M5={BB_WIDTH_MIN_M5:.5f}')
    print(f'ENTRY_WINDOW: M1={ENTRY_WINDOW_SECONDS_M1}s M5={ENTRY_WINDOW_SECONDS_M5}s')
    _ke_m1 = "on" if KELTNER_ENABLE_M1 else "off"
    _ke_m5 = "on" if KELTNER_ENABLE_M5 else "off"
    _pe_m1 = "on" if PIVOT_ENABLE_M1 else "off"
    _pe_m5 = "on" if PIVOT_ENABLE_M5 else "off"
    _re_m1 = "on" if RESPIRO_ENABLE_M1 else "off"
    _re_m5 = "on" if RESPIRO_ENABLE_M5 else "off"
    print(f'Keltner: M1={_ke_m1} M5={_ke_m5} | Pivot: M1={_pe_m1} M5={_pe_m5} | Respiro: M1={_re_m1} M5={_re_m5}')
    _snm1 = "ATIVO" if SNIPER_MODE_M1 else "off"
    _snm5 = "ATIVO" if SNIPER_MODE_M5 else "off"
    if SNIPER_MODE_M1 or SNIPER_MODE_M5:
        _af_label = (
            f"antifakeout_extreme: M1={'on' if SNIPER_ANTIFAKEOUT_EXTREME_M1 else 'off'} "
            f"M5={'on' if SNIPER_ANTIFAKEOUT_EXTREME_M5 else 'off'}"
        )
        print(
            f'ARM+SNIPER: M1={_snm1}(arm≥{ARM_SCORE_MIN_M1}/fb≥{FALLBACK_ARM_SCORE_MIN_M1}/win={SNIPER_WINDOW_SECONDS_M1}s) '
            f'M5={_snm5}(arm≥{ARM_SCORE_MIN_M5}/fb≥{FALLBACK_ARM_SCORE_MIN_M5}/win={SNIPER_WINDOW_SECONDS_M5}s) '
            f'{_af_label}'
        )
    else:
        print(f'ARM+SNIPER: M1={_snm1} M5={_snm5} (modo padrão V15 confirm-pending)')
    if TIMEFRAME_MINUTES == 5 and M5_POOL_DYNAMIC_ENABLE:
        _scale_label = f"univ_div={M5_POOL_SWAP_UNIVERSE_DIVISOR} max_abs={M5_POOL_SWAP_MAX_ABS}" if M5_POOL_SWAP_SCALE_WITH_UNIVERSE else "scale=off"
        _don_label = f"don={M5_POOL_DEAD_MARKET_DONCHIAN_PERIOD}c@{M5_POOL_DEAD_MARKET_RANGE_RATIO_THR:.3f} pen={M5_POOL_DEAD_MARKET_PENALTY:.1f}" if M5_POOL_DEAD_MARKET_DONCHIAN_PERIOD > 0 else "donchian=off"
        print(
            f'Pool Dinâmico M5: ATIVO | rebalance={M5_POOL_REBALANCE_MINUTES:.0f}min '
            f'dead={M5_POOL_DEAD_MINUTES:.0f}min '
            f'swap_normal={M5_POOL_SWAP_MAX_NORMAL} swap_dead={M5_POOL_SWAP_MAX_DEAD} '
            f'cooldown={M5_POOL_ASSET_COOLDOWN_MINUTES:.0f}min | '
            f'{_scale_label} | {_don_label} | window={M5_POOL_SCORE_WINDOW_MINUTES:.0f}min'
        )
    elif TIMEFRAME_MINUTES == 5:
        print('Pool Dinâmico M5: desativado (pool_dynamic_enable=false)')
    print(f'Logs: {LOG_DIR.as_posix()}/ | State: {STATE_DIR.as_posix()}/')
    if SINAIS_CONFIRMADOS_LOG is not None:
        print(f'Sinais confirmados (ordens aceitas): {SINAIS_CONFIRMADOS_LOG.as_posix()}')
    if SINAIS_ACIONAVEIS_LOG is not None:
        print(f'Sinais acionáveis (decisão de entrar): {SINAIS_ACIONAVEIS_LOG.as_posix()}')
    print('=' * 70)
    print('\n🚀 Iniciando...\n')

    try:
        loop_patterns_multi(
            ativos_lista,
            tf_min=TIMEFRAME_MINUTES,
            max_ativos=max_ativos,
            use_otc=use_otc,
            allow_open_market=allow_open_market,
            run_minutes=run_minutes,
            max_entries=MAX_ENTRIES,
        )
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário.")
    except Exception as e:
        _log_error("Erro inesperado no loop principal.", e)
        print("\n❌ Ocorreu um erro. Veja logs/runtime_errors_*.log")
    finally:
        print("✅ Bot finalizado.")