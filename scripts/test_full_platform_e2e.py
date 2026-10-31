#!/usr/bin/env python3
"""
Scorva — Full Platform Production Readiness & End-to-End Integration Test Suite

Covers the complete 4-stage lifecycle across all 3 personas:
  Stage 1: Organizer manages hackathon, rubric, teams, submissions, and judge assignments
  Stage 2: Participant accesses hackathon, team, repository submission, and tasks
  Stage 3: Judge reviews assigned project, saves draft, submits final review (independent scoring)
  Stage 4: Organizer officially publishes results; Participant accesses final score, criteria, feedback, and leaderboard
  Stage 5: Security, boundary, privacy, and support ticket integration verification
"""

import sys
import uuid
import asyncio
import requests
from sqlalchemy import text
from apps.api.core.database import AsyncSessionLocal

BASE_URL = "http://localhost:8000"

async def _reset_review_for_idempotency(sub_id: str, judge_uid: str):
    async with AsyncSessionLocal() as db:
        await db.execute(text("""
            DELETE FROM judge_criterion_scores 
            WHERE judge_review_id IN (
                SELECT id FROM judge_reviews 
                WHERE submission_id = :sid AND judge_user_id = :jid
            )
        """), {"sid": sub_id, "jid": judge_uid})
        await db.execute(text("""
            DELETE FROM judge_reviews 
            WHERE submission_id = :sid AND judge_user_id = :jid
        """), {"sid": sub_id, "jid": judge_uid})
        await db.commit()

def log_section(title: str):
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)

