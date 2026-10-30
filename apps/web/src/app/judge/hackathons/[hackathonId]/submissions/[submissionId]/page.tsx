'use client';

import React, { useState, useEffect, useMemo } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft,
  Scale,
  GitBranch,
  Github,
  CheckCircle2,
  AlertCircle,
  Copy,
  Check,
  ExternalLink,
  Bot,
  ShieldCheck,
  FileText,
  Save,
  Send,
  Lock,
  Calendar,
  Sparkles,
  RefreshCw,
  Sliders,
  ChevronDown,
  Info,
  Code,
} from 'lucide-react';
import { api, ApiClientError } from '@/lib/api-client';
import {
  JudgeSubmissionReviewResponse,
  SaveJudgeReviewRequest,
  SubmitJudgeReviewRequest,
} from '@/types/api';

export default function JudgeProjectReviewPage() {
  const params = useParams();
  const router = useRouter();
  const hackathonId = params.hackathonId as string;
  const submissionId = params.submissionId as string;

  const [reviewData, setReviewData] = useState<JudgeSubmissionReviewResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Form State
  const [criterionScores, setCriterionScores] = useState<
    Record<string, { score: number; notes: string }>
  >({});
  const [overallFeedback, setOverallFeedback] = useState('');
  const [decision, setDecision] = useState<string>('accepted');
  const [version, setVersion] = useState<number | undefined>(undefined);

  // UI state
  const [isSavingDraft, setIsSavingDraft] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isConfirmModalOpen, setIsConfirmModalOpen] = useState(false);
  const [statusMessage, setStatusMessage] = useState<{
    type: 'success' | 'error';
    text: string;
  } | null>(null);
  const [copiedSha, setCopiedSha] = useState(false);

  // Fetch submission review payload
  const fetchReview = async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const data = await api.getJudgeSubmissionReview(hackathonId, submissionId);
      setReviewData(data);

      // Populate form state from existing review or AI suggestions
      const scoresMap: Record<string, { score: number; notes: string }> = {};

      // Build criteria map from rubric criteria
      data.rubric_criteria.forEach((crit) => {
        // Find existing score if review exists
        const existingScore = data.review?.criterion_scores?.find(
          (cs) => cs.criterion_id === crit.id
        );

        if (existingScore && existingScore.score !== null && existingScore.score !== undefined) {
          scoresMap[crit.id] = {
            score: Number(existingScore.score),
            notes: existingScore.judge_notes || '',
          };
        } else {
          // If no judge score yet, leave at default midpoint or min
          const min = Number(crit.min_score) || 0;
          scoresMap[crit.id] = {
            score: min,
            notes: '',
          };
        }
      });

      setCriterionScores(scoresMap);
      setOverallFeedback(data.review?.overall_feedback || '');
      setDecision(data.review?.decision || 'accepted');
      setVersion(data.review?.version);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setLoadError(err.message);
      } else {
        setLoadError('Failed to load submission review details.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (hackathonId && submissionId) {
      fetchReview();
    }
  }, [hackathonId, submissionId]);

  // Live total score calculation
  const calculatedTotalScore = useMemo(() => {
    if (!reviewData || reviewData.rubric_criteria.length === 0) return 0;

    let weightedSum = 0;
    let totalWeight = 0;

    reviewData.rubric_criteria.forEach((crit) => {
      const weight = Number(crit.weight) || 1;
      const scoreObj = criterionScores[crit.id];
      const score = scoreObj ? scoreObj.score : 0;
      weightedSum += score * weight;
      totalWeight += weight;
    });

    if (totalWeight <= 0) return 0;
    return Number((weightedSum / totalWeight).toFixed(2));
  }, [reviewData, criterionScores]);

  // Copy commit sha
  const handleCopySha = (sha: string) => {
    navigator.clipboard.writeText(sha);
    setCopiedSha(true);
    setTimeout(() => setCopiedSha(false), 2000);
  };

  // Score change handler
  const handleScoreChange = (criterionId: string, newScore: number) => {
    if (!reviewData?.can_edit) return;
    setCriterionScores((prev) => ({
      ...prev,
      [criterionId]: {
        score: newScore,
        notes: prev[criterionId]?.notes || '',
      },
    }));
  };

  // Notes change handler
  const handleNotesChange = (criterionId: string, notes: string) => {
    if (!reviewData?.can_edit) return;
    setCriterionScores((prev) => ({
      ...prev,
      [criterionId]: {
        score: prev[criterionId]?.score || 0,
        notes,
      },
    }));
  };

  // Adopt AI suggested score for a criterion
  const handleAdoptAiScore = (criterionId: string, aiScore: number) => {
    if (!reviewData?.can_edit) return;
    handleScoreChange(criterionId, aiScore);
  };

  // Save Draft
  const handleSaveDraft = async () => {
    if (!reviewData || !reviewData.can_edit) return;
    setIsSavingDraft(true);
    setStatusMessage(null);

    const payload: SaveJudgeReviewRequest = {
      overall_feedback: overallFeedback || undefined,
      decision: decision || 'accepted',
      version: version,
      criterion_scores: Object.entries(criterionScores).map(([critId, val]) => ({
        criterion_id: critId,
        score: val.score,
        judge_notes: val.notes || undefined,
      })),
    };

    try {
      const updatedReview = await api.saveJudgeSubmissionReviewDraft(
        hackathonId,
        submissionId,
        payload
      );
      setVersion(updatedReview.version);
      setStatusMessage({
        type: 'success',
        text: 'Draft review saved successfully. Your progress is preserved.',
      });
      // Refresh review details
      const refreshed = await api.getJudgeSubmissionReview(hackathonId, submissionId);
      setReviewData(refreshed);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setStatusMessage({ type: 'error', text: err.message });
      } else {
        setStatusMessage({
          type: 'error',
          text: 'Failed to save review draft. Please check your network connection.',
        });
      }
    } finally {
      setIsSavingDraft(false);
    }
  };

  // Submit Final Review
  const handleSubmitFinal = async () => {
    if (!reviewData || !reviewData.can_edit) return;

    if (!overallFeedback.trim()) {
      setStatusMessage({
        type: 'error',
        text: 'Overall feedback is required before final submission.',
      });
      setIsConfirmModalOpen(false);
      return;
    }

    setIsSubmitting(true);
    setStatusMessage(null);

    const payload: SubmitJudgeReviewRequest = {
      overall_feedback: overallFeedback.trim(),
      decision: decision || 'accepted',
      version: version,
      criterion_scores: Object.entries(criterionScores).map(([critId, val]) => ({
        criterion_id: critId,
        score: val.score,
        judge_notes: val.notes || undefined,
      })),
    };

    try {
      await api.submitJudgeReview(hackathonId, submissionId, payload);
      setIsConfirmModalOpen(false);
      setStatusMessage({
        type: 'success',
        text: 'Review successfully submitted! Your scores and feedback are now recorded.',
      });
      // Refresh to lock the view
      const refreshed = await api.getJudgeSubmissionReview(hackathonId, submissionId);
      setReviewData(refreshed);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setStatusMessage({ type: 'error', text: err.message });
      } else {
        setStatusMessage({
          type: 'error',
          text: 'Failed to submit review. Please try again.',
        });
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="bg-white border border-[#E2E8F0] rounded-xl p-16 flex flex-col items-center justify-center gap-3">
        <RefreshCw className="w-8 h-8 text-[#2563EB] animate-spin" />
        <p className="text-sm font-medium text-[#64748B]">
          Loading submission review workspace...
        </p>
      </div>
    );
  }

  if (loadError || !reviewData) {
    return (
      <div className="bg-white border border-[#E2E8F0] rounded-xl p-8 max-w-2xl mx-auto text-center space-y-4">
        <AlertCircle className="w-10 h-10 text-red-500 mx-auto" />
        <h2 className="text-lg font-bold text-[#111827]">
          Unable to Load Submission
        </h2>
        <p className="text-xs text-[#64748B]">
          {loadError || 'The requested project could not be found or you do not have permission.'}
        </p>
        <div className="pt-2">
          <Link
            href="/judge/projects"
            className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-white bg-[#2563EB] rounded-lg hover:bg-blue-700 transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>Return to My Projects</span>
          </Link>
        </div>
      </div>
    );
  }

  const isSubmitted = reviewData.review?.status === 'submitted' || !reviewData.can_edit;

  return (
    <div className="space-y-8 pb-16">
      {/* Top Breadcrumb & Status Navigation */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-[#E2E8F0]">
        <div className="flex items-center gap-3">
          <Link
            href="/judge/projects"
            className="p-2 text-[#64748B] hover:text-[#111827] hover:bg-white rounded-lg border border-[#E2E8F0] transition-colors"
            title="Back to assigned projects"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <div className="flex items-center gap-2 text-xs text-[#64748B]">
              <span>Judge Workspace</span>
              <span>/</span>
              <span>{reviewData.hackathon_title || 'Hackathon Event'}</span>
            </div>
            <h1 className="text-xl font-bold tracking-tight text-[#111827] mt-0.5">
              {reviewData.submission_title}
            </h1>
          </div>
        </div>

        {/* Status Badge */}
        <div>
          {isSubmitted ? (
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-50 border border-emerald-200 text-xs font-bold text-emerald-800">
              <CheckCircle2 className="w-4 h-4 text-emerald-600" />
              <span>Review Submitted ({Number(reviewData.review?.score).toFixed(1)} / 100)</span>
            </div>
          ) : reviewData.review?.status === 'draft' ? (
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-blue-50 border border-blue-200 text-xs font-semibold text-[#2563EB]">
              <FileText className="w-4 h-4 text-[#2563EB]" />
              <span>Draft In Progress</span>
            </div>
          ) : (
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-amber-50 border border-amber-200 text-xs font-semibold text-amber-800">
              <Scale className="w-4 h-4 text-amber-600" />
              <span>Awaiting Evaluation</span>
            </div>
          )}
        </div>
      </div>

      {/* Status banner alerts */}
      {statusMessage && (
        <div
          className={`p-4 rounded-xl border flex items-start gap-3 text-xs ${
            statusMessage.type === 'success'
              ? 'bg-emerald-50 border-emerald-200 text-emerald-900'
              : 'bg-red-50 border-red-200 text-red-900'
          }`}
        >
          {statusMessage.type === 'success' ? (
            <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
          ) : (
            <AlertCircle className="w-4 h-4 text-red-600 shrink-0 mt-0.5" />
          )}
          <span className="font-medium">{statusMessage.text}</span>
        </div>
      )}

      {/* Submitted Review Banner (Locked State) */}
      {isSubmitted && (
        <div className="p-4 rounded-xl bg-slate-100 border border-[#CBD5E1] flex items-center justify-between text-xs text-[#334155]">
          <div className="flex items-center gap-2.5">
            <Lock className="w-4 h-4 text-[#64748B]" />
            <span>
              This review was finalized and submitted on{' '}
              <strong>
                {reviewData.review?.submitted_at
                  ? new Date(reviewData.review.submitted_at).toLocaleDateString()
                  : 'earlier'}
              </strong>
              . It is in read-only mode to maintain integrity.
            </span>
          </div>
          <span className="font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
            Locked
          </span>
        </div>
      )}

      {/* ========================================================
          SECTION A: PROJECT OVERVIEW
      ======================================================== */}
      <section className="bg-white border border-[#E2E8F0] rounded-xl p-6 shadow-xs space-y-4">
        <div className="flex items-center justify-between border-b border-[#E2E8F0] pb-3">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#2563EB]" />
            <h2 className="text-sm font-bold uppercase tracking-wider text-[#111827]">
              Section A: Project Overview
            </h2>
          </div>
          <span className="text-xs text-[#64748B]">Team: <strong className="text-[#111827]">{reviewData.team_name}</strong></span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="md:col-span-2 space-y-3">
            <div>
              <h3 className="text-xs font-semibold text-[#64748B] uppercase tracking-wider">
                Project Summary
              </h3>
              <p className="text-sm text-[#334155] mt-1 leading-relaxed whitespace-pre-line">
                {reviewData.description || 'No project description provided by the submitting team.'}
              </p>
            </div>
          </div>

          <div className="space-y-3 bg-[#F8FAFC] border border-[#E2E8F0] rounded-lg p-4">
            <h3 className="text-xs font-semibold text-[#64748B] uppercase tracking-wider">
              Submission Details
            </h3>
            <div className="space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-[#64748B]">Team:</span>
                <span className="font-semibold text-[#111827]">{reviewData.team_name}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#64748B]">Event:</span>
                <span className="font-medium text-[#111827]">{reviewData.hackathon_title || 'Hackathon'}</span>
              </div>
              {reviewData.created_at && (
                <div className="flex justify-between">
                  <span className="text-[#64748B]">Submitted:</span>
                  <span className="text-[#111827]">{new Date(reviewData.created_at).toLocaleDateString()}</span>
                </div>
              )}
              <div className="pt-2 border-t border-[#E2E8F0]">
                <a
                  href={reviewData.repository_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-[#2563EB] bg-[#EFF6FF] hover:bg-blue-100 rounded-md transition-colors border border-[#BFDBFE]"
                >
                  <Github className="w-3.5 h-3.5" />
                  <span>Open GitHub Repository</span>
                  <ExternalLink className="w-3 h-3 ml-0.5" />
                </a>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ========================================================
          SECTION B: SUBMISSION INFORMATION
      ======================================================== */}
      <section className="bg-white border border-[#E2E8F0] rounded-xl p-6 shadow-xs space-y-4">
        <div className="flex items-center justify-between border-b border-[#E2E8F0] pb-3">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#2563EB]" />
            <h2 className="text-sm font-bold uppercase tracking-wider text-[#111827]">
              Section B: Repository & Git Information
            </h2>
          </div>
          <span className="text-xs text-[#64748B]">Branch: <strong className="text-[#111827]">{reviewData.target_branch}</strong></span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 text-xs">
          {/* Repo Name */}
          <div className="p-3 bg-[#F8FAFC] border border-[#E2E8F0] rounded-lg">
            <span className="text-[#64748B] block font-medium">Repository</span>
            <span className="font-bold text-[#111827] block truncate mt-1">
              {reviewData.repository_owner ? `${reviewData.repository_owner}/${reviewData.repository_name}` : reviewData.repository_url}
            </span>
          </div>

          {/* Branch */}
          <div className="p-3 bg-[#F8FAFC] border border-[#E2E8F0] rounded-lg">
            <span className="text-[#64748B] block font-medium">Target Branch</span>
            <div className="flex items-center gap-1.5 mt-1 font-semibold text-[#111827]">
              <GitBranch className="w-3.5 h-3.5 text-[#2563EB]" />
              <span>{reviewData.target_branch}</span>
            </div>
          </div>

          {/* Commit SHA */}
          <div className="p-3 bg-[#F8FAFC] border border-[#E2E8F0] rounded-lg">
            <span className="text-[#64748B] block font-medium">Verified Commit</span>
            <div className="flex items-center gap-2 mt-1">
              <code className="bg-white px-2 py-0.5 rounded border border-[#E2E8F0] font-mono text-[11px] text-[#111827]">
                {reviewData.verified_commit_sha ? reviewData.verified_commit_sha.slice(0, 10) : 'Head SHA'}
              </code>
              {reviewData.verified_commit_sha && (
                <button
                  type="button"
                  onClick={() => handleCopySha(reviewData.verified_commit_sha || '')}
                  title="Copy full commit SHA"
                  className="p-1 text-[#64748B] hover:text-[#111827] rounded hover:bg-slate-200 transition-colors"
                >
                  {copiedSha ? (
                    <Check className="w-3.5 h-3.5 text-emerald-600" />
                  ) : (
                    <Copy className="w-3.5 h-3.5" />
                  )}
                </button>
              )}
            </div>
          </div>

          {/* Connection Status */}
          <div className="p-3 bg-[#F8FAFC] border border-[#E2E8F0] rounded-lg">
            <span className="text-[#64748B] block font-medium">Repository Connection</span>
            <span
              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold mt-1 ${
                reviewData.connection_status === 'verified'
                  ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                  : 'bg-amber-50 text-amber-700 border border-amber-200'
              }`}
            >
              <CheckCircle2 className="w-3 h-3" />
              <span className="capitalize">{reviewData.connection_status}</span>
            </span>
          </div>
        </div>
      </section>

      {/* ========================================================
          SECTION C: ADVISORY AI ASSESSMENT
      ======================================================== */}
      <section className="bg-white border border-[#E2E8F0] rounded-xl p-6 shadow-xs space-y-5">
        <div className="flex items-center justify-between border-b border-[#E2E8F0] pb-3">
          <div className="flex items-center gap-2">
            <Bot className="w-4 h-4 text-[#2563EB]" />
            <h2 className="text-sm font-bold uppercase tracking-wider text-[#111827]">
              Section C: AI Assessment & Evidence Citations
            </h2>
          </div>
          {reviewData.ai_evaluation?.normalized_score !== undefined && (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-[#EFF6FF] border border-[#BFDBFE] text-xs font-bold text-[#2563EB]">
              AI Overall: {Number(reviewData.ai_evaluation.normalized_score).toFixed(1)} / 100
            </span>
          )}
        </div>

        {/* Mandatory Guidance Notice */}
        <div className="p-4 rounded-xl bg-[#EFF6FF] border border-[#BFDBFE] flex items-start gap-3">
          <ShieldCheck className="w-5 h-5 text-[#2563EB] shrink-0 mt-0.5" />
          <div className="text-xs text-[#1E3A8A] leading-relaxed">
            <strong className="block text-sm font-bold mb-0.5 text-[#1E3A8A]">
              Advisory Guidance Notice
            </strong>
            AI assessment is provided as guidance. Your score and feedback are your independent decision. You are encouraged to review the code references below to verify implementation quality.
          </div>
        </div>

        {reviewData.ai_evaluation ? (
          <div className="space-y-5">
            {/* AI Summary Assessment */}
            <div className="p-4 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0] space-y-1.5">
              <span className="text-xs font-semibold text-[#64748B] uppercase tracking-wider">
                Automated Technical Analysis
              </span>
              <p className="text-xs text-[#334155] leading-relaxed">
                {reviewData.ai_evaluation.summary_assessment}
              </p>
            </div>

            {/* Criteria Level AI Findings */}
            {reviewData.ai_evaluation.criterion_scores &&
              reviewData.ai_evaluation.criterion_scores.length > 0 && (
                <div className="space-y-3">
                  <h3 className="text-xs font-bold text-[#111827] uppercase tracking-wider">
                    Criterion Level Suggestions & Code References
                  </h3>

                  <div className="grid grid-cols-1 gap-4">
                    {reviewData.ai_evaluation.criterion_scores.map((cs) => (
                      <div
                        key={cs.id || cs.criterion_id}
                        className="p-4 rounded-lg border border-[#E2E8F0] bg-white space-y-3"
                      >
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-[#F1F5F9] pb-2">
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-xs text-[#111827]">
                              {cs.title || 'Rubric Criterion'}
                            </span>
                            <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-[#EFF6FF] text-[#2563EB]">
                              Suggested: {Number(cs.awarded_score).toFixed(1)} / 100
                            </span>
                          </div>

                          {!isSubmitted && (
                            <button
                              type="button"
                              onClick={() =>
                                handleAdoptAiScore(cs.criterion_id, Number(cs.awarded_score))
                              }
                              className="text-[11px] font-semibold text-[#2563EB] hover:underline self-start sm:self-auto"
                            >
                              Use AI score ({Number(cs.awarded_score).toFixed(0)}) in rubric form
                            </button>
                          )}
                        </div>

                        {/* Rationale */}
                        <p className="text-xs text-[#475569] leading-relaxed">
                          {cs.rationale}
                        </p>

                        {/* Evidence References */}
                        {cs.evidence_references && cs.evidence_references.length > 0 && (
                          <div className="space-y-2 pt-2 border-t border-[#F1F5F9]">
                            <span className="text-[11px] font-semibold text-[#64748B] flex items-center gap-1.5">
                              <Code className="w-3.5 h-3.5 text-[#2563EB]" />
                              <span>Code References Cited:</span>
                            </span>

                            {cs.evidence_references.map((ev, idx) => (
                              <div
                                key={ev.id || idx}
                                className="rounded-lg bg-[#0F172A] p-3 text-slate-200 font-mono text-[11px] space-y-1.5"
                              >
                                <div className="flex items-center justify-between text-slate-400 text-[10px] pb-1 border-b border-slate-800">
                                  <span>
                                    {ev.file_path}
                                    {ev.start_line ? ` (Lines ${ev.start_line}-${ev.end_line})` : ''}
                                  </span>
                                  {ev.is_verified_in_repo && (
                                    <span className="text-emerald-400 font-semibold text-[10px]">
                                      ✓ Verified in Repository
                                    </span>
                                  )}
                                </div>
                                <pre className="overflow-x-auto whitespace-pre leading-relaxed text-slate-300">
                                  <code>{ev.snippet}</code>
                                </pre>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
          </div>
        ) : (
          <div className="p-8 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0] text-center space-y-2">
            <Bot className="w-8 h-8 text-[#94A3B8] mx-auto" />
            <h4 className="text-xs font-semibold text-[#111827]">
              AI evaluation not yet run for this project
            </h4>
            <p className="text-[11px] text-[#64748B] max-w-sm mx-auto">
              Automated AI evaluation is either queued or disabled for this event. You may proceed with human scoring directly.
            </p>
          </div>
        )}
      </section>

      {/* ========================================================
          SECTION D: JUDGE SCORING FORM
      ======================================================== */}
      <section className="bg-white border border-[#E2E8F0] rounded-xl p-6 shadow-xs space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-[#E2E8F0] pb-3">
          <div className="flex items-center gap-2">
            <Scale className="w-4 h-4 text-[#2563EB]" />
            <h2 className="text-sm font-bold uppercase tracking-wider text-[#111827]">
              Section D: Rubric Scoring Form
            </h2>
          </div>

          {/* Live Total Score Pill */}
          <div className="flex items-center gap-3 bg-[#F8FAFC] px-4 py-2 rounded-lg border border-[#E2E8F0]">
            <span className="text-xs font-medium text-[#64748B]">
              Calculated Total:
            </span>
            <span className="text-lg font-bold text-[#111827]">
              {calculatedTotalScore.toFixed(1)}
              <span className="text-xs font-normal text-[#64748B]"> / 100</span>
            </span>
          </div>
        </div>

        {/* Rubric Criteria List */}
        <div className="space-y-6">
          {reviewData.rubric_criteria.map((crit, index) => {
            const min = Number(crit.min_score) || 0;
            const max = Number(crit.max_score) || 100;
            const weightPercent = Math.round(Number(crit.weight) * 100);
            const currentScore = criterionScores[crit.id]?.score ?? min;
            const currentNotes = criterionScores[crit.id]?.notes ?? '';

            return (
              <div
                key={crit.id}
                className="p-5 rounded-xl border border-[#E2E8F0] bg-[#F8FAFC] space-y-4"
              >
                {/* Header */}
                <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-2">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="w-5 h-5 rounded-full bg-[#2563EB] text-white flex items-center justify-center font-bold text-[10px]">
                        {index + 1}
                      </span>
                      <h3 className="text-sm font-bold text-[#111827]">
                        {crit.title}
                      </h3>
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-[#EFF6FF] text-[#2563EB] border border-[#BFDBFE]">
                        Weight: {weightPercent}%
                      </span>
                    </div>
                    {crit.description && (
                      <p className="text-xs text-[#64748B] mt-1 pl-7">
                        {crit.description}
                      </p>
                    )}
                  </div>

                  {/* Numerical input */}
                  <div className="flex items-center gap-2 pl-7 sm:pl-0">
                    <span className="text-xs text-[#64748B] font-medium">Score:</span>
                    <input
                      type="number"
                      min={min}
                      max={max}
                      step={1}
                      disabled={isSubmitted}
                      value={currentScore}
                      onChange={(e) => {
                        const val = Math.min(
                          max,
                          Math.max(min, Number(e.target.value) || 0)
                        );
                        handleScoreChange(crit.id, val);
                      }}
                      className="w-20 px-3 py-1.5 text-center font-bold text-sm text-[#111827] bg-white border border-[#CBD5E1] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] disabled:bg-slate-100 disabled:text-slate-600 transition-colors"
                    />
                    <span className="text-xs text-[#64748B]">/ {max}</span>
                  </div>
                </div>

                {/* Score Slider */}
                <div className="pl-7 pr-2">
                  <input
                    type="range"
                    min={min}
                    max={max}
                    step={1}
                    disabled={isSubmitted}
                    value={currentScore}
                    onChange={(e) =>
                      handleScoreChange(crit.id, Number(e.target.value))
                    }
                    className="w-full accent-[#2563EB] cursor-pointer disabled:cursor-not-allowed"
                  />
                  <div className="flex justify-between text-[10px] text-[#94A3B8] mt-1 font-mono">
                    <span>{min} (Minimum)</span>
                    <span>{Math.round((min + max) / 2)}</span>
                    <span>{max} (Outstanding)</span>
                  </div>
                </div>

                {/* Criterion Notes */}
                <div className="pl-7 space-y-1">
                  <label className="text-xs font-semibold text-[#64748B] block">
                    Criterion Notes (Optional)
                  </label>
                  <textarea
                    rows={2}
                    disabled={isSubmitted}
                    value={currentNotes}
                    onChange={(e) => handleNotesChange(crit.id, e.target.value)}
                    placeholder={`Notes on ${crit.title.toLowerCase()} implementation, architecture, or edge cases...`}
                    className="w-full px-3 py-2 text-xs text-[#111827] bg-white border border-[#CBD5E1] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] disabled:bg-slate-100 disabled:text-slate-600 placeholder-[#94A3B8] transition-colors resize-y"
                  />
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* ========================================================
          SECTION E: WRITTEN FEEDBACK
      ======================================================== */}
      <section className="bg-white border border-[#E2E8F0] rounded-xl p-6 shadow-xs space-y-5">
        <div className="flex items-center gap-2 border-b border-[#E2E8F0] pb-3">
          <FileText className="w-4 h-4 text-[#2563EB]" />
          <h2 className="text-sm font-bold uppercase tracking-wider text-[#111827]">
            Section E: Written Feedback & Recommendation
          </h2>
        </div>

        <div className="space-y-4">
          {/* Decision recommendation */}
          <div className="space-y-1.5 max-w-xs">
            <label className="text-xs font-bold text-[#111827] block">
              Recommendation Decision:
            </label>
            <select
              disabled={isSubmitted}
              value={decision}
              onChange={(e) => setDecision(e.target.value)}
              className="w-full px-3 py-2 text-xs font-semibold text-[#111827] bg-[#F8FAFC] border border-[#CBD5E1] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] disabled:bg-slate-100 disabled:text-slate-600 transition-colors"
            >
              <option value="accepted">Accepted / Recommend for Award</option>
              <option value="adjusted">Adjusted / Qualified</option>
              <option value="rejected">Rejected / Needs Major Rework</option>
            </select>
          </div>

          {/* Overall feedback textarea */}
          <div className="space-y-1.5">
            <label className="text-xs font-bold text-[#111827] block">
              Overall Constructive Feedback{' '}
              <span className="text-red-500 font-normal">
                (Mandatory for final submission)
              </span>
            </label>
            <textarea
              rows={5}
              disabled={isSubmitted}
              value={overallFeedback}
              onChange={(e) => setOverallFeedback(e.target.value)}
              placeholder="Provide constructive feedback for the team. Detail key strengths, innovative aspects, architecture soundness, and recommendations for future iterations..."
              className="w-full px-4 py-3 text-xs text-[#111827] bg-[#F8FAFC] border border-[#CBD5E1] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:bg-white disabled:bg-slate-100 disabled:text-slate-600 placeholder-[#94A3B8] transition-colors resize-y leading-relaxed"
            />
            <p className="text-[11px] text-[#64748B]">
              This feedback will be accessible to event organizers and may be shared with the team following the judging period.
            </p>
          </div>
        </div>
      </section>

      {/* ========================================================
          SECTION F: ACTIONS
      ======================================================== */}
      <section className="bg-white border border-[#E2E8F0] rounded-xl p-6 shadow-xs flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <span className="text-xs font-semibold text-[#64748B] block">
            Weighted Total Score:
          </span>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-[#111827]">
              {calculatedTotalScore.toFixed(1)}
            </span>
            <span className="text-xs text-[#64748B]">out of 100 points</span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Link
            href="/judge/projects"
            className="px-4 py-2.5 text-xs font-semibold text-[#64748B] hover:text-[#111827] hover:bg-[#F8FAFC] border border-[#E2E8F0] rounded-lg transition-colors"
          >
            Cancel / Back
          </Link>

          {!isSubmitted && (
            <>
              <button
                type="button"
                onClick={handleSaveDraft}
                disabled={isSavingDraft || isSubmitting}
                className="inline-flex items-center gap-2 px-4 py-2.5 text-xs font-semibold text-[#2563EB] bg-[#EFF6FF] border border-[#BFDBFE] hover:bg-blue-100 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] disabled:opacity-50 transition-colors shadow-xs"
              >
                <Save className="w-3.5 h-3.5" />
                <span>{isSavingDraft ? 'Saving Draft...' : 'Save Draft'}</span>
              </button>

              <button
                type="button"
                onClick={() => setIsConfirmModalOpen(true)}
                disabled={isSavingDraft || isSubmitting}
                className="inline-flex items-center gap-2 px-5 py-2.5 text-xs font-semibold text-white bg-[#2563EB] hover:bg-blue-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-[#2563EB] disabled:opacity-50 transition-colors shadow-xs"
              >
                <Send className="w-3.5 h-3.5" />
                <span>Submit Final Review</span>
              </button>
            </>
          )}
        </div>
      </section>

      {/* ========================================================
          CONFIRMATION MODAL FOR FINAL SUBMISSION
      ======================================================== */}
      {isConfirmModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-xs">
          <div className="bg-white border border-[#E2E8F0] rounded-xl max-w-md w-full p-6 shadow-xl space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-blue-50 border border-blue-200 flex items-center justify-center text-[#2563EB]">
                <Scale className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-base font-bold text-[#111827]">
                  Confirm Final Review Submission
                </h3>
                <p className="text-xs text-[#64748B]">
                  Project: {reviewData.submission_title}
                </p>
              </div>
            </div>

            <div className="p-4 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0] space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-[#64748B]">Awarded Score:</span>
                <span className="font-bold text-[#111827]">{calculatedTotalScore.toFixed(1)} / 100</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#64748B]">Recommendation:</span>
                <span className="font-semibold capitalize text-[#111827]">{decision}</span>
              </div>
              <div className="pt-2 border-t border-[#E2E8F0] text-[#D97706] font-medium leading-relaxed">
                Notice: Submitting this review is final and locks your scores into the event leaderboard. You will not be able to edit this review after submitting.
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setIsConfirmModalOpen(false)}
                disabled={isSubmitting}
                className="px-4 py-2 text-xs font-semibold text-[#64748B] hover:text-[#111827] rounded-lg border border-[#E2E8F0] hover:bg-[#F8FAFC] transition-colors"
              >
                Go Back
              </button>
              <button
                type="button"
                onClick={handleSubmitFinal}
                disabled={isSubmitting}
                className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-white bg-[#2563EB] hover:bg-blue-700 rounded-lg transition-colors shadow-xs"
              >
                {isSubmitting ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    <span>Submitting...</span>
                  </>
                ) : (
                  <>
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    <span>Confirm & Submit</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
