# SCORVA — Super Admin Dashboard
## Screen-by-Screen Functional & UI Specification

**Document version:** 1.0  
**Status:** Implementation-ready specification  
**Product:** Scorva — AI-assisted hackathon evaluation platform  
**Scope:** Super Admin dashboard MVP  
**Frontend:** Next.js, TypeScript, Tailwind CSS, Lucide React  
**Backend:** FastAPI, Pydantic, SQLAlchemy, PostgreSQL  
**Background processing:** Redis + Celery or equivalent  
**Design approach:** Dark-first, professional, responsive SaaS interface

---

# 1. Purpose and Product Principles

The Super Admin dashboard is the internal control center for operating Scorva. It enables authorized platform administrators to manage organizations, users, hackathons, AI evaluations, system health, integrations, and security.

It is an operational interface—not merely a collection of attractive charts.

### Core principles

1. **Real data only:** Every metric and status must come from a real API or be explicitly identified as unavailable.
2. **Least privilege:** Administrators see and perform only actions permitted by their role.
3. **Human accountability:** AI evaluations remain inspectable and auditable. Administrative actions must not silently alter judging results.
4. **Evidence and traceability:** Important changes, evaluation retries, access changes, and overrides must be logged.
5. **Safe failure:** Network errors, unavailable metrics, and failed jobs must be visible and recoverable.
6. **Progressive delivery:** Implement MVP functionality first; add billing, advanced analytics, and enterprise controls later.

**Product principle:** AI evaluates the evidence. Judges make the decisions. Scorva makes the process transparent.

# 2. Global Application Shell

## 2.1 Sidebar navigation

The desktop layout uses a persistent left sidebar with collapsible behavior.

### Primary navigation

| Navigation item | Route | MVP priority |
|---|---|---|
| Dashboard | `/admin` | P0 |
| Organizations | `/admin/organizations` | P0 |
| Users & Access | `/admin/users` | P0 |
| Hackathons | `/admin/hackathons` | P0 |
| Plans & Billing | `/admin/billing` | P2 |
| AI Operations | `/admin/ai-operations` | P0 |
| System Health | `/admin/system-health` | P0 |
| Security & Audit | `/admin/security` | P0 |
| Support Center | `/admin/support` | P1 |
| Notifications | `/admin/notifications` | P1 |
| Integrations | `/admin/integrations` | P0 |
| Settings | `/admin/settings` | P0 |

Models and Evaluations should be subpages within AI Operations, not separate top-level navigation items.

### Sidebar behavior

- Display the Scorva logo and product name at the top.
- Show a compact icon and label for each item.
- Highlight the active route.
- Support collapsed and expanded states.
- Show badges only for meaningful counts, such as unresolved critical alerts.
- Hide or disable unauthorized navigation items according to the chosen access policy.
- On mobile, replace the persistent sidebar with a drawer.
- Keep navigation labels consistent across the application.

## 2.2 Global top bar

The header contains:

- Breadcrumbs for the current location.
- Page title where appropriate.
- Global search entry point.
- Notification icon with unread count.
- Environment indicator, such as Development or Production, when configured.
- Administrator avatar and profile menu.

### Global search

Search should support authorized records such as organizations, users, hackathons, and evaluation jobs.

Requirements:

- Debounce requests.
- Display categorized results.
- Navigate to the selected record.
- Respect the current administrator's permissions.
- Display a useful empty state when there are no matches.
- Never return hidden records merely because the requester knows a name or identifier.

## 2.3 Global interaction states

Every data-driven screen must support:

- Loading state.
- Loaded state.
- Empty state.
- Recoverable error state with retry.
- Permission-denied state.
- Unavailable or stale data state, where applicable.
- Pagination and filter persistence when useful.

Use skeletons for initial loading, not fake rows that resemble real data.

## 2.4 Design system

| Element | Specification |
|---|---|
| Application background | `#0B1020` |
| Surface / cards | `#111827` |
| Primary accent | `#3B82F6` |
| Primary text | `#F8FAFC` |
| Secondary text | `#94A3B8` |
| Success | `#10B981` |
| Warning | `#F59E0B` |
| Error | `#EF4444` |
| Font | Inter or Plus Jakarta Sans |
| Icons | Lucide React |
| Border radius | Consistent, moderately rounded |
| Layout | Responsive grid with clear spacing |

Use semantic colors consistently. Do not rely on color alone to convey status; pair colors with text or icons.

Avoid excessive gradients, decorative charts, emojis, and unnecessary animation.

# 3. Administrator Roles and Permissions

The interface must support role-based access control (RBAC) enforced by the backend.

