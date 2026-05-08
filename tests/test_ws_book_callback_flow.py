"""
test_ws_book_callback_flow.py

WEBSOCKET ORDER BOOK PARSER/CALLBACK SEAM TEST — CITADEL GRADE

Tests that KrakenWebSocketClient._parse_order_book() correctly parses
Kraken v2 order book (book) messages and delivers them to the registered
callback as OrderBookSnapshot objects.

This is a NARROW parser/callback seam test. It does NOT test:
- _process_message() routing
- Queue processing
- Full WebSocket runtime flow

Contracts tested (from repo truth):
1. Valid order book payload → callback invoked with OrderBookSnapshot
2. exchange_ts_ns extracted from timestamp (RFC3339)
3. Bids and asks extracted as dicts with "price"/"qty" keys
4. Missing timestamp → rejected (no callback)
5. Invalid timestamp → rejected
6. Missing symbol → rejected
7. Empty bids AND asks → no callback (parser skips)
8. Multiple symbols in payload → each processed

Regression guard for:
- Kraken v2 WebSocket order book parsing
- RFC3339 timestamp conversion
- OrderBookSnapshot population from WebSocket feed
"""

from unittest.mock import Mock

import pytest

from app.data.websocket_client import KrakenWebSocketClient
from app.models import OrderBookSnapshot


