'use client';

import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Users,
  RefreshCw,
  Shield,
  ShieldCheck,
  ShieldAlert,
  Ban,
  CheckCircle2,
  Lock,
  Search,
  ChevronLeft,
  ChevronRight,
  X,
  Calendar,
  UserPlus,
  Building2,
  Eye,
  EyeOff,
  Sparkles,
  AlertCircle,
} from 'lucide-react';
import { PageHeader } from '@/components/admin/PageHeader';
import { api, ApiClientError } from '@/lib/api-client';
import { UserProfile, OrganizationSummaryResponse, PlatformRole } from '@/types/api';

export default function UsersPage() {
  const [users, setUsers] = useState<UserProfile[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [page, setPage] = useState<number>(1);
  const [totalPages, setTotalPages] = useState<number>(1);
  const [limit] = useState<number>(15);

  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Filters
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [debouncedSearch, setDebouncedSearch] = useState<string>('');
  const [roleFilter, setRoleFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');

  // Create User / Organizer Modal state
  const [isCreateModalOpen, setIsCreateModalOpen] = useState<boolean>(false);
  const [isSubmittingCreate, setIsSubmittingCreate] = useState<boolean>(false);
  const [createFullName, setCreateFullName] = useState<string>('');
  const [createEmail, setCreateEmail] = useState<string>('');
  const [createPassword, setCreatePassword] = useState<string>('');
  const [showCreatePassword, setShowCreatePassword] = useState<boolean>(false);
  const [createRoleType, setCreateRoleType] = useState<'organizer' | 'platform_owner' | 'security_admin'>('organizer');
  const [createOrgId, setCreateOrgId] = useState<string>('');
  const [createOrgRole, setCreateOrgRole] = useState<string>('organizer');
  const [createError, setCreateError] = useState<string | null>(null);
  const [orgOptions, setOrgOptions] = useState<OrganizationSummaryResponse[]>([]);

  useEffect(() => {
    if (isCreateModalOpen) {
      api.getAdminOrganizations({ limit: 100 }).then((res) => {
        setOrgOptions(res.items || []);
        if (res.items?.length && !createOrgId) {
          setCreateOrgId(res.items[0].id);
        }
      }).catch(() => {});
    }
  }, [isCreateModalOpen, createOrgId]);

  const generatePassword = () => {
    const chars = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%';
    let res = '';
    for (let i = 0; i < 12; i++) {
      res += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    setCreatePassword(res);
  };

  const handleCreateUserSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateError(null);
    setIsSubmittingCreate(true);
    try {
      const isPlatform = createRoleType !== 'organizer';
      await api.createAdminUser({
        full_name: createFullName.trim(),
        email: createEmail.trim(),
        password: createPassword.trim() || 'OrganizerPass123!',
        platform_role: isPlatform ? (createRoleType as PlatformRole) : null,
        organization_id: !isPlatform && createOrgId ? createOrgId : undefined,
        org_role: !isPlatform ? createOrgRole : undefined,
      });
      setIsCreateModalOpen(false);
      setCreateFullName('');
      setCreateEmail('');
      setCreatePassword('');
      setSuccessMessage(`Account for ${createEmail} created successfully.`);
      setTimeout(() => setSuccessMessage(null), 4000);
      setPage(1);
      await loadUsers();
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setCreateError(err.message);
      } else {
        setCreateError('Failed to create user account.');
      }
    } finally {
      setIsSubmittingCreate(false);
    }
  };

  const abortControllerRef = useRef<AbortController | null>(null);

  // Debounce search query input by 300ms
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery);
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const loadUsers = useCallback(async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const signal = controller.signal;

    setIsLoading(true);
    setError(null);
    try {
      const data = await api.getUsers(
        {
          page,
          limit,
          search: debouncedSearch.trim() || undefined,
          role: roleFilter !== 'all' ? roleFilter : undefined,
          status: statusFilter !== 'all' ? statusFilter : undefined,
        },
        { signal }
      );

      if (signal.aborted) return;
      setUsers(data.items);
      setTotal(data.total);
      setTotalPages(data.total_pages || 1);
    } catch (err: unknown) {
      if (signal.aborted) return;
      if (err instanceof ApiClientError) {
        if (err.code === 'REQUEST_ABORTED') return;
        setError(err.message);
      } else {
        setError('Failed to load user directory.');
      }
    } finally {
      if (!signal.aborted) {
        setIsLoading(false);
      }
    }
  }, [page, limit, debouncedSearch, roleFilter, statusFilter]);

  useEffect(() => {
    loadUsers();
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [loadUsers]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setDebouncedSearch(searchQuery);
    setPage(1);
  };

  const handleClearFilters = () => {
    setSearchQuery('');
    setDebouncedSearch('');
    setRoleFilter('all');
    setStatusFilter('all');
    setPage(1);
  };

  const handleToggleStatus = async (user: UserProfile) => {
    const action = user.is_active ? 'suspend' : 'activate';
    if (!confirm(`Are you sure you want to ${action} user ${user.email}?`)) {
      return;
    }

    setActionInProgress(user.id);
    setError(null);
    try {
      await api.updateUserStatus(user.id, !user.is_active, `Administrative ${action}`);
      setSuccessMessage(`User ${user.email} successfully ${action}ed.`);
      setTimeout(() => setSuccessMessage(null), 3000);
      await loadUsers();
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError(`Failed to ${action} user.`);
      }
    } finally {
      setActionInProgress(null);
    }
  };

  const handleRevokeSessions = async (user: UserProfile) => {
    if (!confirm(`Revoke all active sessions for ${user.email}? They will be forced to log in again.`)) {
      return;
    }

    setActionInProgress(user.id);
    setError(null);
    try {
      const res = await api.revokeUserSessions(user.id);
      setSuccessMessage(res.message);
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to revoke sessions.');
      }
    } finally {
      setActionInProgress(null);
    }
  };

  const formatRole = (role?: string | null) => {
    if (!role) return 'None (Organization User)';
    return role
      .split('_')
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
      .join(' ');
  };

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return '—';
    try {
      return new Date(dateStr).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      });
    } catch {
      return '—';
    }
  };

  const hasActiveFilters = searchQuery !== '' || roleFilter !== 'all' || statusFilter !== 'all';

  return (
    <div className="space-y-6">
      <PageHeader
        title="Users & Access Management"
        description="Super Admin directory of platform administrator accounts, organizers, role assignments, MFA status, and session controls."
      >
        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={() => setIsCreateModalOpen(true)}
            className="flex items-center gap-2 px-3.5 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover rounded-lg transition-colors shadow-sm"
          >
            <UserPlus className="w-3.5 h-3.5" />
            <span>Create User / Organizer</span>
          </button>
          <button
            type="button"
            onClick={() => loadUsers()}
            disabled={isLoading}
            className="flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
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
            onClick={() => loadUsers()}
            className="underline font-semibold hover:text-white"
          >
            Retry
          </button>
        </div>
      )}

      {/* Search & Filter Toolbar */}
      <div className="p-4 bg-surface border border-surface-border rounded-xl flex flex-col md:flex-row items-stretch md:items-center justify-between gap-4 shadow-surface-elevated">
        <div className="flex flex-1 flex-col sm:flex-row items-stretch sm:items-center gap-3">
          {/* Search Input */}
          <form onSubmit={handleSearchSubmit} className="relative flex-1 sm:max-w-xs">
            <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by name or email..."
              className="w-full pl-9 pr-8 py-1.5 bg-surface-elevated border border-surface-border rounded-lg text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:border-primary transition-colors"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => {
                  setSearchQuery('');
                  setDebouncedSearch('');
                  setPage(1);
                }}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary p-0.5 rounded"
                title="Clear search"
              >
                <X className="w-3 h-3" />
              </button>
            )}
          </form>

          {/* Role Filter */}
          <select
            value={roleFilter}
            onChange={(e) => {
              setRoleFilter(e.target.value);
              setPage(1);
            }}
            className="px-3 py-1.5 bg-surface-elevated border border-surface-border rounded-lg text-xs text-text-primary focus:outline-none focus:border-primary transition-colors"
            aria-label="Filter by Platform Role"
          >
            <option value="all">All Roles</option>
            <option value="platform_owner">Platform Owner</option>
            <option value="platform_ops_admin">Platform Ops Admin</option>
            <option value="ai_ops_admin">AI Ops Admin</option>
            <option value="security_admin">Security Admin</option>
            <option value="support_admin">Support Admin</option>
            <option value="billing_admin">Billing Admin</option>
            <option value="none">Org Users (No Platform Role)</option>
          </select>

          {/* Status Filter */}
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(1);
            }}
            className="px-3 py-1.5 bg-surface-elevated border border-surface-border rounded-lg text-xs text-text-primary focus:outline-none focus:border-primary transition-colors"
            aria-label="Filter by Account Status"
          >
            <option value="all">All Statuses</option>
            <option value="active">Active Only</option>
            <option value="suspended">Suspended Only</option>
          </select>

          {hasActiveFilters && (
            <button
              type="button"
              onClick={handleClearFilters}
              className="px-2.5 py-1.5 text-xs text-text-muted hover:text-text-primary hover:bg-surface-elevated border border-dashed border-surface-border rounded-lg transition-colors flex items-center gap-1.5 self-start sm:self-auto"
            >
              <X className="w-3 h-3" />
              <span>Reset</span>
            </button>
          )}
        </div>

        <div className="text-xs text-text-muted shrink-0 self-end md:self-center">
          Total Users: <span className="font-semibold text-text-primary">{total.toLocaleString()}</span>
        </div>
      </div>

      {/* Users Directory Table */}
      <div className="bg-surface border border-surface-border rounded-xl overflow-hidden shadow-surface-elevated">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="border-b border-surface-border bg-surface-elevated/50 text-text-muted font-medium">
                <th className="py-3 px-4">User</th>
                <th className="py-3 px-4">Platform Role</th>
                <th className="py-3 px-4">Account Status</th>
                <th className="py-3 px-4">MFA Policy</th>
                <th className="py-3 px-4">Created Date</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-border">
              {isLoading && users.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-text-muted">
                    <div className="flex flex-col items-center justify-center gap-2">
                      <RefreshCw className="w-5 h-5 animate-spin text-primary" />
                      <span>Loading users directory...</span>
                    </div>
                  </td>
                </tr>
              ) : users.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-text-muted">
                    <div className="flex flex-col items-center justify-center gap-2">
                      <Users className="w-6 h-6 text-text-muted/60" />
                      <p>No users found matching query.</p>
                      {hasActiveFilters && (
                        <button
                          type="button"
                          onClick={handleClearFilters}
                          className="mt-1 text-xs text-primary hover:underline font-medium"
                        >
                          Clear all filters
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ) : (
                users.map((u) => (
                  <tr key={u.id} className="hover:bg-surface-hover/50 transition-colors">
                    <td className="py-3 px-4">
                      <div className="font-medium text-text-primary">{u.full_name}</div>
                      <div className="text-text-muted font-mono text-[11px]">{u.email}</div>
                    </td>
                    <td className="py-3 px-4">
                      <div className="flex items-center gap-1.5">
                        <Shield className="w-3.5 h-3.5 text-primary" />
                        <span className="font-medium text-text-primary">
                          {formatRole(u.platform_role)}
                        </span>
                      </div>
                    </td>
                    <td className="py-3 px-4">
                      {u.is_active ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-status-success/10 text-status-success border border-status-success/30">
                          <CheckCircle2 className="w-3 h-3" />
                          <span>Active</span>
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-status-error/10 text-status-error border border-status-error/30">
                          <Ban className="w-3 h-3" />
                          <span>Suspended</span>
                        </span>
                      )}
                    </td>
                    <td className="py-3 px-4">
                      {u.mfa_enabled ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-primary/10 text-primary border border-primary/20">
                          <ShieldCheck className="w-3 h-3" />
                          <span>Enrolled</span>
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-status-warning/10 text-status-warning border border-status-warning/30">
                          <ShieldAlert className="w-3 h-3" />
                          <span>Pending Enrollment</span>
                        </span>
                      )}
                    </td>
                    <td className="py-3 px-4 text-text-muted font-mono text-[11px]">
                      {formatDate(u.created_at)}
                    </td>
                    <td className="py-3 px-4 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => handleRevokeSessions(u)}
                          disabled={actionInProgress === u.id}
                          className="px-2.5 py-1 text-[11px] font-medium text-text-secondary hover:text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-md transition-colors disabled:opacity-50"
                          title="Revoke all active sessions for this user"
                        >
                          Revoke Sessions
                        </button>
                        <button
                          type="button"
                          onClick={() => handleToggleStatus(u)}
                          disabled={actionInProgress === u.id}
                          className={`px-2.5 py-1 text-[11px] font-medium rounded-md transition-colors disabled:opacity-50 ${
                            u.is_active
                              ? 'text-status-error hover:bg-status-error/10 border border-status-error/30'
                              : 'text-status-success hover:bg-status-success/10 border border-status-success/30'
                          }`}
                        >
                          {u.is_active ? 'Suspend' : 'Activate'}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Bar */}
        <div className="p-4 border-t border-surface-border flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-text-muted">
          <div>
            Showing{' '}
            <span className="font-semibold text-text-primary">
              {total === 0 ? 0 : (page - 1) * limit + 1}
            </span>{' '}
            to{' '}
            <span className="font-semibold text-text-primary">
              {Math.min(page * limit, total)}
            </span>{' '}
            of <span className="font-semibold text-text-primary">{total.toLocaleString()}</span> users
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(p - 1, 1))}
              disabled={page <= 1 || isLoading}
              className="p-1.5 rounded-lg border border-surface-border hover:bg-surface-elevated disabled:opacity-40 disabled:cursor-not-allowed text-text-primary transition-colors"
              aria-label="Previous page"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="px-2 font-medium">
              Page {page} of {Math.max(totalPages, 1)}
            </span>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(p + 1, totalPages))}
              disabled={page >= totalPages || isLoading}
              className="p-1.5 rounded-lg border border-surface-border hover:bg-surface-elevated disabled:opacity-40 disabled:cursor-not-allowed text-text-primary transition-colors"
              aria-label="Next page"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Modal: Create User / Organizer */}
      {isCreateModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="bg-surface border border-surface-border rounded-2xl w-full max-w-md shadow-surface-elevated overflow-hidden">
            <div className="p-5 border-b border-surface-border flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
                  <UserPlus className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-text-primary">Create User / Organizer</h3>
                  <p className="text-[11px] text-text-muted">Provision login credentials directly</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setIsCreateModalOpen(false)}
                className="p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-surface-elevated transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleCreateUserSubmit} className="p-5 space-y-4">
              {createError && (
                <div className="p-3 bg-status-error/10 border border-status-error/30 rounded-lg text-status-error text-xs flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{createError}</span>
                </div>
              )}

              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1">
                  Full Name <span className="text-status-error">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Alex Morgan"
                  value={createFullName}
                  onChange={(e) => setCreateFullName(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1">
                  Email Address <span className="text-status-error">*</span>
                </label>
                <input
                  type="email"
                  required
                  placeholder="alex@organization.com"
                  value={createEmail}
                  onChange={(e) => setCreateEmail(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="block text-xs font-medium text-text-secondary">
                    Password Credentials <span className="text-status-error">*</span>
                  </label>
                  <button
                    type="button"
                    onClick={generatePassword}
                    className="text-[10px] text-primary hover:text-primary-hover flex items-center gap-1 font-medium transition-colors"
                  >
                    <Sparkles className="w-3 h-3" />
                    <span>Generate</span>
                  </button>
                </div>
                <div className="relative">
                  <input
                    type={showCreatePassword ? 'text' : 'password'}
                    required
                    placeholder="Enter password or click Generate"
                    value={createPassword}
                    onChange={(e) => setCreatePassword(e.target.value)}
                    className="w-full pl-3 pr-8 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary font-mono"
                  />
                  <button
                    type="button"
                    onClick={() => setShowCreatePassword(!showCreatePassword)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary transition-colors"
                  >
                    {showCreatePassword ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1">
                  Account Type
                </label>
                <select
                  value={createRoleType}
                  onChange={(e) => setCreateRoleType(e.target.value as 'organizer' | 'platform_owner' | 'security_admin')}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                >
                  <option value="organizer">Event Organizer / Tenant User</option>
                  <option value="platform_owner">Platform Owner (Super Admin)</option>
                  <option value="security_admin">Security Administrator</option>
                </select>
              </div>

              {createRoleType === 'organizer' && orgOptions.length > 0 && (
                <div className="p-3 bg-surface-elevated border border-surface-border rounded-xl space-y-3">
                  <div>
                    <label className="block text-xs font-medium text-text-secondary mb-1">
                      Assign to Organization
                    </label>
                    <select
                      value={createOrgId}
                      onChange={(e) => setCreateOrgId(e.target.value)}
                      className="w-full px-3 py-2 text-xs bg-surface border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                    >
                      <option value="">Do not assign to an organization now</option>
                      {orgOptions.map((org) => (
                        <option key={org.id} value={org.id}>
                          {org.name} (/{org.slug})
                        </option>
                      ))}
                    </select>
                  </div>

                  {createOrgId && (
                    <div>
                      <label className="block text-xs font-medium text-text-secondary mb-1">
                        Organization Role
                      </label>
                      <select
                        value={createOrgRole}
                        onChange={(e) => setCreateOrgRole(e.target.value)}
                        className="w-full px-3 py-2 text-xs bg-surface border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                      >
                        <option value="organizer">Organizer (Manage Hackathons)</option>
                        <option value="org_admin">Admin (Manage Members & Settings)</option>
                        <option value="org_owner">Owner (Full Control)</option>
                      </select>
                    </div>
                  )}
                </div>
              )}

              <p className="text-[10px] text-text-muted">
                The user can use these credentials to sign in immediately. No self-registration is required.
              </p>

              <div className="pt-2 flex items-center justify-end gap-2.5 border-t border-surface-border">
                <button
                  type="button"
                  onClick={() => setIsCreateModalOpen(false)}
                  className="px-3 py-2 text-xs font-medium text-text-muted hover:text-text-primary hover:bg-surface-elevated rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingCreate || !createFullName.trim() || !createEmail.trim()}
                  className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg transition-colors shadow-sm"
                >
                  {isSubmittingCreate ? 'Creating Account...' : 'Create Account'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
