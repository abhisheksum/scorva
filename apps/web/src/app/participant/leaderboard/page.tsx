'use client';

import React, { useState, useEffect } from 'react';
import {
  Trophy,
  Medal,
  RefreshCw,
  AlertCircle,
  Clock,
  Sparkles,
  ChevronRight,
  ShieldAlert,
} from 'lucide-react';
import { api, ApiClientError } from '@/lib/api-client';
import { LeaderboardResponse, ParticipantTeamItem } from '@/types/api';

export default function ParticipantLeaderboardPage() {
  const [leaderboard, setLeaderboard] = useState<LeaderboardResponse | null>(null);
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
        // Handled in leaderboard fetch
      }
    };
    fetchTeams();
  }, []);

  // Fetch leaderboard when hackathon changes
  useEffect(() => {
    const fetchLeaderboard = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const data = await api.getParticipantLeaderboard(selectedHackathonId || undefined);
        setLeaderboard(data);
      } catch (err: unknown) {
        if (err instanceof ApiClientError) {
          setError(err.message);
        } else {
          setError('Failed to load leaderboard. Please try again.');
        }
      } finally {
        setIsLoading(false);
      }
    };

    fetchLeaderboard();
  }, [selectedHackathonId]);

  return (
    <div className="space-y-6">
      {/* Header & Hackathon Selector */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4 shadow-xs">
        <div>
          <div className="flex items-center gap-2 mb-1 text-xs font-semibold uppercase tracking-wider text-[#2563EB]">
            <Trophy className="w-4 h-4" />
            Official Rankings
          </div>
          <h1 className="text-xl sm:text-2xl font-bold text-[#111827]">
            Hackathon Leaderboard
          </h1>
          <p className="text-xs text-[#64748B] mt-1">
            Real-time verified standings based on independent rubric evaluations.
          </p>
        </div>

        {teams.length > 1 && (
          <div className="shrink-0">
            <label htmlFor="hackathon-select" className="block text-xs font-medium text-[#64748B] mb-1">
              Select Hackathon
            </label>
            <select
              id="hackathon-select"
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
          <p className="text-sm font-semibold text-[#111827]">Fetching leaderboard rankings...</p>
        </div>
      ) : error ? (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-8 text-center max-w-lg mx-auto shadow-xs">
          <AlertCircle className="w-10 h-10 text-[#DC2626] mx-auto mb-3" />
          <h3 className="text-sm font-semibold text-[#111827]">Could not load leaderboard</h3>
          <p className="text-xs text-[#64748B] mt-1">{error}</p>
        </div>
      ) : !leaderboard?.is_published ? (
        /* Unpublished / In Progress State */
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-12 text-center max-w-xl mx-auto shadow-xs space-y-4">
          <div className="w-12 h-12 rounded-full bg-[#FEF3C7] border border-[#FDE68A] flex items-center justify-center mx-auto text-[#D97706]">
            <Clock className="w-6 h-6" />
          </div>
          <div>
            <h3 className="text-base font-bold text-[#111827]">
              Rankings Currently Under Evaluation
            </h3>
            <p className="text-xs text-[#64748B] mt-2 leading-relaxed">
              {leaderboard?.message ||
                'Judges are currently reviewing project submissions. Official rankings will be published by the event organizers once final scoring is completed.'}
            </p>
          </div>
          <div className="pt-2">
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-[#F8FAFC] border border-[#E2E8F0] text-[#64748B]">
              <Sparkles className="w-3.5 h-3.5 text-[#2563EB]" />
              Check back soon for finalized results
            </span>
          </div>
        </div>
      ) : leaderboard.entries.length === 0 ? (
        /* Published but 0 entries */
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-12 text-center max-w-xl mx-auto shadow-xs">
          <Medal className="w-10 h-10 text-[#94A3B8] mx-auto mb-3" />
          <h3 className="text-sm font-semibold text-[#111827]">No published submissions found</h3>
          <p className="text-xs text-[#64748B] mt-1">
            There are currently no finalized submission scores for {leaderboard.hackathon_title}.
          </p>
        </div>
      ) : (
        /* Published Leaderboard Table */
        <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden shadow-xs">
          <div className="px-6 py-4 border-b border-[#E2E8F0] flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-[#64748B]">
              Standings for {leaderboard.hackathon_title} ({leaderboard.entries.length} teams)
            </span>
            <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-[#F0FDF4] text-[#16A34A] border border-[#BBF7D0]">
              Official Results Published
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-[#F8FAFC] border-b border-[#E2E8F0] text-[11px] font-semibold uppercase tracking-wider text-[#64748B]">
                  <th className="py-3 px-6 w-20">Rank</th>
                  <th className="py-3 px-6">Team</th>
                  <th className="py-3 px-6">Project Title</th>
                  <th className="py-3 px-6 text-right">Score</th>
                  <th className="py-3 px-6 text-center w-32">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E2E8F0] text-sm">
                {leaderboard.entries.map((entry) => {
                  const isTop3 = entry.rank <= 3;
                  return (
                    <tr
                      key={entry.rank + entry.team_name}
                      className={`transition-colors ${
                        entry.is_my_team
                          ? 'bg-[#EFF6FF] border-l-4 border-l-[#2563EB] font-medium'
                          : 'hover:bg-[#F8FAFC]'
                      }`}
                    >
                      {/* Rank Column */}
                      <td className="py-4 px-6 whitespace-nowrap">
                        <div className="flex items-center gap-2">
                          {entry.rank === 1 ? (
                            <span className="w-7 h-7 rounded-full bg-[#FEF3C7] border border-[#FDE68A] flex items-center justify-center text-xs font-bold text-[#D97706] shadow-2xs">
                              1
                            </span>
                          ) : entry.rank === 2 ? (
                            <span className="w-7 h-7 rounded-full bg-[#F1F5F9] border border-[#CBD5E1] flex items-center justify-center text-xs font-bold text-[#475569] shadow-2xs">
                              2
                            </span>
                          ) : entry.rank === 3 ? (
                            <span className="w-7 h-7 rounded-full bg-[#FFEDD5] border border-[#FED7AA] flex items-center justify-center text-xs font-bold text-[#C2410C] shadow-2xs">
                              3
                            </span>
                          ) : (
                            <span className="w-7 h-7 rounded-full bg-[#F8FAFC] border border-[#E2E8F0] flex items-center justify-center text-xs font-medium text-[#64748B]">
                              {entry.rank}
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Team Name */}
                      <td className="py-4 px-6 whitespace-nowrap">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-[#111827]">{entry.team_name}</span>
                          {entry.is_my_team && (
                            <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-[#2563EB] text-white">
                              Your Team
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Project Title */}
                      <td className="py-4 px-6 text-[#475569]">
                        {entry.project_title || '—'}
                      </td>

                      {/* Score */}
                      <td className="py-4 px-6 text-right whitespace-nowrap">
                        <span className="font-bold text-[#111827] text-base">
                          {entry.score.toFixed(1)}
                        </span>
                        <span className="text-xs text-[#64748B]"> / 100</span>
                      </td>

                      {/* Status */}
                      <td className="py-4 px-6 text-center whitespace-nowrap">
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold capitalize bg-[#F0FDF4] text-[#16A34A] border border-[#BBF7D0]">
                          {entry.status}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
