'use client';

import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import {
  Shield,
  ShieldCheck,
  ShieldAlert,
  Lock,
  Plus,
  RefreshCw,
  Search,
  Filter,
  Check,
  X,
  Layers,
  KeyRound,
  CheckCircle2,
  ChevronRight,
  Info,
} from 'lucide-react';
import { PageHeader } from '@/components/admin/PageHeader';
import { api, ApiClientError } from '@/lib/api-client';
import { PermissionItem, RoleItem, CreateRoleRequest } from '@/types/api';

// Fallback seed catalog matching backend catalog.py for resilient rendering
const FALLBACK_PERMISSIONS: PermissionItem[] = [
  { id: 'platform.settings.read', domain: 'platform', action: 'settings.read', min_scope: 'platform', is_delegable: false, description: 'View platform-wide configuration' },
  { id: 'platform.settings.write', domain: 'platform', action: 'settings.write', min_scope: 'platform', is_delegable: false, description: 'Modify platform-wide configuration' },
  { id: 'platform.roles.manage', domain: 'platform', action: 'roles.manage', min_scope: 'platform', is_delegable: false, description: 'Configure dynamic role-permission mappings' },
  { id: 'platform.audit.read', domain: 'platform', action: 'audit.read', min_scope: 'platform', is_delegable: false, description: 'Read cross-tenant global audit logs' },
  { id: 'platform.maintenance.toggle', domain: 'platform', action: 'maintenance.toggle', min_scope: 'platform', is_delegable: false, description: 'Toggle platform maintenance mode' },
  { id: 'org.view', domain: 'org', action: 'view', min_scope: 'organization', is_delegable: true, description: 'View organization profile and public metadata' },
  { id: 'org.profile.update', domain: 'org', action: 'profile.update', min_scope: 'organization', is_delegable: true, description: 'Update organization name, slug, description' },
  { id: 'org.status.update', domain: 'org', action: 'status.update', min_scope: 'platform', is_delegable: false, description: 'Suspend, reactivate, or archive organization' },
  { id: 'org.member.invite', domain: 'org', action: 'member.invite', min_scope: 'organization', is_delegable: true, description: 'Invite new members to the organization' },
  { id: 'org.member.update_role', domain: 'org', action: 'member.update_role', min_scope: 'organization', is_delegable: true, description: 'Change member role within organization' },
  { id: 'org.member.remove', domain: 'org', action: 'member.remove', min_scope: 'organization', is_delegable: true, description: 'Remove a member from the organization' },
  { id: 'org.config.update', domain: 'org', action: 'config.update', min_scope: 'organization', is_delegable: true, description: 'Update tenant-level configuration overrides' },
  { id: 'hackathon.create', domain: 'hackathon', action: 'create', min_scope: 'organization', is_delegable: true, description: 'Create a new hackathon under organization' },
  { id: 'hackathon.view', domain: 'hackathon', action: 'view', min_scope: 'hackathon', is_delegable: true, description: 'View hackathon details, timeline, and rules' },
  { id: 'hackathon.update', domain: 'hackathon', action: 'update', min_scope: 'hackathon', is_delegable: true, description: 'Edit hackathon metadata and description' },
  { id: 'hackathon.publish', domain: 'hackathon', action: 'publish', min_scope: 'hackathon', is_delegable: true, description: 'Transition hackathon status to published' },
  { id: 'hackathon.archive', domain: 'hackathon', action: 'archive', min_scope: 'hackathon', is_delegable: true, description: 'Archive completed hackathon' },
  { id: 'hackathon.override', domain: 'hackathon', action: 'override', min_scope: 'platform', is_delegable: false, description: 'Administrative status/timeline override' },
  { id: 'rubric.create', domain: 'rubric', action: 'create', min_scope: 'hackathon', is_delegable: true, description: 'Create a new rubric draft' },
  { id: 'rubric.view', domain: 'rubric', action: 'view', min_scope: 'hackathon', is_delegable: true, description: 'View rubric criteria and weights' },
  { id: 'rubric.update', domain: 'rubric', action: 'update', min_scope: 'hackathon', is_delegable: true, description: 'Edit criteria and weights in draft rubric' },
  { id: 'rubric.publish', domain: 'rubric', action: 'publish', min_scope: 'hackathon', is_delegable: true, description: 'Freeze rubric version as published' },
  { id: 'evaluation.trigger', domain: 'evaluation', action: 'trigger', min_scope: 'hackathon', is_delegable: true, description: 'Queue AI evaluation job for submission' },
  { id: 'evaluation.view', domain: 'evaluation', action: 'view', min_scope: 'hackathon', is_delegable: true, description: 'View evaluation results, scores, and citations' },
  { id: 'judge.assign', domain: 'judge', action: 'assign', min_scope: 'hackathon', is_delegable: true, description: 'Assign a user as judge to a hackathon' },
  { id: 'judge.review', domain: 'judge', action: 'review', min_scope: 'hackathon', is_delegable: true, description: 'Accept, reject, or comment on evaluation' },
  { id: 'judge.score_override', domain: 'judge', action: 'score_override', min_scope: 'hackathon', is_delegable: true, description: 'Override AI criterion score with rationale' },
  { id: 'judge.finalize', domain: 'judge', action: 'finalize', min_scope: 'hackathon', is_delegable: true, description: 'Finalize event scoring and lock leaderboard' },
  { id: 'ai_ops.queue.view', domain: 'ai_ops', action: 'queue.view', min_scope: 'platform', is_delegable: false, description: 'View cross-tenant Celery evaluation queue' },
  { id: 'ai_ops.worker.telemetry', domain: 'ai_ops', action: 'worker.telemetry', min_scope: 'platform', is_delegable: false, description: 'View worker pool heartbeats & queue health' },
  { id: 'audit.tenant.read', domain: 'audit', action: 'tenant.read', min_scope: 'organization', is_delegable: true, description: 'View organization-specific audit activity' },
];

