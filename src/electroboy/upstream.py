"""Upstream issue provider adapters for intake workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlparse

from .config import UpstreamConfig, load_pipeline_config


@dataclass(frozen=True)
class IssueRecord:
    """Normalized upstream issue metadata."""

    reference: str
    provider: str
    title: str
    url: str | None = None
    number: str | None = None
    labels: list[str] = field(default_factory=list)
    body: str = ""
    state: str | None = None
    author: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class UpstreamError(RuntimeError):
    """Raised when an upstream provider cannot load issue metadata."""


def load_issue_record(
    root: Path | str,
    reference: str,
    provider_name: str | None = None,
) -> IssueRecord:
    """Load issue metadata using the selected upstream provider."""

    root_path = Path(root)
    config = load_pipeline_config(root_path)
    provider = _select_provider(config.upstreams, config.upstream_default, reference, provider_name)
    if provider.adapter == "generic":
        return _generic_issue(reference, provider.name)
    if provider.adapter == "local":
        return _local_issue(root_path, reference, provider.name)
    if provider.adapter == "command":
        return _command_issue(root_path, reference, provider)
    raise UpstreamError(f"unknown upstream adapter: {provider.adapter}")


def _select_provider(
    providers: dict[str, UpstreamConfig],
    default_name: str,
    reference: str,
    requested_name: str | None,
) -> UpstreamConfig:
    if requested_name:
        try:
            return providers[requested_name]
        except KeyError as error:
            raise UpstreamError(f"unknown upstream provider: {requested_name}") from error
    host = urlparse(reference).netloc.lower()
    if host:
        for provider in providers.values():
            if any(host == domain or host.endswith(f".{domain}") for domain in provider.domains):
                return provider
    return providers[default_name]


def _generic_issue(reference: str, provider_name: str) -> IssueRecord:
    number = _issue_number(reference)
    title = f"Bug from issue {number}" if number else _title_from_reference(reference)
    return IssueRecord(
        reference=reference,
        provider=provider_name,
        title=title,
        url=reference if _looks_like_url(reference) else None,
        number=number,
    )


def _local_issue(root: Path, reference: str, provider_name: str) -> IssueRecord:
    path = Path(reference).expanduser()
    if not path.is_absolute():
        path = root / path
    if not path.exists():
        return _generic_issue(reference, provider_name)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise UpstreamError(f"invalid local issue JSON: {path}") from error
        return _issue_from_payload(reference, provider_name, payload)
    title = _first_markdown_heading(text) or path.stem.replace("-", " ").title()
    return IssueRecord(
        reference=reference,
        provider=provider_name,
        title=title,
        body=text,
        metadata={"path": str(path)},
    )


def _command_issue(root: Path, reference: str, provider: UpstreamConfig) -> IssueRecord:
    if not provider.command:
        raise UpstreamError(f"upstream provider {provider.name} has no command")
    argv = [
        _expand_arg(arg, reference)
        for arg in ([provider.command] + provider.args)
    ]
    env = {name: os.environ[name] for name in provider.env if name in os.environ}
    completed = subprocess.run(
        argv,
        cwd=root,
        env={**env} if env else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise UpstreamError(
            f"upstream provider {provider.name} failed"
            + (f": {detail}" if detail else "")
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise UpstreamError(
            f"upstream provider {provider.name} did not return JSON"
        ) from error
    return _issue_from_payload(reference, provider.name, payload)


def _issue_from_payload(
    reference: str,
    provider_name: str,
    payload: object,
) -> IssueRecord:
    if not isinstance(payload, dict):
        raise UpstreamError("upstream issue payload must be a JSON object")
    labels = payload.get("labels", [])
    if isinstance(labels, list):
        label_values = [
            str(label.get("name") if isinstance(label, dict) else label)
            for label in labels
        ]
    else:
        label_values = [str(labels)]
    title = str(payload.get("title") or _title_from_reference(reference)).strip()
    return IssueRecord(
        reference=reference,
        provider=provider_name,
        title=title or _title_from_reference(reference),
        url=_optional_string(payload.get("url") or payload.get("web_url")) or (
            reference if _looks_like_url(reference) else None
        ),
        number=_optional_string(
            payload.get("number")
            or payload.get("iid")
            or payload.get("id")
            or _issue_number(reference)
        ),
        labels=[label for label in label_values if label],
        body=str(payload.get("body") or payload.get("description") or ""),
        state=_optional_string(payload.get("state") or payload.get("status")),
        author=_author_name(payload.get("author") or payload.get("user")),
        metadata={
            key: value
            for key, value in payload.items()
            if key
            not in {
                "title",
                "url",
                "web_url",
                "number",
                "iid",
                "id",
                "labels",
                "body",
                "description",
                "state",
                "status",
                "author",
                "user",
            }
        },
    )


def _expand_arg(arg: str, reference: str) -> str:
    return arg.replace("{reference}", reference)


def _author_name(value: object) -> str | None:
    if isinstance(value, dict):
        return _optional_string(value.get("login") or value.get("username") or value.get("name"))
    return _optional_string(value)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_markdown_heading(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or None
    return None


def _title_from_reference(reference: str) -> str:
    value = reference.strip()
    if _looks_like_url(value):
        parts = [part for part in urlparse(value).path.split("/") if part]
        if len(parts) >= 2 and parts[-2] in {"issues", "bug", "bugs"}:
            return f"Bug from issue {parts[-1]}"
        if parts:
            return parts[-1].replace("-", " ").title()
    return value or "Bug"


def _issue_number(reference: str) -> str | None:
    value = reference.rstrip("/")
    if _looks_like_url(value):
        parts = [part for part in urlparse(value).path.split("/") if part]
        if len(parts) >= 2 and parts[-2] in {"issues", "bug", "bugs"}:
            return parts[-1]
    return None


def _looks_like_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")
