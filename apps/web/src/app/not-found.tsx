import Link from 'next/link';

export default function NotFound() {
  return (
    <div className="min-h-screen bg-background flex flex-col items-center justify-center p-4">
      <h1 className="text-4xl font-bold text-text-primary mb-2">404</h1>
      <p className="text-text-muted mb-6">Page not found</p>
      <Link
        href="/admin"
        className="px-4 py-2 bg-primary hover:bg-primary-hover text-white rounded-lg text-sm"
      >
        Return to Admin
      </Link>
    </div>
  );
}
