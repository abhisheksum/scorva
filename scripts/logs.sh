#!/usr/bin/env bash
# ==============================================================================
# Scorva — Log Viewing Utility
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

TARGET="all"
LINES=50

usage() {
    cat <<EOF
${BOLD}Scorva Log Viewing Utility${NC}

${BOLD}Usage:${NC}
  ./scripts/logs.sh [target] [-n lines]

${BOLD}Targets:${NC}
  all       Tail both API and Web logs (default)
  api       Tail FastAPI backend logs only (.run/logs/api.log)
  web       Tail Next.js frontend logs only (.run/logs/web.log)
  docker    Follow Docker Compose container logs (docker compose logs -f)
  -h, --help Show this help message

EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        all|api|web|docker)
            TARGET="$1"
            shift
            ;;
        -n)
            LINES="$2"
            shift 2
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

ensure_run_dirs

case "$TARGET" in
    api)
        touch "${API_LOG_FILE}"
        echo -e "${CYAN}Tailing FastAPI logs (${API_LOG_FILE})...${NC}"
        tail -n "${LINES}" -f "${API_LOG_FILE}"
        ;;
    web)
        touch "${WEB_LOG_FILE}"
        echo -e "${CYAN}Tailing Next.js logs (${WEB_LOG_FILE})...${NC}"
        tail -n "${LINES}" -f "${WEB_LOG_FILE}"
        ;;
    docker)
        echo -e "${CYAN}Following Docker Compose logs...${NC}"
        docker compose logs -f --tail="${LINES}"
        ;;
    all)
        touch "${API_LOG_FILE}" "${WEB_LOG_FILE}"
        echo -e "${CYAN}Tailing all application logs (.run/logs/)...${NC}"
        tail -n "${LINES}" -f "${API_LOG_FILE}" "${WEB_LOG_FILE}"
        ;;
esac
