'use client';

import React, { useState, useEffect, useMemo } from 'react';
import Link from 'next/link';
import {
  CheckCircle2,
  Search,
  ExternalLink,
  Eye,
  RefreshCw,
  AlertCircle,
  Calendar,
  Award,
  FileCheck,
} from 'lucide-react';
import { api, ApiClientError } from '@/lib/api-client';
import { JudgeQueueItem, JudgeAssignmentItem } from '@/types/api';

export default function JudgeCompletedReviewsPage() {
  const [submissions, setSubmissions] = useState<JudgeQueueItem[]>([]);
  const [assignments, setAssignments] = useState<JudgeAssignmentItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  const loadData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [subsData, assignData] = await Promise.all([
        api.getJudgeSubmissions(),
        api.getJudgeAssignments().catch(() => [] as JudgeAssignmentItem[]),
      ]);
      setSubmissions(subsData.filter((s) => s.review_status === 'submitted'));
      setAssignments(assignData);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to load completed reviews.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const filteredReviews = useMemo(() => {
    if (!searchQuery.trim()) return submissions;
    const query = searchQuery.toLowerCase();
    return submissions.filter(
      (sub) =>
        sub.title?.toLowerCase().includes(query) ||
        sub.team_name?.toLowerCase().includes(query) ||
        sub.hackathon_title?.toLowerCase().includes(query)
    );
  }, [submissions, searchQuery]);

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2 border-b border-[#E2E8F0]">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-[#111827]">
            Completed Reviews
          </h1>
          <p className="text-sm text-[#64748B] mt-1">
            Browse and inspect your final, submitted project assessments.
          </p>
        </div>

        <button
          type="button"
          onClick={loadData}
          disabled={isLoading}
          className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-semibold text-[#111827] bg-white border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] focus:outline-none focus:ring-2 focus:ring-[#2563EB] disabled:opacity-50 transition-colors shadow-xs self-start sm:self-auto"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin text-[#2563EB]' : 'text-[#64748B]'}`} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Error state */}
      {error && (
        <div className="p-4 rounded-xl bg-red-50 border border-red-200 flex items-start gap-3 text-sm text-[#DC2626]">
          <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="font-semibold">Unable to load completed reviews</p>
            <p className="text-xs text-red-600 mt-0.5">{error}</p>
          </div>
          <button
            type="button"
            onClick={loadData}
            className="text-xs font-semibold underline hover:no-underline ml-auto"
          >
            Retry
          </button>
        </div>
      )}

      {/* Search Bar */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl p-4 shadow-xs">
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[#64748B]" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search completed reviews by project or team name..."
            className="w-full pl-9 pr-4 py-2 text-xs text-[#111827] bg-[#F8FAFC] border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:bg-white placeholder-[#94A3B8] transition-colors"
          />
        </div>
      </div>

      {/* Table */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl shadow-xs overflow-hidden">
        {isLoading ? (
          <div className="p-12 text-center flex flex-col items-center justify-center gap-3">
            <RefreshCw className="w-6 h-6 text-[#2563EB] animate-spin" />
            <p className="text-xs text-[#64748B]">Loading completed reviews...</p>
          </div>
        ) : filteredReviews.length === 0 ? (
          <div className="p-12 text-center">
            <FileCheck className="w-10 h-10 text-gray-300 mx-auto mb-3" />
            <h3 className="text-sm font-semibold text-[#111827]">
              No completed reviews yet
            </h3>
            <p className="text-xs text-[#64748B] mt-1 max-w-sm mx-auto">
              When you finalize and submit project scores and feedback, they will appear in this registry.
            </p>
            <div className="mt-4">
              <Link
                href="/judge/projects"
                className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-white bg-[#2563EB] rounded-lg hover:bg-blue-700 transition-colors shadow-xs"
              >
                Go to My Projects
              </Link>
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-[#F8FAFC] border-b border-[#E2E8F0] text-[#64748B] font-semibold uppercase tracking-wider text-[11px]">
                  <th className="py-3 px-5">Project & Team</th>
                  <th className="py-3 px-4">Hackathon</th>
                  <th className="py-3 px-4">Submitted Date</th>
                  <th className="py-3 px-4">Awarded Score</th>
                  <th className="py-3 px-5 text-right">Review Record</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E2E8F0]">
                {filteredReviews.map((sub) => {
                  const targetHackathonId = sub.hackathon_id || assignments[0]?.hackathon_id;
                  const reviewUrl = `/judge/hackathons/${targetHackathonId}/submissions/${sub.submission_id}`;

                  return (
                    <tr
                      key={sub.submission_id}
                      className="hover:bg-[#F8FAFC] transition-colors"
                    >
                      <td className="py-4 px-5">
                        <div className="flex flex-col">
                          <Link
                            href={reviewUrl}
                            className="font-bold text-[#111827] text-sm hover:text-[#2563EB] transition-colors"
                          >
                            {sub.title}
                          </Link>
                          <span className="text-xs text-[#64748B] mt-0.5">
                            {sub.team_name}
                          </span>
                        </div>
                      </td>

                      <td className="py-4 px-4 text-[#111827] font-medium">
                        {sub.hackathon_title || 'Assigned Hackathon'}
                      </td>

                      <td className="py-4 px-4 text-[#64748B]">
                        {sub.review_submitted_at ? (
                          <div className="flex items-center gap-1.5">
                            <Calendar className="w-3.5 h-3.5 text-[#64748B]" />
                            <span>
                              {new Date(sub.review_submitted_at).toLocaleDateString()}
                            </span>
                          </div>
                        ) : (
                          <span>—</span>
                        )}
                      </td>

                      <td className="py-4 px-4">
                        <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-emerald-50 border border-emerald-200 text-xs font-bold text-emerald-800">
                          <Award className="w-3.5 h-3.5 text-emerald-600" />
                          <span>
                            {sub.review_score !== null && sub.review_score !== undefined
                              ? `${Number(sub.review_score).toFixed(1)} / 100`
                              : 'Submitted'}
                          </span>
                        </div>
                      </td>

                      <td className="py-4 px-5 text-right">
                        <Link
                          href={reviewUrl}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-white border border-[#E2E8F0] text-[#111827] hover:bg-[#F8FAFC] hover:border-[#BFDBFE] transition-colors shadow-xs"
                        >
                          <Eye className="w-3.5 h-3.5 text-[#2563EB]" />
                          <span>View Review</span>
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
