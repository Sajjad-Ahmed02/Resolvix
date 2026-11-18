"""SQLAlchemy models. Importing this package registers every mapper."""

from app.models.conversation import Conversation
from app.models.faq import FAQ
from app.models.knowledge_chunk import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    KnowledgeChunk,
)
from app.models.knowledge_document import KnowledgeDocument
from app.models.message import Message
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.refresh_token import RefreshToken
from app.models.user import User

__all__ = [
    "Conversation",
    "EMBEDDING_DIMENSION",
    "EMBEDDING_MODEL",
    "FAQ",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "Message",
    "Order",
    "OrderItem",
    "RefreshToken",
    "User",
]