| Role | Primary responsibility |
|---|---|
| Platform Owner | Full platform administration |
| Platform Operations Admin | Organizations, hackathons, and routine operations |
| AI Operations Admin | Evaluation jobs, model configuration, and benchmarks |
| Security Admin | Security alerts, access controls, and audit review |
| Support Admin | Support cases and limited user assistance |
| Billing Admin | Plans, subscriptions, and billing operations |

The Platform Owner is the highest-privilege role. Creating or changing privileged accounts must require explicit authorization.

### Permission requirements

- Frontend permission checks improve usability but are not security boundaries.
- The backend must authorize every protected request.
- Administrative actions must record the acting user, target, timestamp, action, and outcome.
- Sensitive actions require confirmation.
- Destructive actions may require re-authentication or additional approval.
- Support staff must not be able to inspect private repository contents or sensitive evaluation evidence without explicit permission.
- Access changes must not silently invalidate the audit trail.

# 4. Screen 01 — Dashboard Overview

**Route:** `/admin`

**Purpose:** Give administrators a reliable, high-level view of platform activity and operational health.

## 4.1 Page layout

### Section A — Page header

- Heading: `Platform Overview`
- Supporting text: `Monitor Scorva activity, evaluations, and system health.`
- Last-updated timestamp.
- Refresh action.

The refresh action should update the dashboard data without unnecessarily resetting filters on other pages.

### Section B — Metric cards

Display the following cards:

1. Total organizations.
2. Total registered users.
3. Active hackathons.
4. Total submissions.
5. Evaluations completed.
6. Evaluations queued or running.
7. Evaluation failure rate.
8. System availability or health summary, only if supported by real monitoring data.

Each card should contain:

- Metric label.
- Current value.
- Optional comparison with a clearly defined previous period.
- Short explanatory text or a link to the relevant detail page.

Do not show a percentage change unless the backend supplies enough information to calculate it correctly.

### Section C — Evaluation activity

Display a time-series chart for evaluation activity.

Requirements:

- Allow daily and weekly ranges.
- Distinguish completed, failed, and in-progress jobs.
- Include tooltips with exact values.
- Provide an accessible textual summary.
- Use backend aggregation instead of loading every job into the browser.

If insufficient data exists, display an empty state rather than a fabricated trend.

### Section D — Recent platform activity

Table columns:

- Timestamp.
- Administrator or actor.
- Action.
- Target resource.
- Outcome.
- Link to audit details.

Examples include an organization being suspended, an evaluation being retried, or a privileged role being changed.

### Section E — Operational alerts

Show a concise list of actionable issues:

- Repeated evaluation failures.
- Queue backlog above configured thresholds.
- Worker unavailable.
- Integration authentication failures.
- Critical security events.

Every alert should link to the relevant operational screen.

### Section F — Quick actions

Provide permission-controlled shortcuts:

- View organizations.
- View users.
- Inspect evaluation jobs.
- Open system health.
- Review security events.

Do not expose unrestricted account creation, deletion, or suspension through one-click shortcuts.

## 4.2 API dependencies

Proposed endpoints:

- `GET /api/v1/admin/dashboard/overview`
- `GET /api/v1/admin/dashboard/activity`
- `GET /api/v1/admin/dashboard/alerts`

The overview response should contain values, reporting windows, and freshness metadata.

## 4.3 Acceptance criteria

- Every metric has a defined meaning.
- Counts match the underlying records and filtering rules.
- Missing metrics are identified as unavailable.
- Charts use actual aggregated data.
- Alert links navigate to the correct resource.
- Refresh failures preserve the last valid data while indicating that it may be stale.

# 5. Screen 02 — Organizations

**Route:** `/admin/organizations`  
**Status:** **Implemented & Verified (Phase 3 Milestone 4)**  
**Purpose:** Manage organizations using Scorva to run hackathons.

## 5.1 Organization list

### Header

- Page title: `Organizations`
- Supporting text describing platform organization management.
- `Create organization` action, if authorized.

### Summary cards

- Total organizations.
- Active organizations.
- Suspended organizations.
- Organizations created during the selected period.

### Table columns

| Column | Details |
|---|---|
| Organization | Name and stable identifier |
| Owner | Primary owner |
| Members | Current member count |
| Hackathons | Associated hackathon count |
| Status | Active, pending, suspended, or other supported states |
| Created | Creation date |
| Actions | View, edit, manage status |

### Filters

- Search by name or identifier.
- Status.
- Creation date range.
- Owner.
- Sort by creation date, name, or activity.
- Pagination.

Search, filters, and sorting must be applied consistently by the backend.

## 5.2 Organization detail page

