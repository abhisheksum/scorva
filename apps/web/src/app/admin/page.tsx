'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  ShieldCheck,
  Server,
  Database,
  Layers,
  ArrowRight,
  Cpu,
  Clock,
  Sparkles,
  Info,
} from 'lucide-react';
import { PageHeader } from '@/components/admin/PageHeader';
import { StatusBadge } from '@/components/admin/StatusBadge';
import { api } from '@/lib/api-client';
import { HealthResponse } from '@/types/api';

export default function AdminOverviewPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    async function loadHealth() {
      try {
        const data = await api.getHealth();
        setHealth(data);
      } catch {
        // Error state handled gracefully by null check
      } finally {
        setLoading(false);
      }
    }
    loadHealth();
  }, []);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Platform Overview"
        description="Central administrative control and operational health for Scorva."
      >
        <div className="flex items-center gap-2">
          <StatusBadge status="active" label="Phase 1: Foundation Active" />
        </div>
      </PageHeader>

      {/* Foundation Status Banner */}
      <div className="p-5 rounded-xl bg-surface border border-surface-border">
        <div className="flex items-start gap-4">
          <div className="p-3 rounded-lg bg-primary/10 text-primary shrink-0">
            <Sparkles className="w-6 h-6" />
          </div>
          <div className="space-y-1 flex-1">
            <h2 className="text-base font-semibold text-text-primary">
              Scorva System Foundation Operational
            </h2>
            <p className="text-sm text-text-secondary">
              The Next.js frontend, FastAPI backend, shared design system, and Docker Compose environment are initialized. Core relational models, authentication sessions, and platform metrics will be activated incrementally in upcoming phases.
            </p>
          </div>
        </div>
      </div>

      {/* Real Infrastructure Telemetry (From Live API) */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-text-muted">
            Live Dependency Probes
          </h2>
          <span className="text-xs text-text-muted flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5" />
            {health?.timestamp ? new Date(health.timestamp).toLocaleTimeString() : 'Awaiting heartbeat'}
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* API Core Service */}
          <div className="p-4 rounded-xl bg-surface border border-surface-border space-y-3">
            <div className="flex items-center justify-between">
              <div className="p-2 rounded-lg bg-surface-elevated text-primary">
                <Server className="w-4 h-4" />
              </div>
              <StatusBadge status={health?.status || 'unknown'} size="sm" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-text-primary">FastAPI Core</h3>
              <p className="text-xs text-text-secondary mt-0.5">
                {health?.services?.api?.details || (loading ? 'Checking...' : 'Connection error')}
              </p>
            </div>
            {health?.services?.api?.latency_ms !== undefined && (
              <div className="text-[11px] font-mono text-text-muted pt-2 border-t border-surface-border">
                Latency: {health.services.api.latency_ms} ms
              </div>
            )}
          </div>

          {/* Database */}
          <div className="p-4 rounded-xl bg-surface border border-surface-border space-y-3">
            <div className="flex items-center justify-between">
              <div className="p-2 rounded-lg bg-surface-elevated text-status-info">
                <Database className="w-4 h-4" />
              </div>
              <StatusBadge status={health?.services?.database?.status || 'unknown'} size="sm" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-text-primary">PostgreSQL 16</h3>
              <p className="text-xs text-text-secondary mt-0.5">
                {health?.services?.database?.details || 'Relational primary database'}
              </p>
            </div>
            <div className="text-[11px] font-mono text-text-muted pt-2 border-t border-surface-border">
              Driver: asyncpg pool
            </div>
          </div>

          {/* Redis Task Broker */}
          <div className="p-4 rounded-xl bg-surface border border-surface-border space-y-3">
            <div className="flex items-center justify-between">
              <div className="p-2 rounded-lg bg-surface-elevated text-status-warning">
                <Layers className="w-4 h-4" />
              </div>
              <StatusBadge status={health?.services?.redis?.status || 'unknown'} size="sm" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-text-primary">Redis 7 Broker</h3>
              <p className="text-xs text-text-secondary mt-0.5">
                {health?.services?.redis?.details || 'Session cache & task queue'}
              </p>
            </div>
            <div className="text-[11px] font-mono text-text-muted pt-2 border-t border-surface-border">
              Queues: evaluations.*
            </div>
          </div>

          {/* AI Provider (Ollama) */}
          <div className="p-4 rounded-xl bg-surface border border-surface-border space-y-3">
            <div className="flex items-center justify-between">
              <div className="p-2 rounded-lg bg-surface-elevated text-status-info">
                <Cpu className="w-4 h-4" />
              </div>
              <StatusBadge status={health?.services?.ollama?.status || 'unknown'} size="sm" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-text-primary">Ollama Daemon</h3>
              <p className="text-xs text-text-secondary mt-0.5">
                {health?.services?.ollama?.details || 'Local inference server'}
              </p>
            </div>
            <div className="text-[11px] font-mono text-text-muted pt-2 border-t border-surface-border">
              Target: llama3:8b
            </div>
          </div>
        </div>
      </div>

      {/* Implementation Roadmap Cards */}
      <div className="space-y-4 pt-2">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-text-muted">
          Upcoming Architecture Phases
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="p-4 rounded-xl bg-surface border border-surface-border flex flex-col justify-between">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-primary">Phase 2</span>
                <span className="text-xs text-text-muted font-mono">Next</span>
              </div>
              <h3 className="text-sm font-semibold text-text-primary">
                Authentication & Dual-Plane RBAC
              </h3>
              <p className="text-xs text-text-secondary">
                Redis stateful session store, TOTP MFA challenge, Super Admin route guards, and append-only audit event logging.
              </p>
            </div>
            <div className="mt-4 pt-3 border-t border-surface-border flex items-center justify-between text-xs text-text-muted">
              <span>PRD §2 & §9</span>
              <ShieldCheck className="w-4 h-4 text-primary" />
            </div>
          </div>

          <div className="p-4 rounded-xl bg-surface border border-surface-border flex flex-col justify-between">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-text-muted">Phase 3</span>
                <span className="text-xs text-text-muted font-mono">Planned</span>
              </div>
              <h3 className="text-sm font-semibold text-text-primary">
                Organizations & Hackathons Oversight
              </h3>
              <p className="text-xs text-text-secondary">
                Tenant isolation enforcement, multi-tenant directory pagination, organization suspension workflows, and hackathon commit tracking.
              </p>
            </div>
            <div className="mt-4 pt-3 border-t border-surface-border flex items-center justify-between text-xs text-text-muted">
              <span>PRD §4.2 & §4.4</span>
              <Layers className="w-4 h-4 text-text-muted" />
            </div>
          </div>

          <div className="p-4 rounded-xl bg-surface border border-surface-border flex flex-col justify-between">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-text-muted">Phase 4</span>
                <span className="text-xs text-text-muted font-mono">Planned</span>
              </div>
              <h3 className="text-sm font-semibold text-text-primary">
                AI Evaluation Pipeline & Workers
              </h3>
              <p className="text-xs text-text-secondary">
                Celery worker pool, immutable Git tarball archiving, Ollama structured JSON schema scoring, and evidence verification.
              </p>
            </div>
            <div className="mt-4 pt-3 border-t border-surface-border flex items-center justify-between text-xs text-text-muted">
              <span>PRD §4.6 & §4.7</span>
              <Cpu className="w-4 h-4 text-text-muted" />
            </div>
          </div>
        </div>
      </div>

      {/* Honest Empty State Notice for Modules */}
      <div className="p-4 rounded-lg bg-surface-elevated border border-surface-border flex items-center gap-3 text-xs text-text-secondary">
        <Info className="w-4 h-4 text-status-info shrink-0" />
        <span>
          Scorva strictly enforces real data: metrics cards and activity logs are not populated with fabricated mock data and will connect to live database aggregation queries in Phase 2 & Phase 3.
        </span>
      </div>
    </div>
  );
}
