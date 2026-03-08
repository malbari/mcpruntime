"""MCP (Model Context Protocol) protocol implementation.

This module provides MCP tool registration and protocol handling
for agent communication.
"""

import logging
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class MCPTool:
    """Definition of an MCP tool.

    Attributes:
        name: Tool name/identifier
        description: Human-readable description
        parameters: JSON Schema for parameters
        handler: Callable that executes the tool
    """
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: Callable[..., Any]
    returns: Dict[str, Any] = field(default_factory=dict)


class MCPRegistry:
    """Registry for MCP tools.

    The registry maintains a collection of available tools that agents
can invoke via the Model Context Protocol.

    Example:
        ```python
        registry = MCPRegistry()
        registry.register_tool(
            name="calculate",
            description="Perform a calculation",
            parameters={"expression": {"type": "string"}},
            handler=lambda expr: eval(expr)  # Simplified example
        )
        ```
    """

    def __init__(self):
        """Initialize an empty tool registry."""
        self._tools: Dict[str, MCPTool] = {}

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable[..., Any],
        returns: Optional[Dict[str, Any]] = None
    ) -> None:
        """Register a new tool.

        Args:
            name: Tool name (must be unique)
            description: What the tool does
            parameters: JSON Schema for tool parameters
            handler: Function to call when tool is invoked
            returns: Optional schema for return value

        Raises:
            ValueError: If tool name already registered
        """
        if name in self._tools:
            raise ValueError(f"Tool '{name}' already registered")

        self._tools[name] = MCPTool(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            returns=returns or {}
        )

        logger.info(f"Registered MCP tool: {name}")

    def unregister_tool(self, name: str) -> None:
        """Remove a tool from the registry.

        Args:
            name: Tool name to remove
        """
        if name in self._tools:
            del self._tools[name]
            logger.info(f"Unregistered MCP tool: {name}")

    def get_tool(self, name: str) -> Optional[MCPTool]:
        """Get a tool by name.

        Args:
            name: Tool name

        Returns:
            MCPTool if found, None otherwise
        """
        return self._tools.get(name)

    def list_tools(self) -> List[Dict[str, Any]]:
        """List all registered tools.

        Returns:
            List of tool definitions as dictionaries
        """
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "returns": tool.returns
            }
            for tool in self._tools.values()
        ]

    def invoke_tool(self, name: str, **kwargs) -> Any:
        """Invoke a tool by name with given arguments.

        Args:
            name: Tool name
            **kwargs: Arguments to pass to the tool

        Returns:
            Tool return value

        Raises:
            KeyError: If tool not found
            Exception: If tool execution fails
        """
        tool = self._tools.get(name)
        if not tool:
            raise KeyError(f"Tool '{name}' not found")

        logger.info(f"Invoking tool: {name}")
        return tool.handler(**kwargs)

    def clear(self) -> None:
        """Clear all registered tools."""
        self._tools.clear()
        logger.info("Cleared all MCP tools")


class MCPProtocolHandler:
    """Handler for MCP protocol messages.

    Processes incoming MCP requests and dispatches to appropriate tools.
    """

    def __init__(self, registry: Optional[MCPRegistry] = None):
        """Initialize protocol handler.

        Args:
            registry: Tool registry to use (creates new if None)
        """
        self.registry = registry or MCPRegistry()

    def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Process an MCP protocol request.

        Args:
            request: MCP request dictionary with 'tool' and 'params'

        Returns:
            Response dictionary with 'result' or 'error'
        """
        try:
            tool_name = request.get("tool")
            params = request.get("params", {})

            if not tool_name:
                return {"error": "Missing 'tool' field", "code": 400}

            result = self.registry.invoke_tool(tool_name, **params)
            return {"result": result, "code": 200}

        except KeyError as e:
            logger.warning(f"Tool not found: {e}")
            return {"error": str(e), "code": 404}

        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            return {"error": str(e), "code": 500}
