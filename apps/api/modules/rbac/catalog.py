import uuid
from typing import Dict, List, NamedTuple, Optional
from apps.api.modules.rbac.models import PLATFORM_SCOPE_ID


class PermissionDefinition(NamedTuple):
    id: str
    domain: str
    action: str
    min_scope: str
    is_delegable: bool
    description: str


PERMISSIONS_CATALOG: List[PermissionDefinition] = [
    # Platform Domain
    PermissionDefinition("platform.settings.read", "platform", "settings.read", "platform", False, "View platform-wide configuration"),
    PermissionDefinition("platform.settings.write", "platform", "settings.write", "platform", False, "Modify platform-wide configuration"),
    PermissionDefinition("platform.roles.manage", "platform", "roles.manage", "platform", False, "Configure dynamic role-permission mappings"),
    PermissionDefinition("platform.audit.read", "platform", "audit.read", "platform", False, "Read cross-tenant global audit logs"),
    PermissionDefinition("platform.maintenance.toggle", "platform", "maintenance.toggle", "platform", False, "Toggle platform maintenance mode"),

    # Organization Domain
    PermissionDefinition("org.view", "org", "view", "organization", True, "View organization profile and public metadata"),
    PermissionDefinition("org.profile.update", "org", "profile.update", "organization", True, "Update organization name, slug, description"),
    PermissionDefinition("org.status.update", "org", "status.update", "platform", False, "Suspend, reactivate, or archive organization"),
    PermissionDefinition("org.member.invite", "org", "member.invite", "organization", True, "Invite new members to the organization"),
    PermissionDefinition("org.member.update_role", "org", "member.update_role", "organization", True, "Change member role within organization"),
    PermissionDefinition("org.member.remove", "org", "member.remove", "organization", True, "Remove a member from the organization"),
    PermissionDefinition("org.config.update", "org", "config.update", "organization", True, "Update tenant-level configuration overrides"),

    # Hackathon Domain
    PermissionDefinition("hackathon.create", "hackathon", "create", "organization", True, "Create a new hackathon under organization"),
    PermissionDefinition("hackathon.view", "hackathon", "view", "hackathon", True, "View hackathon details, timeline, and rules"),
    PermissionDefinition("hackathon.update", "hackathon", "update", "hackathon", True, "Edit hackathon metadata and description"),
    PermissionDefinition("hackathon.publish", "hackathon", "publish", "hackathon", True, "Transition hackathon status to published"),
    PermissionDefinition("hackathon.archive", "hackathon", "archive", "hackathon", True, "Archive completed hackathon"),
    PermissionDefinition("hackathon.override", "hackathon", "override", "platform", False, "Administrative status/timeline override"),
    PermissionDefinition("hackathon.config.update", "hackathon", "config.update", "hackathon", True, "Update event-level configuration overrides"),

    # Participant Domain
    PermissionDefinition("participant.register", "participant", "register", "hackathon", True, "Register for an open hackathon"),
    PermissionDefinition("participant.team.create", "participant", "team.create", "hackathon", True, "Create a new participant team for the event"),
    PermissionDefinition("participant.team.join", "participant", "team.join", "hackathon", True, "Join an existing team via invite/join code"),
    PermissionDefinition("participant.team.manage", "participant", "team.manage", "resource", True, "Add/remove team members (team leader)"),
    PermissionDefinition("participant.submission.create", "participant", "submission.create", "resource", True, "Submit project repository URL or upload"),
    PermissionDefinition("participant.submission.update", "participant", "submission.update", "resource", True, "Update submission before deadline"),
    PermissionDefinition("participant.submission.withdraw", "participant", "submission.withdraw", "resource", True, "Withdraw submission before deadline"),
    PermissionDefinition("participant.submission.view_own", "participant", "submission.view_own", "resource", True, "View own team's submission details and status"),
    PermissionDefinition("participant.feedback.view", "participant", "feedback.view", "hackathon", True, "View scores/feedback once released to public"),
    PermissionDefinition("participant.appeal.submit", "participant", "appeal.submit", "resource", True, "Submit scoring appeal/inquiry to organizers"),

    # Rubric Domain
    PermissionDefinition("rubric.create", "rubric", "create", "hackathon", True, "Create a new rubric draft"),
    PermissionDefinition("rubric.view", "rubric", "view", "hackathon", True, "View rubric criteria and weights"),
    PermissionDefinition("rubric.update", "rubric", "update", "hackathon", True, "Edit criteria and weights in draft rubric"),
    PermissionDefinition("rubric.publish", "rubric", "publish", "hackathon", True, "Freeze rubric version as published (immutable)"),

    # Evaluation Domain
    PermissionDefinition("evaluation.trigger", "evaluation", "trigger", "hackathon", True, "Queue AI evaluation job for submission"),
    PermissionDefinition("evaluation.view", "evaluation", "view", "hackathon", True, "View evaluation results, scores, and citations"),
    PermissionDefinition("evaluation.view_raw_model", "evaluation", "view_raw_model", "hackathon", False, "View raw LLM completion diagnostics"),
    PermissionDefinition("evaluation.cancel", "evaluation", "cancel", "hackathon", True, "Cancel an in-flight evaluation job"),
    PermissionDefinition("evaluation.retry", "evaluation", "retry", "hackathon", True, "Retry a failed evaluation job"),

    # Judging Domain
    PermissionDefinition("judge.assign", "judge", "assign", "hackathon", True, "Assign a user as judge to a hackathon"),
    PermissionDefinition("judge.view_assigned", "judge", "view_assigned", "hackathon", True, "View evaluation queue for assigned events"),
    PermissionDefinition("judge.review", "judge", "review", "hackathon", True, "Accept, reject, or comment on evaluation"),
    PermissionDefinition("judge.score_override", "judge", "score_override", "hackathon", True, "Override AI criterion score with rationale"),
    PermissionDefinition("judge.finalize", "judge", "finalize", "hackathon", True, "Finalize event scoring and lock leaderboard"),

    # Integrations Domain
    PermissionDefinition("integration.github.configure", "integration", "github.configure", "organization", True, "Add encrypted GitHub PAT/App credentials"),
    PermissionDefinition("integration.github.view", "integration", "github.view", "organization", True, "View masked token previews"),
    PermissionDefinition("integration.github.revoke", "integration", "github.revoke", "organization", True, "Revoke GitHub integration credential"),

    # AI Operations Domain
    PermissionDefinition("ai_ops.queue.view", "ai_ops", "queue.view", "platform", False, "View cross-tenant Celery evaluation queue"),
    PermissionDefinition("ai_ops.job.cancel", "ai_ops", "job.cancel", "platform", False, "Cross-tenant administrative job cancel"),
    PermissionDefinition("ai_ops.worker.telemetry", "ai_ops", "worker.telemetry", "platform", False, "View worker pool heartbeats & queue health"),
    PermissionDefinition("ai_ops.model.manage", "ai_ops", "model.manage", "platform", False, "Add or update approved LLM model registry"),

    # Audit Domain
    PermissionDefinition("audit.tenant.read", "audit", "tenant.read", "organization", True, "View organization-specific audit activity"),
]


