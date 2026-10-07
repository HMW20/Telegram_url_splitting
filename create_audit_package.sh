#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="${HOME}/projects/Telegram_url_splitting"
TIMESTAMP="$(date '+%Y-%m-%d_%H-%M-%S')"
AUDIT_DIR="${PROJECT_DIR}/Telegram-Splitter-Audit-${TIMESTAMP}"
ARCHIVE="${PROJECT_DIR}/Telegram-Splitter-Audit-${TIMESTAMP}.tar.gz"

cleanup() {
    rm -f "${AUDIT_DIR}/.env" 2>/dev/null || true
}
trap cleanup EXIT

echo "=============================================="
echo " Telegram Splitter - Audit Package Generator"
echo "=============================================="
echo

if [[ ! -d "${PROJECT_DIR}" ]]; then
    echo "ERROR: Project directory not found:"
    echo "${PROJECT_DIR}"
    exit 1
fi

cd "${PROJECT_DIR}"

mkdir -p \
    "${AUDIT_DIR}/source" \
    "${AUDIT_DIR}/system" \
    "${AUDIT_DIR}/configuration" \
    "${AUDIT_DIR}/logs" \
    "${AUDIT_DIR}/tests"

chmod 700 "${AUDIT_DIR}"

echo "[1/10] Collecting project files..."

# Copy source/configuration files that are useful for review.
# Explicitly exclude secrets and runtime/generated data.
for file in \
    bot.py \
    requirements.txt \
    Dockerfile \
    docker-compose.yml \
    compose.yml \
    README.md \
    .gitignore \
    pyproject.toml \
    setup.py
do
    if [[ -f "${PROJECT_DIR}/${file}" ]]; then
        cp -p "${PROJECT_DIR}/${file}" "${AUDIT_DIR}/source/"
    fi
done

# Collect Python files from the project, excluding virtualenv,
# caches, Git data and generated/runtime directories.
find "${PROJECT_DIR}" \
    -type f \
    -name "*.py" \
    -not -path "${PROJECT_DIR}/.venv/*" \
    -not -path "${PROJECT_DIR}/venv/*" \
    -not -path "${PROJECT_DIR}/__pycache__/*" \
    -not -path "${PROJECT_DIR}/.git/*" \
    -not -path "${PROJECT_DIR}/Telegram-Splitter-Audit-*/*" \
    -print0 2>/dev/null |
while IFS= read -r -d '' file; do
    rel="${file#${PROJECT_DIR}/}"
    mkdir -p "${AUDIT_DIR}/source/$(dirname "${rel}")"
    cp -p "${file}" "${AUDIT_DIR}/source/${rel}"
done

echo "[2/10] Collecting system information..."

{
    echo "===== DATE ====="
    date
    echo

    echo "===== HOSTNAME ====="
    hostname
    echo

    echo "===== OS ====="
    if [[ -f /etc/os-release ]]; then
        cat /etc/os-release
    fi
    echo

    echo "===== KERNEL ====="
    uname -a
    echo

    echo "===== ARCHITECTURE ====="
    uname -m
    echo

    echo "===== UPTIME ====="
    uptime
} > "${AUDIT_DIR}/system/system_info.txt" 2>&1 || true

{
    echo "===== CPU ====="
    if command -v lscpu >/dev/null 2>&1; then
        lscpu
    fi
    echo

    echo "===== MEMORY ====="
    free -h
    echo

    echo "===== DISK ====="
    df -h
    echo

    echo "===== INODE USAGE ====="
    df -ih
} > "${AUDIT_DIR}/system/resources.txt" 2>&1 || true

echo "[3/10] Collecting software versions..."

{
    echo "===== PYTHON ====="
    python3 --version 2>&1 || true
    echo

    echo "===== VIRTUALENV PYTHON ====="
    if [[ -x "${PROJECT_DIR}/.venv/bin/python" ]]; then
        "${PROJECT_DIR}/.venv/bin/python" --version 2>&1 || true
    fi
    echo

    echo "===== PIP PACKAGES ====="
    if [[ -x "${PROJECT_DIR}/.venv/bin/pip" ]]; then
        "${PROJECT_DIR}/.venv/bin/pip" list 2>&1 || true
    fi
    echo

    echo "===== ARIA2 ====="
    if command -v aria2c >/dev/null 2>&1; then
        aria2c --version 2>&1 || true
    else
        echo "aria2c: NOT FOUND"
    fi
    echo

    echo "===== 7-ZIP ====="
    if command -v 7z >/dev/null 2>&1; then
        7z i 2>&1 | head -40 || true
    elif command -v 7zz >/dev/null 2>&1; then
        7zz i 2>&1 | head -40 || true
    else
        echo "7-Zip: NOT FOUND"
    fi
    echo

    echo "===== FFMPEG ====="
    if command -v ffmpeg >/dev/null 2>&1; then
        ffmpeg -version 2>&1 | head -5 || true
    else
        echo "ffmpeg: NOT FOUND"
    fi

} > "${AUDIT_DIR}/system/software_versions.txt" 2>&1

