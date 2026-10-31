"""
Clean all dummy, test, and mock data from the Scorva database.
Leaves only the standard system roles, permissions, base configuration,
and seeds a clean Super Admin account (admin@scorva.io / Password123!).
"""
import asyncio
import os
import sys
from sqlalchemy import text

# Ensure root directory is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from apps.api.core.database import AsyncSessionLocal
from apps.api.core.security import hash_password
import apps.api.core.redis as core_async_redis


async def clean_database():
    print("[*] Starting complete dummy data cleanup...")

    async with AsyncSessionLocal() as session:
        # 1. Truncate operational and tenant tables CASCADE
        operational_tables = [
            "evaluation_criterion_scores",
            "judge_criterion_scores",
            "judge_reviews",
            "evidence_references",
            "evaluation_results",
            "evaluation_jobs",
            "evaluation_job_outbox",
            "submission_snapshots",
            "submissions",
            "participant_support_replies",
            "participant_support_tickets",
            "participant_task_records",
            "participant_project_registrations",
            "participant_notification_states",
            "participant_pat_tokens",
            "github_events",
            "hackathon_judges",
            "team_members",
            "teams",
            "rubric_criteria",
            "rubric_versions",
            "rubrics",
            "hackathons",
            "organization_integrations",
            "organization_memberships",
            "organizations",
            "audit_events",
            "authz_invalidation_outbox",
            "configuration_history",
            "configuration_overrides",
            "mfa_pending_tokens",
            "rate_limit_buckets",
            "totp_replay_prevention",
            "user_role_assignments",
            "user_sessions",
        ]

        for tbl in operational_tables:
            await session.execute(text(f'TRUNCATE TABLE "{tbl}" CASCADE;'))
            print(f"    - Truncated {tbl}")

        # 2. Clean custom test roles
        await session.execute(text("DELETE FROM role_permissions WHERE role_id IN (SELECT id FROM roles WHERE is_system = false);"))
        await session.execute(text("DELETE FROM roles WHERE is_system = false;"))
        print("    - Cleaned non-system test roles")

        # 3. Clean users except super admin
        await session.execute(text("DELETE FROM users;"))
        print("    - Cleared all users")

        # 4. Insert fresh standard persona accounts
        default_pw_hash = hash_password("Password123!")
        insert_users_sql = text("""
            INSERT INTO users (
                id, email, full_name, hashed_password, platform_role,
                is_active, is_verified, mfa_enabled, created_at, updated_at
            ) VALUES 
            (gen_random_uuid(), 'admin@scorva.io', 'Platform Administrator', :pw, CAST('PLATFORM_OWNER' AS platform_role_enum), true, true, false, NOW(), NOW()),
            (gen_random_uuid(), 'organizer@scorva.io', 'Event Organizer', :pw, NULL, true, true, false, NOW(), NOW()),
            (gen_random_uuid(), 'judge@scorva.io', 'Hackathon Judge', :pw, NULL, true, true, false, NOW(), NOW()),
            (gen_random_uuid(), 'participant@scorva.io', 'Participant Student', :pw, NULL, true, true, false, NOW(), NOW());
        """)
        await session.execute(insert_users_sql, {"pw": default_pw_hash})
        print("    - Seeded core personas (admin@scorva.io, organizer@scorva.io, judge@scorva.io, participant@scorva.io / Password123!)")

        await session.commit()

    # 5. Clear Redis cache
    try:
        redis = core_async_redis.get_redis_client()
        await redis.flushdb()
        print("[+] Redis cache and sessions flushed successfully.")
    except Exception as e:
        print(f"[!] Redis flush warning: {e}")

    print("[SUCCESS] Database cleaned! Zero dummy records remain.")


if __name__ == "__main__":
    asyncio.run(clean_database())
