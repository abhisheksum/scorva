'use client';

import React, { useState, useEffect, useMemo } from 'react';
import Link from 'next/link';
import {
  Megaphone,
  Plus,
  Send,
  Users,
  Search,
  Filter,
  CheckCircle2,
  Clock,
  Layout,
  Check,
  X,
  AlertCircle,
  Eye,
  Trash2,
  ArrowRight,
  Shield,
  Layers,
  Sparkles,
  Calendar,
  UserCheck,
} from 'lucide-react';
import { PageHeader } from '@/components/admin/PageHeader';
import { StatusBadge } from '@/components/admin/StatusBadge';
import { api, ApiClientError } from '@/lib/api-client';
import { UserProfile } from '@/types/api';

export type AudienceRole = 'all' | 'organizers' | 'judges' | 'participants';
export type AnnouncementPlacement = 'all' | 'home' | 'header' | 'announcements';
export type AnnouncementPriority = 'normal' | 'important' | 'urgent';

export interface AdminAnnouncement {
  id: string;
  title: string;
  content: string;
  targetRole: AudienceRole;
  placement: AnnouncementPlacement;
  priority: AnnouncementPriority;
  recipientIds: string[]; // Specific user IDs if not broadcasting to all in role
  recipientCount: number;
  authorName: string;
  createdAt: string;
  status: 'active' | 'scheduled' | 'archived';
  actionUrl?: string;
}

const STORAGE_KEY = 'scorva_admin_announcements_v1';

// Seed default platform announcements if none exist
const DEFAULT_ANNOUNCEMENTS: AdminAnnouncement[] = [
  {
    id: 'ann_welcome_001',
    title: 'Platform Maintenance Scheduled for Sunday 02:00 UTC',
    content: 'We will be conducting scheduled infrastructure upgrades. Submissions and judging portals may experience brief latency.',
    targetRole: 'all',
    placement: 'header',
    priority: 'important',
    recipientIds: [],
    recipientCount: 556,
    authorName: 'Platform Operations Admin',
    createdAt: new Date(Date.now() - 3600000 * 4).toISOString(),
    status: 'active',
    actionUrl: '/participant/announcements',
  },
  {
    id: 'ann_judge_002',
    title: 'Judge Evaluation Guidelines v2.1 Released',
    content: 'All assigned judges are requested to review the updated evaluation rubric criteria before scoring milestone repositories.',
    targetRole: 'judges',
    placement: 'home',
    priority: 'normal',
    recipientIds: [],
    recipientCount: 30,
    authorName: 'Super Admin',
    createdAt: new Date(Date.now() - 3600000 * 24).toISOString(),
    status: 'active',
    actionUrl: '/judge/guidelines',
  },
  {
    id: 'ann_organizer_003',
    title: 'Urgent: Verify Hackathon Webhook Integration Status',
    content: 'Organizers with active competitions must verify their GitHub webhook secrets in the integrations tab to ensure branch events stream properly.',
    targetRole: 'organizers',
    placement: 'announcements',
    priority: 'urgent',
    recipientIds: [],
    recipientCount: 488,
    authorName: 'Security Admin',
    createdAt: new Date(Date.now() - 3600000 * 48).toISOString(),
    status: 'active',
    actionUrl: '/admin/integrations',
  },
];

