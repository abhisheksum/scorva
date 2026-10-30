'use client';

import React from 'react';
import Link from 'next/link';
import { Menu, Bell, LifeBuoy, Sparkles } from 'lucide-react';
import { useAuth } from '@/lib/auth-context';

interface ParticipantHeaderProps {
  onOpenMobileMenu: () => void;
  unreadNotificationsCount?: number;
}

export function ParticipantHeader({
  onOpenMobileMenu,
  unreadNotificationsCount = 0,
}: ParticipantHeaderProps) {
  const { user } = useAuth();

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
      <div className="flex items-center gap-3">
        {/* Notifications Icon with Badge */}
        <Link
          href="/participant/notifications"
          className="relative p-2 text-[#64748B] hover:text-[#111827] hover:bg-[#F8FAFC] rounded-lg border border-[#E2E8F0] transition-colors"
          title="Notifications"
          aria-label="View notifications"
        >
          <Bell className="w-4 h-4" />
          {unreadNotificationsCount > 0 && (
            <span className="absolute -top-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-[#2563EB] text-[10px] font-bold text-white shadow-xs">
              {unreadNotificationsCount > 9 ? '9+' : unreadNotificationsCount}
            </span>
          )}
        </Link>

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
