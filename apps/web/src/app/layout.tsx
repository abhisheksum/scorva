import type { Metadata, Viewport } from 'next';
import './globals.css';
import { Providers } from '@/components/providers';

export const metadata: Metadata = {
  title: 'Scorva — AI-Assisted Hackathon Evaluation',
  description:
    'Scorva central administrative control center for hackathon management, AI evaluation pipelines, and platform operations.',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: '#0B1020',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark h-full">
      <body className="h-full bg-background text-text-primary antialiased selection:bg-primary/30 selection:text-white">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
