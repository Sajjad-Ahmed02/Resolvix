from __future__ import annotations

from datetime import date
import json

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.ai.providers.base import ToolCall
from app.db.session import SessionLocal
from app.tools import order_tools
from app.tools.base import ToolContext
from app.tools.order_tools import (
    ORDER_DETAILS_TOOL_NAME,
    OrderDetailsTool,
    get_order_details,
)
from app.tools.registry import build_default_registry


def _context(session, user_id) -> ToolContext:
    return ToolContext(session=session, user_id=user_id)


def _call(arguments: dict, *, name: str = ORDER_DETAILS_TOOL_NAME) -> ToolCall:
    return ToolCall(id="call_test", name=name, arguments=arguments)


def test_registry_exposes_only_the_allow_listed_order_tool() -> None:
    registry = build_default_registry()

    definitions = registry.definitions

    assert [definition.name for definition in definitions] == [
        ORDER_DETAILS_TOOL_NAME
    ]
    schema = definitions[0].parameters
    assert schema["type"] == "object"
    assert schema["required"] == ["order_number"]
    assert schema["additionalProperties"] is False
    assert "authenticated_user_id" not in schema["properties"]


def test_order_lookup_returns_status_delivery_and_items(accounts) -> None:
    session = SessionLocal()
    try:
        outcome = build_default_registry().execute(
            _call({"order_number": accounts["order_a_number"]}),
            _context(session, accounts["customer_a"]["id"]),
        )
    finally:
        session.close()

    assert outcome.ok is True
    assert outcome.data == {
        "order_number": accounts["order_a_number"],
        "status": "processing",
        "shipping_status": "in_transit",
        "estimated_delivery": date.today().isoformat(),
        "order_date": outcome.data["order_date"],
        "total_amount": "19.98",
        "items": [
            {
                "product_name": "Test USB-C Cable",
                "quantity": 2,
                "unit_price": "9.99",
            }
        ],
    }
    assert "T" in outcome.data["order_date"]


def test_get_order_details_function_uses_authenticated_user_id(accounts) -> None:
    session = SessionLocal()
    try:
        data = get_order_details(
            accounts["order_a_number"],
            accounts["customer_a"]["id"],
            session=session,
        )
    finally:
        session.close()

    assert data["order_number"] == accounts["order_a_number"]
    assert data["status"] == "processing"
    assert data["shipping_status"] == "in_transit"
    assert data["items"] == [
        {
            "product_name": "Test USB-C Cable",
            "quantity": 2,
            "unit_price": "9.99",
        }
    ]


def test_order_numbers_are_normalized_before_lookup(accounts) -> None:
    session = SessionLocal()
    try:
        outcome = build_default_registry().execute(
            _call({"order_number": f"  {accounts['order_a_number'].lower()}  "}),
            _context(session, accounts["customer_a"]["id"]),
        )
    finally:
        session.close()

    assert outcome.ok is True
    assert outcome.data["order_number"] == accounts["order_a_number"]


def test_other_customers_order_is_not_disclosed(accounts, monkeypatch) -> None:
    calls: list[str] = []
    original_order = order_tools.orders.get_for_user_by_number
    original_items = order_tools.orders.list_items_for_order

    def spy_order(*args, **kwargs):
        calls.append("order")
        return original_order(*args, **kwargs)

    def spy_items(*args, **kwargs):
        calls.append("items")
        return original_items(*args, **kwargs)

    monkeypatch.setattr(
        order_tools.orders,
        "get_for_user_by_number",
        spy_order,
    )
    monkeypatch.setattr(order_tools.orders, "list_items_for_order", spy_items)

    session = SessionLocal()
    try:
        outcome = build_default_registry().execute(
            _call({"order_number": accounts["order_b_number"]}),
            _context(session, accounts["customer_a"]["id"]),
        )
    finally:
        session.close()

    assert outcome.ok is False
    assert outcome.error_code == "order_not_found"
    assert outcome.data is None
    assert calls == ["order"]
    serialized = outcome.to_json()
    assert "Test Bluetooth Speaker" not in serialized
    assert "49.99" not in serialized
    assert "completed" not in serialized


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"order_number": ""},
        {"order_number": "   "},
        {"order_number": "RX 2026 1001"},
        {"order_number": "X" * 31},
        {"order_number": "RX-2026-1001' OR 1=1"},
        {
            "order_number": "RX-2026-1001",
            "authenticated_user_id": "00000000-0000-0000-0000-000000000000",
        },
    ],
)
def test_invalid_or_extra_arguments_are_rejected(accounts, arguments) -> None:
    session = SessionLocal()
    try:
        outcome = build_default_registry().execute(
            _call(arguments),
            _context(session, accounts["customer_a"]["id"]),
        )
    finally:
        session.close()

    assert outcome.ok is False
    assert outcome.error_code == "invalid_arguments"


def test_unknown_tools_are_rejected_without_execution(accounts) -> None:
    session = SessionLocal()
    try:
        outcome = build_default_registry().execute(
            _call(
                {"sql": "DROP TABLE orders"},
                name="execute_sql",
            ),
            _context(session, accounts["customer_a"]["id"]),
        )
    finally:
        session.close()

    assert outcome.ok is False
    assert outcome.error_code == "unknown_tool"


def test_database_failure_returns_a_sanitized_controlled_error(
    accounts,
    monkeypatch,
) -> None:
    def fail(*args, **kwargs):
        raise SQLAlchemyError("connection string password=super-secret")

    monkeypatch.setattr(
        order_tools.orders,
        "get_for_user_by_number",
        fail,
    )

    session = SessionLocal()
    try:
        outcome = OrderDetailsTool().execute(
            _context(session, accounts["customer_a"]["id"]),
            {"order_number": accounts["order_a_number"]},
        )
    finally:
        session.close()

    assert outcome.ok is False
    assert outcome.error_code == "database_error"
    assert "super-secret" not in outcome.error_message
    assert "super-secret" not in outcome.to_json()


def test_tool_outcome_json_is_small_and_structured(accounts) -> None:
    session = SessionLocal()
    try:
        outcome = build_default_registry().execute(
            _call({"order_number": accounts["order_a_number"]}),
            _context(session, accounts["customer_a"]["id"]),
        )
    finally:
        session.close()

    payload = json.loads(outcome.to_json())
    assert payload["ok"] is True
    assert payload["data"]["items"][0]["product_name"] == "Test USB-C Cable"
