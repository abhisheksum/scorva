'use client';

import React, { useState, useEffect, useCallback, useRef, use } from 'react';
import Link from 'next/link';
import {
  Trophy,
  ChevronLeft,
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  Calendar,
  Clock,
  Globe,
  CheckCheck,
  Archive,
  ShieldAlert,
  FileText,
  Copy,
  Check,
  Edit,
  X,
  Users,
  GitBranch,
  Scale,
  Plus,
  Trash2,
  ExternalLink,
  Award,
  Layers,
  Send,
  Link2,
  Unlink,
  GitCommit,
  Activity,
  GitPullRequest,
  Play,
  FileCode,
  Sparkles,
} from 'lucide-react';
import { StatusBadge } from '@/components/admin/StatusBadge';
import { api, ApiClientError } from '@/lib/api-client';
import {
  HackathonDetailResponse,
  HackathonStatus,
  HackathonOverviewResponse,
  TeamListItem,
  SubmissionListItem,
  JudgeListItem,
  RubricDetailResponse,
  RepositoryValidationResult,
  RepositoryActivityItem,
  SubmissionEvaluationTransparencyResponse,
  HackathonEvaluationSummaryResponse,
  JudgeSubmissionReviewResponse,
  OrganizerReviewProgressResponse,
  JudgeReviewDetail,
} from '@/types/api';

type TabKey = 'overview' | 'teams' | 'submissions' | 'judges' | 'rubric' | 'reviews';

