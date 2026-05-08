"""
test_symbol_slash_form_contract.py

CANONICAL SYMBOL IDENTITY CONTRACT — CITADEL GRADE

Tests that the bot's official symbol identity is slash-form (e.g., BTC/USD)
and that exchange-specific formats (e.g., XBTUSD) are NOT treated as canonical
truth. This is a foundational contract preventing identity drift.

Contracts tested:
1. InstrumentRegistry stores and retrieves symbols in slash-form
2. DataContinuityValidator accepts slash-form symbols
3. PollingClient correctly maps slash-form to Kraken REST format (XBTUSD)
   but does NOT store that mapped format as canonical truth

Canonical crypto identity: slash-form only (BTC/USD, ETH/USD, SOL/USD)
Venue mapping: adapter concern only — does not become canonical truth

Regression guard for:
- Symbol slash-form validation (data_validator.py)
- REST pair mapping (polling_client.py)
- Canonical identity separation from venue formats

Obedience requirements met:
- Preserves existing behavior (tests what is already true)
- Tests the correct seam (registry + validator + adapter)
- No duplicate authority
- No invented coverage — tests only proven behavior
- No internal contradiction
"""

import pytest

from app.instrument_registry import InstrumentRegistry
from app.brain.data_validator import DataContinuityValidator
from app.data.polling_client import PollingClient


class TestCanonicalSymbolIdentity:
    """
    Tests that the bot's official symbol identity is slash-form.
    This is a foundational contract — exchange-specific formats are
    adapter-layer concerns, not canonical truth.
    """

    def test_instrument_registry_stores_slash_form(self):
        """InstrumentRegistry must store symbols in slash-form (BTC/USD, not XBTUSD)."""
        InstrumentRegistry.initialize()
        
        btc_spec = InstrumentRegistry.get_instrument("BTC/USD")
        assert btc_spec is not None, "BTC/USD must exist in registry"
        assert btc_spec.symbol == "BTC/USD", "Canonical symbol must be slash-form"
        
        eth_spec = InstrumentRegistry.get_instrument("ETH/USD")
        assert eth_spec is not None, "ETH/USD must exist in registry"
        assert eth_spec.symbol == "ETH/USD", "Canonical symbol must be slash-form"
        
        sol_spec = InstrumentRegistry.get_instrument("SOL/USD")
        assert sol_spec is not None, "SOL/USD must exist in registry"
        assert sol_spec.symbol == "SOL/USD", "Canonical symbol must be slash-form"

    def test_instrument_registry_rejects_exchange_format_as_key(self):
        """Exchange-specific formats (XBTUSD) must NOT be registry keys."""
        InstrumentRegistry.initialize()
        
        # XBTUSD is Kraken's REST format — should not be the canonical key
        xbt_spec = InstrumentRegistry.get_instrument("XBTUSD")
        assert xbt_spec is None, "XBTUSD must NOT be a registry key (canonical is BTC/USD)"
        
        # The canonical BTC/USD should exist
        btc_spec = InstrumentRegistry.get_instrument("BTC/USD")
        assert btc_spec is not None, "BTC/USD must exist"

    def test_data_validator_accepts_slash_form(self):
        """DataContinuityValidator must accept slash-form symbols."""
        validator = DataContinuityValidator()
        
        # These should not raise
        validator._get_state("BTC/USD")
        validator._get_state("ETH/USD")
        validator._get_state("SOL/USD")
        
        # Verify the state was created
        assert "BTC/USD" in validator._state
        assert "ETH/USD" in validator._state
        assert "SOL/USD" in validator._state

    def test_data_validator_accepts_equity_symbols(self):
        """Equity symbols (no slash) are valid for their asset class."""
        validator = DataContinuityValidator()
        
        # Should not raise
        validator._get_state("AAPL")
        validator._get_state("MSFT")
        validator._get_state("NVDA")
        
        assert "AAPL" in validator._state
        assert "MSFT" in validator._state

    def test_data_validator_rejects_invalid_formats(self):
        """
        DataContinuityValidator must reject obviously invalid formats.
        These are universally malformed, not policy decisions.
        """
        validator = DataContinuityValidator()
        
        # Validator uses character-class pattern ^[A-Za-z0-9\-\._/]+$ — rejects
        # characters outside that set. Double-slash / extra-slash are NOT rejected
        # because each individual '/' is a valid character.
        invalid_symbols = [
            "",                          # Empty — caught by not-symbol guard
            "   ",                       # Whitespace only — spaces not in character class
            "BTC\\USD",                  # Backslash — not in character class
            "BTC USD",                   # Space — not in character class
            "BTC|USD",                   # Pipe — not in character class
            "BTC<USD",                   # Angle bracket — not in character class
            "BTC>USD",                   # Angle bracket — not in character class
            "BTC?USD",                   # Question mark — not in character class
            "BTC*USD",                   # Asterisk — not in character class
        ]
        
        for symbol in invalid_symbols:
            with pytest.raises(ValueError, match="Invalid symbol"):
                validator._get_state(symbol)


