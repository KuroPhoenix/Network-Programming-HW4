# Stabilization and Protocol Plan

This document contains two parts:
1) Comments on the current implementation (root causes of the buggy behavior).
2) A proposed, detailed solution plan to make the orchestrator robust and more "universal."

No code changes are made here; this is a design and execution plan.

## Scope and goals
- Target system: lobby -> spawn game server -> spawn local clients -> report game result.
- Primary goal: deterministic, race-free launching and cleanup in multi-client, real-world usage.
- Secondary goal: a clear, enforceable control-plane protocol (server <-> platform).
- Out of scope for now: rewriting game logic or designing a universal gameplay protocol.

## Feedback integration decisions
- Accept: random per-launch client/report tokens plus `match_id` to prevent spoofing and stale reports; add to Phase 0.
- Accept: validate reports using both `report_token` and `match_id`; ignore stale or mismatched reports.
- Accept: pre-generate and store expected `client_token`/`report_token`/`match_id` under lock before spawn to avoid STARTED races.
- Accept: separate bind host vs advertised host; add `bind_host` placeholder and default to `0.0.0.0`.
- Accept: define roles (`report_token` = auth secret, `client_token` = client auth, `match_id` = correlation) and log tokens only in redacted form.
- Accept: extend END payload with a universal `results` list for multi-player games.
- Accept: NDJSON hardening with max line size, rate limits, and report socket timeouts.
- Accept: explicit rate-limit policy (drop with cooldown, warn, disconnect on sustained abuse).
- Accept: define `players_json_path` lifecycle and cleanup via per-match temp directory.
- Accept: match-scoped stop/kill (do not stop if match_id changed).
- Accept: keep client launch gated to IN_GAME only; no early-connect retries in v1.
- Accept: define STARTED semantics checklist (bind, init, auth ready, handshake ready).
- Accept: avoid `bind_host` as a healthcheck connect target.
- Accept: define client<->server handshake v1 fields and responses.
- Accept: expose match_id in snapshots from STARTING onward (non-secret).
- Accept: move tokens to env/file transport; do not pass tokens via CLI args.
- Accept: specify `results` minimal schema and allow extras.
- Accept: harden temp dir cleanup rules (age + lease/PID or running-room check).
- Accept: split client_token vs report_token roles (may be equal but treated distinctly).
- Accept: avoid blocking process stop/kill while holding the room lock; mark intent under lock, stop outside.
- Accept: healthcheck host fallback (try 127.0.0.1, then configured host) and allow manifest override.
- Accept: treat STARTED as the sole readiness gate; TCP healthcheck is diagnostic only (not a readiness signal).
- Accept: heartbeat tolerance (warn at ~3x interval, kill at ~5x) to avoid false kills.
- Accept: add stable identifiers to context (`match_id`, `platform_protocol_version`, `players_json_path`).
- Partial: watchdog threading consolidation deferred to a later phase; per-room watchers are acceptable for class scope.
- Partial: Windows process tree kill remains best-effort without job objects; document limitation.
- Accept: NDJSON parsing hardening (log + drop bad line; do not drop connection).

## Comments on current behavior (root causes tied to code)
Note: the current code uses a single room token for both client auth and report auth; the proposed plan splits these into `client_token` and `report_token`.

### 1) Room state visibility is not atomic (race / stale reads)
Observed behavior:
- Clients sometimes see "IN_GAME" but still receive no port/token.
- Non-hosts launch early and fail with "missing launch info" or connection errors.

Why it happens:
- `RoomGenie.start_game()` updates room state in a multi-step sequence:
  - sets `room.status = "IN_GAME"`
  - launches game server (can take time)
  - then sets `room.port`, `room.token`, `room.server_pid`
- `RoomGenie.get_room()` returns the live room object without locking.
- `server/core/handlers/lobby_handler.py` calls `genie.get_room()` without a lock.

Concrete code paths:
- `server/core/room_genie.py`:
  - `RoomGenie.get_room()` returns the object directly.
  - `RoomGenie.start_game()` sets `status` before port/token.
- `server/core/handlers/lobby_handler.py:get_room()` uses `asdict(room)` on a potentially half-updated room.
- `user/user_cli.py` and `user/api/user_api.py` treat `status == "IN_GAME"` as a launch signal.

Impact:
- The UI can immediately attempt client launch when `status == "IN_GAME"` even though port/token are still None.
- This is a direct cause of flaky demos.

Severity: High.

Minimal fix idea:
- Do not expose "IN_GAME" until port/client_token are set.
- Add a transitional state like "STARTING" so clients know to wait.
- Make `get_room()` return a snapshot created under lock (or add `snapshot_room`).

---

### 2) Launcher does not verify server readiness (only checks early exit)
Observed behavior:
- Clients attempt to connect before server is listening.
- "Connection refused" / "timeout" appears randomly.
- Adding manual delays makes failures disappear.

