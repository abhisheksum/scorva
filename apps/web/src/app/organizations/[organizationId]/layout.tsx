'use client';

import React, { useState, useEffect, use } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Building2,
  Trophy,
  Shield,
  LogOut,
  Sparkles,
  ArrowLeft,
  Calendar,
  AlertCircle,
  Menu,
  X,
} from 'lucide-react';
import { api, ApiClientError } from '@/lib/api-client';
import { OrganizationProfileResponse } from '@/types/api';
import { useAuth } from '@/lib/auth-context';
import { StatusBadge } from '@/components/admin/StatusBadge';

export default function TenantOrganizationLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ organizationId: string }>;
}) {
  const unwrappedParams = use(params);
  const orgId = unwrappedParams.organizationId;
  const pathname = usePathname();
  const { user, logout } = useAuth();

  const [prevOrgId, setPrevOrgId] = useState<string>(orgId);
  const [org, setOrg] = useState<OrganizationProfileResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState<boolean>(false);

  // Synchronous render-phase state adjustment: eliminates 1-frame stale data paint on navigation
  if (orgId !== prevOrgId) {
    setPrevOrgId(orgId);
    setOrg(null);
    setIsLoading(true);
    setError(null);
  }

  useEffect(() => {
    const controller = new AbortController();
    // Immediately reset tenant state to prevent stale data when switching organizations
    setOrg(null);
    setError(null);
    setIsLoading(true);

    async function loadTenantProfile() {
      try {
        const data = await api.getTenantOrganizationProfile(orgId, { signal: controller.signal });
        if (!controller.signal.aborted) {
          setOrg(data);
        }
      } catch (err: unknown) {
        if (controller.signal.aborted) return;
        if (err instanceof ApiClientError && err.code === 'REQUEST_ABORTED') return;
        if (err instanceof ApiClientError) {
          setError(err.message);
        } else {
          setError('Failed to load tenant workspace.');
        }
      } finally {
        if (!controller.signal.aborted) {
          setIsLoading(false);
        }
      }
    }
    loadTenantProfile();
    return () => {
      controller.abort();
    };
  }, [orgId]);

  const formatRole = (role?: string) => {
    if (!role) return 'Member';
    return role
      .split('_')
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
      .join(' ');
  };

  const navLinks = [
    {
      title: 'Hackathons',
      href: `/organizations/${orgId}/hackathons`,
      icon: Trophy,
    },
    {
      title: 'Organization Profile',
      href: `/organizations/${orgId}`,
      icon: Building2,
    },
  ];

  return (
    <div className="min-h-screen bg-background flex flex-col font-sans">
      {/* Top Tenant Navigation Bar */}
      <header className="h-16 bg-surface border-b border-surface-border px-4 sm:px-6 flex items-center justify-between shrink-0 z-20">
        <div className="flex items-center gap-4">
          <Link
            href={`/organizations/${orgId}`}
            className="flex items-center gap-2.5 overflow-hidden focus:outline-none"
          >
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center text-white font-bold shrink-0 shadow-md shadow-primary/20">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <div className="flex flex-col truncate">
              <span className="font-bold text-sm tracking-wide text-text-primary">
                {(org && org.id === orgId) ? org.name : 'Scorva Tenant'}
              </span>
              <span className="text-[10px] text-text-muted font-mono truncate">
                /{(org && org.id === orgId) ? org.slug : orgId.slice(0, 8)}
              </span>
            </div>
          </Link>

          {org && org.id === orgId && (
            <div className="hidden sm:flex items-center gap-2 pl-3 border-l border-surface-border">
              <StatusBadge status={org.status} size="sm" />
              <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-primary/10 text-primary border border-primary/20">
                {formatRole(org.current_user_role)}
              </span>
            </div>
          )}
        </div>

        {/* Center / Navigation Links (Desktop) */}
        <nav className="hidden md:flex items-center gap-1">
          {navLinks.map((item) => {
            const active = pathname === item.href || (item.href.includes('/hackathons') && pathname.startsWith(item.href));
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  active
                    ? 'bg-primary text-white shadow-xs'
                    : 'text-text-secondary hover:text-text-primary hover:bg-surface-elevated'
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                <span>{item.title}</span>
              </Link>
            );
          })}
        </nav>

        {/* Right Controls */}
        <div className="flex items-center gap-3">
          {/* Platform Admin Back Link if user has platform privileges */}
          {user?.platform_role && (
            <Link
              href="/admin/organizations"
              className="hidden lg:flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-text-muted hover:text-text-primary bg-surface-elevated hover:bg-surface-hover rounded-lg border border-surface-border transition-colors"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Platform Admin Plane</span>
            </Link>
          )}

          <div className="flex items-center gap-2 pl-2 border-l border-surface-border">
            <span className="hidden sm:inline-block text-xs font-semibold text-text-primary">
              {user?.full_name}
            </span>
            <button
              type="button"
              onClick={async () => {
                await logout();
              }}
              className="p-1.5 text-text-muted hover:text-status-error hover:bg-status-error/10 rounded-lg transition-colors"
              title="Log out"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>

          <button
            type="button"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="md:hidden p-1.5 text-text-muted hover:text-text-primary hover:bg-surface-elevated rounded-lg transition-colors"
          >
            {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>
      </header>

      {/* Mobile Drawer */}
      {mobileMenuOpen && (
        <div className="md:hidden bg-surface border-b border-surface-border p-4 space-y-2 animate-in slide-in-from-top-2">
          {navLinks.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setMobileMenuOpen(false)}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium text-text-secondary hover:text-text-primary hover:bg-surface-elevated transition-colors"
            >
              <item.icon className="w-4 h-4" />
              <span>{item.title}</span>
            </Link>
          ))}
          {user?.platform_role && (
            <Link
              href="/admin/organizations"
              onClick={() => setMobileMenuOpen(false)}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium text-text-muted hover:text-text-primary transition-colors border-t border-surface-border pt-3"
            >
              <ArrowLeft className="w-4 h-4" />
              <span>Return to Platform Super Admin</span>
            </Link>
          )}
        </div>
      )}

      {/* Main Tenant Container */}
      <main className="flex-1 p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto w-full">
        {error ? (
          <div className="p-8 bg-surface rounded-2xl border border-surface-border text-center max-w-md mx-auto my-12">
            <AlertCircle className="w-10 h-10 text-status-error mx-auto mb-3" />
            <h2 className="text-base font-semibold text-text-primary">Tenant Access Denied</h2>
            <p className="text-xs text-text-muted mt-1 mb-4">{error}</p>
            <Link
              href="/admin/organizations"
              className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-text-primary bg-surface-elevated hover:bg-surface-hover rounded-lg transition-colors border border-surface-border"
            >
              <ArrowLeft className="w-4 h-4" />
              <span>Return to Platform Admin</span>
            </Link>
          </div>
        ) : (
          children
        )}
      </main>
    </div>
  );
}
