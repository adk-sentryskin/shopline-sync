"""
Vertex AI Embedding Service (SHOPLINE).

Mirrors the Shopify app-webhook service: text-embedding-004 (768 dims),
batched generation, used for semantic product search. Field names below match
the real SHOPLINE product schema (product_category = the category; tags may be a
list or comma string; body_html = description).
"""
import logging
import re
from typing import List, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self):
        # Heavy GCP imports are deferred to construction time so the module can be
        # imported (and prepare_product_text tested) without the Vertex AI libs.
        from google.cloud import aiplatform
        from vertexai.language_models import TextEmbeddingModel, TextEmbeddingInput

        self.model_name = "text-embedding-004"
        self.dimension = 768
        self.task_type = "SEMANTIC_SIMILARITY"
        self._input_cls = TextEmbeddingInput
        aiplatform.init(project=settings.GCP_PROJECT_ID, location=settings.GCP_REGION)
        self.model = TextEmbeddingModel.from_pretrained(self.model_name)
        logger.info("Vertex AI Embedding Service initialized: %s", self.model_name)

    def generate_embedding(self, text: str) -> Optional[List[float]]:
        if not text or not text.strip():
            return None
        try:
            inputs = [self._input_cls(text=text[:20000], task_type=self.task_type)]
            embeddings = self.model.get_embeddings(inputs)
            return embeddings[0].values if embeddings else None
        except Exception as e:
            logger.error("Error generating embedding: %s", e)
            return None

    def generate_embeddings_batch(self, texts: List[str], batch_size: int = 25) -> List[Optional[List[float]]]:
        """Batch embeddings (SHOPLINE platform convention: 25 at a time)."""
        if not texts:
            return []
        all_embeddings: List[Optional[List[float]]] = []
        total_batches = (len(texts) + batch_size - 1) // batch_size

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            try:
                valid_texts, valid_indices = [], []
                for idx, text in enumerate(batch):
                    if text and text.strip():
                        valid_texts.append(text[:20000])
                        valid_indices.append(idx)
                if not valid_texts:
                    all_embeddings.extend([None] * len(batch))
                    continue
                inputs = [self._input_cls(text=t, task_type=self.task_type) for t in valid_texts]
                embeddings = self.model.get_embeddings(inputs)
                batch_embeddings: List[Optional[List[float]]] = [None] * len(batch)
                for idx, emb in zip(valid_indices, embeddings):
                    batch_embeddings[idx] = emb.values
                all_embeddings.extend(batch_embeddings)
                logger.info("Embeddings batch %d/%d: %d generated", batch_num, total_batches, len(valid_texts))
            except Exception as e:
                logger.error("Embeddings batch %d/%d failed: %s", batch_num, total_batches, e)
                all_embeddings.extend([None] * len(batch))

        return all_embeddings

    @staticmethod
    def prepare_product_text(product_data: dict) -> str:
        """Build the embedding text from a SHOPLINE product (real field names)."""
        parts = []

        title = (product_data.get("title") or "").strip()
        if title:
            parts.append(f"Title: {title}")

        subtitle = (product_data.get("subtitle") or "").strip()
        if subtitle:
            parts.append(f"Subtitle: {subtitle}")

        # ⚠️ product_category is the real category; product_type is a source enum.
        category = (product_data.get("product_category") or "").strip()
        if category:
            parts.append(f"Category: {category}")

        vendor = (product_data.get("vendor") or "").strip()
        if vendor:
            parts.append(f"Brand: {vendor}")

        tags = product_data.get("tags")
        if isinstance(tags, list):
            tag_list = [str(t).strip() for t in tags if str(t).strip()]
        else:
            tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
        if tag_list:
            parts.append(f"Tags: {', '.join(tag_list)}")

        description = product_data.get("body_html") or product_data.get("description") or ""
        description = re.sub(r"<[^>]+>", "", description).strip()
        if description:
            parts.append(f"Description: {description[:1000]}")

        combined = "\n".join(parts)
        return combined[:20000]


_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
