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

export interface UserProfile {
  id: string;
  email: string;
  full_name: string;
  platform_role: string | null;
  mfa_enabled: boolean;
  is_active: boolean;
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
  message: string;
}

export type LoginResponse = LoginSuccessResponse | LoginMfaRequiredResponse;

export interface MfaSetupResponse {
  secret: string;
  qr_code_uri: string;
}

export interface AuthSuccessResponse {
  user: UserProfile;
  message: string;
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

