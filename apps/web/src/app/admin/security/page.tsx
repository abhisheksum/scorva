'use client';

import React, { useState, useEffect, useCallback } from 'react';
import {
  RefreshCw,
  Search,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Lock,
  Filter,
} from 'lucide-react';
import { PageHeader } from '@/components/admin/PageHeader';
import { api, ApiClientError } from '@/lib/api-client';
import { AuditEventItem } from '@/types/api';

export default function SecurityPage() {
  const [events, setEvents] = useState<AuditEventItem[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [actorEmail, setActorEmail] = useState<string>('');
  const [actionFilter, setActionFilter] = useState<string>('');

  const loadAuditEvents = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await api.getAuditEvents({
        actor_email: actorEmail ? actorEmail.trim() : undefined,
        action: actionFilter ? actionFilter.trim() : undefined,
        limit: 50,
      });
      setEvents(data.items);
      setTotal(data.total);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to load security audit events. Ensure backend is running.');
      }
    } finally {
      setIsLoading(false);
    }
  }, [actorEmail, actionFilter]);

  useEffect(() => {
    loadAuditEvents();
  }, [loadAuditEvents]);

  const renderOutcomeBadge = (outcome: 'SUCCESS' | 'FAILURE' | 'DENIED') => {
    switch (outcome) {
      case 'SUCCESS':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-status-success/10 text-status-success border border-status-success/30">
            <CheckCircle2 className="w-3 h-3" />
            <span>Success</span>
          </span>
        );
      case 'FAILURE':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-status-error/10 text-status-error border border-status-error/30">
            <XCircle className="w-3 h-3" />
            <span>Failure</span>
          </span>
        );
      case 'DENIED':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-status-warning/10 text-status-warning border border-status-warning/30">
            <AlertTriangle className="w-3 h-3" />
            <span>Denied</span>
          </span>
        );
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Security & Audit Trail"
        description="Immutable, append-only record of privileged administrative actions, authentication lifecycle, and access governance."
      >
        <button
          type="button"
          onClick={() => loadAuditEvents()}
          disabled={isLoading}
          className="flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
          <span>Refresh</span>
        </button>
      </PageHeader>

      {/* Security Architecture Notice */}
      <div className="p-4 bg-surface border border-surface-border rounded-xl flex items-start gap-3.5">
        <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center text-primary shrink-0 mt-0.5">
          <Lock className="w-4 h-4" />
        </div>
        <div className="text-xs space-y-1">
          <p className="font-semibold text-text-primary">
            Cryptographic & Database-Enforced Immutability
          </p>
          <p className="text-text-secondary leading-relaxed">
            All administrative events are recorded synchronously in PostgreSQL with a database-level trigger (<code className="text-primary font-mono text-[11px]">trg_audit_events_immutable</code>) strictly preventing <code className="text-text-muted font-mono">UPDATE</code> or <code className="text-text-muted font-mono">DELETE</code> operations.
          </p>
        </div>
      </div>

      {/* Filter Toolbar */}
      <div className="p-4 bg-surface border border-surface-border rounded-xl flex flex-col sm:flex-row items-center gap-3 justify-between">
        <div className="flex flex-col sm:flex-row items-center gap-3 w-full sm:w-auto">
          <div className="relative w-full sm:w-64">
            <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
            <input
              type="text"
              value={actorEmail}
              onChange={(e) => setActorEmail(e.target.value)}
              placeholder="Filter by actor email..."
              className="w-full pl-9 pr-3 py-1.5 bg-surface-elevated border border-surface-border rounded-lg text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:border-primary"
            />
          </div>

          <div className="relative w-full sm:w-48">
            <Filter className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
            <input
              type="text"
              value={actionFilter}
              onChange={(e) => setActionFilter(e.target.value)}
              placeholder="Filter by action..."
              className="w-full pl-9 pr-3 py-1.5 bg-surface-elevated border border-surface-border rounded-lg text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:border-primary"
            />
          </div>
        </div>

        <div className="text-xs text-text-muted shrink-0 w-full sm:w-auto text-right">
          Total Recorded: <span className="font-semibold text-text-primary">{total}</span>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="p-4 bg-status-error/10 border border-status-error/20 rounded-xl text-xs text-status-error flex items-center justify-between">
          <span>{error}</span>
          <button
            type="button"
            onClick={() => loadAuditEvents()}
            className="underline font-semibold hover:text-white"
          >
            Retry
          </button>
        </div>
      )}

      {/* Events Table */}
      <div className="bg-surface border border-surface-border rounded-xl overflow-hidden shadow-surface-elevated">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="border-b border-surface-border bg-surface-elevated/50 text-text-muted font-medium">
                <th className="py-3 px-4">Timestamp (UTC)</th>
                <th className="py-3 px-4">Outcome</th>
                <th className="py-3 px-4">Action</th>
                <th className="py-3 px-4">Actor</th>
                <th className="py-3 px-4">Resource</th>
                <th className="py-3 px-4">IP / Client</th>
                <th className="py-3 px-4">Details / Reason</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-border">
              {isLoading && events.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-text-muted">
                    Loading security audit trail...
                  </td>
                </tr>
              ) : events.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-text-muted">
                    No audit records match the selected filters.
                  </td>
                </tr>
              ) : (
                events.map((evt) => (
                  <tr
                    key={evt.id}
                    className="hover:bg-surface-hover/50 transition-colors"
                  >
                    <td className="py-3 px-4 font-mono text-[11px] text-text-secondary whitespace-nowrap">
                      {new Date(evt.timestamp).toLocaleString()}
                    </td>
                    <td className="py-3 px-4 whitespace-nowrap">
                      {renderOutcomeBadge(evt.outcome)}
                    </td>
                    <td className="py-3 px-4 font-mono font-medium text-text-primary whitespace-nowrap">
                      {evt.action}
                    </td>
                    <td className="py-3 px-4 whitespace-nowrap">
                      <div className="font-medium text-text-primary">
                        {evt.actor_email}
                      </div>
                      <div className="text-[10px] text-text-muted uppercase">
                        {evt.actor_role}
                      </div>
                    </td>
                    <td className="py-3 px-4 whitespace-nowrap font-mono text-[11px] text-text-secondary">
                      {evt.resource_type}:{evt.resource_id.slice(0, 8)}
                    </td>
                    <td className="py-3 px-4 whitespace-nowrap font-mono text-[11px] text-text-muted">
                      {evt.ip_address}
                    </td>
                    <td className="py-3 px-4 text-text-secondary max-w-xs truncate" title={evt.reason || ''}>
                      {evt.reason || '—'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
