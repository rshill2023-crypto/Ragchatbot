"""Artifact persistence.

Every RAG stage writes an inspectable file under
`<root>/<run_id>/<stage>/...` so the demo can show what happened at each step.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Union

_FORMAT_SUFFIX = {
    "json": ".json",
    "jsonl": ".jsonl",
    "text": ".txt",
    "txt": ".txt",
    "html": ".html",
}


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _check_relative(raw: str, label: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        raise ValueError("%s must be relative, got %s" % (label, raw))
    if ".." in path.parts:
        raise ValueError("%s must not contain '..', got %s" % (label, raw))
    return path


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".%s." % path.name, suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


class ArtifactWriter:
    """Write stage outputs to a versioned run directory."""

    def __init__(
        self,
        root: Union[str, Path] = "data/artifacts",
        run_id: Optional[str] = None,
    ) -> None:
        self.root = Path(root)
        self.run_id = run_id or datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%S%fZ"
        )
        self.run_dir = self.root / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def stage_dir(self, stage: str) -> Path:
        if stage in ("", "."):
            return self.run_dir
        path = self.run_dir / _check_relative(stage, "stage")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save(
        self,
        stage: str,
        name: str,
        payload: Any,
        fmt: str = "json",
    ) -> Path:
        """Persist `payload` and return the written path.

        `stage` may be nested (for example `raw/html`). `name` is given an
        extension automatically unless it already ends with the right one.
        """
        if fmt not in _FORMAT_SUFFIX:
            raise ValueError(
                "unsupported format %r; expected one of %s"
                % (fmt, ", ".join(sorted(_FORMAT_SUFFIX)))
            )

        filename = str(_check_relative(name, "name"))
        suffix = _FORMAT_SUFFIX[fmt]
        if not filename.endswith(suffix):
            filename += suffix

        path = self.stage_dir(stage) / filename

        if fmt == "json":
            content = json.dumps(
                payload, indent=2, ensure_ascii=False, default=_json_default
            ) + "\n"
        elif fmt == "jsonl":
            content = self._render_jsonl(payload)
        else:
            content = str(payload)
            if not content.endswith("\n"):
                content += "\n"

        _atomic_write(path, content)
        return path

    @staticmethod
    def _render_jsonl(payload: Iterable[Any]) -> str:
        if isinstance(payload, (str, bytes, dict)):
            raise TypeError("jsonl payload must be an iterable of objects")
        lines = [
            json.dumps(item, ensure_ascii=False, default=_json_default)
            for item in payload
        ]
        return "\n".join(lines) + ("\n" if lines else "")

    def write_run_meta(self, config_snapshot: Optional[Dict[str, Any]] = None) -> Path:
        payload = {
            "run_id": self.run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "config": config_snapshot or {},
        }
        return self.save("", "run_meta", payload)