export default function TenantHackathonDetailPage({
  params,
}: {
  params: Promise<{ organizationId: string; hackathonId: string }>;
}) {
  const unwrappedParams = use(params);
  const { organizationId: orgId, hackathonId } = unwrappedParams;

  const [prevIds, setPrevIds] = useState<{ orgId: string; hackathonId: string }>({ orgId, hackathonId });
  const [hackathon, setHackathon] = useState<HackathonDetailResponse | null>(null);
  const [overview, setOverview] = useState<HackathonOverviewResponse | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>('overview');

  const [teams, setTeams] = useState<TeamListItem[]>([]);
  const [submissions, setSubmissions] = useState<SubmissionListItem[]>([]);
  const [judges, setJudges] = useState<JudgeListItem[]>([]);
  const [rubric, setRubric] = useState<RubricDetailResponse | null>(null);

  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isTabLoading, setIsTabLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<boolean>(false);

  // Lifecycle Action In Progress
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);
  const [isPublishingResults, setIsPublishingResults] = useState<boolean>(false);

  // Edit Modal State
  const [isEditModalOpen, setIsEditModalOpen] = useState<boolean>(false);
  const [editTitle, setEditTitle] = useState<string>('');
  const [editDescription, setEditDescription] = useState<string>('');
  const [isSavingEdit, setIsSavingEdit] = useState<boolean>(false);

  // Team Modals
  const [isCreateTeamOpen, setIsCreateTeamOpen] = useState<boolean>(false);
  const [teamName, setTeamName] = useState<string>('');
  const [isJoinTeamOpen, setIsJoinTeamOpen] = useState<boolean>(false);
  const [joinCode, setJoinCode] = useState<string>('');

  // Submission Modal
  const [isSubmitModalOpen, setIsSubmitModalOpen] = useState<boolean>(false);
  const [subTeamId, setSubTeamId] = useState<string>('');
  const [subRepoUrl, setSubRepoUrl] = useState<string>('');
  const [subBranch, setSubBranch] = useState<string>('main');
  const [subTitle, setSubTitle] = useState<string>('');
  const [subDesc, setSubDesc] = useState<string>('');
  const [isValidatingRepo, setIsValidatingRepo] = useState<boolean>(false);
  const [repoValidation, setRepoValidation] = useState<RepositoryValidationResult | null>(null);

  // Submission Operations (M6.2)
  const [refreshingSubId, setRefreshingSubId] = useState<string | null>(null);
  const [isBranchModalOpen, setIsBranchModalOpen] = useState<boolean>(false);
  const [branchSub, setBranchSub] = useState<SubmissionListItem | null>(null);
  const [editBranch, setEditBranch] = useState<string>('main');
  const [isUpdatingBranch, setIsUpdatingBranch] = useState<boolean>(false);

  const [isRelinkModalOpen, setIsRelinkModalOpen] = useState<boolean>(false);
  const [relinkSub, setRelinkSub] = useState<SubmissionListItem | null>(null);
  const [relinkUrl, setRelinkUrl] = useState<string>('');
  const [relinkBranch, setRelinkBranch] = useState<string>('main');
  const [isRelinking, setIsRelinking] = useState<boolean>(false);
  const [relinkValidation, setRelinkValidation] = useState<RepositoryValidationResult | null>(null);
  const [isValidatingRelink, setIsValidatingRelink] = useState<boolean>(false);

  // Activity Modal (M6.3)
  const [isActivityModalOpen, setIsActivityModalOpen] = useState<boolean>(false);
  const [activitySub, setActivitySub] = useState<SubmissionListItem | null>(null);
  const [activities, setActivities] = useState<RepositoryActivityItem[]>([]);
  const [isLoadingActivity, setIsLoadingActivity] = useState<boolean>(false);

  // Judge Modal
  const [isAssignJudgeOpen, setIsAssignJudgeOpen] = useState<boolean>(false);
  const [judgeEmail, setJudgeEmail] = useState<string>('');

  // Rubric Modals
  const [isCreateRubricOpen, setIsCreateRubricOpen] = useState<boolean>(false);
  const [rubricName, setRubricName] = useState<string>('Default Evaluation Rubric');
  const [rubricDesc, setRubricDesc] = useState<string>('Standard code quality, architecture, and innovation assessment');
  const [isAddCriterionOpen, setIsAddCriterionOpen] = useState<boolean>(false);
  const [critTitle, setCritTitle] = useState<string>('');
  const [critDesc, setCritDesc] = useState<string>('');
  const [critWeight, setCritWeight] = useState<string>('0.5000');
  const [critEvidence, setCritEvidence] = useState<string>('');

  // AI Evaluation Transparency (M6.4)
  const [evalSummary, setEvalSummary] = useState<HackathonEvaluationSummaryResponse | null>(null);
  const [isEvalModalOpen, setIsEvalModalOpen] = useState<boolean>(false);
  const [evalSub, setEvalSub] = useState<SubmissionListItem | null>(null);
  const [evalTransparency, setEvalTransparency] = useState<SubmissionEvaluationTransparencyResponse | null>(null);
  const [isLoadingEvalTransparency, setIsLoadingEvalTransparency] = useState<boolean>(false);
  const [evalError, setEvalError] = useState<string | null>(null);
  const [isTriggeringEval, setIsTriggeringEval] = useState<boolean>(false);
  const [triggeringSubId, setTriggeringSubId] = useState<string | null>(null);
  const [isCancellingEval, setIsCancellingEval] = useState<boolean>(false);

  // Judge Review & Human Decisions (M6.5)
  const [reviewProgress, setReviewProgress] = useState<OrganizerReviewProgressResponse | null>(null);
  const [isReviewModalOpen, setIsReviewModalOpen] = useState<boolean>(false);
  const [reviewSub, setReviewSub] = useState<SubmissionListItem | null>(null);
  const [reviewData, setReviewData] = useState<JudgeSubmissionReviewResponse | null>(null);
  const [isLoadingReview, setIsLoadingReview] = useState<boolean>(false);
  const [isSavingReview, setIsSavingReview] = useState<boolean>(false);
  const [isSubmittingReview, setIsSubmittingReview] = useState<boolean>(false);
  const [reviewOverallFeedback, setReviewOverallFeedback] = useState<string>('');
  const [reviewDecision, setReviewDecision] = useState<string>('accepted');
  const [reviewCriterionScores, setReviewCriterionScores] = useState<Record<string, { score: string; notes: string }>>({});
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [reviewSuccessMsg, setReviewSuccessMsg] = useState<string | null>(null);

  // Synchronous render-phase state adjustment
  if (orgId !== prevIds.orgId || hackathonId !== prevIds.hackathonId) {
    setPrevIds({ orgId, hackathonId });
    setHackathon(null);
    setOverview(null);
    setEvalSummary(null);
    setIsEvalModalOpen(false);
    setEvalSub(null);
    setEvalTransparency(null);
    setTeams([]);
    setSubmissions([]);
    setJudges([]);
    setRubric(null);
    setEditTitle('');
    setEditDescription('');
    setIsLoading(true);
    setError(null);
  }

  const abortControllerRef = useRef<AbortController | null>(null);

  const loadData = useCallback(async (isRefresh: boolean = false) => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const signal = controller.signal;

    if (!isRefresh) {
      setHackathon(null);
      setIsLoading(true);
      setError(null);
    }

    try {
      const [hackData, overData, evalSum] = await Promise.all([
        api.getTenantHackathon(orgId, hackathonId, { signal }),
        api.getHackathonOverview(orgId, hackathonId, { signal }).catch(() => null),
        api.getHackathonEvaluationSummary(orgId, hackathonId, { signal }).catch(() => null),
      ]);
      if (!signal.aborted) {
        setHackathon(hackData);
        setOverview(overData);
        if (evalSum) setEvalSummary(evalSum);
        setEditTitle(hackData.title);
        setEditDescription(hackData.description || '');
      }
    } catch (err: unknown) {
      if (signal.aborted) return;
      if (err instanceof ApiClientError && err.code === 'REQUEST_ABORTED') return;
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to load hackathon details.');
      }
    } finally {
      if (!signal.aborted) {
        setIsLoading(false);
      }
    }
  }, [orgId, hackathonId]);

  const loadTabData = useCallback(async (tab: TabKey) => {
    setIsTabLoading(true);
    try {
      if (tab === 'teams') {
        const data = await api.getHackathonTeams(orgId, hackathonId);
        setTeams(data);
      } else if (tab === 'submissions') {
        const [subs, evalSum] = await Promise.all([
          api.getHackathonSubmissions(orgId, hackathonId),
          api.getHackathonEvaluationSummary(orgId, hackathonId).catch(() => null),
        ]);
        setSubmissions(subs);
        if (evalSum) setEvalSummary(evalSum);
      } else if (tab === 'judges') {
        const data = await api.getHackathonJudges(orgId, hackathonId);
        setJudges(data);
      } else if (tab === 'rubric') {
        try {
          const data = await api.getHackathonRubric(orgId, hackathonId);
          setRubric(data);
        } catch (err: unknown) {
          if (err instanceof ApiClientError && err.code === 'RUBRIC_NOT_FOUND') {
            setRubric(null);
          } else {
            throw err;
          }
        }
      } else if (tab === 'reviews') {
        const data = await api.getHackathonReviewProgress(orgId, hackathonId).catch(() => null);
        if (data) setReviewProgress(data);
      }
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      }
    } finally {
      setIsTabLoading(false);
    }
  }, [orgId, hackathonId]);

  useEffect(() => {
    loadData(false);
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [loadData]);

  useEffect(() => {
    if (activeTab !== 'overview') {
      loadTabData(activeTab);
    }
  }, [activeTab, loadTabData]);

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(true);
    setTimeout(() => setCopiedId(false), 2000);
  };

  // State Machine Transitions
  const handlePublish = async () => {
    if (!confirm('Are you sure you want to publish this hackathon?')) return;
    setActionInProgress('publish');
    setError(null);
    try {
      const updated = await api.publishTenantHackathon(orgId, hackathonId);
      setHackathon(updated);
      setSuccessMessage('Hackathon published successfully! It is now live.');
      setTimeout(() => setSuccessMessage(null), 4000);
      loadData(true);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setError(err.message);
      else setError('Failed to publish hackathon.');
    } finally {
      setActionInProgress(null);
    }
  };

  const handleComplete = async () => {
    if (!confirm('Complete this hackathon? Submissions will close and the event will be concluded.')) return;
    setActionInProgress('complete');
    setError(null);
    try {
      const updated = await api.completeTenantHackathon(orgId, hackathonId);
      setHackathon(updated);
      setSuccessMessage('Hackathon marked as completed.');
      setTimeout(() => setSuccessMessage(null), 4000);
      loadData(true);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setError(err.message);
      else setError('Failed to complete hackathon.');
    } finally {
      setActionInProgress(null);
    }
  };

  const handleArchive = async () => {
    if (!confirm('Archive this completed hackathon?')) return;
    setActionInProgress('archive');
    setError(null);
    try {
      const updated = await api.archiveTenantHackathon(orgId, hackathonId);
      setHackathon(updated);
      setSuccessMessage('Hackathon successfully archived.');
      setTimeout(() => setSuccessMessage(null), 4000);
      loadData(true);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setError(err.message);
      else setError('Failed to archive hackathon.');
    } finally {
      setActionInProgress(null);
    }
  };

  const handleSuspendResume = async (targetStatus: HackathonStatus) => {
    const actionName = targetStatus === 'suspended' ? 'suspend' : 'resume';
    if (!confirm(`Are you sure you want to ${actionName} this hackathon?`)) return;
    setActionInProgress(actionName);
    setError(null);
    try {
      const updated = await api.updateTenantHackathonStatus(orgId, hackathonId, {
        status: targetStatus,
        reason: `Tenant organizer ${actionName}`,
      });
      setHackathon(updated);
      setSuccessMessage(`Hackathon successfully ${actionName}ed.`);
      setTimeout(() => setSuccessMessage(null), 4000);
      loadData(true);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setError(err.message);
      else setError(`Failed to ${actionName} hackathon.`);
    } finally {
      setActionInProgress(null);
    }
  };

  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSavingEdit(true);
    setError(null);
    try {
      const updated = await api.updateTenantHackathon(orgId, hackathonId, {
        title: editTitle.trim(),
        description: editDescription.trim() || undefined,
      });
      setHackathon(updated);
      setIsEditModalOpen(false);
      setSuccessMessage('Hackathon details saved.');
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setError(err.message);
      else setError('Failed to update hackathon.');
    } finally {
      setIsSavingEdit(false);
    }
  };

  // Team Handlers
  const handleCreateTeam = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const newTeam = await api.createHackathonTeam(orgId, hackathonId, { name: teamName.trim() });
      setIsCreateTeamOpen(false);
      setTeamName('');
      setSuccessMessage(`Team "${newTeam.name}" registered! Join Code: ${newTeam.join_code}`);
      setTimeout(() => setSuccessMessage(null), 5000);
      loadTabData('teams');
      loadData(true);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setError(err.message);
      else setError('Failed to create team.');
    }
  };

  const handleJoinTeam = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const joinedTeam = await api.joinHackathonTeam(orgId, hackathonId, { join_code: joinCode.trim() });
      setIsJoinTeamOpen(false);
      setJoinCode('');
      setSuccessMessage(`Successfully joined team "${joinedTeam.name}"!`);
      setTimeout(() => setSuccessMessage(null), 4000);
      loadTabData('teams');
      loadData(true);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setError(err.message);
      else setError('Failed to join team.');
    }
  };

  // Submission Handler
  const handleCreateSubmission = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await api.createHackathonSubmission(orgId, hackathonId, {
        team_id: subTeamId,
        repository_url: subRepoUrl.trim(),
        target_branch: subBranch.trim() || 'main',
        title: subTitle.trim(),
        description: subDesc.trim() || undefined,
      });
      setIsSubmitModalOpen(false);
      setSubRepoUrl('');
      setSubTitle('');
      setSubDesc('');
      setRepoValidation(null);
      setSuccessMessage('Repository project submission registered successfully!');
      setTimeout(() => setSuccessMessage(null), 4000);
      loadTabData('submissions');
      loadData(true);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setError(err.message);
      else setError('Failed to register submission.');
    }
  };

  const handleValidateRepo = async () => {
    if (!subRepoUrl.trim()) return;
    setIsValidatingRepo(true);
    setRepoValidation(null);
    try {
      const res = await api.validateRepository(orgId, hackathonId, {
        repository_url: subRepoUrl.trim(),
        target_branch: subBranch.trim() || undefined,
      });
      setRepoValidation(res);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setError(err.message);
      else setError('Failed to validate repository connection.');
    } finally {
      setIsValidatingRepo(false);
    }
  };

  const handleRefreshVerification = async (subId: string) => {
    setRefreshingSubId(subId);
    setError(null);
    try {
      await api.refreshSubmissionVerification(orgId, hackathonId, subId);
      setSuccessMessage('Repository connection status refreshed.');
      setTimeout(() => setSuccessMessage(null), 3000);
      loadTabData('submissions');
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setError(err.message);
      else setError('Failed to refresh repository verification.');
    } finally {
      setRefreshingSubId(null);
    }
  };

  const handleOpenBranchModal = (sub: SubmissionListItem) => {
    setBranchSub(sub);
    setEditBranch(sub.target_branch || 'main');
    setIsBranchModalOpen(true);
  };

  const handleUpdateBranch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!branchSub) return;
    setIsUpdatingBranch(true);
    setError(null);
    try {
      await api.updateSubmissionBranch(orgId, hackathonId, branchSub.id, {
        target_branch: editBranch.trim(),
      });
      setIsBranchModalOpen(false);
      setBranchSub(null);
      setSuccessMessage(`Target branch updated to "${editBranch.trim()}".`);
      setTimeout(() => setSuccessMessage(null), 3000);
      loadTabData('submissions');
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setError(err.message);
      else setError('Failed to update branch.');
    } finally {
      setIsUpdatingBranch(false);
    }
  };

  const handleOpenRelinkModal = (sub: SubmissionListItem) => {
    setRelinkSub(sub);
    setRelinkUrl(sub.repository_url || '');
    setRelinkBranch(sub.target_branch || 'main');
    setRelinkValidation(null);
    setIsRelinkModalOpen(true);
  };

  const handleValidateRelink = async () => {
    if (!relinkUrl.trim()) return;
    setIsValidatingRelink(true);
    setRelinkValidation(null);
    try {
      const res = await api.validateRepository(orgId, hackathonId, {
        repository_url: relinkUrl.trim(),
        target_branch: relinkBranch.trim() || undefined,
      });
      setRelinkValidation(res);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setError(err.message);
      else setError('Failed to validate repository.');
    } finally {
      setIsValidatingRelink(false);
    }
  };

  const handleRelinkRepository = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!relinkSub) return;
    setIsRelinking(true);
    setError(null);
    try {
      await api.linkSubmissionRepository(orgId, hackathonId, relinkSub.id, {
        repository_url: relinkUrl.trim(),
        target_branch: relinkBranch.trim() || undefined,
      });
      setIsRelinkModalOpen(false);
      setRelinkSub(null);
      setSuccessMessage('Repository linked and verified successfully.');
      setTimeout(() => setSuccessMessage(null), 4000);
      loadTabData('submissions');
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setError(err.message);
      else setError('Failed to link repository.');
    } finally {
      setIsRelinking(false);
    }
  };

  const handleUnlinkRepository = async (sub: SubmissionListItem) => {
    if (!confirm(`Unlink repository from "${sub.title}"? This is only allowed if no evaluation runs exist.`)) return;
    setError(null);
    try {
      await api.unlinkSubmissionRepository(orgId, hackathonId, sub.id);
      setSuccessMessage('Repository unlinked from submission.');
      setTimeout(() => setSuccessMessage(null), 3000);
      loadTabData('submissions');
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setError(err.message);
      else setError('Failed to unlink repository.');
    }
  };

  const handleOpenActivityModal = async (sub: SubmissionListItem) => {
    setActivitySub(sub);
    setIsActivityModalOpen(true);
    setIsLoadingActivity(true);
    setActivities([]);
    try {
      const res = await api.getSubmissionActivity(orgId, hackathonId, sub.id);
      setActivities(res);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setError(err.message);
      else setError('Failed to load repository activity.');
    } finally {
      setIsLoadingActivity(false);
    }
  };

  // AI Evaluation Transparency Handlers (M6.4)
  const handleOpenEvaluationModal = async (sub: SubmissionListItem, jobId?: string) => {
    setEvalSub(sub);
    setIsEvalModalOpen(true);
    setIsLoadingEvalTransparency(true);
    setEvalTransparency(null);
    setEvalError(null);
    try {
      const data = await api.getSubmissionEvaluation(orgId, hackathonId, sub.id, jobId);
      setEvalTransparency(data);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setEvalError(err.message);
      else setEvalError('Failed to load evaluation details.');
    } finally {
      setIsLoadingEvalTransparency(false);
    }
  };

  const handleTriggerEvaluation = async (submissionId: string) => {
    setIsTriggeringEval(true);
    setTriggeringSubId(submissionId);
    setError(null);
    setSuccessMessage(null);
    try {
      await api.triggerSubmissionEvaluation(orgId, hackathonId, submissionId);
      setSuccessMessage('AI evaluation job dispatched successfully.');
      setTimeout(() => setSuccessMessage(null), 4000);
      const [newSubs, newSum] = await Promise.all([
        api.getHackathonSubmissions(orgId, hackathonId),
        api.getHackathonEvaluationSummary(orgId, hackathonId).catch(() => null),
      ]);
      setSubmissions(newSubs);
      if (newSum) setEvalSummary(newSum);

      if (isEvalModalOpen && evalSub && evalSub.id === submissionId) {
        const data = await api.getSubmissionEvaluation(orgId, hackathonId, submissionId);
        setEvalTransparency(data);
      }
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
        if (isEvalModalOpen) setEvalError(err.message);
      } else {
        setError('Failed to dispatch evaluation.');
        if (isEvalModalOpen) setEvalError('Failed to dispatch evaluation.');
      }
    } finally {
      setIsTriggeringEval(false);
      setTriggeringSubId(null);
    }
  };

  // Judge Review Handlers (M6.5)
  const handleOpenReviewModal = async (sub: SubmissionListItem, judgeId?: string) => {
    setReviewSub(sub);
    setIsReviewModalOpen(true);
    setIsLoadingReview(true);
    setReviewData(null);
    setReviewError(null);
    setReviewSuccessMsg(null);
    try {
      const data = await api.getSubmissionReview(orgId, hackathonId, sub.id, judgeId);
      setReviewData(data);
      setReviewOverallFeedback(data.review?.overall_feedback || '');
      setReviewDecision(data.review?.decision || 'accepted');

      const scoresMap: Record<string, { score: string; notes: string }> = {};
      if (data.review && data.review.criterion_scores) {
        data.review.criterion_scores.forEach((cs) => {
          scoresMap[cs.criterion_id] = {
            score: cs.score !== null && cs.score !== undefined ? String(cs.score) : '',
            notes: cs.judge_notes || '',
          };
        });
      }
      setReviewCriterionScores(scoresMap);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setReviewError(err.message);
      else setReviewError('Failed to load review form.');
    } finally {
      setIsLoadingReview(false);
    }
  };

  const handleSaveReviewDraft = async () => {
    if (!reviewSub || !reviewData) return;
    setIsSavingReview(true);
    setReviewError(null);
    setReviewSuccessMsg(null);
    try {
      const criterion_scores = Object.entries(reviewCriterionScores)
        .filter(([_, val]) => val.score.trim() !== '')
        .map(([criterion_id, val]) => ({
          criterion_id,
          score: val.score.trim(),
          judge_notes: val.notes.trim() || null,
        }));

      const updated = await api.saveSubmissionReviewDraft(orgId, hackathonId, reviewSub.id, {
        overall_feedback: reviewOverallFeedback.trim() || null,
        decision: reviewDecision || 'accepted',
        criterion_scores,
        version: reviewData.review?.version,
      });

      setReviewSuccessMsg('Review draft saved successfully.');
      setTimeout(() => setReviewSuccessMsg(null), 3500);

      const refreshed = await api.getSubmissionReview(orgId, hackathonId, reviewSub.id);
      setReviewData(refreshed);
      if (activeTab === 'reviews') {
        api.getHackathonReviewProgress(orgId, hackathonId).then(setReviewProgress).catch(() => null);
      }
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setReviewError(err.message);
      else setReviewError('Failed to save review draft.');
    } finally {
      setIsSavingReview(false);
    }
  };

  const handleSubmitReview = async () => {
    if (!reviewSub || !reviewData) return;
    if (!reviewOverallFeedback.trim()) {
      setReviewError('Overall feedback is required for final submission.');
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

      await api.submitSubmissionReview(orgId, hackathonId, reviewSub.id, {
        overall_feedback: reviewOverallFeedback.trim(),
        decision: reviewDecision || 'accepted',
        criterion_scores,
        version: reviewData.review?.version,
      });

      setReviewSuccessMsg('Final review submitted successfully.');
      setTimeout(() => setReviewSuccessMsg(null), 3500);

      const refreshed = await api.getSubmissionReview(orgId, hackathonId, reviewSub.id);
      setReviewData(refreshed);
      if (activeTab === 'reviews') {
        api.getHackathonReviewProgress(orgId, hackathonId).then(setReviewProgress).catch(() => null);
      }
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setReviewError(err.message);
      else setReviewError('Failed to submit final review.');
    } finally {
      setIsSubmittingReview(false);
    }
  };

  const handlePublishResults = async () => {
    if (!confirm('Publish official evaluation results and release the leaderboard to all participants?')) return;
    setIsPublishingResults(true);
    setError(null);
    try {
      await api.publishHackathonResults(orgId, hackathonId);
      setSuccessMessage('Official evaluation results and leaderboard released to participants!');
      setTimeout(() => setSuccessMessage(null), 4000);
      loadData(true);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setError(err.message);
      else setError('Failed to publish results.');
    } finally {
      setIsPublishingResults(false);
    }
  };

  const handleUnpublishResults = async () => {
    if (!confirm('Conceal results from participants? The leaderboard will return to pending publication.')) return;
    setIsPublishingResults(true);
    setError(null);
    try {
      await api.unpublishHackathonResults(orgId, hackathonId);
      setSuccessMessage('Official results unpublished. Leaderboard is now concealed from participants.');
      setTimeout(() => setSuccessMessage(null), 4000);
      loadData(true);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setError(err.message);
      else setError('Failed to unpublish results.');
    } finally {
      setIsPublishingResults(false);
    }
  };

  const handleCancelEvaluation = async (jobId: string) => {
    if (!confirm('Cancel this evaluation job? Active worker processes will abort cooperatively.')) return;
    setIsCancellingEval(true);
    setError(null);
    try {
      await api.cancelEvaluationJob(orgId, jobId);
      setSuccessMessage('Evaluation job cancellation requested.');
      setTimeout(() => setSuccessMessage(null), 4000);
      if (evalSub) {
        const data = await api.getSubmissionEvaluation(orgId, hackathonId, evalSub.id);
        setEvalTransparency(data);
      }
      const [newSubs, newSum] = await Promise.all([
        api.getHackathonSubmissions(orgId, hackathonId),
        api.getHackathonEvaluationSummary(orgId, hackathonId).catch(() => null),
      ]);
      setSubmissions(newSubs);
      if (newSum) setEvalSummary(newSum);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to cancel evaluation.');
      }
    } finally {
      setIsCancellingEval(false);
    }
  };

  // Judge Handlers
  const handleAssignJudge = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const judge = await api.assignHackathonJudge(orgId, hackathonId, { email: judgeEmail.trim() });
      setIsAssignJudgeOpen(false);
      setJudgeEmail('');
      setSuccessMessage(`Judge ${judge.user_email} assigned successfully!`);
      setTimeout(() => setSuccessMessage(null), 4000);
      loadTabData('judges');
      loadData(true);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setError(err.message);
      else setError('Failed to assign judge.');
    }
  };

  const handleRemoveJudge = async (judgeUserId: string, email: string) => {
    if (!confirm(`Remove judge ${email} from this hackathon?`)) return;
    setError(null);
    try {
      await api.removeHackathonJudge(orgId, hackathonId, judgeUserId);
      setSuccessMessage(`Judge ${email} removed.`);
      setTimeout(() => setSuccessMessage(null), 3000);
      loadTabData('judges');
      loadData(true);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setError(err.message);
      else setError('Failed to remove judge.');
    }
  };

  // Rubric Handlers
  const handleCreateRubric = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const res = await api.createHackathonRubric(orgId, hackathonId, {
        name: rubricName.trim(),
        description: rubricDesc.trim() || undefined,
        scoring_mode: 'offset_normalized',
      });
      setRubric(res);
      setIsCreateRubricOpen(false);
      setSuccessMessage('Rubric initialized in draft state.');
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setError(err.message);
      else setError('Failed to create rubric.');
    }
  };

  const handleAddCriterion = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!rubric) return;
    setError(null);
    try {
      const res = await api.addRubricCriterion(orgId, hackathonId, rubric.id, {
        title: critTitle.trim(),
        description: critDesc.trim(),
        weight: critWeight.trim(),
        min_score: '0.00',
        max_score: '10.00',
        evidence_requirements: critEvidence.trim(),
        order_index: (rubric.active_version?.criteria.length || 0) + 1,
      });
      setRubric(res);
      setIsAddCriterionOpen(false);
      setCritTitle('');
      setCritDesc('');
      setCritWeight('0.5000');
      setCritEvidence('');
      setSuccessMessage('Criterion added to draft rubric.');
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setError(err.message);
      else setError('Failed to add criterion.');
    }
  };

  const handlePublishRubric = async () => {
    if (!rubric) return;
    if (!confirm('Publish and freeze this rubric? Once published, criteria weights become immutable.')) return;
    setError(null);
    try {
      const res = await api.publishRubric(orgId, hackathonId, rubric.id);
      setRubric(res);
      setSuccessMessage('Rubric published and frozen successfully!');
      setTimeout(() => setSuccessMessage(null), 4000);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) setError(err.message);
      else setError('Failed to publish rubric.');
    }
  };

  // Timeline Progress Calculator
  const getTimelineStatus = () => {
    if (!hackathon) return null;
    const now = new Date();
    const start = new Date(hackathon.start_date);
    const deadline = new Date(hackathon.submission_deadline);
    const end = new Date(hackathon.end_date);

    if (now < start) {
      return {
        label: 'Upcoming / Scheduled',
        badge: 'bg-status-info/10 text-status-info border-status-info/30',
      };
    }
    if (now >= start && now <= deadline) {
      return {
        label: 'Submissions Open (Active)',
        badge: 'bg-status-success/10 text-status-success border-status-success/30',
      };
    }
    if (now > deadline && now <= end) {
      return {
        label: 'Judging / Evaluation Period',
        badge: 'bg-status-warning/10 text-status-warning border-status-warning/30',
      };
    }
    return {
      label: 'Concluded / Closed',
      badge: 'bg-slate-800 text-slate-400 border-slate-700',
    };
  };

  const isStale = Boolean(hackathon && (hackathon.id !== hackathonId || hackathon.organization_id !== orgId));

  if (error && !hackathon) {
    return (
      <div className="p-8 bg-surface rounded-2xl border border-surface-border text-center">
        <AlertCircle className="w-10 h-10 text-status-error mx-auto mb-3" />
        <h2 className="text-base font-semibold text-text-primary">Failed to load hackathon</h2>
        <p className="text-xs text-text-muted mt-1 mb-4">{error}</p>
        <Link
          href={`/organizations/${orgId}/hackathons`}
          className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-text-primary bg-surface-elevated hover:bg-surface-hover rounded-lg transition-colors border border-surface-border"
        >
          <ChevronLeft className="w-4 h-4" />
          <span>Back to Hackathons</span>
        </Link>
      </div>
    );
  }

  if (isLoading || !hackathon || isStale) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-4 bg-surface-elevated rounded w-48" />
        <div className="h-24 bg-surface rounded-2xl border border-surface-border p-6" />
        <div className="h-64 bg-surface rounded-2xl border border-surface-border p-6" />
      </div>
    );
  }

  const timeline = getTimelineStatus();

  return (
    <div className="space-y-6">
      {/* Top Breadcrumb & Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <Link
          href={`/organizations/${orgId}/hackathons`}
          className="inline-flex items-center gap-2 text-xs text-text-muted hover:text-text-primary transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
          <span>Back to Organization Hackathons</span>
        </Link>

        <div className="flex items-center gap-2 flex-wrap">
          <button
            type="button"
            onClick={() => loadData(true)}
            disabled={isLoading}
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>

          {/* State Machine Transition Buttons */}
          {hackathon.status === 'draft' && (
            <>
              <button
                type="button"
                onClick={() => setIsEditModalOpen(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors"
              >
                <Edit className="w-3.5 h-3.5" />
                <span>Edit Draft</span>
              </button>
              <button
                type="button"
                onClick={handlePublish}
                disabled={actionInProgress !== null}
                className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg transition-colors shadow-sm"
              >
                <Globe className="w-3.5 h-3.5" />
                <span>Publish Event</span>
              </button>
            </>
          )}

          {hackathon.status === 'published' && (
            <>
              <button
                type="button"
                onClick={handleComplete}
                disabled={actionInProgress !== null}
                className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold text-white bg-status-success hover:bg-status-success/90 disabled:opacity-50 rounded-lg transition-colors shadow-sm"
              >
                <CheckCheck className="w-3.5 h-3.5" />
                <span>Complete Event</span>
              </button>
              <button
                type="button"
                onClick={() => handleSuspendResume('suspended')}
                disabled={actionInProgress !== null}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-status-error bg-status-error/10 hover:bg-status-error/20 border border-status-error/30 rounded-lg transition-colors"
              >
                <ShieldAlert className="w-3.5 h-3.5" />
                <span>Suspend</span>
              </button>
            </>
          )}

          {hackathon.status === 'completed' && (
            <button
              type="button"
              onClick={handleArchive}
              disabled={actionInProgress !== null}
              className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors"
            >
              <Archive className="w-3.5 h-3.5 text-text-muted" />
              <span>Archive</span>
            </button>
          )}

          {hackathon.status === 'suspended' && (
            <button
              type="button"
              onClick={() => handleSuspendResume('published')}
              disabled={actionInProgress !== null}
              className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg transition-colors"
            >
              <span>Reactivate</span>
            </button>
          )}
        </div>
      </div>

      {/* Notifications */}
      {successMessage && (
        <div className="flex items-center gap-3 p-4 bg-status-success/10 border border-status-success/30 rounded-xl text-status-success text-sm animate-in fade-in">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{successMessage}</span>
        </div>
      )}

      {error && (
        <div className="flex items-center justify-between p-4 bg-status-error/10 border border-status-error/30 rounded-xl text-status-error text-sm">
          <div className="flex items-center gap-3">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)} className="text-xs font-bold">
            Dismiss
          </button>
        </div>
      )}

      {/* Header Banner */}
      <div className="bg-surface rounded-2xl border border-surface-border p-6 shadow-sm">
        <div className="flex items-start gap-4">
          <div className="w-14 h-14 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary shrink-0 shadow-inner">
            <Trophy className="w-7 h-7" />
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-xl font-bold text-text-primary tracking-tight">
                {hackathon.title}
              </h1>
              <StatusBadge status={hackathon.status} size="sm" />
              {timeline && (
                <span
                  className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[10px] font-semibold ${timeline.badge}`}
                >
                  {timeline.label}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 text-xs text-text-muted mt-1 flex-wrap">
              <span className="font-mono bg-surface-elevated px-2 py-0.5 rounded border border-surface-border text-text-secondary">
                /{hackathon.slug}
              </span>
              <span className="flex items-center gap-1 font-mono">
                ID: {hackathon.id.slice(0, 8)}...
                <button
                  onClick={() => copyToClipboard(hackathon.id)}
                  className="p-1 hover:text-text-primary transition-colors"
                  title="Copy UUID"
                >
                  {copiedId ? <Check className="w-3 h-3 text-status-success" /> : <Copy className="w-3 h-3" />}
                </button>
              </span>
              <span className="flex items-center gap-1">
                <Calendar className="w-3 h-3" />
                Created: {new Date(hackathon.created_at).toLocaleDateString()}
              </span>
            </div>
          </div>
        </div>

        {/* Operational Overview Metric Counters */}
        {overview && (
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mt-6 pt-5 border-t border-surface-border">
            <div className="p-3 bg-surface-elevated/60 rounded-xl border border-surface-border/60">
              <span className="text-[11px] text-text-muted block">Teams</span>
              <span className="text-lg font-bold text-text-primary mt-0.5 block">
                {overview.total_teams}
              </span>
            </div>
            <div className="p-3 bg-surface-elevated/60 rounded-xl border border-surface-border/60">
              <span className="text-[11px] text-text-muted block">Submissions</span>
              <span className="text-lg font-bold text-text-primary mt-0.5 block">
                {overview.total_submissions}
              </span>
            </div>
            <div className="p-3 bg-surface-elevated/60 rounded-xl border border-surface-border/60">
              <span className="text-[11px] text-text-muted block">Evaluations</span>
              <span className="text-lg font-bold text-text-primary mt-0.5 block">
                {overview.completed_evaluations} / {overview.total_evaluations}
              </span>
            </div>
            <div className="p-3 bg-surface-elevated/60 rounded-xl border border-surface-border/60">
              <span className="text-[11px] text-text-muted block">Judges</span>
              <span className="text-lg font-bold text-text-primary mt-0.5 block">
                {overview.total_judges}
              </span>
            </div>
            <div className="p-3 bg-surface-elevated/60 rounded-xl border border-surface-border/60">
              <span className="text-[11px] text-text-muted block">Avg Score</span>
              <span className="text-lg font-bold text-primary mt-0.5 block">
                {overview.average_score !== null && overview.average_score !== undefined
                  ? `${overview.average_score} / 100`
                  : '—'}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Navigation Tabs */}
      <div className="flex items-center gap-1 border-b border-surface-border">
        <button
          type="button"
          onClick={() => setActiveTab('overview')}
          className={`px-4 py-2 text-xs font-semibold border-b-2 transition-colors flex items-center gap-2 ${
            activeTab === 'overview'
              ? 'border-primary text-primary'
              : 'border-transparent text-text-muted hover:text-text-primary'
          }`}
        >
          <Clock className="w-3.5 h-3.5" />
          <span>Timeline & Rules</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('teams')}
          className={`px-4 py-2 text-xs font-semibold border-b-2 transition-colors flex items-center gap-2 ${
            activeTab === 'teams'
              ? 'border-primary text-primary'
              : 'border-transparent text-text-muted hover:text-text-primary'
          }`}
        >
          <Users className="w-3.5 h-3.5" />
          <span>Teams ({overview ? overview.total_teams : teams.length})</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('submissions')}
          className={`px-4 py-2 text-xs font-semibold border-b-2 transition-colors flex items-center gap-2 ${
            activeTab === 'submissions'
              ? 'border-primary text-primary'
              : 'border-transparent text-text-muted hover:text-text-primary'
          }`}
        >
          <GitBranch className="w-3.5 h-3.5" />
          <span>Submissions ({overview ? overview.total_submissions : submissions.length})</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('judges')}
          className={`px-4 py-2 text-xs font-semibold border-b-2 transition-colors flex items-center gap-2 ${
            activeTab === 'judges'
              ? 'border-primary text-primary'
              : 'border-transparent text-text-muted hover:text-text-primary'
          }`}
        >
          <Award className="w-3.5 h-3.5" />
          <span>Judges ({overview ? overview.total_judges : judges.length})</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('rubric')}
          className={`px-4 py-2 text-xs font-semibold border-b-2 transition-colors flex items-center gap-2 ${
            activeTab === 'rubric'
              ? 'border-primary text-primary'
              : 'border-transparent text-text-muted hover:text-text-primary'
          }`}
        >
          <Scale className="w-3.5 h-3.5" />
          <span>Rubric Criteria</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('reviews')}
          className={`px-4 py-2 text-xs font-semibold border-b-2 transition-colors flex items-center gap-2 ${
            activeTab === 'reviews'
              ? 'border-primary text-primary'
              : 'border-transparent text-text-muted hover:text-text-primary'
          }`}
        >
          <Award className="w-3.5 h-3.5" />
          <span>Reviews & Scoring</span>
        </button>
      </div>

      {/* Tab 1: Overview & Timeline */}
      {activeTab === 'overview' && (
        <div className="space-y-6">
          <div className="bg-surface rounded-xl border border-surface-border p-5 space-y-4">
            <div className="flex items-center justify-between border-b border-surface-border pb-3">
              <div className="flex items-center gap-2">
                <Clock className="w-4 h-4 text-primary" />
                <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider">
                  Event Timeline (UTC)
                </h3>
              </div>
              <span className="text-[11px] text-text-muted font-mono">
                {hackathon.status === 'published' ? 'Immutable Timeline' : 'Draft Schedule'}
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="p-3 bg-surface-elevated rounded-lg border border-surface-border">
                <span className="text-[11px] text-text-muted block">Event Start Date</span>
                <span className="font-semibold text-text-primary text-xs mt-0.5 block">
                  {new Date(hackathon.start_date).toUTCString()}
                </span>
              </div>

              <div className="p-3 bg-surface-elevated rounded-lg border border-primary/30 bg-primary/5">
                <span className="text-[11px] text-primary font-semibold block">Submission Deadline (Cutoff)</span>
                <span className="font-semibold text-text-primary text-xs mt-0.5 block">
                  {new Date(hackathon.submission_deadline).toUTCString()}
                </span>
              </div>

              <div className="p-3 bg-surface-elevated rounded-lg border border-surface-border">
                <span className="text-[11px] text-text-muted block">Event Conclusion Date</span>
                <span className="font-semibold text-text-primary text-xs mt-0.5 block">
                  {new Date(hackathon.end_date).toUTCString()}
                </span>
              </div>
            </div>
          </div>

          <div className="bg-surface rounded-xl border border-surface-border p-5 space-y-4">
            <div className="flex items-center gap-2 border-b border-surface-border pb-3">
              <FileText className="w-4 h-4 text-primary" />
              <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider">
                Description & Participation Rules
              </h3>
            </div>

            {hackathon.description ? (
              <div className="text-xs text-text-secondary whitespace-pre-wrap leading-relaxed">
                {hackathon.description}
              </div>
            ) : (
              <p className="text-xs text-text-muted italic">No custom description or rules provided.</p>
            )}
          </div>
        </div>
      )}

      {/* Tab 2: Teams */}
      {activeTab === 'teams' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-text-primary">Participating Teams</h3>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setIsJoinTeamOpen(true)}
                className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors"
              >
                <span>Join with Code</span>
              </button>
              <button
                type="button"
                onClick={() => setIsCreateTeamOpen(true)}
                className="flex items-center gap-1 px-3 py-1.5 text-xs font-semibold text-white bg-primary hover:bg-primary-hover rounded-lg transition-colors shadow-sm"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>Register Team</span>
              </button>
            </div>
          </div>

          {isTabLoading ? (
            <div className="p-8 text-center text-xs text-text-muted">Loading teams...</div>
          ) : teams.length === 0 ? (
            <div className="p-8 bg-surface rounded-xl border border-surface-border text-center">
              <Users className="w-8 h-8 text-text-muted mx-auto mb-2 opacity-50" />
              <p className="text-xs text-text-muted">No teams registered yet. Be the first to register a team!</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {teams.map((t) => (
                <div key={t.id} className="p-4 bg-surface rounded-xl border border-surface-border space-y-3">
                  <div className="flex items-start justify-between">
                    <div>
                      <h4 className="text-sm font-bold text-text-primary">{t.name}</h4>
                      <span className="text-[11px] text-text-muted font-mono block mt-0.5">
                        Join Code: <span className="text-primary font-bold">{t.join_code}</span>
                      </span>
                    </div>
                    <span className="text-[11px] px-2 py-0.5 bg-surface-elevated border border-surface-border rounded text-text-secondary">
                      {t.member_count} {t.member_count === 1 ? 'member' : 'members'}
                    </span>
                  </div>

                  {t.submission ? (
                    <div className="p-2.5 bg-surface-elevated/80 rounded-lg border border-surface-border/60 text-xs flex items-center justify-between">
                      <div className="truncate pr-2">
                        <span className="font-semibold text-text-primary block truncate">{t.submission.title}</span>
                        <span className="text-[10px] text-text-muted truncate block">{t.submission.repository_url}</span>
                      </div>
                      <StatusBadge status={t.submission.status} size="sm" />
                    </div>
                  ) : (
                    <div className="p-2.5 bg-surface-elevated/40 rounded-lg border border-dashed border-surface-border text-[11px] text-text-muted italic">
                      No repository submitted yet
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Tab 3: Submissions */}
      {activeTab === 'submissions' && (
        <div className="space-y-4">
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-text-primary">Project Submissions</h3>
                <p className="text-[11px] text-text-muted mt-0.5">
                  Evidence-grounded AI assessments and repository tracking
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsSubmitModalOpen(true)}
                disabled={teams.length === 0}
                className="flex items-center gap-1 px-3 py-1.5 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg transition-colors shadow-sm"
              >
                <Send className="w-3.5 h-3.5" />
                <span>Submit Project</span>
              </button>
            </div>

            {/* Evaluation Status Banner */}
            {evalSummary && (
              <div className="p-3.5 bg-surface rounded-xl border border-surface-border space-y-2.5">
                <div className="flex items-center justify-between flex-wrap gap-2 text-xs">
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className="text-[11px] text-text-muted">
                      Evaluated: <strong className="text-text-primary">{evalSummary.evaluated_submissions} / {evalSummary.total_submissions}</strong>
                    </span>
                    {(evalSummary.queued_jobs > 0 || evalSummary.running_jobs > 0) && (
                      <span className="inline-flex items-center gap-1 text-[11px] text-primary font-medium">
                        <RefreshCw className="w-3 h-3 animate-spin" />
                        {evalSummary.running_jobs + evalSummary.queued_jobs} In Progress
                      </span>
                    )}
                    {evalSummary.failed_jobs > 0 && (
                      <span className="inline-flex items-center gap-1 text-[11px] text-status-error font-medium">
                        <AlertCircle className="w-3 h-3" />
                        {evalSummary.failed_jobs} Failed
                      </span>
                    )}
                    {evalSummary.average_score !== null && (
                      <span className="text-[11px] text-text-muted">
                        Avg Score: <strong className="text-primary font-bold">{evalSummary.average_score} / 100</strong>
                      </span>
                    )}
                  </div>

                  <div>
                    {evalSummary.has_published_rubric ? (
                      <span className="inline-flex items-center gap-1 text-[11px] text-status-success font-medium bg-status-success/10 px-2.5 py-0.5 rounded border border-status-success/30">
                        <CheckCircle2 className="w-3 h-3" />
                        Rubric Active ({evalSummary.published_rubric_name})
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setActiveTab('rubric')}
                        className="inline-flex items-center gap-1 text-[11px] text-status-warning font-medium bg-status-warning/10 hover:bg-status-warning/20 px-2.5 py-0.5 rounded border border-status-warning/30 transition-colors"
                      >
                        <AlertCircle className="w-3 h-3" />
                        No Published Rubric (Submissions Cannot Be Evaluated)
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>

          {isTabLoading ? (
            <div className="p-8 text-center text-xs text-text-muted">Loading submissions...</div>
          ) : submissions.length === 0 ? (
            <div className="p-8 bg-surface rounded-xl border border-surface-border text-center">
              <GitBranch className="w-8 h-8 text-text-muted mx-auto mb-2 opacity-50" />
              <p className="text-xs text-text-muted">No projects submitted yet.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {submissions.map((s) => (
                <div key={s.id} className="p-4 bg-surface rounded-xl border border-surface-border space-y-3">
                  <div className="flex items-start justify-between gap-4">
                    <div className="space-y-1.5 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h4 className="text-xs font-bold text-text-primary truncate">{s.title}</h4>
                        <StatusBadge status={s.status} size="sm" />
                        {s.connection_status === 'verified' && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-status-success/10 text-status-success border border-status-success/30">
                            <Check className="w-3 h-3" />
                            Verified
                          </span>
                        )}
                        {s.connection_status === 'failed' && (
                          <span
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-status-error/10 text-status-error border border-status-error/30"
                            title={s.verification_diagnostic || 'Verification failed'}
                          >
                            <AlertCircle className="w-3 h-3" />
                            Failed ({s.verification_diagnostic || 'ERROR'})
                          </span>
                        )}
                        {s.connection_status === 'unlinked' && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-surface-elevated text-text-muted border border-surface-border">
                            <Unlink className="w-3 h-3" />
                            Unlinked
                          </span>
                        )}
                        {(!s.connection_status || s.connection_status === 'unverified') && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-status-warning/10 text-status-warning border border-status-warning/30">
                            <Clock className="w-3 h-3" />
                            Unverified
                          </span>
                        )}
                      </div>

                      <p className="text-[11px] text-text-muted font-mono flex items-center gap-2 flex-wrap">
                        <span>Team: <strong className="text-text-secondary">{s.team_name}</strong></span>
                        <span>•</span>
                        <span>Branch: <strong className="text-text-secondary">{s.target_branch}</strong></span>
                        {s.verified_commit_sha && (
                          <>
                            <span>•</span>
                            <span className="inline-flex items-center gap-0.5 text-text-secondary">
                              <GitCommit className="w-3 h-3" />
                              <code>{s.verified_commit_sha.slice(0, 7)}</code>
                            </span>
                          </>
                        )}
                      </p>

                      <div className="flex items-center gap-2">
                        <a
                          href={s.repository_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[11px] text-primary hover:underline inline-flex items-center gap-1 font-mono truncate"
                        >
                          <Link2 className="w-3 h-3 shrink-0" />
                          <span>{s.repository_url}</span>
                          <ExternalLink className="w-2.5 h-2.5 shrink-0" />
                        </a>
                      </div>
                    </div>

                    <div className="text-right shrink-0">
                      <span className="text-[10px] text-text-muted block">AI Score</span>
                      <span className="text-sm font-bold text-primary">
                        {s.latest_score !== null && s.latest_score !== undefined
                          ? `${s.latest_score} / 100`
                          : s.latest_job_status
                          ? s.latest_job_status
                          : 'Pending'}
                      </span>
                    </div>
                  </div>

                  <div className="pt-2 border-t border-surface-border flex items-center justify-between gap-2 flex-wrap text-xs">
                    <div className="text-[10px] text-text-muted font-mono">
                      {s.verified_at ? (
                        <span>Last verified: {new Date(s.verified_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                      ) : (
                        <span>Not yet verified</span>
                      )}
                    </div>

                    <div className="flex items-center gap-1.5 flex-wrap">
                      {/* Judge Review Modal Button */}
                      <button
                        type="button"
                        onClick={() => handleOpenReviewModal(s)}
                        className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold text-white bg-primary hover:bg-primary-hover rounded-md transition-colors shadow-sm"
                        title="Score submission against published rubric"
                      >
                        <Scale className="w-3 h-3" />
                        <span>Judge Review</span>
                      </button>

                      {/* AI Assessment Modal Button */}
                      <button
                        type="button"
                        onClick={() => handleOpenEvaluationModal(s)}
                        className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-md transition-colors"
                        title="View transparent AI assessment, criterion scores, and grounded line citations"
                      >
                        <FileCode className="w-3 h-3 text-primary" />
                        <span>AI Assessment</span>
                      </button>

                      {/* Evaluate / Re-evaluate Button */}
                      {s.latest_job_status === 'running' || s.latest_job_status === 'queued' ? (
                        <span className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium text-primary bg-primary/10 border border-primary/20 rounded-md">
                          <RefreshCw className="w-3 h-3 animate-spin" />
                          <span>Evaluating...</span>
                        </span>
                      ) : s.latest_score !== null && s.latest_score !== undefined ? (
                        <button
                          type="button"
                          onClick={() => handleTriggerEvaluation(s.id)}
                          disabled={isTriggeringEval && triggeringSubId === s.id}
                          className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium text-text-secondary hover:text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-md transition-colors disabled:opacity-50"
                          title="Run fresh re-evaluation"
                        >
                          <RefreshCw className={`w-3 h-3 ${isTriggeringEval && triggeringSubId === s.id ? 'animate-spin' : ''}`} />
                          <span>Re-evaluate</span>
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => handleTriggerEvaluation(s.id)}
                          disabled={isTriggeringEval && triggeringSubId === s.id}
                          className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium text-status-success hover:text-white bg-status-success/10 hover:bg-status-success border border-status-success/30 rounded-md transition-colors disabled:opacity-50"
                          title="Evaluate submission repository"
                        >
                          <Play className={`w-3 h-3 ${isTriggeringEval && triggeringSubId === s.id ? 'animate-spin' : ''}`} />
                          <span>Evaluate</span>
                        </button>
                      )}

                      <button
                        type="button"
                        onClick={() => handleRefreshVerification(s.id)}
                        disabled={refreshingSubId === s.id}
                        className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-md transition-colors disabled:opacity-50"
                        title="Re-verify repository connection and refresh commit SHA"
                      >
                        <RefreshCw className={`w-3 h-3 ${refreshingSubId === s.id ? 'animate-spin' : ''}`} />
                        <span>{refreshingSubId === s.id ? 'Verifying...' : 'Verify'}</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => handleOpenBranchModal(s)}
                        className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-md transition-colors"
                        title="Update target branch"
                      >
                        <GitBranch className="w-3 h-3" />
                        <span>Branch</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => handleOpenRelinkModal(s)}
                        className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-md transition-colors"
                        title="Link or replace repository"
                      >
                        <Link2 className="w-3 h-3" />
                        <span>Relink</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => handleOpenActivityModal(s)}
                        className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-md transition-colors"
                        title="View repository activity timeline"
                      >
                        <Activity className="w-3 h-3 text-primary" />
                        <span>Activity</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => handleUnlinkRepository(s)}
                        disabled={s.connection_status === 'unlinked'}
                        className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium text-status-error/80 hover:text-status-error bg-surface-elevated hover:bg-status-error/10 border border-surface-border rounded-md transition-colors disabled:opacity-40"
                        title="Unlink repository"
                      >
                        <Unlink className="w-3 h-3" />
                        <span>Unlink</span>
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Tab 4: Judges */}
      {activeTab === 'judges' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-text-primary">Evaluation Judges</h3>
            <button
              type="button"
              onClick={() => setIsAssignJudgeOpen(true)}
              className="flex items-center gap-1 px-3 py-1.5 text-xs font-semibold text-white bg-primary hover:bg-primary-hover rounded-lg transition-colors shadow-sm"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>Assign Judge</span>
            </button>
          </div>

          {isTabLoading ? (
            <div className="p-8 text-center text-xs text-text-muted">Loading judges...</div>
          ) : judges.length === 0 ? (
            <div className="p-8 bg-surface rounded-xl border border-surface-border text-center">
              <Award className="w-8 h-8 text-text-muted mx-auto mb-2 opacity-50" />
              <p className="text-xs text-text-muted">No judges assigned to this event yet.</p>
            </div>
          ) : (
            <div className="divide-y divide-surface-border bg-surface rounded-xl border border-surface-border overflow-hidden">
              {judges.map((j) => (
                <div key={j.id} className="p-3.5 flex items-center justify-between text-xs">
                  <div>
                    <span className="font-semibold text-text-primary block">{j.user_name || j.user_email}</span>
                    <span className="text-[11px] text-text-muted font-mono">{j.user_email}</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleRemoveJudge(j.user_id, j.user_email)}
                    className="p-1.5 text-text-muted hover:text-status-error hover:bg-status-error/10 rounded-lg transition-colors"
                    title="Remove Judge"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Tab 5: Rubric */}
      {activeTab === 'rubric' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-text-primary">Evaluation Rubric & Criteria</h3>
              <p className="text-[11px] text-text-muted mt-0.5">
                Criteria define weights and evidence requirements evaluated by the AI engine.
              </p>
            </div>

            {rubric && rubric.active_version?.status === 'draft' && (
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setIsAddCriterionOpen(true)}
                  className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors"
                >
                  <Plus className="w-3.5 h-3.5" />
                  <span>Add Criterion</span>
                </button>
                <button
                  type="button"
                  onClick={handlePublishRubric}
                  className="flex items-center gap-1 px-3 py-1.5 text-xs font-semibold text-white bg-status-success hover:bg-status-success/90 rounded-lg transition-colors shadow-sm"
                >
                  <CheckCheck className="w-3.5 h-3.5" />
                  <span>Publish & Freeze Rubric</span>
                </button>
              </div>
            )}
          </div>

          {isTabLoading ? (
            <div className="p-8 text-center text-xs text-text-muted">Loading rubric...</div>
          ) : !rubric ? (
            <div className="p-8 bg-surface rounded-xl border border-surface-border text-center space-y-3">
              <Scale className="w-8 h-8 text-text-muted mx-auto opacity-50" />
              <div>
                <h4 className="text-xs font-semibold text-text-primary">No Rubric Configured</h4>
                <p className="text-[11px] text-text-muted mt-0.5">
                  Initialize an evaluation rubric to define criteria weights before starting evaluations.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsCreateRubricOpen(true)}
                className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover rounded-lg transition-colors shadow-sm"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>Initialize Rubric</span>
              </button>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="p-4 bg-surface rounded-xl border border-surface-border flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <h4 className="text-xs font-bold text-text-primary">{rubric.name}</h4>
                    <span className="text-[10px] font-mono px-2 py-0.5 bg-surface-elevated rounded border border-surface-border text-text-secondary">
                      v{rubric.active_version?.version_number || 1}
                    </span>
                    <StatusBadge status={rubric.active_version?.status || 'draft'} size="sm" />
                  </div>
                  {rubric.description && (
                    <p className="text-[11px] text-text-muted mt-1">{rubric.description}</p>
                  )}
                </div>
                <span className="text-[11px] font-mono text-text-muted">
                  Mode: {rubric.scoring_mode}
                </span>
              </div>

              {rubric.active_version?.criteria.length === 0 ? (
                <div className="p-6 bg-surface rounded-xl border border-dashed border-surface-border text-center text-xs text-text-muted">
                  No criteria defined in this version. Click "Add Criterion" to start configuring weights.
                </div>
              ) : (
                <div className="space-y-3">
                  {rubric.active_version?.criteria.map((c) => (
                    <div key={c.id} className="p-4 bg-surface rounded-xl border border-surface-border space-y-2">
                      <div className="flex items-center justify-between">
                        <h5 className="text-xs font-bold text-text-primary">{c.title}</h5>
                        <span className="font-mono text-xs font-bold text-primary">
                          Weight: {(c.weight * 100).toFixed(0)}%
                        </span>
                      </div>
                      <p className="text-[11px] text-text-secondary">{c.description}</p>
                      {c.evidence_requirements && (
                        <div className="p-2 bg-surface-elevated rounded text-[11px] text-text-muted font-mono">
                          Evidence: {c.evidence_requirements}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Tab 6: Organizer Reviews & Scoring Dashboard (M6.5) */}
      {activeTab === 'reviews' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2">
                <Award className="w-4 h-4 text-primary" />
                <span>Judge Reviews & Scoring Progress</span>
              </h3>
              <p className="text-[11px] text-text-muted mt-0.5">
                AI evaluates the evidence. Judges make the decisions. Track independent human review coverage.
              </p>
            </div>
            <div className="flex items-center gap-2">
              {hackathon?.settings?.results_published ? (
                <button
                  type="button"
                  onClick={handleUnpublishResults}
                  disabled={isPublishingResults}
                  className="px-3 py-1.5 text-xs font-semibold text-status-success bg-status-success/10 hover:bg-status-success/20 border border-status-success/30 rounded-lg inline-flex items-center gap-1.5 transition-colors disabled:opacity-50"
                  title="Results are live. Click to conceal from participants."
                >
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  <span>{isPublishingResults ? 'Updating...' : 'Results Published (Live)'}</span>
                </button>
              ) : (
                <button
                  type="button"
                  onClick={handlePublishResults}
                  disabled={isPublishingResults}
                  className="px-3 py-1.5 text-xs font-semibold text-white bg-primary hover:bg-primary-hover rounded-lg inline-flex items-center gap-1.5 shadow-xs transition-colors disabled:opacity-50"
                  title="Release official results and leaderboard to participants"
                >
                  <Award className="w-3.5 h-3.5" />
                  <span>{isPublishingResults ? 'Publishing...' : 'Publish Official Results'}</span>
                </button>
              )}
              <button
                type="button"
                onClick={() => loadTabData('reviews')}
                disabled={isTabLoading}
                className="px-3 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg inline-flex items-center gap-1.5 transition-colors disabled:opacity-50"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isTabLoading ? 'animate-spin' : ''}`} />
                <span>Refresh Progress</span>
              </button>
            </div>
          </div>

          {/* Metric Cards */}
          {reviewProgress ? (
            <div className="space-y-5">
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
                <div className="p-3.5 rounded-xl border border-surface-border bg-surface-card space-y-1">
                  <span className="text-[10px] text-text-muted uppercase font-semibold">Submissions</span>
                  <div className="text-xl font-bold font-mono text-text-primary">{reviewProgress.total_submissions}</div>
                </div>
                <div className="p-3.5 rounded-xl border border-surface-border bg-surface-card space-y-1">
                  <span className="text-[10px] text-text-muted uppercase font-semibold">Assigned Judges</span>
                  <div className="text-xl font-bold font-mono text-text-primary">{reviewProgress.total_judges}</div>
                </div>
                <div className="p-3.5 rounded-xl border border-surface-border bg-surface-card space-y-1">
                  <span className="text-[10px] text-text-muted uppercase font-semibold">Fully Reviewed</span>
                  <div className="text-xl font-bold font-mono text-status-success">{reviewProgress.submissions_fully_reviewed}</div>
                </div>
                <div className="p-3.5 rounded-xl border border-surface-border bg-surface-card space-y-1">
                  <span className="text-[10px] text-text-muted uppercase font-semibold">Awaiting Review</span>
                  <div className="text-xl font-bold font-mono text-status-warning">{reviewProgress.submissions_awaiting_review}</div>
                </div>
                <div className="p-3.5 rounded-xl border border-surface-border bg-surface-card space-y-1">
                  <span className="text-[10px] text-text-muted uppercase font-semibold">Submitted Reviews</span>
                  <div className="text-xl font-bold font-mono text-primary">{reviewProgress.submitted_reviews_count}</div>
                </div>
                <div className="p-3.5 rounded-xl border border-surface-border bg-surface-card space-y-1">
                  <span className="text-[10px] text-text-muted uppercase font-semibold">Active Drafts</span>
                  <div className="text-xl font-bold font-mono text-text-muted">{reviewProgress.draft_reviews_count}</div>
                </div>
              </div>

              {/* Judge Progress Table */}
              <div className="bg-surface-card rounded-xl border border-surface-border overflow-hidden">
                <div className="p-4 border-b border-surface-border flex items-center justify-between">
                  <h4 className="text-xs font-semibold text-text-primary uppercase tracking-wider">
                    Judge Completion Breakdown
                  </h4>
                  <span className="text-[11px] text-text-muted font-mono">
                    {reviewProgress.judge_progress.length} judges assigned
                  </span>
                </div>
                {reviewProgress.judge_progress.length === 0 ? (
                  <div className="p-8 text-center text-xs text-text-muted">
                    No judges assigned yet. Assign judges from the Judges tab.
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-surface-elevated/50 text-text-muted text-[10px] uppercase font-semibold border-b border-surface-border">
                        <tr>
                          <th className="py-2.5 px-4">Judge</th>
                          <th className="py-2.5 px-4">Submitted</th>
                          <th className="py-2.5 px-4">Drafts</th>
                          <th className="py-2.5 px-4">Pending</th>
                          <th className="py-2.5 px-4 text-right">Completion Rate</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-surface-border">
                        {reviewProgress.judge_progress.map((jp) => {
                          const total = reviewProgress.total_submissions;
                          const rate = total > 0 ? Math.round((jp.submitted_count / total) * 100) : 0;
                          return (
                            <tr key={jp.judge_user_id} className="hover:bg-surface-hover/30 transition-colors">
                              <td className="py-3 px-4">
                                <div className="font-semibold text-text-primary">{jp.judge_name || 'Anonymous Judge'}</div>
                                <div className="text-[11px] text-text-muted font-mono">{jp.judge_email}</div>
                              </td>
                              <td className="py-3 px-4 font-mono font-bold text-status-success">{jp.submitted_count}</td>
                              <td className="py-3 px-4 font-mono text-status-warning">{jp.draft_count}</td>
                              <td className="py-3 px-4 font-mono text-text-muted">{jp.pending_count}</td>
                              <td className="py-3 px-4 text-right">
                                <span className="font-mono font-bold text-text-primary">{rate}%</span>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Submission Review Coverage Table */}
              <div className="bg-surface-card rounded-xl border border-surface-border overflow-hidden">
                <div className="p-4 border-b border-surface-border flex items-center justify-between">
                  <h4 className="text-xs font-semibold text-text-primary uppercase tracking-wider">
                    Submission Review Coverage
                  </h4>
                  <span className="text-[11px] text-text-muted font-mono">
                    {reviewProgress.submission_coverage.length} submissions
                  </span>
                </div>
                {reviewProgress.submission_coverage.length === 0 ? (
                  <div className="p-8 text-center text-xs text-text-muted">
                    No submissions registered yet.
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-surface-elevated/50 text-text-muted text-[10px] uppercase font-semibold border-b border-surface-border">
                        <tr>
                          <th className="py-2.5 px-4">Submission & Team</th>
                          <th className="py-2.5 px-4">Submitted Reviews</th>
                          <th className="py-2.5 px-4">Drafts</th>
                          <th className="py-2.5 px-4">Average Human Score</th>
                          <th className="py-2.5 px-4 text-right">Action</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-surface-border">
                        {reviewProgress.submission_coverage.map((sc) => {
                          const subObj = submissions.find((s) => s.id === sc.submission_id);
                          return (
                            <tr key={sc.submission_id} className="hover:bg-surface-hover/30 transition-colors">
                              <td className="py-3 px-4">
                                <div className="font-semibold text-text-primary">{sc.title}</div>
                                <div className="text-[11px] text-text-muted">Team: {sc.team_name}</div>
                              </td>
                              <td className="py-3 px-4 font-mono font-semibold text-status-success">{sc.submitted_reviews_count}</td>
                              <td className="py-3 px-4 font-mono text-status-warning">{sc.draft_reviews_count}</td>
                              <td className="py-3 px-4 font-mono font-bold text-text-primary">
                                {sc.average_human_score !== null && sc.average_human_score !== undefined
                                  ? `${sc.average_human_score} / 10.00`
                                  : '—'}
                              </td>
                              <td className="py-3 px-4 text-right">
                                {subObj && (
                                  <button
                                    type="button"
                                    onClick={() => handleOpenReviewModal(subObj)}
                                    className="px-2.5 py-1 text-[11px] font-semibold text-primary hover:text-white bg-primary/10 hover:bg-primary rounded-md transition-colors"
                                  >
                                    Review
                                  </button>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="p-8 text-center text-xs text-text-muted">
              Loading review progress...
            </div>
          )}
        </div>
      )}

      {/* Edit Draft Modal */}
      {isEditModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="bg-surface border border-surface-border rounded-2xl w-full max-w-md shadow-surface-elevated overflow-hidden">
            <div className="p-5 border-b border-surface-border flex items-center justify-between">
              <h3 className="text-sm font-semibold text-text-primary">Edit Draft Hackathon</h3>
              <button
                type="button"
                onClick={() => setIsEditModalOpen(false)}
                className="p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-surface-elevated"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleSaveEdit} className="p-5 space-y-4 text-xs">
              <div>
                <label className="block font-medium text-text-secondary mb-1">Title</label>
                <input
                  type="text"
                  required
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>
              <div>
                <label className="block font-medium text-text-secondary mb-1">Description</label>
                <textarea
                  rows={4}
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>
              <div className="pt-2 flex items-center justify-end gap-2.5 border-t border-surface-border">
                <button
                  type="button"
                  onClick={() => setIsEditModalOpen(false)}
                  className="px-3 py-2 text-xs font-medium text-text-muted hover:text-text-primary"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSavingEdit || !editTitle.trim()}
                  className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg shadow-sm"
                >
                  {isSavingEdit ? 'Saving...' : 'Save Draft'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Register Team Modal */}
      {isCreateTeamOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="bg-surface border border-surface-border rounded-2xl w-full max-w-md shadow-surface-elevated overflow-hidden">
            <div className="p-5 border-b border-surface-border flex items-center justify-between">
              <h3 className="text-sm font-semibold text-text-primary">Register New Team</h3>
              <button
                type="button"
                onClick={() => setIsCreateTeamOpen(false)}
                className="p-1.5 rounded-lg text-text-muted hover:text-text-primary"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleCreateTeam} className="p-5 space-y-4 text-xs">
              <div>
                <label className="block font-medium text-text-secondary mb-1">Team Name</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Neural Pioneers"
                  value={teamName}
                  onChange={(e) => setTeamName(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>
              <div className="pt-2 flex items-center justify-end gap-2.5 border-t border-surface-border">
                <button
                  type="button"
                  onClick={() => setIsCreateTeamOpen(false)}
                  className="px-3 py-2 text-xs font-medium text-text-muted hover:text-text-primary"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!teamName.trim()}
                  className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg shadow-sm"
                >
                  Register Team
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Join Team Modal */}
      {isJoinTeamOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="bg-surface border border-surface-border rounded-2xl w-full max-w-md shadow-surface-elevated overflow-hidden">
            <div className="p-5 border-b border-surface-border flex items-center justify-between">
              <h3 className="text-sm font-semibold text-text-primary">Join Team via Code</h3>
              <button
                type="button"
                onClick={() => setIsJoinTeamOpen(false)}
                className="p-1.5 rounded-lg text-text-muted hover:text-text-primary"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleJoinTeam} className="p-5 space-y-4 text-xs">
              <div>
                <label className="block font-medium text-text-secondary mb-1">12-Character Join Code</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. 4B7B5F8A9C12"
                  value={joinCode}
                  onChange={(e) => setJoinCode(e.target.value.toUpperCase())}
                  className="w-full px-3 py-2 text-xs font-mono uppercase bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>
              <div className="pt-2 flex items-center justify-end gap-2.5 border-t border-surface-border">
                <button
                  type="button"
                  onClick={() => setIsJoinTeamOpen(false)}
                  className="px-3 py-2 text-xs font-medium text-text-muted hover:text-text-primary"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!joinCode.trim()}
                  className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg shadow-sm"
                >
                  Join Team
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Submit Project Modal */}
      {isSubmitModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="bg-surface border border-surface-border rounded-2xl w-full max-w-md shadow-surface-elevated overflow-hidden">
            <div className="p-5 border-b border-surface-border flex items-center justify-between">
              <h3 className="text-sm font-semibold text-text-primary">Submit Project Repository</h3>
              <button
                type="button"
                onClick={() => setIsSubmitModalOpen(false)}
                className="p-1.5 rounded-lg text-text-muted hover:text-text-primary"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleCreateSubmission} className="p-5 space-y-4 text-xs">
              <div>
                <label className="block font-medium text-text-secondary mb-1">Select Team</label>
                <select
                  required
                  value={subTeamId}
                  onChange={(e) => setSubTeamId(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                >
                  <option value="">-- Choose your team --</option>
                  {teams.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block font-medium text-text-secondary mb-1">Project Title</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Autonomous Research Copilot"
                  value={subTitle}
                  onChange={(e) => setSubTitle(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>
              <div>
                <label className="block font-medium text-text-secondary mb-1">GitHub Repository URL</label>
                <input
                  type="url"
                  required
                  placeholder="https://github.com/owner/repository"
                  value={subRepoUrl}
                  onChange={(e) => setSubRepoUrl(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>
              <div>
                <label className="block font-medium text-text-secondary mb-1">Target Branch</label>
                <input
                  type="text"
                  required
                  placeholder="main"
                  value={subBranch}
                  onChange={(e) => setSubBranch(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>

              <div className="flex items-center justify-between pt-1">
                <span className="text-[11px] text-text-muted">Verify repository accessibility before submitting</span>
                <button
                  type="button"
                  onClick={handleValidateRepo}
                  disabled={isValidatingRepo || !subRepoUrl.trim()}
                  className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-md transition-colors disabled:opacity-50"
                >
                  <RefreshCw className={`w-3 h-3 ${isValidatingRepo ? 'animate-spin' : ''}`} />
                  <span>{isValidatingRepo ? 'Testing...' : 'Test Connection'}</span>
                </button>
              </div>

              {repoValidation && (
                <div
                  className={`p-3 rounded-lg border text-[11px] space-y-1 ${
                    repoValidation.is_accessible
                      ? 'bg-status-success/10 border-status-success/30 text-status-success'
                      : 'bg-status-error/10 border-status-error/30 text-status-error'
                  }`}
                >
                  <div className="flex items-center gap-1.5 font-semibold">
                    {repoValidation.is_accessible ? (
                      <>
                        <Check className="w-3.5 h-3.5 shrink-0" />
                        <span>Repository Accessible</span>
                      </>
                    ) : (
                      <>
                        <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                        <span>Verification Failed: {repoValidation.diagnostic_code}</span>
                      </>
                    )}
                  </div>
                  {repoValidation.is_accessible ? (
                    <div className="text-[10px] space-y-0.5 text-text-secondary font-mono">
                      <p>Target Branch: {repoValidation.target_branch || 'main'}</p>
                      {repoValidation.commit_sha && <p>Commit: {repoValidation.commit_sha.slice(0, 7)}</p>}
                      <p>
                        Ownership: {repoValidation.ownership_verified ? 'Verified (via App)' : 'Public Access (Unauthenticated)'}
                      </p>
                    </div>
                  ) : (
                    <p className="text-[10px] text-status-error/90">{repoValidation.message}</p>
                  )}
                </div>
              )}

              <div className="pt-2 flex items-center justify-end gap-2.5 border-t border-surface-border">
                <button
                  type="button"
                  onClick={() => {
                    setIsSubmitModalOpen(false);
                    setRepoValidation(null);
                  }}
                  className="px-3 py-2 text-xs font-medium text-text-muted hover:text-text-primary"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!subTeamId || !subTitle.trim() || !subRepoUrl.trim()}
                  className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg shadow-sm"
                >
                  Submit Project
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Change Branch Modal (M6.2) */}
      {isBranchModalOpen && branchSub && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="bg-surface border border-surface-border rounded-2xl w-full max-w-md shadow-surface-elevated overflow-hidden">
            <div className="p-5 border-b border-surface-border flex items-center justify-between">
              <h3 className="text-sm font-semibold text-text-primary">Update Target Branch</h3>
              <button
                type="button"
                onClick={() => setIsBranchModalOpen(false)}
                className="p-1.5 rounded-lg text-text-muted hover:text-text-primary"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleUpdateBranch} className="p-5 space-y-4 text-xs">
              <div>
                <p className="text-[11px] text-text-muted mb-2">
                  Update evaluation target branch for <strong className="text-text-primary">{branchSub.title}</strong>.
                  Scorva will verify that this branch exists on GitHub and resolve its latest commit.
                </p>
                <label className="block font-medium text-text-secondary mb-1">New Target Branch</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. staging or release-v1"
                  value={editBranch}
                  onChange={(e) => setEditBranch(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>
              <div className="pt-2 flex items-center justify-end gap-2.5 border-t border-surface-border">
                <button
                  type="button"
                  onClick={() => setIsBranchModalOpen(false)}
                  className="px-3 py-2 text-xs font-medium text-text-muted hover:text-text-primary"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isUpdatingBranch || !editBranch.trim()}
                  className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg shadow-sm"
                >
                  {isUpdatingBranch ? 'Verifying & Updating...' : 'Update Branch'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Relink Repository Modal (M6.2) */}
      {isRelinkModalOpen && relinkSub && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="bg-surface border border-surface-border rounded-2xl w-full max-w-md shadow-surface-elevated overflow-hidden">
            <div className="p-5 border-b border-surface-border flex items-center justify-between">
              <h3 className="text-sm font-semibold text-text-primary">Link / Relink Repository</h3>
              <button
                type="button"
                onClick={() => setIsRelinkModalOpen(false)}
                className="p-1.5 rounded-lg text-text-muted hover:text-text-primary"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleRelinkRepository} className="p-5 space-y-4 text-xs">
              <div>
                <p className="text-[11px] text-text-muted mb-2">
                  Link or replace the repository for <strong className="text-text-primary">{relinkSub.title}</strong>.
                  Failsafe guarantee: If verification fails, your existing link remains unmodified.
                </p>
                <label className="block font-medium text-text-secondary mb-1">GitHub Repository URL</label>
                <input
                  type="url"
                  required
                  placeholder="https://github.com/owner/repo"
                  value={relinkUrl}
                  onChange={(e) => setRelinkUrl(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>

              <div>
                <label className="block font-medium text-text-secondary mb-1">Target Branch</label>
                <input
                  type="text"
                  required
                  placeholder="main"
                  value={relinkBranch}
                  onChange={(e) => setRelinkBranch(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>

              <div className="flex items-center justify-between pt-1">
                <span className="text-[11px] text-text-muted">Test connection</span>
                <button
                  type="button"
                  onClick={handleValidateRelink}
                  disabled={isValidatingRelink || !relinkUrl.trim()}
                  className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-md transition-colors disabled:opacity-50"
                >
                  <RefreshCw className={`w-3 h-3 ${isValidatingRelink ? 'animate-spin' : ''}`} />
                  <span>{isValidatingRelink ? 'Testing...' : 'Test Connection'}</span>
                </button>
              </div>

              {relinkValidation && (
                <div
                  className={`p-3 rounded-lg border text-[11px] space-y-1 ${
                    relinkValidation.is_accessible
                      ? 'bg-status-success/10 border-status-success/30 text-status-success'
                      : 'bg-status-error/10 border-status-error/30 text-status-error'
                  }`}
                >
                  <div className="flex items-center gap-1.5 font-semibold">
                    {relinkValidation.is_accessible ? (
                      <>
                        <Check className="w-3.5 h-3.5 shrink-0" />
                        <span>Repository Accessible</span>
                      </>
                    ) : (
                      <>
                        <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                        <span>Verification Failed: {relinkValidation.diagnostic_code}</span>
                      </>
                    )}
                  </div>
                  {relinkValidation.is_accessible ? (
                    <div className="text-[10px] space-y-0.5 text-text-secondary font-mono">
                      <p>Target Branch: {relinkValidation.target_branch || 'main'}</p>
                      {relinkValidation.commit_sha && <p>Commit: {relinkValidation.commit_sha.slice(0, 7)}</p>}
                    </div>
                  ) : (
                    <p className="text-[10px] text-status-error/90">{relinkValidation.message}</p>
                  )}
                </div>
              )}

              <div className="pt-2 flex items-center justify-end gap-2.5 border-t border-surface-border">
                <button
                  type="button"
                  onClick={() => {
                    setIsRelinkModalOpen(false);
                    setRelinkValidation(null);
                  }}
                  className="px-3 py-2 text-xs font-medium text-text-muted hover:text-text-primary"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isRelinking || !relinkUrl.trim()}
                  className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg shadow-sm"
                >
                  {isRelinking ? 'Verifying & Linking...' : 'Link Repository'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Activity Timeline Modal (M6.3) */}
      {isActivityModalOpen && activitySub && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="bg-surface border border-surface-border rounded-2xl w-full max-w-2xl max-h-[85vh] flex flex-col shadow-surface-elevated overflow-hidden">
            <div className="p-5 border-b border-surface-border flex items-center justify-between shrink-0">
              <div>
                <div className="flex items-center gap-2">
                  <Activity className="w-4 h-4 text-primary" />
                  <h3 className="text-sm font-semibold text-text-primary">Repository Activity Timeline</h3>
                </div>
                <p className="text-[11px] text-text-muted mt-0.5 font-mono">
                  {activitySub.title} • {activitySub.repository_url} (branch: {activitySub.target_branch})
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsActivityModalOpen(false)}
                className="p-1.5 rounded-lg text-text-muted hover:text-text-primary"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-5 overflow-y-auto space-y-3 flex-1 text-xs">
              {isLoadingActivity ? (
                <div className="p-8 text-center text-xs text-text-muted">Loading activity events...</div>
              ) : activities.length === 0 ? (
                <div className="p-8 bg-surface-elevated/40 rounded-xl border border-dashed border-surface-border text-center space-y-1.5">
                  <Activity className="w-6 h-6 text-text-muted mx-auto opacity-50" />
                  <p className="text-xs font-medium text-text-secondary">No repository webhook events recorded yet.</p>
                  <p className="text-[11px] text-text-muted">
                    Configure your repository webhook to receive real-time push, pull request, and commit timeline evidence.
                  </p>
                </div>
              ) : (
                <div className="divide-y divide-surface-border/60 border border-surface-border rounded-xl bg-surface-elevated/20 overflow-hidden">
                  {activities.map((act) => (
                    <div key={act.id} className="p-3.5 space-y-1.5 hover:bg-surface-elevated/40 transition-colors">
                      <div className="flex items-center justify-between gap-2 flex-wrap">
                        <div className="flex items-center gap-2">
                          {act.event_type === 'push' && (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-status-success/15 text-status-success border border-status-success/30 font-mono">
                              <GitCommit className="w-3 h-3" />
                              push
                            </span>
                          )}
                          {act.event_type === 'pull_request' && (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-purple-500/15 text-purple-400 border border-purple-500/30 font-mono">
                              <GitPullRequest className="w-3 h-3" />
                              pull_request ({act.action || 'updated'})
                            </span>
                          )}
                          {!['push', 'pull_request'].includes(act.event_type) && (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-status-info/15 text-status-info border border-status-info/30 font-mono">
                              <Activity className="w-3 h-3" />
                              {act.event_type}
                            </span>
                          )}

                          <span className="font-semibold text-text-primary text-xs">{act.summary || 'Event recorded'}</span>
                        </div>

                        <span className="text-[10px] text-text-muted font-mono">
                          {new Date(act.event_timestamp).toLocaleDateString([], { month: 'short', day: 'numeric' })}{' '}
                          {new Date(act.event_timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </span>
                      </div>

                      <div className="flex items-center gap-3 text-[11px] text-text-muted font-mono flex-wrap">
                        {act.sender_login && (
                          <span>Author: <strong className="text-text-secondary">@{act.sender_login}</strong></span>
                        )}
                        {act.ref && (
                          <span>Branch: <strong className="text-text-secondary">{act.ref.replace('refs/heads/', '')}</strong></span>
                        )}
                        {act.commit_sha && (
                          <span className="inline-flex items-center gap-0.5 text-text-secondary">
                            <GitCommit className="w-3 h-3" />
                            <code>{act.commit_sha.slice(0, 7)}</code>
                          </span>
                        )}
                        {act.status && (
                          <span className={`px-1.5 py-0.5 rounded text-[9px] uppercase font-semibold ${
                            act.status === 'processed' ? 'bg-status-success/10 text-status-success' : 'bg-surface-elevated text-text-muted'
                          }`}>
                            {act.status}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="p-4 border-t border-surface-border flex items-center justify-end shrink-0">
              <button
                type="button"
                onClick={() => setIsActivityModalOpen(false)}
                className="px-4 py-2 text-xs font-semibold text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Assign Judge Modal */}
      {isAssignJudgeOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="bg-surface border border-surface-border rounded-2xl w-full max-w-md shadow-surface-elevated overflow-hidden">
            <div className="p-5 border-b border-surface-border flex items-center justify-between">
              <h3 className="text-sm font-semibold text-text-primary">Assign Judge</h3>
              <button
                type="button"
                onClick={() => setIsAssignJudgeOpen(false)}
                className="p-1.5 rounded-lg text-text-muted hover:text-text-primary"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleAssignJudge} className="p-5 space-y-4 text-xs">
              <div>
                <label className="block font-medium text-text-secondary mb-1">Judge User Email</label>
                <input
                  type="email"
                  required
                  placeholder="judge@university.edu"
                  value={judgeEmail}
                  onChange={(e) => setJudgeEmail(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
                <span className="text-[11px] text-text-muted block mt-1">
                  The user must already have a registered Scorva account.
                </span>
              </div>
              <div className="pt-2 flex items-center justify-end gap-2.5 border-t border-surface-border">
                <button
                  type="button"
                  onClick={() => setIsAssignJudgeOpen(false)}
                  className="px-3 py-2 text-xs font-medium text-text-muted hover:text-text-primary"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!judgeEmail.trim()}
                  className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg shadow-sm"
                >
                  Assign Judge
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Initialize Rubric Modal */}
      {isCreateRubricOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="bg-surface border border-surface-border rounded-2xl w-full max-w-md shadow-surface-elevated overflow-hidden">
            <div className="p-5 border-b border-surface-border flex items-center justify-between">
              <h3 className="text-sm font-semibold text-text-primary">Initialize Evaluation Rubric</h3>
              <button
                type="button"
                onClick={() => setIsCreateRubricOpen(false)}
                className="p-1.5 rounded-lg text-text-muted hover:text-text-primary"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleCreateRubric} className="p-5 space-y-4 text-xs">
              <div>
                <label className="block font-medium text-text-secondary mb-1">Rubric Name</label>
                <input
                  type="text"
                  required
                  value={rubricName}
                  onChange={(e) => setRubricName(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>
              <div>
                <label className="block font-medium text-text-secondary mb-1">Description</label>
                <textarea
                  rows={3}
                  value={rubricDesc}
                  onChange={(e) => setRubricDesc(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>
              <div className="pt-2 flex items-center justify-end gap-2.5 border-t border-surface-border">
                <button
                  type="button"
                  onClick={() => setIsCreateRubricOpen(false)}
                  className="px-3 py-2 text-xs font-medium text-text-muted hover:text-text-primary"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!rubricName.trim()}
                  className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg shadow-sm"
                >
                  Create Rubric
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Add Criterion Modal */}
      {isAddCriterionOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="bg-surface border border-surface-border rounded-2xl w-full max-w-md shadow-surface-elevated overflow-hidden">
            <div className="p-5 border-b border-surface-border flex items-center justify-between">
              <h3 className="text-sm font-semibold text-text-primary">Add Rubric Criterion</h3>
              <button
                type="button"
                onClick={() => setIsAddCriterionOpen(false)}
                className="p-1.5 rounded-lg text-text-muted hover:text-text-primary"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <form onSubmit={handleAddCriterion} className="p-5 space-y-4 text-xs">
              <div>
                <label className="block font-medium text-text-secondary mb-1">Criterion Title</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Technical Execution"
                  value={critTitle}
                  onChange={(e) => setCritTitle(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>
              <div>
                <label className="block font-medium text-text-secondary mb-1">Description</label>
                <textarea
                  rows={2}
                  required
                  placeholder="Specific assessment guidelines for AI evaluator"
                  value={critDesc}
                  onChange={(e) => setCritDesc(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>
              <div>
                <label className="block font-medium text-text-secondary mb-1">Weight (0.01 - 1.00)</label>
                <input
                  type="number"
                  step="0.05"
                  min="0.01"
                  max="1.00"
                  required
                  value={critWeight}
                  onChange={(e) => setCritWeight(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>
              <div>
                <label className="block font-medium text-text-secondary mb-1">Evidence Requirements</label>
                <input
                  type="text"
                  placeholder="e.g. Unit tests, benchmarks, architecture documentation"
                  value={critEvidence}
                  onChange={(e) => setCritEvidence(e.target.value)}
                  className="w-full px-3 py-2 text-xs bg-surface-elevated border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary"
                />
              </div>
              <div className="pt-2 flex items-center justify-end gap-2.5 border-t border-surface-border">
                <button
                  type="button"
                  onClick={() => setIsAddCriterionOpen(false)}
                  className="px-3 py-2 text-xs font-medium text-text-muted hover:text-text-primary"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!critTitle.trim() || !critDesc.trim()}
                  className="px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg shadow-sm"
                >
                  Add Criterion
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Judge Review & Scoring Form Modal (M6.5) */}
      {isReviewModalOpen && reviewSub && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs">
          <div className="bg-surface border border-surface-border rounded-2xl w-full max-w-5xl max-h-[92vh] shadow-surface-elevated overflow-hidden flex flex-col animate-in fade-in zoom-in-95 duration-150">
            {/* Header */}
            <div className="p-4 border-b border-surface-border flex items-center justify-between shrink-0 bg-surface-elevated/40">
              <div className="space-y-0.5">
                <div className="flex items-center gap-2">
                  <Scale className="w-4 h-4 text-primary" />
                  <h3 className="text-sm font-semibold text-text-primary">
                    Judge Review & Scoring: {reviewSub.title}
                  </h3>
                  {reviewData?.review && (
                    <StatusBadge status={reviewData.review.status} size="sm" />
                  )}
                  {reviewData?.review?.version && (
                    <span className="text-[10px] font-mono px-1.5 py-0.5 bg-surface-elevated border border-surface-border rounded text-text-muted">
                      v{reviewData.review.version}
                    </span>
                  )}
                </div>
                <div className="text-[11px] text-text-muted flex items-center gap-2 font-mono">
                  <span>Team: {reviewSub.team_name}</span>
                  {reviewSub.repository_owner && (
                    <>
                      <span>•</span>
                      <span>{reviewSub.repository_owner}/{reviewSub.repository_name}</span>
                    </>
                  )}
                  {reviewSub.target_branch && (
                    <>
                      <span>•</span>
                      <span>branch: {reviewSub.target_branch}</span>
                    </>
                  )}
                </div>
              </div>
              <button
                type="button"
                onClick={() => setIsReviewModalOpen(false)}
                className="p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-surface-elevated transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-5 overflow-y-auto space-y-5 text-xs flex-1">
              {isLoadingReview && (
                <div className="p-12 text-center text-text-muted space-y-2">
                  <RefreshCw className="w-5 h-5 animate-spin mx-auto text-primary" />
                  <p>Loading rubric and submission assessment...</p>
                </div>
              )}

              {reviewError && (
                <div className="p-3.5 rounded-xl bg-status-danger/10 border border-status-danger/20 text-status-danger flex items-center gap-2 text-xs">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{reviewError}</span>
                </div>
              )}

              {reviewSuccessMsg && (
                <div className="p-3.5 rounded-xl bg-status-success/10 border border-status-success/20 text-status-success flex items-center gap-2 text-xs">
                  <CheckCircle2 className="w-4 h-4 shrink-0" />
                  <span>{reviewSuccessMsg}</span>
                </div>
              )}

              {!isLoadingReview && reviewData && (
                <div className="space-y-5">
                  {/* Immutability Banner */}
                  {!reviewData.can_edit && reviewData.review?.status === 'submitted' && (
                    <div className="p-3.5 rounded-xl bg-status-success/10 border border-status-success/30 text-text-primary flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2 text-status-success font-semibold">
                        <CheckCheck className="w-4 h-4" />
                        <span>This review has been submitted and is permanently recorded.</span>
                      </div>
                      {reviewData.review.submitted_at && (
                        <span className="text-[11px] text-text-muted font-mono">
                          Submitted: {new Date(reviewData.review.submitted_at).toLocaleDateString()} {new Date(reviewData.review.submitted_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </span>
                      )}
                    </div>
                  )}

                  {/* Two-Column Side-by-Side: AI Evidence vs Human Decision */}
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
                    {/* Left Column: AI Advisory Assessment (Transparent Evidence) */}
                    <div className="space-y-4 bg-surface-elevated/30 rounded-xl p-4 border border-surface-border">
                      <div className="flex items-center justify-between border-b border-surface-border pb-2.5">
                        <div className="flex items-center gap-2">
                          <FileCode className="w-4 h-4 text-primary" />
                          <h4 className="text-xs font-bold text-text-primary uppercase tracking-wider">
                            AI Advisory Findings
                          </h4>
                        </div>
                        <span className="text-[10px] text-text-muted italic">Non-Binding Evidence</span>
                      </div>

                      {reviewData.ai_evaluation ? (
                        <div className="space-y-3">
                          <div className="flex items-center justify-between p-3 rounded-lg bg-surface-card border border-surface-border">
                            <div>
                              <span className="text-[10px] text-text-muted uppercase font-semibold block">AI Suggested Score</span>
                              <div className="text-lg font-bold font-mono text-primary">
                                {reviewData.ai_evaluation.normalized_score !== null && reviewData.ai_evaluation.normalized_score !== undefined
                                  ? `${reviewData.ai_evaluation.normalized_score} / 100`
                                  : 'Not Scored'}
                              </div>
                            </div>
                            <StatusBadge status="completed" size="sm" />
                          </div>

                          {reviewData.ai_evaluation.has_insufficient_evidence && (
                            <div className="p-2.5 rounded-lg bg-status-warning/10 border border-status-warning/30 text-status-warning text-[11px]">
                              Warning: The AI model reported insufficient repository evidence to evaluate reliably.
                            </div>
                          )}

                          {reviewData.ai_evaluation.summary_assessment && (
                            <div className="p-3 rounded-lg bg-surface-card border border-surface-border space-y-1">
                              <span className="text-[10px] uppercase font-semibold text-text-muted tracking-wider block">AI Evaluation Summary</span>
                              <p className="text-text-secondary text-[11px] leading-relaxed whitespace-pre-wrap">
                                {reviewData.ai_evaluation.summary_assessment}
                              </p>
                            </div>
                          )}

                          {/* Criterion breakdown with line citations */}
                          <div className="space-y-2.5">
                            <span className="text-[10px] uppercase font-semibold text-text-muted tracking-wider block">
                              AI Criterion Rationale & Citations
                            </span>
                            {reviewData.ai_evaluation.criterion_scores.map((cs) => (
                              <div key={cs.id} className="p-3 rounded-lg bg-surface-card border border-surface-border space-y-2 text-[11px]">
                                <div className="flex items-center justify-between font-semibold">
                                  <span className="text-text-primary">{cs.title}</span>
                                  <span className="font-mono text-primary">
                                    {cs.awarded_score} / {cs.max_score}
                                  </span>
                                </div>
                                <p className="text-text-muted italic">{cs.rationale}</p>

                                {cs.evidence_references && cs.evidence_references.length > 0 && (
                                  <div className="pt-1.5 border-t border-surface-border/60 space-y-1">
                                    <span className="text-[9px] uppercase font-semibold text-text-muted tracking-wider block">
                                      Evidence Citations ({cs.evidence_references.length})
                                    </span>
                                    {cs.evidence_references.map((ev) => (
                                      <div key={ev.id} className="p-2 bg-black/30 rounded border border-surface-border font-mono text-[10px] space-y-1">
                                        <div className="flex items-center justify-between text-primary">
                                          <span>{ev.file_path}:{ev.start_line}-{ev.end_line}</span>
                                          {ev.is_verified_in_repo && <span className="text-status-success text-[9px]">Verified</span>}
                                        </div>
                                        <pre className="text-text-muted overflow-x-auto whitespace-pre p-1.5 bg-black/40 rounded">
                                          {ev.snippet}
                                        </pre>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : (
                        <div className="p-8 text-center text-xs text-text-muted border border-dashed border-surface-border rounded-lg">
                          No automated AI assessment exists for this submission. Judges can evaluate independently.
                        </div>
                      )}
                    </div>

                    {/* Right Column: Independent Human Judge Scoring Form */}
                    <div className="space-y-4 bg-surface-card rounded-xl p-4 border border-surface-border">
                      <div className="flex items-center justify-between border-b border-surface-border pb-2.5">
                        <div className="flex items-center gap-2">
                          <Scale className="w-4 h-4 text-status-success" />
                          <h4 className="text-xs font-bold text-text-primary uppercase tracking-wider">
                            Judge Rubric Scoring
                          </h4>
                        </div>
                        <span className="text-[10px] text-text-muted font-mono">
                          Rubric: {reviewData.rubric_name}
                        </span>
                      </div>

                      {/* Criteria Forms */}
                      <div className="space-y-4">
                        {reviewData.rubric_criteria.map((c) => {
                          const val = reviewCriterionScores[c.id] || { score: '', notes: '' };
                          return (
                            <div key={c.id} className="p-3.5 bg-surface-elevated/40 rounded-xl border border-surface-border space-y-2.5">
                              <div className="flex items-start justify-between gap-2">
                                <div>
                                  <div className="font-semibold text-text-primary text-xs">{c.title}</div>
                                  {c.description && <p className="text-[11px] text-text-muted mt-0.5">{c.description}</p>}
                                </div>
                                <div className="flex items-center gap-1.5 shrink-0 font-mono text-[10px]">
                                  <span className="px-1.5 py-0.5 rounded bg-surface-elevated text-text-muted">Weight: {c.weight}</span>
                                  <span className="px-1.5 py-0.5 rounded bg-surface-elevated text-text-muted">[{c.min_score} - {c.max_score}]</span>
                                </div>
                              </div>

                              <div className="grid grid-cols-1 sm:grid-cols-4 gap-2.5 items-start">
                                <div className="sm:col-span-1">
                                  <label className="block text-[10px] uppercase font-semibold text-text-muted mb-1">
                                    Judge Score <span className="text-status-danger">*</span>
                                  </label>
                                  <input
                                    type="number"
                                    step="0.1"
                                    min={Number(c.min_score)}
                                    max={Number(c.max_score)}
                                    disabled={!reviewData.can_edit}
                                    placeholder={`${c.min_score} - ${c.max_score}`}
                                    value={val.score}
                                    onChange={(e) => {
                                      const newScore = e.target.value;
                                      setReviewCriterionScores((prev) => ({
                                        ...prev,
                                        [c.id]: { ...prev[c.id], score: newScore, notes: prev[c.id]?.notes || '' },
                                      }));
                                    }}
                                    className="w-full px-2.5 py-1.5 text-xs font-mono font-semibold bg-surface border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary disabled:opacity-70 disabled:bg-surface-elevated"
                                  />
                                </div>
                                <div className="sm:col-span-3">
                                  <label className="block text-[10px] uppercase font-semibold text-text-muted mb-1">
                                    Criterion Feedback / Notes
                                  </label>
                                  <input
                                    type="text"
                                    disabled={!reviewData.can_edit}
                                    placeholder="Optional notes or rationale for this criterion..."
                                    value={val.notes}
                                    onChange={(e) => {
                                      const newNotes = e.target.value;
                                      setReviewCriterionScores((prev) => ({
                                        ...prev,
                                        [c.id]: { score: prev[c.id]?.score || '', notes: newNotes },
                                      }));
                                    }}
                                    className="w-full px-2.5 py-1.5 text-xs bg-surface border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary disabled:opacity-70 disabled:bg-surface-elevated"
                                  />
                                </div>
                              </div>
                            </div>
                          );
                        })}
                      </div>

                      {/* Overall Feedback */}
                      <div className="space-y-1.5 pt-2 border-t border-surface-border">
                        <label className="block text-xs font-semibold text-text-primary">
                          Overall Feedback <span className="text-status-danger">*</span>
                        </label>
                        <textarea
                          rows={3}
                          disabled={!reviewData.can_edit}
                          placeholder="Provide constructive feedback for the hackathon team (required for submission)..."
                          value={reviewOverallFeedback}
                          onChange={(e) => setReviewOverallFeedback(e.target.value)}
                          className="w-full px-3 py-2 text-xs bg-surface border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary disabled:opacity-70 disabled:bg-surface-elevated"
                        />
                      </div>

                      {/* Decision Select */}
                      <div className="space-y-1.5">
                        <label className="block text-xs font-semibold text-text-primary">
                          Judge Decision
                        </label>
                        <select
                          disabled={!reviewData.can_edit}
                          value={reviewDecision}
                          onChange={(e) => setReviewDecision(e.target.value)}
                          className="w-full px-3 py-2 text-xs bg-surface border border-surface-border rounded-lg text-text-primary focus:outline-none focus:border-primary disabled:opacity-70 disabled:bg-surface-elevated"
                        >
                          <option value="accepted">Accepted (Verified Submission)</option>
                          <option value="adjusted">Adjusted (Scored with Human Override)</option>
                          <option value="rejected">Rejected (Disqualified or Incomplete)</option>
                        </select>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="p-4 border-t border-surface-border flex items-center justify-between shrink-0 bg-surface-elevated/40">
              <div className="text-[11px] text-text-muted">
                {reviewData?.can_edit ? (
                  <span>Drafts can be saved at any time. Final submission permanently locks your review.</span>
                ) : (
                  <span>View-only mode. Review is finalized and immutable.</span>
                )}
              </div>
              <div className="flex items-center gap-2.5">
                {reviewData?.can_edit && (
                  <>
                    <button
                      type="button"
                      onClick={handleSaveReviewDraft}
                      disabled={isSavingReview || isSubmittingReview}
                      className="px-3.5 py-1.5 text-xs font-semibold text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors disabled:opacity-50 inline-flex items-center gap-1.5"
                    >
                      <RefreshCw className={`w-3 h-3 ${isSavingReview ? 'animate-spin' : ''}`} />
                      <span>{isSavingReview ? 'Saving Draft...' : 'Save Draft'}</span>
                    </button>

                    <button
                      type="button"
                      onClick={handleSubmitReview}
                      disabled={isSavingReview || isSubmittingReview}
                      className="px-4 py-1.5 text-xs font-semibold text-white bg-status-success hover:bg-status-success/90 rounded-lg transition-colors shadow-sm disabled:opacity-50 inline-flex items-center gap-1.5"
                    >
                      <CheckCircle2 className={`w-3.5 h-3.5 ${isSubmittingReview ? 'animate-spin' : ''}`} />
                      <span>{isSubmittingReview ? 'Submitting...' : 'Submit Final Review'}</span>
                    </button>
                  </>
                )}
                <button
                  type="button"
                  onClick={() => setIsReviewModalOpen(false)}
                  className="px-4 py-1.5 text-xs font-semibold text-text-secondary hover:text-text-primary bg-surface-elevated rounded-lg transition-colors"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* AI Evaluation Transparency Modal (M6.4) */}
      {isEvalModalOpen && evalSub && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
          <div className="bg-surface border border-surface-border rounded-2xl w-full max-w-3xl shadow-surface-elevated max-h-[90vh] flex flex-col overflow-hidden">
            {/* Header */}
            <div className="p-5 border-b border-surface-border flex items-center justify-between shrink-0 bg-surface-elevated/30">
              <div className="flex items-center gap-2.5 min-w-0">
                <div className="p-2 rounded-xl bg-primary/10 text-primary border border-primary/20 shrink-0">
                  <Scale className="w-5 h-5" />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-bold text-text-primary truncate">
                      {evalSub.title}
                    </h3>
                    <span className="text-[10px] font-medium px-2 py-0.5 rounded bg-surface border border-surface-border text-text-secondary">
                      {evalSub.team_name}
                    </span>
                  </div>
                  <p className="text-[11px] text-text-muted mt-0.5 font-mono truncate">
                    AI Evaluation & Evidence Transparency
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setIsEvalModalOpen(false)}
                className="p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-surface-elevated transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Product Principle Callout */}
            <div className="px-5 py-2.5 bg-primary/5 border-b border-primary/15 text-[11px] text-primary flex items-center justify-between shrink-0">
              <div className="flex items-center gap-2">
                <Sparkles className="w-3.5 h-3.5 shrink-0" />
                <span className="font-medium">
                  &ldquo;AI evaluates the evidence. Judges make the decisions. Scorva makes the process transparent.&rdquo;
                </span>
              </div>
              <span className="text-[10px] font-mono text-primary/70 uppercase tracking-wider shrink-0 hidden sm:inline">
                Subsystem C
              </span>
            </div>

            {/* Modal Scrollable Body */}
            <div className="p-5 overflow-y-auto space-y-5 text-xs flex-1">
              {isLoadingEvalTransparency ? (
                <div className="py-12 text-center space-y-3">
                  <RefreshCw className="w-7 h-7 text-primary animate-spin mx-auto" />
                  <p className="text-xs text-text-muted">Loading verified AI evaluation assessment and evidence citations...</p>
                </div>
              ) : evalError ? (
                <div className="p-4 bg-status-error/10 border border-status-error/30 rounded-xl space-y-2">
                  <div className="flex items-center gap-2 text-status-error font-semibold">
                    <AlertCircle className="w-4 h-4" />
                    <span>Error Loading Evaluation</span>
                  </div>
                  <p className="text-xs text-status-error/90">{evalError}</p>
                  <button
                    type="button"
                    onClick={() => handleOpenEvaluationModal(evalSub)}
                    className="mt-2 px-3 py-1 text-xs bg-status-error/20 hover:bg-status-error/30 text-status-error rounded-md transition-colors font-medium inline-flex items-center gap-1"
                  >
                    <RefreshCw className="w-3 h-3" />
                    <span>Retry</span>
                  </button>
                </div>
              ) : !evalTransparency?.has_evaluation ? (
                <div className="py-10 text-center space-y-4">
                  <div className="w-12 h-12 rounded-2xl bg-surface-elevated border border-surface-border flex items-center justify-center mx-auto text-text-muted">
                    <FileCode className="w-6 h-6" />
                  </div>
                  <div className="max-w-md mx-auto space-y-1">
                    <h4 className="font-semibold text-text-primary text-sm">No Evaluation Requested Yet</h4>
                    <p className="text-xs text-text-muted">
                      This submission has not yet been processed by the automated evaluation pipeline.
                    </p>
                  </div>

                  {evalTransparency && !evalTransparency.can_evaluate ? (
                    <div className="max-w-md mx-auto p-3 bg-status-warning/10 border border-status-warning/30 rounded-lg text-left space-y-1">
                      <div className="flex items-center gap-1.5 text-status-warning font-semibold text-[11px]">
                        <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                        <span>Cannot Evaluate Submission</span>
                      </div>
                      <p className="text-[11px] text-text-secondary">
                        {evalTransparency.cannot_evaluate_reason}
                      </p>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => handleTriggerEvaluation(evalSub.id)}
                      disabled={isTriggeringEval}
                      className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg shadow-sm transition-colors"
                    >
                      <Play className={`w-3.5 h-3.5 ${isTriggeringEval ? 'animate-spin' : ''}`} />
                      <span>{isTriggeringEval ? 'Dispatching...' : 'Dispatch AI Evaluation'}</span>
                    </button>
                  )}
                </div>
              ) : (
                <div className="space-y-5">
                  {/* Job Status & Metadata Ribbon */}
                  <div className="p-3.5 bg-surface-elevated rounded-xl border border-surface-border space-y-2.5">
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-[11px] text-text-muted font-medium">Status:</span>
                        <StatusBadge status={evalTransparency.job?.status || 'pending'} size="sm" />
                        {evalTransparency.job?.current_stage && evalTransparency.job.status === 'running' && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono bg-primary/10 text-primary border border-primary/20">
                            <RefreshCw className="w-2.5 h-2.5 animate-spin" />
                            Stage: {evalTransparency.job.current_stage}
                          </span>
                        )}
                        {evalTransparency.job?.attempts_count !== undefined && (
                          <span className="text-[10px] text-text-muted font-mono">
                            (Attempt {evalTransparency.job.attempts_count} / {evalTransparency.job.max_attempts})
                          </span>
                        )}
                      </div>

                      <div className="flex items-center gap-2 text-[10px] text-text-muted font-mono">
                        {evalTransparency.job?.completed_at && (
                          <span>Completed: {new Date(evalTransparency.job.completed_at).toLocaleString()}</span>
                        )}
                        {evalTransparency.job?.started_at && !evalTransparency.job.completed_at && (
                          <span>Started: {new Date(evalTransparency.job.started_at).toLocaleTimeString()}</span>
                        )}
                      </div>
                    </div>

                    {/* Provenance chips: Rubric & Snapshot */}
                    <div className="flex items-center gap-2 flex-wrap pt-2 border-t border-surface-border/60 text-[11px]">
                      {evalTransparency.rubric && (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-md bg-surface border border-surface-border text-text-secondary">
                          <Scale className="w-3 h-3 text-primary" />
                          <span>{evalTransparency.rubric.rubric_name} (v{evalTransparency.rubric.version_number})</span>
                        </span>
                      )}
                      {evalTransparency.snapshot && (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-md bg-surface border border-surface-border text-text-secondary font-mono">
                          <GitCommit className="w-3 h-3 text-primary" />
                          <code>{evalTransparency.snapshot.commit_sha.slice(0, 7)}</code>
                          <span className="text-text-muted">
                            ({evalTransparency.snapshot.file_count} files, {Math.round(evalTransparency.snapshot.total_bytes / 1024)} KB)
                          </span>
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Running / Queued State */}
                  {(evalTransparency.job?.status === 'queued' || evalTransparency.job?.status === 'running') && (
                    <div className="p-4 bg-primary/5 border border-primary/20 rounded-xl space-y-3">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2 text-primary font-semibold text-xs">
                          <RefreshCw className="w-4 h-4 animate-spin" />
                          <span>
                            {evalTransparency.job.status === 'queued'
                              ? 'Evaluation queued in transactional outbox...'
                              : `Worker pipeline active: stage "${evalTransparency.job.current_stage || 'processing'}"`}
                          </span>
                        </div>
                        <button
                          type="button"
                          onClick={() => handleOpenEvaluationModal(evalSub, evalTransparency.job?.id)}
                          className="px-2.5 py-1 text-[11px] font-medium text-text-primary bg-surface hover:bg-surface-elevated border border-surface-border rounded-md transition-colors inline-flex items-center gap-1"
                        >
                          <RefreshCw className="w-3 h-3" />
                          <span>Refresh</span>
                        </button>
                      </div>
                      <p className="text-[11px] text-text-secondary">
                        Scorva worker nodes are analyzing repository commits, indexing evidence citations, and running rubric validation with fenced persistence.
                      </p>
                      <div className="flex items-center justify-end">
                        <button
                          type="button"
                          onClick={() => evalTransparency.job && handleCancelEvaluation(evalTransparency.job.id)}
                          disabled={isCancellingEval || evalTransparency.job?.cancellation_requested}
                          className="px-3 py-1.5 text-xs font-medium text-status-error bg-surface hover:bg-status-error/10 border border-status-error/30 rounded-lg transition-colors disabled:opacity-50"
                        >
                          {evalTransparency.job?.cancellation_requested ? 'Cancellation Requested' : 'Cancel Evaluation'}
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Failed State */}
                  {evalTransparency.job?.status === 'failed' && (
                    <div className="p-4 bg-status-error/10 border border-status-error/30 rounded-xl space-y-2.5">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2 text-status-error font-semibold">
                          <AlertCircle className="w-4 h-4 shrink-0" />
                          <span>Evaluation Failed: {evalTransparency.job.error_code || 'PROCESSING_ERROR'}</span>
                        </div>
                        {evalTransparency.job.is_retryable && (
                          <span className="text-[10px] px-2 py-0.5 rounded bg-status-warning/20 text-status-warning font-medium">
                            Retry Eligible
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-text-secondary">
                        {evalTransparency.job.error_message || 'Evaluation encountered an unclassified error.'}
                      </p>
                      <div className="pt-2 flex items-center justify-end">
                        <button
                          type="button"
                          onClick={() => handleTriggerEvaluation(evalSub.id)}
                          disabled={isTriggeringEval}
                          className="px-3 py-1.5 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg transition-colors inline-flex items-center gap-1"
                        >
                          <RefreshCw className={`w-3.5 h-3.5 ${isTriggeringEval ? 'animate-spin' : ''}`} />
                          <span>Retry Evaluation</span>
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Cancelled State */}
                  {evalTransparency.job?.status === 'cancelled' && (
                    <div className="p-4 bg-surface-elevated border border-surface-border rounded-xl space-y-2">
                      <div className="flex items-center gap-2 text-text-muted font-semibold">
                        <AlertCircle className="w-4 h-4" />
                        <span>Evaluation Cancelled</span>
                      </div>
                      <p className="text-xs text-text-secondary">
                        This evaluation job was cancelled before terminal completion. Historical records remain preserved.
                      </p>
                      <div className="pt-2 flex items-center justify-end">
                        <button
                          type="button"
                          onClick={() => handleTriggerEvaluation(evalSub.id)}
                          disabled={isTriggeringEval}
                          className="px-3 py-1.5 text-xs font-semibold text-white bg-primary hover:bg-primary-hover disabled:opacity-50 rounded-lg transition-colors inline-flex items-center gap-1"
                        >
                          <Play className="w-3.5 h-3.5" />
                          <span>Start New Evaluation</span>
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Completed State with Authoritative Result */}
                  {evalTransparency.job?.status === 'completed' && evalTransparency.result && (
                    <div className="space-y-4">
                      {/* Overall Score Hero Card */}
                      <div className="p-5 bg-surface-elevated rounded-xl border border-surface-border space-y-3">
                        <div className="flex items-start justify-between gap-4">
                          <div className="space-y-1">
                            <span className="text-[10px] uppercase font-semibold text-text-muted tracking-wider">
                              Overall AI Assessment
                            </span>
                            <div className="flex items-baseline gap-2">
                              <span className="text-3xl font-extrabold text-primary font-mono">
                                {evalTransparency.result.normalized_score}
                              </span>
                              <span className="text-sm font-semibold text-text-muted">/ 100</span>
                              <span className="text-xs text-text-muted ml-2 font-mono">
                                (Raw: {evalTransparency.result.raw_score})
                              </span>
                            </div>
                          </div>

                          <div className="text-right text-[10px] text-text-muted font-mono space-y-0.5">
                            <div>Model: <strong className="text-text-secondary">{evalTransparency.result.model_name}</strong></div>
                            <div>Provider: <strong className="text-text-secondary">{evalTransparency.result.model_provider}</strong></div>
                            <div>Prompt: <strong className="text-text-secondary">{evalTransparency.result.prompt_version}</strong></div>
                          </div>
                        </div>

                        {/* Summary Assessment Text */}
                        <div className="p-3 bg-surface rounded-lg border border-surface-border text-xs text-text-secondary leading-relaxed whitespace-pre-wrap">
                          {evalTransparency.result.summary_assessment}
                        </div>

                        {/* Insufficient Evidence Warning Banner */}
                        {evalTransparency.result.has_insufficient_evidence && (
                          <div className="p-3 bg-status-warning/10 border border-status-warning/30 rounded-lg flex items-center gap-2 text-status-warning text-xs">
                            <AlertCircle className="w-4 h-4 shrink-0" />
                            <span>
                              <strong>Evidence Warning:</strong> The evaluation model noted insufficient evidence in the repository for one or more criteria.
                            </span>
                          </div>
                        )}
                      </div>

                      {/* Criterion-by-Criterion Score & Evidence Cards */}
                      <div className="space-y-3">
                        <h4 className="text-xs font-semibold text-text-primary uppercase tracking-wider flex items-center gap-1.5">
                          <Award className="w-3.5 h-3.5 text-primary" />
                          <span>Criterion Assessments & Verifiable Evidence</span>
                        </h4>

                        {evalTransparency.result.criterion_scores.map((cs) => (
                          <div
                            key={cs.id}
                            className="p-4 bg-surface rounded-xl border border-surface-border space-y-3"
                          >
                            <div className="flex items-start justify-between gap-4">
                              <div className="space-y-0.5 min-w-0">
                                <div className="flex items-center gap-2 flex-wrap">
                                  <h5 className="font-bold text-xs text-text-primary">{cs.title}</h5>
                                  <span className={`px-2 py-0.5 rounded text-[10px] font-medium border ${
                                    cs.evidence_status === 'verified'
                                      ? 'bg-status-success/10 text-status-success border-status-success/30'
                                      : cs.evidence_status === 'partial'
                                      ? 'bg-status-warning/10 text-status-warning border-status-warning/30'
                                      : 'bg-status-error/10 text-status-error border-status-error/30'
                                  }`}>
                                    {cs.evidence_status === 'verified' ? 'Verified in Snapshot' : cs.evidence_status === 'partial' ? 'Partial Evidence' : 'Missing Evidence'}
                                  </span>
                                </div>
                                <p className="text-[11px] text-text-muted">{cs.description}</p>
                              </div>

                              <div className="text-right shrink-0">
                                <div className="text-sm font-bold text-primary font-mono">
                                  {cs.awarded_score} <span className="text-[10px] text-text-muted font-normal">/ {cs.max_score}</span>
                                </div>
                                <span className="text-[10px] text-text-muted block font-mono">
                                  Weight: {Math.round(Number(cs.weight) * 100)}%
                                </span>
                              </div>
                            </div>

                            {/* Rationale */}
                            <div className="p-3 bg-surface-elevated rounded-lg text-xs text-text-secondary leading-relaxed">
                              <strong className="text-text-primary text-[11px] block mb-1">Evaluator Rationale:</strong>
                              {cs.rationale}
                            </div>

                            {/* Evidence References */}
                            {cs.evidence_references && cs.evidence_references.length > 0 ? (
                              <div className="space-y-2 pt-1">
                                <span className="text-[10px] uppercase font-semibold text-text-muted tracking-wider block">
                                  Grounded Citations ({cs.evidence_references.length})
                                </span>
                                <div className="space-y-2">
                                  {cs.evidence_references.map((ev) => (
                                    <div
                                      key={ev.id}
                                      className="p-2.5 bg-black/40 rounded-lg border border-surface-border font-mono text-[11px] space-y-1.5"
                                    >
                                      <div className="flex items-center justify-between text-text-muted text-[10px]">
                                        <span className="text-primary font-semibold flex items-center gap-1">
                                          <FileCode className="w-3 h-3" />
                                          {ev.file_path}
                                          {ev.start_line !== null && ev.start_line !== undefined && (
                                            <span>:{ev.start_line}{ev.end_line ? `-${ev.end_line}` : ''}</span>
                                          )}
                                        </span>
                                        {ev.is_verified_in_repo ? (
                                          <span className="text-status-success inline-flex items-center gap-0.5">
                                            <CheckCircle2 className="w-3 h-3" /> Verified in Repo
                                          </span>
                                        ) : (
                                          <span className="text-status-warning inline-flex items-center gap-0.5" title={ev.verification_failure_reason || ''}>
                                            <AlertCircle className="w-3 h-3" /> Unverified
                                          </span>
                                        )}
                                      </div>
                                      <pre className="text-text-primary text-[11px] overflow-x-auto whitespace-pre p-2 bg-black/50 rounded border border-white/5 font-mono">
                                        {ev.snippet}
                                      </pre>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            ) : (
                              <div className="text-[11px] text-text-muted italic px-2 py-1 bg-surface-elevated/40 rounded border border-dashed border-surface-border">
                                No specific line citations were extracted for this criterion.
                              </div>
                            )}
                          </div>
                        ))}
                      </div>

                      {/* Prior Evaluation Runs Section (Re-evaluation History) */}
                      {evalTransparency.prior_runs && evalTransparency.prior_runs.length > 0 && (
                        <div className="pt-3 border-t border-surface-border space-y-2">
                          <span className="text-[10px] uppercase font-semibold text-text-muted tracking-wider block">
                            Prior Evaluation Runs (Audit Trail)
                          </span>
                          <div className="space-y-1.5">
                            {evalTransparency.prior_runs.map((pr) => (
                              <div
                                key={pr.job_id}
                                className="p-2.5 bg-surface-elevated/60 rounded-lg border border-surface-border text-xs flex items-center justify-between"
                              >
                                <div className="flex items-center gap-2">
                                  <span className="text-[11px] font-mono text-text-muted">
                                    {new Date(pr.created_at).toLocaleDateString()} {new Date(pr.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                  </span>
                                  <StatusBadge status={pr.status} size="sm" />
                                </div>
                                <div className="flex items-center gap-3">
                                  {pr.normalized_score !== null && pr.normalized_score !== undefined && (
                                    <span className="font-mono font-bold text-text-primary">
                                      Score: {pr.normalized_score} / 100
                                    </span>
                                  )}
                                  <button
                                    type="button"
                                    onClick={() => handleOpenEvaluationModal(evalSub, pr.job_id)}
                                    className="text-[11px] text-primary hover:underline font-medium"
                                  >
                                    View Run
                                  </button>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="p-4 border-t border-surface-border flex items-center justify-between shrink-0 bg-surface-elevated/30">
              <div className="text-[11px] text-text-muted">
                {evalTransparency?.has_evaluation && evalTransparency.job?.status === 'completed' ? (
                  <span className="text-text-muted">Human judges make the final decisions. Scorva makes the process transparent.</span>
                ) : (
                  <span>Automated asynchronous evaluation engine.</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                {evalTransparency?.has_evaluation && (evalTransparency.job?.status === 'completed' || evalTransparency.job?.status === 'failed') && (
                  <button
                    type="button"
                    onClick={() => handleTriggerEvaluation(evalSub.id)}
                    disabled={isTriggeringEval}
                    className="px-3.5 py-1.5 text-xs font-semibold text-text-primary bg-surface-elevated hover:bg-surface-hover border border-surface-border rounded-lg transition-colors inline-flex items-center gap-1.5 disabled:opacity-50"
                  >
                    <RefreshCw className={`w-3 h-3 ${isTriggeringEval ? 'animate-spin' : ''}`} />
                    <span>{isTriggeringEval ? 'Dispatching...' : 'Re-evaluate'}</span>
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setIsEvalModalOpen(false)}
                  className="px-4 py-1.5 text-xs font-semibold text-white bg-primary hover:bg-primary-hover rounded-lg transition-colors shadow-sm"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
