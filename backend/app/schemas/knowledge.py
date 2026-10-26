from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class DocumentUploadResponse(BaseModel):
    documentId: str
    fileName: str
    documentType: str
    totalPages: int
    chunksCount: int
    message: str


class DocumentSummarySchema(BaseModel):
    id: str
    fileName: str
    documentType: str
    source: Optional[str] = None
    author: Optional[str] = None
    category: str
    totalPages: int
    chunkCount: int
    uploadedAt: str


class KnowledgeSearchRequest(BaseModel):
    query: str
    topK: int = 4
    category: Optional[str] = None


class KnowledgeSearchResultItem(BaseModel):
    chunkId: str
    documentId: str
    fileName: str
    pageNumber: int
    chunkIndex: int
    chunkText: str
    score: float
    metadata: Optional[Dict[str, Any]] = None
