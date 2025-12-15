#include <algorithm>
#include <cstring>
#include <iostream>
#include <cstring>
#include <vector>
#include <string>
#include <sstream>
#include <string_view>
#include <cstdint>
#include <arpa/inet.h>
#include <cstdio>
#include "game_engine.h"
#include "config.h"
#include <random>
using namespace std;
namespace {
    // Upper bound to protect memory / protocol abuse. Tune as you like.
    constexpr uint32_t MAX_FRAME = 1u << 20; // 1 MiB

    // Read exactly n bytes from a blocking TCP socket.
    bool recv_n(int fd, void* buf, size_t n) {
        char* p = static_cast<char*>(buf);
        while (n) {
            ssize_t r = recv(fd, p, n, 0);
            if (r < 0) { if (errno == EINTR) continue; return false; }
            if (r == 0) return false; // peer closed mid-frame
            p += r; n -= static_cast<size_t>(r);
        }
        return true;
    }

    // Same as above, but directly into a std::string (resizes it).
    bool recv_n_string(int fd, std::string& out, size_t n) {
        out.resize(n);
        return recv_n(fd, out.data(), n);
    }

    // Parse a decimal length (header line you got via recv_line).
    // Returns true on success and writes the length to out_len.
    bool parse_len_header(const std::string& line, uint32_t& out_len) {
        if (line.empty()) return false;
        // strict decimal digits only
        for (char c : line) if (c < '0' || c > '9') return false;

        // convert and range-check
        unsigned long long ull = strtoull(line.c_str(), nullptr, 10);
        if (ull > MAX_FRAME) return false;
        out_len = static_cast<uint32_t>(ull);
        return true;
    }
} // namespace

// ------------------------ TCP framed I/O ------------------------
void parse_frame(const std::string& s, std::string& action, std::string& content) {
    size_t sp = s.find(' ');
    if (sp == std::string::npos) { action = s; content.clear(); }
    else { action = s.substr(0, sp); content = s.substr(sp + 1); }
}
bool send_frame(int fd, const std::string& payload) {
    // Header is ASCII "<len>\n" so we can reuse your recv_line()
    std::string header = std::to_string(payload.size()) + "\n";
    // Reuse your existing writer for simplicity
    if(!send_msg(fd, header)){
        fprintf(stderr, "GAMESESS: Failure to send header %s\n", header.c_str());
        return false;
    }
    if(!send_msg(fd, payload)){
        fprintf(stderr, "GAMESESS: Failure to send payload %s\n", payload.c_str());
        return false;
    }
    return true; // (If you want error reporting, add a "send_all" that returns bool.)
}

bool recv_frame(int fd, std::string& payload) {
    // 1) Read "<len>\n" using your line reader
    std::string header;
    for (;;) {
        if (recv_line(fd, header)) break;
        if (errno == EINTR) continue;
        if (errno == EAGAIN || errno == EWOULDBLOCK) {
            if (!running) return false;   // interrupted shutdown
            header.clear();               // poll again for more data
            continue;
        }
        return false;
    }

    // 2) Parse decimal length with validation and cap
    uint32_t len = 0;
    if (!parse_len_header(header, len)) return false;

    // 3) Read exactly len bytes into payload
    return recv_n_string(fd, payload, len);
}

// ------------------------ UDP framed I/O ------------------------
// For UDP we send one datagram: "<len>\n<payload>"

bool udp_send_frame(int fd, const std::string& payload,
                    const sockaddr* to, socklen_t tolen)
{
    std::string frame;
    frame.reserve(16 + payload.size());   // avoid extra allocs
    frame.append(std::to_string(payload.size()));
    frame.push_back('\n');
    frame.append(payload);

    return udp_send_msg(fd, frame, to, tolen);
}

