'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth-context';
import { Shield, Loader2 } from 'lucide-react';

export default function HomePage() {
  const router = useRouter();
  const { user, isLoading } = useAuth();

  useEffect(() => {
    if (!isLoading) {
      if (user) {
        const dest =
          user.routing?.default_destination ||
          (user.platform_role ? '/admin' : '/participant');
        router.replace(dest);
      } else {
        router.replace('/login');
      }
    }
  }, [user, isLoading, router]);

  return (
    <div className="h-screen w-screen bg-background flex flex-col items-center justify-center gap-3">
      <div className="w-10 h-10 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
        <Shield className="w-5 h-5 animate-pulse" />
      </div>
      <div className="flex items-center gap-2 text-xs text-text-muted">
        <Loader2 className="w-3.5 h-3.5 animate-spin text-primary" />
        <span>Routing to your workspace...</span>
      </div>
    </div>
  );
}
