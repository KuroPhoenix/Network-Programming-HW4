#include <sys/types.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netdb.h>
#include <arpa/inet.h>
#include <iostream>
#include <cstring>
#include <unistd.h>
#include <fstream>
#include <vector>
#include <string>
#include "config.h"
#include "game_engine.h"
#include <csignal>     
#include <atomic>      
using namespace std;



int lobby(int& lobbyFD, const string& player) {
    int playerA_FD = getUDPSocket();
    int tcp_conn_to_B = -1;
    bool logout = false;
    while (!logout && running && check_opponent(lobbyFD)) {
        cout << "Welcome, " << player << endl;
        int wins = 0, losses = 0;
        if (fetch_stats(lobbyFD, player, wins, losses)) {
            cout << "Record: " << wins << " win" << (wins == 1 ? "" : "s")
                 << ", " << losses << " loss" << (losses == 1 ? "" : "es") << "\n";
        }
        cout << "What would you like to do today?\n1. Find Opponents\n2. Learn the rules\n3. Log out\nPlease enter a number (1~3) to choose your action." << endl;
        if (!running || !check_opponent(lobbyFD)) {
            clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
            return 2;
        }
        int cmd = 0;
        cin >> cmd;
        bool has_found_opponents = false;
        string in;
        switch (cmd) {
            case 1:
                while (!has_found_opponents && running) {
                    if (!running || !check_opponent(lobbyFD)) {
                        clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
                        return 2;
                    }

                    std::vector<endpoint> activeB;
                    int status = discover_waiting_players(playerA_FD, player, activeB);
                    if (status == -1) {
                        if (!running || !check_opponent(lobbyFD)) {
                            clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
                            return 2;
                        }
                        std::cout << "Error discovering active opponents." << std::endl;
                        close(playerA_FD);
                        playerA_FD = -1;
                        return 1;
                    }

                    if (!running || !check_opponent(lobbyFD)) {
                        clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
                        return 2;
                    }

                    if (activeB.empty()) {
                        std::cout << "No waiting opponents detected." << std::endl;
                        std::cout << "Rescan? (y = yes / q = quit): " << std::flush;
                        std::string decision;
                        if (!std::getline(std::cin >> std::ws, decision)) {
                            if (!running || std::cin.eof()) {
                                clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
                                return 2;
                            }
                            std::cin.clear();
                            continue;
                        }
                        if (!running || !check_opponent(lobbyFD)) {
                            clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
                            return 2;
                        }
                        if (decision == "q" || decision == "Q") {
                            close(playerA_FD);
                            playerA_FD = -1;
                            return 1;
                        }
                        continue; // rescan
                    }

                    std::cout << "Pick an opponent or refresh (R) / quit (Q):" << std::endl;
                    int index = 0;
                    for (const auto& end : activeB) {
                        std::cout << "  [" << ++index << "] "
                                  << (end.label.empty() ? visualise_sockaddr_storage(end.addr) : end.label)
                                  << std::endl;
                    }
                    std::cout << "  [Q] Quit to menu" << std::endl;
                    std::cout << "  [R] Refresh list" << std::endl;
                    std::cout << "> " << std::flush;

                    std::string choice;
                    if (!std::getline(std::cin >> std::ws, choice)) {
                        if (!running || std::cin.eof()) {
                            clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
                            return 2;
                        }
                        std::cin.clear();
                        continue;
                    }
                    if (!running || !check_opponent(lobbyFD)) {
                        clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
                        return 2;
                    }
                    if (choice == "R" || choice == "r") {
                        continue; // rescan
                    }
                    if (choice == "Q" || choice == "q") {
                        close(playerA_FD);
                        playerA_FD = -1;
                        return 1;
                    }

                    errno = 0;
                    char* endptr = nullptr;
                    long userInput = strtol(choice.c_str(), &endptr, 10);
                    if (choice.c_str() == endptr || *endptr != '\0' || errno == ERANGE ||
                        userInput < 1 || userInput > static_cast<long>(activeB.size())) {
                        std::cout << "Invalid selection. Try again." << std::endl;
                        continue;
                    }

                    endpoint selected = activeB[userInput - 1];
                    IpPort expected_addr;
                    try {
                        expected_addr = ip_port_from_sockaddr(selected.addr);
                    } catch (const std::exception& ex) {
                        std::cout << "Unable to interpret opponent address: " << ex.what() << std::endl;
                        continue;
                    }

                    sockaddr_storage peer_addr = selected.addr;
                    socklen_t peer_len = selected.addrlen;
                    std::string opponent_label = selected.label.empty()
                                                  ? visualise_sockaddr_storage(selected.addr)
                                                  : selected.label;

                    std::cout << "[" << player << "] Sending invitation to " << opponent_label << "..." << std::endl;
                    std::string msg = player + " GAME REQ\n";
                    if (!udp_send_msg(playerA_FD, msg, reinterpret_cast<sockaddr*>(&peer_addr), peer_len)) {
                        std::cout << "Failed to send invitation." << std::endl;
                        continue;
                    }

                    bool awaiting_reply = true;
                    bool invitation_accepted = false;
                    std::string opponent_name;

                    while (awaiting_reply) {
                        sockaddr_storage from{};
                        socklen_t from_len = sizeof(from);
                        std::string response;
                        if (!recv_udp_with_timeout(playerA_FD, response, &from, &from_len, 5000)) {
                            if (errno == EAGAIN) {
                                std::cout << "[" << player << "] No response yet from " << opponent_label
                                          << ". Wait longer? (y = wait / q = quit): " << std::flush;
                                std::string wait_choice;
                                if (!std::getline(std::cin >> std::ws, wait_choice)) {
                                    if (!running || std::cin.eof()) {
                                        int dummy = -1;
                                        clean_up(dummy, playerA_FD, lobbyFD, player, "INTERRUPT");
                                        return 2;
                                    }
                                    std::cin.clear();
                                    continue;
                                }
                                if (!running || !check_opponent(lobbyFD)) {
                                    int dummy = -1;
                                    clean_up(dummy, playerA_FD, lobbyFD, player, "INTERRUPT");
                                    return 2;
                                }
                                if (wait_choice.empty() || wait_choice == "y" || wait_choice == "Y") {
                                    continue;
                                }
                                if (wait_choice == "q" || wait_choice == "Q") {
                                    close(playerA_FD);
                                    playerA_FD = -1;
                                    return 1;
                                }
                                std::cout << "[" << player << "] Invalid choice. Returning to the menu.\n";
                                close(playerA_FD);
                                playerA_FD = -1;
                                return 1;
                            }
                            std::perror("recv_udp_with_timeout");
                            clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
                            return 2;
                        }

                        std::string arr[3];
                        parse_line(response, arr);
                        IpPort actual;
                        try {
                            actual = ip_port_from_sockaddr(from);
                        } catch (...) {
                            continue;
                        }
                        if (actual.ip != expected_addr.ip || actual.port != expected_addr.port) {
                            continue; // stray response from discovery
                        }

                        if (arr[1] == "HERE") {
                            continue;
                        }

                        if (arr[1] == "REQ" && arr[2] == "RJ") {
                            std::cout << arr[0] << " declined your invitation." << std::endl;
                            awaiting_reply = false;
                            break;
                        }

                        if (arr[1] == "REQ" && arr[2] == "AC") {
                            opponent_name = arr[0];
                            peer_addr = from;
                            peer_len = from_len;
                            invitation_accepted = true;
                            awaiting_reply = false;
                            break;
                        }
                    }

                    if (!invitation_accepted) {
                        continue;
                    }

                    if (!running || !check_opponent(lobbyFD)) {
                        clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
                        return 2;
                    }

                    std::cout << "Your invitation was accepted. Starting the match!" << std::endl;
                    uint16_t out_port = 0;
                    int listeningFD = start_tcp_server(PLAYERA_IP, out_port);
                    if (listeningFD == -1) {
                        fprintf(stderr, "[%s] listening B error: %s\n", player.c_str(), strerror(errno));
                        close(playerA_FD);
                        playerA_FD = -1;
                        return 1;
                    }
                    msg = player + " PORT " + std::to_string(out_port);
                    udp_send_msg(playerA_FD, msg, reinterpret_cast<sockaddr*>(&peer_addr), peer_len);
                    if (!running || !check_opponent(lobbyFD)) {
                        close(listeningFD);
                        clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
                        return 2;
                    }
                    tcp_conn_to_B = accept(listeningFD, reinterpret_cast<sockaddr*>(&peer_addr), &peer_len);
                    if (!running || !check_opponent(lobbyFD)) {
                        close(listeningFD);
                        clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
                        return 2;
                    }
                    if (tcp_conn_to_B == -1) {
                        fprintf(stderr, "[%s] accept error: %s\n", player.c_str(), strerror(errno));
                        close(listeningFD);
                        return 2;
                    }
                    has_found_opponents = true;
                    if(!send_msg(lobbyFD, player + " MATCH " + opponent_name + "\n")){
                        cout << "Error sending match message to lobby server." << endl;
                        close(listeningFD);
                        clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
                        return 2;
                    }
                    close(listeningFD);
                }
                if (!running || !check_opponent(lobbyFD)) {
                    clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
                    return 2;
                }
                if (has_found_opponents && tcp_conn_to_B > 0) {
                    if (!running || !check_opponent(lobbyFD)) {
                        clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
                        return 2;
                    }
                    int win = 0;
                    bool remote_aborted = false;
                    int status = host_game(tcp_conn_to_B, lobbyFD, playerA_FD, win, remote_aborted);
                    if(status == 1){
                        cout << "Game Runtime Error." << endl;
                        close(tcp_conn_to_B);
                        tcp_conn_to_B = -1;
                        close(playerA_FD);
                        playerA_FD = -1;
                        return 1;
                    }
                    if(win == 1){
                        if(!send_msg(lobbyFD, player + " WIN GAME\n")){
                            cout << "Error sending message to lobby server." << endl;
                            clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
                            return 2;
                        }
                        if (!running || !check_opponent(lobbyFD)) {
                            clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
                            return 2;
                        }
                        if (!remote_aborted) {
                            string reply;
                            string arr[3];
                            if(!recv_line(lobbyFD, reply)){
                                cout << "[Info] Unable to confirm result with lobby, but the win has been reported." << endl;
                            } else {
                                parse_line(reply, arr);
                                if(arr[0] == player && arr[1] == "WIN" && arr[2] == "RECORDED"){
                                    cout << "WIN LOGGING SUCCESS!" << endl;
                                } else {
                                    cout << "[Warning] Unexpected lobby reply: " << reply << endl;
                                }
                            }
                        } else {
                            cout << "[Info] Opponent disconnected; win reported to lobby." << endl;
                        }
                        close(tcp_conn_to_B);
                        tcp_conn_to_B = -1;
                        close(playerA_FD);
                        playerA_FD = -1;
                        return 1;
                    }
                    else{
                        if(!send_msg(lobbyFD, player + " LOSE GAME\n")){
                            cout << "Error sending message to lobby server." << endl;
                            clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
                            return 2;
                        }
                        if (!running || !check_opponent(lobbyFD)) {
                            clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
                            return 2;
                        }
                        if (!remote_aborted) {
                            string reply;
                            string arr[3];
                            if(!recv_line(lobbyFD, reply)){
                                cout << "[Info] Unable to confirm loss with lobby." << endl;
                            } else {
                                parse_line(reply, arr);
                                if(arr[0] == player && arr[1] == "LOSS" && arr[2] == "RECORDED"){
                                    cout << "LOSS LOGGING SUCCESS!" << endl;
                                } else {
                                    cout << "[Warning] Unexpected lobby reply: " << reply << endl;
                                }
                            }
                        } else {
                            cout << "[Info] Opponent disconnected before the result was confirmed." << endl;
                        }
                        close(tcp_conn_to_B);
                        tcp_conn_to_B = -1;
                        close(playerA_FD);
                        playerA_FD = -1;
                        return 1;
                    }
                    close(tcp_conn_to_B);
                    tcp_conn_to_B = -1;
                    close(playerA_FD);
                    playerA_FD = -1;
                    return 1;
                }
                if (!running || !check_opponent(lobbyFD)) {
                    clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
                    return 2;
                }
                close(tcp_conn_to_B);
                tcp_conn_to_B = -1;
                break;
            case 2:
                cout << RULES << endl;
                cout << "(q)uit?" << endl;
                getline(cin >> ws, in);
                if (in == "q" || in == "Q" || in.empty()) {
                    break;
                }
                if (!running || !check_opponent(lobbyFD)) {
                    clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
                    return 2;
                }
                break;
            case 3: {
                if (!running || !check_opponent(lobbyFD)) {
                    clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
                    return 2;
                }
                if (!send_msg(lobbyFD, player + " LOGOUT MANUAL\n")) {
                    cout << "Error sending logout message to lobby server." << endl;
                    clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
                    return 2;
                }
                cout << "[player" << player << "] logging out, returning to lobby..." << endl;
                if (playerA_FD != -1) close(playerA_FD);
                playerA_FD = -1;
                if (tcp_conn_to_B != -1) close(tcp_conn_to_B);
                tcp_conn_to_B = -1;
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



int main(int argc, char *argv[]){
    /* Checking execution parameters*/
    int tcp_conn_to_B = -1;
    int playerA_FD = -1;
    install_signal_handlers();
    int lobbyFD = -1;
    int status = 0;
    bool loggedIn = false;
    while (running) {
        if (!running || (lobbyFD > 0 && !check_opponent(lobbyFD))){
            clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, "A", "INTERRUPT");
            break;
        }
        
        while (!loggedIn) {
            lobbyFD = tcp_connect_to("A", "Lobby", LOBBY_IP, LOBBY_PORT);
            if (lobbyFD == -1) {
                fprintf(stderr, "[playerA] connect error: %s\n", strerror(errno));
                return -1;
            }
            int st = welcome(lobbyFD, "A", loggedIn);
            if (st == 1) {
                cout << "An error happened in welcome. Exiting Programme..." << endl;
                clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, "A", "INTERRUPT");
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
            if (!running || !check_opponent(lobbyFD)){
                clean_up(tcp_conn_to_B, playerA_FD, lobbyFD, player, "INTERRUPT");
                break;
            }
            status = lobby(lobbyFD, player);
        }
        if(status == 2) loggedIn = false;
    }
    return 0;
}
