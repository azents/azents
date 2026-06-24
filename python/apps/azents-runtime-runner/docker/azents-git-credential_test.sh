#!/bin/sh
# azents-git-credential helper smoke test.

set -e

SCRIPT="$(dirname "$0")/azents-git-credential.sh"

if [ ! -x "$SCRIPT" ]; then
    chmod +x "$SCRIPT"
fi

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1" >&2; exit 1; }

result=$(GH_TOKEN="ghp_test_token_1" "$SCRIPT" get <<'EOF'
protocol=https
host=github.com
path=owner/repo.git
EOF
)
echo "$result" | grep -q "^protocol=https$" || fail "case1 missing protocol"
echo "$result" | grep -q "^host=github.com$" || fail "case1 missing host"
echo "$result" | grep -q "^username=x-access-token$" || fail "case1 missing username"
echo "$result" | grep -q "^password=ghp_test_token_1$" || fail "case1 missing/wrong password"
pass "case1: GH_TOKEN fallback"

result=$(unset GH_TOKEN; GITHUB_TOKEN="ghs_installation_xxx" "$SCRIPT" get <<'EOF'
protocol=https
host=github.com
path=owner/repo.git
EOF
)
echo "$result" | grep -q "^password=ghs_installation_xxx$" || fail "case2 GITHUB_TOKEN fallback"
pass "case2: GITHUB_TOKEN fallback"

map='{"azents":{"installation_id":"101","env":"GITHUB_TOKEN_INSTALLATION_101"},"hardtack":{"installation_id":"202","env":"GITHUB_TOKEN_INSTALLATION_202"}}'
result=$(GITHUB_INSTALLATION_MAP="$map" GITHUB_TOKEN_INSTALLATION_101="ghs_azents" GITHUB_TOKEN_INSTALLATION_202="ghs_hardtack" "$SCRIPT" get <<'EOF'
protocol=https
host=github.com
path=hardtack/repo.git
EOF
)
echo "$result" | grep -q "^password=ghs_hardtack$" || fail "case3 hardtack token"
pass "case3: multi-installation owner routing"

result=$(GITHUB_INSTALLATION_MAP="$map" GITHUB_TOKEN_INSTALLATION_101="ghs_azents" "$SCRIPT" get <<'EOF'
protocol=https
host=github.com
path=azents/repo.git
EOF
)
echo "$result" | grep -q "^password=ghs_azents$" || fail "case4 azents token"
pass "case4: multi-installation owner routing with another owner"

result=$(GH_TOKEN="ghp_test" "$SCRIPT" get <<'EOF'
protocol=https
host=example.com
path=owner/repo.git
EOF
)
if [ -n "$result" ]; then
    fail "case5 expected empty output for non-GitHub host"
fi
pass "case5: ignore non-GitHub host"

result=$(unset GH_TOKEN GITHUB_TOKEN GITHUB_INSTALLATION_MAP; "$SCRIPT" get <<'EOF'
protocol=https
host=github.com
path=owner/repo.git
EOF
)
if [ -n "$result" ]; then
    fail "case6 expected empty output, got: $result"
fi
pass "case6: empty response when no token"

result=$(GH_TOKEN="ghp_test" "$SCRIPT" store <<'EOF'
protocol=https
host=github.com
username=x-access-token
password=ghp_test
EOF
)
if [ -n "$result" ]; then
    fail "case7 store expected no output, got: $result"
fi
pass "case7: store action silently ignored"

echo "=== All tests passed ==="
