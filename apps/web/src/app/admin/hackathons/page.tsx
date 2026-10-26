'use client';

import React, { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import {
  Trophy,
  Search,
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  X,
  ChevronLeft,
  ChevronRight,
  Building2,
  Calendar,
  Clock,
  ShieldAlert,
  ArrowRight,
  ExternalLink,
  MoreVertical,
  Filter,
} from 'lucide-react';
import { PageHeader } from '@/components/admin/PageHeader';
import { StatusBadge } from '@/components/admin/StatusBadge';
import { api, ApiClientError } from '@/lib/api-client';
import {
  HackathonDetailResponse,
  HackathonStatus,
  AdminUpdateHackathonStatusRequest,
} from '@/types/api';

export default function AdminHackathonsPage() {
  const [hackathons, setHackathons] = useState<HackathonDetailResponse[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [page, setPage] = useState<number>(1);
  const [totalPages, setTotalPages] = useState<number>(1);
  const [limit] = useState<number>(15);

  const [searchQuery, setSearchQuery] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [orgFilter, setOrgFilter] = useState<string>('');
  const [sortBy, setSortBy] = useState<string>('created_at');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');

  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Administrative Override Modal
  const [overrideHackathon, setOverrideHackathon] = useState<HackathonDetailResponse | null>(null);
  const [overrideStatus, setOverrideStatus] = useState<HackathonStatus>('suspended');
  const [overrideReason, setOverrideReason] = useState<string>('');
  const [isSubmittingOverride, setIsSubmittingOverride] = useState<boolean>(false);
  const [overrideError, setOverrideError] = useState<string | null>(null);

  const [activeDropdownId, setActiveDropdownId] = useState<string | null>(null);

  const loadHackathons = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await api.getAdminHackathons({
        page,
        limit,
        search: searchQuery.trim() || undefined,
        status: statusFilter !== 'all' ? (statusFilter as HackathonStatus) : undefined,
        organization_id: orgFilter.trim() || undefined,
        sort_by: sortBy,
        sort_order: sortOrder,
      });
      setHackathons(data.items);
      setTotal(data.total);
      setTotalPages(data.total_pages || 1);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to load hackathons directory.');
      }
    } finally {
      setIsLoading(false);
    }
  }, [page, limit, searchQuery, statusFilter, orgFilter, sortBy, sortOrder]);

  useEffect(() => {
    loadHackathons();
  }, [loadHackathons]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    loadHackathons();
  };

  const handleOverrideSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!overrideHackathon) return;
    setOverrideError(null);

    const trimmedReason = overrideReason.trim();
    if (!trimmedReason) {
      setOverrideError('Mandatory administrative justification reason is required.');
      return;
    }

    setIsSubmittingOverride(true);
    try {
      await api.overrideAdminHackathonStatus(overrideHackathon.id, {
        status: overrideStatus,
        reason: trimmedReason,
      });
      setOverrideHackathon(null);
      setOverrideReason('');
      setSuccessMessage(`Hackathon status overridden to "${overrideStatus}".`);
      setTimeout(() => setSuccessMessage(null), 4000);
      await loadHackathons();
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setOverrideError(err.message);
      } else {
        setOverrideError('Failed to execute administrative status override.');
      }
    } finally {
      setIsSubmittingOverride(false);
    }
  };

  // Metrics calculation from current page items or totals
  const draftCount = hackathons.filter((h) => h.status === 'draft').length;
  const publishedCount = hackathons.filter((h) => h.status === 'published').length;
  const completedCount = hackathons.filter((h) => h.status === 'completed').length;
  const suspendedCount = hackathons.filter((h) => h.status === 'suspended').length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Hackathon Oversight"
        description="Cross-tenant oversight of hackathon lifecycles, timeline constraints, submissions, and platform administrative overrides."
      >
        <button
          type="button"
          onClick={() => loadHackathons()}
          disabled={isLoading}
          className="flex items-center gap-2 px-3 py-2 text-xs font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
          <span>Refresh</span>
        </button>
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
            onClick={() => loadHackathons()}
            className="text-xs underline hover:no-underline font-medium"
          >
            Retry
          </button>
        </div>
      )}

      {/* Metric Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <div className="p-4 bg-surface rounded-xl border border-surface-border">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-text-muted">Total Events</span>
            <Trophy className="w-4 h-4 text-primary" />
          </div>
          <p className="mt-2 text-2xl font-bold text-text-primary">{total}</p>
          <span className="text-[11px] text-text-muted">Across all tenants</span>
        </div>
        <div className="p-4 bg-surface rounded-xl border border-surface-border">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-text-muted">Draft (Sample)</span>
            <span className="w-2 h-2 rounded-full bg-slate-500" />
          </div>
          <p className="mt-2 text-2xl font-bold text-slate-300">{draftCount}</p>
          <span className="text-[11px] text-text-muted">In preparation</span>
        </div>
        <div className="p-4 bg-surface rounded-xl border border-surface-border">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-text-muted">Published (Sample)</span>
            <span className="w-2 h-2 rounded-full bg-primary" />
          </div>
          <p className="mt-2 text-2xl font-bold text-primary">{publishedCount}</p>
          <span className="text-[11px] text-text-muted">Live & immutable</span>
        </div>
        <div className="p-4 bg-surface rounded-xl border border-surface-border">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-text-muted">Completed (Sample)</span>
            <span className="w-2 h-2 rounded-full bg-status-success" />
          </div>
          <p className="mt-2 text-2xl font-bold text-status-success">{completedCount}</p>
          <span className="text-[11px] text-text-muted">Concluded events</span>
        </div>
        <div className="p-4 bg-surface rounded-xl border border-surface-border">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-text-muted">Suspended (Sample)</span>
            <span className="w-2 h-2 rounded-full bg-status-error" />
          </div>
          <p className="mt-2 text-2xl font-bold text-status-error">{suspendedCount}</p>
          <span className="text-[11px] text-text-muted">Override locked</span>
        </div>
      </div>

      {/* Search and Filters Bar */}
      <div className="bg-surface p-4 rounded-xl border border-surface-border flex flex-col md:flex-row gap-3 items-stretch md:items-center justify-between">
        <form onSubmit={handleSearchSubmit} className="relative flex-1">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
          <input
            type="text"
            placeholder="Search hackathons by title or slug..."
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

        <div className="flex items-center gap-2.5 flex-wrap">
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(1);
            }}
            className="px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary transition-colors"
          >
            <option value="all">All Statuses</option>
            <option value="draft">Draft</option>
            <option value="published">Published</option>
            <option value="completed">Completed</option>
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
            <option value="start_date:asc">Start Date (Earliest)</option>
            <option value="start_date:desc">Start Date (Latest)</option>
            <option value="title:asc">Title (A-Z)</option>
          </select>
        </div>
      </div>

      {/* Hackathons Table */}
      <div className="bg-surface rounded-xl border border-surface-border overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-surface-border bg-surface-elevated/50 text-text-muted uppercase text-[10px] tracking-wider font-semibold">
                <th className="py-3 px-4">Hackathon</th>
                <th className="py-3 px-4">Organization</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4">Timeline Window</th>
                <th className="py-3 px-4">Submission Deadline</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-border text-text-secondary">
              {isLoading ? (
                Array.from({ length: 6 }).map((_, idx) => (
                  <tr key={`skel-h-${idx}`} className="animate-pulse">
                    <td className="py-3.5 px-4">
                      <div className="h-3.5 bg-surface-elevated rounded w-40 mb-1.5" />
                      <div className="h-2.5 bg-surface-elevated rounded w-24" />
                    </td>
                    <td className="py-3.5 px-4">
                      <div className="h-3.5 bg-surface-elevated rounded w-28" />
                    </td>
                    <td className="py-3.5 px-4">
                      <div className="h-5 bg-surface-elevated rounded-full w-16" />
                    </td>
                    <td className="py-3.5 px-4">
                      <div className="h-3.5 bg-surface-elevated rounded w-32" />
                    </td>
                    <td className="py-3.5 px-4">
                      <div className="h-3.5 bg-surface-elevated rounded w-28" />
                    </td>
                    <td className="py-3.5 px-4 text-right">
                      <div className="h-6 bg-surface-elevated rounded w-16 ml-auto" />
                    </td>
                  </tr>
                ))
              ) : hackathons.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-text-muted">
                    <Trophy className="w-8 h-8 mx-auto text-text-muted/40 mb-2" />
                    <p className="text-sm font-medium text-text-secondary">No hackathons found</p>
                    <p className="text-xs mt-1">Try adjusting your search criteria or status filter.</p>
                  </td>
                </tr>
              ) : (
                hackathons.map((h) => (
                  <tr key={h.id} className="hover:bg-surface-hover/50 transition-colors group">
                    <td className="py-3.5 px-4">
                      <Link
                        href={`/admin/hackathons/${h.id}`}
                        className="font-semibold text-text-primary hover:text-primary transition-colors flex items-center gap-1.5"
                      >
                        <span>{h.title}</span>
                        <ArrowRight className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity" />
                      </Link>
                      <div className="text-[11px] text-text-muted font-mono mt-0.5">
                        /{h.slug}
                      </div>
                    </td>
                    <td className="py-3.5 px-4">
                      {h.organization ? (
                        <Link
                          href={`/admin/organizations/${h.organization_id}`}
                          className="font-medium text-text-primary hover:text-primary transition-colors flex items-center gap-1"
                        >
                          <Building2 className="w-3 h-3 text-text-muted" />
                          <span>{h.organization.name}</span>
                        </Link>
                      ) : (
                        <span className="text-text-muted font-mono text-[11px]">
                          {h.organization_id.slice(0, 8)}...
                        </span>
                      )}
                    </td>
                    <td className="py-3.5 px-4">
                      <StatusBadge status={h.status} size="sm" />
                    </td>
                    <td className="py-3.5 px-4 text-text-muted whitespace-nowrap">
                      <div className="flex items-center gap-1.5">
                        <Calendar className="w-3 h-3" />
                        <span>
                          {new Date(h.start_date).toLocaleDateString()} — {new Date(h.end_date).toLocaleDateString()}
                        </span>
                      </div>
                    </td>
                    <td className="py-3.5 px-4 text-text-muted whitespace-nowrap">
                      <div className="flex items-center gap-1.5">
                        <Clock className="w-3 h-3" />
                        <span>{new Date(h.submission_deadline).toLocaleString()}</span>
                      </div>
                    </td>
                    <td className="py-3.5 px-4 text-right">
                      <div className="relative inline-block text-left">
                        <button
                          type="button"
                          onClick={() =>
                            setActiveDropdownId(activeDropdownId === h.id ? null : h.id)
                          }
                          className="p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-surface-elevated transition-colors"
                          aria-label="Actions"
                        >
                          <MoreVertical className="w-4 h-4" />
                        </button>

                        {activeDropdownId === h.id && (
                          <div className="absolute right-0 mt-1 w-44 bg-surface border border-surface-border rounded-xl shadow-surface-elevated py-1.5 z-30 animate-in fade-in zoom-in-95 duration-100">
                            <Link
                              href={`/admin/hackathons/${h.id}`}
                              className="flex items-center gap-2 px-3 py-1.5 text-xs text-text-primary hover:bg-surface-elevated transition-colors"
                              onClick={() => setActiveDropdownId(null)}
                            >
                              <span>Inspect Details</span>
                            </Link>
                            <button
                              type="button"
                              onClick={() => {
                                setActiveDropdownId(null);
                                setOverrideHackathon(h);
                                setOverrideStatus(h.status === 'suspended' ? 'published' : 'suspended');
                                setOverrideReason('');
                                setOverrideError(null);
                              }}
                              className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-status-warning hover:bg-surface-elevated transition-colors text-left"
                            >
                              <span>Administrative Override</span>
                            </button>
                            <Link
                              href={`/admin/organizations/${h.organization_id}?tab=hackathons`}
                              className="flex items-center gap-2 px-3 py-1.5 text-xs text-text-primary hover:bg-surface-elevated transition-colors"
                              onClick={() => setActiveDropdownId(null)}
                            >
                              <span>Owning Organization</span>
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
            of <span className="font-semibold text-text-primary">{total}</span> hackathons
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

      {/* Modal: Administrative Status Override */}
      {overrideHackathon && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="bg-surface border border-surface-border rounded-2xl w-full max-w-md shadow-surface-elevated overflow-hidden">
            <div className="p-5 border-b border-surface-border flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-status-warning/10 flex items-center justify-center text-status-warning">
                  <ShieldAlert className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-text-primary">Administrative Override</h3>
                  <p className="text-[11px] text-text-muted">Event: {overrideHackathon.title}</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setOverrideHackathon(null)}
                className="p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-surface-elevated transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleOverrideSubmit} className="p-5 space-y-4">
              {overrideError && (
                <div className="p-3 bg-status-error/10 border border-status-error/30 rounded-lg text-status-error text-xs flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{overrideError}</span>
                </div>
              )}

              <div className="p-3 bg-status-warning/10 border border-status-warning/30 rounded-lg text-[11px] text-status-warning">
                <strong>Platform Override Notice:</strong> This action bypasses tenant ownership and emits an immutable audit event tagged with your platform administrator credentials.
              </div>

              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1">
                  Target Status <span className="text-status-error">*</span>
                </label>
                <select
                  value={overrideStatus}
                  onChange={(e) => setOverrideStatus(e.target.value as HackathonStatus)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                >
                  <option value="draft">Draft (Reset state)</option>
                  <option value="published">Published (Live event)</option>
                  <option value="completed">Completed (Conclude)</option>
                  <option value="suspended">Suspended (Lock event)</option>
                  <option value="archived">Archived (Cold storage)</option>
                </select>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="block text-xs font-medium text-text-secondary">
                    Mandatory Operational Justification <span className="text-status-error">*</span>
                  </label>
                  <span className="text-[10px] text-text-muted">{overrideReason.length}/500</span>
                </div>
                <textarea
                  rows={3}
                  maxLength={500}
                  required
                  placeholder="Explain why this platform administrative override is required..."
                  value={overrideReason}
                  onChange={(e) => setOverrideReason(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary placeholder-text-muted"
                />
              </div>

              <div className="pt-2 flex items-center justify-end gap-2.5 border-t border-surface-border">
                <button
                  type="button"
                  onClick={() => setOverrideHackathon(null)}
                  className="px-3 py-2 text-xs font-medium text-text-muted hover:text-text-primary hover:bg-surface-elevated rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingOverride || !overrideReason.trim()}
                  className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg transition-colors shadow-sm"
                >
                  {isSubmittingOverride ? 'Executing...' : 'Confirm Status Override'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
