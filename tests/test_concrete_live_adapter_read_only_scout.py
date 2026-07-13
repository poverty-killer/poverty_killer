from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import main as runtime_main
from app.config import Config
from app.state.state_store import StateStore


ORDER_ROUTER = Path("app/execution/order_router.py")
BROKER_ADAPTER = Path("app/execution/broker_adapter.py")
LIVE_BROKER = Path("app/execution/live_broker.py")
CONFIG = Path("app/config.py")


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def test_broker_adapter_and_live_broker_are_not_concrete_active_adapters():
    broker_adapter = _source(BROKER_ADAPTER)
    live_broker = _source(LIVE_BROKER)

    assert "Protocol/ABC definitions only" in broker_adapter
    assert "NO IMPLEMENTATION" in broker_adapter
    assert "class BrokerAdapter(Protocol)" in broker_adapter
    assert "def get_account" in broker_adapter
    assert "def get_positions" in broker_adapter
    assert "def get_open_orders" in broker_adapter
    assert "def get_fills" in broker_adapter
    assert "def submit_order" in broker_adapter
    assert "def cancel_order" in broker_adapter

    assert "Under construction" in live_broker
    assert "def submit_order" not in live_broker
    assert "def cancel_order" not in live_broker
    assert "requests." not in live_broker


def test_order_router_contains_read_only_fetch_foundation_but_mixes_mutating_authority():
    order_router = _source(ORDER_ROUTER)

    read_only_surfaces = {
        "fetch_balances": "def fetch_balances",
        "fetch_open_orders": "def fetch_open_orders",
        "fetch_normalized_open_orders": "def fetch_normalized_open_orders",
        "fetch_fills": "def fetch_fills",
        "fetch_positions": "def fetch_positions",
        "get_exchange_truth_snapshot": "def get_exchange_truth_snapshot",
        "get_order_status": "def get_order_status",
    }
    mutating_surfaces = {
        "submit_order": "def submit_order",
        "cancel_order": "def cancel_order",
        "kraken_submit": "def _submit_order_kraken",
        "kraken_cancel": "def _cancel_order_kraken",
        "alpaca_submit": "def _submit_order_alpaca",
        "alpaca_cancel": "def _cancel_order_alpaca",
    }

    for marker in read_only_surfaces.values():
        assert marker in order_router
    for marker in mutating_surfaces.values():
        assert marker in order_router

    assert '"/private/Balance"' in order_router
    assert '"/private/OpenOrders"' in order_router
    assert '"/private/TradesHistory"' in order_router
    assert '"/private/QueryOrders"' in order_router
    assert '"/private/AddOrder"' in order_router
    assert '"/private/CancelOrder"' in order_router
    assert "def get_exchange_truth_snapshot" in order_router
    assert '"account_id"' not in order_router[order_router.index("def get_exchange_truth_snapshot") : order_router.index("def submit_order")]
    assert '"environment"' not in order_router[order_router.index("def get_exchange_truth_snapshot") : order_router.index("def submit_order")]


def test_config_defaults_to_paper_with_optional_credentials_and_default_off_safety_gate():
    config = Config()
    config_source = _source(CONFIG)

    assert config.broker_mode == "paper"
    assert config.kraken_api_key in {None, ""}
    assert config.kraken_api_secret in {None, ""}
    assert config.alpaca_paper is True
    assert config.shadow_read_only is False
    assert 'broker_mode: Literal["paper", "live"] = Field(default="paper"' in config_source
    assert "kraken_api_key: Optional[str]" in config_source
    assert "kraken_api_secret: Optional[str]" in config_source
    assert "alpaca_api_key: Optional[str]" in config_source
    assert "alpaca_api_secret: Optional[str]" in config_source
    assert "shadow_read_only: bool" in config_source
    assert "sandbox_read_only" not in config_source


def test_live_reservation_lifecycle_stays_disabled_under_live_config(tmp_path):
    root = runtime_main.SovereignHeartbeat.__new__(runtime_main.SovereignHeartbeat)
    root.state_store = StateStore(str(tmp_path / "state.db"))
    root._bootstrap_reservation_lifecycle_disabled(
        SimpleNamespace(
            initial_capital=20_000.0,
            broker_mode="live",
            reservation_lifecycle_paper_enabled=True,
        )
    )

    assert root.reservation_lifecycle_enabled is False
    assert root.reservation_lifecycle_bootstrap_status["reservation_lifecycle_live_blocked"] is True
    assert root.reservation_lifecycle_bootstrap_status["broker_command_performed"] is False
    assert root.reservation_lifecycle_bootstrap_status["runtime_lifecycle_wired"] is False


def test_scout_classification_requires_read_only_wrapper_before_broker_calls():
    order_router = _source(ORDER_ROUTER)
    broker_adapter = _source(BROKER_ADAPTER)

    classification = {
        "concrete_adapter": "order_router_mixed_read_mutate_foundation",
        "safe_for_broker_call_now": False,
        "next_required_seam": "read_only_wrapper_config_gate",
        "has_protocol_contract": "class BrokerAdapter(Protocol)" in broker_adapter,
        "has_read_fetchers": all(
            marker in order_router
            for marker in (
                "def fetch_balances",
                "def fetch_open_orders",
                "def fetch_fills",
                "def fetch_positions",
            )
        ),
        "mutating_methods_in_same_class": all(
            marker in order_router
            for marker in (
                "def submit_order",
                "def cancel_order",
                "def _submit_order_kraken",
                "def _cancel_order_kraken",
            )
        ),
    }

    assert classification["has_protocol_contract"] is True
    assert classification["has_read_fetchers"] is True
    assert classification["mutating_methods_in_same_class"] is True
    assert classification["safe_for_broker_call_now"] is False
    assert classification["next_required_seam"] == "read_only_wrapper_config_gate"
