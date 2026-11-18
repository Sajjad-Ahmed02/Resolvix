from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.db.session import get_db
from app.knowledge.dependencies import get_knowledge_ingestor
from app.knowledge.ingestion import KnowledgeIngestor
from app.schemas.admin import (
    FAQMutationResponse,
    FAQWrite,
    IndexingResult,
    KnowledgeDocumentMutationResponse,
    KnowledgeDocumentWrite,
    KnowledgeReindexResponse,
    SourceIndexingResult,
)
from app.schemas.common import ErrorResponse
from app.schemas.knowledge import FAQRead, KnowledgeDocumentRead
from app.services import knowledge as knowledge_service


router = APIRouter(
    prefix="/knowledge",
    tags=["Administration"],
    dependencies=[Depends(require_admin)],
)


def _indexing(result) -> IndexingResult:
    return knowledge_service.indexing_result(result)


def _reindex_failed(result) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={
            "message": "The source was saved but re-indexing failed.",
            "status": result.action,
            "error": result.error,
        },
    )


@router.get(
    "/faqs",
    response_model=list[FAQRead],
    summary="List all FAQs including inactive entries",
)
def list_faqs(session: Session = Depends(get_db)) -> list[FAQRead]:
    return knowledge_service.list_faqs(session, active_only=False)


@router.post(
    "/faqs",
    response_model=FAQMutationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an FAQ and synchronize its embeddings",
)
async def create_faq(
    payload: FAQWrite,
    session: Session = Depends(get_db),
    ingestor: KnowledgeIngestor = Depends(get_knowledge_ingestor),
) -> FAQMutationResponse:
    faq, result = await knowledge_service.create_faq(
        session,
        ingestor=ingestor,
        question=payload.question,
        answer=payload.answer,
        category=payload.category,
        is_active=payload.is_active,
    )
    return FAQMutationResponse(
        faq=FAQRead.model_validate(faq),
        indexing=_indexing(result),
    )


@router.get(
    "/faqs/{faq_id}",
    response_model=FAQRead,
    summary="Read one FAQ including inactive entries",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "FAQ not found.",
        }
    },
)
def get_faq(
    faq_id: UUID,
    session: Session = Depends(get_db),
) -> FAQRead:
    faq = knowledge_service.get_faq(session, faq_id)
    if faq is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="FAQ not found",
        )
    return faq


@router.put(
    "/faqs/{faq_id}",
    response_model=FAQMutationResponse,
    summary="Update an FAQ and re-synchronize its embeddings",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "FAQ not found.",
        }
    },
)
async def update_faq(
    faq_id: UUID,
    payload: FAQWrite,
    session: Session = Depends(get_db),
    ingestor: KnowledgeIngestor = Depends(get_knowledge_ingestor),
) -> FAQMutationResponse:
    faq = knowledge_service.get_faq(session, faq_id)
    if faq is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="FAQ not found",
        )
    faq, result = await knowledge_service.update_faq(
        session,
        faq,
        ingestor=ingestor,
        question=payload.question,
        answer=payload.answer,
        category=payload.category,
        is_active=payload.is_active,
    )
    return FAQMutationResponse(
        faq=FAQRead.model_validate(faq),
        indexing=_indexing(result),
    )


@router.delete(
    "/faqs/{faq_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an FAQ and its indexed chunks",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "FAQ not found.",
        }
    },
)
def delete_faq(
    faq_id: UUID,
    session: Session = Depends(get_db),
) -> None:
    faq = knowledge_service.get_faq(session, faq_id)
    if faq is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="FAQ not found",
        )
    knowledge_service.delete_faq(session, faq)
    return None


@router.post(
    "/faqs/{faq_id}/reindex",
    response_model=IndexingResult,
    summary="Re-index one FAQ",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "FAQ not found.",
        },
        status.HTTP_502_BAD_GATEWAY: {
            "model": ErrorResponse,
            "description": "The embedding/indexing step failed.",
        },
    },
)
async def reindex_faq(
    faq_id: UUID,
    session: Session = Depends(get_db),
    ingestor: KnowledgeIngestor = Depends(get_knowledge_ingestor),
) -> IndexingResult:
    faq = knowledge_service.get_faq(session, faq_id)
    if faq is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="FAQ not found",
        )
    result = await knowledge_service.reindex_faq(
        session,
        faq,
        ingestor=ingestor,
    )
    if result.action == "failed":
        raise _reindex_failed(result)
    return _indexing(result)


