'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  LayoutDashboard,
  Trophy,
  BarChart3,
  CheckSquare,
  Bell,
  LifeBuoy,
  LogOut,
  User,
  Compass,
  X,
} from 'lucide-react';
import { useAuth } from '@/lib/auth-context';

interface ParticipantSidebarProps {
  onCloseMobile?: () => void;
  unreadNotificationsCount?: number;
}

export function ParticipantSidebar({
  onCloseMobile,
  unreadNotificationsCount = 0,
}: ParticipantSidebarProps) {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  const navItems = [
    {
      name: 'Overview',
      href: '/participant',
      icon: LayoutDashboard,
      exact: true,
    },
    {
      name: 'Leaderboard',
      href: '/participant/leaderboard',
      icon: Trophy,
      exact: false,
    },
    {
      name: 'My Performance',
      href: '/participant/performance',
      icon: BarChart3,
      exact: false,
    },
    {
      name: 'Tasks & Opportunities',
      href: '/participant/tasks',
      icon: CheckSquare,
      exact: false,
    },
    {
      name: 'Notifications',
      href: '/participant/notifications',
      icon: Bell,
      exact: false,
      badge: unreadNotificationsCount > 0 ? unreadNotificationsCount : null,
    },
    {
      name: 'Support Center',
      href: '/participant/support',
      icon: LifeBuoy,
      exact: false,
    },
  ];

  const isItemActive = (href: string, exact: boolean) => {
    if (exact) {
      return pathname === href;
    }
    return pathname.startsWith(href);
  };

  return (
    <aside className="w-64 bg-[#FFFFFF] text-[#111827] flex flex-col h-full border-r border-[#E2E8F0] select-none">
      {/* Brand Header */}
      <div className="h-16 px-6 flex items-center justify-between border-b border-[#E2E8F0]">
        <Link
          href="/participant"
          className="flex items-center gap-2.5 focus:outline-none focus:ring-2 focus:ring-[#2563EB] rounded-md"
          onClick={onCloseMobile}
        >
          <div className="w-8 h-8 rounded-lg bg-[#2563EB] flex items-center justify-center text-white shadow-xs">
            <Compass className="w-4 h-4 text-white" />
          </div>
          <div className="flex flex-col">
            <span className="font-bold text-base tracking-tight text-[#111827] leading-tight">
              SCORVA
            </span>
            <span className="text-[10px] font-semibold uppercase tracking-wider text-[#2563EB] leading-tight">
              Participant Hub
            </span>
          </div>
        </Link>

        {onCloseMobile && (
          <button
            type="button"
            onClick={onCloseMobile}
            className="md:hidden p-1.5 text-[#64748B] hover:text-[#111827] rounded-lg hover:bg-[#F1F5F9] transition-colors"
            aria-label="Close menu"
          >
            <X className="w-5 h-5" />
          </button>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-6 space-y-1.5 overflow-y-auto">
        <div className="px-3 pb-2 text-[10px] font-semibold uppercase tracking-wider text-[#64748B]">
          Participant Workspace
        </div>
        {navItems.map((item) => {
          const active = isItemActive(item.href, item.exact);
          const Icon = item.icon;
          return (
            <Link
              key={item.name}
              href={item.href}
              onClick={onCloseMobile}
              className={`flex items-center justify-between px-3.5 py-2.5 rounded-lg text-sm font-medium transition-all ${
                active
                  ? 'bg-[#EFF6FF] text-[#2563EB] font-semibold border border-[#BFDBFE]/60 shadow-xs'
                  : 'text-[#475569] hover:text-[#111827] hover:bg-[#F1F5F9] border border-transparent'
              }`}
            >
              <div className="flex items-center gap-3">
                <Icon
                  className={`w-4 h-4 shrink-0 transition-colors ${
                    active ? 'text-[#2563EB]' : 'text-[#64748B]'
                  }`}
                />
                <span>{item.name}</span>
              </div>
              {item.badge !== null && item.badge !== undefined && (
                <span className="px-1.5 py-0.5 rounded-full text-[11px] font-semibold bg-[#2563EB] text-white leading-none">
                  {item.badge}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* Footer / Participant Profile */}
      <div className="p-4 border-t border-[#E2E8F0] bg-[#FFFFFF]">
        <div className="flex items-center justify-between gap-3 p-2.5 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0]">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-8 h-8 rounded-full bg-[#EFF6FF] border border-[#BFDBFE] flex items-center justify-center text-[#2563EB] shrink-0 font-semibold text-xs">
              {user?.full_name
                ? user.full_name
                    .split(' ')
                    .map((n) => n[0])
                    .join('')
                    .toUpperCase()
                    .slice(0, 2)
                : <User className="w-3.5 h-3.5" />}
            </div>
            <div className="flex flex-col min-w-0">
              <span className="text-xs font-semibold text-[#111827] truncate leading-tight">
                {user?.full_name || 'Participant'}
              </span>
              <span className="text-[10px] text-[#64748B] truncate leading-tight mt-0.5">
                {user?.email}
              </span>
            </div>
          </div>

          <button
            type="button"
            onClick={async () => {
              await logout();
              window.location.href = '/auth/login';
            }}
            className="p-1.5 text-[#64748B] hover:text-[#DC2626] rounded-md hover:bg-white transition-colors"
            title="Sign out"
            aria-label="Sign out"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}
