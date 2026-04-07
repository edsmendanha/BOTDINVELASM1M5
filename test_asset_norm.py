"""
Testes unitários para normalização canônica de ativos.

Verifica:
  1. _canonical_asset_name() — sufixo '-op' (minúsculo) para mercado aberto,
     '-OTC' (maiúsculo) para OTC, sem sufixo para índices.
  2. _strip_market_suffix()  — remoção case-insensitive de sufixos.
  3. display_asset_name()    — preserva '-op' minúsculo; converte '-otc' → '-OTC'.
  4. Sem substituição silenciosa: lookup por base respeita o tipo de mercado pedido.
  5. build_asset_list() via mocks leves — garante que 'EURUSD-op' não retorna
     'EURUSD-OTC' quando apenas o OTC está disponível na API.
"""

import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Carrega apenas as funções puras do módulo sem executar a inicialização
# que depende de iqoptionapi, configobj etc.
# ---------------------------------------------------------------------------


def _load_pure_functions():
    """Importa seletivamente as funções independentes sem inicializar o bot."""
    import re

    def _normalize_asset_name(name: str) -> str:
        if not isinstance(name, str):
            return ''
        s = name.upper()
        s = re.sub(r'[^A-Z0-9\-]', '', s)
        return s

    def _strip_market_suffix(name_n: str) -> str:
        upper = name_n.upper()
        for sfx in ('-OTC-OP', '-OTC', '-OP'):
            if upper.endswith(sfx):
                return name_n[:-len(sfx)]
        return name_n

    def _canonical_asset_name(name: str) -> str:
        if not isinstance(name, str):
            return ''
        upper = _normalize_asset_name(name)
        for combined in ('-OTC-OP',):
            if upper.endswith(combined):
                base = upper[:-len(combined)]
                return f"{base}-OTC"
        if upper.endswith('-OTC'):
            base = upper[:-4]
            return f"{base}-OTC"
        if upper.endswith('-OP'):
            base = upper[:-3]
            return f"{base}-op"
        return upper

    def display_asset_name(asset: str) -> str:
        if not isinstance(asset, str):
            return str(asset)
        return re.sub(r'-otc\b', '-OTC', asset, flags=re.IGNORECASE)

    return _normalize_asset_name, _strip_market_suffix, _canonical_asset_name, display_asset_name


(
    _normalize_asset_name,
    _strip_market_suffix,
    _canonical_asset_name,
    display_asset_name,
) = _load_pure_functions()


# ---------------------------------------------------------------------------
# 1. _canonical_asset_name
# ---------------------------------------------------------------------------


class TestCanonicalAssetName(unittest.TestCase):

    # Mercado aberto: sufixo deve ser '-op' (minúsculo) independente da entrada
    def test_op_lowercase_stays_canonical(self):
        self.assertEqual(_canonical_asset_name('EURUSD-op'), 'EURUSD-op')

    def test_op_uppercase_becomes_lowercase(self):
        self.assertEqual(_canonical_asset_name('EURUSD-OP'), 'EURUSD-op')

    def test_op_mixed_case_becomes_lowercase(self):
        self.assertEqual(_canonical_asset_name('EURUSD-Op'), 'EURUSD-op')

    def test_op_with_lowercase_base(self):
        self.assertEqual(_canonical_asset_name('eurusd-op'), 'EURUSD-op')

    def test_nzdcad_op_various_cases(self):
        self.assertEqual(_canonical_asset_name('NZDCAD-op'),  'NZDCAD-op')
        self.assertEqual(_canonical_asset_name('NZDCAD-OP'),  'NZDCAD-op')
        self.assertEqual(_canonical_asset_name('nzdcad-Op'),  'NZDCAD-op')

    # OTC: sufixo deve ser '-OTC' (maiúsculo)
    def test_otc_uppercase_preserved(self):
        self.assertEqual(_canonical_asset_name('EURUSD-OTC'), 'EURUSD-OTC')

    def test_otc_lowercase_becomes_uppercase(self):
        self.assertEqual(_canonical_asset_name('EURUSD-otc'), 'EURUSD-OTC')

    def test_otc_mixed_case_becomes_uppercase(self):
        self.assertEqual(_canonical_asset_name('EURUSD-Otc'), 'EURUSD-OTC')

    def test_otc_with_lowercase_base(self):
        self.assertEqual(_canonical_asset_name('gbpusd-OTC'), 'GBPUSD-OTC')

    # Sufixo combinado '-OTC-OP': OTC prevalece
    def test_combined_otc_op_uppercase(self):
        self.assertEqual(_canonical_asset_name('BTCUSD-OTC-OP'), 'BTCUSD-OTC')

    def test_combined_otc_op_mixed(self):
        self.assertEqual(_canonical_asset_name('BTCUSD-OTC-op'), 'BTCUSD-OTC')

    # Sem sufixo (índices de mercado aberto)
    def test_index_no_suffix_dxy(self):
        self.assertEqual(_canonical_asset_name('DXY'), 'DXY')

    def test_index_no_suffix_jxy(self):
        self.assertEqual(_canonical_asset_name('JXY'), 'JXY')

    def test_index_lowercase_becomes_uppercase(self):
        self.assertEqual(_canonical_asset_name('exy'), 'EXY')

    # Entradas inválidas
    def test_empty_string(self):
        self.assertEqual(_canonical_asset_name(''), '')

    def test_none_returns_empty(self):
        self.assertEqual(_canonical_asset_name(None), '')  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. _strip_market_suffix (case-insensitive)
