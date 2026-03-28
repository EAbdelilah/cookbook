import os
import random
import time
import logging
from typing import Callable, Any, TypeVar, List, Optional
from google import genai
from google.genai import types
import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

T = TypeVar('T')

class GeminiClient:
    """Encapsulates the Gemini API client with robust retry and quota handling."""

    def __init__(self, api_key: str, generation_model: str = 'gemini-1.5-flash', embedding_model: str = 'gemini-embedding-001'):
        self.client = genai.Client(api_key=api_key)
        self.generation_model = generation_model
        self.embedding_model = embedding_model

    def call_with_retry(self, func: Callable[..., T], *args, max_retries: int = 15, **kwargs) -> T:
        """Industry-standard retry wrapper with exponential backoff, jitter, and quota detection."""
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_message = str(e).lower()

                # Identify retryable errors (Rate limits, quotas, transient server issues)
                is_quota_error = any(x in error_message for x in ["429", "quota", "resource_exhausted"])
                is_transient_error = any(x in error_message for x in ["503", "unavailable", "high demand", "deadline_exceeded"])

                if is_quota_error or is_transient_error:
                    # Implement an immediate 60-second cooldown if quota limits are consistently hit
                    if is_quota_error and attempt >= 5:
                        wait_time = 60 + random.uniform(0, 5)
                        logger.warning(f"[Critical Quota Hit] Waiting for {wait_time:.2f}s (Attempt {attempt+1}/{max_retries})...")
                    else:
                        # Exponential backoff with jitter: 2^attempt + random(0, 2)
                        wait_time = (2 ** attempt) + random.uniform(0, 2)
                        logger.info(f"Transient error or Rate limit hit. Waiting for {wait_time:.2f}s (Attempt {attempt+1}/{max_retries})...")

                    time.sleep(wait_time)
                else:
                    # Non-transient errors are raised immediately
                    logger.error(f"Non-retryable API error: {e}")
                    raise e

        raise Exception(f"Failed after {max_retries} attempts due to persistent API errors or rate limits.")

    def embed_documents(self, chunks: List[str]) -> List[List[float]]:
        """Batch embeds a list of document chunks."""
        logger.info(f"Embedding {len(chunks)} document chunks...")
        def do_embed():
            return self.client.models.embed_content(
                model=self.embedding_model,
                contents=chunks,
                config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT")
            )

        result = self.call_with_retry(do_embed)
        return [e.values for e in result.embeddings]

    def embed_query(self, query: str) -> List[float]:
        """Embeds a single query string."""
        def do_embed_query():
            return self.client.models.embed_content(
                model=self.embedding_model,
                contents=query,
                config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY")
            )

        result = self.call_with_retry(do_embed_query)
        return result.embeddings[0].values

    def generate_answer(self, prompt: str, system_instruction: str) -> str:
        """Generates a response for a given prompt and system instruction."""
        def do_generate():
            return self.client.models.generate_content(
                model=self.generation_model,
                contents=prompt,
                config=types.GenerateContentConfig(system_instruction=system_instruction)
            )

        response = self.call_with_retry(do_generate)
        return response.text

class RAGEngine:
    """Manages the core RAG pipeline: chunking, embedding, retrieval, and generation."""

    def __init__(self, gemini_client: GeminiClient, top_k_chunks: int = 15):
        self.gemini = gemini_client
        self.top_k_chunks = top_k_chunks

    @staticmethod
    def chunk_text(text: str, chunk_size: int = 2000, overlap: int = 400) -> List[str]:
        """Splits text into overlapping chunks, attempting to break at whitespace or newlines."""
        if not text: return []

        chunks, start, text_len = [], 0, len(text)
        while start < text_len:
            if start + chunk_size >= text_len:
                chunks.append(text[start:].strip())
                break

            end = start + chunk_size
            break_point = text.rfind('\n', end - 200, end)
            if break_point == -1:
                break_point = text.rfind(' ', end - 100, end)

            if break_point != -1: end = break_point

            chunk = text[start:end].strip()
            if chunk: chunks.append(chunk)

            start = max(0, end - overlap)
            if start >= end: start = end # Safety check

        return [c for c in chunks if c]

    def find_relevant_context(self, query_embedding: List[float], chunk_embeddings: List[List[float]], chunks: List[str]) -> str:
        """Performs vector search using cosine similarity to find the most relevant document chunks."""
        query_vec = np.array(query_embedding)
        chunk_vecs = np.array(chunk_embeddings)

        dot_products = np.dot(chunk_vecs, query_vec)
        norms = np.linalg.norm(chunk_vecs, axis=1) * np.linalg.norm(query_vec)
        similarities = dot_products / norms

        k = min(self.top_k_chunks, len(chunks))
        top_k_indices = np.argsort(similarities)[-k:][::-1]

        return "\n---\n".join([chunks[i] for i in top_k_indices])

    def process_question(self, question: str, chunk_embeddings: List[List[float]], chunks: List[str], grant_context: str, persona: str) -> str:
        """Processes a single question through the RAG pipeline."""
        logger.info(f"Processing question: '{question}'")

        try:
            # 1. Embed Query
            query_embedding = self.gemini.embed_query(question)

            # 2. Retrieve Context
            context = self.find_relevant_context(query_embedding, chunk_embeddings, chunks)

            # 3. Generate Answer
            system_prompt = (
                "You are a world-class AI writer and grant reviewer. Synthesize the query, persona, "
                "and provided knowledge base to produce a polished, final-version answer. "
                "Ensure alignment with the provided persona and context. Provide ONLY the final text."
            )

            full_prompt = (
                f"--- PERSONA ---\n{persona}\n\n"
                f"--- APPLICATION CONTEXT ---\n{grant_context}\n\n"
                f"--- KNOWLEDGE BASE ---\n{context}\n\n"
                f"--- QUESTION ---\n'{question}'"
            )

            return self.gemini.generate_answer(full_prompt, system_prompt)

        except Exception as e:
            logger.error(f"Failed to process question '{question}': {e}")
            return f"[Error] Failed to process this question after multiple retries: {e}"
