#include <sys/types.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netdb.h>
#include <arpa/inet.h>
#include <iostream>
#include <cstring>
#include <unistd.h>
#include <fstream>
#include <poll.h>
#include <unordered_map>
#include <string>
#include <cstdint>
#include "config.h"
#include "game_engine.h"
using namespace std;


int lobby(int& lobbyFD, const string& player) { //0: success 1: return to lobby 2: outright logout
    cout << "Welcome, " << player << endl;
    int wins = 0, losses = 0;
    if (fetch_stats(lobbyFD, player, wins, losses)) {
        cout << "Record: " << wins << " win" << (wins == 1 ? "" : "s")
             << ", " << losses << " loss" << (losses == 1 ? "" : "es") << "\n";
    }
    bool logout = false;
    int cmd = 0;
    int tcp_to_A_sock = -1;
    int playerB_FD = -1;
    while (!logout && running) {
        cout << "What would you like to do today?\n1. Look for invitations\n2. Learn the rules\n3. Log out\nPlease enter a number (1~3) to choose your action." << endl;
        cmd = 0;
        cin >> cmd;
        switch (cmd) {
            case 1: {
                tcp_to_A_sock = -1;
                std::uint16_t udp_port = 0;
                playerB_FD = bind_udp_port_range(PLAYERB_BIND_IP, PLAYERB_PORT_MIN, PLAYERB_PORT_MAX, udp_port);
                if (playerB_FD == -1) {
                    fprintf(stderr, "[%s] unable to bind UDP listener: %s\n", player.c_str(), strerror(errno));
                    break;
                }

                auto close_udp = [&]() {
                    if (playerB_FD != -1) {
                        close(playerB_FD);
                        playerB_FD = -1;
                    }
                };

                if (!running || !check_opponent(lobbyFD)) {
                    close_udp();
                    clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                    return 2;
                }

                cout << "[" << player << "] Listening for invitations on UDP port " << udp_port << endl;
                string msg;
                sockaddr_storage from{}; socklen_t flen = sizeof(from);
                sockaddr_storage dst{};
                socklen_t destlen = sizeof(dst);
                string arr[3];
                bool connectedGame = false;
                IpPort peer;
                while (true) {
                    if (!recv_udp_with_timeout(playerB_FD, msg, &from, &flen, 60000)) {
                        if (errno == EAGAIN) {          // no data within TIMEOUT
                            if (!running || !check_opponent(lobbyFD)) {
                                close_udp();
                                clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                                return 2;
                            }
                            cout << "Timeout without response. Returning to menu..." << endl;
                            close_udp();
                            return 1;
                        }
                        // permanent error (poll/recv failed)
                        std::perror("recv_udp_with_timeout");
                        close_udp();
                        close(tcp_to_A_sock);
                        tcp_to_A_sock = -1;
                        close(playerB_FD);
                        playerB_FD = -1;
                        return 2;
                    }
                    parse_line(msg, arr);
                    if (arr[1] == "DISCOVER" && arr[2] == "WHO") {
                        std::string reply = player + " HERE WAITING\n";
                        udp_send_msg(playerB_FD, reply, (sockaddr*)&from, flen);
                        continue;
                    }
                    IpPort A_ip_port = ip_port_from_sockaddr(from);
                    if (arr[1] == "connection" && arr[2] == "SYN") {
                        if (!construct_udp_addr(A_ip_port.ip.c_str(), A_ip_port.port.c_str(), dst, destlen)) {
                            cout << "Error constructing playerA UDP Addr." << endl;
                            break;
                        }
                        if (!running || !check_opponent(lobbyFD)) {
                            close_udp();
                            clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                            return 2;
                        }
                        msg = player + " connection ACK\n";
                        udp_send_msg(playerB_FD, msg, (sockaddr*)&from, flen);
                    }
                    else if (arr[1] == "GAME" && arr[2] == "REQ") {
                        if (!running || !check_opponent(lobbyFD)) {
                            close_udp();
                            clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                            return 2;
                        }
                        cout << arr[0] << " sent you a game request. Accept (y/n)?" << endl;
                        string line;
                        getline(cin >> ws, line);
                        if (line == "y" || line == "Y") {
                            udp_send_msg(playerB_FD, player + " REQ AC\n", (sockaddr *) &from, flen);
                        } else {
                            udp_send_msg(playerB_FD, player + " REQ RJ\n", (sockaddr*)&from, flen);
                            cout << "Invitation declined. Listening for new opponents..." << endl;
                            continue;
                        }
                    }
                    else if (arr[1] == "PORT") {
                        if (!running || !check_opponent(lobbyFD)) {
                            close_udp();
                            clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                            return 2;
                        }
                        cout << "Received " << arr[0] << "'s connection info. Establishing the game session..." << endl;
                        connectedGame = true;
                        if(!send_msg(lobbyFD, player + " MATCH " + arr[0] + "\n")){
                            cout << "Error sending match message to lobby server." << endl;
                            close_udp();
                            clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                            return 2;
                        }
                        peer = ip_port_from_sockaddr(from);
                        break;

                    }
                    else {
                        cout << "Unexpected lobby message from " << arr[0] << ": " << arr[1] << ' ' << arr[2] << endl;
                        close_udp();
                        clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                        return 2;
                    }
                }
                if (connectedGame) {
                    close_udp();
                    if (!running || !check_opponent(lobbyFD)) {
                        close_udp();
                        clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                        return 2;
                    }
                    tcp_to_A_sock = tcp_connect_to(player, arr[0], peer.ip, arr[2]);
                    if (tcp_to_A_sock == -1) {
                        fprintf(stderr, "[%s] connect error: %s\n", player.c_str(), strerror(errno));
                        close(playerB_FD);
                        playerB_FD = -1;
                        close_udp();
                        return 1;
                    }
                    if (!running || !check_opponent(lobbyFD)) {
                        close_udp();
                        clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                        return 2;
                    }
                    if(!send_frame(tcp_to_A_sock, "USER " + sock_to_user[lobbyFD])){
                        fprintf(stderr, "playerB Lobby: Failure sending info to opponent.\n");
                        close_udp();
                        clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                        return 2;
                    }
                    while (true) {
                        string action, content, input;
                        if (recv_frame(tcp_to_A_sock, msg)) {
                            if (!running || !check_opponent(lobbyFD)) {
                        close_udp();
                                clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                                return 2;
                            }
                            parse_frame(msg, action, content);
                            cout << content;
                            fflush(stdout);
                        }
                        else{
                            cout << "Lost connection to " << arr[0] << " during the game." << endl;
                        close_udp();
                            clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                            return 2;
                        }
                        if (action ==  "PROMPT") {
                            cout << "> " << std::flush;
                            getline(cin >> ws, input);
                            if(!send_frame(tcp_to_A_sock, input)){
                                fprintf(stderr, "playerB Lobby: Failure sending input to opponent.\n");
                                close_udp();
                                clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                                return 2;
                            }
                            if (!running || !check_opponent(lobbyFD)) {
                                close_udp();
                                clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                                return 2;
                            }
                        }
                        if(action == "GAMESESS"){
                            if(content == "ERR PARSING"){
                                cout << "An error occurred at parsing player input." << endl;
                                close(tcp_to_A_sock);
                                tcp_to_A_sock = -1;
                                close(playerB_FD);
                                playerB_FD = -1;
                                close_udp();
                                return 1;
                            }
                            if (content == "WIN B\n") {
                                if(!send_msg(lobbyFD, player + " WIN GAME\n")){
                                    cout << "Error sending message to lobby server." << endl;
                                    close_udp();
                                    clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                                    return 2;
                                }
                                if (!running || !check_opponent(lobbyFD)) {
                                    close_udp();
                                    clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                                    return 2;
                                }
                                string reply;
                                string arr[3];
                                if(!recv_line(lobbyFD, reply)){
                                    cout << "Error receiving message from lobby server." << endl;
                                    close_udp();
                                    clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                                    return 2;
                                }
                                parse_line(reply, arr);
                                if(arr[0] == player && arr[1] == "WIN" && arr[2] == "RECORDED"){
                                    cout << "WIN LOGGING SUCCESS!" << endl;
                                    close(tcp_to_A_sock);
                                    tcp_to_A_sock = -1;
                                    close(playerB_FD);
                                    playerB_FD = -1;
                                    close_udp();
                                    return 1;
                                }
                                else if(arr[0] == "ERR" && arr[1] == "UNKNOWN" && arr[2] == "USER"){
                                    cout << "Oops! There seems to be something wrong with the player client. Please log in again, this game's result will NOT be recorded. We apologise for any inconvenience caused." << endl;
                                    close_udp();
                                    clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                                    return 2;
                                }
                                else{
                                    cout << "An unexpected error occurred. Please log in again. This game's result will NOT be recorded. We apologise for any inconvenience caused." << endl;
                                    close_udp();
                                    clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                                    return 2;
                                }
                            }
                            if (content == "LOSE B\n") {
                                if(!send_msg(lobbyFD, player + " LOSE GAME\n")){
                                    cout << "Error sending message to lobby server." << endl;
                                    close_udp();
                                    clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                                    return 2;
                                }
                                string reply;
                                string arr[3];
                                if(!recv_line(lobbyFD, reply)){
                                    cout << "Error receiving message from lobby server." << endl;
                                    close_udp();
                                    clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                                    return 2;
                                }
                                parse_line(reply, arr);
                                if(arr[0] == player && arr[1] == "LOSS" && arr[2] == "RECORDED"){
                                    cout << "LOSS LOGGING SUCCESS!" << endl;
                                    close(tcp_to_A_sock);
                                    tcp_to_A_sock = -1;
                                    close(playerB_FD);
                                    playerB_FD = -1;
                                    close_udp();
                                    return 1;
                                }
                                else if(arr[0] == "ERR" && arr[1] == "UNKNOWN" && arr[2] == "USER"){
                                    cout << "Oops! There seems to be something wrong with the player client. Please log in again, this game's result will NOT be recorded. We apologise for any inconvenience caused." << endl;
                                    close_udp();
                                    clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                                    return 2;
                                }
                                else{
                                    cout << "An unexpected error occurred. Please log in again. This game's result will NOT be recorded. We apologise for any inconvenience caused." << endl;
                                    close_udp();
                                    clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                                    return 2;
                                }
                            }
                            close(tcp_to_A_sock);
                            tcp_to_A_sock = -1;
                            close(playerB_FD);
                            playerB_FD = -1;
                            close_udp();
                            return 1;
                        }
                    }
                }
                if (!running || !check_opponent(lobbyFD)) {
                    close_udp();
                    clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                    return 2;
                }
                close_udp();
                if (playerB_FD != -1) {
                    close(playerB_FD);
                    playerB_FD = -1;
                }
                break;
            }
            case 2:
                if (!running || !check_opponent(lobbyFD)) {
                    clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                    return 2;
                }
                cout << RULES << endl;
                break;
            case 3: {
                if (!running || !check_opponent(lobbyFD)) {
                    clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                    return 2;
                }
                if (!send_msg(lobbyFD, player + " LOGOUT MANUAL\n")) {
                    cout << "Error sending logout message to lobby server." << endl;
                    clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                    return 2;
                }
                cout << "[player" << player << "] logging out, returning to lobby..." << endl;
                if (playerB_FD != -1) close(playerB_FD);
                playerB_FD = -1;
                if (tcp_to_A_sock != -1) close(tcp_to_A_sock);
                tcp_to_A_sock = -1;
                const int oldLobbyFD = lobbyFD;
                if (lobbyFD != -1) close(lobbyFD);
                lobbyFD = -1;
                if (oldLobbyFD != -1) {
                    sock_to_user.erase(oldLobbyFD);
                }
                user_to_sock.erase(player);
                if (username_to_info.contains(player)) {
                    username_to_info[player].online = false;
                }
                logout = true;
                return 2;
                break;
            }

            default:
                break;
        }
    }
    return 0;
}