Why it happens:
- `GameLauncher._wait_for_process_start()` only checks if process exited immediately.
- There is no TCP readiness check or report-based readiness.
- Manifests include a `healthcheck` section, but it is unused.

Concrete code paths:
- `server/core/game_launcher.py`:
  - `_wait_for_process_start()` uses `proc.poll()` only.
  - `launch_room()` never tests port bind.
- `server/cloudGames/*/manifest.json` includes `healthcheck.tcp_port`, but it is ignored.

Impact:
- The orchestrator returns launch info before the server is ready.
- Multi-client demo feels random and flaky.

Severity: High.

Minimal fix idea:
- Implement a TCP healthcheck for diagnostics.
- Gate readiness on STARTED (not on TCP connect).

---

### 3) Cleanup path is inconsistent depending on how the game ends
Observed behavior:
- If the game ends normally and reports `END`, ready flags are cleared.
- If the process exits without a report, ready flags stay set.
- This creates "phantom ready" states that mess up the next round.

Why it happens:
- `RoomGenie.game_ended_normally()` clears `ready_players`.
- `_watch_room()` resets status/port/token but does NOT clear `ready_players`.

Concrete code paths:
- `server/core/room_genie.py`:
  - `game_ended_normally()` -> `room.ready_players.clear()`.
  - `_watch_room()` -> resets status/port/token but keeps ready set.

Impact:
- Next game can start with stale readiness.
- Lobby shows confusing ready state.

Severity: High.

Minimal fix idea:
- In `_watch_room()` cleanup, also clear `ready_players`.
- Use a single shared cleanup helper to avoid divergence.

---

### 4) BigTwo server does not report end-of-game (manifest missing report args)
Observed behavior:
- BigTwo often ends without sending an END report.
- Watcher path is used instead of normal report path.

Why it happens:
- BigTwo manifest does not pass `--report_host`, `--report_port`, `--report_token`.
- Wordle does pass these arguments, so it reports correctly.

Concrete code paths:
- `server/cloudGames/BigTwo/1.0.0/manifest.json` missing report args.
- `server/cloudGames/Wordle/1.0.0/manifest.json` includes them.

Impact:
- BigTwo likely uses crash/exit path cleanup, which currently does not clear ready flags.

Severity: Medium (but visible).

Minimal fix idea:
- Add report args to BigTwo manifest (same as Wordle).

---

### 5) Hardcoded host IP makes demos brittle
Observed behavior:
- Server only works reliably on the machine/network matching `140.113.17.11`.
- Local testing or changing networks breaks connections.

Why it happens:
- `server/core/config.py` hardcodes `USER_SERVER_HOST` and `DEV_SERVER_HOST_IP`.

Impact:
- "Worked yesterday, fails today" demo behavior.
- Clients on different networks fail to connect.

Severity: Medium.

Minimal fix idea:
- Read host/ports from env vars or CLI args, with safe defaults.

---

### 6) Process management does not kill child processes (or process groups)
Observed behavior:
- After stop, ports sometimes remain in use.
- Game server "dies" but a child process can still bind or keep port.

Why it happens:
- `GameLauncher.stop_room()` only terminates the main process PID.
- If the game server spawns children, those can survive.

Impact:
- Port conflicts and zombie processes, especially on repeated launches.

Severity: Medium.

Minimal fix idea:
- Launch server in its own process group/session.
- Kill the whole group on stop.

---

### 7) Protocol simplicity makes noisy games easy to break
Observed behavior:
- Newline-delimited JSON is fragile if a game emits malformed JSON.
- No end-to-end request_id correlation.
- Any malformed line drops the connection.

Why it happens:
- Protocol uses NDJSON with no length framing.
- There is no backpressure or tolerance for stray output.

Impact:
- A single malformed line can cascade into disconnects.

Severity: Medium to Low (but frequent in real usage).

Minimal fix idea:
- Keep NDJSON for now but add:
  - strict, defensive parsing (drop bad line, keep connection).
  - optional length-prefix framing for v2.
  - request_id usage end-to-end for debugging.

---

### 8) "Universal" packaging is partial (player count and readiness not standardized)
Observed behavior:
- `GameLauncher` only injects `{p1}` and `{p2}` and `{player_name}`.
- Games needing more players have no standardized input list.
- `healthcheck` exists in manifests but unused.

Impact:
- "Universal" means "2-player only" right now.
- Multi-player game onboarding is ad-hoc.

Severity: Medium.

Minimal fix idea:
- Pass `players_json`, `players_csv`, `player_count`, and optional `{pN}`.
- Require new games to use the standardized fields.

---

### 9) Report token is deterministic and reusable (spoofing + stale report risk)
Observed behavior:
- The room token is derived from room_id (`room{room_id:06d}`).
- Tokens repeat if the same room_id is reused across launches.

