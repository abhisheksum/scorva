'use client';

import React, { useState, useEffect, useMemo } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import {
  FolderGit2,
  Search,
  Filter,
  CheckCircle2,
  Clock,
  AlertCircle,
  ExternalLink,
  ChevronRight,
  RefreshCw,
  GitBranch,
  Sparkles,
  Bot,
  FileEdit,
  Eye,
} from 'lucide-react';
import { api, ApiClientError } from '@/lib/api-client';
import { JudgeQueueItem, JudgeAssignmentItem } from '@/types/api';

type TabStatus = 'all' | 'awaiting' | 'draft' | 'submitted';

export default function JudgeProjectsPage() {
  const searchParams = useSearchParams();
  const hackathonFilterParam = searchParams.get('hackathon');

  const [submissions, setSubmissions] = useState<JudgeQueueItem[]>([]);
  const [assignments, setAssignments] = useState<JudgeAssignmentItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [selectedHackathon, setSelectedHackathon] = useState<string>(
    hackathonFilterParam || 'all'
  );
  const [currentTab, setCurrentTab] = useState<TabStatus>('all');

  const loadData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [subsData, assignData] = await Promise.all([
        api.getJudgeSubmissions(),
        api.getJudgeAssignments().catch(() => [] as JudgeAssignmentItem[]),
      ]);
      setSubmissions(subsData);
      setAssignments(assignData);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to load assigned project submissions.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    if (hackathonFilterParam) {
      setSelectedHackathon(hackathonFilterParam);
    }
  }, [hackathonFilterParam]);

  // Filtered submissions
  const filteredSubmissions = useMemo(() => {
    return submissions.filter((sub) => {
      // Hackathon filter
      if (selectedHackathon !== 'all') {
        if (sub.hackathon_id !== selectedHackathon) {
          return false;
        }
      }

      // Tab status filter
      if (currentTab === 'awaiting') {
        if (sub.review_status !== 'not_started') return false;
      } else if (currentTab === 'draft') {
        if (sub.review_status !== 'draft') return false;
      } else if (currentTab === 'submitted') {
        if (sub.review_status !== 'submitted') return false;
      }

      // Search filter
      if (searchQuery.trim()) {
        const query = searchQuery.toLowerCase();
        const titleMatch = sub.title?.toLowerCase().includes(query);
        const teamMatch = sub.team_name?.toLowerCase().includes(query);
        const hackathonMatch = sub.hackathon_title?.toLowerCase().includes(query);
        if (!titleMatch && !teamMatch && !hackathonMatch) return false;
      }

      return true;
    });
  }, [submissions, selectedHackathon, currentTab, searchQuery]);

  // Tab counts
  const tabCounts = useMemo(() => {
    const list = selectedHackathon === 'all'
      ? submissions
      : submissions.filter((s) => s.hackathon_id === selectedHackathon);

    return {
      all: list.length,
      awaiting: list.filter((s) => s.review_status === 'not_started').length,
      draft: list.filter((s) => s.review_status === 'draft').length,
      submitted: list.filter((s) => s.review_status === 'submitted').length,
    };
  }, [submissions, selectedHackathon]);

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'submitted':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
            <CheckCircle2 className="w-3.5 h-3.5" />
            <span>Completed</span>
          </span>
        );
      case 'draft':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-semibold bg-blue-50 text-[#2563EB] border border-blue-200">
            <FileEdit className="w-3.5 h-3.5" />
            <span>In Progress (Draft)</span>
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-200">
            <Clock className="w-3.5 h-3.5" />
            <span>Awaiting Review</span>
          </span>
        );
    }
  };

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2 border-b border-[#E2E8F0]">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-[#111827]">
            My Projects
          </h1>
          <p className="text-sm text-[#64748B] mt-1">
            Browse all submissions assigned to you for evaluation.
          </p>
        </div>

        <button
          type="button"
          onClick={loadData}
          disabled={isLoading}
          className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-semibold text-[#111827] bg-white border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] focus:outline-none focus:ring-2 focus:ring-[#2563EB] disabled:opacity-50 transition-colors shadow-xs self-start sm:self-auto"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin text-[#2563EB]' : 'text-[#64748B]'}`} />
          <span>Refresh Queue</span>
        </button>
      </div>

      {/* Error state */}
      {error && (
        <div className="p-4 rounded-xl bg-red-50 border border-red-200 flex items-start gap-3 text-sm text-[#DC2626]">
          <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="font-semibold">Unable to load assigned submissions</p>
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

      {/* Filters and Search Bar */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl p-4 shadow-xs space-y-4">
        <div className="flex flex-col sm:flex-row gap-3">
          {/* Search box */}
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[#64748B]" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by project title, team, or hackathon..."
              className="w-full pl-9 pr-4 py-2 text-xs text-[#111827] bg-[#F8FAFC] border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:bg-white placeholder-[#94A3B8] transition-colors"
            />
          </div>

          {/* Hackathon filter dropdown */}
          <div className="sm:w-64">
            <select
              value={selectedHackathon}
              onChange={(e) => setSelectedHackathon(e.target.value)}
              className="w-full px-3 py-2 text-xs text-[#111827] bg-[#F8FAFC] border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:bg-white transition-colors"
            >
              <option value="all">All Hackathons</option>
              {assignments.map((a) => (
                <option key={a.hackathon_id} value={a.hackathon_id}>
                  {a.hackathon_title}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Status Tabs */}
        <div className="flex items-center gap-2 border-t border-[#E2E8F0] pt-3 overflow-x-auto">
          {(
            [
              { id: 'all', label: 'All Projects', count: tabCounts.all },
              { id: 'awaiting', label: 'Awaiting Review', count: tabCounts.awaiting },
              { id: 'draft', label: 'In Progress (Draft)', count: tabCounts.draft },
              { id: 'submitted', label: 'Completed', count: tabCounts.submitted },
            ] as const
          ).map((tab) => {
            const isActive = currentTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setCurrentTab(tab.id)}
                className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${
                  isActive
                    ? 'bg-[#2563EB] text-white shadow-xs'
                    : 'text-[#64748B] hover:text-[#111827] hover:bg-[#F8FAFC]'
                }`}
              >
                <span>{tab.label}</span>
                <span
                  className={`px-1.5 py-0.2 rounded-full text-[10px] font-bold ${
                    isActive ? 'bg-white/20 text-white' : 'bg-[#F1F5F9] text-[#64748B]'
                  }`}
                >
                  {tab.count}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Submissions List / Table */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl shadow-xs overflow-hidden">
        {isLoading ? (
          <div className="p-12 text-center flex flex-col items-center justify-center gap-3">
            <RefreshCw className="w-6 h-6 text-[#2563EB] animate-spin" />
            <p className="text-xs text-[#64748B]">Loading submissions...</p>
          </div>
        ) : filteredSubmissions.length === 0 ? (
          <div className="p-12 text-center">
            <FolderGit2 className="w-10 h-10 text-gray-300 mx-auto mb-3" />
            <h3 className="text-sm font-semibold text-[#111827]">
              No submissions match your filter
            </h3>
            <p className="text-xs text-[#64748B] mt-1 max-w-sm mx-auto">
              Try adjusting your search criteria or switching the status filter tab above.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-[#F8FAFC] border-b border-[#E2E8F0] text-[#64748B] font-semibold uppercase tracking-wider text-[11px]">
                  <th className="py-3 px-5">Project & Team</th>
                  <th className="py-3 px-4">Hackathon</th>
                  <th className="py-3 px-4">AI Assessment</th>
                  <th className="py-3 px-4">Review Status</th>
                  <th className="py-3 px-4">Score</th>
                  <th className="py-3 px-5 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E2E8F0]">
                {filteredSubmissions.map((sub) => {
                  const targetHackathonId = sub.hackathon_id || assignments[0]?.hackathon_id;
                  const reviewUrl = `/judge/hackathons/${targetHackathonId}/submissions/${sub.submission_id}`;

                  return (
                    <tr
                      key={sub.submission_id}
                      className="hover:bg-[#F8FAFC] transition-colors"
                    >
                      {/* Project & Team */}
                      <td className="py-4 px-5">
                        <div className="flex flex-col">
                          <Link
                            href={reviewUrl}
                            className="font-bold text-[#111827] text-sm hover:text-[#2563EB] transition-colors"
                          >
                            {sub.title}
                          </Link>
                          <div className="flex items-center gap-2 text-xs text-[#64748B] mt-0.5">
                            <span className="font-medium text-[#111827]">
                              {sub.team_name}
                            </span>
                            {sub.created_at && (
                              <>
                                <span>•</span>
                                <span>
                                  Submitted {new Date(sub.created_at).toLocaleDateString()}
                                </span>
                              </>
                            )}
                          </div>
                        </div>
                      </td>

                      {/* Hackathon */}
                      <td className="py-4 px-4 text-[#111827] font-medium">
                        {sub.hackathon_title || 'Assigned Hackathon'}
                      </td>

                      {/* AI Assessment */}
                      <td className="py-4 px-4">
                        {sub.ai_evaluation_status === 'completed' && sub.ai_normalized_score !== null && sub.ai_normalized_score !== undefined ? (
                          <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-[#EFF6FF] border border-[#BFDBFE] text-xs font-semibold text-[#2563EB]">
                            <Bot className="w-3.5 h-3.5" />
                            <span>Score: {Number(sub.ai_normalized_score).toFixed(1)} / 100</span>
                          </div>
                        ) : sub.ai_evaluation_status === 'running' || sub.ai_evaluation_status === 'queued' ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-blue-50 text-blue-700 border border-blue-200">
                            Evaluating...
                          </span>
                        ) : (
                          <span className="text-[11px] text-[#94A3B8]">
                            Not evaluated
                          </span>
                        )}
                      </td>

                      {/* Review Status */}
                      <td className="py-4 px-4">
                        {getStatusBadge(sub.review_status)}
                      </td>

                      {/* Score */}
                      <td className="py-4 px-4 font-bold text-sm text-[#111827]">
                        {sub.review_score !== null && sub.review_score !== undefined ? (
                          <span>{Number(sub.review_score).toFixed(1)}</span>
                        ) : (
                          <span className="text-[#94A3B8] font-normal">—</span>
                        )}
                      </td>

                      {/* Action */}
                      <td className="py-4 px-5 text-right">
                        <Link
                          href={reviewUrl}
                          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all shadow-xs ${
                            sub.review_status === 'submitted'
                              ? 'bg-white border border-[#E2E8F0] text-[#111827] hover:bg-[#F8FAFC]'
                              : sub.review_status === 'draft'
                              ? 'bg-[#EFF6FF] text-[#2563EB] border border-[#BFDBFE] hover:bg-blue-100'
                              : 'bg-[#2563EB] text-white hover:bg-blue-700'
                          }`}
                        >
                          {sub.review_status === 'submitted' ? (
                            <>
                              <Eye className="w-3.5 h-3.5" />
                              <span>View Review</span>
                            </>
                          ) : sub.review_status === 'draft' ? (
                            <>
                              <FileEdit className="w-3.5 h-3.5" />
                              <span>Continue Draft</span>
                            </>
                          ) : (
                            <>
                              <span>Start Review</span>
                              <ChevronRight className="w-3.5 h-3.5" />
                            </>
                          )}
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
