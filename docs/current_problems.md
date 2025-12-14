Key items missing against the provided specs:
                                                                                                                                                                                                         
  - Developer down-shelf/status control (D3): Specs require a way to mark games OFFLINE so “該遊戲不再出現在一般玩家可見的『可下載 / 可遊玩』列表中”. Code only supports full deletion; there is no      
    status flag or “SET_GAME_STATUS”/online filter.                                                                                                                                                      
  - Developer version management (D2): Specs call for updating versions with validation (“若版本號格式不合法（例如空白或重複使用舊版號且未被允許），系統應提示錯誤…” and “這款遊戲在後台被標記為最新版   
    本”). Current upload just inserts versions without semver/duplicate checks or marking latest.                                                                                                        
  - Game detail/store browsing (P1): Specs expect showing description, type, version, avg score, and review samples (“系統顯示該遊戲的詳細資訊…評分與部分玩家評論”). Current GAME_GET_DETAILS returns    
    only the latest row from games.db and no review samples or status/latest_version field.                                                                                                              
  - Latest version/checksum for downloads (P2): Specs define LATEST_VERSION and DOWNLOAD_BEGIN/CHUNK/END with size/checksum (“LATEST_VERSION — payload … size_bytes … checksum”). Code lacks             
    LATEST_VERSION, doesn’t send size/checksum, and uses pull-per-chunk RPC rather than server-pushed DOWNLOAD_CHUNK/END.                                                                                
  - Upload validation flow (D1/D2): Specs define UPLOAD_BEGIN with size_bytes/checksum and chunk sequencing errors (120 CHUNK_OUT_OF_ORDER, 121 CHECKSUM_MISMATCH). Current upload accepts chunks without
    size/checksum and only enforces seq alignment; no checksum or chunk_size guidance.                                                                                                                   
  - Authentication duplicate-login policy: Specs require either reject or invalidate old session (“避免重複登入…擇一實作即可”). Current Authenticator raises duplicate login error and doesn’t invalidate
    old tokens nor return an explicit “帳號已在其他裝置登入” message.                                                                                                                                    
  - Room start/host flow (P3): Specs require “玩家選擇一款遊戲…系統檢查玩家是否已有對應版本…房間建立成功後…啟動對應的 game server”. Current START_ROOM lacks host-only enforcement and doesn’t ensure    
    players have the version locally; JOIN_ROOM doesn’t surface port/token for late join after start.                                                                                                    
  - Presence/updates: Specs allow polling or notify; clients should see room/player status updates. Current user client only polls manually; no push messages (ROOM_UPDATED/PLAYER_PRESENCE) are         
    implemented.                                                                                                                                                                                         
  - Reviews eligibility and display (P4): Specs want “玩家曾經成功啟動並結束某款遊戲的遊玩流程…評分與部分玩家評論”. The review list isn’t included in GET_GAME_DETAIL, and play-history eligibility      
    depends on GAME.REPORT; sample games don’t always send END on client quit, so eligibility can fail.                                                                                                  
  - README/startup usability: Specs require a clear README with startup instructions (“必須包含一份完整且清楚的 README…如何啟動 Developer Client / Lobby Client”). README.md is empty; run.sh still      
    references wrong ports (16532/16533 vs config 16534/16533).                                                                                                                                          
  - Plugin use cases (PL1–PL4): Not implemented at all; no plugin listing/install/uninstall or plugin-aware gameplay paths.                 