'use client';

import React, { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import {
  Building2,
  Plus,
  Search,
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  X,
  ChevronLeft,
  ChevronRight,
  Users,
  Trophy,
  MoreVertical,
  ShieldAlert,
  ArrowRight,
  Calendar,
} from 'lucide-react';
import { PageHeader } from '@/components/admin/PageHeader';
import { StatusBadge } from '@/components/admin/StatusBadge';
import { api, ApiClientError } from '@/lib/api-client';
import {
  OrganizationSummaryResponse,
  OrganizationStatus,
  CreateOrganizationRequest,
} from '@/types/api';

export default function AdminOrganizationsPage() {
  const [organizations, setOrganizations] = useState<OrganizationSummaryResponse[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [page, setPage] = useState<number>(1);
  const [totalPages, setTotalPages] = useState<number>(1);
  const [limit] = useState<number>(15);

  const [searchQuery, setSearchQuery] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [sortBy, setSortBy] = useState<string>('created_at');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');

  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Modals state
  const [isCreateModalOpen, setIsCreateModalOpen] = useState<boolean>(false);
  const [isSubmittingCreate, setIsSubmittingCreate] = useState<boolean>(false);
  const [createForm, setCreateForm] = useState<CreateOrganizationRequest>({
    name: '',
    slug: '',
    owner_email: '',
  });
  const [createError, setCreateError] = useState<string | null>(null);

  const [statusModalOrg, setStatusModalOrg] = useState<OrganizationSummaryResponse | null>(null);
  const [targetStatus, setTargetStatus] = useState<OrganizationStatus>('active');
  const [statusReason, setStatusReason] = useState<string>('');
  const [isSubmittingStatus, setIsSubmittingStatus] = useState<boolean>(false);
  const [statusError, setStatusError] = useState<string | null>(null);

  const [activeDropdownId, setActiveDropdownId] = useState<string | null>(null);

  const loadOrganizations = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await api.getAdminOrganizations({
        page,
        limit,
        search: searchQuery.trim() || undefined,
        status: statusFilter !== 'all' ? (statusFilter as OrganizationStatus) : undefined,
        sort_by: sortBy,
        sort_order: sortOrder,
      });
      setOrganizations(data.items);
      setTotal(data.total);
      setTotalPages(data.total_pages || 1);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to load organizations.');
      }
    } finally {
      setIsLoading(false);
    }
  }, [page, limit, searchQuery, statusFilter, sortBy, sortOrder]);

  useEffect(() => {
    loadOrganizations();
  }, [loadOrganizations]);

  // Handle Search submit
  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    loadOrganizations();
  };

  // Auto-slug generator
  const handleNameChange = (name: string) => {
    setCreateForm((prev) => {
      const generatedSlug = name
        .toLowerCase()
        .replace(/[^a-z0-9\s-]/g, '')
        .trim()
        .replace(/\s+/g, '-');
      return {
        ...prev,
        name,
        slug: prev.slug === '' || prev.slug === prev.name.toLowerCase().replace(/[^a-z0-9\s-]/g, '').trim().replace(/\s+/g, '-') ? generatedSlug : prev.slug,
      };
    });
  };

  // Create Organization submit
  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateError(null);
    setIsSubmittingCreate(true);

    try {
      await api.createAdminOrganization({
        name: createForm.name.trim(),
        slug: createForm.slug.trim(),
        owner_email: createForm.owner_email.trim(),
      });
      setIsCreateModalOpen(false);
      setCreateForm({ name: '', slug: '', owner_email: '' });
      setSuccessMessage(`Organization "${createForm.name}" created successfully.`);
      setTimeout(() => setSuccessMessage(null), 4000);
      setPage(1);
      await loadOrganizations();
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setCreateError(err.message);
      } else {
        setCreateError('An unexpected error occurred while creating the organization.');
      }
    } finally {
      setIsSubmittingCreate(false);
    }
  };

  // Status Change submit
  const handleStatusSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!statusModalOrg) return;
    setStatusError(null);

    const trimmedReason = statusReason.trim();
    if (!trimmedReason && targetStatus !== 'active') {
      setStatusError('A non-empty justification reason is required for status changes.');
      return;
    }

    setIsSubmittingStatus(true);
    try {
      await api.updateAdminOrganizationStatus(statusModalOrg.id, {
        status: targetStatus,
        reason: trimmedReason || undefined,
      });
      setStatusModalOrg(null);
      setStatusReason('');
      setSuccessMessage(`Organization status updated to "${targetStatus}".`);
      setTimeout(() => setSuccessMessage(null), 4000);
      await loadOrganizations();
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setStatusError(err.message);
      } else {
        setStatusError('Failed to update organization status.');
      }
    } finally {
      setIsSubmittingStatus(false);
    }
  };

  // Metrics calculation from current or aggregated data
  const activeCount = organizations.filter((o) => o.status === 'active').length;
  const suspendedCount = organizations.filter((o) => o.status === 'suspended').length;
  const archivedCount = organizations.filter((o) => o.status === 'archived').length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Organizations Management"
        description="Platform-wide tenant administration, membership rosters, status controls, and tenant isolation policies."
      >
        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={() => loadOrganizations()}
            disabled={isLoading}
            className="flex items-center gap-2 px-3 py-2 text-xs font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors disabled:opacity-50"
            title="Refresh list"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span className="hidden sm:inline">Refresh</span>
          </button>
          <button
            type="button"
            onClick={() => {
              setCreateError(null);
              setIsCreateModalOpen(true);
            }}
            className="flex items-center gap-2 px-3.5 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover rounded-lg transition-colors shadow-sm"
          >
            <Plus className="w-4 h-4" />
            <span>New Organization</span>
          </button>
        </div>
      </PageHeader>

      {/* Success Notification Banner */}
      {successMessage && (
        <div className="flex items-center gap-3 p-4 bg-status-success/10 border border-status-success/30 rounded-xl text-status-success text-sm animate-in fade-in">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{successMessage}</span>
        </div>
      )}

      {/* Error Banner */}
      {error && (
        <div className="flex items-center justify-between p-4 bg-status-error/10 border border-status-error/30 rounded-xl text-status-error text-sm">
          <div className="flex items-center gap-3">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
          <button
            onClick={() => loadOrganizations()}
            className="text-xs underline hover:no-underline font-medium"
          >
            Retry
          </button>
        </div>
      )}

      {/* Metric Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="p-4 bg-surface rounded-xl border border-surface-border">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-text-muted">Total Tenants</span>
            <Building2 className="w-4 h-4 text-primary" />
          </div>
          <p className="mt-2 text-2xl font-bold text-text-primary">{total}</p>
          <span className="text-[11px] text-text-muted">All registered tenants</span>
        </div>
        <div className="p-4 bg-surface rounded-xl border border-surface-border">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-text-muted">Active (Sample)</span>
            <span className="w-2 h-2 rounded-full bg-status-success" />
          </div>
          <p className="mt-2 text-2xl font-bold text-status-success">{activeCount}</p>
          <span className="text-[11px] text-text-muted">Operating normally</span>
        </div>
        <div className="p-4 bg-surface rounded-xl border border-surface-border">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-text-muted">Suspended (Sample)</span>
            <span className="w-2 h-2 rounded-full bg-status-error" />
          </div>
          <p className="mt-2 text-2xl font-bold text-status-error">{suspendedCount}</p>
          <span className="text-[11px] text-text-muted">Operations locked</span>
        </div>
        <div className="p-4 bg-surface rounded-xl border border-surface-border">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-text-muted">Archived (Sample)</span>
            <span className="w-2 h-2 rounded-full bg-slate-500" />
          </div>
          <p className="mt-2 text-2xl font-bold text-text-muted">{archivedCount}</p>
          <span className="text-[11px] text-text-muted">Read-only cold storage</span>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="bg-surface p-4 rounded-xl border border-surface-border flex flex-col md:flex-row gap-3 items-stretch md:items-center justify-between">
        <form onSubmit={handleSearchSubmit} className="relative flex-1">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
          <input
            type="text"
            placeholder="Search by organization name or slug..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-8 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary placeholder-text-muted focus:outline-none focus:border-primary transition-colors"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => {
                setSearchQuery('');
                setPage(1);
              }}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </form>

        <div className="flex items-center gap-2.5">
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(1);
            }}
            className="px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary transition-colors"
          >
            <option value="all">All Statuses</option>
            <option value="active">Active</option>
            <option value="suspended">Suspended</option>
            <option value="archived">Archived</option>
          </select>

          <select
            value={`${sortBy}:${sortOrder}`}
            onChange={(e) => {
              const [field, order] = e.target.value.split(':');
              setSortBy(field);
              setSortOrder(order as 'asc' | 'desc');
              setPage(1);
            }}
            className="px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary transition-colors"
          >
            <option value="created_at:desc">Newest First</option>
            <option value="created_at:asc">Oldest First</option>
            <option value="name:asc">Name (A-Z)</option>
            <option value="name:desc">Name (Z-A)</option>
          </select>
        </div>
      </div>

      {/* Organizations Directory Table */}
      <div className="bg-surface rounded-xl border border-surface-border overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-surface-border bg-surface-elevated/50 text-text-muted uppercase text-[10px] tracking-wider font-semibold">
                <th className="py-3 px-4">Organization</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4">Owner</th>
                <th className="py-3 px-4 text-center">Members</th>
                <th className="py-3 px-4 text-center">Hackathons</th>
                <th className="py-3 px-4">Created At</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-border text-text-secondary">
              {isLoading ? (
                Array.from({ length: 6 }).map((_, idx) => (
                  <tr key={`skel-${idx}`} className="animate-pulse">
                    <td className="py-3.5 px-4">
                      <div className="h-3.5 bg-surface-elevated rounded w-36 mb-1.5" />
                      <div className="h-2.5 bg-surface-elevated rounded w-20" />
                    </td>
                    <td className="py-3.5 px-4">
                      <div className="h-5 bg-surface-elevated rounded-full w-16" />
                    </td>
                    <td className="py-3.5 px-4">
                      <div className="h-3.5 bg-surface-elevated rounded w-28 mb-1.5" />
                      <div className="h-2.5 bg-surface-elevated rounded w-32" />
                    </td>
                    <td className="py-3.5 px-4 text-center">
                      <div className="h-3.5 bg-surface-elevated rounded w-8 mx-auto" />
                    </td>
                    <td className="py-3.5 px-4 text-center">
                      <div className="h-3.5 bg-surface-elevated rounded w-8 mx-auto" />
                    </td>
                    <td className="py-3.5 px-4">
                      <div className="h-3.5 bg-surface-elevated rounded w-24" />
                    </td>
                    <td className="py-3.5 px-4 text-right">
                      <div className="h-6 bg-surface-elevated rounded w-16 ml-auto" />
                    </td>
                  </tr>
                ))
              ) : organizations.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-text-muted">
                    <Building2 className="w-8 h-8 mx-auto text-text-muted/40 mb-2" />
                    <p className="text-sm font-medium text-text-secondary">No organizations found</p>
                    <p className="text-xs mt-1">Try refining your search keywords or status filter.</p>
                  </td>
                </tr>
              ) : (
                organizations.map((org) => (
                  <tr
                    key={org.id}
                    className="hover:bg-surface-hover/50 transition-colors group"
                  >
                    <td className="py-3.5 px-4">
                      <Link
                        href={`/admin/organizations/${org.id}`}
                        className="font-semibold text-text-primary hover:text-primary transition-colors flex items-center gap-1.5"
                      >
                        <span>{org.name}</span>
                        <ArrowRight className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity" />
                      </Link>
                      <div className="text-[11px] text-text-muted font-mono mt-0.5">
                        /{org.slug}
                      </div>
                    </td>
                    <td className="py-3.5 px-4">
                      <StatusBadge status={org.status} size="sm" />
                    </td>
                    <td className="py-3.5 px-4">
                      <div className="font-medium text-text-primary truncate max-w-[160px]">
                        {org.owner?.full_name || org.owner_name || 'System Owner'}
                      </div>
                      <div className="text-[11px] text-text-muted truncate max-w-[180px]">
                        {org.owner?.email || org.owner_email || '—'}
                      </div>
                    </td>
                    <td className="py-3.5 px-4 text-center">
                      <span className="inline-flex items-center gap-1 font-mono text-text-primary">
                        <Users className="w-3 h-3 text-text-muted" />
                        {org.member_count}
                      </span>
                    </td>
                    <td className="py-3.5 px-4 text-center">
                      <span className="inline-flex items-center gap-1 font-mono text-text-primary">
                        <Trophy className="w-3 h-3 text-text-muted" />
                        {org.hackathon_count}
                      </span>
                    </td>
                    <td className="py-3.5 px-4 text-text-muted whitespace-nowrap">
                      <div className="flex items-center gap-1.5">
                        <Calendar className="w-3 h-3" />
                        <span>{new Date(org.created_at).toLocaleDateString()}</span>
                      </div>
                    </td>
                    <td className="py-3.5 px-4 text-right">
                      <div className="relative inline-block text-left">
                        <button
                          type="button"
                          onClick={() =>
                            setActiveDropdownId(activeDropdownId === org.id ? null : org.id)
                          }
                          className="p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-surface-elevated transition-colors"
                          aria-label="Actions"
                        >
                          <MoreVertical className="w-4 h-4" />
                        </button>

                        {activeDropdownId === org.id && (
                          <div className="absolute right-0 mt-1 w-44 bg-surface border border-surface-border rounded-xl shadow-surface-elevated py-1.5 z-30 animate-in fade-in zoom-in-95 duration-100">
                            <Link
                              href={`/admin/organizations/${org.id}`}
                              className="flex items-center gap-2 px-3 py-1.5 text-xs text-text-primary hover:bg-surface-elevated transition-colors"
                              onClick={() => setActiveDropdownId(null)}
                            >
                              <span>View Details</span>
                            </Link>
                            <button
                              type="button"
                              onClick={() => {
                                setActiveDropdownId(null);
                                setStatusModalOrg(org);
                                setTargetStatus(org.status);
                                setStatusReason('');
                                setStatusError(null);
                              }}
                              className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-text-primary hover:bg-surface-elevated transition-colors text-left"
                            >
                              <span>Change Status</span>
                            </button>
                            <Link
                              href={`/admin/organizations/${org.id}?tab=members`}
                              className="flex items-center gap-2 px-3 py-1.5 text-xs text-text-primary hover:bg-surface-elevated transition-colors"
                              onClick={() => setActiveDropdownId(null)}
                            >
                              <span>Manage Members</span>
                            </Link>
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Bar */}
        <div className="p-4 border-t border-surface-border flex items-center justify-between text-xs text-text-muted">
          <div>
            Showing{' '}
            <span className="font-semibold text-text-primary">
              {total === 0 ? 0 : (page - 1) * limit + 1}
            </span>{' '}
            to{' '}
            <span className="font-semibold text-text-primary">
              {Math.min(page * limit, total)}
            </span>{' '}
            of <span className="font-semibold text-text-primary">{total}</span> organizations
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
              Page {page} of {totalPages}
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

      {/* Modal: Create Organization */}
      {isCreateModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="bg-surface border border-surface-border rounded-2xl w-full max-w-md shadow-surface-elevated overflow-hidden">
            <div className="p-5 border-b border-surface-border flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
                  <Building2 className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-text-primary">Create Organization</h3>
                  <p className="text-[11px] text-text-muted">Provision a new multi-tenant organization</p>
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

            <form onSubmit={handleCreateSubmit} className="p-5 space-y-4">
              {createError && (
                <div className="p-3 bg-status-error/10 border border-status-error/30 rounded-lg text-status-error text-xs flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{createError}</span>
                </div>
              )}

              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1">
                  Organization Name <span className="text-status-error">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Acme Innovations"
                  value={createForm.name}
                  onChange={(e) => handleNameChange(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1">
                  Slug (URL Identifier) <span className="text-status-error">*</span>
                </label>
                <div className="flex items-center bg-surface-elevated border border-surface-border rounded-lg overflow-hidden focus-within:border-primary">
                  <span className="px-2.5 text-xs text-text-muted select-none">scorva.io/</span>
                  <input
                    type="text"
                    required
                    pattern="^[a-z0-9]+(?:-[a-z0-9]+)*$"
                    placeholder="acme-innovations"
                    value={createForm.slug}
                    onChange={(e) =>
                      setCreateForm((prev) => ({ ...prev, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '') }))
                    }
                    className="w-full py-2 pr-3 text-xs bg-transparent text-text-primary focus:outline-none font-mono"
                  />
                </div>
                <p className="text-[10px] text-text-muted mt-1">Lowercase letters, numbers, and hyphens only.</p>
              </div>

              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1">
                  Initial Owner Email <span className="text-status-error">*</span>
                </label>
                <input
                  type="email"
                  required
                  placeholder="admin@example.com"
                  value={createForm.owner_email}
                  onChange={(e) =>
                    setCreateForm((prev) => ({ ...prev, owner_email: e.target.value }))
                  }
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
                <p className="text-[10px] text-text-muted mt-1">
                  Must be an existing registered Scorva user account.
                </p>
              </div>

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
                  disabled={isSubmittingCreate || !createForm.name || !createForm.slug || !createForm.owner_email}
                  className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg transition-colors shadow-sm"
                >
                  {isSubmittingCreate ? 'Provisioning...' : 'Provision Tenant'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Change Organization Status */}
      {statusModalOrg && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="bg-surface border border-surface-border rounded-2xl w-full max-w-md shadow-surface-elevated overflow-hidden">
            <div className="p-5 border-b border-surface-border flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-status-warning/10 flex items-center justify-center text-status-warning">
                  <ShieldAlert className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-text-primary">Update Organization Status</h3>
                  <p className="text-[11px] text-text-muted">
                    Tenant: <span className="font-semibold text-text-secondary">{statusModalOrg.name}</span>
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setStatusModalOrg(null)}
                className="p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-surface-elevated transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleStatusSubmit} className="p-5 space-y-4">
              {statusError && (
                <div className="p-3 bg-status-error/10 border border-status-error/30 rounded-lg text-status-error text-xs flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{statusError}</span>
                </div>
              )}

              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1">
                  Target Status
                </label>
                <select
                  value={targetStatus}
                  onChange={(e) => setTargetStatus(e.target.value as OrganizationStatus)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                >
                  <option value="active">Active (Normal Operations)</option>
                  <option value="suspended">Suspended (Tenant Blocked)</option>
                  <option value="archived">Archived (Read-Only Cold Storage)</option>
                </select>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="block text-xs font-medium text-text-secondary">
                    Operational Reason {targetStatus !== 'active' && <span className="text-status-error">*</span>}
                  </label>
                  <span className="text-[10px] text-text-muted">{statusReason.length}/500</span>
                </div>
                <textarea
                  rows={3}
                  maxLength={500}
                  required={targetStatus !== 'active'}
                  placeholder={
                    targetStatus === 'suspended'
                      ? 'Mandatory reason for suspension (e.g. Terms of Service violation investigation)...'
                      : 'Operational note or justification...'
                  }
                  value={statusReason}
                  onChange={(e) => setStatusReason(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary placeholder-text-muted"
                />
              </div>

              <div className="pt-2 flex items-center justify-end gap-2.5 border-t border-surface-border">
                <button
                  type="button"
                  onClick={() => setStatusModalOrg(null)}
                  className="px-3 py-2 text-xs font-medium text-text-muted hover:text-text-primary hover:bg-surface-elevated rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingStatus || (targetStatus !== 'active' && !statusReason.trim())}
                  className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg transition-colors shadow-sm"
                >
                  {isSubmittingStatus ? 'Updating...' : 'Confirm Status Change'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
