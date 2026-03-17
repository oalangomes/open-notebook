import base64
import hashlib
from dataclasses import dataclass
from urllib.parse import quote

import httpx


@dataclass
class RawFetchResult:
    raw_url: str
    content: str
    content_hash: str


class GitRawClientError(Exception):
    pass


class GitRawAuthError(GitRawClientError):
    pass


class GitRawNotFoundError(GitRawClientError):
    pass


class GitRawClient:
    def __init__(self, provider: str, base_url: str, pat: str) -> None:
        self.provider = provider.lower()
        self.base_url = base_url.rstrip("/")
        self.pat = pat

    def build_raw_url(self, repo: str, branch: str, path: str) -> str:
        normalized_path = path if path.startswith("/") else f"/{path}"

        if self.provider == "azure_devops":
            repo_part = quote(repo, safe="")
            path_part = quote(normalized_path, safe="/")
            branch_part = quote(branch, safe="")
            return (
                f"{self.base_url}/_apis/git/repositories/{repo_part}/items"
                f"?path={path_part}"
                f"&versionDescriptor.versionType=branch"
                f"&versionDescriptor.version={branch_part}"
                f"&includeContent=true"
                f"&resolveLfs=true"
                f"&api-version=7.1"
            )

        if self.provider == "github":
            if self.pat:
                path_part = quote(normalized_path.lstrip("/"), safe="/")
                repo_part = quote(repo, safe="/")
                branch_part = quote(branch, safe="")
                return (
                    f"https://api.github.com/repos/{repo_part}/contents/{path_part}"
                    f"?ref={branch_part}"
                )

            repo_part = quote(repo, safe="/")
            branch_part = quote(branch, safe="")
            path_part = quote(normalized_path.lstrip("/"), safe="/")
            return f"https://raw.githubusercontent.com/{repo_part}/{branch_part}/{path_part}"

        raise GitRawClientError(f"Unsupported Git provider: {self.provider}")

    def build_headers(self) -> dict[str, str]:
        if self.provider == "azure_devops":
            token = base64.b64encode(f":{self.pat}".encode("utf-8")).decode("ascii")
            return {
                "Authorization": f"Basic {token}",
                "Accept": "application/json",
            }

        if self.provider == "github":
            headers = {"Accept": "application/vnd.github.raw"}
            if self.pat:
                headers["Authorization"] = f"Bearer {self.pat}"
            return headers

        raise GitRawClientError(f"Unsupported Git provider: {self.provider}")

    async def fetch_text_file(self, repo: str, branch: str, path: str) -> RawFetchResult:
        raw_url = self.build_raw_url(repo=repo, branch=branch, path=path)
        headers = self.build_headers()

        try:
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                response = await client.get(raw_url, headers=headers)
        except httpx.TimeoutException as exc:
            raise GitRawClientError("Timed out while fetching repository file") from exc
        except httpx.HTTPError as exc:
            raise GitRawClientError(f"Failed to fetch repository file: {exc}") from exc

        if response.status_code == 401:
            raise GitRawAuthError("Authentication failed for repository file fetch")
        if response.status_code == 403:
            raise GitRawAuthError("PAT lacks permission to fetch repository file")
        if response.status_code == 404:
            raise GitRawNotFoundError("Repository file not found")
        if response.status_code >= 400:
            raise GitRawClientError(
                f"Repository file fetch failed with status {response.status_code}"
            )

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            payload = response.json()
            content = payload.get("content")
            if not isinstance(content, str):
                raise GitRawClientError("RAW response did not include textual content")
        else:
            content = response.text

        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return RawFetchResult(raw_url=raw_url, content=content, content_hash=content_hash)

    async def fetch_markdown(self, repo: str, branch: str, path: str) -> RawFetchResult:
        return await self.fetch_text_file(repo=repo, branch=branch, path=path)
