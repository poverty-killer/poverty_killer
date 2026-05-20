# Seam 6C Corrected Alpaca PAPER Crypto Fallthrough Expansion

- report_ts_ns: 1779243731558849900
- endpoint: https://paper-api.alpaca.markets
- approval_env_present: True
- selected_candidate_universe: `[{"symbol": "AAPL", "asset_class": "equity"}, {"symbol": "MSFT", "asset_class": "equity"}, {"symbol": "NVDA", "asset_class": "equity"}, {"symbol": "AMZN", "asset_class": "equity"}, {"symbol": "META", "asset_class": "equity"}, {"symbol": "GOOGL", "asset_class": "equity"}, {"symbol": "TSLA", "asset_class": "equity"}, {"symbol": "AMD", "asset_class": "equity"}, {"symbol": "JPM", "asset_class": "equity"}, {"symbol": "V", "asset_class": "equity"}, {"symbol": "MA", "asset_class": "equity"}, {"symbol": "UNH", "asset_class": "equity"}, {"symbol": "HD", "asset_class": "equity"}, {"symbol": "COST", "asset_class": "equity"}, {"symbol": "AVGO", "asset_class": "equity"}, {"symbol": "CRM", "asset_class": "equity"}, {"symbol": "NFLX", "asset_class": "equity"}, {"symbol": "XOM", "asset_class": "equity"}, {"symbol": "JNJ", "asset_class": "equity"}, {"symbol": "PG", "asset_class": "equity"}, {"symbol": "KO", "asset_class": "equity"}, {"symbol": "PEP", "asset_class": "equity"}, {"symbol": "WMT", "asset_class": "equity"}, {"symbol": "SPY", "asset_class": "etf"}, {"symbol": "QQQ", "asset_class": "etf"}, {"symbol": "DIA", "asset_class": "etf"}, {"symbol": "IWM", "asset_class": "etf"}, {"symbol": "XLK", "asset_class": "etf"}, {"symbol": "XLF", "asset_class": "etf"}, {"symbol": "XLE", "asset_class": "etf"}, {"symbol": "XLV", "asset_class": "etf"}, {"symbol": "XLY", "asset_class": "etf"}, {"symbol": "BTC/USD", "asset_class": "crypto"}, {"symbol": "ETH/USD", "asset_class": "crypto"}, {"symbol": "SOL/USD", "asset_class": "crypto"}]`
- system_chosen_symbols: `[]`
- submitted_orders_count: 0
- broker_post_count: 0
- crypto_fallthrough_behavior: equity/ETF candidates were skipped for MARKET_CLOSED/stale quote truth, crypto candidates were evaluated, and crypto failed closed on min-notional/precision/cap truth
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
    "intended_notional": "9.98",
    "limit_price": "76794.06",
    "qty": "0.000130",
    "reason_codes": [
      "MIN_NOTIONAL_CANNOT_BE_MET_WITH_CAP_AND_PRECISION",
      "BROKER_MIN_NOTIONAL_NOT_MET"
    ],
    "symbol": "BTC/USD"
  },
  {
    "asset_class": "crypto",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "2114.243",
    "qty": "0.004729",
    "reason_codes": [
      "MIN_NOTIONAL_CANNOT_BE_MET_WITH_CAP_AND_PRECISION",
      "BROKER_MIN_NOTIONAL_NOT_MET"
    ],
    "symbol": "ETH/USD"
  },
  {
    "asset_class": "crypto",
    "final_action": "SKIP_GUARDRAIL_OR_TRUTH",
    "intended_notional": "9.99",
    "limit_price": "84.399",
    "qty": "0.118497",
    "reason_codes": [
      "MIN_NOTIONAL_CANNOT_BE_MET_WITH_CAP_AND_PRECISION",
      "REQUESTED_NOTIONAL_ABOVE_INTERNAL_MAX"
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
    "current_price": "298.89",
    "market_value": "5.052138",
    "qty": "0.016903",
    "side": "long",
    "symbol": "AAPL",
    "unrealized_pl": "0.052569"
  },
  {
    "asset_class": "us_equity",
    "avg_entry_price": "264.372",
    "cost_basis": "4.999803",
    "current_price": "259.13",
    "market_value": "4.900667",
    "qty": "0.018912",
    "side": "long",
    "symbol": "AMZN",
    "unrealized_pl": "-0.099136"
  },
  {
    "asset_class": "us_equity",
    "avg_entry_price": "397.628",
    "cost_basis": "4.998979",
    "current_price": "388.87",
    "market_value": "4.888874",
    "qty": "0.012572",
    "side": "long",
    "symbol": "GOOGL",
    "unrealized_pl": "-0.110105"
  },
  {
    "asset_class": "us_equity",
    "avg_entry_price": "221.284",
    "cost_basis": "4.999469",
    "current_price": "221.61",
    "market_value": "5.006835",
    "qty": "0.022593",
    "side": "long",
    "symbol": "NVDA",
    "unrealized_pl": "0.007366"
  },
  {
    "asset_class": "us_equity",
    "avg_entry_price": "703.048",
    "cost_basis": "4.999374",
    "current_price": "703.15",
    "market_value": "5.0001",
    "qty": "0.007111",
    "side": "long",
    "symbol": "QQQ",
    "unrealized_pl": "0.000726"
  },
  {
    "asset_class": "us_equity",
    "avg_entry_price": "736.628",
    "cost_basis": "4.999494",
    "current_price": "734.41",
    "market_value": "4.984441",
    "qty": "0.006787",
    "side": "long",
    "symbol": "SPY",
    "unrealized_pl": "-0.015053"
  },
  {
    "asset_class": "us_equity",
    "avg_entry_price": "409.966",
    "cost_basis": "4.999535",
    "current_price": "404.11",
    "market_value": "4.928121",
    "qty": "0.012195",
    "side": "long",
    "symbol": "TSLA",
    "unrealized_pl": "-0.071414"
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
  "buying_power": "199964.76",
  "cash": "99965",
  "equity": "99999.76",
  "long_market_value": "34.76",
  "multiplier": "2",
  "pattern_day_trader": false,
  "portfolio_value": "99999.76",
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
      "MIN_NOTIONAL_CANNOT_BE_MET_WITH_CAP_AND_PRECISION",
      "BROKER_MIN_NOTIONAL_NOT_MET",
      "REQUESTED_NOTIONAL_ABOVE_INTERNAL_MAX"
    ],
    "selection_status": "NO_SAFE_CANDIDATES_AFTER_REAL_TRUTH_GATES"
  }
]
```
