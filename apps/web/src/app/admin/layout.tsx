'use client';

import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Shield, Loader2 } from 'lucide-react';
import { AdminSidebar } from '@/components/admin/AdminSidebar';
import { AdminHeader } from '@/components/admin/AdminHeader';
import { useAuth } from '@/lib/auth-context';

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const { user, isLoading } = useAuth();
  const [isCollapsed, setIsCollapsed] = useState<boolean>(false);
  const [mobileOpen, setMobileOpen] = useState<boolean>(false);

  useEffect(() => {
    if (!isLoading) {
      if (!user) {
        router.replace('/login');
      } else if (!user.platform_role) {
        const dest = user.routing?.default_destination || '/participant';
        router.replace(dest);
      }
    }
  }, [user, isLoading, router]);

  if (isLoading) {
    return (
      <div className="h-screen w-screen bg-background flex flex-col items-center justify-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
          <Shield className="w-5 h-5 animate-pulse" />
        </div>
        <div className="flex items-center gap-2 text-xs text-text-muted">
          <Loader2 className="w-3.5 h-3.5 animate-spin text-primary" />
          <span>Verifying administrative authorization...</span>
        </div>
      </div>
    );
  }

  if (!user || !user.platform_role) {
    return (
      <div className="h-screen w-screen bg-background flex flex-col items-center justify-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-status-danger/10 border border-status-danger/20 flex items-center justify-center text-status-danger">
          <Shield className="w-5 h-5 animate-pulse" />
        </div>
        <div className="flex flex-col items-center gap-1 text-center max-w-sm px-4">
          <span className="text-sm font-semibold text-text-primary">Administrative Access Restricted</span>
          <span className="text-xs text-text-muted">
            Your account does not possess platform administration privileges. Redirecting to your assigned workspace...
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-background overflow-hidden">
      {/* Sidebar Navigation */}
      <AdminSidebar
        isCollapsed={isCollapsed}
        setIsCollapsed={setIsCollapsed}
        mobileOpen={mobileOpen}
        setMobileOpen={setMobileOpen}
      />

      {/* Main Content Area */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <AdminHeader onOpenMobileMenu={() => setMobileOpen(true)} />
        <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8">
          <div className="max-w-7xl mx-auto">{children}</div>
        </main>
      </div>
    </div>
  );
}