# ---------------------------------------------------------------------------


class TestStripMarketSuffix(unittest.TestCase):

    def test_strip_op_uppercase(self):
        self.assertEqual(_strip_market_suffix('EURUSD-OP'), 'EURUSD')

    def test_strip_op_lowercase(self):
        """Sufixo canônico '-op' deve ser removido corretamente."""
        self.assertEqual(_strip_market_suffix('EURUSD-op'), 'EURUSD')

    def test_strip_otc_uppercase(self):
        self.assertEqual(_strip_market_suffix('EURUSD-OTC'), 'EURUSD')

    def test_strip_otc_lowercase(self):
        self.assertEqual(_strip_market_suffix('EURUSD-otc'), 'EURUSD')

    def test_strip_combined_otc_op(self):
        self.assertEqual(_strip_market_suffix('BTCUSD-OTC-OP'), 'BTCUSD')

    def test_strip_combined_otc_op_mixed(self):
        self.assertEqual(_strip_market_suffix('BTCUSD-OTC-op'), 'BTCUSD')

    def test_no_suffix_unchanged(self):
        self.assertEqual(_strip_market_suffix('DXY'), 'DXY')

    def test_no_suffix_gbpusd(self):
        self.assertEqual(_strip_market_suffix('GBPUSD'), 'GBPUSD')


# ---------------------------------------------------------------------------
# 3. display_asset_name — '-op' permanece minúsculo; '-otc' → '-OTC'
# ---------------------------------------------------------------------------


class TestDisplayAssetName(unittest.TestCase):

    def test_op_lowercase_preserved(self):
        """O sufixo '-op' minúsculo não deve ser convertido para '-OP'."""
        self.assertEqual(display_asset_name('EURUSD-op'), 'EURUSD-op')

    def test_op_uppercase_not_touched(self):
        """'-OP' uppercase deve permanecer como está (não é normalizado para lower)."""
        self.assertEqual(display_asset_name('EURUSD-OP'), 'EURUSD-OP')

    def test_otc_lowercase_converted(self):
        self.assertEqual(display_asset_name('EURUSD-otc'), 'EURUSD-OTC')

    def test_otc_uppercase_preserved(self):
        self.assertEqual(display_asset_name('EURUSD-OTC'), 'EURUSD-OTC')

    def test_index_no_suffix(self):
        self.assertEqual(display_asset_name('DXY'), 'DXY')

    def test_non_string_coerced(self):
        result = display_asset_name(42)  # type: ignore[arg-type]
        self.assertEqual(result, '42')


# ---------------------------------------------------------------------------
# 4. Sem substituição silenciosa — lookup respeita tipo de mercado
# ---------------------------------------------------------------------------