export default function AdminAnnouncementsPage() {
  const [announcements, setAnnouncements] = useState<AdminAnnouncement[]>([]);
  const [filterRole, setFilterRole] = useState<string>('all');
  const [filterPlacement, setFilterPlacement] = useState<string>('all');
  const [filterPriority, setFilterPriority] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Create Modal State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [targetRole, setTargetRole] = useState<AudienceRole>('all');
  const [placement, setPlacement] = useState<AnnouncementPlacement>('all');
  const [priority, setPriority] = useState<AnnouncementPriority>('normal');
  const [actionUrl, setActionUrl] = useState('');
  
  // Specific Recipient Selection
  const [recipientMode, setRecipientMode] = useState<'broadcast' | 'specific'>('broadcast');
  const [selectedUserIds, setSelectedUserIds] = useState<string[]>([]);
  const [availableUsers, setAvailableUsers] = useState<UserProfile[]>([]);
  const [isLoadingUsers, setIsLoadingUsers] = useState(false);
  const [userSearch, setUserSearch] = useState('');

  // UI state
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [previewItem, setPreviewItem] = useState<AdminAnnouncement | null>(null);

  // Load announcements from backend
  const loadAnnouncements = async () => {
    try {
      const data = await api.getAdminAnnouncements();
      const mapped: AdminAnnouncement[] = data.map((d) => ({
        id: d.id,
        title: d.title,
        content: d.content,
        targetRole: d.target_role as AudienceRole,
        placement: d.placement as AnnouncementPlacement,
        priority: d.priority as AnnouncementPriority,
        recipientIds: d.recipient_ids || [],
        recipientCount: d.recipient_count,
        authorName: d.author_name,
        createdAt: d.created_at,
        status: (d.status as 'active' | 'scheduled' | 'archived') || 'active',
        actionUrl: d.action_url || undefined,
      }));
      setAnnouncements(mapped);
    } catch {
      // Fallback to local default if offline
      setAnnouncements(DEFAULT_ANNOUNCEMENTS);
    }
  };

  useEffect(() => {
    loadAnnouncements();
  }, []);

  // Fetch available users when specific recipient mode is selected
  useEffect(() => {
    if (recipientMode === 'specific' && availableUsers.length === 0) {
      setIsLoadingUsers(true);
      api.getUsers({ limit: 100 })
        .then((res) => {
          setAvailableUsers(res.items || []);
        })
        .catch(() => {})
        .finally(() => {
          setIsLoadingUsers(false);
        });
    }
  }, [recipientMode, availableUsers.length]);

  // Filtered available users in recipient selector
  const filteredUsers = useMemo(() => {
    if (!userSearch.trim()) return availableUsers;
    const q = userSearch.toLowerCase();
    return availableUsers.filter(
      (u) =>
        u.full_name.toLowerCase().includes(q) ||
        u.email.toLowerCase().includes(q)
    );
  }, [availableUsers, userSearch]);

  const toggleUserSelection = (userId: string) => {
    setSelectedUserIds((prev) =>
      prev.includes(userId) ? prev.filter((id) => id !== userId) : [...prev, userId]
    );
  };

  const handleSelectAllFiltered = () => {
    const ids = filteredUsers.map((u) => u.id);
    setSelectedUserIds((prev) => Array.from(new Set([...prev, ...ids])));
  };

  const handleDeselectAll = () => {
    setSelectedUserIds([]);
  };

  const handleCreateAnnouncement = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !content.trim()) {
      setErrorMsg('Please enter both an announcement title and message content.');
      return;
    }

    if (recipientMode === 'specific' && selectedUserIds.length === 0) {
      setErrorMsg('Please select at least one specific recipient or switch to Broadcast mode.');
      return;
    }

    setIsSubmitting(true);
    setErrorMsg(null);

    try {
      await api.createAdminAnnouncement({
        title: title.trim(),
        content: content.trim(),
        target_role: targetRole,
        placement: placement,
        priority: priority,
        recipient_ids: recipientMode === 'specific' ? selectedUserIds : [],
        action_url: actionUrl.trim() || undefined,
      });

      await loadAnnouncements();
      setIsModalOpen(false);
      setSuccessMsg(`Announcement "${title}" broadcast successfully across the platform.`);
      setTimeout(() => setSuccessMsg(null), 5000);

      // Reset Form
      setTitle('');
      setContent('');
      setTargetRole('all');
      setPlacement('all');
      setPriority('normal');
      setActionUrl('');
      setRecipientMode('broadcast');
      setSelectedUserIds([]);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setErrorMsg(err.message);
      } else {
        setErrorMsg('Failed to broadcast announcement. Please verify your connection.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeleteAnnouncement = async (id: string) => {
    try {
      await api.deleteAdminAnnouncement(id);
      await loadAnnouncements();
    } catch (err) {
      console.error('Failed to delete announcement', err);
    }
  };

  // Filter announcements for the main list
  const filteredAnnouncements = announcements.filter((item) => {
    if (filterRole !== 'all' && item.targetRole !== filterRole && item.targetRole !== 'all') {
      return false;
    }
    if (filterPlacement !== 'all' && item.placement !== filterPlacement && item.placement !== 'all') {
      return false;
    }
    if (filterPriority !== 'all' && item.priority !== filterPriority) {
      return false;
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      return (
        item.title.toLowerCase().includes(q) ||
        item.content.toLowerCase().includes(q) ||
        item.authorName.toLowerCase().includes(q)
      );
    }
    return true;
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Announcements & Broadcast System"
        description="Create and dispatch targeted platform announcements to organizers, judges, and participants across Home, Header, and Announcements sections."
      >
        <button
          onClick={() => setIsModalOpen(true)}
          className="inline-flex items-center gap-2 px-4 py-2 bg-primary hover:bg-primary-hover text-white text-xs font-semibold rounded-lg shadow-sm shadow-primary/25 transition-all"
        >
          <Plus className="w-4 h-4" />
          <span>New Announcement</span>
        </button>
      </PageHeader>

      {/* Success Notification Alert */}
      {successMsg && (
        <div className="p-4 rounded-xl bg-status-success/10 border border-status-success/30 flex items-center justify-between text-xs text-status-success animate-in fade-in duration-200">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 shrink-0" />
            <span>{successMsg}</span>
          </div>
          <button onClick={() => setSuccessMsg(null)} className="p-1 hover:opacity-75">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Metric Cards Summary */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-4 rounded-xl bg-surface border border-surface-border shadow-surface">
          <div className="flex items-center justify-between text-text-muted">
            <span className="text-xs font-semibold uppercase tracking-wider">Total Broadcasts</span>
            <Megaphone className="w-4 h-4 text-primary" />
          </div>
          <div className="mt-2 text-2xl font-bold text-text-primary">{announcements.length}</div>
          <p className="text-[11px] text-text-muted mt-1">Platform-wide messages posted</p>
        </div>

        <div className="p-4 rounded-xl bg-surface border border-surface-border shadow-surface">
          <div className="flex items-center justify-between text-text-muted">
            <span className="text-xs font-semibold uppercase tracking-wider">Target: Organizers</span>
            <Shield className="w-4 h-4 text-purple-400" />
          </div>
          <div className="mt-2 text-2xl font-bold text-text-primary">
            {announcements.filter((a) => a.targetRole === 'organizers' || a.targetRole === 'all').length}
          </div>
          <p className="text-[11px] text-text-muted mt-1">Broadcasts reaching event hosts</p>
        </div>

        <div className="p-4 rounded-xl bg-surface border border-surface-border shadow-surface">
          <div className="flex items-center justify-between text-text-muted">
            <span className="text-xs font-semibold uppercase tracking-wider">Target: Judges</span>
            <Users className="w-4 h-4 text-amber-400" />
          </div>
          <div className="mt-2 text-2xl font-bold text-text-primary">
            {announcements.filter((a) => a.targetRole === 'judges' || a.targetRole === 'all').length}
          </div>
          <p className="text-[11px] text-text-muted mt-1">Evaluation & scoring notices</p>
        </div>

        <div className="p-4 rounded-xl bg-surface border border-surface-border shadow-surface">
          <div className="flex items-center justify-between text-text-muted">
            <span className="text-xs font-semibold uppercase tracking-wider">Target: Participants</span>
            <Layers className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="mt-2 text-2xl font-bold text-text-primary">
            {announcements.filter((a) => a.targetRole === 'participants' || a.targetRole === 'all').length}
          </div>
          <p className="text-[11px] text-text-muted mt-1">Participant Hub & Home broadcasts</p>
        </div>
      </div>

      {/* Filter & Search Bar */}
      <div className="bg-surface border border-surface-border rounded-xl p-4 flex flex-col md:flex-row items-center justify-between gap-4">
        <div className="relative w-full md:w-80">
          <Search className="w-4 h-4 text-text-muted absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search announcements..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-3 py-1.5 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary placeholder:text-text-muted focus:outline-none focus:border-primary transition-colors"
          />
        </div>

        <div className="flex flex-wrap items-center gap-3 w-full md:w-auto">
          {/* Role Filter */}
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] text-text-muted font-medium">Recipient:</span>
            <select
              value={filterRole}
              onChange={(e) => setFilterRole(e.target.value)}
              className="text-xs bg-surface-elevated border border-surface-border rounded-lg px-2.5 py-1.5 text-text-primary focus:outline-none focus:border-primary"
            >
              <option value="all">All Roles</option>
              <option value="organizers">Organizers</option>
              <option value="judges">Judges</option>
              <option value="participants">Participants</option>
            </select>
          </div>

          {/* Placement Filter */}
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] text-text-muted font-medium">Placement:</span>
            <select
              value={filterPlacement}
              onChange={(e) => setFilterPlacement(e.target.value)}
              className="text-xs bg-surface-elevated border border-surface-border rounded-lg px-2.5 py-1.5 text-text-primary focus:outline-none focus:border-primary"
            >
              <option value="all">All Placements</option>
              <option value="home">Home Page</option>
              <option value="header">Header Banner</option>
              <option value="announcements">Announcements Hub</option>
            </select>
          </div>

          {/* Priority Filter */}
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] text-text-muted font-medium">Priority:</span>
            <select
              value={filterPriority}
              onChange={(e) => setFilterPriority(e.target.value)}
              className="text-xs bg-surface-elevated border border-surface-border rounded-lg px-2.5 py-1.5 text-text-primary focus:outline-none focus:border-primary"
            >
              <option value="all">All Priorities</option>
              <option value="normal">Normal</option>
              <option value="important">Important</option>
              <option value="urgent">Urgent</option>
            </select>
          </div>
        </div>
      </div>

      {/* Announcements Table / List */}
      <div className="bg-surface border border-surface-border rounded-xl overflow-hidden shadow-surface">
        <div className="px-6 py-4 border-b border-surface-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Megaphone className="w-4 h-4 text-primary" />
            <h3 className="text-sm font-bold text-text-primary">Dispatched Announcements</h3>
            <span className="text-xs text-text-muted">({filteredAnnouncements.length})</span>
          </div>
        </div>

        {filteredAnnouncements.length === 0 ? (
          <div className="p-12 text-center space-y-3">
            <CheckCircle2 className="w-8 h-8 text-status-success mx-auto opacity-75" />
            <p className="text-sm font-semibold text-text-primary">No announcements match the criteria</p>
            <p className="text-xs text-text-muted max-w-sm mx-auto">
              Try adjusting your role or placement filters, or create a new announcement above.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-surface-border">
            {filteredAnnouncements.map((item) => (
              <div
                key={item.id}
                className="p-5 hover:bg-surface-elevated/40 transition-colors flex flex-col lg:flex-row lg:items-center justify-between gap-4"
              >
                <div className="space-y-2 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-bold text-text-primary">{item.title}</span>

                    {/* Priority Tag */}
                    <span
                      className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full border ${
                        item.priority === 'urgent'
                          ? 'bg-status-danger/10 text-status-danger border-status-danger/30'
                          : item.priority === 'important'
                          ? 'bg-status-warning/10 text-status-warning border-status-warning/30'
                          : 'bg-primary/10 text-primary border-primary/30'
                      }`}
                    >
                      {item.priority}
                    </span>

                    {/* Target Role Tag */}
                    <span className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded bg-surface-elevated border border-surface-border text-text-secondary flex items-center gap-1">
                      <Users className="w-3 h-3 text-text-muted" />
                      {item.recipientIds.length > 0
                        ? `${item.recipientIds.length} Specific Users (${item.targetRole})`
                        : item.targetRole === 'all'
                        ? 'All Platform Roles'
                        : item.targetRole}
                    </span>

                    {/* Placement Tag */}
                    <span className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded bg-surface-elevated border border-surface-border text-text-muted flex items-center gap-1">
                      <Layout className="w-3 h-3" />
                      Placement: {item.placement === 'all' ? 'Everywhere' : item.placement}
                    </span>
                  </div>

                  <p className="text-xs text-text-secondary leading-relaxed line-clamp-2">
                    {item.content}
                  </p>

                  <div className="flex flex-wrap items-center gap-4 text-[11px] text-text-muted pt-1">
                    <span className="flex items-center gap-1">
                      <Calendar className="w-3 h-3" />
                      {new Date(item.createdAt).toLocaleString()}
                    </span>
                    <span>•</span>
                    <span>Author: {item.authorName}</span>
                    <span>•</span>
                    <span className="flex items-center gap-1 text-primary">
                      <UserCheck className="w-3 h-3" />
                      {item.recipientCount} Recipients targeted
                    </span>
                    {item.actionUrl && (
                      <>
                        <span>•</span>
                        <span className="font-mono text-[10px] text-text-muted truncate max-w-xs">
                          Action: {item.actionUrl}
                        </span>
                      </>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-2 self-end lg:self-center shrink-0">
                  <button
                    onClick={() => setPreviewItem(item)}
                    className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors"
                    title="Preview Announcement"
                  >
                    <Eye className="w-3.5 h-3.5" />
                    <span>Preview</span>
                  </button>

                  <button
                    onClick={() => handleDeleteAnnouncement(item.id)}
                    className="p-1.5 text-text-muted hover:text-status-danger hover:bg-status-danger/10 rounded-lg transition-colors"
                    title="Delete Announcement"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* CREATE ANNOUNCEMENT MODAL */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="bg-surface border border-surface-border rounded-xl shadow-surface-elevated w-full max-w-2xl overflow-hidden flex flex-col max-h-[90vh]">
            <div className="px-6 py-4 border-b border-surface-border flex items-center justify-between bg-surface-elevated/40">
              <div className="flex items-center gap-2">
                <Megaphone className="w-5 h-5 text-primary" />
                <h3 className="text-base font-bold text-text-primary">Broadcast New Announcement</h3>
              </div>
              <button
                onClick={() => setIsModalOpen(false)}
                className="p-1.5 text-text-muted hover:text-text-primary rounded-lg transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleCreateAnnouncement} className="p-6 overflow-y-auto space-y-5 flex-1">
              {errorMsg && (
                <div className="p-3 rounded-lg bg-status-danger/10 border border-status-danger/30 text-xs text-status-danger flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{errorMsg}</span>
                </div>
              )}

              {/* Title */}
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-text-primary block">
                  Announcement Title <span className="text-status-danger">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g., Scheduled Platform Maintenance / Submission Deadline Extension"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary placeholder:text-text-muted focus:outline-none focus:border-primary"
                />
              </div>

              {/* Message Content */}
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-text-primary block">
                  Message Content <span className="text-status-danger">*</span>
                </label>
                <textarea
                  required
                  rows={4}
                  placeholder="Provide detailed information regarding timeline updates, requirements, or instructions..."
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary placeholder:text-text-muted focus:outline-none focus:border-primary leading-relaxed"
                />
              </div>

              {/* Recipient Audience & Placement Grid */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                {/* Target Audience Role */}
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-text-primary block">
                    Target Role
                  </label>
                  <select
                    value={targetRole}
                    onChange={(e) => setTargetRole(e.target.value as AudienceRole)}
                    className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                  >
                    <option value="all">All Audiences (Universal)</option>
                    <option value="organizers">Organizers Only</option>
                    <option value="judges">Judges Only</option>
                    <option value="participants">Participants Only</option>
                  </select>
                </div>

                {/* Announcement Placement Type */}
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-text-primary block">
                    Display Location
                  </label>
                  <select
                    value={placement}
                    onChange={(e) => setPlacement(e.target.value as AnnouncementPlacement)}
                    className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                  >
                    <option value="all">All Locations</option>
                    <option value="home">Home Page Card</option>
                    <option value="header">Header Banner</option>
                    <option value="announcements">Dedicated Announcements Hub</option>
                  </select>
                </div>

                {/* Priority */}
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-text-primary block">
                    Priority Level
                  </label>
                  <select
                    value={priority}
                    onChange={(e) => setPriority(e.target.value as AnnouncementPriority)}
                    className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                  >
                    <option value="normal">Normal</option>
                    <option value="important">Important</option>
                    <option value="urgent">Urgent</option>
                  </select>
                </div>
              </div>

              {/* Recipient Targeting Mode: Broadcast vs Specific Selection */}
              <div className="space-y-3 pt-2 border-t border-surface-border">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-text-primary">
                    Recipient Scope
                  </label>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setRecipientMode('broadcast')}
                      className={`px-2.5 py-1 text-xs rounded-md font-medium transition-colors ${
                        recipientMode === 'broadcast'
                          ? 'bg-primary text-white'
                          : 'bg-surface-elevated text-text-muted hover:text-text-primary'
                      }`}
                    >
                      Broadcast to Entire Role
                    </button>
                    <button
                      type="button"
                      onClick={() => setRecipientMode('specific')}
                      className={`px-2.5 py-1 text-xs rounded-md font-medium transition-colors ${
                        recipientMode === 'specific'
                          ? 'bg-primary text-white'
                          : 'bg-surface-elevated text-text-muted hover:text-text-primary'
                      }`}
                    >
                      Select Specific Users ({selectedUserIds.length})
                    </button>
                  </div>
                </div>

                {recipientMode === 'specific' && (
                  <div className="p-4 rounded-xl bg-surface-elevated/40 border border-surface-border space-y-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="relative flex-1">
                        <Search className="w-3.5 h-3.5 text-text-muted absolute left-2.5 top-1/2 -translate-y-1/2" />
                        <input
                          type="text"
                          placeholder="Search users by name or email..."
                          value={userSearch}
                          onChange={(e) => setUserSearch(e.target.value)}
                          className="w-full pl-8 pr-3 py-1.5 text-xs bg-surface border border-surface-border rounded-lg text-text-primary placeholder:text-text-muted focus:outline-none focus:border-primary"
                        />
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={handleSelectAllFiltered}
                          className="text-[11px] font-medium text-primary hover:underline"
                        >
                          Select All
                        </button>
                        <span className="text-text-muted text-[10px]">•</span>
                        <button
                          type="button"
                          onClick={handleDeselectAll}
                          className="text-[11px] font-medium text-text-muted hover:text-text-primary"
                        >
                          Clear
                        </button>
                      </div>
                    </div>

                    <div className="max-h-48 overflow-y-auto divide-y divide-surface-border border border-surface-border rounded-lg bg-surface">
                      {isLoadingUsers ? (
                        <div className="p-4 text-center text-xs text-text-muted">Loading user directory...</div>
                      ) : filteredUsers.length === 0 ? (
                        <div className="p-4 text-center text-xs text-text-muted">No users found.</div>
                      ) : (
                        filteredUsers.map((u) => {
                          const isSelected = selectedUserIds.includes(u.id);
                          return (
                            <div
                              key={u.id}
                              onClick={() => toggleUserSelection(u.id)}
                              className={`p-2.5 flex items-center justify-between cursor-pointer hover:bg-surface-elevated transition-colors ${
                                isSelected ? 'bg-primary/5' : ''
                              }`}
                            >
                              <div className="truncate pr-2">
                                <div className="text-xs font-medium text-text-primary truncate">{u.full_name}</div>
                                <div className="text-[11px] text-text-muted truncate">{u.email}</div>
                              </div>
                              <div
                                className={`w-4 h-4 rounded flex items-center justify-center border shrink-0 transition-colors ${
                                  isSelected
                                    ? 'bg-primary border-primary text-white'
                                    : 'border-surface-border bg-surface'
                                }`}
                              >
                                {isSelected && <Check className="w-3 h-3" />}
                              </div>
                            </div>
                          );
                        })
                      )}
                    </div>
                  </div>
                )}
              </div>

              {/* Action Link (Optional) */}
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-text-primary block">
                  Action Link URL <span className="text-text-muted font-normal">(Optional)</span>
                </label>
                <input
                  type="text"
                  placeholder="e.g., /participant/performance or https://github.com/scorva/docs"
                  value={actionUrl}
                  onChange={(e) => setActionUrl(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary placeholder:text-text-muted focus:outline-none focus:border-primary"
                />
              </div>

              {/* Form Submission Actions */}
              <div className="pt-4 border-t border-surface-border flex items-center justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="px-4 py-2 text-xs font-medium text-text-secondary hover:text-text-primary hover:bg-surface-elevated rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="inline-flex items-center gap-1.5 px-4 py-2 bg-primary hover:bg-primary-hover text-white text-xs font-semibold rounded-lg shadow-sm shadow-primary/25 transition-all disabled:opacity-50"
                >
                  <Send className="w-3.5 h-3.5" />
                  <span>{isSubmitting ? 'Dispatching...' : 'Dispatch Announcement'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* PREVIEW MODAL */}
      {previewItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="bg-surface border border-surface-border rounded-xl shadow-surface-elevated w-full max-w-lg overflow-hidden">
            <div className="px-5 py-3.5 border-b border-surface-border flex items-center justify-between bg-surface-elevated/40">
              <span className="text-xs font-bold text-text-primary flex items-center gap-1.5">
                <Eye className="w-4 h-4 text-primary" />
                Announcement Preview
              </span>
              <button
                onClick={() => setPreviewItem(null)}
                className="p-1 text-text-muted hover:text-text-primary rounded-lg"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-6 space-y-4">
              <div className="flex items-center gap-2">
                <span
                  className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full border ${
                    previewItem.priority === 'urgent'
                      ? 'bg-status-danger/10 text-status-danger border-status-danger/30'
                      : previewItem.priority === 'important'
                      ? 'bg-status-warning/10 text-status-warning border-status-warning/30'
                      : 'bg-primary/10 text-primary border-primary/30'
                  }`}
                >
                  {previewItem.priority}
                </span>
                <span className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded bg-surface-elevated border border-surface-border text-text-muted">
                  Placement: {previewItem.placement}
                </span>
                <span className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded bg-surface-elevated border border-surface-border text-primary">
                  Audience: {previewItem.targetRole}
                </span>
              </div>

              <h3 className="text-base font-bold text-text-primary">{previewItem.title}</h3>
              <p className="text-xs text-text-secondary leading-relaxed bg-surface-elevated/30 p-3.5 rounded-lg border border-surface-border">
                {previewItem.content}
              </p>

              <div className="text-[11px] text-text-muted space-y-1 pt-2 border-t border-surface-border">
                <div>Posted: {new Date(previewItem.createdAt).toLocaleString()}</div>
                <div>Target Count: {previewItem.recipientCount} accounts</div>
                {previewItem.actionUrl && (
                  <div>
                    Action Link:{' '}
                    <span className="text-primary font-mono">{previewItem.actionUrl}</span>
                  </div>
                )}
              </div>
            </div>

            <div className="p-3 border-t border-surface-border bg-surface-elevated/40 text-right">
              <button
                onClick={() => setPreviewItem(null)}
                className="px-4 py-1.5 text-xs font-semibold text-text-primary bg-surface hover:bg-surface-elevated border border-surface-border rounded-lg transition-colors"
              >
                Close Preview
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
