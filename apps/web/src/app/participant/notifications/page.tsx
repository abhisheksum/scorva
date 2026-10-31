'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import {
  Megaphone,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  CheckCheck,
  Calendar,
  Sparkles,
  ExternalLink,
} from 'lucide-react';
import { api, ApiClientError } from '@/lib/api-client';
import { NotificationListResponse, ParticipantNotificationItem } from '@/types/api';

export default function ParticipantAnnouncementsPage() {
  const [data, setData] = useState<NotificationListResponse | null>(null);
  const [filter, setFilter] = useState<'all' | 'unread'>('all');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isMarkingAll, setIsMarkingAll] = useState(false);

  const fetchAnnouncements = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await api.getParticipantNotifications();
      setData(res);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to load announcements.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchAnnouncements();
  }, []);

  // Filter strictly for announcements
  const allAnnouncements = (data?.notifications || []).filter(
    (n) => n.type === 'announcement'
  );

  const unreadAnnouncementsCount = allAnnouncements.filter((n) => !n.is_read).length;

  const filteredAnnouncements = allAnnouncements.filter((n) => {
    if (filter === 'unread') return !n.is_read;
    return true;
  });

  const handleMarkRead = async (id: string) => {
    try {
      await api.markParticipantNotificationRead(id);
      setData((prev) => {
        if (!prev) return null;
        return {
          ...prev,
          unread_count: Math.max(0, prev.unread_count - 1),
          notifications: prev.notifications.map((n) =>
            n.id === id ? { ...n, is_read: true } : n
          ),
        };
      });
    } catch (err) {
      console.error('Failed to mark announcement as read', err);
    }
  };

  const handleMarkAllRead = async () => {
    setIsMarkingAll(true);
    try {
      await api.markAllParticipantNotificationsRead();
      setData((prev) => {
        if (!prev) return null;
        return {
          ...prev,
          unread_count: 0,
          notifications: prev.notifications.map((n) => ({ ...n, is_read: true })),
        };
      });
    } catch (err) {
      console.error('Failed to mark all announcements as read', err);
    } finally {
      setIsMarkingAll(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4 shadow-xs">
        <div>
          <div className="flex items-center gap-2 mb-1 text-xs font-semibold uppercase tracking-wider text-[#2563EB]">
            <Megaphone className="w-4 h-4" />
            Broadcasts & Updates
          </div>
          <h1 className="text-xl sm:text-2xl font-bold text-[#111827]">
            Announcements
          </h1>
          <p className="text-xs text-[#64748B] mt-1">
            Official announcements, timeline changes, and competition broadcasts from hackathon organizers.
          </p>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          {unreadAnnouncementsCount > 0 && (
            <button
              onClick={handleMarkAllRead}
              disabled={isMarkingAll}
              className="inline-flex items-center gap-1.5 px-3 py-2 bg-white border border-[#E2E8F0] text-xs font-medium text-[#111827] rounded-lg hover:bg-[#F8FAFC] transition-colors disabled:opacity-50"
            >
              <CheckCheck className="w-4 h-4 text-[#2563EB]" />
              <span>{isMarkingAll ? 'Marking...' : 'Mark all as read'}</span>
            </button>
          )}

          <div className="flex items-center bg-[#F8FAFC] p-1 rounded-lg border border-[#E2E8F0]">
            <button
              onClick={() => setFilter('all')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                filter === 'all'
                  ? 'bg-white text-[#111827] shadow-2xs font-semibold'
                  : 'text-[#64748B] hover:text-[#111827]'
              }`}
            >
              All ({allAnnouncements.length})
            </button>
            <button
              onClick={() => setFilter('unread')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                filter === 'unread'
                  ? 'bg-white text-[#111827] shadow-2xs font-semibold'
                  : 'text-[#64748B] hover:text-[#111827]'
              }`}
            >
              Unread ({unreadAnnouncementsCount})
            </button>
          </div>
        </div>
      </div>

      {isLoading ? (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-16 flex flex-col items-center justify-center text-center shadow-xs">
          <RefreshCw className="w-8 h-8 text-[#2563EB] animate-spin mb-3" />
          <p className="text-sm font-semibold text-[#111827]">Loading announcements...</p>
        </div>
      ) : error ? (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-8 text-center max-w-lg mx-auto shadow-xs">
          <AlertCircle className="w-10 h-10 text-[#DC2626] mx-auto mb-3" />
          <h3 className="text-sm font-semibold text-[#111827]">Unable to load announcements</h3>
          <p className="text-xs text-[#64748B] mt-1">{error}</p>
        </div>
      ) : filteredAnnouncements.length === 0 ? (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-12 text-center max-w-xl mx-auto shadow-xs space-y-3">
          <CheckCircle2 className="w-10 h-10 text-[#16A34A] mx-auto mb-2" />
          <h3 className="text-base font-bold text-[#111827]">
            {filter === 'unread' ? 'All caught up!' : 'No announcements yet'}
          </h3>
          <p className="text-xs text-[#64748B]">
            {filter === 'unread'
              ? 'You have read all official announcements.'
              : 'There are no announcements broadcast to participants at this time.'}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredAnnouncements.map((item) => (
            <div
              key={item.id}
              className={`p-5 rounded-xl border transition-all flex flex-col sm:flex-row sm:items-center justify-between gap-4 ${
                !item.is_read
                  ? 'bg-white border-[#BFDBFE] shadow-xs'
                  : 'bg-white border-[#E2E8F0]'
              }`}
            >
              <div className="flex items-start gap-3.5">
                <div
                  className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 border ${
                    !item.is_read
                      ? 'bg-[#EFF6FF] border-[#BFDBFE]'
                      : 'bg-[#F8FAFC] border-[#E2E8F0]'
                  }`}
                >
                  <Megaphone
                    className={`w-4 h-4 ${
                      !item.is_read ? 'text-[#2563EB]' : 'text-[#64748B]'
                    }`}
                  />
                </div>

                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-bold text-[#111827]">{item.title}</span>
                    {!item.is_read && (
                      <span className="w-2 h-2 rounded-full bg-[#2563EB]" />
                    )}
                    <span className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded bg-[#EFF6FF] border border-[#BFDBFE] text-[#2563EB]">
                      Announcement
                    </span>
                  </div>
                  <p className="text-xs text-[#475569] leading-relaxed">{item.description}</p>
                  <div className="flex items-center gap-1.5 text-[10px] text-[#94A3B8]">
                    <Calendar className="w-3 h-3 text-[#94A3B8]" />
                    <span>{new Date(item.created_at).toLocaleString()}</span>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2 shrink-0 self-end sm:self-center">
                {item.action_url && (
                  <Link
                    href={item.action_url}
                    className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-semibold text-[#2563EB] hover:bg-[#EFF6FF] rounded-lg transition-colors"
                  >
                    <span>View Details</span>
                    <ExternalLink className="w-3 h-3" />
                  </Link>
                )}

                {!item.is_read && (
                  <button
                    onClick={() => handleMarkRead(item.id)}
                    className="px-3 py-1.5 text-xs font-medium text-[#64748B] hover:text-[#111827] hover:bg-[#F8FAFC] rounded-lg border border-[#E2E8F0] transition-colors"
                  >
                    Mark as read
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
