#include <cstring>
#include <iostream>
#include <string>
#include <unistd.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <fstream>
#include <sys/poll.h>
#include <sys/types.h>
#include <netdb.h>
#include <vector>
#include <arpa/inet.h>
#include "config.h"
#include <string>
#include <stdexcept>
#include <chrono>
#include <cerrno>
#include <sstream>
#include <unordered_set>
using namespace std;
volatile std::sig_atomic_t running = 1;
void handle_signal(int /*signo*/) {
    running = 0;
}
void install_signal_handlers() {
    struct sigaction sa{};
    sa.sa_handler = handle_signal;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = 0;            

    sigaction(SIGINT,  &sa, nullptr);  // Ctrl-C
    sigaction(SIGTERM, &sa, nullptr);  // polite kill (e.g., from system)

    // Optional but recommended for socket apps: ignore SIGPIPE so writes to a
    // closed peer don’t kill the process. You’ll get EPIPE on send/write instead.
    struct sigaction ign{};
    ign.sa_handler = SIG_IGN;
    sigemptyset(&ign.sa_mask);
    ign.sa_flags = 0;
    sigaction(SIGPIPE, &ign, nullptr);
}


IpPort ip_port_from_sockaddr(const sockaddr_storage& ss) {
    char host[NI_MAXHOST]{};
    char serv[NI_MAXSERV]{};

    socklen_t len = 0;
    if (ss.ss_family == AF_INET)   len = sizeof(sockaddr_in);
    else if (ss.ss_family == AF_INET6) len = sizeof(sockaddr_in6);
    else throw std::runtime_error("Unsupported address family");

    const int rc = getnameinfo(
        reinterpret_cast<const sockaddr*>(&ss), len,
        host, sizeof(host),
        serv, sizeof(serv),
        NI_NUMERICHOST | NI_NUMERICSERV   // numeric, no DNS lookups
    );
    if (rc != 0) throw std::runtime_error(gai_strerror(rc));

    return {host, serv};
}

bool send_msg(int fd, const std::string& s) {
    const char* p = s.data();
    size_t n = s.size();

    while (n > 0) {
        ssize_t w = ::send(fd, p, n
#ifdef MSG_NOSIGNAL
                           , MSG_NOSIGNAL   // avoid SIGPIPE if available
#else
                           , 0
#endif
        );
        if (w > 0) {
            p += static_cast<size_t>(w);
            n -= static_cast<size_t>(w);
            continue;
        }
        if (w == 0) {
            // treat as peer gone; surface as failure
            errno = EPIPE;
            return false;
        }
        // w < 0 → error
        if (errno == EINTR) continue;                 // interrupted → retry

        if (errno == EAGAIN || errno == EWOULDBLOCK) {
            // Non-blocking socket and no room right now.
            // Minimal backoff so we don't busy-spin:
            struct pollfd pfd{fd, POLLOUT, 0};
            (void) ::poll(&pfd, 1, 100);              // 100ms wait
            continue;                                  // then retry
        }

        // Unrecoverable error (EPIPE, ECONNRESET, etc.)
        return false;
    }
    return true; // everything sent
}

bool udp_send_msg(int fd, const std::string& s, const sockaddr* to, socklen_t tolen) {
    for (;;) {
        ssize_t w = sendto(fd, s.data(), s.size(), 0, to, tolen);
        if (w < 0) {
            if (errno == EINTR) continue;    // interrupted: retry
            return false;                    // EAGAIN/EWOULDBLOCK on nonblocking, EMSGSIZE, etc.
        }
        return static_cast<size_t>(w) == s.size();
    }
}
// tools.cpp (or a small net_utils.cpp)
bool construct_udp_addr(const char* ip, const char* port, sockaddr_storage& out, socklen_t& outlen) {
    addrinfo hints{}, *res = nullptr;
    memset(&hints, 0, sizeof(hints));
    hints.ai_family   = AF_INET;      // or AF_UNSPEC if you want v4/v6
    hints.ai_socktype = SOCK_DGRAM;

    int rc = getaddrinfo(ip, port, &hints, &res);
    if (rc != 0 || !res) return false;

    memcpy(&out, res->ai_addr, res->ai_addrlen);
    outlen = (socklen_t)res->ai_addrlen;
    freeaddrinfo(res);
    return true;
}