class TestWebSocketOrderBookParsing:
    """
    Tests that _parse_order_book() correctly extracts order book data from
    Kraken v2 WebSocket messages and invokes the callback.

    This is a direct parser seam test, not a full runtime flow test.
    """

    @pytest.mark.asyncio
    async def test_valid_order_book_message_invokes_callback(self):
        """
        A valid Kraken v2 book message must be parsed and delivered
        to the on_order_book callback as an OrderBookSnapshot object.
        """
        mock_callback = Mock()
        client = KrakenWebSocketClient(
            symbols=["BTC/USD"],
            on_order_book=mock_callback,
            on_candle=None,
            on_trade=None
        )
        
        # Kraken v2 book message format — bids/asks as dicts with "price"/"qty"
        message = {
            "channel": "book",
            "data": [
                {
                    "symbol": "BTC/USD",
                    "timestamp": "2024-01-15T12:00:00.000Z",
                    "bids": [
                        {"price": "43210.50", "qty": "1.23456"},
                        {"price": "43200.00", "qty": "2.00000"}
                    ],
                    "asks": [
                        {"price": "43220.00", "qty": "0.98765"},
                        {"price": "43230.00", "qty": "1.50000"}
                    ]
                }
            ]
        }
        
        receive_ts_ns = 1_000_000_000_000_000_000
        await client._parse_order_book(message, receive_ts_ns)
        
        assert mock_callback.call_count == 1
        call_args = mock_callback.call_args[0][0]
        
        assert isinstance(call_args, OrderBookSnapshot)
        assert call_args.symbol == "BTC/USD"
        assert len(call_args.bids) == 2
        assert len(call_args.asks) == 2
        assert call_args.bids[0][0] == 43210.50
        assert call_args.bids[0][1] == 1.23456
        assert call_args.asks[0][0] == 43220.00
        assert call_args.asks[0][1] == 0.98765

    @pytest.mark.asyncio
    async def test_timestamp_extraction_from_timestamp_field(self):
        """
        exchange_ts_ns must be correctly extracted from timestamp field
        (RFC3339 timestamp). This is the authoritative timestamp source.
        """
        mock_callback = Mock()
        client = KrakenWebSocketClient(
            symbols=["BTC/USD"],
            on_order_book=mock_callback,
            on_candle=None,
            on_trade=None
        )
        
        # RFC3339: 2024-01-15T12:00:00.000Z = 1705320000 seconds
        expected_ts_ns = 1705320000 * 1_000_000_000
        
        message = {
            "channel": "book",
            "data": [
                {
                    "symbol": "BTC/USD",
                    "timestamp": "2024-01-15T12:00:00.000Z",
                    "bids": [{"price": "43210.50", "qty": "1.23456"}],
                    "asks": [{"price": "43220.00", "qty": "0.98765"}]
                }
            ]
        }
        
        receive_ts_ns = 1_000_000_000_000_000_000
        await client._parse_order_book(message, receive_ts_ns)
        
        call_args = mock_callback.call_args[0][0]
        assert call_args.exchange_ts_ns == expected_ts_ns

    @pytest.mark.asyncio
    async def test_order_book_without_timestamp_rejected(self):
        """
        Order book message missing timestamp must be rejected.
        No callback invocation. This enforces timestamp authority.
        """
        mock_callback = Mock()
        client = KrakenWebSocketClient(
            symbols=["BTC/USD"],
            on_order_book=mock_callback,
            on_candle=None,
            on_trade=None
        )
        
        message = {
            "channel": "book",
            "data": [
                {
                    "symbol": "BTC/USD",
                    "bids": [{"price": "43210.50", "qty": "1.23456"}],
                    "asks": [{"price": "43220.00", "qty": "0.98765"}]
                }
            ]
        }
        
        receive_ts_ns = 1_000_000_000_000_000_000
        await client._parse_order_book(message, receive_ts_ns)
        
        assert mock_callback.call_count == 0

    @pytest.mark.asyncio
    async def test_order_book_with_invalid_timestamp_rejected(self):
        """
        Order book message with invalid RFC3339 timestamp must be rejected.
        No callback invocation.
        """
        mock_callback = Mock()
        client = KrakenWebSocketClient(
            symbols=["BTC/USD"],
            on_order_book=mock_callback,
            on_candle=None,
            on_trade=None
        )
        
        message = {
            "channel": "book",
            "data": [
                {
                    "symbol": "BTC/USD",
                    "timestamp": "not-a-timestamp",
                    "bids": [{"price": "43210.50", "qty": "1.23456"}],
                    "asks": [{"price": "43220.00", "qty": "0.98765"}]
                }
            ]
        }
        
        receive_ts_ns = 1_000_000_000_000_000_000
        await client._parse_order_book(message, receive_ts_ns)
        
        assert mock_callback.call_count == 0

    @pytest.mark.asyncio
    async def test_order_book_missing_symbol_rejected(self):
        """
        Order book message missing symbol must be rejected.
        No callback invocation.
        """
        mock_callback = Mock()
        client = KrakenWebSocketClient(
            symbols=["BTC/USD"],
            on_order_book=mock_callback,
            on_candle=None,
            on_trade=None
        )
        
        message = {
            "channel": "book",
            "data": [
                {
                    "timestamp": "2024-01-15T12:00:00.000Z",
                    "bids": [{"price": "43210.50", "qty": "1.23456"}],
                    "asks": [{"price": "43220.00", "qty": "0.98765"}]
                }
            ]
        }
        
        receive_ts_ns = 1_000_000_000_000_000_000
        await client._parse_order_book(message, receive_ts_ns)
        
        assert mock_callback.call_count == 0

    @pytest.mark.asyncio
    async def test_order_book_with_empty_bids_and_asks_skipped(self):
        """
        Order book with empty bids AND empty asks must be skipped.
        No callback invocation. (Parser does: if not bids and not asks: continue)
        """
        mock_callback = Mock()
        client = KrakenWebSocketClient(
            symbols=["BTC/USD"],
            on_order_book=mock_callback,
            on_candle=None,
            on_trade=None
        )
        
        message = {
            "channel": "book",
            "data": [
                {
                    "symbol": "BTC/USD",
                    "timestamp": "2024-01-15T12:00:00.000Z",
                    "bids": [],
                    "asks": []
                }
            ]
        }
        
        receive_ts_ns = 1_000_000_000_000_000_000
        await client._parse_order_book(message, receive_ts_ns)
        
        assert mock_callback.call_count == 0

    @pytest.mark.asyncio
    async def test_multiple_symbols_in_payload(self):
        """
        A single message may contain multiple order book entries for
        different symbols. Each must be processed and callback invoked for each.
        """
        mock_callback = Mock()
        client = KrakenWebSocketClient(
            symbols=["BTC/USD", "ETH/USD"],
            on_order_book=mock_callback,
            on_candle=None,
            on_trade=None
        )
        
        message = {
            "channel": "book",
            "data": [
                {
                    "symbol": "BTC/USD",
                    "timestamp": "2024-01-15T12:00:00.000Z",
                    "bids": [{"price": "43210.50", "qty": "1.23456"}],
                    "asks": [{"price": "43220.00", "qty": "0.98765"}]
                },
                {
                    "symbol": "ETH/USD",
                    "timestamp": "2024-01-15T12:00:00.000Z",
                    "bids": [{"price": "3200.50", "qty": "10.00000"}],
                    "asks": [{"price": "3210.00", "qty": "8.00000"}]
                }
            ]
        }
        
        receive_ts_ns = 1_000_000_000_000_000_000
        await client._parse_order_book(message, receive_ts_ns)
        
        assert mock_callback.call_count == 2
        
        calls = mock_callback.call_args_list
        symbols = [call[0][0].symbol for call in calls]
        assert "BTC/USD" in symbols
        assert "ETH/USD" in symbols