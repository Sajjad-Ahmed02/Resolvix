"""Synthetic data for local development.

Run from the backend directory:

    python -m scripts.seed

The script is idempotent: rows are matched by their natural keys and existing
rows are left untouched. Unchanged demo passwords are upgraded from the Phase 1
PBKDF2 format to Argon2id. It never uses real customer data.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# Allow ``python scripts/seed.py`` as well as ``python -m scripts.seed``.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password, is_argon2_hash, verify_password
from app.db.session import SessionLocal
from app.models import FAQ, KnowledgeDocument, Order, OrderItem, User


ADMIN_PASSWORD = "Admin123!"
CUSTOMER_PASSWORD = "Customer123!"

USERS = (
    ("Avery Admin", "admin@resolvix.local", "admin", ADMIN_PASSWORD),
    ("Alice Morgan", "alice.morgan@example.com", "customer", CUSTOMER_PASSWORD),
    ("Ben Carter", "ben.carter@example.com", "customer", CUSTOMER_PASSWORD),
    ("Chloe Diaz", "chloe.diaz@example.com", "customer", CUSTOMER_PASSWORD),
    ("Daniel Kim", "daniel.kim@example.com", "customer", CUSTOMER_PASSWORD),
    ("Emma Rossi", "emma.rossi@example.com", "customer", CUSTOMER_PASSWORD),
    ("Farid Hassan", "farid.hassan@example.com", "customer", CUSTOMER_PASSWORD),
    ("Grace Lee", "grace.lee@example.com", "customer", CUSTOMER_PASSWORD),
)

PRODUCTS = (
    ("Wireless Noise-Cancelling Headphones", Decimal("249.99")),
    ("USB-C Charging Cable (2m)", Decimal("19.99")),
    ("Ergonomic Laptop Stand", Decimal("59.95")),
    ("Mechanical Keyboard", Decimal("129.00")),
    ("Portable SSD 1TB", Decimal("119.50")),
    ("Smart Home Hub", Decimal("89.99")),
    ("Protective Phone Case", Decimal("24.99")),
    ("Bluetooth Speaker", Decimal("79.00")),
    ("4K Webcam", Decimal("149.99")),
    ("LED Desk Lamp", Decimal("39.99")),
)

# (order_number, user_index, status, shipping_status, order_date,
#  [(product_index, quantity), ...])
ORDERS = (
    ("RX-2026-1001", 0, "completed", "delivered", "2026-09-02", [(0, 1), (2, 1)]),
    ("RX-2026-1002", 1, "processing", "in_transit", "2026-09-08", [(3, 1), (1, 2)]),
    ("RX-2026-1003", 2, "pending", "not_shipped", "2026-09-14", [(6, 1)]),
    ("RX-2026-1004", 3, "confirmed", "not_shipped", "2026-09-21", [(4, 1), (7, 1)]),
    ("RX-2026-1005", 4, "cancelled", None, "2026-09-27", [(5, 1), (9, 1)]),
    ("RX-2026-1006", 5, "completed", "delivered", "2026-10-03", [(3, 1), (8, 1)]),
    ("RX-2026-1007", 6, "processing", "out_for_delivery", "2026-10-09", [(0, 1), (1, 1)]),
    ("RX-2026-1008", 0, "pending", "not_shipped", "2026-10-15", [(2, 2), (9, 1)]),
    ("RX-2026-1009", 1, "confirmed", "not_shipped", "2026-10-20", [(5, 1), (6, 1), (1, 1)]),
    ("RX-2026-1010", 2, "completed", "delivered", "2026-10-26", [(4, 1), (7, 1)]),
    ("RX-2026-1011", 3, "cancelled", None, "2026-11-01", [(8, 1)]),
    ("RX-2026-1012", 4, "processing", "in_transit", "2026-11-06", [(3, 1), (2, 1)]),
)

FAQS = (
    (
        "How long does standard shipping take?",
        "Standard shipping usually arrives within 3 to 5 business days after "
        "an order leaves our warehouse. Remote areas may take up to 7 business "
        "days. Express shipping arrives within 1 to 2 business days.",
        "Shipping",
    ),
    (
        "How can I track my order?",
        "Open the Orders page in your account and select the order you want to "
        "track. The tracking number and the latest carrier scan appear on the "
        "order details page as soon as the parcel is collected.",
        "Shipping",
    ),
    (
        "What is your return window?",
        "Unused products in their original packaging can be returned within 30 "
        "days of delivery. Items that arrive damaged or defective can be "
        "returned within 90 days.",
        "Returns",
    ),
    (
        "How do I start a return?",
        "Go to Orders, choose the item, and select Request return. We will email "
        "a prepaid return label and instructions. Refunds are issued after the "
        "warehouse checks the returned item.",
        "Returns",
    ),
    (
        "When will I receive my refund?",
        "Refunds are processed within 2 business days after we receive and "
        "inspect the return. Your bank or card issuer may take another 5 to 10 "
        "business days to post the credit.",
        "Refunds",
    ),
    (
        "Which payment methods do you accept?",
        "We accept major credit and debit cards, Apple Pay, Google Pay, and "
        "PayPal. All payments are processed by our PCI-compliant payment "
        "provider; we never store full card numbers.",
        "Payments",
    ),
    (
        "Why was my payment declined?",
        "A payment can be declined when card details are incorrect, the card "
        "has expired, or the issuer blocks the transaction. Check your details "
        "and try another payment method, or contact your bank.",
        "Payments",
    ),
    (
        "Can I change or cancel an order after placing it?",
        "Orders can be changed or cancelled while their status is Pending or "
        "Confirmed. Once processing starts, the order cannot be modified, but "
        "you can return it after delivery.",
        "Orders",
    ),
    (
        "How do I check the status of my order?",
        "Your account shows the latest order status: Pending, Confirmed, "
        "Processing, Completed, or Cancelled. Shipping status is shown "
        "separately as Not shipped, In transit, Out for delivery, or Delivered.",
        "Orders",
    ),
    (
        "How do I reset my password?",
        "Select Forgot password on the sign-in page and follow the emailed "
        "reset link. The link expires after 30 minutes. Contact support if you "
        "no longer have access to the email address on your account.",
        "Account",
    ),
    (
        "What does the one-year warranty cover?",
        "The one-year limited warranty covers manufacturing defects and "
        "hardware failures under normal use. Accidental damage, normal wear, "
        "and unauthorized repairs are not covered.",
        "Warranty",
    ),
    (
        "Are product manuals available online?",
        "Yes. Open the product page and select the Manuals tab to download the "
        "setup guide and user manual as a PDF. Printed manuals are included "
        "with larger appliances.",
        "Products",
    ),
)

KNOWLEDGE_DOCUMENTS = (
    (
        "Shipping and Delivery Policy",
        "Shipping",
        """Shipping and Delivery Policy

