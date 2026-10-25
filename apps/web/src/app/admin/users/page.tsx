import { Users } from 'lucide-react';
import { ModulePlaceholder } from '@/components/admin/ModulePlaceholder';

export default function UsersPage() {
  return (
    <ModulePlaceholder
      title="Users & Access Management"
      description="Super Admin oversight of platform-wide user accounts, platform roles, MFA, and active sessions."
      icon={Users}
      targetPhase="Phase 3"
      routeSpec="/admin/users"
      prdSection="PRD §4.3 & Screen Spec §6"
    />
  );
}
