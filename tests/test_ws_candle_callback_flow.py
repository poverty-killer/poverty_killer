"""
test_ws_candle_callback_flow.py

WEBSOCKET CANDLE PARSER/CALLBACK SEAM TEST — CITADEL GRADE

Tests that KrakenWebSocketClient._parse_candle() correctly parses
Kraken v2 candle (ohlc) messages and delivers them to the registered
callback as Candle objects.

This is a NARROW parser/callback seam test. It does NOT test:
- _process_message() routing
- Queue processing
- Full WebSocket runtime flow

Contracts tested (from repo truth):
1. Valid candle payload → callback invoked with Candle
2. exchange_ts_ns extracted from interval_begin (RFC3339)
3. Missing timestamp → rejected (no callback)
4. Invalid timestamp → rejected
5. Missing symbol → rejected
6. Multiple nested payload entries → each processed

Regression guard for:
- Kraken v2 WebSocket candle parsing
- RFC3339 timestamp conversion
- Candle model population from WebSocket feed
"""

from unittest.mock import Mock

import pytest

from app.data.websocket_client import KrakenWebSocketClient
from app.models import Candle


class TestWebSocketCandleParsing:
    """
    Tests that _parse_candle() correctly extracts candle data from
    Kraken v2 WebSocket messages and invokes the callback.

    This is a direct parser seam test, not a full runtime flow test.
    """

    @pytest.mark.asyncio
    async def test_valid_candle_message_invokes_callback(self):
        """
        A valid Kraken v2 ohlc message must be parsed and delivered
        to the on_candle callback as a Candle object.
        """
        mock_callback = Mock()
        client = KrakenWebSocketClient(
            symbols=["BTC/USD"],
            on_candle=mock_callback,
            on_order_book=None,
            on_trade=None
        )
        
        # Kraken v2 ohlc message format
        message = {
            "channel": "ohlc",
            "data": [
                {
                    "symbol": "BTC/USD",
                    "interval_begin": "2024-01-15T12:00:00.000Z",
                    "open": "43210.50",
                    "high": "43500.00",
                    "low": "43100.00",
                    "close": "43450.25",
                    "volume": "1234.56789"
                }
            ]
        }
        
        receive_ts_ns = 1_000_000_000_000_000_000
        await client._parse_candle(message, receive_ts_ns)
        
        assert mock_callback.call_count == 1
        call_args = mock_callback.call_args[0][0]
        
        assert isinstance(call_args, Candle)
        assert call_args.symbol == "BTC/USD"
        assert call_args.open == 43210.50
        assert call_args.high == 43500.00
        assert call_args.low == 43100.00
        assert call_args.close == 43450.25
        assert call_args.volume == 1234.56789
        assert call_args.timeframe == "1m"

    @pytest.mark.asyncio
    async def test_timestamp_extraction_from_interval_begin(self):
        """
        exchange_ts_ns must be correctly extracted from interval_begin
        (RFC3339 timestamp). This is the authoritative timestamp source.
        """
        mock_callback = Mock()
        client = KrakenWebSocketClient(
            symbols=["BTC/USD"],
            on_candle=mock_callback,
            on_order_book=None,
            on_trade=None
        )
        
        # RFC3339: 2024-01-15T12:00:00.000Z = 1705320000 seconds
        expected_ts_ns = 1705320000 * 1_000_000_000
        
        message = {
            "channel": "ohlc",
            "data": [
                {
                    "symbol": "BTC/USD",
                    "interval_begin": "2024-01-15T12:00:00.000Z",
                    "open": "43210.50",
                    "high": "43500.00",
                    "low": "43100.00",
                    "close": "43450.25",
                    "volume": "1234.56789"
                }
            ]
        }
        
        receive_ts_ns = 1_000_000_000_000_000_000
        await client._parse_candle(message, receive_ts_ns)
        
        call_args = mock_callback.call_args[0][0]
        assert call_args.exchange_ts_ns == expected_ts_ns

    @pytest.mark.asyncio
    async def test_candle_without_timestamp_rejected(self):
        """
        Candle message missing interval_begin (or timestamp) must be rejected.
        No callback invocation. This enforces timestamp authority.
        """
        mock_callback = Mock()
        client = KrakenWebSocketClient(
            symbols=["BTC/USD"],
            on_candle=mock_callback,
            on_order_book=None,
            on_trade=None
        )
        
        message = {
            "channel": "ohlc",
            "data": [
                {
                    "symbol": "BTC/USD",
                    "open": "43210.50",
                    "high": "43500.00",
                    "low": "43100.00",
                    "close": "43450.25",
                    "volume": "1234.56789"
                }
            ]
        }
        
        receive_ts_ns = 1_000_000_000_000_000_000
        await client._parse_candle(message, receive_ts_ns)
        
        assert mock_callback.call_count == 0

    @pytest.mark.asyncio
    async def test_candle_with_invalid_timestamp_rejected(self):
        """
        Candle message with invalid RFC3339 timestamp must be rejected.
        No callback invocation.
        """
        mock_callback = Mock()
        client = KrakenWebSocketClient(
            symbols=["BTC/USD"],
            on_candle=mock_callback,
            on_order_book=None,
            on_trade=None
        )
        
        message = {
            "channel": "ohlc",
            "data": [
                {
                    "symbol": "BTC/USD",
                    "interval_begin": "not-a-timestamp",
                    "open": "43210.50",
                    "high": "43500.00",
                    "low": "43100.00",
                    "close": "43450.25",
                    "volume": "1234.56789"
                }
            ]
        }
        
        receive_ts_ns = 1_000_000_000_000_000_000
        await client._parse_candle(message, receive_ts_ns)
        
        assert mock_callback.call_count == 0

    @pytest.mark.asyncio
    async def test_candle_missing_symbol_rejected(self):
        """
        Candle message missing symbol must be rejected.
        No callback invocation.
        """
        mock_callback = Mock()
        client = KrakenWebSocketClient(
            symbols=["BTC/USD"],
            on_candle=mock_callback,
            on_order_book=None,
            on_trade=None
        )
        
        message = {
            "channel": "ohlc",
            "data": [
                {
                    "interval_begin": "2024-01-15T12:00:00.000Z",
                    "open": "43210.50",
                    "high": "43500.00",
                    "low": "43100.00",
                    "close": "43450.25",
                    "volume": "1234.56789"
                }
            ]
        }
        
        receive_ts_ns = 1_000_000_000_000_000_000
        await client._parse_candle(message, receive_ts_ns)
        
        assert mock_callback.call_count == 0

    @pytest.mark.asyncio
    async def test_multiple_candles_in_payload(self):
        """
        A single message may contain multiple candle entries (data array).
        Each must be processed and callback invoked for each.
        """
        mock_callback = Mock()
        client = KrakenWebSocketClient(
            symbols=["BTC/USD", "ETH/USD"],
            on_candle=mock_callback,
            on_order_book=None,
            on_trade=None
        )
        
        message = {
            "channel": "ohlc",
            "data": [
                {
                    "symbol": "BTC/USD",
                    "interval_begin": "2024-01-15T12:00:00.000Z",
                    "open": "43210.50",
                    "high": "43500.00",
                    "low": "43100.00",
                    "close": "43450.25",
                    "volume": "1234.56789"
                },
                {
                    "symbol": "ETH/USD",
                    "interval_begin": "2024-01-15T12:00:00.000Z",
                    "open": "3200.50",
                    "high": "3250.00",
                    "low": "3180.00",
                    "close": "3240.25",
                    "volume": "56789.12345"
                }
            ]
        }
        
        receive_ts_ns = 1_000_000_000_000_000_000
        await client._parse_candle(message, receive_ts_ns)
        
        assert mock_callback.call_count == 2
        
        calls = mock_callback.call_args_list
        symbols = [call[0][0].symbol for call in calls]
        assert "BTC/USD" in symbols
        assert "ETH/USD" in symbols