"""runloq MCP server package.

Exposes the runloq issue tracker as an MCP server so any MCP-capable agent
(Claude Code, Cursor, Codex) can drive the tracker programmatically over
the stdio transport — no CLI, no UI.

Entry point: ``runloq-mcp`` console script → ``prism.mcp.server:main``
"""