We offer standard, express, and same-day delivery in selected areas. Standard
delivery takes 3 to 5 business days after dispatch. Express delivery takes 1 to
2 business days. Same-day delivery is available in selected metropolitan areas
for orders placed before 11:00 local time.

Orders are dispatched from the nearest warehouse with available stock. If an
order contains items from more than one warehouse, the parcels may arrive on
different days. You will receive a separate tracking number for each parcel.

Shipping costs are calculated at checkout based on the destination, parcel
weight, and selected service. Orders above the published free-shipping
threshold receive standard shipping at no charge. Express and same-day services
always incur their listed fee.

Tracking information is emailed when a parcel is collected by the carrier and
is also available on the order details page. A parcel is considered delayed
when it has not moved for two business days; contact support with the order
number so we can open a carrier trace.

Delivery addresses can be changed while an order is Pending or Confirmed. Once
the order enters Processing, the address cannot be changed. If delivery fails
because of an incorrect address, the carrier returns the parcel to us and we
contact you to arrange a replacement or refund.

Risk of loss passes to the customer on delivery. Report missing or damaged
parcels within 7 days of the recorded delivery date.""",
    ),
    (
        "Returns and Refunds Policy",
        "Returns",
        """Returns and Refunds Policy

Unused products in their original packaging may be returned within 30 days of
delivery. Products that arrive damaged, defective, or materially different from
the description may be returned within 90 days. Proof of purchase is required
for all returns.

