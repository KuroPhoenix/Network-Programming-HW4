#include "common.hpp"
#include "lp_framing.hpp"
#include <unordered_map>
#include <vector>
#include <string>
#include <sstream>
#include <iostream>
#include <poll.h>
#include <unistd.h>
#include <set> // For inviteList
#include <fstream>
#include <iomanip>
#include <limits>
#include <cstdlib>
#include <cerrno>
#include <cctype>
#include <algorithm>

// --- Data Models ---
struct UserRec {
    std::string username;
    std::string pass;
    bool online = false;
};

struct RoomRec {
    int id = 0;
    std::string name;
    std::string host; // username of host
    std::string visibility = "public"; // public | private
    std::string status = "idle"; // idle | playing
    std::string p1;
    std::string p2;
    std::string token; // For game server auth
    std::set<std::string> inviteList; // For private rooms
    std::set<std::string> spectators; // Current spectators
};

struct GameLogRec {
    int id = 0;
    int roomId = 0;
    std::string user1, user2;
    int score1 = 0, score2 = 0;
};

// --- In-Memory Database ---
static std::unordered_map<std::string, UserRec> g_users;
static std::unordered_map<int, RoomRec> g_rooms;
static std::vector<GameLogRec> g_gamelogs; // **FIX: Correctly defined**
static int g_next_room_id = 1;
static int g_next_game_id = 1;
// --- End Database ---

static bool load_state(const std::string& path,
                       std::unordered_map<std::string, UserRec>& users,
                       std::unordered_map<int, RoomRec>& rooms,
                       std::vector<GameLogRec>& gamelogs,
                       int& next_room_id,
                       int& next_game_id)
{
    std::ifstream in(path);
    if (!in.is_open()) {
        return false;
    }
    std::string line;
    int max_room = 0;
    int max_log = 0;
    while (std::getline(in, line)) {
        if (line.empty() || line[0] == '#') continue;
        std::istringstream iss(line);
        std::string tag;
        iss >> tag;
        if (tag == "USER") {
            UserRec u;
            int online = 0;
            if (iss >> std::quoted(u.username) >> std::quoted(u.pass) >> online) {
                u.online = (online != 0);
                users[u.username] = u;
            }
        } else if (tag == "ROOM") {
            RoomRec r;
            size_t invite_count = 0;
            size_t spec_count = 0;
            if (!(iss >> r.id >> std::quoted(r.name) >> std::quoted(r.host)
                  >> std::quoted(r.visibility) >> std::quoted(r.status)
                  >> std::quoted(r.p1) >> std::quoted(r.p2) >> std::quoted(r.token))) {
                continue;
            }
            if (iss >> invite_count) {
                for (size_t i = 0; i < invite_count; ++i) {
                    std::string val;
                    if (iss >> std::quoted(val)) r.inviteList.insert(val);
                }
            }
            if (iss >> spec_count) {
                for (size_t i = 0; i < spec_count; ++i) {
                    std::string val;
                    if (iss >> std::quoted(val)) r.spectators.insert(val);
                }
            }
            rooms[r.id] = r;
            if (r.id > max_room) max_room = r.id;
        } else if (tag == "LOG") {
            GameLogRec g;
            if (iss >> g.id >> g.roomId >> std::quoted(g.user1) >> std::quoted(g.user2) >> g.score1 >> g.score2) {
                gamelogs.push_back(g);
                if (g.id > max_log) max_log = g.id;
            }
        }
    }
    if (max_room >= g_next_room_id) next_room_id = max_room + 1;
    if (max_log >= g_next_game_id) next_game_id = max_log + 1;
    return true;
}

static void mark_all_users_offline(std::unordered_map<std::string, UserRec>& users) {
    for (auto& kv : users) {
        kv.second.online = false;
    }
}

