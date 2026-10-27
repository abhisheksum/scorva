'use client';

import React, { useState, useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  Shield,
  Lock,
  Mail,
  KeyRound,
  AlertCircle,
  CheckCircle2,
  Copy,
  Check,
  ArrowRight,
  ArrowLeft,
  Loader2,
} from 'lucide-react';
import { api, ApiClientError } from '@/lib/api-client';
import { useAuth } from '@/lib/auth-context';

type AuthStep = 'credentials' | 'mfa_setup' | 'mfa_verify';

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, refreshUser } = useAuth();

  const [step, setStep] = useState<AuthStep>('credentials');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [token, setToken] = useState(''); // challenge or enrollment token
  const [mfaSecret, setMfaSecret] = useState('');
  const [copiedSecret, setCopiedSecret] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // If already authenticated, redirect to user default destination
  useEffect(() => {
    if (user) {
      const destination = user.routing?.default_destination || (user.platform_role ? '/admin' : '/participant');
      router.push(destination);
    }
  }, [user, router]);

  // Check for expired session notice
  useEffect(() => {
    if (searchParams.get('expired') === '1') {
      setError('Your session has expired or was revoked. Please log in again.');
    }
  }, [searchParams]);

  const handleCredentialsSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      const redirectParam = searchParams.get('redirect') || searchParams.get('return_to') || undefined;
      const response = await api.login(email.trim(), password, redirectParam);

      if (response.mfa_required) {
        if (!response.enrolled && response.enrollment_token) {
          // Admin needs to enroll TOTP
          setToken(response.enrollment_token);
          const setupData = await api.setupMfa(response.enrollment_token);
          setMfaSecret(setupData.secret);
          setStep('mfa_setup');
        } else if (response.challenge_token) {
          // Admin already enrolled, needs to provide TOTP challenge
          setToken(response.challenge_token);
          setStep('mfa_verify');
        }
      } else {
        // MFA not required or non-admin session created
        if ('user' in response && response.user) {
          await refreshUser(response.user);
        } else {
          await refreshUser();
        }
        const target = ('default_destination' in response && response.default_destination)
          ? response.default_destination
          : (('user' in response && response.user?.routing?.default_destination) || '/participant');
        router.push(target);
      }
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('An unexpected error occurred during sign in. Please try again.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleMfaSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (totpCode.trim().length !== 6) {
      setError('Please enter a valid 6-digit authentication code.');
      return;
    }

    setError(null);
    setIsSubmitting(true);

    try {
      const authRes = await api.verifyMfa(token, totpCode.trim());
      await refreshUser(authRes.user);
      const target = authRes.default_destination || authRes.user?.routing?.default_destination || '/admin';
      router.push(target);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to verify authentication code. Please try again.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCopySecret = () => {
    if (mfaSecret) {
      navigator.clipboard.writeText(mfaSecret);
      setCopiedSecret(true);
      setTimeout(() => setCopiedSecret(false), 2500);
    }
  };

  const resetToCredentials = () => {
    setStep('credentials');
    setToken('');
    setTotpCode('');
    setMfaSecret('');
    setError(null);
  };

  return (
    <div className="min-h-screen bg-background flex flex-col justify-center items-center p-4 sm:p-6 lg:p-8">
      {/* Background radial gradient decoration */}
      <div className="fixed inset-0 pointer-events-none bg-[radial-gradient(circle_at_top,_var(--tw-gradient-stops))] from-primary/10 via-background to-background" />

      <div className="w-full max-w-md relative z-10">
        {/* Branding Header */}
        <div className="flex flex-col items-center text-center mb-8">
          <div className="w-12 h-12 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary mb-3 shadow-lg shadow-primary/10">
            <Shield className="w-6 h-6" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-text-primary">
            SCORVA
          </h1>
          <p className="text-xs uppercase tracking-widest text-text-muted mt-1 font-semibold">
            Super Admin Control Center
          </p>
        </div>

        {/* Card Container */}
        <div className="bg-surface border border-surface-border rounded-xl shadow-surface-elevated p-6 sm:p-8 backdrop-blur-sm">
          {/* Error Banner */}
          {error && (
            <div className="mb-6 p-3.5 bg-status-error/10 border border-status-error/20 rounded-lg flex items-start gap-3 text-status-error text-xs leading-relaxed animate-in fade-in duration-200">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {/* STEP 1: CREDENTIALS */}
          {step === 'credentials' && (
            <form onSubmit={handleCredentialsSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1.5">
                  Admin Email Address
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-text-muted">
                    <Mail className="w-4 h-4" />
                  </div>
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="admin@scorva.io"
                    className="w-full pl-9 pr-3.5 py-2.5 bg-surface-elevated border border-surface-border rounded-lg text-sm text-text-primary placeholder:text-text-muted/60 focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary transition-colors"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1.5">
                  Password
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-text-muted">
                    <Lock className="w-4 h-4" />
                  </div>
                  <input
                    type="password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••••••"
                    className="w-full pl-9 pr-3.5 py-2.5 bg-surface-elevated border border-surface-border rounded-lg text-sm text-text-primary placeholder:text-text-muted/60 focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary transition-colors"
                  />
                </div>
              </div>

              <div className="pt-2">
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="w-full py-2.5 px-4 bg-primary hover:bg-primary-hover disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2 shadow-sm"
                >
                  {isSubmitting ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span>Authenticating...</span>
                    </>
                  ) : (
                    <>
                      <span>Sign In</span>
                      <ArrowRight className="w-4 h-4" />
                    </>
                  )}
                </button>
              </div>

              {/* Development presets helper */}
              <div className="pt-3 border-t border-surface-border">
                <div className="text-[11px] text-text-muted mb-2 font-medium">
                  Development Quick-Login Personas (Password: <code className="text-primary font-mono font-semibold">Password123!</code>):
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <button
                    type="button"
                    onClick={() => {
                      setEmail('admin@scorva.io');
                      setPassword('Password123!');
                      setError(null);
                    }}
                    className="p-2 text-left bg-surface-elevated hover:bg-surface-border/50 border border-surface-border rounded-lg transition-colors cursor-pointer"
                  >
                    <div className="font-medium text-text-primary truncate">admin@scorva.io</div>
                    <div className="text-[10px] text-primary mt-0.5">Super Admin (Direct Login)</div>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setEmail('organizer@scorva.io');
                      setPassword('Password123!');
                      setError(null);
                    }}
                    className="p-2 text-left bg-surface-elevated hover:bg-surface-border/50 border border-surface-border rounded-lg transition-colors cursor-pointer"
                  >
                    <div className="font-medium text-text-primary truncate">organizer@scorva.io</div>
                    <div className="text-[10px] text-text-muted mt-0.5">Tenant Organizer</div>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setEmail('judge@scorva.io');
                      setPassword('Password123!');
                      setError(null);
                    }}
                    className="p-2 text-left bg-surface-elevated hover:bg-surface-border/50 border border-surface-border rounded-lg transition-colors cursor-pointer"
                  >
                    <div className="font-medium text-text-primary truncate">judge@scorva.io</div>
                    <div className="text-[10px] text-text-muted mt-0.5">Assigned Judge</div>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setEmail('participant@scorva.io');
                      setPassword('Password123!');
                      setError(null);
                    }}
                    className="p-2 text-left bg-surface-elevated hover:bg-surface-border/50 border border-surface-border rounded-lg transition-colors cursor-pointer"
                  >
                    <div className="font-medium text-text-primary truncate">participant@scorva.io</div>
                    <div className="text-[10px] text-text-muted mt-0.5">Team Participant</div>
                  </button>
                </div>
              </div>

              <div className="pt-2 text-center">
                <p className="text-[11px] text-text-muted">
                  Scorva platform authentication gateway. Direct Super Admin access enabled for development.
                </p>
              </div>
            </form>
          )}

          {/* STEP 2: MFA ENROLLMENT */}
          {step === 'mfa_setup' && (
            <form onSubmit={handleMfaSubmit} className="space-y-4">
              <div className="text-center mb-4">
                <div className="w-10 h-10 rounded-full bg-primary/10 border border-primary/20 text-primary mx-auto flex items-center justify-center mb-2">
                  <KeyRound className="w-5 h-5" />
                </div>
                <h2 className="text-base font-semibold text-text-primary">
                  Set Up Two-Factor Authentication
                </h2>
                <p className="text-xs text-text-muted mt-1">
                  MFA is mandatory for all administrative roles. Add this key to your authenticator app (Google Authenticator, 1Password, Authy).
                </p>
              </div>

              {/* Secret key box */}
              <div className="p-3 bg-surface-elevated border border-surface-border rounded-lg space-y-1.5">
                <div className="flex items-center justify-between text-[11px] text-text-muted">
                  <span>Manual Entry Secret Key</span>
                  <button
                    type="button"
                    onClick={handleCopySecret}
                    className="flex items-center gap-1 text-primary hover:underline"
                  >
                    {copiedSecret ? (
                      <>
                        <Check className="w-3 h-3 text-status-success" />
                        <span className="text-status-success">Copied</span>
                      </>
                    ) : (
                      <>
                        <Copy className="w-3 h-3" />
                        <span>Copy</span>
                      </>
                    )}
                  </button>
                </div>
                <div className="font-mono text-xs text-text-primary tracking-widest break-all select-all font-semibold py-1">
                  {mfaSecret}
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1.5 text-center">
                  Enter 6-Digit Code from App
                </label>
                <input
                  type="text"
                  maxLength={6}
                  required
                  autoFocus
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ''))}
                  placeholder="000000"
                  className="w-full text-center tracking-[0.5em] font-mono text-xl py-2.5 bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary"
                />
              </div>

              <div className="pt-2 flex flex-col gap-2">
                <button
                  type="submit"
                  disabled={isSubmitting || totpCode.length !== 6}
                  className="w-full py-2.5 px-4 bg-primary hover:bg-primary-hover disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2"
                >
                  {isSubmitting ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span>Enrolling...</span>
                    </>
                  ) : (
                    <>
                      <CheckCircle2 className="w-4 h-4" />
                      <span>Complete MFA Enrollment</span>
                    </>
                  )}
                </button>

                <button
                  type="button"
                  onClick={resetToCredentials}
                  className="w-full py-2 text-xs text-text-muted hover:text-text-primary transition-colors flex items-center justify-center gap-1.5"
                >
                  <ArrowLeft className="w-3.5 h-3.5" />
                  <span>Back to login</span>
                </button>
              </div>
            </form>
          )}

          {/* STEP 3: MFA VERIFICATION */}
          {step === 'mfa_verify' && (
            <form onSubmit={handleMfaSubmit} className="space-y-4">
              <div className="text-center mb-4">
                <div className="w-10 h-10 rounded-full bg-primary/10 border border-primary/20 text-primary mx-auto flex items-center justify-center mb-2">
                  <KeyRound className="w-5 h-5" />
                </div>
                <h2 className="text-base font-semibold text-text-primary">
                  Two-Factor Verification
                </h2>
                <p className="text-xs text-text-muted mt-1">
                  Enter the 6-digit verification code from your authenticator application.
                </p>
              </div>

              <div>
                <input
                  type="text"
                  maxLength={6}
                  required
                  autoFocus
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ''))}
                  placeholder="000000"
                  className="w-full text-center tracking-[0.5em] font-mono text-xl py-2.5 bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary"
                />
              </div>

              {email === 'owner@scorva.io' && (
                <div className="p-2.5 bg-primary/10 border border-primary/20 rounded-lg text-xs text-text-secondary text-center space-y-1">
                  <div className="text-[11px] text-text-muted">Development Authenticator Seed:</div>
                  <div className="font-mono font-semibold text-primary select-all">JBSWY3DPEHPK3PXP</div>
                  <div className="text-[10px] text-text-muted">Add to authenticator app or test with <code>pyotp</code></div>
                </div>
              )}

              <div className="pt-2 flex flex-col gap-2">
                <button
                  type="submit"
                  disabled={isSubmitting || totpCode.length !== 6}
                  className="w-full py-2.5 px-4 bg-primary hover:bg-primary-hover disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2"
                >
                  {isSubmitting ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span>Verifying...</span>
                    </>
                  ) : (
                    <>
                      <span>Verify Identity</span>
                      <ArrowRight className="w-4 h-4" />
                    </>
                  )}
                </button>

                <button
                  type="button"
                  onClick={resetToCredentials}
                  className="w-full py-2 text-xs text-text-muted hover:text-text-primary transition-colors flex items-center justify-center gap-1.5"
                >
                  <ArrowLeft className="w-3.5 h-3.5" />
                  <span>Back to login</span>
                </button>
              </div>
            </form>
          )}
        </div>

        {/* Security badge at bottom */}
        <div className="mt-6 text-center">
          <p className="text-[11px] text-text-muted flex items-center justify-center gap-1.5">
            <Shield className="w-3.5 h-3.5 text-primary" />
            <span>Encrypted Session • CSRF Protected • Argon2id & AES-256-GCM</span>
          </p>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-background flex items-center justify-center">
          <div className="w-8 h-8 rounded-full border-2 border-primary border-t-transparent animate-spin" />
        </div>
      }
    >
      <LoginForm />
    </Suspense>
  );
}