echo "[4/10] Collecting project structure..."

{
    echo "Project directory:"
    echo "${PROJECT_DIR}"
    echo

    echo "===== FILE TREE ====="

    if command -v tree >/dev/null 2>&1; then
        tree -a -L 3 \
            -I '.venv|venv|__pycache__|.git|*.pyc|Telegram-Splitter-Audit-*' \
            "${PROJECT_DIR}" 2>&1 || true
    else
        find "${PROJECT_DIR}" \
            -maxdepth 3 \
            -not -path "${PROJECT_DIR}/.venv*" \
            -not -path "${PROJECT_DIR}/venv*" \
            -not -path "${PROJECT_DIR}/.git*" \
            -not -path "${PROJECT_DIR}/__pycache__*" \
            -not -name "*.pyc" \
            -print 2>/dev/null | sort
    fi

} > "${AUDIT_DIR}/system/project_structure.txt"

echo "[5/10] Collecting systemd service information..."

{
    echo "===== SERVICE STATUS ====="
    systemctl status telegram-splitter.service --no-pager 2>&1 || true
    echo

    echo "===== SERVICE UNIT ====="
    systemctl cat telegram-splitter.service 2>&1 || true
    echo

    echo "===== ENABLED / ACTIVE ====="
    systemctl is-enabled telegram-splitter.service 2>&1 || true
    systemctl is-active telegram-splitter.service 2>&1 || true
} > "${AUDIT_DIR}/system/systemd_service.txt"

echo "[6/10] Collecting recent logs..."

{
    echo "===== LAST 500 SERVICE LOG LINES ====="
    journalctl -u telegram-splitter.service -n 500 --no-pager 2>&1 || true
} > "${AUDIT_DIR}/logs/recent_service_log.txt"

{
    echo "===== SERVICE LOG SINCE LAST 24 HOURS ====="
    journalctl -u telegram-splitter.service --since "24 hours ago" --no-pager 2>&1 || true
} > "${AUDIT_DIR}/logs/service_last_24h.txt"

echo "[7/10] Collecting networking information..."

{
    echo "===== LISTENING SOCKETS ====="
    if command -v ss >/dev/null 2>&1; then
        ss -lntup 2>&1 || true
    fi
    echo

    echo "===== FIREWALL ====="
    if command -v ufw >/dev/null 2>&1; then
        sudo ufw status verbose 2>&1 || true
    else
        echo "ufw: NOT INSTALLED"
    fi
    echo

    echo "===== ROUTING ====="
    ip route 2>&1 || true
} > "${AUDIT_DIR}/system/networking.txt"

echo "[8/10] Collecting process and resource information..."

{
    echo "===== TOP PROCESSES ====="
    ps aux --sort=-%mem | head -30 2>&1 || true
    echo

    echo "===== TELEGRAM SPLITTER PROCESSES ====="
    ps aux | grep -E 'telegram|bot.py|aria2|7z|7zz' | grep -v grep 2>&1 || true
} > "${AUDIT_DIR}/system/processes.txt"

echo "[9/10] Running safe code/environment checks..."

{
    echo "===== PYTHON SYNTAX CHECK ====="

    if [[ -x "${PROJECT_DIR}/.venv/bin/python" ]]; then
        PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"
    else
        PYTHON_BIN="python3"
    fi

    if [[ -f "${PROJECT_DIR}/bot.py" ]]; then
        "${PYTHON_BIN}" -m py_compile "${PROJECT_DIR}/bot.py" 2>&1 || true
    else
        echo "bot.py not found"
    fi

    echo
    echo "===== PYTHON IMPORT CHECK ====="

    if [[ -f "${PROJECT_DIR}/bot.py" ]]; then
        (
            cd "${PROJECT_DIR}"
            "${PYTHON_BIN}" -c 'import bot; print("IMPORT_OK")' 2>&1
        ) || true
    fi

    echo
    echo "===== PROJECT REQUIREMENTS ====="

    if [[ -f "${PROJECT_DIR}/requirements.txt" ]]; then
        cat "${PROJECT_DIR}/requirements.txt"
    else
        echo "requirements.txt not found"
    fi

} > "${AUDIT_DIR}/tests/basic_checks.txt" 2>&1

echo "[10/10] Creating security/redaction documentation..."

cat > "${AUDIT_DIR}/SECURITY-NOTES.md" <<'EOF'
# Security and Privacy Notes