bool udp_recv_frame(int fd, std::string& payload,
                    sockaddr_storage* src, socklen_t* srclen)
{
    std::string frame;
    if (!recv_udp(fd, frame, src, srclen)) return false;

    // Find the first '\n' to split header and payload
    auto nl = frame.find('\n');
    if (nl == std::string::npos) return false;

    std::string header = frame.substr(0, nl);
    uint32_t len = 0;
    if (!parse_len_header(header, len)) return false;

    // Remaining bytes after the '\n'
    std::string body = frame.substr(nl + 1);

    // Validate exact length match (strict framing)
    if (body.size() != len) return false;

    payload.swap(body);
    return true;
}


void createDeck(vector<card>& deck){
    deck.reserve(52);
    for (auto& s : suits)
        for (auto& r : ranks)
            deck.push_back({r, s});          // aggregate init
}

void shuffleDeck(vector<card>& deck){
    static std::mt19937 rng{std::random_device{}()};
    std::shuffle(deck.begin(), deck.end(), rng);
}


string displayHand(vector<card> &deck) {
    string str;
    str += "Hand:\n";
    for (int i = 0 ; i < deck.size(); i++) {
        str += ("[" + to_string(i + 1) + "] " + deck[i].rank + " of " + deck[i].suit + "\n");
    }
    return str;
}


string playerBegin(state& world) {
    string str = "It's ";
    str += world.players[world.whose_turn];
    str += " turn.\n";
    return str;
}

string translateSuit(char s) {
    if (s == 'S') {
        return "Spade";
    }
    if (s == 'H') {
        return "Hearts";
    }
    if (s == 'C') {
        return "Clubs";
    }
    if (s == 'D') {
        return "Diamond";
    }
    return "Invalid";
}

int translateRank(string c) {
    if (c == "Ace") return 14;
    if (c == "10") return 10;
    if (c == "J") return 11;
    if (c == "Q") return 12;
    if (c == "K") return 13;
    if (c == "2") return 15;
    return c[0] - '0';
}

int digitaliseSuit(string c) {
    if (c == "Spade") return 4;
    if (c == "Hearts") return 3;
    if (c == "Diamond") return 2;
    if (c == "Clubs") return 1;
    return -1;
}

bool sortCards(card &a, card &b) {
    if (a.rank != b.rank) {
        return translateRank(a.rank) < translateRank(b.rank);

    }
    return digitaliseSuit(a.suit) < digitaliseSuit(b.suit);
}
bool findDominatingCard(const card& a, const card& b) {
    /* Determines whether card a is greater than card b.*/
    if (a.rank != b.rank) {
        return translateRank(a.rank) > translateRank(b.rank);
    }
    return digitaliseSuit(a.suit) > digitaliseSuit(b.suit);
}


string introduceCard(const card& c) {
   return c.rank + " of " + c.suit + "\n";
}
string displayMove(vector <card>&move) {
    string str;
    str += "Your Move:\n";
    for (int i = 0; i < move.size(); i++) {
        str += introduceCard(move[i]);
    }
    return str;
}
/* Mode: 1: Single Card | 2: 對子 | 3: 葫蘆 | 4: 鐡枝 | 5: 順子*/
combo checkMove(vector<card> &move) {
    sort(move.begin(), move.end(), sortCards);
    displayMove(move);
    if (move.size() == 1) {
        return {1, move[0]}; //單張
    }
    if (move.size() == 2) { //對子
        if (move[0].rank == move[1].rank) {
            return {2, move[1]};
        }
    }
    if (move.size() == 5) {
        if ((move[0].rank == move[1].rank && move[1].rank == move[2].rank && move[3].rank == move[4].rank) ||
            (move[0].rank == move[1].rank && move[3].rank == move[2].rank && move[3].rank == move[4].rank)) {
            return {3, move[2]}; //葫蘆
        }
        if ((move[0].rank == move[1].rank && move[1].rank == move[2].rank && move[2].rank == move[3].rank) ||
            (move[1].rank == move[2].rank && move[2].rank == move[3].rank && move[3].rank == move[4].rank)) {
            return {5, move[2]}; //鐡枝
        }
        if (translateRank(move[0].rank) + 1 == translateRank(move[1].rank) &&
            translateRank(move[1].rank) + 1 == translateRank(move[2].rank) &&
            translateRank(move[2].rank) + 1 == translateRank(move[3].rank) &&
            translateRank(move[3].rank) + 1 == translateRank(move[4].rank)) {
            if (move[0].suit == move[1].suit && move[1].suit == move[2].suit && move[2].suit == move[3].suit && move[3].suit == move[4].suit) {
                return {6, move[4]}; //同花順
            }
            return {4, move[4]}; //順子
        }
    }
    return {-1, move[0]};
}

