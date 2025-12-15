#pragma once
#include <string>
#include <cstdint>
#include <csignal>
#include <thread>
#include <mutex>
#include <unordered_map> // Added for lobby server state

enum class LogLevel {
    Error = 0,
    Warn,
    Info,
    Debug,
    Trace
};

// global running flag for all servers
extern volatile std::sig_atomic_t running;

// install SIGINT, SIGTERM, ignore SIGPIPE
void install_signal_handlers();

// TCP helpers
// start a TCP server on ip:port; if out_port==0, system picks a free port and writes it back
// return listening fd or -1 on error
int start_tcp_server(const char* ip, uint16_t& out_port);

// connect to TCP server, return fd or -1
int connect_tcp(const std::string& ip, uint16_t port);

// reliable send/recv
bool send_all(int fd, const void* buf, size_t len);
bool recv_all(int fd, void* buf, size_t len);

// Logging helpers shared across modules
void set_log_level(LogLevel level);
void log_message(LogLevel level, const std::string& module, const std::string& message);
void log_checkpoint(const std::string& module, const std::string& checkpoint, const std::string& details = "");
void log_communication(const std::string& module,
                       const std::string& direction,
                       const std::string& peer,
                       const std::string& payload);