To start a return, open the Orders page, select the relevant item, and choose
Request return. We issue a prepaid return label by email unless the item is
classified as non-returnable for hygiene or safety reasons. Return the item in
its original packaging with all included accessories.

After the warehouse receives the return, it is inspected within 2 business days.
If the item meets the return conditions, the refund is approved and sent to the
original payment method. Bank processing can take an additional 5 to 10
business days. Shipping charges are refunded only when the return is caused by
our error or a defective product.

Replacements are offered when the same product is in stock. If it is not, you
may choose a refund or a store credit. Store credit is issued immediately after
approval and does not expire.

The following items cannot be returned: gift cards, downloadable software,
perishable goods, and products marked as final sale. Items returned without
authorization may be refused or subject to a restocking fee.

If a parcel is lost in transit, contact support. We will open a carrier
investigation and, when the loss is confirmed, send a replacement or refund.""",
    ),
    (
        "Payment and Billing Guide",
        "Payments",
        """Payment and Billing Guide

We accept major credit and debit cards, Apple Pay, Google Pay, and PayPal.
Payment is captured when an order is confirmed. For pre-orders, authorization
is placed at checkout and captured when the product is dispatched.

All card data is handled by our PCI-compliant payment provider. Resolvix stores
only a payment token, the card brand, and the last four digits. We never store
full card numbers or security codes.

A payment may be declined when the card number is incorrect, the card has
expired, the billing address does not match, or the issuer blocks the
transaction. Try another payment method or contact your bank. A temporary
authorization hold may appear on your statement after a failed attempt; it is
released by the issuer, usually within 3 to 5 business days.

Invoices are available from the Orders page as soon as the order is confirmed.
Business customers can add a VAT number and company details before checkout.
Changes to billing details after capture may require a credit and re-issue.

If you are charged more than once for the same order, contact support with the
order number and a screenshot of the transactions. We verify duplicate charges
and refund the extra amount within 3 business days.""",
    ),
    (
        "Product Warranty and Support",
        "Warranty",
        """Product Warranty and Support

Most Resolvix hardware products include a one-year limited warranty from the
delivery date. The warranty covers manufacturing defects and hardware failures
under normal use. It does not cover accidental damage, liquid damage, normal
wear, or repairs performed by unauthorized service providers.

To make a warranty claim, provide the order number, product serial number, and
a description of the fault. Support may ask for photographs or a short video.
Approved claims are repaired or replaced at our discretion. If the product is
no longer available, we may offer a comparable model or a refund.

Products bought from unauthorized resellers are not covered. Keep your proof of
purchase; the order record is normally sufficient when the order was placed
with us.

Software products, consumable parts, and accessories have separate warranty
terms shown on the product page. Batteries are covered for defects but not for
capacity loss caused by normal use.

