#include "common.hpp"
#include "lp_framing.hpp"
#include "tetris_runtime.hpp"
#include <unordered_map>
#include <string>
#include <sstream>
#include <iostream>
#include <vector>
#include <poll.h>
#include <thread>
#include <mutex>
#include <unistd.h>
#include <random> // For token generation

// ClientInfo struct - this is the lobby's *only* state
struct ClientInfo {
    std::string username;
    bool authed = false;
    int fd = -1;
    int roomId = 0; // The ID of the room they are "in"
    int spectateRoomId = 0; // Room being spectated
};

// --- Global, thread-safe state ---
static std::mutex g_clients_mutex;
static std::unordered_map<int, ClientInfo> g_clients;
// --- No g_rooms! DB is the source of truth ---

static int db_fd = -1;
static std::mutex g_db_mutex; // Mutex for DB connection
static std::string g_db_ip;
static uint16_t g_db_port = 0;

static std::mutex g_games_mutex;
static std::unordered_map<int, uint16_t> g_game_ports;
static std::unordered_map<int, std::string> g_game_tokens;
static GameRegistry g_game_registry{&g_games_mutex, &g_game_ports, &g_game_tokens};
static uint16_t g_next_game_port = 15000;

// Helper to generate a random token
std::string generate_token() {
    static std::mt19937 rng(std::random_device{}());
    std::uniform_int_distribution<uint32_t> dist;
    std::stringstream ss;
    ss << std::hex << dist(rng) << dist(rng);
    return ss.str();
}

static bool db_req(const std::string& cmd, std::string& reply) {
    std::lock_guard<std::mutex> lock(g_db_mutex);
    if (db_fd < 0) return false;
    const std::string peer = "db:" + g_db_ip + ":" + std::to_string(g_db_port);
    log_communication("Lobby", "TX", peer, cmd);
    if (!lp_send_frame(db_fd, cmd)) return false;
    if (!lp_recv_frame(db_fd, reply)) return false;
    log_communication("Lobby", "RX", peer, reply);
    return true;
}

static std::string peer_for_fd(const std::string& category, int fd) {
    return category + " fd=" + std::to_string(fd);
}

static bool lobby_send_frame(int fd, const std::string& body) {
    log_communication("Lobby", "TX", peer_for_fd("client", fd), body);
    return lp_send_frame(fd, body);
}

static bool lobby_recv_client_frame(int fd, std::string& out) {
    bool ok = lp_recv_frame(fd, out);
    if (ok) {
        log_communication("Lobby", "RX", peer_for_fd("client", fd), out);
    }
    return ok;
}

static int open_game_listener(uint16_t& out_port) {
    const uint16_t kMinPort = 15000;
    const uint16_t kMaxPort = 60000;
    if (g_next_game_port < kMinPort || g_next_game_port > kMaxPort) g_next_game_port = kMinPort;
    for (int attempt = 0; attempt < 2000; ++attempt) {
        uint16_t candidate = g_next_game_port;
        uint16_t port = candidate;
        int fd = start_tcp_server("0.0.0.0", port);
        g_next_game_port = (candidate >= kMaxPort) ? kMinPort : static_cast<uint16_t>(candidate + 1);
        if (fd >= 0) {
            out_port = port;
            return fd;
        }
    }
    out_port = 0;
    return -1;
}

// Helper to find a client's FD by username
int find_fd_by_username(const std::string& username) {
    std::lock_guard<std::mutex> lock(g_clients_mutex);
    for (auto const& [fd, client] : g_clients) {
        if (client.authed && client.username == username) {
            return fd;
        }
    }
    return -1;
}

