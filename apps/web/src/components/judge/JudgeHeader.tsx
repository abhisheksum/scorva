'use client';

import React from 'react';
import Link from 'next/link';
import { Menu, Scale, ShieldCheck, ExternalLink, HelpCircle } from 'lucide-react';
import { useAuth } from '@/lib/auth-context';

interface JudgeHeaderProps {
  onOpenMobileMenu: () => void;
}

export function JudgeHeader({ onOpenMobileMenu }: JudgeHeaderProps) {
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
          <span className="font-semibold text-[#111827]">Judge Workspace</span>
          <span>/</span>
          <span>Scorva Evaluation Portal</span>
        </div>
      </div>

      {/* Right status & quick links */}
      <div className="flex items-center gap-3">
        <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[#EFF6FF] border border-[#BFDBFE] text-xs font-medium text-[#2563EB]">
          <ShieldCheck className="w-3.5 h-3.5" />
          <span>Independent Reviewer</span>
        </div>

        <Link
          href="/judge/guidelines"
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-[#64748B] hover:text-[#111827] hover:bg-[#F8FAFC] border border-[#E2E8F0] transition-colors"
          title="Judging Guidelines"
        >
          <HelpCircle className="w-3.5 h-3.5 text-[#2563EB]" />
          <span className="hidden sm:inline">Review Guidelines</span>
        </Link>
      </div>
    </header>
  );
}
