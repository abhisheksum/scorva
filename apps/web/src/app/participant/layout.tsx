'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth-context';
import { ParticipantSidebar } from '@/components/participant/ParticipantSidebar';
import { ParticipantHeader } from '@/components/participant/ParticipantHeader';
import { UnskippableRegistrationModal } from '@/components/participant/UnskippableRegistrationModal';
import { api } from '@/lib/api-client';
import { RegistrationStatusResponse } from '@/types/api';
import { Loader2 } from 'lucide-react';

export default function ParticipantLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user, isLoading } = useAuth();
  const router = useRouter();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState<number>(0);
  const [regStatus, setRegStatus] = useState<RegistrationStatusResponse | null>(null);
  const [isCheckingReg, setIsCheckingReg] = useState(true);

  const refreshNotificationCount = useCallback(async () => {
    try {
      const data = await api.getParticipantNotifications();
      const announcements = data.notifications.filter((n) => n.type === 'announcement');
      if (announcements.length > 0) {
        const unreadAnnouncements = announcements.filter((n) => !n.is_read).length;
        setUnreadCount(unreadAnnouncements);
      } else {
        setUnreadCount(data.unread_count);
      }
    } catch {
      // Non-blocking
    }
  }, []);

  const checkRegistrationStatus = useCallback(async () => {
    setIsCheckingReg(true);
    try {
      const data = await api.getParticipantRegistrationStatus();
      setRegStatus(data);
    } catch (err) {
      console.error('Failed to check registration status', err);
    } finally {
      setIsCheckingReg(false);
    }
  }, []);

  useEffect(() => {
    if (!isLoading && !user) {
      router.push('/auth/login?redirect=/participant');
    } else if (user) {
      refreshNotificationCount();
      checkRegistrationStatus();
    }
  }, [user, isLoading, router, refreshNotificationCount, checkRegistrationStatus]);

  if (isLoading || !user || isCheckingReg) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] flex flex-col items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-8 h-8 text-[#2563EB] animate-spin" />
          <p className="text-xs font-medium text-[#64748B]">
            Loading Participant Workspace...
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-[#F8FAFC] text-[#111827] overflow-hidden relative">
      {/* Unskippable Mandatory Onboarding Intake Modal */}
      {regStatus && !regStatus.is_registered && (
        <UnskippableRegistrationModal
          statusData={regStatus}
          onSuccess={() => {
            checkRegistrationStatus();
            refreshNotificationCount();
          }}
        />
      )}

      {/* Desktop Sidebar */}
      <div className="hidden md:flex md:w-64 md:shrink-0 h-full">
        <ParticipantSidebar unreadNotificationsCount={unreadCount} />
      </div>

      {/* Mobile Sidebar Overlay Drawer */}
      {mobileMenuOpen && (
        <div className="fixed inset-0 z-40 md:hidden flex">
          <div
            className="fixed inset-0 bg-black/50 backdrop-blur-xs transition-opacity"
            onClick={() => setMobileMenuOpen(false)}
            aria-hidden="true"
          />
          <div className="relative flex-1 flex flex-col max-w-xs w-full bg-white z-40">
            <ParticipantSidebar
              onCloseMobile={() => setMobileMenuOpen(false)}
              unreadNotificationsCount={unreadCount}
            />
          </div>
        </div>
      )}

      {/* Main Content Column */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <ParticipantHeader
          onOpenMobileMenu={() => setMobileMenuOpen(true)}
          unreadNotificationsCount={unreadCount}
        />
        <main className="flex-1 overflow-y-auto bg-[#F8FAFC]">
          <div className="max-w-7xl mx-auto px-4 sm:px-8 py-7 md:py-8">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
