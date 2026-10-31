'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Cpu,
  Wifi,
  WifiOff,
  RefreshCw,
  Activity,
  Database,
  Layers,
  Clock,
  CheckCircle2,
  XCircle,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Zap,
  Server,
  BarChart3,
  Box,
  Settings2,
  HardDrive,
  Search,
  ArrowUpDown,
  Info,
  Timer,
  PieChart as PieChartIcon,
  Send,
  Terminal,
  Sliders,
  Copy,
  Check,
  Trash2,
  Sparkles,
  Download,
  Ban,
  CloudDownload,
} from 'lucide-react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
} from 'recharts';
import { PageHeader } from '@/components/admin/PageHeader';
import { api } from '@/lib/api-client';
import type {
  OllamaHealthResponse,
  OllamaModel,
  AiMetricsResponse,
  AdminEvalJobItem,
  ConfigurationSetting,
  CatalogModelInfo,
  ModelPullStatusResponse,
} from '@/types/api';

// ─── Helpers ───────────────────────────────────────────────────────────────

function fmtBytes(bytes: number): string {
  if (!bytes || bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function fmtDuration(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return '—';
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  if (seconds < 60) return `${seconds.toFixed(2)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = (seconds % 60).toFixed(1);
  return `${mins}m ${secs}s`;
}

function statusColor(s: string): string {
  switch (s?.toLowerCase()) {
    case 'completed':
      return 'text-status-success bg-status-success/10 border-status-success/30';
    case 'running':
      return 'text-primary bg-primary/10 border-primary/30';
    case 'queued':
      return 'text-status-warning bg-status-warning/10 border-status-warning/30';
    case 'failed':
      return 'text-status-danger bg-status-danger/10 border-status-danger/30';
    case 'cancelled':
      return 'text-text-muted bg-surface-elevated border-surface-border';
    default:
      return 'text-text-muted bg-surface-elevated border-surface-border';
  }
}

const JOB_STATUS_OPTIONS = ['', 'queued', 'running', 'completed', 'failed', 'cancelled'];

const CHART_COLORS = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899'];

// ─── Component ─────────────────────────────────────────────────────────────

export default function AiOperationsPage() {
  // ── States ──
  const [health, setHealth] = useState<OllamaHealthResponse | null>(null);
  const [healthLoading, setHealthLoading] = useState(true);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [lastSuccessfulHealthCheck, setLastSuccessfulHealthCheck] = useState<Date | null>(null);

  // Models table states
  const [models, setModels] = useState<OllamaModel[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [modelSearch, setModelSearch] = useState('');
  const [modelSortBy, setModelSortBy] = useState<'name' | 'size' | 'modified_at'>('name');
  const [modelSortOrder, setModelSortOrder] = useState<'asc' | 'desc'>('asc');
  const [selectedModel, setSelectedModel] = useState<OllamaModel | null>(null);

  // AI Metrics
  const [metrics, setMetrics] = useState<AiMetricsResponse | null>(null);
  const [metricsLoading, setMetricsLoading] = useState(true);

  // Evaluation Jobs
  const [jobs, setJobs] = useState<AdminEvalJobItem[]>([]);
  const [jobsTotal, setJobsTotal] = useState(0);
  const [jobsPage, setJobsPage] = useState(1);
  const [jobsStatusFilter, setJobsStatusFilter] = useState('');
  const [jobsLoading, setJobsLoading] = useState(true);
  const [jobsError, setJobsError] = useState<string | null>(null);

  // Tab state
  const [activeTab, setActiveTab] = useState<'overview' | 'playground' | 'lifecycle'>('overview');

  // Model Lifecycle & Catalog States
  const [catalog, setCatalog] = useState<CatalogModelInfo[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogSearch, setCatalogSearch] = useState('');
  const [pullTasks, setPullTasks] = useState<ModelPullStatusResponse[]>([]);
  const [pullingModelName, setPullingModelName] = useState<string | null>(null);
  const [lifecycleMessage, setLifecycleMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [modelToDelete, setModelToDelete] = useState<string | null>(null);
  const [deletingModel, setDeletingModel] = useState(false);

  // Playground states
  const [playgroundModel, setPlaygroundModel] = useState<string>('');
  const [playgroundPrompt, setPlaygroundPrompt] = useState<string>('');
  const [playgroundTemperature, setPlaygroundTemperature] = useState<number>(0.7);
  const [playgroundMaxTokens, setPlaygroundMaxTokens] = useState<number>(2048);
  const [playgroundLoading, setPlaygroundLoading] = useState<boolean>(false);
  const [playgroundResponse, setPlaygroundResponse] = useState<any | null>(null);
  const [playgroundError, setPlaygroundError] = useState<string | null>(null);
  const [copiedResponse, setCopiedResponse] = useState<boolean>(false);

  // AI Config Settings
  const [aiConfig, setAiConfig] = useState<ConfigurationSetting[]>([]);
  const [configLoading, setConfigLoading] = useState(true);

  const JOB_LIMIT = 10;

  // Sync default playground model when models load
  useEffect(() => {
    if (models.length > 0 && !playgroundModel) {
      setPlaygroundModel(models[0].name);
    }
  }, [models, playgroundModel]);

  // ── Data Loaders ──

  const loadHealthAndModels = useCallback(async () => {
    setHealthLoading(true);
    setHealthError(null);
    setModelsLoading(true);
    setModelsError(null);

    try {
      const data = await api.getOllamaHealth();
      setHealth(data);
      if (data.reachable) {
        setLastSuccessfulHealthCheck(new Date());
        // Use installed_models from health response or fetch separately if needed
        const modelList = data.installed_models ?? data.models ?? [];
        setModels(modelList);
      } else {
        setModels([]);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to probe Ollama service';
      setHealthError(msg);
      setModelsError(msg);
    } finally {
      setHealthLoading(false);
      setModelsLoading(false);
    }
  }, []);

  // Load catalog
  const loadCatalog = useCallback(async () => {
    setCatalogLoading(true);
    try {
      const data = await api.getModelCatalog();
      setCatalog(data);
    } catch {
      // Graceful degradation
    } finally {
      setCatalogLoading(false);
    }
  }, []);

  // Poll active pull status
  const loadPullStatus = useCallback(async () => {
    try {
      const tasks = await api.getPullStatus();
      setPullTasks(tasks);
      // If any active, keep polling
      const hasActive = tasks.some((t) => ['queued', 'downloading', 'verifying', 'cancelling'].includes(t.status));
      if (!hasActive && pullingModelName) {
        setPullingModelName(null);
        loadHealthAndModels();
      }
    } catch {
      // Degrade gracefully
    }
  }, [pullingModelName, loadHealthAndModels]);

  useEffect(() => {
    loadPullStatus();
    const interval = setInterval(loadPullStatus, 3000);
    return () => clearInterval(interval);
  }, [loadPullStatus]);

  const loadMetrics = useCallback(async () => {
    setMetricsLoading(true);
    try {
      const data = await api.getAiMetrics();
      setMetrics(data);
    } catch {
      // Degrade gracefully; counters will display —
    } finally {
      setMetricsLoading(false);
    }
  }, []);

  const loadJobs = useCallback(async () => {
    setJobsLoading(true);
    setJobsError(null);
    try {
      const data = await api.getAdminEvaluationJobs({
        page: jobsPage,
        limit: JOB_LIMIT,
        status: jobsStatusFilter || undefined,
      });
      setJobs(data.items);
      setJobsTotal(data.total);
    } catch (err: unknown) {
      setJobsError(err instanceof Error ? err.message : 'Failed to load evaluation jobs');
      setJobs([]);
      setJobsTotal(0);
    } finally {
      setJobsLoading(false);
    }
  }, [jobsPage, jobsStatusFilter]);

  const loadConfig = useCallback(async () => {
    setConfigLoading(true);
    try {
      const all = await api.getConfigurationSettings();
      setAiConfig(all.filter((s: ConfigurationSetting) => s.key.startsWith('ai.')));
    } catch {
      // Degrade gracefully
    } finally {
      setConfigLoading(false);
    }
  }, []);

  // Fetch all parallel independent blocks
  const handleRefresh = useCallback(() => {
    loadHealthAndModels();
    loadMetrics();
    loadJobs();
    loadConfig();
  }, [loadHealthAndModels, loadMetrics, loadJobs, loadConfig]);

  useEffect(() => {
    loadHealthAndModels();
    loadMetrics();
    loadConfig();
  }, [loadHealthAndModels, loadMetrics, loadConfig]);

  useEffect(() => {
    loadJobs();
  }, [loadJobs]);

  // ── Filtered & Sorted Models ──
  const filteredAndSortedModels = useMemo(() => {
    let result = [...models];

    if (modelSearch.trim()) {
      const q = modelSearch.toLowerCase();
      result = result.filter((m) => m.name.toLowerCase().includes(q));
    }

    result.sort((a, b) => {
      let comparison = 0;
      if (modelSortBy === 'name') {
        comparison = a.name.localeCompare(b.name);
      } else if (modelSortBy === 'size') {
        comparison = (a.size || 0) - (b.size || 0);
      } else if (modelSortBy === 'modified_at') {
        const da = a.modified_at ? new Date(a.modified_at).getTime() : 0;
        const db = b.modified_at ? new Date(b.modified_at).getTime() : 0;
        comparison = da - db;
      }
      return modelSortOrder === 'asc' ? comparison : -comparison;
    });

    return result;
  }, [models, modelSearch, modelSortBy, modelSortOrder]);

  // ── Metrics Chart Data Preparation ──
  const providerModelData = useMemo(() => {
    if (!metrics) return [];
    const breakdown = metrics.provider_model_breakdown ?? metrics.provider_calls ?? {};
    return Object.entries(breakdown).map(([key, val]) => ({
      name: key.replace(/_/g, ' '),
      calls: Number(val),
    }));
  }, [metrics]);

  const jobStatusData = useMemo(() => {
    if (!metrics?.jobs_by_status) return [];
    return Object.entries(metrics.jobs_by_status).map(([status, count]) => ({
      name: status.charAt(0).toUpperCase() + status.slice(1),
      value: Number(count),
    }));
  }, [metrics]);

  const totalJobPages = Math.max(1, Math.ceil(jobsTotal / JOB_LIMIT));

  // ── Playground Handlers ──
  const handleExecutePlayground = async () => {
    if (!playgroundPrompt.trim()) {
      setPlaygroundError('Prompt cannot be empty.');
      return;
    }
    if (!playgroundModel) {
      setPlaygroundError('Please select an installed model.');
      return;
    }

    setPlaygroundLoading(true);
    setPlaygroundError(null);
    setPlaygroundResponse(null);

    try {
      const res = await api.runAiPlayground({
        model: playgroundModel,
        prompt: playgroundPrompt,
        temperature: playgroundTemperature,
        max_tokens: playgroundMaxTokens,
      });

      if (!res.success) {
        setPlaygroundError(res.error || 'Playground execution failed.');
      } else {
        setPlaygroundResponse(res);
      }
    } catch (err: unknown) {
      setPlaygroundError(err instanceof Error ? err.message : 'Failed to connect to playground endpoint.');
    } finally {
      setPlaygroundLoading(false);
    }
  };

  const handleCopyResponse = () => {
    if (playgroundResponse?.response) {
      navigator.clipboard.writeText(playgroundResponse.response);
      setCopiedResponse(true);
      setTimeout(() => setCopiedResponse(false), 2000);
    }
  };

  // ── Model Lifecycle Handlers ──
  const handlePullModel = async (modelName: string) => {
    setPullingModelName(modelName);
    setLifecycleMessage(null);
    try {
      const res = await api.pullModel(modelName);
      setLifecycleMessage({
        type: 'success',
        text: `Model pull initiated: ${res.model_name}. Download running in background.`,
      });
      loadPullStatus();
    } catch (err: unknown) {
      setLifecycleMessage({
        type: 'error',
        text: err instanceof Error ? err.message : 'Failed to initiate model pull',
      });
      setPullingModelName(null);
    }
  };

  const handleCancelPull = async (taskId: string) => {
    try {
      await api.cancelModelPull(taskId);
      setLifecycleMessage({
        type: 'success',
        text: 'Cancellation requested for active model pull.',
      });
      loadPullStatus();
    } catch (err: unknown) {
      setLifecycleMessage({
        type: 'error',
        text: err instanceof Error ? err.message : 'Failed to cancel model pull',
      });
    }
  };

  const handleConfirmDeleteModel = async () => {
    if (!modelToDelete) return;
    setDeletingModel(true);
    setLifecycleMessage(null);
    try {
      const res = await api.deleteModel(modelToDelete);
      setLifecycleMessage({
        type: 'success',
        text: res.message || `Model "${modelToDelete}" deleted successfully from Ollama storage.`,
      });
      setModelToDelete(null);
      await loadHealthAndModels();
    } catch (err: unknown) {
      setLifecycleMessage({
        type: 'error',
        text: err instanceof Error ? err.message : 'Failed to delete model',
      });
    } finally {
      setDeletingModel(false);
    }
  };

  const filteredCatalog = useMemo(() => {
    if (!catalogSearch.trim()) return catalog;
    const q = catalogSearch.toLowerCase();
    return catalog.filter(
      (m) =>
        m.name.toLowerCase().includes(q) ||
        m.description.toLowerCase().includes(q) ||
        m.category.toLowerCase().includes(q) ||
        m.tags.some((t) => t.toLowerCase().includes(q))
    );
  }, [catalog, catalogSearch]);

  const EXAMPLE_PROMPTS = [
    {
      title: 'Hackathon Submission Rubric Evaluation',
      prompt: `You are an expert technical hackathon judge evaluating a decentralized IoT tracking submission.
Analyze the implementation based on:
1. Technical Complexity & Architecture (Score 1-10)
2. Innovation & Practical Impact (Score 1-10)
3. Code Cleanliness and Documentation (Score 1-10)

Provide a constructive summary and final verdict.`,
    },
    {
      title: 'Security & Vulnerability Audit',
      prompt: `Audit the following backend authentication function for common vulnerabilities:
- SSRF vectors
- SQL / NoSQL Injection
- Timing attacks and token leakage

Suggest concrete remediation steps.`,
    },
    {
      title: 'Short Latency & Token Velocity Probe',
      prompt: `Respond with a concise, 3-sentence summary of how Retrieval-Augmented Generation (RAG) improves LLM factual reliability in domain-specific tasks.`,
    },
  ];

  return (
    <div className="space-y-6">
      {/* ── Top Header ── */}
      <PageHeader
        title="AI Operations"
        description="Monitor Ollama connectivity, manage local model registry, review inference execution metrics, and monitor evaluation queues."
      >
        <button
          onClick={handleRefresh}
          className="inline-flex items-center gap-2 px-3 py-2 text-xs font-medium text-text-secondary hover:text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors cursor-pointer"
        >
          <RefreshCw
            className={`w-3.5 h-3.5 ${
              healthLoading || metricsLoading || jobsLoading ? 'animate-spin' : ''
            }`}
          />
          Refresh All
        </button>
      </PageHeader>

      {/* ── Tabs Navigation ── */}
      <div className="flex items-center gap-2 border-b border-surface-border pb-3">
        <button
          onClick={() => setActiveTab('overview')}
          className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
            activeTab === 'overview'
              ? 'bg-primary text-white shadow-sm'
              : 'text-text-muted hover:text-text-primary hover:bg-surface-elevated'
          }`}
        >
          <Activity className="w-3.5 h-3.5" />
          Infrastructure Overview
        </button>
        <button
          onClick={() => setActiveTab('playground')}
          className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
            activeTab === 'playground'
              ? 'bg-primary text-white shadow-sm'
              : 'text-text-muted hover:text-text-primary hover:bg-surface-elevated'
          }`}
        >
          <Terminal className="w-3.5 h-3.5" />
          AI Playground
          {models.length > 0 && (
            <span className="ml-1 text-[10px] px-1.5 py-0.2 rounded-full bg-white/20 font-mono">
              {models.length}
            </span>
          )}
        </button>
        <button
          onClick={() => {
            setActiveTab('lifecycle');
            loadCatalog();
          }}
          className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
            activeTab === 'lifecycle'
              ? 'bg-primary text-white shadow-sm'
              : 'text-text-muted hover:text-text-primary hover:bg-surface-elevated'
          }`}
        >
          <CloudDownload className="w-3.5 h-3.5" />
          Model Lifecycle
          {pullTasks.filter((t) => ['queued', 'downloading', 'verifying'].includes(t.status)).length > 0 && (
            <span className="ml-1 text-[10px] px-1.5 py-0.2 rounded-full bg-status-warning text-black font-bold animate-pulse">
              {pullTasks.filter((t) => ['queued', 'downloading', 'verifying'].includes(t.status)).length}
            </span>
          )}
        </button>
      </div>

      {activeTab === 'playground' ? (
        /* ── Dedicated AI Playground Section ── */
        <section className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Controls & Prompt Editor (Left 7 Cols) */}
          <div className="lg:col-span-7 space-y-4">
            <div className="bg-surface border border-surface-border rounded-xl shadow-surface p-5 space-y-5">
              <div className="flex items-center justify-between pb-3 border-b border-surface-border">
                <div className="flex items-center gap-2">
                  <Terminal className="w-4 h-4 text-primary" />
                  <h3 className="text-sm font-bold text-text-primary">Inference Prompt Editor</h3>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-text-muted">Target Model:</span>
                  <select
                    value={playgroundModel}
                    onChange={(e) => setPlaygroundModel(e.target.value)}
                    disabled={models.length === 0}
                    className="text-xs bg-surface-elevated border border-surface-border rounded-lg px-2.5 py-1 font-mono text-text-primary focus:outline-none focus:border-primary cursor-pointer disabled:opacity-50"
                  >
                    {models.length === 0 ? (
                      <option value="">No models installed</option>
                    ) : (
                      models.map((m) => (
                        <option key={m.name} value={m.name}>
                          {m.name} {m.parameter_size ? `(${m.parameter_size})` : ''}
                        </option>
                      ))
                    )}
                  </select>
                </div>
              </div>

              {/* Example Prompts pills */}
              <div className="space-y-1.5">
                <div className="flex items-center gap-1.5 text-[11px] text-text-muted font-medium">
                  <Sparkles className="w-3 h-3 text-primary" /> Quick Evaluation Templates:
                </div>
                <div className="flex flex-wrap gap-2">
                  {EXAMPLE_PROMPTS.map((ex, i) => (
                    <button
                      key={i}
                      onClick={() => setPlaygroundPrompt(ex.prompt)}
                      className="text-[10px] px-2.5 py-1 rounded-lg bg-surface-elevated hover:bg-surface-hover border border-surface-border text-text-secondary hover:text-text-primary transition-colors cursor-pointer text-left"
                    >
                      {ex.title}
                    </button>
                  ))}
                </div>
              </div>

              {/* Textarea */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-xs text-text-muted">
                  <span>Prompt Payload</span>
                  <span className={playgroundPrompt.length > 30000 ? 'text-status-warning' : ''}>
                    {playgroundPrompt.length.toLocaleString()} / 32,768 characters
                  </span>
                </div>
                <textarea
                  rows={9}
                  value={playgroundPrompt}
                  onChange={(e) => setPlaygroundPrompt(e.target.value.slice(0, 32768))}
                  placeholder="Enter evaluation guidelines, repository files, or instructions for the local Ollama model..."
                  className="w-full text-xs font-mono bg-surface-elevated border border-surface-border rounded-xl p-3 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-primary resize-y leading-relaxed"
                />
              </div>

              {/* Generation Settings Controls */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 p-3.5 rounded-xl bg-surface-elevated/40 border border-surface-border text-xs">
                {/* Temperature */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-text-secondary flex items-center gap-1.5">
                      <Sliders className="w-3.5 h-3.5 text-text-muted" /> Temperature
                    </span>
                    <span className="font-mono text-primary font-bold">{playgroundTemperature.toFixed(2)}</span>
                  </div>
                  <input
                    type="range"
                    min="0.0"
                    max="1.5"
                    step="0.05"
                    value={playgroundTemperature}
                    onChange={(e) => setPlaygroundTemperature(parseFloat(e.target.value))}
                    className="w-full accent-primary cursor-pointer"
                  />
                  <div className="flex justify-between text-[10px] text-text-muted">
                    <span>0.0 (Deterministic)</span>
                    <span>1.5 (Creative)</span>
                  </div>
                </div>

                {/* Max Tokens */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-text-secondary flex items-center gap-1.5">
                      <Zap className="w-3.5 h-3.5 text-text-muted" /> Max Tokens
                    </span>
                    <span className="font-mono text-primary font-bold">{playgroundMaxTokens}</span>
                  </div>
                  <input
                    type="range"
                    min="128"
                    max="4096"
                    step="128"
                    value={playgroundMaxTokens}
                    onChange={(e) => setPlaygroundMaxTokens(parseInt(e.target.value, 10))}
                    className="w-full accent-primary cursor-pointer"
                  />
                  <div className="flex justify-between text-[10px] text-text-muted">
                    <span>128</span>
                    <span>4096</span>
                  </div>
                </div>
              </div>

              {/* Action Controls */}
              <div className="flex items-center justify-between pt-2">
                <button
                  onClick={() => {
                    setPlaygroundPrompt('');
                    setPlaygroundResponse(null);
                    setPlaygroundError(null);
                  }}
                  disabled={playgroundLoading || (!playgroundPrompt && !playgroundResponse)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs text-text-muted hover:text-text-primary rounded-lg border border-surface-border bg-surface-elevated hover:bg-surface-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
                >
                  <Trash2 className="w-3.5 h-3.5" /> Clear Session
                </button>

                <button
                  onClick={handleExecutePlayground}
                  disabled={playgroundLoading || !playgroundPrompt.trim() || !playgroundModel}
                  className="inline-flex items-center gap-2 px-5 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed rounded-lg shadow-sm transition-all cursor-pointer"
                >
                  {playgroundLoading ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      Generating Inference…
                    </>
                  ) : (
                    <>
                      <Send className="w-3.5 h-3.5" />
                      Run Inference
                    </>
                  )}
                </button>
              </div>

              {playgroundError && (
                <div className="flex items-start gap-2 p-3 rounded-lg bg-status-danger/10 border border-status-danger/30 text-xs text-status-danger">
                  <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                  <div>
                    <div className="font-semibold">Inference Error</div>
                    <div className="text-[11px] opacity-90">{playgroundError}</div>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Response Output Panel (Right 5 Cols) */}
          <div className="lg:col-span-5 flex flex-col">
            <div className="bg-surface border border-surface-border rounded-xl shadow-surface p-5 flex-1 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between pb-3 border-b border-surface-border">
                  <div className="flex items-center gap-2">
                    <Activity className="w-4 h-4 text-primary" />
                    <h3 className="text-sm font-bold text-text-primary">Model Response</h3>
                  </div>
                  {playgroundResponse?.response && (
                    <button
                      onClick={handleCopyResponse}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] rounded bg-surface-elevated hover:bg-surface-hover border border-surface-border text-text-secondary hover:text-text-primary transition-colors cursor-pointer"
                    >
                      {copiedResponse ? (
                        <>
                          <Check className="w-3 h-3 text-status-success" /> Copied!
                        </>
                      ) : (
                        <>
                          <Copy className="w-3 h-3" /> Copy Text
                        </>
                      )}
                    </button>
                  )}
                </div>

                {playgroundLoading ? (
                  <div className="py-20 text-center space-y-3">
                    <RefreshCw className="w-8 h-8 text-primary mx-auto animate-spin" />
                    <div className="text-xs font-semibold text-text-primary">
                      Awaiting response from {playgroundModel}…
                    </div>
                    <p className="text-[11px] text-text-muted max-w-xs mx-auto">
                      Inference is executing natively on local Ollama hardware.
                    </p>
                  </div>
                ) : !playgroundResponse ? (
                  <div className="py-20 text-center space-y-2">
                    <Terminal className="w-8 h-8 text-text-muted mx-auto opacity-30" />
                    <div className="text-xs font-semibold text-text-primary">Playground Idle</div>
                    <p className="text-[11px] text-text-muted max-w-xs mx-auto">
                      Select an installed model, type a test prompt, and click &quot;Run Inference&quot; to inspect output.
                    </p>
                  </div>
                ) : (
                  <div className="mt-4 space-y-3">
                    <div className="p-3.5 rounded-xl bg-surface-elevated font-mono text-xs text-text-primary leading-relaxed whitespace-pre-wrap max-h-[460px] overflow-y-auto border border-surface-border">
                      {playgroundResponse.response}
                    </div>
                  </div>
                )}
              </div>

              {/* Execution Telemetry Footer */}
              {playgroundResponse && (
                <div className="mt-4 pt-3 border-t border-surface-border grid grid-cols-2 gap-2 text-[11px] text-text-muted">
                  <div>
                    <span className="text-text-secondary font-medium">Model:</span>{' '}
                    <span className="font-mono">{playgroundResponse.model}</span>
                  </div>
                  <div className="text-right">
                    <span className="text-text-secondary font-medium">Duration:</span>{' '}
                    <span className="font-mono text-primary font-bold">
                      {playgroundResponse.duration_ms} ms
                    </span>
                  </div>
                  {playgroundResponse.token_usage?.prompt_tokens !== undefined && (
                    <div>
                      <span className="text-text-secondary">Prompt Tokens:</span>{' '}
                      <span className="font-mono">{playgroundResponse.token_usage.prompt_tokens}</span>
                    </div>
                  )}
                  {playgroundResponse.token_usage?.completion_tokens !== undefined && (
                    <div className="text-right">
                      <span className="text-text-secondary">Generated Tokens:</span>{' '}
                      <span className="font-mono">{playgroundResponse.token_usage.completion_tokens}</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </section>
      ) : activeTab === 'lifecycle' ? (
        /* ── Model Lifecycle Management Section ── */
        <div className="space-y-6">
          {/* Notification banner */}
          {lifecycleMessage && (
            <div
              className={`p-4 rounded-xl border flex items-center justify-between gap-3 text-xs ${
                lifecycleMessage.type === 'success'
                  ? 'bg-status-success/10 border-status-success/30 text-status-success'
                  : 'bg-status-danger/10 border-status-danger/30 text-status-danger'
              }`}
            >
              <div className="flex items-center gap-2">
                {lifecycleMessage.type === 'success' ? (
                  <CheckCircle2 className="w-4 h-4 shrink-0" />
                ) : (
                  <AlertCircle className="w-4 h-4 shrink-0" />
                )}
                <span>{lifecycleMessage.text}</span>
              </div>
              <button
                onClick={() => setLifecycleMessage(null)}
                className="text-text-muted hover:text-text-primary px-2 py-0.5"
              >
                Dismiss
              </button>
            </div>
          )}

          {/* Active Operations & Download Progress */}
          <div className="bg-surface border border-surface-border rounded-xl p-5 shadow-surface space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-surface-border">
              <div className="flex items-center gap-2">
                <CloudDownload className="w-4 h-4 text-primary" />
                <h3 className="text-sm font-bold text-text-primary">Active Model Operations & Pulls</h3>
              </div>
              <span className="text-[11px] text-text-muted">
                {pullTasks.length} recorded operation{pullTasks.length === 1 ? '' : 's'}
              </span>
            </div>

            {pullTasks.length === 0 ? (
              <p className="text-xs text-text-muted py-4 text-center">
                No recent or active model pull tasks recorded in this session.
              </p>
            ) : (
              <div className="space-y-3">
                {pullTasks.map((task) => {
                  const isActive = ['queued', 'downloading', 'verifying', 'cancelling'].includes(task.status);
                  return (
                    <div
                      key={task.task_id}
                      className="p-4 rounded-lg bg-surface-elevated border border-surface-border space-y-2.5"
                    >
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                        <div className="flex items-center gap-2.5">
                          <span className="text-xs font-bold font-mono text-text-primary">
                            {task.model_name}
                          </span>
                          <span
                            className={`text-[10px] px-2 py-0.5 rounded-full border font-semibold uppercase ${
                              task.status === 'completed'
                                ? 'bg-status-success/15 border-status-success/30 text-status-success'
                                : task.status === 'downloading'
                                ? 'bg-primary/15 border-primary/30 text-primary animate-pulse'
                                : task.status === 'failed'
                                ? 'bg-status-danger/15 border-status-danger/30 text-status-danger'
                                : task.status === 'cancelled'
                                ? 'bg-surface-elevated border-surface-border text-text-muted'
                                : 'bg-status-warning/15 border-status-warning/30 text-status-warning'
                            }`}
                          >
                            {task.status}
                          </span>
                        </div>

                        <div className="flex items-center gap-3 text-xs">
                          {task.total_bytes > 0 && (
                            <span className="text-text-muted font-mono">
                              {fmtBytes(task.completed_bytes)} / {fmtBytes(task.total_bytes)} (
                              {task.progress_percentage.toFixed(1)}%)
                            </span>
                          )}
                          {isActive && (
                            <button
                              onClick={() => handleCancelPull(task.task_id)}
                              className="px-2.5 py-1 text-[11px] font-semibold text-status-danger hover:bg-status-danger/10 border border-status-danger/30 rounded-md transition-colors cursor-pointer flex items-center gap-1.5"
                            >
                              <Ban className="w-3 h-3" />
                              Cancel Pull
                            </button>
                          )}
                        </div>
                      </div>

                      {/* Genuine Progress Bar */}
                      {isActive && (
                        <div className="w-full bg-surface-border rounded-full h-2 overflow-hidden">
                          <div
                            className="bg-primary h-2 rounded-full transition-all duration-300 ease-out"
                            style={{ width: `${Math.min(100, Math.max(2, task.progress_percentage))}%` }}
                          />
                        </div>
                      )}

                      <div className="flex items-center justify-between text-[11px] text-text-muted">
                        <span>
                          Current step:{' '}
                          <span className="text-text-secondary font-medium">
                            {task.current_step || 'Waiting for Ollama stream...'}
                          </span>
                        </span>
                        {task.error && (
                          <span className="text-status-danger font-medium">
                            Error: {task.error}
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Trusted Catalog Models Grid */}
          <div className="bg-surface border border-surface-border rounded-xl p-5 shadow-surface space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-surface-border">
              <div>
                <h3 className="text-sm font-bold text-text-primary">Approved Ollama Model Catalog</h3>
                <p className="text-[11px] text-text-muted">
                  Discover curated and benchmarked models vetted for Scorva evaluation and code analysis.
                </p>
              </div>

              <div className="flex items-center gap-2">
                <div className="relative">
                  <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
                  <input
                    type="text"
                    placeholder="Search catalog models..."
                    value={catalogSearch}
                    onChange={(e) => setCatalogSearch(e.target.value)}
                    className="pl-8 pr-3 py-1.5 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary placeholder:text-text-muted focus:outline-none focus:border-primary w-48 sm:w-60"
                  />
                </div>
                <button
                  onClick={loadCatalog}
                  disabled={catalogLoading}
                  className="p-1.5 text-text-muted hover:text-text-primary bg-surface-elevated border border-surface-border rounded-lg cursor-pointer"
                  title="Reload catalog"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${catalogLoading ? 'animate-spin' : ''}`} />
                </button>
              </div>
            </div>

            {catalogLoading ? (
              <div className="py-12 text-center text-xs text-text-muted">Loading vetted model catalog...</div>
            ) : filteredCatalog.length === 0 ? (
              <p className="py-8 text-center text-xs text-text-muted">
                No catalog models match your search criteria.
              </p>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {filteredCatalog.map((item) => {
                  const isInstalled = models.some(
                    (m) => m.name.toLowerCase() === item.name.toLowerCase() || m.name.startsWith(item.name.split(':')[0])
                  );
                  const isPulling =
                    pullingModelName === item.name ||
                    pullTasks.some(
                      (t) => t.model_name === item.name && ['queued', 'downloading', 'verifying'].includes(t.status)
                    );

                  return (
                    <div
                      key={item.name}
                      className="p-4 rounded-xl bg-surface-elevated border border-surface-border flex flex-col justify-between hover:border-primary/40 transition-colors space-y-3"
                    >
                      <div className="space-y-2">
                        <div className="flex items-start justify-between gap-2">
                          <div>
                            <span className="text-xs font-bold font-mono text-text-primary block">
                              {item.name}
                            </span>
                            <span className="text-[10px] text-text-muted uppercase font-semibold">
                              {item.category} • {item.parameter_size}
                            </span>
                          </div>
                          {isInstalled && (
                            <span className="text-[10px] px-2 py-0.5 rounded-full bg-status-success/15 border border-status-success/30 text-status-success font-semibold shrink-0">
                              Installed
                            </span>
                          )}
                        </div>

                        <p className="text-[11px] text-text-secondary leading-relaxed line-clamp-3">
                          {item.description}
                        </p>

                        <div className="flex flex-wrap gap-1 pt-1">
                          {item.tags.map((tag) => (
                            <span
                              key={tag}
                              className="text-[9px] px-1.5 py-0.5 rounded bg-surface border border-surface-border text-text-muted font-mono"
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      </div>

                      <div className="pt-2 border-t border-surface-border flex items-center justify-between">
                        <span className="text-[10px] text-text-muted">
                          Download: <span className="font-semibold text-text-primary">{fmtBytes(item.approx_size_bytes)}</span>
                        </span>

                        <button
                          onClick={() => handlePullModel(item.name)}
                          disabled={isPulling}
                          className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors flex items-center gap-1.5 cursor-pointer ${
                            isInstalled
                              ? 'bg-surface hover:bg-surface-elevated text-text-secondary border border-surface-border'
                              : 'bg-primary hover:bg-primary-hover text-white shadow-sm'
                          } ${isPulling ? 'opacity-50 cursor-not-allowed' : ''}`}
                        >
                          <Download className={`w-3.5 h-3.5 ${isPulling ? 'animate-bounce' : ''}`} />
                          {isPulling ? 'Pulling...' : isInstalled ? 'Re-pull' : 'Pull Model'}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Installed Models Management Table */}
          <div className="bg-surface border border-surface-border rounded-xl p-5 shadow-surface space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-surface-border">
              <div className="flex items-center gap-2">
                <HardDrive className="w-4 h-4 text-primary" />
                <h3 className="text-sm font-bold text-text-primary">Installed Ollama Models ({models.length})</h3>
              </div>
              <span className="text-[11px] text-text-muted">
                Total Local Storage:{' '}
                <span className="font-bold text-text-primary">
                  {fmtBytes(models.reduce((acc, m) => acc + (m.size || 0), 0))}
                </span>
              </span>
            </div>

            {models.length === 0 ? (
              <div className="text-center py-8 text-xs text-text-muted">
                No Ollama models currently installed. Pull one from the catalog above.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-surface-elevated text-text-muted font-semibold border-b border-surface-border">
                    <tr>
                      <th className="px-4 py-2.5">Model Name</th>
                      <th className="px-4 py-2.5">Disk Size</th>
                      <th className="px-4 py-2.5">Parameters / Quant</th>
                      <th className="px-4 py-2.5">Modified</th>
                      <th className="px-4 py-2.5 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-border font-mono text-[11px]">
                    {models.map((m) => (
                      <tr key={m.name} className="hover:bg-surface-elevated/50 transition-colors">
                        <td className="px-4 py-3 font-bold text-text-primary">{m.name}</td>
                        <td className="px-4 py-3 text-text-secondary">{fmtBytes(m.size || 0)}</td>
                        <td className="px-4 py-3 text-text-muted font-sans">
                          {m.parameter_size || m.quantization_level
                            ? `${m.parameter_size || '—'} (${m.quantization_level || '—'})`
                            : '—'}
                        </td>
                        <td className="px-4 py-3 text-text-muted font-sans">{fmtDate(m.modified_at)}</td>
                        <td className="px-4 py-3 text-right">
                          <button
                            onClick={() => setModelToDelete(m.name)}
                            className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-sans font-semibold text-status-danger hover:bg-status-danger/10 border border-status-danger/30 rounded-md transition-colors cursor-pointer"
                          >
                            <Trash2 className="w-3 h-3" />
                            Delete
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Model Deletion Confirmation Modal */}
          {modelToDelete && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4">
              <div className="bg-surface border border-surface-border rounded-xl shadow-xl max-w-md w-full p-6 space-y-4">
                <div className="flex items-center gap-3 text-status-danger">
                  <AlertCircle className="w-5 h-5 shrink-0" />
                  <h4 className="text-base font-bold text-text-primary">Confirm Model Deletion</h4>
                </div>
                <p className="text-xs text-text-secondary leading-relaxed">
                  Are you sure you want to permanently delete model{' '}
                  <span className="font-mono font-bold text-text-primary">{modelToDelete}</span> from local Ollama
                  storage? This action will remove the weights from disk and cannot be undone.
                </p>
                <div className="p-3 rounded-lg bg-surface-elevated border border-surface-border text-[11px] text-text-muted">
                  Safe Deletion Guard: Active evaluation jobs running with this model will block deletion.
                </div>
                <div className="flex items-center justify-end gap-3 pt-2">
                  <button
                    onClick={() => setModelToDelete(null)}
                    disabled={deletingModel}
                    className="px-3.5 py-2 text-xs font-semibold rounded-lg bg-surface-elevated hover:bg-surface-hover border border-surface-border text-text-secondary cursor-pointer"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleConfirmDeleteModel}
                    disabled={deletingModel}
                    className="px-4 py-2 text-xs font-semibold rounded-lg bg-status-danger hover:bg-status-danger/90 text-white cursor-pointer flex items-center gap-1.5 shadow-sm"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    {deletingModel ? 'Deleting Model...' : 'Yes, Delete Model'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      ) : (
        /* ── Overview Dashboard (All Sections A-F) ── */
        <>
          {/* ── Section A: Infrastructure Overview Cards ── */}
          <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3">
        {/* 1. Connection Status */}
        <div className="p-4 rounded-xl bg-surface border border-surface-border shadow-surface flex flex-col justify-between">
          <div className="flex items-center justify-between text-text-muted mb-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider">Ollama Status</span>
            <Server className="w-4 h-4 text-primary" />
          </div>
          {healthLoading ? (
            <div className="h-7 w-20 bg-surface-elevated rounded animate-pulse" />
          ) : (
            <div className="flex items-center gap-2">
              <div
                className={`w-2.5 h-2.5 rounded-full ${
                  health?.reachable ? 'bg-status-success animate-pulse' : 'bg-status-danger'
                }`}
              />
              <span className="text-lg font-bold text-text-primary">
                {health?.reachable ? 'Online' : 'Offline'}
              </span>
            </div>
          )}
          <span className="text-[10px] text-text-muted mt-1 truncate">
            {health?.base_url || 'http://localhost:11434'}
          </span>
        </div>

        {/* 2. Ollama Version */}
        <div className="p-4 rounded-xl bg-surface border border-surface-border shadow-surface flex flex-col justify-between">
          <div className="flex items-center justify-between text-text-muted mb-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider">Version</span>
            <Box className="w-4 h-4 text-text-muted" />
          </div>
          {healthLoading ? (
            <div className="h-7 w-16 bg-surface-elevated rounded animate-pulse" />
          ) : (
            <div className="text-lg font-bold text-text-primary font-mono truncate">
              {health?.version || (health?.reachable ? 'v0.4+' : '—')}
            </div>
          )}
          <span className="text-[10px] text-text-muted mt-1">Host daemon version</span>
        </div>

        {/* 3. Installed Models Count */}
        <div className="p-4 rounded-xl bg-surface border border-surface-border shadow-surface flex flex-col justify-between">
          <div className="flex items-center justify-between text-text-muted mb-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider">Models</span>
            <HardDrive className="w-4 h-4 text-primary" />
          </div>
          {healthLoading ? (
            <div className="h-7 w-12 bg-surface-elevated rounded animate-pulse" />
          ) : (
            <div className="text-lg font-bold text-text-primary">
              {health?.installed_model_count ?? health?.model_count ?? models.length}
            </div>
          )}
          <span className="text-[10px] text-text-muted mt-1">Available on disk</span>
        </div>

        {/* 4. Total Provider Calls */}
        <div className="p-4 rounded-xl bg-surface border border-surface-border shadow-surface flex flex-col justify-between">
          <div className="flex items-center justify-between text-text-muted mb-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider">Total Inferences</span>
            <Zap className="w-4 h-4 text-primary" />
          </div>
          {metricsLoading ? (
            <div className="h-7 w-16 bg-surface-elevated rounded animate-pulse" />
          ) : (
            <div className="text-lg font-bold text-text-primary">
              {metrics?.total_provider_calls ??
                Object.values(metrics?.provider_calls ?? {}).reduce((a, b) => a + b, 0)}
            </div>
          )}
          <span className="text-[10px] text-text-muted mt-1">Cumulative API calls</span>
        </div>

        {/* 5. Avg Execution Duration */}
        <div className="p-4 rounded-xl bg-surface border border-surface-border shadow-surface flex flex-col justify-between">
          <div className="flex items-center justify-between text-text-muted mb-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider">Avg Duration</span>
            <Timer className="w-4 h-4 text-amber-400" />
          </div>
          {metricsLoading ? (
            <div className="h-7 w-16 bg-surface-elevated rounded animate-pulse" />
          ) : (
            <div className="text-lg font-bold text-text-primary">
              {fmtDuration(
                metrics?.eval_execution_duration?.avg_seconds ??
                  metrics?.eval_duration_avg_seconds ??
                  null
              )}
            </div>
          )}
          <span className="text-[10px] text-text-muted mt-1">
            {metrics?.eval_execution_duration?.count ?? metrics?.eval_duration_count ?? 0} samples
          </span>
        </div>

        {/* 6. AI Failures */}
        <div className="p-4 rounded-xl bg-surface border border-surface-border shadow-surface flex flex-col justify-between">
          <div className="flex items-center justify-between text-text-muted mb-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider">Failures</span>
            <XCircle className="w-4 h-4 text-status-danger" />
          </div>
          {metricsLoading ? (
            <div className="h-7 w-12 bg-surface-elevated rounded animate-pulse" />
          ) : (
            <div className="text-lg font-bold text-status-danger">
              {metrics?.failed_calls ?? metrics?.jobs_by_status?.['failed'] ?? 0}
            </div>
          )}
          <span className="text-[10px] text-text-muted mt-1">Provider or job errors</span>
        </div>
      </section>

      {/* ── Section B & C: Ollama Service Health Panel & Installed Models Registry ── */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Section B: Service Health Panel */}
        <div className="lg:col-span-1 p-5 rounded-xl bg-surface border border-surface-border shadow-surface flex flex-col justify-between gap-4">
          <div>
            <div className="flex items-center justify-between pb-3 border-b border-surface-border">
              <div className="flex items-center gap-2">
                <Cpu className="w-4 h-4 text-primary" />
                <h3 className="text-sm font-bold text-text-primary">Ollama Service Health</h3>
              </div>
              <button
                onClick={loadHealthAndModels}
                title="Probe Ollama health"
                className="p-1 rounded hover:bg-surface-elevated text-text-muted hover:text-text-primary transition-colors cursor-pointer"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${healthLoading ? 'animate-spin' : ''}`} />
              </button>
            </div>

            {healthError && (
              <div className="mt-3 flex items-start gap-2 p-3 rounded-lg bg-status-danger/10 border border-status-danger/30 text-xs text-status-danger">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <div className="font-semibold">Ollama Unreachable</div>
                  <div className="text-[11px] leading-relaxed opacity-90">{healthError}</div>
                </div>
              </div>
            )}

            <div className="mt-4 space-y-3 text-xs">
              <div className="flex items-center justify-between py-1 border-b border-surface-border/50">
                <span className="text-text-muted">Connection Status</span>
                <span
                  className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border ${
                    health?.reachable
                      ? 'text-status-success bg-status-success/10 border-status-success/30'
                      : 'text-status-danger bg-status-danger/10 border-status-danger/30'
                  }`}
                >
                  {health?.reachable ? (
                    <>
                      <Wifi className="w-3 h-3" /> Online
                    </>
                  ) : (
                    <>
                      <WifiOff className="w-3 h-3" /> Offline
                    </>
                  )}
                </span>
              </div>

              <div className="flex items-center justify-between py-1 border-b border-surface-border/50">
                <span className="text-text-muted">Target Endpoint</span>
                <span
                  className="font-mono text-[11px] text-text-primary truncate max-w-[170px]"
                  title={health?.base_url}
                >
                  {health?.base_url || 'http://localhost:11434'}
                </span>
              </div>

              <div className="flex items-center justify-between py-1 border-b border-surface-border/50">
                <span className="text-text-muted">HTTP Probe Latency</span>
                <span className="font-semibold text-primary">
                  {health?.latency_ms !== null && health?.latency_ms !== undefined
                    ? `${health.latency_ms} ms`
                    : '—'}
                </span>
              </div>

              <div className="flex items-center justify-between py-1 border-b border-surface-border/50">
                <span className="text-text-muted">Daemon Version</span>
                <span className="font-mono text-text-primary">
                  {health?.version || (health?.reachable ? '0.4+' : 'Unavailable')}
                </span>
              </div>

              <div className="flex items-center justify-between py-1 border-b border-surface-border/50">
                <span className="text-text-muted">Installed Models</span>
                <span className="font-bold text-text-primary">
                  {health?.installed_model_count ?? health?.model_count ?? models.length}
                </span>
              </div>

              <div className="flex items-center justify-between py-1">
                <span className="text-text-muted">Last Successful Probe</span>
                <span className="text-[11px] text-text-secondary">
                  {lastSuccessfulHealthCheck
                    ? lastSuccessfulHealthCheck.toLocaleTimeString()
                    : health?.reachable
                    ? 'Just now'
                    : 'Never'}
                </span>
              </div>
            </div>
          </div>

          {!health?.reachable && (
            <div className="p-3 rounded-lg bg-surface-elevated border border-surface-border text-[11px] text-text-muted space-y-1">
              <div className="font-semibold text-text-primary flex items-center gap-1.5">
                <Info className="w-3.5 h-3.5 text-primary" /> Troubleshooting
              </div>
              <p>
                Ensure Ollama is running locally via <code className="font-mono">ollama serve</code>{' '}
                or Docker container <code className="font-mono">scorva-ollama</code>.
              </p>
            </div>
          )}
        </div>

        {/* Section C: Installed Models Registry */}
        <div className="lg:col-span-2 bg-surface border border-surface-border rounded-xl shadow-surface overflow-hidden flex flex-col">
          <div className="px-5 py-3.5 border-b border-surface-border flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Box className="w-4 h-4 text-primary" />
              <h3 className="text-sm font-bold text-text-primary">Installed Models Registry</h3>
              <span className="text-xs text-text-muted">({filteredAndSortedModels.length})</span>
            </div>

            <div className="flex items-center gap-2">
              {/* Search */}
              <div className="relative">
                <Search className="w-3.5 h-3.5 text-text-muted absolute left-2.5 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  placeholder="Filter models..."
                  value={modelSearch}
                  onChange={(e) => setModelSearch(e.target.value)}
                  className="text-xs bg-surface-elevated border border-surface-border rounded-lg pl-8 pr-2.5 py-1 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-primary w-36 sm:w-44"
                />
              </div>

              {/* Sort selector */}
              <select
                value={modelSortBy}
                onChange={(e) => setModelSortBy(e.target.value as 'name' | 'size' | 'modified_at')}
                className="text-xs bg-surface-elevated border border-surface-border rounded-lg px-2 py-1 text-text-secondary focus:outline-none focus:border-primary cursor-pointer"
              >
                <option value="name">Sort: Name</option>
                <option value="size">Sort: Size</option>
                <option value="modified_at">Sort: Modified</option>
              </select>

              <button
                onClick={() => setModelSortOrder((o) => (o === 'asc' ? 'desc' : 'asc'))}
                title={`Sort ${modelSortOrder === 'asc' ? 'Descending' : 'Ascending'}`}
                className="p-1.5 rounded-lg border border-surface-border bg-surface-elevated text-text-muted hover:text-text-primary cursor-pointer"
              >
                <ArrowUpDown className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-x-auto">
            {modelsLoading ? (
              <div className="p-12 text-center text-xs text-text-muted animate-pulse">
                Querying Ollama installed models catalog…
              </div>
            ) : !health?.reachable ? (
              <div className="p-12 text-center space-y-2">
                <WifiOff className="w-8 h-8 text-status-danger mx-auto opacity-60" />
                <div className="text-sm font-semibold text-text-primary">
                  Ollama Service Unavailable
                </div>
                <div className="text-xs text-text-muted max-w-sm mx-auto">
                  Installed models cannot be queried while the host daemon is unreachable.
                </div>
              </div>
            ) : filteredAndSortedModels.length === 0 ? (
              <div className="p-12 text-center space-y-2">
                <Box className="w-8 h-8 text-text-muted mx-auto opacity-40" />
                <div className="text-sm font-semibold text-text-primary">
                  {modelSearch ? 'No matching models' : 'No Models Pulled'}
                </div>
                <p className="text-xs text-text-muted max-w-sm mx-auto">
                  {modelSearch
                    ? 'No models match your search query.'
                    : 'To evaluate hackathons using local AI, pull an LLM such as llama3.3:70b or gemma2:9b.'}
                </p>
              </div>
            ) : (
              <div className="divide-y divide-surface-border min-w-[550px]">
                <div className="grid grid-cols-[1.5fr_90px_100px_90px_110px] px-5 py-2 text-[10px] font-semibold uppercase tracking-wider text-text-muted bg-surface-elevated/40">
                  <span>Model Identifier</span>
                  <span>Parameters</span>
                  <span>Quantization</span>
                  <span>Storage</span>
                  <span>Modified</span>
                </div>

                {filteredAndSortedModels.map((m) => (
                  <div
                    key={m.name}
                    onClick={() => setSelectedModel(m)}
                    className="grid grid-cols-[1.5fr_90px_100px_90px_110px] px-5 py-3 text-xs hover:bg-surface-elevated/40 transition-colors items-center cursor-pointer"
                  >
                    <div>
                      <span className="font-semibold text-text-primary">{m.name}</span>
                      {m.digest && (
                        <div className="text-[10px] font-mono text-text-muted mt-0.5 truncate max-w-[200px]">
                          {m.digest.slice(0, 19)}…
                        </div>
                      )}
                    </div>
                    <span className="text-text-secondary">{m.parameter_size ?? '—'}</span>
                    <span className="text-text-secondary font-mono text-[11px]">
                      {m.quantization_level ?? '—'}
                    </span>
                    <span className="text-text-primary font-medium">{fmtBytes(m.size)}</span>
                    <span className="text-text-muted text-[11px]">
                      {m.modified_at ? new Date(m.modified_at).toLocaleDateString() : '—'}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Model Details Modal / Drawer if selected */}
          {selectedModel && (
            <div className="p-4 border-t border-surface-border bg-surface-elevated/30 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-text-primary">{selectedModel.name}</span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded border border-surface-border bg-surface font-mono">
                    {selectedModel.quantization_level ?? 'Standard'}
                  </span>
                </div>
                <div className="text-[11px] text-text-muted font-mono truncate max-w-md">
                  Digest: {selectedModel.digest || 'Unavailable'}
                </div>
              </div>
              <button
                onClick={() => setSelectedModel(null)}
                className="px-2.5 py-1 text-xs text-text-secondary hover:text-text-primary rounded border border-surface-border bg-surface hover:bg-surface-elevated transition-colors self-end sm:self-auto cursor-pointer"
              >
                Close Inspector
              </button>
            </div>
          )}
        </div>
      </section>

      {/* ── Section D: AI Performance Analytics ── */}
      <section className="bg-surface border border-surface-border rounded-xl shadow-surface p-5 space-y-5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-surface-border">
          <div className="flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-primary" />
            <h3 className="text-sm font-bold text-text-primary">AI Performance & Pipeline Analytics</h3>
          </div>
          <div className="text-xs text-text-muted">In-process telemetry from Prometheus registry</div>
        </div>

        {metricsLoading ? (
          <div className="p-12 text-center text-xs text-text-muted animate-pulse">
            Aggregating platform AI telemetry…
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Chart 1: Provider / Model Calls Breakdown */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-text-primary flex items-center gap-1.5">
                  <Zap className="w-3.5 h-3.5 text-primary" /> Provider Calls Breakdown
                </span>
                <span className="text-[11px] text-text-muted">
                  Total: {metrics?.total_provider_calls ?? 0}
                </span>
              </div>

              {providerModelData.length === 0 ? (
                <div className="h-48 rounded-lg bg-surface-elevated/30 border border-surface-border flex items-center justify-center text-xs text-text-muted">
                  No AI provider calls recorded yet.
                </div>
              ) : (
                <div className="h-56 w-full pt-2">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={providerModelData} margin={{ top: 10, right: 10, left: -20, bottom: 20 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#2D3748" opacity={0.4} />
                      <XAxis dataKey="name" tick={{ fill: '#A0AEC0', fontSize: 10 }} interval={0} angle={-15} textAnchor="end" />
                      <YAxis tick={{ fill: '#A0AEC0', fontSize: 10 }} />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: '#1A202C',
                          borderColor: '#2D3748',
                          borderRadius: '8px',
                          fontSize: '11px',
                        }}
                      />
                      <Bar dataKey="calls" fill="#3B82F6" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>

            {/* Chart 2: Job Lifecycle Status Breakdown */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-text-primary flex items-center gap-1.5">
                  <PieChartIcon className="w-3.5 h-3.5 text-status-success" /> Job Lifecycle Distribution
                </span>
                <span className="text-[11px] text-text-muted">
                  Across all tenants
                </span>
              </div>

              {jobStatusData.length === 0 ? (
                <div className="h-48 rounded-lg bg-surface-elevated/30 border border-surface-border flex items-center justify-center text-xs text-text-muted">
                  No evaluation jobs observed yet.
                </div>
              ) : (
                <div className="h-56 w-full flex items-center justify-center">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={jobStatusData}
                        cx="50%"
                        cy="50%"
                        innerRadius={45}
                        outerRadius={75}
                        paddingAngle={4}
                        dataKey="value"
                      >
                        {jobStatusData.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{
                          backgroundColor: '#1A202C',
                          borderColor: '#2D3748',
                          borderRadius: '8px',
                          fontSize: '11px',
                        }}
                      />
                      <Legend
                        verticalAlign="bottom"
                        height={36}
                        formatter={(val: string) => <span className="text-xs text-text-secondary">{val}</span>}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Unavailable Metrics Banner */}
        {metrics?.unavailable_metrics && metrics.unavailable_metrics.length > 0 && (
          <div className="pt-3 border-t border-surface-border flex flex-wrap items-center gap-2 text-[11px] text-text-muted">
            <span className="font-semibold text-text-secondary flex items-center gap-1">
              <Info className="w-3.5 h-3.5 text-text-muted" /> Uninstrumented in native Ollama:
            </span>
            {metrics.unavailable_metrics.map((m) => (
              <span
                key={m}
                className="px-2 py-0.5 rounded bg-surface-elevated border border-surface-border font-mono text-[10px]"
              >
                {m}
              </span>
            ))}
          </div>
        )}
      </section>

      {/* ── Section E: Cross-Org Evaluation Job Queue ── */}
      <section className="bg-surface border border-surface-border rounded-xl shadow-surface overflow-hidden">
        <div className="px-5 py-4 border-b border-surface-border flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-primary" />
            <h3 className="text-sm font-bold text-text-primary">Evaluation Monitoring</h3>
            <span className="text-xs text-text-muted">({jobsTotal} total records)</span>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5 text-xs text-text-muted">
              <span>Status:</span>
              <select
                value={jobsStatusFilter}
                onChange={(e) => {
                  setJobsStatusFilter(e.target.value);
                  setJobsPage(1);
                }}
                className="text-xs bg-surface-elevated border border-surface-border rounded-lg px-2.5 py-1 text-text-primary focus:outline-none focus:border-primary cursor-pointer"
              >
                <option value="">All Statuses</option>
                {JOB_STATUS_OPTIONS.filter(Boolean).map((s) => (
                  <option key={s} value={s} className="capitalize">
                    {s}
                  </option>
                ))}
              </select>
            </div>

            <button
              onClick={loadJobs}
              title="Refresh jobs list"
              className="p-1.5 rounded-lg border border-surface-border bg-surface-elevated hover:bg-surface-hover text-text-muted hover:text-text-primary cursor-pointer transition-colors"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${jobsLoading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {jobsLoading ? (
          <div className="p-12 text-center text-xs text-text-muted animate-pulse">
            Loading evaluation job records…
          </div>
        ) : jobsError ? (
          <div className="p-12 text-center space-y-2">
            <AlertCircle className="w-7 h-7 text-status-danger mx-auto" />
            <div className="text-sm font-semibold text-text-primary">Failed to load jobs</div>
            <div className="text-xs text-text-muted">{jobsError}</div>
          </div>
        ) : jobs.length === 0 ? (
          <div className="p-12 text-center space-y-2">
            <Database className="w-8 h-8 text-text-muted mx-auto opacity-40" />
            <div className="text-sm font-semibold text-text-primary">No Evaluation Jobs Found</div>
            <p className="text-xs text-text-muted">
              No evaluation jobs match the selected filter.
            </p>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-surface-border bg-surface-elevated/40 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                    <th className="px-5 py-2.5">Job ID</th>
                    <th className="px-5 py-2.5">Organization / Hackathon</th>
                    <th className="px-5 py-2.5">Status</th>
                    <th className="px-5 py-2.5">Pipeline Stage</th>
                    <th className="px-5 py-2.5">Attempts</th>
                    <th className="px-5 py-2.5">Created At</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-border">
                  {jobs.map((job) => (
                    <tr
                      key={job.id}
                      className="hover:bg-surface-elevated/30 transition-colors"
                    >
                      <td className="px-5 py-3.5 font-mono text-[11px] text-text-primary">
                        <span title={job.id}>{String(job.id).slice(0, 13)}…</span>
                        <div className="text-[10px] text-text-muted font-normal">
                          Sub: {String(job.submission_id).slice(0, 8)}…
                        </div>
                      </td>
                      <td className="px-5 py-3.5 text-text-secondary">
                        <div className="font-mono text-[11px]">
                          Org: {String(job.organization_id).slice(0, 8)}…
                        </div>
                        <div className="text-[10px] text-text-muted">
                          Hack: {String(job.hackathon_id).slice(0, 8)}…
                        </div>
                      </td>
                      <td className="px-5 py-3.5">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border ${statusColor(
                            job.status
                          )}`}
                        >
                          {job.status}
                        </span>
                      </td>
                      <td className="px-5 py-3.5 text-text-secondary">
                        {job.current_stage ? (
                          <span className="inline-flex items-center gap-1">
                            <Layers className="w-3 h-3 text-text-muted" />
                            {job.current_stage}
                          </span>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td className="px-5 py-3.5 text-text-secondary">
                        {job.attempts_count} / {job.max_attempts}
                        {job.cancellation_requested && (
                          <span className="ml-1 text-[10px] text-status-warning font-semibold">
                            (cancellation requested)
                          </span>
                        )}
                      </td>
                      <td className="px-5 py-3.5 text-[11px] text-text-muted">
                        {fmtDate(job.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination Controls */}
            {totalJobPages > 1 && (
              <div className="px-5 py-3 border-t border-surface-border flex items-center justify-between text-xs text-text-muted">
                <div>
                  Page <span className="font-semibold text-text-primary">{jobsPage}</span> of{' '}
                  <span className="font-semibold text-text-primary">{totalJobPages}</span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setJobsPage((p) => Math.max(1, p - 1))}
                    disabled={jobsPage <= 1}
                    className="p-1.5 rounded-lg border border-surface-border bg-surface-elevated hover:bg-surface-hover text-text-muted hover:text-text-primary disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => setJobsPage((p) => Math.min(totalJobPages, p + 1))}
                    disabled={jobsPage >= totalJobPages}
                    className="p-1.5 rounded-lg border border-surface-border bg-surface-elevated hover:bg-surface-hover text-text-muted hover:text-text-primary disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
                  >
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </section>

      {/* ── Section F: AI Configuration Inspector (Read-only) ── */}
      <section className="bg-surface border border-surface-border rounded-xl shadow-surface overflow-hidden">
        <div className="px-5 py-4 border-b border-surface-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Settings2 className="w-4 h-4 text-primary" />
            <h3 className="text-sm font-bold text-text-primary">Effective AI Configuration</h3>
            <span className="text-xs text-text-muted">(Read-only inspector)</span>
          </div>
          <span className="text-[11px] text-text-muted">
            Configured in <code className="font-mono text-primary">catalog.py</code>
          </span>
        </div>

        {configLoading ? (
          <div className="p-8 text-center text-xs text-text-muted animate-pulse">
            Loading AI configuration parameters…
          </div>
        ) : aiConfig.length === 0 ? (
          <div className="p-8 text-center text-xs text-text-muted">
            No dynamic AI configuration entries loaded.
          </div>
        ) : (
          <div className="divide-y divide-surface-border">
            {aiConfig.map((item) => (
              <div
                key={item.key}
                className="px-5 py-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-2"
              >
                <div className="space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-text-primary font-mono">
                      {item.key}
                    </span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded border border-surface-border bg-surface-elevated text-text-muted uppercase font-semibold">
                      {item.effect_timing}
                    </span>
                  </div>
                  {item.description && (
                    <p className="text-[11px] text-text-muted">{item.description}</p>
                  )}
                </div>

                <div className="flex items-center gap-3 shrink-0">
                  {item.current_value !== item.default_value && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 border border-primary/30 text-primary font-semibold uppercase">
                      Overridden
                    </span>
                  )}
                  <span className="text-xs font-bold text-text-primary font-mono bg-surface-elevated px-2.5 py-1 rounded-lg border border-surface-border">
                    {item.current_value}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
        </>
      )}
    </div>
  );
}
