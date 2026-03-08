"""OpenSandbox integration for Docker-based execution.

This module provides the OpenSandbox integration for containerized
code execution with proper isolation.
"""

import logging
from typing import Any, Dict, Optional, List

logger = logging.getLogger(__name__)


class OpenSandboxClient:
    """Client for OpenSandbox Docker-based execution.

    This client provides a Python interface to the OpenSandbox server
    for running code in isolated Docker containers.

    Attributes:
        server_url: URL of the OpenSandbox server
        default_image: Default Docker image to use

    Example:
        ```python
        client = OpenSandboxClient("http://localhost:8080")
        result = client.execute("print('Hello, World!')")
        ```
    """

    def __init__(
        self,
        server_url: str = "http://localhost:8080",
        default_image: str = "python:3.11-slim",
        api_key: Optional[str] = None
    ):
        """Initialize the OpenSandbox client.

        Args:
            server_url: URL of the OpenSandbox server
            default_image: Default Docker image for containers
            api_key: Optional API key for authentication
        """
        self.server_url = server_url.rstrip("/")
        self.default_image = default_image
        self.api_key = api_key
        self._session = None

    def _get_session(self):
        """Get or create HTTP session."""
        if self._session is None:
            try:
                import httpx
                self._session = httpx.Client(
                    headers=self._get_headers(),
                    timeout=300.0
                )
            except ImportError:
                raise ImportError("httpx is required for OpenSandbox client")
        return self._session

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def execute(
        self,
        code: str,
        context: Optional[Dict] = None,
        skills: Optional[List[str]] = None,
        timeout: Optional[int] = None,
        max_memory: Optional[int] = None,
        image: Optional[str] = None
    ) -> Dict[str, Any]:
        """Execute code in a sandboxed container.

        Args:
            code: Python code to execute
            context: Optional context dictionary to inject
            skills: Optional list of skills to make available
            timeout: Execution timeout in seconds
            max_memory: Maximum memory in MB
            image: Docker image to use (defaults to default_image)

        Returns:
            Dictionary with keys: success, output, error, execution_time
        """
        import time

        start_time = time.time()

        payload = {
            "code": code,
            "image": image or self.default_image,
        }

        if context:
            payload["context"] = context

        if skills:
            payload["skills"] = skills

        if timeout:
            payload["timeout"] = timeout

        if max_memory:
            payload["max_memory"] = max_memory

        try:
            session = self._get_session()
            response = session.post(
                f"{self.server_url}/execute",
                json=payload
            )
            response.raise_for_status()

            result = response.json()
            result["execution_time"] = time.time() - start_time
            return result

        except Exception as e:
            logger.error(f"Sandbox execution failed: {e}")
            return {
                "success": False,
                "output": "",
                "error": str(e),
                "execution_time": time.time() - start_time
            }

    def health_check(self) -> bool:
        """Check if the OpenSandbox server is reachable.

        Returns:
            True if server is healthy, False otherwise
        """
        try:
            session = self._get_session()
            response = session.get(f"{self.server_url}/health", timeout=5.0)
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False

    def close(self) -> None:
        """Close the HTTP session."""
        if self._session:
            self._session.close()
            self._session = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
