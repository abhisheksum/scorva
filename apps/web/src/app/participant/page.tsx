'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import {
  Trophy,
  Layers,
  Clock,
  CheckCircle2,
  AlertCircle,
  Copy,
  Check,
  RefreshCw,
  ArrowRight,
  Github,
  GitBranch,
  ShieldCheck,
  Calendar,
  Sparkles,
  Award,
  ChevronRight,
  ExternalLink,
  Megaphone,
} from 'lucide-react';
import { api, ApiClientError } from '@/lib/api-client';
import { ParticipantOverviewResponse, ParticipantTeamItem, ParticipantNotificationItem } from '@/types/api';

export default function ParticipantOverviewPage() {
  const [data, setData] = useState<ParticipantOverviewResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copiedCode, setCopiedCode] = useState<string | null>(null);

  // Announcements state
  const [announcements, setAnnouncements] = useState<ParticipantNotificationItem[]>([]);
  const [isAnnouncementsLoading, setIsAnnouncementsLoading] = useState(true);
  const [announcementsError, setAnnouncementsError] = useState<string | null>(null);

  const fetchOverview = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await api.getParticipantOverview();
      setData(res);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to load participant overview. Please verify your connection.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  const fetchAnnouncements = async () => {
    setIsAnnouncementsLoading(true);
    setAnnouncementsError(null);
    try {
      const res = await api.getParticipantNotifications();
      const items = (res.notifications || []).filter((n) => n.type === 'announcement');
      setAnnouncements(items.slice(0, 3));
    } catch {
      setAnnouncementsError('Unable to load latest announcements.');
    } finally {
      setIsAnnouncementsLoading(false);
    }
  };

  useEffect(() => {
    fetchOverview();
    fetchAnnouncements();
  }, []);

  const handleCopyCode = (code: string) => {
    navigator.clipboard.writeText(code);
    setCopiedCode(code);
    setTimeout(() => setCopiedCode(null), 2000);
  };

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center">
        <RefreshCw className="w-8 h-8 text-[#2563EB] animate-spin mb-3" />
        <h3 className="text-sm font-semibold text-[#111827]">Loading Workspace Overview</h3>
        <p className="text-xs text-[#64748B] mt-1">Retrieving your teams, submissions, and timeline...</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="bg-white border border-[#E2E8F0] rounded-xl p-8 text-center max-w-xl mx-auto shadow-xs">
        <AlertCircle className="w-10 h-10 text-[#DC2626] mx-auto mb-3" />
        <h3 className="text-base font-semibold text-[#111827]">Unable to load dashboard</h3>
        <p className="text-sm text-[#64748B] mt-1 mb-6">{error || 'Something went wrong.'}</p>
        <button
          onClick={fetchOverview}
          className="inline-flex items-center gap-2 px-4 py-2 bg-[#2563EB] text-white text-xs font-medium rounded-lg hover:bg-[#1D4ED8] transition-colors"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Welcome Banner */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl p-6 sm:p-8 flex flex-col md:flex-row md:items-center justify-between gap-6 shadow-xs">
        <div>
          <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full bg-[#EFF6FF] border border-[#BFDBFE] text-xs font-semibold text-[#2563EB] mb-2.5">
            <Sparkles className="w-3.5 h-3.5" />
            Hackathon Participant Workspace
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-[#111827]">
            Welcome back, {data.welcome_name}
          </h1>
          <p className="text-sm text-[#64748B] mt-1.5 max-w-2xl">
            Track your team’s progress, manage your submission, review evaluation feedback, and monitor real-time rankings.
          </p>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          <Link
            href="/participant/leaderboard"
            className="inline-flex items-center gap-2 px-4 py-2.5 bg-[#2563EB] text-white text-xs font-semibold rounded-lg hover:bg-[#1D4ED8] transition-colors shadow-xs"
          >
            <Trophy className="w-4 h-4" />
            Live Leaderboard
          </Link>
          <Link
            href="/participant/performance"
            className="inline-flex items-center gap-2 px-4 py-2.5 bg-white text-[#111827] text-xs font-semibold rounded-lg border border-[#E2E8F0] hover:bg-[#F8FAFC] transition-colors shadow-xs"
          >
            My Performance
          </Link>
        </div>
      </div>

      {/* 4 Top Metric Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-6">
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-[#64748B]">Active Events</span>
            <div className="w-8 h-8 rounded-lg bg-[#EFF6FF] flex items-center justify-center text-[#2563EB]">
              <Layers className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-[#111827]">{data.active_hackathons_count}</span>
            <span className="text-xs text-[#64748B]">Enrolled</span>
          </div>
          <p className="text-xs text-[#64748B] mt-1">Hackathons you are participating in</p>
        </div>

        <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-[#64748B]">Project Status</span>
            <div className="w-8 h-8 rounded-lg bg-[#EFF6FF] flex items-center justify-center text-[#2563EB]">
              <ShieldCheck className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-lg font-bold text-[#111827] truncate capitalize">
              {data.submission_status.replace('_', ' ')}
            </span>
          </div>
          <p className="text-xs text-[#64748B] mt-1">Primary team submission state</p>
        </div>

        <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-[#64748B]">Current Standing</span>
            <div className="w-8 h-8 rounded-lg bg-[#EFF6FF] flex items-center justify-center text-[#2563EB]">
              <Trophy className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-[#111827]">
              {data.current_rank ? `#${data.current_rank}` : '—'}
            </span>
            <span className="text-xs text-[#64748B]">Rank</span>
          </div>
          <p className="text-xs text-[#64748B] mt-1">
            {data.current_rank ? 'Official placement' : 'Pending published results'}
          </p>
        </div>

        <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-[#64748B]">Overall Score</span>
            <div className="w-8 h-8 rounded-lg bg-[#EFF6FF] flex items-center justify-center text-[#2563EB]">
              <Award className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-[#111827]">
              {data.total_score !== null && data.total_score !== undefined ? `${data.total_score}` : '—'}
            </span>
            <span className="text-xs text-[#64748B]">/ 100</span>
          </div>
          <p className="text-xs text-[#64748B] mt-1">Weighted evaluation total</p>
        </div>
      </div>

      {/* Lifecycle Progress Stepper */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl p-6 shadow-xs">
        <div className="flex items-center justify-between pb-4 border-b border-[#E2E8F0] mb-6">
          <div>
            <h2 className="text-base font-bold text-[#111827]">Hackathon Progression</h2>
            <p className="text-xs text-[#64748B] mt-0.5">Key milestones from registration to final results</p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-6 gap-3">
          {data.stages.map((stage, idx) => {
            const isCompleted = stage.status === 'completed';
            const isInProgress = stage.status === 'in_progress';
            return (
              <div
                key={stage.id}
                className={`flex flex-col p-3.5 rounded-lg border transition-all ${
                  isCompleted
                    ? 'bg-[#F0FDF4] border-[#BBF7D0]'
                    : isInProgress
                    ? 'bg-[#EFF6FF] border-[#BFDBFE]'
                    : 'bg-[#F8FAFC] border-[#E2E8F0]'
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-[#64748B]">
                    Step {idx + 1}
                  </span>
                  {isCompleted && <CheckCircle2 className="w-4 h-4 text-[#16A34A]" />}
                  {isInProgress && (
                    <span className="flex h-2 w-2 relative">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#2563EB] opacity-75"></span>
                      <span className="relative inline-flex rounded-full h-2 w-2 bg-[#2563EB]"></span>
                    </span>
                  )}
                  {!isCompleted && !isInProgress && (
                    <div className="w-2.5 h-2.5 rounded-full bg-[#CBD5E1]" />
                  )}
                </div>
                <span className="text-xs font-semibold text-[#111827] leading-snug">{stage.name}</span>
                <span className="text-[11px] text-[#64748B] mt-1 leading-normal line-clamp-2">
                  {stage.description}
                </span>
                <span
                  className={`mt-2 text-[10px] font-semibold uppercase tracking-wider ${
                    isCompleted
                      ? 'text-[#16A34A]'
                      : isInProgress
                      ? 'text-[#2563EB]'
                      : 'text-[#94A3B8]'
                  }`}
                >
                  {isCompleted ? 'Completed' : isInProgress ? 'In Progress' : 'Upcoming'}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Participations: Teams & Project Details */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-[#111827]">Your Teams & Submissions</h2>
          <span className="text-xs text-[#64748B] font-medium">
            {data.participations.length} {data.participations.length === 1 ? 'Hackathon' : 'Hackathons'}
          </span>
        </div>

        {data.participations.length === 0 ? (
          <div className="bg-white border border-[#E2E8F0] rounded-xl p-8 text-center shadow-xs">
            <Layers className="w-10 h-10 text-[#94A3B8] mx-auto mb-3" />
            <h3 className="text-sm font-semibold text-[#111827]">No active hackathons found</h3>
            <p className="text-xs text-[#64748B] mt-1">
              You are not enrolled in any hackathon teams yet. Reach out to your event organizer to receive an invitation or join code.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-6">
            {data.participations.map((team: ParticipantTeamItem) => (
              <div
                key={team.team_id}
                className="bg-white border border-[#E2E8F0] rounded-xl p-6 shadow-xs flex flex-col gap-6"
              >
                {/* Header Info */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-[#E2E8F0] gap-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold text-[#2563EB] bg-[#EFF6FF] px-2 py-0.5 rounded-md border border-[#BFDBFE]">
                        {team.organization_name}
                      </span>
                      <span className="text-xs text-[#64748B]">Role: <strong className="capitalize text-[#111827]">{team.role_in_team}</strong></span>
                    </div>
                    <h3 className="text-xl font-bold text-[#111827] mt-1.5">
                      {team.hackathon_title}
                    </h3>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="text-xs text-[#64748B]">Team Join Code:</span>
                    <button
                      onClick={() => handleCopyCode(team.join_code)}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-[#F8FAFC] border border-[#E2E8F0] text-xs font-mono font-medium text-[#111827] hover:bg-[#F1F5F9] transition-colors"
                      title="Copy join code to share with teammates"
                    >
                      <span>{team.join_code}</span>
                      {copiedCode === team.join_code ? (
                        <Check className="w-3.5 h-3.5 text-[#16A34A]" />
                      ) : (
                        <Copy className="w-3.5 h-3.5 text-[#64748B]" />
                      )}
                    </button>
                  </div>
                </div>

                {/* Team Details & Submission Block */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Left: Team Members */}
                  <div className="space-y-3">
                    <span className="text-xs font-semibold uppercase tracking-wider text-[#64748B]">
                      Team: <strong className="text-[#111827] normal-case">{team.team_name}</strong>
                    </span>
                    <div className="p-4 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0] space-y-2">
                      <span className="text-xs font-medium text-[#475569] block">Roster ({(team.team_members || []).length} members):</span>
                      <div className="flex flex-wrap gap-2">
                        {(team.team_members || []).map((member, idx) => (
                          <span
                            key={idx}
                            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-white border border-[#E2E8F0] text-[#111827]"
                          >
                            <span className="w-1.5 h-1.5 rounded-full bg-[#2563EB]" />
                            {member}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>

                  {/* Right: Submission Info */}
                  <div className="space-y-3">
                    <span className="text-xs font-semibold uppercase tracking-wider text-[#64748B]">
                      Project Submission
                    </span>
                    {team.submission ? (
                      <div className="p-4 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0] space-y-3">
                        <div className="flex items-center justify-between">
                          <span className="text-sm font-bold text-[#111827] truncate">
                            {team.submission.title}
                          </span>
                          <span className="text-[11px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full bg-[#F0FDF4] text-[#16A34A] border border-[#BBF7D0]">
                            {team.submission.connection_status}
                          </span>
                        </div>

                        {team.submission.description && (
                          <p className="text-xs text-[#64748B] line-clamp-2">
                            {team.submission.description}
                          </p>
                        )}

                        <div className="flex flex-wrap items-center gap-3 text-xs text-[#64748B] pt-1 border-t border-[#E2E8F0]/80">
                          <a
                            href={team.submission.repository_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 text-[#2563EB] hover:underline font-medium"
                          >
                            <Github className="w-3.5 h-3.5" />
                            <span>{team.submission.repository_name || 'Repository'}</span>
                            <ExternalLink className="w-3 h-3" />
                          </a>
                          {team.submission.default_branch && (
                            <span className="inline-flex items-center gap-1">
                              <GitBranch className="w-3.5 h-3.5 text-[#64748B]" />
                              {team.submission.default_branch}
                            </span>
                          )}
                          {team.submission.verified_commit_sha && (
                            <span className="font-mono text-[11px] bg-white px-1.5 py-0.5 rounded border border-[#E2E8F0]">
                              {team.submission.verified_commit_sha.slice(0, 7)}
                            </span>
                          )}
                        </div>
                      </div>
                    ) : (
                      <div className="p-4 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0] text-center">
                        <p className="text-xs text-[#64748B]">No project submitted yet for this hackathon.</p>
                      </div>
                    )}
                  </div>
                </div>

                {/* Footer Quick Links */}
                <div className="flex flex-wrap items-center justify-between pt-3 border-t border-[#E2E8F0] text-xs text-[#64748B] gap-2">
                  <div className="flex items-center gap-1.5">
                    <Calendar className="w-3.5 h-3.5 text-[#2563EB]" />
                    <span>
                      {team.submission_deadline
                        ? `Submission Deadline: ${new Date(team.submission_deadline).toLocaleString()}`
                        : 'Submission deadline TBA by organizer'}
                    </span>
                  </div>

                  <div className="flex items-center gap-3">
                    <Link
                      href={`/participant/performance?hackathon_id=${team.hackathon_id}`}
                      className="font-medium text-[#2563EB] hover:underline inline-flex items-center gap-1"
                    >
                      View Detailed Feedback
                      <ChevronRight className="w-3.5 h-3.5" />
                    </Link>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Dedicated Announcements Section */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl p-6 shadow-xs space-y-4">
        <div className="flex items-center justify-between pb-3 border-b border-[#E2E8F0]">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-[#EFF6FF] flex items-center justify-center text-[#2563EB]">
              <Megaphone className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-[#111827]">Announcements & Broadcasts</h3>
              <p className="text-[11px] text-[#64748B]">Official updates from competition organizers</p>
            </div>
          </div>
          <Link
            href="/participant/announcements"
            className="text-xs font-semibold text-[#2563EB] hover:underline inline-flex items-center gap-1"
          >
            <span>View All Announcements</span>
            <ChevronRight className="w-3.5 h-3.5" />
          </Link>
        </div>

        {isAnnouncementsLoading ? (
          <div className="py-6 flex items-center justify-center gap-2 text-xs text-[#64748B]">
            <RefreshCw className="w-4 h-4 animate-spin text-[#2563EB]" />
            <span>Loading announcements...</span>
          </div>
        ) : announcementsError ? (
          <div className="p-4 rounded-lg bg-[#FEF2F2] border border-[#FEE2E2] text-xs text-[#991B1B] flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{announcementsError}</span>
          </div>
        ) : announcements.length === 0 ? (
          <div className="py-6 text-center space-y-1">
            <CheckCircle2 className="w-6 h-6 text-[#16A34A] mx-auto mb-1.5" />
            <p className="text-xs font-medium text-[#111827]">No active announcements</p>
            <p className="text-[11px] text-[#64748B]">
              New broadcasts from the event team will appear here in real time.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {announcements.map((item) => (
              <div
                key={item.id}
                className={`p-4 rounded-xl border transition-all flex flex-col justify-between ${
                  !item.is_read
                    ? 'bg-[#F0F7FF] border-[#BFDBFE] shadow-2xs'
                    : 'bg-[#F8FAFC] border-[#E2E8F0]'
                }`}
              >
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-white border border-[#E2E8F0] text-[#2563EB]">
                      Announcement
                    </span>
                    {!item.is_read && (
                      <span className="flex items-center gap-1 text-[10px] font-semibold text-[#2563EB]">
                        <span className="w-1.5 h-1.5 rounded-full bg-[#2563EB]" />
                        Unread
                      </span>
                    )}
                  </div>
                  <h4 className="text-xs font-bold text-[#111827] line-clamp-1">{item.title}</h4>
                  <p className="text-[11px] text-[#475569] leading-relaxed line-clamp-2">
                    {item.description}
                  </p>
                </div>

                <div className="mt-3 pt-2 border-t border-[#E2E8F0]/80 flex items-center justify-between text-[10px] text-[#94A3B8]">
                  <span>{new Date(item.created_at).toLocaleDateString()}</span>
                  {item.action_url ? (
                    <Link
                      href={item.action_url}
                      className="font-semibold text-[#2563EB] hover:underline inline-flex items-center gap-0.5"
                    >
                      <span>Open</span>
                      <ChevronRight className="w-3 h-3" />
                    </Link>
                  ) : (
                    <Link
                      href="/participant/announcements"
                      className="font-semibold text-[#2563EB] hover:underline inline-flex items-center gap-0.5"
                    >
                      <span>Details</span>
                      <ChevronRight className="w-3 h-3" />
                    </Link>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Deadlines & Updates Row */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Deadlines */}
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-6 shadow-xs space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-[#E2E8F0]">
            <h3 className="text-sm font-bold text-[#111827]">Upcoming Deadlines</h3>
            <Clock className="w-4 h-4 text-[#2563EB]" />
          </div>

          {data.upcoming_deadlines.length === 0 ? (
            <p className="text-xs text-[#64748B] py-3 text-center">No upcoming deadlines.</p>
          ) : (
            <div className="space-y-3">
              {data.upcoming_deadlines.map((item, idx) => (
                <div key={idx} className="flex items-start justify-between p-3 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0]">
                  <div>
                    <span className="text-xs font-semibold text-[#111827] block">{item.title}</span>
                    <span className="text-[11px] text-[#64748B] mt-0.5 block">{item.hackathon}</span>
                  </div>
                  <span className="text-[11px] font-semibold text-[#D97706] bg-[#FEF3C7] px-2 py-0.5 rounded border border-[#FDE68A] shrink-0">
                    {new Date(item.due_date).toLocaleDateString()}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Recent Updates */}
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-6 shadow-xs space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-[#E2E8F0]">
            <h3 className="text-sm font-bold text-[#111827]">Recent Updates</h3>
            <Link
              href="/participant/notifications"
              className="text-xs font-medium text-[#2563EB] hover:underline"
            >
              All Notifications
            </Link>
          </div>

          {data.recent_updates.length === 0 ? (
            <p className="text-xs text-[#64748B] py-3 text-center">No recent updates.</p>
          ) : (
            <div className="space-y-3">
              {data.recent_updates.map((item, idx) => (
                <div key={idx} className="p-3 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0] space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-[#111827]">{item.title}</span>
                    <span className="text-[10px] text-[#64748B]">
                      {new Date(item.timestamp).toLocaleDateString()}
                    </span>
                  </div>
                  <p className="text-xs text-[#64748B] leading-snug">{item.description}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
