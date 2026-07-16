"""Verified file-upload handling for ATS application forms."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.control_engine import element_descriptor, normalize_text


@dataclass
class UploadOutcome:
    filled_count: int = 0
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    review_items: List[Dict[str, Any]] = field(default_factory=list)


def _required_review(descriptor: str, *, reason: str, accept: str = "") -> Dict[str, Any]:
    return {
        "reason_code": "unsupported_control",
        "summary": reason,
        "details": {
            "descriptor": descriptor,
            "control_type": "file_upload",
            "required": True,
            "accept": accept,
        },
    }


def _classify_upload(descriptor: str) -> Optional[str]:
    text = normalize_text(descriptor)
    if any(token in text for token in ("resume", "curriculum vitae", " cv ", "upload cv")):
        return "resume"
    if any(token in text for token in ("cover letter", "lettre de motivation")):
        return "cover_letter"
    if any(token in text for token in ("portfolio", "work sample", "writing sample")):
        return "portfolio"
    return None


def _path_matches_accept(path: str, accept: str) -> bool:
    if not accept:
        return True
    extension = os.path.splitext(path)[1].lower()
    tokens = [token.strip().lower() for token in accept.split(",") if token.strip()]
    if not tokens:
        return True
    if extension and extension in tokens:
        return True
    broad = {
        ".pdf": {"application/pdf", "application/*", "*/*"},
        ".doc": {"application/msword", "application/*", "*/*"},
        ".docx": {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/*",
            "*/*",
        },
        ".txt": {"text/plain", "text/*", "*/*"},
    }
    return any(token in broad.get(extension, set()) for token in tokens)


async def fill_upload_fields(
    surface: Any,
    *,
    resume_path: str = "",
    cover_letter_path: str = "",
    portfolio_path: str = "",
    log: Optional[List[Dict[str, Any]]] = None,
) -> UploadOutcome:
    outcome = UploadOutcome()
    log = log if log is not None else []
    paths = {
        "resume": resume_path,
        "cover_letter": cover_letter_path,
        "portfolio": portfolio_path,
    }

    for element in await surface.query_selector_all('input[type="file"]'):
        try:
            if not await element.is_visible() or not await element.is_enabled():
                continue
        except Exception:
            pass

        descriptor = await element_descriptor(surface, element)
        upload_type = _classify_upload(f" {descriptor} ")
        required = (
            await element.get_attribute("required") is not None
            or normalize_text(await element.get_attribute("aria-required")) == "true"
        )
        accept = await element.get_attribute("accept") or ""
        path = paths.get(upload_type or "", "")

        if not upload_type:
            if required:
                outcome.review_items.append(_required_review(
                    descriptor,
                    reason=f"Required upload type is not recognized: {descriptor}",
                    accept=accept,
                ))
            log.append({
                "action": "upload_unclassified",
                "descriptor": descriptor[:200],
                "required": required,
            })
            continue

        if not path or not os.path.exists(path):
            if required:
                outcome.review_items.append(_required_review(
                    descriptor,
                    reason=f"Required {upload_type.replace('_', ' ')} file is missing.",
                    accept=accept,
                ))
            log.append({
                "action": "upload_missing",
                "upload_type": upload_type,
                "descriptor": descriptor[:200],
                "required": required,
            })
            continue

        if not _path_matches_accept(path, accept):
            outcome.review_items.append(_required_review(
                descriptor,
                reason=(
                    f"{upload_type.replace('_', ' ').title()} file type does not match "
                    f"the accepted formats for this upload."
                ),
                accept=accept,
            ))
            continue

        try:
            await element.set_input_files(path)
            files = await element.evaluate(
                """(el) => Array.from(el.files || []).map((file) => ({
                  name: file.name, size: file.size, type: file.type
                }))"""
            )
            expected = os.path.basename(path)
            verified = bool(files and files[0].get("name") == expected)
            if not verified:
                outcome.review_items.append(_required_review(
                    descriptor,
                    reason=f"Upload could not be verified for {descriptor}.",
                    accept=accept,
                ))
                continue
            outcome.filled_count += 1
            evidence = {
                "action": "upload_verified",
                "upload_type": upload_type,
                "descriptor": descriptor,
                "filename": expected,
                "files": files,
                "accept": accept,
                "verification": "passed",
            }
            outcome.evidence.append(evidence)
            log.append(evidence)
        except Exception as exc:
            outcome.review_items.append(_required_review(
                descriptor,
                reason=f"Upload failed for {descriptor}: {str(exc)[:160]}",
                accept=accept,
            ))
    return outcome
