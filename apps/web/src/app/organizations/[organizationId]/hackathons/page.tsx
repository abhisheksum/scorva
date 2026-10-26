'use client';

import React, { useState, useEffect, useCallback, useRef, use } from 'react';
import Link from 'next/link';
import {
  Trophy,
  Plus,
  Search,
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  X,
  ChevronLeft,
  ChevronRight,
  Calendar,
  Clock,
  ArrowRight,
  ExternalLink,
} from 'lucide-react';
import { StatusBadge } from '@/components/admin/StatusBadge';
import { api, ApiClientError } from '@/lib/api-client';
import {
  HackathonDetailResponse,
  HackathonStatus,
} from '@/types/api';

export default function TenantHackathonsPage({
  params,
}: {
  params: Promise<{ organizationId: string }>;
}) {
  const unwrappedParams = use(params);
  const orgId = unwrappedParams.organizationId;

  const [prevOrgId, setPrevOrgId] = useState<string>(orgId);
  const [hackathons, setHackathons] = useState<HackathonDetailResponse[]>([]);
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

  // Synchronous render-phase state adjustment: eliminates 1-frame stale data paint on navigation
  if (orgId !== prevOrgId) {
    setPrevOrgId(orgId);
    setHackathons([]);
    setTotal(0);
    setPage(1);
    setIsLoading(true);
    setError(null);
  }

  const abortControllerRef = useRef<AbortController | null>(null);

  const loadHackathons = useCallback(async (isRefresh: boolean = false) => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const signal = controller.signal;

    if (!isRefresh) {
      // Immediately reset hackathon list to avoid stale records during tenant navigation
      setHackathons([]);
      setTotal(0);
      setIsLoading(true);
      setError(null);
    }

    try {
      const data = await api.getTenantHackathons(
        orgId,
        {
          page,
          limit,
          search: searchQuery.trim() || undefined,
          status: statusFilter !== 'all' ? (statusFilter as HackathonStatus) : undefined,
          sort_by: sortBy,
          sort_order: sortOrder,
        },
        { signal }
      );
      if (!signal.aborted) {
        setHackathons(data.items);
        setTotal(data.total);
        setTotalPages(data.total_pages || 1);
      }
    } catch (err: unknown) {
      if (signal.aborted) return;
      if (err instanceof ApiClientError && err.code === 'REQUEST_ABORTED') return;
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to load hackathons.');
      }
    } finally {
      if (!signal.aborted) {
        setIsLoading(false);
      }
    }
  }, [orgId, page, limit, searchQuery, statusFilter, sortBy, sortOrder]);

  useEffect(() => {
    loadHackathons(false);
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [loadHackathons]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    loadHackathons(true);
  };

  return (
    <div className="space-y-6">
      {/* Top Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-text-primary tracking-tight">Organization Hackathons</h1>
          <p className="text-xs text-text-muted mt-0.5">
            Manage your organization's hackathons, timeline schedules, and lifecycle status.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={() => loadHackathons(true)}
            disabled={isLoading}
            className="flex items-center gap-2 px-3 py-2 text-xs font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
          <Link
            href={`/organizations/${orgId}/hackathons/new`}
            className="flex items-center gap-2 px-3.5 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover rounded-lg transition-colors shadow-sm"
          >
            <Plus className="w-4 h-4" />
            <span>Create Hackathon</span>
          </Link>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="flex items-center justify-between p-4 bg-status-error/10 border border-status-error/30 rounded-xl text-status-error text-sm">
          <div className="flex items-center gap-3">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
          <button onClick={() => loadHackathons()} className="text-xs underline font-medium">
            Retry
          </button>
        </div>
      )}

      {/* Search and Filters Bar */}
      <div className="bg-surface p-4 rounded-xl border border-surface-border flex flex-col md:flex-row gap-3 items-stretch md:items-center justify-between">
        <form onSubmit={handleSearchSubmit} className="relative flex-1">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
          <input
            type="text"
            placeholder="Search events by title or slug..."
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
                <th className="py-3 px-4">Event</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4">Timeline Window</th>
                <th className="py-3 px-4">Submission Cutoff</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-border text-text-secondary">
              {isLoading || hackathons.some((h) => h.organization_id !== orgId) ? (
                Array.from({ length: 4 }).map((_, idx) => (
                  <tr key={`skel-${idx}`} className="animate-pulse">
                    <td className="py-3.5 px-4">
                      <div className="h-3.5 bg-surface-elevated rounded w-40 mb-1.5" />
                      <div className="h-2.5 bg-surface-elevated rounded w-24" />
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
                  <td colSpan={5} className="py-12 text-center text-text-muted">
                    <Trophy className="w-8 h-8 mx-auto text-text-muted/40 mb-2" />
                    <p className="text-sm font-medium text-text-secondary">No hackathons hosted yet</p>
                    <p className="text-xs mt-1">Ready to host your first event? Create one below.</p>
                    <Link
                      href={`/organizations/${orgId}/hackathons/new`}
                      className="inline-flex items-center gap-2 mt-4 px-3.5 py-1.5 text-xs font-semibold text-white bg-primary hover:bg-primary-hover rounded-lg transition-colors shadow-sm"
                    >
                      <Plus className="w-4 h-4" />
                      <span>Create New Hackathon</span>
                    </Link>
                  </td>
                </tr>
              ) : (
                hackathons.map((h) => (
                  <tr key={h.id} className="hover:bg-surface-hover/50 transition-colors group">
                    <td className="py-3.5 px-4">
                      <Link
                        href={`/organizations/${orgId}/hackathons/${h.id}`}
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
                      <Link
                        href={`/organizations/${orgId}/hackathons/${h.id}`}
                        className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors"
                      >
                        <span>Manage</span>
                      </Link>
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
    </div>
  );
}
