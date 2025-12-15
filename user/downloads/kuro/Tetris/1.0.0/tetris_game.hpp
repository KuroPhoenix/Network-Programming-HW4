#pragma once
#include <vector>
#include <string>
#include <random>
#include <algorithm>
#include <sstream>

#define BOARD_COLS 10
#define BOARD_ROWS 20

// Shape definitions (using 4x4 matrix)
const int SHAPE_I[4][4] = {{0,1,0,0},{0,1,0,0},{0,1,0,0},{0,1,0,0}};
const int SHAPE_T[4][4] = {{0,1,0,0},{1,1,1,0},{0,0,0,0},{0,0,0,0}};
const int SHAPE_L[4][4] = {{0,1,0,0},{0,1,0,0},{0,1,1,0},{0,0,0,0}};
const int SHAPE_L2[4][4] = {{0,1,0,0},{0,1,0,0},{1,1,0,0},{0,0,0,0}};
const int SHAPE_O[4][4] = {{1,1,0,0},{1,1,0,0},{0,0,0,0},{0,0,0,0}};
const int SHAPE_S[4][4] = {{0,1,1,0},{1,1,0,0},{0,0,0,0},{0,0,0,0}};
const int SHAPE_S2[4][4] = {{1,1,0,0},{0,1,1,0},{0,0,0,0},{0,0,0,0}};
const std::vector<const int(*)[4]> SHAPES = {SHAPE_I, SHAPE_T, SHAPE_L, SHAPE_L2, SHAPE_O, SHAPE_S, SHAPE_S2};

struct Piece {
    int shape[4][4] = {0};
    int x = BOARD_COLS / 2 - 2;
    int y = 0;
    int shape_id = 0;
};

class TetrisGame {
public:
    int board[BOARD_ROWS][BOARD_COLS] = {0};
    int score = 0;
    int lines_cleared = 0;
    bool game_over = false;
    Piece current_piece;
    int hold_shape_id = -1;
    bool hold_used = false;

    std::mt19937 rng;
    std::vector<int> bag;

    TetrisGame(int seed) : rng(seed) {
        fill_bag();
        spawn_piece();
    }

    void fill_bag() {
        bag = {0, 1, 2, 3, 4, 5, 6};
        std::shuffle(bag.begin(), bag.end(), rng);
    }

    void set_active_shape(int shape_id) {
        current_piece.shape_id = shape_id;
        const int(*shape_ptr)[4] = SHAPES[shape_id];
        current_piece.x = BOARD_COLS / 2 - 2;
        current_piece.y = 0;
        for (int r = 0; r < 4; ++r) {
            for (int c = 0; c < 4; ++c) {
                current_piece.shape[r][c] = shape_ptr[r][c];
            }
        }
        if (check_collision(current_piece.x, current_piece.y)) {
            game_over = true;
        }
    }

    void spawn_piece() {
        if (bag.empty()) fill_bag();
        int next_id = bag.back();
        bag.pop_back();
        set_active_shape(next_id);
        hold_used = false;
    }

    bool check_collision(int px, int py) {
        for (int r = 0; r < 4; ++r) {
            for (int c = 0; c < 4; ++c) {
                if (current_piece.shape[r][c]) {
                    int board_r = py + r;
                    int board_c = px + c;
                    if (board_r < 0 || board_r >= BOARD_ROWS || // Out of bounds (bottom/top)
                        board_c < 0 || board_c >= BOARD_COLS || // Out of bounds (left/right)
                        board[board_r][board_c])                // Colliding with another piece
                    {
                        return true;
                    }
                }
            }
        }
        return false;
    }

    void lock_piece() {
        for (int r = 0; r < 4; ++r) {
            for (int c = 0; c < 4; ++c) {
                if (current_piece.shape[r][c]) {
                    board[current_piece.y + r][current_piece.x + c] = current_piece.shape_id + 1; // Use 1-7 as color id
                }
            }
        }
        clear_lines();
        spawn_piece();
    }

    void hold_piece() {
        if (game_over || hold_used) return;
        int current_id = current_piece.shape_id;
        if (hold_shape_id == -1) {
            hold_shape_id = current_id;
            spawn_piece();
        } else {
            int swap_id = hold_shape_id;
            hold_shape_id = current_id;
            set_active_shape(swap_id);
        }
        hold_used = true;
    }

