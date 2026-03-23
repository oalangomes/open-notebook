from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from api.command_service import CommandService


@pytest.mark.asyncio
async def test_list_command_jobs_marks_stale_source_job_as_failed():
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=20)
    refreshed_time = datetime.now(timezone.utc)

    command_rows = [
        {
            "id": "command:stale",
            "app": "open_notebook",
            "name": "process_source",
            "status": "new",
            "result": None,
            "error_message": None,
            "created": stale_time,
            "updated": stale_time,
            "progress": None,
        }
    ]
    source_rows = [
        {
            "id": "source:1",
            "title": "docs/guide.md",
            "asset": {"file_path": "docs/guide.md", "url": "https://raw/guide"},
            "command": "command:stale",
        }
    ]
    refreshed_row = {
        "id": "command:stale",
        "app": "open_notebook",
        "name": "process_source",
        "status": "failed",
        "result": None,
        "error_message": "Command exceeded 15 minutes without status change and was marked as failed",
        "created": stale_time,
        "updated": refreshed_time,
        "progress": None,
    }

    with patch(
        "api.command_service.repo_query",
        new=AsyncMock(side_effect=[command_rows, source_rows, [refreshed_row]]),
    ), patch(
        "api.command_service.repo_update",
        new=AsyncMock(return_value=[refreshed_row]),
    ) as mock_update:
        jobs = await CommandService.list_command_jobs(source_only=True, limit=10)

    assert jobs[0]["status"] == "failed"
    assert "marked as failed" in (jobs[0]["error_message"] or "")
    mock_update.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_command_status_marks_completed_job_with_success_false_as_failed():
    completed_row = {
        "id": "command:1",
        "status": "completed",
        "result": {
            "success": False,
            "error_message": "Model is not a LanguageModel",
        },
        "error_message": None,
        "created": datetime.now(timezone.utc),
        "updated": datetime.now(timezone.utc),
        "progress": None,
    }
    refreshed_row = {
        **completed_row,
        "status": "failed",
        "error_message": "Model is not a LanguageModel",
    }

    with patch(
        "api.command_service.repo_query",
        new=AsyncMock(side_effect=[[completed_row], [refreshed_row]]),
    ), patch(
        "api.command_service.repo_update",
        new=AsyncMock(return_value=[refreshed_row]),
    ):
        status = await CommandService.get_command_status("command:1")

    assert status["status"] == "failed"
    assert status["error_message"] == "Model is not a LanguageModel"


@pytest.mark.asyncio
async def test_list_command_jobs_source_only_skips_orphan_reconciliation():
    command_rows = [
        {
            "id": "command:orphan",
            "app": "open_notebook",
            "name": "process_source",
            "status": "new",
            "result": None,
            "error_message": None,
            "created": datetime.now(timezone.utc),
            "updated": datetime.now(timezone.utc),
            "progress": None,
        }
    ]

    with patch(
        "api.command_service.repo_query",
        new=AsyncMock(side_effect=[command_rows, []]),
    ), patch.object(
        CommandService,
        "_reconcile_command_record",
        new=AsyncMock(side_effect=AssertionError("should not reconcile orphan job")),
    ):
        jobs = await CommandService.list_command_jobs(source_only=True, limit=10)

    assert jobs == []
