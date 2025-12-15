#include <arpa/inet.h>
#include <poll.h>
#include <sys/socket.h>
#include <termios.h>
#include <unistd.h>

#if defined(HAVE_X11_GUI)
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/keysym.h>
#undef None
#endif

#include <algorithm>

#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <csignal>
#include <cctype>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#include "common.hpp"
#include "lp_framing.hpp"
#include "tetris_game.hpp"

namespace {
std::mutex g_console_mutex;

void safe_print(const std::string& text) {
    std::lock_guard<std::mutex> lock(g_console_mutex);
    std::cout << text << std::flush;
}

void safe_print_notice(const std::string& text) {
    std::string msg = text;
    if (msg.empty() || msg.front() != '\n') msg.insert(msg.begin(), '\n');
    if (msg.empty() || msg.back() != '\n') msg.push_back('\n');
    safe_print(msg);
}

struct TerminalRawMode {
    termios old{};
    bool active = false;

    TerminalRawMode() { activate(); }
    explicit TerminalRawMode(bool auto_activate) {
        if (auto_activate) activate();
    }

    void activate() {
        if (active) return;
        if (!isatty(STDIN_FILENO)) return;
        termios raw{};
        tcgetattr(STDIN_FILENO, &old);
        raw = old;
        raw.c_lflag &= ~(ICANON | ECHO);
        raw.c_cc[VMIN] = 0;
        raw.c_cc[VTIME] = 0;
        tcsetattr(STDIN_FILENO, TCSANOW, &raw);
        active = true;
    }

    ~TerminalRawMode() {
        if (active) {
            tcsetattr(STDIN_FILENO, TCSANOW, &old);
        }
    }
};

struct SnapshotData {
    std::string board;
    int score = 0;
    int lines = 0;
    bool gameover = false;
};

#if defined(HAVE_X11_GUI)
class X11Renderer {
   public:
    static std::unique_ptr<X11Renderer> Create(const std::string& local_user, bool spectator) {
        std::unique_ptr<X11Renderer> renderer(new X11Renderer(local_user, spectator));
        if (!renderer->ready()) return nullptr;
        return renderer;
    }

    ~X11Renderer() {
        if (display_) {
            if (gc_) XFreeGC(display_, gc_);
            if (window_) XDestroyWindow(display_, window_);
            XCloseDisplay(display_);
        }
    }

    bool is_open() const { return display_ && window_ && running_; }

    void set_status(const std::string& text) {
        status_text_ = text;
        redraw_pending_ = true;
    }

    void render(const std::vector<std::pair<std::string, SnapshotData>>& players,
                const std::string& local_user) {
        if (!ready()) return;

        std::vector<std::pair<std::string, SnapshotData>> ordered = players;
        while (ordered.size() < 2) ordered.emplace_back("(waiting)", SnapshotData{});

        XSetForeground(display_, gc_, bg_color_);
        XFillRectangle(display_, window_, gc_, 0, 0, width_, height_);

        XSetForeground(display_, gc_, text_color_);
        XDrawString(display_, window_, gc_, 20, 30,
                    status_text_.c_str(), static_cast<int>(status_text_.size()));

        draw_board(ordered[0], 40, 70, ordered[0].first == local_user ? "You" : ordered[0].first);
        draw_board(ordered[1], width_ / 2 + 20, 70,
                   ordered[1].first == local_user ? "You" : ordered[1].first);

        XFlush(display_);
        redraw_pending_ = false;
    }

    std::optional<std::string> poll_action() {
        if (!ready()) return std::nullopt;

        while (XPending(display_)) {
            XEvent ev;
            XNextEvent(display_, &ev);
            if (ev.type == ClientMessage && static_cast<unsigned long>(ev.xclient.data.l[0]) == wm_delete_window_) {
                running_ = false;
                break;
            } else if (ev.type == DestroyNotify) {
                running_ = false;
                break;
            } else if (ev.type == KeyPress) {
                KeySym sym = XLookupKeysym(&ev.xkey, 0);
                if (sym == XK_Escape || sym == XK_q || sym == XK_Q) {
                    running_ = false;
                    break;
                }
                if (spectator_) continue;
                if (sym == XK_Left) return std::string("LEFT");
                if (sym == XK_Right) return std::string("RIGHT");
                if (sym == XK_Down) return std::string("DOWN");
                if (sym == XK_Up) return std::string("ROTATE");
                if (sym == XK_space) return std::string("DROP");
                if (sym == XK_h || sym == XK_H) return std::string("HOLD");
            } else if (ev.type == Expose || ev.type == ConfigureNotify) {
                redraw_pending_ = true;
            }
        }
        return std::nullopt;
    }

    bool consume_redraw_request() {
        if (!redraw_pending_) return false;
        redraw_pending_ = false;
        return true;
    }

