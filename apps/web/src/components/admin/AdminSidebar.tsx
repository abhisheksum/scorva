'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  LayoutDashboard,
  Building2,
  Users,
  ShieldCheck,
  Trophy,
  CreditCard,
  Cpu,
  Activity,
  ShieldAlert,
  LifeBuoy,
  Bell,
  Blocks,
  Settings,
  X,
  ChevronLeft,
  ChevronRight,
  Sparkles,
} from 'lucide-react';
import { NavSection } from '@/types/admin';

const navigationSections: NavSection[] = [
  {
    title: 'Overview',
    items: [
      {
        title: 'Dashboard',
        href: '/admin',
        icon: LayoutDashboard,
        priority: 'P0',
      },
    ],
  },
  {
    title: 'Platform Management',
    items: [
      {
        title: 'Organizations',
        href: '/admin/organizations',
        icon: Building2,
        priority: 'P0',
      },
      {
        title: 'Users & Access',
        href: '/admin/users',
        icon: Users,
        priority: 'P0',
      },
      {
        title: 'Roles & Permissions',
        href: '/admin/roles-permissions',
        icon: ShieldCheck,
        priority: 'P0',
      },
      {
        title: 'Hackathons',
        href: '/admin/hackathons',
        icon: Trophy,
        priority: 'P0',
      },
      {
        title: 'Plans & Billing',
        href: '/admin/billing',
        icon: CreditCard,
        priority: 'P2',
      },
    ],
  },
  {
    title: 'AI & Infrastructure',
    items: [
      {
        title: 'AI Operations',
        href: '/admin/ai-operations',
        icon: Cpu,
        priority: 'P0',
      },
      {
        title: 'System Health',
        href: '/admin/system-health',
        icon: Activity,
        priority: 'P0',
      },
    ],
  },
  {
    title: 'Trust & Support',
    items: [
      {
        title: 'Security & Audit',
        href: '/admin/security',
        icon: ShieldAlert,
        priority: 'P0',
      },
      {
        title: 'Support Center',
        href: '/admin/support',
        icon: LifeBuoy,
        priority: 'P1',
      },
      {
        title: 'Notifications',
        href: '/admin/notifications',
        icon: Bell,
        priority: 'P1',
      },
      {
        title: 'Integrations',
        href: '/admin/integrations',
        icon: Blocks,
        priority: 'P0',
      },
      {
        title: 'Platform Settings',
        href: '/admin/settings',
        icon: Settings,
        priority: 'P0',
      },
    ],
  },
];

interface AdminSidebarProps {
  isCollapsed: boolean;
  setIsCollapsed: (collapsed: boolean) => void;
  mobileOpen: boolean;
  setMobileOpen: (open: boolean) => void;
}