This audit package was generated for external technical/security review.

## Intentionally excluded

The following sensitive materials were NOT copied:

- `.env`
- SSH private keys
- private keys
- Telegram session files
- cookies
- cloud credentials
- passwords
- API secrets
- bot tokens
- authentication databases
- virtual environment contents
- Git object database
- large runtime/download files

## Important

This package is intended for code and infrastructure review.

It should still be treated as potentially sensitive because it may contain:

- server paths
- usernames
- IP addresses
- service configuration
- log messages
- software versions
- operational information

Review the generated package before sharing it publicly.
EOF

cat > "${AUDIT_DIR}/AUDIT-INSTRUCTIONS.md" <<'EOF'
# Telegram Splitter - Audit Instructions

You are reviewing a production Telegram file-splitting/download bot.

The project currently has the following intended behavior:

1. Files smaller than 1000 MiB:
   - Download normally.
   - Send directly to Telegram.
   - Do NOT split or archive.
   - Preserve the original filename and extension.
   - Preserve the appropriate Telegram media type when supported.

2. Files 1000 MiB or larger:
   - Download the file.
   - Split it into 1000 MiB parts.
   - Upload the parts to Telegram.
   - Clean up temporary files when appropriate.

3. The project uses:
   - Python
   - Pyrogram
   - aria2c
   - 7-Zip
   - systemd
   - Ubuntu

4. Social-media downloading is NOT part of the current project.
   YouTube, TikTok, Instagram and Facebook support was removed.

## Review objectives

Perform a comprehensive review covering:

### A. Correctness
- Logic errors
- Edge cases
- Incorrect assumptions
- Broken state transitions
- Filename/extension handling
- File-size boundary behavior
- Telegram media handling

### B. Reliability
- Crashes
- Unhandled exceptions
- asyncio problems
- race conditions
- deadlocks
- stuck queue items
- failed downloads
- failed uploads
- failed splitting
- cancellation behavior
- restart/recovery behavior
- cleanup failures
- disk exhaustion
- memory exhaustion

### C. Security
Look specifically for:
- command injection
- path traversal
- unsafe subprocess usage
- malicious filenames
- malicious URLs
- arbitrary file access
- symlink problems
- insecure temporary files
- permission problems
- secret leakage
- denial-of-service possibilities
- resource exhaustion

### D. Concurrency
Test reasoning around:
- multiple users
- multiple simultaneous requests
- queue behavior
- cancellation
- duplicate requests
- simultaneous file operations
- service restart during an active job

### E. External dependencies
Review interaction with:
- aria2c
- 7-Zip
- Telegram/Pyrogram
- systemd
- filesystem

### F. Operational reliability
Check:
- logging
- restart policy
- failure recovery
- disk usage
- stale files
- orphan processes
- temporary-file cleanup
- long-running stability

### G. Testing

Suggest concrete tests for every important problem.

For each finding, report:

- Severity: Critical / High / Medium / Low / Informational
- Exact file
- Exact function or line if possible
- Why it is a problem
- Realistic failure scenario
- How to reproduce it
- Recommended fix
- Whether the issue can cause the entire bot to stop

Do NOT assume that a problem is fixed merely because the code appears reasonable.

Distinguish clearly between:
- confirmed vulnerabilities
- likely bugs
- potential risks
- recommendations

Do not invent missing information.
EOF

echo
echo "===== Creating checksums ====="

if command -v sha256sum >/dev/null 2>&1; then
    (
        cd "${AUDIT_DIR}"
        find . -type f -print0 |
            sort -z |
            xargs -0 sha256sum
    ) > "${AUDIT_DIR}/SHA256SUMS.txt" 2>/dev/null || true
fi

echo "===== Creating archive ====="

tar \
    --exclude='*.env' \
    --exclude='.env' \
    --exclude='*.key' \
    --exclude='*.pem' \
    --exclude='*.p12' \
    --exclude='*.pfx' \
    --exclude='Telegram-Splitter-Audit-*.tar.gz' \
    -czf "${ARCHIVE}" \
    -C "${PROJECT_DIR}" \
    "$(basename "${AUDIT_DIR}")"

chmod 600 "${ARCHIVE}"

echo
echo "=============================================="
echo " AUDIT PACKAGE CREATED SUCCESSFULLY"
echo "=============================================="
echo
echo "Directory:"
echo "${AUDIT_DIR}"
echo
echo "Archive:"
echo "${ARCHIVE}"
echo
echo "Size:"
ls -lh "${ARCHIVE}"
echo
echo "IMPORTANT:"
echo "Review the package before sharing it with anyone."
echo "The script did NOT modify bot.py or restart the service."
echo