   private:
    X11Renderer(const std::string& local_user, bool spectator)
        : spectator_(spectator), local_user_(local_user) {
        display_ = XOpenDisplay(nullptr);
        if (!display_) return;
        int screen = DefaultScreen(display_);
        width_ = 700;
        height_ = 520;
        window_ = XCreateSimpleWindow(display_, RootWindow(display_, screen), 0, 0, width_, height_, 1,
                                      BlackPixel(display_, screen), BlackPixel(display_, screen));
        if (!window_) {
            XCloseDisplay(display_);
            display_ = nullptr;
            return;
        }
        XStoreName(display_, window_, spectator ? "Tetris Spectator" : "Tetris Match");
        XSelectInput(display_, window_, ExposureMask | KeyPressMask | StructureNotifyMask);
        wm_delete_window_ = XInternAtom(display_, "WM_DELETE_WINDOW", False);
        XSetWMProtocols(display_, window_, &wm_delete_window_, 1);
        gc_ = XCreateGC(display_, window_, 0, nullptr);
        if (!gc_) {
            XDestroyWindow(display_, window_);
            XCloseDisplay(display_);
            display_ = nullptr;
            window_ = 0;
            return;
        }
        colormap_ = DefaultColormap(display_, screen);
        allocate_palette();
        XMapWindow(display_, window_);
        running_ = true;
        redraw_pending_ = true;
    }

    bool ready() const { return display_ && window_ && gc_; }

    unsigned long alloc_color(unsigned char r, unsigned char g, unsigned char b) {
        XColor color;
        color.red = static_cast<unsigned short>(r) * 257;
        color.green = static_cast<unsigned short>(g) * 257;
        color.blue = static_cast<unsigned short>(b) * 257;
        color.flags = DoRed | DoGreen | DoBlue;
        if (!XAllocColor(display_, colormap_, &color)) {
            return WhitePixel(display_, DefaultScreen(display_));
        }
        return color.pixel;
    }

    void allocate_palette() {
        bg_color_ = alloc_color(16, 24, 32);
        panel_color_ = alloc_color(34, 45, 60);
        text_color_ = alloc_color(240, 240, 240);
        std::array<std::array<unsigned char, 3>, 8> base = {
            std::array<unsigned char, 3>{0, 0, 0},
            std::array<unsigned char, 3>{92, 225, 255},
            std::array<unsigned char, 3>{255, 105, 120},
            std::array<unsigned char, 3>{110, 255, 110},
            std::array<unsigned char, 3>{255, 224, 102},
            std::array<unsigned char, 3>{160, 102, 255},
            std::array<unsigned char, 3>{255, 159, 28},
            std::array<unsigned char, 3>{26, 145, 255}
        };
        for (size_t i = 0; i < base.size(); ++i) {
            block_colors_[i] = alloc_color(base[i][0], base[i][1], base[i][2]);
        }
    }

    void draw_board(const std::pair<std::string, SnapshotData>& player,
                    int origin_x,
                    int origin_y,
                    const std::string& label) {
        const int board_w = cell_size_ * BOARD_COLS;
        const int board_h = cell_size_ * BOARD_ROWS;

        unsigned long panel = panel_color_;
        XSetForeground(display_, gc_, panel);
        XFillRectangle(display_, window_, gc_, origin_x - 10, origin_y - 36, board_w + 20, board_h + 56);

        XSetForeground(display_, gc_, text_color_);
        std::string caption = label.empty() ? "(waiting)" : label;
        caption += " | Score: " + std::to_string(player.second.score);
        XDrawString(display_, window_, gc_, origin_x, origin_y - 12,
                    caption.c_str(), static_cast<int>(caption.size()));

        XSetForeground(display_, gc_, block_colors_[0]);
        XFillRectangle(display_, window_, gc_, origin_x, origin_y, board_w, board_h);

        const std::string& board = player.second.board;
        if (board.size() != BOARD_ROWS * BOARD_COLS) {
            return;
        }

        for (int r = 0; r < BOARD_ROWS; ++r) {
            for (int c = 0; c < BOARD_COLS; ++c) {
                char ch = board[r * BOARD_COLS + c];
                int idx = (ch >= '0' && ch <= '7') ? ch - '0' : 0;
                XSetForeground(display_, gc_, block_colors_[idx]);
                XFillRectangle(display_, window_, gc_,
                               origin_x + c * cell_size_ + 1,
                               origin_y + r * cell_size_ + 1,
                               cell_size_ - 2, cell_size_ - 2);
            }
        }
    }

    Display* display_{nullptr};
    Window window_{0};
    GC gc_{0};
    Colormap colormap_{0};
    Atom wm_delete_window_{0};
    bool spectator_ = false;
    std::string local_user_;
    bool running_ = false;
    bool redraw_pending_ = false;
    int width_ = 0;
    int height_ = 0;
    int cell_size_ = 18;
    unsigned long bg_color_ = 0;
    unsigned long panel_color_ = 0;
    unsigned long text_color_ = 0;
    std::array<unsigned long, 8> block_colors_{};
    std::string status_text_ = "Waiting for snapshots...";
};
#endif  // HAVE_X11_GUI

struct GameRequest {
    std::string host;
    uint16_t port = 0;
    std::string token;
    bool spectator = false;
};

class GameSession {
   public:
    GameSession(const std::string& host,
                uint16_t port,
                std::string username,
                std::string token,
                bool spectator)
        : host_(host), port_(port), username_(std::move(username)), token_(std::move(token)), spectator_(spectator) {}

