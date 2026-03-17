import posixpath
import re
from collections import deque
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import List, Optional
from urllib.parse import unquote, urlparse

import httpx
from fastapi import HTTPException
from loguru import logger
from pydantic import SecretStr

from api.command_service import CommandService
from api.git_raw_client import (
    GitRawAuthError,
    GitRawClient,
    GitRawClientError,
    GitRawNotFoundError,
)
from api.models import (
    GitSyncCreateRequest,
    GitSyncFileStateResponse,
    GitSyncResponse,
    GitSyncRunResponse,
    GitSyncRunSummaryResponse,
    GitSyncUpdateRequest,
    normalize_github_repo_input,
)
from commands.source_commands import SourceProcessingInput
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.credential import Credential
from open_notebook.domain.git_sync import GitSync, GitSyncFileState, GitSyncRunSummary
from open_notebook.domain.notebook import Notebook, Source
from open_notebook.domain.transformation import Transformation


class GitSyncService:
    SUPPORTED_PROVIDERS = {"azure_devops", "github"}
    MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown", ".mkd"}
    DISCOVERABLE_EXTENSIONS = MARKDOWN_EXTENSIONS | {".puml", ".svg"}
    MARKDOWN_LINK_RE = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)]+)\)")
    MARKDOWN_IMAGE_RE = re.compile(r"\!\[[^\]]*\]\(([^)]+)\)")

    @staticmethod
    async def list_syncs() -> List[GitSyncResponse]:
        syncs = await GitSync.get_all(order_by="updated desc")
        return [GitSyncService.to_response(sync) for sync in syncs]

    @staticmethod
    async def get_sync(sync_id: str) -> GitSyncResponse:
        sync = await GitSync.get(sync_id)
        return GitSyncService.to_response(sync)

    @staticmethod
    async def create_sync(request: GitSyncCreateRequest) -> GitSyncResponse:
        await GitSyncService._validate_config(
            provider=request.provider,
            repo=request.repo,
            paths=request.paths,
            seed_paths=request.seed_paths,
            credential_id=request.credential_id,
            notebooks=request.notebooks,
            transformations=request.transformations,
        )

        sync = GitSync(
            provider=request.provider,
            repo=request.repo,
            branch=request.branch,
            paths=request.paths,
            seed_paths=request.seed_paths,
            max_discovery_depth=request.max_discovery_depth,
            max_discovery_files=request.max_discovery_files,
            credential_id=request.credential_id,
            notebooks=request.notebooks,
            transformations=request.transformations,
            embed=request.embed,
            refresh_interval=request.refresh_interval,
        )
        sync.sync_path_states(deactivate_missing=False)
        await sync.save()
        return GitSyncService.to_response(sync)

    @staticmethod
    async def update_sync(sync_id: str, request: GitSyncUpdateRequest) -> GitSyncResponse:
        sync = await GitSync.get(sync_id)

        provider = sync.provider
        credential_id = request.credential_id or sync.credential_id
        notebooks = request.notebooks if request.notebooks is not None else sync.notebooks
        transformations = (
            request.transformations
            if request.transformations is not None
            else sync.transformations
        )

        await GitSyncService._validate_config(
            provider=provider,
            repo=sync.repo,
            paths=request.paths if request.paths is not None else sync.paths,
            seed_paths=(
                request.seed_paths if request.seed_paths is not None else sync.seed_paths
            ),
            credential_id=credential_id,
            notebooks=notebooks,
            transformations=transformations,
        )

        if request.branch is not None:
            sync.branch = request.branch
        if request.paths is not None:
            sync.paths = request.paths
        if request.seed_paths is not None:
            sync.seed_paths = request.seed_paths
        if request.max_discovery_depth is not None:
            sync.max_discovery_depth = request.max_discovery_depth
        if request.max_discovery_files is not None:
            sync.max_discovery_files = request.max_discovery_files
        if request.credential_id is not None:
            sync.credential_id = request.credential_id
        if request.notebooks is not None:
            sync.notebooks = request.notebooks
        if request.transformations is not None:
            sync.transformations = request.transformations
        if request.embed is not None:
            sync.embed = request.embed
        if request.refresh_interval is not None:
            sync.refresh_interval = request.refresh_interval

        sync.sync_path_states(deactivate_missing=False)
        await sync.save()
        return GitSyncService.to_response(sync)

    @staticmethod
    async def run_sync(sync_id: str) -> GitSyncRunResponse:
        sync = await GitSync.get(sync_id)
        credential = await GitSyncService._get_valid_credential(
            provider=sync.provider,
            credential_id=sync.credential_id,
            repo=sync.repo,
        )
        client = GitSyncService._build_client(sync.provider, credential)
        effective_paths = await GitSyncService._resolve_sync_paths(sync, client)
        sync.sync_path_states(effective_paths)

        summary = GitSyncRunSummary(started_at=datetime.now(timezone.utc))

        for path in effective_paths:
            state = sync.upsert_file_state(path)
            state.active = True
            file_sync_time = datetime.now(timezone.utc)

            try:
                fetch_result = await client.fetch_text_file(
                    repo=sync.repo,
                    branch=sync.branch,
                    path=path,
                )
                state.raw_url = fetch_result.raw_url

                if state.content_hash == fetch_result.content_hash and state.source_id:
                    try:
                        existing_source = await Source.get(state.source_id)
                        await GitSyncService._ensure_source_title(
                            existing_source,
                            GitSyncService._build_source_title(path),
                        )
                        summary.skipped += 1
                        state.last_sync = file_sync_time
                        state.last_status = "skipped"
                        state.last_error = None
                        continue
                    except Exception:
                        logger.warning(
                            f"Source {state.source_id} missing for sync {sync.id} path={path}. "
                            "Recreating source record."
                        )

                source, created = await GitSyncService._resolve_source(sync, state)
                await GitSyncService._ensure_source_notebooks(source, sync.notebooks)
                command_id = await GitSyncService._submit_source_processing(
                    source=source,
                    sync=sync,
                    content=fetch_result.content,
                    raw_url=fetch_result.raw_url,
                    source_title=GitSyncService._build_source_title(path),
                )

                state.source_id = source.id
                state.content_hash = fetch_result.content_hash
                state.last_sync = file_sync_time
                state.last_status = "queued"
                state.last_error = None

                if created:
                    summary.created += 1
                else:
                    summary.updated += 1

                logger.info(
                    f"Queued git sync processing for {sync.id} path={path} command={command_id}"
                )
            except (GitRawAuthError, GitRawNotFoundError, GitRawClientError) as exc:
                summary.failed += 1
                state.last_sync = file_sync_time
                state.last_status = "failed"
                state.last_error = str(exc)
                logger.warning(f"Git sync file failed for {sync.id} path={path}: {exc}")
            except Exception as exc:
                summary.failed += 1
                state.last_sync = file_sync_time
                state.last_status = "failed"
                state.last_error = str(exc)
                logger.exception(exc)

        summary.completed_at = datetime.now(timezone.utc)
        sync.last_run_summary = summary
        sync.last_sync = summary.completed_at
        sync.last_status = "completed" if summary.failed == 0 else "completed_with_errors"
        sync.last_error = None if summary.failed == 0 else "One or more files failed to sync"
        sync.sync_path_states(effective_paths)
        await sync.save()

        return GitSyncRunResponse(
            sync_id=sync.id or "",
            summary=GitSyncService._summary_to_response(summary),
            file_states=[
                GitSyncService._file_state_to_response(state)
                for state in sync.file_states
            ],
        )

    @staticmethod
    async def _resolve_sync_paths(sync: GitSync, client: GitRawClient) -> List[str]:
        ordered_paths: dict[str, None] = {}

        for path in sync.paths:
            normalized = GitSyncService._normalize_repo_path(path)
            if normalized:
                ordered_paths[normalized] = None

        markdown_queue: deque[tuple[str, int]] = deque()
        visited_markdown: set[str] = set()

        for seed_path in sync.seed_paths:
            normalized_seed = GitSyncService._normalize_repo_path(seed_path)
            if not normalized_seed:
                continue
            ordered_paths[normalized_seed] = None
            if GitSyncService._is_markdown_path(normalized_seed):
                markdown_queue.append((normalized_seed, 0))

        while markdown_queue and len(ordered_paths) < sync.max_discovery_files:
            current_path, depth = markdown_queue.popleft()
            if current_path in visited_markdown:
                continue

            visited_markdown.add(current_path)

            try:
                fetch_result = await client.fetch_text_file(
                    repo=sync.repo,
                    branch=sync.branch,
                    path=current_path,
                )
            except (GitRawAuthError, GitRawNotFoundError, GitRawClientError) as exc:
                logger.warning(
                    f"Skipping discovery expansion for {sync.id} path={current_path}: {exc}"
                )
                continue

            for linked_path in GitSyncService._extract_discoverable_links(
                markdown_content=fetch_result.content,
                current_path=current_path,
            ):
                if linked_path in ordered_paths:
                    continue
                if len(ordered_paths) >= sync.max_discovery_files:
                    logger.warning(
                        f"Discovery file limit reached for sync {sync.id} "
                        f"(max_discovery_files={sync.max_discovery_files})"
                    )
                    break

                ordered_paths[linked_path] = None

                if (
                    depth < sync.max_discovery_depth
                    and GitSyncService._is_markdown_path(linked_path)
                ):
                    markdown_queue.append((linked_path, depth + 1))

        return list(ordered_paths.keys())

    @staticmethod
    def _extract_discoverable_links(
        markdown_content: str,
        current_path: str,
    ) -> List[str]:
        discovered: dict[str, None] = {}
        raw_targets = list(GitSyncService.MARKDOWN_LINK_RE.findall(markdown_content or ""))
        raw_targets.extend(GitSyncService.MARKDOWN_IMAGE_RE.findall(markdown_content or ""))
        for raw_target in raw_targets:
            normalized = GitSyncService._resolve_repo_link(current_path, raw_target)
            if normalized and GitSyncService._is_discoverable_path(normalized):
                discovered[normalized] = None
        return list(discovered.keys())

    @staticmethod
    def _resolve_repo_link(current_path: str, raw_target: str) -> Optional[str]:
        target = GitSyncService._coerce_link_target(raw_target)
        if not target:
            return None

        parsed = urlparse(target)
        if parsed.scheme or parsed.netloc:
            return None

        candidate = unquote(parsed.path or "").strip()
        if not candidate:
            return None
        if candidate.startswith("#") or candidate.startswith("mailto:"):
            return None

        base_dir = posixpath.dirname(current_path)
        if candidate.startswith("/"):
            normalized = posixpath.normpath(candidate.lstrip("/"))
        else:
            normalized = posixpath.normpath(posixpath.join(base_dir, candidate))

        if normalized in ("", ".") or normalized.startswith("../") or normalized == "..":
            return None
        return normalized.replace("\\", "/")

    @staticmethod
    def _coerce_link_target(raw_target: str) -> Optional[str]:
        target = raw_target.strip()
        if not target:
            return None

        if target.startswith("<"):
            closing = target.find(">")
            if closing > 0:
                return target[1:closing].strip()
            return target[1:].strip()

        return target.split(maxsplit=1)[0].strip()

    @staticmethod
    def _normalize_repo_path(path: str) -> Optional[str]:
        cleaned = path.strip()
        if not cleaned:
            return None

        normalized = posixpath.normpath(cleaned.lstrip("/"))
        if normalized in ("", ".") or normalized.startswith("../") or normalized == "..":
            return None
        return normalized.replace("\\", "/")

    @staticmethod
    def _is_markdown_path(path: str) -> bool:
        return PurePosixPath(path).suffix.lower() in GitSyncService.MARKDOWN_EXTENSIONS

    @staticmethod
    def _is_discoverable_path(path: str) -> bool:
        return PurePosixPath(path).suffix.lower() in GitSyncService.DISCOVERABLE_EXTENSIONS

    @staticmethod
    async def _validate_config(
        provider: str,
        repo: str,
        paths: List[str],
        seed_paths: List[str],
        credential_id: Optional[str],
        notebooks: List[str],
        transformations: List[str],
    ) -> None:
        if provider not in GitSyncService.SUPPORTED_PROVIDERS:
            raise HTTPException(status_code=400, detail=f"Unsupported Git provider: {provider}")
        if not paths and not seed_paths:
            raise HTTPException(
                status_code=400,
                detail="At least one explicit path or seed_path must be provided",
            )

        await GitSyncService._get_valid_credential(
            provider=provider,
            credential_id=credential_id,
            repo=repo,
            require_access_validation=True,
        )

        for notebook_id in notebooks:
            try:
                await Notebook.get(notebook_id)
            except Exception:
                raise HTTPException(
                    status_code=404, detail=f"Notebook {notebook_id} not found"
                )

        for transformation_id in transformations:
            try:
                await Transformation.get(transformation_id)
            except Exception:
                raise HTTPException(
                    status_code=404,
                    detail=f"Transformation {transformation_id} not found",
                )

    @staticmethod
    async def _get_valid_credential(
        provider: str,
        credential_id: Optional[str],
        repo: Optional[str] = None,
        require_access_validation: bool = False,
    ) -> Optional[Credential]:
        if provider == "github" and not credential_id:
            if require_access_validation and repo:
                await GitSyncService._ensure_github_repo_is_public(repo)
            return None

        if not credential_id:
            raise HTTPException(status_code=400, detail="Credential is required for Git sync")

        try:
            credential = await Credential.get(credential_id)
        except Exception as exc:
            raise HTTPException(status_code=404, detail="Credential not found") from exc
        if credential.provider.lower() != provider.lower():
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Credential provider '{credential.provider}' is incompatible with sync "
                    f"provider '{provider}'"
                ),
            )
        if not credential.api_key or not credential.api_key.get_secret_value().strip():
            raise HTTPException(
                status_code=400,
                detail="Credential does not contain a PAT for Git sync",
            )
        if provider == "azure_devops" and (
            not credential.base_url or not credential.base_url.strip()
        ):
            raise HTTPException(
                status_code=400,
                detail="Credential must define base_url for Azure DevOps RAW access",
            )
        return credential

    @staticmethod
    def _build_client(provider: str, credential: Optional[Credential]) -> GitRawClient:
        token = ""
        base_url = ""
        if credential and credential.api_key:
            token = (
                credential.api_key.get_secret_value()
                if isinstance(credential.api_key, SecretStr)
                else str(credential.api_key)
            )
        if credential and credential.base_url:
            base_url = credential.base_url
        return GitRawClient(
            provider=provider,
            base_url=base_url,
            pat=token,
        )

    @staticmethod
    async def _ensure_github_repo_is_public(repo: str) -> None:
        repo_part = normalize_github_repo_input(repo).strip("/")
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                response = await client.get(f"https://api.github.com/repos/{repo_part}")
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail="Unable to validate GitHub repository visibility",
            ) from exc

        if response.status_code == 200:
            return
        if response.status_code == 404:
            raise HTTPException(
                status_code=400,
                detail="GitHub repository is private or not found; credential_id is required",
            )
        raise HTTPException(
            status_code=400,
            detail=f"Unable to validate GitHub repository visibility (status {response.status_code})",
        )

    @staticmethod
    async def _resolve_source(sync: GitSync, state: GitSyncFileState) -> tuple[Source, bool]:
        source_title = GitSyncService._build_source_title(state.path)
        if state.source_id:
            try:
                source = await Source.get(state.source_id)
                await GitSyncService._ensure_source_title(source, source_title)
                return source, False
            except Exception:
                logger.warning(
                    f"Source {state.source_id} referenced by sync {sync.id} was not found. "
                    "Creating a new source."
                )

        source = Source(title=source_title, topics=[])
        await source.save()
        return source, True

    @staticmethod
    async def _ensure_source_title(source: Source, title: str) -> None:
        if source.title == title:
            return

        source.title = title
        await source.save()

    @staticmethod
    def _build_source_title(path: str) -> str:
        normalized_path = GitSyncService._normalize_repo_path(path)
        return normalized_path or PurePosixPath(path).name

    @staticmethod
    async def _ensure_source_notebooks(source: Source, notebook_ids: List[str]) -> None:
        if not source.id or not notebook_ids:
            return

        existing_query = await repo_query(
            "SELECT VALUE out FROM reference WHERE in = $source_id",
            {"source_id": ensure_record_id(source.id)},
        )
        existing = {str(record_id) for record_id in existing_query} if existing_query else set()

        for notebook_id in notebook_ids:
            if notebook_id not in existing:
                await source.add_to_notebook(notebook_id)

    @staticmethod
    async def _submit_source_processing(
        source: Source, sync: GitSync, content: str, raw_url: str, source_title: str
    ) -> str:
        import commands.source_commands  # noqa: F401

        command_input = SourceProcessingInput(
            source_id=str(source.id),
            content_state={"content": content, "url": raw_url, "title": source_title},
            notebook_ids=sync.notebooks,
            transformations=sync.transformations,
            embed=sync.embed,
        )
        command_id = await CommandService.submit_command_job(
            "open_notebook",
            "process_source",
            command_input.model_dump(),
        )
        source.command = ensure_record_id(command_id)
        await source.save()
        return command_id

    @staticmethod
    def to_response(sync: GitSync) -> GitSyncResponse:
        return GitSyncResponse(
            id=sync.id or "",
            provider=sync.provider,
            repo=sync.repo,
            branch=sync.branch,
            paths=sync.paths,
            seed_paths=sync.seed_paths,
            max_discovery_depth=sync.max_discovery_depth,
            max_discovery_files=sync.max_discovery_files,
            credential_id=sync.credential_id,
            notebooks=sync.notebooks,
            transformations=sync.transformations,
            embed=sync.embed,
            refresh_interval=sync.refresh_interval,
            last_sync=sync.last_sync.isoformat() if sync.last_sync else None,
            last_status=sync.last_status,
            last_error=sync.last_error,
            last_run_summary=GitSyncService._summary_to_response(sync.last_run_summary)
            if sync.last_run_summary
            else None,
            file_states=[
                GitSyncService._file_state_to_response(state)
                for state in sync.file_states
            ],
            created=str(sync.created),
            updated=str(sync.updated),
        )

    @staticmethod
    def _summary_to_response(
        summary: GitSyncRunSummary,
    ) -> GitSyncRunSummaryResponse:
        return GitSyncRunSummaryResponse(
            created=summary.created,
            updated=summary.updated,
            skipped=summary.skipped,
            failed=summary.failed,
            started_at=summary.started_at.isoformat() if summary.started_at else None,
            completed_at=summary.completed_at.isoformat() if summary.completed_at else None,
        )

    @staticmethod
    def _file_state_to_response(
        state: GitSyncFileState,
    ) -> GitSyncFileStateResponse:
        return GitSyncFileStateResponse(
            path=state.path,
            raw_url=state.raw_url,
            source_id=state.source_id,
            content_hash=state.content_hash,
            last_sync=state.last_sync.isoformat() if state.last_sync else None,
            last_status=state.last_status,
            last_error=state.last_error,
            active=state.active,
        )
