'use client';

import React, { useState, useEffect } from 'react';
import {
  Scale,
  Github,
  Users,
  FileText,
  AlertCircle,
  CheckCircle2,
  Lock,
  ArrowRight,
  Plus,
  Trash2,
  ShieldCheck,
  UserCheck,
} from 'lucide-react';
import { api, ApiClientError } from '@/lib/api-client';
import { useAuth } from '@/lib/auth-context';
import { RegistrationStatusResponse } from '@/types/api';

interface TeamMemberEntry {
  name: string;
  email: string;
}

interface UnskippableRegistrationModalProps {
  statusData: RegistrationStatusResponse;
  onSuccess: () => void;
}

export function UnskippableRegistrationModal({
  statusData,
  onSuccess,
}: UnskippableRegistrationModalProps) {
  const { user } = useAuth();

  const [teamName, setTeamName] = useState(statusData.default_team_name || '');
  const [teamNumber, setTeamNumber] = useState('');
  const [githubUrl, setGithubUrl] = useState('');
  const [projectTitle, setProjectTitle] = useState('');
  const [projectDescription, setProjectDescription] = useState('');
  const [agreementAccepted, setAgreementAccepted] = useState(false);

  // Dynamic team members list: up to 4 members, one by one (Name & Email in one line)
  const [members, setMembers] = useState<TeamMemberEntry[]>([
    {
      name: user?.full_name || '',
      email: user?.email || '',
    },
  ]);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Prevent background scrolling while modal is open
  useEffect(() => {
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = 'unset';
    };
  }, []);

  const handleMemberChange = (
    index: number,
    field: 'name' | 'email',
    value: string
  ) => {
    setMembers((prev) => {
      const updated = [...prev];
      updated[index] = { ...updated[index], [field]: value };
      return updated;
    });
  };

  const handleAddMember = () => {
    if (members.length >= 4) return;
    setMembers((prev) => [...prev, { name: '', email: '' }]);
  };

  const handleRemoveMember = (index: number) => {
    if (members.length <= 1) return;
    setMembers((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);

    // Validation checks
    if (!teamName.trim()) {
      setErrorMessage('Please provide your official team name.');
      return;
    }
    if (!teamNumber.trim()) {
      setErrorMessage('Please enter your team number or assigned ID (e.g. Team #12 or T-04).');
      return;
    }
    if (!githubUrl.trim() || !githubUrl.toLowerCase().includes('github.com')) {
      setErrorMessage('Please provide a valid GitHub repository URL (e.g. https://github.com/org/repo).');
      return;
    }

    // Validate each member entry
    for (let i = 0; i < members.length; i++) {
      const m = members[i];
      if (!m.name.trim()) {
        setErrorMessage(`Please enter the full name for Member ${i + 1}.`);
        return;
      }
      if (!m.email.trim() || !m.email.includes('@')) {
        setErrorMessage(`Please enter a valid email address for Member ${i + 1} (${m.name || 'unnamed'}).`);
        return;
      }
    }

    if (!projectTitle.trim() || projectTitle.trim().length < 3) {
      setErrorMessage('Please provide your project title (at least 3 characters).');
      return;
    }
    if (!projectDescription.trim() || projectDescription.trim().length < 10) {
      setErrorMessage('Please write a brief summary about your project (at least 10 characters).');
      return;
    }
    if (!agreementAccepted) {
      setErrorMessage('You must agree to the evaluation terms: judges score will be final as your score is evaluated with AI + judges.');
      return;
    }

    // Format member details string
    const formattedMemberDetails = members
      .map(
        (m, idx) =>
          `Member ${idx + 1}${idx === 0 ? ' (Lead)' : ''}: ${m.name.trim()} (${m.email.trim()})`
      )
      .join('\n');

    setIsSubmitting(true);
    try {
      await api.registerParticipantProject({
        team_name: teamName.trim(),
        team_number: teamNumber.trim(),
        github_url: githubUrl.trim(),
        team_members_details: formattedMemberDetails,
        project_title: projectTitle.trim(),
        project_description: projectDescription.trim(),
        agreement_accepted: agreementAccepted,
        hackathon_id: statusData.default_hackathon_id || undefined,
        team_id: statusData.default_team_id || undefined,
      });

      onSuccess();
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage('Failed to submit intake registration. Please verify your connection.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-slate-900/80 backdrop-blur-sm overflow-y-auto"
      role="dialog"
      aria-modal="true"
      aria-labelledby="mandatory-intake-title"
    >
      <div className="relative w-full max-w-2xl bg-white border border-[#E2E8F0] rounded-2xl shadow-2xl overflow-hidden my-auto animate-in fade-in zoom-in-95 duration-200">
        {/* Header Bar */}
        <div className="bg-[#FFFFFF] border-b border-[#E2E8F0] p-6 sm:p-7">
          <div className="flex items-center justify-between gap-3 mb-2">
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-[#EFF6FF] text-[#2563EB] border border-[#BFDBFE]">
              <Lock className="w-3.5 h-3.5" />
              Mandatory Hackathon Intake
            </span>

            {statusData.default_hackathon_title && (
              <span className="text-xs text-[#64748B] font-medium truncate max-w-[200px] sm:max-w-xs">
                {statusData.default_hackathon_title}
              </span>
            )}
          </div>

          <h2
            id="mandatory-intake-title"
            className="text-xl sm:text-2xl font-bold tracking-tight text-[#111827]"
          >
            Complete Team & Project Registration
          </h2>
          <p className="text-xs sm:text-sm text-[#64748B] mt-1.5 leading-relaxed">
            Please register your team information and project repository before accessing the workspace.
            All project submissions are verified and evaluated automatically.
          </p>
        </div>

        {/* Error Alert Banner */}
        {errorMessage && (
          <div className="mx-6 sm:mx-7 mt-5 p-3.5 rounded-lg bg-[#FEF2F2] border border-[#FECACA] flex items-start gap-2.5 text-xs text-[#DC2626]">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <span className="font-medium leading-relaxed">{errorMessage}</span>
          </div>
        )}

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="p-6 sm:p-7 space-y-5">
          {/* Row 1: Team Name & Team Number */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label
                htmlFor="intake-team-name"
                className="block text-xs font-semibold text-[#111827] mb-1.5"
              >
                Team Name <span className="text-[#DC2626]">*</span>
              </label>
              <input
                id="intake-team-name"
                type="text"
                required
                value={teamName}
                onChange={(e) => setTeamName(e.target.value)}
                placeholder="e.g. Team Quantum"
                className="w-full px-3.5 py-2.5 text-xs sm:text-sm rounded-lg bg-white border border-[#E2E8F0] text-[#111827] placeholder-[#94A3B8] focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent transition-all"
              />
            </div>

            <div>
              <label
                htmlFor="intake-team-number"
                className="block text-xs font-semibold text-[#111827] mb-1.5"
              >
                Team No. / Identifier <span className="text-[#DC2626]">*</span>
              </label>
              <input
                id="intake-team-number"
                type="text"
                required
                value={teamNumber}
                onChange={(e) => setTeamNumber(e.target.value)}
                placeholder="e.g. Team #07 or T-42"
                className="w-full px-3.5 py-2.5 text-xs sm:text-sm rounded-lg bg-white border border-[#E2E8F0] text-[#111827] placeholder-[#94A3B8] focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent transition-all"
              />
            </div>
          </div>

          {/* Row 2: GitHub Repository URL */}
          <div>
            <label
              htmlFor="intake-github-url"
              className="block text-xs font-semibold text-[#111827] mb-1.5"
            >
              GitHub Repository URL <span className="text-[#DC2626]">*</span>
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-[#64748B]">
                <Github className="w-4 h-4" />
              </div>
              <input
                id="intake-github-url"
                type="url"
                required
                value={githubUrl}
                onChange={(e) => setGithubUrl(e.target.value)}
                placeholder="https://github.com/username/repository"
                className="w-full pl-10 pr-3.5 py-2.5 text-xs sm:text-sm rounded-lg bg-white border border-[#E2E8F0] text-[#111827] placeholder-[#94A3B8] focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent transition-all"
              />
            </div>
            <p className="text-[11px] text-[#64748B] mt-1">
              Ensure repository is public or accessible to Scorva automated evaluation worker.
            </p>
          </div>

          {/* Row 3: Team Members Details (One by one, in one line: Name & Email, up to 4 members) */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <label className="block text-xs font-semibold text-[#111827]">
                  Team Member Details <span className="text-[#DC2626]">*</span>
                </label>
                <p className="text-[11px] text-[#64748B]">
                  Add member names and emails one by one (minimum 1, up to 4 members total).
                </p>
              </div>

              <span className="text-xs font-semibold text-[#2563EB] bg-[#EFF6FF] px-2.5 py-0.5 rounded-full border border-[#BFDBFE]">
                {members.length} / 4 Members
              </span>
            </div>

            <div className="space-y-2.5">
              {members.map((m, idx) => (
                <div
                  key={idx}
                  className="p-3 rounded-xl bg-[#F8FAFC] border border-[#E2E8F0] space-y-2"
                >
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-semibold text-[#111827] flex items-center gap-1.5">
                      <UserCheck className="w-3.5 h-3.5 text-[#2563EB]" />
                      Member {idx + 1} {idx === 0 && <span className="text-[10px] uppercase font-bold text-[#2563EB] bg-[#EFF6FF] px-1.5 py-0.5 rounded border border-[#BFDBFE]">Team Lead</span>}
                    </span>

                    {members.length > 1 && (
                      <button
                        type="button"
                        onClick={() => handleRemoveMember(idx)}
                        className="text-xs text-[#DC2626] hover:text-[#B91C1C] inline-flex items-center gap-1 font-medium p-0.5 rounded hover:bg-white transition-colors"
                        title="Remove member"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                        <span>Remove</span>
                      </button>
                    )}
                  </div>

                  {/* One line for Name and Email */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <input
                        type="text"
                        required
                        value={m.name}
                        onChange={(e) => handleMemberChange(idx, 'name', e.target.value)}
                        placeholder={`Member ${idx + 1} Full Name`}
                        className="w-full px-3 py-2 text-xs rounded-lg bg-white border border-[#E2E8F0] text-[#111827] placeholder-[#94A3B8] focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent transition-all"
                      />
                    </div>
                    <div>
                      <input
                        type="email"
                        required
                        value={m.email}
                        onChange={(e) => handleMemberChange(idx, 'email', e.target.value)}
                        placeholder={`Member ${idx + 1} Email Address`}
                        className="w-full px-3 py-2 text-xs rounded-lg bg-white border border-[#E2E8F0] text-[#111827] placeholder-[#94A3B8] focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent transition-all"
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* Add Member Button */}
            {members.length < 4 ? (
              <button
                type="button"
                onClick={handleAddMember}
                className="w-full py-2.5 px-3 rounded-lg border-2 border-dashed border-[#BFDBFE] bg-[#EFF6FF]/40 hover:bg-[#EFF6FF] text-xs font-semibold text-[#2563EB] flex items-center justify-center gap-2 transition-colors"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>Add Another Member ({members.length}/4)</span>
              </button>
            ) : (
              <div className="p-2.5 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0] text-center text-xs text-[#64748B]">
                Maximum team capacity reached (4 members limit).
              </div>
            )}
          </div>

          {/* Row 4: Project Title & About Project */}
          <div className="space-y-3">
            <div>
              <label
                htmlFor="intake-project-title"
                className="block text-xs font-semibold text-[#111827] mb-1.5"
              >
                Project Title <span className="text-[#DC2626]">*</span>
              </label>
              <input
                id="intake-project-title"
                type="text"
                required
                value={projectTitle}
                onChange={(e) => setProjectTitle(e.target.value)}
                placeholder="e.g. Quantum Distributed Agent Engine"
                className="w-full px-3.5 py-2.5 text-xs sm:text-sm rounded-lg bg-white border border-[#E2E8F0] text-[#111827] placeholder-[#94A3B8] focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent transition-all"
              />
            </div>

            <div>
              <label
                htmlFor="intake-about-project"
                className="block text-xs font-semibold text-[#111827] mb-1.5"
              >
                About Project (Summary & Problem Statement) <span className="text-[#DC2626]">*</span>
              </label>
              <textarea
                id="intake-about-project"
                rows={4}
                required
                value={projectDescription}
                onChange={(e) => setProjectDescription(e.target.value)}
                placeholder="Explain the problem you are solving, core architecture, key features, and tools used..."
                className="w-full px-3.5 py-2.5 text-xs sm:text-sm rounded-lg bg-white border border-[#E2E8F0] text-[#111827] placeholder-[#94A3B8] focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent transition-all"
              />
            </div>
          </div>

          {/* Agreement Checkbox Section */}
          <div className="p-4 rounded-xl bg-[#F8FAFC] border border-[#E2E8F0] space-y-2">
            <label className="flex items-start gap-3 cursor-pointer select-none">
              <input
                type="checkbox"
                required
                checked={agreementAccepted}
                onChange={(e) => setAgreementAccepted(e.target.checked)}
                className="mt-1 h-4 w-4 rounded border-[#CBD5E1] text-[#2563EB] focus:ring-[#2563EB] cursor-pointer"
              />
              <div className="space-y-1">
                <span className="text-xs sm:text-sm font-semibold text-[#111827] leading-tight block">
                  Mandatory Evaluation & Score Finality Agreement
                </span>
                <p className="text-xs text-[#475569] leading-relaxed">
                  I agree and acknowledge that all project submissions will be evaluated through
                  automated <strong>AI verification combined with official human judges</strong>.
                  I understand that the <strong>judges&apos; final score is binding and final</strong>.
                </p>
              </div>
            </label>
          </div>

          {/* Submit Action */}
          <div className="pt-2 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <span className="text-[11px] text-[#64748B] flex items-center gap-1.5">
              <ShieldCheck className="w-4 h-4 text-[#16A34A] shrink-0" />
              Submission unlocks participant workspace navigation.
            </span>

            <button
              type="submit"
              disabled={isSubmitting || !agreementAccepted}
              className="inline-flex items-center justify-center gap-2 px-6 py-2.5 rounded-lg bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-xs sm:text-sm font-semibold shadow-xs transition-colors disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
            >
              <span>{isSubmitting ? 'Registering...' : 'Submit & Enter Workspace'}</span>
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