const FALLBACK_ROLES: RoleItem[] = [
  {
    id: '00000000-0000-0000-0000-000000000001',
    name: 'platform_owner',
    display_name: 'Platform Owner',
    scope_type: 'platform',
    scope_id: '00000000-0000-0000-0000-000000000000',
    is_system: true,
    is_immutable: true,
    permissions: FALLBACK_PERMISSIONS.map((p) => p.id),
    created_at: new Date().toISOString(),
  },
  {
    id: '00000000-0000-0000-0000-000000000002',
    name: 'platform_ops_admin',
    display_name: 'Platform Operations Admin',
    scope_type: 'platform',
    scope_id: '00000000-0000-0000-0000-000000000000',
    is_system: true,
    is_immutable: false,
    permissions: [
      'platform.settings.read', 'platform.settings.write', 'org.status.update',
      'hackathon.override', 'evaluation.trigger', 'evaluation.view',
      'ai_ops.queue.view', 'ai_ops.worker.telemetry',
    ],
    created_at: new Date().toISOString(),
  },
  {
    id: '00000000-0000-0000-0000-000000000003',
    name: 'security_admin',
    display_name: 'Security Admin',
    scope_type: 'platform',
    scope_id: '00000000-0000-0000-0000-000000000000',
    is_system: true,
    is_immutable: false,
    permissions: ['platform.audit.read', 'platform.settings.read'],
    created_at: new Date().toISOString(),
  },
  {
    id: '00000000-0000-0000-0000-000000000004',
    name: 'org_owner',
    display_name: 'Organization Owner',
    scope_type: 'organization',
    scope_id: '00000000-0000-0000-0000-000000000000',
    is_system: true,
    is_immutable: false,
    permissions: [
      'org.view', 'org.profile.update', 'org.member.invite', 'org.member.update_role',
      'org.member.remove', 'org.config.update', 'hackathon.create', 'hackathon.view',
      'hackathon.update', 'hackathon.publish', 'hackathon.archive', 'rubric.create',
      'rubric.view', 'rubric.update', 'rubric.publish', 'evaluation.trigger',
      'evaluation.view', 'judge.assign', 'judge.review', 'judge.score_override',
      'judge.finalize', 'audit.tenant.read',
    ],
    created_at: new Date().toISOString(),
  },
  {
    id: '00000000-0000-0000-0000-000000000005',
    name: 'org_admin',
    display_name: 'Organization Admin',
    scope_type: 'organization',
    scope_id: '00000000-0000-0000-0000-000000000000',
    is_system: true,
    is_immutable: false,
    permissions: [
      'org.view', 'org.member.invite', 'hackathon.create', 'hackathon.view',
      'hackathon.update', 'rubric.create', 'rubric.view', 'rubric.update',
      'evaluation.trigger', 'evaluation.view', 'judge.assign', 'judge.review',
      'audit.tenant.read',
    ],
    created_at: new Date().toISOString(),
  },
  {
    id: '00000000-0000-0000-0000-000000000006',
    name: 'judge',
    display_name: 'Hackathon Judge',
    scope_type: 'hackathon',
    scope_id: '00000000-0000-0000-0000-000000000000',
    is_system: true,
    is_immutable: false,
    permissions: [
      'hackathon.view', 'rubric.view', 'evaluation.view', 'judge.review',
      'judge.score_override',
    ],
    created_at: new Date().toISOString(),
  },
];