// Helper to parse "OK ..." replies from DB
std::unordered_map<std::string, std::string> parse_ok_reply(const std::string& reply) {
    std::unordered_map<std::string, std::string> map;
    if (reply.rfind("OK", 0) != 0) return map;

    std::istringstream iss(reply);
    std::string word;
    iss >> word; // Skip "OK"

    while (iss >> word) {
        auto pos = word.find('=');
        if (pos != std::string::npos) {
            map[word.substr(0, pos)] = word.substr(pos + 1);
        }
    }
    return map;
}

int main(int argc, char** argv) {
    install_signal_handlers();

    std::string ip = "0.0.0.0";
    uint16_t lobby_port = 13472;
    g_db_ip = "127.0.0.1";
    g_db_port = 12977;

    if (argc >= 2) ip = argv[1];
    if (argc >= 3) lobby_port = static_cast<uint16_t>(std::stoi(argv[2]));
    if (argc >= 4) g_db_ip = argv[3];
    if (argc >= 5) g_db_port = static_cast<uint16_t>(std::stoi(argv[4]));

    db_fd = connect_tcp(g_db_ip, g_db_port);
    if (db_fd < 0) { std::cerr << "[Lobby] cannot connect to DB\n"; return 1; }
    log_checkpoint("Lobby", "DB_CONNECTED", g_db_ip + ":" + std::to_string(g_db_port));

    int listen_fd = start_tcp_server(ip.c_str(), lobby_port);
    if (listen_fd < 0) return 1;
    std::cerr << "[Lobby] listening on " << ip << ":" << lobby_port << "\n";
    log_checkpoint("Lobby", "LISTENING", ip + ":" + std::to_string(lobby_port));

    std::vector<pollfd> pfds;

    while (running) {
        // Rebuild pfds from g_clients list (handles dynamic client FDs)
        pfds.clear();
        pfds.push_back({listen_fd, POLLIN, 0});
        pfds.push_back({db_fd, POLLIN, 0});
        {
            std::lock_guard<std::mutex> lock(g_clients_mutex);
            for (auto const& [fd, client] : g_clients) {
                pfds.push_back({fd, POLLIN, 0});
            }
        }

        int rc = ::poll(pfds.data(), pfds.size(), 500);
        if (rc < 0) { if (errno == EINTR) continue; perror("poll"); break; }
        if (rc == 0) continue;

        // --- Handle New Connection ---
        if (pfds[0].revents & POLLIN) {
            int cfd = ::accept(listen_fd, nullptr, nullptr);
            if (cfd >= 0) {
                {
                    std::lock_guard<std::mutex> lock(g_clients_mutex);
                    g_clients[cfd] = ClientInfo{.fd=cfd};
                }
                log_checkpoint("Lobby", "CLIENT_CONNECTED", "fd=" + std::to_string(cfd));
                lobby_send_frame(cfd, "WELCOME LOBBY");
            }
        }

        // --- Handle DB Response (unexpected) ---
        if (pfds[1].revents & POLLIN) {
            std::string tmp;
            if (!lp_recv_frame(db_fd, tmp)) {
                std::cerr << "[Lobby] DB connection lost." << std::endl;
                running = 0; break;
            } else {
                log_communication("Lobby", "RX", "db:" + g_db_ip + ":" + std::to_string(g_db_port), tmp);
            }
        }

        // --- Handle Client IO ---
        for (size_t i = 2; i < pfds.size(); ++i) {
            if (!(pfds[i].revents & POLLIN)) continue;

            int cfd = pfds[i].fd;
            std::string req;
            ClientInfo cli; // Local copy

            {
                std::lock_guard<std::mutex> lock(g_clients_mutex);
                if (!g_clients.count(cfd)) continue; // Disconnected already
                cli = g_clients[cfd];
            }

            if (!lobby_recv_client_frame(cfd, req)) {
                // client gone
                if (cli.authed) {
                    std::string r2;
                    db_req("User setOnline username=" + cli.username + " online=0", r2);
                    if (cli.roomId != 0) {
                        db_req("Room leave roomId=" + std::to_string(cli.roomId) + " user=" + cli.username, r2);
                    }
                    if (cli.spectateRoomId != 0) {
                        db_req("Room unspectate roomId=" + std::to_string(cli.spectateRoomId) + " user=" + cli.username, r2);
                    }
                }
                log_checkpoint("Lobby", "CLIENT_DISCONNECTED",
                               "fd=" + std::to_string(cfd) +
                               (cli.username.empty() ? "" : " user=" + cli.username));
                ::close(cfd);
                {
                    std::lock_guard<std::mutex> lock(g_clients_mutex);
                    g_clients.erase(cfd);
                }
                continue;
            }

            std::istringstream iss(req);
            std::string cmd;
            iss >> cmd;
            std::string u, p; // For register/login
            std::string reply; // For DB replies

            if (cmd == "REGISTER") {
                iss >> u >> p;
                if (db_req("User create username=" + u + " pass=" + p, reply)) {
                    lobby_send_frame(cfd, reply);
                    if (reply.rfind("OK", 0) == 0) {
                        log_checkpoint("Lobby", "REGISTER_OK", "user=" + u);
                    } else {
                        log_checkpoint("Lobby", "REGISTER_FAIL", "user=" + u + " reason=" + reply);
                    }
                } else {
                    lobby_send_frame(cfd, "ERR db");
                    log_checkpoint("Lobby", "REGISTER_FAIL", "user=" + u + " reason=db_unreachable");
                }
            }
            else if (cmd == "LOGIN") {
                iss >> u >> p;
                if (db_req("User read username=" + u, reply)) {
                    auto reply_map = parse_ok_reply(reply);
                    bool already_online = reply_map.count("online") && reply_map["online"] == "1";
                    if (!already_online) {
                        std::lock_guard<std::mutex> lock(g_clients_mutex);
                        for (auto const& kv : g_clients) {
                            if (kv.second.authed && kv.second.username == u) {
                                already_online = true;
                                break;
                            }
                        }
                    }

                    if (already_online) {
                        lobby_send_frame(cfd, "ERR already_online");
                        log_checkpoint("Lobby", "LOGIN_REJECT", "user=" + u + " reason=already_online");
                    }
                    else if (reply_map.count("pass") && reply_map["pass"] == p) {
                        std::string acquire_reply;
                        if (!db_req("User compareSetOnline username=" + u + " expect=0 value=1", acquire_reply)) {
                            lobby_send_frame(cfd, "ERR db");
                            log_checkpoint("Lobby", "LOGIN_REJECT", "user=" + u + " reason=db_error");
                            continue;
                        }
                        if (acquire_reply.rfind("OK", 0) != 0) {
                            std::string reason = acquire_reply;
                            if (acquire_reply.rfind("ERR mismatch", 0) == 0) {
                                lobby_send_frame(cfd, "ERR already_online");
                                log_checkpoint("Lobby", "LOGIN_REJECT", "user=" + u + " reason=already_online_race");
                            } else {
                                lobby_send_frame(cfd, acquire_reply);
                                log_checkpoint("Lobby", "LOGIN_REJECT", "user=" + u + " reason=" + acquire_reply);
                            }
                            continue;
                        }

                        {
                            std::lock_guard<std::mutex> lock(g_clients_mutex);
                            g_clients[cfd].username = u;
                            g_clients[cfd].authed = true;
                        }
                        lobby_send_frame(cfd, "OK LOGIN");
                        log_checkpoint("Lobby", "LOGIN_OK", "user=" + u);
                    } else {
                        lobby_send_frame(cfd, "ERR bad_credentials");
                        log_checkpoint("Lobby", "LOGIN_REJECT", "user=" + u + " reason=bad_credentials");
                    }
                } else {
                    lobby_send_frame(cfd, reply.empty() ? "ERR db" : reply);
                    log_checkpoint("Lobby", "LOGIN_REJECT", "user=" + u + " reason=db_error");
                }
            }
            else if (cmd == "LOGOUT") { // **FIX: Added LOGOUT**
                if (!cli.authed) { lobby_send_frame(cfd, "ERR not_logged_in"); continue; }
                db_req("User setOnline username=" + cli.username + " online=0", reply);
                if (cli.roomId != 0) {
                    std::string tmp;
                    db_req("Room leave roomId=" + std::to_string(cli.roomId) + " user=" + cli.username, tmp);
                }
                if (cli.spectateRoomId != 0) {
                    std::string tmp;
                    db_req("Room unspectate roomId=" + std::to_string(cli.spectateRoomId) + " user=" + cli.username, tmp);
                }
                {
                    std::lock_guard<std::mutex> lock(g_clients_mutex);
                    g_clients[cfd].authed = false;
                    g_clients[cfd].username = "";
                    g_clients[cfd].roomId = 0;
                    g_clients[cfd].spectateRoomId = 0;
                }
                lobby_send_frame(cfd, "OK LOGOUT");
                log_checkpoint("Lobby", "LOGOUT", "user=" + cli.username);
            }
            else if (cmd == "LIST_ONLINE") {
                if (db_req("User listOnline", reply))
                    lobby_send_frame(cfd, reply);
                else
                    lobby_send_frame(cfd, "ERR db");
            }
            else if (cmd == "CREATE_ROOM") {
                if (!cli.authed) { lobby_send_frame(cfd, "ERR not_logged_in"); continue; }
                std::string name, visibility;
                iss >> name >> visibility;
                if (visibility.empty()) visibility = "public";

                if(db_req("Room create name=" + name + " host=" + cli.username + " visibility=" + visibility, reply)) {
                    auto reply_map = parse_ok_reply(reply);
                    if (reply_map.count("roomId")) {
                        int rid = std::stoi(reply_map["roomId"]);
                        {
                            std::lock_guard<std::mutex> lock(g_clients_mutex);
                            g_clients[cfd].roomId = rid;
                            g_clients[cfd].spectateRoomId = 0;
                        }
                        lobby_send_frame(cfd, reply); // Forward "OK roomId=..."
                        log_checkpoint("Lobby", "ROOM_CREATED",
                                       "room=" + std::to_string(rid) + " host=" + cli.username + " vis=" + visibility);
                    } else {
                        lobby_send_frame(cfd, "ERR create_failed");
                        log_checkpoint("Lobby", "ROOM_CREATE_FAIL", "host=" + cli.username + " reason=bad_reply");
                    }
                } else {
                    lobby_send_frame(cfd, "ERR db");
                    log_checkpoint("Lobby", "ROOM_CREATE_FAIL", "host=" + cli.username + " reason=db_error");
                }
            }
            else if (cmd == "LIST_ROOMS") {
                if (db_req("Room list", reply))
                    lobby_send_frame(cfd, reply);
                else
                    lobby_send_frame(cfd, "ERR db");
            }
            else if (cmd == "JOIN_ROOM") {
                if (!cli.authed) { lobby_send_frame(cfd, "ERR not_logged_in"); continue; }
                int rid; iss >> rid;
                if(db_req("Room join roomId=" + std::to_string(rid) + " user=" + cli.username, reply)) {
                    if (reply.rfind("OK", 0) == 0) {
                        {
                            std::lock_guard<std::mutex> lock(g_clients_mutex);
                            g_clients[cfd].roomId = rid;
                            g_clients[cfd].spectateRoomId = 0;
                        }
                        lobby_send_frame(cfd, "OK joined");
                        log_checkpoint("Lobby", "ROOM_JOINED",
                                       "room=" + std::to_string(rid) + " user=" + cli.username);
                    } else {
                        lobby_send_frame(cfd, reply); // Forward error
                        log_checkpoint("Lobby", "ROOM_JOIN_FAIL",
                                       "room=" + std::to_string(rid) + " user=" + cli.username + " reason=" + reply);
                    }
                } else {
                    lobby_send_frame(cfd, "ERR db");
                    log_checkpoint("Lobby", "ROOM_JOIN_FAIL",
                                   "room=" + std::to_string(rid) + " user=" + cli.username + " reason=db_error");
                }
            }
            else if (cmd == "LEAVE_ROOM") {
                if (!cli.authed) { lobby_send_frame(cfd, "ERR not_logged_in"); continue; }
                if (cli.roomId == 0) { lobby_send_frame(cfd, "ERR not_in_room"); continue; }

                if (db_req("Room leave roomId=" + std::to_string(cli.roomId) + " user=" + cli.username, reply)) {
                    if (reply.rfind("OK", 0) == 0) {
                        {
                            std::lock_guard<std::mutex> lock(g_clients_mutex);
                            g_clients[cfd].roomId = 0;
                            g_clients[cfd].spectateRoomId = 0;
                        }
                        lobby_send_frame(cfd, reply);
                        log_checkpoint("Lobby", "ROOM_LEFT",
                                       "user=" + cli.username + " room=" + std::to_string(cli.roomId));
                    } else {
                        lobby_send_frame(cfd, reply);
                        log_checkpoint("Lobby", "ROOM_LEAVE_FAIL",
                                       "user=" + cli.username + " room=" + std::to_string(cli.roomId) + " reason=" + reply);
                    }
                } else {
                    lobby_send_frame(cfd, "ERR db");
                    log_checkpoint("Lobby", "ROOM_LEAVE_FAIL",
                                   "user=" + cli.username + " room=" + std::to_string(cli.roomId) + " reason=db_error");
                }
            }
            else if (cmd == "SPECTATE") {
                if (!cli.authed) { lobby_send_frame(cfd, "ERR not_logged_in"); continue; }
                int rid; iss >> rid;
                if (rid == 0) { lobby_send_frame(cfd, "ERR invalid_room"); continue; }
                if (cli.roomId != 0) { lobby_send_frame(cfd, "ERR must_leave_room"); continue; }

                if (cli.spectateRoomId == rid) {
                    lobby_send_frame(cfd, "ERR already_spectating");
                    continue;
                }

                if (db_req("Room spectate roomId=" + std::to_string(rid) + " user=" + cli.username, reply)) {
                    if (reply.rfind("OK", 0) == 0) {
                        uint16_t port = 0;
                        std::string tok;
                        {
                            std::lock_guard<std::mutex> lock(g_games_mutex);
                            auto pit = g_game_ports.find(rid);
                            if (pit != g_game_ports.end()) port = pit->second;
                            auto tit = g_game_tokens.find(rid);
                            if (tit != g_game_tokens.end()) tok = tit->second;
                        }
                        if (port == 0 || tok.empty()) {
                            lobby_send_frame(cfd, "ERR no_active_game");
                            std::string rollback;
                            db_req("Room unspectate roomId=" + std::to_string(rid) + " user=" + cli.username, rollback);
                            log_checkpoint("Lobby", "SPECTATE_FAIL",
                                           "user=" + cli.username + " room=" + std::to_string(rid) + " reason=no_active_game");
                        } else {
                            {
                                std::lock_guard<std::mutex> lock(g_clients_mutex);
                                g_clients[cfd].spectateRoomId = rid;
                            }
                            lobby_send_frame(cfd, "OK SPECTATE");
                            lobby_send_frame(cfd, "SPECTATE_READY port=" + std::to_string(port) + " token=" + tok + " role=SPEC");
                            log_checkpoint("Lobby", "SPECTATE_READY",
                                           "user=" + cli.username + " room=" + std::to_string(rid) + " port=" + std::to_string(port));
                        }
                    } else {
                        lobby_send_frame(cfd, reply);
                        log_checkpoint("Lobby", "SPECTATE_FAIL",
                                       "user=" + cli.username + " room=" + std::to_string(rid) + " reason=" + reply);
                    }
                } else {
                    lobby_send_frame(cfd, "ERR db");
                    log_checkpoint("Lobby", "SPECTATE_FAIL",
                                   "user=" + cli.username + " room=" + std::to_string(rid) + " reason=db_error");
                }
            }
            else if (cmd == "UNSPECTATE") {
                if (!cli.authed) { lobby_send_frame(cfd, "ERR not_logged_in"); continue; }
                if (cli.spectateRoomId == 0) { lobby_send_frame(cfd, "ERR not_spectating"); continue; }

                if (db_req("Room unspectate roomId=" + std::to_string(cli.spectateRoomId) + " user=" + cli.username, reply)) {
                    if (reply.rfind("OK", 0) == 0) {
                        {
                            std::lock_guard<std::mutex> lock(g_clients_mutex);
                            g_clients[cfd].spectateRoomId = 0;
                        }
                        lobby_send_frame(cfd, "OK UNSPECTATE");
                        log_checkpoint("Lobby", "UNSPECTATE", "user=" + cli.username + " room=" + std::to_string(cli.spectateRoomId));
                    } else {
                        lobby_send_frame(cfd, reply);
                        log_checkpoint("Lobby", "UNSPECTATE_FAIL",
                                       "user=" + cli.username + " room=" + std::to_string(cli.spectateRoomId) + " reason=" + reply);
                    }
                } else {
                    lobby_send_frame(cfd, "ERR db");
                    log_checkpoint("Lobby", "UNSPECTATE_FAIL",
                                   "user=" + cli.username + " room=" + std::to_string(cli.spectateRoomId) + " reason=db_error");
                }
            }
            else if (cmd == "INVITE") { // **FIX: Added INVITE**
                if (!cli.authed) { lobby_send_frame(cfd, "ERR not_logged_in"); continue; }
                std::string target_user;
                int rid = cli.roomId;
                iss >> target_user;
                if (rid == 0) { lobby_send_frame(cfd, "ERR not_in_room"); continue; }

                // Only host can invite
                if (db_req("Room invite roomId=" + std::to_string(rid) + " user=" + target_user + " host=" + cli.username, reply)) {
                    lobby_send_frame(cfd, reply); // Forward DB reply (OK or ERR not_host)
                    if (reply.rfind("OK", 0) == 0) {
                        log_checkpoint("Lobby", "ROOM_INVITE",
                                       "room=" + std::to_string(rid) + " from=" + cli.username + " to=" + target_user);
                        std::string room_info;
                        if (db_req("Room get roomId=" + std::to_string(rid), room_info) && room_info.rfind("OK", 0) == 0) {
                            auto info = parse_ok_reply(room_info);
                            std::string room_name = info.count("name") ? info["name"] : "";
                            int target_fd = find_fd_by_username(target_user);
                            if (target_fd != -1) {
                                std::string notice = "ROOM_INVITE roomId=" + std::to_string(rid)
                                                     + " name=" + room_name
                                                     + " host=" + cli.username;
                                lobby_send_frame(target_fd, notice);
                            }
                        }
                    } else {
                        log_checkpoint("Lobby", "ROOM_INVITE_FAIL",
                                       "room=" + std::to_string(rid) + " from=" + cli.username + " to=" + target_user + " reason=" + reply);
                    }
                } else {
                    lobby_send_frame(cfd, "ERR db");
                    log_checkpoint("Lobby", "ROOM_INVITE_FAIL",
                                   "room=" + std::to_string(rid) + " from=" + cli.username + " to=" + target_user + " reason=db_error");
                }
            }
            else if (cmd == "LIST_INVITES") { // **FIX: Added LIST_INVITES**
                 if (!cli.authed) { lobby_send_frame(cfd, "ERR not_logged_in"); continue; }
                 if (db_req("Room listInvites user=" + cli.username, reply)) {
                    lobby_send_frame(cfd, reply);
                 } else {
                    lobby_send_frame(cfd, "ERR db");
                 }
            }
            else if (cmd == "START_GAME") {
                if (!cli.authed) { lobby_send_frame(cfd, "ERR not_logged_in"); continue; }
                int rid = cli.roomId;
                if (rid == 0) { lobby_send_frame(cfd, "ERR not_in_room"); continue; }

                // 1. Get room details from DB
                std::string room_details;
                if (!db_req("Room get roomId=" + std::to_string(rid), room_details) || room_details.rfind("OK", 0) != 0) {
                    lobby_send_frame(cfd, "ERR no_such_room"); continue;
                }

                auto room_map = parse_ok_reply(room_details);
                if (room_map["host"] != cli.username) { lobby_send_frame(cfd, "ERR not_host"); continue; }
                if (room_map["p1"].empty() || room_map["p2"].empty()) { lobby_send_frame(cfd, "ERR need_2_players"); continue; }
                if (room_map["status"] != "idle") { lobby_send_frame(cfd, "ERR already_playing"); continue; }

                // 2. Room is valid, create game server
                uint16_t gport = 0;
                int gfd = open_game_listener(gport);
                if (gfd < 0 || gport < 10000) {
                    lobby_send_frame(cfd, "ERR cannot_start_game_port");
                    log_checkpoint("Lobby", "GAME_START_FAIL",
                                   "room=" + std::to_string(rid) + " reason=listen_error");
                    continue;
                }

                // 3. Generate token and update DB
                std::string token = generate_token();
                std::string p1_name = room_map["p1"];
                std::string p2_name = room_map["p2"];
                db_req("Room setStatus roomId=" + std::to_string(rid) + " status=playing", reply);
                db_req("Room setToken roomId=" + std::to_string(rid) + " token=" + token, reply);

                {
                    std::lock_guard<std::mutex> lock(g_games_mutex);
                    g_game_ports[rid] = gport;
                    g_game_tokens[rid] = token;
                }

                // 4. Tell both players
                std::string msg = "GAME_READY port=" + std::to_string(gport) + " token=" + token;
                int p1_fd = find_fd_by_username(p1_name);
                int p2_fd = find_fd_by_username(p2_name);
                if (p1_fd != -1) lobby_send_frame(p1_fd, msg);
                if (p2_fd != -1) lobby_send_frame(p2_fd, msg);
                log_checkpoint("Lobby", "GAME_START",
                               "room=" + std::to_string(rid) + " port=" + std::to_string(gport) +
                               " p1=" + p1_name + " p2=" + p2_name);

                // 5. Spawn game thread
                auto finish_cb = [rid](int room_id,
                                      const std::string& user1,
                                      int score1,
                                      const std::string& user2,
                                      int score2) {
                    (void)room_id; // room_id == rid
                    std::string reply;
                    db_req("GameLog create roomId=" + std::to_string(rid)
                           + " user1=" + user1
                           + " user2=" + user2
                           + " score1=" + std::to_string(score1)
                           + " score2=" + std::to_string(score2), reply);
                    db_req("Room setStatus roomId=" + std::to_string(rid) + " status=idle", reply);
                };

                std::thread([gfd, p1_name, p2_name, rid, token, finish_cb](){
                    run_tetris_server_on_fd(gfd, p1_name, p2_name, g_db_ip, g_db_port, rid, token, &g_game_registry, finish_cb);
                }).detach();
            }
            else {
                lobby_send_frame(cfd, "ERR unknown_command");
            }
        }
    }

    // Close all client sockets
    {
        std::lock_guard<std::mutex> lock(g_clients_mutex);
        for (auto const& [fd, client] : g_clients) {
            ::close(fd);
        }
        g_clients.clear();
    }
    ::close(listen_fd);
    ::close(db_fd);
    return 0;
}
