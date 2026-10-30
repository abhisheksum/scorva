'use client';

import React, { useEffect, useState, useCallback, useMemo } from 'react';
import Link from 'next/link';
import {
  Users,
  Building2,
  Trophy,
  RefreshCw,
  Clock,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ArrowRight,
  Shield,
  FileCode,
  Server,
  Database,
  Cpu,
  Zap,
  Layers,
  Bot,
  Bell,
  LineChart as LineChartIcon,
} from 'lucide-react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { api } from '@/lib/api-client';
import {
  HealthResponse,
  DashboardOverviewResponse,
  DashboardTrendPoint,
  OrganizationSummaryResponse,
} from '@/types/api';

// ─── Types ──────────────────────────────────────────────────────────────────

interface SystemAlert {
  id: string;
  severity: 'High' | 'Medium' | 'Low';
  title: string;
  context: string;
  time: string;
  href?: string;
}

// ─── Visual Mini-Components ─────────────────────────────────────────────────

/**
 * Honest SVG Sparkline mapping directly to genuine historical time-series points.
 * Renders a flat neutral baseline if all points are zero or identical.
 */
function Sparkline({
  color,
  gradientId,
  data,
  width = 96,
  height = 36,
}: {
  color: string;
  gradientId: string;
  data?: number[];
  width?: number;
  height?: number;
}) {
  const safeData = data && data.length > 1 ? data : [0, 0];
  const max = Math.max(...safeData);
  const min = Math.min(...safeData);
  const range = max - min;

  if (range === 0) {
    const yBaseline = height - 8;
    return (
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className="shrink-0 overflow-visible"
        aria-hidden="true"
      >
        <line
          x1={2}
          y1={yBaseline}
          x2={width - 2}
          y2={yBaseline}
          stroke={color}
          strokeWidth="1.5"
          strokeDasharray="3 3"
          opacity="0.3"
        />
      </svg>
    );
  }

  const points: [number, number][] = safeData.map((val, idx) => {
    const x = (idx / (safeData.length - 1)) * (width - 4) + 2;
    const y = height - ((val - min) / range) * (height - 8) - 4;
    return [x, y];
  });

  let curvePath = `M ${points[0][0].toFixed(1)} ${points[0][1].toFixed(1)}`;
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i];
    const p1 = points[i + 1];
    const cpX = ((p0[0] + p1[0]) / 2).toFixed(1);
    curvePath += ` C ${cpX} ${p0[1].toFixed(1)}, ${cpX} ${p1[1].toFixed(1)}, ${p1[0].toFixed(1)} ${p1[1].toFixed(1)}`;
  }

  const areaPath = `${curvePath} L ${points[points.length - 1][0].toFixed(1)} ${height} L ${points[0][0].toFixed(1)} ${height} Z`;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="shrink-0 overflow-visible"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.25" />
          <stop offset="100%" stopColor={color} stopOpacity="0.0" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#${gradientId})`} />
      <path
        d={curvePath}
        fill="none"
        stroke={color}
        strokeWidth="2.0"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function KPISkeleton() {
  return (
    <div className="p-4 sm:p-5 rounded-2xl bg-[#0D1A2B] border border-[#24364D] animate-pulse flex flex-col justify-between h-[116px]">
      <div className="flex items-center gap-2">
        <div className="w-4 h-4 bg-[#112139] rounded shrink-0" />
        <div className="h-4 w-28 bg-[#112139] rounded" />
      </div>
      <div className="flex items-end justify-between mt-4">
        <div>
          <div className="h-3 w-16 bg-[#112139] rounded" />
          <div className="mt-2 h-6 w-20 bg-[#112139] rounded" />
        </div>
        <div className="w-20 h-8 bg-[#112139] rounded-lg shrink-0" />
      </div>
    </div>
  );
}

function PanelSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="p-5 rounded-2xl bg-[#0D1A2B] border border-[#24364D] animate-pulse space-y-4">
      <div className="flex items-center justify-between">
        <div className="h-4 w-40 bg-[#112139] rounded" />
        <div className="h-3 w-16 bg-[#112139] rounded" />
      </div>
      <div className="space-y-3">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="h-12 bg-[#112139]/60 rounded-xl" />
        ))}
      </div>
    </div>
  );
}

// ─── Custom Tooltip ─────────────────────────────────────────────────────────

interface CustomTooltipProps {
  active?: boolean;
  payload?: Array<{
    name: string;
    value: number;
    color: string;
  }>;
  label?: string;
}

function ChartTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-[#0D1A2B] border border-[#24364D] rounded-xl p-3 shadow-xl backdrop-blur-md">
      <p className="text-xs font-semibold text-[#F3F6FC] mb-2">{label}</p>
      <div className="space-y-1">
        {payload.map((entry, i) => (
          <div key={i} className="flex items-center justify-between gap-4 text-xs">
            <div className="flex items-center gap-1.5">
              <span
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: entry.color }}
              />
              <span className="text-[#91A4BE]">{entry.name}</span>
            </div>
            <span className="text-[#F3F6FC] font-mono font-medium">
              {entry.value.toLocaleString()}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Helpers ────────────────────────────────────────────────────────────────

const formatRelativeTime = (isoStr: string) => {
  try {
    const now = Date.now();
    const diff = now - new Date(isoStr).getTime();
    const minutes = Math.floor(diff / 60000);
    if (minutes < 1) return 'Just now';
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  } catch {
    return 'Recent';
  }
};

const formatTimeOnly = (isoStr: string) => {
  try {
    const d = new Date(isoStr);
    return d.toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: true,
    });
  } catch {
    return '—';
  }
};

const getInitials = (name: string) => {
  return (
    name
      .split(/[\s\-_]+/)
      .filter(Boolean)
      .map((w) => w.charAt(0))
      .join('')
      .toUpperCase()
      .slice(0, 2) || 'OR'
  );
};

// ─── Main Component ─────────────────────────────────────────────────────────

