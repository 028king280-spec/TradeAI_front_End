from typing import List
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db
from app.schemas.market import ApiResponse
from app.schemas.knowledge import (
    DocumentUploadResponse,
    DocumentSummarySchema,
    KnowledgeSearchRequest,
    KnowledgeSearchResultItem
)
from app.rag.document_processor import DocumentProcessor
from app.rag.vector_store import VectorStoreService

router = APIRouter(prefix="/knowledge", tags=["RAG Knowledge System"])


@router.post("/upload", response_model=ApiResponse[DocumentUploadResponse])
async def upload_document(
    file: UploadFile = File(...),
    category: str = Form(default="Technical Analysis"),
    author: str = Form(default="Institutional Research"),
    db: AsyncSession = Depends(get_db)
):
    contents = await file.read()
    file_name = file.filename or "uploaded_document"
    ext = file_name.split(".")[-1].lower()

    if ext == "pdf":
        pages = DocumentProcessor.extract_text_from_pdf(contents)
    elif ext in ["txt", "md", "text"]:
        pages = DocumentProcessor.extract_text_from_txt(contents)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported document format. Please upload PDF or TXT documents."
        )

    if not pages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No extractable text found in uploaded document."
        )

    chunks = DocumentProcessor.chunk_text(pages, chunk_size=500, chunk_overlap=80)
    doc = await VectorStoreService.add_document(
        session=db,
        file_name=file_name,
        document_type=ext,
        total_pages=len(pages),
        chunks_data=chunks,
        category=category,
        author=author,
    )

    return ApiResponse(
        success=True,
        data=DocumentUploadResponse(
            documentId=doc.id,
            fileName=doc.file_name,
            documentType=doc.document_type,
            totalPages=doc.total_pages,
            chunksCount=doc.chunk_count,
            message="Document successfully processed and indexed into vector knowledge base.",
        )
    )


@router.get("/documents", response_model=ApiResponse[List[DocumentSummarySchema]])
async def list_documents(db: AsyncSession = Depends(get_db)):
    docs = await VectorStoreService.list_documents(db)
    items = [
        DocumentSummarySchema(
            id=d.id,
            fileName=d.file_name,
            documentType=d.document_type,
            source=d.source,
            author=d.author,
            category=d.category,
            totalPages=d.total_pages,
            chunkCount=d.chunk_count,
            uploadedAt=d.uploaded_at.isoformat(),
        )
        for d in docs
    ]
    return ApiResponse(success=True, data=items)


@router.get("/documents/{doc_id}", response_model=ApiResponse[DocumentSummarySchema])
async def get_document(doc_id: str, db: AsyncSession = Depends(get_db)):
    doc = await VectorStoreService.get_document(db, doc_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    return ApiResponse(
        success=True,
        data=DocumentSummarySchema(
            id=doc.id,
            fileName=doc.file_name,
            documentType=doc.document_type,
            source=doc.source,
            author=doc.author,
            category=doc.category,
            totalPages=doc.total_pages,
            chunkCount=doc.chunk_count,
            uploadedAt=doc.uploaded_at.isoformat(),
        )
    )


@router.delete("/documents/{doc_id}", response_model=ApiResponse[dict])
async def delete_document(doc_id: str, db: AsyncSession = Depends(get_db)):
    deleted = await VectorStoreService.delete_document(db, doc_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return ApiResponse(success=True, data={"message": f"Document '{doc_id}' deleted successfully"})


@router.post("/search", response_model=ApiResponse[List[KnowledgeSearchResultItem]])
async def search_knowledge(
    req: KnowledgeSearchRequest,
    db: AsyncSession = Depends(get_db)
):
    results = await VectorStoreService.search(db, req.query, top_k=req.topK, category=req.category)
    items = [
        KnowledgeSearchResultItem(
            chunkId=r["chunkId"],
            documentId=r["documentId"],
            fileName=r["fileName"],
            pageNumber=r["pageNumber"],
            chunkIndex=r["chunkIndex"],
            chunkText=r["chunkText"],
            score=r["score"],
            metadata=r.get("metadata"),
        )
        for r in results
    ]
    return ApiResponse(success=True, data=items)