Why it happens:
- `server/core/game_launcher.py` sets `token = f"room{room_id:06d}"`.
- `server/core/handlers/game_handler.py` only validates `report_token` against `room.token`.
- The current design uses a single token for both client auth and report auth.

Impact:
- Any process can guess tokens and spoof END/ERROR reports.
- Late reports from a previous launch can be accepted if the token is reused.

Severity: High (correctness) and Medium (security).

Minimal fix idea:
- Generate random per-launch `report_token` and `client_token` (128-bit hex).
- Add a per-launch `match_id` and require it in reports.
- Treat `report_token` and `client_token` as separate roles even if values match.

---

### 10) Blocking stop/kill operations occur while holding the room lock
Observed behavior:
- Some code paths call `gmLauncher.stop_room()` while the room lock is held.

Why it happens:
- `_clear_running()` is called from locked sections and immediately calls `gmLauncher.stop_room()`.
- `stop_room()` can block while terminating processes.

Impact:
- Lock contention and UI stalls.
- Risk of deadlocks if other handlers wait on the same lock.

Severity: Medium.

Minimal fix idea:
- Under lock: mark room as stopping and snapshot required fields.
- Outside lock: perform `stop_room()` and any blocking waits.
- Reacquire lock only for final, minimal updates if needed.

---

### 11) STARTED/report validation race (token/match_id not stored before spawn)
Observed behavior:
- A fast game server can report STARTED immediately after spawn.
- If the platform stores `report_token`/`match_id` only after launch completes, validation can race.

Impact:
- Valid STARTED reports can be rejected (flaky launch).
- Or STARTED is accepted without validation (correctness hole).

Minimal fix idea:
- Pre-generate `client_token`, `report_token`, and `match_id` under lock when setting STARTING.
- Store them before spawn, but keep them hidden from clients until IN_GAME.

---

### 12) Bind host vs advertised host is conflated
Observed behavior:
- The server bind address and the client connection address are assumed to be the same.

Impact:
- Binding to 127.0.0.1 passes healthcheck but remote clients cannot connect.
- Binding to a specific NIC can make localhost healthcheck fail even if clients can connect.

Minimal fix idea:
- Add `bind_host` placeholder (default `0.0.0.0`) for server bind.
- Keep `host` as the advertised client connection host.

---

### 13) Token vs match_id roles are not defined
Observed behavior:
- Both `token` and `match_id` exist but roles are not explicit.

Impact:
- Developers may log or reuse tokens incorrectly.
- Conformance tooling cannot enforce correct handling.

Minimal fix idea:
- Define `client_token` and `report_token` as capability secrets (auth).
- Define `match_id` as non-secret correlation ID.
- Log match_id freely; log only a redacted token prefix.

---

### 14) END payload is still 2-player centric
Observed behavior:
- END payload only specifies winner/loser.

Impact:
- Multi-player games lack a standard results schema.

Minimal fix idea:
- Add `results` array with per-player outcome/rank/score; keep winner/loser optional.

---

### 15) NDJSON hardening lacks size/rate caps
Observed behavior:
- Plan only mentions dropping malformed lines.

Impact:
- A buggy server can send massive lines or flood the report socket.

Minimal fix idea:
- Add max line length, max message rate, and per-connection timeouts.

---

### 16) players_json_path cleanup is not defined
Observed behavior:
- Temp files for `players_json_path` are created but not cleaned up.

Impact:
- Repeated demos can leak files and cause unexpected behavior over time.

Minimal fix idea:
- Create a per-match temp dir and delete it in `_reset_room()` and on startup scan.

---

### 17) Stop/kill should be match-scoped
Observed behavior:
- Stop operations may execute after a newer match has started.

Impact:
- A delayed stop can kill the new server instance.

Minimal fix idea:
- Capture `match_id` when deciding to stop; only stop if it still matches.

---

## Proposed solution (phased, detailed)

### Phase 0: Immediate stability fixes (lowest risk, minimal change set)
Goal: Remove the biggest sources of flakiness with minimal protocol change.

1) Make room reads atomic and state updates consistent.
   - Add `RoomGenie.snapshot_room(room_id)`:
     - Acquire lock.
     - Build a dict (via `asdict`) and copy `ready_players`.
     - Return the dict (no live references).
     - Redact `port`/`client_token`/`report_token` while status is STARTING (even if stored internally).
     - Always include `match_id` in snapshots once STARTING begins.
   - Update `lobby_handler.get_room()` to use `snapshot_room`.
   - Update `RoomGenie.get_room()` to be "private" (used only by locked code).
   - Introduce a transitional room state ("STARTING"):
     - Extend `Room.status` to: "WAITING", "STARTING", "IN_GAME", "ENDING" (optional).
     - Only show "IN_GAME" once `port` and `client_token` are set AND readiness verified.
     - When start is requested:
       - Set status to "STARTING".
       - Release lock and launch.
       - After readiness, set "IN_GAME" + port + client_token/report_token.
     - Update client UI to treat STARTING as "wait" (no launch).
   - Do not call `stop_room()` while holding the room lock:
     - Under lock: mark intent and snapshot identifiers.
     - Outside lock: stop/kill processes.
     - Reacquire lock for minimal final updates only if needed.

