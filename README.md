# Scorva — AI-Assisted Hackathon Evaluation SaaS Platform

Scorva is a multi-tenant platform designed to evaluate hackathon software repositories using automated AI pipelines, evidence-backed rubric scoring, and human judge review workflows.

This repository contains the central **Super Admin Dashboard** and the supporting platform services.

---

## Architecture & Project Structure

The project is structured as a **modular monolith** with an asynchronous task processing subsystem:

```text
scorva/
├── apps/
│   ├── web/                           # Next.js 15+ Frontend (TypeScript, Tailwind CSS, Lucide React)
│   │   ├── src/app/                   # App Router pages and Super Admin layout
│   │   ├── src/components/admin/      # Reusable UI shell, badges, indicators
│   │   ├── src/lib/                   # Typed API client
│   │   └── src/types/                 # TypeScript interfaces
│   │
│   └── api/                           # FastAPI Backend Modular Monolith
│       ├── core/                      # Config, logging, RFC 7807 exceptions
│       ├── modules/                   # Domain modules (health, auth, orgs, etc.)
│       │   └── health/                # Service health & readiness probes
│       └── tests/                     # Automated pytest suite
│
├── docker/                            # Docker Compose & multi-stage Dockerfiles
│   ├── Dockerfile.api                 # FastAPI production container
│   ├── Dockerfile.web                 # Next.js production container
│   └── docker-compose.yml             # Local dev environment
│
├── docs/                              # Product and Technical Documentation
│   ├── PRD.md                         # Product Requirements Document
│   ├── SUPER_ADMIN_SCREEN_SPEC.md     # UI/UX Screen-by-Screen Specification
│   └── ARCHITECTURE.md                # System Architecture & Technical Blueprint
│
├── .env.example                       # Environment configuration template
├── package.json                       # Monorepo root workspace scripts
└── README.md                          # Getting Started & Setup Guide
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | Next.js 15+ (App Router), React 19, TypeScript, Tailwind CSS, Lucide React |
| **Backend** | FastAPI, Pydantic v2, Pydantic-Settings, Uvicorn |
| **Database** | PostgreSQL 16 (asyncpg driver) |
| **Task Queue & Cache** | Redis 7, Celery 5.4 |
| **Object Storage** | MinIO / AWS S3 API |
| **AI Inference** | Ollama (`llama3:8b`, `deepseek-coder:6.7b`) |
| **Testing** | pytest, pytest-asyncio, httpx, tsc, Next.js build |

---

## Local Development Quickstart

### Prerequisites

- **Node.js**: v18.0.0 or higher (v20+ recommended)
- **npm**: v9.0.0 or higher
- **Python**: v3.11 or higher
- **Docker & Docker Compose**: v2.20+ (optional for local mock mode, required for full container stack)

### 1. Environment Configuration

Copy the template `.env.example` file to create your local `.env`:

```bash
cp .env.example .env
```

Review `.env` and adjust database, Redis, or API port configurations if needed.

---

### 2. Option A: One-Command Start & Stop Scripts (Recommended)

Start the entire platform (PostgreSQL, Redis, FastAPI backend, Next.js frontend):
```bash
./start.sh
# or: npm start
```

Check real-time service health and status:
```bash
./status.sh
# or: npm run status
```

Stream live application logs:
```bash
./scripts/logs.sh
# or: npm run logs
```

Stop the platform and backing services cleanly:
```bash
./stop.sh
# or: npm stop
```

Options:
- `./start.sh -f`: Start services and follow live logs in foreground.
- `./start.sh -d`: Start complete containerized stack via Docker Compose.
- `./stop.sh -k`: Stop API and Web servers while keeping database containers running.
- `./stop.sh -c`: Stop and tear down all Docker containers (`docker compose down`).

---

### 3. Option B: Run with Docker Compose Directly

Start the entire platform stack (PostgreSQL, Redis, MinIO, Ollama, FastAPI Backend, and Next.js Web):

```bash
docker compose up -d
```

Check the health status of running containers:

```bash
docker compose ps
```

- **Frontend Super Admin Web:** [http://localhost:3000/admin](http://localhost:3000/admin)
- **FastAPI Backend API:** [http://localhost:8000](http://localhost:8000)
- **Interactive OpenAPI Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **MinIO Storage Console:** [http://localhost:9001](http://localhost:9001) (`minioadmin` / `minioadmin`)

To stop all services:

```bash
docker compose down
```

---

### 3. Option B: Run Services Locally (Host Mode)

#### Backend (FastAPI)

1. Create and activate a Python virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r apps/api/requirements.txt
   ```

3. Run the development server:
   ```bash
   uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000
   ```

