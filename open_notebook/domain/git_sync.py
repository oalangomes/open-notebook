from datetime import datetime
from typing import Any, ClassVar, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from open_notebook.domain.base import ObjectModel


class GitSyncFileState(BaseModel):
    path: str
    raw_url: Optional[str] = None
    source_id: Optional[str] = None
    content_hash: Optional[str] = None
    last_sync: Optional[datetime] = None
    last_status: Optional[str] = None
    last_error: Optional[str] = None
    active: bool = True

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Path cannot be empty")
        return cleaned


class GitSyncRunSummary(BaseModel):
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class GitSync(ObjectModel):
    table_name: ClassVar[str] = "git_sync"
    nullable_fields: ClassVar[set[str]] = {
        "credential_id",
        "refresh_interval",
        "last_sync",
        "last_status",
        "last_error",
        "last_run_summary",
    }

    provider: str
    repo: str
    branch: str
    paths: List[str] = Field(default_factory=list)
    seed_paths: List[str] = Field(default_factory=list)
    max_discovery_depth: int = 2
    max_discovery_files: int = 200
    credential_id: Optional[str] = None
    notebooks: List[str] = Field(default_factory=list)
    transformations: List[str] = Field(default_factory=list)
    embed: bool = False
    refresh_interval: Optional[str] = None
    file_states: List[GitSyncFileState] = Field(default_factory=list)
    last_sync: Optional[datetime] = None
    last_status: Optional[str] = None
    last_error: Optional[str] = None
    last_run_summary: Optional[GitSyncRunSummary] = None

    @field_validator("provider", "repo", "branch", mode="before")
    @classmethod
    def normalize_required_strings(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field cannot be empty")
        return cleaned

    @field_validator("credential_id", mode="before")
    @classmethod
    def normalize_optional_credential_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("paths", "seed_paths", mode="before")
    @classmethod
    def normalize_paths(cls, value: List[str]) -> List[str]:
        normalized = []
        for item in value or []:
            cleaned = item.strip()
            if not cleaned:
                raise ValueError("Paths cannot contain empty values")
            normalized.append(cleaned)
        return normalized

    @field_validator("max_discovery_depth", mode="before")
    @classmethod
    def normalize_max_discovery_depth(cls, value: Optional[int]) -> int:
        if value is None:
            return 2
        return int(value)

    @field_validator("max_discovery_files", mode="before")
    @classmethod
    def normalize_max_discovery_files(cls, value: Optional[int]) -> int:
        if value is None:
            return 200
        return int(value)

    @field_validator("file_states", mode="before")
    @classmethod
    def normalize_file_states(
        cls, value: Optional[List[GitSyncFileState | Dict[str, Any]]]
    ) -> List[GitSyncFileState]:
        normalized: List[GitSyncFileState] = []
        for item in value or []:
            if isinstance(item, GitSyncFileState):
                normalized.append(item)
            else:
                normalized.append(GitSyncFileState(**item))
        return normalized

    @field_validator("last_run_summary", mode="before")
    @classmethod
    def normalize_last_run_summary(
        cls, value: Optional[GitSyncRunSummary | Dict[str, Any]]
    ) -> Optional[GitSyncRunSummary]:
        if value is None or isinstance(value, GitSyncRunSummary):
            return value
        return GitSyncRunSummary(**value)

    def hydrate_nested_models(self) -> None:
        self.file_states = self.normalize_file_states(self.file_states)
        self.last_run_summary = self.normalize_last_run_summary(self.last_run_summary)

    async def save(self) -> None:
        self.hydrate_nested_models()
        await super().save()
        self.hydrate_nested_models()

    def get_file_state(self, path: str) -> Optional[GitSyncFileState]:
        self.hydrate_nested_models()
        for state in self.file_states:
            if state.path == path:
                return state
        return None

    def upsert_file_state(self, path: str) -> GitSyncFileState:
        state = self.get_file_state(path)
        if state is not None:
            state.active = True
            return state

        state = GitSyncFileState(path=path)
        self.file_states.append(state)
        return state

    def sync_path_states(
        self, active_paths: Optional[List[str]] = None, deactivate_missing: bool = True
    ) -> None:
        self.hydrate_nested_models()
        configured_paths = list(active_paths) if active_paths is not None else list(
            dict.fromkeys([*self.paths, *self.seed_paths])
        )
        current_paths = set(configured_paths)
        for state in self.file_states:
            if state.path in current_paths:
                state.active = True
                if state.last_status == "inactive":
                    state.last_status = None
                    state.last_error = None
            elif deactivate_missing:
                state.active = False
                state.last_status = "inactive"
                state.last_error = None

        existing_paths = {state.path for state in self.file_states}
        for path in configured_paths:
            if path not in existing_paths:
                self.file_states.append(GitSyncFileState(path=path, active=True))

    def _prepare_save_data(self) -> Dict[str, Any]:
        self.hydrate_nested_models()
        data = super()._prepare_save_data()
        if self.last_run_summary is not None:
            data["last_run_summary"] = self.last_run_summary.model_dump()
        if self.file_states:
            data["file_states"] = [state.model_dump() for state in self.file_states]
        return data