Support is available by chat and email. Include the product model and a clear
description of the problem so the team can help faster. Do not attempt repairs
yourself while a claim is open, because disassembly may void the warranty.""",
    ),
)


def seed_users(session: Session) -> tuple[int, int]:
    existing = set(session.scalars(select(User.email)).all())
    created = 0
    skipped = 0

    for name, email, role, password in USERS:
        if email in existing:
            skipped += 1
            continue

        session.add(
            User(
                name=name,
                email=email,
                password_hash=hash_password(password),
                role=role,
            )
        )
        created += 1

    session.flush()
    return created, skipped


def upgrade_demo_password_hashes(session: Session) -> int:
    """Upgrade unchanged demo passwords from Phase 1 PBKDF2 to Argon2id.

    Only hashes that still verify against the documented demo password are
    touched, so a manually changed development password is preserved.
    """
    upgraded = 0
    for _, email, _, password in USERS:
        user = session.scalar(select(User).where(User.email == email))
        if user is None or is_argon2_hash(user.password_hash):
            continue
        if verify_password(password, user.password_hash):
            user.password_hash = hash_password(password)
            upgraded += 1

    session.flush()
    return upgraded


def seed_orders(session: Session) -> tuple[int, int]:
    existing = set(session.scalars(select(Order.order_number)).all())
    users = {
        user.email: user
        for user in session.scalars(
            select(User).where(User.role == "customer").order_by(User.email)
        ).all()
    }
    customer_emails = [
        email for _, email, role, _ in USERS if role == "customer"
    ]

    created = 0
    skipped = 0

    for index, (
        order_number,
        user_index,
        status,
        shipping_status,
        order_date_text,
        item_specs,
    ) in enumerate(ORDERS):
        if order_number in existing:
            skipped += 1
            continue

        order_date = datetime.strptime(
            f"{order_date_text} 12:00", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=timezone.utc)

        items: list[OrderItem] = []
        total = Decimal("0.00")
        for product_index, quantity in item_specs:
            product_name, unit_price = PRODUCTS[product_index]
            line_total = unit_price * quantity
            total += line_total
            items.append(
                OrderItem(
                    product_name=product_name,
                    quantity=quantity,
                    unit_price=unit_price,
                )
            )

        estimated_delivery: date | None = None
        if status != "cancelled":
            estimated_delivery = order_date.date() + timedelta(
                days=4 + (index % 3)
            )

        session.add(
            Order(
                user=users[customer_emails[user_index % len(customer_emails)]],
                order_number=order_number,
                order_date=order_date,
                status=status,
                shipping_status=shipping_status,
                total_amount=total.quantize(Decimal("0.01")),
                estimated_delivery=estimated_delivery,
                items=items,
            )
        )
        created += 1

    session.flush()
    return created, skipped


def seed_faqs(session: Session) -> tuple[int, int]:
    existing = set(session.scalars(select(FAQ.question)).all())
    created = 0
    skipped = 0

    for question, answer, category in FAQS:
        if question in existing:
            skipped += 1
            continue
        session.add(FAQ(question=question, answer=answer, category=category))
        created += 1

    session.flush()
    return created, skipped


def seed_documents(session: Session) -> tuple[int, int]:
    existing = set(session.scalars(select(KnowledgeDocument.title)).all())
    created = 0
    skipped = 0

    for title, category, content in KNOWLEDGE_DOCUMENTS:
        if title in existing:
            skipped += 1
            continue
        session.add(
            KnowledgeDocument(
                title=title,
                category=category,
                content=content.strip(),
            )
        )
        created += 1

    session.flush()
    return created, skipped


def main() -> None:
    with SessionLocal() as session:
        users_created, users_skipped = seed_users(session)
        hashes_upgraded = upgrade_demo_password_hashes(session)
        orders_created, orders_skipped = seed_orders(session)
        faqs_created, faqs_skipped = seed_faqs(session)
        documents_created, documents_skipped = seed_documents(session)
        session.commit()

        print("Seed complete.")
        print(
            f"  users:       {users_created} created, {users_skipped} already present"
        )
        print(
            f"  passwords:   {hashes_upgraded} legacy hash(es) upgraded to Argon2id"
        )
        print(
            f"  orders:      {orders_created} created, {orders_skipped} already present"
        )
        print(
            f"  FAQs:        {faqs_created} created, {faqs_skipped} already present"
        )
        print(
            f"  documents:   {documents_created} created, {documents_skipped} already present"
        )
        print("  chunks:      none (created by the Phase 5 ingestion pipeline)")
        print()
        print("Demo accounts (local development only):")
        print(f"  admin:    admin@resolvix.local / {ADMIN_PASSWORD}")
        print(f"  customer: alice.morgan@example.com / {CUSTOMER_PASSWORD}")


if __name__ == "__main__":
    main()
