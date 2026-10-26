import hashlib
from typing import List
import numpy as np


class EmbeddingEngine:
    """
    High-performance semantic embedding generator.
    Produces 128-dimensional unit-normalized dense vectors
    using token n-gram feature hashing and character subword projections.
    Runs 100% locally and deterministically.
    """

    DIMENSION = 128

    @classmethod
    def get_embedding(cls, text: str) -> List[float]:
        tokens = text.lower().split()
        if not tokens:
            return [0.0] * cls.DIMENSION

        vec = np.zeros(cls.DIMENSION, dtype=np.float32)

        for token in tokens:
            # Word hash
            h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
            idx = h % cls.DIMENSION
            sign = 1.0 if ((h >> 8) & 1) == 1 else -1.0
            vec[idx] += sign

            # Character 3-gram subwords for morphological sensitivity
            if len(token) >= 3:
                for i in range(len(token) - 2):
                    sub = token[i:i+3]
                    sub_h = int(hashlib.sha256(sub.encode("utf-8")).hexdigest(), 16)
                    sub_idx = sub_h % cls.DIMENSION
                    sub_sign = 1.0 if ((sub_h >> 8) & 1) == 1 else -1.0
                    vec[sub_idx] += 0.5 * sub_sign

        # L2 Unit Normalization
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm

        return [round(float(x), 6) for x in vec]

    @classmethod
    def compute_cosine_similarity(cls, vec1: List[float], vec2: List[float]) -> float:
        v1 = np.array(vec1, dtype=np.float32)
        v2 = np.array(vec2, dtype=np.float32)
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(v1, v2) / (norm1 * norm2))