2) Implement TCP healthcheck diagnostics with host fallback.
   - Use `manifest["healthcheck"]["tcp_port"]` or fall back to `port`.
   - Try `127.0.0.1` first, then `USER_SERVER_HOST` or `healthcheck.host` if provided.
   - Do not attempt to connect to `bind_host` when it is `0.0.0.0`.
   - If healthcheck fails, log diagnostics and continue waiting for STARTED until timeout.
   - Healthcheck never sets IN_GAME; STARTED is the sole readiness signal.

3) Ensure crash cleanup clears ready flags.
   - In `_watch_room()` cleanup, `room.ready_players.clear()`.
   - Ideally centralize cleanup in a single `_reset_room()` helper.

4) Add random per-launch client/report tokens plus `match_id`.
   - Replace deterministic tokens with `secrets.token_hex(16)` (or UUID4).
   - Generate a `match_id` per launch and store it in room state.
   - Pre-generate and store expected `client_token`/`report_token`/`match_id` under lock before spawn.
   - Optionally generate a separate `client_token` (may equal `report_token` by configuration).
   - Pass tokens/match_id into launcher so the server can report immediately.
   - Require reports to include both `report_token` and `match_id`; ignore stale reports.
   - Make stop/kill match-scoped (only stop if match_id is still current).

5) Kill process groups, not just PIDs.
   - Spawn server with new process group/session:
     - Linux: `start_new_session=True` or `preexec_fn=os.setsid`.
     - Windows: `creationflags=subprocess.CREATE_NEW_PROCESS_GROUP`.
   - On stop, send termination to group (SIGTERM -> SIGKILL).

6) Make host/port configurable (no hardcoding).
   - Use env vars: `USER_SERVER_HOST`, `USER_SERVER_HOST_PORT`, etc.
   - Default to `127.0.0.1` if env not set.

7) Separate bind host from advertised host.
   - Add `bind_host` placeholder for server bind (default `0.0.0.0`).
   - Keep `host` as advertised client connect host (configurable).

8) Update game manifests to remove tokens from CLI args.
   - Keep non-secret args like `--report_host`/`--report_port`.
   - Pass `report_token` (and `client_token` if needed) via env or token files.
   - Update BigTwo and Wordle manifests accordingly.

These steps alone should eliminate most "unexpected behavior" in demos.

---

### Phase 1: Control-plane protocol hardening (robust readiness and lifecycle)
Goal: Make "ready" and "ended" a deterministic protocol, not a guess.

Add new report statuses (extend existing GAME.REPORT):
- `STARTED`: game server is ready to accept clients.
- `HEARTBEAT`: periodic liveness ping.
- `END`: normal end (includes `results` for multi-player games).
- `ERROR`: fatal error with reason.

Platform behavior:
- On launch:
  - set room status STARTING
  - start timer `startup_deadline`
  - pre-store `client_token`/`report_token`/`match_id` under lock before spawning the server
  - wait for GAME.REPORT STARTED
- If STARTED is not received within timeout:
  - kill server, set WAITING, report error to host.
- After STARTED:
  - set IN_GAME and allow client launch.
- Track `last_heartbeat` timestamp per room.
- If heartbeat timeout:
  - warn at ~3x interval, kill at ~5x interval.
  - set WAITING and mark as ERROR.

Protocol strictness:
- All games must send STARTED and HEARTBEAT; platform does not accept alternate readiness signals.

---

### Phase 2: Universal manifest context (multi-player support)
Goal: Remove 2-player assumption and standardize multi-player inputs.

Add to manifest rendering context:
- `player_count`: number of players in the room.
- `players_json`: JSON array of player names, e.g. ["alice","bob","carl"].
- `players_csv`: comma-separated names, e.g. "alice,bob,carl".
- `players_json_path`: file path to a JSON array (preferred for shell safety).
- `match_id`: unique per launch identifier.
- `platform_protocol_version`: control-plane protocol version string/int.
- `bind_host`: server bind address (default `0.0.0.0`).
- `client_token`: client authentication token.
- `report_token`: report authentication token.
- `client_token_path`: file path containing client_token.
- `report_token_path`: file path containing report_token.
- `{p1}`, `{p2}`, ..., `{pN}` generated dynamically for max players.

Rules:
- Support `{p1}` and `{p2}` as convenience placeholders.
- Games must accept `players_json_path` or `players_json` (minimum requirement), with `players_json_path` preferred.

