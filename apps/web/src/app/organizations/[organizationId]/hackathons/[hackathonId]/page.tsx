'use client';

import React, { useState, useEffect, useCallback, useRef, use } from 'react';
import Link from 'next/link';
import {
  Trophy,
  ChevronLeft,
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  Calendar,
  Clock,
  Globe,
  CheckCheck,
  Archive,
  ShieldAlert,
  Lock,
  FileText,
  Copy,
  Check,
  Edit,
  X,
} from 'lucide-react';
import { StatusBadge } from '@/components/admin/StatusBadge';
import { api, ApiClientError } from '@/lib/api-client';
import {
  HackathonDetailResponse,
  HackathonStatus,
  UpdateHackathonRequest,
} from '@/types/api';

export default function TenantHackathonDetailPage({
  params,
}: {
  params: Promise<{ organizationId: string; hackathonId: string }>;
}) {
  const unwrappedParams = use(params);
  const { organizationId: orgId, hackathonId } = unwrappedParams;

  const [prevIds, setPrevIds] = useState<{ orgId: string; hackathonId: string }>({ orgId, hackathonId });
  const [hackathon, setHackathon] = useState<HackathonDetailResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<boolean>(false);

  // Lifecycle Action In Progress
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);

  // Edit Modal State
  const [isEditModalOpen, setIsEditModalOpen] = useState<boolean>(false);
  const [editTitle, setEditTitle] = useState<string>('');
  const [editDescription, setEditDescription] = useState<string>('');
  const [isSavingEdit, setIsSavingEdit] = useState<boolean>(false);

  // Synchronous render-phase state adjustment: eliminates 1-frame stale data paint on navigation
  if (orgId !== prevIds.orgId || hackathonId !== prevIds.hackathonId) {
    setPrevIds({ orgId, hackathonId });
    setHackathon(null);
    setEditTitle('');
    setEditDescription('');
    setIsLoading(true);
    setError(null);
  }

  const abortControllerRef = useRef<AbortController | null>(null);

  const loadData = useCallback(async (isRefresh: boolean = false) => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const signal = controller.signal;

    if (!isRefresh) {
      setHackathon(null);
      setIsLoading(true);
      setError(null);
    }

    try {
      const data = await api.getTenantHackathon(orgId, hackathonId, { signal });
      if (!signal.aborted) {
        setHackathon(data);
        setEditTitle(data.title);
        setEditDescription(data.description || '');
      }
    } catch (err: unknown) {
      if (signal.aborted) return;
      if (err instanceof ApiClientError && err.code === 'REQUEST_ABORTED') return;
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to load hackathon details.');
      }
    } finally {
      if (!signal.aborted) {
        setIsLoading(false);
      }
    }
  }, [orgId, hackathonId]);

  useEffect(() => {
    loadData(false);
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [loadData]);

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(true);
    setTimeout(() => setCopiedId(false), 2000);
  };

  // State Machine Transitions
  const handlePublish = async () => {
    if (
      !confirm(
        'Are you sure you want to publish this hackathon? Once published, its slug and owning organization cannot be changed.'
      )
    ) {
      return;
    }

    setActionInProgress('publish');
    setError(null);
    try {
      const updated = await api.publishTenantHackathon(orgId, hackathonId);
      setHackathon(updated);
      setSuccessMessage('Hackathon published successfully! It is now live.');
      setTimeout(() => setSuccessMessage(null), 4000);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to publish hackathon.');
      }
    } finally {
      setActionInProgress(null);
    }
  };

  const handleComplete = async () => {
    if (
      !confirm(
        'Complete this hackathon? Submissions will close and the event will be marked as concluded.'
      )
    ) {
      return;
    }

    setActionInProgress('complete');
    setError(null);
    try {
      const updated = await api.completeTenantHackathon(orgId, hackathonId);
      setHackathon(updated);
      setSuccessMessage('Hackathon marked as completed.');
      setTimeout(() => setSuccessMessage(null), 4000);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to complete hackathon.');
      }
    } finally {
      setActionInProgress(null);
    }
  };

  const handleArchive = async () => {
    if (
      !confirm(
        'Archive this completed hackathon? It will be moved to cold storage and set to read-only.'
      )
    ) {
      return;
    }

    setActionInProgress('archive');
    setError(null);
    try {
      const updated = await api.archiveTenantHackathon(orgId, hackathonId);
      setHackathon(updated);
      setSuccessMessage('Hackathon successfully archived.');
      setTimeout(() => setSuccessMessage(null), 4000);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to archive hackathon.');
      }
    } finally {
      setActionInProgress(null);
    }
  };

  const handleSuspendResume = async (targetStatus: HackathonStatus) => {
    const actionName = targetStatus === 'suspended' ? 'suspend' : 'resume';
    if (!confirm(`Are you sure you want to ${actionName} this hackathon?`)) {
      return;
    }

    setActionInProgress(actionName);
    setError(null);
    try {
      const updated = await api.updateTenantHackathonStatus(orgId, hackathonId, {
        status: targetStatus,
        reason: `Tenant organizer ${actionName}`,
      });
      setHackathon(updated);
      setSuccessMessage(`Hackathon successfully ${actionName}ed.`);
      setTimeout(() => setSuccessMessage(null), 4000);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError(`Failed to ${actionName} hackathon.`);
      }
    } finally {
      setActionInProgress(null);
    }
  };

  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSavingEdit(true);
    setError(null);
    try {
      const updated = await api.updateTenantHackathon(orgId, hackathonId, {
        title: editTitle.trim(),
        description: editDescription.trim() || undefined,
      });
      setHackathon(updated);
      setIsEditModalOpen(false);
      setSuccessMessage('Hackathon details saved.');
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to update hackathon.');
      }
    } finally {
      setIsSavingEdit(false);
    }
  };

  // Timeline Progress Calculator
  const getTimelineStatus = () => {
    if (!hackathon) return null;
    const now = new Date();
    const start = new Date(hackathon.start_date);
    const deadline = new Date(hackathon.submission_deadline);
    const end = new Date(hackathon.end_date);

    if (now < start) {
      return {
        label: 'Upcoming / Scheduled',
        badge: 'bg-status-info/10 text-status-info border-status-info/30',
      };
    }
    if (now >= start && now <= deadline) {
      return {
        label: 'Submissions Open (Active)',
        badge: 'bg-status-success/10 text-status-success border-status-success/30',
      };
    }
    if (now > deadline && now <= end) {
      return {
        label: 'Judging / Evaluation Period',
        badge: 'bg-status-warning/10 text-status-warning border-status-warning/30',
      };
    }
    return {
      label: 'Concluded / Closed',
      badge: 'bg-slate-800 text-slate-400 border-slate-700',
    };
  };

  const isStale = Boolean(hackathon && (hackathon.id !== hackathonId || hackathon.organization_id !== orgId));

  if (error && !hackathon) {
    return (
      <div className="p-8 bg-surface rounded-2xl border border-surface-border text-center">
        <AlertCircle className="w-10 h-10 text-status-error mx-auto mb-3" />
        <h2 className="text-base font-semibold text-text-primary">Failed to load hackathon</h2>
        <p className="text-xs text-text-muted mt-1 mb-4">{error}</p>
        <Link
          href={`/organizations/${orgId}/hackathons`}
          className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-text-primary bg-surface-elevated hover:bg-surface-hover rounded-lg transition-colors border border-surface-border"
        >
          <ChevronLeft className="w-4 h-4" />
          <span>Back to Hackathons</span>
        </Link>
      </div>
    );
  }

  if (isLoading || !hackathon || isStale) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-4 bg-surface-elevated rounded w-48" />
        <div className="h-24 bg-surface rounded-2xl border border-surface-border p-6" />
        <div className="h-64 bg-surface rounded-2xl border border-surface-border p-6" />
      </div>
    );
  }

  if (!hackathon) return null;

  const timeline = getTimelineStatus();

  return (
    <div className="space-y-6">
      {/* Top Breadcrumb & Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <Link
          href={`/organizations/${orgId}/hackathons`}
          className="inline-flex items-center gap-2 text-xs text-text-muted hover:text-text-primary transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
          <span>Back to Organization Hackathons</span>
        </Link>

        <div className="flex items-center gap-2 flex-wrap">
          <button
            type="button"
            onClick={() => loadData(true)}
            disabled={isLoading}
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>

          {/* State Machine Transition Buttons */}
          {hackathon.status === 'draft' && (
            <>
              <button
                type="button"
                onClick={() => setIsEditModalOpen(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors"
              >
                <Edit className="w-3.5 h-3.5" />
                <span>Edit Draft</span>
              </button>
              <button
                type="button"
                onClick={handlePublish}
                disabled={actionInProgress !== null}
                className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg transition-colors shadow-sm"
              >
                <Globe className="w-3.5 h-3.5" />
                <span>Publish Event</span>
              </button>
            </>
          )}

          {hackathon.status === 'published' && (
            <>
              <button
                type="button"
                onClick={handleComplete}
                disabled={actionInProgress !== null}
                className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold text-white bg-status-success hover:bg-status-success/90 disabled:opacity-50 rounded-lg transition-colors shadow-sm"
              >
                <CheckCheck className="w-3.5 h-3.5" />
                <span>Complete Event</span>
              </button>
              <button
                type="button"
                onClick={() => handleSuspendResume('suspended')}
                disabled={actionInProgress !== null}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-status-error bg-status-error/10 hover:bg-status-error/20 border border-status-error/30 rounded-lg transition-colors"
              >
                <ShieldAlert className="w-3.5 h-3.5" />
                <span>Suspend</span>
              </button>
            </>
          )}

          {hackathon.status === 'completed' && (
            <button
              type="button"
              onClick={handleArchive}
              disabled={actionInProgress !== null}
              className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors"
            >
              <Archive className="w-3.5 h-3.5 text-text-muted" />
              <span>Archive to Cold Storage</span>
            </button>
          )}

          {hackathon.status === 'suspended' && (
            <button
              type="button"
              onClick={() => handleSuspendResume('published')}
              disabled={actionInProgress !== null}
              className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg transition-colors"
            >
              <span>Reactivate Hackathon</span>
            </button>
          )}
        </div>
      </div>

      {/* Notifications */}
      {successMessage && (
        <div className="flex items-center gap-3 p-4 bg-status-success/10 border border-status-success/30 rounded-xl text-status-success text-sm animate-in fade-in">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{successMessage}</span>
        </div>
      )}

      {error && (
        <div className="flex items-center justify-between p-4 bg-status-error/10 border border-status-error/30 rounded-xl text-status-error text-sm">
          <div className="flex items-center gap-3">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)} className="text-xs font-bold">
            Dismiss
          </button>
        </div>
      )}

      {/* Header Banner */}
      <div className="bg-surface rounded-2xl border border-surface-border p-6 shadow-sm">
        <div className="flex items-start gap-4">
          <div className="w-14 h-14 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary shrink-0 shadow-inner">
            <Trophy className="w-7 h-7" />
          </div>
          <div>
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-xl font-bold text-text-primary tracking-tight">
                {hackathon.title}
              </h1>
              <StatusBadge status={hackathon.status} size="sm" />
              {timeline && (
                <span
                  className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[10px] font-semibold ${timeline.badge}`}
                >
                  {timeline.label}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 text-xs text-text-muted mt-1 flex-wrap">
              <span className="font-mono bg-surface-elevated px-2 py-0.5 rounded border border-surface-border text-text-secondary">
                /{hackathon.slug}
              </span>
              <span className="flex items-center gap-1 font-mono">
                ID: {hackathon.id.slice(0, 8)}...
                <button
                  onClick={() => copyToClipboard(hackathon.id)}
                  className="p-1 hover:text-text-primary transition-colors"
                  title="Copy UUID"
                >
                  {copiedId ? <Check className="w-3 h-3 text-status-success" /> : <Copy className="w-3 h-3" />}
                </button>
              </span>
              <span className="flex items-center gap-1">
                <Calendar className="w-3 h-3" />
                Created: {new Date(hackathon.created_at).toLocaleDateString()}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Timeline Constraints Banner */}
      <div className="bg-surface rounded-xl border border-surface-border p-5 space-y-4">
        <div className="flex items-center justify-between border-b border-surface-border pb-3">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-primary" />
            <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider">
              Event Timeline (UTC)
            </h3>
          </div>
          <span className="text-[11px] text-text-muted font-mono">
            {hackathon.status === 'published' ? 'Immutable Timeline' : 'Draft Schedule'}
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="p-3 bg-surface-elevated rounded-lg border border-surface-border">
            <span className="text-[11px] text-text-muted block">Event Start Date</span>
            <span className="font-semibold text-text-primary text-xs mt-0.5 block">
              {new Date(hackathon.start_date).toUTCString()}
            </span>
          </div>

          <div className="p-3 bg-surface-elevated rounded-lg border border-primary/30 bg-primary/5">
            <span className="text-[11px] text-primary font-semibold block">Submission Deadline (Cutoff)</span>
            <span className="font-semibold text-text-primary text-xs mt-0.5 block">
              {new Date(hackathon.submission_deadline).toUTCString()}
            </span>
          </div>

          <div className="p-3 bg-surface-elevated rounded-lg border border-surface-border">
            <span className="text-[11px] text-text-muted block">Event Conclusion Date</span>
            <span className="font-semibold text-text-primary text-xs mt-0.5 block">
              {new Date(hackathon.end_date).toUTCString()}
            </span>
          </div>
        </div>
      </div>

      {/* Description & Rules */}
      <div className="bg-surface rounded-xl border border-surface-border p-5 space-y-4">
        <div className="flex items-center gap-2 border-b border-surface-border pb-3">
          <FileText className="w-4 h-4 text-primary" />
          <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider">
            Description & Participation Rules
          </h3>
        </div>

        {hackathon.description ? (
          <div className="text-xs text-text-secondary whitespace-pre-wrap leading-relaxed">
            {hackathon.description}
          </div>
        ) : (
          <p className="text-xs text-text-muted italic">No custom description or rules provided.</p>
        )}
      </div>

      {/* Edit Draft Modal */}
      {isEditModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="bg-surface border border-surface-border rounded-2xl w-full max-w-md shadow-surface-elevated overflow-hidden">
            <div className="p-5 border-b border-surface-border flex items-center justify-between">
              <h3 className="text-sm font-semibold text-text-primary">Edit Draft Hackathon</h3>
              <button
                type="button"
                onClick={() => setIsEditModalOpen(false)}
                className="p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-surface-elevated transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleSaveEdit} className="p-5 space-y-4 text-xs">
              <div>
                <label className="block font-medium text-text-secondary mb-1">Title</label>
                <input
                  type="text"
                  required
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>

              <div>
                <label className="block font-medium text-text-secondary mb-1">Description</label>
                <textarea
                  rows={4}
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>

              <div className="pt-2 flex items-center justify-end gap-2.5 border-t border-surface-border">
                <button
                  type="button"
                  onClick={() => setIsEditModalOpen(false)}
                  className="px-3 py-2 text-xs font-medium text-text-muted hover:text-text-primary hover:bg-surface-elevated rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSavingEdit || !editTitle.trim()}
                  className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg transition-colors shadow-sm"
                >
                  {isSavingEdit ? 'Saving...' : 'Save Draft'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
