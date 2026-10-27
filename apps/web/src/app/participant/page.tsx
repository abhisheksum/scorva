'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import {
  Users,
  Trophy,
  Github,
  GitBranch,
  Clock,
  CheckCircle2,
  AlertCircle,
  Copy,
  Check,
  RefreshCw,
  LogOut,
  User,
  ExternalLink,
  Shield,
  Layers,
} from 'lucide-react';
import { StatusBadge } from '@/components/admin/StatusBadge';
import { api, ApiClientError } from '@/lib/api-client';
import { useAuth } from '@/lib/auth-context';
import { ParticipantTeamItem } from '@/types/api';

export default function ParticipantWorkspacePage() {
  const { user, logout } = useAuth();
  const [teams, setTeams] = useState<ParticipantTeamItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copiedCode, setCopiedCode] = useState<string | null>(null);

  const fetchTeams = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await api.getParticipantTeams();
      setTeams(data);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to load enrolled teams. Please check your network connection.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchTeams();
  }, []);

  const handleCopyCode = (code: string) => {
    navigator.clipboard.writeText(code);
    setCopiedCode(code);
    setTimeout(() => setCopiedCode(null), 2000);
  };

  return (
    <div className="min-h-screen bg-surface-bg text-text-primary">
      {/* Top Header */}
      <header className="h-16 bg-surface border-b border-surface-border px-4 sm:px-6 flex items-center justify-between shrink-0 z-10">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center text-primary font-bold">
            <Users className="w-4 h-4" />
          </div>
          <div>
            <span className="font-bold text-sm tracking-wide text-text-primary">Scorva Participant Workspace</span>
            <span className="hidden sm:inline-block ml-2 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-primary/10 text-primary border border-primary/20">
              Team Member
            </span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {user?.routing?.accessible_destinations && user.routing.accessible_destinations.length > 1 && (
            <div className="hidden md:flex items-center gap-1.5 pr-2 border-r border-surface-border text-xs">
              <span className="text-text-muted text-[11px]">Workspaces:</span>
              {user.routing.accessible_destinations.map((dest) => (
                <Link
                  key={dest.destination}
                  href={dest.destination}
                  className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors ${
                    dest.destination === '/participant'
                      ? 'bg-primary text-white'
                      : 'text-text-muted hover:text-text-primary hover:bg-surface-elevated'
                  }`}
                >
                  {dest.label}
                </Link>
              ))}
            </div>
          )}

          <div className="flex items-center gap-2 pl-2">
            <div className="w-7 h-7 rounded-full bg-surface-elevated border border-surface-border flex items-center justify-center text-text-primary shrink-0">
              <User className="w-3.5 h-3.5 text-primary" />
            </div>
            <div className="hidden sm:flex flex-col text-left">
              <span className="text-xs font-semibold text-text-primary leading-tight">
                {user?.full_name || user?.email || 'Participant'}
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
        {/* Workspace Title & Actions */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-surface-border pb-6">
          <div>
            <div className="flex items-center gap-2.5 text-xs text-text-muted mb-1">
              <Users className="w-4 h-4 text-primary" />
              <span>Participant Portal</span>
              <span>•</span>
              <span className="text-text-primary font-medium">My Teams</span>
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-text-primary">
              Enrolled Teams & Submissions
            </h1>
            <p className="text-xs text-text-muted mt-1">
              Manage registered hackathon teams, view linked GitHub repositories, and track project status.
            </p>
          </div>

          <button
            type="button"
            onClick={fetchTeams}
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
            <p className="text-xs">Loading your team enrollments...</p>
          </div>
        )}

        {/* Empty State */}
        {!isLoading && teams.length === 0 && !error && (
          <div className="p-12 text-center rounded-2xl border border-surface-border bg-surface max-w-md mx-auto space-y-4 my-8">
            <div className="w-12 h-12 rounded-2xl bg-surface-elevated border border-surface-border flex items-center justify-center text-text-muted mx-auto">
              <Users className="w-6 h-6" />
            </div>
            <div>
              <h3 className="text-base font-bold text-text-primary">No Enrolled Teams</h3>
              <p className="text-xs text-text-muted mt-1 leading-relaxed">
                You are not currently enrolled in any hackathon teams. When you register a team or join via a hackathon invite code, your teams and submission progress will appear here.
              </p>
            </div>
          </div>
        )}

        {/* Teams Grid */}
        {!isLoading && teams.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {teams.map((item) => (
              <div
                key={item.team_id}
                className="bg-surface border border-surface-border hover:border-surface-border-hover rounded-2xl p-6 shadow-sm flex flex-col justify-between transition-all"
              >
                <div className="space-y-4">
                  {/* Top line: Organization & Hackathon Status */}
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] font-medium text-text-muted truncate">
                      {item.organization_name}
                    </span>
                    <StatusBadge status={item.hackathon_status} size="sm" />
                  </div>

                  {/* Team Title & Hackathon */}
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="text-lg font-bold text-text-primary">
                        {item.team_name}
                      </h3>
                      <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-primary/10 text-primary border border-primary/20">
                        {item.role_in_team}
                      </span>
                    </div>
                    <p className="text-xs text-text-muted mt-1 flex items-center gap-1.5">
                      <Trophy className="w-3.5 h-3.5 text-primary" />
                      <span>{item.hackathon_title}</span>
                    </p>
                  </div>

                  {/* Join Code Chip */}
                  <div className="flex items-center justify-between p-3 bg-surface-elevated/40 rounded-xl border border-surface-border/60 text-xs">
                    <span className="text-text-muted text-[11px]">Team Join Code:</span>
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold tracking-wider text-text-primary">
                        {item.join_code}
                      </span>
                      <button
                        type="button"
                        onClick={() => handleCopyCode(item.join_code)}
                        className="p-1 hover:bg-surface-elevated rounded text-text-muted hover:text-text-primary transition-colors"
                        title="Copy Join Code"
                      >
                        {copiedCode === item.join_code ? (
                          <Check className="w-3.5 h-3.5 text-status-success" />
                        ) : (
                          <Copy className="w-3.5 h-3.5" />
                        )}
                      </button>
                    </div>
                  </div>

                  {/* Submission Details */}
                  <div className="pt-3 border-t border-surface-border/60 space-y-2">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-semibold text-text-primary">Project Submission</span>
                      {item.submission ? (
                        <StatusBadge status={item.submission.status} size="sm" />
                      ) : (
                        <span className="text-[11px] text-text-muted italic">Not Created</span>
                      )}
                    </div>

                    {item.submission ? (
                      <div className="p-3.5 bg-surface-elevated/30 rounded-xl border border-surface-border/60 space-y-2 text-xs">
                        <div className="font-medium text-text-primary">
                          {item.submission.title}
                        </div>

                        {item.submission.repository_owner && item.submission.repository_name ? (
                          <div className="space-y-1 pt-1 border-t border-surface-border/40">
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-1.5 font-mono text-[11px] text-text-primary">
                                <Github className="w-3.5 h-3.5 text-text-muted" />
                                <span>
                                  {item.submission.repository_owner}/{item.submission.repository_name}
                                </span>
                              </div>
                              <span
                                className={`px-1.5 py-0.5 rounded text-[10px] font-semibold font-mono ${
                                  item.submission.connection_status === 'verified'
                                    ? 'bg-status-success/10 text-status-success border border-status-success/20'
                                    : 'bg-status-warning/10 text-status-warning border border-status-warning/20'
                                }`}
                              >
                                {item.submission.connection_status}
                              </span>
                            </div>

                            {item.submission.default_branch && (
                              <div className="flex items-center gap-1 font-mono text-[10px] text-text-muted">
                                <GitBranch className="w-3 h-3" />
                                <span>branch: {item.submission.default_branch}</span>
                              </div>
                            )}

                            {item.submission.verified_commit_sha && (
                              <div className="text-[10px] font-mono text-text-muted truncate">
                                commit: {item.submission.verified_commit_sha.slice(0, 7)}
                              </div>
                            )}
                          </div>
                        ) : (
                          <div className="text-text-muted text-[11px] italic">
                            No GitHub repository linked to this submission yet.
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="p-3 bg-surface-elevated/20 rounded-xl border border-dashed border-surface-border text-center text-xs text-text-muted">
                        No submission submitted yet.
                      </div>
                    )}
                  </div>
                </div>

                {/* Footer / Meta */}
                {item.submission_deadline && (
                  <div className="pt-4 mt-4 border-t border-surface-border/60 flex items-center justify-between text-[11px] text-text-muted">
                    <span className="flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      <span>Deadline:</span>
                    </span>
                    <span className="font-medium text-text-primary">
                      {new Date(item.submission_deadline).toLocaleDateString()}
                    </span>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
