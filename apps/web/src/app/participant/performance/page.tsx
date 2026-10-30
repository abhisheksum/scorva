'use client';

import React, { useState, useEffect } from 'react';
import {
  BarChart3,
  Award,
  Trophy,
  CheckCircle2,
  AlertCircle,
  Clock,
  Sparkles,
  MessageSquare,
  ShieldCheck,
  RefreshCw,
  Cpu,
} from 'lucide-react';
import { api, ApiClientError } from '@/lib/api-client';
import { PerformanceResponse, ParticipantTeamItem } from '@/types/api';

export default function ParticipantPerformancePage() {
  const [performance, setPerformance] = useState<PerformanceResponse | null>(null);
  const [teams, setTeams] = useState<ParticipantTeamItem[]>([]);
  const [selectedHackathonId, setSelectedHackathonId] = useState<string>('');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Load user's hackathons first
  useEffect(() => {
    const fetchTeams = async () => {
      try {
        const teamList = await api.getParticipantTeams();
        setTeams(teamList);
        if (teamList.length > 0) {
          setSelectedHackathonId(teamList[0].hackathon_id);
        }
      } catch {
        // Handled in performance fetch
      }
    };
    fetchTeams();
  }, []);

  // Fetch performance whenever hackathon changes
  useEffect(() => {
    const fetchPerformance = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const data = await api.getParticipantPerformance(selectedHackathonId || undefined);
        setPerformance(data);
      } catch (err: unknown) {
        if (err instanceof ApiClientError) {
          setError(err.message);
        } else {
          setError('Failed to load performance metrics.');
        }
      } finally {
        setIsLoading(false);
      }
    };

    fetchPerformance();
  }, [selectedHackathonId]);

  return (
    <div className="space-y-6">
      {/* Header with hackathon switcher */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4 shadow-xs">
        <div>
          <div className="flex items-center gap-2 mb-1 text-xs font-semibold uppercase tracking-wider text-[#2563EB]">
            <BarChart3 className="w-4 h-4" />
            Evaluation Insights
          </div>
          <h1 className="text-xl sm:text-2xl font-bold text-[#111827]">
            My Project Performance
          </h1>
          <p className="text-xs text-[#64748B] mt-1">
            Detailed criteria breakdown, transparent scoring rubrics, and judge feedback.
          </p>
        </div>

        {teams.length > 1 && (
          <div className="shrink-0">
            <label htmlFor="hackathon-perf-select" className="block text-xs font-medium text-[#64748B] mb-1">
              Select Hackathon
            </label>
            <select
              id="hackathon-perf-select"
              value={selectedHackathonId}
              onChange={(e) => setSelectedHackathonId(e.target.value)}
              className="px-3 py-2 text-xs font-medium rounded-lg bg-white border border-[#E2E8F0] text-[#111827] focus:outline-none focus:ring-2 focus:ring-[#2563EB]"
            >
              {teams.map((t) => (
                <option key={t.hackathon_id} value={t.hackathon_id}>
                  {t.hackathon_title}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {isLoading ? (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-16 flex flex-col items-center justify-center text-center shadow-xs">
          <RefreshCw className="w-8 h-8 text-[#2563EB] animate-spin mb-3" />
          <p className="text-sm font-semibold text-[#111827]">Analyzing evaluation data...</p>
        </div>
      ) : error ? (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-8 text-center max-w-lg mx-auto shadow-xs">
          <AlertCircle className="w-10 h-10 text-[#DC2626] mx-auto mb-3" />
          <h3 className="text-sm font-semibold text-[#111827]">Unable to load performance details</h3>
          <p className="text-xs text-[#64748B] mt-1">{error}</p>
        </div>
      ) : !performance?.has_submission ? (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-12 text-center max-w-xl mx-auto shadow-xs space-y-3">
          <Clock className="w-10 h-10 text-[#94A3B8] mx-auto mb-2" />
          <h3 className="text-base font-bold text-[#111827]">No Submission Found</h3>
          <p className="text-xs text-[#64748B]">
            Your team has not yet linked a repository or submitted a project for evaluation in this hackathon.
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {/* Top Summary Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 sm:gap-6">
            <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 shadow-xs">
              <span className="text-xs font-semibold uppercase tracking-wider text-[#64748B]">
                Overall Final Score
              </span>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-3xl font-extrabold text-[#111827]">
                  {performance.final_score !== null && performance.final_score !== undefined
                    ? performance.final_score.toFixed(1)
                    : '—'}
                </span>
                <span className="text-xs text-[#64748B]">/ {performance.max_score}</span>
              </div>
              <p className="text-xs text-[#64748B] mt-1">
                Weighted composite score across all evaluated criteria
              </p>
            </div>

            <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 shadow-xs">
              <span className="text-xs font-semibold uppercase tracking-wider text-[#64748B]">
                Current Hackathon Rank
              </span>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-3xl font-extrabold text-[#111827]">
                  {performance.current_rank ? `#${performance.current_rank}` : '—'}
                </span>
                <span className="text-xs text-[#64748B]">
                  {performance.current_rank ? 'Place' : 'Pending publication'}
                </span>
              </div>
              <p className="text-xs text-[#64748B] mt-1">
                Official standing in {performance.hackathon_title}
              </p>
            </div>

            <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 shadow-xs">
              <span className="text-xs font-semibold uppercase tracking-wider text-[#64748B]">
                Review Status
              </span>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-xl font-bold text-[#111827] capitalize">
                  {performance.evaluation_status}
                </span>
              </div>
              <p className="text-xs text-[#64748B] mt-1">
                {performance.completed_reviews_count}{' '}
                {performance.completed_reviews_count === 1 ? 'review' : 'reviews'} completed
              </p>
            </div>
          </div>

          {/* Criteria Breakdown Section */}
          <div className="bg-white border border-[#E2E8F0] rounded-xl p-6 shadow-xs space-y-6">
            <div className="flex items-center justify-between pb-4 border-b border-[#E2E8F0]">
              <div>
                <h2 className="text-base font-bold text-[#111827]">Rubric Criteria Breakdown</h2>
                <p className="text-xs text-[#64748B] mt-0.5">
                  Individual scores and weights awarded for each judged criterion
                </p>
              </div>
              <span className="text-xs font-medium text-[#64748B]">
                {performance.criteria_breakdown.length} Criteria
              </span>
            </div>

            {performance.criteria_breakdown.length === 0 ? (
              <div className="text-center py-8 text-xs text-[#64748B]">
                Criterion breakdown is being computed by the evaluation engine.
              </div>
            ) : (
              <div className="space-y-5">
                {performance.criteria_breakdown.map((c) => (
                  <div key={c.criterion_id} className="p-4 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0] space-y-3">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                      <div>
                        <span className="text-sm font-bold text-[#111827]">{c.criterion_name}</span>
                        <span className="text-xs text-[#64748B] ml-2 font-medium">
                          (Weight: {(c.weight * 100).toFixed(0)}%)
                        </span>
                      </div>
                      <div className="text-sm font-semibold text-[#111827] flex items-center gap-1.5">
                        <span className="text-base font-bold text-[#2563EB]">
                          {c.awarded_score !== null && c.awarded_score !== undefined
                            ? c.awarded_score.toFixed(1)
                            : '—'}
                        </span>
                        <span className="text-xs text-[#64748B]">/ {c.max_score} pts</span>
                      </div>
                    </div>

                    {/* Progress Bar */}
                    <div className="w-full bg-[#E2E8F0] rounded-full h-2 overflow-hidden">
                      <div
                        className="bg-[#2563EB] h-2 rounded-full transition-all duration-500"
                        style={{ width: `${Math.min(100, Math.max(0, c.progress_percentage))}%` }}
                      />
                    </div>

                    {/* Rationale feedback */}
                    {c.rationale && (
                      <p className="text-xs text-[#475569] bg-white p-3 rounded border border-[#E2E8F0] italic">
                        &quot;{c.rationale}&quot;
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* AI Transparency Summary */}
          {performance.ai_summary && (
            <div className="bg-white border border-[#E2E8F0] rounded-xl p-6 shadow-xs space-y-3">
              <div className="flex items-center gap-2 pb-3 border-b border-[#E2E8F0]">
                <Cpu className="w-4 h-4 text-[#2563EB]" />
                <h3 className="text-sm font-bold text-[#111827]">
                  AI Assessment & Verification Highlights
                </h3>
              </div>
              <p className="text-xs text-[#475569] leading-relaxed whitespace-pre-line bg-[#F8FAFC] p-4 rounded-lg border border-[#E2E8F0]">
                {performance.ai_summary}
              </p>
            </div>
          )}

          {/* Authorized Judge Feedback */}
          <div className="bg-white border border-[#E2E8F0] rounded-xl p-6 shadow-xs space-y-4">
            <div className="flex items-center gap-2 pb-3 border-b border-[#E2E8F0]">
              <MessageSquare className="w-4 h-4 text-[#2563EB]" />
              <h3 className="text-sm font-bold text-[#111827]">
                Official Judge Feedback
              </h3>
            </div>

            {performance.authorized_feedback.length === 0 ? (
              <p className="text-xs text-[#64748B] py-4 text-center">
                Judge feedback comments will appear here once written reviews are published by the organizers.
              </p>
            ) : (
              <div className="space-y-3">
                {performance.authorized_feedback.map((comment, idx) => (
                  <div
                    key={idx}
                    className="p-4 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0] text-xs text-[#111827] leading-relaxed"
                  >
                    <div className="flex items-center gap-1.5 text-[11px] font-semibold text-[#2563EB] mb-1.5">
                      <ShieldCheck className="w-3.5 h-3.5" />
                      Reviewer Feedback #{idx + 1}
                    </div>
                    {comment}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
