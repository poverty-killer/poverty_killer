# Seam 6 Controlled Alpaca PAPER Portfolio Expansion Machine

- report_ts_ns: 1779228790839203400
- endpoint: https://paper-api.alpaca.markets
- approval_env_present: True
- selected_candidate_universe: `[{"symbol": "AAPL", "asset_class": "equity"}, {"symbol": "MSFT", "asset_class": "equity"}, {"symbol": "NVDA", "asset_class": "equity"}, {"symbol": "AMZN", "asset_class": "equity"}, {"symbol": "META", "asset_class": "equity"}, {"symbol": "GOOGL", "asset_class": "equity"}, {"symbol": "TSLA", "asset_class": "equity"}, {"symbol": "AMD", "asset_class": "equity"}, {"symbol": "JPM", "asset_class": "equity"}, {"symbol": "V", "asset_class": "equity"}, {"symbol": "MA", "asset_class": "equity"}, {"symbol": "UNH", "asset_class": "equity"}, {"symbol": "HD", "asset_class": "equity"}, {"symbol": "COST", "asset_class": "equity"}, {"symbol": "AVGO", "asset_class": "equity"}, {"symbol": "CRM", "asset_class": "equity"}, {"symbol": "NFLX", "asset_class": "equity"}, {"symbol": "XOM", "asset_class": "equity"}, {"symbol": "JNJ", "asset_class": "equity"}, {"symbol": "PG", "asset_class": "equity"}, {"symbol": "KO", "asset_class": "equity"}, {"symbol": "PEP", "asset_class": "equity"}, {"symbol": "WMT", "asset_class": "equity"}, {"symbol": "SPY", "asset_class": "etf"}, {"symbol": "QQQ", "asset_class": "etf"}, {"symbol": "DIA", "asset_class": "etf"}, {"symbol": "IWM", "asset_class": "etf"}, {"symbol": "XLK", "asset_class": "etf"}, {"symbol": "XLF", "asset_class": "etf"}, {"symbol": "XLE", "asset_class": "etf"}, {"symbol": "XLV", "asset_class": "etf"}, {"symbol": "XLY", "asset_class": "etf"}, {"symbol": "BTC/USD", "asset_class": "crypto"}, {"symbol": "ETH/USD", "asset_class": "crypto"}, {"symbol": "SOL/USD", "asset_class": "crypto"}]`
- system_chosen_symbols: `[]`
- submitted_orders_count: 0
- no_live_endpoint_or_mode: True
- no_sell_rebalance_cancel_replace_retry_storm: True
- no_fake_broker_facts: True

