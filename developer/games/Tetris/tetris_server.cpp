#include "common.hpp"
#include "tetris_runtime.hpp"

#include <iostream>
#include <string>

int main(int argc, char** argv) {
    install_signal_handlers();

    uint16_t port = 15234;
    if (argc >= 2) {
        port = static_cast<uint16_t>(std::stoi(argv[1]));
    }

    int listen_fd = start_tcp_server("0.0.0.0", port);
    if (listen_fd < 0) {
        std::cerr << "cannot start tetris server\n";
        return 1;
    }
    std::cerr << "[Tetris] listening on 0.0.0.0:" << port << "\n";
    log_checkpoint("Tetris", "LISTENING", "0.0.0.0:" + std::to_string(port));

    // Standalone mode won't have lobby state, so we pass dummies.
    run_tetris_server_on_fd(listen_fd, "p1", "p2", "127.0.0.1", 12000, 0, "demo");
    return 0;
}
