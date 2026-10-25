'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { RefreshCw, Wifi, WifiOff } from 'lucide-react';
import { api, ApiClientError } from '@/lib/api-client';
import { HealthResponse } from '@/types/api';
import { StatusBadge } from './StatusBadge';

export const HealthIndicator: React.FC = () => {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getHealth();
      setHealth(data);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(`Backend Error: ${err.message}`);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Failed to connect to Scorva API');
      }
      setHealth(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    // Poll every 30 seconds for live health status
    const interval = setInterval(fetchStatus, 30000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  if (loading && !health && !error) {
    return (
      <div className="flex items-center gap-2 text-xs text-text-secondary bg-surface px-3 py-1.5 rounded-lg border border-surface-border">
        <RefreshCw className="w-3.5 h-3.5 animate-spin text-primary" />
        <span>Connecting to API...</span>
      </div>
    );
  }

  if (error || !health) {
    return (
      <div className="flex items-center gap-2 text-xs bg-status-error/10 text-status-error px-3 py-1.5 rounded-lg border border-status-error/30">
        <WifiOff className="w-3.5 h-3.5" />
        <span className="font-medium truncate max-w-[180px] sm:max-w-none" title={error || 'Disconnected'}>
          API Offline
        </span>
        <button
          onClick={fetchStatus}
          disabled={loading}
          aria-label="Retry connection"
          className="ml-1 hover:text-white transition-colors"
        >
          <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2.5 text-xs bg-surface px-3 py-1.5 rounded-lg border border-surface-border">
      <div className="flex items-center gap-1.5">
        <Wifi className="w-3.5 h-3.5 text-status-success" />
        <span className="text-text-secondary">API:</span>
        <StatusBadge status={health.status} size="sm" />
      </div>
      <span className="text-surface-border">|</span>
      <span className="text-text-muted hidden sm:inline">v{health.version}</span>
      <button
        onClick={fetchStatus}
        disabled={loading}
        title="Refresh health status"
        aria-label="Refresh health status"
        className="text-text-muted hover:text-text-primary transition-colors ml-0.5"
      >
        <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin text-primary' : ''}`} />
      </button>
    </div>
  );
};
