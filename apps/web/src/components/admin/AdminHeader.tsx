'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Menu,
  Search,
  Bell,
  Shield,
  User,
  LogOut,
  ChevronDown,
  Building2,
  ExternalLink,
} from 'lucide-react';
import { HealthIndicator } from './HealthIndicator';
import { useAuth } from '@/lib/auth-context';
import { api } from '@/lib/api-client';
import { OrganizationSummaryResponse } from '@/types/api';

interface AdminHeaderProps {
  onOpenMobileMenu: () => void;
}

export const AdminHeader: React.FC<AdminHeaderProps> = ({ onOpenMobileMenu }) => {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [tenantSwitcherOpen, setTenantSwitcherOpen] = useState(false);
  const [recentOrgs, setRecentOrgs] = useState<OrganizationSummaryResponse[]>([]);

  const handleToggleTenantSwitcher = () => {
    const nextState = !tenantSwitcherOpen;
    setTenantSwitcherOpen(nextState);
    if (nextState && recentOrgs.length === 0) {
      api.getAdminOrganizations({ limit: 5, sort_by: 'created_at', sort_order: 'desc' })
        .then((res) => setRecentOrgs(res.items))
        .catch(() => {});
    }
  };

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

  const formatRole = (role?: string | null) => {
    if (!role) return 'Administrator';
    return role
      .split('_')
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
      .join(' ');
  };

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

        {/* Tenant Plane Context Switcher */}
        <div className="relative">
          <button
            type="button"
            onClick={handleToggleTenantSwitcher}
            className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors"
            title="Switch to Tenant Organization Workspace"
          >
            <Building2 className="w-3.5 h-3.5 text-primary" />
            <span className="hidden md:inline">Tenant Plane</span>
            <ChevronDown className="w-3 h-3 text-text-muted" />
          </button>

          {tenantSwitcherOpen && (
            <div className="absolute right-0 mt-2 w-72 bg-surface border border-surface-border rounded-xl shadow-surface-elevated py-2 z-50 animate-in fade-in zoom-in-95 duration-100">
              <div className="px-3 py-1.5 border-b border-surface-border">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                  Tenant Organization Workspace
                </span>
                <p className="text-[11px] text-text-muted mt-0.5">
                  Inspect organization-scoped portal view
                </p>
              </div>

              <div className="py-1 max-h-56 overflow-y-auto">
                {recentOrgs.length === 0 ? (
                  <div className="px-3 py-2 text-xs text-text-muted text-center">
                    No organizations loaded
                  </div>
                ) : (
                  recentOrgs.map((o) => (
                    <Link
                      key={o.id}
                      href={`/organizations/${o.id}`}
                      onClick={() => setTenantSwitcherOpen(false)}
                      className="flex items-center justify-between px-3 py-2 text-xs text-text-primary hover:bg-surface-elevated transition-colors"
                    >
                      <div className="truncate pr-2">
                        <div className="font-medium truncate">{o.name}</div>
                        <div className="text-[10px] text-text-muted font-mono">/{o.slug}</div>
                      </div>
                      <ExternalLink className="w-3.5 h-3.5 text-text-muted shrink-0" />
                    </Link>
                  ))
                )}
              </div>

              <div className="px-2 pt-1.5 border-t border-surface-border">
                <Link
                  href="/admin/organizations"
                  onClick={() => setTenantSwitcherOpen(false)}
                  className="flex items-center justify-center gap-1.5 w-full px-2 py-1.5 text-xs text-primary font-medium hover:bg-primary/10 rounded-lg transition-colors"
                >
                  <span>Manage All Tenants in Admin</span>
                </Link>
              </div>
            </div>
          )}
        </div>

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
          <span className="truncate max-w-[200px] lg:max-w-none">Search organizations, users, hackathons...</span>
          <kbd className="px-1.5 py-0.5 text-[10px] bg-surface rounded border border-surface-border text-text-muted">
            ⌘K
          </kbd>
        </button>

        {/* Live Backend Health Indicator */}
        <HealthIndicator />

        {/* Announcements Bell */}
        <button
          type="button"
          aria-label="View announcements"
          className="relative p-2 text-text-muted hover:text-text-primary hover:bg-surface-elevated rounded-lg transition-colors"
        >
          <Bell className="w-4 h-4" />
          <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-primary rounded-full animate-pulse" />
        </button>

        {/* Profile Chip & Dropdown */}
        <div className="relative pl-2 border-l border-surface-border">
          <button
            type="button"
            onClick={() => setMenuOpen(!menuOpen)}
            className="flex items-center gap-2.5 p-1 rounded-lg hover:bg-surface-elevated transition-colors text-left"
          >
            <div className="w-8 h-8 rounded-full bg-surface-elevated border border-surface-border flex items-center justify-center text-text-primary shrink-0">
              <User className="w-4 h-4 text-primary" />
            </div>
            <div className="hidden xl:flex flex-col text-left">
              <span className="text-xs font-semibold text-text-primary leading-tight">
                {user?.full_name || 'Platform Administrator'}
              </span>
              <div className="flex items-center gap-1">
                <Shield className="w-2.5 h-2.5 text-primary" />
                <span className="text-[10px] text-text-muted leading-tight">
                  {formatRole(user?.platform_role)}
                </span>
              </div>
            </div>
            <ChevronDown className="w-3.5 h-3.5 text-text-muted hidden xl:block" />
          </button>

          {/* User Menu Dropdown */}
          {menuOpen && (
            <div className="absolute right-0 mt-2 w-64 bg-surface border border-surface-border rounded-xl shadow-surface-elevated py-2 z-50 animate-in fade-in zoom-in-95 duration-100">
              <div className="px-4 py-2 border-b border-surface-border">
                <p className="text-xs font-semibold text-text-primary truncate">
                  {user?.full_name || 'Super Administrator'}
                </p>
                <p className="text-[11px] text-text-muted truncate mt-0.5">
                  {user?.email || 'admin@scorva.io'}
                </p>
                <div className="mt-2 flex items-center gap-1.5">
                  <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-status-success/10 text-status-success border border-status-success/20">
                    Active Session
                  </span>
                  {user?.mfa_enabled && (
                    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-primary/10 text-primary border border-primary/20">
                      MFA Protected
                    </span>
                  )}
                </div>
              </div>

              <div className="px-2 pt-1">
                <button
                  type="button"
                  onClick={async () => {
                    setMenuOpen(false);
                    await logout();
                  }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-xs text-status-error hover:bg-status-error/10 rounded-lg transition-colors"
                >
                  <LogOut className="w-3.5 h-3.5" />
                  <span>Log Out of Scorva</span>
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
};
