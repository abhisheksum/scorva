'use client';

import React, { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  Scale,
  ArrowLeft,
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  Clock,
  Sparkles,
  GitBranch,
  Github,
  FileText,
  ExternalLink,
  ChevronRight,
  LogOut,
  User,
  X,
  Save,
  Check,
  ShieldAlert,
} from 'lucide-react';
import { StatusBadge } from '@/components/admin/StatusBadge';
import { api, ApiClientError } from '@/lib/api-client';
import { useAuth } from '@/lib/auth-context';
import {
  JudgeHackathonDetail,
  JudgeQueueItem,
  JudgeSubmissionReviewResponse,
  SubmissionEvaluationTransparencyResponse,
} from '@/types/api';

export default function JudgeSubmissionsQueuePage() {
  const params = useParams();
  const router = useRouter();
  const hackathonId = params.hackathonId as string;
  const { user, logout } = useAuth();

  const [hackathon, setHackathon] = useState<JudgeHackathonDetail | null>(null);
  const [queue, setQueue] = useState<JudgeQueueItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // AI Assessment Modal State
  const [isAiModalOpen, setIsAiModalOpen] = useState(false);
  const [selectedSubForAi, setSelectedSubForAi] = useState<JudgeQueueItem | null>(null);
  const [aiTransparency, setAiTransparency] = useState<SubmissionEvaluationTransparencyResponse | null>(null);
  const [isLoadingAi, setIsLoadingAi] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);

  // Review Modal State
  const [isReviewModalOpen, setIsReviewModalOpen] = useState(false);
  const [selectedSubForReview, setSelectedSubForReview] = useState<JudgeQueueItem | null>(null);
  const [reviewData, setReviewData] = useState<JudgeSubmissionReviewResponse | null>(null);
  const [isLoadingReview, setIsLoadingReview] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [reviewSuccessMsg, setReviewSuccessMsg] = useState<string | null>(null);
  const [isSavingDraft, setIsSavingDraft] = useState(false);
  const [isSubmittingReview, setIsSubmittingReview] = useState(false);

  // Form State
  const [reviewOverallFeedback, setReviewOverallFeedback] = useState<string>('');
  const [reviewDecision, setReviewDecision] = useState<string>('accepted');
  const [reviewCriterionScores, setReviewCriterionScores] = useState<Record<string, { score: string; notes: string }>>({});

  const loadData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [hackathonRes, queueRes] = await Promise.all([
        api.getJudgeHackathonDetail(hackathonId),
        api.getJudgeHackathonSubmissions(hackathonId),
      ]);
      setHackathon(hackathonRes);
      setQueue(queueRes);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        if (err.status === 403 || err.code === 'FORBIDDEN_NOT_ASSIGNED_JUDGE') {
          setError('Access Denied: You are not assigned as a judge for this hackathon.');
        } else {
          setError(err.message);
        }
      } else {
        setError('Failed to load hackathon review queue.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (hackathonId) {
      loadData();
    }
  }, [hackathonId]);

  // Open AI modal
  const handleOpenAiModal = async (sub: JudgeQueueItem) => {
    setSelectedSubForAi(sub);
    setIsAiModalOpen(true);
    setIsLoadingAi(true);
    setAiError(null);
    try {
      const data = await api.getJudgeSubmissionTransparency(hackathonId, sub.submission_id);
      setAiTransparency(data);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setAiError(err.message);
      else setAiError('Failed to load AI evaluation assessment details.');
    } finally {
      setIsLoadingAi(false);
    }
  };

  // Open Review modal
  const handleOpenReviewModal = async (sub: JudgeQueueItem) => {
    setSelectedSubForReview(sub);
    setIsReviewModalOpen(true);
    setIsLoadingReview(true);
    setReviewError(null);
    setReviewSuccessMsg(null);
    try {
      const data = await api.getJudgeSubmissionReview(hackathonId, sub.submission_id);
      setReviewData(data);
      setReviewOverallFeedback(data.review?.overall_feedback || '');
      setReviewDecision(data.review?.decision || 'accepted');

      const initialScores: Record<string, { score: string; notes: string }> = {};
      if (data.review && data.review.criterion_scores) {
        data.review.criterion_scores.forEach((cs) => {
          initialScores[cs.criterion_id] = {
            score: cs.score !== null ? String(cs.score) : '',
            notes: cs.judge_notes || '',
          };
        });
      }
      setReviewCriterionScores(initialScores);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setReviewError(err.message);
      else setReviewError('Failed to load review form.');
    } finally {
      setIsLoadingReview(false);
    }
  };

  // Save Draft Review
  const handleSaveDraft = async () => {
    if (!selectedSubForReview || !reviewData) return;
    setIsSavingDraft(true);
    setReviewError(null);
    setReviewSuccessMsg(null);
    try {
      const criterion_scores = Object.entries(reviewCriterionScores)
        .filter(([, val]) => val.score.trim() !== '')
        .map(([criterion_id, val]) => ({
          criterion_id,
          score: val.score.trim(),
          judge_notes: val.notes.trim() || null,
        }));

      await api.saveJudgeSubmissionReviewDraft(hackathonId, selectedSubForReview.submission_id, {
        overall_feedback: reviewOverallFeedback.trim() || null,
        decision: reviewDecision || 'accepted',
        criterion_scores,
        version: reviewData.review?.version,
      });

      setReviewSuccessMsg('Draft saved successfully.');
      const refreshed = await api.getJudgeSubmissionReview(hackathonId, selectedSubForReview.submission_id);
      setReviewData(refreshed);
      // Refresh list
      const queueRes = await api.getJudgeHackathonSubmissions(hackathonId);
      setQueue(queueRes);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setReviewError(err.message);
      else setReviewError('Failed to save review draft.');
    } finally {
      setIsSavingDraft(false);
    }
  };

  // Submit Final Review
  const handleSubmitReview = async () => {
    if (!selectedSubForReview || !reviewData) return;
    if (!reviewOverallFeedback.trim()) {
      setReviewError('Overall review feedback is required before final submission.');
      return;
    }
    const allCriteriaScored = reviewData.rubric_criteria.every(
      (c) => reviewCriterionScores[c.id] && reviewCriterionScores[c.id].score.trim() !== ''
    );
    if (!allCriteriaScored) {
      setReviewError('All published criteria must be scored before submitting final review.');
      return;
    }

    if (!confirm('Submit your final review? Submitted reviews are permanently recorded and immutable.')) {
      return;
    }

    setIsSubmittingReview(true);
    setReviewError(null);
    setReviewSuccessMsg(null);
    try {
      const criterion_scores = reviewData.rubric_criteria.map((c) => ({
        criterion_id: c.id,
        score: reviewCriterionScores[c.id].score.trim(),
        judge_notes: reviewCriterionScores[c.id]?.notes?.trim() || null,
      }));

      await api.submitJudgeSubmissionReview(hackathonId, selectedSubForReview.submission_id, {
        overall_feedback: reviewOverallFeedback.trim(),
        decision: reviewDecision || 'accepted',
        criterion_scores,
        version: reviewData.review?.version,
      });

      setReviewSuccessMsg('Final review submitted successfully.');
      const refreshed = await api.getJudgeSubmissionReview(hackathonId, selectedSubForReview.submission_id);
      setReviewData(refreshed);
      // Refresh list
      const queueRes = await api.getJudgeHackathonSubmissions(hackathonId);
      setQueue(queueRes);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setReviewError(err.message);
      else setReviewError('Failed to submit final review.');
    } finally {
      setIsSubmittingReview(false);
    }
  };

  return (
    <div className="min-h-screen bg-surface-bg text-text-primary">
      {/* Top Header */}
      <header className="h-16 bg-surface border-b border-surface-border px-4 sm:px-6 flex items-center justify-between shrink-0 z-10">
        <div className="flex items-center gap-3">
          <Link
            href="/judge"
            className="flex items-center gap-1.5 text-xs text-text-muted hover:text-text-primary px-2 py-1 bg-surface-elevated rounded-lg border border-surface-border transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>Judge Events</span>
          </Link>
          <div className="hidden sm:block h-4 w-px bg-surface-border" />
          <div className="flex items-center gap-2">
            <span className="font-bold text-sm tracking-wide text-text-primary">
              {hackathon?.hackathon_title || 'Review Queue'}
            </span>
            <span className="text-xs text-text-muted font-normal">
              ({hackathon?.organization_name || 'Assigned Event'})
            </span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 pl-2 border-l border-surface-border">
            <div className="w-7 h-7 rounded-full bg-surface-elevated border border-surface-border flex items-center justify-center text-text-primary shrink-0">
              <User className="w-3.5 h-3.5 text-primary" />
            </div>
            <div className="hidden sm:flex flex-col text-left">
              <span className="text-xs font-semibold text-text-primary leading-tight">
                {user?.full_name || user?.email || 'Judge'}
              </span>
              <span className="text-[10px] text-text-muted leading-tight">
                Assigned Judge
              </span>
            </div>
            <button
              type="button"
              onClick={async () => {
                await logout();
              }}
              className="p-1.5 text-text-muted hover:text-status-error hover:bg-status-error/10 rounded-lg transition-colors ml-1"
              title="Log out"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      <div className="p-6 md:p-8 max-w-7xl mx-auto space-y-6">
        {/* Navigation Breadcrumb & Actions */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-surface-border pb-6">
          <div>
            <div className="flex items-center gap-2 text-xs text-text-muted mb-1">
              <Scale className="w-4 h-4 text-primary" />
              <Link href="/judge" className="hover:underline">Judge Workspace</Link>
              <span>•</span>
              <span className="text-text-primary font-medium">{hackathon?.hackathon_title}</span>
              <span>•</span>
              <span>Submissions Queue</span>
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-text-primary">
              Submissions Review Queue
            </h1>
            <p className="text-xs text-text-muted mt-1">
              AI evaluates the evidence. Judges make the decisions. Scorva makes the process transparent.
            </p>
          </div>

          <button
            type="button"
            onClick={loadData}
            disabled={isLoading}
            className="self-start md:self-auto px-3.5 py-2 text-xs font-semibold text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors inline-flex items-center gap-1.5 shadow-sm disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>Refresh Queue</span>
          </button>
        </div>

        {/* Error Alert */}
        {error && (
          <div className="p-6 rounded-2xl bg-surface border border-status-danger/30 text-center space-y-4 max-w-md mx-auto my-12">
            <ShieldAlert className="w-10 h-10 text-status-danger mx-auto" />
            <div>
              <h2 className="text-base font-bold text-text-primary">Judge Access Restricted</h2>
              <p className="text-xs text-text-muted mt-1">{error}</p>
            </div>
            <Link
              href="/judge"
              className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover rounded-lg transition-colors"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Return to Judge Workspace</span>
            </Link>
          </div>
        )}

        {/* Metrics Overview Cards */}
        {!error && hackathon && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="p-4 bg-surface rounded-xl border border-surface-border space-y-1">
              <span className="text-xs text-text-muted font-medium">Total Submissions</span>
              <div className="text-2xl font-bold font-mono text-text-primary">
                {hackathon.total_submissions}
              </div>
            </div>
            <div className="p-4 bg-surface rounded-xl border border-surface-border space-y-1">
              <span className="text-xs text-text-muted font-medium">Submitted Reviews</span>
              <div className="text-2xl font-bold font-mono text-status-success">
                {hackathon.my_submitted_count}
              </div>
            </div>
            <div className="p-4 bg-surface rounded-xl border border-surface-border space-y-1">
              <span className="text-xs text-text-muted font-medium">Draft Reviews</span>
              <div className="text-2xl font-bold font-mono text-status-warning">
                {hackathon.my_draft_count}
              </div>
            </div>
            <div className="p-4 bg-surface rounded-xl border border-surface-border space-y-1">
              <span className="text-xs text-text-muted font-medium">Awaiting Review</span>
              <div className="text-2xl font-bold font-mono text-text-muted">
                {hackathon.my_pending_count}
              </div>
            </div>
          </div>
        )}

        {/* Loading Queue */}
        {isLoading && (
          <div className="p-12 text-center text-text-muted space-y-3">
            <RefreshCw className="w-6 h-6 animate-spin mx-auto text-primary" />
            <p className="text-xs">Loading assigned submissions...</p>
          </div>
        )}

        {/* Queue Table */}
        {!isLoading && !error && queue.length === 0 && (
          <div className="p-12 text-center rounded-xl border border-surface-border bg-surface space-y-3">
            <FileText className="w-10 h-10 mx-auto text-text-muted/60" />
            <h3 className="text-sm font-semibold text-text-primary">No Submissions Found</h3>
            <p className="text-xs text-text-muted max-w-md mx-auto">
              There are currently no active team submissions registered for this hackathon.
            </p>
          </div>
        )}

        {!isLoading && !error && queue.length > 0 && (
          <div className="bg-surface rounded-xl border border-surface-border overflow-hidden shadow-xs">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-surface-border bg-surface-elevated/40 text-text-muted uppercase text-[10px] tracking-wider font-semibold">
                    <th className="py-3 px-4">Submission & Team</th>
                    <th className="py-3 px-4">Repository</th>
                    <th className="py-3 px-4">Advisory AI Assessment</th>
                    <th className="py-3 px-4">Your Review</th>
                    <th className="py-3 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-border">
                  {queue.map((item) => {
                    const hasAi =
                      item.ai_evaluation_status === 'completed' ||
                      (item.ai_normalized_score !== null && item.ai_normalized_score !== undefined);

                    return (
                      <tr key={item.submission_id} className="hover:bg-surface-elevated/30 transition-colors">
                        <td className="py-4 px-4">
                          <div className="font-semibold text-text-primary text-sm">
                            {item.title}
                          </div>
                          <div className="text-xs text-text-muted mt-0.5">
                            Team: <span className="text-text-primary font-medium">{item.team_name}</span>
                          </div>
                        </td>

                        <td className="py-4 px-4">
                          {item.repository_owner && item.repository_name ? (
                            <div className="space-y-1">
                              <div className="flex items-center gap-1.5 font-mono text-[11px] text-text-primary">
                                <Github className="w-3.5 h-3.5 text-text-muted" />
                                <span>{item.repository_owner}/{item.repository_name}</span>
                              </div>
                              {item.target_branch && (
                                <div className="flex items-center gap-1 font-mono text-[10px] text-text-muted">
                                  <GitBranch className="w-3 h-3" />
                                  <span>{item.target_branch}</span>
                                </div>
                              )}
                            </div>
                          ) : (
                            <span className="text-text-muted text-[11px] italic">No repository linked</span>
                          )}
                        </td>

                        <td className="py-4 px-4">
                          {item.ai_evaluation_status === 'completed' &&
                          item.ai_normalized_score !== null &&
                          item.ai_normalized_score !== undefined ? (
                            <div className="flex items-center gap-2">
                              <span className="px-2 py-0.5 rounded text-xs font-bold font-mono bg-primary/10 text-primary border border-primary/20">
                                {item.ai_normalized_score} / 100
                              </span>
                              <button
                                type="button"
                                onClick={() => handleOpenAiModal(item)}
                                className="text-[11px] text-primary hover:underline inline-flex items-center gap-1 ml-1"
                              >
                                <span>Inspect</span>
                                <ExternalLink className="w-3 h-3" />
                              </button>
                            </div>
                          ) : item.ai_evaluation_status === 'processing' ||
                            item.ai_evaluation_status === 'running' ||
                            item.ai_evaluation_status === 'queued' ? (
                            <div className="flex items-center gap-1.5 text-status-warning text-xs">
                              <RefreshCw className="w-3 h-3 animate-spin" />
                              <span>AI Ingesting...</span>
                            </div>
                          ) : (
                            <span className="text-text-muted text-xs">Not Evaluated</span>
                          )}
                        </td>

                        <td className="py-4 px-4">
                          {item.review_status === 'submitted' ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-status-success/10 text-status-success border border-status-success/20">
                              <CheckCircle2 className="w-3 h-3" />
                              <span>Submitted</span>
                            </span>
                          ) : item.review_status === 'draft' ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-status-warning/10 text-status-warning border border-status-warning/20">
                              <Clock className="w-3 h-3" />
                              <span>Draft</span>
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-surface-elevated text-text-muted border border-surface-border">
                              <span>Pending</span>
                            </span>
                          )}
                        </td>

                        <td className="py-4 px-4 text-right">
                          <button
                            type="button"
                            onClick={() => handleOpenReviewModal(item)}
                            className="px-3 py-1.5 text-xs font-semibold text-white bg-primary hover:bg-primary-hover rounded-lg transition-colors inline-flex items-center gap-1.5 shadow-xs"
                          >
                            <Scale className="w-3.5 h-3.5" />
                            <span>
                              {item.review_status === 'submitted'
                                ? 'View Review'
                                : item.review_status === 'draft'
                                ? 'Resume Review'
                                : 'Score Submission'}
                            </span>
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* AI Assessment Transparency Modal */}
      {isAiModalOpen && selectedSubForAi && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-surface border border-surface-border rounded-2xl max-w-3xl w-full max-h-[90vh] flex flex-col shadow-2xl animate-in fade-in zoom-in-95 duration-150">
            {/* Header */}
            <div className="p-5 border-b border-surface-border flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2 text-xs text-primary font-semibold">
                  <Sparkles className="w-4 h-4" />
                  <span>Advisory AI Evidence Analysis</span>
                </div>
                <h3 className="text-base font-bold text-text-primary mt-0.5">
                  {selectedSubForAi.title}
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setIsAiModalOpen(false)}
                className="p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-surface-elevated transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Body */}
            <div className="p-6 overflow-y-auto space-y-5 text-xs">
              {isLoadingAi ? (
                <div className="p-8 text-center text-text-muted space-y-2">
                  <RefreshCw className="w-5 h-5 animate-spin mx-auto text-primary" />
                  <p>Loading AI evaluation telemetry and grounded evidence...</p>
                </div>
              ) : aiError ? (
                <div className="p-4 rounded-xl bg-status-danger/10 border border-status-danger/20 text-status-danger">
                  {aiError}
                </div>
              ) : aiTransparency && aiTransparency.result ? (
                <>
                  <div className="p-4 bg-primary/5 border border-primary/15 rounded-xl space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-text-primary text-sm">Overall Advisory Assessment</span>
                      <span className="text-base font-bold font-mono text-primary">
                        {aiTransparency.result.normalized_score !== null && aiTransparency.result.normalized_score !== undefined
                          ? `${aiTransparency.result.normalized_score} / 100`
                          : 'Score Pending'}
                      </span>
                    </div>
                    {aiTransparency.result.summary_assessment && (
                      <p className="text-text-secondary leading-relaxed">
                        {aiTransparency.result.summary_assessment}
                      </p>
                    )}
                  </div>

                  <div className="space-y-4">
                    <h4 className="text-xs font-bold text-text-muted uppercase tracking-wider">
                      Criterion-Level Findings & Grounded Code References
                    </h4>
                    {aiTransparency.result.criterion_scores?.map((cs) => (
                      <div
                        key={cs.criterion_id}
                        className="p-4 bg-surface-elevated/40 rounded-xl border border-surface-border space-y-3"
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-semibold text-text-primary text-sm">{cs.title}</span>
                          <span className="font-mono font-bold text-xs px-2 py-0.5 rounded bg-surface border border-surface-border">
                            Advisory: {cs.awarded_score !== null && cs.awarded_score !== undefined ? cs.awarded_score : '—'} / {cs.max_score}
                          </span>
                        </div>
                        {cs.rationale && (
                          <p className="text-text-secondary leading-relaxed">{cs.rationale}</p>
                        )}

                        {/* Evidence References */}
                        {cs.evidence_references && cs.evidence_references.length > 0 && (
                          <div className="space-y-1.5 pt-2 border-t border-surface-border/50">
                            <span className="text-[10px] uppercase font-bold text-text-muted">Repository Evidence</span>
                            {cs.evidence_references.map((ev, idx) => (
                              <div
                                key={idx}
                                className="p-2 rounded bg-surface border border-surface-border/60 font-mono text-[11px] space-y-1"
                              >
                                <div className="text-primary font-medium flex items-center gap-1.5">
                                  <span>{ev.file_path}</span>
                                  {ev.start_line && (
                                    <span className="text-text-muted text-[10px]">
                                      (lines {ev.start_line}-{ev.end_line || ev.start_line})
                                    </span>
                                  )}
                                </div>
                                {ev.snippet && (
                                  <pre className="text-[10px] text-text-muted bg-surface-elevated p-2 rounded overflow-x-auto whitespace-pre-wrap">
                                    {ev.snippet}
                                  </pre>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <div className="p-6 text-center text-text-muted">
                  <p>No completed AI evaluation results available for this submission.</p>
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="p-4 border-t border-surface-border flex justify-end">
              <button
                type="button"
                onClick={() => setIsAiModalOpen(false)}
                className="px-4 py-2 text-xs font-semibold text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors"
              >
                Close Findings
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Judge Review & Scoring Modal */}
      {isReviewModalOpen && selectedSubForReview && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-surface border border-surface-border rounded-2xl max-w-4xl w-full max-h-[92vh] flex flex-col shadow-2xl animate-in fade-in zoom-in-95 duration-150">
            {/* Header */}
            <div className="p-5 border-b border-surface-border flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2 text-xs text-primary font-semibold">
                  <Scale className="w-4 h-4" />
                  <span>Independent Human Judge Review</span>
                  {reviewData?.review?.status === 'submitted' && (
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-status-success/10 text-status-success border border-status-success/20">
                      Immutable Review
                    </span>
                  )}
                  {reviewData?.review?.version && (
                    <span className="text-text-muted text-[10px] font-mono">
                      v{reviewData.review.version}
                    </span>
                  )}
                </div>
                <h3 className="text-base font-bold text-text-primary mt-0.5">
                  {selectedSubForReview.title}
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setIsReviewModalOpen(false)}
                className="p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-surface-elevated transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Body */}
            <div className="p-6 overflow-y-auto space-y-6 text-xs">
              {reviewError && (
                <div className="p-3 rounded-xl bg-status-danger/10 border border-status-danger/20 text-status-danger flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{reviewError}</span>
                </div>
              )}

              {reviewSuccessMsg && (
                <div className="p-3 rounded-xl bg-status-success/10 border border-status-success/20 text-status-success flex items-center gap-2">
                  <Check className="w-4 h-4 shrink-0" />
                  <span>{reviewSuccessMsg}</span>
                </div>
              )}

              {isLoadingReview ? (
                <div className="p-8 text-center text-text-muted space-y-2">
                  <RefreshCw className="w-5 h-5 animate-spin mx-auto text-primary" />
                  <p>Loading rubric and scoring form...</p>
                </div>
              ) : reviewData ? (
                <>
                  {/* Advisory Notice */}
                  <div className="p-3 rounded-xl bg-surface-elevated border border-surface-border text-text-muted text-[11px] flex items-center justify-between">
                    <span>
                      Scoring against rubric: <strong>{reviewData.rubric_name}</strong>
                    </span>
                    {reviewData.ai_evaluation?.normalized_score !== null &&
                      reviewData.ai_evaluation?.normalized_score !== undefined && (
                        <span className="font-mono text-primary font-semibold">
                          AI Advisory: {reviewData.ai_evaluation.normalized_score} / 100
                        </span>
                      )}
                  </div>

                  {/* Rubric Criteria Scoring Form */}
                  <div className="space-y-4">
                    <h4 className="text-xs font-bold text-text-muted uppercase tracking-wider">
                      Rubric Criteria Scoring
                    </h4>
                    {reviewData.rubric_criteria.map((criterion) => {
                      const currentVal = reviewCriterionScores[criterion.id] || { score: '', notes: '' };
                      const aiCrit = reviewData.ai_evaluation?.criterion_scores?.find(
                        (ac) => ac.criterion_id === criterion.id
                      );

                      return (
                        <div
                          key={criterion.id}
                          className="p-4 rounded-xl bg-surface-elevated/40 border border-surface-border space-y-3"
                        >
                          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                            <div>
                              <span className="font-semibold text-text-primary text-sm">{criterion.title}</span>
                              <p className="text-text-muted text-[11px] mt-0.5">{criterion.description}</p>
                            </div>
                            <div className="flex items-center gap-2">
                              {aiCrit && aiCrit.awarded_score !== null && aiCrit.awarded_score !== undefined && (
                                <span className="text-[10px] text-text-muted font-mono bg-surface px-2 py-1 rounded border border-surface-border">
                                  AI: {aiCrit.awarded_score}/{criterion.max_score}
                                </span>
                              )}
                              <div className="flex items-center gap-1">
                                <label className="text-text-muted text-[11px] font-medium">Score:</label>
                                <input
                                  type="number"
                                  step="0.1"
                                  min="0"
                                  max={Number(criterion.max_score)}
                                  value={currentVal.score}
                                  disabled={!reviewData.can_edit}
                                  onChange={(e) => {
                                    setReviewCriterionScores((prev) => ({
                                      ...prev,
                                      [criterion.id]: {
                                        score: e.target.value,
                                        notes: prev[criterion.id]?.notes || '',
                                      },
                                    }));
                                  }}
                                  className="w-20 px-2 py-1 bg-surface border border-surface-border rounded text-text-primary font-mono text-xs focus:outline-none focus:border-primary disabled:opacity-60"
                                  placeholder={`0-${criterion.max_score}`}
                                />
                                <span className="text-text-muted text-xs font-mono">/ {criterion.max_score}</span>
                              </div>
                            </div>
                          </div>

                          <div>
                            <input
                              type="text"
                              value={currentVal.notes}
                              disabled={!reviewData.can_edit}
                              onChange={(e) => {
                                setReviewCriterionScores((prev) => ({
                                  ...prev,
                                  [criterion.id]: {
                                    score: prev[criterion.id]?.score || '',
                                    notes: e.target.value,
                                  },
                                }));
                              }}
                              className="w-full px-3 py-1.5 bg-surface border border-surface-border rounded text-text-primary text-xs focus:outline-none focus:border-primary placeholder:text-text-muted/60 disabled:opacity-60"
                              placeholder="Add optional notes for this criterion..."
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {/* Decision & Overall Feedback */}
                  <div className="space-y-4 pt-2 border-t border-surface-border">
                    <div>
                      <label className="block text-xs font-bold text-text-muted uppercase tracking-wider mb-1.5">
                        Judge Decision
                      </label>
                      <select
                        value={reviewDecision}
                        disabled={!reviewData.can_edit}
                        onChange={(e) => setReviewDecision(e.target.value)}
                        className="w-full max-w-xs px-3 py-2 bg-surface border border-surface-border rounded-lg text-text-primary text-xs focus:outline-none focus:border-primary disabled:opacity-60"
                      >
                        <option value="accepted">Accepted (Meets standards)</option>
                        <option value="needs_revision">Needs Revision (Borderline)</option>
                        <option value="rejected">Rejected (Does not meet standards)</option>
                      </select>
                    </div>

                    <div>
                      <label className="block text-xs font-bold text-text-muted uppercase tracking-wider mb-1.5">
                        Overall Review Feedback (Required for submission)
                      </label>
                      <textarea
                        rows={4}
                        value={reviewOverallFeedback}
                        disabled={!reviewData.can_edit}
                        onChange={(e) => setReviewOverallFeedback(e.target.value)}
                        className="w-full px-3 py-2 bg-surface border border-surface-border rounded-lg text-text-primary text-xs focus:outline-none focus:border-primary placeholder:text-text-muted/60 disabled:opacity-60"
                        placeholder="Provide detailed qualitative evaluation of the repository, implementation quality, and alignment with the rubric..."
                      />
                    </div>
                  </div>
                </>
              ) : null}
            </div>

            {/* Footer */}
            <div className="p-4 border-t border-surface-border flex items-center justify-between">
              <span className="text-[11px] text-text-muted">
                {reviewData?.can_edit
                  ? 'Drafts can be resumed. Final submission permanently locks your review.'
                  : 'This review is finalized and immutable.'}
              </span>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setIsReviewModalOpen(false)}
                  className="px-4 py-2 text-xs font-semibold text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors"
                >
                  Close
                </button>

                {reviewData?.can_edit && (
                  <>
                    <button
                      type="button"
                      disabled={isSavingDraft || isSubmittingReview}
                      onClick={handleSaveDraft}
                      className="px-4 py-2 text-xs font-semibold text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors inline-flex items-center gap-1.5 disabled:opacity-50"
                    >
                      <Save className="w-3.5 h-3.5" />
                      <span>{isSavingDraft ? 'Saving Draft...' : 'Save Draft'}</span>
                    </button>

                    <button
                      type="button"
                      disabled={isSavingDraft || isSubmittingReview}
                      onClick={handleSubmitReview}
                      className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover rounded-lg transition-colors inline-flex items-center gap-1.5 shadow-sm disabled:opacity-50"
                    >
                      <Check className="w-3.5 h-3.5" />
                      <span>{isSubmittingReview ? 'Submitting...' : 'Submit Final Review'}</span>
                    </button>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