    void run() {
        safe_print("\n[game] Connecting to match on " + host_ + ':' + std::to_string(port_) + "...\n");
        int fd = connect_tcp(host_, port_);
        if (fd < 0) {
            safe_print("[game] Failed to connect to game server.\n");
            return;
        }

        std::string hello = "HELLO username=" + username_ + " token=" + token_;
        if (spectator_) hello += " role=SPEC";

        if (!lp_send_frame(fd, hello)) {
            safe_print("[game] Failed to send HELLO.\n");
            ::close(fd);
            return;
        }

#if defined(HAVE_X11_GUI)
        gui_ = X11Renderer::Create(username_, spectator_);
        if (gui_) {
            gui_->set_status("Waiting for match snapshots...");
        }
#endif
        std::unique_ptr<TerminalRawMode> raw;
#if defined(HAVE_X11_GUI)
        if (!gui_) {
            raw = std::make_unique<TerminalRawMode>(true);
            render_header();
        }
#else
        raw = std::make_unique<TerminalRawMode>(true);
        render_header();
#endif

        running_ = true;
        std::map<std::string, SnapshotData> snapshots;
        std::string local_user = username_;

        while (running_) {
            struct pollfd pfds[2];
            pfds[0].fd = fd;
            pfds[0].events = POLLIN;
            int nfds = 1;
#if defined(HAVE_X11_GUI)
            if (!spectator_ && !gui_) {
                pfds[1].fd = STDIN_FILENO;
                pfds[1].events = POLLIN;
                nfds = 2;
            }
#else
            if (!spectator_) {
                pfds[1].fd = STDIN_FILENO;
                pfds[1].events = POLLIN;
                nfds = 2;
            }
#endif

            int rc = poll(pfds, nfds, 50);
            if (rc < 0 && errno == EINTR) continue;
            if (rc < 0) {
                safe_print("[game] poll error.\n");
                break;
            }

            if (pfds[0].revents & POLLIN) {
                std::string msg;
                if (!lp_recv_frame(fd, msg)) {
                    safe_print("[game] Connection closed by server.\n");
                    break;
                }
                handle_message(msg, snapshots, local_user);
            }

            if (!spectator_
#if defined(HAVE_X11_GUI)
                && !gui_
#endif
                && nfds == 2 && (pfds[1].revents & POLLIN)) {
                handle_input(fd);
            }

#if defined(HAVE_X11_GUI)
            if (gui_) {
                auto action = gui_->poll_action();
                if (!gui_->is_open()) {
                    safe_print("[game] GUI window closed. Ending session.\n");
                    break;
                }
                if (action && !spectator_) {
                    lp_send_frame(fd, "INPUT " + *action);
                }
                if (gui_->consume_redraw_request()) {
                    gui_->render(latest_gui_state_, local_user);
                }
            }
#endif
        }

        safe_print("[game] Session ended. Press Enter to continue.\n");
        ::close(fd);
#if defined(HAVE_X11_GUI)
        gui_.reset();
#endif
    }

   private:
    void render_header() {
#if defined(HAVE_X11_GUI)
        if (gui_) return;
#endif
        safe_print("\033[2J\033[H");
        safe_print("==== Tetris Match ====" + std::string(spectator_ ? " (Spectator)\n" : "\n"));
    }

    void handle_message(const std::string& msg,
                        std::map<std::string, SnapshotData>& snapshots,
                        std::string& local_user) {
        if (msg.rfind("SNAPSHOT", 0) == 0) {
            auto kv = parse_pairs(msg);
            std::string user = kv["user"];
            SnapshotData data;
            data.board = kv["board"];
            data.score = kv.count("score") ? std::stoi(kv["score"]) : 0;
            data.lines = kv.count("lines") ? std::stoi(kv["lines"]) : 0;
            data.gameover = kv.count("gameover") && kv["gameover"] == "1";
            snapshots[user] = data;
            render_boards(snapshots, local_user);
#if defined(HAVE_X11_GUI)
            if (gui_) {
                gui_->set_status("Game in progress");
            }
#endif
        } else if (msg.rfind("WELCOME", 0) == 0) {
            auto kv = parse_pairs(msg);
            if (kv.count("role")) {
                std::lock_guard<std::mutex> lock(g_console_mutex);
                std::cout << "[game] Connected as " << kv["role"] << "\n";
            }
        } else if (msg.rfind("GAME_OVER", 0) == 0) {
            auto kv = parse_pairs(msg);
            std::ostringstream oss;
            oss << "\n[game] Final scores: P1=" << kv["p1_score"]
                << " P2=" << kv["p2_score"] << "\n";
            safe_print(oss.str());
#if defined(HAVE_X11_GUI)
            if (gui_) {
                gui_->set_status("Game over");
                gui_->render(latest_gui_state_, local_user);
            }
#endif
            running_ = false;
        } else {
            safe_print("[game] " + msg + '\n');
        }
    }

    void render_boards(const std::map<std::string, SnapshotData>& snapshots,
                       const std::string& local_user) {
        std::vector<std::pair<std::string, SnapshotData>> ordered;
        for (auto const& kv : snapshots) ordered.push_back(kv);

        if (!spectator_) {
            auto it = snapshots.find(local_user);
            if (it != snapshots.end()) {
                ordered.erase(std::remove_if(ordered.begin(), ordered.end(), [&](auto const& p) {
                                     return p.first == local_user;
                                 }),
                                ordered.end());
                ordered.insert(ordered.begin(), *it);
            }
        }

        if (ordered.empty()) return;

        while (ordered.size() < 2) ordered.emplace_back("(waiting)", SnapshotData{});

#if defined(HAVE_X11_GUI)
        latest_gui_state_ = ordered;
        if (gui_) {
            gui_->render(latest_gui_state_, local_user);
            return;
        }
#endif

        std::lock_guard<std::mutex> lock(g_console_mutex);
        std::cout << "\033[2J\033[H";
        std::cout << "==== Tetris Match ====" << (spectator_ ? " (Spectator)" : "") << "\n";

        std::cout << std::left << std::setw(25) << (ordered[0].first + " Score: " + std::to_string(ordered[0].second.score))
                  << std::setw(25) << (ordered[1].first + " Score: " + std::to_string(ordered[1].second.score)) << "\n";

        for (int r = 0; r < BOARD_ROWS; ++r) {
            render_row(ordered[0].second.board, r);
            std::cout << "    ";
            render_row(ordered[1].second.board, r);
            std::cout << '\n';
        }

        std::cout << std::flush;
    }