Optional improvements:
- add `players_json_path` as a file path containing JSON (for shell safety).
- add `client_token`, `report_token`, `match_id`, and `room_id` to env consistently.

---

### Phase 3: Conformance tooling
Goal: Make "universal" enforceable instead of hopeful.

Add `tools/validate_game_package.py`:
- Validates manifest schema, required fields, and placeholders.
- Optionally spawns server and checks:
  - server binds port
  - server sends STARTED within timeout
  - heartbeat works
  - handshake succeeds with v1 fields
  - tokens are not present in process args (env/file only)
  - server responds to SIGTERM
- Prints detailed errors for developers.

---

### Phase 4 (optional): Watchdog consolidation
Goal: Reduce per-room thread count and improve determinism at scale.

Plan:
- Replace one-thread-per-room watchers with a single watchdog loop.
- Track `{room_id -> proc, last_heartbeat, last_seen}` in a central map.
- Scan every 200-500ms to:
  - detect exits,
  - enforce heartbeat timeouts,
  - trigger cleanup.

Why defer:
- Class project scope does not require high room counts.
- Adds complexity that is not needed for the minimum stabilization patch set.

---

## Detailed implementation plan (per file / component)

### server/core/room_genie.py
Changes:
- Extend `Room.status` to include STARTING (and optionally ENDING/ERROR).
- Add new fields (recommended):
  - `launch_seq` (int) to prevent stale updates.
  - `match_id` (str) unique per launch; included in reports.
  - `players_json_dir` (Path/str) for per-match temp files (players_json + token files).
  - `launch_started_at` (float) for timeouts.
  - `last_heartbeat` (float) for watchdog.
  - `registered` (bool) if using STARTED report.
  - `last_error` (str) for UI visibility.
  - `client_token` (str) for client auth.
  - `report_token` (str) for report auth.
- Add helper methods:
  - `snapshot_room(room_id) -> dict`: lock-protected copy.
    - redacts `client_token`/`report_token`/`port`; always include `match_id` for STARTING/IN_GAME.
  - `_reset_room(room, clear_ready: bool, stop_launcher: bool)`:
    - clears status, port, tokens, pid
    - clears match_id and any per-launch metadata
    - removes `players_json_dir` if present
    - optionally clears ready_players
  - `_set_in_game(room, launch_result)`:
    - set port/client_token/report_token/pid
    - set match_id
    - set status IN_GAME

Start game flow (suggested pseudocode):
```
def start_game(room_id):
  with lock:
    validate room and readiness
    room.status = "STARTING"
    room.launch_seq += 1
    launch_seq = room.launch_seq
    room.client_token = gen_random_token()
    room.report_token = gen_random_token()
    room.match_id = gen_match_id()
    expected_match_id = room.match_id
    expected_client_token = room.client_token
    expected_report_token = room.report_token
  # launch outside lock to avoid blocking all room operations
  result = gmLauncher.launch_room(..., report_token=expected_report_token, client_token=expected_client_token, match_id=expected_match_id)
  # healthcheck before visibility
  gmLauncher.wait_for_healthcheck(result.port, timeout)
  should_stop = False
  with lock:
    room = get_room(room_id)
    if room.launch_seq != launch_seq or room.match_id != expected_match_id:
      # room changed or canceled while launching
      should_stop = True
    else:
      room.port = result.port
      room.client_token = result.client_token
      room.report_token = result.report_token
      room.match_id = result.match_id
      room.server_pid = result.proc.pid
      room.status = "IN_GAME"
  if should_stop:
    gmLauncher.stop_room(room_id)
    return error
  start watcher thread
  return launch_info
```

Watcher cleanup:
- Always clear `ready_players` on abnormal exit.
- Use `_reset_room` to ensure consistent cleanup.
- Avoid double-stop loops (stop_room should be idempotent).
- Ensure stop/kill happens outside the room lock.
- Only stop/kill if the match_id still matches (avoid killing a newer match).

Threading:
- The new flow reduces lock hold time.
- Readers must use `snapshot_room`, not direct access.

### server/core/handlers/lobby_handler.py
Changes:
- Replace `genie.get_room()` with `genie.snapshot_room()`.
- Ensure `ready_players` in response is already a list from snapshot.

Client visible behavior:
- If status STARTING, show "starting, please wait".

### server/core/handlers/game_handler.py
Changes:
- Accept new statuses: STARTED, HEARTBEAT.
- On STARTED:
  - validate `report_token`
  - validate `match_id` (required)
  - set room registered + possibly flip status to IN_GAME
  - update port/tokens if missing (though normally set on launch)
- On HEARTBEAT:
  - update room.last_heartbeat
- On END / ERROR:
  - call unified cleanup helper and record results
  - ignore stale reports where `match_id` or `report_token` do not match current room state