**Route:** `/admin/organizations/[organizationId]`

Use tabs:

### Overview

- Organization name and identifier.
- Current status.
- Owner and creation date.
- Member and hackathon counts.
- Recent activity.
- Internal administrative notes, if enabled.

### Members

- Member list.
- Role within the organization.
- Membership status.
- Invitation status, if supported.
- View member profile.
- Change membership only when authorized.

### Hackathons

- Associated hackathons.
- Status, dates, team count, and submission count.
- Link to the corresponding hackathon detail.

### Activity

- Organization-specific audit history.
- Relevant membership and configuration changes.

## 5.3 Organization actions

- Create organization.
- Edit permitted organization metadata.
- Suspend or reactivate an organization.
- View associated users and hackathons.
- Transfer ownership through an explicit, validated workflow.

Suspension must show a confirmation dialog explaining its consequences. The system must define how suspension affects active hackathons, logins, submissions, and ongoing evaluations before this feature is enabled.

Do not permanently delete an organization in the initial MVP.

## 5.4 Acceptance criteria

- Duplicate identifiers are rejected.
- Organization ownership is validated.
- Status changes are audited.
- Related records remain consistent.
- Unauthorized administrators cannot perform privileged actions.
- The list supports pagination and useful empty states.

# 6. Screen 03 — Users & Access

**Route:** `/admin/users`

**Purpose:** Provide controlled visibility into accounts, roles, and access status.

## 6.1 User directory

### Table columns

- Name.
- Email.
- Platform role.
- Organization membership.
- Account status.
- Email verification status, if implemented.
- Last login, if recorded.
- Created date.
- Actions.

### Filters

- Name or email search.
- Platform role.
- Account status.
- Organization.
- Creation date.
- Verification status.

### User detail page

**Route:** `/admin/users/[userId]`

Sections:

**Profile**
- Display name.
- Email.
- Account identifier.
- Creation date.
- Verification status.

**Access**
- Platform-level role.
- Organization memberships and their roles.
- Account status.
- Available permissions or role summary.

**Activity**
- Recent authentication events, where safely available.
- Administrative changes.
- Account security events.

## 6.2 User actions

- View user.
- Edit permitted profile fields.
- Change platform role, with elevated authorization.
- Suspend or reactivate account.
- Revoke active sessions, if session management supports it.
- Trigger an account recovery workflow, if implemented.

### Role-change confirmation

Before changing a privileged role, show:

- Current role.
- Proposed role.
- Expected permission changes.
- Confirmation action.

Prevent accidental removal of the last active Platform Owner unless an explicit, safe ownership-transfer workflow is completed.

Do not expose password hashes, authentication secrets, session tokens, or private credentials.

## 6.3 Acceptance criteria

- Role changes take effect on the backend.
- Every access change is audited.
- Account suspension follows documented session and access rules.
- Search results respect administrator permissions.
- Email addresses and other personal data are displayed only to authorized staff.

# 7. Screen 04 — Hackathons

**Route:** `/admin/hackathons`  
**Status:** **Implemented & Verified (Phase 3 Milestone 4)**  
**Purpose:** Give platform administrators oversight of hackathons without replacing the Organizer dashboard.

## 7.1 Hackathon directory

### Table columns

- Hackathon name.
- Organization.
- Organizer.
- Status.
- Start and end dates.
- Registered teams.
- Submissions.
- Evaluation progress.
- Created date.
- Actions.

### Filters

- Search by name or identifier.
- Organization.
- Status.
- Date range.
- Evaluation state.

### Summary cards

- Total hackathons.
- Currently active.
- Upcoming.
- Completed.
- Hackathons with evaluation issues.

## 7.2 Hackathon detail page

**Route:** `/admin/hackathons/[hackathonId]`

### Overview

- Name and description.
- Owning organization.
- Organizers.
- Start and end dates.
- Registration and submission deadlines.
- Status.
- Team and submission counts.

### Teams and submissions

- Team name.
- Submission identifier.
- Repository URL, when authorized.
- Frozen commit SHA.
- Submission timestamp.
- Evaluation status.
- Judge review status.

The frozen commit SHA is important: an evaluation must remain tied to the exact source revision assessed, not a repository's later state.

### Rubric

- Rubric name and version.
- Criteria and weights.
- Score definitions.
- Effective version for each evaluation.

### Results

- Current leaderboard or result status.
- Publication state.
- Relevant changes and audit records.

The Super Admin must not silently alter published scores or override judges' decisions. Exceptional corrections require an authorized workflow and audit history.

## 7.3 Administrative actions