    void render_row(const std::string& board, int row) {
        if (board.size() != BOARD_ROWS * BOARD_COLS) {
            std::cout << std::string(BOARD_COLS, ' ');
            return;
        }
        for (int c = 0; c < BOARD_COLS; ++c) {
            char ch = board[row * BOARD_COLS + c];
            if (ch == '0') std::cout << '.';
            else std::cout << ch;
        }
    }

    void handle_input(int fd) {
        char buf[8];
        ssize_t n = ::read(STDIN_FILENO, buf, sizeof(buf));
        if (n <= 0) return;
        std::string action;
        if (buf[0] == '\x1b' && n >= 3 && buf[1] == '[') {
            switch (buf[2]) {
                case 'A': action = "ROTATE"; break;
                case 'B': action = "DOWN"; break;
                case 'C': action = "RIGHT"; break;
                case 'D': action = "LEFT"; break;
            }
        } else if (buf[0] == ' ' || buf[0] == '\n') {
            action = "DROP";
        } else if (buf[0] == 'h' || buf[0] == 'H') {
            action = "HOLD";
        } else if (buf[0] == 'q' || buf[0] == 'Q') {
            running_ = false;
            safe_print("[game] Exiting match...\n");
        }

        if (!action.empty()) {
            lp_send_frame(fd, "INPUT " + action);
        }
    }

    static std::unordered_map<std::string, std::string> parse_pairs(const std::string& line) {
        std::unordered_map<std::string, std::string> m;
        std::istringstream iss(line);
        std::string word;
        iss >> word;  // consume command
        while (iss >> word) {
            auto eq = word.find('=');
            if (eq == std::string::npos) continue;
            m[word.substr(0, eq)] = word.substr(eq + 1);
        }
        return m;
    }

    std::string host_;
    uint16_t port_{};
    std::string username_;
    std::string token_;
    bool spectator_{};
    bool running_ = true;
#if defined(HAVE_X11_GUI)
    std::unique_ptr<X11Renderer> gui_;
    std::vector<std::pair<std::string, SnapshotData>> latest_gui_state_;
#endif
};

class ClientApp {
   public:
    ClientApp(std::string host, uint16_t port)
        : lobby_host_(std::move(host)), lobby_port_(port) {}

    bool connect() {
        lobby_fd_ = connect_tcp(lobby_host_, lobby_port_);
        if (lobby_fd_ < 0) {
            safe_print_notice("[client] Unable to connect to lobby.");
            return false;
        }
        safe_print_notice("[client] Connected to lobby at " + lobby_host_ + ':' + std::to_string(lobby_port_) + '.');
        lobby_thread_ = std::thread(&ClientApp::lobby_reader, this);
        return true;
    }

    void run() {
        prompt_login();
        if (!running_) return;
        menu_loop();
    }

    ~ClientApp() {
        running_ = false;
        if (lobby_thread_.joinable()) lobby_thread_.join();
        if (lobby_fd_ >= 0) ::close(lobby_fd_);
    }

   private:
    enum class AuthAction { None, Register, Login };

    void prompt_login() {
        while (running_ && !logged_in_) {
            render_login_prompt(false);
            std::string choice;
            if (!std::getline(std::cin, choice)) {
                login_prompt_visible_ = false;
                return;
            }
            login_prompt_visible_ = false;
            if (choice == "0") {
                running_ = false;
                return;
            } else if (choice == "1") {
                std::string user, pass;
                safe_print("Choose username: ");
                if (!std::getline(std::cin, user)) return;
                safe_print("Choose password: ");
                if (!std::getline(std::cin, pass)) return;
                if (user.empty() || pass.empty()) continue;
                pending_auth_ = AuthAction::Register;
                {
                    std::unique_lock<std::mutex> lock(auth_mutex_);
                    auth_waiting_ = true;
                    auth_success_ = false;
                }
                lp_send_frame(lobby_fd_, "REGISTER " + user + ' ' + pass);
                wait_for_auth();
                if (auth_success_) {
                    username_hint_ = user;
                    password_hint_ = pass;
                    pending_auth_ = AuthAction::Login;
                    {
                        std::unique_lock<std::mutex> lock(auth_mutex_);
                        auth_waiting_ = true;
                        auth_success_ = false;
                    }
                    lp_send_frame(lobby_fd_, "LOGIN " + user + ' ' + pass);
                    wait_for_auth();
                    if (!auth_success_) continue;
                }
            } else if (choice == "2") {
                std::string user, pass;
                safe_print("Username: ");
                if (!std::getline(std::cin, user)) return;
                safe_print("Password: ");
                if (!std::getline(std::cin, pass)) return;
                if (user.empty() || pass.empty()) continue;
                username_hint_ = user;
                password_hint_ = pass;
                pending_auth_ = AuthAction::Login;
                {
                    std::unique_lock<std::mutex> lock(auth_mutex_);
                    auth_waiting_ = true;
                    auth_success_ = false;
                }
                lp_send_frame(lobby_fd_, "LOGIN " + user + ' ' + pass);
                wait_for_auth();
                if (!auth_success_) continue;
            } else {
                safe_print("Invalid selection.\n");
            }
        }
        login_prompt_visible_ = false;
    }

