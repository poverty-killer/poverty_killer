# Alpaca PAPER Credential / Environment Authority Audit

Date: 2026-05-21

Starting HEAD: d87e14d

Scope: safe diagnostics and report only. No autonomous PAPER run, no order placement, no cancel/replace, no broker mutation, and no production code changes.

## Credential Authority Path

The active helper path is:

- `AlpacaPaperBrokerAdapter.from_env()`
- `load_alpaca_paper_credentials()`
- `collect_alpaca_paper_read_only_reconciliation_truth(adapter)`

The helper reads exactly these Alpaca PAPER credential variables:

- `APCA_API_BASE_URL`
- `APCA_API_KEY_ID`
- `APCA_API_SECRET_KEY`

It also supports an optional credential file selector:

- `POVERTY_KILLER_ALPACA_PAPER_ENV_PATH`

If `POVERTY_KILLER_ALPACA_PAPER_ENV_PATH` is not set, the fallback file is:

- `/home/shahn/.poverty_killer_alpaca_paper_env`

Process environment values take precedence over fallback-file values.

## Endpoint / Live Safety

Expected paper endpoint:

- `https://paper-api.alpaca.markets`

Forbidden live endpoint:

- `https://api.alpaca.markets`

Observed WSL endpoint:

- `https://paper-api.alpaca.markets`

Verdict:

- exact paper endpoint: true
- live endpoint: false
- adapter environment: paper
- adapter live blocked: true
- credential status: configured

The adapter validates the exact paper endpoint before making requests and blocks live/non-paper endpoints. No live credential path was found in this audit.

## WSL Credential Shape

No secret values were printed.

WSL process environment:

| Variable | Present | Length | Quotes | Leading/trailing spaces | Newline |
| --- | ---: | ---: | ---: | ---: | ---: |
| `APCA_API_BASE_URL` | true | 32 | false | false | false |
| `APCA_API_KEY_ID` | true | 26 | false | false | false |
| `APCA_API_SECRET_KEY` | true | 44 | false | false | false |
| `POVERTY_KILLER_ALPACA_PAPER_ENV_PATH` | false | 0 | false | false | false |

Fallback file:

- exists: true
- path: `/home/shahn/.poverty_killer_alpaca_paper_env`

Fallback file credential shape:

| Variable | Present | Length | Quotes | Leading/trailing spaces | Newline |
| --- | ---: | ---: | ---: | ---: | ---: |
| `APCA_API_BASE_URL` | true | 32 | false | false | false |
| `APCA_API_KEY_ID` | true | 26 | false | false | false |
| `APCA_API_SECRET_KEY` | true | 44 | false | false | false |

WSL process environment and fallback file comparison:

| Variable | Same exact value |
| --- | ---: |
| `APCA_API_BASE_URL` | true |
| `APCA_API_KEY_ID` | true |
| `APCA_API_SECRET_KEY` | true |

## Windows PowerShell Comparison

The audit attempted to compare sanitized Windows PowerShell environment visibility from WSL without printing secrets.

Result:

- Windows probe available from this WSL shell: false
- blocker: `UtilBindVsockAnyPort:309: socket failed 1`

Therefore, this audit cannot truthfully prove whether the Windows PowerShell process environment has the same key/secret pair as WSL. The current blocker is the known WSL/Windows interop failure, not a repo credential-loader finding.

## Read-Only Alpaca PAPER Reconciliation

Approved read-only helper used:

- `AlpacaPaperBrokerAdapter.from_env(timeout=20.0)`
- `collect_alpaca_paper_read_only_reconciliation_truth(adapter)`

Individual GET results:

| Request | Path | Method | HTTP status | OK | Reason | Message | Mutation |
| --- | --- | --- | ---: | ---: | --- | --- | ---: |
| account | `/v2/account` | GET | 401 | false | `HTTP_401` | `unauthorized.` | false |
| positions | `/v2/positions` | GET | 401 | false | `HTTP_401` | `unauthorized.` | false |
| open orders | `/v2/orders` | GET | 401 | false | `HTTP_401` | `unauthorized.` | false |

Helper result:

- status: `FAILED_CLOSED`
- reason_codes: `BROKER_READ_ONLY_GET_FAILED`
- account_status: `missing`
- positions_count: 0
- open_orders_count: 0
- endpoint: `https://paper-api.alpaca.markets`
- environment: `paper`
- live_endpoint_used: false
- mutation_occurred: false
- GET count: 3
- POST count: 0

The helper only supports read-only account, positions, and open-order reconciliation for this path. No order-history query was run because the adapter requires `/v2/orders` GETs to use `status=open`.

## Findings

1. The helper reads the correct Alpaca PAPER env names:
   `APCA_API_BASE_URL`, `APCA_API_KEY_ID`, and `APCA_API_SECRET_KEY`.

2. WSL has configured credentials with correct shape:
   exact paper endpoint, key length 26, secret length 44, no quotes, no leading/trailing spaces, and no newlines.

3. WSL process env and `/home/shahn/.poverty_killer_alpaca_paper_env` contain the same exact credential values.

4. The adapter is not silently using the live endpoint. It reports paper environment, blocks live, and uses `https://paper-api.alpaca.markets`.

5. Broker-canonical read-only GETs still return `HTTP_401 unauthorized.` for account, positions, and open orders.

6. Windows PowerShell versus WSL credential equality could not be proven from this shell because WSL interop failed before the sanitized comparison could run.

## Exact Current Reason

Alpaca PAPER read-only reconciliation is still blocked because Alpaca returns `HTTP_401 unauthorized.` for the configured WSL paper credentials on all approved GET requests.

This report does not infer whether the key is wrong, expired, revoked, live-vs-paper mismatched, account-scoped incorrectly, or different from the Windows PowerShell key. Those remain unproven until Windows PowerShell environment truth or Alpaca key authority is checked directly.

## Recommended Next Step

Run a sanitized Windows PowerShell credential-shape check from the repo directory, then run the same read-only helper from Windows PowerShell. Do not print secrets.

Required Windows-side facts:

- endpoint equals `https://paper-api.alpaca.markets`
- key present and length 26
- secret present and length 44
- no quotes/spaces/newlines
- read-only account/positions/open-orders GET result
- GET count
- POST count remains 0

If Windows succeeds while WSL returns 401, the problem is WSL credential authority. If Windows also returns 401 with the same shaped key, the problem is the Alpaca PAPER key/account authority, not repo code.

## Verdict

CONDITIONAL

The repo helper path is using the correct variables and blocks live/non-paper endpoints, and WSL credential formatting looks clean. The read-only broker truth remains unresolved because Alpaca returns `HTTP_401 unauthorized.` with GET count 3 and POST count 0. Windows PowerShell credential equality could not be confirmed from this WSL shell due the WSL interop blocker.