## Skips
```json
[
  {
    "asset_class": "equity",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "311.68",
    "qty": "0.032084",
    "reason_codes": [
      "DUPLICATE_EXISTING_EXPOSURE",
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED"
    ],
    "symbol": "AAPL"
  },
  {
    "asset_class": "equity",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": null,
    "limit_price": null,
    "qty": null,
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED",
      "LIMIT_PRICE_NONPOSITIVE",
      "REQUESTED_NOTIONAL_MISSING",
      "QUANTITY_NOT_POSITIVE"
    ],
    "symbol": "MSFT"
  },
  {
    "asset_class": "equity",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "235.79",
    "qty": "0.042410",
    "reason_codes": [
      "DUPLICATE_EXISTING_EXPOSURE",
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED"
    ],
    "symbol": "NVDA"
  },
  {
    "asset_class": "equity",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": null,
    "limit_price": null,
    "qty": null,
    "reason_codes": [
      "DUPLICATE_EXISTING_EXPOSURE",
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED",
      "LIMIT_PRICE_NONPOSITIVE",
      "REQUESTED_NOTIONAL_MISSING",
      "QUANTITY_NOT_POSITIVE"
    ],
    "symbol": "AMZN"
  },
  {
    "asset_class": "equity",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "639.14",
    "qty": "0.015646",
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED"
    ],
    "symbol": "META"
  },
  {
    "asset_class": "equity",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "409.08",
    "qty": "0.024445",
    "reason_codes": [
      "DUPLICATE_EXISTING_EXPOSURE",
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED"
    ],
    "symbol": "GOOGL"
  },
  {
    "asset_class": "equity",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "423.61",
    "qty": "0.023606",
    "reason_codes": [
      "DUPLICATE_EXISTING_EXPOSURE",
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED"
    ],
    "symbol": "TSLA"
  },
  {
    "asset_class": "equity",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": null,
    "limit_price": null,
    "qty": null,
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED",
      "LIMIT_PRICE_NONPOSITIVE",
      "REQUESTED_NOTIONAL_MISSING",
      "QUANTITY_NOT_POSITIVE"
    ],
    "symbol": "AMD"
  },
  {
    "asset_class": "equity",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "310.24",
    "qty": "0.032233",
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED"
    ],
    "symbol": "JPM"
  },
  {
    "asset_class": "equity",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": null,
    "limit_price": null,
    "qty": null,
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED",
      "LIMIT_PRICE_NONPOSITIVE",
      "REQUESTED_NOTIONAL_MISSING",
      "QUANTITY_NOT_POSITIVE"
    ],
    "symbol": "V"
  },
  {
    "asset_class": "equity",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "532.95",
    "qty": "0.018763",
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED"
    ],
    "symbol": "MA"
  },
  {
    "asset_class": "equity",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": null,
    "limit_price": null,
    "qty": null,
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED",
      "LIMIT_PRICE_NONPOSITIVE",
      "REQUESTED_NOTIONAL_MISSING",
      "QUANTITY_NOT_POSITIVE"
    ],
    "symbol": "UNH"
  },
  {
    "asset_class": "equity",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "313.92",
    "qty": "0.031855",
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED"
    ],
    "symbol": "HD"
  },
  {
    "asset_class": "equity",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "1120",
    "qty": "0.008928",
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED"
    ],
    "symbol": "COST"
  },
  {
    "asset_class": "equity",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "440.68",
    "qty": "0.022692",
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED"
    ],
    "symbol": "AVGO"
  },
  {
    "asset_class": "equity",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": null,
    "limit_price": null,
    "qty": null,
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED",
      "LIMIT_PRICE_NONPOSITIVE",
      "REQUESTED_NOTIONAL_MISSING",
      "QUANTITY_NOT_POSITIVE"
    ],
    "symbol": "CRM"
  },
  {
    "asset_class": "equity",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "97.26",
    "qty": "0.102817",
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED"
    ],
    "symbol": "NFLX"
  },
  {
    "asset_class": "equity",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "169.5",
    "qty": "0.058997",
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED"
    ],
    "symbol": "XOM"
  },
  {
    "asset_class": "equity",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "241.26",
    "qty": "0.041449",
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED"
    ],
    "symbol": "JNJ"
  },
  {
    "asset_class": "equity",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "149.67",
    "qty": "0.066813",
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED"
    ],
    "symbol": "PG"
  },
  {
    "asset_class": "equity",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "85.54",
    "qty": "0.116904",
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED"
    ],
    "symbol": "KO"
  },
  {
    "asset_class": "equity",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "157.85",
    "qty": "0.063351",
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED"
    ],
    "symbol": "PEP"
  },
  {
    "asset_class": "equity",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": null,
    "limit_price": null,
    "qty": null,
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED",
      "LIMIT_PRICE_NONPOSITIVE",
      "REQUESTED_NOTIONAL_MISSING",
      "QUANTITY_NOT_POSITIVE"
    ],
    "symbol": "WMT"
  },
  {
    "asset_class": "etf",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "756.77",
    "qty": "0.013214",
    "reason_codes": [
      "DUPLICATE_EXISTING_EXPOSURE",
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED"
    ],
    "symbol": "SPY"
  },
  {
    "asset_class": "etf",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "701.66",
    "qty": "0.014251",
    "reason_codes": [
      "DUPLICATE_EXISTING_EXPOSURE",
      "QUOTE_STALE",
      "MARKET_CLOSED"
    ],
    "symbol": "QQQ"
  },
  {
    "asset_class": "etf",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": null,
    "limit_price": null,
    "qty": null,
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED",
      "LIMIT_PRICE_NONPOSITIVE",
      "REQUESTED_NOTIONAL_MISSING",
      "QUANTITY_NOT_POSITIVE"
    ],
    "symbol": "DIA"
  },
  {
    "asset_class": "etf",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "282.06",
    "qty": "0.035453",
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED"
    ],
    "symbol": "IWM"
  },
  {
    "asset_class": "etf",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "178.02",
    "qty": "0.056173",
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED"
    ],
    "symbol": "XLK"
  },
  {
    "asset_class": "etf",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "51.11",
    "qty": "0.195656",
    "reason_codes": [
      "QUOTE_STALE",
      "MARKET_CLOSED"
    ],
    "symbol": "XLF"
  },
  {
    "asset_class": "etf",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "63.31",
    "qty": "0.157952",
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED"
    ],
    "symbol": "XLE"
  },
  {
    "asset_class": "etf",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "151.52",
    "qty": "0.065997",
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED"
    ],
    "symbol": "XLV"
  },
  {
    "asset_class": "etf",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "117.64",
    "qty": "0.085005",
    "reason_codes": [
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED"
    ],
    "symbol": "XLY"
  },
  {
    "asset_class": "crypto",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": null,
    "limit_price": null,
    "qty": null,
    "reason_codes": [
      "CRYPTO_NOT_SELECTED_EQUITIES_ETFS_FIRST_FOR_SEAM6",
      "QUOTE_MISSING",
      "LIMIT_PRICE_NONPOSITIVE",
      "REQUESTED_NOTIONAL_MISSING",
      "QUANTITY_NOT_POSITIVE"
    ],
    "symbol": "BTC/USD"
  },
  {
    "asset_class": "crypto",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": null,
    "limit_price": null,
    "qty": null,
    "reason_codes": [
      "CRYPTO_NOT_SELECTED_EQUITIES_ETFS_FIRST_FOR_SEAM6",
      "QUOTE_MISSING",
      "LIMIT_PRICE_NONPOSITIVE",
      "REQUESTED_NOTIONAL_MISSING",
      "QUANTITY_NOT_POSITIVE"
    ],
    "symbol": "ETH/USD"
  },
  {
    "asset_class": "crypto",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": null,
    "limit_price": null,
    "qty": null,
    "reason_codes": [
      "CRYPTO_NOT_SELECTED_EQUITIES_ETFS_FIRST_FOR_SEAM6",
      "QUOTE_MISSING",
      "LIMIT_PRICE_NONPOSITIVE",
      "REQUESTED_NOTIONAL_MISSING",
      "QUANTITY_NOT_POSITIVE"
    ],
    "symbol": "SOL/USD"
  }
]
```