    void wait_for_auth() {
        std::unique_lock<std::mutex> lock(auth_mutex_);
        auth_cv_.wait(lock, [&] { return !auth_waiting_ || !running_; });
    }

    void menu_loop() {
        while (running_) {
            if (game_active_) {
                std::this_thread::sleep_for(std::chrono::milliseconds(200));
                continue;
            }
            if (menu_dirty_.exchange(false)) {
                render_menu();
            }

            std::string choice;
            if (!std::getline(std::cin, choice)) break;
            if (!running_) break;
            if (choice == "0") {
                running_ = false;
                lp_send_frame(lobby_fd_, "LOGOUT");
                break;
            }

            int sel = -1;
            try {
                sel = std::stoi(choice);
            } catch (...) {
                safe_print("Invalid selection.\n");
                menu_dirty_ = true;
                continue;
            }

            int action_code = -1;
            {
                std::lock_guard<std::mutex> lock(menu_mutex_);
                if (sel < 1 || sel > static_cast<int>(menu_codes_.size())) {
                    safe_print("Invalid selection.\n");
                    menu_dirty_ = true;
                    continue;
                }
                action_code = menu_codes_[sel - 1];
            }

            execute_action(action_code);
        }
    }

    void render_menu() {
        if (!logged_in_ || game_active_) return;
        std::lock_guard<std::mutex> lock(menu_mutex_);
        menu_codes_.clear();
        std::ostringstream oss;
        oss << "\n=== Lobby Menu ===\n";
        oss << "User: " << username_hint_
            << " | Room: " << room_status()
            << " | Spectating: " << spectate_status() << "\n";

        auto add_option = [&](int code) {
            menu_codes_.push_back(code);
            oss << menu_codes_.size() << ") " << label_for_code(code) << "\n";
        };

        add_option(1);                // list online
        if (!current_room_) {
            add_option(2);            // create room
            add_option(3);            // list rooms
            add_option(4);            // join room
        } else {
            add_option(3);            // list rooms
            add_option(5);            // leave room
            add_option(6);            // invite user
            if (room_host_ == username_hint_) add_option(8); // start game
        }
        add_option(7);                // list invites
        add_option(9);                // spectate room
        if (spectating_room_) add_option(10); // stop spectating
        add_option(11);               // logout

        oss << "0) Exit\nSelect action > ";
        safe_print(oss.str());
    }

    void render_login_prompt(bool refresh) {
        std::string prompt = login_prompt_text_;
        if (refresh) prompt.insert(prompt.begin(), '\n');
        safe_print(prompt);
        login_prompt_visible_ = true;
    }

    void refresh_menu_async() {
        if (!logged_in_) {
            if (login_prompt_visible_) {
                render_login_prompt(true);
            }
            return;
        }
        menu_dirty_ = true;
        if (!game_active_) {
            render_menu();
        }
    }

    bool maybe_handle_leave_ack(const std::string& msg) {
        if (!pending_leave_) return false;
        if (msg.rfind("OK", 0) == 0) {
            int previous_room = current_room_.value_or(0);
            current_room_.reset();
            room_host_.clear();
            pending_leave_ = false;
            std::string notice;
            if (msg == "OK closed") {
                notice = previous_room > 0
                             ? "[lobby] Room #" + std::to_string(previous_room) + " closed."
                             : "[lobby] Room closed.";
            } else {
                notice = previous_room > 0
                             ? "[lobby] Left room #" + std::to_string(previous_room) + '.'
                             : "[lobby] You left the room.";
            }
            safe_print_notice(notice);
            refresh_menu_async();
            return true;
        }
        if (msg.rfind("ERR", 0) == 0) {
            pending_leave_ = false;
        }
        return false;
    }

    std::string label_for_code(int code) const {
        switch (code) {
            case 1: return "List online users";
            case 2: return "Create room";
            case 3: return "List rooms";
            case 4: return "Join room";
            case 5: return "Leave room";
            case 6: return "Invite user";
            case 7: return "List invites";
            case 8: return "Start game";
            case 9: return "Spectate room";
            case 10: return "Stop spectating";
            case 11: return "Logout";
            default: return "Unknown";
        }
    }

