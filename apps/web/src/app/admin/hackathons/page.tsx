import { Trophy } from 'lucide-react';
import { ModulePlaceholder } from '@/components/admin/ModulePlaceholder';

export default function HackathonsPage() {
  return (
    <ModulePlaceholder
      title="Hackathon Oversight"
      description="Cross-tenant visibility into active hackathon events, submissions, rubric assignments, and evaluation progress."
      icon={Trophy}
      targetPhase="Phase 3"
      routeSpec="/admin/hackathons"
      prdSection="PRD §4.4 & Screen Spec §7"
    />
  );
}
