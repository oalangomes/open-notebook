from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from api.git_raw_client import GitRawClient, GitRawNotFoundError, RawFetchResult
from api.git_sync_service import GitSyncService
from api.models import GitSyncCreateRequest
from open_notebook.domain.credential import Credential
from open_notebook.domain.git_sync import GitSync, GitSyncFileState
from open_notebook.domain.notebook import Asset, Source


class TestGitRawClient:
    def test_build_raw_url_and_headers_for_azure_devops(self):
        client = GitRawClient(
            provider="azure_devops",
            base_url="https://dev.azure.com/example/project",
            pat="secret-token",
        )

        raw_url = client.build_raw_url(
            repo="My Repo",
            branch="main",
            path="docs/readme.md",
        )
        headers = client.build_headers()

        assert "repositories/My%20Repo/items" in raw_url
        assert "versionDescriptor.version=main" in raw_url
        assert "path=/docs/readme.md" in raw_url
        assert headers["Authorization"].startswith("Basic ")
        assert headers["Accept"] == "application/json"

    def test_build_raw_url_and_headers_for_public_github(self):
        client = GitRawClient(
            provider="github",
            base_url="",
            pat="",
        )

        raw_url = client.build_raw_url(
            repo="openai/openai-python",
            branch="main",
            path="README.md",
        )
        headers = client.build_headers()

        assert (
            raw_url
            == "https://raw.githubusercontent.com/openai/openai-python/main/README.md"
        )
        assert headers["Accept"] == "application/vnd.github.raw"
        assert "Authorization" not in headers

    def test_build_raw_url_and_headers_for_private_github(self):
        client = GitRawClient(
            provider="github",
            base_url="",
            pat="secret-token",
        )

        raw_url = client.build_raw_url(
            repo="owner/repo",
            branch="main",
            path="docs/readme.md",
        )
        headers = client.build_headers()

        assert raw_url == "https://api.github.com/repos/owner/repo/contents/docs/readme.md?ref=main"
        assert headers["Authorization"] == "Bearer secret-token"
        assert headers["Accept"] == "application/vnd.github.raw"


class TestGitSyncModels:
    def test_git_sync_create_request_normalizes_paths(self):
        request = GitSyncCreateRequest(
            provider="azure_devops",
            repo="repo",
            branch="main",
            paths=[" docs/a.md ", "docs/b.md"],
            credential_id="credential:1",
        )

        assert request.paths == ["docs/a.md", "docs/b.md"]

    def test_git_sync_create_request_accepts_public_github_without_credential(self):
        request = GitSyncCreateRequest(
            provider="github",
            repo="owner/repo",
            branch="main",
            paths=["docs/a.md"],
        )

        assert request.credential_id is None

    def test_git_sync_create_request_accepts_seed_paths_without_explicit_paths(self):
        request = GitSyncCreateRequest(
            provider="github",
            repo="owner/repo",
            branch="main",
            seed_paths=["README.md"],
        )

        assert request.paths == []
        assert request.seed_paths == ["README.md"]

    def test_git_sync_create_request_accepts_github_repo_url(self):
        request = GitSyncCreateRequest(
            provider="github",
            repo="https://github.com/openai/openai-python.git",
            branch="main",
            paths=["README.md"],
        )

        assert request.repo == "openai/openai-python"

    def test_git_sync_create_request_rejects_invalid_github_repo(self):
        with pytest.raises(ValueError):
            GitSyncCreateRequest(
                provider="github",
                repo="owner-only",
                branch="main",
                paths=["docs/a.md"],
            )

    def test_git_sync_domain_allows_missing_credential_id_for_public_github(self):
        sync = GitSync(
            provider="github",
            repo="openai/openai-python",
            branch="main",
            paths=["README.md"],
            credential_id=None,
        )

        assert sync.credential_id is None

    @pytest.mark.asyncio
    async def test_git_sync_save_rehydrates_file_states_from_dicts(self):
        sync = GitSync(
            provider="github",
            repo="openai/openai-python",
            branch="main",
            paths=["README.md"],
            credential_id=None,
            file_states=[GitSyncFileState(path="README.md")],
        )

        with patch(
            "open_notebook.domain.base.repo_create",
            new=AsyncMock(
                return_value=[
                    {
                        "id": "git_sync:1",
                        "provider": "github",
                        "repo": "openai/openai-python",
                        "branch": "main",
                        "paths": ["README.md"],
                        "credential_id": None,
                        "file_states": [
                            {
                                "path": "README.md",
                                "active": True,
                            }
                        ],
                    }
                ]
            ),
        ):
            await sync.save()

        assert isinstance(sync.file_states[0], GitSyncFileState)
        assert sync.file_states[0].path == "README.md"


