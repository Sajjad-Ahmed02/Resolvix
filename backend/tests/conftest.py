from __future__ import annotations

import os

# Configure test-only settings before app modules import Settings. Real
# environment variables take precedence over backend/.env.
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "phase2-test-only-secret-key-0123456789abcdef0123456789abcdef",
)
os.environ.setdefault("DEBUG", "false")

import uuid
from collections.abc import Sequence
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.ai.dependencies import get_llm_provider
from app.ai.providers.base import (
    ChatMessage,
    LLMProvider,
    LLMResponse,
    ToolCall,
    ToolDefinition,
)
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.knowledge.dependencies import (
    get_knowledge_ingestor,
    get_knowledge_retriever,
)
from app.knowledge.ingestion import KnowledgeIngestor
from app.knowledge.retrieval import RetrievedChunk
from app.main import app
from app.models import (
    Conversation,
    FAQ,
    KnowledgeDocument,
    Message,
    Order,
    OrderItem,
    User,
)


TEST_PASSWORD = "TestPass123!"


class StubLLMProvider(LLMProvider):
    """Deterministic provider so tests never call a real model vendor."""

    name = "stub"
    model = "stub-model"

    def __init__(self) -> None:
        self.calls: list[list[ChatMessage]] = []
        self.tool_definitions: list[tuple[ToolDefinition, ...]] = []
        self.pending_tool_calls: list[tuple[ToolCall, ...]] = []
        self.reply = "This is a generated test reply."
        self.error: Exception | None = None
        self.closed = False

    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolDefinition] | None = None,
    ) -> LLMResponse:
        self.calls.append(list(messages))
        self.tool_definitions.append(tuple(tools or ()))
        if self.error is not None:
            raise self.error
        if self.pending_tool_calls:
            tool_calls = self.pending_tool_calls.pop(0)
            return LLMResponse(
                content="",
                provider=self.name,
                model=self.model,
                finish_reason="tool_calls",
                usage={"input_tokens": 12, "output_tokens": 8},
                tool_calls=tool_calls,
            )
        return LLMResponse(
            content=self.reply,
            provider=self.name,
            model=self.model,
            finish_reason="stop",
            usage={"input_tokens": 12, "output_tokens": 8},
        )

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def fake_llm_provider():
    """Replace the real provider for every test."""
    provider = StubLLMProvider()
    app.dependency_overrides[get_llm_provider] = lambda: provider
    try:
        yield provider
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)