    void execute_action(int code) {
        switch (code) {
            case 1:  // list online
                last_command_ = "LIST_ONLINE";
                lp_send_frame(lobby_fd_, "LIST_ONLINE");
                break;
            case 2: {  // create room
                std::string name, vis;
                safe_print("Room name (no spaces): ");
                if (!std::getline(std::cin, name)) { running_ = false; return; }
                safe_print("Visibility [public/private]: ");
                if (!std::getline(std::cin, vis)) { running_ = false; return; }
                vis = trim_copy(vis);
                if (vis.empty()) {
                    vis = "public";
                } else {
                    vis = to_lower_copy(vis);
                    if (vis != "public" && vis != "private") {
                        safe_print_notice("[lobby] Visibility must be 'public' or 'private'.");
                        menu_dirty_ = true;
                        break;
                    }
                }
                lp_send_frame(lobby_fd_, "CREATE_ROOM " + name + ' ' + vis);
                break;
            }
            case 3:  // list rooms
                last_command_ = "LIST_ROOMS";
                lp_send_frame(lobby_fd_, "LIST_ROOMS");
                break;
            case 4: {  // join room
                std::string rid;
                safe_print("Room ID to join: ");
                if (!std::getline(std::cin, rid)) { running_ = false; return; }
                if (!rid.empty()) {
                    auto parsed = parse_numeric_id(rid);
                    if (!parsed) {
                        safe_print_notice("[lobby] Room IDs must be numeric.");
                        menu_dirty_ = true;
                        break;
                    }
                    pending_join_ = *parsed;
                    lp_send_frame(lobby_fd_, "JOIN_ROOM " + rid);
                }
                break;
            }
            case 5:  // leave room
                if (!current_room_) {
                    safe_print_notice("[lobby] You are not in a room.");
                    menu_dirty_ = true;
                } else {
                    pending_leave_ = true;
                    lp_send_frame(lobby_fd_, "LEAVE_ROOM");
                }
                break;
            case 6: {  // invite user
                std::string user;
                safe_print("Invite username: ");
                if (!std::getline(std::cin, user)) { running_ = false; return; }
                if (!user.empty()) lp_send_frame(lobby_fd_, "INVITE " + user);
                break;
            }
            case 7:  // list invites
                last_command_ = "LIST_INVITES";
                lp_send_frame(lobby_fd_, "LIST_INVITES");
                break;
            case 8:  // start game
                if (!current_room_) {
                    safe_print_notice("[lobby] Join a room first.");
                    menu_dirty_ = true;
                } else if (room_host_ != username_hint_) {
                    safe_print_notice("[lobby] Only the host can start the match.");
                    menu_dirty_ = true;
                } else {
                    lp_send_frame(lobby_fd_, "START_GAME");
                }
                break;
            case 9: {  // spectate room
                std::string rid;
                safe_print("Room ID to spectate: ");
                if (!std::getline(std::cin, rid)) { running_ = false; return; }
                if (!rid.empty()) {
                    auto parsed = parse_numeric_id(rid);
                    if (!parsed) {
                        safe_print_notice("[lobby] Room IDs must be numeric.");
                        menu_dirty_ = true;
                        break;
                    }
                    pending_spectate_ = *parsed;
                    lp_send_frame(lobby_fd_, "SPECTATE " + rid);
                }
                break;
            }
            case 10:  // stop spectating
                lp_send_frame(lobby_fd_, "UNSPECTATE");
                break;
            case 11:  // logout
                lp_send_frame(lobby_fd_, "LOGOUT");
                logged_in_ = false;
                current_room_.reset();
                room_host_.clear();
                spectating_room_.reset();
                prompt_login();
                menu_dirty_ = true;
                break;
            default:
                safe_print("Invalid selection.\n");
                menu_dirty_ = true;
                break;
        }
    }

    void lobby_reader() {
        while (running_) {
            std::string frame;
            if (!lp_recv_frame(lobby_fd_, frame)) {
                safe_print_notice("[client] Lobby connection closed.");
                running_ = false;
                break;
            }
            handle_lobby_message(frame);
        }
    }

