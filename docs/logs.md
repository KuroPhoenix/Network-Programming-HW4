# Logs / Progress

## Stage 1 — Minimal Auth Server + Test Clients

- **Servers**: `server/user_server.py` (player/lobby) and `server/dev_server.py` (developer) listen on localhost (user: 16532, dev: 16533). They use `server/core/auth.py` for registration/login, returning session tokens and rejecting duplicates/bad credentials. Logging starts fresh each run (`mode="w"`).
- **Protocol**: Single `Message` envelope in `server/core/protocol.py` with fields `{type, payload, token, request_id, status, code, message}`. Helpers `message_to_dict`/`message_from_dict` serialize/deserialize between the dataclass and plain dict for JSON transport.
- **Client transport**: Shared helpers in `shared/net.py` (`connect_to_server`, `send_request`) build/send `Message` envelopes as newline-delimited JSON and parse responses back into `Message`.
- **Clients**: `user/api/user_api.py` and `developer/api/dev_api.py` wrap sockets, build `Message` requests, parse `Message` replies, and manage session tokens. CLI menus in `user/main.py` and `developer/dev.py` call these APIs to register/login with basic prompts.
- **Handlers**: Auth handlers in `server/core/handlers/auth_handler.py` return simple dicts; servers wrap them into `Message` before sending. Unknown types and errors are wrapped into `Message` with `status="error"` and appropriate codes.
- **Data flow**: Client builds `Message` → `message_to_dict` → JSON + `\n` → server reads JSON → handler returns dict → server wraps to `Message` → `message_to_dict` → JSON → client reads → `message_from_dict` → client logic.