static bool save_state(const std::string& path,
                       const std::unordered_map<std::string, UserRec>& users,
                       const std::unordered_map<int, RoomRec>& rooms,
                       const std::vector<GameLogRec>& gamelogs)
{
    std::ofstream out(path, std::ios::trunc);
    if (!out.is_open()) {
        std::cerr << "[DB] failed to write state file: " << path << "\n";
        return false;
    }
    for (const auto& kv : users) {
        const auto& u = kv.second;
        out << "USER " << std::quoted(u.username) << ' ' << std::quoted(u.pass)
            << ' ' << (u.online ? 1 : 0) << '\n';
    }
    for (const auto& kv : rooms) {
        const auto& r = kv.second;
        out << "ROOM " << r.id << ' ' << std::quoted(r.name) << ' ' << std::quoted(r.host)
            << ' ' << std::quoted(r.visibility) << ' ' << std::quoted(r.status)
            << ' ' << std::quoted(r.p1) << ' ' << std::quoted(r.p2) << ' ' << std::quoted(r.token);
        out << ' ' << r.inviteList.size();
        for (const auto& inv : r.inviteList) {
            out << ' ' << std::quoted(inv);
        }
        out << ' ' << r.spectators.size();
        for (const auto& spec : r.spectators) {
            out << ' ' << std::quoted(spec);
        }
        out << '\n';
    }
    for (const auto& g : gamelogs) {
        out << "LOG " << g.id << ' ' << g.roomId << ' '
            << std::quoted(g.user1) << ' ' << std::quoted(g.user2) << ' '
            << g.score1 << ' ' << g.score2 << '\n';
    }
    return true;
}

// Helper to find a room
RoomRec* find_room(int rid) {
    auto it = g_rooms.find(rid);
    if (it == g_rooms.end()) return nullptr;
    return &it->second;
}

// Helper to parse key-value pairs
std::unordered_map<std::string, std::string> parse_kv(std::istringstream& iss) {
    std::unordered_map<std::string, std::string> kv_map;
    std::string kv;
    while (iss >> kv) {
        auto pos = kv.find('=');
        if (pos == std::string::npos) continue;
        kv_map[kv.substr(0, pos)] = kv.substr(pos + 1);
    }
    return kv_map;
}

bool parse_int_field(const std::unordered_map<std::string, std::string>& kv_map,
                     const std::string& key,
                     int& value,
                     bool allow_negative = false) {
    auto it = kv_map.find(key);
    if (it == kv_map.end() || it->second.empty()) return false;
    const std::string& text = it->second;
    char* end = nullptr;
    errno = 0;
    long parsed = std::strtol(text.c_str(), &end, 10);
    if (errno != 0 || end == text.c_str() || *end != '\0') return false;
    if (!allow_negative && parsed < 0) return false;
    if (parsed > std::numeric_limits<int>::max()) return false;
    value = static_cast<int>(parsed);
    return true;
}

static std::string db_peer(int fd) {
    return "client fd=" + std::to_string(fd);
}

static bool db_send_frame(int fd, const std::string& body) {
    log_communication("DB", "TX", db_peer(fd), body);
    return lp_send_frame(fd, body);
}

static bool db_recv_frame(int fd, std::string& out) {
    bool ok = lp_recv_frame(fd, out);
    if (ok) {
        log_communication("DB", "RX", db_peer(fd), out);
    }
    return ok;
}

