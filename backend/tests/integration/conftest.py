"""Integration-only application startup isolation.

Production lifespan still performs reranker warmup and index loading.  These
tests exercise HTTP wiring and persistence, so they inject a small in-memory
indexer/graph before entering LifespanManager to avoid downloading/loading
multi-gigabyte models during every test.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from app.config import settings


@pytest.fixture(autouse=True)
def isolate_expensive_startup():
    settings.AUTH_ADMIN_USERNAME = "test-admin"
    settings.AUTH_ADMIN_PASSWORD = "Admin-pass-1"
    fake_indexer = MagicMock(name="integration_indexer")
    fake_indexer.get_retriever.return_value = MagicMock(name="integration_retriever")
    fake_indexer.chroma_collection = SimpleNamespace(
        count=MagicMock(return_value=0),
        get=MagicMock(return_value={"metadatas": []}),
    )
    fake_graph = MagicMock(name="integration_graph")

    with patch("app.rag.retriever.get_cross_encoder", return_value=MagicMock(name="reranker")), \
         patch("app.rag.indexer.create_profiled_indexer", return_value=fake_indexer), \
         patch("app.graph.builder.build_graph", return_value=fake_graph):
        yield {
            "indexer": fake_indexer,
            "graph": fake_graph,
        }
