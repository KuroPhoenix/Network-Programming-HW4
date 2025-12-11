• Findings
                                                                                                                                                                                                         
  - server/user_server.py:11-18 and server/core/game_launcher.py:7-78 couple the servers to user.config.user_config (client IP/port). A remote deployment will bind/advertise the wrong address and      
    creates a client → server dependency loop.                                                                                                                                                           
  - Game/version model is too thin for D1/D2/P2/P3: server/core/game_manager.py tracks only (author, game_name, version, type) with one table, no game_id/status/latest flag, no per-version listing, and
    get_game always returns the single latest by name. Collisions across developers, down-shelf/offline, rollbacks, and “download/update latest” are undefined.                                          
  - Install/update flow is not per-player and has no version guard: downloads land in user/utils/download_wizard.py → user/downloads/<game>/<version> (shared for all players), existing versions can’t  
    be overwritten, and user/api/user_api.py:107-137 launches clients even if the manifest isn’t installed or is stale. Spec requires downloads/<Player>/<Game>/<version>/ and “update to latest” logic. 
  - Room start/join is incomplete for P3: start uses the client HOST_IP (user/api/user_api.py:117) instead of the server-returned host, only the caller sees host/port/token (no registry for joiners),  
    and the launcher’s port/token aren’t surfaced back through a queryable endpoint. There’s no guarantee players have the matching version before starting.                                             
 
  - Dev UX bugs: developer/util/local_game_manager.py:12-21 points to developer/util/games, so the built-in sample games under developer/games/ aren’t detected; create manifest/upload flows don’t call 
    server metadata endpoints (Stage 2 “create/list metadata” is effectively unused).                                                                                                                    
  - Docs/ops gap: README.md is empty; no end-to-end start/run instructions, manifest format, or demo walkthrough. No local launcher/packaging helpers beyond a template; stubs mentioned in docs         
    (packaging, launcher) are absent.                                                                                                                                                                    
                                                                                                                                                                                                         
  What’s in place                                                                                                                                                                                        
                                                                                                                                                                                                         
  - Basic register/login/logout for developers and players with SQLite persistence and session tokens.                                                                                                   
  - Chunked upload/download pipeline with manifest validation and temp-to-final moves (server/core/storage_manager.py), plus dev/user CLI shells, store browsing, room CRUD, and text-only reviews.      
  - run.sh tmux helper starts both servers and optional clients; sample manifests/templates exist under developer/template/ and developer/games/.                                                        
                                                                                                                                                                                                         
  Next focus                                                                                                                                                                                             
                                                                                                                                                                                                         
  1. Decouple server config from client (server should read its own host/port), and return real host/port/token to clients; expose a way for all room members to fetch launch info.                      
  2. Redesign game/version schema: game_id + status (online/offline), separate versions table with version string, path, latest flag, and per-dev ownership; update list/detail/download endpoints       
     accordingly.                                                                                                                                                                                        
  3. Fix install/update flow: per-player download root, allow reinstall/update, detect local vs latest, and block GAME_START until the needed version is present.                                        
  4. Harden room lifecycle: single port allocator, persist launch info on the room, ensure cleanup on end/error/leave, and verify start/download preconditions.                                          
  5. Implement P4 properly (score 1–5, average, list in game detail; optional “played check”).                                                                                                           
  6. Repair dev client local path + Stage 2 menu (create/list metadata, upload entry points) and fill in README with setup/run/demo steps.     