#!/usr/bin/env bash
# ==============================================================================
# Scorva — Project Startup Script
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

MODE="hybrid"
START_API=1
START_WEB=1
START_DOCKER_SERVICES=1
FOLLOW_LOGS=0

usage() {
    cat <<EOF
${BOLD}Scorva Project Startup Utility${NC}

${BOLD}Usage:${NC}
  ./start.sh [options]

${BOLD}Options:${NC}
  -f, --foreground    Start services and follow live logs in the console
  -d, --docker        Start full containerized stack via Docker Compose
  --api-only          Start backing services (Postgres, Redis) and FastAPI backend only
  --web-only          Start Next.js frontend only
  --no-db             Skip starting Docker Postgres/Redis containers
  -h, --help          Show this help message

${BOLD}Default Behavior:${NC}
  Starts PostgreSQL & Redis via Docker, then launches FastAPI (port 8000)
  and Next.js (port 3000) in local development mode with live reload.
  Logs are piped to .run/logs/ and PIDs tracked in .run/pids/.

EOF
    exit 0
}

# Parse command line options
while [[ $# -gt 0 ]]; do
    case "$1" in
        -f|--foreground)
            FOLLOW_LOGS=1
            shift
            ;;
        -d|--docker)
            MODE="docker"
            shift
            ;;
        --api-only)
            START_WEB=0
            shift
            ;;
        --web-only)
            START_API=0
            START_DOCKER_SERVICES=0
            shift
            ;;
        --no-db)
            START_DOCKER_SERVICES=0
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            ;;
    esac
done

cd "${PROJECT_ROOT}"

echo -e "\n${BOLD}${CYAN}======================================================${NC}"
echo -e "${BOLD}${CYAN}            Starting Scorva Platform                  ${NC}"
echo -e "${BOLD}${CYAN}======================================================${NC}\n"

# Full Docker Compose mode
if [ "$MODE" = "docker" ]; then
    log_step "Starting complete stack via Docker Compose..."
    ensure_env_file
    docker compose up -d
    log_success "Docker Compose services launched."
    docker compose ps
    if [ "$FOLLOW_LOGS" -eq 1 ]; then
        docker compose logs -f
    fi
    exit 0
fi

# Pre-flight environment validation
ensure_run_dirs
ensure_env_file
if ! check_prerequisites; then
    log_error "Pre-flight checks failed. Please fix missing dependencies above."
    exit 1
fi

# 1. Backing Services (PostgreSQL & Redis)
if [ "$START_DOCKER_SERVICES" -eq 1 ]; then
    log_step "Starting infrastructure services (PostgreSQL & Redis via Docker)..."
    
    if ! docker info >/dev/null 2>&1; then
        log_error "Docker daemon is not responding. Please start Docker."
        exit 1
    fi

    docker compose up -d postgres redis

    # Wait for PostgreSQL to report healthy
    echo -n "  Waiting for PostgreSQL to be ready"
    local_timeout=20
    while [ $local_timeout -gt 0 ]; do
        if is_port_listening "$DB_PORT"; then
            # Verify postgres is accepting connections
            if docker compose exec -T postgres pg_isready -U scorva -d scorva >/dev/null 2>&1; then
                break
            fi
        fi
        echo -n "."
        sleep 1
        local_timeout=$((local_timeout - 1))
    done
    echo ""

    if [ $local_timeout -le 0 ]; then
        log_error "Timed out waiting for PostgreSQL container on port ${DB_PORT}."
        exit 1
    fi
    log_success "PostgreSQL is healthy on port ${DB_PORT}"
    log_success "Redis is active on port ${REDIS_PORT}"

    # Apply database schema migrations
    log_step "Running Alembic database migrations..."
    if [ -x "${PROJECT_ROOT}/.venv/bin/alembic" ]; then
        if ! "${PROJECT_ROOT}/.venv/bin/alembic" upgrade head; then
            log_error "Alembic database migration failed. Aborting startup to prevent running against an inconsistent schema."
            exit 1
        fi
        log_success "Database schema is up to date."
    else
        log_error "Alembic binary not found at ${PROJECT_ROOT}/.venv/bin/alembic. Aborting startup."
        exit 1
    fi

    # Ensure development administrator accounts exist if in development
    if [ -x "${PROJECT_ROOT}/.venv/bin/python" ] && [ "${SCORVA_ENV:-development}" != "production" ]; then
        log_step "Ensuring development administrative seed accounts exist..."
        PYTHONPATH="${PROJECT_ROOT}" "${PROJECT_ROOT}/.venv/bin/python" "${PROJECT_ROOT}/apps/api/scripts/seed_admin.py" --dev-defaults >/dev/null 2>&1 || true
        log_success "Development administrative seed accounts verified."
    fi
fi

