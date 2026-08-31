#!/data/data/com.termux/files/usr/bin/bash
set -uo pipefail

PROOT_DISTRO="${JOBTOMATIK_PROOT_DISTRO:-ubuntu}"
PROOT_REPO="${JOBTOMATIK_PROOT_REPO:-/root/JobTomatik}"
PILOT_COMMAND="${JOBTOMATIK_PILOT_COMMAND:-jobtomatik-pilot}"
CONTROL_DIR="${JOBTOMATIK_PILOT_CONTROL_DIR:-/tmp/jobtomatik-pilot-control}"
HEARTBEAT_PATH="$CONTROL_DIR/controller-heartbeat"
POLL_SECONDS="${JOBTOMATIK_PILOT_CONTROL_POLL_SECONDS:-1}"
SELF_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SELF_DIGEST="$(sha256sum "$SELF_PATH" | awk '{print $1}')"

mkdir -p "$CONTROL_DIR"
chmod 700 "$CONTROL_DIR" 2>/dev/null || true

run_bridge() {
  local action="$1"
  shift || true
  local command quoted arg
  printf -v command "set -e; cd %q; .venv/bin/python scripts/lever_supervised_pilot_control_bridge.py %q --control-dir %q" \
    "$PROOT_REPO/backend" "$action" "$CONTROL_DIR"
  for arg in "$@"; do
    printf -v quoted "%q" "$arg"
    command+=" $quoted"
  done
  proot-distro login "$PROOT_DISTRO" --shared-tmp -- bash -lc "$command"
}

write_heartbeat() {
  local temporary="${HEARTBEAT_PATH}.tmp.$$"
  printf '%s\n' "$$" > "$temporary"
  chmod 600 "$temporary" 2>/dev/null || true
  mv -f "$temporary" "$HEARTBEAT_PATH"
}

reload_if_replaced() {
  local current_digest
  current_digest="$(sha256sum "$SELF_PATH" 2>/dev/null | awk '{print $1}')"
  if [[ -n "$current_digest" && "$current_digest" != "$SELF_DIGEST" ]]; then
    echo "JOBTOMATIK_PILOT_CONTROLLER_REEXECUTING_UPDATED_BINARY"
    exec "$SELF_PATH"
  fi
}

complete_request() {
  local request_id="$1"
  local outcome="$2"
  local exit_code="$3"
  run_bridge complete-request \
    --request-id "$request_id" \
    --outcome "$outcome" \
    --exit-code "$exit_code"
}

# An inflight request means a previous controller died after the request was claimed.
# Never replay it automatically. Record an uncertain operator-control outcome and let
# the independently verified runtime lease tell the UI whether an arm actually landed.
run_bridge recover-inflight >/dev/null 2>&1 || true

while true; do
  reload_if_replaced
  write_heartbeat

  if [[ -f "$CONTROL_DIR/request.json" ]]; then
    claim_output=""
    if claim_output="$(run_bridge claim-request 2>&1)"; then
      request_id=""
      action=""
      application_id=""
      IFS=$'\t' read -r request_id action application_id <<< "$claim_output"

      if [[ -z "$request_id" || ( "$action" != "arm" && "$action" != "disarm" ) ]]; then
        echo "JOBTOMATIK_PILOT_CONTROL_INVALID_CLAIM output=$claim_output" >&2
      else
        echo "JOBTOMATIK_PILOT_CONTROL_CLAIMED request_id=$request_id action=$action application_id=$application_id"
        "$PILOT_COMMAND" "$action"
        action_exit=$?

        if [[ "$action_exit" -eq 0 ]]; then
          if ! complete_request "$request_id" success 0; then
            echo "JOBTOMATIK_PILOT_CONTROL_COMPLETE_FAILED request_id=$request_id outcome=success" >&2
          fi
        else
          if ! complete_request "$request_id" failed "$action_exit"; then
            echo "JOBTOMATIK_PILOT_CONTROL_COMPLETE_FAILED request_id=$request_id outcome=failed exit_code=$action_exit" >&2
          fi
        fi
      fi
    else
      claim_exit=$?
      # Exit 3 is the bridge's ordinary "nothing claimable" result, including an
      # expired request that it already removed and recorded. Other failures are
      # logged but never cause automatic execution.
      if [[ "$claim_exit" -ne 3 ]]; then
        echo "JOBTOMATIK_PILOT_CONTROL_CLAIM_FAILED exit_code=$claim_exit detail=$claim_output" >&2
      fi
    fi
  fi

  sleep "$POLL_SECONDS"
done
