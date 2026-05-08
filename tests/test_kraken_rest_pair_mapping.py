"""
test_kraken_rest_pair_mapping.py

KRAKEN REST PAIR MAPPING CONTRACT — CITADEL GRADE

Tests that PollingClient correctly maps canonical slash-form symbols
to Kraken REST API format (e.g., BTC/USD → XBTUSD) while preserving
canonical identity internally.

This is an adapter-seam regression test only. It does not assert anything
about canonical identity — that belongs in test_symbol_slash_form_contract.py.

Contracts tested:
1. BTC/USD maps to XBTUSD (special case: BTC → XBT)
2. ETH/USD maps to ETHUSD (slash removed, no base mapping)
3. SOL/USD maps to SOLUSD (slash removed, no base mapping)
4. Non-slash symbols (equities, ETFs, futures) pass through unchanged
5. PollingClient stores canonical symbols internally, not mapped formats
6. Mapping does not mutate stored symbols
7. BTC base mapping applies to all BTC pairs (USD, USDT, EUR)

Regression guard for:
- Kraken REST pair mapping fix (polling_client.py)
- BTC special-case mapping (BTC → XBT)
- Canonical identity preservation in adapter
"""

import pytest

from app.data.polling_client import PollingClient


class TestKrakenRestPairMapping:
    """
    Tests that PollingClient correctly maps canonical slash-form symbols
    to Kraken REST API format. This is the adapter seam — canonical
    identity remains slash-form; mapping is for REST compatibility only.
    """

    def test_btc_usd_maps_to_xbtusd(self):
        """
        BTC/USD must map to XBTUSD for Kraken REST API.
        This is a special case: BTC → XBT per Kraken's legacy naming.
        """
        client = PollingClient(
            symbols=["BTC/USD"],
            interval=1.0,
            exchange="kraken"
        )
        
        formatted = client._format_symbol("BTC/USD")
        assert formatted == "XBTUSD", "BTC/USD must map to XBTUSD for Kraken REST"

    def test_eth_usd_maps_to_ethusd(self):
        """ETH/USD must map to ETHUSD (slash removed, no base mapping)."""
        client = PollingClient(
            symbols=["ETH/USD"],
            interval=1.0,
            exchange="kraken"
        )
        
        formatted = client._format_symbol("ETH/USD")
        assert formatted == "ETHUSD", "ETH/USD must map to ETHUSD for Kraken REST"

    def test_sol_usd_maps_to_solusd(self):
        """SOL/USD must map to SOLUSD (slash removed, no base mapping)."""
        client = PollingClient(
            symbols=["SOL/USD"],
            interval=1.0,
            exchange="kraken"
        )
        
        formatted = client._format_symbol("SOL/USD")
        assert formatted == "SOLUSD", "SOL/USD must map to SOLUSD for Kraken REST"

    def test_xrp_usd_maps_to_xrpusd(self):
        """XRP/USD must map to XRPUSD (slash removed, no base mapping)."""
        client = PollingClient(
            symbols=["XRP/USD"],
            interval=1.0,
            exchange="kraken"
        )
        
        formatted = client._format_symbol("XRP/USD")
        assert formatted == "XRPUSD", "XRP/USD must map to XRPUSD for Kraken REST"

    def test_btc_usdt_maps_to_xbtusdt(self):
        """BTC/USDT must map to XBTUSDT (BTC → XBT, slash removed)."""
        client = PollingClient(
            symbols=["BTC/USDT"],
            interval=1.0,
            exchange="kraken"
        )
        
        formatted = client._format_symbol("BTC/USDT")
        assert formatted == "XBTUSDT", "BTC/USDT must map to XBTUSDT for Kraken REST"

    def test_btc_eur_maps_to_xbteur(self):
        """BTC/EUR must map to XBTEUR (BTC → XBT, slash removed)."""
        client = PollingClient(
            symbols=["BTC/EUR"],
            interval=1.0,
            exchange="kraken"
        )
        
        formatted = client._format_symbol("BTC/EUR")
        assert formatted == "XBTEUR", "BTC/EUR must map to XBTEUR for Kraken REST"

    def test_equity_symbol_passes_through(self):
        """Equity symbols (no slash) must pass through unchanged."""
        client = PollingClient(
            symbols=["AAPL", "MSFT", "NVDA"],
            interval=1.0,
            exchange="kraken"
        )
        
        assert client._format_symbol("AAPL") == "AAPL"
        assert client._format_symbol("MSFT") == "MSFT"
        assert client._format_symbol("NVDA") == "NVDA"

    def test_etf_symbol_passes_through(self):
        """ETF symbols (no slash) must pass through unchanged."""
        client = PollingClient(
            symbols=["SPY", "QQQ", "DIA"],
            interval=1.0,
            exchange="kraken"
        )
        
        assert client._format_symbol("SPY") == "SPY"
        assert client._format_symbol("QQQ") == "QQQ"
        assert client._format_symbol("DIA") == "DIA"

    def test_futures_symbol_passes_through(self):
        """Futures symbols (no slash) must pass through unchanged."""
        client = PollingClient(
            symbols=["ES", "NQ", "YM"],
            interval=1.0,
            exchange="kraken"
        )
        
        assert client._format_symbol("ES") == "ES"
        assert client._format_symbol("NQ") == "NQ"
        assert client._format_symbol("YM") == "YM"

    def test_symbol_without_slash_passes_through(self):
        """Any symbol without a slash must pass through unchanged."""
        client = PollingClient(
            symbols=["CUSTOM", "TEST123"],
            interval=1.0,
            exchange="kraken"
        )
        
        assert client._format_symbol("CUSTOM") == "CUSTOM"
        assert client._format_symbol("TEST123") == "TEST123"


