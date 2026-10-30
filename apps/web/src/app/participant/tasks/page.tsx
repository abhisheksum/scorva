'use client';

import React, { useState, useEffect } from 'react';
import {
  CheckSquare,
  Award,
  Calendar,
  Clock,
  ExternalLink,
  Filter,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  Sparkles,
  ChevronRight,
  X,
} from 'lucide-react';
import { api, ApiClientError } from '@/lib/api-client';
import { ParticipantTaskItem } from '@/types/api';

export default function ParticipantTasksPage() {
  const [tasks, setTasks] = useState<ParticipantTaskItem[]>([]);
  const [activeTab, setActiveTab] = useState<'all' | 'task' | 'sponsorship'>('all');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updatingTaskId, setUpdatingTaskId] = useState<string | null>(null);
  const [selectedTask, setSelectedTask] = useState<ParticipantTaskItem | null>(null);

  const fetchTasks = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await api.getParticipantTasks();
      setTasks(data);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to load tasks and opportunities.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchTasks();
  }, []);

  const handleUpdateStatus = async (
    taskId: string,
    newStatus: 'new' | 'in_progress' | 'completed'
  ) => {
    setUpdatingTaskId(taskId);
    try {
      await api.updateParticipantTaskStatus(taskId, newStatus);
      // Update local state
      setTasks((prev) =>
        prev.map((t) => (t.id === taskId ? { ...t, status: newStatus } : t))
      );
      if (selectedTask?.id === taskId) {
        setSelectedTask((prev) => (prev ? { ...prev, status: newStatus } : null));
      }
    } catch (err) {
      console.error('Failed to update status', err);
    } finally {
      setUpdatingTaskId(null);
    }
  };

  const filteredTasks = tasks.filter((t) => {
    if (activeTab === 'all') return true;
    return t.category === activeTab;
  });

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'completed':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-[#F0FDF4] text-[#16A34A] border border-[#BBF7D0]">
            <CheckCircle2 className="w-3 h-3" />
            Completed
          </span>
        );
      case 'in_progress':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-[#EFF6FF] text-[#2563EB] border border-[#BFDBFE]">
            <Clock className="w-3 h-3" />
            In Progress
          </span>
        );
      case 'overdue':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-[#FEF2F2] text-[#DC2626] border border-[#FECACA]">
            <AlertCircle className="w-3 h-3" />
            Overdue
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-[#F8FAFC] text-[#64748B] border border-[#E2E8F0]">
            New
          </span>
        );
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4 shadow-xs">
        <div>
          <div className="flex items-center gap-2 mb-1 text-xs font-semibold uppercase tracking-wider text-[#2563EB]">
            <CheckSquare className="w-4 h-4" />
            Action Center
          </div>
          <h1 className="text-xl sm:text-2xl font-bold text-[#111827]">
            Tasks & Sponsor Opportunities
          </h1>
          <p className="text-xs text-[#64748B] mt-1">
            Complete organizer milestones, explore sponsor bonus tracks, and unlock platform rewards.
          </p>
        </div>

        {/* Filter Tabs */}
        <div className="flex items-center bg-[#F8FAFC] p-1 rounded-lg border border-[#E2E8F0] shrink-0">
          <button
            onClick={() => setActiveTab('all')}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
              activeTab === 'all'
                ? 'bg-white text-[#111827] shadow-2xs font-semibold'
                : 'text-[#64748B] hover:text-[#111827]'
            }`}
          >
            All Items ({tasks.length})
          </button>
          <button
            onClick={() => setActiveTab('task')}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
              activeTab === 'task'
                ? 'bg-white text-[#111827] shadow-2xs font-semibold'
                : 'text-[#64748B] hover:text-[#111827]'
            }`}
          >
            Milestones
          </button>
          <button
            onClick={() => setActiveTab('sponsorship')}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
              activeTab === 'sponsorship'
                ? 'bg-white text-[#111827] shadow-2xs font-semibold'
                : 'text-[#64748B] hover:text-[#111827]'
            }`}
          >
            Sponsorships
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-16 flex flex-col items-center justify-center text-center shadow-xs">
          <RefreshCw className="w-8 h-8 text-[#2563EB] animate-spin mb-3" />
          <p className="text-sm font-semibold text-[#111827]">Loading tasks & opportunities...</p>
        </div>
      ) : error ? (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-8 text-center max-w-lg mx-auto shadow-xs">
          <AlertCircle className="w-10 h-10 text-[#DC2626] mx-auto mb-3" />
          <h3 className="text-sm font-semibold text-[#111827]">Failed to load tasks</h3>
          <p className="text-xs text-[#64748B] mt-1">{error}</p>
        </div>
      ) : filteredTasks.length === 0 ? (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-12 text-center max-w-xl mx-auto shadow-xs space-y-3">
          <CheckCircle2 className="w-10 h-10 text-[#16A34A] mx-auto mb-2" />
          <h3 className="text-base font-bold text-[#111827]">No active tasks in this view</h3>
          <p className="text-xs text-[#64748B]">
            You have caught up with all current items. New opportunities will appear here as the hackathon progresses.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {filteredTasks.map((task) => (
            <div
              key={task.id}
              className="bg-white border border-[#E2E8F0] rounded-xl p-5 shadow-xs flex flex-col justify-between hover:border-[#BFDBFE] transition-colors"
            >
              <div>
                <div className="flex items-center justify-between gap-2 mb-2">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-[#2563EB] bg-[#EFF6FF] px-2 py-0.5 rounded border border-[#BFDBFE]">
                      {task.category}
                    </span>
                    {task.sponsor_name && (
                      <span className="text-[11px] font-medium text-[#475569] bg-[#F8FAFC] px-2 py-0.5 rounded border border-[#E2E8F0]">
                        {task.sponsor_name}
                      </span>
                    )}
                  </div>
                  {getStatusBadge(task.status)}
                </div>

                <h3 className="text-sm font-bold text-[#111827] mt-1">{task.title}</h3>
                <p className="text-xs text-[#64748B] mt-1.5 leading-relaxed line-clamp-2">
                  {task.description}
                </p>
              </div>

              <div className="pt-4 mt-4 border-t border-[#E2E8F0] flex items-center justify-between gap-3 text-xs">
                <div className="flex items-center gap-1.5 text-[#64748B]">
                  <Calendar className="w-3.5 h-3.5 text-[#64748B]" />
                  <span>
                    {task.due_date ? new Date(task.due_date).toLocaleDateString() : 'Rolling'}
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setSelectedTask(task)}
                    className="px-2.5 py-1 text-xs font-semibold text-[#2563EB] hover:bg-[#EFF6FF] rounded-md transition-colors"
                  >
                    View Details
                  </button>

                  {task.status !== 'completed' ? (
                    <button
                      disabled={updatingTaskId === task.id}
                      onClick={() => handleUpdateStatus(task.id, 'completed')}
                      className="px-2.5 py-1 text-xs font-semibold text-white bg-[#2563EB] hover:bg-[#1D4ED8] rounded-md transition-colors disabled:opacity-50"
                    >
                      {updatingTaskId === task.id ? 'Saving...' : 'Mark Complete'}
                    </button>
                  ) : (
                    <button
                      disabled={updatingTaskId === task.id}
                      onClick={() => handleUpdateStatus(task.id, 'in_progress')}
                      className="px-2.5 py-1 text-xs font-medium text-[#64748B] hover:text-[#111827] border border-[#E2E8F0] rounded-md transition-colors disabled:opacity-50"
                    >
                      Reopen
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Detail Modal */}
      {selectedTask && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-xs">
          <div className="bg-white rounded-xl border border-[#E2E8F0] max-w-lg w-full p-6 shadow-xl space-y-5">
            <div className="flex items-center justify-between pb-3 border-b border-[#E2E8F0]">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-[#2563EB] bg-[#EFF6FF] px-2 py-0.5 rounded border border-[#BFDBFE]">
                  {selectedTask.category}
                </span>
                {getStatusBadge(selectedTask.status)}
              </div>
              <button
                onClick={() => setSelectedTask(null)}
                className="p-1 rounded-md text-[#64748B] hover:text-[#111827] hover:bg-[#F8FAFC]"
                aria-label="Close modal"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div>
              <h2 className="text-lg font-bold text-[#111827]">{selectedTask.title}</h2>
              <span className="text-xs text-[#64748B] block mt-0.5">
                Issued by {selectedTask.issued_by} • {selectedTask.hackathon_title}
              </span>
              <p className="text-xs text-[#475569] mt-3 leading-relaxed bg-[#F8FAFC] p-4 rounded-lg border border-[#E2E8F0]">
                {selectedTask.description}
              </p>
            </div>

            {selectedTask.action_url && (
              <div>
                <a
                  href={selectedTask.action_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#2563EB] hover:underline"
                >
                  <span>Open Task Resource / External Link</span>
                  <ExternalLink className="w-3.5 h-3.5" />
                </a>
              </div>
            )}

            <div className="pt-3 border-t border-[#E2E8F0] flex items-center justify-between">
              <span className="text-xs text-[#64748B]">Update status:</span>
              <div className="flex items-center gap-2">
                <button
                  disabled={updatingTaskId === selectedTask.id}
                  onClick={() => handleUpdateStatus(selectedTask.id, 'new')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium border ${
                    selectedTask.status === 'new'
                      ? 'bg-[#111827] text-white border-[#111827]'
                      : 'border-[#E2E8F0] text-[#64748B] hover:bg-[#F8FAFC]'
                  }`}
                >
                  New
                </button>
                <button
                  disabled={updatingTaskId === selectedTask.id}
                  onClick={() => handleUpdateStatus(selectedTask.id, 'in_progress')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium border ${
                    selectedTask.status === 'in_progress'
                      ? 'bg-[#2563EB] text-white border-[#2563EB]'
                      : 'border-[#E2E8F0] text-[#64748B] hover:bg-[#F8FAFC]'
                  }`}
                >
                  In Progress
                </button>
                <button
                  disabled={updatingTaskId === selectedTask.id}
                  onClick={() => handleUpdateStatus(selectedTask.id, 'completed')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium border ${
                    selectedTask.status === 'completed'
                      ? 'bg-[#16A34A] text-white border-[#16A34A]'
                      : 'border-[#E2E8F0] text-[#64748B] hover:bg-[#F8FAFC]'
                  }`}
                >
                  Completed
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
