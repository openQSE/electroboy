"""Review report discovery and issue metadata summaries."""

from __future__ import annotations

import html
import json
from pathlib import Path


def review_report_index(project_root: Path | str) -> dict[str, object]:
    root = Path(project_root).resolve()
    run_dir, run_id = _current_run(root)
    reviews: list[dict[str, object]] = []
    represented_issue_files: set[str] = set()

    if run_dir is not None:
        registry_path = run_dir / "code-reviews.jsonl"
        for record in _latest_records(registry_path, "review_id"):
            issue_file = str(record.get("issue_file") or "")
            represented_issue_files.add(issue_file)
            reviews.append(
                _review_payload(
                    root,
                    run_dir,
                    review_id=str(record.get("review_id") or registry_path.stem),
                    category="code",
                    report_path=str(record.get("summary_path") or ""),
                    issue_file=issue_file,
                    record=record,
                )
            )

        for issue_path in sorted(run_dir.glob("*review*.jsonl")):
            if issue_path.name == "code-reviews.jsonl":
                continue
            if issue_path.name in represented_issue_files:
                continue
            reviews.append(
                _review_payload(
                    root,
                    run_dir,
                    review_id=issue_path.stem,
                    category=_review_category(issue_path.name),
                    report_path=_matching_report(root, issue_path.stem),
                    issue_file=issue_path.name,
                    record={},
                )
            )

    represented_reports = {
        str(review.get("report_path") or "") for review in reviews
    }
    docs_root = root / "docs"
    if docs_root.exists():
        for report in sorted(docs_root.rglob("*review*.md")):
            relative = report.relative_to(root).as_posix()
            if relative in represented_reports:
                continue
            reviews.append(
                {
                    "id": report.stem,
                    "category": _review_category(report.name),
                    "status": "report-only",
                    "report_path": relative,
                    "metadata_path": None,
                    "finding_count": 0,
                    "open_count": 0,
                    "severity_counts": {},
                }
            )

    reviews.sort(
        key=lambda item: (
            str(item.get("category") or ""),
            str(item.get("id") or ""),
        )
    )
    return {"run_id": run_id, "reviews": reviews}


def review_report_index_html(project_root: Path | str, category: str) -> str:
    payload = review_report_index(project_root)
    reviews = [
        item
        for item in payload["reviews"]
        if item.get("category") == category
    ]
    title = f"{category.title()} Reviews"
    items: list[str] = []
    for review in reviews:
        report_path = str(review.get("report_path") or "")
        label = html.escape(str(review.get("id") or report_path))
        counts = html.escape(
            f"{review.get('open_count', 0)} open / "
            f"{review.get('finding_count', 0)} findings"
        )
        if report_path:
            href = "/artifacts/document?path=" + html.escape(
                report_path,
                quote=True,
            )
            label = f'<a href="{href}">{label}</a>'
        items.append(f"<li>{label} <small>{counts}</small></li>")
    content = "".join(items) if items else "<li>No reviews recorded.</li>"
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(title)}</title></head><body>"
        f"<h1>{html.escape(title)}</h1><ul>{content}</ul></body></html>"
    )


def _current_run(root: Path) -> tuple[Path | None, str | None]:
    current_run = root / ".electroboy" / "shared" / "current-run"
    if not current_run.exists():
        return None, None
    run_id = current_run.read_text(encoding="utf-8").strip()
    if not run_id:
        return None, None
    run_dir = root / ".electroboy" / "shared" / "runs" / run_id
    return (run_dir if run_dir.exists() else None), run_id


def _review_payload(
    root: Path,
    run_dir: Path,
    *,
    review_id: str,
    category: str,
    report_path: str,
    issue_file: str,
    record: dict[str, object],
) -> dict[str, object]:
    issue_path = run_dir / issue_file
    issues = _latest_records(issue_path, "issue_id")
    severity_counts: dict[str, int] = {}
    for issue in issues:
        severity = str(issue.get("severity") or "unknown")
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
    open_count = len(
        [
            issue
            for issue in issues
            if str(issue.get("status") or "open")
            not in {"closed", "resolved", "fixed", "accepted"}
        ]
    )
    normalized_report = _relative_path(root, report_path)
    return {
        "id": review_id,
        "category": category,
        "status": str(record.get("status") or "recorded"),
        "report_path": normalized_report or None,
        "metadata_path": _relative_path(root, issue_path),
        "finding_count": len(issues),
        "open_count": open_count,
        "severity_counts": severity_counts,
        "metadata": record,
    }


def _latest_records(path: Path, key: str) -> list[dict[str, object]]:
    if not path.exists():
        return []
    latest: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        record_id = str(record.get(key) or "")
        if not record_id:
            continue
        if record_id not in latest:
            order.append(record_id)
        latest[record_id] = record
    return [latest[record_id] for record_id in order]


def _review_category(name: str) -> str:
    lowered = name.lower()
    if "validation" in lowered:
        return "validation"
    if "test-review" in lowered:
        return "test"
    if "design-review" in lowered:
        return "design"
    return "code"


def _matching_report(root: Path, stem: str) -> str:
    docs_root = root / "docs"
    if not docs_root.exists():
        return ""
    normalized = stem.removesuffix("-review")
    candidates = sorted(docs_root.rglob(f"*{normalized}*.md"))
    return candidates[0].relative_to(root).as_posix() if candidates else ""


def _relative_path(root: Path, path: Path | str) -> str:
    if not str(path):
        return ""
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return candidate.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)
