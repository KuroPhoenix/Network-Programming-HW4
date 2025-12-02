#include "tetris_runtime.hpp"

#include "common.hpp"
#include "lp_framing.hpp"
#include "tetris_game.hpp"

#include <chrono>
#include <iostream>
#include <map>
#include <memory>
#include <poll.h>
#include <set>
#include <sstream>
#include <string>
#include <vector>
#include <unistd.h>

namespace {

bool tetris_db_req(const std::string& db_ip, uint16_t db_port, const std::string& cmd, std::string& reply) {
    int fd = connect_tcp(db_ip, db_port);
    if (fd < 0) {
        log_checkpoint("Tetris", "DB_CONNECT_FAIL", db_ip + ":" + std::to_string(db_port));
        return false;
    }
    const std::string peer = "db:" + db_ip + ":" + std::to_string(db_port);
    log_communication("Tetris", "TX", peer, cmd);
    bool ok = lp_send_frame(fd, cmd);
    if (ok) {
        ok = lp_recv_frame(fd, reply);
        if (ok) {
            log_communication("Tetris", "RX", peer, reply);
        }
    }
    ::close(fd);
    if (!ok) {
        log_checkpoint("Tetris", "DB_REQ_FAIL", cmd);
    }
    return ok;
}

std::string peer_desc(int fd) {
    return "socket fd=" + std::to_string(fd);
}

bool tetris_send_frame(int fd, const std::string& msg) {
    log_communication("Tetris", "TX", peer_desc(fd), msg);
    return lp_send_frame(fd, msg);
}

bool tetris_recv_frame(int fd, std::string& out) {
    bool ok = lp_recv_frame(fd, out);
    if (ok) {
        log_communication("Tetris", "RX", peer_desc(fd), out);
    }
    return ok;
}

void broadcast(const std::vector<int>& fds, const std::string& msg) {
    for (int fd : fds) {
        if (fd >= 0) {
            tetris_send_frame(fd, msg);
        }
    }
}

struct Player {
    std::string name;
    int fd = -1;
    bool authed = false;
    std::unique_ptr<TetrisGame> game;
};

} // namespace