- View hackathon.
- Inspect configuration.
- Inspect submission and evaluation status.
- Suspend or restore a hackathon if the policy permits it.
- Escalate a problem to the owning Organizer.

Creation and routine event management should remain Organizer responsibilities unless platform policy explicitly assigns those tasks to Super Admins.

## 7.4 Acceptance criteria

- Every submission links to its exact evaluated commit.
- Rubric versions remain identifiable.
- Administrative intervention is recorded.
- Published results cannot be silently changed.
- Organization-level access restrictions are enforced.

# 8. Screen 05 — Plans & Billing

**Route:** `/admin/billing`

**Priority:** P2 — future release.

This screen is specified for consistency but is not required to launch the core evaluation MVP.

## Planned sections

### Plans

- Plan name.
- Features and quotas.
- Evaluation limits.
- Repository or storage limits.
- Billing interval.
- Active/inactive state.

### Subscriptions

- Organization.
- Current plan.
- Subscription status.
- Renewal date.
- Usage against plan limits.

### Transactions

- Payment reference.
- Organization.
- Amount and currency.
- Payment status.
- Date.
- Provider reference.

### Billing actions

- View plan.
- Change plan configuration.
- Inspect subscription.
- Review failed payments.
- View billing history.

Financial changes require appropriate authorization, audit records, and reconciliation with the payment provider.

**Do not show revenue, invoices, or payment status as real until a billing provider and verified data pipeline are implemented.** Do not store raw card details.

# 9. Screen 06 — AI Operations

**Route:** `/admin/ai-operations`

**Purpose:** Monitor and manage Scorva's AI evaluation pipeline.

This is one of the most important operational screens because evaluation failures directly affect teams and judges.

## 9.1 Overview tab

### Metric cards

- Total jobs.
- Queued jobs.
- Running jobs.
- Completed jobs.
- Failed jobs.
- Median or average duration, with the calculation clearly defined.
- Retry count.
- Current queue depth.

### Job table

| Column | Description |
|---|---|
| Job ID | Stable job identifier |
| Hackathon | Associated event |
| Submission | Evaluated submission |
| Status | Queued, running, completed, failed, cancelled |
| Stage | Current pipeline stage |
| Attempt | Current attempt / maximum attempts |
| Duration | Elapsed or completed duration |
| Created | Creation timestamp |
| Actions | Inspect, retry, cancel if supported |

### Filters

- Status.
- Hackathon.
- Date range.
- Pipeline stage.
- Failure category.
- Model/provider.
- Submission identifier.

## 9.2 Job detail page

**Route:** `/admin/ai-operations/jobs/[jobId]`

### Summary

- Job identifier.
- Submission identifier.
- Frozen commit SHA.
- Hackathon and rubric version.
- Current status.
- Created, started, and completed timestamps.
- Attempt number.
- Model/provider and configuration version.

### Pipeline timeline

Display the stages that actually exist in the backend, for example:

1. Repository acquisition.
2. Repository inventory.
3. Documentation analysis.
4. Technical analysis.
5. Evidence validation.
6. Rubric scoring.
7. Report persistence.

Each stage should show:

- Status.
- Start and end time.
- Duration.
- Safe, user-facing failure summary.
- Retryability, when known.

These are logical pipeline stages; they do not need to be separate LLM agents.

### Evidence and assessment

Authorized administrators should be able to inspect:

- Evidence references.
- Rubric criterion scores.
- Explanations supporting each score.
- Missing evidence.
- Confidence or uncertainty indicators, if implemented.
- Known analysis limitations.
- Model and prompt version identifiers.

Do not expose hidden internal reasoning or unrestricted model chain-of-thought. Provide concise explanations grounded in observable repository evidence.

### Logs

- Timestamped operational events.
- Sanitized error details.
- Correlation or trace identifier.
- Retry history.

Never display API keys, access tokens, session secrets, or other credentials in logs.

## 9.3 Retry workflow

When retry is available:

1. Check that the job is retryable.
2. Show the failure reason and previous attempt count.
3. Confirm the retry.
4. Create a traceable new attempt or linked retry job.
5. Preserve the original attempt and its logs.
6. Update status through the backend.
7. Record the requesting administrator and action.

A retry must not silently replace an existing evaluation or overwrite the source snapshot. Define how new results affect judge review before enabling automatic replacement.

## 9.4 Cancel workflow

Cancellation is permitted only if the worker and queue support it safely.

- Confirm the action.
- Display the current stage.
- Explain that cancellation may not reverse already completed work.
- Record the outcome.
- Preserve logs and history.

## 9.5 API dependencies

Proposed endpoints:

