from unittest.mock import AsyncMock, patch

import pytest

from api.models import BulkDeleteSourcesRequest
from api.routers.sources import bulk_delete_sources


class FakeSource:
    def __init__(self, source_id: str, delete_side_effect: Exception | None = None):
        self.id = source_id
        self._delete_side_effect = delete_side_effect

    async def delete(self):
        if self._delete_side_effect is not None:
            raise self._delete_side_effect
        return True


@pytest.mark.asyncio
async def test_bulk_delete_sources_returns_deleted_not_found_and_failed_ids():
    async def get_source(source_id: str):
        if source_id == "source:missing":
            return None
        if source_id == "source:failed":
            return FakeSource(source_id, RuntimeError("delete failed"))
        return FakeSource(source_id)

    with patch("api.routers.sources.Source.get", new=AsyncMock(side_effect=get_source)):
        response = await bulk_delete_sources(
            BulkDeleteSourcesRequest(
                source_ids=["source:1", "source:missing", "source:failed"]
            )
        )

    assert response.deleted_ids == ["source:1"]
    assert response.not_found_ids == ["source:missing"]
    assert response.failed_ids == ["source:failed"]
