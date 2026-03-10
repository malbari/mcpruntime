"""Tool selection using semantic search on tool descriptions.

This module provides generic tool selection capabilities that can be used
by any example or agent to determine which tools are needed for a task.
"""

import ast
import logging
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Try to import sentence-transformers for semantic search
try:
    from sentence_transformers import SentenceTransformer

    HAS_SENTENCE_TRANSFORMERS = True
except Exception as e:
    HAS_SENTENCE_TRANSFORMERS = False
    SentenceTransformer = None  # type: ignore
    logger.warning(f"sentence-transformers not available or broken ({e}). Using keyword matching instead.")

# Class-level model cache to avoid reloading the model across instances
_SHARED_MODEL: Optional[Any] = None
_SHARED_MODEL_LOCK = None
try:
    import threading
    _SHARED_MODEL_LOCK = threading.Lock()
except ImportError:
    pass


_GENERIC_PREFIXES = ("chiama ", "calls ", "call ", "stub per ", "wrapper per ")


def extract_tool_description(tool_code: str) -> str:
    """Extract tool description from Python code docstring.

    For auto-generated stubs with generic docstrings ("Chiama X su Y"),
    builds a richer description from the function name and parameter names
    so that semantic search can match natural-language prompts.
    """
    try:
        tree = ast.parse(tool_code)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                docstring = ast.get_docstring(node) or ""
                params = [arg.arg for arg in node.args.args]
                # If the docstring carries real semantic content, use it
                if docstring and not any(
                    docstring.lower().startswith(p) for p in _GENERIC_PREFIXES
                ):
                    # Still append param names for extra matching surface
                    param_str = " ".join(params)
                    return f"{docstring} {param_str}".strip() if param_str else docstring
                # Generic / missing docstring → derive from function name + params
                # Repeat the function name words 3× so they dominate the embedding
                # regardless of how many parameter names are present.
                name_words = node.name.replace("_", " ")
                param_str = " ".join(params)
                return f"{name_words} {name_words} {name_words} {param_str}".strip()
    except Exception as e:
        logger.debug(f"Failed to extract tool description: {e}")
    return ""


