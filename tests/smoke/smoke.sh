#!/usr/bin/env bash
# End-to-end smoke test against a running stack (docker compose up).
#   API_URL=http://localhost:8000 WEB_URL=http://localhost:3000 ./tests/smoke/smoke.sh
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
WEB_URL="${WEB_URL:-http://localhost:3000}"
TIMEOUT="${SMOKE_TIMEOUT:-180}"

wait_for() {
  local url=$1 deadline=$((SECONDS + TIMEOUT))
  until curl -fsS -o /dev/null "$url"; do
    if ((SECONDS > deadline)); then echo "timeout waiting for $url" >&2; return 1; fi
    sleep 3
  done
}

echo "waiting for API and web..."
wait_for "$API_URL/health"
wait_for "$WEB_URL/"

python3 - "$API_URL" <<'PY'
import json, sys, urllib.request

api = sys.argv[1]

def get(path):
    with urllib.request.urlopen(api + path, timeout=10) as r:
        return json.load(r)

health = get("/health")
assert health["status"] == "ok", health
fixtures = get("/fixtures?days=7")["fixtures"]
assert fixtures, "no fixtures - did the seed run?"
picked, teams = [], set()
for f in fixtures:
    pair = {f["home_team"]["id"], f["away_team"]["id"]}
    if f["prediction_id"] and f["status"] == "scheduled" and not pair & teams:
        picked.append(f); teams |= pair
assert len(picked) >= 2, "need two predicted fixtures"
pred = get(f"/fixtures/{picked[0]['id']}/prediction")
assert abs(sum(pred["probabilities"].values()) - 1) < 1e-6
assert abs(sum(pred["fair_market_probabilities"].values()) - 1) < 1e-9
body = json.dumps({"selections": [{"fixture_id": f["id"], "outcome": "HOME"} for f in picked[:2]]})
req = urllib.request.Request(api + "/combinations/analyze", data=body.encode(),
                             headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=10) as r:
    combo = json.load(r)
assert combo["method"] == "independence_approximation" and combo["is_approximation"] is True
pick = get("/picks/today")
assert pick["status"] in {"scheduled", "published", "no_qualifying_match", "no_matches",
                          "voided", "settled"}, pick["status"]
assert pick["is_demo"] is True, "mock data must be flagged as demo"
assert get("/picks/today")["pick_id"] == pick["pick_id"], "pick changed on refresh"
assert "summary" in get("/picks/history")
perf = get("/performance")
assert perf["evaluation"] is not None, "seed should import the backtest report"
assert get("/status/data")["last_success_at"], "no successful ingestion run logged"
print(f"API ok: {len(fixtures)} fixtures this week, combination EV {combo['expected_value']:+.3f}, "
      f"today's pick: {pick['status']}")
PY

for path in / "/?range=week" /combinations /methodology /guide /picks /performance; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "$WEB_URL$path")
  [[ "$code" == "200" ]] || { echo "web $path -> $code" >&2; exit 1; }
done
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST -H 'Content-Type: application/json' \
  -d '{"selections":[]}' "$WEB_URL/api/combinations")
[[ "$code" == "422" ]] || { echo "web proxy validation -> $code" >&2; exit 1; }
echo "web ok"
echo "SMOKE TEST PASSED"
