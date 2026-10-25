import { Bell } from 'lucide-react';
import { ModulePlaceholder } from '@/components/admin/ModulePlaceholder';

export default function NotificationsPage() {
  return (
    <ModulePlaceholder
      title="Platform Notifications"
      description="Platform-wide operational broadcasts, evaluation failure alerts, and email delivery dispatch logs."
      icon={Bell}
      targetPhase="Phase 5"
      routeSpec="/admin/notifications"
      prdSection="PRD §4.11 & Screen Spec §14"
    />
  );
}