- Avoid logging full report tokens; log a short prefix if needed.
- Accept `results` payload for multi-player games; winner/loser remains optional convenience.
- Prefer `client_token` for client auth and `report_token` for reporting; treat them as separate roles even if values match.

Note:
- If healthcheck is implemented, ensure it remains diagnostic and does not gate IN_GAME.

### server/core/game_launcher.py
Changes:
- Add `players_json`, `players_csv`, `player_count` to context.
- Optionally generate `p3..pN` based on room player list.
- Add `match_id` and `platform_protocol_version` to context.
- Add `bind_host` to context (default `0.0.0.0`) for server bind.
- Keep `host` as the advertised client connection host.
- Add `players_json_path` and/or `PLAYERS_JSON_PATH` env var:
  - write the JSON array to a temp file to avoid shell quoting issues.
  - create a per-match temp dir (named by match_id) and store it on the room.
  - clean up the directory on END/ERROR/crash.
  - startup scan: delete dirs older than N minutes AND not referenced by any running room.
  - optional: write a lease file with PID/match_id to aid safe cleanup.
  - if delete fails (Windows file locks), rename to `stale_<match_id>_<ts>` and delete later.
- Implement `wait_for_tcp_ready(host, port, timeout)`.
- Use manifest `healthcheck` if present:
  - `healthcheck.tcp_port` can be templated; format it using same context.
  - `healthcheck.timeout_sec` overrides default.
  - optionally support `healthcheck.host` (templated); otherwise try localhost and advertised host if applicable.
  - healthcheck is diagnostic only; STARTED controls readiness.
- Replace deterministic tokens with random per-launch tokens:
  - `client_token` for client auth
  - `report_token` for report auth
- Provide tokens via env or token files:
  - env: `CLIENT_TOKEN`, `REPORT_TOKEN`
  - files: `CLIENT_TOKEN_PATH`, `REPORT_TOKEN_PATH` in per-match temp dir
  - do not include tokens in command args
- Add `client_token_path`/`report_token_path` to context for templated env/file usage.
- Extend `LaunchResult` to include `match_id`.
- Allow `launch_room` to accept pre-generated `client_token`/`report_token`/`match_id` from RoomGenie.
- Spawn process in a new process group/session.
- On stop, terminate the process group to avoid orphans.

Suggested readiness helper:
```
def _wait_for_tcp_ready(host, port, timeout):
  deadline = time.time() + timeout
  while time.time() < deadline:
    try:
      with socket.create_connection((host, port), timeout=0.3):
        return True
    except OSError:
      time.sleep(0.1)
  return False
```
Try `host = "127.0.0.1"` first, then fall back to `USER_SERVER_HOST` or `healthcheck.host` if needed.
Do not attempt to connect to `bind_host` when it is `0.0.0.0` (bind-only).

### server/core/config.py
Changes:
- Read host/port from environment:
  - `USER_SERVER_HOST` = env or "127.0.0.1"
  - `USER_SERVER_HOST_PORT` = env or 16534
  - `USER_SERVER_BIND_HOST` = env or "0.0.0.0"
  - `DEV_SERVER_HOST_IP` = env or "127.0.0.1"
  - `DEV_SERVER_HOST_PORT` = env or 16533
- Provide a helper `get_env_int(name, default)` to avoid parsing errors.

### server/cloudGames/BigTwo/1.0.0/manifest.json
Changes:
- Remove tokens from server command args.
- Pass `report_token` via env or token file; keep `report_host`/`report_port` as args or env.
- Align Wordle and BigTwo manifests to the same token transport rules.

### user/user_cli.py and user/api/user_api.py
Changes:
- Treat STARTING as "do not launch yet".
- If status STARTING and port/client_token missing, wait/poll.
- Only launch when status IN_GAME (and port + client_token are present).
- Optional: add a short backoff or progressive polling message to reduce spam.

---

## Room state machine (proposed)
States:
- WAITING: no game running; room open to join/ready.
- STARTING: server spawning; `match_id` visible, port/tokens hidden from clients.
- IN_GAME: server ready; clients can connect with port + client_token.
- ENDING (optional): finishing/reporting; no new joins.

Transitions:
- WAITING -> STARTING: host starts game.
- STARTING -> IN_GAME: server readiness confirmed by STARTED report.
- STARTING -> WAITING: launch failure or timeout.
- IN_GAME -> WAITING: END or ERROR or crash.
- IN_GAME -> ENDING (optional): server reports END, cleanup pending.

Invariants:
- IN_GAME implies `port` and `client_token`/`report_token` are not None.
- STARTING implies `port` and tokens are not visible to clients (even if stored internally).
- After any exit path (END or crash), `ready_players` must be empty.
- `match_id` changes on every launch; reports must match the current `match_id`.
- Only one active match per room; stop/kill actions are scoped to the current `match_id`.
- Clients must not launch until IN_GAME; the platform guarantees IN_GAME => server is ready.

