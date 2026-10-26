'use client';

import React, { useState, useEffect, use } from 'react';
import Link from 'next/link';
import {
  Building2,
  Trophy,
  Shield,
  Calendar,
  Clock,
  ArrowRight,
  CheckCircle2,
  AlertCircle,
  Edit,
  Save,
  Users,
} from 'lucide-react';
import { StatusBadge } from '@/components/admin/StatusBadge';
import { api, ApiClientError } from '@/lib/api-client';
import { OrganizationProfileResponse } from '@/types/api';

export default function TenantOrganizationProfilePage({
  params,
}: {
  params: Promise<{ organizationId: string }>;
}) {
  const unwrappedParams = use(params);
  const orgId = unwrappedParams.organizationId;

  const [prevOrgId, setPrevOrgId] = useState<string>(orgId);
  const [org, setOrg] = useState<OrganizationProfileResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Edit Name
  const [isEditing, setIsEditing] = useState<boolean>(false);
  const [newName, setNewName] = useState<string>('');
  const [isSaving, setIsSaving] = useState<boolean>(false);

  // Synchronous render-phase state adjustment: eliminates 1-frame stale data paint on navigation
  if (orgId !== prevOrgId) {
    setPrevOrgId(orgId);
    setOrg(null);
    setNewName('');
    setIsLoading(true);
    setError(null);
  }

  useEffect(() => {
    const controller = new AbortController();
    // Immediately reset organization profile state
    setOrg(null);
    setNewName('');
    setIsLoading(true);
    setError(null);

    async function loadData() {
      try {
        const data = await api.getTenantOrganizationProfile(orgId, { signal: controller.signal });
        if (!controller.signal.aborted) {
          setOrg(data);
          setNewName(data.name);
        }
      } catch (err: unknown) {
        if (controller.signal.aborted) return;
        if (err instanceof ApiClientError && err.code === 'REQUEST_ABORTED') return;
        if (err instanceof ApiClientError) {
          setError(err.message);
        } else {
          setError('Failed to load profile.');
        }
      } finally {
        if (!controller.signal.aborted) {
          setIsLoading(false);
        }
      }
    }
    loadData();
    return () => {
      controller.abort();
    };
  }, [orgId]);

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim() || newName.trim() === org?.name) {
      setIsEditing(false);
      return;
    }

    setIsSaving(true);
    try {
      const updated = await api.updateTenantOrganizationProfile(orgId, {
        name: newName.trim(),
      });
      setOrg(updated);
      setIsEditing(false);
      setSuccessMessage('Organization profile updated.');
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to update organization profile.');
      }
    } finally {
      setIsSaving(false);
    }
  };

  const formatRole = (role?: string) => {
    if (!role) return 'Member';
    return role
      .split('_')
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
      .join(' ');
  };

  const isStale = Boolean(org && org.id !== orgId);

  if (error && !org) {
    return (
      <div className="p-8 bg-surface rounded-2xl border border-surface-border text-center">
        <AlertCircle className="w-10 h-10 text-status-error mx-auto mb-3" />
        <h2 className="text-base font-semibold text-text-primary">Failed to load organization profile</h2>
        <p className="text-xs text-text-muted mt-1">{error}</p>
      </div>
    );
  }

  if (isLoading || !org || isStale) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="h-6 bg-surface-elevated rounded w-48" />
        <div className="h-40 bg-surface rounded-2xl border border-surface-border p-6" />
      </div>
    );
  }

  if (!org) return null;

  const canEdit = org.current_user_role === 'org_owner' || org.current_user_role === 'org_admin';

  return (
    <div className="space-y-6">
      {/* Notifications */}
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

      {/* Header Banner */}
      <div className="bg-surface rounded-2xl border border-surface-border p-6 shadow-sm">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div className="flex items-start gap-4">
            <div className="w-14 h-14 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary shrink-0 shadow-inner">
              <Building2 className="w-7 h-7" />
            </div>
            <div>
              <div className="flex items-center gap-3 flex-wrap">
                {isEditing ? (
                  <form onSubmit={handleSaveProfile} className="flex items-center gap-2">
                    <input
                      type="text"
                      required
                      value={newName}
                      onChange={(e) => setNewName(e.target.value)}
                      className="px-2.5 py-1 text-base font-bold bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                    />
                    <button
                      type="submit"
                      disabled={isSaving}
                      className="p-1.5 rounded-lg bg-primary text-white hover:bg-primary-hover disabled:opacity-50"
                      title="Save"
                    >
                      <Save className="w-4 h-4" />
                    </button>
                  </form>
                ) : (
                  <h1 className="text-xl font-bold text-text-primary tracking-tight">
                    {org.name}
                  </h1>
                )}
                <StatusBadge status={org.status} size="sm" />
                <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-primary/10 text-primary border border-primary/20">
                  Your Role: {formatRole(org.current_user_role)}
                </span>
              </div>
              <div className="flex items-center gap-3 text-xs text-text-muted mt-1 flex-wrap">
                <span className="font-mono bg-surface-elevated px-2 py-0.5 rounded border border-surface-border text-text-secondary">
                  /{org.slug}
                </span>
                <span className="flex items-center gap-1">
                  <Calendar className="w-3 h-3" />
                  Tenant Established: {new Date(org.created_at).toLocaleDateString()}
                </span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {canEdit && !isEditing && (
              <button
                type="button"
                onClick={() => setIsEditing(true)}
                className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors"
              >
                <Edit className="w-3.5 h-3.5" />
                <span>Rename Organization</span>
              </button>
            )}
            <Link
              href={`/organizations/${orgId}/hackathons`}
              className="flex items-center gap-2 px-3.5 py-1.5 text-xs font-semibold text-white bg-primary hover:bg-primary-hover rounded-lg transition-colors shadow-sm"
            >
              <Trophy className="w-3.5 h-3.5" />
              <span>Go to Hackathons</span>
            </Link>
          </div>
        </div>
      </div>

      {/* Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-surface rounded-xl border border-surface-border p-5 space-y-4">
          <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider border-b border-surface-border pb-3">
            Tenant Boundary Status
          </h3>
          <div className="space-y-3 text-xs">
            <div>
              <span className="text-text-muted block text-[11px]">Organization ID</span>
              <span className="font-mono text-text-secondary">{org.id}</span>
            </div>
            <div>
              <span className="text-text-muted block text-[11px]">Lifecycle Status</span>
              <span className="text-text-secondary capitalize">{org.status}</span>
            </div>
            <div>
              <span className="text-text-muted block text-[11px]">Current Access Level</span>
              <span className="text-text-secondary">
                You are authenticated as <strong>{formatRole(org.current_user_role)}</strong>.
              </span>
            </div>
          </div>
        </div>

        <div className="bg-surface rounded-xl border border-surface-border p-5 space-y-4">
          <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider border-b border-surface-border pb-3">
            Custom Settings JSON
          </h3>
          <pre className="p-3 bg-surface-elevated rounded-lg border border-surface-border text-xs text-text-secondary font-mono overflow-x-auto max-h-40">
            {JSON.stringify(org.settings || {}, null, 2)}
          </pre>
        </div>
      </div>
    </div>
  );
}