void run_tetris_server_on_fd(int listen_fd,
                             const std::string& p1_name,
                             const std::string& p2_name,
                             const std::string& db_ip,
                             uint16_t db_port,
                             int room_id,
                             const std::string& expected_token,
                             GameRegistry* registry,
                             GameFinishedCallback finished_cb)
{
    Player players[2];
    players[0].name = p1_name;
    players[1].name = p2_name;

    std::map<int, int> fd_to_player_idx;
    std::set<int> spectator_fds;
    std::map<int, std::string> spectator_names;
    std::vector<pollfd> pfds;
    pfds.push_back({listen_fd, POLLIN, 0});

    int authed_players = 0;
    long game_seed = std::chrono::system_clock::now().time_since_epoch().count();

    auto last_tick = std::chrono::steady_clock::now();
    bool game_started = false;

    while (running) {
        int rc = ::poll(pfds.data(), pfds.size(), 100);
        if (rc < 0) {
            if (errno == EINTR) continue;
            perror("[Tetris] poll");
            break;
        }

        if (listen_fd >= 0 && (pfds[0].revents & POLLIN)) {
            int cfd = ::accept(listen_fd, nullptr, nullptr);
            if (cfd >= 0) {
                pfds.push_back({cfd, POLLIN, 0});
                log_checkpoint("Tetris", "CLIENT_CONNECTED", peer_desc(cfd));
            }
        }

        for (size_t i = 1; i < pfds.size(); ++i) {
            if (!(pfds[i].revents & POLLIN)) continue;

            int cfd = pfds[i].fd;
            std::string req;
            if (!tetris_recv_frame(cfd, req)) {
                std::string who = peer_desc(cfd);
                ::close(cfd);
                pfds.erase(pfds.begin() + i);
                if (fd_to_player_idx.count(cfd)) {
                    int p_idx = fd_to_player_idx[cfd];
                    if (!game_started) {
                        players[p_idx].authed = false;
                        if (authed_players > 0) --authed_players;
                    } else if (players[p_idx].game) {
                        players[p_idx].game->game_over = true;
                    }
                    players[p_idx].fd = -1;
                    fd_to_player_idx.erase(cfd);
                    who += " player=" + players[p_idx].name;
                } else {
                    auto sit = spectator_names.find(cfd);
                    if (sit != spectator_names.end()) {
                        who += " spec=" + sit->second;
                    }
                    spectator_fds.erase(cfd);
                    spectator_names.erase(cfd);
                }
                --i;
                log_checkpoint("Tetris", "CLIENT_DISCONNECTED", who);
                continue;
            }

            std::istringstream iss(req);
            std::string cmd;
            iss >> cmd;

            if (cmd == "HELLO") {
                std::string kv, uname, token, role_param;
                while (iss >> kv) {
                    auto pos = kv.find('=');
                    if (pos == std::string::npos) continue;
                    std::string key = kv.substr(0, pos);
                    std::string val = kv.substr(pos + 1);
                    if (key == "username") uname = val;
                    else if (key == "token") token = val;
                    else if (key == "role") role_param = val;
                }

                bool handled = false;
                bool wants_spec = (role_param == "SPEC");

                if (token == expected_token) {
                    if (!wants_spec && uname == players[0].name && !players[0].authed) {
                        players[0].fd = cfd;
                        players[0].authed = true;
                        fd_to_player_idx[cfd] = 0;
                        authed_players++;
                        tetris_send_frame(cfd, "WELCOME role=P1 seed=" + std::to_string(game_seed) + " gravity=500 bag=7");
                        log_checkpoint("Tetris", "HELLO_ACCEPTED", "user=" + uname + " role=P1");
                        handled = true;
                    } else if (!wants_spec && uname == players[1].name && !players[1].authed) {
                        players[1].fd = cfd;
                        players[1].authed = true;
                        fd_to_player_idx[cfd] = 1;
                        authed_players++;
                        tetris_send_frame(cfd, "WELCOME role=P2 seed=" + std::to_string(game_seed) + " gravity=500 bag=7");
                        log_checkpoint("Tetris", "HELLO_ACCEPTED", "user=" + uname + " role=P2");
                        handled = true;
                    } else {
                        spectator_fds.insert(cfd);
                        spectator_names[cfd] = uname;
                        tetris_send_frame(cfd, "WELCOME role=SPEC seed=" + std::to_string(game_seed) + " gravity=500 bag=7");
                        log_checkpoint("Tetris", "HELLO_ACCEPTED", "user=" + uname + " role=SPEC");
                        handled = true;
                    }
                }

                if (!handled) {
                    tetris_send_frame(cfd, "ERR invalid_player_or_token");
                    log_checkpoint("Tetris", "HELLO_REJECTED",
                                   "user=" + (!uname.empty() ? uname : "unknown") + " reason=bad_token");
                    ::close(cfd);
                    pfds.erase(pfds.begin() + i);
                    --i;
                }
            } else if (cmd == "INPUT") {
                if (game_started && fd_to_player_idx.count(cfd)) {
                    int p_idx = fd_to_player_idx[cfd];
                    std::string action;
                    iss >> action;
                    players[p_idx].game->handle_input(action);
                }
            }
        }

        if (!game_started && authed_players == 2) {
            players[0].game = std::make_unique<TetrisGame>(game_seed);
            players[1].game = std::make_unique<TetrisGame>(game_seed);
            game_started = true;
            last_tick = std::chrono::steady_clock::now();
            log_checkpoint("Tetris", "MATCH_STARTED",
                           "room=" + std::to_string(room_id) + " seed=" + std::to_string(game_seed));
        }

        if (game_started) {
            auto now = std::chrono::steady_clock::now();
            std::vector<int> conns;
            if (players[0].fd >= 0) conns.push_back(players[0].fd);
            if (players[1].fd >= 0) conns.push_back(players[1].fd);
            for (int fd : spectator_fds) {
                if (fd >= 0) conns.push_back(fd);
            }

            if (std::chrono::duration_cast<std::chrono::milliseconds>(now - last_tick).count() >= 500) {
                if (players[0].game) players[0].game->tick();
                if (players[1].game) players[1].game->tick();

                for (int p_idx = 0; p_idx < 2; ++p_idx) {
                    if (players[p_idx].game) {
                        std::ostringstream os;
                        os << "SNAPSHOT user=" << players[p_idx].name
                           << " score=" << players[p_idx].game->score
                           << " lines=" << players[p_idx].game->lines_cleared
                           << " gameover=" << (players[p_idx].game->game_over ? "1" : "0")
                           << " board=" << players[p_idx].game->get_board_snapshot();
                        broadcast(conns, os.str());
                    }
                }
                last_tick = now;
            }

            bool p1_over = !players[0].game || players[0].game->game_over;
            bool p2_over = !players[1].game || players[1].game->game_over;
            if (p1_over || p2_over) {
                log_checkpoint("Tetris", "MATCH_ENDING",
                               "room=" + std::to_string(room_id) +
                               " p1=" + players[0].name + " score=" + std::to_string(players[0].game ? players[0].game->score : 0) +
                               " p2=" + players[1].name + " score=" + std::to_string(players[1].game ? players[1].game->score : 0));
                broadcast(conns,
                          "GAME_OVER p1_score=" + std::to_string(players[0].game ? players[0].game->score : 0) +
                          " p2_score=" + std::to_string(players[1].game ? players[1].game->score : 0));
                break;
            }
        }
    }

    std::cerr << "[Tetris] Game " << room_id << " finished." << std::endl;
    log_checkpoint("Tetris", "MATCH_FINISHED", "room=" + std::to_string(room_id));

    int p1_score = players[0].game ? players[0].game->score : 0;
    int p2_score = players[1].game ? players[1].game->score : 0;

    if (finished_cb) {
        finished_cb(room_id, players[0].name, p1_score, players[1].name, p2_score);
    } else {
        std::string reply;
        std::string log_req = "GameLog create roomId=" + std::to_string(room_id)
           + " user1=" + players[0].name
           + " user2=" + players[1].name
           + " score1=" + std::to_string(p1_score)
           + " score2=" + std::to_string(p2_score);
        tetris_db_req(db_ip, db_port, log_req, reply);

        std::string status_req = "Room setStatus roomId=" + std::to_string(room_id) + " status=idle";
        tetris_db_req(db_ip, db_port, status_req, reply);
    }

    if (registry && registry->mutex) {
        std::lock_guard<std::mutex> lock(*registry->mutex);
        if (registry->ports) registry->ports->erase(room_id);
        if (registry->tokens) registry->tokens->erase(room_id);
    }

    for (size_t i = 0; i < pfds.size(); ++i) ::close(pfds[i].fd);
    if (listen_fd >= 0) ::close(listen_fd);
}