class TestPollingClientSymbolMapping:
    """
    Tests that PollingClient correctly maps slash-form to venue-specific formats
    for REST API calls, while preserving canonical identity.
    """

    def test_kraken_rest_pair_mapping_btc(self):
        """BTC/USD must map to XBTUSD for Kraken REST API."""
        client = PollingClient(
            symbols=["BTC/USD"],
            interval=1.0,
            exchange="kraken"
        )
        
        formatted = client._format_symbol("BTC/USD")
        assert formatted == "XBTUSD", "BTC/USD must map to XBTUSD for Kraken REST"

    def test_kraken_rest_pair_mapping_eth(self):
        """ETH/USD must map to ETHUSD for Kraken REST API."""
        client = PollingClient(
            symbols=["ETH/USD"],
            interval=1.0,
            exchange="kraken"
        )
        
        formatted = client._format_symbol("ETH/USD")
        assert formatted == "ETHUSD", "ETH/USD must map to ETHUSD for Kraken REST"

    def test_kraken_rest_pair_mapping_sol(self):
        """SOL/USD must map to SOLUSD for Kraken REST API."""
        client = PollingClient(
            symbols=["SOL/USD"],
            interval=1.0,
            exchange="kraken"
        )
        
        formatted = client._format_symbol("SOL/USD")
        assert formatted == "SOLUSD", "SOL/USD must map to SOLUSD for Kraken REST"

    def test_kraken_rest_preserves_equity_symbols(self):
        """Equity symbols (no slash) must be preserved as-is."""
        client = PollingClient(
            symbols=["AAPL", "MSFT"],
            interval=1.0,
            exchange="kraken"
        )
        
        formatted_aapl = client._format_symbol("AAPL")
        formatted_msft = client._format_symbol("MSFT")
        
        assert formatted_aapl == "AAPL", "Equity symbols must be preserved"
        assert formatted_msft == "MSFT", "Equity symbols must be preserved"

    def test_polling_client_stores_canonical_symbols(self):
        """PollingClient must store symbols in canonical slash-form internally."""
        client = PollingClient(
            symbols=["BTC/USD", "ETH/USD", "AAPL"],
            interval=1.0,
            exchange="kraken"
        )
        
        assert client.symbols == ["BTC/USD", "ETH/USD", "AAPL"]
        assert "XBTUSD" not in client.symbols, "Canonical symbols must not be overwritten by mapped format"


