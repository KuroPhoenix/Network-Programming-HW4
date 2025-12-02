#pragma once

#include <cstdint>
#include <functional>
#include <mutex>
#include <string>
#include <unordered_map>

struct GameRegistry {
    std::mutex* mutex = nullptr;
    std::unordered_map<int, uint16_t>* ports = nullptr;
    std::unordered_map<int, std::string>* tokens = nullptr;
};

using GameFinishedCallback = std::function<void(int room_id,
                                               const std::string& user1,
                                               int score1,
                                               const std::string& user2,
                                               int score2)>;

// Shared Tetris game server runner used by both the lobby and
// the standalone tetris_server executable.
void run_tetris_server_on_fd(int listen_fd,
                             const std::string& p1_name,
                             const std::string& p2_name,
                             const std::string& db_ip,
                             uint16_t db_port,
                             int room_id,
                             const std::string& expected_token,
                             GameRegistry* registry = nullptr,
                             GameFinishedCallback finished_cb = nullptr);
