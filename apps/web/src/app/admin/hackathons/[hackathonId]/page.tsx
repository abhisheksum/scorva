'use client';

import React, { useState, useEffect, useCallback, use } from 'react';
import Link from 'next/link';
import {
  Trophy,
  ChevronLeft,
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  X,
  Building2,
  Calendar,
  Clock,
  ShieldAlert,
  Copy,
  Check,
  User,
  FileText,
  ExternalLink,
  Lock,
  Globe,
  Archive,
} from 'lucide-react';
import { StatusBadge } from '@/components/admin/StatusBadge';
import { api, ApiClientError } from '@/lib/api-client';
import {
  HackathonDetailResponse,
  HackathonStatus,
  AdminUpdateHackathonStatusRequest,
} from '@/types/api';

export default function AdminHackathonDetailPage({
  params,
}: {
  params: Promise<{ hackathonId: string }>;
}) {
  const unwrappedParams = use(params);
  const hackathonId = unwrappedParams.hackathonId;

  const [hackathon, setHackathon] = useState<HackathonDetailResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<boolean>(false);

  // Administrative Override Modal
  const [isOverrideModalOpen, setIsOverrideModalOpen] = useState<boolean>(false);
  const [overrideStatus, setOverrideStatus] = useState<HackathonStatus>('suspended');
  const [overrideReason, setOverrideReason] = useState<string>('');
  const [isSubmittingOverride, setIsSubmittingOverride] = useState<boolean>(false);
  const [overrideError, setOverrideError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await api.getAdminHackathon(hackathonId);
      setHackathon(data);
      setOverrideStatus(data.status === 'suspended' ? 'published' : 'suspended');
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to load hackathon details.');
      }
    } finally {
      setIsLoading(false);
    }
  }, [hackathonId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(true);
    setTimeout(() => setCopiedId(false), 2000);
  };

  const handleOverrideSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setOverrideError(null);

    const trimmedReason = overrideReason.trim();
    if (!trimmedReason) {
      setOverrideError('Mandatory administrative justification reason is required.');
      return;
    }

    setIsSubmittingOverride(true);
    try {
      const updated = await api.overrideAdminHackathonStatus(hackathonId, {
        status: overrideStatus,
        reason: trimmedReason,
      });
      setHackathon(updated);
      setIsOverrideModalOpen(false);
      setOverrideReason('');
      setSuccessMessage(`Hackathon status overridden to "${overrideStatus}".`);
      setTimeout(() => setSuccessMessage(null), 4000);
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
        progress: 10,
      };
    }
    if (now >= start && now <= deadline) {
      return {
        label: 'Submissions Open (Active)',
        badge: 'bg-status-success/10 text-status-success border-status-success/30',
        progress: 50,
      };
    }
    if (now > deadline && now <= end) {
      return {
        label: 'Submissions Cutoff (Judging/Evaluation)',
        badge: 'bg-status-warning/10 text-status-warning border-status-warning/30',
        progress: 80,
      };
    }
    return {
      label: 'Concluded / Closed',
      badge: 'bg-slate-800 text-slate-400 border-slate-700',
      progress: 100,
    };
  };

  if (isLoading && !hackathon) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-4 bg-surface-elevated rounded w-48" />
        <div className="h-24 bg-surface rounded-2xl border border-surface-border p-6" />
        <div className="h-64 bg-surface rounded-2xl border border-surface-border p-6" />
      </div>
    );
  }

  if (error && !hackathon) {
    return (
      <div className="p-8 bg-surface rounded-2xl border border-surface-border text-center">
        <AlertCircle className="w-10 h-10 text-status-error mx-auto mb-3" />
        <h2 className="text-base font-semibold text-text-primary">Failed to load hackathon</h2>
        <p className="text-xs text-text-muted mt-1 mb-4">{error}</p>
        <Link
          href="/admin/hackathons"
          className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-text-primary bg-surface-elevated hover:bg-surface-hover rounded-lg transition-colors border border-surface-border"
        >
          <ChevronLeft className="w-4 h-4" />
          <span>Back to Hackathons</span>
        </Link>
      </div>
    );
  }

  if (!hackathon) return null;

  const timeline = getTimelineStatus();

  return (
    <div className="space-y-6">
      {/* Top Breadcrumb & Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <Link
          href="/admin/hackathons"
          className="inline-flex items-center gap-2 text-xs text-text-muted hover:text-text-primary transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
          <span>Back to Hackathon Oversight</span>
        </Link>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => loadData()}
            disabled={isLoading}
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
          <button
            type="button"
            onClick={() => {
              setOverrideStatus(hackathon.status === 'suspended' ? 'published' : 'suspended');
              setOverrideReason('');
              setOverrideError(null);
              setIsOverrideModalOpen(true);
            }}
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors"
          >
            <ShieldAlert className="w-3.5 h-3.5 text-status-warning" />
            <span>Administrative Override</span>
          </button>
        </div>
      </div>

      {/* Success Notification Banner */}
      {successMessage && (
        <div className="flex items-center gap-3 p-4 bg-status-success/10 border border-status-success/30 rounded-xl text-status-success text-sm animate-in fade-in">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{successMessage}</span>
        </div>
      )}

      {/* Header Banner */}
      <div className="bg-surface rounded-2xl border border-surface-border p-6 shadow-sm">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
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

          {/* Owning Organization Link */}
          {hackathon.organization && (
            <div className="p-3 bg-surface-elevated/70 rounded-xl border border-surface-border shrink-0">
              <span className="text-[10px] font-semibold text-text-muted uppercase tracking-wider block mb-1">
                Owning Organization
              </span>
              <Link
                href={`/admin/organizations/${hackathon.organization_id}`}
                className="flex items-center gap-2 text-xs font-semibold text-text-primary hover:text-primary transition-colors group"
              >
                <Building2 className="w-4 h-4 text-primary" />
                <span>{hackathon.organization.name}</span>
                <ExternalLink className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity" />
              </Link>
            </div>
          )}
        </div>
      </div>

      {/* Event Timeline Visualizer Card */}
      <div className="bg-surface rounded-xl border border-surface-border p-5 space-y-4">
        <div className="flex items-center justify-between border-b border-surface-border pb-3">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-primary" />
            <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider">
              Lifecycle Timeline Constraints (UTC)
            </h3>
          </div>
          <span className="text-[11px] text-text-muted font-mono">Strict ISO 8601</span>
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

        {/* Timeline Rule Notice */}
        <div className="text-[11px] text-text-muted flex items-center gap-2 pt-1">
          <Lock className="w-3.5 h-3.5 text-text-muted/60" />
          <span>Timeline validation rule: start_date &lt; submission_deadline &le; end_date.</span>
        </div>
      </div>

      {/* Description & Settings Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Description / Rules */}
        <div className="bg-surface rounded-xl border border-surface-border p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-surface-border pb-3">
            <div className="flex items-center gap-2">
              <FileText className="w-4 h-4 text-primary" />
              <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider">
                Event Description & Rules
              </h3>
            </div>
          </div>

          {hackathon.description ? (
            <div className="text-xs text-text-secondary whitespace-pre-wrap leading-relaxed max-h-56 overflow-y-auto">
              {hackathon.description}
            </div>
          ) : (
            <p className="text-xs text-text-muted italic">No custom description or rules provided.</p>
          )}
        </div>

        {/* Custom Settings & Creator Card */}
        <div className="space-y-6">
          {/* Creator Summary */}
          {hackathon.created_by && (
            <div className="bg-surface rounded-xl border border-surface-border p-5 space-y-3">
              <div className="flex items-center gap-2 border-b border-surface-border pb-3">
                <User className="w-4 h-4 text-primary" />
                <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider">
                  Event Creator
                </h3>
              </div>
              <div className="text-xs space-y-1">
                <div className="font-semibold text-text-primary">{hackathon.created_by.full_name}</div>
                <div className="text-text-muted font-mono">{hackathon.created_by.email}</div>
                <div className="text-[10px] text-text-muted">User ID: {hackathon.created_by_user_id}</div>
              </div>
            </div>
          )}

          {/* Settings JSON */}
          <div className="bg-surface rounded-xl border border-surface-border p-5 space-y-3">
            <div className="flex items-center justify-between border-b border-surface-border pb-3">
              <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider">
                Hackathon Settings
              </h3>
              <span className="text-[10px] text-text-muted font-mono">JSONB</span>
            </div>
            <pre className="p-3 bg-surface-elevated rounded-lg border border-surface-border text-xs text-text-secondary font-mono overflow-x-auto max-h-40">
              {JSON.stringify(hackathon.settings || {}, null, 2)}
            </pre>
          </div>
        </div>
      </div>

      {/* Modal: Administrative Status Override */}
      {isOverrideModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="bg-surface border border-surface-border rounded-2xl w-full max-w-md shadow-surface-elevated overflow-hidden">
            <div className="p-5 border-b border-surface-border flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-status-warning/10 flex items-center justify-center text-status-warning">
                  <ShieldAlert className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-text-primary">Administrative Override</h3>
                  <p className="text-[11px] text-text-muted">Event: {hackathon.title}</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setIsOverrideModalOpen(false)}
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
                <strong>Platform Override Notice:</strong> This action forces a status change and emits an immutable PostgreSQL audit event with your administrator identity.
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
                  <option value="draft">Draft (Reset lifecycle)</option>
                  <option value="published">Published (Live event)</option>
                  <option value="completed">Completed (Conclude event)</option>
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
                  onClick={() => setIsOverrideModalOpen(false)}
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