    void handle_lobby_message(const std::string& msg) {
        menu_dirty_ = true;
        if (maybe_handle_leave_ack(msg)) {
            return;
        }
        if (msg.rfind("ROOM_INVITE", 0) == 0) {
            auto kv = parse_pairs(msg);
            std::string rid = kv.count("roomId") ? kv["roomId"] : "?";
            std::string host = kv.count("host") ? kv["host"] : "someone";
            std::string name = kv.count("name") ? kv["name"] : "(unnamed)";
            safe_print_notice("[lobby] Invitation from " + host + " to room #" + rid + " \"" + name + "\".");
            refresh_menu_async();
            return;
        }
        if (msg.rfind("OK SPECTATE", 0) == 0) {
            if (pending_spectate_) {
                spectating_room_ = pending_spectate_;
                pending_spectate_.reset();
            }
            safe_print_notice("[lobby] Spectating room " + spectate_status() + ".");
            refresh_menu_async();
            return;
        }
        if (msg.rfind("OK UNSPECTATE", 0) == 0) {
            spectating_room_.reset();
            safe_print_notice("[lobby] Spectate session ended.");
            refresh_menu_async();
            return;
        }
        if (msg.rfind("OK LOGIN", 0) == 0) {
            logged_in_ = true;
            auth_success_ = true;
            complete_auth();
            safe_print_notice("[lobby] Login successful.");
            refresh_menu_async();
            return;
        }
        if (msg.rfind("OK user=", 0) == 0) {
            auth_success_ = true;
            complete_auth();
            safe_print_notice("[lobby] Registration successful.");
            refresh_menu_async();
            return;
        }
        if (msg.rfind("ERR bad_credentials", 0) == 0) {
            auth_success_ = false;
            complete_auth();
            safe_print_notice("[lobby] Login failed: bad credentials.");
            refresh_menu_async();
            return;
        }
        if (msg.rfind("ERR exists", 0) == 0) {
            auth_success_ = false;
            complete_auth();
            safe_print_notice("[lobby] That username is already taken.");
            refresh_menu_async();
            return;
        }
        if (msg.rfind("ERR already_online", 0) == 0) {
            auth_success_ = false;
            complete_auth();
            safe_print_notice("[lobby] This account is already logged in elsewhere.");
            refresh_menu_async();
            return;
        }
        if (msg.rfind("OK LOGOUT", 0) == 0) {
            logged_in_ = false;
            auth_success_ = true;
            complete_auth();
            safe_print_notice("[lobby] Logged out.");
            refresh_menu_async();
            return;
        }
        if (msg.rfind("GAME_READY", 0) == 0 || msg.rfind("SPECTATE_READY", 0) == 0) {
            auto kv = parse_pairs(msg);
            GameRequest req;
            req.host = lobby_host_;
            req.port = static_cast<uint16_t>(std::stoi(kv["port"]));
            req.token = kv["token"];
            req.spectator = msg.rfind("SPECTATE_READY", 0) == 0;
            if (req.spectator) {
                if (!spectating_room_ && pending_spectate_) spectating_room_ = pending_spectate_;
                pending_spectate_.reset();
            }
            safe_print_notice(std::string("[lobby] ") + (req.spectator ? "Spectator" : "Match") +
                              " ready on port " + std::to_string(req.port) + ".");
            start_game_thread(req);
            refresh_menu_async();
            return;
        }
        if (msg.rfind("OK roomId=", 0) == 0) {
            try {
                current_room_ = std::stoi(msg.substr(msg.find('=') + 1));
                room_host_ = username_hint_;
                safe_print_notice("[lobby] Room created. You are now host.");
            } catch (...) {}
            refresh_menu_async();
            return;
        }
        if (msg.rfind("OK joined", 0) == 0) {
            if (pending_join_) {
                current_room_ = pending_join_;
                room_host_.clear();
                pending_join_.reset();
            }
            safe_print_notice("[lobby] Joined room " + room_status());
            refresh_menu_async();
            return;
        }
        if (msg == "OK" && last_command_ == "LIST_ROOMS") {
            safe_print_notice("[lobby] No rooms are available right now.");
            last_command_.clear();
            refresh_menu_async();
            return;
        }
        if (msg == "OK" && last_command_ == "LIST_ONLINE") {
            safe_print_notice("[lobby] No players are currently online.");
            last_command_.clear();
            refresh_menu_async();
            return;
        }
        if (msg == "OK" && last_command_ == "LIST_INVITES") {
            safe_print_notice("[lobby] You have no pending invitations.");
            last_command_.clear();
            refresh_menu_async();
            return;
        }
        if (msg.rfind("ERR", 0) == 0) {
            if (pending_spectate_) pending_spectate_.reset();
            safe_print_notice("[lobby] " + msg);
            refresh_menu_async();
            return;
        }
        if (msg.rfind("OK ", 0) == 0 && !last_command_.empty()) {
            format_ok_payload(msg.substr(3));
            refresh_menu_async();
            return;
        }
        safe_print_notice("[lobby] " + msg);
        refresh_menu_async();
    }

    void complete_auth() {
        std::unique_lock<std::mutex> lock(auth_mutex_);
        auth_waiting_ = false;
        auth_cv_.notify_all();
    }

    void format_ok_payload(const std::string& body) {
        if (last_command_ == "LIST_ONLINE") {
            if (body.empty()) {
                safe_print_notice("[lobby] No players are currently online.");
            } else {
                safe_print_notice("[lobby] Online players:");
                std::stringstream ss(body);
                std::string token;
                while (std::getline(ss, token, ',')) {
                    if (!token.empty()) safe_print("  - " + token + '\n');
                }
            }
        } else if (last_command_ == "LIST_ROOMS") {
            if (body.empty()) {
                safe_print_notice("[lobby] No rooms are available right now.");
            } else {
                safe_print_notice("[lobby] Available rooms:");
                auto trim = [](std::string s) {
                    auto is_ws = [](char ch) {
                        return ch == ' ' || ch == '\t' || ch == '\r' || ch == '\n';
                    };
                    while (!s.empty() && is_ws(s.back())) s.pop_back();
                    while (!s.empty() && is_ws(s.front())) s.erase(s.begin());
                    return s;
                };
                auto pretty_visibility = [](const std::string& vis) {
                    if (vis == "public") return std::string("Public");
                    if (vis == "private") return std::string("Private");
                    return vis.empty() ? std::string("Unknown") : vis;
                };
                auto pretty_status = [](const std::string& status) {
                    if (status == "idle") return std::string("Idle");
                    if (status == "playing") return std::string("In game");
                    if (status == "full") return std::string("Full");
                    return status.empty() ? std::string("Unknown") : status;
                };

                std::stringstream ss(body);
                std::string entry;
                while (std::getline(ss, entry, ';')) {
                    if (entry.empty()) continue;
                    std::vector<std::string> parts;
                    std::stringstream es(entry);
                    std::string tempo;
                    while (std::getline(es, tempo, ':')) parts.push_back(trim(tempo));
                    if (parts.size() < 5) {
                        safe_print("  - " + entry + '\n');
                        continue;
                    }
                    parts.resize(7);
                    const std::string& rid = parts[0];
                    const std::string& name = parts[1];
                    const std::string& host = parts[2];
                    const std::string& status = parts[3];
                    const std::string& visibility = parts[4];
                    const std::string& p1 = parts[5];
                    const std::string& p2 = parts[6];
                    if (current_room_ && std::to_string(*current_room_) == rid) room_host_ = host;

                    std::vector<std::string> players;
                    if (!p1.empty()) players.push_back(p1);
                    if (!p2.empty()) players.push_back(p2);

                    std::string players_line;
                    if (players.empty()) players_line = "(empty)";
                    else if (players.size() == 1) players_line = players[0] + " (waiting)";
                    else players_line = players[0] + " vs " + players[1];

                    int open_slots = std::max(0, 2 - static_cast<int>(players.size()));
                    if (open_slots > 0) {
                        players_line += " | " + std::to_string(open_slots) + " slot" + (open_slots == 1 ? "" : "s") + " open";
                    }

                    std::ostringstream details;
                    details << "  - Room #" << (rid.empty() ? "?" : rid) << " \""
                            << (name.empty() ? "(unnamed)" : name) << "\"\n";
                    details << "      Host: " << (host.empty() ? "?" : host)
                            << " | Visibility: " << pretty_visibility(visibility)
                            << " | Status: " << pretty_status(status) << "\n";
                    details << "      Players [" << players.size() << "/2]: " << players_line << "\n";
                    safe_print(details.str());
                }
            }
        } else if (last_command_ == "LIST_INVITES") {
            if (body.empty()) {
                safe_print_notice("[lobby] You have no pending invitations.");
            } else {
                safe_print_notice("[lobby] Invitations:");
                std::stringstream ss(body);
                std::string entry;
                while (std::getline(ss, entry, ';')) {
                    if (entry.empty()) continue;
                    std::vector<std::string> parts;
                    std::stringstream es(entry);
                    std::string tempo;
                    while (std::getline(es, tempo, ':')) parts.push_back(tempo);
                    if (parts.size() >= 3) {
                        safe_print("  - Room " + parts[0] + " \"" + parts[1] + "\" hosted by " + parts[2] + "\n");
                    } else {
                        safe_print("  - " + entry + '\n');
                    }
                }
            }
        }
        last_command_.clear();
    }

