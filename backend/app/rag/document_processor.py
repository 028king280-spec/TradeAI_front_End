import io
import re
from typing import List, Dict, Any, Tuple
import pypdf


class DocumentProcessor:
    """
    Extracts text, cleans content, and generates chunked passages
    with metadata and page numbering for PDF and TXT documents.
    """

    @classmethod
    def extract_text_from_pdf(cls, file_bytes: bytes) -> List[Tuple[int, str]]:
        """
        Extracts text from PDF bytes page by page.
        Returns list of (page_number, text).
        """
        pages_content = []
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        for page_idx, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            cleaned = cls.clean_text(text)
            if cleaned:
                pages_content.append((page_idx + 1, cleaned))
        return pages_content

    @classmethod
    def extract_text_from_txt(cls, file_bytes: bytes) -> List[Tuple[int, str]]:
        """
        Extracts text from plain text bytes.
        """
        text = file_bytes.decode("utf-8", errors="ignore")
        cleaned = cls.clean_text(text)
        return [(1, cleaned)] if cleaned else []

    @staticmethod
    def clean_text(text: str) -> str:
        # Normalize whitespace while preserving paragraphs
        text = re.sub(r"\r\n", "\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @classmethod
    def chunk_text(
        cls,
        pages_content: List[Tuple[int, str]],
        chunk_size: int = 500,
        chunk_overlap: int = 80
    ) -> List[Dict[str, Any]]:
        """
        Recursively splits text into chunks while preserving page numbers.
        """
        chunks = []
        global_chunk_idx = 0

        for page_num, content in pages_content:
            words = content.split(" ")
            if not words:
                continue

            current_pos = 0
            while current_pos < len(words):
                end_pos = min(len(words), current_pos + chunk_size // 5)
                chunk_words = words[current_pos:end_pos]
                chunk_text = " ".join(chunk_words).strip()

                if len(chunk_text) > 30:  # Ignore trivial noise
                    chunks.append({
                        "chunk_index": global_chunk_idx,
                        "page_number": page_num,
                        "chunk_text": chunk_text,
                        "metadata": {
                            "word_count": len(chunk_words),
                            "char_count": len(chunk_text),
                        }
                    })
                    global_chunk_idx += 1

                if end_pos >= len(words):
                    break
                current_pos += max(1, (chunk_size - chunk_overlap) // 5)

        return chunks
