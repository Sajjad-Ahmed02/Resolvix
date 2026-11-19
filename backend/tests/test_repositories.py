from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.session import SessionLocal
from app.models import Conversation
from app.repositories import conversations, messages, orders, users


@pytest.fixture()
def session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


def test_user_lookups_normalize_email_and_scope_counts(
    session,
    accounts,
) -> None:
    email = accounts["customer_a"]["email"]

    assert users.get_by_id(session, accounts["customer_a"]["id"]) is not None
    assert users.get_by_email(session, f"  {email.upper()}  ") is not None
    assert users.get_by_email(session, "missing@example.com") is None
    assert users.get_by_id(session, uuid.uuid4()) is None

    all_users = users.list_all(session)
    assert accounts["customer_a"]["id"] in [user.id for user in all_users]
    assert users.count(session) >= 3
    assert users.count(session, role="admin") >= 1


def test_conversation_repository_enforces_ownership(session, accounts) -> None:
    created = conversations.create_for_user(
        session,
        accounts["customer_a"]["id"],
        title="Repository-owned thread",
    )
    session.commit()

    try:
        owned = conversations.get_for_user(
            session,
            created.id,
            accounts["customer_a"]["id"],
        )
        other = conversations.get_for_user(
            session,
            created.id,
            accounts["customer_b"]["id"],
        )
        without_messages = conversations.get_for_user(
            session,
            created.id,
            accounts["customer_a"]["id"],
            with_messages=False,
        )

        assert owned is not None
        assert other is None
        assert without_messages is not None
        listing = conversations.list_for_user(
            session,
            accounts["customer_a"]["id"],
        )
        assert listing[0].id == created.id
        assert all(
            item.user_id == accounts["customer_a"]["id"] for item in listing
        )
    finally:
        session.delete(created)
        session.commit()


def test_message_repository_returns_a_bounded_chronological_window(
    session,
    accounts,
) -> None:
    conversation = Conversation(
        id=uuid.uuid4(),
        user_id=accounts["customer_a"]["id"],
        title="Repository message window",
    )
    session.add(conversation)
    session.commit()

    try:
        started = datetime.now(timezone.utc) - timedelta(minutes=5)
        for index in range(5):
            messages.create(
                session,
                conversation.id,
                role="user",
                content=f"Message {index}",
                created_at=started + timedelta(seconds=index),
            )
        session.commit()

        recent = messages.list_recent_for_conversation(
            session,
            conversation.id,
            limit=3,
        )

        assert [message.content for message in recent] == [
            "Message 2",
            "Message 3",
            "Message 4",
        ]
        assert [message.content for message in messages.list_for_conversation(
            session,
            conversation.id,
        )] == [f"Message {index}" for index in range(5)]

        with pytest.raises(ValueError):
            messages.list_recent_for_conversation(
                session,
                conversation.id,
                limit=0,
            )
    finally:
        session.delete(conversation)
        session.commit()


def test_order_repository_scopes_lookups_and_loads_items(
    session,
    accounts,
) -> None:
    own_orders = orders.list_for_user(session, accounts["customer_a"]["id"])
    other_orders = orders.list_for_user(session, accounts["customer_b"]["id"])

    assert [order.order_number for order in own_orders] == [
        accounts["order_a_number"]
    ]
    assert [order.order_number for order in other_orders] == [
        accounts["order_b_number"]
    ]
    assert own_orders[0].items[0].product_name == "Test USB-C Cable"
    assert other_orders[0].items[0].product_name == "Test Bluetooth Speaker"

    own = orders.get_for_user_by_number(
        session,
        accounts["customer_a"]["id"],
        f"  {accounts['order_a_number'].lower()}  ",
    )
    cross_customer = orders.get_for_user_by_number(
        session,
        accounts["customer_a"]["id"],
        accounts["order_b_number"],
    )
    assert own is not None
    assert own.user_id == accounts["customer_a"]["id"]
    assert cross_customer is None

    assert orders.list_items_for_order(session, own.id) == own.items
    admin_view = orders.get_by_id(session, own.id)
    assert admin_view is not None
    assert admin_view.user.email == accounts["customer_a"]["email"]
    assert orders.get_by_number(session, accounts["order_b_number"]) is not None
    assert orders.count(session) >= 2
