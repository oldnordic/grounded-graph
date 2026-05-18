"""grounded-graph — graph traversal and context queries over code metadata."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("grounded-graph")
except PackageNotFoundError:  # running from source without `pip install`
    __version__ = "0.0.0+local"

from grounded_graph.context import NeighborsProvider, pack_context, rank_neighbors
from grounded_graph.embedder import Embedder, HashEmbedder, OllamaEmbedder, embedder_from_config
from grounded_graph.graph import CALL_LIKE_KINDS, Graph, GraphEdge, GraphNode
from grounded_graph.query import QueryEngine

__all__ = [
    "CALL_LIKE_KINDS",
    "Embedder",
    "Graph",
    "GraphEdge",
    "GraphNode",
    "HashEmbedder",
    "NeighborsProvider",
    "OllamaEmbedder",
    "QueryEngine",
    "__version__",
    "embedder_from_config",
    "pack_context",
    "rank_neighbors",
]