- `GET /api/v1/admin/ai/jobs`
- `GET /api/v1/admin/ai/jobs/{job_id}`
- `POST /api/v1/admin/ai/jobs/{job_id}/retry`
- `POST /api/v1/admin/ai/jobs/{job_id}/cancel`
- `GET /api/v1/admin/ai/jobs/{job_id}/events`

Use polling initially if needed; introduce server-sent events or WebSockets when justified.

## 9.6 Acceptance criteria

- Job status reflects backend state.
- Retries preserve prior attempts.
- Duplicate retry requests are handled safely.
- Evidence is linked to the correct commit and rubric version.
- Logs are sanitized.
- Every privileged operation is audited.
- Failed or unavailable data is not displayed as a successful result.

# 10. Screen 07 — Models & Evaluations

**Route:** `/admin/ai-operations/models`

**Priority:** P0 for basic configuration visibility; P1 for benchmarking and advanced controls.

## 10.1 Model registry

Display:

- Model/provider name.
- Model identifier.
- Provider type.
- Availability status.
- Configuration version.
- Last health check.
- Default status.
- Capabilities supported by the provider.

The initial implementation may use Ollama behind a provider abstraction. The dashboard must not assume every model supports the same context size, structured output, or tool behavior.

### Model detail

- Model metadata.
- Provider configuration, excluding secrets.
- Health check history.
- Supported capabilities.
- Usage statistics, if collected.
- Recent evaluation failures.
- Associated configuration versions.

### Actions

- Run a safe connectivity check.
- Select an allowed default model.
- Enable or disable a provider, if policy permits.
- Update non-secret configuration.
- Rotate credentials through a secure secret-management flow.

## 10.2 Evaluation benchmarks

Display:

- Benchmark name and version.
- Dataset or fixture version.
- Model configuration.
- Prompt version.
- Rubric version.
- Number of test cases.
- Completion rate.
- Agreement or quality metrics.
- Latency and resource usage, if measured.
- Run timestamp.

Benchmark results must be reproducible enough to identify which model and configuration produced them.

A benchmark score is not a guarantee of fairness or accuracy. Include limitations and sample size where relevant.

## 10.3 Acceptance criteria

- Secrets are never returned in normal API responses.
- Configuration changes are versioned and audited.
- A health check does not expose sensitive infrastructure details.
- Benchmarks identify their test dataset and configuration.
- Production model changes can be rolled back through a controlled process.

# 11. Screen 08 — System Health

**Route:** `/admin/system-health`

**Purpose:** Identify failures in the application, database, queues, workers, and configured external dependencies.

## 11.1 Service status

Cards or rows for:

- Frontend/API availability.
- Database connectivity.
- Redis connectivity.
- Background worker availability.
- Evaluation queue health.
- GitHub integration.
- AI provider connectivity.
- File or report storage, if used.

Each service should display:

- Status: healthy, degraded, unhealthy, or unknown.
- Last checked time.
- Check duration, if measured.
- A short safe description.
- Link to relevant logs or operational details.

Do not infer health from a process merely existing. Use actual health checks.

## 11.2 Resource metrics

Where infrastructure telemetry exists, show:

- CPU usage.
- Memory usage.
- Disk usage.
- API latency.
- Error rate.
- Queue depth.
- Worker utilization.

Include the measurement window and thresholds. Do not invent live infrastructure numbers when telemetry is unavailable.

## 11.3 Incident history

- Incident identifier.
- Affected component.
- Severity.
- Start and resolution timestamps.
- Current state.
- Related events.

## 11.4 Acceptance criteria

- Health checks use bounded timeouts.
- A failed dependency is distinguishable from an unconfigured one.
- Unknown status is not displayed as healthy.
- Infrastructure details are visible only to authorized administrators.
- Alerts link to actionable diagnostics.

# 12. Screen 09 — Security & Audit

**Route:** `/admin/security`

**Purpose:** Provide accountability for sensitive operations and visibility into security events.

## 12.1 Security overview

Display:

- Critical unresolved alerts.
- Recent authentication failures.
- Privileged account changes.
- Suspicious access patterns, if detection exists.
- Recent administrative actions.
- Audit events awaiting review.

## 12.2 Audit event table

Columns:

- Timestamp.
- Actor.
- Action.
- Resource type.
- Resource identifier.
- Outcome.
- Source context, when collected and appropriate.
- Event identifier.

### Filters

- Actor.
- Action category.
- Resource.
- Outcome.
- Severity.
- Date range.

### Event detail

Display:

- Event identifier.
- Actor identity.
- Action and target.
- Timestamp.
- Outcome.
- Reason or administrative note.
- Safe before/after field differences, where appropriate.
- Request or correlation identifier.

