#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VerificaAtivos.py — Utilitário de verificação de ativos IQ Option.

Conecta-se à IQ Option, chama get_all_open_time() e exibe os ativos
ABERTOS por categoria (digital / binary) e tipo de mercado (-OP / -OTC),
usando as mesmas regras de sufixo e normalização do BOTDINVELAS_M1M5.py.

Uso:
    python VerificaAtivos.py

O script lê credenciais de config.txt [LOGIN] e termina automaticamente
após exibir o relatório de ativos disponíveis.
"""

import re
import sys
import time
from configobj import ConfigObj
from iqoptionapi.stable_api import IQ_Option


# ---------------------------------------------------------------------------
# Leitura de credenciais
# ---------------------------------------------------------------------------

config = ConfigObj("config.txt")
try:
    EMAIL = config["LOGIN"]["email"].strip()
    SENHA = config["LOGIN"]["senha"].strip()
except (KeyError, TypeError):
    print("❌ config.txt não encontrado ou sem seção [LOGIN] com email/senha.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers de normalização (idênticos ao BOTDINVELAS_M1M5.py)
# ---------------------------------------------------------------------------

def _normalize_asset_name(name: str) -> str:
    """Remove caracteres especiais e converte para maiúsculo."""
    if not isinstance(name, str):
        return ""
    s = name.upper()
    s = re.sub(r"[^A-Z0-9\-]", "", s)
    return s


def _strip_market_suffix(name_n: str) -> str:
    """Remove sufixos de mercado conhecidos (-OTC-OP, -OTC, -OP) case-insensitively."""
    upper = name_n.upper()
    for sfx in ("-OTC-OP", "-OTC", "-OP"):
        if upper.endswith(sfx):
            return name_n[: -len(sfx)]
    return name_n


def _canonical_suffix(api_name: str) -> str:
    """Retorna o sufixo canônico de um nome da API: '-op', '-OTC' ou '' (sem sufixo).

    Usa as mesmas regras do BOTDINVELAS_M1M5.py:
      - Sufixo de mercado aberto → '-op' (minúsculo)
      - Sufixo OTC               → '-OTC' (maiúsculo)
      - Sem sufixo               → '' (índices como DXY)
    """
    upper = _normalize_asset_name(api_name)
    if upper.endswith("-OTC-OP") or upper.endswith("-OTC"):
        return "-OTC"
    if upper.endswith("-OP"):
        return "-op"
    return ""


def _market_type(api_name: str) -> str:
    """Retorna 'otc', 'op' ou 'index' para classificação de mercado."""
    sfx = _canonical_suffix(api_name)
    if sfx == "-OTC":
        return "otc"
    if sfx == "-op":
        return "op"
    return "index"


# ---------------------------------------------------------------------------
# Conexão
# ---------------------------------------------------------------------------

def _connect(email: str, senha: str, max_attempts: int = 3) -> IQ_Option:
    """Conecta à IQ Option com retry simples. Encerra o script em caso de falha."""
    print(f"🔗 Conectando como {email}...")
    api = IQ_Option(email, senha)
    for attempt in range(1, max_attempts + 1):
        try:
            ok, reason = api.connect()
            if ok:
                print("✅ Conectado.\n")
                return api
            print(f"  Tentativa {attempt}/{max_attempts} falhou: {reason}")
        except Exception as exc:
            print(f"  Tentativa {attempt}/{max_attempts} erro: {exc}")
        if attempt < max_attempts:
            time.sleep(3)
    print("❌ Não foi possível conectar. Verifique email/senha no config.txt.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Descoberta de ativos
# ---------------------------------------------------------------------------

def _get_all_open_time(api: IQ_Option, max_retries: int = 3):
    """Chama get_all_open_time() com retry automático."""
    for attempt in range(max_retries):
        try:
            result = api.get_all_open_time()
            if result is not None:
                return result
        except Exception as exc:
            print(f"  get_all_open_time() tentativa {attempt + 1}/{max_retries}: {exc}")
        if attempt < max_retries - 1:
            time.sleep(1)
    print("❌ get_all_open_time() falhou após todas as tentativas.")
    return None


def _collect_open_assets(open_times: dict) -> dict:
    """Coleta ativos abertos por categoria e tipo de mercado.

    Retorna um dicionário estruturado:
        {
            'digital': {
                'op':    [(api_name, base), ...],   # ativos -OP abertos
                'otc':   [(api_name, base), ...],   # ativos -OTC abertos
                'index': [(api_name, base), ...],   # índices sem sufixo
            },
            'binary': { ... },
        }
    """
    result = {}
    for categoria in ("digital", "binary"):
        table = open_times.get(categoria, {})
        if not isinstance(table, dict):
            continue
        entry = {"op": [], "otc": [], "index": []}
        for name, info in table.items():
            if not (isinstance(info, dict) and info.get("open")):
                continue
            mtype = _market_type(name)
            base = _strip_market_suffix(_normalize_asset_name(name))
            entry[mtype].append((name, base))
        # Ordena por base para facilitar leitura
        for k in entry:
            entry[k].sort(key=lambda x: x[1])
        result[categoria] = entry
    return result


# ---------------------------------------------------------------------------
# Exibição
# ---------------------------------------------------------------------------

def _print_section(title: str, assets: list) -> None:
    print(f"  {title} ({len(assets)}):")
    if not assets:
        print("    (nenhum)")
    else:
        # Exibe em colunas de 3
        names = [n for n, _ in assets]
        col_w = max(len(n) for n in names) + 2
        cols = 3
        for i in range(0, len(names), cols):
            row = names[i : i + cols]
            print("    " + "".join(n.ljust(col_w) for n in row))
    print()


def _print_report(open_assets: dict) -> None:
    """Exibe relatório de ativos abertos por categoria e tipo de mercado."""
    print("=" * 64)
    print("  ATIVOS ABERTOS — IQ Option (via get_all_open_time())")
    print("=" * 64)

    for categoria in ("digital", "binary"):
        cat_data = open_assets.get(categoria)
        if cat_data is None:
            print(f"\n[{categoria.upper()}] — categoria não retornada pela API.\n")
            continue

        total = sum(len(v) for v in cat_data.values())
        print(f"\n[{categoria.upper()}] — {total} ativo(s) aberto(s)\n")
        _print_section("Mercado Aberto (-op)", cat_data.get("op", []))
        _print_section("OTC (-OTC)", cat_data.get("otc", []))
        _print_section("Índices (sem sufixo)", cat_data.get("index", []))

    print("=" * 64)


def _print_profile_summary(open_assets: dict) -> None:
    """Exibe resumo rápido de quantos ativos estão disponíveis por perfil."""
    print("\nResumo por perfil do bot:")
    print("-" * 36)

    # Conta por categoria e tipo
    for cat in ("digital", "binary"):
        data = open_assets.get(cat, {})
        n_op  = len(data.get("op",  []))
        n_otc = len(data.get("otc", []))
        n_idx = len(data.get("index", []))
        print(f"  [{cat.upper()}]")
        print(f"    PROFILE_OPEN  (-op):   {n_op} ativo(s)")
        print(f"    PROFILE_OTC   (-OTC):  {n_otc} ativo(s)")
        print(f"    PROFILE_MISTO (ambos): {n_op + n_otc + n_idx} ativo(s)")
        print()

    print("Dica: use Ativos.txt com sufixo explícito (-op ou -OTC) para")
    print("evitar ambiguidade. Perfil MISTO faz fallback automático entre")
    print("-op e -OTC quando um dos mercados estiver fechado.\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    api = _connect(EMAIL, SENHA)

    print("📋 Consultando ativos disponíveis (get_all_open_time)...")
    open_times = _get_all_open_time(api)
    if open_times is None:
        sys.exit(1)

    open_assets = _collect_open_assets(open_times)
    _print_report(open_assets)
    _print_profile_summary(open_assets)


if __name__ == "__main__":
    main()
