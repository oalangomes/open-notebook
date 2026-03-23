from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from loguru import logger
from surreal_commands import submit_command

from open_notebook.database.repository import ensure_record_id, repo_query, repo_update
from open_notebook.exceptions import InvalidInputError, NotFoundError


SOURCE_QUEUE_FETCH_LIMIT_CAP = 500
ACTIVE_COMMAND_STATUSES = {"new", "queued", "running"}
COMMAND_STALE_AFTER = timedelta(minutes=15)


class CommandService:
    """Generic service layer for command operations"""

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    @staticmethod
    def _build_status_payload(command: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "job_id": str(command.get("id")),
            "status": command.get("status", "unknown"),
            "result": command.get("result"),
            "error_message": command.get("error_message"),
            "created": str(command.get("created")) if command.get("created") else None,
            "updated": str(command.get("updated")) if command.get("updated") else None,
            "progress": command.get("progress"),
        }

    @staticmethod
    async def _mark_command_failed(job_id: str, error_message: str) -> Dict[str, Any]:
        await repo_update(
            "command",
            job_id,
            {
                "status": "failed",
                "error_message": error_message,
            },
        )
        refreshed = await repo_query("SELECT * FROM $id", {"id": ensure_record_id(job_id)})
        if not refreshed:
            return {
                "id": job_id,
                "status": "failed",
                "error_message": error_message,
                "result": None,
                "created": None,
                "updated": datetime.now(timezone.utc).isoformat(),
                "progress": None,
            }
        return refreshed[0]

    @staticmethod
    async def _reconcile_command_record(command: Dict[str, Any]) -> Dict[str, Any]:
        job_id = str(command.get("id"))
        status = command.get("status", "unknown")
        result = command.get("result")
        error_message = command.get("error_message")

        if status == "completed" and isinstance(result, dict) and result.get("success") is False:
            derived_error = (
                result.get("error_message")
                or error_message
                or "Command completed with success=false"
            )
            logger.warning(
                "Marking command {} as failed because result.success=false: {}",
                job_id,
                derived_error,
            )
            return await CommandService._mark_command_failed(job_id, str(derived_error))

        if status in ACTIVE_COMMAND_STATUSES:
            updated_at = CommandService._parse_datetime(command.get("updated"))
            created_at = CommandService._parse_datetime(command.get("created"))
            reference_time = updated_at or created_at
            if reference_time and datetime.now(timezone.utc) - reference_time > COMMAND_STALE_AFTER:
                timeout_minutes = int(COMMAND_STALE_AFTER.total_seconds() // 60)
                timeout_message = (
                    f"Command exceeded {timeout_minutes} minutes without status change "
                    "and was marked as failed"
                )
                logger.warning("Marking stale command {} as failed: {}", job_id, timeout_message)
                return await CommandService._mark_command_failed(job_id, timeout_message)

        return command

    @staticmethod
    async def submit_command_job(
        module_name: str,  # Actually app_name for surreal-commands
        command_name: str,
        command_args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Submit a generic command job for background processing"""
        try:
            # Ensure command modules are imported before submitting
            # This is needed because submit_command validates against local registry
            try:
                import commands.podcast_commands  # noqa: F401
            except ImportError as import_err:
                logger.error(f"Failed to import command modules: {import_err}")
                raise ValueError("Command modules not available")

            # surreal-commands expects: submit_command(app_name, command_name, args)
            cmd_id = submit_command(
                module_name,  # This is actually the app name (e.g., "open_notebook")
                command_name,  # Command name (e.g., "process_text")
                command_args,  # Input data
            )
            # Convert RecordID to string if needed
            if not cmd_id:
                raise ValueError("Failed to get cmd_id from submit_command")
            cmd_id_str = str(cmd_id)
            logger.info(
                f"Submitted command job: {cmd_id_str} for {module_name}.{command_name}"
            )
            return cmd_id_str

        except Exception as e:
            logger.error(f"Failed to submit command job: {e}")
            raise

    @staticmethod
    async def get_command_status(job_id: str) -> Dict[str, Any]:
        """Get status of any command job"""
        try:
            result = await repo_query("SELECT * FROM $id", {"id": ensure_record_id(job_id)})
            if not result:
                raise NotFoundError(f"Command job {job_id} not found")
            command = await CommandService._reconcile_command_record(result[0])
            return CommandService._build_status_payload(command)
        except Exception as e:
            logger.error(f"Failed to get command status: {e}")
            raise

    @staticmethod
    async def list_command_jobs(
        module_filter: Optional[str] = None,
        command_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        limit: int = 50,
        source_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """List command jobs with optional filtering"""
        try:
            safe_limit = max(1, min(limit, SOURCE_QUEUE_FETCH_LIMIT_CAP))

            command_fetch_limit = safe_limit
            if source_only:
                command_fetch_limit = min(
                    max(safe_limit * 10, 200), SOURCE_QUEUE_FETCH_LIMIT_CAP
                )

            commands = await repo_query(
                "SELECT * FROM command ORDER BY created DESC LIMIT $limit",
                {"limit": command_fetch_limit},
            )

            source_map: Dict[str, Dict[str, Any]] = {}
            if source_only:
                sources = await repo_query(
                    "SELECT id, title, asset, command FROM source WHERE command != NONE"
                )
                source_map = {
                    str(source["command"]): source
                    for source in sources
                    if source.get("command")
                }

            jobs: List[Dict[str, Any]] = []
            for command in commands:
                job_id = str(command.get("id"))
                source = source_map.get(job_id)
                if source_only and source is None:
                    continue

                command = await CommandService._reconcile_command_record(command)
                if module_filter and command.get("app") != module_filter:
                    continue
                if command_filter and command.get("name") != command_filter:
                    continue
                if status_filter and command.get("status") != status_filter:
                    continue

                asset = source.get("asset") if source else None
                jobs.append(
                    {
                        "job_id": job_id,
                        "app": command.get("app"),
                        "command": command.get("name"),
                        "status": command.get("status", "unknown"),
                        "result": command.get("result"),
                        "error_message": command.get("error_message"),
                        "created": str(command.get("created"))
                        if command.get("created")
                        else None,
                        "updated": str(command.get("updated"))
                        if command.get("updated")
                        else None,
                        "progress": command.get("progress"),
                        "source_id": source.get("id") if source else None,
                        "source_title": source.get("title") if source else None,
                        "source_path": asset.get("file_path")
                        if isinstance(asset, dict)
                        else None,
                        "source_url": asset.get("url")
                        if isinstance(asset, dict)
                        else None,
                        "can_cancel": command.get("status") == "new",
                    }
                )

                if len(jobs) >= safe_limit:
                    break

            return jobs
        except Exception as e:
            logger.error(f"Failed to list command jobs: {e}")
            raise

    @staticmethod
    async def cancel_command_job(job_id: str) -> bool:
        """Cancel a running command job"""
        try:
            command = await repo_query(
                "SELECT * FROM $id", {"id": ensure_record_id(job_id)}
            )
            if not command:
                raise NotFoundError(f"Command job {job_id} not found")

            status = command[0].get("status")
            if status == "canceled":
                return True
            if status != "new":
                raise InvalidInputError(
                    "Only queued source jobs can be cancelled before execution starts"
                )

            await repo_update(
                "command",
                job_id,
                {
                    "status": "canceled",
                    "error_message": "Cancelled by user before execution",
                },
            )

            logger.info(f"Cancelled queued job: {job_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel command job: {e}")
            raise