Audit events should be append-only from the application's perspective. Routine administrators must not be able to rewrite or erase history.

## 12.3 Security controls

Depending on implemented capabilities:

- Review active sessions.
- Revoke sessions.
- Inspect account access changes.
- Review provider and integration security events.
- View security configuration status.
- Export authorized audit records.

## 12.4 Acceptance criteria

- Sensitive actions are recorded reliably.
- Audit records are access-controlled.
- Secrets and unnecessary personal data are excluded from logs.
- Event filtering is consistent.
- Failed administrative actions are logged where appropriate.
- Security events have clear severity and timestamps.

# 13. Screen 10 — Support Center

**Route:** `/admin/support`

**Priority:** P1.

## Ticket list

Columns:

- Ticket ID.
- Subject.
- Requester.
- Organization.
- Category.
- Priority.
- Status.
- Assigned administrator.
- Last updated.

### Filters

- Status.
- Priority.
- Category.
- Assigned administrator.
- Organization.
- Date range.

## Ticket detail

- Request summary.
- Conversation history.
- Status and priority.
- Assignment.
- Internal notes, clearly separated from user-visible replies.
- Related organization, user, or hackathon.
- Attachment metadata, if supported.

## Actions

- Assign ticket.
- Change status.
- Change priority.
- Add internal note.
- Send reply.
- Link related records.

Support administrators should not gain unrestricted access to private repository data just because a ticket concerns an evaluation.

## Acceptance criteria

- Internal notes cannot be accidentally sent to users.
- Replies are associated with the correct ticket.
- Changes are auditable.
- Access to attachments is authorized.
- The ticket lifecycle is clearly defined.

# 14. Screen 11 — Notifications

**Route:** `/admin/notifications`

**Priority:** P1.

## Notification center

Display:

- Title.
- Message.
- Category.
- Severity.
- Creation time.
- Read/unread status.
- Related resource.
- Delivery status, if applicable.

### Categories

- Evaluation failures.
- System health.
- Security.
- Integration errors.
- Administrative announcements.

### Actions

- Mark as read.
- Mark all as read.
- Open related resource.
- Configure permitted preferences.
- Create an announcement, if authorized and implemented.

Notifications should link to a real event or resource. Avoid sending repeated alerts for the same underlying failure without a defined deduplication policy.

# 15. Screen 12 — Integrations

**Route:** `/admin/integrations`

**Purpose:** Monitor external services required for Scorva's workflow.

## 15.1 Integration cards

Initial integrations may include:

- GitHub.
- AI model provider or Ollama service.
- Email provider.
- Object/file storage.
- Payment provider, when billing is implemented.

Each card should show:

- Integration name.
- Configuration state.
- Connection status.
- Last successful check.
- Last error summary, if safe to show.
- Available actions.

## 15.2 Integration detail

- Connection status.
- Non-secret configuration fields.
- Permissions or scopes granted.
- Last successful and failed checks.
- Recent relevant events.
- Setup instructions.
- Secure credential update workflow.

### GitHub integration requirements

- Support public repository analysis.
- Support private repositories only when the submitter or organization explicitly authorizes access.
- Use minimum necessary permissions.
- Never log access tokens.
- Record the repository URL and exact commit SHA used for an assessment.
- Handle deleted, inaccessible, rate-limited, or changed repositories safely.

### Test connection

The test action must execute a real, bounded health check and return a meaningful result. It must not report success merely because configuration fields are populated.

## 15.3 Acceptance criteria

- Integration secrets are stored securely.
- Secrets are masked in the interface.
- Failed checks explain the issue without leaking credentials.
- GitHub access is scoped appropriately.
- Integration failures are reflected in System Health when relevant.

# 16. Screen 13 — Settings

**Route:** `/admin/settings`

**Purpose:** Manage platform-wide configuration with clear ownership and safe defaults.

## 16.1 Settings sections

### General

- Platform display name.
- Support contact information.
- Default timezone.
- Default locale, if supported.

### Security

- Session policy.
- Authentication configuration status.
- Privileged-action requirements.
- Account recovery policy.
- Allowed origins and security-related configuration visibility.

Sensitive security settings should be changed through explicit, validated workflows. Some infrastructure settings should remain deployment-managed rather than editable in the UI.

### AI defaults

- Default provider and model.
- Default evaluation configuration.
- Job retry policy.
- Timeout limits.
- Maximum concurrent jobs.

Changes to model, prompt, and rubric configuration should be versioned. Any change that affects scoring must define how it applies to future evaluations and must not silently rewrite existing assessments.

### Operations