int main(int argc, char** argv) {
    install_signal_handlers();

    std::string ip = "0.0.0.0";
    uint16_t port = 12977;
    std::string state_file = "db_state.txt";

    // allow overrides but default is zero-config
    if (argc >= 2) ip = argv[1];
    if (argc >= 3) port = static_cast<uint16_t>(std::stoi(argv[2]));
    if (argc >= 4) state_file = argv[3];

    int listen_fd = start_tcp_server(ip.c_str(), port);
    if (listen_fd < 0) return 1;
    std::cerr << "[DB] listening on " << ip << ":" << port << "\n";
    log_checkpoint("DB", "LISTENING", ip + ":" + std::to_string(port));

    bool loaded = load_state(state_file, g_users, g_rooms, g_gamelogs, g_next_room_id, g_next_game_id);
    if (loaded) {
        mark_all_users_offline(g_users);
        log_checkpoint("DB", "STATE_LOADED",
                       "users=" + std::to_string(g_users.size()) +
                       " rooms=" + std::to_string(g_rooms.size()) +
                       " logs=" + std::to_string(g_gamelogs.size()));
    } else {
        log_checkpoint("DB", "STATE_NEW", state_file);
    }

    std::vector<pollfd> pfds;
    pfds.push_back({listen_fd, POLLIN, 0});

    while (running) {
        int rc = ::poll(pfds.data(), pfds.size(), 500);
        if (rc < 0) {
            if (errno == EINTR) continue;
            perror("poll");
            break;
        }
        if (rc == 0) continue;

        for (size_t i = 0; i < pfds.size(); ++i) {
            if (!(pfds[i].revents & POLLIN)) continue;
            if (pfds[i].fd == listen_fd) {
                int cfd = ::accept(listen_fd, nullptr, nullptr);
                if (cfd >= 0) {
                    pfds.push_back({cfd, POLLIN, 0});
                    log_checkpoint("DB", "CLIENT_CONNECTED", "fd=" + std::to_string(cfd));
                }
            } else {
                int cfd = pfds[i].fd;
                std::string req;
                if (!db_recv_frame(cfd, req)) {
                    ::close(cfd);
                    pfds.erase(pfds.begin() + i);
                    --i;
                    log_checkpoint("DB", "CLIENT_DISCONNECTED", "fd=" + std::to_string(cfd));
                    continue;
                }

                std::istringstream iss(req);
                std::string coll, action;
                iss >> coll >> action;
                auto kv_map = parse_kv(iss);
                std::ostringstream resp;

                // --- User Collection ---
                if (coll == "User" && action == "create") {
                    auto& uname = kv_map["username"];
                    if (uname.empty()) resp << "ERR missing_username";
                    else if (g_users.count(uname)) resp << "ERR exists";
                    else {
                        g_users[uname] = UserRec{uname, kv_map["pass"], false};
                        resp << "OK user=" << uname;
                    }
                }
                else if (coll == "User" && action == "read") {
                    auto& uname = kv_map["username"];
                    if (g_users.count(uname)) {
                        auto &u = g_users[uname];
                        resp << "OK username=" << u.username << " pass=" << u.pass << " online=" << (u.online ? "1" : "0");
                    } else {
                        resp << "ERR not_found";
                    }
                }
                else if (coll == "User" && action == "compareSetOnline") {
                    auto uname_it = kv_map.find("username");
                    int expect = 0;
                    int value = 0;
                    if (uname_it == kv_map.end() || uname_it->second.empty()) {
                        resp << "ERR missing_username";
                    } else if (!parse_int_field(kv_map, "expect", expect) || (expect != 0 && expect != 1)) {
                        resp << "ERR invalid_expect";
                    } else if (!parse_int_field(kv_map, "value", value) || (value != 0 && value != 1)) {
                        resp << "ERR invalid_value";
                    } else {
                        const std::string& uname = uname_it->second;
                        auto uit = g_users.find(uname);
                        if (uit == g_users.end()) {
                            resp << "ERR not_found";
                        } else if (uit->second.online != (expect != 0)) {
                            resp << "ERR mismatch";
                        } else {
                            uit->second.online = (value != 0);
                            resp << "OK";
                        }
                    }
                }
                else if (coll == "User" && action == "setOnline") {
                    auto& uname = kv_map["username"];
                    if (!g_users.count(uname)) resp << "ERR not_found";
                    else {
                        g_users[uname].online = (kv_map["online"] == "1");
                        resp << "OK";
                    }
                }
                else if (coll == "User" && action == "listOnline") {
                    resp << "OK ";
                    bool first = true;
                    for (auto &kv : g_users) {
                        if (!kv.second.online) continue;
                        if (!first) resp << ",";
                        resp << kv.first;
                        first = false;
                    }
                }
                // --- Room Collection (Revised) ---
                else if (coll == "Room" && action == "create") {
                    RoomRec r;
                    r.id = g_next_room_id++;
                    r.name = kv_map["name"];
                    r.host = kv_map["host"];
                    r.p1 = kv_map["host"]; // Host is P1
                    std::string vis = kv_map.count("visibility") ? kv_map["visibility"] : "public";
                    std::transform(vis.begin(), vis.end(), vis.begin(), [](unsigned char c){ return static_cast<char>(std::tolower(c)); });
                    if (vis != "public" && vis != "private") vis = "public";
                    r.visibility = vis;
                    r.status = "idle";
                    g_rooms[r.id] = r;
                    resp << "OK roomId=" << r.id;
                }
                else if (coll == "Room" && action == "join") { // **FIX: Enforce rules**
                    int rid = 0;
                    auto user_it = kv_map.find("user");
                    if (!parse_int_field(kv_map, "roomId", rid)) {
                        resp << "ERR invalid_roomId";
                    } else if (user_it == kv_map.end() || user_it->second.empty()) {
                        resp << "ERR missing_user";
                    } else {
                        const std::string& user = user_it->second;
                        RoomRec* r = find_room(rid);
                        if (!r) resp << "ERR not_found";
                        else if (r->status != "idle") resp << "ERR playing";
                        else if (!r->p2.empty()) resp << "ERR full";
                        else if (r->p1 == user || r->p2 == user) resp << "ERR already_in_room";
                        else if (r->visibility == "public" || r->inviteList.count(user)) {
                            r->p2 = user;
                            r->inviteList.erase(user);
                            resp << "OK";
                        } else {
                            resp << "ERR private_room_not_invited";
                        }
                    }
                }
                else if (coll == "Room" && action == "list") { // **FIX: Return all fields**
                    resp << "OK "; // Format: ID:Name:Host:Status:Visibility:P1:P2;
                    for (auto &kv : g_rooms) {
                        auto &r = kv.second;
                        if (r.visibility != "public") continue;
                        resp << r.id << ":" << r.name << ":" << r.host << ":" << r.status << ":" << r.visibility << ":" << r.p1 << ":" << r.p2 << ";";
                    }
                }
                else if (coll == "Room" && action == "get") { // **FIX: Return all fields**
                    int rid = 0;
                    if (!parse_int_field(kv_map, "roomId", rid)) {
                        resp << "ERR invalid_roomId";
                    } else {
                        RoomRec* r = find_room(rid);
                        if (!r) resp << "ERR not_found";
                        else resp << "OK id=" << r->id << " name=" << r->name << " host=" << r->host << " status=" << r->status << " p1=" << r->p1 << " p2=" << r->p2 << " token=" << r->token;
                    }
                }
                else if (coll == "Room" && action == "setStatus") {
                    int rid = 0;
                    auto status_it = kv_map.find("status");
                    if (!parse_int_field(kv_map, "roomId", rid)) {
                        resp << "ERR invalid_roomId";
                    } else if (status_it == kv_map.end() || status_it->second.empty()) {
                        resp << "ERR missing_status";
                    } else {
                        RoomRec* r = find_room(rid);
                        if (!r) resp << "ERR not_found";
                        else {
                            r->status = status_it->second;
                            if (r->status == "idle") { // Reset transient game state only
                                r->token.clear();
                                r->inviteList.clear(); // Clear invites on game end
                                r->spectators.clear();
                            }
                            resp << "OK";
                        }
                    }
                }
                else if (coll == "Room" && action == "setToken") {
                    int rid = 0;
                    auto tok_it = kv_map.find("token");
                    if (!parse_int_field(kv_map, "roomId", rid)) {
                        resp << "ERR invalid_roomId";
                    } else if (tok_it == kv_map.end() || tok_it->second.empty()) {
                        resp << "ERR missing_token";
                    } else {
                        RoomRec* r = find_room(rid);
                        if (!r) resp << "ERR not_found";
                        else {
                            r->token = tok_it->second;
                            resp << "OK";
                        }
                    }
                }
                else if (coll == "Room" && action == "leave") {
                    int rid = 0;
                    auto user_it = kv_map.find("user");
                    if (!parse_int_field(kv_map, "roomId", rid)) {
                        resp << "ERR invalid_roomId";
                    } else if (user_it == kv_map.end() || user_it->second.empty()) {
                        resp << "ERR missing_user";
                    } else {
                        const std::string& user = user_it->second;
                        auto it = g_rooms.find(rid);
                        if (it == g_rooms.end()) {
                            resp << "ERR not_found";
                        } else {
                            RoomRec& room = it->second;
                            if (room.spectators.erase(user) > 0) {
                                resp << "OK";
                            } else {
                                bool is_member = (room.host == user) || (room.p1 == user) || (room.p2 == user);
                                if (!is_member) {
                                    resp << "ERR not_in_room";
                                } else if (room.host == user) {
                                    if (!room.p2.empty()) {
                                        room.host = room.p2;
                                        room.p1 = room.p2;
                                        room.p2.clear();
                                        room.status = "idle";
                                        room.token.clear();
                                        room.inviteList.erase(user);
                                        room.spectators.clear();
                                        resp << "OK";
                                    } else {
                                        g_rooms.erase(it);
                                        resp << "OK closed";
                                    }
                                } else {
                                    if (room.p2 == user) room.p2.clear();
                                    if (room.p1 == user) room.p1.clear();
                                    room.status = "idle";
                                    room.token.clear();
                                    room.inviteList.erase(user);
                                    room.spectators.erase(user);
                                    resp << "OK";
                                }
                            }
                        }
                    }
                }
                else if (coll == "Room" && action == "invite") { // **FIX: Added Invite**
                    int rid = 0;
                    auto user_it = kv_map.find("user");
                    auto host_it = kv_map.find("host");
                    if (!parse_int_field(kv_map, "roomId", rid)) {
                        resp << "ERR invalid_roomId";
                    } else if (host_it == kv_map.end() || host_it->second.empty()) {
                        resp << "ERR missing_host";
                    } else if (user_it == kv_map.end() || user_it->second.empty()) {
                        resp << "ERR missing_user";
                    } else {
                        RoomRec* r = find_room(rid);
                        if (!r) resp << "ERR not_found";
                        else if (r->host != host_it->second) resp << "ERR not_host";
                        else {
                            r->inviteList.insert(user_it->second);
                            resp << "OK invited=" << user_it->second;
                        }
                    }
                }
                else if (coll == "Room" && action == "spectate") {
                    int rid = 0;
                    auto user_it = kv_map.find("user");
                    if (!parse_int_field(kv_map, "roomId", rid)) {
                        resp << "ERR invalid_roomId";
                    } else if (user_it == kv_map.end() || user_it->second.empty()) {
                        resp << "ERR missing_user";
                    } else {
                        RoomRec* r = find_room(rid);
                        if (!r) resp << "ERR not_found";
                        else if (r->status != "playing") resp << "ERR not_playing";
                        else {
                            r->spectators.insert(user_it->second);
                            resp << "OK";
                        }
                    }
                }
                else if (coll == "Room" && action == "unspectate") {
                    int rid = 0;
                    auto user_it = kv_map.find("user");
                    if (!parse_int_field(kv_map, "roomId", rid)) {
                        resp << "ERR invalid_roomId";
                    } else if (user_it == kv_map.end() || user_it->second.empty()) {
                        resp << "ERR missing_user";
                    } else {
                        RoomRec* r = find_room(rid);
                        if (!r) resp << "ERR not_found";
                        else if (!r->spectators.erase(user_it->second)) resp << "ERR not_spectating";
                        else resp << "OK";
                    }
                }
                else if (coll == "Room" && action == "listInvites") { // **FIX: Added listInvites**
                    auto user_it = kv_map.find("user");
                    if (user_it == kv_map.end() || user_it->second.empty()) {
                        resp << "ERR missing_user";
                    } else {
                        resp << "OK "; // Format: ID:Name:Host;
                        for (auto &kv : g_rooms) {
                            if (kv.second.inviteList.count(user_it->second)) {
                                resp << kv.second.id << ":" << kv.second.name << ":" << kv.second.host << ";";
                            }
                        }
                    }
                }
                // --- GameLog Collection ---
                else if (coll == "GameLog" && action == "create") {
                    int room_id = 0;
                    int score1 = 0;
                    int score2 = 0;
                    auto user1_it = kv_map.find("user1");
                    auto user2_it = kv_map.find("user2");
                    if (!parse_int_field(kv_map, "roomId", room_id)) {
                        resp << "ERR invalid_roomId";
                    } else if (!parse_int_field(kv_map, "score1", score1)) {
                        resp << "ERR invalid_score1";
                    } else if (!parse_int_field(kv_map, "score2", score2)) {
                        resp << "ERR invalid_score2";
                    } else if (user1_it == kv_map.end() || user1_it->second.empty() ||
                               user2_it == kv_map.end() || user2_it->second.empty()) {
                        resp << "ERR missing_user";
                    } else {
                        GameLogRec g;
                        g.id = g_next_game_id++;
                        g.roomId = room_id;
                        g.user1 = user1_it->second;
                        g.user2 = user2_it->second;
                        g.score1 = score1;
                        g.score2 = score2;
                        g_gamelogs.push_back(g); // **FIX: Correctly persist**
                        resp << "OK gameId=" << g.id;
                    }
                }
                else if (coll == "GameLog" && action == "list") { // **FIX: Added list**
                    resp << "OK ";
                    for (auto &g : g_gamelogs) {
                         resp << "id=" << g.id << " room=" << g.roomId << " p1=" << g.user1 << " s1=" << g.score1 << " p2=" << g.user2 << " s2=" << g.score2 << ";";
                    }
                }
                else {
                    resp << "ERR unknown_command";
                }

                std::string response = resp.str();
                db_send_frame(cfd, response);
            }
        }
    }

    for (auto &p : pfds) {
        if (p.fd >= 0) ::close(p.fd);
    }
    save_state(state_file, g_users, g_rooms, g_gamelogs);
    log_checkpoint("DB", "STATE_SAVED",
                   "users=" + std::to_string(g_users.size()) +
                   " rooms=" + std::to_string(g_rooms.size()) +
                   " logs=" + std::to_string(g_gamelogs.size()));
    return 0;
}
