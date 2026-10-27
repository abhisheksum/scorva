export type HealthStatus = 'healthy' | 'degraded' | 'unhealthy' | 'unknown';

export interface ServiceCheck {
  status: HealthStatus;
  latency_ms?: number;
  details?: string;
}

export interface HealthResponse {
  status: HealthStatus;
  app_name: string;
  environment: string;
  version: string;
  timestamp: string;
  services: Record<string, ServiceCheck>;
}

export interface ApiErrorDetail {
  field?: string;
  issue?: string;
  reason?: string;
  type?: string;
}

export interface ApiErrorPayload {
  code: string;
  message: string;
  details: ApiErrorDetail[];
  request_id: string;
  timestamp: string;
}

export interface ProblemDetails {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  instance?: string;
  code?: string;
  request_id?: string;
  timestamp?: string;
  invalid_params?: ApiErrorDetail[];
  error?: ApiErrorPayload;
}

export interface ApiResponseError {
  error?: ApiErrorPayload;
  detail?: string;
  title?: string;
  code?: string;
  request_id?: string;
  invalid_params?: ApiErrorDetail[];
}

export interface AccessibleDestination {
  destination: string;
  label: string;
  role: string;
  context_id?: string | null;
}

export interface UserRoutingProfile {
  default_destination: string;
  accessible_destinations: AccessibleDestination[];
}

export interface UserProfile {
  id: string;
  email: string;
  full_name: string;
  platform_role: string | null;
  mfa_enabled: boolean;
  is_active: boolean;
  routing?: UserRoutingProfile;
  created_at?: string;
  last_login_at?: string | null;
}