bool recv_line(int fd, std::string& out) {
    out.clear();
    char c;
    const auto deadline = chrono::steady_clock::now() + chrono::milliseconds(TIMEOUT);

    auto remaining_ms = [&]() -> int {
        auto left = duration_cast<chrono::milliseconds>(deadline - chrono::steady_clock::now()).count();
        return left > 0 ? static_cast<int>(left) : 0;
    };

    for (;;) {
        // Wait for readability up to the remaining time
        int ms = remaining_ms();
        if (ms == 0) { errno = EAGAIN; return false; }

        struct pollfd pfd{fd, POLLIN, 0};
        int pr;
        do { pr = ::poll(&pfd, 1, ms); } while (pr < 0 && errno == EINTR);

        if (pr == 0)               { errno = EAGAIN; return false; } // overall timeout
        if (pr < 0)                { /* errno set by poll */ return false; }
        if (!(pfd.revents & POLLIN)) continue; // spurious wakeup

        // Now actually read one byte
        ssize_t r;
        do { r = ::recv(fd, &c, 1, 0); } while (r < 0 && errno == EINTR);

        if (r == 0)                { errno = ECONNRESET; return false; } // peer closed
        if (r < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) continue;       // race, re-poll
            return false;                                                // hard error
        }

        if (c == '\n') {
            if (!out.empty() && out.back() == '\r') out.pop_back();      // CRLF
            return true;
        }
        out.push_back(c);
    }
}

bool recv_udp(int fd, std::string& out, sockaddr_storage* src, socklen_t* srclen) {
    out.clear();

    sockaddr_storage peer{};
    socklen_t plen = sizeof(peer);
    char buf[2048];
    for (;;) {
        ssize_t r = recvfrom(fd, buf, sizeof(buf), 0, (sockaddr*)&peer, &plen);
        if (r < 0) {
            if (errno == EINTR) continue;                   // retry on signal
            return false;                                   // error (EAGAIN if non-blocking w/o data)
        }
        // r == 0 is a valid *empty* UDP datagram; treat as success
        out.assign(buf, buf + r);

        // Trim trailing CRLF for convenience (optional)
        while (!out.empty() && (out.back() == '\n' || out.back() == '\r'))
            out.pop_back();

        if (src)    *src    = peer;
        if (srclen) *srclen = plen;
        return true;
    }
}

void erase_fd(int fd, struct pollfd **pfds, int *fd_count)
{
    for (int i = 0; i < *fd_count; ++i) {
        if ((*pfds)[i].fd == fd) {
            // Move the last entry into this slot
            (*pfds)[i] = (*pfds)[*fd_count - 1];
            (*fd_count)--;
            return;
        }
    }
    // not found -> no-op
}

int clientRecvError(int fd, const std::string& player, const std::string& why) {
    close(fd);
    fprintf(stderr, "[player %s] %s\n", player.c_str(), why.c_str());
    return -1;
}

void parse_line(const std::string& msg, std::string (&out)[3]) {
    size_t s1 = msg.find(' ');
    if (s1 == std::string::npos) { out[0]=msg; out[1]=out[2]=""; return; }
    size_t s2 = msg.find(' ', s1+1);
    out[0] = msg.substr(0, s1);
    if (s2 == std::string::npos) { out[1] = msg.substr(s1+1); out[2].clear(); }
    else { out[1] = msg.substr(s1+1, s2-(s1+1)); out[2] = msg.substr(s2+1); }
}



