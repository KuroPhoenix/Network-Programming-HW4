#!/usr/bin/env bash
#!/usr/bin/env bash
# Starts the two servers in a single tmux session with separate windows.
# Usage: ./run.sh

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv_dir="${root}/.venv"

# Create/activate virtualenv
if [ ! -d "$venv_dir" ]; then
  echo "Creating virtualenv at $venv_dir"
  python3 -m venv "$venv_dir"
fi
# shellcheck disable=SC1090
source "$venv_dir/bin/activate"
PYTHON="$venv_dir/bin/python"

# Ensure dependency
if ! "$PYTHON" -c "import loguru" >/dev/null 2>&1; then
  echo "Installing loguru into venv..."
  "$PYTHON" -m pip install --quiet loguru
fi

export PYTHONPATH="${root}:${PYTHONPATH:-}"

TMUX_BIN=$(command -v tmux || true)
if [ -z "$TMUX_BIN" ]; then
  echo "tmux is required. Please install tmux and re-run."
  exit 1
fi

session="hw3"

# Kill any existing session with the same name.
"$TMUX_BIN" kill-session -t "$session" 2>/dev/null || true

cmd_env="PYTHONPATH=\"$root\""

start_session_window() {
  local name="$1"
  shift
  local cmd_str
  cmd_str=$(printf "%q " "$@")
  cmd_str=${cmd_str% }
  "$TMUX_BIN" new-session -d -s "$session" -n "$name"
  "$TMUX_BIN" send-keys -t "$session:$name" "cd '$root'" C-m
  "$TMUX_BIN" send-keys -t "$session:$name" "clear" C-m
  "$TMUX_BIN" send-keys -t "$session:$name" "export $cmd_env" C-m
  "$TMUX_BIN" send-keys -t "$session:$name" "$cmd_str" C-m
}

start_window() {
  local name="$1"
  shift
  local cmd_str
  cmd_str=$(printf "%q " "$@")
  cmd_str=${cmd_str% }
  "$TMUX_BIN" new-window -t "$session" -n "$name"
  "$TMUX_BIN" send-keys -t "$session:$name" "cd '$root'" C-m
  "$TMUX_BIN" send-keys -t "$session:$name" "clear" C-m
  "$TMUX_BIN" send-keys -t "$session:$name" "export $cmd_env" C-m
  "$TMUX_BIN" send-keys -t "$session:$name" "$cmd_str" C-m
}

# Wait until a TCP port is accepting connections.
wait_for_port() {
  local host="$1"
  local port="$2"
  local label="$3"
  local timeout=15
  local start=$SECONDS
  while true; do
    "$PYTHON" - "$host" "$port" <<'PY' >/dev/null 2>&1
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
s = socket.socket()
s.settimeout(1)
try:
    s.connect((host, port))
    sys.exit(0)
except Exception:
    sys.exit(1)
finally:
    s.close()
PY
    if [ $? -eq 0 ]; then
      break
    fi
    if (( SECONDS - start >= timeout )); then
      echo "Timed out waiting for $label on $host:$port"
      return 1
    fi
    sleep 1
  done
}

# Start session with user_server.
start_session_window "user_server" "$PYTHON" -u -m server.user_server
# Add dev_server window.
start_window "dev_server" "$PYTHON" -u -m server.dev_server

# Wait for servers to listen.
if ! wait_for_port "127.0.0.1" 16534 "user_server"; then
  "$TMUX_BIN" kill-session -t "$session"
  exit 1
fi
if ! wait_for_port "127.0.0.1" 16533 "dev_server"; then
  "$TMUX_BIN" kill-session -t "$session"
  exit 1
fi

echo "tmux session '$session' started with windows: user_server, dev_server."
if [ -t 1 ]; then
  "$TMUX_BIN" attach -t "$session"
else
  echo "Not a TTY; attach manually with: tmux attach -t $session"
fi
