"""ResourceManifest — user-declared external data, tools, and MCP servers (scenario 3).

Declared at `sv-init` time (or alongside the query). Skills and providers read it to
attach a population pool MCP, a user-uploaded dataset, or custom tools.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class McpServerDecl(BaseModel):
    name: str
    transport: Literal["stdio", "http", "sse"] = "stdio"
    command: str | None = None      # for stdio
    args: list[str] = Field(default_factory=list)
    url: str | None = None          # for http/sse
    env: dict[str, str] = Field(default_factory=dict)
    description: str = ""


class DatasetDecl(BaseModel):
    name: str
    path: str
    kind: Literal["geojson", "csv", "parquet", "json", "shapefile", "other"] = "other"
    description: str = ""


class ToolDecl(BaseModel):
    name: str
    description: str = ""
    spec: dict[str, Any] = Field(default_factory=dict)


class ResourceManifest(BaseModel):
    study_id: str
    mcp_servers: list[McpServerDecl] = Field(default_factory=list)
    datasets: list[DatasetDecl] = Field(default_factory=list)
    tools: list[ToolDecl] = Field(default_factory=list)

    def dataset(self, name: str) -> DatasetDecl | None:
        return next((d for d in self.datasets if d.name == name), None)
