from unittest.mock import AsyncMock, patch

import pytest

from commands.source_commands import SourceProcessingInput, process_source_command
from open_notebook.domain.notebook import Asset, Source
from open_notebook.exceptions import NotFoundError


class TestProcessSourceCommand:
    @pytest.mark.asyncio
    async def test_process_source_command_retries_source_lookup_and_succeeds(self):
        source = Source(id="source:1", title="old-title")

        with patch(
            "commands.source_commands.Source.get",
            new=AsyncMock(side_effect=[NotFoundError("missing"), source]),
        ) as mock_get, patch(
            "commands.source_commands.asyncio.sleep",
            new=AsyncMock(return_value=None),
        ), patch(
            "open_notebook.domain.notebook.Source.save",
            new=AsyncMock(return_value=None),
        ), patch.object(
            Source,
            "get_insights",
            new=AsyncMock(return_value=[]),
        ):
            result = await process_source_command(
                SourceProcessingInput(
                    source_id="source:1",
                    content_state={
                        "content": "# Guide",
                        "url": "https://raw/guide",
                        "file_path": "docs/guide.md",
                        "title": "docs/guide.md",
                    },
                    notebook_ids=[],
                    transformations=[],
                    embed=False,
                )
            )

        assert result.success is True
        assert mock_get.await_count == 2
        assert source.title == "docs/guide.md"
        assert source.full_text == "# Guide"
        assert source.asset is not None
        assert source.asset.url == "https://raw/guide"
        assert source.asset.file_path == "docs/guide.md"

    @pytest.mark.asyncio
    async def test_process_source_command_returns_failure_when_source_is_missing(self):
        with patch(
            "commands.source_commands.Source.get",
            new=AsyncMock(side_effect=NotFoundError("missing")),
        ), patch(
            "commands.source_commands.asyncio.sleep",
            new=AsyncMock(return_value=None),
        ):
            result = await process_source_command(
                SourceProcessingInput(
                    source_id="source:missing",
                    content_state={"content": "# Guide"},
                    notebook_ids=[],
                    transformations=[],
                    embed=False,
                )
            )

        assert result.success is False
        assert result.source_id == "source:missing"
        assert result.error_message is not None
        assert "not found after" in result.error_message

    @pytest.mark.asyncio
    async def test_process_source_command_preserves_existing_asset_file_path(self):
        source = Source(
            id="source:1",
            title="docs/guide.md",
            asset=Asset(url="https://raw/original", file_path="docs/guide.md"),
        )

        with patch(
            "commands.source_commands.Source.get",
            new=AsyncMock(return_value=source),
        ), patch(
            "open_notebook.domain.notebook.Source.save",
            new=AsyncMock(return_value=None),
        ), patch.object(
            Source,
            "get_insights",
            new=AsyncMock(return_value=[]),
        ):
            result = await process_source_command(
                SourceProcessingInput(
                    source_id="source:1",
                    content_state={
                        "content": "# Guide",
                        "url": "https://raw/updated",
                        "title": "docs/guide.md",
                    },
                    notebook_ids=[],
                    transformations=[],
                    embed=False,
                )
            )

        assert result.success is True
        assert source.asset is not None
        assert source.asset.url == "https://raw/updated"
        assert source.asset.file_path == "docs/guide.md"
