'use client';

import { useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';

export default function HackathonSubmissionsRedirect() {
  const params = useParams();
  const router = useRouter();
  const hackathonId = params.hackathonId as string;

  useEffect(() => {
    if (hackathonId) {
      router.replace(`/judge/projects?hackathon=${hackathonId}`);
    } else {
      router.replace('/judge/projects');
    }
  }, [hackathonId, router]);

  return null;
}
