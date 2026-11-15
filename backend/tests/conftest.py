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
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models import Conversation, Message, Order, OrderItem, User


TEST_PASSWORD = "TestPass123!"


@pytest.fixture(scope="session", autouse=True)
def cleanup_stale_test_rows():
    """Remove temporary rows left by an interrupted previous test run."""
    session = SessionLocal()
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

    order_a = Order(
        user_id=customer_a.id,
        order_number=f"PH2-A-{suffix}",
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
        order_number=f"PH2-B-{suffix}",
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
