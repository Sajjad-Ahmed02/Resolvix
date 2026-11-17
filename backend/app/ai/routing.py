"""Intent-to-capability routing for the customer-support agent.

The router is deliberately deterministic. It narrows the capabilities the
model may use for a turn, recovers order numbers from earlier successful
lookups, and produces a controlled clarification when the request is too
ambiguous or a required identifier is missing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from app.tools.knowledge_tools import KNOWLEDGE_SEARCH_TOOL_NAME
from app.tools.order_tools import ORDER_DETAILS_TOOL_NAME

ORDER_NUMBER_MAX_LENGTH = 30
ORDER_NUMBER_PATTERN = re.compile(
    r"\b(?P<number>[A-Z]{2,6})[\s-]?(?P<year>\d{4})[\s-](?P<sequence>\d{3,8})\b",
    re.IGNORECASE,
)


class Intent(str, Enum):
    """Customer intents supported by the routing table."""

    ORDER_STATUS = "order_status"
    ORDER_ITEMS = "order_items"
    RETURN_REFUND_POLICY = "return_refund_policy"
    SHIPPING_FAQ = "shipping_faq"
    PAYMENT_FAQ = "payment_faq"
    GENERAL = "general"
    AMBIGUOUS = "ambiguous"


class Capability(str, Enum):
    """Approved backend capabilities the orchestrator can coordinate."""

    ORDER_LOOKUP = "order_lookup"
    KNOWLEDGE_SEARCH = "knowledge_search"
    LLM_RESPONSE = "llm_response"
    ASK_FOR_DETAILS = "ask_for_details"


# The routing table from the Phase 7 specification. Order lookups use the
# registered order tool; policy/FAQ questions use controlled RAG; general
# supported questions use the model under the system rules; ambiguous requests
# ask for the missing context instead of guessing.
INTENT_CAPABILITIES: dict[Intent, tuple[Capability, ...]] = {
    Intent.ORDER_STATUS: (Capability.ORDER_LOOKUP, Capability.LLM_RESPONSE),
    Intent.ORDER_ITEMS: (Capability.ORDER_LOOKUP, Capability.LLM_RESPONSE),
    Intent.RETURN_REFUND_POLICY: (
        Capability.KNOWLEDGE_SEARCH,
        Capability.LLM_RESPONSE,
    ),
    Intent.SHIPPING_FAQ: (Capability.KNOWLEDGE_SEARCH, Capability.LLM_RESPONSE),
    Intent.PAYMENT_FAQ: (Capability.KNOWLEDGE_SEARCH, Capability.LLM_RESPONSE),
    Intent.GENERAL: (Capability.LLM_RESPONSE,),
    Intent.AMBIGUOUS: (Capability.ASK_FOR_DETAILS,),
}

ORDER_NUMBER_CLARIFICATION = (
    "I can help with your order. Please share the order number from your order "
    "confirmation, for example RX-2026-1001."
)
AMBIGUOUS_CLARIFICATION = (
    "I want to make sure I help with the right thing. Is this about an order, "
    "a return or refund, shipping, payment, or something else?"
)

_RETURN_REFUND_PATTERNS = (
    r"\breturn(?:s|ed|ing)?\b",
    r"\brefund(?:s|ed|ing)?\b",
    r"\bexchange(?:s|d|ing)?\b",
    r"\bmoney[\s-]?back\b",
    r"\bsend\b.{0,30}\bback\b",
    r"\bwarrant(?:y|ies)\b",
    r"\bdefective\b",
    r"\bdamaged\b",
    r"\brestock(?:ing)?\s+fee\b",
)

_ORDER_ITEM_PATTERNS = (
    r"\bwhat\s+(?:did|do|have)\s+i\s+(?:order|buy|purchase)\b",
    r"\bwhat(?:'s| is)\s+in\s+(?:my|the)\s+order\b",
    r"\b(?:items?|products?|contents?)\s+(?:in|on|of)\s+(?:my|the)\s+order\b",
    r"\border\s+(?:items?|contents?|products?)\b",
    r"\bwhich\s+products?\b.{0,40}\border\b",
    r"\blist\s+(?:the\s+)?(?:items?|products?)\b.{0,40}\border\b",
)

_ORDER_STATUS_PATTERNS = (
    r"\bwhere(?:'s| is| are)\s+(?:my|the)\s+"
    r"(?:order|package|parcel|shipment|delivery)\b",
    r"\b(?:order|package|parcel|shipment|delivery)\b"
    r".{0,80}\b(?:status|tracking|track|arriv(?:e|es|ing|al)|"
    r"deliver(?:y|ed)?|late|delayed|eta|estimated|shipped|shipping|"
    r"in[\s-]?transit|out\s+for\s+delivery|cancel(?:led)?|confirmed|"
    r"processing|missing|stuck)\b",
    r"\b(?:when|will|did|has|had)\b.{0,60}\b(?:order|package|parcel|"
    r"shipment|delivery)\b.{0,60}\b(?:arrive|ship|deliver|get\s+here|come)\b",
    r"\btrack(?:ing)?\s+(?:my|the|an)\s+"
    r"(?:order|package|parcel|shipment|delivery)\b",
    r"\bmy\s+(?:order|package|parcel|shipment|delivery)\s+"
    r"(?:is|was|has\s+been)\s+(?:late|delayed|missing|stuck|processing|"
    r"confirmed|shipped|cancelled|canceled|delivered)\b",
    r"\bestimated\s+delivery\b",
    r"\border\s+status\b",
)

_SHIPPING_FAQ_PATTERNS = (
    r"\bshipp?(?:ing|ed|s)?\b",
    r"\bdelivery\s+(?:options?|costs?|fees?|times?|areas?|address)\b",
    r"\bship\s+to\b",
    r"\binternational\b",
    r"\bcarrier\b",
    r"\bcourier\b",
    r"\btracking\s+number\b",
)

_PAYMENT_FAQ_PATTERNS = (
    r"\bpay(?:ment|ments|ing)?\b",
    r"\bcredit\s+card\b",
    r"\bdebit\s+card\b",
    r"\bpaypal\b",
    r"\bbilling\b",
    r"\binvoice\b",
    r"\bcharg(?:e|ed|es)\b",
    r"\bcheckout\b",
    r"\bcash\s+on\s+delivery\b",
    r"\b(?:gift\s+cards?|vouchers?)\b",
)

_ORDER_FOLLOW_UP_PATTERNS = (
    r"\bwhen\s+will\s+it\s+(?:arrive|be\s+delivered|get\s+here|ship)\b",
    r"\bwhere\s+is\s+it\b",
    r"\bhas\s+it\s+(?:shipped|arrived|been\s+delivered)\b",
    r"\bis\s+it\s+(?:shipped|arriving|delivered|in\s+transit|late)\b",
    r"\bwhat\s+about\s+(?:the\s+)?(?:delivery|shipping|tracking)\b",
)

_FOLLOW_UP_PATTERNS = (
    r"^(?:and|but|so|then|also)\b",
    r"\bwhat\s+about\b",
    r"\bhow\s+about\b",
    r"\bwhat\s+if\b",
    r"\bdoes\s+(?:that|this|it)\s+apply\b",
    r"\bcan\s+i\s+still\b",
    r"\bhow\s+long\b",
    r"\bhow\s+much\b",
    r"\bwhy\b",
    r"\breally\b",
    r"^(?:and\s+then|then)\s*[?!.]*$",
)

_AMBIGUOUS_PATTERNS = (
    r"^(?:please\s+)?(?:help(?:\s+me)?|i\s+need\s+help|can\s+you\s+help"
    r"(?:\s+me)?|support)\s*[.!?]*$",
    r"\b(?:it|this|that|something|things?)\b.{0,50}\b(?:broken|"
    r"doesn'?t\s+work|don'?t\s+work|not\s+working|isn'?t\s+working|wrong|"
    r"problem|issue)\b",
    r"\bi\s+have\s+(?:a|an)\s+(?:problem|issue|question)\b",
    r"^(?:what\s+about\s+(?:it|this|that)|and|so)\s*[.!?]*$",
)

_GREETING_PATTERNS = (
    r"^(?:hi|hello|hey|good\s+(?:morning|afternoon|evening))\b",
    r"^(?:thanks|thank\s+you|cheers|great|perfect|okay|ok|sure)\b",
)


def extract_order_number(content: str) -> str | None:
    """Return the first order number in *content* in canonical form."""
    match = ORDER_NUMBER_PATTERN.search(content)
    if match is None:
        return None
    normalized = (
        f"{match.group('number').upper()}-"
        f"{match.group('year')}-"
        f"{match.group('sequence')}"
    )
    if len(normalized) > ORDER_NUMBER_MAX_LENGTH:
        return None
    return normalized


def _matches(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def is_follow_up(content: str) -> bool:
    """Heuristically identify a turn that depends on the previous topic."""
    return _matches(_FOLLOW_UP_PATTERNS, content.strip())


def _normalize_query_part(value: str, limit: int = 500) -> str:
    normalized = " ".join(value.split())
    return normalized[:limit]


def detect_intent(
    content: str,
    *,
    has_order_context: bool = False,
) -> Intent:
    """Classify one customer message using the routing table rules."""
    text = content.strip()
    if not text:
        return Intent.AMBIGUOUS

    order_number = extract_order_number(text)

    if _matches(_RETURN_REFUND_PATTERNS, text):
        return Intent.RETURN_REFUND_POLICY
    if _matches(_ORDER_ITEM_PATTERNS, text):
        return Intent.ORDER_ITEMS
    if order_number is not None or _matches(_ORDER_STATUS_PATTERNS, text):
        return Intent.ORDER_STATUS
    if _matches(_ORDER_FOLLOW_UP_PATTERNS, text):
        return Intent.ORDER_STATUS if has_order_context else Intent.AMBIGUOUS
    if _matches(_SHIPPING_FAQ_PATTERNS, text):
        return Intent.SHIPPING_FAQ
    if _matches(_PAYMENT_FAQ_PATTERNS, text):
        return Intent.PAYMENT_FAQ
    if _matches(_GREETING_PATTERNS, text):
        return Intent.GENERAL
    if _matches(_AMBIGUOUS_PATTERNS, text):
        return Intent.AMBIGUOUS
    return Intent.GENERAL


@dataclass(frozen=True, slots=True)
class CapabilityRoute:
    """The approved capabilities and hints for one orchestrated turn."""

    intent: Intent
    capabilities: tuple[Capability, ...]
    order_number: str | None = None
    knowledge_query: str | None = None
    clarification_reason: str | None = None
    clarification_message: str | None = None
    order_number_from_context: bool = False

    @property
    def requires_clarification(self) -> bool:
        return self.clarification_message is not None

    @property
    def allowed_tool_names(self) -> tuple[str, ...]:
        names: list[str] = []
        if Capability.ORDER_LOOKUP in self.capabilities:
            names.append(ORDER_DETAILS_TOOL_NAME)
        if Capability.KNOWLEDGE_SEARCH in self.capabilities:
            names.append(KNOWLEDGE_SEARCH_TOOL_NAME)
        return tuple(names)


def resolve_route(
    content: str,
    *,
    previous_order_number: str | None = None,
    previous_intent: Intent | None = None,
    previous_user_message: str | None = None,
) -> CapabilityRoute:
    """Resolve a customer message to one routing-table capability set.

    A follow-up that has no strong keywords inherits the previous supported
    intent. Order follow-ups reuse the last successfully looked-up order number
    so "When will it arrive?" can be answered without asking the customer to
    repeat it.
    """
    normalized = content.strip()
    explicit_order_number = extract_order_number(normalized)
    has_order_context = previous_order_number is not None
    intent = detect_intent(normalized, has_order_context=has_order_context)
    follow_up = is_follow_up(normalized)

    if (
        intent == Intent.GENERAL
        and follow_up
        and previous_intent is not None
        and previous_intent not in {Intent.GENERAL, Intent.AMBIGUOUS}
    ):
        intent = previous_intent
    elif intent == Intent.AMBIGUOUS and follow_up and previous_intent is not None:
        if previous_intent not in {Intent.GENERAL, Intent.AMBIGUOUS}:
            intent = previous_intent

    if intent in {Intent.ORDER_STATUS, Intent.ORDER_ITEMS}:
        order_number = explicit_order_number or previous_order_number
        if order_number is None:
            return CapabilityRoute(
                intent=intent,
                capabilities=(Capability.ASK_FOR_DETAILS,),
                clarification_reason="missing_order_number",
                clarification_message=ORDER_NUMBER_CLARIFICATION,
            )
        return CapabilityRoute(
            intent=intent,
            capabilities=INTENT_CAPABILITIES[intent],
            order_number=order_number,
            order_number_from_context=(
                explicit_order_number is None and previous_order_number is not None
            ),
        )

    if intent in {
        Intent.RETURN_REFUND_POLICY,
        Intent.SHIPPING_FAQ,
        Intent.PAYMENT_FAQ,
    }:
        knowledge_query = normalized
        if (
            follow_up
            and previous_intent == intent
            and previous_user_message
        ):
            knowledge_query = (
                f"{_normalize_query_part(previous_user_message)} "
                f"{_normalize_query_part(normalized)}"
            )
        return CapabilityRoute(
            intent=intent,
            capabilities=INTENT_CAPABILITIES[intent],
            knowledge_query=knowledge_query,
        )

    if intent == Intent.AMBIGUOUS:
        return CapabilityRoute(
            intent=intent,
            capabilities=(Capability.ASK_FOR_DETAILS,),
            clarification_reason="ambiguous_request",
            clarification_message=AMBIGUOUS_CLARIFICATION,
        )

    return CapabilityRoute(
        intent=Intent.GENERAL,
        capabilities=INTENT_CAPABILITIES[Intent.GENERAL],
    )


__all__ = [
    "AMBIGUOUS_CLARIFICATION",
    "INTENT_CAPABILITIES",
    "ORDER_NUMBER_CLARIFICATION",
    "Capability",
    "CapabilityRoute",
    "Intent",
    "detect_intent",
    "extract_order_number",
    "is_follow_up",
    "resolve_route",
]
