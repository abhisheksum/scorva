'use client';

import React from 'react';
import { usePathname } from 'next/navigation';
import {
  Menu,
  Search,
  Bell,
  Shield,
  User,
} from 'lucide-react';
import { HealthIndicator } from './HealthIndicator';

interface AdminHeaderProps {
  onOpenMobileMenu: () => void;
}

export const AdminHeader: React.FC<AdminHeaderProps> = ({ onOpenMobileMenu }) => {
  const pathname = usePathname();

  const getBreadcrumbs = () => {
    const segments = pathname.split('/').filter(Boolean);
    if (segments.length === 1 && segments[0] === 'admin') {
      return [{ label: 'Admin', href: '/admin' }, { label: 'Platform Overview', href: '/admin' }];
    }

    return segments.map((seg, idx) => {
      const href = '/' + segments.slice(0, idx + 1).join('/');
      const label = seg
        .split('-')
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(' ');
      return { label, href };
    });
  };

  const breadcrumbs = getBreadcrumbs();
  const environment = process.env.NEXT_PUBLIC_APP_ENV || 'development';

  return (
    <header className="h-16 bg-surface border-b border-surface-border px-4 sm:px-6 flex items-center justify-between shrink-0 z-10">
      {/* Left: Mobile Menu Button & Breadcrumbs */}
      <div className="flex items-center gap-3">
        <button
          onClick={onOpenMobileMenu}
          className="md:hidden p-2 rounded-lg text-text-muted hover:text-text-primary hover:bg-surface-elevated transition-colors"
          aria-label="Open navigation menu"
        >
          <Menu className="w-5 h-5" />
        </button>

        {/* Breadcrumb Navigation */}
        <nav aria-label="Breadcrumb" className="hidden sm:flex items-center gap-2 text-xs">
          {breadcrumbs.map((crumb, idx) => (
            <React.Fragment key={crumb.href + idx}>
              {idx > 0 && <span className="text-surface-border">/</span>}
              <span
                className={
                  idx === breadcrumbs.length - 1
                    ? 'font-medium text-text-primary'
                    : 'text-text-muted'
                }
              >
                {crumb.label}
              </span>
            </React.Fragment>
          ))}
        </nav>
      </div>

      {/* Right Controls: Global Search, Health, Alerts, Profile */}
      <div className="flex items-center gap-2.5 sm:gap-4">
        {/* Environment Tag */}
        <span className="hidden lg:inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-primary/10 text-primary border border-primary/20">
          {environment}
        </span>

        {/* Global Search Palette Trigger */}
        <button
          type="button"
          onClick={() => {
            // Future phase: opens Command Palette modal
          }}
          className="hidden sm:flex items-center gap-2 px-3 py-1.5 text-xs text-text-muted bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors"
          title="Search organizations, users, jobs (⌘K)"
        >
          <Search className="w-3.5 h-3.5" />
          <span>Quick search...</span>
          <kbd className="px-1.5 py-0.5 text-[10px] bg-surface rounded border border-surface-border text-text-muted">
            ⌘K
          </kbd>
        </button>

        {/* Live Backend Health Indicator */}
        <HealthIndicator />

        {/* Notification Bell */}
        <button
          type="button"
          aria-label="View notifications"
          className="relative p-2 text-text-muted hover:text-text-primary hover:bg-surface-elevated rounded-lg transition-colors"
        >
          <Bell className="w-4 h-4" />
          <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-primary rounded-full animate-pulse" />
        </button>

        {/* Profile Chip */}
        <div className="flex items-center gap-2.5 pl-2 border-l border-surface-border">
          <div className="w-8 h-8 rounded-full bg-surface-elevated border border-surface-border flex items-center justify-center text-text-primary shrink-0">
            <User className="w-4 h-4 text-primary" />
          </div>
          <div className="hidden xl:flex flex-col text-left">
            <span className="text-xs font-semibold text-text-primary leading-tight">
              Platform Admin
            </span>
            <div className="flex items-center gap-1">
              <Shield className="w-2.5 h-2.5 text-primary" />
              <span className="text-[10px] text-text-muted leading-tight">
                Platform Owner
              </span>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
};
