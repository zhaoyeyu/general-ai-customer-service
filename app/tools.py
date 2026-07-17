from __future__ import annotations

from dataclasses import dataclass

from .rag import SearchHit, bm25_search
from .storage import Store


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    risk: str
    requires_approval: bool


class KnowledgeSearchTool:
    definition = ToolDefinition(
        name="knowledge_search",
        description="Search the local customer-service knowledge base and return cited text chunks.",
        risk="read_only",
        requires_approval=False,
    )

    def __init__(self, store: Store):
        self.store = store

    def execute(self, query: str, limit: int) -> list[SearchHit]:
        return bm25_search(query, self.store.all_chunks(), limit=limit)


class HumanHandoffTool:
    definition = ToolDefinition(
        name="request_human_handoff",
        description="Create a human-support handoff ticket with the conversation context.",
        risk="limited_write",
        requires_approval=False,
    )

    def __init__(self, store: Store):
        self.store = store

    def execute(self, conversation_id: str, reason: str, summary: str) -> str:
        return self.store.create_handoff(conversation_id, reason, summary)


class ToolRegistry:
    """Explicit capability boundary for tools available to the support workflow."""

    def __init__(self, store: Store):
        self.knowledge_search = KnowledgeSearchTool(store)
        self.human_handoff = HumanHandoffTool(store)

    def definitions(self) -> list[ToolDefinition]:
        return [self.knowledge_search.definition, self.human_handoff.definition]