class TestGitSyncService:
    def test_extract_discoverable_links_from_markdown(self):
        content = """
        [Guide](docs/guide.md)
        [Sequence](./diagrams/flow.puml)
        ![Local image](./images/logo.svg)
        [SVG](../assets/diagram.svg)
        [External](https://example.com/doc.md)
        [Anchor](#section)
        """

        links = GitSyncService._extract_discoverable_links(
            markdown_content=content,
            current_path="README.md",
        )

        assert links == [
            "docs/guide.md",
            "diagrams/flow.puml",
            "images/logo.svg",
            "assets/diagram.svg",
        ]

    @pytest.mark.asyncio
    async def test_get_valid_credential_rejects_incompatible_provider(self):
        credential = Credential(
            id="credential:1",
            name="Test",
            provider="openai",
            modalities=["language"],
        )

        with patch(
            "api.git_sync_service.Credential.get", new=AsyncMock(return_value=credential)
        ):
            with pytest.raises(HTTPException) as exc:
                await GitSyncService._get_valid_credential(
                    provider="azure_devops",
                    credential_id="credential:1",
                )

        assert exc.value.status_code == 400
        assert "incompatible" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_get_valid_credential_allows_public_github_without_credential(self):
        with patch.object(
            GitSyncService,
            "_ensure_github_repo_is_public",
            new=AsyncMock(return_value=None),
        ):
            credential = await GitSyncService._get_valid_credential(
                provider="github",
                credential_id=None,
                repo="owner/repo",
                require_access_validation=True,
            )

        assert credential is None

    @pytest.mark.asyncio
    async def test_get_valid_credential_rejects_private_github_without_credential(self):
        with patch.object(
            GitSyncService,
            "_ensure_github_repo_is_public",
            new=AsyncMock(
                side_effect=HTTPException(
                    status_code=400,
                    detail="GitHub repository is private or not found; credential_id is required",
                )
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await GitSyncService._get_valid_credential(
                    provider="github",
                    credential_id=None,
                    repo="owner/private-repo",
                    require_access_validation=True,
                )

        assert exc.value.status_code == 400
        assert "credential_id is required" in str(exc.value.detail)

    @pytest.mark.asyncio
    async def test_preview_sync_returns_source_metadata_for_discovered_files(self):
        request = GitSyncCreateRequest(
            provider="github",
            repo="owner/repo",
            branch="main",
            paths=["docs/guide.md"],
            seed_paths=["README.md"],
            credential_id=None,
        )
        client = AsyncMock()
        client.fetch_text_file = AsyncMock(
            return_value=RawFetchResult(
                raw_url="https://raw/readme",
                content="[Flow](docs/flow.puml)\n![Architecture](assets/system.svg)",
                content_hash="hash-readme",
            )
        )

        with patch.object(
            GitSyncService,
            "_validate_discovery_config",
            new=AsyncMock(return_value=None),
        ), patch.object(
            GitSyncService,
            "_get_valid_credential",
            new=AsyncMock(return_value=None),
        ), patch.object(
            GitSyncService, "_build_client", return_value=client
        ):
            response = await GitSyncService.preview_sync(request)

        assert [item.path for item in response.items] == [
            "docs/guide.md",
            "README.md",
            "docs/flow.puml",
            "assets/system.svg",
        ]
        assert response.items[0].source_type == "explicit"
        assert response.items[1].source_type == "seed"
        assert response.items[2].source_type == "discovered"
        assert response.items[2].discovered_from == "README.md"
        assert response.items[2].file_type == "puml"
        assert response.items[3].file_type == "svg"

    @pytest.mark.asyncio
    async def test_resolve_source_uses_repo_path_as_title(self):
        sync = GitSync(
            id="git_sync:resolve",
            provider="github",
            repo="owner/repo",
            branch="main",
            paths=["docs/guide.md"],
            credential_id=None,
        )
        state = GitSyncFileState(path="docs/guide.md")

        with patch("open_notebook.domain.notebook.Source.save", new=AsyncMock(return_value=None)):
            source, created = await GitSyncService._resolve_source(sync, state)

        assert created is True
        assert source.title == "docs/guide.md"

    @pytest.mark.asyncio
    async def test_run_sync_reports_created_and_skipped_files(self):
        sync = GitSync(
            id="git_sync:1",
            provider="azure_devops",
            repo="repo",
            branch="main",
            paths=["docs/new.md", "docs/skip.md"],
            credential_id="credential:1",
            notebooks=["notebook:1"],
            transformations=["transformation:1"],
            embed=True,
            file_states=[
                GitSyncFileState(
                    path="docs/skip.md",
                    source_id="source:skip",
                    content_hash="same-hash",
                    active=True,
                )
            ],
        )
        sync.sync_path_states()

        credential = Credential(
            id="credential:1",
            name="ADO",
            provider="azure_devops",
            modalities=["source_sync"],
            api_key=SecretStr("secret"),
            base_url="https://dev.azure.com/example/project",
        )
        client = AsyncMock()
        client.fetch_text_file = AsyncMock(
            side_effect=[
                RawFetchResult(
                    raw_url="https://raw/new",
                    content="# new",
                    content_hash="new-hash",
                ),
                RawFetchResult(
                    raw_url="https://raw/skip",
                    content="# skip",
                    content_hash="same-hash",
                ),
            ]
        )
        created_source = Source(id="source:new", title="new.md")
        existing_source = Source(
            id="source:skip",
            title="skip.md",
            full_text="# skip",
            asset=Asset(url="https://raw/skip", file_path="docs/skip.md"),
        )

        with patch.object(GitSync, "get", new=AsyncMock(return_value=sync)), patch.object(
            GitSync, "save", new=AsyncMock(return_value=None)
        ), patch.object(
            GitSyncService,
            "_get_valid_credential",
            new=AsyncMock(return_value=credential),
        ), patch.object(
            GitSyncService, "_build_client", return_value=client
        ), patch.object(
            GitSyncService,
            "_resolve_source",
            new=AsyncMock(return_value=(created_source, True)),
        ) as mock_resolve, patch.object(
            GitSyncService,
            "_ensure_source_notebooks",
            new=AsyncMock(return_value=None),
        ), patch.object(
            GitSyncService,
            "_submit_source_processing",
            new=AsyncMock(return_value="command:1"),
        ) as mock_submit, patch(
            "api.git_sync_service.Source.get",
            new=AsyncMock(return_value=existing_source),
        ):
            response = await GitSyncService.run_sync("git_sync:1")

        assert response.summary.created == 1
        assert response.summary.repaired == 0
        assert response.summary.skipped == 1
        assert response.summary.failed == 0
        assert mock_resolve.await_count == 1
        file_states = {state.path: state for state in response.file_states}
        assert file_states["docs/new.md"].source_id == "source:new"
        assert file_states["docs/new.md"].last_status == "queued"
        assert file_states["docs/skip.md"].last_status == "skipped"
        assert existing_source.title == "docs/skip.md"
        assert mock_submit.await_args.kwargs["source_title"] == "docs/new.md"
        assert mock_submit.await_args.kwargs["file_path"] == "docs/new.md"

    @pytest.mark.asyncio
    async def test_run_sync_persists_content_before_processing(self):
        sync = GitSync(
            id="git_sync:persist",
            provider="github",
            repo="owner/repo",
            branch="main",
            paths=["docs/guide.md"],
            credential_id=None,
            notebooks=[],
            transformations=[],
            embed=False,
        )
        sync.sync_path_states()

        client = AsyncMock()
        client.fetch_text_file = AsyncMock(
            return_value=RawFetchResult(
                raw_url="https://raw/guide",
                content="# Guide",
                content_hash="hash-guide",
            )
        )
        source = Source(id="source:guide", title="guide.md")

        with patch.object(GitSync, "get", new=AsyncMock(return_value=sync)), patch.object(
            GitSync, "save", new=AsyncMock(return_value=None)
        ), patch.object(
            GitSyncService,
            "_get_valid_credential",
            new=AsyncMock(return_value=None),
        ), patch.object(
            GitSyncService, "_build_client", return_value=client
        ), patch.object(
            GitSyncService,
            "_resolve_source",
            new=AsyncMock(return_value=(source, True)),
        ), patch.object(
            GitSyncService,
            "_ensure_source_notebooks",
            new=AsyncMock(return_value=None),
        ), patch.object(
            GitSyncService,
            "_submit_source_processing",
            new=AsyncMock(return_value="command:guide"),
        ), patch(
            "open_notebook.domain.notebook.Source.save",
            new=AsyncMock(return_value=None),
        ):
            response = await GitSyncService.run_sync("git_sync:persist")

        assert response.summary.created == 1
        assert source.title == "docs/guide.md"
        assert source.full_text == "# Guide"
        assert source.asset is not None
        assert source.asset.url == "https://raw/guide"
        assert source.asset.file_path == "docs/guide.md"

    @pytest.mark.asyncio
    async def test_run_sync_repairs_empty_source_when_hash_unchanged(self):
        sync = GitSync(
            id="git_sync:repair",
            provider="github",
            repo="owner/repo",
            branch="main",
            paths=["docs/guide.md"],
            credential_id=None,
            notebooks=[],
            transformations=[],
            embed=False,
            file_states=[
                GitSyncFileState(
                    path="docs/guide.md",
                    source_id="source:guide",
                    content_hash="hash-guide",
                    active=True,
                )
            ],
        )
        sync.sync_path_states()

        client = AsyncMock()
        client.fetch_text_file = AsyncMock(
            return_value=RawFetchResult(
                raw_url="https://raw/guide",
                content="# Guide",
                content_hash="hash-guide",
            )
        )
        existing_source = Source(id="source:guide", title="guide.md", full_text=None, asset=None)

        with patch.object(GitSync, "get", new=AsyncMock(return_value=sync)), patch.object(
            GitSync, "save", new=AsyncMock(return_value=None)
        ), patch.object(
            GitSyncService,
            "_get_valid_credential",
            new=AsyncMock(return_value=None),
        ), patch.object(
            GitSyncService, "_build_client", return_value=client
        ), patch.object(
            GitSyncService,
            "_ensure_source_notebooks",
            new=AsyncMock(return_value=None),
        ), patch.object(
            GitSyncService,
            "_submit_source_processing",
            new=AsyncMock(return_value="command:repair"),
        ) as mock_submit, patch(
            "api.git_sync_service.Source.get",
            new=AsyncMock(return_value=existing_source),
        ), patch(
            "open_notebook.domain.notebook.Source.save",
            new=AsyncMock(return_value=None),
        ):
            response = await GitSyncService.run_sync("git_sync:repair")

        assert response.summary.created == 0
        assert response.summary.updated == 0
        assert response.summary.repaired == 1
        assert response.summary.skipped == 0
        assert existing_source.full_text == "# Guide"
        assert existing_source.asset is not None
        assert existing_source.asset.file_path == "docs/guide.md"
        assert response.file_states[0].last_status == "queued"
        assert mock_submit.await_args.kwargs["file_path"] == "docs/guide.md"

    @pytest.mark.asyncio
    async def test_run_sync_uses_confirmed_paths_without_rediscovery(self):
        sync = GitSync(
            id="git_sync:confirmed",
            provider="github",
            repo="owner/repo",
            branch="main",
            paths=["README.md"],
            seed_paths=["README.md"],
            confirmed_paths=["docs/approved.md"],
            credential_id=None,
            notebooks=[],
            transformations=[],
            embed=False,
        )

        client = AsyncMock()
        client.fetch_text_file = AsyncMock(
            return_value=RawFetchResult(
                raw_url="https://raw/approved",
                content="# Approved",
                content_hash="hash-approved",
            )
        )

        with patch.object(GitSync, "get", new=AsyncMock(return_value=sync)), patch.object(
            GitSync, "save", new=AsyncMock(return_value=None)
        ), patch.object(
            GitSyncService,
            "_get_valid_credential",
            new=AsyncMock(return_value=None),
        ), patch.object(
            GitSyncService, "_build_client", return_value=client
        ), patch.object(
            GitSyncService,
            "_resolve_source",
            new=AsyncMock(return_value=(Source(id="source:approved", title="docs/approved.md"), True)),
        ), patch.object(
            GitSyncService,
            "_ensure_source_notebooks",
            new=AsyncMock(return_value=None),
        ), patch.object(
            GitSyncService,
            "_submit_source_processing",
            new=AsyncMock(return_value="command:1"),
        ):
            response = await GitSyncService.run_sync("git_sync:confirmed")

        assert [state.path for state in response.file_states if state.active] == ["docs/approved.md"]
        client.fetch_text_file.assert_awaited_once()
        assert client.fetch_text_file.await_args.kwargs["path"] == "docs/approved.md"

    @pytest.mark.asyncio
    async def test_run_sync_records_not_found_error(self):
        sync = GitSync(
            id="git_sync:2",
            provider="azure_devops",
            repo="repo",
            branch="main",
            paths=["docs/missing.md"],
            credential_id="credential:1",
            file_states=[],
        )
        sync.sync_path_states()

        credential = Credential(
            id="credential:1",
            name="ADO",
            provider="azure_devops",
            modalities=["source_sync"],
            api_key=SecretStr("secret"),
            base_url="https://dev.azure.com/example/project",
        )
        client = AsyncMock()
        client.fetch_text_file = AsyncMock(
            side_effect=GitRawNotFoundError("Markdown file not found in remote repository")
        )

        with patch.object(GitSync, "get", new=AsyncMock(return_value=sync)), patch.object(
            GitSync, "save", new=AsyncMock(return_value=None)
        ), patch.object(
            GitSyncService,
            "_get_valid_credential",
            new=AsyncMock(return_value=credential),
        ), patch.object(
            GitSyncService, "_build_client", return_value=client
        ):
            response = await GitSyncService.run_sync("git_sync:2")

        assert response.summary.failed == 1
        assert response.file_states[0].last_status == "failed"
        assert "not found" in (response.file_states[0].last_error or "").lower()

    @pytest.mark.asyncio
    async def test_run_sync_discovers_markdown_and_leaf_files_from_seed_paths(self):
        sync = GitSync(
            id="git_sync:3",
            provider="github",
            repo="owner/repo",
            branch="main",
            paths=[],
            seed_paths=["README.md"],
            max_discovery_depth=2,
            max_discovery_files=10,
            credential_id=None,
            notebooks=[],
            transformations=[],
            embed=False,
        )

        client = AsyncMock()
        client.fetch_text_file = AsyncMock(
            side_effect=[
                RawFetchResult(
                    raw_url="https://raw/readme",
                    content="[Guide](docs/guide.md)\n[Diagram](docs/flow.puml)\n[Vector](assets/architecture.svg)",
                    content_hash="hash-readme-discovery",
                ),
                RawFetchResult(
                    raw_url="https://raw/guide",
                    content="## Guide\n",
                    content_hash="hash-guide-discovery",
                ),
                RawFetchResult(
                    raw_url="https://raw/readme",
                    content="# README",
                    content_hash="hash-readme-process",
                ),
                RawFetchResult(
                    raw_url="https://raw/guide",
                    content="# Guide",
                    content_hash="hash-guide-process",
                ),
                RawFetchResult(
                    raw_url="https://raw/puml",
                    content="@startuml\nAlice -> Bob\n@enduml",
                    content_hash="hash-puml-process",
                ),
                RawFetchResult(
                    raw_url="https://raw/svg",
                    content="<svg><text>Architecture</text></svg>",
                    content_hash="hash-svg-process",
                ),
            ]
        )

        def resolve_source(sync_obj, state):
            return (Source(id=f"source:{state.path}", title=state.path), True)

        with patch.object(GitSync, "get", new=AsyncMock(return_value=sync)), patch.object(
            GitSync, "save", new=AsyncMock(return_value=None)
        ), patch.object(
            GitSyncService,
            "_get_valid_credential",
            new=AsyncMock(return_value=None),
        ), patch.object(
            GitSyncService, "_build_client", return_value=client
        ), patch.object(
            GitSyncService,
            "_resolve_source",
            new=AsyncMock(side_effect=resolve_source),
        ), patch.object(
            GitSyncService,
            "_ensure_source_notebooks",
            new=AsyncMock(return_value=None),
        ), patch.object(
            GitSyncService,
            "_submit_source_processing",
            new=AsyncMock(return_value="command:1"),
        ):
            response = await GitSyncService.run_sync("git_sync:3")

        assert response.summary.created == 4
        discovered_paths = [state.path for state in response.file_states if state.active]
        assert discovered_paths == [
            "README.md",
            "docs/guide.md",
            "docs/flow.puml",
            "assets/architecture.svg",
        ]
