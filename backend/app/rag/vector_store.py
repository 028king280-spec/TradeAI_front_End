from typing import List, Dict, Any, Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.db_models import KnowledgeDocument, KnowledgeChunk
from app.rag.embeddings import EmbeddingEngine
from app.core.logging import logger


class VectorStoreService:
    """
    Manages storage and semantic cosine-similarity vector retrieval
    for knowledge documents and chunks.
    """

    @classmethod
    async def add_document(
        cls,
        session: AsyncSession,
        file_name: str,
        document_type: str,
        total_pages: int,
        chunks_data: List[Dict[str, Any]],
        category: str = "Technical Analysis",
        author: Optional[str] = None,
        source: Optional[str] = None
    ) -> KnowledgeDocument:
        doc = KnowledgeDocument(
            file_name=file_name,
            document_type=document_type,
            source=source or file_name,
            author=author or "Institutional Research",
            category=category,
            total_pages=total_pages,
            chunk_count=len(chunks_data),
        )
        session.add(doc)
        await session.flush()  # Obtain doc.id

        for chunk_item in chunks_data:
            text = chunk_item["chunk_text"]
            emb = EmbeddingEngine.get_embedding(text)
            chunk_record = KnowledgeChunk(
                document_id=doc.id,
                page_number=chunk_item["page_number"],
                chunk_index=chunk_item["chunk_index"],
                chunk_text=text,
                embedding=emb,
                chunk_metadata=chunk_item.get("metadata", {}),
            )
            session.add(chunk_record)

        await session.commit()
        await session.refresh(doc)
        logger.info(f"Ingested document {doc.id} ({file_name}) with {len(chunks_data)} chunks")
        return doc

    @classmethod
    async def search(
        cls,
        session: AsyncSession,
        query: str,
        top_k: int = 4,
        category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        query_vec = EmbeddingEngine.get_embedding(query)

        stmt = select(KnowledgeChunk, KnowledgeDocument).join(
            KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id
        )
        if category:
            stmt = stmt.where(KnowledgeDocument.category == category)

        result = await session.execute(stmt)
        rows = result.all()

        scored_items = []
        for chunk, doc in rows:
            if chunk.embedding:
                sim = EmbeddingEngine.compute_cosine_similarity(query_vec, chunk.embedding)
                scored_items.append({
                    "chunkId": chunk.id,
                    "documentId": doc.id,
                    "fileName": doc.file_name,
                    "category": doc.category,
                    "pageNumber": chunk.page_number,
                    "chunkIndex": chunk.chunk_index,
                    "chunkText": chunk.chunk_text,
                    "score": round(sim, 4),
                    "metadata": chunk.chunk_metadata,
                })

        # Sort by similarity descending
        scored_items.sort(key=lambda x: x["score"], reverse=True)
        return scored_items[:top_k]

    @classmethod
    async def list_documents(cls, session: AsyncSession) -> List[KnowledgeDocument]:
        stmt = select(KnowledgeDocument).order_by(KnowledgeDocument.uploaded_at.desc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @classmethod
    async def get_document(cls, session: AsyncSession, doc_id: str) -> Optional[KnowledgeDocument]:
        stmt = select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @classmethod
    async def delete_document(cls, session: AsyncSession, doc_id: str) -> bool:
        stmt = delete(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount > 0
