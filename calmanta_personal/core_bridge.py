from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class CoreUnavailableError(RuntimeError):
    """Raised when the portable Calmanta Core package cannot be loaded."""


@dataclass(frozen=True)
class CoreTools:
    root: Path
    reject_auth_material: Callable[[Any], None]
    classify_comment: Callable[[str], Any]
    analysis_factory: Callable[..., Any]
    enforce_analysis_safety: Callable[[str, Any], Any]
    validate_reply: Callable[[str, str, int], list[str]]
    sensitive_tags: Callable[[str], list[str]]
    no_reply_recommended: Callable[[str], bool]
    normalize_voice_profile: Callable[[Any], dict[str, Any]]
    prepare_voice_template: Callable[..., dict[str, Any]]
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
            personal_root.parent / "Calmanta-Core",
            personal_root / "Calmanta-Core",
        )
    )
    for candidate in candidates:
        resolved = candidate.resolve()
        if (resolved / "backend" / "inbox_rules.py").is_file():
            return resolved
    searched = ", ".join(str(path) for path in candidates)
    raise CoreUnavailableError(
        "Calmanta Core was not found. Keep Calmanta-Core and Calmanta-Personal "
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
        from backend.inbox_rules import no_reply_recommended, sensitive_tags
        from backend.models import Analysis, utc_now
        from backend.safety import enforce_analysis_safety, validate_reply
        from backend.voice_guide import normalize_voice_profile
        from backend.voice_templates import prepare_voice_template
    except ImportError as exc:
        message = f"Unable to import Calmanta Core from {root}: {exc}"
        raise CoreUnavailableError(message) from exc
    return CoreTools(
        root=root,
        reject_auth_material=reject_auth_material,
        classify_comment=classify_comment,
        analysis_factory=Analysis,
        enforce_analysis_safety=enforce_analysis_safety,
        validate_reply=validate_reply,
        sensitive_tags=sensitive_tags,
        no_reply_recommended=no_reply_recommended,
        normalize_voice_profile=normalize_voice_profile,
        prepare_voice_template=prepare_voice_template,
        utc_now=utc_now,
    )