int clientAccessAccountInfo(int fd, const string& player, const string& username, const string& password, const string& action) {
    /*
     * 3 actions: findUsername, registration, login.
     * findUsername: Lobby return format
     * 1. "<player> findUsername EXIST -> username already exists (1)
     * 2. "<player> findUsername NOEXIST -> username does not exist yet (0)
     * 3. Other errors (-1)
     * Registration/Login: Lobby return format
     * 1. "<player> <action> OK -> action successful (0)
     * 2. "<player> <action> <Msg> -> error occurred (1)
     * 3. Other errors (-1)
     *
     */
    string reply;
    string arr[3];
    if (action == "findUsername") {
        if(!send_msg(fd, player + " " + action + " " + username + "\n")){
            return clientRecvError(fd, player, "findUsername Send Error");
        }
        if (!recv_line(fd, reply)) {
            return clientRecvError(fd, player, "findUsername Recv Error");
        }
        parse_line(reply, arr);
        if(arr[0] == "ERR"){
            return -1;
        }
        if (arr[0] == player && arr[1] == action && arr[2] == "EXIST") {
            return 1;
        }
        if (arr[0] == player && arr[1] == action && arr[2] == "NOEXIST") {
            return 0;
        }
        cout << "[player" << player << "] Unexpected error occurred at finding Username." << endl;
        return -1;
    }
    if(!send_msg(fd, player + " " + action + " " + username + " " + password + "\n")){
        return clientRecvError(fd, player, "Login/Registration Send Error");
    }
    if (!recv_line(fd, reply)) {
        return clientRecvError(fd, player, "Login/Registration Recv Error");
    }
    parse_line(reply, arr);
    if(arr[0] == "ERR"){
        return -1;
    }
    if (arr[0] == player && arr[1] == action) {
        if (arr[2] == "OK") {
            cout << "player[" << player << "] " << action << " successful!" << endl;
            return 0;
        }
        if (arr[2] == "ONLINE") {
            cout << "player[" << player << "] " << action << " duplicate login detected!" << endl;
            return 2;
        }
        if (arr[2] == "EXIST") {
            cout << "player[" << player << "] " << action << " duplicate registration detected!" << endl;
            return 2;
        }
        else {
            cout << "player[" << player << "] " << action << " error: " << arr[2] << endl;
            return 1;
        }
    }
    cout << "player[" << player << "] Unexpected error occurred at " << action << "." << endl;
    cout << arr[0] << " " << arr[1] << " " << arr[2] << endl;

    return -1;
}

int login(int fd, const string& player, string* user) {
    bool validInput = false;
    string username, password;
    while (!validInput) {
        cout << "[player" << player << "] login: Please enter your username: " << endl;
        std::getline(std::cin >> std::ws, username);  // consume leading whitespace
        int status = clientAccessAccountInfo(fd, player, username, "", "findUsername");
        if (status == 0) {
            cout << "[player" << player << "] Username does not exist. Please try again." << endl;
            return 1;
        }
        if (status == -1) {
            cout << "[player" << player << "] an unexpected error occurred while finding Username." << endl;
            return -1;
        }
        cout << "[player" << player << "] login: Please enter your password: " << endl;
        getline(cin >> ws, password);
        status = clientAccessAccountInfo(fd, player, username, password, "login");
        if (status == 1) {
            cout << "[player" << player << "] login failed." << endl;
            continue;
        }
        if (status == 2) {
            cout  << "[player" << player << "] duplicate login." << endl;
            return 1;
        }
        validInput = true;
    }
    cout << "Welcome, " << username << "!" << endl;
    *user = username;
    return 0;
}

int reg(int fd, const string& player) {
    bool validInput = false;
    string username, password;
    while (!validInput) {
        cout << "[player" << player << "] registration: Please enter your new username: " << endl;
        getline(cin >> ws, username);
        int status = clientAccessAccountInfo(fd, player, username, "", "findUsername");
        if (status == 1) {
            cout << "[player" << player << "] Username already exists. Please re-enter a new username." << endl;
            continue;
        }
        if (status == 2) {
            cout << "[player" << player << "] account already exists. Please re-enter." << endl;
            continue;
        }
        if (status == -1) {
            cout << "[player" << player << "] an unexpected error occurred while finding Username." << endl;
            return -1;
        }
        validInput = true;
    }
    cout << "[player" << player << "] registration: Please enter your new password: " << endl;
    getline(cin >> ws, password);
    int status = clientAccessAccountInfo(fd, player, username, password, "registration");
    if (status == 0) {
        cout << "[player" << player << "] registration complete. Please log in using your new credentials." << endl;

    }
    else {
        cout << "[player" << player << "] error occured while recording your account information to database." << endl;
    }
    return 0;
}

