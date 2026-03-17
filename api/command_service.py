from typing import Any, Dict, List, Optional

from loguru import logger
from surreal_commands import get_command_status, submit_command

from open_notebook.database.repository import ensure_record_id, repo_query, repo_update
from open_notebook.exceptions import InvalidInputError, NotFoundError


SOURCE_QUEUE_FETCH_LIMIT_CAP = 500

class CommandService:
    """Generic service layer for command operations"""

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
            status = await get_command_status(job_id)
            return {
                "job_id": job_id,
                "status": status.status if status else "unknown",
                "result": status.result if status else None,
                "error_message": getattr(status, "error_message", None)
                if status
                else None,
                "created": str(status.created)
                if status and hasattr(status, "created") and status.created
                else None,
                "updated": str(status.updated)
                if status and hasattr(status, "updated") and status.updated
                else None,
                "progress": getattr(status, "progress", None) if status else None,
            }
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
                if module_filter and command.get("app") != module_filter:
                    continue
                if command_filter and command.get("name") != command_filter:
                    continue
                if status_filter and command.get("status") != status_filter:
                    continue

                job_id = str(command.get("id"))
                source = source_map.get(job_id)
                if source_only and source is None:
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