def run_e2e_journey():
    session_org = requests.Session()
    session_judge = requests.Session()
    session_part = requests.Session()
    session_unauth = requests.Session()

    for s in (session_org, session_judge, session_part, session_unauth):
        s.headers.update({"Origin": "http://localhost:3000"})

    # -------------------------------------------------------------
    # STAGE 1: ORGANIZER WORKSPACE
    # -------------------------------------------------------------
    log_section("STAGE 1: ORGANIZER LOGS IN & MANAGES HACKATHON")
    resp = session_org.post(f"{BASE_URL}/api/v1/auth/login", json={
        "email": "organizer@scorva.io",
        "password": "Password123!"
    })
    assert resp.status_code == 200, f"Organizer login failed: {resp.text}"
    org_user = resp.json()["user"]
    org_dest = org_user["routing"]["default_destination"]
    print(f"✅ Organizer logged in: {org_user['email']} (Routing: {org_dest})")
    
    # Extract Organization ID
    org_id = org_dest.split("/")[-1]
    print(f"   Target Organization ID: {org_id}")

    # 1.1 List Hackathons
    resp = session_org.get(f"{BASE_URL}/api/v1/organizations/{org_id}/hackathons")
    assert resp.status_code == 200, f"Failed to list hackathons: {resp.text}"
    hacks = resp.json()["items"]
    assert len(hacks) > 0, "Expected at least 1 hackathon for organizer"
    target_hack = next((h for h in hacks if h["title"] == "Autumn AI Cup 2026"), hacks[0])
    hackathon_id = target_hack["id"]
    print(f"✅ Verified Hackathon: '{target_hack['title']}' (ID: {hackathon_id}, Status: {target_hack['status']})")

    # 1.2 Verify Hackathon Detail & Overview
    resp = session_org.get(f"{BASE_URL}/api/v1/organizations/{org_id}/hackathons/{hackathon_id}")
    assert resp.status_code == 200, f"Failed to get hackathon details: {resp.text}"
    h_detail = resp.json()
    print(f"   Timeline: Start={h_detail['start_date']}, Deadline={h_detail['submission_deadline']}")

    # 1.3 Verify Teams & Participants
    resp = session_org.get(f"{BASE_URL}/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/teams")
    assert resp.status_code == 200, f"Failed to list teams: {resp.text}"
    teams = resp.json()
    print(f"✅ Verified Registered Teams: {len(teams)} teams found")
    assert any(t["name"] == "Team Quantum" for t in teams), "Expected 'Team Quantum' to be enrolled"

    # 1.4 Verify Published Scoring Rubric
    resp = session_org.get(f"{BASE_URL}/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/rubric")
    assert resp.status_code == 200, f"Failed to get rubric: {resp.text}"
    rubric = resp.json()
    active_v = rubric.get("active_version")
    assert active_v is not None and active_v.get("status") == "published", "Rubric active version must be published"
    criteria = active_v["criteria"]
    print(f"✅ Verified Published Rubric: {len(criteria)} criteria (Frozen weights)")
    for c in criteria:
        print(f"   - {c['title']} (Weight: {c['weight']}, Max: {c['max_score']})")

    # 1.5 Verify Assigned Judges
    resp = session_org.get(f"{BASE_URL}/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/judges")
    assert resp.status_code == 200, f"Failed to get judges: {resp.text}"
    judges = resp.json()
    print(f"✅ Verified Assigned Judges: {len(judges)} judges assigned")
    assert any(j["user_email"] == "judge@scorva.io" for j in judges), "Expected judge@scorva.io to be assigned"

    # 1.6 Verify Submitted Projects
    resp = session_org.get(f"{BASE_URL}/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/submissions")
    assert resp.status_code == 200, f"Failed to get submissions: {resp.text}"
    submissions = resp.json()
    print(f"✅ Verified Submissions: {len(submissions)} projects submitted")
    quantum_sub = next((s for s in submissions if s["team_name"] == "Team Quantum"), None)
    assert quantum_sub is not None, "Expected submission from Team Quantum"
    submission_id = quantum_sub["id"]
    print(f"   Target Participant Submission: '{quantum_sub['title']}' (ID: {submission_id})")

    # Ensure Results are UNPUBLISHED initially to verify privacy gating
    session_org.post(f"{BASE_URL}/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/unpublish-results")

    # -------------------------------------------------------------
    # STAGE 2: PARTICIPANT WORKSPACE (PRE-PUBLICATION)
    # -------------------------------------------------------------
    log_section("STAGE 2: PARTICIPANT LOGS IN & VERIFIES PRE-PUBLICATION GATING")
    resp = session_part.post(f"{BASE_URL}/api/v1/auth/login", json={
        "email": "participant@scorva.io",
        "password": "Password123!"
    })
    assert resp.status_code == 200, f"Participant login failed: {resp.text}"
    part_user = resp.json()["user"]
    assert part_user["routing"]["default_destination"] == "/participant"
    print(f"✅ Participant logged in: {part_user['email']}")

    # 2.1 Complete registration intake if pending
    reg_status = session_part.get(f"{BASE_URL}/api/v1/participant/registration-status").json()
    if not reg_status.get("is_registered"):
        session_part.post(f"{BASE_URL}/api/v1/participant/register-project", json={
            "team_name": "Team Quantum",
            "team_number": "TQ-99",
            "github_repo_url": "https://github.com/scorva/quantum-agent",
            "project_title": "Quantum AI Distributed Engine",
            "project_description": "Production autonomous multi-agent scoring and execution harness.",
            "agreement_confirmed": True,
            "team_members": [{"full_name": "Test Administrator", "email": "participant@scorva.io"}]
        })
        print("   Intake form submitted and agreement confirmed.")

    # 2.2 Verify Participant Team & Submissions
    resp = session_part.get(f"{BASE_URL}/api/v1/participant/teams")
    assert resp.status_code == 200
    my_teams = resp.json()
    assert len(my_teams) > 0
    print(f"✅ Verified Enrolled Team: {my_teams[0]['team_name']} in '{my_teams[0]['hackathon_title']}'")
    assert my_teams[0]["submission"] is not None
    print(f"   Project Submission: {my_teams[0]['submission']['title']} (Status: {my_teams[0]['submission']['connection_status']})")

    # 2.3 Verify Tasks and Notifications
    resp = session_part.get(f"{BASE_URL}/api/v1/participant/tasks")
    assert resp.status_code == 200
    tasks = resp.json()
    print(f"✅ Verified Tasks: {len(tasks)} tasks loaded")

    resp = session_part.get(f"{BASE_URL}/api/v1/participant/notifications")
    assert resp.status_code == 200
    notifs = resp.json()
    print(f"✅ Verified Notifications: {len(notifs['notifications'])} in inbox")

    # 2.4 CRITICAL PRIVACY CHECK: Verify Leaderboard is NOT published yet!
    resp = session_part.get(f"{BASE_URL}/api/v1/participant/leaderboard")
    assert resp.status_code == 200
    lb_pre = resp.json()
    assert lb_pre["is_published"] is False, "Privacy Violation: Leaderboard must remain hidden before organizer publication!"
    assert len(lb_pre["entries"]) == 0, "Privacy Violation: Leaderboard entries leaked before publication!"
    print(f"🔒 Verified Privacy Gate: Leaderboard is unpublished. Message: '{lb_pre['message']}'")

    # 2.5 CRITICAL PRIVACY CHECK: Verify Performance score is hidden before publication!
    resp = session_part.get(f"{BASE_URL}/api/v1/participant/performance")
    assert resp.status_code == 200
    perf_pre = resp.json()
    assert perf_pre["final_score"] is None, "Privacy Violation: Final score must remain hidden before publication!"
    assert len(perf_pre["criteria_breakdown"]) == 0, "Privacy Violation: Criteria scores must remain hidden before publication!"
    print("🔒 Verified Privacy Gate: Participant final scores and criteria breakdown are strictly secluded.")

    # -------------------------------------------------------------
    # STAGE 3: JUDGE EVALUATION & INDEPENDENT SCORING
    # -------------------------------------------------------------
    log_section("STAGE 3: JUDGE EVALUATES SUBMISSION & SUBMITS REVIEW")
    resp = session_judge.post(f"{BASE_URL}/api/v1/auth/login", json={
        "email": "judge@scorva.io",
        "password": "Password123!"
    })
    assert resp.status_code == 200, f"Judge login failed: {resp.text}"
    judge_user = resp.json()["user"]
    assert judge_user["routing"]["default_destination"] == "/judge"
    print(f"✅ Judge logged in: {judge_user['email']}")

    # 3.1 Verify Assigned Hackathons
    resp = session_judge.get(f"{BASE_URL}/api/v1/judge/assignments")
    assert resp.status_code == 200
    judge_assignments = resp.json()
    assert any(a["hackathon_id"] == hackathon_id for a in judge_assignments), "Judge must have Autumn AI Cup assignment"
    print(f"✅ Verified Judge Assignment: Assigned to {len(judge_assignments)} hackathon(s)")

    # Reset review state for target submission to ensure complete lifecycle test
    asyncio.run(_reset_review_for_idempotency(submission_id, judge_user["id"]))

    # 3.2 Verify Review Form & Rubric
    resp = session_judge.get(f"{BASE_URL}/api/v1/judge/hackathons/{hackathon_id}/submissions/{submission_id}/review")
    assert resp.status_code == 200
    review_form = resp.json()
    print(f"✅ Loaded Review Form for: '{review_form['submission_title']}'")
    print(f"   AI Assessment Advisory: {'Present' if review_form.get('ai_evaluation') else 'None'}")
    assert len(review_form["rubric_criteria"]) == 2, "Expected 2 published criteria"

    crit1 = review_form["rubric_criteria"][0]
    crit2 = review_form["rubric_criteria"][1]

    # 3.3 Save Review Draft
    draft_payload = {
        "overall_feedback": "Strong architecture, draft notes in progress.",
        "decision": "accepted",
        "criterion_scores": [
            {"criterion_id": crit1["id"], "score": "75.0", "judge_notes": "Solid technical foundation. (CONFIDENTIAL)"},
            {"criterion_id": crit2["id"], "score": "85.0", "judge_notes": "Great innovation concepts. (CONFIDENTIAL)"}
        ]
    }
    resp = session_judge.post(
        f"{BASE_URL}/api/v1/judge/hackathons/{hackathon_id}/submissions/{submission_id}/review",
        json=draft_payload
    )
    assert resp.status_code == 200, f"Failed to save draft: {resp.text}"
    saved_draft = resp.json()
    assert saved_draft["status"] == "draft"
    print(f"✅ Saved Review Draft (Status: {saved_draft['status']}, Score: {saved_draft['score']})")

    # 3.4 Verify Draft Persistence
    resp = session_judge.get(f"{BASE_URL}/api/v1/judge/hackathons/{hackathon_id}/submissions/{submission_id}/review")
    persisted_review = resp.json().get("review")
    assert persisted_review is not None
    assert persisted_review["status"] == "draft"
    assert persisted_review["overall_feedback"] == "Strong architecture, draft notes in progress."
    print("✅ Draft persistence verified on reload.")

    # 3.5 Submit Final Review
    final_payload = {
        "overall_feedback": "Exceptional submission demonstrating robust distributed agent design and reliable execution.",
        "decision": "accepted",
        "criterion_scores": [
            {"criterion_id": crit1["id"], "score": "88.0", "judge_notes": "Evaluated architecture thoroughly: A grade. (CONFIDENTIAL)"},
            {"criterion_id": crit2["id"], "score": "92.0", "judge_notes": "Remarkable novelty and elegance. (CONFIDENTIAL)"}
        ]
    }
    resp = session_judge.post(
        f"{BASE_URL}/api/v1/judge/hackathons/{hackathon_id}/submissions/{submission_id}/review/submit",
        json=final_payload
    )
    assert resp.status_code == 200, f"Failed to submit final review: {resp.text}"
    final_review = resp.json()
    assert final_review["status"] == "submitted"
    # Weighted average: 88 * 0.5 + 92 * 0.5 = 90.0
    expected_score = 90.0
    assert float(final_review["score"]) == expected_score, f"Expected {expected_score}, got {final_review['score']}"
    print(f"✅ Final Review Submitted: Status={final_review['status']}, Score={final_review['score']} / 100.0")

    # 3.6 CRITICAL CHECK: Judge submission MUST NOT automatically publish the leaderboard!
    resp = session_part.get(f"{BASE_URL}/api/v1/participant/leaderboard")
    assert resp.json()["is_published"] is False, "Violation: Judge submitting review must NOT auto-publish leaderboard!"
    print("🔒 Verified: Leaderboard remains unpublished after judge review submission.")

    # -------------------------------------------------------------
    # STAGE 4: ORGANIZER PUBLISHES RESULTS
    # -------------------------------------------------------------
    log_section("STAGE 4: ORGANIZER PUBLISHES OFFICIAL HACKATHON RESULTS")
    # 4.1 Check Review Progress on Organizer Workspace
    resp = session_org.get(f"{BASE_URL}/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/reviews/progress")
    assert resp.status_code == 200
    prog = resp.json()
    print(f"✅ Organizer Review Progress: {prog['submitted_reviews_count']} submitted review(s)")

    # 4.2 Organizer triggers Official Results Publication
    resp = session_org.post(f"{BASE_URL}/api/v1/organizations/{org_id}/hackathons/{hackathon_id}/publish-results")
    assert resp.status_code == 200, f"Failed to publish results: {resp.text}"
    updated_hack = resp.json()
    assert updated_hack["settings"]["results_published"] is True
    print(f"✅ Organizer successfully published official results for '{updated_hack['title']}'!")

    # -------------------------------------------------------------
    # STAGE 5: PARTICIPANT ACCESSES OFFICIAL PUBLISHED RESULTS
    # -------------------------------------------------------------
    log_section("STAGE 5: PARTICIPANT VIEWS PUBLISHED RESULTS & LEADERBOARD")
    # 5.1 Performance breakdown
    resp = session_part.get(f"{BASE_URL}/api/v1/participant/performance")
    assert resp.status_code == 200
    perf_pub = resp.json()
    assert perf_pub["final_score"] is not None, "Final score must now be visible!"
    assert float(perf_pub["final_score"]) == 90.0
    assert len(perf_pub["criteria_breakdown"]) == 2
    assert len(perf_pub["authorized_feedback"]) > 0
    print(f"✅ Participant Final Score: {perf_pub['final_score']} / 100.0 (Status: {perf_pub['evaluation_status']})")
    for cb in perf_pub["criteria_breakdown"]:
        print(f"   - {cb['criterion_name']}: {cb['awarded_score']} / {cb['max_score']} (Weight: {cb['weight']})")
    print(f"   Authorized Judge Feedback: '{perf_pub['authorized_feedback'][0]}'")

    # 5.2 CONFIDENTIALITY CHECK: Verify confidential judge notes are strictly redacted
    for cb in perf_pub["criteria_breakdown"]:
        assert "CONFIDENTIAL" not in str(cb), "CONFIDENTIALITY LEAK: Judge notes exposed in criteria breakdown!"
    for fb in perf_pub["authorized_feedback"]:
        assert "CONFIDENTIAL" not in fb, "CONFIDENTIALITY LEAK: Judge notes exposed in feedback!"
    print("🔒 Verified: Private judge notes are 100% secluded from participant payload.")

    # 5.3 Leaderboard rankings
    resp = session_part.get(f"{BASE_URL}/api/v1/participant/leaderboard")
    assert resp.status_code == 200
    lb_pub = resp.json()
    assert lb_pub["is_published"] is True, "Leaderboard must be published!"
    assert len(lb_pub["entries"]) > 0, "Leaderboard entries must be populated!"
    print(f"✅ Leaderboard Released: {len(lb_pub['entries'])} ranked submissions")
    my_entry = next((e for e in lb_pub["entries"] if e["is_my_team"]), None)
    assert my_entry is not None, "Participant's team must be tagged with is_my_team=True"
    print(f"   Participant Team Entry: Rank {my_entry['rank']} — {my_entry['team_name']} ({my_entry['score']} pts, my_team={my_entry['is_my_team']})")

    # 5.4 Notifications reflect publication
    resp = session_part.get(f"{BASE_URL}/api/v1/participant/notifications")
    notifs = resp.json()["notifications"]
    pub_notif = next((n for n in notifs if "Results Published" in n["title"]), None)
    assert pub_notif is not None, "Expected official results publication notification in participant inbox"
    print(f"✅ Notification Received: '{pub_notif['title']}' -> Action: {pub_notif['action_url']}")

    # -------------------------------------------------------------
    # STAGE 6: SUPPORT & CROSS-WORKSPACE PRIVACY BOUNDARIES
    # -------------------------------------------------------------
    log_section("STAGE 6: SUPPORT TICKETS & ACCESS BOUNDARIES")
    # 6.1 Participant creates support ticket
    resp = session_part.post(f"{BASE_URL}/api/v1/participant/support/tickets", json={
        "category": "technical",
        "subject": "Inquiry regarding Docker evaluation environment",
        "description": "Our repository requires python 3.12 and libglib packages. Please verify runner compatibility.",
        "hackathon_id": hackathon_id
    })
    assert resp.status_code == 200
    ticket = resp.json()
    ticket_id = ticket["id"]
    print(f"✅ Created Support Ticket: {ticket['ticket_number']} (ID: {ticket_id})")

    # 6.2 Organizer / Staff views ticket and posts reply
    resp = session_org.get(f"{BASE_URL}/api/v1/participant/support/tickets/{ticket_id}")
    assert resp.status_code == 200, f"Organizer should have staff access to hackathon support tickets: {resp.text}"
    print(f"✅ Organizer accessed participant support ticket {ticket['ticket_number']}")

    resp = session_org.post(f"{BASE_URL}/api/v1/participant/support/tickets/{ticket_id}/replies", json={
        "message": "Hello Team Quantum. Both Python 3.12 and libglib-2.0 are standard in the Scorva execution container. No extra configuration required."
    })
    assert resp.status_code == 200
    staff_reply = resp.json()
    assert staff_reply["is_staff"] is True
    print(f"✅ Organizer posted staff reply (Author: {staff_reply['author_name']}, is_staff={staff_reply['is_staff']})")

    # 6.3 Participant sees staff reply
    resp = session_part.get(f"{BASE_URL}/api/v1/participant/support/tickets/{ticket_id}")
    t_detail = resp.json()
    assert len(t_detail["replies"]) >= 2
    staff_rep = next((r for r in t_detail["replies"] if r["is_staff"] and "libglib" in r["message"]), None)
    assert staff_rep is not None
    print(f"✅ Participant sees staff reply in ticket conversation.")

    # 6.4 Unauthorized access boundary: Unassigned/different participant blocked
    resp = session_judge.get(f"{BASE_URL}/api/v1/participant/support/tickets/{ticket_id}")
    assert resp.status_code in (403, 404), f"Judge should not access participant support ticket! Got {resp.status_code}"
    print(f"🔒 Access Boundary: Non-staff/unauthorized user blocked with {resp.status_code}")

    # 6.5 Unauthorized judge access to unassigned hackathon
    dummy_hack_id = str(uuid.uuid4())
    resp = session_judge.get(f"{BASE_URL}/api/v1/judge/hackathons/{dummy_hack_id}/submissions")
    assert resp.status_code in (403, 404), f"Unassigned judge must be rejected! Got {resp.status_code}"
    print(f"🔒 Access Boundary: Judge blocked from unassigned hackathon with {resp.status_code}")

    # 6.6 Non-admin access to super admin endpoints
    resp = session_part.get(f"{BASE_URL}/api/v1/admin/organizations")
    assert resp.status_code in (401, 403), f"Participant must not access /admin! Got {resp.status_code}"
    resp = session_org.get(f"{BASE_URL}/api/v1/admin/organizations")
    assert resp.status_code in (401, 403), f"Organizer must not access /admin! Got {resp.status_code}"
    print("🔒 Access Boundary: Non-platform users strictly blocked from Super Admin plane.")

    log_section("🎉 ALL CROSS-WORKSPACE INTEGRATION & PRIVACY TESTS PASSED!")

if __name__ == "__main__":
    try:
        run_e2e_journey()
    except Exception as e:
        print(f"\n❌ E2E TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