int welcome(int fd, const string& player, bool& isLoggedIn) {
    string reply;
    string arr[3];
    if(!send_msg(fd, player + " connection SYN\n")){
        return clientRecvError(fd, player, "CONN_SYN SEND Error");
    }
    if (!recv_line(fd, reply)) {
        return clientRecvError(fd, player, "CONN_ACK Recv Error");
    }
    parse_line(reply, arr);
    if(arr[0] == "ERR"){
        return -1;
    }
    if (!(arr[0] == player && arr[1] == "connection" && arr[2] == "ACK")) {
        fprintf(stderr, "[playerA] connect error: %s\n", strerror(errno));
        return -1;
    }
    if (!recv_line(fd, reply)) {
        return clientRecvError(fd, player, "welcomeMsg Recv Error");
    }

    parse_line(reply, arr);
    if(arr[0] == "ERR"){
        return -1;
    }
    if (!(arr[0] == player && arr[1] == "welcomeMsg")) {
        fprintf(stderr, "[playerA] recv error: %s\n", strerror(errno));
        return -1;
    }
    string userInput;
    bool validInput = false;
    bool exit = false;
    string name;
    while (!exit) {
        if (!running) {
            return 2;
        }
        cout << arr[2] << endl;
        validInput = false;

        if (!(std::cin >> std::ws)) {
            if (!running) {
                return 2;
            }
            if (std::cin.eof()) {
                return 2;
            }
            std::cin.clear();
            continue;
        }

        if (!std::getline(std::cin, userInput)) {
            if (!running || std::cin.eof()) {
                return 2;
            }
            std::cin.clear();
            continue;
        }
        if (userInput == "register") {
            int status = reg(fd, player);
            if (status == 0) {
                userInput = "login";
            }
            else {
                cout << "[player" << player << "] welcome error: occurred at registration." << endl;
                validInput = false;
                exit = true;
            }
        }
        if (userInput == "login") {
            int status = login(fd, player, &name);
            if (status == 0) {
                validInput = true;
                exit = true;
                isLoggedIn = true;
                sock_to_user[fd] = name;
                user_to_sock[name] = fd;
                username_to_info[name].online = true;
            }
            else if (status == 1) {
                cout << "Back to welcome menu..." << endl;
                validInput = true;
                exit = false;
            }
            else {
                cout << "[player" << player << "] welcome error: occurred at log in." << endl;
                validInput = false;
                exit = true;
                return -1;
            }
        }

        if (userInput == "quit") {
            exit = true;
            validInput = true;
        }
        if (!validInput) {
            cout << "[player" << player << "] invalid input. Please re-enter your option." << endl;
        }
    }
    if (!isLoggedIn) {
        cout << "[player" << player << "] lobby error: occurred at after welcome." << endl;
        return -1;
    }
    return 0;
}

int getListeningSocket(const std::string& IP, const std::string& PORT, const std::string& protocol) {
    addrinfo hints{}, *res, *available;
    int sockfd = 0;
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_INET;
    if (protocol == "TCP") hints.ai_socktype = SOCK_STREAM;
    else hints.ai_socktype = SOCK_DGRAM;
    hints.ai_flags = AI_PASSIVE;
    int status = getaddrinfo(IP.c_str(), PORT.c_str(), &hints, &res);
    if (status != 0) {
        fprintf(stderr, "getaddrinfo: %s\n", gai_strerror(status)); return -1;
    }
    for (available = res; available != NULL; available = available->ai_next) {
        sockfd = socket(available->ai_family, available->ai_socktype, available->ai_protocol);
        if (sockfd < 0) {
            continue;
        }
        int yes = 1;
        setsockopt(sockfd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(int));
        if (bind(sockfd, available->ai_addr, available->ai_addrlen) < 0) {
            close(sockfd);
            continue;
        }
        break;
    }

    if (available == nullptr) {
        cout << "No available socket was found for listener." << endl;
        return -1;
    }

    freeaddrinfo(res);
    if (protocol == "TCP") {
        if (listen(sockfd, BACKLOG) < 0) {
            fprintf(stderr, "listen error: %s\n", strerror(errno));
            return -1;
        }
    }
    return sockfd;
}