string introduceField(const combo& field) {
    string str;
    if (field.mode == -1) {
        str += "The current field has no cards. You may make whatever move you like.";
    }
    if (field.mode == 1) {
       str +="Field status: Single Card";
    }
    if (field.mode == 2) {
        str +="Field status: Tuplets";
    }
    if (field.mode == 3) {
        str +="Field status: Triplets with a Twin";
    }
    if (field.mode == 5) {
        str +="Field status: Four in a row";
    }
    if (field.mode == 4) {
        str +="Field status: Five consecutive numbers";
    }
    if (field.mode == 6) {
        str +="Field status: Five consecutive numbers with same suit";
    }
    if (field.mode != -1) {
        str += "Dominating Card: ";
        str += introduceCard(field.dominatingCard);
    }
    return str;
}

bool checkComboIsGreaterThanField(const combo &player, const combo &field) {
    if (player.mode > 4) return player.mode > field.mode;
    if (player.mode != field.mode) return false;
    return findDominatingCard(player.dominatingCard, field.dominatingCard);
}

void removeCardFromHand(vector<card>& hand, const vector<card>& move) {
    for (const auto& m : move) {
        hand.erase(remove_if(hand.begin(), hand.end(),
                   [&](const card& c){ return c.rank==m.rank && c.suit==m.suit; }),
                   hand.end());
    }
}

string get_begin_state_string(state &world) {
    string str;
    str += playerBegin(world);
    str += displayHand(world.playerHand[world.whose_turn]);
    str += introduceField(world.field);
    return str;
}

bool deliver(int currPlayer, string msg, int fd) { //1: playerA, 2: playerB
    if (currPlayer == 0) {
        std::string view = msg;
        if (view.rfind("MSG ", 0) == 0) {
            view = view.substr(4);
        } else if (view.rfind("PROMPT ", 0) == 0) {
            view = view.substr(7);
            if (!view.empty() && view.back() != '\n') view.push_back('\n');
            std::cout << view << "> " << std::flush;
            return true;
        }
        if (!view.empty()) {
            std::cout << view;
            if (view.back() != '\n') std::cout << '\n';
        }
        std::cout.flush();
    }
    else if(!send_frame(fd, msg)){
        fprintf(stderr, "Error Sending Frame to player.\n");
        return false;
    }
    return true;
}

int init(vector<card>&deck, vector<card>(&playerDeck)[3]) {
    /*Game Settings*/
    int player = -1;
    createDeck(deck);
    shuffleDeck(deck);

    /*distribute the cards*/
    for (int i = 0 ; i < 51; i++) {
        playerDeck[i % 3].push_back(deck[i]);
    }
    for (int i = 0; i < 3; i++) {
        sort(playerDeck[i].begin(), playerDeck[i].end(), sortCards);
    }

    /*Find who goes first*/
    for (auto & i : playerDeck[0]) {
        if (i.suit == "Clubs" && i.rank == "3") {
            player = 1;
            break;
        }
    }
    for (auto & i : playerDeck[1]) {
        if (i.suit == "Clubs" && i.rank == "3") {
            player = 0;
            break;
        }
    }
    if (player == -1) {
        srand(time(nullptr));
        player = rand() % 2;
    }
    playerDeck[player].push_back(deck[51]);
    return player;
}