export interface PaginatedUsersResponse {
  items: UserProfile[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

export interface DashboardMetricCounts {
  total_users: number;
  total_organizations: number;
  total_hackathons: number;
  total_submissions: number;
  evaluations_completed: number;
  evaluations_running: number;
  evaluations_failed: number;
}

export interface DashboardAuditEventItem {
  id: string;
  timestamp: string;
  actor_email: string;
  actor_role: string;
  action: string;
  resource_type: string;
  resource_id: string;
  outcome: string;
}

export interface DashboardOverviewResponse {
  counts: DashboardMetricCounts;
  recent_audits: DashboardAuditEventItem[];
  generated_at: string;
}

export interface DashboardTrendPoint {
  date: string;
  users: number;
  organizations: number;
  hackathons: number;
  submissions: number;
  evaluations: number;
}

export interface DashboardTrendsResponse {
  period: string;
  points: DashboardTrendPoint[];
}

export interface LoginMfaRequiredResponse {
  mfa_required: true;
  enrolled: boolean;
  enrollment_token?: string;
  challenge_token?: string;
}

export interface LoginSuccessResponse {
  mfa_required?: false;
  user: UserProfile;
  default_destination?: string;
  message: string;
}

export type LoginResponse = LoginSuccessResponse | LoginMfaRequiredResponse;

export interface MfaSetupResponse {
  secret: string;
  qr_code_uri: string;
}

export interface AuthSuccessResponse {
  user: UserProfile;
  default_destination?: string;
  message?: string;
}

export interface AuditEventItem {
  id: string;
  timestamp: string;
  actor_user_id: string | null;
  actor_email: string;
  actor_role: string;
  action: string;
  resource_type: string;
  resource_id: string;
  organization_id: string | null;
  outcome: 'SUCCESS' | 'FAILURE' | 'DENIED';
  reason: string | null;
  diff_payload: Record<string, unknown> | null;
  ip_address: string;
  user_agent: string;
  correlation_id: string;
}

export interface AuditEventsResponse {
  items: AuditEventItem[];
  total: number;
}

export interface ConfigurationSetting {
  key: string;
  tier: string;
  data_type: string;
  default_value: string;
  current_value: string;
  allow_org_override: boolean;
  allow_hackathon_override: boolean;
  min_value?: string | null;
  max_value?: string | null;
  is_configurable: boolean;
  version: number;
  effect_timing: string;
  description?: string | null;
  updated_at: string;
}

// ==========================================
// Organization Types (Phase 3)
// ==========================================

export type OrganizationStatus = 'active' | 'suspended' | 'archived';

export type OrgRole = 'org_owner' | 'org_admin' | 'organizer';

export type MembershipStatus = 'active' | 'suspended';

export interface OwnerSummary {
  id: string;
  email: string;
  full_name: string;
}

export interface UserSummary {
  id: string;
  email: string;
  full_name: string;
}

export interface OrganizationSummaryResponse {
  id: string;
  name: string;
  slug: string;
  status: OrganizationStatus;
  owner_id: string;
  owner_email?: string | null;
  owner_name?: string | null;
  owner?: OwnerSummary | null;
  member_count: number;
  hackathon_count: number;
  created_at: string;
  updated_at: string;
}

export interface OrganizationDetailResponse {
  id: string;
  name: string;
  slug: string;
  status: OrganizationStatus;
  owner_id: string;
  owner_email?: string | null;
  owner_name?: string | null;
  owner?: OwnerSummary | null;
  settings: Record<string, unknown>;
  member_count: number;
  hackathon_count: number;
  created_at: string;
  updated_at: string;
}

export interface OrganizationProfileResponse {
  id: string;
  name: string;
  slug: string;
  status: OrganizationStatus;
  owner_id: string;
  settings: Record<string, unknown>;
  current_user_role: OrgRole;
  created_at: string;
  updated_at: string;
}

export interface OrganizationMemberResponse {
  id: string;
  organization_id: string;
  user_id: string;
  email?: string | null;
  full_name?: string | null;
  user?: UserSummary | null;
  role: OrgRole;
  status: MembershipStatus;
  created_at: string;
  updated_at: string;
}

export interface PaginatedOrganizationsResponse {
  items: OrganizationSummaryResponse[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

export interface CreateOrganizationRequest {
  name: string;
  slug: string;
  owner_email: string;
  settings?: Record<string, unknown>;
}

export interface AdminUpdateOrganizationRequest {
  name?: string;
  slug?: string;
  settings?: Record<string, unknown>;
}

export interface UpdateOrganizationStatusRequest {
  status?: OrganizationStatus;
  is_active?: boolean;
  reason?: string;
}

export interface TransferOwnershipRequest {
  new_owner_user_id: string;
  reason?: string;
}

export interface AdminAddMemberRequest {
  user_id?: string;
  email?: string;
  role?: OrgRole;
}

export interface UpdateMemberRoleRequest {
  role: OrgRole;
}

export interface TenantUpdateOrganizationRequest {
  name?: string;
  settings?: Record<string, unknown>;
}

export interface InviteMemberRequest {
  email: string;
  role?: OrgRole;
}

export interface MemberOperationResponse {
  status: string;
  message: string;
}

// ==========================================
// Hackathon Types (Phase 3)
// ==========================================

export type HackathonStatus = 'draft' | 'published' | 'completed' | 'suspended' | 'archived';

export interface HackathonOrgSummary {
  id: string;
  name: string;
  slug: string;
}

export interface HackathonSummaryResponse {
  id: string;
  organization_id: string;
  title: string;
  slug: string;
  status: HackathonStatus;
  start_date: string;
  submission_deadline: string;
  end_date: string;
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
}

export interface HackathonDetailResponse {
  id: string;
  organization_id: string;
  title: string;
  slug: string;
  description?: string | null;
  status: HackathonStatus;
  start_date: string;
  submission_deadline: string;
  end_date: string;
  created_by_user_id: string;
  settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  organization?: HackathonOrgSummary | null;
  created_by?: UserSummary | null;
}

export interface PaginatedHackathonsResponse {
  items: HackathonDetailResponse[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

export interface CreateHackathonRequest {
  title: string;
  slug: string;
  description?: string;
  start_date: string;
  submission_deadline: string;
  end_date: string;
  settings?: Record<string, unknown>;
}

export interface UpdateHackathonRequest {
  title?: string;
  slug?: string;
  description?: string;
  start_date?: string;
  submission_deadline?: string;
  end_date?: string;
  settings?: Record<string, unknown>;
}

export interface AdminUpdateHackathonStatusRequest {
  status: HackathonStatus;
  reason: string;
}

export interface TenantUpdateHackathonStatusRequest {
  status: HackathonStatus;
  reason?: string;
}


// ==========================================
// Phase 6 Hackathon Subresources Types
// ==========================================

export interface HackathonOverviewResponse {
  hackathon_id: string;
  organization_id: string;
  title: string;
  status: string;
  total_teams: number;
  total_submissions: number;
  total_evaluations: number;
  completed_evaluations: number;
  pending_evaluations: number;
  total_judges: number;
  average_score?: number | null;
}

export interface TeamMemberInfo {
  id: string;
  user_id: string;
  role_in_team: 'leader' | 'member';
  joined_at: string;
  user_email?: string | null;
  user_name?: string | null;
}

export interface TeamSubmissionSummary {
  id: string;
  title: string;
  repository_url: string;
  target_branch: string;
  status: string;
}

export interface CreateTeamRequest {
  name: string;
}

export interface JoinTeamRequest {
  join_code: string;
}

export interface TeamListItem {
  id: string;
  organization_id: string;
  hackathon_id: string;
  name: string;
  join_code: string;
  created_by_user_id: string;
  created_at: string;
  member_count: number;
  submission?: TeamSubmissionSummary | null;
}

export interface TeamDetailResponse {
  id: string;
  organization_id: string;
  hackathon_id: string;
  name: string;
  join_code: string;
  created_by_user_id: string;
  created_at: string;
  members: TeamMemberInfo[];
  submission?: TeamSubmissionSummary | null;
}

export type RepositoryConnectionStatus = 'unverified' | 'verified' | 'failed' | 'unlinked';

export interface ValidateRepositoryRequest {
  repository_url: string;
  target_branch?: string;
}

export interface RepositoryValidationResult {
  is_valid_url: boolean;
  is_accessible: boolean;
  ownership_verified: boolean;
  owner?: string | null;
  repo?: string | null;
  default_branch?: string | null;
  target_branch?: string | null;
  commit_sha?: string | null;
  connection_status: RepositoryConnectionStatus;
  diagnostic_code?: string | null;
  message?: string | null;
  verified_at: string;
}

export interface LinkRepositoryRequest {
  repository_url: string;
  target_branch?: string;
}

export interface UpdateBranchRequest {
  target_branch: string;
}

export interface WebhookIngestResponse {
  status: string;
  delivery_id: string;
  event_type: string;
  canonical_repo_id?: string | null;
  submission_id?: string | null;
  diagnostic_code?: string | null;
  message?: string | null;
}

export interface RepositoryActivityItem {
  id: string;
  delivery_id: string;
  event_type: string;
  action?: string | null;
  organization_id?: string | null;
  hackathon_id?: string | null;
  submission_id?: string | null;
  repository_owner: string;
  repository_name: string;
  canonical_repo_id: string;
  ref?: string | null;
  commit_sha?: string | null;
  sender_login?: string | null;
  summary?: string | null;
  details: Record<string, unknown>;
  status: string;
  diagnostic_code?: string | null;
  event_timestamp: string;
  created_at: string;
}

export interface CreateSubmissionRequest {
  team_id: string;
  repository_url: string;
  target_branch?: string;
  title: string;
  description?: string;
}

export interface SubmissionListItem {
  id: string;
  organization_id: string;
  hackathon_id: string;
  team_id: string;
  team_name: string;
  repository_url: string;
  target_branch: string;
  title: string;
  description?: string | null;
  status: string;
  repository_owner?: string | null;
  repository_name?: string | null;
  default_branch?: string | null;
  verified_commit_sha?: string | null;
  connection_status: RepositoryConnectionStatus;
  verified_at?: string | null;
  verification_diagnostic?: string | null;
  created_at: string;
  updated_at: string;
  latest_job_id?: string | null;
  latest_job_status?: string | null;
  latest_score?: number | null;
}

export interface SubmissionDetailResponse {
  id: string;
  organization_id: string;
  hackathon_id: string;
  team_id: string;
  team_name: string;
  repository_url: string;
  target_branch: string;
  title: string;
  description?: string | null;
  status: string;
  repository_owner?: string | null;
  repository_name?: string | null;
  default_branch?: string | null;
  verified_commit_sha?: string | null;
  connection_status: RepositoryConnectionStatus;
  verified_at?: string | null;
  verification_diagnostic?: string | null;
  verification_error?: string | null;
  created_at: string;
  updated_at: string;
  snapshots_count: number;
  latest_job_id?: string | null;
  latest_job_status?: string | null;
  latest_score?: number | null;
  summary_assessment?: string | null;
}

export interface AssignJudgeRequest {
  user_id?: string;
  email?: string;
}

export interface JudgeListItem {
  id: string;
  hackathon_id: string;
  user_id: string;
  assigned_by_user_id?: string | null;
  created_at: string;
  user_email: string;
  user_name?: string | null;
}

export interface CreateRubricRequest {
  name: string;
  description?: string;
  scoring_mode?: string;
}

export interface AddCriterionRequest {
  title: string;
  description: string;
  weight: number | string;
  min_score?: number | string;
  max_score?: number | string;
  evidence_requirements?: string;
  order_index?: number;
}

export interface CriterionResponse {
  id: string;
  rubric_version_id: string;
  title: string;
  description: string;
  weight: number;
  min_score: number;
  max_score: number;
  evidence_requirements: string;
  order_index: number;
}

export interface RubricVersionDetail {
  id: string;
  rubric_id: string;
  version_number: number;
  status: 'draft' | 'published' | 'archived';
  published_at?: string | null;
  criteria: CriterionResponse[];
}

export interface RubricDetailResponse {
  id: string;
  organization_id: string;
  hackathon_id: string;
  name: string;
  description?: string | null;
  scoring_mode: string;
  created_at: string;
  active_version?: RubricVersionDetail | null;
}

// ==============================================================================
// Subsystem C Sub-Milestone 6.4: AI Evaluation Transparency Types
// ==============================================================================

export interface EvidenceReferenceDetail {
  id: string;
  file_path: string;
  start_line?: number | null;
  end_line?: number | null;
  snippet: string;
  is_verified_in_repo: boolean;
  verification_failure_reason?: string | null;
}

export interface CriterionScoreDetail {
  id: string;
  criterion_id: string;
  title: string;
  description: string;
  weight: number | string;
  min_score: number | string;
  max_score: number | string;
  order_index: number;
  awarded_score: number | string;
  normalized_criterion_score: number | string;
  confidence_score: number | string;
  rationale: string;
  evidence_status: 'verified' | 'partial' | 'missing';
  evidence_references: EvidenceReferenceDetail[];
}

export interface EvaluationResultDetail {
  id: string;
  attempt_number: number;
  model_provider: string;
  model_name: string;
  prompt_version: string;
  raw_score: number | string;
  normalized_score: number | string;
  summary_assessment: string;
  has_insufficient_evidence: boolean;
  created_at: string;
  criterion_scores: CriterionScoreDetail[];
}

export interface EvaluationJobSummary {
  id: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  current_stage?: string | null;
  attempts_count: number;
  max_attempts: number;
  error_code?: string | null;
  error_message?: string | null;
  is_retryable: boolean;
  cancellation_requested: boolean;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
}

export interface EvaluationRubricSummary {
  rubric_id: string;
  rubric_name: string;
  rubric_version_id: string;
  version_number: number;
  scoring_mode: string;
}

export interface EvaluationSnapshotSummary {
  snapshot_id: string;
  commit_sha: string;
  file_count: number;
  total_bytes: number;
  captured_at: string;
}

export interface PriorEvaluationRunSummary {
  job_id: string;
  status: string;
  attempts_count: number;
  raw_score?: number | string | null;
  normalized_score?: number | string | null;
  completed_at?: string | null;
  created_at: string;
}

export interface SubmissionEvaluationTransparencyResponse {
  submission_id: string;
  submission_title: string;
  team_name: string;
  repository_url: string;
  target_branch: string;
  verified_commit_sha?: string | null;
  can_evaluate: boolean;
  cannot_evaluate_reason?: string | null;
  has_evaluation: boolean;
  job?: EvaluationJobSummary | null;
  rubric?: EvaluationRubricSummary | null;
  snapshot?: EvaluationSnapshotSummary | null;
  result?: EvaluationResultDetail | null;
  prior_runs: PriorEvaluationRunSummary[];
}

export interface HackathonEvaluationSummaryResponse {
  total_submissions: number;
  evaluated_submissions: number;
  queued_jobs: number;
  running_jobs: number;
  completed_jobs: number;
  failed_jobs: number;
  cancelled_jobs: number;
  average_score?: number | string | null;
  has_published_rubric: boolean;
  published_rubric_id?: string | null;
  published_rubric_version_id?: string | null;
  published_rubric_name?: string | null;
}

export interface EvaluationJobListItem {
  id: string;
  submission_id: string;
  submission_title: string;
  team_name: string;
  status: string;
  current_stage?: string | null;
  attempts_count: number;
  max_attempts: number;
  raw_score?: number | string | null;
  normalized_score?: number | string | null;
  error_code?: string | null;
  created_at: string;
  completed_at?: string | null;
}

export interface EvaluationJobResponse {
  id: string;
  organization_id: string;
  hackathon_id: string;
  submission_id: string;
  snapshot_id: string;
  rubric_version_id: string;
  status: string;
  current_stage?: string | null;
  attempts_count: number;
  max_attempts: number;
  lock_version: number;
  idempotency_key?: string | null;
  request_fingerprint?: string | null;
  dispatch_generation: number;
  reevaluation_of_job_id?: string | null;
  cancellation_requested: boolean;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

// Sub-Milestone 6.5: Judge Review & Independent Human Decisions

export interface JudgeCriterionScoreInput {
  criterion_id: string;
  score: number | string;
  judge_notes?: string | null;
}

export interface SaveJudgeReviewRequest {
  overall_feedback?: string | null;
  decision?: string | null;
  criterion_scores?: JudgeCriterionScoreInput[];
  version?: number | null;
}

export interface SubmitJudgeReviewRequest {
  overall_feedback: string;
  decision?: string | null;
  criterion_scores: JudgeCriterionScoreInput[];
  version?: number | null;
}

export interface JudgeCriterionScoreDetail {
  id?: string | null;
  criterion_id: string;
  criterion_title: string;
  weight: number | string;
  min_score: number | string;
  max_score: number | string;
  score?: number | string | null;
  judge_notes?: string | null;
  ai_suggested_score?: number | string | null;
  ai_rationale?: string | null;
}

export interface JudgeReviewDetail {
  id: string;
  organization_id: string;
  hackathon_id: string;
  submission_id: string;
  rubric_version_id: string;
  judge_user_id: string;
  judge_name?: string | null;
  judge_email?: string | null;
  status: 'draft' | 'submitted';
  score?: number | string | null;
  overall_feedback?: string | null;
  decision?: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  submitted_at?: string | null;
  criterion_scores: JudgeCriterionScoreDetail[];
}

export interface JudgeSubmissionReviewResponse {
  submission_id: string;
  hackathon_id: string;
  organization_id: string;
  team_name: string;
  submission_title: string;
  repository_url: string;
  repository_owner?: string | null;
  repository_name?: string | null;
  target_branch: string;
  verified_commit_sha?: string | null;
  connection_status: string;
  rubric_id: string;
  rubric_version_id: string;
  rubric_name: string;
  rubric_criteria: {
    id: string;
    title: string;
    description?: string | null;
    weight: number | string;
    min_score: number | string;
    max_score: number | string;
    evidence_requirements?: string | null;
    order_index: number;
  }[];
  ai_evaluation?: EvaluationResultDetail | null;
  review?: JudgeReviewDetail | null;
  can_edit: boolean;
}

export interface JudgeQueueItem {
  submission_id: string;
  team_name: string;
  title: string;
  repository_owner?: string | null;
  repository_name?: string | null;
  target_branch: string;
  verified_commit_sha?: string | null;
  connection_status: string;
  ai_evaluation_status: string;
  ai_normalized_score?: number | string | null;
  review_status: 'not_started' | 'draft' | 'submitted';
  review_score?: number | string | null;
  review_submitted_at?: string | null;
  review_updated_at?: string | null;
}

export interface JudgeAssignmentItem {
  hackathon_id: string;
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  hackathon_title: string;
  hackathon_slug: string;
  hackathon_status: string;
  submission_deadline?: string | null;
  end_date?: string | null;
  assigned_at: string;
  total_submissions: number;
  my_draft_count: number;
  my_submitted_count: number;
  my_pending_count: number;
}

export interface JudgeProgressItem {
  judge_user_id: string;
  judge_name?: string | null;
  judge_email: string;
  assigned_at: string;
  submitted_count: number;
  draft_count: number;
  pending_count: number;
}

export interface SubmissionCoverageItem {
  submission_id: string;
  team_name: string;
  title: string;
  submitted_reviews_count: number;
  draft_reviews_count: number;
  average_human_score?: number | string | null;
}

export interface OrganizerReviewProgressResponse {
  total_submissions: number;
  total_judges: number;
  submissions_with_reviews: number;
  submissions_fully_reviewed: number;
  submissions_awaiting_review: number;
  draft_reviews_count: number;
  submitted_reviews_count: number;
  judge_progress: JudgeProgressItem[];
  submission_coverage: SubmissionCoverageItem[];
}

export interface SubmissionReviewsResponse {
  submission_id: string;
  reviews: JudgeReviewDetail[];
}

export interface JudgeHackathonDetail {
  hackathon_id: string;
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  hackathon_title: string;
  hackathon_slug: string;
  hackathon_status: string;
  description?: string | null;
  submission_deadline?: string | null;
  end_date?: string | null;
  total_submissions: number;
  my_draft_count: number;
  my_submitted_count: number;
  my_pending_count: number;
}

export interface ParticipantSubmissionSummary {
  submission_id: string;
  title: string;
  description?: string | null;
  repository_url: string;
  repository_owner?: string | null;
  repository_name?: string | null;
  default_branch?: string | null;
  verified_commit_sha?: string | null;
  connection_status: string;
  status: string;
  verified_at?: string | null;
}

export interface ParticipantTeamItem {
  team_id: string;
  team_name: string;
  join_code: string;
  role_in_team: string;
  joined_at: string;
  hackathon_id: string;
  hackathon_title: string;
  hackathon_status: string;
  submission_deadline?: string | null;
  organization_id: string;
  organization_name: string;
  submission?: ParticipantSubmissionSummary | null;
}

// ==========================================
// RBAC: Roles & Permissions Types (Phase 4)
// ==========================================

export interface PermissionItem {
  id: string;
  domain: string;
  action: string;
  min_scope: string;
  is_delegable: boolean;
  description: string;
}

export interface RoleItem {
  id: string;
  name: string;
  display_name: string;
  scope_type: 'platform' | 'organization' | 'hackathon' | string;
  scope_id: string;
  is_system: boolean;
  is_immutable: boolean;
  permissions: string[];
  created_at: string;
}

export interface CreateRoleRequest {
  name: string;
  display_name: string;
  scope_type: 'platform' | 'organization' | 'hackathon';
  scope_id?: string;
  permissions?: string[];
}

export interface UpdateRolePermissionsRequest {
  permissions: string[];
  change_reason?: string;
}

export interface UserRoleAssignmentItem {
  id: string;
  user_id: string;
  role_id: string;
  role_name?: string;
  scope_type: string;
  scope_id: string;
  assigned_by_user_id?: string | null;
  created_at: string;
}


