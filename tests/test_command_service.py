from unittest.mock import AsyncMock, patch

import pytest

from api.command_service import CommandService
from open_notebook.exceptions import InvalidInputError


@pytest.mark.asyncio
async def test_list_command_jobs_returns_source_queue_items():
    command_rows = [
        {
            "id": "command:1",
            "app": "open_notebook",
            "name": "process_source",
            "status": "new",
            "created": "2026-03-17T12:00:00Z",
            "updated": "2026-03-17T12:00:00Z",
        },
        {
            "id": "command:2",
            "app": "open_notebook",
            "name": "embed_note",
            "status": "completed",
            "created": "2026-03-17T11:00:00Z",
            "updated": "2026-03-17T11:00:00Z",
        },
    ]
    source_rows = [
        {
            "id": "source:1",
            "title": "docs/readme.md",
            "asset": {"file_path": "docs/readme.md", "url": "https://example.test/raw"},
            "command": "command:1",
        }
    ]

    with patch(
        "api.command_service.repo_query",
        new=AsyncMock(side_effect=[command_rows, source_rows]),
    ):
        jobs = await CommandService.list_command_jobs(source_only=True, limit=20)

    assert len(jobs) == 1
    assert jobs[0]["job_id"] == "command:1"
    assert jobs[0]["source_id"] == "source:1"
    assert jobs[0]["source_path"] == "docs/readme.md"
    assert jobs[0]["can_cancel"] is True


@pytest.mark.asyncio
async def test_cancel_command_job_updates_new_job_to_canceled():
    with patch(
        "api.command_service.repo_query",
        new=AsyncMock(return_value=[{"id": "command:1", "status": "new"}]),
    ), patch("api.command_service.repo_update", new=AsyncMock()) as mock_update:
        result = await CommandService.cancel_command_job("command:1")

    assert result is True
    mock_update.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_command_job_rejects_running_job():
    with patch(
        "api.command_service.repo_query",
        new=AsyncMock(return_value=[{"id": "command:1", "status": "running"}]),
    ):
        with pytest.raises(InvalidInputError):
            await CommandService.cancel_command_job("command:1")
