'use client';

import React, { useState, useEffect, useRef } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  Menu,
  Megaphone,
  LifeBuoy,
  ChevronRight,
  ExternalLink,
  CheckCircle2,
  RefreshCw,
  AlertCircle,
} from 'lucide-react';
import { useAuth } from '@/lib/auth-context';
import { api } from '@/lib/api-client';
import { ParticipantNotificationItem } from '@/types/api';

interface ParticipantHeaderProps {
  onOpenMobileMenu: () => void;
  unreadNotificationsCount?: number;
}

export function ParticipantHeader({
  onOpenMobileMenu,
  unreadNotificationsCount = 0,
}: ParticipantHeaderProps) {
  const { user } = useAuth();
  const router = useRouter();

  // Dropdown state
  const [isOpen, setIsOpen] = useState(false);
  const [announcements, setAnnouncements] = useState<ParticipantNotificationItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  const fetchDropdownAnnouncements = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await api.getParticipantNotifications();
      const items = (res.notifications || []).filter((n) => n.type === 'announcement');
      setAnnouncements(items.slice(0, 3));
    } catch {
      setError('Unable to load announcements.');
    } finally {
      setIsLoading(false);
    }
  };

  const toggleDropdown = () => {
    if (!isOpen) {
      setIsOpen(true);
      fetchDropdownAnnouncements();
    } else {
      setIsOpen(false);
    }
  };

  // Close on outside click
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node) &&
        buttonRef.current &&
        !buttonRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsOpen(false);
        buttonRef.current?.focus();
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      document.addEventListener('keydown', handleKeyDown);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen]);

  const handleAnnouncementClick = (item: ParticipantNotificationItem) => {
    setIsOpen(false);
    if (item.action_url) {
      router.push(item.action_url);
    } else {
      router.push('/participant/announcements');
    }
  };

  return (
    <header className="h-16 bg-white border-b border-[#E2E8F0] px-4 sm:px-8 flex items-center justify-between sticky top-0 z-20 shrink-0">
      {/* Mobile Burger & Left Breadcrumb */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onOpenMobileMenu}
          className="md:hidden p-2 text-[#64748B] hover:text-[#111827] hover:bg-[#F8FAFC] rounded-lg transition-colors border border-[#E2E8F0]"
          aria-label="Open sidebar menu"
        >
          <Menu className="w-5 h-5" />
        </button>

        <div className="hidden sm:flex items-center gap-2 text-xs text-[#64748B]">
          <span className="font-semibold text-[#111827]">Participant Workspace</span>
          <span>/</span>
          <span>Hackathon Portal</span>
        </div>
      </div>

      {/* Right status & quick links */}
      <div className="flex items-center gap-3 relative">
        {/* Announcements Dropdown Trigger */}
        <div className="relative">
          <button
            ref={buttonRef}
            type="button"
            onClick={toggleDropdown}
            className={`relative p-2 rounded-lg border transition-colors ${
              isOpen
                ? 'bg-[#EFF6FF] text-[#2563EB] border-[#BFDBFE]'
                : 'text-[#64748B] hover:text-[#111827] hover:bg-[#F8FAFC] border-[#E2E8F0]'
            }`}
            title="Announcements"
            aria-label="View announcements"
            aria-expanded={isOpen}
            aria-haspopup="true"
          >
            <Megaphone className="w-4 h-4" />
            {unreadNotificationsCount > 0 && (
              <span className="absolute -top-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-[#2563EB] text-[10px] font-bold text-white shadow-xs">
                {unreadNotificationsCount > 9 ? '9+' : unreadNotificationsCount}
              </span>
            )}
          </button>

          {/* Compact Dropdown Menu */}
          {isOpen && (
            <div
              ref={dropdownRef}
              className="absolute right-0 mt-2 w-80 sm:w-96 bg-white border border-[#E2E8F0] rounded-xl shadow-lg z-50 overflow-hidden animate-in fade-in-0 zoom-in-95 duration-100"
              role="menu"
              aria-orientation="vertical"
              aria-labelledby="announcements-menu"
            >
              <div className="p-3.5 border-b border-[#E2E8F0] flex items-center justify-between bg-[#F8FAFC]">
                <div className="flex items-center gap-2">
                  <Megaphone className="w-4 h-4 text-[#2563EB]" />
                  <span className="text-xs font-bold text-[#111827]">Recent Announcements</span>
                </div>
                {unreadNotificationsCount > 0 && (
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-[#EFF6FF] text-[#2563EB] border border-[#BFDBFE]">
                    {unreadNotificationsCount} new
                  </span>
                )}
              </div>

              <div className="max-h-80 overflow-y-auto divide-y divide-[#E2E8F0]">
                {isLoading ? (
                  <div className="p-8 flex flex-col items-center justify-center gap-2 text-xs text-[#64748B]">
                    <RefreshCw className="w-4 h-4 animate-spin text-[#2563EB]" />
                    <span>Loading announcements...</span>
                  </div>
                ) : error ? (
                  <div className="p-4 text-center space-y-1">
                    <AlertCircle className="w-5 h-5 text-[#DC2626] mx-auto" />
                    <p className="text-xs text-[#DC2626]">{error}</p>
                  </div>
                ) : announcements.length === 0 ? (
                  <div className="p-8 text-center space-y-1">
                    <CheckCircle2 className="w-6 h-6 text-[#16A34A] mx-auto mb-1" />
                    <p className="text-xs font-semibold text-[#111827]">No announcements yet</p>
                    <p className="text-[11px] text-[#64748B]">
                      Official organizer broadcasts will be displayed here.
                    </p>
                  </div>
                ) : (
                  announcements.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => handleAnnouncementClick(item)}
                      className={`w-full text-left p-3.5 transition-colors hover:bg-[#F8FAFC] flex items-start gap-3 ${
                        !item.is_read ? 'bg-[#F0F7FF]/50' : 'bg-white'
                      }`}
                    >
                      <div
                        className={`w-7 h-7 rounded-md flex items-center justify-center shrink-0 mt-0.5 border ${
                          !item.is_read
                            ? 'bg-[#EFF6FF] border-[#BFDBFE] text-[#2563EB]'
                            : 'bg-[#F8FAFC] border-[#E2E8F0] text-[#64748B]'
                        }`}
                      >
                        <Megaphone className="w-3.5 h-3.5" />
                      </div>

                      <div className="flex-1 min-w-0 space-y-1">
                        <div className="flex items-center justify-between gap-1">
                          <span className="text-xs font-semibold text-[#111827] truncate">
                            {item.title}
                          </span>
                          {!item.is_read && (
                            <span className="w-2 h-2 rounded-full bg-[#2563EB] shrink-0" />
                          )}
                        </div>
                        <p className="text-[11px] text-[#64748B] line-clamp-2 leading-relaxed">
                          {item.description}
                        </p>
                        <span className="text-[10px] text-[#94A3B8] block">
                          {new Date(item.created_at).toLocaleDateString()}
                        </span>
                      </div>
                    </button>
                  ))
                )}
              </div>

              <div className="p-2.5 border-t border-[#E2E8F0] bg-[#F8FAFC] text-center">
                <Link
                  href="/participant/announcements"
                  onClick={() => setIsOpen(false)}
                  className="inline-flex items-center justify-center gap-1.5 text-xs font-semibold text-[#2563EB] hover:text-[#1D4ED8] transition-colors py-1 w-full"
                >
                  <span>View All Announcements</span>
                  <ChevronRight className="w-3.5 h-3.5" />
                </Link>
              </div>
            </div>
          )}
        </div>

        {/* Support Center Link */}
        <Link
          href="/participant/support"
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-[#64748B] hover:text-[#111827] hover:bg-[#F8FAFC] border border-[#E2E8F0] transition-colors"
          title="Get Help & Support"
        >
          <LifeBuoy className="w-3.5 h-3.5 text-[#2563EB]" />
          <span className="hidden sm:inline">Support Center</span>
        </Link>
      </div>
    </header>
  );
}