class TestPollingClientCanonicalStorage:
    """
    Tests that PollingClient stores canonical symbols internally,
    not the mapped REST format. This preserves canonical identity
    through the adapter seam.
    """

    def test_stores_canonical_btc_usd_not_xbtusd(self):
        """PollingClient must store BTC/USD internally, not XBTUSD."""
        client = PollingClient(
            symbols=["BTC/USD", "ETH/USD"],
            interval=1.0,
            exchange="kraken"
        )
        
        assert client.symbols == ["BTC/USD", "ETH/USD"]
        assert "XBTUSD" not in client.symbols

    def test_stores_canonical_equity_symbols(self):
        """PollingClient must store equity symbols as-is."""
        client = PollingClient(
            symbols=["AAPL", "MSFT"],
            interval=1.0,
            exchange="kraken"
        )
        
        assert client.symbols == ["AAPL", "MSFT"]

    def test_mapping_does_not_mutate_stored_symbols(self):
        """
        Calling _format_symbol() must not mutate the stored symbols list.
        This prevents accidental canonical identity corruption.
        """
        client = PollingClient(
            symbols=["BTC/USD", "ETH/USD"],
            interval=1.0,
            exchange="kraken"
        )
        
        # Call mapping multiple times
        client._format_symbol("BTC/USD")
        client._format_symbol("ETH/USD")
        
        # Stored symbols must remain canonical
        assert client.symbols == ["BTC/USD", "ETH/USD"]
        assert "XBTUSD" not in client.symbols
        assert "ETHUSD" not in client.symbols


class TestKrakenBaseMapContract:
    """
    Tests the BTC → XBT special-case mapping contract.
    This is the only base mapping in _KRAKEN_BASE_MAP.
    """

    def test_btc_maps_to_xbt(self):
        """BTC base currency must map to XBT."""
        client = PollingClient(
            symbols=["BTC/USD"],
            interval=1.0,
            exchange="kraken"
        )
        
        assert client._format_symbol("BTC/USD") == "XBTUSD"

    def test_btc_with_different_quote_maps_correctly(self):
        """BTC with any quote must have BTC → XBT mapping applied."""
        client = PollingClient(
            symbols=["BTC/USD", "BTC/USDT", "BTC/EUR"],
            interval=1.0,
            exchange="kraken"
        )
        
        assert client._format_symbol("BTC/USD") == "XBTUSD"
        assert client._format_symbol("BTC/USDT") == "XBTUSDT"
        assert client._format_symbol("BTC/EUR") == "XBTEUR"

    def test_non_btc_crypto_no_base_mapping(self):
        """Non-BTC crypto symbols must not have base mapping."""
        client = PollingClient(
            symbols=["ETH/USD", "SOL/USD", "XRP/USD"],
            interval=1.0,
            exchange="kraken"
        )
        
        assert client._format_symbol("ETH/USD") == "ETHUSD"
        assert client._format_symbol("SOL/USD") == "SOLUSD"
        assert client._format_symbol("XRP/USD") == "XRPUSD"