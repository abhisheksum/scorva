#!/usr/bin/env bash
# ==============================================================================
# Scorva — Project Shutdown Script
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

STOP_CONTAINERS=1
TEAR_DOWN_CONTAINERS=0

usage() {
    cat <<EOF
${BOLD}Scorva Project Shutdown Utility${NC}

${BOLD}Usage:${NC}
  ./stop.sh [options]

${BOLD}Options:${NC}
  -k, --keep-containers   Keep backing Docker containers (Postgres, Redis) running
  -c, --down              Tear down and remove Docker containers (docker compose down)
  -h, --help              Show this help message

${BOLD}Default Behavior:${NC}
  Stops the Next.js frontend (port 3000), FastAPI backend (port 8000),
  and pauses the PostgreSQL and Redis containers.

EOF
    exit 0
}

# Parse options
while [[ $# -gt 0 ]]; do
    case "$1" in
        -k|--keep-containers)
            STOP_CONTAINERS=0
            shift
            ;;
        -c|--down)
            TEAR_DOWN_CONTAINERS=1
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
echo -e "${BOLD}${CYAN}            Stopping Scorva Platform                   ${NC}"
echo -e "${BOLD}${CYAN}======================================================${NC}\n"

# Helper to stop a process gracefully by PID with timeout
stop_process_by_pid() {
    local pid="$1"
    local name="$2"

    if [ -z "$pid" ] || ! is_process_running "$pid"; then
        return 0
    fi

    log_step "Stopping ${name} (PID: ${pid})..."
    
    # Kill child processes first if any (e.g., node child worker or uvicorn reloader)
    pkill -TERM -P "$pid" 2>/dev/null || true
    kill -TERM "$pid" 2>/dev/null || true

    local wait_count=10
    while [ $wait_count -gt 0 ]; do
        if ! is_process_running "$pid"; then
            break
        fi
        sleep 0.5
        wait_count=$((wait_count - 1))
    done

    if is_process_running "$pid"; then
        log_warn "${name} did not stop gracefully; forcing termination..."
        pkill -KILL -P "$pid" 2>/dev/null || true
        kill -KILL "$pid" 2>/dev/null || true
    fi
    log_success "${name} stopped."
}

# Helper to clean up any process listening on a port
cleanup_port() {
    local port="$1"
    local name="$2"

    if is_port_listening "$port"; then
        log_warn "Detected lingering listener on port ${port} (${name}). Clearing..."
        if command -v fuser >/dev/null 2>&1; then
            fuser -k -TERM "$port/tcp" 2>/dev/null || true
            sleep 1
            if is_port_listening "$port"; then
                fuser -k -KILL "$port/tcp" 2>/dev/null || true
            fi
        else
            local port_pid
            port_pid=$(get_pid_on_port "$port" || true)
            if [ -n "$port_pid" ]; then
                kill -TERM "$port_pid" 2>/dev/null || true
                sleep 1
                if is_process_running "$port_pid"; then
                    kill -KILL "$port_pid" 2>/dev/null || true
                fi
            fi
        fi
        log_success "Port ${port} cleared."
    fi
}

# 1. Stop Next.js Frontend
WEB_PID=$(get_running_pid "$WEB_PID_FILE" || true)
if [ -n "$WEB_PID" ]; then
    stop_process_by_pid "$WEB_PID" "Next.js Web Frontend"
    rm -f "$WEB_PID_FILE"
else
    log_info "Next.js Web frontend PID file was not active."
fi
cleanup_port "$WEB_PORT" "Next.js Web"

# 2. Stop FastAPI Backend
API_PID=$(get_running_pid "$API_PID_FILE" || true)
if [ -n "$API_PID" ]; then
    stop_process_by_pid "$API_PID" "FastAPI Backend"
    rm -f "$API_PID_FILE"
else
    log_info "FastAPI backend PID file was not active."
fi
cleanup_port "$API_PORT" "FastAPI Backend"

# 3. Handle Docker Containers
if [ "$TEAR_DOWN_CONTAINERS" -eq 1 ]; then
    log_step "Tearing down Docker containers..."
    docker compose down
    log_success "Docker containers removed."
elif [ "$STOP_CONTAINERS" -eq 1 ]; then
    log_step "Stopping backing Docker containers (PostgreSQL, Redis)..."
    docker compose stop postgres redis 2>/dev/null || true
    log_success "Docker containers stopped."
else
    log_info "Preserving running Docker containers (--keep-containers)."
fi

# Clean up stale PID files
rm -f "$API_PID_FILE" "$WEB_PID_FILE"

echo -e "\n${BOLD}${GREEN}✔ Scorva platform has been successfully shut down.${NC}\n"
