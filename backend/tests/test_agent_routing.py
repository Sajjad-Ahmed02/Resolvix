from __future__ import annotations

import pytest

from app.ai.routing import (
    AMBIGUOUS_CLARIFICATION,
    ORDER_NUMBER_CLARIFICATION,
    Capability,
    Intent,
    detect_intent,
    extract_order_number,
    is_follow_up,
    resolve_route,
)
from app.tools.knowledge_tools import KNOWLEDGE_SEARCH_TOOL_NAME
from app.tools.order_tools import ORDER_DETAILS_TOOL_NAME


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("Where is my order RX-2026-1001?", "RX-2026-1001"),
        ("Please check rx 2026 1001 for me", "RX-2026-1001"),
        ("order RX-2026-00042 is late", "RX-2026-00042"),
        ("My order number is RX-2026-1001.", "RX-2026-1001"),
    ],
)
def test_extract_order_number_normalizes_supported_forms(
    content: str,
    expected: str,
) -> None:
    assert extract_order_number(content) == expected


@pytest.mark.parametrize(
    "content",
    [
        "Where is my order?",
        "PH2-A-abc123",
        "RX-1001",
        "RX-2026-12",
        "RX-2026-123456789",
    ],
)
def test_extract_order_number_ignores_unsupported_forms(content: str) -> None:
    assert extract_order_number(content) is None


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("Where is my order RX-2026-1001?", Intent.ORDER_STATUS),
        ("My delivery is late", Intent.ORDER_STATUS),
        ("Can you track my package?", Intent.ORDER_STATUS),
        ("What did I order?", Intent.ORDER_ITEMS),
        ("What is in my order?", Intent.ORDER_ITEMS),
        ("Can I return an opened item?", Intent.RETURN_REFUND_POLICY),
        ("How do refunds work?", Intent.RETURN_REFUND_POLICY),
        ("How long does standard shipping take?", Intent.SHIPPING_FAQ),
        ("Do you ship internationally?", Intent.SHIPPING_FAQ),
        ("What payment methods do you accept?", Intent.PAYMENT_FAQ),
        ("Can I pay with PayPal?", Intent.PAYMENT_FAQ),
        ("Hello", Intent.GENERAL),
        ("What can Resolvix help with?", Intent.GENERAL),
        ("Please help", Intent.AMBIGUOUS),
        ("I have a problem with something", Intent.AMBIGUOUS),
    ],
)
def test_detect_intent_uses_the_routing_table(
    content: str,
    expected: Intent,
) -> None:
    assert detect_intent(content) == expected


def test_order_follow_up_only_becomes_order_intent_with_context() -> None:
    content = "When will it arrive?"

    assert is_follow_up("What about the delivery?") is True
    assert detect_intent(content, has_order_context=False) is Intent.AMBIGUOUS
    assert detect_intent(content, has_order_context=True) is Intent.ORDER_STATUS


def test_missing_order_number_returns_a_clarification_route() -> None:
    route = resolve_route("Where is my order?")

    assert route.intent is Intent.ORDER_STATUS
    assert route.requires_clarification is True
    assert route.clarification_reason == "missing_order_number"
    assert route.clarification_message == ORDER_NUMBER_CLARIFICATION
    assert route.capabilities == (Capability.ASK_FOR_DETAILS,)
    assert route.allowed_tool_names == ()


def test_order_route_allows_only_the_registered_order_tool() -> None:
    route = resolve_route("Where is my order RX-2026-1001?")

    assert route.intent is Intent.ORDER_STATUS
    assert route.requires_clarification is False
    assert route.order_number == "RX-2026-1001"
    assert route.order_number_from_context is False
    assert route.capabilities == (
        Capability.ORDER_LOOKUP,
        Capability.LLM_RESPONSE,
    )
    assert route.allowed_tool_names == (ORDER_DETAILS_TOOL_NAME,)


def test_order_follow_up_reuses_the_previous_order_number() -> None:
    route = resolve_route(
        "When will it arrive?",
        previous_order_number="RX-2026-1001",
        previous_intent=Intent.ORDER_STATUS,
        previous_user_message="Where is my order RX-2026-1001?",
    )

    assert route.intent is Intent.ORDER_STATUS
    assert route.order_number == "RX-2026-1001"
    assert route.order_number_from_context is True
    assert route.requires_clarification is False
    assert route.allowed_tool_names == (ORDER_DETAILS_TOOL_NAME,)


def test_order_items_follow_up_reuses_the_previous_order_number() -> None:
    route = resolve_route(
        "What did I order?",
        previous_order_number="RX-2026-1001",
        previous_intent=Intent.ORDER_STATUS,
    )

    assert route.intent is Intent.ORDER_ITEMS
    assert route.order_number == "RX-2026-1001"
    assert route.order_number_from_context is True


@pytest.mark.parametrize(
    ("content", "expected_intent"),
    [
        ("What is your return policy?", Intent.RETURN_REFUND_POLICY),
        ("How long does standard shipping take?", Intent.SHIPPING_FAQ),
        ("What payment methods do you accept?", Intent.PAYMENT_FAQ),
    ],
)
def test_policy_routes_allow_only_the_knowledge_tool(
    content: str,
    expected_intent: Intent,
) -> None:
    route = resolve_route(content)

    assert route.intent is expected_intent
    assert route.requires_clarification is False
    assert route.knowledge_query == content
    assert route.capabilities == (
        Capability.KNOWLEDGE_SEARCH,
        Capability.LLM_RESPONSE,
    )
    assert route.allowed_tool_names == (KNOWLEDGE_SEARCH_TOOL_NAME,)


def test_policy_follow_up_inherits_intent_and_previous_question() -> None:
    route = resolve_route(
        "What about opened items?",
        previous_intent=Intent.RETURN_REFUND_POLICY,
        previous_user_message="What is your return policy?",
    )

    assert route.intent is Intent.RETURN_REFUND_POLICY
    assert route.knowledge_query == (
        "What is your return policy? What about opened items?"
    )
    assert route.allowed_tool_names == (KNOWLEDGE_SEARCH_TOOL_NAME,)


def test_ambiguous_request_returns_a_clarification_route() -> None:
    route = resolve_route("Please help")

    assert route.intent is Intent.AMBIGUOUS
    assert route.requires_clarification is True
    assert route.clarification_reason == "ambiguous_request"
    assert route.clarification_message == AMBIGUOUS_CLARIFICATION
    assert route.capabilities == (Capability.ASK_FOR_DETAILS,)
    assert route.allowed_tool_names == ()


def test_general_question_routes_to_the_model_without_tools() -> None:
    route = resolve_route("What can Resolvix help with?")

    assert route.intent is Intent.GENERAL
    assert route.requires_clarification is False
    assert route.capabilities == (Capability.LLM_RESPONSE,)
    assert route.allowed_tool_names == ()
