import { LucideIcon } from 'lucide-react';

export type PlatformRole =
  | 'platform_owner'
  | 'platform_ops_admin'
  | 'ai_ops_admin'
  | 'security_admin'
  | 'support_admin'
  | 'billing_admin';

export interface AdminUser {
  id: string;
  email: string;
  fullName: string;
  platformRole: PlatformRole;
  avatarUrl?: string;
}

export interface NavItem {
  title: string;
  href: string;
  icon: LucideIcon;
  badge?: string | number;
  priority: 'P0' | 'P1' | 'P2';
  submodules?: { title: string; href: string }[];
}

export interface NavSection {
  title: string;
  items: NavItem[];
}