---

## Control-plane protocol spec (minimal v1 upgrade)
Transport:
- Keep existing NDJSON (newline-delimited JSON) for now.
- Each report message has `room_id`, `report_token`, `match_id`, `status`, `timestamp`, optional `details`.
- `report_token` is random per launch; `match_id` is unique per launch and used to reject stale reports.
- `report_token` is an auth secret; do not log it fully (log a short prefix if needed).
- `client_token` is for client -> game authentication; `report_token` is for game -> platform reporting.
- `match_id` is non-secret correlation; safe to log.

Required statuses:
- STARTED:
  - Sent once when server is listening and ready.
  - Definition of "ready":
    - server has bound the listen socket
    - game state is initialized
    - auth/token checks are ready
    - it can accept and respond to the handshake
  - Payload: `{ room_id, report_token, match_id, status:"STARTED", port, protocol_version }`
- HEARTBEAT:
  - Sent every N seconds (e.g., 2-5s).
  - Payload: `{ room_id, report_token, match_id, status:"HEARTBEAT", ts }`
- END:
  - Payload: `{ room_id, report_token, match_id, status:"END", results?, winner?, loser?, reason?, stats? }`
  - `results` minimal schema:
    - `{ "player": str, "outcome": "WIN"|"LOSE"|"DRAW"|"QUIT"|"ERROR", "rank": int|null, "score": number|null, "player_id"?: int, "extra"?: dict }`
    - `player` MUST match exactly one entry in the room's player list.
  - `results` example: `[{"player":"alice","rank":1,"score":10,"outcome":"WIN"}, ...]`
- ERROR:
  - Payload: `{ room_id, report_token, match_id, status:"ERROR", err_msg }`

Platform expectations:
- Kill server if STARTED is not received within startup timeout.
- Warn if heartbeat is late by > (heartbeat_interval * 3).
- Kill server if heartbeat missing for > (heartbeat_interval * 5).
- Validate both `report_token` and `match_id` against room state.
- Treat STARTED as the authoritative readiness signal for "official" games.

Compatibility policy:
- All games are expected to implement STARTED/HEARTBEAT and include match_id.

Parsing robustness:
- Bad JSON line -> log + discard line (do not drop the connection).
- Missing required fields -> respond with error but keep the connection alive.
- Unknown status -> warn + ignore, no connection reset.
- Enforce max line length (e.g., 64KB) to avoid memory blowups.
- Enforce max message rate per connection:
  - log warning with match_id
  - drop excess messages for a cooldown window
  - keep connection alive
  - disconnect only on sustained abuse
- Do not sleep inside the shared handler when rate limiting; drop immediately to avoid global stalls.
- Apply read timeouts on report sockets to avoid stuck connections.

---

## Client <-> Game handshake v1
Client -> Server (first message):
- `{ "room_id": int, "match_id": str, "player_name": str, "client_token": str, "client_protocol_version": int }`

Server -> Client (handshake response):
- `{ "ok": true|false, "reason": str?, "assigned_player_index": int?, "game_protocol_version": int? }`

Rules:
- The server must validate `client_token` and `match_id` before accepting.
- STARTED means the server can accept and respond to this handshake.

---

## Readiness rules (single source of truth)
- IN_GAME is set only after STARTED is received and validated.
- TCP healthcheck may be used for diagnostics but never sets IN_GAME.
- If STARTED is not received within startup timeout, the server is terminated.

---

## Secret handling
- Tokens are secrets; do not pass `client_token` or `report_token` via process args.
- Provide tokens via environment variables or token files in the per-match temp dir.
- If using files, create them with restrictive permissions (e.g., 0600).
- Log only short token prefixes; never log full tokens.

---

## Protocol v1 compliance (MUST/SHOULD/MAY)
- MUST: server sends STARTED only after readiness checklist; reports include `room_id`/`report_token`/`match_id`; platform sets IN_GAME only after readiness; clients launch only after IN_GAME; platform rejects mismatched `report_token`/`match_id`; client handshake uses the v1 fields.
- SHOULD: server sends HEARTBEAT on schedule; END includes `results` for multi-player games; platform logs match_id and only redacted token prefixes.
- MAY: platform performs TCP healthcheck for diagnostics; servers include extra fields under `extra` in results.

---

## Manifest v2 proposal (compatible extension)
Required fields (minimum):
- `game_name`, `version`, `type`, `max_players`
- `server.command`, `client.command`
- `healthcheck.tcp_port`, `healthcheck.timeout_sec`

Optional fields:
- `server.env`, `client.env`
- `server.startup_timeout` (override healthcheck timeout)
- `protocol_version` (default 1)