int main(int argc, char *argv[]) {
    install_signal_handlers();
    /* Checking execution parameters*/
    int lobbyFD = -1;
    bool loggedIn = false;
    int tcp_to_A_sock = -1;
    int playerB_FD = -1;
    int status = 0;
    while (running) {
        if (!running || (lobbyFD > 0 && !check_opponent(lobbyFD))) {
            clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, "B", "INTERRUPT");
            break;
        }
        while (!loggedIn){
            lobbyFD = tcp_connect_to("B","Lobby", LOBBY_IP, LOBBY_PORT);
            if (lobbyFD == -1) {
                fprintf(stderr, "[playerB] connect error: %s\n", strerror(errno));
                return -1;
            }
            int st = welcome(lobbyFD, "B", loggedIn);
            if (st == 1) {
                cout << "An error happened at welcome." << endl;
                clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, "B", "INTERRUPT");
                break;
            }
            if (st == 2) {
                if (lobbyFD != -1) {
                    close(lobbyFD);
                    lobbyFD = -1;
                }
                return 0;
            }
        }
        if (loggedIn) {
            string player = sock_to_user[lobbyFD];
            if (!running || !check_opponent(lobbyFD)) {
                clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                break;
            }
            status = lobby(lobbyFD, player);
            if (!running || !check_opponent(lobbyFD)) {
                clean_up(tcp_to_A_sock, playerB_FD, lobbyFD, player, "INTERRUPT");
                break;
            }
        }
        if(status == 2) loggedIn = false;
    }
}