class StubKnowledgeRetriever:
    """Deterministic retriever so tests never load the embedding model."""

    def __init__(self) -> None:
        self.results: list[RetrievedChunk] = []
        self.error: Exception | None = None
        self.queries: list[str] = []

    async def retrieve(
        self,
        session,
        query: str,
        *,
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return list(self.results)


@pytest.fixture(autouse=True)
def fake_knowledge_retriever():
    """Replace pgvector retrieval for every API test by default."""
    retriever = StubKnowledgeRetriever()
    app.dependency_overrides[get_knowledge_retriever] = lambda: retriever
    try:
        yield retriever
    finally:
        app.dependency_overrides.pop(get_knowledge_retriever, None)


class DeterministicEmbedder:
    """Token-word embedder so admin ingestion tests stay fast and offline."""

    model_name = "test-embedder"
    dimension = 384
    max_seq_length = 256

    def reusable_token_limit(self) -> int:
        return 254

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def encode_tokens(self, text: str) -> list[str]:
        return text.split()

    def decode_tokens(self, tokens) -> str:
        return " ".join(tokens)

    async def embed_documents(self, texts):
        return [[0.5] * 384 for _ in texts]

    async def embed_query(self, text: str):
        return [0.5] * 384


@pytest.fixture(autouse=True)
def fake_knowledge_ingestor():
    """Exercise real chunking/database sync without the sentence model."""
    ingestor = KnowledgeIngestor(
        DeterministicEmbedder(),
        max_tokens=200,
        overlap_tokens=40,
    )
    app.dependency_overrides[get_knowledge_ingestor] = lambda: ingestor
    try:
        yield ingestor
    finally:
        app.dependency_overrides.pop(get_knowledge_ingestor, None)


@pytest.fixture(scope="session", autouse=True)
def cleanup_stale_test_rows():
    """Remove temporary rows left by an interrupted previous test run."""
    session = SessionLocal()
    session.execute(delete(FAQ).where(FAQ.category.like("phase5-test-%")))
    session.execute(
        delete(KnowledgeDocument).where(
            KnowledgeDocument.category.like("phase5-test-%")
        )
    )
    stale_ids = list(
        session.scalars(
            select(User.id).where(User.email.like("phase2-%"))
        ).all()
    )
    if stale_ids:
        session.execute(delete(Order).where(Order.user_id.in_(stale_ids)))
        session.execute(delete(User).where(User.id.in_(stale_ids)))
    session.commit()
    session.close()
    yield


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def isolate_auth_cookies(client: TestClient):
    """Keep cookie sessions from leaking between tests.

    Login now writes HttpOnly cookies in addition to returning a bearer token.
    TestClient persists cookies, so each test starts and ends with a clean jar.
    """
    client.cookies.clear()
    try:
        yield
    finally:
        client.cookies.clear()


@pytest.fixture()
def login_headers(client: TestClient):
    """Return a factory that logs in and returns an Authorization header."""

    def _login(email: str, password: str = TEST_PASSWORD) -> dict[str, str]:
        response = client.post(
            "/auth/login",
            json={"email": email, "password": password},
        )
        assert response.status_code == 200, response.text
        return {
            "Authorization": f"Bearer {response.json()['access_token']}"
        }

    return _login


@pytest.fixture()
def accounts():
    """Create isolated users, conversations and orders, then clean them up."""
    session = SessionLocal()
    suffix = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc)

    admin = User(
        name="Phase 2 Admin",
        email=f"phase2-admin-{suffix}@example.com",
        password_hash=hash_password(TEST_PASSWORD),
        role="admin",
    )
    customer_a = User(
        name="Phase 2 Customer A",
        email=f"phase2-customer-a-{suffix}@example.com",
        password_hash=hash_password(TEST_PASSWORD),
        role="customer",
    )
    customer_b = User(
        name="Phase 2 Customer B",
        email=f"phase2-customer-b-{suffix}@example.com",
        password_hash=hash_password(TEST_PASSWORD),
        role="customer",
    )
    session.add_all([admin, customer_a, customer_b])
    session.flush()

    conversation_a = Conversation(
        user_id=customer_a.id,
        title="Phase 2 conversation A",
    )
    conversation_a.messages = [
        Message(
            role="user",
            content="Where is my order?",
            message_metadata={"source": "phase2-test", "attempt": 1},
        ),
        Message(
            role="assistant",
            content="Please share your order number.",
        ),
    ]
    conversation_b = Conversation(
        user_id=customer_b.id,
        title="Phase 2 conversation B",
    )
    conversation_b.messages = [
        Message(role="user", content="Customer B private message")
    ]

    # Order numbers must follow the customer-facing ``RX-2026-1001`` shape so
    # routing can recognise them in conversation text.
    order_sequence = f"{uuid.uuid4().int % 100_000_000:08d}"

    order_a = Order(
        user_id=customer_a.id,
        order_number=f"RX-2026-{order_sequence}",
        order_date=now,
        status="processing",
        shipping_status="in_transit",
        total_amount=Decimal("19.98"),
        estimated_delivery=date.today(),
    )
    order_a.items = [
        OrderItem(
            product_name="Test USB-C Cable",
            quantity=2,
            unit_price=Decimal("9.99"),
        )
    ]
    order_b = Order(
        user_id=customer_b.id,
        order_number=f"RZ-2026-{order_sequence}",
        order_date=now,
        status="completed",
        shipping_status="delivered",
        total_amount=Decimal("49.99"),
        estimated_delivery=date.today(),
    )
    order_b.items = [
        OrderItem(
            product_name="Test Bluetooth Speaker",
            quantity=1,
            unit_price=Decimal("49.99"),
        )
    ]

    session.add_all([conversation_a, conversation_b, order_a, order_b])
    session.commit()

    data = {
        "password": TEST_PASSWORD,
        "admin": {"id": admin.id, "email": admin.email},
        "customer_a": {"id": customer_a.id, "email": customer_a.email},
        "customer_b": {"id": customer_b.id, "email": customer_b.email},
        "conversation_a_id": conversation_a.id,
        "conversation_b_id": conversation_b.id,
        "order_a_number": order_a.order_number,
        "order_b_number": order_b.order_number,
    }

    try:
        yield data
    finally:
        session.rollback()
        user_ids = [admin.id, customer_a.id, customer_b.id]
        # Orders use ON DELETE RESTRICT, so remove them before their users.
        session.execute(delete(Order).where(Order.user_id.in_(user_ids)))
        session.execute(delete(User).where(User.id.in_(user_ids)))
        session.commit()
        session.close()