class ToolSelector:
    """Generic tool selector that uses semantic search to find relevant tools."""

    def __init__(
        self,
        similarity_threshold: float = 0.20,
        top_k: int = 5,
        use_semantic_search: bool = True,
    ):
        """Initialize tool selector.

        Args:
            similarity_threshold: Minimum similarity score for tool selection
            top_k: Maximum number of tools to return
            use_semantic_search: Whether to use semantic search (requires sentence-transformers)
        """
        self.similarity_threshold = similarity_threshold
        self.top_k = top_k
        self.use_semantic_search = use_semantic_search and HAS_SENTENCE_TRANSFORMERS
        self._model: Optional[Any] = None

    def _get_model(self, use_gpu: bool = True) -> Optional[Any]:
        """Lazy load the sentence transformer model (uses shared cache).
        
        Args:
            use_gpu: Whether to use GPU if available (from config)
        """
        global _SHARED_MODEL
        
        if not self.use_semantic_search:
            return None

        # Use instance model if available
        if self._model is not None:
            return self._model
        
        # Try to use shared model cache (thread-safe)
        if _SHARED_MODEL is not None:
            self._model = _SHARED_MODEL
            return self._model
        
        # Load model (with lock if available)
        if _SHARED_MODEL_LOCK:
            with _SHARED_MODEL_LOCK:
                # Double-check after acquiring lock
                if _SHARED_MODEL is not None:
                    self._model = _SHARED_MODEL
                    return self._model
                
                try:
                    # Check for GPU support (optimization)
                    device = "cpu"
                    if use_gpu:
                        try:
                            import torch
                            if torch.cuda.is_available():
                                device = "cuda"
                                logger.info("GPU available, using CUDA for embeddings")
                            elif torch.backends.mps.is_available():
                                device = "mps"
                                logger.info("Apple Silicon GPU available, using MPS for embeddings")
                            else:
                                logger.debug("GPU not available, using CPU")
                        except Exception as e:
                            logger.debug(f"PyTorch not available or broken ({e}), using CPU")
                    
                    logger.info(f"Loading sentence-transformers model on {device}...")
                    # Multilingual model: handles Italian, English, and 50+ languages
                    _SHARED_MODEL = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2", device=device)
                    self._model = _SHARED_MODEL
                    logger.info(f"Model loaded on {device} and cached for future use")
                except Exception as e:
                    logger.warning(f"Failed to load sentence-transformers model: {e}")
                    self.use_semantic_search = False
                    return None
        else:
            # No threading, just load directly
            try:
                device = "cpu"
                if use_gpu:
                    try:
                        import torch
                        if torch.cuda.is_available():
                            device = "cuda"
                        elif torch.backends.mps.is_available():
                            device = "mps"
                    except Exception as e:
                        logger.debug(f"PyTorch broken ({e}), using CPU")
                
                logger.info(f"Loading sentence-transformers model on {device}...")
                self._model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2", device=device)
                _SHARED_MODEL = self._model
            except Exception as e:
                logger.warning(f"Failed to load sentence-transformers model: {e}")
                self.use_semantic_search = False
                return None

        return self._model

    def get_tool_descriptions(
        self,
        fs_helper: Any,  # FilesystemHelper
        discovered_servers: Dict[str, List[str]],
    ) -> Dict[Tuple[str, str], str]:
        """Extract descriptions for all discovered tools.

        Args:
            fs_helper: FilesystemHelper instance
            discovered_servers: Dict mapping server names to lists of tool names

        Returns:
            Dict mapping (server_name, tool_name) tuples to descriptions
        """
        tool_descriptions = {}
        for server_name, tools in discovered_servers.items():
            for tool_name in tools:
                tool_code = fs_helper.read_tool_file(server_name, tool_name)
                if tool_code:
                    description = extract_tool_description(tool_code)
                    # Include server and tool name in description for better matching
                    full_description = f"{server_name} {tool_name}: {description}"
                    tool_descriptions[(server_name, tool_name)] = full_description
        return tool_descriptions

    # ------------------------------------------------------------------
    # BM25 helper (pure Python, no external dependencies)
    # ------------------------------------------------------------------

    @staticmethod
    def _bm25_scores(query: str, documents: List[str]) -> List[float]:
        """BM25 relevance scores for *documents* against *query*.

        Pure Python implementation — no rank_bm25 or other package required.
        Supports accented Latin characters (Italian, French, Spanish, …).
        """
        import math
        import re

        def tokenize(text: str) -> List[str]:
            return re.findall(r"[a-zA-ZàèéìíîòóùúÀÈÉÌÍÎÒÓÙÚ0-9]+", text.lower())

        query_tokens = tokenize(query)
        if not query_tokens:
            return [0.0] * len(documents)

        doc_tokens = [tokenize(doc) for doc in documents]
        n = len(documents)
        k1, b = 1.5, 0.75
        avg_dl = sum(len(d) for d in doc_tokens) / max(n, 1)

        scores = [0.0] * n
        for term in set(query_tokens):
            df = sum(1 for d in doc_tokens if term in d)
            if df == 0:
                continue
            idf = math.log((n - df + 0.5) / (df + 0.5) + 1.0)
            for i, d in enumerate(doc_tokens):
                tf = d.count(term)
                if tf == 0:
                    continue
                dl = len(d)
                denom = tf + k1 * (1.0 - b + b * dl / avg_dl)
                scores[i] += idf * tf * (k1 + 1.0) / denom
        return scores

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def select_tools(
        self,
        task_description: str,
        tool_descriptions: Dict[Tuple[str, str], str],
        use_gpu: bool = True,
    ) -> Dict[str, List[str]]:
        """Select relevant tools for a task using hybrid BM25 + semantic search.

        Args:
            task_description: Description of the task to accomplish
            tool_descriptions: Dict mapping (server_name, tool_name) to descriptions
            use_gpu: Whether to use GPU if available (from config)

        Returns:
            Dict mapping server names to lists of selected tool names
        """
        if self.use_semantic_search:
            return self._hybrid_search_tools(task_description, tool_descriptions, use_gpu=use_gpu)
        else:
            return self._keyword_match_tools(task_description, tool_descriptions)

    def _hybrid_search_tools(
        self,
        task_description: str,
        tool_descriptions: Dict[Tuple[str, str], str],
        use_gpu: bool = True,
    ) -> Dict[str, List[str]]:
        """Hybrid BM25 + dense semantic search with Reciprocal Rank Fusion (RRF).

        Combines keyword precision (BM25) with semantic generalisation (cosine
        similarity) so that neither signal dominates alone.  Tools are ranked
        by the combined RRF score; the dense-similarity threshold still gates
        which tools are actually returned.

        Args:
            task_description: Natural-language description of the task.
            tool_descriptions: Dict mapping (server, tool) → text description.
            use_gpu: Whether to use GPU/MPS for embedding computation.
        """
        model = self._get_model(use_gpu=use_gpu)
        if model is None:
            logger.warning("Falling back to keyword matching")
            return self._keyword_match_tools(task_description, tool_descriptions)

        try:
            import torch

            tool_keys = list(tool_descriptions.keys())
            tool_texts = list(tool_descriptions.values())

            # ---- BM25 ranking ----
            bm25 = self._bm25_scores(task_description, tool_texts)
            bm25_order = sorted(range(len(bm25)), key=lambda i: -bm25[i])
            bm25_rank = {i: rank + 1 for rank, i in enumerate(bm25_order)}

            # ---- Dense cosine similarity ----
            if use_gpu and torch.cuda.is_available():
                device = "cuda"
            elif use_gpu and torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"

            task_emb = model.encode(
                task_description, convert_to_tensor=True, show_progress_bar=False
            ).to(device)
            tool_embs = model.encode(
                tool_texts, convert_to_tensor=True, show_progress_bar=False
            ).to(device)

            task_norm = torch.nn.functional.normalize(task_emb, p=2, dim=0)
            tool_norm = torch.nn.functional.normalize(tool_embs, p=2, dim=1)
            sims = torch.mm(tool_norm, task_norm.unsqueeze(1)).squeeze(1).cpu().tolist()

            dense_order = sorted(range(len(sims)), key=lambda i: -sims[i])
            dense_rank = {i: rank + 1 for rank, i in enumerate(dense_order)}

            # ---- Reciprocal Rank Fusion (k = 60) ----
            RRF_K = 60
            rrf = [
                1.0 / (RRF_K + bm25_rank[i]) + 1.0 / (RRF_K + dense_rank[i])
                for i in range(len(tool_keys))
            ]
            ranked = sorted(range(len(rrf)), key=lambda i: -rrf[i])

            # ---- Log top-5 for diagnostics ----
            for pos, idx in enumerate(ranked[:5], 1):
                srv, tname = tool_keys[idx]
                logger.info(
                    "  Top-%d: %s.%s  (rrf=%.4f  dense=%.3f  bm25=%.3f  "
                    "dense_rank=%d  bm25_rank=%d)",
                    pos, srv, tname,
                    rrf[idx], sims[idx], bm25[idx],
                    dense_rank[idx], bm25_rank[idx],
                )

            # ---- Build result: top_k tools that clear the relevance gate ----
            # A tool is included when EITHER the dense score meets the threshold
            # OR BM25 has a positive hit (query keyword literally in description).
            # This prevents pure-dense threshold from discarding lexically obvious
            # matches (e.g. "news" in prompt → news_get with bm25=3.5 but low cosine).
            top_k = min(self.top_k, len(ranked))
            selected_tools: Dict[str, List[str]] = {}
            for idx in ranked[:top_k]:
                if sims[idx] >= self.similarity_threshold or bm25[idx] > 0:
                    srv, tname = tool_keys[idx]
                    selected_tools.setdefault(srv, []).append(tname)

            if not selected_tools and ranked:
                best_idx = ranked[0]
                best_srv, best_tool = tool_keys[best_idx]
                logger.warning(
                    "[ToolSelector] Nessun tool sopra soglia %.2f "
                    "— uso best-match RRF: %s.%s (dense=%.3f  bm25=%.3f)",
                    self.similarity_threshold, best_srv, best_tool,
                    sims[best_idx], bm25[best_idx],
                )
                selected_tools = {best_srv: [best_tool]}

            return selected_tools

        except Exception as e:
            logger.warning(f"Hybrid search failed ({e}), falling back to keyword matching")
            return self._keyword_match_tools(task_description, tool_descriptions)

    def _semantic_search_tools(
        self,
        task_description: str,
        tool_descriptions: Dict[Tuple[str, str], str],
        use_gpu: bool = True,
    ) -> Dict[str, List[str]]:
        """Dense-only cosine similarity (kept for reference; _hybrid_search_tools is preferred)."""
        return self._hybrid_search_tools(task_description, tool_descriptions, use_gpu=use_gpu)

    def _keyword_match_tools(
        self,
        task_description: str,
        tool_descriptions: Dict[Tuple[str, str], str],
    ) -> Dict[str, List[str]]:
        """Simple keyword-based tool matching (fallback)."""
        task_lower = task_description.lower()
        selected_tools = {}

        # Simple keyword matching
        keywords = {
            "calculator": [
                "calculate",
                "add",
                "multiply",
                "math",
                "compute",
                "sum",
                "subtract",
                "divide",
            ],
            "weather": ["weather", "temperature", "forecast", "climate", "rain", "sunny"],
            "filesystem": ["file", "read", "write", "directory", "folder", "path"],
            "database": ["database", "query", "sql", "table", "data", "insert", "select"],
        }

        for (server_name, tool_name), description in tool_descriptions.items():
            desc_lower = description.lower()
            # Check if task keywords match tool description
            server_keywords = keywords.get(server_name, [])
            if any(keyword in task_lower and keyword in desc_lower for keyword in server_keywords):
                if server_name not in selected_tools:
                    selected_tools[server_name] = []
                selected_tools[server_name].append(tool_name)
                logger.debug(f"Selected {server_name}.{tool_name} (keyword match)")

        return selected_tools