string get_Response(state &world, int fd) {
    string input;
    if (world.whose_turn == 0) {
        if (!running) {
            return "LOCAL_INTERRUPT";
        }
        if (!std::getline(cin >> std::ws, input)) {
            if (!running) return "LOCAL_INTERRUPT";
            return "LOCAL_INPUT_ERROR";
        }
        if (!running) {
            return "LOCAL_INTERRUPT";
        }
    }
    else {
        if (!recv_frame(fd, input)) {
            if (!running) {
                world.local_aborted = true;
                return "LOCAL_INTERRUPT";
            }
            world.connection_lost = true;
            return "REMOTE_DISCONNECT";
        }
    }
    return input;
}

//indexify
bool parsePlayer(vector<card> &move, state& world, int fd) {
    world.pass = false;
    vector<bool> chosenCards(world.playerHand[world.whose_turn].size(), false);
    string promptMsg =  "PROMPT You may either make a move, pass, or surrender.\nYou may enter the indices that are displayed above. The accepted format is as follows: <number><space><number>...\nE.g. A valid input would be 1 2 3 10 11.\nYou may also enter pass if no moves are desired, or surrender to concede.\n";
    if(!deliver(world.whose_turn, promptMsg.c_str(), fd)){
        fprintf(stderr, "parsePlayer: Deliver Error.\n");
        world.whose_turn = 3;
        return true;
    }
    string input = get_Response(world, fd);
    if (input == "REMOTE_DISCONNECT") {
        world.winner = 0;
        world.surrenderer = 1;
        return true;
    }
    if (input == "LOCAL_INTERRUPT") {
        world.winner = 1;
        world.surrenderer = 0;
        world.local_aborted = true;
        return true;
    }
    if (input == "LOCAL_INPUT_ERROR") {
        world.whose_turn = 2;
        return true;
    }
    if (input == "surrender") {
        world.winner = (world.whose_turn + 1) % 2;
        world.surrenderer = world.whose_turn;
        return true;
    }
    if (input == "pass") {
        world.pass = true;
        return true;
    }
    if (input == "ERROR") {
        world.whose_turn = 2;
        return true;
    }
    std::istringstream iss(input);
    bool validInput = true;
    for (std::string tok; iss >> tok; ) {
        int index = atoi(tok.c_str());
        if (index > world.playerHand[world.whose_turn].size() || index < 1 || chosenCards[index - 1]) {
            validInput = false;
            break;
        }
        move.push_back(world.playerHand[world.whose_turn][index - 1]);
        chosenCards[index - 1] = true;
    }
    if (!validInput) {
        string msg = "MSG Invalid move. Please make your move again.\n";
        if(!deliver(world.whose_turn, promptMsg.c_str(), fd)){
            fprintf(stderr, "parsePlayer: Deliver Error.\n");
            world.whose_turn = 3;
            return true;
        }
        return false;
    }
    return true;
}
int host_game(int clientFD, int lobbyFD, int udp_invite_fd, int& win, bool& remote_aborted) {
    state world;
    vector<card> deck;
    vector<card> playerDeck[3];//Lovelace = 0, Furina = 1, Bot = 2;
    combo field = {-1, {"3", "Spade"}};
    vector<card> move;
    int player = init(deck, playerDeck);
    bool gameEnd = false;
    bool pass = false;
    world.field = field;
    world.pass = pass;
    world.playerHand[0] = playerDeck[0];
    world.playerHand[1] = playerDeck[1];
    world.whose_turn = player;
    world.winner = -1;
    world.surrenderer = -1;
    world.connection_lost = false;
    world.local_aborted = false;
    world.players[0] = sock_to_user[lobbyFD];
    world.players[1] = sock_to_user[clientFD];

    std::string hello, act, name;
    if (!recv_frame(clientFD, hello)) {
        fprintf(stderr, "host_game: Failure receiving client HELLO MSG.\n");
        return 1;
    }
    parse_frame(hello, act, name);
    if (act == "USER") world.players[1] = name;

    // (optional, also send your name back)
    if(!send_frame(clientFD, "USER " + world.players[0])){
        fprintf(stderr, "host_game: Failure to send USER_INFO.\n");
        return 1;
    }

    /*Play Game*/
    while (world.winner == -1) {
        string banner = "MSG }--------------------------=========================< [TURN BEGINS] >--------------------------========================={\n";
        if(!deliver(world.whose_turn, banner, clientFD)){
            fprintf(stderr, "host_game: Deliver Error: %s\n", banner.c_str());
            return 1;
        }
        //playerBegin(&player);
        combo playerMove = {-1};
        bool validMove = false;
        while (!validMove) {
            do {
                move.clear();
                string payload = get_begin_state_string(world);
                if(!deliver(world.whose_turn, payload, clientFD)){
                    fprintf(stderr, "host_game: Error sending payload to [player%s]: %s\n",world.players[world.whose_turn].c_str(), payload.c_str());
                    return 1;
                }
                banner = "MSG }--------------------------=========================< [STAGE: CHOOSE YOUR MOVE] >--------------------------========================={\n";
                if(!deliver(world.whose_turn, banner, clientFD)){
                    fprintf(stderr, "host_game: Error sending banner to [player%s]: %s\n",world.players[world.whose_turn].c_str(), banner.c_str());
                    return 1;
                }
                while (!parsePlayer(move, world, clientFD)) {}
                if (world.surrenderer != -1) {
                    validMove = true;
                    break;
                }
                if (world.whose_turn == 2) {
                    if(!deliver(0, "GAMESESS ERR PARSING\n", clientFD)){
                        fprintf(stderr, "host_game: Error sending PARSE_ERR MSG.\n");
                        return 1;
                    }
                    return 1;
                }
                if(world.whose_turn == 3){
                    if(!deliver(0, "GAMESESS ERR DELIVER\n", clientFD)){
                        fprintf(stderr, "host_game: Error sending DELIVER_ERR MSG.\n");
                        return 1;
                    }
                    return 1;
                }
                if (world.pass) {
                    validMove = true;
                    world.field.mode = -1;
                    break;
                }
                world.pass = false;
                banner = "MSG }--------------------------=========================< [MOVE VERIFICATION] >--------------------------========================={\n";
                if(!deliver(world.whose_turn, banner, clientFD)){
                    fprintf(stderr, "host_game: Error sending banner to [player%s]: %s\n",world.players[world.whose_turn].c_str(), banner.c_str());
                    return 1;
                }
                playerMove = checkMove(move);
                if (playerMove.mode == -1) {
                    string errMsg = "Invalid move. The move you made does not adhere to the game rules. Please make your move again.\n";
                    if(!deliver(world.whose_turn, errMsg.c_str(), clientFD)){
                        fprintf(stderr, "host_game: Error sending errMsg to [player%s]: %s\n", world.players[world.whose_turn].c_str(), errMsg.c_str());
                        return 1;
                    }
                }
            }while (playerMove.mode == -1);
            if (world.surrenderer != -1) {
                break;
            }
            if (world.pass) {
                validMove = true;
                string msg = "MSG " + world.players[world.whose_turn] + " passes!\n";
                if(!deliver(world.whose_turn, msg.c_str(), clientFD)){
                    fprintf(stderr, "host_game: Error sending Msg to [player%s]: %s\n", world.players[world.whose_turn].c_str(), msg.c_str());
                    return 1;
                }
                world.field.mode = -1;
                banner = "MSG }--------------------------=========================< [TURN ENDS] >--------------------------========================={\n";
                if(!deliver(world.whose_turn, banner, clientFD)){
                    fprintf(stderr, "host_game: Error sending banner to [player%s]: %s\n",world.players[world.whose_turn].c_str(), banner.c_str());
                    return 1;
                }
                continue;
            }
            if (world.field.mode == -1) {//First Move
                world.field = playerMove;
                validMove = true;
            }
            else {
                banner = "MSG }--------------------------=========================< [FIELD VERIFICATION] >--------------------------========================={\n";
                if(!deliver(world.whose_turn, banner, clientFD)){
                    fprintf(stderr, "host_game: Error sending banner to [player%s]: %s\n",world.players[world.whose_turn].c_str(), banner.c_str());
                    return 1;
                }
                if (!checkComboIsGreaterThanField(playerMove, world.field)) {
                    string msg = "MSG The move you made is not greater than what is currently on the field. Please reconsider your move.\n";
                    if(!deliver(world.whose_turn, msg.c_str(), clientFD)){
                        fprintf(stderr, "host_game: Error sending Msg to [player%s]: %s\n", world.players[world.whose_turn].c_str(), msg.c_str());
                        return 1;
                    }
                }
                else {
                    validMove = true;
                }
            }
        }
        if (world.surrenderer != -1) {
            std::string msg = "MSG " + world.players[world.surrenderer] + " surrendered. " + world.players[world.winner] + " wins!\n";
            bool surrenderer_alive = !(world.connection_lost && world.surrenderer == 1);
            if (surrenderer_alive) {
                if(!deliver(world.surrenderer, msg.c_str(), clientFD)){
                    fprintf(stderr, "host_game: Error announcing surrender to [player%s].\n", world.players[world.surrenderer].c_str());
                    return 1;
                }
            } else {
                // For local player (index 0), still display the message.
                deliver(0, msg.c_str(), clientFD);
            }
            bool opponent_alive = !(world.connection_lost && world.surrenderer == 1);
            if (opponent_alive) {
                if(!deliver((world.surrenderer + 1) % 2, msg.c_str(), clientFD)){
                    fprintf(stderr, "host_game: Error announcing surrender to opponent [player%s].\n", world.players[(world.surrenderer + 1) % 2].c_str());
                    return 1;
                }
            }
            break;
        }
        banner = "MSG }--------------------------=========================< [CARD REMOVAL] >--------------------------========================={\n";
        if(!deliver(world.whose_turn, banner, clientFD)){
            fprintf(stderr, "host_game: Error sending banner to [player%s]: %s\n",world.players[world.whose_turn].c_str(), banner.c_str());
            return 1;
        }
        removeCardFromHand(world.playerHand[world.whose_turn], move);
        banner = "MSG }--------------------------=========================< [TURN ENDS] >--------------------------========================={\n";
        if(!deliver(world.whose_turn, banner, clientFD)){
            fprintf(stderr, "host_game: Error sending banner to [player%s]: %s\n",world.players[world.whose_turn].c_str(), banner.c_str());
            return 1;
        }
        world.field = playerMove;
        world.pass = false;
        if (world.playerHand[world.whose_turn].empty()) {
            string msg = "MSG " + world.players[world.whose_turn] + " wins!\n";
            if(!deliver(world.whose_turn, msg.c_str(), clientFD)){
                fprintf(stderr, "host_game: Error sending Msg to [player%s]: %s\n", world.players[world.whose_turn].c_str(), msg.c_str());
                return 1;
            }
            if(!deliver((world.whose_turn + 1) % 2, msg.c_str(), clientFD)){
                fprintf(stderr, "host_game: Error sending Msg to [player%s]: %s\n", world.players[world.whose_turn].c_str(), msg.c_str());
                return 1;
            }
            world.winner = world.whose_turn;
        }
        world.whose_turn = (world.whose_turn + 1) % 2;
    }
    bool remote_alive = !world.connection_lost;
    remote_aborted = world.connection_lost;
    if(world.winner == 1){
        if(remote_alive){
            if(!send_frame(clientFD, "GAMESESS WIN B\n")){
                fprintf(stderr, "host_game: Error sending B WIN MSG.\n");
                return 1;
            }
        }
        win = 0;
    }
    else {
        if(remote_alive){
            if(!send_frame(clientFD, "GAMESESS LOSE B\n")){
                fprintf(stderr, "host_game: Error sending B LOSE MSG.\n");
                return 1;
            }
        }
        win = 1;
    }
    if (world.connection_lost) {
        deliver(0, "MSG Your opponent disconnected. You win by surrender.\n", clientFD);
    }
    return 0;
}