// tools.cpp
int getUDPSocket() {
    int s = socket(AF_INET, SOCK_DGRAM, 0);
    if (s < 0) { perror("socket"); return -1; }
    // set recv timeout
    timeval tv{0, 500000};  // 500 ms
    setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    return s; // no bind() needed for sending/scanning
}



int tcp_connect_to(const string &player, const string& to, const string& IP, const string& PORT) {
    /*setting up getaddrinfo()*/
    struct addrinfo hints{};
    memset(&hints, 0, sizeof(hints));
    hints.ai_flags = 0;
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_protocol = IPPROTO_TCP;
    struct addrinfo *res, *p;
    int status = getaddrinfo(IP.c_str(), PORT.c_str(), &hints, &res);
    if (status != 0) {
        fprintf(stderr, "getaddrinfo error: %s\n", gai_strerror(status));
        return -1;
    }

    int sockfd = 0;
    char ip_str[INET_ADDRSTRLEN];
    for (p = res; p != NULL; p = p->ai_next) {
        sockfd = socket(p->ai_family, p->ai_socktype, p->ai_protocol);
        if (sockfd == -1) {
            fprintf(stderr, "[player%s to %s] socket error: %s\n", player.c_str(), to.c_str(), strerror(errno));
            continue;
        }
        const void* src = nullptr;
        int family = p->ai_family;
        if (family == AF_INET) {
            const sockaddr_in* sin = reinterpret_cast<const sockaddr_in*>(p->ai_addr);
            src = &sin->sin_addr;
        } else if (family == AF_INET6) {
            const sockaddr_in6* sin6 = reinterpret_cast<const sockaddr_in6*>(p->ai_addr);
            src = &sin6->sin6_addr;
        }
        inet_ntop(p->ai_family, src, ip_str, INET_ADDRSTRLEN);
        cout << "[player" << player << " to " << to << "]: Attempting connection " << ip_str << "..."<< endl;

        status = connect(sockfd, p->ai_addr, p->ai_addrlen);
        if (status != 0) {
            fprintf(stderr, "[player%s to %s] connect error: %s\n", player.c_str(), to.c_str(), strerror(errno));
            close(sockfd);
            continue;
        }
        cout << "[player" << player << " to " << to << "]: Connection established" << endl;
        break;
    }
    if (p == nullptr) {
        fprintf(stderr, "[player%s to %s] failed to connect: %s\n", player.c_str(), to.c_str(), strerror(errno));
        close(sockfd);
        freeaddrinfo(res);
        return -1;
    }
    const void* src = nullptr;
    int family = p->ai_family;
    if (family == AF_INET) {
        const sockaddr_in* sin = reinterpret_cast<const sockaddr_in*>(p->ai_addr);
        src = &sin->sin_addr;
    } else if (family == AF_INET6) {
        const sockaddr_in6* sin6 = reinterpret_cast<const sockaddr_in6*>(p->ai_addr);
        src = &sin6->sin6_addr;
    }
    inet_ntop(p->ai_family, src, ip_str, INET_ADDRSTRLEN);
    cout << "[player" << player << " to " << to << "]: Connected to " << ip_str << "!"<< endl;
    freeaddrinfo(res);
    return sockfd;
}

bool query_bound_port(int fd, std::uint16_t& out_port) {
    sockaddr_storage ss{};
    socklen_t len = sizeof(ss);
    if (getsockname(fd, reinterpret_cast<sockaddr*>(&ss), &len) != 0) {
        return false;
    }
    if (ss.ss_family == AF_INET) {
        out_port = ntohs(reinterpret_cast<sockaddr_in*>(&ss)->sin_port);
        return true;
    }
    if (ss.ss_family == AF_INET6) {
        out_port = ntohs(reinterpret_cast<sockaddr_in6*>(&ss)->sin6_port);
        return true;
    }
    errno = EAFNOSUPPORT;
    return false;
}