# 2. Start FastAPI Backend
if [ "$START_API" -eq 1 ]; then
    log_step "Checking API service on port ${API_PORT}..."
    
    API_PID=$(get_running_pid "$API_PID_FILE" || true)
    if [ -n "$API_PID" ]; then
        log_warn "FastAPI is already running (PID: ${API_PID})."
    elif is_port_listening "$API_PORT"; then
        CONFLICT_PID=$(get_pid_on_port "$API_PORT" || true)
        log_warn "Port ${API_PORT} is already in use by PID ${CONFLICT_PID:-unknown}. Reusing existing listener."
    else
        log_info "Launching FastAPI backend (development reload mode)..."
        # Export environment variables from .env
        set -a
        source "${PROJECT_ROOT}/.env"
        set +a

        nohup "${PROJECT_ROOT}/.venv/bin/python" -m uvicorn apps.api.main:app \
            --reload \
            --host 0.0.0.0 \
            --port "${API_PORT}" \
            < /dev/null > "${API_LOG_FILE}" 2>&1 &
        
        API_PID=$!
        echo "$API_PID" > "${API_PID_FILE}"
        
        echo -n "  Waiting for API health probe"
        api_timeout=15
        while [ $api_timeout -gt 0 ]; do
            if curl -s -f "http://127.0.0.1:${API_PORT}/api/v1/health" >/dev/null 2>&1; then
                break
            fi
            # Check if process unexpectedly exited
            if ! is_process_running "$API_PID"; then
                echo ""
                log_error "API process exited unexpectedly. Check logs at: ${API_LOG_FILE}"
                cat "${API_LOG_FILE}" | tail -n 20
                exit 1
            fi
            echo -n "."
            sleep 0.5
            api_timeout=$((api_timeout - 1))
        done
        echo ""

        if [ $api_timeout -le 0 ]; then
            log_error "Timed out waiting for API to respond at http://127.0.0.1:${API_PORT}/api/v1/health."
            log_info "Last logs from ${API_LOG_FILE}:"
            tail -n 15 "${API_LOG_FILE}"
            exit 1
        fi

        # Save actual listening worker PID if available
        LISTEN_PID=$(get_pid_on_port "${API_PORT}" || true)
        if [ -n "$LISTEN_PID" ]; then
            echo "$LISTEN_PID" > "${API_PID_FILE}"
            API_PID="$LISTEN_PID"
        fi
        log_success "FastAPI backend is ready (PID: ${API_PID}) -> http://localhost:${API_PORT}"
    fi
fi

# 3. Start Next.js Frontend
if [ "$START_WEB" -eq 1 ]; then
    log_step "Checking Frontend Web service on port ${WEB_PORT}..."
    
    WEB_PID=$(get_running_pid "$WEB_PID_FILE" || true)
    if [ -n "$WEB_PID" ]; then
        log_warn "Next.js Web is already running (PID: ${WEB_PID})."
    elif is_port_listening "$WEB_PORT"; then
        CONFLICT_PID=$(get_pid_on_port "$WEB_PORT" || true)
        log_warn "Port ${WEB_PORT} is already in use by PID ${CONFLICT_PID:-unknown}. Reusing existing listener."
    else
        log_info "Launching Next.js frontend (development mode)..."
        nohup npm --prefix "${PROJECT_ROOT}/apps/web" run dev \
            < /dev/null > "${WEB_LOG_FILE}" 2>&1 &
        WEB_PID=$!
        echo "$WEB_PID" > "${WEB_PID_FILE}"

        echo -n "  Waiting for Next.js web server"
        web_timeout=25
        while [ $web_timeout -gt 0 ]; do
            if is_port_listening "$WEB_PORT"; then
                break
            fi
            if ! is_process_running "$WEB_PID"; then
                echo ""
                log_error "Next.js web process exited unexpectedly. Check logs at: ${WEB_LOG_FILE}"
                cat "${WEB_LOG_FILE}" | tail -n 20
                exit 1
            fi
            echo -n "."
            sleep 0.5
            web_timeout=$((web_timeout - 1))
        done
        echo ""

        if [ $web_timeout -le 0 ]; then
            log_error "Timed out waiting for Next.js on port ${WEB_PORT}."
            log_info "Last logs from ${WEB_LOG_FILE}:"
            tail -n 15 "${WEB_LOG_FILE}"
            exit 1
        fi

        # Save actual listening worker PID if available
        LISTEN_WEB_PID=$(get_pid_on_port "${WEB_PORT}" || true)
        if [ -n "$LISTEN_WEB_PID" ]; then
            echo "$LISTEN_WEB_PID" > "${WEB_PID_FILE}"
            WEB_PID="$LISTEN_WEB_PID"
        fi
        log_success "Next.js frontend is ready (PID: ${WEB_PID}) -> http://localhost:${WEB_PORT}"
    fi
fi

# Display Status Dashboard Summary
echo -e "\n${BOLD}${GREEN}✔ All Scorva services are up and operational!${NC}\n"
echo -e "${BOLD}Platform Access Points:${NC}"
echo -e "  • ${BOLD}Super Admin Web UI:${NC}    ${CYAN}http://localhost:${WEB_PORT}/admin${NC}"
echo -e "  • ${BOLD}FastAPI Backend Root:${NC}   ${CYAN}http://localhost:${API_PORT}${NC}"
echo -e "  • ${BOLD}Interactive Swagger Docs:${NC} ${CYAN}http://localhost:${API_PORT}/docs${NC}"
echo -e "  • ${BOLD}System Health Probe:${NC}    ${CYAN}http://localhost:${API_PORT}/api/v1/health${NC}"
echo -e "  • ${BOLD}PostgreSQL Database:${NC}    ${DIM}localhost:${DB_PORT} (db: scorva, user: scorva)${NC}"
echo -e "  • ${BOLD}Redis Broker:${NC}           ${DIM}localhost:${REDIS_PORT}${NC}"

echo -e "\n${BOLD}Operational Controls:${NC}"
echo -e "  • Check service status:     ${BOLD}./status.sh${NC} (or npm run status)"
echo -e "  • Tail live server logs:    ${BOLD}./scripts/logs.sh${NC} (or npm run logs)"
echo -e "  • Stop all services:        ${BOLD}./stop.sh${NC} (or npm stop)"
echo -e "  • Log files location:       ${DIM}${LOG_DIR}/${NC}\n"

if [ "$FOLLOW_LOGS" -eq 1 ]; then
    log_info "Streaming logs (Press Ctrl+C to detach; services will continue running in background)..."
    trap 'echo -e "\n${YELLOW}Detached from logs. Services remain running.${NC}"; exit 0' INT TERM
    tail -f "${API_LOG_FILE}" "${WEB_LOG_FILE}"
fi