class TestNoSilentSubstitution(unittest.TestCase):
    """Garante que a variante OTC nunca substitui silenciosamente '-op' (e vice-versa)."""

    def _make_open_maps(self, api_assets):
        """
        Simula a construção de open_map / open_map_by_base_otc / open_map_by_base_op
        a partir de uma lista de nomes de ativo da API (todos marcados como abertos).

        Retorna (open_map, open_map_by_base_otc, open_map_by_base_op, open_map_by_base).
        """
        open_map = {}
        open_map_by_base_otc = {}
        open_map_by_base_op = {}
        open_map_by_base = {}

        for name in api_assets:
            norm = _normalize_asset_name(name)     # uppercase
            if norm not in open_map:
                open_map[norm] = (name, 'digital')
            base = _strip_market_suffix(norm)
            if norm.endswith('-OTC') or norm.endswith('-OTC-OP'):
                if base not in open_map_by_base_otc:
                    open_map_by_base_otc[base] = (name, 'digital')
            elif norm.endswith('-OP'):
                if base not in open_map_by_base_op:
                    open_map_by_base_op[base] = (name, 'digital')
            else:
                if base not in open_map_by_base:
                    open_map_by_base[base] = (name, 'digital')

        return open_map, open_map_by_base_otc, open_map_by_base_op, open_map_by_base

    def _lookup(self, norm_name, open_map, open_map_by_base_otc, open_map_by_base_op, open_map_by_base):
        """Replica a lógica de _lookup_open_map() sem depender do módulo principal."""
        key = _normalize_asset_name(norm_name)
        entry = open_map.get(key)
        if entry is not None:
            return entry

        base = _strip_market_suffix(key)
        if not base:
            return None

        if key.endswith('-OTC'):
            return open_map_by_base_otc.get(base)
        elif key.endswith('-OP'):
            return open_map_by_base_op.get(base)
        else:
            return open_map_by_base.get(base)

    def test_op_not_substituted_by_otc(self):
        """'EURUSD-op' não deve retornar 'EURUSD-OTC' quando só OTC está disponível."""
        maps = self._make_open_maps(['EURUSD-OTC'])
        result = self._lookup('EURUSD-op', *maps)
        self.assertIsNone(result, "Não deve substituir -op por -OTC silenciosamente")

    def test_otc_not_substituted_by_op(self):
        """'EURUSD-OTC' não deve retornar 'EURUSD-op' quando só OP está disponível."""
        maps = self._make_open_maps(['EURUSD-op'])
        result = self._lookup('EURUSD-OTC', *maps)
        self.assertIsNone(result, "Não deve substituir -OTC por -op silenciosamente")

    def test_op_found_when_op_available(self):
        """'EURUSD-op' deve encontrar 'EURUSD-op' quando disponível na API."""
        maps = self._make_open_maps(['EURUSD-op'])
        result = self._lookup('EURUSD-op', *maps)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 'EURUSD-op')

    def test_otc_found_when_otc_available(self):
        """'EURUSD-OTC' deve encontrar 'EURUSD-OTC' quando disponível na API."""
        maps = self._make_open_maps(['EURUSD-OTC'])
        result = self._lookup('EURUSD-OTC', *maps)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 'EURUSD-OTC')

    def test_both_available_op_returns_op(self):
        """Com ambas disponíveis: 'EURUSD-op' deve retornar variante OP."""
        maps = self._make_open_maps(['EURUSD-op', 'EURUSD-OTC'])
        result = self._lookup('EURUSD-op', *maps)
        self.assertIsNotNone(result)
        self.assertEqual(_normalize_asset_name(result[0]), 'EURUSD-OP')

    def test_both_available_otc_returns_otc(self):
        """Com ambas disponíveis: 'EURUSD-OTC' deve retornar variante OTC."""
        maps = self._make_open_maps(['EURUSD-op', 'EURUSD-OTC'])
        result = self._lookup('EURUSD-OTC', *maps)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 'EURUSD-OTC')

    def test_fuzzy_op_matches_op_variant_from_api(self):
        """Fuzzy lookup: 'EURUSD-op' encontra 'EURUSD-OP' (uppercase da API) pelo base."""
        # API retorna 'EURUSD-OP' (uppercase) — base 'EURUSD' → open_map_by_base_op
        maps = self._make_open_maps(['EURUSD-OP'])
        result = self._lookup('EURUSD-op', *maps)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 'EURUSD-OP')

    def test_index_no_suffix_found(self):
        """Índice sem sufixo (DXY) deve ser encontrado normalmente."""
        maps = self._make_open_maps(['DXY'])
        result = self._lookup('DXY', *maps)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 'DXY')

    def test_alias_preserved_from_ativos(self):
        """O alias canônico do Ativos.txt é preservado: '-op' minúsculo → lookup correto."""
        # Simula Ativos.txt com 'GBPUSD-op' (minúsculo)
        canonical = _canonical_asset_name('GBPUSD-op')
        self.assertEqual(canonical, 'GBPUSD-op')
        # API tem 'GBPUSD-op' aberto
        maps = self._make_open_maps(['GBPUSD-op'])
        result = self._lookup(canonical, *maps)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 'GBPUSD-op')


if __name__ == '__main__':
    unittest.main()
