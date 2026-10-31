import {
  HealthResponse,
  ApiResponseError,
  LoginResponse,
  MfaSetupResponse,
  AuthSuccessResponse,
  UserProfile,
  PaginatedUsersResponse,
  DashboardOverviewResponse,
  DashboardTrendsResponse,
  AuditEventsResponse,
  ConfigurationSetting,
  OrganizationStatus,
  OrgRole,
  OrganizationDetailResponse,
  OrganizationProfileResponse,
  OrganizationMemberResponse,
  PaginatedOrganizationsResponse,
  CreateOrganizationRequest,
  AdminUpdateOrganizationRequest,
  UpdateOrganizationStatusRequest,
  TransferOwnershipRequest,
  AdminAddMemberRequest,
  UpdateMemberRoleRequest,
  TenantUpdateOrganizationRequest,
  InviteMemberRequest,
  MemberOperationResponse,
  HackathonStatus,
  HackathonDetailResponse,
  PaginatedHackathonsResponse,
  CreateHackathonRequest,
  UpdateHackathonRequest,
  AdminUpdateHackathonStatusRequest,
  TenantUpdateHackathonStatusRequest,
  HackathonOverviewResponse,
  TeamListItem,
  TeamDetailResponse,
  CreateTeamRequest,
  JoinTeamRequest,
  SubmissionListItem,
  SubmissionDetailResponse,
  CreateSubmissionRequest,
  JudgeListItem,
  AssignJudgeRequest,
  RubricDetailResponse,
  CreateRubricRequest,
  AddCriterionRequest,
  ValidateRepositoryRequest,
  RepositoryValidationResult,
  LinkRepositoryRequest,
  UpdateBranchRequest,
  RepositoryActivityItem,
  SubmissionEvaluationTransparencyResponse,
  HackathonEvaluationSummaryResponse,
  EvaluationJobListItem,
  EvaluationJobResponse,
  JudgeAssignmentItem,
  JudgeQueueItem,
  JudgeSubmissionReviewResponse,
  SaveJudgeReviewRequest,
  SubmitJudgeReviewRequest,
  JudgeReviewDetail,
  OrganizerReviewProgressResponse,
  SubmissionReviewsResponse,
  JudgeHackathonDetail,
  ParticipantTeamItem,
  PermissionItem,
  RoleItem,
  CreateRoleRequest,
  UpdateRolePermissionsRequest,
  UserRoleAssignmentItem,
  LifecycleStageItem,
  ParticipantOverviewResponse,
  LeaderboardResponse,
  PerformanceResponse,
  ParticipantTaskItem,
  UpdateTaskStatusRequest,
  NotificationListResponse,
  SupportTicketItem,
  SupportReplyItem,
  SupportTicketDetailResponse,
  CreateSupportTicketRequest,
  CreateSupportReplyRequest,
  RegistrationStatusResponse,
  ParticipantProjectRegistrationRequest,
  ProjectRegistrationSuccessResponse,
  ParticipantPatTokenStatus,
  SaveParticipantPatRequest,
  SaveParticipantPatResponse,
  ParticipantGitHubSettingsResponse,
  VerifyParticipantGitHubResponse,
} from '@/types/api';

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export class ApiClientError extends Error {
  public code: string;
  public status: number;
  public details: unknown[];
  public requestId?: string;

  constructor(
    message: string,
    status: number,
    code: string = 'API_ERROR',
    details: unknown[] = [],
    requestId?: string
  ) {
    super(message);
    this.name = 'ApiClientError';
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

export async function fetchApi<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL.replace(/\/$/, '')}/${endpoint.replace(/^\//, '')}`;

  const headers = new Headers(options.headers || {});
  if (!headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 10000); // 10s timeout

  const effectiveSignal = options.signal
    ? typeof AbortSignal.any === 'function'
      ? AbortSignal.any([options.signal, controller.signal])
      : options.signal
    : controller.signal;

  try {
    const response = await fetch(url, {
      ...options,
      credentials: 'include',
      headers,
      signal: effectiveSignal,
    });

    if (!response.ok) {
      let errorBody: ApiResponseError | null = null;
      try {
        errorBody = await response.json();
      } catch {
        // Response was not JSON
      }

      if (errorBody) {
        const message =
          errorBody.detail ||
          errorBody.error?.message ||
          errorBody.title ||
          `HTTP Request failed with status ${response.status}`;
        const code = errorBody.code || errorBody.error?.code || 'API_ERROR';
        const details = (errorBody.invalid_params || errorBody.error?.details || []) as unknown[];
        const requestId = errorBody.request_id || errorBody.error?.request_id;

        throw new ApiClientError(
          message,
          response.status,
          code,
          details,
          requestId
        );
      }

      throw new ApiClientError(
        `HTTP Request failed with status ${response.status}`,
        response.status
      );
    }

    return (await response.json()) as T;
  } catch (err: unknown) {
    if (err instanceof ApiClientError) {
      throw err;
    }

    if (err instanceof DOMException && err.name === 'AbortError') {
      if (options.signal?.aborted) {
        throw new ApiClientError('Request was aborted', 0, 'REQUEST_ABORTED');
      }
      throw new ApiClientError('Request timed out after 10 seconds', 408, 'REQUEST_TIMEOUT');
    }

    throw new ApiClientError(
      err instanceof Error ? err.message : 'Unknown network error',
      0,
      'NETWORK_ERROR'
    );
  } finally {
    clearTimeout(timeoutId);
  }
}

export const api = {
  // Health
  getHealth: async (): Promise<HealthResponse> => {
    return fetchApi<HealthResponse>('/api/v1/health');
  },
  getLiveness: async (): Promise<{ status: string; timestamp: string }> => {
    return fetchApi<{ status: string; timestamp: string }>('/api/v1/health/live');
  },
  getReadiness: async (): Promise<HealthResponse> => {
    return fetchApi<HealthResponse>('/api/v1/health/ready');
  },

  // Auth
  login: async (email: string, password: string, redirectUrl?: string): Promise<LoginResponse> => {
    return fetchApi<LoginResponse>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password, redirect_url: redirectUrl }),
    });
  },
  setupMfa: async (enrollmentToken: string): Promise<MfaSetupResponse> => {
    return fetchApi<MfaSetupResponse>('/api/v1/auth/mfa/setup', {
      method: 'POST',
      body: JSON.stringify({ enrollment_token: enrollmentToken }),
    });
  },
  verifyMfa: async (token: string, totpCode: string): Promise<AuthSuccessResponse> => {
    return fetchApi<AuthSuccessResponse>('/api/v1/auth/mfa/verify', {
      method: 'POST',
      body: JSON.stringify({ token, totp_code: totpCode }),
    });
  },
  getMe: async (): Promise<UserProfile> => {
    return fetchApi<UserProfile>('/api/v1/auth/me');
  },
  logout: async (): Promise<{ message: string }> => {
    return fetchApi<{ message: string }>('/api/v1/auth/logout', {
      method: 'POST',
    });
  },

  // Users Directory & Session Revocation
  getUsers: async (params?: {
    page?: number;
    limit?: number;
    search?: string;
    role?: string;
    status?: string;
    sort_by?: string;
    sort_order?: 'asc' | 'desc';
  }, options?: RequestInit): Promise<PaginatedUsersResponse> => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set('page', String(params.page));
    if (params?.limit) searchParams.set('limit', String(params.limit));
    if (params?.search) searchParams.set('search', params.search);
    if (params?.role) searchParams.set('role', params.role);
    if (params?.status) searchParams.set('status', params.status);
    if (params?.sort_by) searchParams.set('sort_by', params.sort_by);
    if (params?.sort_order) searchParams.set('sort_order', params.sort_order);

    const qs = searchParams.toString();
    return fetchApi<PaginatedUsersResponse>(`/api/v1/admin/users${qs ? `?${qs}` : ''}`, options);
  },
  updateUserStatus: async (userId: string, isActive: boolean, reason?: string): Promise<UserProfile> => {
    return fetchApi<UserProfile>(`/api/v1/admin/users/${userId}/status`, {
      method: 'POST',
      body: JSON.stringify({ is_active: isActive, reason }),
    });
  },
  revokeUserSessions: async (userId: string): Promise<{ message: string }> => {
    return fetchApi<{ message: string }>(`/api/v1/admin/users/${userId}/revoke-sessions`, {
      method: 'POST',
    });
  },

  // Security Audit Log
  getAuditEvents: async (params?: {
    actor_email?: string;
    action?: string;
    resource_type?: string;
    organization_id?: string;
    limit?: number;
    offset?: number;
  }, options?: RequestInit): Promise<AuditEventsResponse> => {
    const searchParams = new URLSearchParams();
    if (params?.actor_email) searchParams.set('actor_email', params.actor_email);
    if (params?.action) searchParams.set('action', params.action);
    if (params?.resource_type) searchParams.set('resource_type', params.resource_type);
    if (params?.organization_id) searchParams.set('organization_id', params.organization_id);
    if (params?.limit) searchParams.set('limit', String(params.limit));
    if (params?.offset) searchParams.set('offset', String(params.offset));

    const qs = searchParams.toString();
    const endpoint = `/api/v1/admin/security/audit-events${qs ? `?${qs}` : ''}`;
    return fetchApi<AuditEventsResponse>(endpoint, options);
  },

  // ==========================================
  // Platform Admin: Dashboard Overview
  getDashboardOverview: async (options?: RequestInit & { refresh?: boolean }): Promise<DashboardOverviewResponse> => {
    const qs = options?.refresh ? '?refresh=true' : '';
    return fetchApi<DashboardOverviewResponse>(`/api/v1/admin/dashboard/overview${qs}`, options);
  },

  getDashboardTrends: async (params?: { period?: string }, options?: RequestInit): Promise<DashboardTrendsResponse> => {
    const qs = params?.period ? `?period=${encodeURIComponent(params.period)}` : '';
    return fetchApi<DashboardTrendsResponse>(`/api/v1/admin/dashboard/trends${qs}`, options);
  },

  // Platform Admin: Organizations
  // ==========================================
  getAdminOrganizations: async (params?: {
    page?: number;
    limit?: number;
    search?: string;
    status?: OrganizationStatus;
    sort_by?: string;
    sort_order?: 'asc' | 'desc';
  }, options?: RequestInit): Promise<PaginatedOrganizationsResponse> => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set('page', String(params.page));
    if (params?.limit) searchParams.set('limit', String(params.limit));
    if (params?.search) searchParams.set('search', params.search);
    if (params?.status) searchParams.set('status', params.status);
    if (params?.sort_by) searchParams.set('sort_by', params.sort_by);
    if (params?.sort_order) searchParams.set('sort_order', params.sort_order);

    const qs = searchParams.toString();
    return fetchApi<PaginatedOrganizationsResponse>(`/api/v1/admin/organizations${qs ? `?${qs}` : ''}`, options);
  },

  createAdminOrganization: async (
    data: CreateOrganizationRequest
  ): Promise<OrganizationDetailResponse> => {
    return fetchApi<OrganizationDetailResponse>('/api/v1/admin/organizations', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  getAdminOrganization: async (
    orgId: string,
    options?: RequestInit
  ): Promise<OrganizationDetailResponse> => {
    return fetchApi<OrganizationDetailResponse>(`/api/v1/admin/organizations/${orgId}`, options);
  },

  updateAdminOrganization: async (
    orgId: string,
    data: AdminUpdateOrganizationRequest
  ): Promise<OrganizationDetailResponse> => {
    return fetchApi<OrganizationDetailResponse>(`/api/v1/admin/organizations/${orgId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  updateAdminOrganizationStatus: async (
    orgId: string,
    data: UpdateOrganizationStatusRequest
  ): Promise<OrganizationDetailResponse> => {
    return fetchApi<OrganizationDetailResponse>(`/api/v1/admin/organizations/${orgId}/status`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  transferAdminOrganizationOwnership: async (
    orgId: string,
    data: TransferOwnershipRequest
  ): Promise<OrganizationDetailResponse> => {
    return fetchApi<OrganizationDetailResponse>(`/api/v1/admin/organizations/${orgId}/transfer-ownership`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  getAdminOrganizationMembers: async (
    orgId: string,
    options?: RequestInit
  ): Promise<OrganizationMemberResponse[]> => {
    return fetchApi<OrganizationMemberResponse[]>(`/api/v1/admin/organizations/${orgId}/members`, options);
  },

  addAdminOrganizationMember: async (
    orgId: string,
    data: AdminAddMemberRequest
  ): Promise<OrganizationMemberResponse> => {
    return fetchApi<OrganizationMemberResponse>(`/api/v1/admin/organizations/${orgId}/members`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  updateAdminOrganizationMemberRole: async (
    orgId: string,
    userId: string,
    data: UpdateMemberRoleRequest
  ): Promise<OrganizationMemberResponse> => {
    return fetchApi<OrganizationMemberResponse>(`/api/v1/admin/organizations/${orgId}/members/${userId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  removeAdminOrganizationMember: async (
    orgId: string,
    userId: string
  ): Promise<MemberOperationResponse> => {
    return fetchApi<MemberOperationResponse>(`/api/v1/admin/organizations/${orgId}/members/${userId}`, {
      method: 'DELETE',
    });
  },

  // ==========================================
  // Platform Admin: Hackathons
  // ==========================================
  getAdminHackathons: async (params?: {
    page?: number;
    limit?: number;
    search?: string;
    status?: HackathonStatus;
    organization_id?: string;
    sort_by?: string;
    sort_order?: 'asc' | 'desc';
  }, options?: RequestInit): Promise<PaginatedHackathonsResponse> => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set('page', String(params.page));
    if (params?.limit) searchParams.set('limit', String(params.limit));
    if (params?.search) searchParams.set('search', params.search);
    if (params?.status) searchParams.set('status', params.status);
    if (params?.organization_id) searchParams.set('organization_id', params.organization_id);
    if (params?.sort_by) searchParams.set('sort_by', params.sort_by);
    if (params?.sort_order) searchParams.set('sort_order', params.sort_order);

    const qs = searchParams.toString();
    return fetchApi<PaginatedHackathonsResponse>(`/api/v1/admin/hackathons${qs ? `?${qs}` : ''}`, options);
  },

  getAdminHackathon: async (
    hackathonId: string,
    options?: RequestInit
  ): Promise<HackathonDetailResponse> => {
    return fetchApi<HackathonDetailResponse>(`/api/v1/admin/hackathons/${hackathonId}`, options);
  },

  overrideAdminHackathonStatus: async (
    hackathonId: string,
    data: AdminUpdateHackathonStatusRequest
  ): Promise<HackathonDetailResponse> => {
    return fetchApi<HackathonDetailResponse>(`/api/v1/admin/hackathons/${hackathonId}/status`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  // ==========================================
  // Tenant Scoped: Organizations & Hackathons
  // ==========================================
  getTenantOrganizationProfile: async (
    orgId: string,
    options?: RequestInit
  ): Promise<OrganizationProfileResponse> => {
    return fetchApi<OrganizationProfileResponse>(`/api/v1/organizations/${orgId}`, options);
  },

  updateTenantOrganizationProfile: async (
    orgId: string,
    data: TenantUpdateOrganizationRequest
  ): Promise<OrganizationProfileResponse> => {
    return fetchApi<OrganizationProfileResponse>(`/api/v1/organizations/${orgId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  getTenantOrganizationMembers: async (
    orgId: string,
    options?: RequestInit
  ): Promise<OrganizationMemberResponse[]> => {
    return fetchApi<OrganizationMemberResponse[]>(`/api/v1/organizations/${orgId}/members`, options);
  },

  inviteTenantOrganizationMember: async (
    orgId: string,
    data: InviteMemberRequest
  ): Promise<OrganizationMemberResponse> => {
    return fetchApi<OrganizationMemberResponse>(`/api/v1/organizations/${orgId}/members`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  updateTenantOrganizationMemberRole: async (
    orgId: string,
    userId: string,
    data: UpdateMemberRoleRequest
  ): Promise<OrganizationMemberResponse> => {
    return fetchApi<OrganizationMemberResponse>(`/api/v1/organizations/${orgId}/members/${userId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  removeTenantOrganizationMember: async (
    orgId: string,
    userId: string
  ): Promise<MemberOperationResponse> => {
    return fetchApi<MemberOperationResponse>(`/api/v1/organizations/${orgId}/members/${userId}`, {
      method: 'DELETE',
    });
  },

  transferTenantOrganizationOwnership: async (
    orgId: string,
    data: TransferOwnershipRequest
  ): Promise<OrganizationProfileResponse> => {
    return fetchApi<OrganizationProfileResponse>(`/api/v1/organizations/${orgId}/transfer-ownership`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  getTenantHackathons: async (
    orgId: string,
    params?: {
      page?: number;
      limit?: number;
      search?: string;
      status?: HackathonStatus;
      sort_by?: string;
      sort_order?: 'asc' | 'desc';
    },
    options?: RequestInit
  ): Promise<PaginatedHackathonsResponse> => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set('page', String(params.page));
    if (params?.limit) searchParams.set('limit', String(params.limit));
    if (params?.search) searchParams.set('search', params.search);
    if (params?.status) searchParams.set('status', params.status);
    if (params?.sort_by) searchParams.set('sort_by', params.sort_by);
    if (params?.sort_order) searchParams.set('sort_order', params.sort_order);

    const qs = searchParams.toString();
    return fetchApi<PaginatedHackathonsResponse>(`/api/v1/organizations/${orgId}/hackathons${qs ? `?${qs}` : ''}`, options);
  },

  createTenantHackathon: async (
    orgId: string,
    data: CreateHackathonRequest
  ): Promise<HackathonDetailResponse> => {
    return fetchApi<HackathonDetailResponse>(`/api/v1/organizations/${orgId}/hackathons`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  getTenantHackathon: async (
    orgId: string,
    hackathonId: string,
    options?: RequestInit
  ): Promise<HackathonDetailResponse> => {
    return fetchApi<HackathonDetailResponse>(`/api/v1/organizations/${orgId}/hackathons/${hackathonId}`, options);
  },

  updateTenantHackathon: async (
    orgId: string,
    hackathonId: string,
    data: UpdateHackathonRequest
  ): Promise<HackathonDetailResponse> => {
    return fetchApi<HackathonDetailResponse>(`/api/v1/organizations/${orgId}/hackathons/${hackathonId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  publishTenantHackathon: async (
    orgId: string,
    hackathonId: string
  ): Promise<HackathonDetailResponse> => {
    return fetchApi<HackathonDetailResponse>(`/api/v1/organizations/${orgId}/hackathons/${hackathonId}/publish`, {
      method: 'POST',
    });
  },

  completeTenantHackathon: async (
    orgId: string,
    hackathonId: string
  ): Promise<HackathonDetailResponse> => {
    return fetchApi<HackathonDetailResponse>(`/api/v1/organizations/${orgId}/hackathons/${hackathonId}/complete`, {
      method: 'POST',
    });
  },

  archiveTenantHackathon: async (
    orgId: string,
    hackathonId: string
  ): Promise<HackathonDetailResponse> => {
    return fetchApi<HackathonDetailResponse>(`/api/v1/organizations/${orgId}/hackathons/${hackathonId}/archive`, {
      method: 'POST',
    });
  },

  updateTenantHackathonStatus: async (
    orgId: string,
    hackathonId: string,
    data: TenantUpdateHackathonStatusRequest
  ): Promise<HackathonDetailResponse> => {
    return fetchApi<HackathonDetailResponse>(`/api/v1/organizations/${orgId}/hackathons/${hackathonId}/status`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  publishHackathonResults: async (
    orgId: string,
    hackathonId: string
  ): Promise<HackathonDetailResponse> => {
    return fetchApi<HackathonDetailResponse>(`/api/v1/organizations/${orgId}/hackathons/${hackathonId}/publish-results`, {
      method: 'POST',
    });
  },

  unpublishHackathonResults: async (
    orgId: string,
    hackathonId: string
  ): Promise<HackathonDetailResponse> => {
    return fetchApi<HackathonDetailResponse>(`/api/v1/organizations/${orgId}/hackathons/${hackathonId}/unpublish-results`, {
      method: 'POST',
    });
  },

  // ==========================================
  // Platform Admin: Configuration Settings
  // ==========================================
  getConfigurationSettings: async (): Promise<ConfigurationSetting[]> => {
    return fetchApi<ConfigurationSetting[]>('/api/v1/admin/configuration');
  },

  getConfigurationSetting: async (key: string): Promise<ConfigurationSetting> => {
    return fetchApi<ConfigurationSetting>(`/api/v1/admin/configuration/${key}`);
  },

  updateConfigurationSetting: async (
    key: string,
    value: string,
    expectedVersion: number,
    changeReason?: string
  ): Promise<ConfigurationSetting> => {
    return fetchApi<ConfigurationSetting>(`/api/v1/admin/configuration/${key}`, {
      method: 'PUT',
      body: JSON.stringify({
        value,
        expected_version: expectedVersion,
        change_reason: changeReason,
      }),
    });
  },

  // ==========================================
  // Phase 6 Hackathon Subresources
  // ==========================================
  getHackathonOverview: async (
    orgId: string,
    hackathonId: string,
    options?: RequestInit
  ): Promise<HackathonOverviewResponse> => {
    return fetchApi<HackathonOverviewResponse>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/overview`,
      options
    );
  },

  getHackathonTeams: async (
    orgId: string,
    hackathonId: string,
    options?: RequestInit
  ): Promise<TeamListItem[]> => {
    return fetchApi<TeamListItem[]>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/teams`,
      options
    );
  },

  createHackathonTeam: async (
    orgId: string,
    hackathonId: string,
    data: CreateTeamRequest
  ): Promise<TeamDetailResponse> => {
    return fetchApi<TeamDetailResponse>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/teams`,
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );
  },

  getHackathonTeam: async (
    orgId: string,
    hackathonId: string,
    teamId: string,
    options?: RequestInit
  ): Promise<TeamDetailResponse> => {
    return fetchApi<TeamDetailResponse>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/teams/${teamId}`,
      options
    );
  },

  joinHackathonTeam: async (
    orgId: string,
    hackathonId: string,
    data: JoinTeamRequest
  ): Promise<TeamDetailResponse> => {
    return fetchApi<TeamDetailResponse>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/teams/join`,
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );
  },

  getHackathonSubmissions: async (
    orgId: string,
    hackathonId: string,
    options?: RequestInit
  ): Promise<SubmissionListItem[]> => {
    return fetchApi<SubmissionListItem[]>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/submissions`,
      options
    );
  },

  createHackathonSubmission: async (
    orgId: string,
    hackathonId: string,
    data: CreateSubmissionRequest
  ): Promise<SubmissionDetailResponse> => {
    return fetchApi<SubmissionDetailResponse>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/submissions`,
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );
  },

  getHackathonSubmission: async (
    orgId: string,
    hackathonId: string,
    submissionId: string,
    options?: RequestInit
  ): Promise<SubmissionDetailResponse> => {
    return fetchApi<SubmissionDetailResponse>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/submissions/${submissionId}`,
      options
    );
  },

  validateRepository: async (
    orgId: string,
    hackathonId: string,
    data: ValidateRepositoryRequest
  ): Promise<RepositoryValidationResult> => {
    return fetchApi<RepositoryValidationResult>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/repositories/validate`,
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );
  },

  linkSubmissionRepository: async (
    orgId: string,
    hackathonId: string,
    submissionId: string,
    data: LinkRepositoryRequest
  ): Promise<SubmissionDetailResponse> => {
    return fetchApi<SubmissionDetailResponse>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/submissions/${submissionId}/link-repository`,
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );
  },

  updateSubmissionBranch: async (
    orgId: string,
    hackathonId: string,
    submissionId: string,
    data: UpdateBranchRequest
  ): Promise<SubmissionDetailResponse> => {
    return fetchApi<SubmissionDetailResponse>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/submissions/${submissionId}/branch`,
      {
        method: 'PATCH',
        body: JSON.stringify(data),
      }
    );
  },

  refreshSubmissionVerification: async (
    orgId: string,
    hackathonId: string,
    submissionId: string
  ): Promise<SubmissionDetailResponse> => {
    return fetchApi<SubmissionDetailResponse>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/submissions/${submissionId}/verify`,
      {
        method: 'POST',
      }
    );
  },

  unlinkSubmissionRepository: async (
    orgId: string,
    hackathonId: string,
    submissionId: string
  ): Promise<SubmissionDetailResponse> => {
    return fetchApi<SubmissionDetailResponse>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/submissions/${submissionId}/unlink-repository`,
      {
        method: 'POST',
      }
    );
  },

  getSubmissionActivity: async (
    orgId: string,
    hackathonId: string,
    submissionId: string,
    options?: RequestInit
  ): Promise<RepositoryActivityItem[]> => {
    return fetchApi<RepositoryActivityItem[]>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/submissions/${submissionId}/activity`,
      options
    );
  },

  getHackathonActivity: async (
    orgId: string,
    hackathonId: string,
    options?: RequestInit
  ): Promise<RepositoryActivityItem[]> => {
    return fetchApi<RepositoryActivityItem[]>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/activity`,
      options
    );
  },

  getHackathonJudges: async (
    orgId: string,
    hackathonId: string,
    options?: RequestInit
  ): Promise<JudgeListItem[]> => {
    return fetchApi<JudgeListItem[]>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/judges`,
      options
    );
  },

  assignHackathonJudge: async (
    orgId: string,
    hackathonId: string,
    data: AssignJudgeRequest
  ): Promise<JudgeListItem> => {
    return fetchApi<JudgeListItem>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/judges`,
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );
  },

  removeHackathonJudge: async (
    orgId: string,
    hackathonId: string,
    judgeUserId: string
  ): Promise<void> => {
    await fetchApi<void>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/judges/${judgeUserId}`,
      {
        method: 'DELETE',
      }
    );
  },

  getHackathonRubric: async (
    orgId: string,
    hackathonId: string,
    options?: RequestInit
  ): Promise<RubricDetailResponse> => {
    return fetchApi<RubricDetailResponse>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/rubric`,
      options
    );
  },

  createHackathonRubric: async (
    orgId: string,
    hackathonId: string,
    data: CreateRubricRequest
  ): Promise<RubricDetailResponse> => {
    return fetchApi<RubricDetailResponse>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/rubrics`,
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );
  },

  addRubricCriterion: async (
    orgId: string,
    hackathonId: string,
    rubricId: string,
    data: AddCriterionRequest
  ): Promise<RubricDetailResponse> => {
    return fetchApi<RubricDetailResponse>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/rubrics/${rubricId}/criteria`,
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );
  },

  publishRubric: async (
    orgId: string,
    hackathonId: string,
    rubricId: string
  ): Promise<RubricDetailResponse> => {
    return fetchApi<RubricDetailResponse>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/rubrics/${rubricId}/publish`,
      {
        method: 'POST',
      }
    );
  },

  getSubmissionEvaluation: async (
    orgId: string,
    hackathonId: string,
    submissionId: string,
    jobId?: string,
    options?: RequestInit
  ): Promise<SubmissionEvaluationTransparencyResponse> => {
    const url = jobId
      ? `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/submissions/${submissionId}/evaluation?job_id=${encodeURIComponent(jobId)}`
      : `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/submissions/${submissionId}/evaluation`;
    return fetchApi<SubmissionEvaluationTransparencyResponse>(url, options);
  },

  getHackathonEvaluationSummary: async (
    orgId: string,
    hackathonId: string,
    options?: RequestInit
  ): Promise<HackathonEvaluationSummaryResponse> => {
    return fetchApi<HackathonEvaluationSummaryResponse>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/evaluations/summary`,
      options
    );
  },

  getHackathonEvaluations: async (
    orgId: string,
    hackathonId: string,
    status?: string,
    options?: RequestInit
  ): Promise<EvaluationJobListItem[]> => {
    const url = status
      ? `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/evaluations?status=${encodeURIComponent(status)}`
      : `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/evaluations`;
    return fetchApi<EvaluationJobListItem[]>(url, options);
  },

  triggerSubmissionEvaluation: async (
    orgId: string,
    hackathonId: string,
    submissionId: string,
    idempotencyKey?: string
  ): Promise<EvaluationJobResponse> => {
    const headers: Record<string, string> = {};
    if (idempotencyKey) {
      headers['Idempotency-Key'] = idempotencyKey;
    }
    return fetchApi<EvaluationJobResponse>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/submissions/${submissionId}/evaluate`,
      {
        method: 'POST',
        headers,
      }
    );
  },

  cancelEvaluationJob: async (
    orgId: string,
    jobId: string
  ): Promise<EvaluationJobResponse> => {
    return fetchApi<EvaluationJobResponse>(
      `/api/v1/organizations/${orgId}/evaluations/${jobId}/cancel`,
      {
        method: 'POST',
      }
    );
  },

  // Judge Workspace & Review Workflow (M6.5)
  getJudgeAssignments: async (
    options?: RequestInit
  ): Promise<JudgeAssignmentItem[]> => {
    return fetchApi<JudgeAssignmentItem[]>('/api/v1/judge/assignments', options);
  },

  getJudgeSubmissions: async (
    options?: RequestInit
  ): Promise<JudgeQueueItem[]> => {
    return fetchApi<JudgeQueueItem[]>('/api/v1/judge/submissions', options);
  },

  getJudgeQueue: async (
    orgId: string,
    hackathonId: string,
    options?: RequestInit
  ): Promise<JudgeQueueItem[]> => {
    return fetchApi<JudgeQueueItem[]>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/judge/queue`,
      options
    );
  },

  getSubmissionReview: async (
    orgId: string,
    hackathonId: string,
    submissionId: string,
    judgeId?: string,
    options?: RequestInit
  ): Promise<JudgeSubmissionReviewResponse> => {
    const url = judgeId
      ? `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/submissions/${submissionId}/review?judge_id=${encodeURIComponent(judgeId)}`
      : `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/submissions/${submissionId}/review`;
    return fetchApi<JudgeSubmissionReviewResponse>(url, options);
  },

  saveSubmissionReviewDraft: async (
    orgId: string,
    hackathonId: string,
    submissionId: string,
    data: SaveJudgeReviewRequest
  ): Promise<JudgeReviewDetail> => {
    return fetchApi<JudgeReviewDetail>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/submissions/${submissionId}/review`,
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );
  },

  submitSubmissionReview: async (
    orgId: string,
    hackathonId: string,
    submissionId: string,
    data: SubmitJudgeReviewRequest
  ): Promise<JudgeReviewDetail> => {
    return fetchApi<JudgeReviewDetail>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/submissions/${submissionId}/review/submit`,
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );
  },

  // Dedicated Judge Workspace & Review Endpoints (Tenant-Isolated from Org Layout)
  getJudgeHackathonDetail: async (
    hackathonId: string,
    options?: RequestInit
  ): Promise<JudgeHackathonDetail> => {
    return fetchApi<JudgeHackathonDetail>(
      `/api/v1/judge/hackathons/${hackathonId}`,
      options
    );
  },

  getJudgeHackathonSubmissions: async (
    hackathonId: string,
    options?: RequestInit
  ): Promise<JudgeQueueItem[]> => {
    return fetchApi<JudgeQueueItem[]>(
      `/api/v1/judge/hackathons/${hackathonId}/submissions`,
      options
    );
  },

  getJudgeSubmissionReview: async (
    hackathonId: string,
    submissionId: string,
    options?: RequestInit
  ): Promise<JudgeSubmissionReviewResponse> => {
    return fetchApi<JudgeSubmissionReviewResponse>(
      `/api/v1/judge/hackathons/${hackathonId}/submissions/${submissionId}/review`,
      options
    );
  },

  saveJudgeSubmissionReviewDraft: async (
    hackathonId: string,
    submissionId: string,
    data: SaveJudgeReviewRequest
  ): Promise<JudgeReviewDetail> => {
    return fetchApi<JudgeReviewDetail>(
      `/api/v1/judge/hackathons/${hackathonId}/submissions/${submissionId}/review`,
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );
  },

  submitJudgeSubmissionReview: async (
    hackathonId: string,
    submissionId: string,
    data: SubmitJudgeReviewRequest
  ): Promise<JudgeReviewDetail> => {
    return fetchApi<JudgeReviewDetail>(
      `/api/v1/judge/hackathons/${hackathonId}/submissions/${submissionId}/review/submit`,
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );
  },

  submitJudgeReview: async (
    hackathonId: string,
    submissionId: string,
    data: SubmitJudgeReviewRequest
  ): Promise<JudgeReviewDetail> => {
    return fetchApi<JudgeReviewDetail>(
      `/api/v1/judge/hackathons/${hackathonId}/submissions/${submissionId}/review/submit`,
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );
  },

  getJudgeSubmissionTransparency: async (
    hackathonId: string,
    submissionId: string,
    options?: RequestInit
  ): Promise<SubmissionEvaluationTransparencyResponse> => {
    return fetchApi<SubmissionEvaluationTransparencyResponse>(
      `/api/v1/judge/hackathons/${hackathonId}/submissions/${submissionId}/transparency`,
      options
    );
  },

  // Participant Workspace
  getParticipantTeams: async (
    options?: RequestInit
  ): Promise<ParticipantTeamItem[]> => {
    return fetchApi<ParticipantTeamItem[]>(
      '/api/v1/participant/teams',
      options
    );
  },

  getHackathonReviewProgress: async (
    orgId: string,
    hackathonId: string,
    options?: RequestInit
  ): Promise<OrganizerReviewProgressResponse> => {
    return fetchApi<OrganizerReviewProgressResponse>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/reviews/progress`,
      options
    );
  },

  getSubmissionAllReviews: async (
    orgId: string,
    hackathonId: string,
    submissionId: string,
    options?: RequestInit
  ): Promise<SubmissionReviewsResponse> => {
    return fetchApi<SubmissionReviewsResponse>(
      `/api/v1/organizations/${orgId}/hackathons/${hackathonId}/submissions/${submissionId}/reviews`,
      options
    );
  },

  // Platform Admin: Roles & Permissions (RBAC)
  getPermissions: async (options?: RequestInit): Promise<PermissionItem[]> => {
    return fetchApi<PermissionItem[]>('/api/v1/admin/permissions', options);
  },

  getRoles: async (
    params?: { scope_type?: string; scope_id?: string },
    options?: RequestInit
  ): Promise<RoleItem[]> => {
    const searchParams = new URLSearchParams();
    if (params?.scope_type) searchParams.set('scope_type', params.scope_type);
    if (params?.scope_id) searchParams.set('scope_id', params.scope_id);
    const qs = searchParams.toString();
    return fetchApi<RoleItem[]>(`/api/v1/admin/roles${qs ? `?${qs}` : ''}`, options);
  },

  createRole: async (
    data: CreateRoleRequest
  ): Promise<RoleItem> => {
    return fetchApi<RoleItem>('/api/v1/admin/roles', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  updateRolePermissions: async (
    roleId: string,
    data: UpdateRolePermissionsRequest
  ): Promise<RoleItem> => {
    return fetchApi<RoleItem>(`/api/v1/admin/roles/${roleId}/permissions`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  // Participant Workspace
  getParticipantOverview: async (
    options?: RequestInit
  ): Promise<ParticipantOverviewResponse> => {
    return fetchApi<ParticipantOverviewResponse>('/api/v1/participant/overview', options);
  },

  getParticipantLeaderboard: async (
    hackathonId?: string,
    options?: RequestInit
  ): Promise<LeaderboardResponse> => {
    const qs = hackathonId ? `?hackathon_id=${encodeURIComponent(hackathonId)}` : '';
    return fetchApi<LeaderboardResponse>(`/api/v1/participant/leaderboard${qs}`, options);
  },

  getParticipantPerformance: async (
    hackathonId?: string,
    options?: RequestInit
  ): Promise<PerformanceResponse> => {
    const qs = hackathonId ? `?hackathon_id=${encodeURIComponent(hackathonId)}` : '';
    return fetchApi<PerformanceResponse>(`/api/v1/participant/performance${qs}`, options);
  },

  getParticipantTasks: async (
    options?: RequestInit
  ): Promise<ParticipantTaskItem[]> => {
    return fetchApi<ParticipantTaskItem[]>('/api/v1/participant/tasks', options);
  },

  updateParticipantTaskStatus: async (
    taskId: string,
    status: 'new' | 'in_progress' | 'completed'
  ): Promise<{ status: string; task_id: string; new_status: string }> => {
    return fetchApi<{ status: string; task_id: string; new_status: string }>(
      `/api/v1/participant/tasks/${encodeURIComponent(taskId)}/status`,
      {
        method: 'POST',
        body: JSON.stringify({ status }),
      }
    );
  },

  getParticipantNotifications: async (
    options?: RequestInit
  ): Promise<NotificationListResponse> => {
    return fetchApi<NotificationListResponse>('/api/v1/participant/notifications', options);
  },

  markParticipantNotificationRead: async (
    notificationId: string
  ): Promise<{ status: string; notification_id: string }> => {
    return fetchApi<{ status: string; notification_id: string }>(
      `/api/v1/participant/notifications/${encodeURIComponent(notificationId)}/read`,
      {
        method: 'POST',
      }
    );
  },

  markAllParticipantNotificationsRead: async (): Promise<{ status: string; count: number }> => {
    return fetchApi<{ status: string; count: number }>(
      '/api/v1/participant/notifications/read-all',
      {
        method: 'POST',
      }
    );
  },

  getParticipantSupportTickets: async (
    options?: RequestInit
  ): Promise<SupportTicketItem[]> => {
    return fetchApi<SupportTicketItem[]>('/api/v1/participant/support/tickets', options);
  },

  createParticipantSupportTicket: async (
    data: CreateSupportTicketRequest
  ): Promise<SupportTicketItem> => {
    return fetchApi<SupportTicketItem>('/api/v1/participant/support/tickets', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  getParticipantSupportTicketDetail: async (
    ticketId: string,
    options?: RequestInit
  ): Promise<SupportTicketDetailResponse> => {
    return fetchApi<SupportTicketDetailResponse>(
      `/api/v1/participant/support/tickets/${encodeURIComponent(ticketId)}`,
      options
    );
  },

  replyParticipantSupportTicket: async (
    ticketId: string,
    data: CreateSupportReplyRequest
  ): Promise<SupportReplyItem> => {
    return fetchApi<SupportReplyItem>(
      `/api/v1/participant/support/tickets/${encodeURIComponent(ticketId)}/replies`,
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );
  },

  getParticipantRegistrationStatus: async (
    options?: RequestInit
  ): Promise<RegistrationStatusResponse> => {
    return fetchApi<RegistrationStatusResponse>(
      '/api/v1/participant/registration-status',
      options
    );
  },

  registerParticipantProject: async (
    data: ParticipantProjectRegistrationRequest
  ): Promise<ProjectRegistrationSuccessResponse> => {
    return fetchApi<ProjectRegistrationSuccessResponse>(
      '/api/v1/participant/register-project',
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );
  },

  getParticipantPatStatus: async (
    options?: RequestInit
  ): Promise<ParticipantPatTokenStatus> => {
    return fetchApi<ParticipantPatTokenStatus>(
      '/api/v1/participant/settings/pat',
      options
    );
  },

  saveParticipantPat: async (
    data: SaveParticipantPatRequest
  ): Promise<SaveParticipantPatResponse> => {
    return fetchApi<SaveParticipantPatResponse>(
      '/api/v1/participant/settings/pat',
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );
  },

  deleteParticipantPat: async (): Promise<{ status: string; message: string }> => {
    return fetchApi<{ status: string; message: string }>(
      '/api/v1/participant/settings/pat',
      {
        method: 'DELETE',
      }
    );
  },

  getParticipantGitHubSettings: async (
    options?: RequestInit
  ): Promise<ParticipantGitHubSettingsResponse> => {
    return fetchApi<ParticipantGitHubSettingsResponse>(
      '/api/v1/participant/settings/github',
      options
    );
  },

  verifyParticipantGitHubRepository: async (): Promise<VerifyParticipantGitHubResponse> => {
    return fetchApi<VerifyParticipantGitHubResponse>(
      '/api/v1/participant/settings/github/verify',
      {
        method: 'POST',
      }
    );
  },
};
