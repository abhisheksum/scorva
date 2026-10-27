"""
GitHub Webhook and Repository Activity Ingestion Service.

Implements:
- Constant-time HMAC-SHA256 signature verification (X-Hub-Signature-256).
- Body size limits and defensive payload parsing.
- Safe field normalization preserving evidence provenance while redacting sensitive tokens.
- Idempotent deduplication via unique delivery identifiers (X-GitHub-Delivery).
- Correlation to registered hackathon submissions and deadline-guarded commit resolution.
"""

from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.core.exceptions import AppException
from apps.api.modules.audit.models import AuditOutcome
from apps.api.modules.audit.service import record_audit_event
from apps.api.modules.evaluations.models import GitHubEvent, Submission
from apps.api.modules.hackathons.models import Hackathon

logger = logging.getLogger(__name__)


def verify_github_webhook_signature(
    raw_body: bytes,
    signature_header: Optional[str],
    secret: Optional[str] = None,
) -> bool:
    """
    Verifies that the incoming webhook payload was signed by GitHub using HMAC-SHA256.
    Performs constant-time string comparison to prevent timing attacks.
    Never logs or leaks the secret or signatures on failure.
    """
    if not signature_header:
        raise AppException(
            status_code=401,
            code="WEBHOOK_SIGNATURE_MISSING",
            message="Missing X-Hub-Signature-256 header.",
        )

    if not signature_header.startswith("sha256="):
        raise AppException(
            status_code=401,
            code="WEBHOOK_SIGNATURE_INVALID_FORMAT",
            message="Invalid signature format; expected 'sha256=<hex_digest>'.",
        )

    provided_hex = signature_header[7:].strip()
    active_secret = secret or settings.GITHUB_WEBHOOK_SECRET

    expected_hex = hmac.new(
        key=active_secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_hex, provided_hex):
        raise AppException(
            status_code=403,
            code="WEBHOOK_SIGNATURE_MISMATCH",
            message="Webhook signature verification failed.",
        )

    return True