    void clear_lines() {
        int lines_to_clear = 0;
        for (int r = BOARD_ROWS - 1; r >= 0; --r) {
            bool line_full = true;
            for (int c = 0; c < BOARD_COLS; ++c) {
                if (board[r][c] == 0) {
                    line_full = false;
                    break;
                }
            }
            if (line_full) {
                lines_to_clear++;
                for (int r_above = r; r_above > 0; --r_above) {
                    for (int c = 0; c < BOARD_COLS; ++c) {
                        board[r_above][c] = board[r_above - 1][c];
                    }
                }
                for (int c = 0; c < BOARD_COLS; ++c) {
                    board[0][c] = 0;
                }
                r++; // Re-check this row
            }
        }
        if (lines_to_clear > 0) {
            lines_cleared += lines_to_clear;
            int points[] = {0, 100, 300, 500, 800};
            score += points[lines_to_clear];
        }
    }

    // Server-side gravity tick
    void tick() {
        if (game_over) return;
        if (!check_collision(current_piece.x, current_piece.y + 1)) {
            current_piece.y++;
        } else {
            lock_piece();
        }
    }

    // Handle player input
    void handle_input(const std::string& action) {
        if (game_over) return;
        if (action == "LEFT") {
            if (!check_collision(current_piece.x - 1, current_piece.y)) {
                current_piece.x--;
            }
        } else if (action == "RIGHT") {
            if (!check_collision(current_piece.x + 1, current_piece.y)) {
                current_piece.x++;
            }
        } else if (action == "DOWN") {
            if (!check_collision(current_piece.x, current_piece.y + 1)) {
                current_piece.y++;
                score += 1; // Score for soft drop
            } else {
                lock_piece();
            }
        } else if (action == "ROTATE") {
            rotate_piece();
        } else if (action == "DROP") {
            int drop_dist = 0;
            while (!check_collision(current_piece.x, current_piece.y + 1)) {
                current_piece.y++;
                drop_dist++;
            }
            score += drop_dist * 2; // Score for hard drop
            lock_piece();
        } else if (action == "HOLD") {
            hold_piece();
        }
    }

    void rotate_piece() {
        int new_shape[4][4];
        // Rotate 90 degrees clockwise
        for(int r = 0; r < 4; ++r) {
            for (int c = 0; c < 4; ++c) {
                new_shape[c][3-r] = current_piece.shape[r][c];
            }
        }

        int old_shape[4][4];
        for(int r = 0; r < 4; ++r) for (int c = 0; c < 4; ++c) old_shape[r][c] = current_piece.shape[r][c];

        for(int r = 0; r < 4; ++r) for (int c = 0; c < 4; ++c) current_piece.shape[r][c] = new_shape[r][c];

        // Wall kick logic (simplified)
        if (check_collision(current_piece.x, current_piece.y)) {
            // Try moving 1 left
            if (!check_collision(current_piece.x - 1, current_piece.y)) {
                current_piece.x--;
            } // Try moving 1 right
            else if (!check_collision(current_piece.x + 1, current_piece.y)) {
                current_piece.x++;
            } // Failed, revert
            else {
                for(int r = 0; r < 4; ++r) for (int c = 0; c < 4; ++c) current_piece.shape[r][c] = old_shape[r][c];
            }
        }
    }

    // Serialize the board for sending over network
    std::string get_board_snapshot() {
        std::ostringstream os;

        // Create a temp board with the active piece
        int temp_board[BOARD_ROWS][BOARD_COLS];
        for (int r = 0; r < BOARD_ROWS; ++r) {
            for (int c = 0; c < BOARD_COLS; ++c) {
                temp_board[r][c] = board[r][c];
            }
        }
        for (int r = 0; r < 4; ++r) {
            for (int c = 0; c < 4; ++c) {
                if (current_piece.shape[r][c]) {
                    int board_r = current_piece.y + r;
                    int board_c = current_piece.x + c;
                    if(board_r >= 0 && board_r < BOARD_ROWS && board_c >= 0 && board_c < BOARD_COLS) {
                        temp_board[board_r][board_c] = current_piece.shape_id + 1;
                    }
                }
            }
        }

        // Serialize the temp board
        for (int r = 0; r < BOARD_ROWS; ++r) {
            for (int c = 0; c < BOARD_COLS; ++c) {
                os << temp_board[r][c];
            }
        }
        return os.str(); // 200-char string (20x10)
    }
};