The backend is now live at [http://localhost:8000](http://localhost:8000).

#### Frontend (Next.js)

1. Install npm packages:
   ```bash
   npm install --prefix apps/web
   ```

2. Run the development server:
   ```bash
   npm --prefix apps/web run dev
   ```

Open [http://localhost:3000/admin](http://localhost:3000/admin) in your browser.

---

## Running Automated Tests & Build Checks

### Backend Test Suite (pytest)

Run the Python test suite verifying health endpoints, async PostgreSQL database connectivity, Alembic configuration, and RFC 7807 error handling:

```bash
.venv/bin/pytest apps/api/tests -v
```

*Expected output: All 11 test cases pass with status code 200/404/422 assertions verified.*

### Database Migrations & Initial Admin Seeding

#### 1. Apply Schema Migrations
Alembic is configured for async SQLAlchemy migrations against PostgreSQL:
```bash
.venv/bin/alembic -c alembic.ini upgrade head
```

#### 2. Seed Initial Administrative Users
Bootstrap development Super Admin accounts (creates password hashes with Argon2id and encrypted TOTP secrets with AES-256-GCM):
```bash
PYTHONPATH=. .venv/bin/python apps/api/scripts/seed_admin.py
```

**Pre-Configured Development Accounts:**
| Account Email | Password | Platform Role | MFA State | TOTP Secret |
|---|---|---|---|---|
| `admin@scorva.io` | `Password123!` | `PLATFORM_OWNER` | Pending Enrollment | Generated on first login |
| `owner@scorva.io` | `Password123!` | `PLATFORM_OWNER` | Enrolled | `JBSWY3DPEHPK3PXP` |
| `security@scorva.io` | `Password123!` | `SECURITY_ADMIN` | Enrolled | `JBSWY3DPEHPK3PXP` |

*Tip: For accounts with secret `JBSWY3DPEHPK3PXP`, you can generate current TOTP codes in Python with `pyotp.TOTP("JBSWY3DPEHPK3PXP").now()` or add the secret to your mobile authenticator app.*

---

## Running Automated Tests & Build Checks

### Backend Test Suite (pytest)

Run the complete 42-test suite covering authentication ceremonies, mandatory MFA, Argon2id hashing, TOTP replay protection, rate limiting, dual-barrier session validation (Redis + PostgreSQL fallback), role-based authorization guards, session invalidation triggers, and immutable audit triggers:

```bash
.venv/bin/pytest apps/api/tests -v
```

*Expected output: All 42 tests pass cleanly.*

Verify database migration downgrade/upgrade cycles:
```bash
.venv/bin/pytest apps/api/tests/test_migrations.py -v
```

### Frontend Typecheck & Build

Run TypeScript type verification:
```bash
npm run typecheck --prefix apps/web
```

Run optimized production build verification:
```bash
npm run build --prefix apps/web
```

---

## Implementation Roadmap & Current Status

- [x] **Phase 1: Project Foundation**
  - Monorepo directory structure established (`apps/web`, `apps/api`, `docker`).
  - Next.js 15+ frontend initialized with dark-first theme tokens (`#0B1020`, `#111827`, `#3B82F6`) and Lucide React icons.
  - Responsive Super Admin shell with persistent desktop sidebar and mobile off-canvas drawer.
  - FastAPI backend configured with CORS, correlation tracking, RFC 7807 exception handling, and `/api/v1/health` probes.
  - Frontend typed API client with timeout and structured error handling.
  - Docker Compose development environment configured for all dependencies.

- [x] **Phase 2: Authentication, Sessions, MFA, & Platform RBAC**
  - **Argon2id Password Hashing:** Constant-time verification with dummy verify against email enumeration.
  - **MFA Enforcement:** Mandatory TOTP for administrative roles; short-lived setup/challenge tokens with Redis replay prevention.
  - **Cryptographic Encryption:** AES-256-GCM authenticated encryption for persisted TOTP secret seeds with environment-injected master key.
  - **Dual-Barrier Session Validation:** 256-bit CSPRNG tokens (only SHA-256 stored server-side), fast-path Redis cache with TTL sliding, resilient PostgreSQL fallback on Redis outage.
  - **Revocation & Invalidation:** Instant session revocation upon account suspension, role change, or explicit logout.
  - **Security Controls:** Trusted reverse-proxy IP extraction (`ProxyHeadersMiddleware`), strict CSRF Origin/Referer verification on mutations (`CsrfOriginMiddleware`).
  - **Append-Only Audit Trail:** `audit_events` table protected by PostgreSQL row-level trigger `trg_audit_events_immutable` preventing `UPDATE` and `DELETE`.
  - **Frontend Integration:** Super Admin login screen (`/login`) with credential, MFA setup, and MFA challenge steps; active session profile and logout in header; interactive audit trail (`/admin/security`) and user session management (`/admin/users`).
  - **Automated Verification:** 42 backend pytest tests and Next.js production build passing.

- [ ] **Phase 3: Core Administration (Organizations, Tenant Isolation, Hackathons)**
  - Multi-tenant directory pagination, organization suspension workflows, and hackathon commit tracking.
  - Foreign key linking between `audit_events.organization_id` and `organizations.id`.

- [ ] **Phase 4: Asynchronous AI Evaluation Engine & Worker Subsystem**
  - Celery worker pool, immutable Git tarball archiving, Ollama structured JSON schema scoring, and evidence verification.

- [ ] **Phase 5: Reliability, Health Probes, Retries, & Audit Hardening**
  - Safe evaluation retry workflows, live readiness telemetry, and audit log search.

- [ ] **Phase 6: End-to-End Validation & Production Packaging**
  - Playwright E2E test suites, rate limiting, and production deployment runbooks.
