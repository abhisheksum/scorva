'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import {
  Scale,
  Calendar,
  Clock,
  CheckCircle2,
  AlertCircle,
  FileText,
  ChevronRight,
  RefreshCw,
  Trophy,
  LogOut,
  User,
} from 'lucide-react';
import { StatusBadge } from '@/components/admin/StatusBadge';
import { api, ApiClientError } from '@/lib/api-client';
import { useAuth } from '@/lib/auth-context';
import { JudgeAssignmentItem } from '@/types/api';

export default function JudgeWorkspacePage() {
  const { user, logout } = useAuth();
  const [assignments, setAssignments] = useState<JudgeAssignmentItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAssignments = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await api.getJudgeAssignments();
      setAssignments(data);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to load judge assignments. Please check your network connection.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchAssignments();
  }, []);

  return (
    <div className="min-h-screen bg-surface-bg text-text-primary">
      {/* Top Header */}
      <header className="h-16 bg-surface border-b border-surface-border px-4 sm:px-6 flex items-center justify-between shrink-0 z-10">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center text-primary font-bold">
            <Scale className="w-4 h-4" />
          </div>
          <div>
            <span className="font-bold text-sm tracking-wide text-text-primary">Scorva Judge Workspace</span>
            <span className="hidden sm:inline-block ml-2 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-primary/10 text-primary border border-primary/20">
              Assigned Judge
            </span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 pl-2 border-l border-surface-border">
            <div className="w-7 h-7 rounded-full bg-surface-elevated border border-surface-border flex items-center justify-center text-text-primary shrink-0">
              <User className="w-3.5 h-3.5 text-primary" />
            </div>
            <div className="hidden sm:flex flex-col text-left">
              <span className="text-xs font-semibold text-text-primary leading-tight">
                {user?.full_name || user?.email || 'Judge'}
              </span>
              <span className="text-[10px] text-text-muted leading-tight">
                {user?.email}
              </span>
            </div>
            <button
              type="button"
              onClick={async () => {
                await logout();
              }}
              className="p-1.5 text-text-muted hover:text-status-error hover:bg-status-error/10 rounded-lg transition-colors ml-1"
              title="Log out"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      <div className="p-6 md:p-8 max-w-6xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-surface-border pb-6">
          <div>
            <div className="flex items-center gap-2.5 text-xs text-text-muted mb-1">
              <Scale className="w-4 h-4 text-primary" />
              <span>Judge Workspace</span>
              <span>•</span>
              <span className="text-text-primary font-medium">Assigned Events</span>
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-text-primary flex items-center gap-2">
              Judge Evaluation Dashboard
            </h1>
            <p className="text-xs text-text-muted mt-1">
              Review hackathon submissions against published rubrics. AI evaluates the evidence. Judges make the decisions.
            </p>
          </div>

          <button
            type="button"
            onClick={fetchAssignments}
            disabled={isLoading}
            className="self-start md:self-auto px-3.5 py-2 text-xs font-semibold text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors inline-flex items-center gap-1.5 shadow-sm disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
        </div>

        {/* Error Alert */}
        {error && (
          <div className="p-4 rounded-xl bg-status-danger/10 border border-status-danger/20 text-status-danger flex items-center gap-3 text-xs">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Loading State */}
        {isLoading && (
          <div className="p-12 text-center text-text-muted space-y-3">
            <RefreshCw className="w-6 h-6 animate-spin mx-auto text-primary" />
            <p className="text-xs">Loading your assigned hackathons...</p>
          </div>
        )}

        {/* Empty State */}
        {!isLoading && assignments.length === 0 && !error && (
          <div className="p-12 text-center rounded-xl border border-surface-border bg-surface-card space-y-3">
            <Scale className="w-10 h-10 mx-auto text-text-muted/60" />
            <h3 className="text-sm font-semibold text-text-primary">No Hackathons Assigned</h3>
            <p className="text-xs text-text-muted max-w-md mx-auto">
              You are not currently assigned as a judge for any active hackathons. Organizers will invite or assign you using your registered account email.
            </p>
          </div>
        )}

        {/* Assignments Grid */}
        {!isLoading && assignments.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {assignments.map((assignment) => {
              const completionRate =
                assignment.total_submissions > 0
                  ? Math.round((assignment.my_submitted_count / assignment.total_submissions) * 100)
                  : 0;

              return (
                <div
                  key={assignment.hackathon_id}
                  className="bg-surface-card border border-surface-border hover:border-surface-border-hover rounded-xl p-5 shadow-sm flex flex-col justify-between transition-all"
                >
                  <div className="space-y-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[11px] font-medium text-text-muted truncate">
                        {assignment.organization_name}
                      </span>
                      <StatusBadge status={assignment.hackathon_status} size="sm" />
                    </div>

                    <div>
                      <h3 className="text-base font-bold text-text-primary hover:text-primary transition-colors line-clamp-1">
                        {assignment.hackathon_title}
                      </h3>
                      {assignment.submission_deadline && (
                        <div className="flex items-center gap-1.5 text-[11px] text-text-muted mt-1">
                          <Clock className="w-3.5 h-3.5 text-text-muted/70" />
                          <span>Deadline: {new Date(assignment.submission_deadline).toLocaleDateString()}</span>
                        </div>
                      )}
                    </div>

                    {/* Progress Bar */}
                    <div className="pt-2 border-t border-surface-border/60 space-y-1.5">
                      <div className="flex items-center justify-between text-[11px]">
                        <span className="text-text-muted">Review Completion</span>
                        <span className="font-semibold text-text-primary font-mono">{completionRate}%</span>
                      </div>
                      <div className="w-full h-1.5 bg-surface-elevated rounded-full overflow-hidden">
                        <div
                          className="h-full bg-primary transition-all duration-300"
                          style={{ width: `${completionRate}%` }}
                        />
                      </div>
                    </div>

                    {/* Counters */}
                    <div className="grid grid-cols-3 gap-2 pt-2 text-center text-xs">
                      <div className="p-2 bg-surface-elevated/40 rounded-lg border border-surface-border/50">
                        <span className="text-[10px] text-text-muted block uppercase font-medium">Submitted</span>
                        <span className="font-bold text-status-success font-mono">
                          {assignment.my_submitted_count}
                        </span>
                      </div>
                      <div className="p-2 bg-surface-elevated/40 rounded-lg border border-surface-border/50">
                        <span className="text-[10px] text-text-muted block uppercase font-medium">Drafts</span>
                        <span className="font-bold text-status-warning font-mono">
                          {assignment.my_draft_count}
                        </span>
                      </div>
                      <div className="p-2 bg-surface-elevated/40 rounded-lg border border-surface-border/50">
                        <span className="text-[10px] text-text-muted block uppercase font-medium">Pending</span>
                        <span className="font-bold text-text-primary font-mono">
                          {assignment.my_pending_count}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="pt-4 mt-4 border-t border-surface-border/60">
                    <Link
                      href={`/judge/hackathons/${assignment.hackathon_id}/submissions`}
                      className="w-full py-2 px-3 text-xs font-semibold text-white bg-primary hover:bg-primary-hover rounded-lg transition-colors flex items-center justify-center gap-1.5 shadow-sm"
                    >
                      <span>Open Review Queue</span>
                      <ChevronRight className="w-3.5 h-3.5" />
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