- Queue thresholds.
- Alert thresholds.
- Log retention policy visibility.
- Report retention configuration, if implemented.

### Feature flags

- Feature name.
- Current state.
- Environment or scope.
- Change history.
- Authorized control.

Feature flags must not bypass security controls or tenant isolation.

## 16.2 Save behavior

- Validate fields on the backend.
- Show unsaved changes.
- Require confirmation for high-impact changes.
- Display success only after the backend confirms persistence.
- Provide an actionable error when saving fails.
- Record who changed the setting and when.

# 17. Shared Forms, Dialogs, and Interaction Rules

## 17.1 Confirmation dialog

Use for suspension, role changes, retries, cancellation, and other consequential actions.

The dialog must include:

- A clear action title.
- The affected resource.
- The consequence.
- A cancel option.
- A specific confirmation label.

For high-risk actions, require a reason and re-authentication or approval where appropriate.

## 17.2 Forms

- Use explicit labels and inline validation.
- Keep backend validation authoritative.
- Preserve safe user input after recoverable errors.
- Prevent duplicate submissions while an operation is in progress.
- Display field-specific error messages.
- Do not clear a form until success is confirmed.

## 17.3 Tables

- Server-side pagination for large datasets.
- Stable sorting.
- Consistent filter behavior.
- Useful empty states.
- Accessible keyboard interaction.
- Explicit status labels.
- No silent truncation of identifiers needed for investigation.

## 17.4 Toasts and feedback

Use concise feedback for completed actions and non-blocking errors.

Do not use a toast as the only record of a security-critical change. The relevant detail page should reflect the persisted result.

# 18. Responsive Behavior and Accessibility

## Desktop

- Persistent collapsible sidebar.
- Multi-column metric cards.
- Wide tables with controlled horizontal overflow where necessary.
- Detail pages with clear section hierarchy.

## Tablet

- Narrower sidebar or drawer.
- Responsive card grid.
- Filters grouped into a compact toolbar.
- Tables retain essential columns.

## Mobile

- Sidebar becomes a drawer.
- Metric cards stack.
- Filters open in a panel.
- Tables may use a compact layout or horizontally scrollable container.
- Primary actions remain accessible.
- Destructive actions must not be placed where accidental taps are likely.

## Accessibility

- Semantic headings and landmarks.
- Keyboard-accessible navigation, dialogs, tables, and menus.
- Visible focus indicators.
- Appropriate contrast.
- Accessible chart summaries.
- Screen-reader labels for icon-only buttons.
- Status indicators that do not rely on color alone.
- Reduced-motion support.

# 19. Technical Contracts

## 19.1 Frontend structure

A proposed route structure:

```text
app/
  admin/
    layout.tsx
    page.tsx
    organizations/
      page.tsx
      [organizationId]/
        page.tsx
    users/
      page.tsx
      [userId]/
        page.tsx
    hackathons/
      page.tsx
      [hackathonId]/
        page.tsx
    ai-operations/
      page.tsx
      jobs/
        [jobId]/
          page.tsx
      models/
        page.tsx
    system-health/
      page.tsx
    security/
      page.tsx
    billing/
      page.tsx
    support/
      page.tsx
    notifications/
      page.tsx
    integrations/
      page.tsx
    settings/
      page.tsx
```

This is a suggested route layout; components should be extracted into shared modules rather than implemented as oversized page files.

## 19.2 Shared frontend components

```text
components/
  admin/
    AdminSidebar.tsx
    AdminHeader.tsx
    Breadcrumbs.tsx
    MetricCard.tsx
    DataTable.tsx
    FilterBar.tsx
    StatusBadge.tsx
    EmptyState.tsx
    ErrorState.tsx
    LoadingSkeleton.tsx
    ConfirmDialog.tsx
    PageHeader.tsx
    AuditEventList.tsx
```

Keep business logic and API access out of purely presentational components where practical.

## 19.3 API conventions

- Prefix protected endpoints with `/api/v1/admin`.
- Use consistent response and error schemas.
- Validate input with Pydantic.
- Apply backend RBAC.
- Use stable identifiers.
- Include pagination metadata.
- Apply server-side filtering and sorting.
- Use explicit UTC timestamps in API responses.
- Document endpoints using OpenAPI.
- Make retry and other non-idempotent actions safe against accidental duplicate requests.

## 19.4 Suggested database entities

The final schema should align with the overall Scorva architecture. Expected entities include:

