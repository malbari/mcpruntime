"""Recursive Agent implementation for infinite context tasks.

This module implements the Recursive Language Model (RLM) pattern, treating context
as a variable in the environment that can be programmatically inspected and
recursively queried by the LLM.

RLM is an advanced capability that requires a QueryableContextProvider —
a context source large enough to require recursive traversal.
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Import QueryableContextProvider for type checking
from mcpruntime.context.provider import QueryableContextProvider, ContextResult

logger = logging.getLogger(__name__)

# Optional litellm import
HAS_LITELLM = False
try:
    import litellm  # noqa: F401
    HAS_LITELLM = True
except ImportError:
    pass


class RecursiveAgent:
    """Agent that handles infinite context using recursive calls.

    **IMPORTANT**: This agent requires a QueryableContextProvider.
    Passing a base ContextProvider will raise a TypeError.

    RLM is not a core primitive — it's an advanced capability for processing
    large context that exceeds standard context windows. It only makes sense
    when you have a context source that supports structured traversal.

    Example:
        ```python
        from mcpruntime.context.default import FileContextProvider
        from extensions.rlm.agent import RecursiveAgent

        # FileContextProvider is NOT Queryable — this will fail
        flat_provider = FileContextProvider("./context")
        # TypeError: RecursiveAgent requires QueryableContextProvider
        agent = RecursiveAgent(provider=flat_provider)

        # Instead, implement QueryableContextProvider for large knowledge bases
        class MyQueryableProvider(QueryableContextProvider):
            def query(self, expression: str, depth: int = 1):
                # Your implementation
                pass

        provider = MyQueryableProvider()
        agent = RecursiveAgent(provider=provider)  # OK
        ```
    """

    def __init__(
        self,
        provider: Any,
        llm_config: Optional[Dict] = None,
        verbose: bool = False
    ):
        """Initialize recursive agent.

        Args:
            provider: Must be a QueryableContextProvider instance
            llm_config: Optional LLM configuration
            verbose: Enable verbose output

        Raises:
            TypeError: If provider is not a QueryableContextProvider
        """
        # Enforce QueryableContextProvider requirement
        if not isinstance(provider, QueryableContextProvider):
            raise TypeError(
                "RecursiveAgent requires a QueryableContextProvider. "
                "The provided context source does not support structured traversal. "
                "RLM is an advanced capability for large knowledge sources — "
                "use a standard Agent with a regular ContextProvider for simpler use cases."
            )

        self.provider = provider
        self.llm_config = llm_config or {}
        self.verbose = verbose
        self.context_data = None

    def _ask_llm(self, prompt: str, data: str) -> str:
        """Recursive callback to query LLM with a chunk of data.

        Args:
            prompt: The question to ask
            data: Context data to provide

        Returns:
            LLM response
        """
        if self.verbose:
            print(f"\n[RLM] ask_llm called with prompt: '{prompt}' and data length: {len(data)}")

        if not HAS_LITELLM:
            return "Error: litellm package not installed. Install with: pip install litellm"

        full_prompt = f"Context:\n{data}\n\nQuestion: {prompt}\n\nAnswer:"

        try:
            import litellm

            model = self.llm_config.get("model", "gpt-4")
            api_key = self.llm_config.get("api_key") or os.environ.get("OPENAI_API_KEY")
            api_base = self.llm_config.get("api_base")
            api_version = self.llm_config.get("api_version")

            completion_params = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant. Answer the question based on the context provided."},
                    {"role": "user", "content": full_prompt}
                ],
                "temperature": 0.0,
            }

            if api_key:
                completion_params["api_key"] = api_key
            if api_base:
                completion_params["api_base"] = api_base
            if api_version:
                completion_params["api_version"] = api_version

            response = litellm.completion(**completion_params)
            answer = response.choices[0].message.content.strip()

            if self.verbose:
                print(f"[RLM] Answer: {answer[:100]}...")

            return answer

        except Exception as e:
            logger.error(f"ask_llm failed: {e}")
            return f"Error during LLM call: {e}"

    def execute_recursive_task(
        self,
        task_description: str,
        context_data: Union[str, Path],
        verbose: bool = True,
        required_tools: Optional[Dict[str, List[str]]] = None
    ) -> Any:
        """Execute a task with large context using RLM pattern.

        Args:
            task_description: The goal (e.g. "Find the error code")
            context_data: The large context (string or Path to file)
            verbose: Whether to print progress
            required_tools: Optional explicit tools to use

        Returns:
            Execution result
        """
        # Load context data
        if isinstance(context_data, Path) or (isinstance(context_data, str) and os.path.exists(context_data)):
            try:
                with open(context_data, "r", encoding="utf-8") as f:
                    self.context_data = f.read()
            except Exception as e:
                return None, None, f"Failed to load context file: {e}"
        else:
            self.context_data = context_data

        # Get context from provider
        context_result = self.provider.get_context(task_description)

        # Use query capability for large context
        if hasattr(self.provider, 'query'):
            # Query for relevant chunks
            query_results = list(self.provider.query(task_description, depth=2))
            if query_results:
                context_result.context['queried_data'] = query_results

        # Define the recursive callback
        execution_context = {
            "inputs": {},
            "functions": {
                "ask_llm": self._ask_llm
            }
        }

        if self.context_data is not None:
            execution_context["inputs"]["CONTEXT_DATA"] = self.context_data

            # Modify task description to include RLM instructions
            rlm_instructions = (
                "\n\nIMPORTANT: The relevant context is loaded into the variable 'CONTEXT_DATA'. "
                "It is too large to read at once. "
                "Write Python code to inspect, slice, or search this variable. "
                "CONTEXT_DATA is a plain Python variable already in scope — access it directly, do NOT call globals(). "
                "To reason about a specific chunk, call 'ask_llm(question, chunk_string)'. "
                "Do NOT print the entire CONTEXT_DATA. "
                "When you find the answer, print it clearly so it appears in the output. "
                "Example pattern:\n"
                "chunk_size = 2000\n"
                "chunks = [CONTEXT_DATA[i:i+chunk_size] for i in range(0, len(CONTEXT_DATA), chunk_size)]\n"
                "found = None\n"
                "for chunk in chunks:\n"
                "    answer = ask_llm('If this chunk contains relevant information to answer the task, reply FOUND: <answer>. Otherwise reply NOT_FOUND.', chunk)\n"
                "    if 'FOUND:' in answer:\n"
                "        found = answer\n"
                "        break\n"
                "if found:\n"
                "    print(found)\n"
                "else:\n"
                "    print('No result found in CONTEXT_DATA.')\n"
            )
            full_task = task_description + rlm_instructions
        else:
            full_task = task_description

        if self.verbose:
            print(f"[RLM] Task: {task_description}")
            print(f"[RLM] Context size: {len(self.context_data) if self.context_data else 0} chars")

        # Return execution context for the caller to use
        return {
            "task": full_task,
            "execution_context": execution_context,
            "context_result": context_result,
            "rlm_enabled": True
        }

    def query_context(self, expression: str, depth: int = 1) -> List[Dict]:
        """Query the context provider directly.

        Args:
            expression: Query expression
            depth: Traversal depth

        Returns:
            List of context chunks
        """
        return list(self.provider.query(expression, depth=depth))