export const AdminSidebar: React.FC<AdminSidebarProps> = ({
  isCollapsed,
  setIsCollapsed,
  mobileOpen,
  setMobileOpen,
}) => {
  const pathname = usePathname();

  const isRouteActive = (href: string) => {
    if (href === '/admin') {
      return pathname === '/admin';
    }
    return pathname.startsWith(href);
  };

  const navContent = (
    <div className="flex flex-col h-full bg-sidebar border-r border-surface-border select-none">
      {/* Brand Header */}
      <div className="flex items-center justify-between px-4 h-16 border-b border-surface-border shrink-0">
        <Link
          href="/admin"
          className="flex items-center gap-2.5 overflow-hidden focus:outline-none"
        >
          <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center text-white font-bold shrink-0 shadow-md shadow-primary/20">
            <Sparkles className="w-5 h-5 text-white" />
          </div>
          {(!isCollapsed || mobileOpen) && (
            <div className="flex flex-col truncate">
              <span className="font-bold text-base tracking-wider text-text-primary uppercase">
                Scorva
              </span>
              <span className="text-[10px] uppercase font-semibold text-text-muted tracking-widest">
                Super Admin
              </span>
            </div>
          )}
        </Link>

        {/* Mobile close button */}
        {mobileOpen && (
          <button
            onClick={() => setMobileOpen(false)}
            className="md:hidden text-text-muted hover:text-text-primary p-1.5 rounded-lg hover:bg-surface-elevated transition-colors"
            aria-label="Close sidebar"
          >
            <X className="w-5 h-5" />
          </button>
        )}
      </div>

      {/* Navigation Links */}
      <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-6">
        {navigationSections.map((section) => (
          <div key={section.title} className="space-y-1">
            {(!isCollapsed || mobileOpen) && (
              <h2 className="px-3 text-[11px] font-semibold text-text-muted uppercase tracking-wider mb-2">
                {section.title}
              </h2>
            )}
            <ul className="space-y-1">
              {section.items.map((item) => {
                const active = isRouteActive(item.href);
                const Icon = item.icon;

                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      onClick={() => setMobileOpen(false)}
                      title={isCollapsed && !mobileOpen ? item.title : undefined}
                      className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-all group ${
                        active
                          ? 'bg-primary text-white shadow-sm shadow-primary/30'
                          : 'text-text-secondary hover:text-text-primary hover:bg-surface-elevated'
                      } ${isCollapsed && !mobileOpen ? 'justify-center px-2' : ''}`}
                    >
                      <Icon
                        className={`w-4 h-4 shrink-0 transition-colors ${
                          active
                            ? 'text-white'
                            : 'text-text-muted group-hover:text-text-primary'
                        }`}
                      />
                      {(!isCollapsed || mobileOpen) && (
                        <div className="flex items-center justify-between flex-1 truncate">
                          <span className="truncate">{item.title}</span>
                          {item.priority === 'P2' && (
                            <span
                              className={`text-[10px] px-1.5 py-0.5 rounded uppercase font-bold tracking-tight ${
                                active
                                  ? 'bg-white/20 text-white'
                                  : 'bg-surface-elevated text-text-muted border border-surface-border'
                              }`}
                            >
                              P2
                            </span>
                          )}
                        </div>
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      {/* Footer / Desktop Collapse Toggle */}
      <div className="p-3 border-t border-surface-border shrink-0 hidden md:flex items-center gap-2.5">
        <div className="w-8 h-8 rounded-full bg-surface-elevated border border-surface-border flex items-center justify-center text-xs font-bold text-text-primary shrink-0 shadow-inner">
          N
        </div>
        {!isCollapsed && (
          <button
            onClick={() => setIsCollapsed(true)}
            aria-label="Collapse sidebar"
            className="flex items-center gap-2 px-2 py-1.5 text-xs font-medium text-text-muted hover:text-text-primary hover:bg-surface-elevated rounded-lg transition-colors flex-1"
          >
            <ChevronLeft className="w-4 h-4" />
            <span>Collapse Sidebar</span>
          </button>
        )}
        {isCollapsed && (
          <button
            onClick={() => setIsCollapsed(false)}
            aria-label="Expand sidebar"
            className="p-1 text-text-muted hover:text-text-primary rounded"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        )}
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop Persistent Sidebar */}
      <aside
        className={`hidden md:flex flex-col shrink-0 transition-all duration-200 ease-in-out z-20 ${
          isCollapsed ? 'w-[72px]' : 'w-[260px]'
        }`}
      >
        {navContent}
      </aside>

      {/* Mobile Off-Canvas Drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          {/* Backdrop */}
          <div
            className="fixed inset-0 bg-black/60 backdrop-blur-xs transition-opacity"
            onClick={() => setMobileOpen(false)}
            aria-hidden="true"
          />
          {/* Drawer panel */}
          <div className="fixed inset-y-0 left-0 w-[280px] z-50 animate-in slide-in-from-left duration-200">
            {navContent}
          </div>
        </div>
      )}
    </>
  );
};