    void start_game_thread(const GameRequest& req) {
        if (game_active_.exchange(true)) {
            safe_print("[game] Match already running, ignoring new request.\n");
            return;
        }
        std::thread([this, req]() {
            GameSession session(req.host, req.port, username_hint_, req.token, req.spectator);
            session.run();
            if (req.spectator && lobby_fd_ >= 0 && running_) {
                lp_send_frame(lobby_fd_, "UNSPECTATE");
            }
            game_active_ = false;
            menu_dirty_ = true;
        }).detach();
    }

    std::string room_status() const {
        if (!current_room_) return "None";
        return std::to_string(*current_room_);
    }

    std::string spectate_status() const {
        if (!spectating_room_) return "No";
        return std::to_string(*spectating_room_);
    }

    static std::string trim_copy(std::string s) {
        auto is_space = [](unsigned char ch) { return std::isspace(ch); };
        s.erase(s.begin(), std::find_if_not(s.begin(), s.end(), is_space));
        s.erase(std::find_if_not(s.rbegin(), s.rend(), is_space).base(), s.end());
        return s;
    }

    static std::string to_lower_copy(std::string s) {
        std::transform(s.begin(), s.end(), s.begin(), [](unsigned char ch) {
            return static_cast<char>(std::tolower(ch));
        });
        return s;
    }

    static std::optional<int> parse_numeric_id(const std::string& text) {
        if (text.empty()) return std::nullopt;
        auto numeric = std::all_of(text.begin(), text.end(), [](unsigned char ch) {
            return std::isdigit(ch);
        });
        if (!numeric) return std::nullopt;
        try {
            return std::stoi(text);
        } catch (...) {
            return std::nullopt;
        }
    }

    static std::unordered_map<std::string, std::string> parse_pairs(const std::string& line) {
        std::unordered_map<std::string, std::string> m;
        std::istringstream iss(line);
        std::string word;
        iss >> word;
        while (iss >> word) {
            auto eq = word.find('=');
            if (eq == std::string::npos) continue;
            m[word.substr(0, eq)] = word.substr(eq + 1);
        }
        return m;
    }

    // Lobby connection state
    std::string lobby_host_;
    uint16_t lobby_port_;
    int lobby_fd_ = -1;
    std::thread lobby_thread_;
    std::atomic<bool> running_{true};

    // Auth handling
    std::mutex auth_mutex_;
    std::condition_variable auth_cv_;
    bool auth_waiting_ = false;
    bool auth_success_ = false;
    AuthAction pending_auth_ = AuthAction::None;

    // Session state
    std::string username_hint_;
    std::string password_hint_;
    std::atomic<bool> logged_in_{false};
    std::optional<int> current_room_;
    std::string room_host_;
    std::optional<int> spectating_room_;
    std::optional<int> pending_join_;
    std::optional<int> pending_spectate_;
    bool pending_leave_ = false;
    std::string last_command_;
    std::atomic<bool> game_active_{false};
    std::mutex menu_mutex_;
    std::vector<int> menu_codes_;
    std::atomic<bool> menu_dirty_{true};
    std::atomic<bool> login_prompt_visible_{false};
    const std::string login_prompt_text_ = "Login menu: [1] Register  [2] Login  [0] Exit > ";
};

}

int main(int argc, char** argv) {
    std::string host = "140.113.17.11";
    uint16_t port = 13472;

    if (argc >= 2) host = argv[1];
    if (argc >= 3) port = static_cast<uint16_t>(std::stoi(argv[2]));

    ClientApp app(host, port);
    if (!app.connect()) return 1;
    app.run();
    return 0;
}
