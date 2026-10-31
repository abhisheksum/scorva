'use client';

import React, { useState, useEffect } from 'react';
import {
  Settings,
  Key,
  ShieldCheck,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  ExternalLink,
  Eye,
  EyeOff,
  Trash2,
  Lock,
  User,
  Github,
  Info,
  Play,
  Clock,
  GitBranch,
  Layers,
  Sparkles,
} from 'lucide-react';
import { api, ApiClientError } from '@/lib/api-client';
import { useAuth } from '@/lib/auth-context';
import {
  ParticipantPatTokenStatus,
  ParticipantGitHubSettingsResponse,
} from '@/types/api';

export default function ParticipantSettingsPage() {
  const { user } = useAuth();

  const [patStatus, setPatStatus] = useState<ParticipantPatTokenStatus | null>(null);
  const [githubSettings, setGithubSettings] = useState<ParticipantGitHubSettingsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // PAT Form states
  const [patTokenInput, setPatTokenInput] = useState('');
  const [showToken, setShowToken] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  // GitHub Verification states
  const [isVerifyingRepo, setIsVerifyingRepo] = useState(false);
  const [verifySuccess, setVerifySuccess] = useState<string | null>(null);
  const [verifyError, setVerifyError] = useState<string | null>(null);

  const fetchSettingsData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [patData, githubData] = await Promise.all([
        api.getParticipantPatStatus(),
        api.getParticipantGitHubSettings(),
      ]);
      setPatStatus(patData);
      setGithubSettings(githubData);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to load settings data.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchSettingsData();
  }, []);

  const handleSavePat = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaveError(null);
    setSaveSuccess(null);

    const token = patTokenInput.trim();
    if (!token || token.length < 15) {
      setSaveError('Personal Access Token must be at least 15 characters long.');
      return;
    }

    setIsSaving(true);
    try {
      const res = await api.saveParticipantPat({ pat_token: token });
      setSaveSuccess(
        `PAT verified successfully! Account @${res.verified_username || 'verified'} authenticated.`
      );
      setPatTokenInput('');
      await fetchSettingsData();
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setSaveError(err.message);
      } else {
        setSaveError('Failed to verify and save token. Please check token permissions.');
      }
    } finally {
      setIsSaving(false);
    }
  };

  const handleDeletePat = async () => {
    if (!confirm('Are you sure you want to remove your stored Personal Access Token?')) {
      return;
    }

    setIsDeleting(true);
    setSaveError(null);
    setSaveSuccess(null);
    try {
      await api.deleteParticipantPat();
      setSaveSuccess('Personal Access Token removed successfully.');
      await fetchSettingsData();
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setSaveError(err.message);
      } else {
        setSaveError('Failed to remove token.');
      }
    } finally {
      setIsDeleting(false);
    }
  };

  const handleRunVerification = async () => {
    setIsVerifyingRepo(true);
    setVerifyError(null);
    setVerifySuccess(null);
    try {
      const res = await api.verifyParticipantGitHubRepository();
      setVerifySuccess(res.message);
      // Refresh GitHub status to show 'verified' badge and updated timestamp
      const updatedGitHub = await api.getParticipantGitHubSettings();
      setGithubSettings(updatedGitHub);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setVerifyError(err.message);
      } else {
        setVerifyError('Repository ownership verification failed. Please check token scopes and repo URL.');
      }
    } finally {
      setIsVerifyingRepo(false);
    }
  };

  return (
    <div className="space-y-8 max-w-4xl mx-auto">
      {/* Header */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl p-6 sm:p-8 flex flex-col sm:flex-row sm:items-center justify-between gap-4 shadow-xs">
        <div>
          <div className="flex items-center gap-2 mb-1.5 text-xs font-semibold uppercase tracking-wider text-[#2563EB]">
            <Settings className="w-4 h-4" />
            Participant Configuration
          </div>
          <h1 className="text-xl sm:text-2xl font-bold text-[#111827]">
            Account & Integration Settings
          </h1>
          <p className="text-xs sm:text-sm text-[#64748B] mt-1 leading-relaxed">
            Manage your registered GitHub repository, verify ownership credentials, and configure Personal Access Tokens.
          </p>
        </div>
      </div>

      {/* SECTION 1: GitHub Repository & Ownership Verification */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden shadow-xs">
        <div className="p-6 sm:p-7 border-b border-[#E2E8F0]">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-[#EFF6FF] border border-[#BFDBFE] flex items-center justify-center text-[#2563EB]">
                <Github className="w-5 h-5" />
              </div>
              <div>
                <h2 className="text-base font-bold text-[#111827]">
                  GitHub Repository & Ownership
                </h2>
                <p className="text-xs text-[#64748B] mt-0.5">
                  Registered during mandatory intake form submission.
                </p>
              </div>
            </div>

            {/* Verification Badge */}
            {!isLoading && githubSettings && (
              <div>
                {githubSettings.verification_status === 'verified' ? (
                  <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-[#F0FDF4] text-[#16A34A] border border-[#BBF7D0] shadow-2xs">
                    <ShieldCheck className="w-4 h-4" />
                    Verified Repository
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-[#FEF3C7] text-[#D97706] border border-[#FDE68A] shadow-2xs">
                    <Clock className="w-3.5 h-3.5" />
                    Unverified
                  </span>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="p-6 sm:p-7 space-y-6">
          {/* Feedback Banners for GitHub Verification */}
          {verifySuccess && (
            <div className="p-3.5 rounded-lg bg-[#F0FDF4] border border-[#BBF7D0] flex items-center gap-2.5 text-xs text-[#16A34A]">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <span className="font-medium">{verifySuccess}</span>
            </div>
          )}

          {verifyError && (
            <div className="p-3.5 rounded-lg bg-[#FEF2F2] border border-[#FECACA] flex items-center gap-2.5 text-xs text-[#DC2626]">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span className="font-medium">{verifyError}</span>
            </div>
          )}

          {isLoading ? (
            <div className="py-8 flex flex-col items-center justify-center text-center">
              <RefreshCw className="w-6 h-6 text-[#2563EB] animate-spin mb-2" />
              <p className="text-xs text-[#64748B]">Loading repository details...</p>
            </div>
          ) : !githubSettings?.has_registration ? (
            <div className="p-5 rounded-xl bg-[#F8FAFC] border border-[#E2E8F0] text-center space-y-2">
              <Github className="w-8 h-8 text-[#94A3B8] mx-auto" />
              <p className="text-xs font-semibold text-[#111827]">No GitHub repository registered yet</p>
              <p className="text-xs text-[#64748B]">
                Your repository will appear here once you submit the team and project intake registration.
              </p>
            </div>
          ) : (
            <div className="space-y-5">
              {/* Registered Intake Info Grid */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="p-4 rounded-xl bg-[#F8FAFC] border border-[#E2E8F0] space-y-1">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-[#64748B]">
                    Registered Team
                  </span>
                  <div className="text-sm font-bold text-[#111827]">
                    {githubSettings.team_name}
                    {githubSettings.team_number && (
                      <span className="ml-2 font-mono text-xs font-semibold text-[#2563EB] bg-[#EFF6FF] px-2 py-0.5 rounded border border-[#BFDBFE]">
                        {githubSettings.team_number}
                      </span>
                    )}
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-[#F8FAFC] border border-[#E2E8F0] space-y-1">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-[#64748B]">
                    Project Submission Title
                  </span>
                  <div className="text-sm font-bold text-[#111827] truncate">
                    {githubSettings.project_title || 'Untitled Submission'}
                  </div>
                </div>
              </div>

              {/* Repository Link Details */}
              <div className="p-4 rounded-xl bg-[#F8FAFC] border border-[#E2E8F0] space-y-3">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div>
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-[#64748B] block">
                      Target Repository URL
                    </span>
                    <a
                      href={githubSettings.repository_url || '#'}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-mono text-xs sm:text-sm font-semibold text-[#2563EB] hover:underline inline-flex items-center gap-1.5 mt-0.5"
                    >
                      <Github className="w-4 h-4 text-[#111827]" />
                      <span>{githubSettings.repository_url}</span>
                      <ExternalLink className="w-3.5 h-3.5" />
                    </a>
                  </div>

                  {githubSettings.verified_at && (
                    <div className="text-[11px] text-[#64748B]">
                      Verified on {new Date(githubSettings.verified_at).toLocaleString()}
                    </div>
                  )}
                </div>

                {githubSettings.diagnostic_message && (
                  <p className="text-xs text-[#64748B] pt-2 border-t border-[#E2E8F0]">
                    {githubSettings.diagnostic_message}
                  </p>
                )}
              </div>

              {/* Run Verification Button Section */}
              <div className="pt-2 flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 rounded-xl bg-[#EFF6FF]/50 border border-[#BFDBFE]">
                <div className="space-y-0.5">
                  <span className="text-xs font-bold text-[#111827] flex items-center gap-1.5">
                    <Sparkles className="w-3.5 h-3.5 text-[#2563EB]" />
                    Automated Ownership Verification
                  </span>
                  <p className="text-xs text-[#475569]">
                    {githubSettings.pat_configured
                      ? 'PAT is configured. Click "Run Verification" to verify repository ownership and grant evaluation access.'
                      : 'Please configure your Personal Access Token (PAT) below to run ownership verification.'}
                  </p>
                </div>

                <button
                  type="button"
                  onClick={handleRunVerification}
                  disabled={isVerifyingRepo || !githubSettings.pat_configured}
                  className={`inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg text-xs font-semibold shadow-xs transition-colors shrink-0 ${
                    githubSettings.verification_status === 'verified'
                      ? 'bg-white border border-[#E2E8F0] text-[#111827] hover:bg-[#F8FAFC]'
                      : 'bg-[#2563EB] hover:bg-[#1D4ED8] text-white'
                  } disabled:opacity-50 disabled:cursor-not-allowed`}
                  title={
                    !githubSettings.pat_configured
                      ? 'Save your PAT token in the section below first'
                      : 'Verify repository ownership'
                  }
                >
                  {isVerifyingRepo ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      <span>Running Verification...</span>
                    </>
                  ) : (
                    <>
                      <Play className="w-3.5 h-3.5 fill-current" />
                      <span>
                        {githubSettings.verification_status === 'verified'
                          ? 'Re-Run Verification'
                          : 'Run Verification'}
                      </span>
                    </>
                  )}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* SECTION 2: Personal Access Token (PAT) Configuration */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden shadow-xs">
        <div className="p-6 sm:p-7 border-b border-[#E2E8F0]">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-[#EFF6FF] border border-[#BFDBFE] flex items-center justify-center text-[#2563EB]">
                <Key className="w-5 h-5" />
              </div>
              <div>
                <h2 className="text-base font-bold text-[#111827]">
                  Personal Access Token (PAT) Configuration
                </h2>
                <p className="text-xs text-[#64748B] mt-0.5">
                  Used by the verification engine to confirm GitHub repository access.
                </p>
              </div>
            </div>

            {/* Current Status Pill */}
            {!isLoading && patStatus && (
              <div>
                {patStatus.has_token && patStatus.is_verified ? (
                  <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-[#F0FDF4] text-[#16A34A] border border-[#BBF7D0]">
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    PAT Active ({patStatus.verified_username ? `@${patStatus.verified_username}` : 'Authenticated'})
                  </span>
                ) : patStatus.has_token ? (
                  <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-[#FEF3C7] text-[#D97706] border border-[#FDE68A]">
                    Token Unverified
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-[#F8FAFC] text-[#64748B] border border-[#E2E8F0]">
                    Not Configured
                  </span>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Card Body */}
        <div className="p-6 sm:p-7 space-y-6">
          <div className="p-4 rounded-xl bg-[#F8FAFC] border border-[#E2E8F0] flex items-start gap-3">
            <Info className="w-4 h-4 text-[#2563EB] shrink-0 mt-0.5" />
            <div className="text-xs text-[#475569] space-y-1 leading-relaxed">
              <p>
                <strong>Security note:</strong> Your PAT token is encrypted using AES-256-GCM.
                It is used exclusively to verify repository access and ownership for hackathon evaluation.
              </p>
              <p className="text-[11px] text-[#64748B]">
                Supported formats: Classic Personal Access Tokens (<code>ghp_...</code>) or Fine-Grained Tokens (<code>github_pat_...</code>).
              </p>
            </div>
          </div>

          {/* Feedback Banners for PAT */}
          {saveSuccess && (
            <div className="p-3.5 rounded-lg bg-[#F0FDF4] border border-[#BBF7D0] flex items-center gap-2.5 text-xs text-[#16A34A]">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <span className="font-medium">{saveSuccess}</span>
            </div>
          )}

          {saveError && (
            <div className="p-3.5 rounded-lg bg-[#FEF2F2] border border-[#FECACA] flex items-center gap-2.5 text-xs text-[#DC2626]">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span className="font-medium">{saveError}</span>
            </div>
          )}

          {/* Active Configured Token Box */}
          {!isLoading && patStatus?.has_token && (
            <div className="p-4 rounded-xl bg-[#EFF6FF]/60 border border-[#BFDBFE] space-y-3">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div>
                  <span className="text-xs font-bold text-[#111827] block">Active PAT Credential</span>
                  <span className="font-mono text-xs text-[#2563EB] bg-white px-2 py-0.5 rounded border border-[#BFDBFE] mt-1 inline-block">
                    {patStatus.token_masked}
                  </span>
                </div>

                <button
                  type="button"
                  onClick={handleDeletePat}
                  disabled={isDeleting}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-[#DC2626] hover:bg-white border border-transparent hover:border-[#FECACA] transition-colors disabled:opacity-50 self-start sm:self-center"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  <span>{isDeleting ? 'Removing...' : 'Revoke Token'}</span>
                </button>
              </div>

              {patStatus.last_verified_at && (
                <div className="text-[11px] text-[#64748B] flex items-center gap-1.5 pt-1 border-t border-[#BFDBFE]/60">
                  <ShieldCheck className="w-3.5 h-3.5 text-[#16A34A]" />
                  <span>Token authenticated on {new Date(patStatus.last_verified_at).toLocaleString()}</span>
                  {patStatus.verified_username && (
                    <span>• User: <strong>@{patStatus.verified_username}</strong></span>
                  )}
                </div>
              )}
            </div>
          )}

          {/* PAT Entry / Update Form */}
          <form onSubmit={handleSavePat} className="space-y-4">
            <div>
              <label
                htmlFor="pat-token-input"
                className="block text-xs font-semibold text-[#111827] mb-1.5"
              >
                {patStatus?.has_token ? 'Update Personal Access Token' : 'Enter Personal Access Token (PAT)'}
              </label>

              <div className="relative">
                <input
                  id="pat-token-input"
                  type={showToken ? 'text' : 'password'}
                  required
                  value={patTokenInput}
                  onChange={(e) => setPatTokenInput(e.target.value)}
                  placeholder="Paste your ghp_ or github_pat_ token here"
                  className="w-full pr-10 pl-3.5 py-2.5 text-xs sm:text-sm rounded-lg bg-white border border-[#E2E8F0] font-mono text-[#111827] placeholder-[#94A3B8] focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent transition-all"
                />
                <button
                  type="button"
                  onClick={() => setShowToken(!showToken)}
                  className="absolute inset-y-0 right-0 pr-3 flex items-center text-[#64748B] hover:text-[#111827]"
                  title={showToken ? 'Hide token' : 'Show token'}
                >
                  {showToken ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>

              <div className="mt-2 flex flex-col sm:flex-row sm:items-center justify-between text-xs text-[#64748B] gap-2">
                <span>Recommended scopes: <code>read:user</code>, <code>repo</code></span>
                <a
                  href="https://github.com/settings/tokens"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-[#2563EB] hover:underline font-medium"
                >
                  <span>Generate token on GitHub</span>
                  <ExternalLink className="w-3 h-3" />
                </a>
              </div>
            </div>

            <div className="pt-2 flex justify-end">
              <button
                type="submit"
                disabled={isSaving || !patTokenInput.trim()}
                className="inline-flex items-center gap-2 px-5 py-2.5 bg-[#2563EB] text-white text-xs font-semibold rounded-lg hover:bg-[#1D4ED8] transition-colors shadow-xs disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isSaving ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    <span>Verifying Token...</span>
                  </>
                ) : (
                  <>
                    <ShieldCheck className="w-3.5 h-3.5" />
                    <span>Verify & Save Token</span>
                  </>
                )}
              </button>
            </div>
          </form>
        </div>

        {/* Security / Encryption Notice Footer */}
        <div className="px-6 sm:px-7 py-4 bg-[#F8FAFC] border-t border-[#E2E8F0] flex items-center gap-2.5 text-xs text-[#64748B]">
          <Lock className="w-4 h-4 text-[#2563EB] shrink-0" />
          <span>
            Tokens are encrypted at rest with <strong>AES-256-GCM</strong>.
            Raw token secrets are never exposed over APIs.
          </span>
        </div>
      </div>

      {/* Account Info Card */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl p-6 sm:p-7 shadow-xs space-y-4">
        <h3 className="text-sm font-bold text-[#111827] flex items-center gap-2">
          <User className="w-4 h-4 text-[#2563EB]" />
          Participant Profile Details
        </h3>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-1">
          <div className="p-3.5 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0]">
            <span className="text-[11px] font-semibold text-[#64748B] block">Full Name</span>
            <span className="text-sm font-bold text-[#111827] mt-0.5 block">
              {user?.full_name || 'Participant'}
            </span>
          </div>

          <div className="p-3.5 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0]">
            <span className="text-[11px] font-semibold text-[#64748B] block">Email Address</span>
            <span className="text-sm font-bold text-[#111827] mt-0.5 block truncate">
              {user?.email}
            </span>
          </div>

          <div className="p-3.5 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0]">
            <span className="text-[11px] font-semibold text-[#64748B] block">Workspace Role</span>
            <span className="text-sm font-bold text-[#2563EB] capitalize mt-0.5 block">
              Hackathon Participant
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
