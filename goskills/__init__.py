"""GoSkills: group-structured skill retrieval for agent skill libraries."""

from .group_graph import build_group_graph, ensure_group_graph
from .retrieval import retrieve

__all__ = ["build_group_graph", "ensure_group_graph", "retrieve"]
