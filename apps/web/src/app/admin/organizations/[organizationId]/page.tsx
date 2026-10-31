'use client';

import React, { useState, useEffect, useCallback, useRef, use } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  Building2,
  ChevronLeft,
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  X,
  Users,
  Trophy,
  Shield,
  ShieldAlert,
  Calendar,
  Copy,
  Check,
  UserPlus,
  Trash2,
  ArrowRightLeft,
  FileText,
  Clock,
  ExternalLink,
  Edit,
  History,
  Eye,
  EyeOff,
  Sparkles,
  KeyRound,
} from 'lucide-react';
import { StatusBadge } from '@/components/admin/StatusBadge';
import { api, ApiClientError } from '@/lib/api-client';
import {
  OrganizationDetailResponse,
  OrganizationMemberResponse,
  HackathonDetailResponse,
  AuditEventItem,
  OrgRole,
  OrganizationStatus,
} from '@/types/api';

type TabKey = 'overview' | 'members' | 'hackathons' | 'audit';

export default function AdminOrganizationDetailPage({
  params,
}: {
  params: Promise<{ organizationId: string }>;
}) {
  const unwrappedParams = use(params);
  const orgId = unwrappedParams.organizationId;
  const router = useRouter();
  const searchParams = useSearchParams();

  const currentTab = (searchParams.get('tab') as TabKey) || 'overview';
  const setTab = (tab: TabKey) => {
    router.replace(`/admin/organizations/${orgId}?tab=${tab}`);
  };

  const [prevOrgId, setPrevOrgId] = useState<string>(orgId);
  const [org, setOrg] = useState<OrganizationDetailResponse | null>(null);
  const [members, setMembers] = useState<OrganizationMemberResponse[]>([]);
  const [hackathons, setHackathons] = useState<HackathonDetailResponse[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEventItem[]>([]);
  const [auditAccessDenied, setAuditAccessDenied] = useState<boolean>(false);
  const [auditError, setAuditError] = useState<string | null>(null);

  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Synchronous render-phase state adjustment: eliminates 1-frame stale data paint on navigation
  if (orgId !== prevOrgId) {
    setPrevOrgId(orgId);
    setOrg(null);
    setMembers([]);
    setHackathons([]);
    setAuditEvents([]);
    setAuditAccessDenied(false);
    setAuditError(null);
    setIsLoading(true);
    setError(null);
  }
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<boolean>(false);

  // Edit Org Modal
  const [isEditModalOpen, setIsEditModalOpen] = useState<boolean>(false);
  const [editName, setEditName] = useState<string>('');
  const [editSlug, setEditSlug] = useState<string>('');
  const [isSubmittingEdit, setIsSubmittingEdit] = useState<boolean>(false);
  const [editError, setEditError] = useState<string | null>(null);

  // Status Modal
  const [isStatusModalOpen, setIsStatusModalOpen] = useState<boolean>(false);
  const [targetStatus, setTargetStatus] = useState<OrganizationStatus>('active');
  const [statusReason, setStatusReason] = useState<string>('');
  const [isSubmittingStatus, setIsSubmittingStatus] = useState<boolean>(false);
  const [statusError, setStatusError] = useState<string | null>(null);

  // Transfer Ownership Modal
  const [isTransferModalOpen, setIsTransferModalOpen] = useState<boolean>(false);
  const [newOwnerUserId, setNewOwnerUserId] = useState<string>('');
  const [transferReason, setTransferReason] = useState<string>('');
  const [isSubmittingTransfer, setIsSubmittingTransfer] = useState<boolean>(false);
  const [transferError, setTransferError] = useState<string | null>(null);

  // Add Member Modal
  const [isAddMemberModalOpen, setIsAddMemberModalOpen] = useState<boolean>(false);
  const [newMemberEmail, setNewMemberEmail] = useState<string>('');
  const [newMemberFullName, setNewMemberFullName] = useState<string>('');
  const [newMemberPassword, setNewMemberPassword] = useState<string>('');
  const [showMemberPassword, setShowMemberPassword] = useState<boolean>(false);
  const [newMemberRole, setNewMemberRole] = useState<OrgRole>('organizer');
  const [isSubmittingMember, setIsSubmittingMember] = useState<boolean>(false);
  const [memberError, setMemberError] = useState<string | null>(null);

  // Remove Member Confirm
  const [memberToRemove, setMemberToRemove] = useState<OrganizationMemberResponse | null>(null);
  const [isRemovingMember, setIsRemovingMember] = useState<boolean>(false);

  const abortControllerRef = useRef<AbortController | null>(null);

  const loadData = useCallback(async (isRefresh: boolean = false) => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const signal = controller.signal;

    if (!isRefresh) {
      // Immediate reset: prevent stale organization data during navigation
      setOrg(null);
      setMembers([]);
      setHackathons([]);
      setAuditEvents([]);
      setAuditAccessDenied(false);
      setAuditError(null);
      setIsLoading(true);
      setError(null);
    }

    try {
      const [orgData, membersData, hackathonsData] = await Promise.all([
        api.getAdminOrganization(orgId, { signal }),
        api.getAdminOrganizationMembers(orgId, { signal }).catch((err) => {
          if (err instanceof ApiClientError && err.code === 'REQUEST_ABORTED') throw err;
          return [];
        }),
        api.getAdminHackathons({ organization_id: orgId, limit: 50 }, { signal }).catch((err) => {
          if (err instanceof ApiClientError && err.code === 'REQUEST_ABORTED') throw err;
          return { items: [] };
        }),
      ]);

      if (signal.aborted) return;

      setOrg(orgData);
      setMembers(membersData);
      setHackathons(hackathonsData.items || []);

      setEditName(orgData.name);
      setEditSlug(orgData.slug);
      setTargetStatus(orgData.status);

      // Fetch audit events separately to distinguish 403 access denial honestly
      try {
        const auditData = await api.getAuditEvents({ organization_id: orgId, limit: 30 }, { signal });
        if (!signal.aborted) {
          setAuditEvents(auditData.items || []);
          setAuditAccessDenied(false);
          setAuditError(null);
        }
      } catch (auditErr: unknown) {
        if (signal.aborted) return;
        if (auditErr instanceof ApiClientError && auditErr.status === 403) {
          setAuditAccessDenied(true);
          setAuditError('Audit log access requires Security Administrator or Platform Owner privileges.');
        } else if (auditErr instanceof ApiClientError && auditErr.code === 'REQUEST_ABORTED') {
          return;
        } else {
          setAuditError(auditErr instanceof Error ? auditErr.message : 'Failed to retrieve audit events.');
        }
      }
    } catch (err: unknown) {
      if (signal.aborted) return;
      if (err instanceof ApiClientError && err.code === 'REQUEST_ABORTED') return;
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to load organization details.');
      }
    } finally {
      if (!signal.aborted) {
        setIsLoading(false);
      }
    }
  }, [orgId]);

  useEffect(() => {
    loadData(false);
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [loadData]);

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(true);
    setTimeout(() => setCopiedId(false), 2000);
  };

  const handleEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setEditError(null);
    setIsSubmittingEdit(true);
    try {
      const updated = await api.updateAdminOrganization(orgId, {
        name: editName.trim(),
        slug: editSlug.trim(),
      });
      setOrg(updated);
      setIsEditModalOpen(false);
      setSuccessMessage('Organization details updated successfully.');
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setEditError(err.message);
      } else {
        setEditError('Failed to update organization.');
      }
    } finally {
      setIsSubmittingEdit(false);
    }
  };

  const handleStatusSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setStatusError(null);
    const trimmed = statusReason.trim();
    if (!trimmed && targetStatus !== 'active') {
      setStatusError('A justification reason is required for status changes.');
      return;
    }

    setIsSubmittingStatus(true);
    try {
      const updated = await api.updateAdminOrganizationStatus(orgId, {
        status: targetStatus,
        reason: trimmed || undefined,
      });
      setOrg(updated);
      setIsStatusModalOpen(false);
      setStatusReason('');
      setSuccessMessage(`Organization status changed to "${targetStatus}".`);
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setStatusError(err.message);
      } else {
        setStatusError('Failed to change status.');
      }
    } finally {
      setIsSubmittingStatus(false);
    }
  };

  const handleTransferSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setTransferError(null);
    if (!newOwnerUserId) {
      setTransferError('Please select or specify an eligible member user ID.');
      return;
    }

    setIsSubmittingTransfer(true);
    try {
      const updated = await api.transferAdminOrganizationOwnership(orgId, {
        new_owner_user_id: newOwnerUserId.trim(),
        reason: transferReason.trim() || undefined,
      });
      setOrg(updated);
      setIsTransferModalOpen(false);
      setNewOwnerUserId('');
      setTransferReason('');
      setSuccessMessage('Organization ownership transferred successfully.');
      setTimeout(() => setSuccessMessage(null), 3000);
      await loadData(true);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setTransferError(err.message);
      } else {
        setTransferError('Failed to transfer ownership.');
      }
    } finally {
      setIsSubmittingTransfer(false);
    }
  };

  const handleAddMemberSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setMemberError(null);
    setIsSubmittingMember(true);
    try {
      await api.addAdminOrganizationMember(orgId, {
        email: newMemberEmail.trim(),
        role: newMemberRole,
        full_name: newMemberFullName.trim() || undefined,
        password: newMemberPassword.trim() || undefined,
      });
      setIsAddMemberModalOpen(false);
      setNewMemberEmail('');
      setNewMemberFullName('');
      setNewMemberPassword('');
      setNewMemberRole('organizer');
      setSuccessMessage('Member/Organizer credentials provisioned and added successfully.');
      setTimeout(() => setSuccessMessage(null), 4000);
      const membersData = await api.getAdminOrganizationMembers(orgId);
      setMembers(membersData);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setMemberError(err.message);
      } else {
        setMemberError('Failed to add member.');
      }
    } finally {
      setIsSubmittingMember(false);
    }
  };

  const handleRoleChange = async (userId: string, newRole: OrgRole) => {
    try {
      await api.updateAdminOrganizationMemberRole(orgId, userId, { role: newRole });
      setSuccessMessage('Member role updated successfully.');
      setTimeout(() => setSuccessMessage(null), 3000);
      const membersData = await api.getAdminOrganizationMembers(orgId);
      setMembers(membersData);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to update member role.');
      }
    }
  };

  const handleRemoveMember = async () => {
    if (!memberToRemove) return;
    setIsRemovingMember(true);
    try {
      await api.removeAdminOrganizationMember(orgId, memberToRemove.user_id);
      setMemberToRemove(null);
      setSuccessMessage('Member removed from organization.');
      setTimeout(() => setSuccessMessage(null), 3000);
      const membersData = await api.getAdminOrganizationMembers(orgId);
      setMembers(membersData);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to remove member.');
      }
    } finally {
      setIsRemovingMember(false);
    }
  };

  const formatRole = (role: OrgRole) => {
    switch (role) {
      case 'org_owner':
        return 'Organization Owner';
      case 'org_admin':
        return 'Organization Admin';
      case 'organizer':
        return 'Event Organizer';
      default:
        return role;
    }
  };

  const isStale = Boolean(org && org.id !== orgId);

  if (error && !org) {
    return (
      <div className="p-8 bg-surface rounded-2xl border border-surface-border text-center">
        <AlertCircle className="w-10 h-10 text-status-error mx-auto mb-3" />
        <h2 className="text-base font-semibold text-text-primary">Failed to load organization</h2>
        <p className="text-xs text-text-muted mt-1 mb-4">{error}</p>
        <Link
          href="/admin/organizations"
          className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-text-primary bg-surface-elevated hover:bg-surface-hover rounded-lg transition-colors border border-surface-border"
        >
          <ChevronLeft className="w-4 h-4" />
          <span>Back to Organizations</span>
        </Link>
      </div>
    );
  }

  if (isLoading || !org || isStale) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-4 bg-surface-elevated rounded w-48" />
        <div className="h-20 bg-surface rounded-2xl border border-surface-border p-6" />
        <div className="h-64 bg-surface rounded-2xl border border-surface-border p-6" />
      </div>
    );
  }

  if (!org) return null;

  return (
    <div className="space-y-6">
      {/* Top Breadcrumb & Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <Link
          href="/admin/organizations"
          className="inline-flex items-center gap-2 text-xs text-text-muted hover:text-text-primary transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
          <span>Back to Organizations Directory</span>
        </Link>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => loadData(true)}
            disabled={isLoading}
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
          <button
            type="button"
            onClick={() => {
              setEditName(org.name);
              setEditSlug(org.slug);
              setEditError(null);
              setIsEditModalOpen(true);
            }}
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors"
          >
            <Edit className="w-3.5 h-3.5" />
            <span>Edit Profile</span>
          </button>
          <button
            type="button"
            onClick={() => {
              setTargetStatus(org.status);
              setStatusReason('');
              setStatusError(null);
              setIsStatusModalOpen(true);
            }}
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors"
          >
            <ShieldAlert className="w-3.5 h-3.5 text-status-warning" />
            <span>Change Status</span>
          </button>
        </div>
      </div>

      {/* Notification Banners */}
      {successMessage && (
        <div className="flex items-center gap-3 p-4 bg-status-success/10 border border-status-success/30 rounded-xl text-status-success text-sm animate-in fade-in">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{successMessage}</span>
        </div>
      )}

      {error && (
        <div className="flex items-center justify-between p-4 bg-status-error/10 border border-status-error/30 rounded-xl text-status-error text-sm">
          <div className="flex items-center gap-3">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)} className="text-xs font-bold">
            Dismiss
          </button>
        </div>
      )}

      {/* Organization Header Card */}
      <div className="bg-surface rounded-2xl border border-surface-border p-6 shadow-sm">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-start gap-4">
            <div className="w-14 h-14 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary shrink-0 shadow-inner">
              <Building2 className="w-7 h-7" />
            </div>
            <div>
              <div className="flex items-center gap-3 flex-wrap">
                <h1 className="text-xl font-bold text-text-primary tracking-tight">{org.name}</h1>
                <StatusBadge status={org.status} size="sm" />
              </div>
              <div className="flex items-center gap-3 text-xs text-text-muted mt-1 flex-wrap">
                <span className="font-mono bg-surface-elevated px-2 py-0.5 rounded border border-surface-border text-text-secondary">
                  /{org.slug}
                </span>
                <span className="flex items-center gap-1 font-mono">
                  ID: {org.id.slice(0, 8)}...
                  <button
                    onClick={() => copyToClipboard(org.id)}
                    className="p-1 hover:text-text-primary transition-colors"
                    title="Copy UUID"
                  >
                    {copiedId ? <Check className="w-3 h-3 text-status-success" /> : <Copy className="w-3 h-3" />}
                  </button>
                </span>
                <span className="flex items-center gap-1">
                  <Calendar className="w-3 h-3" />
                  Created: {new Date(org.created_at).toLocaleDateString()}
                </span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-6 border-t md:border-t-0 md:border-l border-surface-border pt-4 md:pt-0 md:pl-6">
            <div className="text-center">
              <div className="text-2xl font-bold text-text-primary font-mono">{members.length || org.member_count}</div>
              <div className="text-[11px] text-text-muted uppercase tracking-wider font-semibold">Members</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-text-primary font-mono">{hackathons.length || org.hackathon_count}</div>
              <div className="text-[11px] text-text-muted uppercase tracking-wider font-semibold">Hackathons</div>
            </div>
          </div>
        </div>
      </div>

      {/* Tabs Bar */}
      <div className="flex items-center gap-2 border-b border-surface-border">
        <button
          onClick={() => setTab('overview')}
          className={`flex items-center gap-2 px-4 py-2.5 text-xs font-semibold transition-all border-b-2 -mb-px ${
            currentTab === 'overview'
              ? 'border-primary text-primary'
              : 'border-transparent text-text-muted hover:text-text-primary'
          }`}
        >
          <FileText className="w-4 h-4" />
          <span>Overview</span>
        </button>

        <button
          onClick={() => setTab('members')}
          className={`flex items-center gap-2 px-4 py-2.5 text-xs font-semibold transition-all border-b-2 -mb-px ${
            currentTab === 'members'
              ? 'border-primary text-primary'
              : 'border-transparent text-text-muted hover:text-text-primary'
          }`}
        >
          <Users className="w-4 h-4" />
          <span>Members Roster ({members.length})</span>
        </button>

        <button
          onClick={() => setTab('hackathons')}
          className={`flex items-center gap-2 px-4 py-2.5 text-xs font-semibold transition-all border-b-2 -mb-px ${
            currentTab === 'hackathons'
              ? 'border-primary text-primary'
              : 'border-transparent text-text-muted hover:text-text-primary'
          }`}
        >
          <Trophy className="w-4 h-4" />
          <span>Hackathons ({hackathons.length})</span>
        </button>

        <button
          onClick={() => setTab('audit')}
          className={`flex items-center gap-2 px-4 py-2.5 text-xs font-semibold transition-all border-b-2 -mb-px ${
            currentTab === 'audit'
              ? 'border-primary text-primary'
              : 'border-transparent text-text-muted hover:text-text-primary'
          }`}
        >
          <History className="w-4 h-4" />
          <span>Tenant Audit Activity</span>
        </button>
      </div>

      {/* TAB CONTENT: Overview */}
      {currentTab === 'overview' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Owner Details Card */}
          <div className="bg-surface rounded-xl border border-surface-border p-5 space-y-4">
            <div className="flex items-center justify-between border-b border-surface-border pb-3">
              <div className="flex items-center gap-2">
                <Shield className="w-4 h-4 text-primary" />
                <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider">
                  Organization Owner
                </h3>
              </div>
              <button
                type="button"
                onClick={() => {
                  setNewOwnerUserId('');
                  setTransferReason('');
                  setTransferError(null);
                  setIsTransferModalOpen(true);
                }}
                className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors"
              >
                <ArrowRightLeft className="w-3.5 h-3.5 text-primary" />
                <span>Transfer Ownership</span>
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <span className="text-text-muted block text-[11px]">Owner Name</span>
                <span className="font-semibold text-text-primary text-sm">
                  {org.owner?.full_name || org.owner_name || 'System Owner'}
                </span>
              </div>
              <div>
                <span className="text-text-muted block text-[11px]">Owner Email</span>
                <span className="text-text-secondary font-mono">
                  {org.owner?.email || org.owner_email || '—'}
                </span>
              </div>
              <div>
                <span className="text-text-muted block text-[11px]">Owner User ID</span>
                <span className="text-text-muted font-mono text-[11px] break-all">
                  {org.owner_id}
                </span>
              </div>
            </div>
          </div>

          {/* Tenant Settings JSON */}
          <div className="bg-surface rounded-xl border border-surface-border p-5 space-y-4">
            <div className="flex items-center justify-between border-b border-surface-border pb-3">
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4 text-primary" />
                <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider">
                  Tenant Configuration & Settings
                </h3>
              </div>
              <span className="text-[10px] text-text-muted font-mono">JSONB</span>
            </div>

            <pre className="p-3 bg-surface-elevated rounded-lg border border-surface-border text-xs text-text-secondary font-mono overflow-x-auto max-h-48">
              {JSON.stringify(org.settings || {}, null, 2)}
            </pre>
          </div>
        </div>
      )}

      {/* TAB CONTENT: Members Roster */}
      {currentTab === 'members' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-text-primary">Member Roster</h3>
              <p className="text-xs text-text-muted">
                Authorized user memberships and tenant-scoped role assignments.
              </p>
            </div>
            <button
              type="button"
              onClick={() => {
                setNewMemberEmail('');
                setNewMemberRole('organizer');
                setMemberError(null);
                setIsAddMemberModalOpen(true);
              }}
              className="flex items-center gap-2 px-3 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover rounded-lg transition-colors shadow-sm"
            >
              <UserPlus className="w-3.5 h-3.5" />
              <span>Add Member</span>
            </button>
          </div>

          <div className="bg-surface rounded-xl border border-surface-border overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-surface-border bg-surface-elevated/50 text-text-muted uppercase text-[10px] tracking-wider font-semibold">
                    <th className="py-3 px-4">Member</th>
                    <th className="py-3 px-4">Role</th>
                    <th className="py-3 px-4">Status</th>
                    <th className="py-3 px-4">Joined At</th>
                    <th className="py-3 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-border text-text-secondary">
                  {members.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="py-8 text-center text-text-muted">
                        No members currently enrolled in this organization.
                      </td>
                    </tr>
                  ) : (
                    members.map((member) => {
                      const isOwner = member.role === 'org_owner';
                      return (
                        <tr key={member.id} className="hover:bg-surface-hover/50 transition-colors">
                          <td className="py-3.5 px-4">
                            <div className="font-semibold text-text-primary">
                              {member.user?.full_name || member.full_name || 'Member'}
                            </div>
                            <div className="text-[11px] text-text-muted font-mono mt-0.5">
                              {member.user?.email || member.email || member.user_id}
                            </div>
                          </td>
                          <td className="py-3.5 px-4">
                            <select
                              value={member.role}
                              disabled={isOwner}
                              onChange={(e) => handleRoleChange(member.user_id, e.target.value as OrgRole)}
                              className="px-2.5 py-1 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary disabled:opacity-60"
                            >
                              <option value="org_owner" disabled={!isOwner}>
                                Owner
                              </option>
                              <option value="org_admin">Admin</option>
                              <option value="organizer">Organizer</option>
                            </select>
                          </td>
                          <td className="py-3.5 px-4">
                            <StatusBadge status={member.status} size="sm" />
                          </td>
                          <td className="py-3.5 px-4 text-text-muted">
                            {new Date(member.created_at).toLocaleDateString()}
                          </td>
                          <td className="py-3.5 px-4 text-right">
                            {!isOwner && (
                              <button
                                type="button"
                                onClick={() => setMemberToRemove(member)}
                                className="p-1.5 rounded-lg text-status-error hover:bg-status-error/10 transition-colors"
                                title="Remove member"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* TAB CONTENT: Hackathons */}
      {currentTab === 'hackathons' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-text-primary">Hosted Hackathons</h3>
              <p className="text-xs text-text-muted">
                Hackathon events organized under this tenant boundary.
              </p>
            </div>
          </div>

          <div className="bg-surface rounded-xl border border-surface-border overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-surface-border bg-surface-elevated/50 text-text-muted uppercase text-[10px] tracking-wider font-semibold">
                    <th className="py-3 px-4">Hackathon</th>
                    <th className="py-3 px-4">Status</th>
                    <th className="py-3 px-4">Event Window</th>
                    <th className="py-3 px-4">Submission Cutoff</th>
                    <th className="py-3 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-border text-text-secondary">
                  {hackathons.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="py-8 text-center text-text-muted">
                        No hackathons hosted yet by this organization.
                      </td>
                    </tr>
                  ) : (
                    hackathons.map((h) => (
                      <tr key={h.id} className="hover:bg-surface-hover/50 transition-colors">
                        <td className="py-3.5 px-4">
                          <Link
                            href={`/admin/hackathons/${h.id}`}
                            className="font-semibold text-text-primary hover:text-primary transition-colors"
                          >
                            {h.title}
                          </Link>
                          <div className="text-[11px] text-text-muted font-mono mt-0.5">
                            /{h.slug}
                          </div>
                        </td>
                        <td className="py-3.5 px-4">
                          <StatusBadge status={h.status} size="sm" />
                        </td>
                        <td className="py-3.5 px-4 text-text-muted whitespace-nowrap">
                          {new Date(h.start_date).toLocaleDateString()} — {new Date(h.end_date).toLocaleDateString()}
                        </td>
                        <td className="py-3.5 px-4 text-text-muted whitespace-nowrap">
                          {new Date(h.submission_deadline).toLocaleString()}
                        </td>
                        <td className="py-3.5 px-4 text-right">
                          <Link
                            href={`/admin/hackathons/${h.id}`}
                            className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors"
                          >
                            <span>Inspect</span>
                            <ExternalLink className="w-3 h-3" />
                          </Link>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* TAB CONTENT: Audit Activity */}
      {currentTab === 'audit' && (
        <div className="space-y-4">
          <div>
            <h3 className="text-sm font-semibold text-text-primary">Tenant Audit Trail</h3>
            <p className="text-xs text-text-muted">
              Immutable PostgreSQL audit events specifically tagged with this organization ID.
            </p>
          </div>

          {auditAccessDenied ? (
            <div className="p-8 bg-surface rounded-2xl border border-surface-border text-center">
              <ShieldAlert className="w-8 h-8 text-status-warning mx-auto mb-2" />
              <h4 className="text-sm font-semibold text-text-primary">Audit Log Access Restricted</h4>
              <p className="text-xs text-text-muted max-w-md mx-auto mt-1">
                Viewing organization audit event records requires Security Administrator or Platform Owner privileges.
              </p>
            </div>
          ) : auditError ? (
            <div className="p-4 bg-status-error/10 border border-status-error/20 rounded-xl text-status-error text-xs flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>Failed to load audit events: {auditError}</span>
            </div>
          ) : (
            <div className="bg-surface rounded-xl border border-surface-border overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-surface-border bg-surface-elevated/50 text-text-muted uppercase text-[10px] tracking-wider font-semibold">
                      <th className="py-3 px-4">Timestamp</th>
                      <th className="py-3 px-4">Actor</th>
                      <th className="py-3 px-4">Action</th>
                      <th className="py-3 px-4">Resource</th>
                      <th className="py-3 px-4">Outcome</th>
                      <th className="py-3 px-4">Reason / Notes</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-border text-text-secondary">
                    {auditEvents.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="py-8 text-center text-text-muted">
                          No audit events recorded for this organization yet.
                        </td>
                      </tr>
                    ) : (
                      auditEvents.map((evt) => (
                        <tr key={evt.id} className="hover:bg-surface-hover/50 transition-colors">
                          <td className="py-3.5 px-4 text-text-muted whitespace-nowrap font-mono text-[11px]">
                            {new Date(evt.timestamp).toLocaleString()}
                          </td>
                          <td className="py-3.5 px-4">
                            <div className="font-medium text-text-primary">{evt.actor_email}</div>
                            <div className="text-[10px] text-text-muted">{evt.actor_role}</div>
                          </td>
                          <td className="py-3.5 px-4 font-mono font-medium text-text-primary">
                            {evt.action}
                          </td>
                          <td className="py-3.5 px-4">
                            <span className="font-mono text-[11px] text-text-muted">
                              {evt.resource_type}:{evt.resource_id.slice(0, 8)}...
                            </span>
                          </td>
                          <td className="py-3.5 px-4">
                            <span
                              className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                                evt.outcome === 'SUCCESS'
                                  ? 'bg-status-success/10 text-status-success border border-status-success/20'
                                  : 'bg-status-error/10 text-status-error border border-status-error/20'
                              }`}
                            >
                              {evt.outcome}
                            </span>
                          </td>
                          <td className="py-3.5 px-4 text-text-muted max-w-xs truncate">
                            {evt.reason || '—'}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Modal: Edit Organization */}
      {isEditModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="bg-surface border border-surface-border rounded-2xl w-full max-w-md shadow-surface-elevated overflow-hidden">
            <div className="p-5 border-b border-surface-border flex items-center justify-between">
              <h3 className="text-sm font-semibold text-text-primary">Edit Organization</h3>
              <button
                type="button"
                onClick={() => setIsEditModalOpen(false)}
                className="p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-surface-elevated transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleEditSubmit} className="p-5 space-y-4">
              {editError && (
                <div className="p-3 bg-status-error/10 border border-status-error/30 rounded-lg text-status-error text-xs flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{editError}</span>
                </div>
              )}

              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1">
                  Organization Name
                </label>
                <input
                  type="text"
                  required
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1">
                  Organization Slug
                </label>
                <input
                  type="text"
                  required
                  pattern="^[a-z0-9]+(?:-[a-z0-9]+)*$"
                  value={editSlug}
                  onChange={(e) => setEditSlug(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary font-mono"
                />
              </div>

              <div className="pt-2 flex items-center justify-end gap-2.5 border-t border-surface-border">
                <button
                  type="button"
                  onClick={() => setIsEditModalOpen(false)}
                  className="px-3 py-2 text-xs font-medium text-text-muted hover:text-text-primary hover:bg-surface-elevated rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingEdit || !editName.trim() || !editSlug.trim()}
                  className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg transition-colors shadow-sm"
                >
                  {isSubmittingEdit ? 'Saving...' : 'Save Changes'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Transfer Ownership */}
      {isTransferModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="bg-surface border border-surface-border rounded-2xl w-full max-w-md shadow-surface-elevated overflow-hidden">
            <div className="p-5 border-b border-surface-border flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-status-error/10 flex items-center justify-center text-status-error">
                  <ArrowRightLeft className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-text-primary">Transfer Ownership</h3>
                  <p className="text-[11px] text-text-muted">Reassign primary ownership of this tenant</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setIsTransferModalOpen(false)}
                className="p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-surface-elevated transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleTransferSubmit} className="p-5 space-y-4">
              {transferError && (
                <div className="p-3 bg-status-error/10 border border-status-error/30 rounded-lg text-status-error text-xs flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{transferError}</span>
                </div>
              )}

              <div className="p-3 bg-status-warning/10 border border-status-warning/30 rounded-lg text-[11px] text-status-warning">
                <strong>Important:</strong> The recipient must be an active registered user with an active membership in this organization. The current owner will be demoted to Admin.
              </div>

              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1">
                  Select Destination Member <span className="text-status-error">*</span>
                </label>
                <select
                  value={newOwnerUserId}
                  onChange={(e) => setNewOwnerUserId(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                  required
                >
                  <option value="">-- Choose active member --</option>
                  {members
                    .filter((m) => m.role !== 'org_owner')
                    .map((m) => (
                      <option key={m.user_id} value={m.user_id}>
                        {m.user?.full_name || m.full_name || 'Member'} ({m.user?.email || m.email || m.user_id}) - {m.role}
                      </option>
                    ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1">
                  Transfer Justification / Reason
                </label>
                <textarea
                  rows={2}
                  maxLength={500}
                  placeholder="Operational justification for ownership re-assignment..."
                  value={transferReason}
                  onChange={(e) => setTransferReason(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary placeholder-text-muted"
                />
              </div>

              <div className="pt-2 flex items-center justify-end gap-2.5 border-t border-surface-border">
                <button
                  type="button"
                  onClick={() => setIsTransferModalOpen(false)}
                  className="px-3 py-2 text-xs font-medium text-text-muted hover:text-text-primary hover:bg-surface-elevated rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingTransfer || !newOwnerUserId}
                  className="px-4 py-2 text-xs font-semibold text-white bg-status-error hover:bg-status-error/90 disabled:opacity-50 rounded-lg transition-colors shadow-sm"
                >
                  {isSubmittingTransfer ? 'Transferring...' : 'Execute Ownership Transfer'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Add Member */}
      {isAddMemberModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="bg-surface border border-surface-border rounded-2xl w-full max-w-md shadow-surface-elevated overflow-hidden">
            <div className="p-5 border-b border-surface-border flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
                  <UserPlus className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-text-primary">Add Organization Member</h3>
                  <p className="text-[11px] text-text-muted">Enroll user into {org.name}</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setIsAddMemberModalOpen(false)}
                className="p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-surface-elevated transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleAddMemberSubmit} className="p-5 space-y-4">
              {memberError && (
                <div className="p-3 bg-status-error/10 border border-status-error/30 rounded-lg text-status-error text-xs flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{memberError}</span>
                </div>
              )}

              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1">
                  Full Name (Optional for existing user)
                </label>
                <input
                  type="text"
                  placeholder="e.g. John Doe"
                  value={newMemberFullName}
                  onChange={(e) => setNewMemberFullName(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1">
                  User Email Address <span className="text-status-error">*</span>
                </label>
                <input
                  type="email"
                  required
                  placeholder="organizer@example.com"
                  value={newMemberEmail}
                  onChange={(e) => setNewMemberEmail(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="block text-xs font-medium text-text-secondary">
                    Login Password Credentials
                  </label>
                  <button
                    type="button"
                    onClick={() => {
                      const chars = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%';
                      let res = '';
                      for (let i = 0; i < 12; i++) {
                        res += chars.charAt(Math.floor(Math.random() * chars.length));
                      }
                      setNewMemberPassword(res);
                    }}
                    className="text-[10px] text-primary hover:text-primary-hover flex items-center gap-1 font-medium transition-colors"
                  >
                    <Sparkles className="w-3 h-3" />
                    <span>Generate</span>
                  </button>
                </div>
                <div className="relative">
                  <input
                    type={showMemberPassword ? 'text' : 'password'}
                    placeholder="Leave blank to default to OrganizerPass123!"
                    value={newMemberPassword}
                    onChange={(e) => setNewMemberPassword(e.target.value)}
                    className="w-full pl-3 pr-8 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary font-mono"
                  />
                  <button
                    type="button"
                    onClick={() => setShowMemberPassword(!showMemberPassword)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary transition-colors"
                  >
                    {showMemberPassword ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                  </button>
                </div>
                <p className="text-[10px] text-text-muted mt-1">
                  Organizers do not need to register. They can log in immediately with this email and password.
                </p>
              </div>

              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1">
                  Initial Role
                </label>
                <select
                  value={newMemberRole}
                  onChange={(e) => setNewMemberRole(e.target.value as OrgRole)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                >
                  <option value="organizer">Organizer (Manage Hackathons)</option>
                  <option value="org_admin">Admin (Manage Members & Settings)</option>
                </select>
              </div>

              <div className="pt-2 flex items-center justify-end gap-2.5 border-t border-surface-border">
                <button
                  type="button"
                  onClick={() => setIsAddMemberModalOpen(false)}
                  className="px-3 py-2 text-xs font-medium text-text-muted hover:text-text-primary hover:bg-surface-elevated rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingMember || !newMemberEmail.trim()}
                  className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg transition-colors shadow-sm"
                >
                  {isSubmittingMember ? 'Adding...' : 'Add Member'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Change Status */}
      {isStatusModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="bg-surface border border-surface-border rounded-2xl w-full max-w-md shadow-surface-elevated overflow-hidden">
            <div className="p-5 border-b border-surface-border flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-status-warning/10 flex items-center justify-center text-status-warning">
                  <ShieldAlert className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-text-primary">Update Organization Status</h3>
                  <p className="text-[11px] text-text-muted">Target: {org.name}</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setIsStatusModalOpen(false)}
                className="p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-surface-elevated transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleStatusSubmit} className="p-5 space-y-4">
              {statusError && (
                <div className="p-3 bg-status-error/10 border border-status-error/30 rounded-lg text-status-error text-xs flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{statusError}</span>
                </div>
              )}

              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1">
                  Target Status
                </label>
                <select
                  value={targetStatus}
                  onChange={(e) => setTargetStatus(e.target.value as OrganizationStatus)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                >
                  <option value="active">Active (Normal Operations)</option>
                  <option value="suspended">Suspended (Tenant Blocked)</option>
                  <option value="archived">Archived (Read-Only Cold Storage)</option>
                </select>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="block text-xs font-medium text-text-secondary">
                    Operational Reason {targetStatus !== 'active' && <span className="text-status-error">*</span>}
                  </label>
                  <span className="text-[10px] text-text-muted">{statusReason.length}/500</span>
                </div>
                <textarea
                  rows={3}
                  maxLength={500}
                  required={targetStatus !== 'active'}
                  placeholder="Mandatory justification reason..."
                  value={statusReason}
                  onChange={(e) => setStatusReason(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary placeholder-text-muted"
                />
              </div>

              <div className="pt-2 flex items-center justify-end gap-2.5 border-t border-surface-border">
                <button
                  type="button"
                  onClick={() => setIsStatusModalOpen(false)}
                  className="px-3 py-2 text-xs font-medium text-text-muted hover:text-text-primary hover:bg-surface-elevated rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingStatus || (targetStatus !== 'active' && !statusReason.trim())}
                  className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg transition-colors shadow-sm"
                >
                  {isSubmittingStatus ? 'Updating...' : 'Confirm Status Change'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Confirmation Modal: Remove Member */}
      {memberToRemove && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="bg-surface border border-surface-border rounded-2xl w-full max-w-sm shadow-surface-elevated p-5 space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-status-error/10 flex items-center justify-center text-status-error shrink-0">
                <Trash2 className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-text-primary">Remove Member</h3>
                <p className="text-xs text-text-muted">Revoke access from this organization</p>
              </div>
            </div>

            <p className="text-xs text-text-secondary leading-relaxed">
              Are you sure you want to remove{' '}
              <strong className="text-text-primary">
                {memberToRemove.user?.full_name || memberToRemove.email || memberToRemove.user_id}
              </strong>{' '}
              from {org.name}? They will immediately lose tenant access.
            </p>

            <div className="pt-2 flex items-center justify-end gap-2.5 border-t border-surface-border">
              <button
                type="button"
                onClick={() => setMemberToRemove(null)}
                className="px-3 py-2 text-xs font-medium text-text-muted hover:text-text-primary hover:bg-surface-elevated rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleRemoveMember}
                disabled={isRemovingMember}
                className="px-4 py-2 text-xs font-semibold text-white bg-status-error hover:bg-status-error/90 disabled:opacity-50 rounded-lg transition-colors shadow-sm"
              >
                {isRemovingMember ? 'Removing...' : 'Confirm Remove'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