## Submitted Orders
```json
[]
```

## Reconciled Orders
```json
[]
```

## Positions After Reconciliation
```json
[
  {
    "asset_class": "us_equity",
    "avg_entry_price": "295.78",
    "cost_basis": "4.999569",
    "current_price": "298.71",
    "market_value": "5.049095",
    "qty": "0.016903",
    "side": "long",
    "symbol": "AAPL",
    "unrealized_pl": "0.049526"
  },
  {
    "asset_class": "us_equity",
    "avg_entry_price": "264.372",
    "cost_basis": "4.999803",
    "current_price": "259",
    "market_value": "4.898208",
    "qty": "0.018912",
    "side": "long",
    "symbol": "AMZN",
    "unrealized_pl": "-0.101595"
  },
  {
    "asset_class": "us_equity",
    "avg_entry_price": "397.628",
    "cost_basis": "4.998979",
    "current_price": "387.5638",
    "market_value": "4.872452",
    "qty": "0.012572",
    "side": "long",
    "symbol": "GOOGL",
    "unrealized_pl": "-0.126527"
  },
  {
    "asset_class": "us_equity",
    "avg_entry_price": "221.284",
    "cost_basis": "4.999469",
    "current_price": "221.87",
    "market_value": "5.012709",
    "qty": "0.022593",
    "side": "long",
    "symbol": "NVDA",
    "unrealized_pl": "0.01324"
  },
  {
    "asset_class": "us_equity",
    "avg_entry_price": "703.048",
    "cost_basis": "4.999374",
    "current_price": "701.88",
    "market_value": "4.991069",
    "qty": "0.007111",
    "side": "long",
    "symbol": "QQQ",
    "unrealized_pl": "-0.008305"
  },
  {
    "asset_class": "us_equity",
    "avg_entry_price": "736.628",
    "cost_basis": "4.999494",
    "current_price": "733.69",
    "market_value": "4.979554",
    "qty": "0.006787",
    "side": "long",
    "symbol": "SPY",
    "unrealized_pl": "-0.01994"
  },
  {
    "asset_class": "us_equity",
    "avg_entry_price": "409.966",
    "cost_basis": "4.999535",
    "current_price": "404.18",
    "market_value": "4.928975",
    "qty": "0.012195",
    "side": "long",
    "symbol": "TSLA",
    "unrealized_pl": "-0.07056"
  }
]
```

## Open Orders After Reconciliation
```json
[]
```

## Account After Reconciliation
```json
{
  "account_blocked": false,
  "buying_power": "199964.73",
  "cash": "99965",
  "equity": "99999.73",
  "long_market_value": "34.73",
  "multiplier": "2",
  "pattern_day_trader": false,
  "portfolio_value": "99999.73",
  "short_market_value": "0",
  "status": "ACTIVE",
  "trade_suspended_by_user": false,
  "trading_blocked": false,
  "transfers_blocked": false
}
```

## Machine Evidence
```json
[
  {
    "broker_gateway_post_count": 0,
    "decision_compiler_reached": false,
    "execution_engine_reached": false,
    "order_router_reached": false,
    "reason_codes": [
      "DUPLICATE_EXISTING_EXPOSURE",
      "QUOTE_STALE",
      "QUOTE_WIDE_SPREAD",
      "MARKET_CLOSED",
      "LIMIT_PRICE_NONPOSITIVE",
      "REQUESTED_NOTIONAL_MISSING",
      "QUANTITY_NOT_POSITIVE",
      "CRYPTO_NOT_SELECTED_EQUITIES_ETFS_FIRST_FOR_SEAM6",
      "QUOTE_MISSING"
    ],
    "selection_status": "NO_SAFE_CANDIDATES_AFTER_REAL_TRUTH_GATES"
  }
]
```
