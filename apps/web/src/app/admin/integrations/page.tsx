import { Blocks } from 'lucide-react';
import { ModulePlaceholder } from '@/components/admin/ModulePlaceholder';

export default function IntegrationsPage() {
  return (
    <ModulePlaceholder
      title="Platform Integrations"
      description="Manage connections and credential rotation for GitHub App, Ollama endpoints, S3 storage, and email services."
      icon={Blocks}
      targetPhase="Phase 5"
      routeSpec="/admin/integrations"
      prdSection="PRD §4.12 & Screen Spec §15"
    />
  );
}
