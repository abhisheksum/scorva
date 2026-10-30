'use client';

import React, { useState, useEffect } from 'react';
import {
  LifeBuoy,
  PlusCircle,
  MessageSquare,
  Clock,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  Send,
  ArrowLeft,
  ShieldCheck,
  User,
  Paperclip,
} from 'lucide-react';
import { api, ApiClientError } from '@/lib/api-client';
import {
  SupportTicketItem,
  SupportTicketDetailResponse,
  ParticipantTeamItem,
} from '@/types/api';

export default function ParticipantSupportPage() {
  const [activeTab, setActiveTab] = useState<'list' | 'new'>('list');
  const [tickets, setTickets] = useState<SupportTicketItem[]>([]);
  const [teams, setTeams] = useState<ParticipantTeamItem[]>([]);
  const [selectedTicketId, setSelectedTicketId] = useState<string | null>(null);
  const [ticketDetail, setTicketDetail] = useState<SupportTicketDetailResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form states
  const [category, setCategory] = useState('Technical / Repository Issue');
  const [subject, setSubject] = useState('');
  const [description, setDescription] = useState('');
  const [hackathonId, setHackathonId] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Reply state
  const [replyMessage, setReplyMessage] = useState('');
  const [isSendingReply, setIsSendingReply] = useState(false);

  const fetchTickets = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [ticketList, teamList] = await Promise.all([
        api.getParticipantSupportTickets(),
        api.getParticipantTeams(),
      ]);
      setTickets(ticketList);
      setTeams(teamList);
      if (teamList.length > 0) {
        setHackathonId(teamList[0].hackathon_id);
      }
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError('Failed to load support tickets.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchTickets();
  }, []);

  const fetchTicketDetail = async (ticketId: string) => {
    setSelectedTicketId(ticketId);
    setIsDetailLoading(true);
    try {
      const res = await api.getParticipantSupportTicketDetail(ticketId);
      setTicketDetail(res);
    } catch (err) {
      console.error('Failed to load ticket detail', err);
    } finally {
      setIsDetailLoading(false);
    }
  };

  const handleCreateTicket = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!subject.trim() || subject.length < 3) {
      setFormError('Subject must be at least 3 characters.');
      return;
    }
    if (!description.trim() || description.length < 10) {
      setFormError('Please provide more description (at least 10 characters).');
      return;
    }

    setIsSubmitting(true);
    setFormError(null);
    try {
      const newTicket = await api.createParticipantSupportTicket({
        category,
        subject: subject.trim(),
        description: description.trim(),
        hackathon_id: hackathonId || undefined,
      });

      // Clear form
      setSubject('');
      setDescription('');
      // Refresh tickets list and switch to detail
      await fetchTickets();
      fetchTicketDetail(newTicket.id);
      setActiveTab('list');
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setFormError(err.message);
      } else {
        setFormError('Failed to create ticket. Please try again.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSendReply = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedTicketId || !replyMessage.trim()) return;

    setIsSendingReply(true);
    try {
      const newReply = await api.replyParticipantSupportTicket(selectedTicketId, {
        message: replyMessage.trim(),
      });
      setTicketDetail((prev) =>
        prev ? { ...prev, replies: [...prev.replies, newReply] } : null
      );
      setReplyMessage('');
      // Also update ticket list reply count
      setTickets((prev) =>
        prev.map((t) =>
          t.id === selectedTicketId
            ? { ...t, replies_count: t.replies_count + 1, updated_at: new Date().toISOString() }
            : t
        )
      );
    } catch (err) {
      console.error('Failed to post reply', err);
    } finally {
      setIsSendingReply(false);
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'resolved':
      case 'closed':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-[#F0FDF4] text-[#16A34A] border border-[#BBF7D0]">
            <CheckCircle2 className="w-3 h-3" />
            Resolved
          </span>
        );
      case 'in_progress':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-[#EFF6FF] text-[#2563EB] border border-[#BFDBFE]">
            <Clock className="w-3 h-3" />
            In Progress
          </span>
        );
      case 'waiting_response':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-[#FEF3C7] text-[#D97706] border border-[#FDE68A]">
            Awaiting Staff
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-[#F8FAFC] text-[#64748B] border border-[#E2E8F0]">
            Open
          </span>
        );
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4 shadow-xs">
        <div>
          <div className="flex items-center gap-2 mb-1 text-xs font-semibold uppercase tracking-wider text-[#2563EB]">
            <LifeBuoy className="w-4 h-4" />
            Participant Help Desk
          </div>
          <h1 className="text-xl sm:text-2xl font-bold text-[#111827]">
            Support & Help Center
          </h1>
          <p className="text-xs text-[#64748B] mt-1">
            Need help with your repository, evaluation feedback, team roster, or platform tools? Contact hackathon organizers directly.
          </p>
        </div>

        {/* Tab Switcher */}
        {!selectedTicketId && (
          <div className="flex items-center bg-[#F8FAFC] p-1 rounded-lg border border-[#E2E8F0] shrink-0">
            <button
              onClick={() => {
                setActiveTab('list');
                setSelectedTicketId(null);
              }}
              className={`px-3.5 py-1.5 rounded-md text-xs font-medium transition-all ${
                activeTab === 'list'
                  ? 'bg-white text-[#111827] shadow-2xs font-semibold'
                  : 'text-[#64748B] hover:text-[#111827]'
              }`}
            >
              My Requests ({tickets.length})
            </button>
            <button
              onClick={() => {
                setActiveTab('new');
                setSelectedTicketId(null);
              }}
              className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-md text-xs font-medium transition-all ${
                activeTab === 'new'
                  ? 'bg-white text-[#111827] shadow-2xs font-semibold'
                  : 'text-[#64748B] hover:text-[#111827]'
              }`}
            >
              <PlusCircle className="w-3.5 h-3.5" />
              New Request
            </button>
          </div>
        )}
      </div>

      {/* Main Content Area */}
      {selectedTicketId ? (
        /* Ticket Detail & Conversation View */
        <div className="space-y-6">
          <button
            onClick={() => {
              setSelectedTicketId(null);
              setTicketDetail(null);
            }}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#2563EB] hover:underline"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to All Requests
          </button>

          {isDetailLoading || !ticketDetail ? (
            <div className="bg-white border border-[#E2E8F0] rounded-xl p-16 flex flex-col items-center justify-center text-center shadow-xs">
              <RefreshCw className="w-8 h-8 text-[#2563EB] animate-spin mb-3" />
              <p className="text-sm font-semibold text-[#111827]">Loading conversation thread...</p>
            </div>
          ) : (
            <div className="space-y-6">
              {/* Ticket Overview Card */}
              <div className="bg-white border border-[#E2E8F0] rounded-xl p-6 shadow-xs space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-[#E2E8F0] gap-3">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-mono text-xs font-bold text-[#2563EB] bg-[#EFF6FF] px-2 py-0.5 rounded border border-[#BFDBFE]">
                        {ticketDetail.ticket.ticket_number}
                      </span>
                      <span className="text-xs text-[#64748B]">
                        {ticketDetail.ticket.category}
                      </span>
                    </div>
                    <h2 className="text-lg font-bold text-[#111827]">
                      {ticketDetail.ticket.subject}
                    </h2>
                  </div>
                  <div className="shrink-0">{getStatusBadge(ticketDetail.ticket.status)}</div>
                </div>

                <div className="p-4 rounded-lg bg-[#F8FAFC] border border-[#E2E8F0] space-y-2">
                  <div className="flex items-center justify-between text-xs text-[#64748B]">
                    <span className="font-semibold text-[#111827]">Initial Description</span>
                    <span>{new Date(ticketDetail.ticket.created_at).toLocaleString()}</span>
                  </div>
                  <p className="text-xs text-[#334155] leading-relaxed whitespace-pre-line">
                    {ticketDetail.ticket.description}
                  </p>
                </div>
              </div>

              {/* Replies Thread */}
              <div className="bg-white border border-[#E2E8F0] rounded-xl p-6 shadow-xs space-y-5">
                <div className="flex items-center justify-between pb-3 border-b border-[#E2E8F0]">
                  <h3 className="text-sm font-bold text-[#111827]">
                    Conversation Thread ({ticketDetail.replies.length} replies)
                  </h3>
                </div>

                {ticketDetail.replies.length === 0 ? (
                  <p className="text-xs text-[#64748B] py-6 text-center">
                    No replies yet. An organizer or support member will respond shortly.
                  </p>
                ) : (
                  <div className="space-y-4">
                    {ticketDetail.replies.map((reply) => (
                      <div
                        key={reply.id}
                        className={`p-4 rounded-xl border ${
                          reply.is_staff
                            ? 'bg-[#EFF6FF] border-[#BFDBFE] ml-4 sm:ml-8'
                            : 'bg-[#F8FAFC] border-[#E2E8F0] mr-4 sm:mr-8'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            {reply.is_staff ? (
                              <div className="w-6 h-6 rounded-full bg-[#2563EB] text-white flex items-center justify-center text-[10px] font-bold">
                                <ShieldCheck className="w-3.5 h-3.5" />
                              </div>
                            ) : (
                              <div className="w-6 h-6 rounded-full bg-[#E2E8F0] text-[#475569] flex items-center justify-center text-[10px] font-bold">
                                <User className="w-3.5 h-3.5" />
                              </div>
                            )}
                            <span className="text-xs font-bold text-[#111827]">
                              {reply.author_name}
                            </span>
                            {reply.is_staff && (
                              <span className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full bg-[#2563EB] text-white">
                                Organizer Staff
                              </span>
                            )}
                          </div>
                          <span className="text-[10px] text-[#64748B]">
                            {new Date(reply.created_at).toLocaleString()}
                          </span>
                        </div>
                        <p className="text-xs text-[#334155] leading-relaxed whitespace-pre-line pl-8">
                          {reply.message}
                        </p>
                      </div>
                    ))}
                  </div>
                )}

                {/* Reply Form */}
                <form onSubmit={handleSendReply} className="pt-4 border-t border-[#E2E8F0] space-y-3">
                  <label htmlFor="reply-input" className="block text-xs font-semibold text-[#111827]">
                    Add a follow-up reply
                  </label>
                  <textarea
                    id="reply-input"
                    rows={3}
                    value={replyMessage}
                    onChange={(e) => setReplyMessage(e.target.value)}
                    placeholder="Type your reply to the organizer here..."
                    className="w-full px-3 py-2 text-xs rounded-lg border border-[#E2E8F0] focus:outline-none focus:ring-2 focus:ring-[#2563EB]"
                  />
                  <div className="flex justify-end">
                    <button
                      type="submit"
                      disabled={isSendingReply || !replyMessage.trim()}
                      className="inline-flex items-center gap-1.5 px-4 py-2 bg-[#2563EB] text-white text-xs font-semibold rounded-lg hover:bg-[#1D4ED8] transition-colors disabled:opacity-50"
                    >
                      <Send className="w-3.5 h-3.5" />
                      <span>{isSendingReply ? 'Sending...' : 'Send Reply'}</span>
                    </button>
                  </div>
                </form>
              </div>
            </div>
          )}
        </div>
      ) : activeTab === 'new' ? (
        /* Create New Ticket Form */
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-6 sm:p-8 max-w-2xl mx-auto shadow-xs">
          <h2 className="text-lg font-bold text-[#111827] mb-1">Submit a Support Request</h2>
          <p className="text-xs text-[#64748B] mb-6">
            Describe your inquiry clearly so our team can help you resolve it quickly.
          </p>

          {formError && (
            <div className="mb-5 p-3 rounded-lg bg-[#FEF2F2] border border-[#FECACA] flex items-center gap-2 text-xs text-[#DC2626]">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{formError}</span>
            </div>
          )}

          <form onSubmit={handleCreateTicket} className="space-y-4">
            <div>
              <label htmlFor="req-category" className="block text-xs font-semibold text-[#111827] mb-1">
                Category
              </label>
              <select
                id="req-category"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="w-full px-3 py-2 text-xs rounded-lg bg-white border border-[#E2E8F0] text-[#111827] focus:outline-none focus:ring-2 focus:ring-[#2563EB]"
              >
                <option value="Technical / Repository Issue">Technical / Repository Issue</option>
                <option value="Judging & Evaluation Inquiry">Judging & Evaluation Inquiry</option>
                <option value="Team & Registration">Team & Registration</option>
                <option value="Platform Bug">Platform Bug</option>
                <option value="General Inquiry">General Inquiry</option>
              </select>
            </div>

            {teams.length > 1 && (
              <div>
                <label htmlFor="req-hackathon" className="block text-xs font-semibold text-[#111827] mb-1">
                  Related Hackathon
                </label>
                <select
                  id="req-hackathon"
                  value={hackathonId}
                  onChange={(e) => setHackathonId(e.target.value)}
                  className="w-full px-3 py-2 text-xs rounded-lg bg-white border border-[#E2E8F0] text-[#111827] focus:outline-none focus:ring-2 focus:ring-[#2563EB]"
                >
                  {teams.map((t) => (
                    <option key={t.hackathon_id} value={t.hackathon_id}>
                      {t.hackathon_title}
                    </option>
                  ))}
                </select>
              </div>
            )}

            <div>
              <label htmlFor="req-subject" className="block text-xs font-semibold text-[#111827] mb-1">
                Subject
              </label>
              <input
                id="req-subject"
                type="text"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder="e.g. Cannot trigger automated code evaluation for commit 7c8f"
                className="w-full px-3 py-2 text-xs rounded-lg border border-[#E2E8F0] focus:outline-none focus:ring-2 focus:ring-[#2563EB]"
              />
            </div>

            <div>
              <label htmlFor="req-description" className="block text-xs font-semibold text-[#111827] mb-1">
                Detailed Description
              </label>
              <textarea
                id="req-description"
                rows={5}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Include relevant details, error messages, repository branch, or step-by-step notes..."
                className="w-full px-3 py-2 text-xs rounded-lg border border-[#E2E8F0] focus:outline-none focus:ring-2 focus:ring-[#2563EB]"
              />
            </div>

            <div className="pt-3 flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => setActiveTab('list')}
                className="px-4 py-2 text-xs font-medium text-[#64748B] hover:text-[#111827] rounded-lg hover:bg-[#F8FAFC] transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isSubmitting}
                className="inline-flex items-center gap-2 px-5 py-2 bg-[#2563EB] text-white text-xs font-semibold rounded-lg hover:bg-[#1D4ED8] transition-colors disabled:opacity-50"
              >
                <Send className="w-3.5 h-3.5" />
                <span>{isSubmitting ? 'Submitting...' : 'Submit Request'}</span>
              </button>
            </div>
          </form>
        </div>
      ) : (
        /* Requests List View */
        <div>
          {isLoading ? (
            <div className="bg-white border border-[#E2E8F0] rounded-xl p-16 flex flex-col items-center justify-center text-center shadow-xs">
              <RefreshCw className="w-8 h-8 text-[#2563EB] animate-spin mb-3" />
              <p className="text-sm font-semibold text-[#111827]">Loading your support tickets...</p>
            </div>
          ) : error ? (
            <div className="bg-white border border-[#E2E8F0] rounded-xl p-8 text-center max-w-lg mx-auto shadow-xs">
              <AlertCircle className="w-10 h-10 text-[#DC2626] mx-auto mb-3" />
              <h3 className="text-sm font-semibold text-[#111827]">Failed to load tickets</h3>
              <p className="text-xs text-[#64748B] mt-1">{error}</p>
            </div>
          ) : tickets.length === 0 ? (
            <div className="bg-white border border-[#E2E8F0] rounded-xl p-12 text-center max-w-xl mx-auto shadow-xs space-y-3">
              <LifeBuoy className="w-10 h-10 text-[#94A3B8] mx-auto mb-2" />
              <h3 className="text-base font-bold text-[#111827]">No support requests yet</h3>
              <p className="text-xs text-[#64748B]">
                Have a question or running into an issue during the hackathon? Create a ticket and the organizing team will assist you.
              </p>
              <button
                onClick={() => setActiveTab('new')}
                className="inline-flex items-center gap-1.5 px-4 py-2 mt-2 bg-[#2563EB] text-white text-xs font-semibold rounded-lg hover:bg-[#1D4ED8] transition-colors"
              >
                <PlusCircle className="w-3.5 h-3.5" />
                Create First Ticket
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              {tickets.map((ticket) => (
                <div
                  key={ticket.id}
                  onClick={() => fetchTicketDetail(ticket.id)}
                  className="bg-white border border-[#E2E8F0] hover:border-[#BFDBFE] rounded-xl p-5 shadow-xs transition-all cursor-pointer flex flex-col sm:flex-row sm:items-center justify-between gap-4"
                >
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-2.5">
                      <span className="font-mono text-xs font-bold text-[#2563EB] bg-[#EFF6FF] px-2 py-0.5 rounded border border-[#BFDBFE]">
                        {ticket.ticket_number}
                      </span>
                      <span className="text-xs font-semibold text-[#111827]">{ticket.subject}</span>
                      {getStatusBadge(ticket.status)}
                    </div>
                    <p className="text-xs text-[#64748B] line-clamp-1">{ticket.description}</p>
                    <div className="flex items-center gap-3 text-[11px] text-[#94A3B8] pt-0.5">
                      <span>Category: {ticket.category}</span>
                      {ticket.hackathon_title && <span>• {ticket.hackathon_title}</span>}
                      <span>• Created {new Date(ticket.created_at).toLocaleDateString()}</span>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 shrink-0 self-end sm:self-center">
                    <div className="flex items-center gap-1.5 text-xs text-[#64748B]">
                      <MessageSquare className="w-3.5 h-3.5 text-[#2563EB]" />
                      <span>{ticket.replies_count} {ticket.replies_count === 1 ? 'reply' : 'replies'}</span>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        fetchTicketDetail(ticket.id);
                      }}
                      className="px-3 py-1.5 text-xs font-semibold text-[#2563EB] hover:bg-[#EFF6FF] rounded-lg transition-colors"
                    >
                      View
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