int bind_udp_port_range(const char* ip, std::uint16_t min_port, std::uint16_t max_port, std::uint16_t& out_port) {
    if (min_port > max_port) {
        errno = EINVAL;
        return -1;
    }

    int last_errno = 0;
    for (std::uint32_t port = min_port; port <= max_port; ++port) {
        int fd = socket(AF_INET, SOCK_DGRAM, 0);
        if (fd < 0) {
            return -1;
        }

        int yes = 1;
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
#ifdef SO_REUSEPORT
        setsockopt(fd, SOL_SOCKET, SO_REUSEPORT, &yes, sizeof(yes));
#endif

        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_port = htons(static_cast<std::uint16_t>(port));
        if (!ip || std::strcmp(ip, "0.0.0.0") == 0) {
            addr.sin_addr.s_addr = INADDR_ANY;
        } else if (inet_pton(AF_INET, ip, &addr.sin_addr) != 1) {
            close(fd);
            last_errno = EINVAL;
            continue;
        }

        if (bind(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0) {
            timeval tv{0, 500000};
            setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
            out_port = static_cast<std::uint16_t>(port);
            return fd;
        }

        last_errno = errno;
        close(fd);
    }

    if (last_errno != 0) {
        errno = last_errno;
    }
    return -1;
}

int discover_waiting_players(int fd, const std::string& player, std::vector<endpoint>& opponents) {
    opponents.clear();
    if (fd < 0) {
        errno = EBADF;
        return -1;
    }

    const std::string probe = player + " DISCOVER WHO\n";
    for (const auto& host : PLAYERB_SCAN_HOSTS) {
        for (std::uint32_t port = PLAYERB_PORT_MIN; port <= PLAYERB_PORT_MAX; ++port) {
            sockaddr_storage dest{};
            socklen_t destlen = sizeof(dest);
            const std::string port_str = std::to_string(port);
            if (!construct_udp_addr(host.c_str(), port_str.c_str(), dest, destlen)) {
                continue;
            }
            (void)udp_send_msg(fd, probe, reinterpret_cast<const sockaddr*>(&dest), destlen);
        }
    }

    const auto deadline = std::chrono::steady_clock::now() +
                          std::chrono::milliseconds(PLAYERB_SCAN_TOTAL_WINDOW_MS);
    std::unordered_set<std::string> seen;

    while (std::chrono::steady_clock::now() < deadline) {
        auto now = std::chrono::steady_clock::now();
        int remaining_ms = static_cast<int>(
            std::chrono::duration_cast<std::chrono::milliseconds>(deadline - now).count());
        if (remaining_ms <= 0) break;
        int timeout_ms = PLAYERB_SCAN_SLICE_MS;
        if (timeout_ms > remaining_ms) timeout_ms = remaining_ms;

        std::string reply;
        sockaddr_storage src{};
        socklen_t srclen = sizeof(src);
        if (!recv_udp_with_timeout(fd, reply, &src, &srclen, timeout_ms)) {
            if (errno == EAGAIN || errno == EINTR) {
                continue;
            }
            return -1;
        }

        std::string arr[3];
        parse_line(reply, arr);
        if (arr[1] != "HERE") continue;

        if (arr[2] == "WAITING") {
            IpPort ip_port = ip_port_from_sockaddr(src);
            std::string key = ip_port.ip + ":" + ip_port.port;
            if (seen.insert(key).second) {
                endpoint entry{};
                entry.addr = src;
                entry.addrlen = srclen;
                entry.label = arr[0].empty() ? key : arr[0] + " (" + key + ")";
                opponents.push_back(entry);
            }
        }
    }

    return 0;
}

std::string visualise_sockaddr_storage(const sockaddr_storage& ss) {
    char host[NI_MAXHOST], serv[NI_MAXSERV];
    socklen_t len = (socklen_t)sizeof(sockaddr_in);
    if (getnameinfo((const sockaddr*)&ss, len, host, sizeof(host), serv, sizeof(serv), NI_NUMERICHOST | NI_NUMERICSERV) != 0) {
        return "<unprintable>";
    }
    return std::string(host) + ":" + serv;
}

// tools.cpp
int start_tcp_server(std::string ip, uint16_t &out_port) {
    addrinfo hints{}, *res=nullptr;
    memset(&hints,0,sizeof(hints));
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_flags = AI_PASSIVE;

    if (getaddrinfo(ip.c_str(), nullptr, &hints, &res)!=0) return -1;

    int s = socket(res->ai_family, SOCK_STREAM, 0);
    if (s<0) { freeaddrinfo(res); return -1; }
    int yes=1; setsockopt(s,SOL_SOCKET,SO_REUSEADDR,&yes,sizeof(yes));

    // bind to ephemeral port >=10000: loop until bind succeeds
    for (uint16_t p=10000; p<65535; ++p) {
        ((sockaddr_in*)res->ai_addr)->sin_port = htons(p);
        if (bind(s, res->ai_addr, res->ai_addrlen)==0) {
            out_port = p;
            if (listen(s, BACKLOG)==0) { freeaddrinfo(res); return s; }
            break;
        }
        if (errno!=EADDRINUSE) break;
    }
    close(s); freeaddrinfo(res); return -1;
}

bool recv_udp_with_timeout(int fd, std::string& out, sockaddr_storage* src, socklen_t* srclen, int timeout_ms){
    struct pollfd pfd{fd, POLLIN, 0};
    int rc = poll(&pfd, 1, timeout_ms);
    if (rc == 0) { errno = EAGAIN; return false; }     // timeout
    if (rc < 0)  { return false; }                     // poll error (errno set)
    return recv_udp(fd, out, src, srclen);             // your existing function
}


void clean_up(int& game_tcp_fd, int& invite_udp_fd, int& sockfd, const string& player, const string& reason) {
    if(reason == "INTERRUPT") cout << "[player" << player << "] An interrupt has been detected. Ending connection." << endl;
    else if(reason == "MANUAL") cout << "[player" << player << "] has quit the game. Ending connection." << endl;
    if(sockfd != -1) {
        if(!send_msg(sockfd, player + " LOGOUT " + reason + "\n")){
            fprintf(stderr, "[player %s] %s\n", player.c_str(), "LOGOUT SEND ERROR");
        }
    }
    if(sockfd != -1) close(sockfd);
    if(game_tcp_fd != -1) close(game_tcp_fd);
    if(invite_udp_fd != -1) close(invite_udp_fd);
    sockfd = -1;
    invite_udp_fd = -1;
    game_tcp_fd = -1;
}


bool check_opponent(int fd) {
    if (fd < 0) return true;

    struct pollfd pfd{fd, POLLIN, 0};
    int rc;
    do { rc = poll(&pfd, 1, 0); } while (rc < 0 && errno == EINTR);
    if (rc < 0) return false;
    if (rc == 0) return true;

    if (pfd.revents & (POLLERR | POLLHUP | POLLNVAL)) return false;
    if (!(pfd.revents & POLLIN)) return true;

    char buf[BUFFER_SIZE];
    const ssize_t peeked = recv(fd, buf, sizeof(buf), MSG_PEEK);
    if (peeked <= 0) {
        if (peeked == 0) return false;
        if (errno == EAGAIN || errno == EWOULDBLOCK) return true;
        return false;
    }

    size_t newline = 0;
    bool has_newline = false;
    for (; newline < static_cast<size_t>(peeked); ++newline) {
        if (buf[newline] == '\n') {
            has_newline = true;
            break;
        }
    }
    if (!has_newline) return true;

    std::string line(buf, buf + newline);
    if (!line.empty() && line.back() == '\r') line.pop_back();

    std::string arr[3];
    parse_line(line, arr);
    if (arr[1] == "LOGOUT" && arr[2] == "INTERRUPT") {
        std::string discard;
        if (!recv_line(fd, discard)) return false;
        std::cout << "[Info] Opponent " << arr[0] << " has disconnected." << std::endl;
        return true;
    }

    return true;
}



bool fetch_stats(int lobbyFD, const std::string& player, int& wins, int& losses) {
    wins = 0;
    losses = 0;
    if(!send_msg(lobbyFD, player + " STATS REQUEST\n")){
        return false;
    }
    std::string reply;
    if(!recv_line(lobbyFD, reply)){
        return false;
    }
    std::string arr[3];
    parse_line(reply, arr);
    if(arr[0] != player || arr[1] != "STATS"){
        return false;
    }
    std::istringstream iss(arr[2]);
    if(!(iss >> wins >> losses)){
        return false;
    }
    return true;
}