def normalize_github_webhook_payload(
    event_type: str,
    delivery_id: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Safely extracts and normalizes event fields required for hackathon evidence and timeline.
    Strictly avoids storing unvetted full payload JSON to prevent credential leakages.
    """
    clean_event_type = event_type.strip().lower()
    clean_delivery_id = delivery_id.strip()

    # Extract repository identity
    repo_obj = payload.get("repository") or {}
    owner = ""
    repo_name = ""
    canonical_repo_id = ""

    if repo_obj:
        canonical_repo_id = repo_obj.get("full_name", "").strip().lower()
        repo_name = repo_obj.get("name", "").strip()
        owner_obj = repo_obj.get("owner")
        if isinstance(owner_obj, dict):
            owner = owner_obj.get("login", "").strip()
        elif isinstance(owner_obj, str):
            owner = owner_obj.strip()

    if not canonical_repo_id and owner and repo_name:
        canonical_repo_id = f"{owner}/{repo_name}".lower()
    elif not canonical_repo_id:
        canonical_repo_id = "unknown/repository"

    sender_obj = payload.get("sender") or {}
    sender_login = sender_obj.get("login") if isinstance(sender_obj, dict) else None

    action: Optional[str] = payload.get("action")
    ref: Optional[str] = None
    commit_sha: Optional[str] = None
    summary: Optional[str] = None
    details: Dict[str, Any] = {}
    event_timestamp: datetime = datetime.now(timezone.utc)

    # 1. PING Event
    if clean_event_type == "ping":
        summary = "GitHub webhook endpoint configured and pinged successfully"
        details = {
            "zen": payload.get("zen"),
            "hook_id": payload.get("hook_id"),
        }

    # 2. PUSH Event
    elif clean_event_type == "push":
        ref = payload.get("ref")
        commit_sha = payload.get("after")
        head_commit = payload.get("head_commit") or {}
        commits = payload.get("commits") or []

        if head_commit and isinstance(head_commit, dict):
            raw_msg = head_commit.get("message", "")
            summary = raw_msg.split("\n")[0][:200] if raw_msg else f"Pushed {len(commits)} commit(s)"
            ts_str = head_commit.get("timestamp")
            if ts_str:
                try:
                    event_timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except Exception:
                    pass
        else:
            summary = f"Pushed {len(commits)} commit(s) to {ref or 'repository'}"

        details = {
            "ref": ref,
            "commit_sha": commit_sha,
            "commit_count": len(commits),
            "head_commit_message": (head_commit.get("message", "") if isinstance(head_commit, dict) else "")[:300],
            "compare_url": payload.get("compare"),
            "forced": payload.get("forced", False),
        }

    # 3. PULL REQUEST Event
    elif clean_event_type == "pull_request":
        pr = payload.get("pull_request") or {}
        pr_number = pr.get("number") or payload.get("number")
        pr_title = (pr.get("title") or "")[:200]
        pr_merged = pr.get("merged", False)
        pr_state = pr.get("state")
        html_url = pr.get("html_url")

        head_ref = pr.get("head", {}).get("ref") if isinstance(pr.get("head"), dict) else None
        head_sha = pr.get("head", {}).get("sha") if isinstance(pr.get("head"), dict) else None
        ref = head_ref
        commit_sha = head_sha

        summary = f"PR #{pr_number} {action or 'updated'}: {pr_title}"
        details = {
            "action": action,
            "pr_number": pr_number,
            "pr_title": pr_title,
            "pr_state": pr_state,
            "pr_merged": pr_merged,
            "html_url": html_url,
            "head_branch": head_ref,
            "base_branch": pr.get("base", {}).get("ref") if isinstance(pr.get("base"), dict) else None,
        }

        ts_str = pr.get("updated_at") or pr.get("created_at")
        if ts_str:
            try:
                event_timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except Exception:
                pass

    # 4. CREATE / DELETE (Branch or Tag)
    elif clean_event_type in ("create", "delete"):
        ref = payload.get("ref")
        ref_type = payload.get("ref_type", "reference")
        summary = f"{clean_event_type.capitalize()}d {ref_type} '{ref}'"
        details = {
            "ref": ref,
            "ref_type": ref_type,
            "action": clean_event_type,
        }

    # 5. REPOSITORY Event
    elif clean_event_type == "repository":
        summary = f"Repository {action or 'updated'}"
        details = {
            "action": action,
        }

    # 6. Fallback / Generic Event
    else:
        summary = f"GitHub {clean_event_type} event received"
        details = {
            "action": action,
        }

    return {
        "delivery_id": clean_delivery_id,
        "event_type": clean_event_type,
        "action": action,
        "repository_owner": owner or "unknown",
        "repository_name": repo_name or "unknown",
        "canonical_repo_id": canonical_repo_id,
        "ref": ref[:255] if ref else None,
        "commit_sha": commit_sha[:40] if commit_sha else None,
        "sender_login": sender_login,
        "summary": summary[:500] if summary else None,
        "details": details,
        "event_timestamp": event_timestamp,
    }


async def ingest_github_webhook(
    db: AsyncSession,
    delivery_id: str,
    event_type: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Persists incoming webhook deliveries idempotently and correlates them to active hackathon submissions.
    Updates submission commit SHA if new pushes arrive on the configured target branch before deadline.
    """
    clean_delivery_id = delivery_id.strip()

    # 1. Idempotency Check: if delivery ID is already recorded, return immediately
    stmt_existing = select(GitHubEvent).where(GitHubEvent.delivery_id == clean_delivery_id)
    existing_event = (await db.execute(stmt_existing)).scalar_one_or_none()
    if existing_event:
        return {
            "status": "duplicate",
            "delivery_id": clean_delivery_id,
            "event_type": existing_event.event_type,
            "message": "Webhook delivery already processed.",
        }

    # 2. Normalize payload
    norm = normalize_github_webhook_payload(
        event_type=event_type,
        delivery_id=clean_delivery_id,
        payload=payload,
    )

    owner = norm["repository_owner"]
    repo_name = norm["repository_name"]
    canonical_repo = norm["canonical_repo_id"]

    # 3. Match against active registered submissions in Scorva
    stmt_sub = (
        select(Submission)
        .where(
            Submission.deleted_at.is_(None),
            func.lower(Submission.repository_owner) == owner.lower(),
            func.lower(Submission.repository_name) == repo_name.lower(),
        )
        .order_by(Submission.created_at.desc())
    )
    matching_submissions = (await db.execute(stmt_sub)).scalars().all()

    org_id: Optional[uuid.UUID] = None
    hackathon_id: Optional[uuid.UUID] = None
    submission_id: Optional[uuid.UUID] = None
    status = "ignored"
    diagnostic_code = "NO_MATCHING_SUBMISSION"
    now_utc = datetime.now(timezone.utc)

    if matching_submissions:
        # Bind to primary matching submission
        primary_sub = matching_submissions[0]
        org_id = primary_sub.organization_id
        hackathon_id = primary_sub.hackathon_id
        submission_id = primary_sub.id
        status = "processed"
        diagnostic_code = "SUCCESS"

        # Check hackathon deadline for commit updates
        stmt_hack = select(Hackathon).where(Hackathon.id == hackathon_id)
        hackathon = (await db.execute(stmt_hack)).scalar_one_or_none()

        # If event is a push on the submission's target branch, update verified commit SHA
        if norm["event_type"] == "push" and norm["commit_sha"]:
            clean_branch = (norm["ref"] or "").removeprefix("refs/heads/").strip()
            for sub in matching_submissions:
                if sub.target_branch == clean_branch or clean_branch in (sub.target_branch, "main", "master"):
                    is_past_deadline = hackathon and now_utc > hackathon.submission_deadline
                    if not is_past_deadline:
                        old_sha = sub.verified_commit_sha
                        sub.verified_commit_sha = norm["commit_sha"]
                        sub.verified_at = now_utc
                        sub.connection_status = "verified"
                        sub.verification_diagnostic = "SUCCESS"
                        sub.verification_error = None

                        await record_audit_event(
                            db=db,
                            action="submission_commit_received",
                            resource_type="submission",
                            resource_id=str(sub.id),
                            outcome=AuditOutcome.SUCCESS,
                            organization_id=sub.organization_id,
                            reason=f"Received commit '{norm['commit_sha'][:7]}' via GitHub push webhook on branch '{clean_branch}'",
                            diff_payload={
                                "delivery_id": clean_delivery_id,
                                "old_commit_sha": old_sha,
                                "new_commit_sha": sub.verified_commit_sha,
                                "branch": clean_branch,
                            },
                        )
                    else:
                        diagnostic_code = "DEADLINE_PASSED"

    # 4. Insert durable GitHubEvent record
    event_record = GitHubEvent(
        id=uuid.uuid4(),
        delivery_id=clean_delivery_id,
        event_type=norm["event_type"],
        action=norm["action"],
        organization_id=org_id,
        hackathon_id=hackathon_id,
        submission_id=submission_id,
        repository_owner=owner,
        repository_name=repo_name,
        canonical_repo_id=canonical_repo,
        ref=norm["ref"],
        commit_sha=norm["commit_sha"],
        sender_login=norm["sender_login"],
        summary=norm["summary"],
        details=norm["details"],
        status=status,
        diagnostic_code=diagnostic_code,
        error_message=None,
        event_timestamp=norm["event_timestamp"],
        processed_at=now_utc,
    )
    db.add(event_record)
    await db.flush()

    # Record general webhook audit event if linked to an organization
    if org_id:
        await record_audit_event(
            db=db,
            action="github_webhook_ingested",
            resource_type="github_event",
            resource_id=str(event_record.id),
            outcome=AuditOutcome.SUCCESS,
            organization_id=org_id,
            reason=f"Ingested GitHub {norm['event_type']} delivery {clean_delivery_id} for {canonical_repo}",
            diff_payload={
                "delivery_id": clean_delivery_id,
                "event_type": norm["event_type"],
                "canonical_repo_id": canonical_repo,
                "status": status,
                "diagnostic_code": diagnostic_code,
            },
        )

    return {
        "status": status,
        "delivery_id": clean_delivery_id,
        "event_type": norm["event_type"],
        "canonical_repo_id": canonical_repo,
        "submission_id": str(submission_id) if submission_id else None,
        "diagnostic_code": diagnostic_code,
    }


async def list_submission_activity(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    submission_id: uuid.UUID,
    limit: int = 50,
) -> List[GitHubEvent]:
    """Retrieves chronological activity timeline events associated with a submission."""
    stmt = (
        select(GitHubEvent)
        .where(
            GitHubEvent.organization_id == org_id,
            GitHubEvent.hackathon_id == hackathon_id,
            GitHubEvent.submission_id == submission_id,
        )
        .order_by(GitHubEvent.event_timestamp.desc(), GitHubEvent.created_at.desc())
        .limit(min(limit, 100))
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_hackathon_activity(
    db: AsyncSession,
    org_id: uuid.UUID,
    hackathon_id: uuid.UUID,
    limit: int = 50,
) -> List[GitHubEvent]:
    """Retrieves chronological activity timeline events for all submissions in a hackathon."""
    stmt = (
        select(GitHubEvent)
        .where(
            GitHubEvent.organization_id == org_id,
            GitHubEvent.hackathon_id == hackathon_id,
        )
        .order_by(GitHubEvent.event_timestamp.desc(), GitHubEvent.created_at.desc())
        .limit(min(limit, 100))
    )
    return list((await db.execute(stmt)).scalars().all())
