"""Capability / tool registry.

Every capability the orchestrator can invoke — analysis, retrieval, web search,
visual generation, warehouse queries — is a `Tool` registered here. The registry
is the single source of truth for:

  * which tools exist and their JSON schemas (advertised to the LLM),
  * which tools a given mode / trust-tier is allowed to use (gating),
  * how each tool executes (a uniform `execute(ctx, input) -> dict` contract).

This is also the surface we expose over MCP (see mcp.py) so the same tools work
across Claude, Ollama and external MCP clients.
"""
from .base import Tool, ToolContext, ToolRegistry, get_registry

__all__ = ["Tool", "ToolContext", "ToolRegistry", "get_registry"]
