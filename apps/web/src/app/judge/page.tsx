'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import {
  Trophy,
  Calendar,
  Clock,
  CheckCircle2,
  AlertCircle,
  FileText,
  ChevronRight,
  RefreshCw,
  FolderGit2,
  Clock4,
  ExternalLink,
  ShieldCheck,
  Award,
} from 'lucide-react';
import { api, ApiClientError } from '@/lib/api-client';
import { useAuth } from '@/lib/auth-context';
import { JudgeAssignmentItem, JudgeQueueItem } from '@/types/api';

export default function JudgeOverviewPage() {
  const { user } = useAuth();
  const [assignments, setAssignments] = useState<JudgeAssignmentItem[]>([]);
  const [allSubmissions, setAllSubmissions] = useState<JudgeQueueItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchOverviewData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [assignmentsData, subsData] = await Promise.all([
        api.getJudgeAssignments(),
        api.getJudgeSubmissions().catch(() => [] as JudgeQueueItem[]),
      ]);
      setAssignments(assignmentsData);
      setAllSubmissions(subsData);
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
    fetchOverviewData();
  }, []);

  // Compute real metrics from backend assignments and submissions
  const totalAssignedHackathons = assignments.length;
  const totalSubmissions = assignments.reduce(
    (acc, a) => acc + (a.total_submissions || 0),
    0
  );
  const totalSubmittedReviews = assignments.reduce(
    (acc, a) => acc + (a.my_submitted_count || 0),
    0
  );
  const totalDraftReviews = assignments.reduce(
    (acc, a) => acc + (a.my_draft_count || 0),
    0
  );
  const totalPendingReviews = Math.max(
    0,
    totalSubmissions - totalSubmittedReviews - totalDraftReviews
  );

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2 border-b border-[#E2E8F0]">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-[#111827]">
            Welcome back, {user?.full_name?.split(' ')[0] || 'Judge'}
          </h1>
          <p className="text-sm text-[#64748B] mt-1">
            Here is an overview of your assigned hackathons and project review workload.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={fetchOverviewData}
            disabled={isLoading}
            className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-semibold text-[#111827] bg-white border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] focus:outline-none focus:ring-2 focus:ring-[#2563EB] disabled:opacity-50 transition-colors shadow-xs"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin text-[#2563EB]' : 'text-[#64748B]'}`} />
            <span>Refresh</span>
          </button>

          <Link
            href="/judge/projects"
            className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-white bg-[#2563EB] rounded-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-[#2563EB] transition-colors shadow-xs"
          >
            <FolderGit2 className="w-3.5 h-3.5" />
            <span>View All Projects</span>
          </Link>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="p-4 rounded-xl bg-red-50 border border-red-200 flex items-start gap-3 text-sm text-[#DC2626]">
          <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="font-semibold">Unable to load assignments</p>
            <p className="text-xs text-red-600 mt-0.5">{error}</p>
          </div>
          <button
            type="button"
            onClick={fetchOverviewData}
            className="text-xs font-semibold underline hover:no-underline ml-auto"
          >
            Retry
          </button>
        </div>
      )}

      {/* Summary KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        {/* Card 1: Assigned Hackathons */}
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-[#64748B] uppercase tracking-wider">
              Assigned Hackathons
            </span>
            <div className="w-9 h-9 rounded-lg bg-[#EFF6FF] border border-[#BFDBFE] flex items-center justify-center text-[#2563EB]">
              <Trophy className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3">
            <span className="text-2xl font-bold tracking-tight text-[#111827]">
              {isLoading ? '—' : totalAssignedHackathons}
            </span>
            <p className="text-xs text-[#64748B] mt-1">
              Active events under evaluation
            </p>
          </div>
        </div>

        {/* Card 2: Projects Awaiting Review */}
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-[#64748B] uppercase tracking-wider">
              Awaiting Review
            </span>
            <div className="w-9 h-9 rounded-lg bg-amber-50 border border-amber-200 flex items-center justify-center text-[#D97706]">
              <Clock4 className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3">
            <span className="text-2xl font-bold tracking-tight text-[#111827]">
              {isLoading ? '—' : totalPendingReviews}
            </span>
            <p className="text-xs text-[#64748B] mt-1">
              Submissions pending initial review
            </p>
          </div>
        </div>

        {/* Card 3: Reviews In Progress */}
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-[#64748B] uppercase tracking-wider">
              Reviews In Progress
            </span>
            <div className="w-9 h-9 rounded-lg bg-blue-50 border border-blue-200 flex items-center justify-center text-[#2563EB]">
              <FileText className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3">
            <span className="text-2xl font-bold tracking-tight text-[#111827]">
              {isLoading ? '—' : totalDraftReviews}
            </span>
            <p className="text-xs text-[#64748B] mt-1">
              Saved drafts ready for submission
            </p>
          </div>
        </div>

        {/* Card 4: Reviews Completed */}
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-[#64748B] uppercase tracking-wider">
              Reviews Completed
            </span>
            <div className="w-9 h-9 rounded-lg bg-emerald-50 border border-emerald-200 flex items-center justify-center text-[#16A34A]">
              <CheckCircle2 className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-3">
            <span className="text-2xl font-bold tracking-tight text-[#111827]">
              {isLoading ? '—' : totalSubmittedReviews}
            </span>
            <p className="text-xs text-[#64748B] mt-1">
              Final evaluations submitted
            </p>
          </div>
        </div>
      </div>

      {/* Advisory Guidance Notice */}
      <div className="p-4 rounded-xl bg-[#EFF6FF] border border-[#BFDBFE] flex items-start gap-3">
        <ShieldCheck className="w-5 h-5 text-[#2563EB] shrink-0 mt-0.5" />
        <div className="text-xs text-[#1E3A8A]">
          <span className="font-semibold block text-sm mb-0.5 text-[#1E3A8A]">
            Independent Evaluation Standard
          </span>
          AI assessment is provided as guidance. Your score and feedback are your independent decision. You may review automated suggestions, source code references, and grounded findings to inform your final scoring.
        </div>
      </div>

      {/* Assigned Hackathons List */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-[#111827]">
              Assigned Hackathons
            </h2>
            <p className="text-xs text-[#64748B] mt-0.5">
              Select an event to view submission queues and start reviewing
            </p>
          </div>
        </div>

        {isLoading ? (
          <div className="bg-white border border-[#E2E8F0] rounded-xl p-12 flex flex-col items-center justify-center gap-3">
            <RefreshCw className="w-6 h-6 text-[#2563EB] animate-spin" />
            <p className="text-xs text-[#64748B]">Loading your assigned events...</p>
          </div>
        ) : assignments.length === 0 ? (
          <div className="bg-white border border-[#E2E8F0] rounded-xl p-12 text-center">
            <Trophy className="w-10 h-10 text-gray-300 mx-auto mb-3" />
            <h3 className="text-sm font-semibold text-[#111827]">
              No hackathon assignments found
            </h3>
            <p className="text-xs text-[#64748B] mt-1 max-w-sm mx-auto">
              You have not been assigned to judge any hackathons yet. Once an organizer designates you as a judge, events will appear here.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {assignments.map((hackathon) => {
              const reviewedPercent =
                hackathon.total_submissions > 0
                  ? Math.round(
                      (hackathon.my_submitted_count / hackathon.total_submissions) * 100
                    )
                  : 0;

              return (
                <div
                  key={hackathon.hackathon_id}
                  className="bg-white border border-[#E2E8F0] rounded-xl p-6 hover:border-[#BFDBFE] hover:shadow-sm transition-all flex flex-col justify-between"
                >
                  <div>
                    {/* Header info */}
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <span className="inline-block px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-[#2563EB] bg-[#EFF6FF] border border-[#BFDBFE] rounded mb-2">
                          {hackathon.organization_name}
                        </span>
                        <h3 className="text-base font-bold text-[#111827] leading-snug">
                          {hackathon.hackathon_title}
                        </h3>
                      </div>
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium capitalize ${
                          hackathon.hackathon_status === 'published' ||
                          hackathon.hackathon_status === 'active'
                            ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                            : 'bg-gray-100 text-gray-700 border border-gray-200'
                        }`}
                      >
                        {hackathon.hackathon_status}
                      </span>
                    </div>

                    {/* Progress metrics */}
                    <div className="mt-5 space-y-2">
                      <div className="flex items-center justify-between text-xs text-[#64748B]">
                        <span>Review Progress</span>
                        <span className="font-semibold text-[#111827]">
                          {hackathon.my_submitted_count} of {hackathon.total_submissions} completed ({reviewedPercent}%)
                        </span>
                      </div>
                      <div className="w-full bg-[#F1F5F9] rounded-full h-2 overflow-hidden">
                        <div
                          className="bg-[#2563EB] h-2 rounded-full transition-all duration-300"
                          style={{ width: `${reviewedPercent}%` }}
                        />
                      </div>
                    </div>

                    {/* Meta stats */}
                    <div className="mt-4 grid grid-cols-3 gap-2 py-3 border-y border-[#E2E8F0] text-center">
                      <div>
                        <span className="text-[11px] text-[#64748B] block">Total</span>
                        <span className="text-sm font-bold text-[#111827]">
                          {hackathon.total_submissions}
                        </span>
                      </div>
                      <div>
                        <span className="text-[11px] text-[#D97706] block">Awaiting</span>
                        <span className="text-sm font-bold text-[#D97706]">
                          {hackathon.my_pending_count}
                        </span>
                      </div>
                      <div>
                        <span className="text-[11px] text-[#2563EB] block">Drafts</span>
                        <span className="text-sm font-bold text-[#2563EB]">
                          {hackathon.my_draft_count}
                        </span>
                      </div>
                    </div>

                    {/* Deadline info */}
                    <div className="mt-3 flex items-center gap-4 text-xs text-[#64748B]">
                      {hackathon.submission_deadline ? (
                        <div className="flex items-center gap-1.5">
                          <Calendar className="w-3.5 h-3.5 text-[#64748B]" />
                          <span>
                            Deadline: {new Date(hackathon.submission_deadline).toLocaleDateString()}
                          </span>
                        </div>
                      ) : (
                        <div className="flex items-center gap-1.5">
                          <Clock className="w-3.5 h-3.5 text-[#64748B]" />
                          <span>No deadline set</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Action Link */}
                  <div className="mt-5 pt-3">
                    <Link
                      href={`/judge/projects?hackathon=${hackathon.hackathon_id}`}
                      className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 text-xs font-semibold text-[#2563EB] bg-[#EFF6FF] hover:bg-blue-100 rounded-lg transition-colors border border-[#BFDBFE]"
                    >
                      <span>Open Assigned Projects</span>
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