- `users`
- `organizations`
- `organization_memberships`
- `platform_roles`
- `hackathons`
- `teams`
- `submissions`
- `submission_snapshots`
- `rubrics`
- `rubric_versions`
- `evaluation_jobs`
- `evaluation_attempts`
- `evaluation_results`
- `evidence_references`
- `model_configurations`
- `benchmark_runs`
- `audit_events`
- `integration_configurations`
- `notifications`
- `support_tickets`

Additional tables should be introduced only when required by a concrete workflow. Sensitive configuration values must not be stored as plaintext database fields.

# 20. MVP Delivery Priorities

## P0 — Required for the first usable release

- Authentication and administrator RBAC.
- Global layout and responsive navigation.
- Dashboard with real metrics.
- Organization list and detail.
- User directory and controlled access management.
- Hackathon oversight.
- AI job list, details, logs, and safe retries.
- Basic model/provider visibility.
- System health checks.
- Security and audit event visibility.
- Integration status.
- Essential platform settings.
- Loading, empty, error, and permission-denied states.

## P1 — After the operational core

- Advanced model benchmarking.
- Support Center.
- Notification preferences and announcements.
- Expanded analytics.
- Advanced quota management.
- Audit export.
- More sophisticated incident workflows.

## P2 — Later commercial and enterprise capabilities

- Plans and subscriptions.
- Payment integration.
- Revenue and billing analytics.
- Cost optimization dashboards.
- Enterprise-specific policy controls.
- Advanced anomaly detection.

The UI may show a planned feature only when its status is unmistakable. Do not build decorative placeholders that imply working functionality.

# 21. Testing Strategy

## Unit tests

- Permission checks.
- Form validation.
- Status mapping.
- Metric formatting.
- Filter construction.
- Error handling.

## API tests

- Authorized and unauthorized requests.
- Organization isolation.
- User role changes.
- Hackathon access rules.
- Evaluation retry behavior.
- Audit event creation.
- Integration health checks.

## Integration tests

- Database persistence.
- Background job transitions.
- Retry and failure scenarios.
- Model-provider errors.
- GitHub repository access failures.
- Queue and worker unavailability.

## End-to-end tests

At minimum, verify these flows:

1. Administrator signs in and opens the dashboard.
2. Authorized administrator searches for an organization and opens its details.
3. Authorized administrator finds a user and inspects access.
4. Administrator opens a hackathon and inspects its submissions.
5. AI Operations Admin inspects a failed evaluation and retries it.
6. Administrator sees a failed dependency health check.
7. Security Admin searches audit events.
8. An unauthorized role is blocked from privileged actions.
9. A failed API request produces a useful error state.
10. The dashboard remains usable on mobile.

Use synthetic test records only in a clearly identified test environment.

# 22. Definition of Done

A screen is considered complete when:

- Its purpose and supported actions match this specification.
- It uses real backend data for implemented functionality.
- Authorization is enforced by the backend.
- Loading, empty, error, and success states are handled.
- Forms and destructive actions have appropriate validation and confirmation.
- Sensitive data is protected.
- Important administrative actions are auditable.
- Tests cover core success and failure paths.
- Responsive layouts and accessibility have been checked.
- No critical security issues remain.
- Documentation describes the route, API dependencies, permissions, and known limitations.

# 23. Recommended Implementation Sequence

Build in small, testable phases.

**Phase 1 — Foundation**
- Establish the Next.js application structure.
- Configure design tokens, typography, and Lucide icons.
- Build the global admin shell.
- Connect authentication and permission-aware navigation.
- Create reusable tables, status labels, dialogs, and page states.

**Phase 2 — Read-only operational visibility**
- Implement Dashboard Overview.
- Implement Organizations list and detail views.
- Implement Users & Access directory.
- Implement Hackathons list and detail views.
- Connect real API endpoints and pagination.

**Phase 3 — AI Operations**
- Implement job list and detail.
- Add pipeline timeline and sanitized logs.
- Add safe retry and cancellation where supported.
- Add model/provider status.

**Phase 4 — Reliability and security**
- Implement System Health.
- Implement Security & Audit.
- Implement integration status.
- Test authorization boundaries and failure handling.

**Phase 5 — Supporting workflows**
- Add essential Settings.
- Add Notifications and Support Center.
- Add advanced benchmarks and other P1 features.

**Phase 6 — Commercial and enterprise features**
- Add Plans & Billing only after the payment and subscription architecture is defined.
- Add advanced analytics and enterprise controls when there is a validated requirement.

## Final implementation rule

Do not generate the entire dashboard in one large coding pass. Complete each phase, test it, review the implementation against this specification, and only then continue.

The next technical deliverable should be the **shared architecture, database schema, and API contract specification**. That document will connect the Super Admin interface to Scorva's underlying platform and reduce costly redesign during implementation.
