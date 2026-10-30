'use client';

import React from 'react';
import Link from 'next/link';
import {
  BookOpen,
  ShieldCheck,
  Scale,
  Sparkles,
  CheckCircle2,
  AlertTriangle,
  FileText,
  Lock,
  ArrowRight,
} from 'lucide-react';

export default function JudgeGuidelinesPage() {
  return (
    <div className="space-y-8 max-w-4xl">
      {/* Page Header */}
      <div className="pb-2 border-b border-[#E2E8F0]">
        <h1 className="text-2xl font-bold tracking-tight text-[#111827]">
          Judge Guidelines & Review Standards
        </h1>
        <p className="text-sm text-[#64748B] mt-1">
          Reference material and best practices for evaluating hackathon submissions on Scorva.
        </p>
      </div>

      {/* Advisory Guidance Standard */}
      <div className="p-6 rounded-xl bg-[#EFF6FF] border border-[#BFDBFE] shadow-xs space-y-3">
        <div className="flex items-center gap-2.5 text-[#1E3A8A]">
          <ShieldCheck className="w-5 h-5 text-[#2563EB]" />
          <h2 className="text-base font-bold text-[#1E3A8A]">
            Core Principle: Human Independence
          </h2>
        </div>
        <p className="text-sm text-[#1E3A8A] leading-relaxed">
          <strong>AI assessment is provided as guidance. Your score and feedback are your independent decision.</strong>
        </p>
        <p className="text-xs text-[#3B82F6] leading-relaxed">
          The automated analysis checks static analysis, code references, and rubric adherence to assist your workflow. You are never obligated to adopt suggested scores. Discrepancies between your evaluation and AI recommendations are normal and respected.
        </p>
      </div>

      {/* 4-Step Review Workflow */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl p-6 shadow-xs space-y-6">
        <div className="flex items-center gap-2.5">
          <Scale className="w-5 h-5 text-[#2563EB]" />
          <h2 className="text-base font-bold text-[#111827]">
            The 4-Step Review Workflow
          </h2>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          <div className="p-4 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0] space-y-2">
            <div className="flex items-center gap-2">
              <span className="w-6 h-6 rounded-full bg-[#2563EB] text-white flex items-center justify-center font-bold text-xs">
                1
              </span>
              <h3 className="text-sm font-bold text-[#111827]">
                Inspect Project & Repository
              </h3>
            </div>
            <p className="text-xs text-[#64748B] leading-relaxed">
              Examine the team’s description, problem statement, repository URL, target branch, and verified commit SHA. Ensure the codebase matches the stated goals.
            </p>
          </div>

          <div className="p-4 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0] space-y-2">
            <div className="flex items-center gap-2">
              <span className="w-6 h-6 rounded-full bg-[#2563EB] text-white flex items-center justify-center font-bold text-xs">
                2
              </span>
              <h3 className="text-sm font-bold text-[#111827]">
                Examine Advisory AI Findings
              </h3>
            </div>
            <p className="text-xs text-[#64748B] leading-relaxed">
              Review automated suggestions and grounded code references (file citations, line numbers, and snippets). Verify that key architectural claims are backed by code.
            </p>
          </div>

          <div className="p-4 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0] space-y-2">
            <div className="flex items-center gap-2">
              <span className="w-6 h-6 rounded-full bg-[#2563EB] text-white flex items-center justify-center font-bold text-xs">
                3
              </span>
              <h3 className="text-sm font-bold text-[#111827]">
                Award Rubric Criterion Scores
              </h3>
            </div>
            <p className="text-xs text-[#64748B] leading-relaxed">
              Score each published rubric criterion within the permitted range (0 to 100). Scorva automatically calculates the weighted score based on organizer-configured weights.
            </p>
          </div>

          <div className="p-4 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0] space-y-2">
            <div className="flex items-center gap-2">
              <span className="w-6 h-6 rounded-full bg-[#2563EB] text-white flex items-center justify-center font-bold text-xs">
                4
              </span>
              <h3 className="text-sm font-bold text-[#111827]">
                Provide Constructive Feedback
              </h3>
            </div>
            <p className="text-xs text-[#64748B] leading-relaxed">
              Compose detailed feedback highlighting the team’s strengths and actionable areas for improvement. Select a recommendation decision (Accept, Adjusted, or Reject).
            </p>
          </div>
        </div>
      </div>

      {/* Drafts vs Final Submission */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl p-6 shadow-xs space-y-4">
        <div className="flex items-center gap-2.5">
          <FileText className="w-5 h-5 text-[#2563EB]" />
          <h2 className="text-base font-bold text-[#111827]">
            Drafts & Submission Immutability
          </h2>
        </div>

        <div className="space-y-3 text-xs text-[#64748B] leading-relaxed">
          <div className="flex items-start gap-2.5">
            <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
            <div>
              <strong className="text-[#111827] block">Saving Drafts:</strong>
              Drafts are private to you. You can save your progress at any time, exit, and resume later. Organizers cannot see unfinished drafts.
            </div>
          </div>

          <div className="flex items-start gap-2.5">
            <Lock className="w-4 h-4 text-[#D97706] shrink-0 mt-0.5" />
            <div>
              <strong className="text-[#111827] block">Submitting Reviews:</strong>
              Once submitted, a review is final and locked. Submitted scores feed directly into the hackathon leaderboard aggregations. A confirmation modal will appear before finalizing.
            </div>
          </div>
        </div>
      </div>

      {/* Quick navigation */}
      <div className="pt-2">
        <Link
          href="/judge/projects"
          className="inline-flex items-center gap-2 px-5 py-2.5 text-xs font-semibold text-white bg-[#2563EB] hover:bg-blue-700 rounded-lg transition-colors shadow-xs"
        >
          <span>Return to Assigned Projects</span>
          <ArrowRight className="w-4 h-4" />
        </Link>
      </div>
    </div>
  );
}
