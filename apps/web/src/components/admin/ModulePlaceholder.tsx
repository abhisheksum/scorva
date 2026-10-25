import React from 'react';
import { LucideIcon, Layers } from 'lucide-react';
import { PageHeader } from './PageHeader';
import { StatusBadge } from './StatusBadge';

interface ModulePlaceholderProps {
  title: string;
  description: string;
  icon: LucideIcon;
  targetPhase: string;
  routeSpec: string;
  prdSection: string;
}

export const ModulePlaceholder: React.FC<ModulePlaceholderProps> = ({
  title,
  description,
  icon: Icon,
  targetPhase,
  routeSpec,
  prdSection,
}) => {
  return (
    <div className="space-y-6">
      <PageHeader title={title} description={description}>
        <StatusBadge status="pending" label={`Scheduled for ${targetPhase}`} />
      </PageHeader>

      <div className="p-8 sm:p-12 rounded-xl bg-surface border border-surface-border flex flex-col items-center justify-center text-center max-w-2xl mx-auto space-y-4">
        <div className="w-14 h-14 rounded-2xl bg-surface-elevated border border-surface-border flex items-center justify-center text-primary shadow-sm">
          <Icon className="w-7 h-7" />
        </div>
        <div className="space-y-1">
          <h2 className="text-lg font-semibold text-text-primary">
            {title} Module Defined
          </h2>
          <p className="text-sm text-text-secondary">
            This module route is registered in the Super Admin application shell. Its backend API contracts and data models are defined in ARCHITECTURE.md and will be connected in {targetPhase}.
          </p>
        </div>

        <div className="w-full pt-4 mt-2 border-t border-surface-border grid grid-cols-2 gap-3 text-left">
          <div className="p-3 rounded-lg bg-surface-elevated/50 border border-surface-border/50 text-xs">
            <span className="text-text-muted font-medium block">Route Specification</span>
            <code className="text-primary font-mono mt-1 block">{routeSpec}</code>
          </div>
          <div className="p-3 rounded-lg bg-surface-elevated/50 border border-surface-border/50 text-xs">
            <span className="text-text-muted font-medium block">Requirement Reference</span>
            <span className="text-text-primary font-medium mt-1 block">{prdSection}</span>
          </div>
        </div>
      </div>
    </div>
  );
};
