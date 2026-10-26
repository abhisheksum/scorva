'use client';

import React, { useState, use } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  Trophy,
  ChevronLeft,
  AlertCircle,
  Calendar,
  Clock,
  Sparkles,
  Lock,
} from 'lucide-react';
import { api, ApiClientError } from '@/lib/api-client';

export default function NewTenantHackathonPage({
  params,
}: {
  params: Promise<{ organizationId: string }>;
}) {
  const unwrappedParams = use(params);
  const orgId = unwrappedParams.organizationId;
  const router = useRouter();

  const [title, setTitle] = useState<string>('');
  const [slug, setSlug] = useState<string>('');
  const [description, setDescription] = useState<string>('');
  const [startDate, setStartDate] = useState<string>('');
  const [submissionDeadline, setSubmissionDeadline] = useState<string>('');
  const [endDate, setEndDate] = useState<string>('');

  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [formError, setFormError] = useState<string | null>(null);

  const handleTitleChange = (val: string) => {
    setTitle(val);
    const generatedSlug = val
      .toLowerCase()
      .replace(/[^a-z0-9\s-]/g, '')
      .trim()
      .replace(/\s+/g, '-');
    setSlug(generatedSlug);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    const start = new Date(startDate);
    const deadline = new Date(submissionDeadline);
    const end = new Date(endDate);

    if (isNaN(start.getTime()) || isNaN(deadline.getTime()) || isNaN(end.getTime())) {
      setFormError('Please specify valid start, submission deadline, and end dates.');
      return;
    }

    // Timeline constraint validation: start_date < submission_deadline <= end_date
    if (!(start < deadline && deadline <= end)) {
      setFormError('Invalid timeline constraints: Event Start must be earlier than Submission Deadline, which must be on or before Event End Date.');
      return;
    }

    setIsSubmitting(true);
    try {
      const created = await api.createTenantHackathon(orgId, {
        title: title.trim(),
        slug: slug.trim(),
        description: description.trim() || undefined,
        start_date: start.toISOString(),
        submission_deadline: deadline.toISOString(),
        end_date: end.toISOString(),
      });
      router.push(`/organizations/${orgId}/hackathons/${created.id}`);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setFormError(err.message);
      } else {
        setFormError('Failed to create hackathon. Please verify inputs and try again.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <Link
        href={`/organizations/${orgId}/hackathons`}
        className="inline-flex items-center gap-2 text-xs text-text-muted hover:text-text-primary transition-colors"
      >
        <ChevronLeft className="w-4 h-4" />
        <span>Back to Hackathons</span>
      </Link>

      <div className="bg-surface rounded-2xl border border-surface-border p-6 shadow-sm">
        <div className="flex items-center gap-3 border-b border-surface-border pb-5 mb-5">
          <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center text-primary">
            <Trophy className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-text-primary">Create New Hackathon</h1>
            <p className="text-xs text-text-muted">
              Configure event timeline, unique URL slug, and participation rules.
            </p>
          </div>
        </div>

        {formError && (
          <div className="p-4 bg-status-error/10 border border-status-error/30 rounded-xl text-status-error text-xs flex items-center gap-2 mb-5">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{formError}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-5 text-xs">
          <div>
            <label className="block font-medium text-text-secondary mb-1">
              Hackathon Title <span className="text-status-error">*</span>
            </label>
            <input
              type="text"
              required
              placeholder="e.g. Scorva Global AI Hackathon 2026"
              value={title}
              onChange={(e) => handleTitleChange(e.target.value)}
              className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
            />
          </div>

          <div>
            <label className="block font-medium text-text-secondary mb-1">
              Event Slug (URL identifier) <span className="text-status-error">*</span>
            </label>
            <input
              type="text"
              required
              pattern="^[a-z0-9]+(?:-[a-z0-9]+)*$"
              placeholder="global-ai-hackathon-2026"
              value={slug}
              onChange={(e) => setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ''))}
              className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary font-mono"
            />
            <p className="text-[10px] text-text-muted mt-1">
              Lowercase letters, numbers, and hyphens. Immutable once published.
            </p>
          </div>

          <div>
            <label className="block font-medium text-text-secondary mb-1">
              Description & Rules (Markdown Supported)
            </label>
            <textarea
              rows={4}
              maxLength={10000}
              placeholder="Explain the hackathon theme, guidelines, and rules..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary placeholder-text-muted"
            />
          </div>

          <div className="p-4 bg-surface-elevated/60 rounded-xl border border-surface-border space-y-4">
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4 text-primary" />
              <span className="font-semibold text-text-primary uppercase tracking-wider text-[11px]">
                Timeline Dates & Constraints
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div>
                <label className="block text-[11px] text-text-muted mb-1">
                  Start Date <span className="text-status-error">*</span>
                </label>
                <input
                  type="datetime-local"
                  required
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="w-full px-2.5 py-1.5 text-xs bg-surface border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>

              <div>
                <label className="block text-[11px] text-primary font-semibold mb-1">
                  Submission Deadline <span className="text-status-error">*</span>
                </label>
                <input
                  type="datetime-local"
                  required
                  value={submissionDeadline}
                  onChange={(e) => setSubmissionDeadline(e.target.value)}
                  className="w-full px-2.5 py-1.5 text-xs bg-surface border border-primary/40 rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>

              <div>
                <label className="block text-[11px] text-text-muted mb-1">
                  End Date <span className="text-status-error">*</span>
                </label>
                <input
                  type="datetime-local"
                  required
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="w-full px-2.5 py-1.5 text-xs bg-surface border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>
            </div>

            <div className="flex items-center gap-1.5 text-[10px] text-text-muted">
              <Lock className="w-3 h-3 text-text-muted/70" />
              <span>Enforced constraint: Start Date &lt; Submission Deadline &le; End Date.</span>
            </div>
          </div>

          <div className="pt-3 border-t border-surface-border flex items-center justify-end gap-3">
            <Link
              href={`/organizations/${orgId}/hackathons`}
              className="px-3.5 py-2 text-xs font-medium text-text-muted hover:text-text-primary hover:bg-surface-elevated rounded-lg transition-colors"
            >
              Cancel
            </Link>
            <button
              type="submit"
              disabled={isSubmitting || !title || !slug || !startDate || !submissionDeadline || !endDate}
              className="px-5 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg transition-colors shadow-sm"
            >
              {isSubmitting ? 'Creating Event...' : 'Create Draft Event'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
