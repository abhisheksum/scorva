#!/usr/bin/env bash
# ==============================================================================
# Scorva — Service Status Utility
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

echo -e "\n${BOLD}${CYAN}======================================================${NC}"
echo -e "${BOLD}${CYAN}            Scorva Platform Status                     ${NC}"
echo -e "${BOLD}${CYAN}======================================================${NC}\n"

format_status() {
    local status="$1"
    if [ "$status" = "RUNNING" ] || [ "$status" = "healthy" ]; then
        echo -e "${GREEN}${BOLD}RUNNING${NC}"
    elif [ "$status" = "STOPPED" ]; then
        echo -e "${RED}STOPPED${NC}"
    elif [ "$status" = "DEGRADED" ]; then
        echo -e "${YELLOW}DEGRADED${NC}"
    else
        echo -e "${YELLOW}${status}${NC}"
    fi
}

# 1. Check Next.js Frontend
echo -e "${BOLD}Frontend Web Application:${NC}"
WEB_PID=$(get_running_pid "$WEB_PID_FILE" || true)
if is_port_listening "$WEB_PORT"; then
    ACTIVE_PID=${WEB_PID:-$(get_pid_on_port "$WEB_PORT")}
    echo -e "  • Status: $(format_status RUNNING) (Port: ${WEB_PORT}, PID: ${ACTIVE_PID:-unknown})"
    echo -e "  • URL:    ${CYAN}http://localhost:${WEB_PORT}/admin${NC}"
else
    echo -e "  • Status: $(format_status STOPPED) (Port: ${WEB_PORT} not listening)"
fi

# 2. Check FastAPI Backend
echo -e "\n${BOLD}Backend Platform API:${NC}"
API_PID=$(get_running_pid "$API_PID_FILE" || true)
if is_port_listening "$API_PORT"; then
    ACTIVE_PID=${API_PID:-$(get_pid_on_port "$API_PORT")}
    HEALTH_JSON=$(curl -s "http://127.0.0.1:${API_PORT}/api/v1/health" 2>/dev/null || true)
    HEALTH_STATUS=$(echo "$HEALTH_JSON" | grep -o '"status":"[^"]*"' | head -n 1 | cut -d: -f2 | tr -d '"' || echo "active")
    echo -e "  • Status: $(format_status RUNNING) [Health: ${HEALTH_STATUS:-healthy}] (Port: ${API_PORT}, PID: ${ACTIVE_PID:-unknown})"
    echo -e "  • URL:    ${CYAN}http://localhost:${API_PORT}${NC}"
    echo -e "  • Docs:   ${CYAN}http://localhost:${API_PORT}/docs${NC}"
else
    echo -e "  • Status: $(format_status STOPPED) (Port: ${API_PORT} not listening)"
fi

# 3. Check Docker Infrastructure Containers
echo -e "\n${BOLD}Infrastructure Containers (Docker):${NC}"
if docker info >/dev/null 2>&1; then
    docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || docker compose ps
else
    echo -e "  • Docker daemon is ${RED}NOT RUNNING${NC} or inaccessible."
fi

# 4. Log Files Information
echo -e "\n${BOLD}Runtime Log Files:${NC}"
if [ -f "$API_LOG_FILE" ]; then
    API_SIZE=$(du -h "$API_LOG_FILE" 2>/dev/null | awk '{print $1}')
    echo -e "  • API Log:  ${DIM}${API_LOG_FILE}${NC} (${API_SIZE:-0B})"
fi
if [ -f "$WEB_LOG_FILE" ]; then
    WEB_SIZE=$(du -h "$WEB_LOG_FILE" 2>/dev/null | awk '{print $1}')
    echo -e "  • Web Log:  ${DIM}${WEB_LOG_FILE}${NC} (${WEB_SIZE:-0B})"
fi

echo ""