Standard placeholders:
- `{room_id}`, `{client_token}`, `{report_token}`, `{client_token_path}`, `{report_token_path}`, `{match_id}`, `{port}`, `{host}`, `{bind_host}`
- `{platform_protocol_version}`
- `{player_name}` (for client)
- `{player_count}`, `{players_json}`, `{players_csv}`, `{players_json_path}`
- `{p1}`, `{p2}`, ... `{pN}`
- `{report_host}`, `{report_port}`, `{report_token}`
 
Token roles:
- `client_token` is used by clients to authenticate to the game server.
- `report_token` is used by the game server to authenticate to the platform.

Guidance for game devs:
- Prefer reading player list from `players_json_path` or env var `PLAYERS_JSON_PATH` to avoid shell quoting issues.
- If `players_json_path` is missing, fall back to `players_json` or `PLAYERS_JSON`.
- Bind the server to `{bind_host}` (default `0.0.0.0`) and let clients connect via advertised `{host}`.
- Use `client_token` for client -> server authentication; use `report_token` for server -> platform reporting.
- Do not pass tokens in CLI args; use env vars or token files (`*_token_path`).
- Must send STARTED and HEARTBEAT to report endpoint.

---

## Implementation rollout
Stage 1 (protocol v1 adoption):
- Add STARTING state and enforce the IN_GAME invariant (port + client_token ready).
- Require STARTED/HEARTBEAT and match_id in reports.
- Generate random client/report tokens and match_id per launch.
- Enforce token transport via env/file (no tokens in CLI args).
- Require client->server handshake v1 fields.
- Keep manifests aligned to the new placeholders (update BigTwo/Wordle accordingly).

Stage 2 (enforcement + tooling):
- Reject reports missing match_id or STARTED/HEARTBEAT.
- Require `results` in END for multi-player games.
- Validate with `tools/validate_game_package.py`.

---

## Test and validation plan
Manual tests (quick):
- Start a game with two clients:
  - verify no client launches before port is ready.
  - verify port is listening before IN_GAME status.
- Force server to exit:
  - verify room returns to WAITING and ready_players cleared.
- Run BigTwo:
  - verify END report is received after manifest fix.
- Change `USER_SERVER_HOST` env and verify client launch uses new host.
- Set `bind_host` to `127.0.0.1` and advertised host to a LAN IP; verify healthcheck and client behavior match expectations.

Automated tests (recommended):
- Unit test: `RoomGenie.snapshot_room` returns copy and is lock-safe.
- Integration test: fake game server that delays bind for 2-3 seconds.
  - Expect STARTING state during delay, no early client launch.
- Integration test: fake game server that exits early.
  - Expect WAITING + ready cleared.
- Heartbeat test: fake server that stops heartbeats -> orchestrator kills.
- Stale report test: old server sends END with old `match_id` -> ignored.
- STARTED race test: server sends STARTED immediately; platform accepts because report_token/match_id are pre-stored.
- NDJSON guard test: oversized line -> dropped; rate limit -> throttled.
- Handshake test: client sends v1 handshake; server validates client_token/match_id and responds.
- Token transport test: verify process args do not include client/report tokens.

---

## Observability improvements
Suggested logging additions:
- Log transitions: WAITING -> STARTING -> IN_GAME -> WAITING.
- Log healthcheck attempts and final result.
- Log report status handling with room_id, report_token, and match_id match.
- Log heartbeat lateness warnings before kill.
- Log process group termination outcome.
- Log tokens only as a short prefix (e.g., first 6-8 chars) to avoid leaking secrets.

Optional metrics:
- launch time (spawn -> ready)
- heartbeat gap duration
- number of failed launches per game version

---

## Risks and tradeoffs
- Adding STARTING state requires minor UI changes (clients must handle new status).
- TCP healthcheck is diagnostic only and may succeed even if the app is not fully ready; STARTED remains the readiness gate.
- Process group termination is OS-specific; code must handle Windows vs Unix.
- Windows: without job objects, process-tree kill is best-effort; document limitation.
- Strict protocol requires updating all games and manifests together (no compatibility fallback).
- Random tokens and `match_id` require coordinated updates to game servers and clients.

---

## Summary of the smallest stabilizing patch set
If only a handful of changes are allowed, do these first:
1) Lock-protected room snapshots + STARTING state; IN_GAME only after port + client_token; stop/kill outside the room lock.
2) TCP healthcheck diagnostics using manifest settings, with host fallback.
3) Clear ready_players on all exit paths (unified cleanup).
4) Pre-generate random per-launch client/report tokens + `match_id` before spawn; validate and match-scope stop/kill (reject stale reports).
5) Process group cleanup (terminate full group).
6) Make advertised host configurable (env vars) and add `bind_host` for server bind.
7) Remove tokens from CLI args; pass tokens via env/file and update manifests.

These are the core fixes that remove most "unexpected" behavior while keeping the current architecture intact.
