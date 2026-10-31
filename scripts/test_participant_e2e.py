#!/usr/bin/env python3
"""
Participant Workspace End-to-End Integration Verification Script
Tests all 11 endpoints and participant workflows against the live backend API.
"""

import sys
import requests

BASE_URL = "http://localhost:8000"

def run_tests():
    session = requests.Session()
    session.headers.update({"Origin": "http://localhost:3000"})

    print("\n=======================================================")
    print(" 1. Authenticating as Participant (participant@scorva.io)")
    print("=======================================================")
    login_payload = {
        "email": "participant@scorva.io",
        "password": "Password123!"
    }
    resp = session.post(f"{BASE_URL}/api/v1/auth/login", json=login_payload)
    if resp.status_code != 200:
        print(f"❌ Failed to login: {resp.status_code} {resp.text}")
        sys.exit(1)

    login_data = resp.json()
    user_info = login_data.get("user", {})
    routing = user_info.get("routing", {})
    default_dest = routing.get("default_destination")
    print(f"✅ Login successful for {user_info.get('email')} (ID: {user_info.get('id')})")
    print(f"   Default Destination: {default_dest}")
    assert default_dest == "/participant", f"Expected default destination /participant, got {default_dest}"

    print("\n=======================================================")
    print(" 1B. Unskippable Intake Form & Agreement Enforcement")
    print("=======================================================")
    # Check registration status
    resp = session.get(f"{BASE_URL}/api/v1/participant/registration-status")
    assert resp.status_code == 200, f"Failed: {resp.status_code} {resp.text}"
    reg_status = resp.json()
    print(f"✅ Initial Registration Status: is_registered={reg_status['is_registered']}")

    # Attempt to submit without agreement checkbox
    bad_agreement_payload = {
        "team_name": "Team Quantum",
        "team_number": "TQ-99",
        "github_url": "https://github.com/scorva/quantum-agent",
        "team_members_details": "Peter Participant, Test Administrator",
        "project_title": "Quantum AI Distributed Engine",
        "project_description": "A distributed system for AI code verification.",
        "agreement_accepted": False,
    }
    resp = session.post(f"{BASE_URL}/api/v1/participant/register-project", json=bad_agreement_payload)
    assert resp.status_code == 400, "Expected 400 when agreement checkbox is unchecked"
    assert "AGREEMENT_REQUIRED" in resp.text, "Expected code AGREEMENT_REQUIRED"
    print("✅ Verified: Unskippable form rejects submission when agreement is not checked.")

    # Attempt to submit with invalid GitHub URL
    bad_url_payload = dict(bad_agreement_payload)
    bad_url_payload["agreement_accepted"] = True
    bad_url_payload["github_url"] = "https://invalid-git-host.com/project"
    resp = session.post(f"{BASE_URL}/api/v1/participant/register-project", json=bad_url_payload)
    assert resp.status_code == 400, "Expected 400 when GitHub URL is invalid"
    assert "INVALID_GITHUB_URL" in resp.text, "Expected code INVALID_GITHUB_URL"
    print("✅ Verified: Unskippable form rejects non-GitHub repository URLs.")

    # Submit valid complete form with 4 team members added one by one
    valid_payload = dict(bad_agreement_payload)
    valid_payload["agreement_accepted"] = True
    valid_payload["github_url"] = "https://github.com/scorva/quantum-agent"
    valid_payload["team_members_details"] = (
        "Member 1 (Lead): Peter Participant (peter@scorva.io)\n"
        "Member 2: Alice Vance (alice@scorva.io)\n"
        "Member 3: Bob Smith (bob@scorva.io)\n"
        "Member 4: Charlie Davis (charlie@scorva.io)"
    )
    resp = session.post(f"{BASE_URL}/api/v1/participant/register-project", json=valid_payload)
    assert resp.status_code == 200, f"Failed to submit intake registration: {resp.status_code} {resp.text}"
    reg_res = resp.json()
    print(f"✅ Verified: Successfully submitted intake registration with 4 team members! (Team: {reg_res['team_name']}, No: {reg_res['team_number']})")

    # Verify status is now registered
    resp = session.get(f"{BASE_URL}/api/v1/participant/registration-status")
    assert resp.status_code == 200
    assert resp.json()["is_registered"] is True, "Status must now be is_registered=True"
    print("✅ Verified: Subsequent calls report is_registered=True, unlocking dashboard access.")

    print("\n=======================================================")
    print(" 2. GET /api/v1/participant/teams")
    print("=======================================================")
    resp = session.get(f"{BASE_URL}/api/v1/participant/teams")
    assert resp.status_code == 200, f"Failed: {resp.status_code} {resp.text}"
    teams = resp.json()
    print(f"✅ Teams returned: {len(teams)}")
    for t in teams:
        print(f"   - Team: {t['team_name']}, Hackathon: {t['hackathon_title']}, Role: {t['role_in_team']}, Members: {t.get('team_members')}")
    assert len(teams) > 0, "Expected at least 1 enrolled team for participant"

    print("\n=======================================================")
    print(" 3. GET /api/v1/participant/overview")
    print("=======================================================")
    resp = session.get(f"{BASE_URL}/api/v1/participant/overview")
    assert resp.status_code == 200, f"Failed: {resp.status_code} {resp.text}"
    overview = resp.json()
    print(f"✅ Overview loaded for: {overview['welcome_name']}")
    print(f"   Active Hackathons Count: {overview['active_hackathons_count']}")
    print(f"   Submission Status: {overview['submission_status']}")
    print(f"   Rank: {overview['current_rank']}, Total Score: {overview['total_score']}")
    print(f"   Stages count: {len(overview['stages'])}")
    for s in overview['stages']:
        print(f"     [{s['status'].upper()}] Step: {s['name']}")
    assert len(overview['stages']) >= 4, "Expected lifecycle stages"

    print("\n=======================================================")
    print(" 4. GET /api/v1/participant/leaderboard")
    print("=======================================================")
    resp = session.get(f"{BASE_URL}/api/v1/participant/leaderboard")
    assert resp.status_code == 200, f"Failed: {resp.status_code} {resp.text}"
    lb = resp.json()
    print(f"✅ Leaderboard: Hackathon '{lb['hackathon_title']}', Published: {lb['is_published']}")
    print(f"   Entries count: {len(lb['entries'])}")
    my_team_found = False
    for e in lb['entries']:
        print(f"     Rank {e['rank']}: {e['team_name']} - {e['score']} pts (my_team={e['is_my_team']})")
        if e['is_my_team']:
            my_team_found = True
    if lb['is_published'] and len(lb['entries']) > 0:
        assert my_team_found, "Participant's own team should be flagged with is_my_team=True"

    print("\n=======================================================")
    print(" 5. GET /api/v1/participant/performance")
    print("=======================================================")
    resp = session.get(f"{BASE_URL}/api/v1/participant/performance")
    assert resp.status_code == 200, f"Failed: {resp.status_code} {resp.text}"
    perf = resp.json()
    print(f"✅ Performance: Has Submission: {perf['has_submission']}")
    print(f"   Final Score: {perf['final_score']} / {perf['max_score']}")
    print(f"   Criteria count: {len(perf['criteria_breakdown'])}")
    for c in perf['criteria_breakdown']:
        print(f"     Criterion: {c['criterion_name']} -> {c['awarded_score']}/{c['max_score']} ({c['progress_percentage']}%)")
    print(f"   Authorized Feedback count: {len(perf['authorized_feedback'])}")
    for fb in perf['authorized_feedback']:
        print(f"     Feedback: {fb}")
    # Verify private judge notes are never present
    assert "judge_notes" not in perf, "CRITICAL: Private judge notes must NOT be exposed in performance response"

    print("\n=======================================================")
    print(" 6. Tasks: GET /api/v1/participant/tasks")
    print("=======================================================")
    resp = session.get(f"{BASE_URL}/api/v1/participant/tasks")
    assert resp.status_code == 200, f"Failed: {resp.status_code} {resp.text}"
    tasks = resp.json()
    print(f"✅ Tasks returned: {len(tasks)}")
    for t in tasks:
        print(f"   - [{t['category'].upper()}] {t['title']} (status: {t['status']})")
    assert len(tasks) > 0, "Expected seed tasks/opportunities"

    print("\n=======================================================")
    print(" 7. Task Status Update: POST /api/v1/participant/tasks/{id}/status")
    print("=======================================================")
    first_task = tasks[0]
    task_id = first_task["id"]
    new_status = "completed" if first_task["status"] != "completed" else "in_progress"
    resp = session.post(
        f"{BASE_URL}/api/v1/participant/tasks/{task_id}/status",
        json={"status": new_status}
    )
    assert resp.status_code == 200, f"Failed: {resp.status_code} {resp.text}"
    print(f"✅ Task {task_id} updated to {new_status}")

    # Verify persistence
    resp = session.get(f"{BASE_URL}/api/v1/participant/tasks")
    refreshed_tasks = resp.json()
    matched = [t for t in refreshed_tasks if t["id"] == task_id]
    assert len(matched) == 1 and matched[0]["status"] == new_status, "Status persistence failed"
    print(f"✅ Status persistence verified: {matched[0]['status']}")

    print("\n=======================================================")
    print(" 8. Notifications: GET /api/v1/participant/notifications")
    print("=======================================================")
    resp = session.get(f"{BASE_URL}/api/v1/participant/notifications")
    assert resp.status_code == 200, f"Failed: {resp.status_code} {resp.text}"
    notif_data = resp.json()
    print(f"✅ Notifications: Total: {len(notif_data['notifications'])}, Unread: {notif_data['unread_count']}")
    assert len(notif_data['notifications']) > 0, "Expected notifications"

    print("\n=======================================================")
    print(" 9. Mark Read: POST /api/v1/participant/notifications/{id}/read")
    print("=======================================================")
    notif_id = notif_data['notifications'][0]['id']
    resp = session.post(f"{BASE_URL}/api/v1/participant/notifications/{notif_id}/read")
    assert resp.status_code == 200, f"Failed: {resp.status_code} {resp.text}"
    print(f"✅ Marked notification {notif_id} as read")

    print("\n=======================================================")
    print(" 10. Mark All Read: POST /api/v1/participant/notifications/read-all")
    print("=======================================================")
    resp = session.post(f"{BASE_URL}/api/v1/participant/notifications/read-all")
    assert resp.status_code == 200, f"Failed: {resp.status_code} {resp.text}"
    resp = session.get(f"{BASE_URL}/api/v1/participant/notifications")
    assert resp.json()["unread_count"] == 0, "Unread count should be 0 after read-all"
    print("✅ Verified unread count is 0 after mark-all-read")

    print("\n=======================================================")
    print(" 11. Support: POST /api/v1/participant/support/tickets")
    print("=======================================================")
    ticket_payload = {
        "category": "Technical / Repository Issue",
        "subject": "Docker container build error during AI verification",
        "description": "Our test suite passes locally but Scorva AI evaluation reports exit code 127 in step 3.",
    }
    resp = session.post(f"{BASE_URL}/api/v1/participant/support/tickets", json=ticket_payload)
    assert resp.status_code in (200, 201), f"Failed: {resp.status_code} {resp.text}"
    ticket = resp.json()
    ticket_id = ticket["id"]
    ticket_number = ticket["ticket_number"]
    print(f"✅ Created Ticket {ticket_number} (ID: {ticket_id})")

    print("\n=======================================================")
    print(" 12. Support: GET /api/v1/participant/support/tickets")
    print("=======================================================")
    resp = session.get(f"{BASE_URL}/api/v1/participant/support/tickets")
    assert resp.status_code == 200, f"Failed: {resp.status_code} {resp.text}"
    user_tickets = resp.json()
    assert any(t["id"] == ticket_id for t in user_tickets), "Created ticket not found in list"
    print(f"✅ Found created ticket in tickets list (Total tickets: {len(user_tickets)})")

    print("\n=======================================================")
    print(" 13. Support Detail: GET /api/v1/participant/support/tickets/{id}")
    print("=======================================================")
    resp = session.get(f"{BASE_URL}/api/v1/participant/support/tickets/{ticket_id}")
    assert resp.status_code == 200, f"Failed: {resp.status_code} {resp.text}"
    detail = resp.json()
    print(f"✅ Retrieved ticket details for {detail['ticket']['ticket_number']}: '{detail['ticket']['subject']}'")

    print("\n=======================================================")
    print(" 14. Support Reply: POST /api/v1/participant/support/tickets/{id}/replies")
    print("=======================================================")
    reply_payload = {
        "message": "We have pushed commit 7c8fa10 resolving the missing dependency. Please re-trigger."
    }
    resp = session.post(f"{BASE_URL}/api/v1/participant/support/tickets/{ticket_id}/replies", json=reply_payload)
    assert resp.status_code in (200, 201), f"Failed: {resp.status_code} {resp.text}"
    new_reply = resp.json()
    print(f"✅ Reply posted successfully! ID: {new_reply['id']}")
    print(f"   Author: {new_reply['author_name']} | Message: {new_reply['message']}")

    # Verify ticket detail includes the new reply
    resp = session.get(f"{BASE_URL}/api/v1/participant/support/tickets/{ticket_id}")
    assert resp.status_code == 200, f"Failed: {resp.status_code} {resp.text}"
    detail_with_replies = resp.json()
    assert len(detail_with_replies["replies"]) >= 1, "Expected replies in ticket detail"
    print(f"✅ Verified ticket detail contains {len(detail_with_replies['replies'])} replies.")

    print("\n=======================================================")
    print(" 15. PAT Token Settings: GET, POST, DELETE /api/v1/participant/settings/pat")
    print("=======================================================")
    # 1. Initial state
    resp = session.get(f"{BASE_URL}/api/v1/participant/settings/pat")
    assert resp.status_code == 200, f"Failed: {resp.status_code} {resp.text}"
    print(f"✅ Initial PAT status retrieved: has_token={resp.json()['has_token']}")

    # 2. Save PAT token
    sample_pat = "github_pat_11ABCD_efghijklmnopqrstuvwxyz0123456789"
    resp = session.post(f"{BASE_URL}/api/v1/participant/settings/pat", json={"pat_token": sample_pat})
    assert resp.status_code == 200, f"Failed: {resp.status_code} {resp.text}"
    saved_pat = resp.json()
    print(f"✅ PAT token saved and verified: masked='{saved_pat['token_masked']}', is_verified={saved_pat['is_verified']}")
    assert saved_pat["is_verified"] is True
    assert "github_pat_" in saved_pat["token_masked"]

    # 3. Retrieve updated status
    resp = session.get(f"{BASE_URL}/api/v1/participant/settings/pat")
    assert resp.status_code == 200
    pat_info = resp.json()
    assert pat_info["has_token"] is True
    print(f"✅ Verified PAT token persistence in settings dashboard: {pat_info['token_masked']}")

    # 4. Revoke / Delete PAT token
    resp = session.delete(f"{BASE_URL}/api/v1/participant/settings/pat")
    assert resp.status_code == 200
    print("✅ PAT token revoked successfully.")

    # 5. Confirm deletion
    resp = session.get(f"{BASE_URL}/api/v1/participant/settings/pat")
    assert resp.status_code == 200
    assert resp.json()["has_token"] is False
    print("✅ Verified token removal confirmed in settings.")

    print("\n=======================================================")
    print(" 16. GitHub Settings & Ownership Verification Run Button")
    print("=======================================================")
    # 1. Fetch GitHub settings (should show registered repo from intake form)
    resp = session.get(f"{BASE_URL}/api/v1/participant/settings/github")
    assert resp.status_code == 200, f"Failed: {resp.status_code} {resp.text}"
    gh_info = resp.json()
    print(f"✅ Registered GitHub repo retrieved: url='{gh_info['repository_url']}', team='{gh_info['team_name']}'")
    assert gh_info["has_registration"] is True
    assert gh_info["repository_url"] == "https://github.com/scorva/quantum-agent"

    # 2. Re-configure PAT token
    resp = session.post(f"{BASE_URL}/api/v1/participant/settings/pat", json={"pat_token": sample_pat})
    assert resp.status_code == 200

    # 3. Click "Run Verification" button -> POST /api/v1/participant/settings/github/verify
    resp = session.post(f"{BASE_URL}/api/v1/participant/settings/github/verify")
    assert resp.status_code == 200, f"Failed: {resp.status_code} {resp.text}"
    verify_res = resp.json()
    print(f"✅ Run Verification succeeded: status='{verify_res['verification_status']}'")
    assert verify_res["verification_status"] == "verified"

    # 4. Verify GitHub settings reflects verified status badge
    resp = session.get(f"{BASE_URL}/api/v1/participant/settings/github")
    assert resp.status_code == 200
    updated_gh = resp.json()
    assert updated_gh["verification_status"] == "verified"
    assert updated_gh["verified_at"] is not None
    print(f"✅ Verified: GitHub settings status badge is now '{updated_gh['verification_status']}' on {updated_gh['verified_at']}")

    print("\n=======================================================")
    print(" 🎉 ALL 16 PARTICIPANT WORKSPACE TESTS PASSED!")
    print("=======================================================\n")

if __name__ == "__main__":
    run_tests()
