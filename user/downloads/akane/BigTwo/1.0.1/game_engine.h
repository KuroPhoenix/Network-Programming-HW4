//
// Created by kurop on 29-Sep-25.
//

#ifndef GAME_ENGINE_H
#define GAME_ENGINE_H
#include <vector>
#include <string>
#include <array>
using namespace std;
struct card {
    string rank;
    string suit;
};
struct combo {
    int mode;
    card dominatingCard;
};

struct state {
    array<string, 2> players;
    vector<card> playerHand[2];
    combo field;
    int whose_turn;
    int winner = -1;
    bool pass;
    int surrenderer = -1;
    bool connection_lost = false;
    bool local_aborted = false;
};
// game_engine.h
inline const std::array<std::string,4> suits = {"Spade","Hearts","Clubs","Diamond"};
inline const std::array<std::string,13> ranks = {"Ace","2","3","4","5","6","7","8","9","10","J","Q","K"};

int init(vector<card>&deck, vector<card>(&playerDeck)[3]);
int host_game(int clientFD, int lobbyFD, int udp_invite_fd, int& win, bool& remote_aborted);
bool fetch_stats(int lobbyFD, const std::string& player, int& wins, int& losses);
bool recv_frame(int fd, std::string& payload);
bool send_frame(int fd, const std::string& payload);
void parse_frame(const std::string& s, std::string& action, std::string& content);
#endif //GAME_ENGINE_H
