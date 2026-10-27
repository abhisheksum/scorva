'use client';

import React, { useState, useEffect, useCallback } from 'react';
import {
  Shield,
  KeyRound,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Sliders,
  Cpu,
  Archive,
  Scale,
  Lock,
  Layers,
  Info,
} from 'lucide-react';
import { PageHeader } from '@/components/admin/PageHeader';
import { StatusBadge } from '@/components/admin/StatusBadge';
import { api, ApiClientError } from '@/lib/api-client';
import { ConfigurationSetting } from '@/types/api';

export default function SettingsPage() {
  const [settingsList, setSettingsList] = useState<ConfigurationSetting[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isUpdatingMfa, setIsUpdatingMfa] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const loadSettings = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await api.getConfigurationSettings();
      setSettingsList(data);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to fetch platform configuration settings. Ensure API backend is reachable.');
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  const mfaSetting = settingsList.find((s) => s.key === 'auth.mfa_enforced');
  const isMfaEnforced = mfaSetting?.current_value.toLowerCase() === 'true';

  const handleToggleMfa = async () => {
    if (!mfaSetting) return;

    setIsUpdatingMfa(true);
    setError(null);
    setSuccessMessage(null);

    const targetValue = isMfaEnforced ? 'false' : 'true';
    const actionDesc = targetValue === 'true' ? 'enabling' : 'disabling';

    try {
      const updated = await api.updateConfigurationSetting(
        'auth.mfa_enforced',
        targetValue,
        mfaSetting.version,
        `Super admin changed 2FA policy: ${actionDesc} mandatory TOTP`
      );

      setSettingsList((prev) =>
        prev.map((s) => (s.key === 'auth.mfa_enforced' ? updated : s))
      );

      setSuccessMessage(
        `Two-Factor Authentication policy updated: 2FA is now ${
          targetValue === 'true' ? 'ENFORCED' : 'DISABLED'
        } for platform administrators.`
      );
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(`Failed to update 2FA policy: ${err.message}`);
      } else {
        setError('Failed to update 2FA policy due to an unexpected error.');
      }
    } finally {
      setIsUpdatingMfa(false);
    }
  };

  const getCategoryIcon = (key: string) => {
    if (key.startsWith('auth')) return KeyRound;
    if (key.startsWith('ai')) return Cpu;
    if (key.startsWith('extract')) return Archive;
    if (key.startsWith('judge')) return Scale;
    return Sliders;
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Platform Settings & Governance"
        description="Centralized platform configuration, cryptographic security policies, and AI evaluation parameters."
      >
        <button
          type="button"
          onClick={() => loadSettings()}
          disabled={isLoading || isUpdatingMfa}
          className="flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
          <span>Refresh</span>
        </button>
      </PageHeader>

      {/* Notifications */}
      {successMessage && (
        <div className="p-4 bg-status-success/10 border border-status-success/30 rounded-xl flex items-start gap-3">
          <CheckCircle2 className="w-5 h-5 text-status-success shrink-0 mt-0.5" />
          <div className="text-sm text-status-success">{successMessage}</div>
        </div>
      )}

      {error && (
        <div className="p-4 bg-status-error/10 border border-status-error/30 rounded-xl flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-status-error shrink-0 mt-0.5" />
          <div className="text-sm text-status-error">{error}</div>
        </div>
      )}

      {/* 2FA Master Switch Card */}
      <div className="p-6 bg-surface border border-surface-border rounded-2xl shadow-sm">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div className="flex items-start gap-4">
            <div className="w-12 h-12 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary shrink-0">
              <Shield className="w-6 h-6" />
            </div>
            <div className="space-y-1">
              <div className="flex items-center gap-3">
                <h2 className="text-lg font-semibold text-text-primary">
                  Mandatory Two-Factor Authentication (2FA / TOTP)
                </h2>
                <StatusBadge
                  status={isMfaEnforced ? 'active' : 'suspended'}
                  label={isMfaEnforced ? 'Enforced' : 'Disabled'}
                  size="sm"
                />
              </div>
              <p className="text-sm text-text-secondary max-w-2xl">
                Controls whether all platform administrators are required to provide a 6-digit TOTP verification token during sign in. When disabled, administrators can log in directly with their primary credentials.
              </p>
              <div className="pt-2 flex items-center gap-4 text-xs text-text-tertiary">
                <span className="font-mono bg-surface-elevated px-2 py-0.5 rounded border border-surface-border">
                  Key: auth.mfa_enforced
                </span>
                <span className="font-mono bg-surface-elevated px-2 py-0.5 rounded border border-surface-border">
                  Tier: 1 (Super Admin Modifiable)
                </span>
                {mfaSetting && (
                  <span>Version: v{mfaSetting.version}</span>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-4 self-end md:self-center">
            <button
              type="button"
              disabled={isLoading || isUpdatingMfa || !mfaSetting}
              onClick={handleToggleMfa}
              className={`relative inline-flex h-7 w-14 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 focus:ring-offset-background disabled:opacity-50 ${
                isMfaEnforced ? 'bg-primary' : 'bg-surface-elevated border-surface-border'
              }`}
              role="switch"
              aria-checked={isMfaEnforced}
            >
              <span className="sr-only">Toggle Two-Factor Authentication</span>
              <span
                className={`pointer-events-none inline-block h-6 w-6 transform rounded-full bg-white shadow-lg ring-0 transition duration-200 ease-in-out ${
                  isMfaEnforced ? 'translate-x-7' : 'translate-x-0'
                }`}
              />
            </button>
            <span className="text-sm font-medium text-text-primary w-20">
              {isUpdatingMfa ? 'Saving...' : isMfaEnforced ? 'Enabled' : 'Disabled'}
            </span>
          </div>
        </div>
      </div>

      {/* Configuration Catalog Overview */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Layers className="w-4 h-4 text-primary" />
            <h3 className="text-base font-semibold text-text-primary">
              All Centralized Configuration Parameters
            </h3>
          </div>
          <span className="text-xs text-text-tertiary">
            {settingsList.length} parameters registered in system catalog
          </span>
        </div>

        <div className="bg-surface border border-surface-border rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-surface-elevated/50 text-text-tertiary border-b border-surface-border text-xs uppercase tracking-wider">
                <tr>
                  <th scope="col" className="px-6 py-3 font-medium">Setting Key</th>
                  <th scope="col" className="px-6 py-3 font-medium">Tier & Scope</th>
                  <th scope="col" className="px-6 py-3 font-medium">Current Value</th>
                  <th scope="col" className="px-6 py-3 font-medium">Type</th>
                  <th scope="col" className="px-6 py-3 font-medium">Description</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-border">
                {isLoading ? (
                  <tr>
                    <td colSpan={5} className="px-6 py-8 text-center text-text-tertiary">
                      Loading configuration parameters...
                    </td>
                  </tr>
                ) : settingsList.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-6 py-8 text-center text-text-tertiary">
                      No configuration parameters found.
                    </td>
                  </tr>
                ) : (
                  settingsList.map((setting) => {
                    const IconComponent = getCategoryIcon(setting.key);
                    return (
                      <tr key={setting.key} className="hover:bg-surface-hover/50 transition-colors">
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-2.5">
                            <IconComponent className="w-4 h-4 text-text-tertiary shrink-0" />
                            <span className="font-mono text-xs font-semibold text-text-primary">
                              {setting.key}
                            </span>
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-2">
                            <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-surface-elevated text-text-secondary border border-surface-border uppercase">
                              {setting.tier.replace('_', ' ')}
                            </span>
                            {!setting.is_configurable && (
                              <span className="flex items-center gap-1 text-[11px] text-amber-400 font-medium">
                                <Lock className="w-3 h-3" />
                                Immutable
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <span className="font-mono text-xs font-medium text-primary bg-primary/10 px-2 py-0.5 rounded border border-primary/20">
                            {setting.current_value}
                          </span>
                        </td>
                        <td className="px-6 py-4 text-xs font-mono text-text-tertiary">
                          {setting.data_type}
                        </td>
                        <td className="px-6 py-4 text-xs text-text-secondary max-w-md">
                          {setting.description || 'No description provided.'}
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
    </div>
  );
}