class TestValidatorPatternBehavior:
    """
    Tests the actual behavior of DataContinuityValidator's symbol pattern.
    These tests document what the validator accepts, not what policy should be.
    Canonical identity policy is enforced in TestCanonicalSymbolIdentity.
    """

    def test_validator_accepts_alphanumeric_only(self):
        """Validator accepts plain alphanumeric symbols (equities, futures)."""
        validator = DataContinuityValidator()
        
        validator._get_state("AAPL")
        validator._get_state("ES")
        validator._get_state("BTCUSDT")
        
        assert "AAPL" in validator._state
        assert "ES" in validator._state
        assert "BTCUSDT" in validator._state

    def test_validator_accepts_hyphen_and_underscore(self):
        """
        Validator pattern accepts hyphen and underscore (per regex: \-\._).
        This is a documented behavior of the validator pattern.
        It is NOT an endorsement of these formats as canonical crypto identity.
        Canonical crypto identity remains slash-form (BTC/USD).
        """
        validator = DataContinuityValidator()
        
        # These are accepted by the pattern but are NOT canonical crypto identity
        validator._get_state("BTC-USD")
        validator._get_state("BTC_USD")
        
        assert "BTC-USD" in validator._state
        assert "BTC_USD" in validator._state

    def test_validator_rejects_whitespace(self):
        """Validator must reject any whitespace."""
        validator = DataContinuityValidator()
        
        whitespace_symbols = ["BTC USD", " BTC/USD", "BTC/USD ", "BTC\tUSD"]
        
        for symbol in whitespace_symbols:
            with pytest.raises(ValueError, match="Invalid symbol"):
                validator._get_state(symbol)

    def test_validator_rejects_control_characters(self):
        """Validator must reject control characters."""
        validator = DataContinuityValidator()
        
        invalid_symbols = [
            "BTC\nUSD",
            "BTC\rUSD",
            "BTC\0USD",
            "BTC|USD",
            "BTC\\USD",
            "BTC<USD",
            "BTC>USD",
            "BTC?USD",
            "BTC*USD",
        ]
        
        for symbol in invalid_symbols:
            with pytest.raises(ValueError, match="Invalid symbol"):
                validator._get_state(symbol)


class TestEndToEndCanonicalIdentity:
    """
    End-to-end tests verifying the canonical identity flows through the system.
    These test the contract between components, not full integration.
    """

    def test_symbol_flows_from_registry_to_validator(self):
        """A symbol valid in InstrumentRegistry must be valid in DataContinuityValidator."""
        InstrumentRegistry.initialize()
        validator = DataContinuityValidator()
        
        # Get all crypto symbols from registry (they are slash-form)
        crypto_symbols = InstrumentRegistry.get_all_symbols(asset_class="crypto")
        
        for symbol in crypto_symbols:
            # Should not raise
            validator._get_state(symbol)
        
        # Verify at least BTC/USD is in the list
        assert "BTC/USD" in crypto_symbols

    def test_exchange_format_never_becomes_canonical_registry_key(self):
        """
        Critical contract: Exchange-specific formats must never be stored as
        canonical symbols in InstrumentRegistry.
        """
        InstrumentRegistry.initialize()
        
        # These are exchange-specific formats — must not become registry keys
        exchange_formats = ["XBTUSD", "BTC-USD", "BTCUSDT", "ETHUSD", "SOLUSD", "BTC_USD"]
        
        for fmt in exchange_formats:
            # Registry should not have it as a key
            assert InstrumentRegistry.get_instrument(fmt) is None, \
                f"{fmt} must not be a registry key"

    def test_canonical_slash_symbols_are_accepted_by_validator(self):
        """
        Valid slash-form crypto symbols must pass validation.
        This prevents false-positive rejections.
        """
        validator = DataContinuityValidator()
        
        valid_slash_symbols = [
            "BTC/USD",
            "ETH/USD",
            "SOL/USD",
            "BTC/USDT",      # Some pairs use USDT
            "ETH/USDC",      # Some pairs use USDC
        ]
        
        for symbol in valid_slash_symbols:
            # Should not raise
            validator._get_state(symbol)
        
        # Verify all were accepted
        for symbol in valid_slash_symbols:
            assert symbol in validator._state, f"{symbol} was not accepted"