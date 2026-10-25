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

### 2. Option A: Run with Docker Compose (Recommended)

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

Run the Python test suite verifying health endpoints, configuration loading, and error handling:

```bash
.venv/bin/pytest apps/api/tests
```

*Expected output: All test cases pass with status code 200/404 assertions verified.*

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

- [x] **Phase 1: Project Foundation** (Current)
  - Monorepo directory structure established (`apps/web`, `apps/api`, `docker`).
  - Next.js 15+ frontend initialized with dark-first theme tokens (`#0B1020`, `#111827`, `#3B82F6`) and Lucide React icons.
  - Responsive Super Admin shell with persistent desktop sidebar and mobile off-canvas drawer.
  - FastAPI backend configured with CORS, correlation tracking, RFC 7807 exception handling, and `/api/v1/health` probes.
  - Frontend typed API client with timeout and structured error handling.
  - Docker Compose development environment configured for all dependencies.
  - Automated tests and build checks verified.

- [ ] **Phase 2: Authentication, Sessions, & Dual-Plane RBAC**
  - Redis session store, TOTP MFA challenge, and Super Admin authorization guards.
  - Append-only `audit_events` logging for privileged administrative mutations.

- [ ] **Phase 3: Core Administration (Organizations, Users, Hackathons)**
  - Multi-tenant directory pagination, organization suspension workflows, and hackathon commit tracking.

- [ ] **Phase 4: Asynchronous AI Evaluation Engine & Worker Subsystem**
  - Celery worker pool, immutable Git tarball archiving, Ollama structured JSON schema scoring, and evidence verification.

- [ ] **Phase 5: Reliability, Health Probes, Retries, & Audit Hardening**
  - Safe evaluation retry workflows, live readiness telemetry, and audit log search.

- [ ] **Phase 6: End-to-End Validation & Production Packaging**
  - Playwright E2E test suites, rate limiting, and production deployment runbooks.
