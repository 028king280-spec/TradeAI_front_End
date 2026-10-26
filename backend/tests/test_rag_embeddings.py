import pytest
from app.rag.embeddings import EmbeddingEngine
from app.rag.document_processor import DocumentProcessor


def test_embedding_generation_and_cosine_similarity():
    text1 = "Technical analysis momentum breakout above 20 EMA and VWAP"
    text2 = "Bullish continuation trend following moving average breakout"
    text3 = "Unrelated recipe for baking chocolate cake in oven"

    vec1 = EmbeddingEngine.get_embedding(text1)
    vec2 = EmbeddingEngine.get_embedding(text2)
    vec3 = EmbeddingEngine.get_embedding(text3)

    assert len(vec1) == 128
    assert len(vec2) == 128
    assert len(vec3) == 128

    sim_related = EmbeddingEngine.compute_cosine_similarity(vec1, vec2)
    sim_unrelated = EmbeddingEngine.compute_cosine_similarity(vec1, vec3)

    # Momentum trading text should be closer to trend following text than cake recipe
    assert sim_related > sim_unrelated


def test_document_chunking():
    pages = [
        (1, "Page 1 intro to technical trading in Indian equities on the National Stock Exchange."),
        (2, "Page 2 analysis of support and resistance pivot levels Camarilla R3 and S3 zones."),
    ]
    chunks = DocumentProcessor.chunk_text(pages, chunk_size=100, chunk_overlap=20)
    assert len(chunks) >= 2
    assert chunks[0]["page_number"] == 1
    assert "page_number" in chunks[1]