@router.get(
    "/documents",
    response_model=list[KnowledgeDocumentRead],
    summary="List all knowledge documents including inactive entries",
)
def list_documents(
    session: Session = Depends(get_db),
) -> list[KnowledgeDocumentRead]:
    return knowledge_service.list_documents(session, active_only=False)


@router.post(
    "/documents",
    response_model=KnowledgeDocumentMutationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a knowledge document and generate its embeddings",
)
async def create_document(
    payload: KnowledgeDocumentWrite,
    session: Session = Depends(get_db),
    ingestor: KnowledgeIngestor = Depends(get_knowledge_ingestor),
) -> KnowledgeDocumentMutationResponse:
    document, result = await knowledge_service.create_document(
        session,
        ingestor=ingestor,
        title=payload.title,
        content=payload.content,
        category=payload.category,
        is_active=payload.is_active,
    )
    return KnowledgeDocumentMutationResponse(
        document=KnowledgeDocumentRead.model_validate(document),
        indexing=_indexing(result),
    )


@router.get(
    "/documents/{document_id}",
    response_model=KnowledgeDocumentRead,
    summary="Read one knowledge document including inactive entries",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Knowledge document not found.",
        }
    },
)
def get_document(
    document_id: UUID,
    session: Session = Depends(get_db),
) -> KnowledgeDocumentRead:
    document = knowledge_service.get_document(session, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge document not found",
        )
    return document


@router.put(
    "/documents/{document_id}",
    response_model=KnowledgeDocumentMutationResponse,
    summary="Update a document, chunk it, and regenerate embeddings",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Knowledge document not found.",
        }
    },
)
async def update_document(
    document_id: UUID,
    payload: KnowledgeDocumentWrite,
    session: Session = Depends(get_db),
    ingestor: KnowledgeIngestor = Depends(get_knowledge_ingestor),
) -> KnowledgeDocumentMutationResponse:
    document = knowledge_service.get_document(session, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge document not found",
        )
    document, result = await knowledge_service.update_document(
        session,
        document,
        ingestor=ingestor,
        title=payload.title,
        content=payload.content,
        category=payload.category,
        is_active=payload.is_active,
    )
    return KnowledgeDocumentMutationResponse(
        document=KnowledgeDocumentRead.model_validate(document),
        indexing=_indexing(result),
    )


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a knowledge document and its indexed chunks",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Knowledge document not found.",
        }
    },
)
def delete_document(
    document_id: UUID,
    session: Session = Depends(get_db),
) -> None:
    document = knowledge_service.get_document(session, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge document not found",
        )
    knowledge_service.delete_document(session, document)
    return None


@router.post(
    "/documents/{document_id}/reindex",
    response_model=IndexingResult,
    summary="Re-index one knowledge document",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Knowledge document not found.",
        },
        status.HTTP_502_BAD_GATEWAY: {
            "model": ErrorResponse,
            "description": "The embedding/indexing step failed.",
        },
    },
)
async def reindex_document(
    document_id: UUID,
    session: Session = Depends(get_db),
    ingestor: KnowledgeIngestor = Depends(get_knowledge_ingestor),
) -> IndexingResult:
    document = knowledge_service.get_document(session, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge document not found",
        )
    result = await knowledge_service.reindex_document(
        session,
        document,
        ingestor=ingestor,
    )
    if result.action == "failed":
        raise _reindex_failed(result)
    return _indexing(result)


@router.post(
    "/reindex",
    response_model=KnowledgeReindexResponse,
    summary="Re-index every FAQ and knowledge document",
)
async def reindex_all(
    session: Session = Depends(get_db),
    ingestor: KnowledgeIngestor = Depends(get_knowledge_ingestor),
) -> KnowledgeReindexResponse:
    report = await knowledge_service.reindex_all(
        session,
        ingestor=ingestor,
    )
    return KnowledgeReindexResponse(
        summary=report.summary(),
        results=[
            SourceIndexingResult(
                status=result.action,
                chunks=result.chunks,
                error=result.error,
                source_type=result.source_type,
                source_id=result.source_id,
                title=result.title,
            )
            for result in report.results
        ],
    )
