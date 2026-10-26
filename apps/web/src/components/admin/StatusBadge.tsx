import React from 'react';
import { CheckCircle2, AlertTriangle, XCircle, Info, HelpCircle, FileEdit, Globe } from 'lucide-react';
import { HealthStatus, HackathonStatus, OrganizationStatus } from '@/types/api';

interface StatusBadgeProps {
  status: HealthStatus | OrganizationStatus | HackathonStatus | 'pending' | 'running' | 'failed' | 'queued' | 'cancelled' | string;
  label?: string;
  className?: string;
  size?: 'sm' | 'md';
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({
  status,
  label,
  className = '',
  size = 'md',
}) => {
  const displayLabel = label || status.charAt(0).toUpperCase() + status.slice(1);

  let badgeColor = 'bg-slate-800 text-slate-300 border-slate-700';
  let Icon = HelpCircle;

  switch (status.toLowerCase()) {
    case 'healthy':
    case 'active':
    case 'completed':
      badgeColor = 'bg-status-success/10 text-status-success border-status-success/30';
      Icon = CheckCircle2;
      break;
    case 'published':
      badgeColor = 'bg-primary/10 text-primary border-primary/30';
      Icon = Globe;
      break;
    case 'draft':
      badgeColor = 'bg-slate-800/80 text-slate-300 border-slate-700';
      Icon = FileEdit;
      break;
    case 'degraded':
    case 'pending':
    case 'running':
    case 'queued':
      badgeColor = 'bg-status-warning/10 text-status-warning border-status-warning/30';
      Icon = AlertTriangle;
      break;
    case 'unhealthy':
    case 'suspended':
    case 'failed':
      badgeColor = 'bg-status-error/10 text-status-error border-status-error/30';
      Icon = XCircle;
      break;
    case 'info':
      badgeColor = 'bg-status-info/10 text-status-info border-status-info/30';
      Icon = Info;
      break;
    case 'archived':
    case 'cancelled':
    case 'unknown':
    default:
      badgeColor = 'bg-slate-800 text-slate-400 border-slate-700';
      Icon = HelpCircle;
      break;
  }

  const sizeClasses = size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-xs';

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-medium rounded-full border ${badgeColor} ${sizeClasses} ${className}`}
      role="status"
    >
      <Icon className={size === 'sm' ? 'w-3 h-3' : 'w-3.5 h-3.5'} aria-hidden="true" />
      <span>{displayLabel}</span>
    </span>
  );
};