SYSTEM_ROLES_CATALOG = [
    {
        "name": "platform_owner",
        "display_name": "Platform Owner",
        "scope_type": "platform",
        "scope_id": PLATFORM_SCOPE_ID,
        "is_system": True,
        "is_immutable": True,
        "permissions": [p.id for p in PERMISSIONS_CATALOG],  # Platform Owner possesses all permissions
    },
    {
        "name": "platform_ops_admin",
        "display_name": "Platform Operations Admin",
        "scope_type": "platform",
        "scope_id": PLATFORM_SCOPE_ID,
        "is_system": True,
        "is_immutable": False,
        "permissions": [
            "platform.settings.read", "platform.settings.write", "org.status.update",
            "hackathon.override", "evaluation.trigger", "evaluation.view",
            "evaluation.cancel", "evaluation.retry", "ai_ops.queue.view",
            "ai_ops.job.cancel", "ai_ops.worker.telemetry", "ai_ops.model.manage",
        ],
    },
    {
        "name": "ai_ops_admin",
        "display_name": "AI Operations Admin",
        "scope_type": "platform",
        "scope_id": PLATFORM_SCOPE_ID,
        "is_system": True,
        "is_immutable": False,
        "permissions": [
            "ai_ops.queue.view", "ai_ops.worker.telemetry", "ai_ops.model.manage",
            "evaluation.view_raw_model",
        ],
    },
    {
        "name": "security_admin",
        "display_name": "Security Admin",
        "scope_type": "platform",
        "scope_id": PLATFORM_SCOPE_ID,
        "is_system": True,
        "is_immutable": False,
        "permissions": [
            "platform.audit.read", "platform.settings.read",
        ],
    },
    {
        "name": "org_owner",
        "display_name": "Organization Owner",
        "scope_type": "platform",
        "scope_id": PLATFORM_SCOPE_ID,
        "is_system": True,
        "is_immutable": False,
        "permissions": [
            "org.view", "org.profile.update", "org.member.invite", "org.member.update_role",
            "org.member.remove", "org.config.update", "hackathon.create", "hackathon.view",
            "hackathon.update", "hackathon.publish", "hackathon.archive", "hackathon.config.update",
            "rubric.create", "rubric.view", "rubric.update", "rubric.publish",
            "evaluation.trigger", "evaluation.view", "evaluation.cancel", "evaluation.retry",
            "judge.assign", "judge.view_assigned", "judge.review", "judge.score_override",
            "judge.finalize", "integration.github.configure", "integration.github.view",
            "integration.github.revoke", "audit.tenant.read",
        ],
    },
    {
        "name": "org_admin",
        "display_name": "Organization Admin",
        "scope_type": "platform",
        "scope_id": PLATFORM_SCOPE_ID,
        "is_system": True,
        "is_immutable": False,
        "permissions": [
            "org.view", "org.profile.update", "org.member.invite", "org.member.update_role",
            "org.member.remove", "org.config.update", "hackathon.create", "hackathon.view",
            "hackathon.update", "hackathon.publish", "hackathon.archive", "hackathon.config.update",
            "rubric.create", "rubric.view", "rubric.update", "rubric.publish",
            "evaluation.trigger", "evaluation.view", "evaluation.cancel", "evaluation.retry",
            "judge.assign", "judge.view_assigned", "judge.review", "judge.score_override",
            "judge.finalize", "integration.github.configure", "integration.github.view",
            "integration.github.revoke", "audit.tenant.read",
        ],
    },
    {
        "name": "organizer",
        "display_name": "Hackathon Organizer",
        "scope_type": "platform",
        "scope_id": PLATFORM_SCOPE_ID,
        "is_system": True,
        "is_immutable": False,
        "permissions": [
            "org.view", "hackathon.create", "hackathon.view", "hackathon.update",
            "hackathon.config.update", "rubric.create", "rubric.view", "rubric.update",
            "evaluation.trigger", "evaluation.view", "evaluation.retry",
            "judge.assign", "judge.view_assigned", "judge.review", "judge.score_override",
        ],
    },
    {
        "name": "judge",
        "display_name": "Judge / Evaluator",
        "scope_type": "platform",
        "scope_id": PLATFORM_SCOPE_ID,
        "is_system": True,
        "is_immutable": False,
        "permissions": [
            "hackathon.view", "rubric.view", "evaluation.view", "judge.view_assigned",
            "judge.review", "judge.score_override",
        ],
    },
    {
        "name": "participant",
        "display_name": "Hackathon Participant",
        "scope_type": "platform",
        "scope_id": PLATFORM_SCOPE_ID,
        "is_system": True,
        "is_immutable": False,
        "permissions": [
            "hackathon.view", "participant.register", "participant.team.create",
            "participant.team.join", "participant.team.manage",
            "participant.submission.create", "participant.submission.update",
            "participant.submission.withdraw", "participant.submission.view_own",
            "participant.feedback.view", "participant.appeal.submit",
        ],
    },
]
