from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class CoreUnavailableError(RuntimeError):
    """Raised when the sibling Calmanta formal project cannot be loaded."""


@dataclass(frozen=True)
class CoreTools:
    root: Path
    reject_auth_material: Callable[[Any], None]
    classify_comment: Callable[[str], Any]
    enforce_analysis_safety: Callable[[str, Any], Any]
    validate_reply: Callable[[str, str, int], list[str]]
    sensitive_tags: Callable[[str], list[str]]
    no_reply_recommended: Callable[[str], bool]
    utc_now: Callable[[], str]


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def find_core_root() -> Path:
    configured = os.getenv("CALMANTA_CORE_DIR", "").strip()
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())
    personal_root = project_root()
    candidates.extend(
        (
            personal_root.parent / "Calmanta-Official",
            personal_root.parent / "Calmanta",
            personal_root / "Calmanta-Official",
            personal_root / "Calmanta",
        )
    )
    for candidate in candidates:
        resolved = candidate.resolve()
        if (resolved / "backend" / "platform_workflow.py").is_file():
            return resolved
    searched = ", ".join(str(path) for path in candidates)
    raise CoreUnavailableError(
        "Calmanta formal core was not found. Keep Calmanta-Official and Calmanta-Personal "
        f"side by side, or set CALMANTA_CORE_DIR. Searched: {searched}"
    )


def load_core() -> CoreTools:
    root = find_core_root()
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    try:
        from backend.adapters.browser_assist import reject_auth_material
        from backend.classifier import classify_comment
        from backend.models import utc_now
        from backend.platform_workflow import PlatformWorkflowService
        from backend.safety import enforce_analysis_safety, validate_reply
    except ImportError as exc:
        message = f"Unable to import Calmanta formal core from {root}: {exc}"
        raise CoreUnavailableError(message) from exc
    return CoreTools(
        root=root,
        reject_auth_material=reject_auth_material,
        classify_comment=classify_comment,
        enforce_analysis_safety=enforce_analysis_safety,
        validate_reply=validate_reply,
        sensitive_tags=PlatformWorkflowService._sensitive_tags,
        no_reply_recommended=PlatformWorkflowService._no_reply_recommended,
        utc_now=utc_now,
    )