export default function AdminOverviewPage() {
  const [dashboard, setDashboard] = useState<DashboardOverviewResponse | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [recentOrgs, setRecentOrgs] = useState<OrganizationSummaryResponse[]>([]);
  const [trendPoints, setTrendPoints] = useState<DashboardTrendPoint[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [trendPeriod, setTrendPeriod] = useState<'7D' | '30D' | '90D' | '1Y'>('30D');

  const loadData = useCallback(
    async (isRefresh = false, periodOverride?: '7D' | '30D' | '90D' | '1Y') => {
      if (refreshing && isRefresh) return;

      if (isRefresh) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }
      setError(null);

      const period = periodOverride || trendPeriod;

      try {
        const [dashData, healthData, orgsData, trendsData] = await Promise.all([
          api.getDashboardOverview({ refresh: isRefresh }),
          api.getHealth(),
          api.getAdminOrganizations({
            limit: 5,
            sort_by: 'created_at',
            sort_order: 'desc',
          }),
          api.getDashboardTrends({ period }).catch(() => ({ period, points: [] })),
        ]);
        setDashboard(dashData);
        setHealth(healthData);
        setRecentOrgs(orgsData.items || []);
        setTrendPoints(trendsData.points || []);
        setLastUpdated(new Date());
      } catch (err: unknown) {
        console.error('Failed to load dashboard data:', err);
        setError(
          'Unable to fetch live platform metrics. Please verify that backend services are active.'
        );
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [refreshing, trendPeriod]
  );

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handlePeriodChange = (period: '7D' | '30D' | '90D' | '1Y') => {
    setTrendPeriod(period);
    api.getDashboardTrends({ period })
      .then((res) => setTrendPoints(res.points || []))
      .catch(() => {});
  };

  const counts = dashboard?.counts;

  // ─── Extract real sparkline series from trendPoints ───────────────────────
  const sparklineData = useMemo(() => {
    if (!trendPoints || trendPoints.length === 0) {
      return {
        users: [0, 0],
        orgs: [0, 0],
        hackathons: [0, 0],
        submissions: [0, 0],
        evaluations: [0, 0],
      };
    }
    return {
      users: trendPoints.map((p) => p.users),
      orgs: trendPoints.map((p) => p.organizations),
      hackathons: trendPoints.map((p) => p.hackathons),
      submissions: trendPoints.map((p) => p.submissions),
      evaluations: trendPoints.map((p) => p.evaluations),
    };
  }, [trendPoints]);

  // ─── Calculate dynamic AI Evaluation Failure Rate ─────────────────────────
  const failureRate = useMemo(() => {
    if (!counts) return '0.0%';
    const totalFinished = (counts.evaluations_completed || 0) + (counts.evaluations_failed || 0);
    if (totalFinished === 0) return '0.0%';
    return ((counts.evaluations_failed / totalFinished) * 100).toFixed(1) + '%';
  }, [counts]);

  // ─── Derive verified system alerts exclusively from real runtime data ─────
  const systemAlerts = useMemo<SystemAlert[]>(() => {
    const alerts: SystemAlert[] = [];

    // 1. High queue depth alert
    if (counts && counts.evaluations_running > 50) {
      alerts.push({
        id: 'eval-queue-latency',
        severity: 'High',
        title: 'Evaluation Queue Depth Elevated',
        context: `${counts.evaluations_running.toLocaleString()} jobs currently queued or executing in Celery pool`,
        time: 'Active',
        href: '/admin/ai-operations',
      });
    }

    // 2. Evaluation failures alert
    if (counts && counts.evaluations_failed > 0) {
      alerts.push({
        id: 'eval-failures',
        severity: counts.evaluations_failed > 5 ? 'High' : 'Medium',
        title: 'Evaluation Worker Failures Detected',
        context: `${counts.evaluations_failed.toLocaleString()} jobs failed or moved to dead-letter queue`,
        time: 'Active',
        href: '/admin/ai-operations',
      });
    }

    // 3. Service health alerts from live telemetry
    if (health?.services) {
      Object.entries(health.services).forEach(([name, svc]) => {
        if (svc.status === 'unhealthy') {
          alerts.push({
            id: `svc-${name}`,
            severity: 'High',
            title: `${name.toUpperCase()} Service Degraded`,
            context: svc.details || 'Live health check probe returned unhealthy.',
            time: 'Live',
            href: '/admin/system-health',
          });
        } else if (svc.status === 'degraded') {
          alerts.push({
            id: `svc-${name}-degraded`,
            severity: 'Medium',
            title: `${name.toUpperCase()} Latency Elevated`,
            context: svc.details || 'Service response latency exceeds threshold.',
            time: 'Live',
            href: '/admin/system-health',
          });
        }
      });
    }

    return alerts.slice(0, 5);
  }, [counts, health]);

  // ─── Format audit action label & styling ──────────────────────────────────
  const getAuditInfo = (action: string) => {
    const act = action.toLowerCase();
    if (act.includes('org')) {
      return {
        label: 'Organization action',
        icon: Building2,
        bg: 'bg-[#00D6A0]/10 text-[#00D6A0] border-[#00D6A0]/20',
      };
    }
    if (act.includes('role') || act.includes('user')) {
      return {
        label: 'User role updated',
        icon: Users,
        bg: 'bg-[#A855F7]/10 text-[#A855F7] border-[#A855F7]/20',
      };
    }
    if (act.includes('hackathon')) {
      return {
        label: 'Hackathon action',
        icon: Trophy,
        bg: 'bg-[#FF5C66]/10 text-[#FF5C66] border-[#FF5C66]/20',
      };
    }
    if (act.includes('login') || act.includes('auth')) {
      return {
        label: 'Authentication event',
        icon: Shield,
        bg: 'bg-[#2784FF]/10 text-[#2784FF] border-[#2784FF]/20',
      };
    }
    if (act.includes('api') || act.includes('token') || act.includes('key')) {
      return {
        label: 'API credential action',
        icon: Zap,
        bg: 'bg-[#F5B82E]/10 text-[#F5B82E] border-[#F5B82E]/20',
      };
    }
    return {
      label: 'Governance change',
      icon: Shield,
      bg: 'bg-[#2784FF]/10 text-[#2784FF] border-[#2784FF]/20',
    };
  };

  // ─── Real Organization Status Badges ─────────────────────────────────────
  const getOrgStatusBadge = (status?: string) => {
    const s = (status || 'active').toLowerCase();
    if (s === 'active') {
      return {
        label: 'Active',
        badgeClass: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
      };
    }
    if (s === 'suspended') {
      return {
        label: 'Suspended',
        badgeClass: 'bg-rose-500/10 text-rose-400 border-rose-500/30',
      };
    }
    if (s === 'archived') {
      return {
        label: 'Archived',
        badgeClass: 'bg-slate-500/10 text-slate-400 border-slate-500/30',
      };
    }
    return {
      label: s.charAt(0).toUpperCase() + s.slice(1),
      badgeClass: 'bg-blue-500/10 text-blue-400 border-blue-500/30',
    };
  };

  // ─── Service Telemetry Status Component ──────────────────────────────────
  const renderServiceStatus = (svc?: { status: string; latency_ms?: number | null }) => {
    const status = svc?.status || 'unknown';
    if (status === 'healthy') {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-[#00D6A0]/10 text-[#00D6A0] border border-[#00D6A0]/30">
          <span className="w-1.5 h-1.5 rounded-full bg-[#00D6A0]" />
          <span>Healthy</span>
        </span>
      );
    }
    if (status === 'degraded') {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-amber-500/10 text-amber-400 border border-amber-500/30">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
          <span>Degraded</span>
        </span>
      );
    }
    if (status === 'unhealthy') {
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-rose-500/10 text-rose-400 border border-rose-500/30">
          <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
          <span>Unhealthy</span>
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-slate-500/10 text-slate-400 border border-slate-500/30">
        <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />
        <span>Unknown</span>
      </span>
    );
  };

  // ─── Format Last Updated string ───────────────────────────────────────────
  const lastUpdatedString = useMemo(() => {
    if (!lastUpdated) return '—';
    return (
      lastUpdated.toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        hour12: true,
      }) +
      ', ' +
      lastUpdated.toLocaleDateString([], {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      })
    );
  }, [lastUpdated]);

  return (
    <div className="space-y-6 pb-8">
      {/* ─── 1. Page Header ─── */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-[#F3F6FC]">
            Platform Overview
          </h1>
          <p className="text-xs sm:text-sm text-[#91A4BE] mt-1">
            Real-time platform activity, asynchronous AI evaluations, and infrastructure telemetry.
          </p>
        </div>

        {/* Right side: Timestamp & Refresh */}
        <div className="flex items-center gap-3 self-start sm:self-auto">
          {lastUpdated && (
            <span className="text-xs text-[#91A4BE]">
              Last updated {lastUpdatedString}
            </span>
          )}
          <button
            type="button"
            onClick={() => loadData(true)}
            disabled={loading || refreshing}
            aria-label="Refresh dashboard data"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-[#F3F6FC] bg-[#0D1A2B] hover:bg-[#112139] border border-[#24364D] rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw
              className={`w-3.5 h-3.5 ${
                loading || refreshing ? 'animate-spin text-[#2784FF]' : 'text-[#91A4BE]'
              }`}
            />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Error Notice */}
      {error && (
        <div className="p-4 bg-[#FF5C66]/10 border border-[#FF5C66]/30 rounded-xl text-xs text-[#FF5C66] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
          <button
            type="button"
            onClick={() => loadData(true)}
            className="underline font-semibold hover:text-white transition-colors"
          >
            Retry
          </button>
        </div>
      )}

      {/* ─── 2. Row 1: Platform Entities KPI Cards (4 Columns) ─── */}
      <section aria-labelledby="primary-metrics-heading">
        <h2 id="primary-metrics-heading" className="sr-only">
          Platform Primary Metrics
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {loading ? (
            <>
              <KPISkeleton />
              <KPISkeleton />
              <KPISkeleton />
              <KPISkeleton />
            </>
          ) : (
            <>
              {/* Card 1: Total Users */}
              <Link
                href="/admin/users"
                className="group relative p-4 sm:p-5 rounded-2xl bg-gradient-to-b from-[#0D1A2B] to-[#0A1424] border border-[#24364D] hover:border-[#2784FF]/60 hover:shadow-[0_8px_30px_-6px_rgba(39,132,255,0.22)] transition-all duration-200 hover:-translate-y-0.5 flex flex-col justify-between shadow-card overflow-hidden before:absolute before:inset-x-0 before:top-0 before:h-px before:bg-gradient-to-r before:from-transparent before:via-white/[0.12] before:to-transparent"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Users className="w-4 h-4 text-[#2784FF] shrink-0" />
                    <span className="text-sm font-medium text-white tracking-tight">
                      Total Users
                    </span>
                  </div>
                  <ArrowRight className="w-3.5 h-3.5 text-text-muted opacity-0 group-hover:opacity-100 transition-opacity" />
                </div>
                <div className="flex items-end justify-between gap-3 mt-4">
                  <div className="min-w-0">
                    <div className="text-xs text-[#91A4BE] whitespace-nowrap">
                      Platform accounts
                    </div>
                    <div className="text-2xl sm:text-[28px] font-bold tracking-tight text-white mt-1 leading-none tabular-nums whitespace-nowrap">
                      {counts?.total_users !== undefined
                        ? counts.total_users.toLocaleString()
                        : '0'}
                    </div>
                  </div>
                  <div className="shrink-0">
                    <Sparkline
                      color="#2784FF"
                      gradientId="spark-users"
                      data={sparklineData.users}
                      width={96}
                      height={36}
                    />
                  </div>
                </div>
              </Link>

              {/* Card 2: Organizations */}
              <Link
                href="/admin/organizations"
                className="group relative p-4 sm:p-5 rounded-2xl bg-gradient-to-b from-[#0D1A2B] to-[#0A1424] border border-[#24364D] hover:border-[#A855F7]/60 hover:shadow-[0_8px_30px_-6px_rgba(168,85,247,0.22)] transition-all duration-200 hover:-translate-y-0.5 flex flex-col justify-between shadow-card overflow-hidden before:absolute before:inset-x-0 before:top-0 before:h-px before:bg-gradient-to-r before:from-transparent before:via-white/[0.12] before:to-transparent"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Building2 className="w-4 h-4 text-[#A855F7] shrink-0" />
                    <span className="text-sm font-medium text-white tracking-tight">
                      Organizations
                    </span>
                  </div>
                  <ArrowRight className="w-3.5 h-3.5 text-text-muted opacity-0 group-hover:opacity-100 transition-opacity" />
                </div>
                <div className="flex items-end justify-between gap-3 mt-4">
                  <div className="min-w-0">
                    <div className="text-xs text-[#91A4BE] whitespace-nowrap">
                      Registered tenants
                    </div>
                    <div className="text-2xl sm:text-[28px] font-bold tracking-tight text-white mt-1 leading-none tabular-nums whitespace-nowrap">
                      {counts?.total_organizations !== undefined
                        ? counts.total_organizations.toLocaleString()
                        : '0'}
                    </div>
                  </div>
                  <div className="shrink-0">
                    <Sparkline
                      color="#A855F7"
                      gradientId="spark-orgs"
                      data={sparklineData.orgs}
                      width={96}
                      height={36}
                    />
                  </div>
                </div>
              </Link>

              {/* Card 3: Active Hackathons */}
              <Link
                href="/admin/hackathons"
                className="group relative p-4 sm:p-5 rounded-2xl bg-gradient-to-b from-[#0D1A2B] to-[#0A1424] border border-[#24364D] hover:border-[#F5B82E]/60 hover:shadow-[0_8px_30px_-6px_rgba(245,184,46,0.22)] transition-all duration-200 hover:-translate-y-0.5 flex flex-col justify-between shadow-card overflow-hidden before:absolute before:inset-x-0 before:top-0 before:h-px before:bg-gradient-to-r before:from-transparent before:via-white/[0.12] before:to-transparent"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Trophy className="w-4 h-4 text-[#F5B82E] shrink-0" />
                    <span className="text-sm font-medium text-white tracking-tight">
                      Active Hackathons
                    </span>
                  </div>
                  <ArrowRight className="w-3.5 h-3.5 text-text-muted opacity-0 group-hover:opacity-100 transition-opacity" />
                </div>
                <div className="flex items-end justify-between gap-3 mt-4">
                  <div className="min-w-0">
                    <div className="text-xs text-[#91A4BE] whitespace-nowrap">
                      {counts?.total_hackathons !== undefined
                        ? `${counts.total_hackathons.toLocaleString()} total registered`
                        : 'Competitions'}
                    </div>
                    <div className="text-2xl sm:text-[28px] font-bold tracking-tight text-white mt-1 leading-none tabular-nums whitespace-nowrap">
                      {counts?.active_hackathons !== undefined
                        ? counts.active_hackathons.toLocaleString()
                        : counts?.total_hackathons !== undefined
                        ? counts.total_hackathons.toLocaleString()
                        : '0'}
                    </div>
                  </div>
                  <div className="shrink-0">
                    <Sparkline
                      color="#F5B82E"
                      gradientId="spark-hackathons"
                      data={sparklineData.hackathons}
                      width={96}
                      height={36}
                    />
                  </div>
                </div>
              </Link>

              {/* Card 4: Project Submissions */}
              <Link
                href="/admin/hackathons"
                className="group relative p-4 sm:p-5 rounded-2xl bg-gradient-to-b from-[#0D1A2B] to-[#0A1424] border border-[#24364D] hover:border-[#00D6A0]/60 hover:shadow-[0_8px_30px_-6px_rgba(0,214,160,0.22)] transition-all duration-200 hover:-translate-y-0.5 flex flex-col justify-between shadow-card overflow-hidden before:absolute before:inset-x-0 before:top-0 before:h-px before:bg-gradient-to-r before:from-transparent before:via-white/[0.12] before:to-transparent"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <FileCode className="w-4 h-4 text-[#00D6A0] shrink-0" />
                    <span className="text-sm font-medium text-white tracking-tight">
                      Project Submissions
                    </span>
                  </div>
                  <ArrowRight className="w-3.5 h-3.5 text-text-muted opacity-0 group-hover:opacity-100 transition-opacity" />
                </div>
                <div className="flex items-end justify-between gap-3 mt-4">
                  <div className="min-w-0">
                    <div className="text-xs text-[#91A4BE] whitespace-nowrap">
                      Repositories linked
                    </div>
                    <div className="text-2xl sm:text-[28px] font-bold tracking-tight text-white mt-1 leading-none tabular-nums whitespace-nowrap">
                      {counts?.total_submissions !== undefined
                        ? counts.total_submissions.toLocaleString()
                        : '0'}
                    </div>
                  </div>
                  <div className="shrink-0">
                    <Sparkline
                      color="#00D6A0"
                      gradientId="spark-submissions"
                      data={sparklineData.submissions}
                      width={96}
                      height={36}
                    />
                  </div>
                </div>
              </Link>
            </>
          )}
        </div>
      </section>

      {/* ─── 3. Row 2: AI Operations & Pipeline Health Cards (PRD §4.1 & §4.6) ─── */}
      <section aria-labelledby="ai-operations-metrics-heading">
        <h2 id="ai-operations-metrics-heading" className="sr-only">
          AI Operations & Pipeline Health Metrics
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {loading ? (
            <>
              <KPISkeleton />
              <KPISkeleton />
              <KPISkeleton />
              <KPISkeleton />
            </>
          ) : (
            <>
              {/* AI Card 1: Completed Evaluations */}
              <Link
                href="/admin/ai-operations"
                className="group relative p-4 sm:p-5 rounded-2xl bg-gradient-to-b from-[#0D1A2B] to-[#0A1424] border border-[#24364D] hover:border-[#00D6A0]/60 hover:shadow-[0_8px_30px_-6px_rgba(0,214,160,0.22)] transition-all duration-200 hover:-translate-y-0.5 flex flex-col justify-between shadow-card overflow-hidden before:absolute before:inset-x-0 before:top-0 before:h-px before:bg-gradient-to-r before:from-transparent before:via-white/[0.12] before:to-transparent"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 text-[#00D6A0] shrink-0" />
                    <span className="text-sm font-medium text-white tracking-tight">
                      Evaluations Completed
                    </span>
                  </div>
                  <ArrowRight className="w-3.5 h-3.5 text-text-muted opacity-0 group-hover:opacity-100 transition-opacity" />
                </div>
                <div className="flex items-end justify-between gap-3 mt-4">
                  <div className="min-w-0">
                    <div className="text-xs text-[#91A4BE] whitespace-nowrap">
                      Scored & evidence indexed
                    </div>
                    <div className="text-2xl sm:text-[28px] font-bold tracking-tight text-white mt-1 leading-none tabular-nums whitespace-nowrap">
                      {counts?.evaluations_completed !== undefined
                        ? counts.evaluations_completed.toLocaleString()
                        : '0'}
                    </div>
                  </div>
                  <div className="shrink-0">
                    <Sparkline
                      color="#00D6A0"
                      gradientId="spark-evals-done"
                      data={sparklineData.evaluations}
                      width={96}
                      height={36}
                    />
                  </div>
                </div>
              </Link>

              {/* AI Card 2: Queued / Running Jobs */}
              <Link
                href="/admin/ai-operations"
                className="group relative p-4 sm:p-5 rounded-2xl bg-gradient-to-b from-[#0D1A2B] to-[#0A1424] border border-[#24364D] hover:border-[#2784FF]/60 hover:shadow-[0_8px_30px_-6px_rgba(39,132,255,0.22)] transition-all duration-200 hover:-translate-y-0.5 flex flex-col justify-between shadow-card overflow-hidden before:absolute before:inset-x-0 before:top-0 before:h-px before:bg-gradient-to-r before:from-transparent before:via-white/[0.12] before:to-transparent"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Clock className="w-4 h-4 text-[#2784FF] shrink-0" />
                    <span className="text-sm font-medium text-white tracking-tight">
                      Queued / Running
                    </span>
                  </div>
                  <ArrowRight className="w-3.5 h-3.5 text-text-muted opacity-0 group-hover:opacity-100 transition-opacity" />
                </div>
                <div className="flex items-end justify-between gap-3 mt-4">
                  <div className="min-w-0">
                    <div className="text-xs text-[#91A4BE] whitespace-nowrap">
                      Asynchronous queue depth
                    </div>
                    <div className="text-2xl sm:text-[28px] font-bold tracking-tight text-white mt-1 leading-none tabular-nums whitespace-nowrap">
                      {counts?.evaluations_running !== undefined
                        ? counts.evaluations_running.toLocaleString()
                        : '0'}
                    </div>
                  </div>
                  <div className="shrink-0">
                    <div className="w-20 h-9 flex items-center justify-end">
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono font-medium bg-[#2784FF]/10 text-[#2784FF] border border-[#2784FF]/25">
                        In Pipeline
                      </span>
                    </div>
                  </div>
                </div>
              </Link>

              {/* AI Card 3: Evaluation Failures */}
              <Link
                href="/admin/ai-operations"
                className="group relative p-4 sm:p-5 rounded-2xl bg-gradient-to-b from-[#0D1A2B] to-[#0A1424] border border-[#24364D] hover:border-[#FF5C66]/60 hover:shadow-[0_8px_30px_-6px_rgba(255,92,102,0.22)] transition-all duration-200 hover:-translate-y-0.5 flex flex-col justify-between shadow-card overflow-hidden before:absolute before:inset-x-0 before:top-0 before:h-px before:bg-gradient-to-r before:from-transparent before:via-white/[0.12] before:to-transparent"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <XCircle className="w-4 h-4 text-[#FF5C66] shrink-0" />
                    <span className="text-sm font-medium text-white tracking-tight">
                      Evaluation Failures
                    </span>
                  </div>
                  <ArrowRight className="w-3.5 h-3.5 text-text-muted opacity-0 group-hover:opacity-100 transition-opacity" />
                </div>
                <div className="flex items-end justify-between gap-3 mt-4">
                  <div className="min-w-0">
                    <div className="text-xs text-[#91A4BE] whitespace-nowrap">
                      Retry / dead-lettered
                    </div>
                    <div className="text-2xl sm:text-[28px] font-bold tracking-tight text-white mt-1 leading-none tabular-nums whitespace-nowrap">
                      {counts?.evaluations_failed !== undefined
                        ? counts.evaluations_failed.toLocaleString()
                        : '0'}
                    </div>
                  </div>
                  <div className="shrink-0">
                    <div className="w-20 h-9 flex items-center justify-end">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-mono font-medium border ${
                          (counts?.evaluations_failed || 0) > 0
                            ? 'bg-[#FF5C66]/10 text-[#FF5C66] border-[#FF5C66]/30'
                            : 'bg-[#00D6A0]/10 text-[#00D6A0] border-[#00D6A0]/30'
                        }`}
                      >
                        {(counts?.evaluations_failed || 0) > 0 ? 'Needs Attention' : 'Zero Errors'}
                      </span>
                    </div>
                  </div>
                </div>
              </Link>

              {/* AI Card 4: Evaluation Failure Rate */}
              <Link
                href="/admin/ai-operations"
                className="group relative p-4 sm:p-5 rounded-2xl bg-gradient-to-b from-[#0D1A2B] to-[#0A1424] border border-[#24364D] hover:border-[#F5B82E]/60 hover:shadow-[0_8px_30px_-6px_rgba(245,184,46,0.22)] transition-all duration-200 hover:-translate-y-0.5 flex flex-col justify-between shadow-card overflow-hidden before:absolute before:inset-x-0 before:top-0 before:h-px before:bg-gradient-to-r before:from-transparent before:via-white/[0.12] before:to-transparent"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="w-4 h-4 text-[#F5B82E] shrink-0" />
                    <span className="text-sm font-medium text-white tracking-tight">
                      Failure Rate
                    </span>
                  </div>
                  <ArrowRight className="w-3.5 h-3.5 text-text-muted opacity-0 group-hover:opacity-100 transition-opacity" />
                </div>
                <div className="flex items-end justify-between gap-3 mt-4">
                  <div className="min-w-0">
                    <div className="text-xs text-[#91A4BE] whitespace-nowrap">
                      Completed vs failed ratio
                    </div>
                    <div className="text-2xl sm:text-[28px] font-bold tracking-tight text-white mt-1 leading-none tabular-nums whitespace-nowrap">
                      {failureRate}
                    </div>
                  </div>
                  <div className="shrink-0">
                    <div className="w-20 h-9 flex items-center justify-end">
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono font-medium bg-[#F5B82E]/10 text-[#F5B82E] border border-[#F5B82E]/25">
                        Dynamic SLA
                      </span>
                    </div>
                  </div>
                </div>
              </Link>
            </>
          )}
        </div>
      </section>

      {/* ─── 4. Middle Row: Platform Activity Trends (60%) + Infrastructure Health (40%) ─── */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Panel Left: Platform Activity Trends (approx 60%) */}
        <section
          aria-labelledby="trends-heading"
          className="lg:col-span-7 p-6 rounded-2xl bg-[#0D1A2B] border border-[#24364D] shadow-card flex flex-col justify-between"
        >
          {/* Header & Controls */}
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2">
            <div>
              <h2
                id="trends-heading"
                className="text-base font-semibold text-[#F3F6FC] flex items-center gap-2"
              >
                <LineChartIcon className="w-4 h-4 text-[#2784FF]" />
                <span>Platform Activity Trends</span>
              </h2>
              <p className="text-xs text-[#91A4BE] mt-0.5">
                Aggregated daily volume over the selected timeframe ({trendPeriod})
              </p>
            </div>

            {/* Timeframe Buttons */}
            <div className="flex items-center gap-1 bg-[#112139] p-1 rounded-xl border border-[#24364D] self-start sm:self-auto">
              {(['7D', '30D', '90D', '1Y'] as const).map((period) => (
                <button
                  key={period}
                  type="button"
                  onClick={() => handlePeriodChange(period)}
                  className={`px-3 py-1 text-xs font-semibold rounded-lg transition-all ${
                    trendPeriod === period
                      ? 'bg-[#2784FF] text-white shadow-md'
                      : 'text-[#91A4BE] hover:text-[#F3F6FC]'
                  }`}
                >
                  {period}
                </button>
              ))}
            </div>
          </div>

          {/* Area Chart Area */}
          <div className="mt-4 h-[280px] w-full">
            {loading ? (
              <div className="w-full h-full bg-[#112139]/40 rounded-xl animate-pulse" />
            ) : trendPoints.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center">
                <LineChartIcon className="w-8 h-8 text-[#91A4BE] mb-2 opacity-50" />
                <p className="text-xs font-medium text-[#F3F6FC]">
                  No historical trend data available
                </p>
                <p className="text-[11px] text-[#91A4BE] mt-1 max-w-xs">
                  Historical platform time-series metrics will appear as events are recorded.
                </p>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={trendPoints}
                  margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
                >
                  <defs>
                    <linearGradient id="colorUsers" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#2784FF" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#2784FF" stopOpacity={0.0} />
                    </linearGradient>
                    <linearGradient id="colorOrgs" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#A855F7" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#A855F7" stopOpacity={0.0} />
                    </linearGradient>
                    <linearGradient id="colorHackathons" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#F97316" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#F97316" stopOpacity={0.0} />
                    </linearGradient>
                    <linearGradient id="colorSubs" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#00D6A0" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#00D6A0" stopOpacity={0.0} />
                    </linearGradient>
                    <linearGradient id="colorEvals" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#EAB308" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#EAB308" stopOpacity={0.0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid
                    stroke="#24364D"
                    strokeDasharray="0"
                    vertical={false}
                    opacity={0.6}
                  />
                  <XAxis
                    dataKey="date"
                    stroke="#5A7294"
                    fontSize={11}
                    tickLine={false}
                    axisLine={{ stroke: '#24364D' }}
                  />
                  <YAxis
                    stroke="#5A7294"
                    fontSize={11}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(v) => v.toLocaleString()}
                  />
                  <Tooltip content={<ChartTooltip />} />
                  <Area
                    type="monotone"
                    dataKey="users"
                    name="New Users"
                    stroke="#2784FF"
                    strokeWidth={2}
                    fillOpacity={1}
                    fill="url(#colorUsers)"
                  />
                  <Area
                    type="monotone"
                    dataKey="organizations"
                    name="New Organizations"
                    stroke="#A855F7"
                    strokeWidth={2}
                    fillOpacity={1}
                    fill="url(#colorOrgs)"
                  />
                  <Area
                    type="monotone"
                    dataKey="hackathons"
                    name="Hackathons"
                    stroke="#F97316"
                    strokeWidth={2}
                    fillOpacity={1}
                    fill="url(#colorHackathons)"
                  />
                  <Area
                    type="monotone"
                    dataKey="submissions"
                    name="Submissions"
                    stroke="#00D6A0"
                    strokeWidth={2}
                    fillOpacity={1}
                    fill="url(#colorSubs)"
                  />
                  <Area
                    type="monotone"
                    dataKey="evaluations"
                    name="Evaluations"
                    stroke="#EAB308"
                    strokeWidth={2}
                    fillOpacity={1}
                    fill="url(#colorEvals)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Chart Legend */}
          <div className="flex flex-wrap items-center justify-center gap-4 sm:gap-6 pt-3 border-t border-[#24364D]/60 text-xs">
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-[#2784FF]" />
              <span className="text-[#91A4BE]">New Users</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-[#A855F7]" />
              <span className="text-[#91A4BE]">New Organizations</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-[#F97316]" />
              <span className="text-[#91A4BE]">Hackathons</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-[#00D6A0]" />
              <span className="text-[#91A4BE]">Submissions</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-[#EAB308]" />
              <span className="text-[#91A4BE]">Evaluations</span>
            </div>
          </div>
        </section>

        {/* Panel Right: Infrastructure Health (approx 40%) */}
        <section
          aria-labelledby="infrastructure-heading"
          className="lg:col-span-5 p-6 rounded-2xl bg-[#0D1A2B] border border-[#24364D] shadow-card flex flex-col justify-between"
        >
          {/* Header */}
          <div className="flex items-center justify-between pb-2">
            <div>
              <h2
                id="infrastructure-heading"
                className="text-base font-semibold text-[#F3F6FC] flex items-center gap-2"
              >
                <Server className="w-4 h-4 text-[#2784FF]" />
                <span>Infrastructure Health</span>
              </h2>
              <p className="text-xs text-[#91A4BE] mt-0.5">
                Live dependency probes & service availability
              </p>
            </div>
            <Link
              href="/admin/system-health"
              className="text-xs text-[#2784FF] hover:underline font-medium flex items-center gap-1"
            >
              <span>View All</span>
              <span>→</span>
            </Link>
          </div>

          {/* Services List */}
          <div className="space-y-3 mt-4">
            {/* Service 1: FastAPI Core */}
            <div className="flex items-center justify-between p-2.5 rounded-xl hover:bg-[#112139]/40 transition-colors">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-[#00D6A0]/15 text-[#00D6A0] flex items-center justify-center shrink-0">
                  <Zap className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-xs font-semibold text-[#F3F6FC]">
                    FastAPI Core
                  </h3>
                  <p className="text-[11px] text-[#91A4BE]">
                    Primary API service
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                {renderServiceStatus(health?.services?.api)}
                <span className="text-xs font-mono text-[#91A4BE] w-14 text-right">
                  {health?.services?.api?.latency_ms !== undefined
                    ? `${health.services.api.latency_ms} ms`
                    : '—'}
                </span>
              </div>
            </div>

            {/* Service 2: PostgreSQL Database */}
            <div className="flex items-center justify-between p-2.5 rounded-xl hover:bg-[#112139]/40 transition-colors">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-[#2784FF]/15 text-[#2784FF] flex items-center justify-center shrink-0">
                  <Database className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-xs font-semibold text-[#F3F6FC]">
                    PostgreSQL 16
                  </h3>
                  <p className="text-[11px] text-[#91A4BE]">Primary relational database</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                {renderServiceStatus(health?.services?.database)}
                <span className="text-xs font-mono text-[#91A4BE] w-14 text-right">
                  {health?.services?.database?.latency_ms !== undefined && health.services.database.latency_ms !== null
                    ? `${health.services.database.latency_ms} ms`
                    : '—'}
                </span>
              </div>
            </div>

            {/* Service 3: Redis */}
            <div className="flex items-center justify-between p-2.5 rounded-xl hover:bg-[#112139]/40 transition-colors">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-[#FF5C66]/15 text-[#FF5C66] flex items-center justify-center shrink-0">
                  <Layers className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-xs font-semibold text-[#F3F6FC]">Redis</h3>
                  <p className="text-[11px] text-[#91A4BE]">
                    Cache & session store
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                {renderServiceStatus(health?.services?.redis)}
                <span className="text-xs font-mono text-[#91A4BE] w-14 text-right">
                  {health?.services?.redis?.latency_ms !== undefined && health.services.redis.latency_ms !== null
                    ? `${health.services.redis.latency_ms} ms`
                    : '—'}
                </span>
              </div>
            </div>

            {/* Service 4: Celery Queue Broker */}
            <div className="flex items-center justify-between p-2.5 rounded-xl hover:bg-[#112139]/40 transition-colors">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-[#A855F7]/15 text-[#A855F7] flex items-center justify-center shrink-0">
                  <Cpu className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-xs font-semibold text-[#F3F6FC]">
                    Celery Workers
                  </h3>
                  <p className="text-[11px] text-[#91A4BE]">
                    Background evaluation broker
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                {renderServiceStatus(health?.services?.broker)}
                <span className="text-xs font-mono text-[#91A4BE] w-14 text-right">
                  {health?.services?.broker?.latency_ms !== undefined && health.services.broker.latency_ms !== null
                    ? `${health.services.broker.latency_ms} ms`
                    : '—'}
                </span>
              </div>
            </div>

            {/* Service 5: AI Provider (Ollama) - Honest Telemetry */}
            <div className="flex items-center justify-between p-2.5 rounded-xl hover:bg-[#112139]/40 transition-colors">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-[#2784FF]/15 text-[#2784FF] flex items-center justify-center shrink-0">
                  <Bot className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-xs font-semibold text-[#F3F6FC]">
                    AI Inference (Ollama)
                  </h3>
                  <p className="text-[11px] text-[#91A4BE]">
                    {health?.services?.ollama?.details || 'Local inference server'}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                {renderServiceStatus(health?.services?.ollama)}
                <span className="text-xs font-mono text-[#91A4BE] w-14 text-right">
                  {health?.services?.ollama?.latency_ms !== undefined && health.services.ollama.latency_ms !== null
                    ? `${health.services.ollama.latency_ms} ms`
                    : 'N/A'}
                </span>
              </div>
            </div>
          </div>
        </section>
      </div>

      {/* ─── 5. Bottom Section: Three Verification Panels ─── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Panel A: Recent Governance Activity */}
        <section
          aria-labelledby="governance-heading"
          className="p-6 rounded-2xl bg-[#0D1A2B] border border-[#24364D] shadow-card flex flex-col"
        >
          {/* Header */}
          <div className="flex items-center justify-between pb-3 border-b border-[#24364D]/40">
            <h2
              id="governance-heading"
              className="text-sm font-semibold text-[#F3F6FC] flex items-center gap-2"
            >
              <Shield className="w-4 h-4 text-[#2784FF]" />
              <span>Recent Governance Activity</span>
            </h2>
            <Link
              href="/admin/security"
              className="text-xs text-[#2784FF] hover:underline font-medium flex items-center gap-1"
            >
              <span>View All</span>
              <span>→</span>
            </Link>
          </div>

          {/* List */}
          <div className="space-y-4 mt-4">
            {loading ? (
              <PanelSkeleton rows={5} />
            ) : !dashboard?.recent_audits || dashboard.recent_audits.length === 0 ? (
              <div className="py-8 text-center text-xs text-[#91A4BE]">
                No recent governance activity.
              </div>
            ) : (
              dashboard.recent_audits.slice(0, 5).map((audit, idx) => {
                const info = getAuditInfo(audit.action);
                const Icon = info.icon;
                return (
                  <div
                    key={audit.id || idx}
                    className="flex items-center justify-between gap-3 text-xs"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <div
                        className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 border ${info.bg}`}
                      >
                        <Icon className="w-4 h-4" />
                      </div>
                      <div className="min-w-0">
                        <p className="font-semibold text-[#F3F6FC] truncate">
                          {audit.action}
                        </p>
                        <p className="text-[11px] text-[#91A4BE] truncate mt-0.5 font-mono">
                          {audit.actor_email || 'System'}
                        </p>
                      </div>
                    </div>
                    <div className="text-right shrink-0">
                      <p className="font-mono text-[11px] text-[#F3F6FC]">
                        {formatTimeOnly(audit.timestamp)}
                      </p>
                      <p className="text-[10px] text-[#91A4BE] mt-0.5">
                        {formatRelativeTime(audit.timestamp)}
                      </p>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </section>

        {/* Panel B: Recent Organizations */}
        <section
          aria-labelledby="recent-orgs-heading"
          className="p-6 rounded-2xl bg-[#0D1A2B] border border-[#24364D] shadow-card flex flex-col"
        >
          {/* Header */}
          <div className="flex items-center justify-between pb-3 border-b border-[#24364D]/40">
            <h2
              id="recent-orgs-heading"
              className="text-sm font-semibold text-[#F3F6FC] flex items-center gap-2"
            >
              <Building2 className="w-4 h-4 text-[#2784FF]" />
              <span>Recent Organizations</span>
            </h2>
            <Link
              href="/admin/organizations"
              className="text-xs text-[#2784FF] hover:underline font-medium flex items-center gap-1"
            >
              <span>View All</span>
              <span>→</span>
            </Link>
          </div>

          {/* List */}
          <div className="space-y-4 mt-4">
            {loading ? (
              <PanelSkeleton rows={5} />
            ) : recentOrgs.length === 0 ? (
              <div className="py-8 text-center text-xs text-[#91A4BE]">
                No organizations registered yet.
              </div>
            ) : (
              recentOrgs.slice(0, 5).map((org) => {
                const statusBadge = getOrgStatusBadge(org.status);
                return (
                  <Link
                    key={org.id}
                    href={`/admin/organizations/${org.id}`}
                    className="flex items-center justify-between gap-3 text-xs group"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="w-8 h-8 rounded-lg bg-[#112139] border border-[#24364D] flex items-center justify-center shrink-0 font-bold text-xs text-[#2784FF] group-hover:border-[#2784FF]/40 transition-colors">
                        {getInitials(org.name)}
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="font-semibold text-[#F3F6FC] truncate group-hover:text-[#2784FF] transition-colors">
                            {org.name}
                          </p>
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-medium border ${statusBadge.badgeClass}`}
                          >
                            {statusBadge.label}
                          </span>
                        </div>
                        <p className="text-[11px] text-[#91A4BE] truncate mt-0.5 font-mono">
                          /{org.slug}
                        </p>
                      </div>
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-[11px] text-[#F3F6FC]">
                        {org.hackathon_count} hackathon
                        {org.hackathon_count !== 1 ? 's' : ''}
                      </p>
                      <p className="text-[10px] text-[#91A4BE] mt-0.5">
                        {org.member_count} member{org.member_count !== 1 ? 's' : ''}
                      </p>
                    </div>
                  </Link>
                );
              })
            )}
          </div>
        </section>

        {/* Panel C: System Alerts */}
        <section
          aria-labelledby="alerts-heading"
          className="p-6 rounded-2xl bg-[#0D1A2B] border border-[#24364D] shadow-card flex flex-col"
        >
          {/* Header */}
          <div className="flex items-center justify-between pb-3 border-b border-[#24364D]/40">
            <h2
              id="alerts-heading"
              className="text-sm font-semibold text-[#F3F6FC] flex items-center gap-2"
            >
              <Bell className="w-4 h-4 text-[#2784FF]" />
              <span>System Alerts</span>
            </h2>
            <Link
              href="/admin/system-health"
              className="text-xs text-[#2784FF] hover:underline font-medium flex items-center gap-1"
            >
              <span>View All</span>
              <span>→</span>
            </Link>
          </div>

          {/* List */}
          <div className="space-y-4 mt-4">
            {loading ? (
              <PanelSkeleton rows={5} />
            ) : systemAlerts.length === 0 ? (
              <div className="py-8 text-center text-xs text-[#00D6A0] flex flex-col items-center justify-center gap-1.5">
                <CheckCircle2 className="w-5 h-5 opacity-80" />
                <span>All systems normal. No active operational alerts.</span>
              </div>
            ) : (
              systemAlerts.map((alert) => {
                const badgeStyle =
                  alert.severity === 'High'
                    ? 'bg-[#FF5C66]/15 text-[#FF5C66] border-[#FF5C66]/30'
                    : alert.severity === 'Medium'
                    ? 'bg-[#F5B82E]/15 text-[#F5B82E] border-[#F5B82E]/30'
                    : 'bg-[#2784FF]/15 text-[#2784FF] border-[#2784FF]/30';

                return (
                  <div
                    key={alert.id}
                    className="flex items-center justify-between gap-3 text-xs"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <span
                        className={`px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider shrink-0 border ${badgeStyle}`}
                      >
                        {alert.severity}
                      </span>
                      <div className="min-w-0">
                        {alert.href ? (
                          <Link
                            href={alert.href}
                            className="font-semibold text-[#F3F6FC] hover:text-[#2784FF] truncate block transition-colors"
                          >
                            {alert.title}
                          </Link>
                        ) : (
                          <p className="font-semibold text-[#F3F6FC] truncate">
                            {alert.title}
                          </p>
                        )}
                        <p className="text-[11px] text-[#91A4BE] truncate mt-0.5">
                          {alert.context}
                        </p>
                      </div>
                    </div>
                    <span className="font-mono text-[11px] text-[#91A4BE] shrink-0 text-right">
                      {alert.time}
                    </span>
                  </div>
                );
              })
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