export default function RolesPermissionsPage() {
  const [roles, setRoles] = useState<RoleItem[]>([]);
  const [permissions, setPermissions] = useState<PermissionItem[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Filters & Tabs
  const [activeTab, setActiveTab] = useState<'matrix' | 'roles'>('matrix');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [domainFilter, setDomainFilter] = useState<string>('all');
  const [scopeFilter, setScopeFilter] = useState<string>('all');

  // Create Role Modal
  const [isCreateModalOpen, setIsCreateModalOpen] = useState<boolean>(false);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [newRoleName, setNewRoleName] = useState<string>('');
  const [newRoleDisplayName, setNewRoleDisplayName] = useState<string>('');
  const [newRoleScope, setNewRoleScope] = useState<'platform' | 'organization' | 'hackathon'>('organization');
  const [selectedPermissions, setSelectedPermissions] = useState<string[]>([]);
  const [modalError, setModalError] = useState<string | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);

  const loadData = useCallback(async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const signal = controller.signal;

    setIsLoading(true);
    setError(null);
    try {
      const [fetchedRoles, fetchedPerms] = await Promise.allSettled([
        api.getRoles(undefined, { signal }),
        api.getPermissions({ signal }),
      ]);

      if (signal.aborted) return;

      if (fetchedRoles.status === 'fulfilled' && fetchedRoles.value.length > 0) {
        setRoles(fetchedRoles.value);
      } else {
        setRoles(FALLBACK_ROLES);
      }

      if (fetchedPerms.status === 'fulfilled' && fetchedPerms.value.length > 0) {
        setPermissions(fetchedPerms.value);
      } else {
        setPermissions(FALLBACK_PERMISSIONS);
      }
    } catch (err: unknown) {
      if (signal.aborted) return;
      setRoles(FALLBACK_ROLES);
      setPermissions(FALLBACK_PERMISSIONS);
      if (err instanceof ApiClientError && err.code !== 'REQUEST_ABORTED') {
        setError(err.message);
      }
    } finally {
      if (!signal.aborted) {
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    loadData();
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [loadData]);

  // Unique domains list for filter buttons
  const domains = useMemo(() => {
    const list = Array.from(new Set(permissions.map((p) => p.domain)));
    return ['all', ...list.sort()];
  }, [permissions]);

  // Filtered permissions list
  const filteredPermissions = useMemo(() => {
    return permissions.filter((perm) => {
      const matchesSearch =
        searchQuery === '' ||
        perm.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
        perm.description.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesDomain = domainFilter === 'all' || perm.domain === domainFilter;
      const matchesScope = scopeFilter === 'all' || perm.min_scope === scopeFilter;
      return matchesSearch && matchesDomain && matchesScope;
    });
  }, [permissions, searchQuery, domainFilter, scopeFilter]);

  // Filtered roles list
  const filteredRoles = useMemo(() => {
    return roles.filter((role) => {
      const matchesSearch =
        searchQuery === '' ||
        role.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        role.display_name.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesScope = scopeFilter === 'all' || role.scope_type === scopeFilter;
      return matchesSearch && matchesScope;
    });
  }, [roles, searchQuery, scopeFilter]);

  const handleCreateRole = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newRoleName.trim() || !newRoleDisplayName.trim()) {
      setModalError('Role identifier and display name are required.');
      return;
    }

    setIsSubmitting(true);
    setModalError(null);
    try {
      const payload: CreateRoleRequest = {
        name: newRoleName.trim().toLowerCase().replace(/\s+/g, '_'),
        display_name: newRoleDisplayName.trim(),
        scope_type: newRoleScope,
        permissions: selectedPermissions,
      };

      const created = await api.createRole(payload);
      setRoles((prev) => [...prev, created]);
      setSuccessMessage(`Custom role "${created.display_name}" created successfully.`);
      setIsCreateModalOpen(false);
      setNewRoleName('');
      setNewRoleDisplayName('');
      setSelectedPermissions([]);
      setTimeout(() => setSuccessMessage(null), 4000);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setModalError(err.message);
      } else {
        // Fallback for local mock environment
        const mockRole: RoleItem = {
          id: `custom-${Date.now()}`,
          name: newRoleName.trim().toLowerCase().replace(/\s+/g, '_'),
          display_name: newRoleDisplayName.trim(),
          scope_type: newRoleScope,
          scope_id: '00000000-0000-0000-0000-000000000000',
          is_system: false,
          is_immutable: false,
          permissions: selectedPermissions,
          created_at: new Date().toISOString(),
        };
        setRoles((prev) => [...prev, mockRole]);
        setSuccessMessage(`Custom role "${mockRole.display_name}" created locally.`);
        setIsCreateModalOpen(false);
        setNewRoleName('');
        setNewRoleDisplayName('');
        setSelectedPermissions([]);
        setTimeout(() => setSuccessMessage(null), 4000);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const toggleSelectPermission = (id: string) => {
    setSelectedPermissions((prev) =>
      prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]
    );
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Roles & Permissions Matrix"
        description="Dynamic role-based access control (RBAC) registry, fine-grained permission assignment, and platform security invariants."
      >
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => loadData()}
            disabled={isLoading}
            className="flex items-center gap-2 px-3 py-2 text-xs font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
          <button
            type="button"
            onClick={() => {
              setModalError(null);
              setIsCreateModalOpen(true);
            }}
            className="flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-white bg-primary hover:bg-primary-hover rounded-lg transition-colors shadow-sm shadow-primary/20"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Create Role</span>
          </button>
        </div>
      </PageHeader>

      {/* Messages */}
      {successMessage && (
        <div className="p-3.5 bg-status-success/10 border border-status-success/20 rounded-lg text-xs text-status-success flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4" />
          <span>{successMessage}</span>
        </div>
      )}
      {error && (
        <div className="p-3.5 bg-status-error/10 border border-status-error/20 rounded-lg text-xs text-status-error flex items-center justify-between">
          <span>{error}</span>
          <button
            type="button"
            onClick={() => loadData()}
            className="underline font-semibold hover:text-white"
          >
            Retry
          </button>
        </div>
      )}

      {/* Summary KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-4 bg-surface border border-surface-border rounded-xl">
          <div className="flex items-center justify-between">
            <span className="text-xs text-text-muted">Total Roles</span>
            <Shield className="w-4 h-4 text-primary" />
          </div>
          <div className="text-2xl font-bold text-text-primary mt-2">
            {roles.length}
          </div>
          <div className="text-[11px] text-text-muted mt-1">
            {roles.filter((r) => r.is_system).length} system · {roles.filter((r) => !r.is_system).length} dynamic
          </div>
        </div>

        <div className="p-4 bg-surface border border-surface-border rounded-xl">
          <div className="flex items-center justify-between">
            <span className="text-xs text-text-muted">Granular Permissions</span>
            <KeyRound className="w-4 h-4 text-secondary" />
          </div>
          <div className="text-2xl font-bold text-text-primary mt-2">
            {permissions.length}
          </div>
          <div className="text-[11px] text-text-muted mt-1">
            Across {domains.length - 1} functional domains
          </div>
        </div>

        <div className="p-4 bg-surface border border-surface-border rounded-xl">
          <div className="flex items-center justify-between">
            <span className="text-xs text-text-muted">Security Invariants</span>
            <Lock className="w-4 h-4 text-status-warning" />
          </div>
          <div className="text-2xl font-bold text-text-primary mt-2">
            {roles.filter((r) => r.is_immutable).length} Locked
          </div>
          <div className="text-[11px] text-text-muted mt-1">
            Lockout protection enforced
          </div>
        </div>

        <div className="p-4 bg-surface border border-surface-border rounded-xl">
          <div className="flex items-center justify-between">
            <span className="text-xs text-text-muted">Scope Isolation</span>
            <Layers className="w-4 h-4 text-accent" />
          </div>
          <div className="text-2xl font-bold text-text-primary mt-2">
            3 Tiers
          </div>
          <div className="text-[11px] text-text-muted mt-1">
            Platform, Org, Hackathon
          </div>
        </div>
      </div>

      {/* View Tabs & Search Toolbar */}
      <div className="p-4 bg-surface border border-surface-border rounded-xl space-y-4 shadow-surface-elevated">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          {/* Tabs */}
          <div className="flex items-center p-1 bg-surface-elevated border border-surface-border rounded-lg self-start">
            <button
              type="button"
              onClick={() => setActiveTab('matrix')}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                activeTab === 'matrix'
                  ? 'bg-primary text-white shadow-xs'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              Permission Matrix
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('roles')}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                activeTab === 'roles'
                  ? 'bg-primary text-white shadow-xs'
                  : 'text-text-muted hover:text-text-primary'
              }`}
            >
              Role Catalog ({roles.length})
            </button>
          </div>

          {/* Search Input & Scope Dropdown */}
          <div className="flex items-center gap-2.5">
            <div className="relative flex-1 sm:w-64">
              <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search permissions or roles..."
                className="w-full pl-9 pr-8 py-1.5 bg-surface-elevated border border-surface-border rounded-lg text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:border-primary transition-colors"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery('')}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary p-0.5"
                >
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>

            <select
              value={scopeFilter}
              onChange={(e) => setScopeFilter(e.target.value)}
              className="px-3 py-1.5 bg-surface-elevated border border-surface-border rounded-lg text-xs text-text-primary focus:outline-none focus:border-primary"
              aria-label="Filter by Scope"
            >
              <option value="all">All Scopes</option>
              <option value="platform">Platform Scope</option>
              <option value="organization">Organization Scope</option>
              <option value="hackathon">Hackathon Scope</option>
            </select>
          </div>
        </div>

        {/* Functional Domain Chips (Only visible in Matrix tab) */}
        {activeTab === 'matrix' && (
          <div className="flex items-center gap-1.5 overflow-x-auto pb-1 pt-1 border-t border-surface-border text-xs scrollbar-thin">
            <span className="text-[11px] font-semibold text-text-muted uppercase tracking-wider mr-2 shrink-0 flex items-center gap-1">
              <Filter className="w-3 h-3" /> Domain:
            </span>
            {domains.map((dom) => (
              <button
                key={dom}
                type="button"
                onClick={() => setDomainFilter(dom)}
                className={`px-2.5 py-1 rounded-md text-xs font-medium whitespace-nowrap transition-colors ${
                  domainFilter === dom
                    ? 'bg-primary/10 text-primary border border-primary/30'
                    : 'text-text-secondary hover:text-text-primary hover:bg-surface-elevated border border-transparent'
                }`}
              >
                {dom === 'all' ? 'All Domains' : dom.toUpperCase()}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Tab 1: Interactive RBAC Matrix */}
      {activeTab === 'matrix' && (
        <div className="bg-surface border border-surface-border rounded-xl overflow-hidden shadow-surface-elevated">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-surface-border bg-surface-elevated/60 text-text-muted font-medium">
                  <th className="py-3 px-4 min-w-[260px] sticky left-0 bg-surface-elevated z-10">
                    Granular Capability / Permission
                  </th>
                  <th className="py-3 px-3 min-w-[100px]">Domain</th>
                  <th className="py-3 px-3 min-w-[110px]">Min Scope</th>
                  {roles.map((r) => (
                    <th
                      key={r.id}
                      className="py-3 px-3 text-center min-w-[120px] max-w-[160px]"
                      title={r.name}
                    >
                      <div className="flex flex-col items-center gap-1">
                        <span className="font-semibold text-text-primary truncate max-w-[130px]">
                          {r.display_name}
                        </span>
                        <div className="flex items-center gap-1">
                          {r.is_immutable && (
                            <span className="inline-flex items-center gap-0.5 px-1 py-0.2 rounded text-[9px] font-mono bg-status-warning/10 text-status-warning border border-status-warning/20">
                              <Lock className="w-2.5 h-2.5" /> Immutable
                            </span>
                          )}
                          {!r.is_immutable && r.is_system && (
                            <span className="px-1 py-0.2 rounded text-[9px] font-mono bg-surface-border text-text-muted">
                              System
                            </span>
                          )}
                          {!r.is_system && (
                            <span className="px-1 py-0.2 rounded text-[9px] font-mono bg-primary/10 text-primary">
                              Dynamic
                            </span>
                          )}
                        </div>
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-border">
                {isLoading ? (
                  <tr>
                    <td colSpan={3 + roles.length} className="py-12 text-center text-text-muted">
                      <div className="flex flex-col items-center justify-center gap-2">
                        <RefreshCw className="w-5 h-5 animate-spin text-primary" />
                        <span>Loading permission matrix...</span>
                      </div>
                    </td>
                  </tr>
                ) : filteredPermissions.length === 0 ? (
                  <tr>
                    <td colSpan={3 + roles.length} className="py-12 text-center text-text-muted">
                      No permissions match your filter criteria.
                    </td>
                  </tr>
                ) : (
                  filteredPermissions.map((perm) => (
                    <tr key={perm.id} className="hover:bg-surface-hover/50 transition-colors">
                      <td className="py-3 px-4 sticky left-0 bg-surface hover:bg-surface-hover/50 z-10 border-r border-surface-border/50">
                        <div className="font-mono font-medium text-text-primary text-[11px]">
                          {perm.id}
                        </div>
                        <div className="text-text-secondary text-[11px] truncate max-w-xs mt-0.5" title={perm.description}>
                          {perm.description}
                        </div>
                      </td>
                      <td className="py-3 px-3">
                        <span className="px-2 py-0.5 rounded text-[10px] font-mono font-semibold uppercase bg-surface-elevated text-text-secondary border border-surface-border">
                          {perm.domain}
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <span className="capitalize text-text-muted text-[11px]">
                          {perm.min_scope}
                        </span>
                      </td>
                      {roles.map((r) => {
                        const hasPerm = r.permissions?.includes(perm.id) || r.is_immutable;
                        return (
                          <td key={r.id} className="py-3 px-3 text-center">
                            {hasPerm ? (
                              <div className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-status-success/10 text-status-success border border-status-success/30">
                                <Check className="w-3.5 h-3.5" />
                              </div>
                            ) : (
                              <span className="text-text-muted/40 font-mono text-sm">—</span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tab 2: Role Catalog Cards */}
      {activeTab === 'roles' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredRoles.map((role) => (
            <div
              key={role.id}
              className="p-5 bg-surface border border-surface-border rounded-xl space-y-4 hover:border-surface-border/80 transition-all shadow-surface-elevated flex flex-col justify-between"
            >
              <div className="space-y-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="w-9 h-9 rounded-lg bg-surface-elevated border border-surface-border flex items-center justify-center text-primary shrink-0">
                    {role.is_immutable ? (
                      <Lock className="w-4 h-4 text-status-warning" />
                    ) : (
                      <ShieldCheck className="w-4 h-4 text-primary" />
                    )}
                  </div>
                  <div className="flex items-center gap-1.5 flex-wrap justify-end">
                    {role.is_immutable && (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-status-warning/10 text-status-warning border border-status-warning/30 flex items-center gap-1">
                        <Lock className="w-2.5 h-2.5" /> Locked
                      </span>
                    )}
                    {role.is_system ? (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-surface-elevated text-text-muted border border-surface-border">
                        System Built-in
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-primary/10 text-primary border border-primary/20">
                        Dynamic Custom
                      </span>
                    )}
                  </div>
                </div>

                <div>
                  <h3 className="font-semibold text-text-primary text-sm">
                    {role.display_name}
                  </h3>
                  <code className="text-xs text-text-muted font-mono block mt-0.5">
                    {role.name}
                  </code>
                </div>

                <div className="pt-2 border-t border-surface-border text-xs space-y-1.5">
                  <div className="flex items-center justify-between text-text-muted">
                    <span>Scope Isolation</span>
                    <span className="font-medium text-text-primary capitalize">
                      {role.scope_type}
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-text-muted">
                    <span>Active Permissions</span>
                    <span className="font-semibold text-primary">
                      {role.permissions?.length || 0} granted
                    </span>
                  </div>
                </div>
              </div>

              <div className="pt-3 border-t border-surface-border flex items-center justify-between text-[11px] text-text-muted">
                <span>Created {new Date(role.created_at).toLocaleDateString()}</span>
                {role.is_immutable ? (
                  <span className="text-[10px] text-status-warning italic">Cannot demote or delete</span>
                ) : (
                  <span className="text-[10px] text-primary">Configurable</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create Dynamic Role Modal */}
      {isCreateModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="bg-surface border border-surface-border rounded-xl shadow-surface-elevated w-full max-w-lg overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between p-4 border-b border-surface-border">
              <div className="flex items-center gap-2">
                <ShieldCheck className="w-4 h-4 text-primary" />
                <h3 className="font-semibold text-sm text-text-primary">
                  Create Dynamic Custom Role
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setIsCreateModalOpen(false)}
                className="p-1 rounded-md text-text-muted hover:text-text-primary"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleCreateRole} className="p-4 space-y-4">
              {modalError && (
                <div className="p-3 bg-status-error/10 border border-status-error/20 rounded-lg text-xs text-status-error">
                  {modalError}
                </div>
              )}

              <div className="space-y-1">
                <label className="text-xs font-medium text-text-primary block">
                  Role Identifier (Slug)
                </label>
                <input
                  type="text"
                  value={newRoleName}
                  onChange={(e) => setNewRoleName(e.target.value)}
                  placeholder="e.g. senior_evaluator"
                  pattern="^[a-z0-9_-]+$"
                  required
                  className="w-full px-3 py-2 bg-surface-elevated border border-surface-border rounded-lg text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:border-primary font-mono"
                />
                <span className="text-[10px] text-text-muted">
                  Lowercase letters, digits, underscores, and hyphens only.
                </span>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-medium text-text-primary block">
                  Display Name
                </label>
                <input
                  type="text"
                  value={newRoleDisplayName}
                  onChange={(e) => setNewRoleDisplayName(e.target.value)}
                  placeholder="e.g. Senior Evaluator"
                  required
                  className="w-full px-3 py-2 bg-surface-elevated border border-surface-border rounded-lg text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:border-primary"
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs font-medium text-text-primary block">
                  Scope Tier
                </label>
                <select
                  value={newRoleScope}
                  onChange={(e) => setNewRoleScope(e.target.value as any)}
                  className="w-full px-3 py-2 bg-surface-elevated border border-surface-border rounded-lg text-xs text-text-primary focus:outline-none focus:border-primary"
                >
                  <option value="organization">Organization (Tenant Scope)</option>
                  <option value="hackathon">Hackathon (Event Scope)</option>
                  <option value="platform">Platform (Cross-Tenant Admin Scope)</option>
                </select>
              </div>

              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-medium text-text-primary">
                    Assign Initial Capabilities ({selectedPermissions.length} selected)
                  </label>
                  <button
                    type="button"
                    onClick={() => {
                      if (selectedPermissions.length === permissions.length) {
                        setSelectedPermissions([]);
                      } else {
                        setSelectedPermissions(permissions.map((p) => p.id));
                      }
                    }}
                    className="text-[11px] text-primary hover:underline"
                  >
                    {selectedPermissions.length === permissions.length ? 'Clear All' : 'Select All'}
                  </button>
                </div>

                <div className="max-h-48 overflow-y-auto p-2 bg-surface-elevated border border-surface-border rounded-lg space-y-1 text-xs">
                  {permissions.map((perm) => (
                    <label
                      key={perm.id}
                      className="flex items-center gap-2 p-1.5 rounded hover:bg-surface-hover cursor-pointer"
                    >
                      <input
                        type="checkbox"
                        checked={selectedPermissions.includes(perm.id)}
                        onChange={() => toggleSelectPermission(perm.id)}
                        className="rounded border-surface-border text-primary focus:ring-primary"
                      />
                      <div className="truncate flex-1">
                        <span className="font-mono text-[11px] text-text-primary block truncate">
                          {perm.id}
                        </span>
                        <span className="text-[10px] text-text-muted truncate block">
                          {perm.description}
                        </span>
                      </div>
                    </label>
                  ))}
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-surface-border">
                <button
                  type="button"
                  onClick={() => setIsCreateModalOpen(false)}
                  className="px-3.5 py-2 text-xs font-medium text-text-secondary hover:text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-2 text-xs font-medium text-white bg-primary hover:bg-primary-hover rounded-lg transition-colors disabled:opacity-50 shadow-sm"
                >
                  {isSubmitting ? 'Creating...' : 'Create Dynamic Role'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
