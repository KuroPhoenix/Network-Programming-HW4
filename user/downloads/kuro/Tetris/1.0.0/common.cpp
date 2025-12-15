#include "common.hpp"
#include <unistd.h>
#include <cstdio>
#include <cstring>
#include <cerrno>
#include <netinet/in.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <atomic>
#include <chrono>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <sstream>

namespace {
std::mutex g_log_mutex;
std::atomic<LogLevel> g_log_level(LogLevel::Info);

std::string now_timestamp() {
    using namespace std::chrono;
    auto now = system_clock::now();
    auto tt = system_clock::to_time_t(now);
    std::tm tm_buf{};
#if defined(_WIN32)
    localtime_s(&tm_buf, &tt);
#else
    localtime_r(&tt, &tm_buf);
#endif
    auto ms = duration_cast<milliseconds>(now.time_since_epoch()) % 1000;
    std::ostringstream os;
    os << std::put_time(&tm_buf, "%Y-%m-%d %H:%M:%S")
       << '.' << std::setfill('0') << std::setw(3) << ms.count();
    return os.str();
}

const char* level_to_string(LogLevel level) {
    switch (level) {
        case LogLevel::Error: return "ERROR";
        case LogLevel::Warn:  return "WARN";
        case LogLevel::Info:  return "INFO";
        case LogLevel::Debug: return "DEBUG";
        case LogLevel::Trace: return "TRACE";
        default: return "INFO";
    }
}

bool is_delim(char c) {
    switch (c) {
        case ' ': case '\\t': case '\\n': case '\\r':
            return true;
        default:
            return false;
    }
}

std::string sanitize_payload(const std::string& payload) {
    std::string sanitized = payload;
    auto mask_key = [&](const std::string& key) {
        size_t pos = 0;
        while ((pos = sanitized.find(key, pos)) != std::string::npos) {
            size_t value_start = pos + key.size();
            size_t value_end = value_start;
            while (value_end < sanitized.size() && !is_delim(sanitized[value_end])) {
                ++value_end;
            }
            sanitized.replace(value_start, value_end - value_start, "***");
            pos = value_end;
        }
    };
    mask_key("pass=");
    mask_key("password=");
    mask_key("token=");
    mask_key("auth=");
    mask_key("secret=");

    auto mask_positional = [&](const std::string& prefix) {
        if (sanitized.rfind(prefix, 0) != 0) return;
        std::istringstream iss(sanitized);
        std::string cmd, user;
        iss >> cmd >> user;
        if (!user.empty()) {
            sanitized = cmd + " " + user + " ***";
        }
    };
    mask_positional("REGISTER");
    mask_positional("LOGIN");

    constexpr size_t limit = 240;
    if (sanitized.size() > limit) {
        std::ostringstream os;
        size_t head = limit - 20;
        os << sanitized.substr(0, head) << "...<" << sanitized.size() << " bytes>";
        sanitized = os.str();
    }
    return sanitized;
}
} // namespace

volatile std::sig_atomic_t running = 1;

static void handle_signal_internal(int signo) {
    (void)signo;
    running = 0;
    const char msg[] = "signal received, shutting down...\n";
    ::write(STDERR_FILENO, msg, sizeof(msg)-1);
}

void install_signal_handlers() {
    struct sigaction sa{};
    sa.sa_handler = handle_signal_internal;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = 0;
    if (sigaction(SIGINT, &sa, nullptr) == -1) {
        perror("sigaction(SIGINT)");
    }
    if (sigaction(SIGTERM, &sa, nullptr) == -1) {
        perror("sigaction(SIGTERM)");
    }
    // ignore SIGPIPE, so send() gives EPIPE instead of killing us
    struct sigaction ign{};
    ign.sa_handler = SIG_IGN;
    sigemptyset(&ign.sa_mask);
    ign.sa_flags = 0;
    if (sigaction(SIGPIPE, &ign, nullptr) == -1) {
        perror("sigaction(SIGPIPE)");
    }
}

bool send_all(int fd, const void* buf, size_t len) {
    const char* p = static_cast<const char*>(buf);
    while (len > 0) {
        ssize_t w = ::send(fd, p, len,
#ifdef MSG_NOSIGNAL
                           MSG_NOSIGNAL
#else
                           0
#endif
        );
        if (w > 0) {
            p += w;
            len -= (size_t)w;
        } else if (w < 0 && errno == EINTR) {
            continue;
        } else {
            return false;
        }
    }
    return true;
}

bool recv_all(int fd, void* buf, size_t len) {
    char* p = static_cast<char*>(buf);
    while (len > 0) {
        ssize_t r = ::recv(fd, p, len, 0);
        if (r > 0) {
            p += r;
            len -= (size_t)r;
        } else if (r == 0) {
            return false;
        } else if (r < 0 && errno == EINTR) {
            continue;
        } else {
            return false;
        }
    }
    return true;
}

int start_tcp_server(const char* ip, uint16_t& out_port) {
    int fd = ::socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        perror("socket");
        return -1;
    }
    int yes = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(out_port);
    addr.sin_addr.s_addr = inet_addr(ip);

    if (bind(fd, (sockaddr*)&addr, sizeof(addr)) < 0) {
        perror("bind");
        ::close(fd);
        return -1;
    }
    if (out_port == 0) {
        socklen_t sl = sizeof(addr);
        if (getsockname(fd, (sockaddr*)&addr, &sl) == 0) {
            out_port = ntohs(addr.sin_port);
        }
    }
    if (listen(fd, 32) < 0) {
        perror("listen");
        ::close(fd);
        return -1;
    }
    return fd;
}

int connect_tcp(const std::string& ip, uint16_t port) {
    int fd = ::socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        perror("socket");
        return -1;
    }
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    addr.sin_addr.s_addr = inet_addr(ip.c_str());
    if (::connect(fd, (sockaddr*)&addr, sizeof(addr)) < 0) {
        perror("connect");
        ::close(fd);
        return -1;
    }
    return fd;
}

void set_log_level(LogLevel level) {
    g_log_level.store(level);
}

void log_message(LogLevel level, const std::string& module, const std::string& message) {
    if (static_cast<int>(level) > static_cast<int>(g_log_level.load())) return;
    std::lock_guard<std::mutex> lock(g_log_mutex);
    std::cerr << '[' << now_timestamp() << "] [" << module << "] ["
              << level_to_string(level) << "] " << message << std::endl;
}

void log_checkpoint(const std::string& module, const std::string& checkpoint, const std::string& details) {
    std::string msg = "CHECKPOINT " + checkpoint;
    if (!details.empty()) msg += " " + details;
    log_message(LogLevel::Info, module, msg);
}

void log_communication(const std::string& module,
                       const std::string& direction,
                       const std::string& peer,
                       const std::string& payload)
{
    log_message(LogLevel::Info, module,
                "COMM " + direction + " peer=" + peer + " body=" + sanitize_payload(payload));
}
