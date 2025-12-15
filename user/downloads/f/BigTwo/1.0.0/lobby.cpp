#include <sys/types.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netdb.h>
#include <arpa/inet.h>
#include <string>
#include <poll.h>
#include <iostream>
#include <cstring>
#include <unistd.h>
#include <vector>
#include <fstream>
#include <sstream>
#include <cstdlib>
#include <unordered_map>
#include <algorithm>
#include <csignal>
#include <atomic>
#include "config.h"
using namespace std;
// lobby.cpp (top-level)
namespace {
    std::atomic<bool> lobby_running{true};

    void lobby_signal_handler(int signo) noexcept {
        if (signo == SIGINT || signo == SIGTERM) {
            lobby_running.store(false, std::memory_order_relaxed);
        }
    }
}

bool save_file_atomic(const std::string& path, unordered_map<string, user>& username_to_info) {
    const std::string tmp = path + ".tmp";
    {
        std::ofstream out(tmp, std::ios::trunc);
        if (!out) return false;

        // deterministic order: sort keys
        std::vector<std::string> keys;
        keys.reserve(username_to_info.size());
        for (auto const& kv : username_to_info) keys.push_back(kv.first);
        std::sort(keys.begin(), keys.end());

        for (auto const& name : keys) {
            auto const& u = username_to_info.at(name);
            out << name << ' ' << u.password << ' '
                << u.wins << ' ' << u.losses << ' '
                << 0 << '\n';
        }
        out.flush();
        if (!out) return false;
    }
    // On POSIX, rename over existing file is atomic when same filesystem
    // (No need to std::remove(path.c_str()); rename will replace.)
    if (std::rename(tmp.c_str(), path.c_str()) != 0) {
        std::remove(tmp.c_str());
        return false;
    }
    return true;
}
void pfds_add(int fd, struct pollfd **pfds, int* fd_count, int* fd_size) {
    if (*fd_count == *fd_size) {
        *fd_size *= 2;
        *pfds = static_cast<struct pollfd *>(realloc(*pfds, *fd_size * sizeof(**pfds)));
    }
    (*pfds)[*fd_count].fd = fd;
    (*pfds)[*fd_count].events = POLLIN;
    (*pfds)[*fd_count].revents = 0;
    (*fd_count)++;
}

void pfds_del(int whichFD, struct pollfd **pfds, int* fd_count) {
    (*pfds)[whichFD] = (*pfds)[*fd_count-1];
    (*fd_count)--;
}

void new_connection(int listeningSocket, int *fd_count, int *fd_size, pollfd **pfds) {
    sockaddr_storage connectionQueue{};
    socklen_t connectionQueueLen = sizeof(connectionQueue);

    string remoteIP;
    char host[NI_MAXHOST], serv[NI_MAXSERV];
    int newFD = accept(listeningSocket, reinterpret_cast<sockaddr*>(&connectionQueue), &connectionQueueLen);
    if (newFD < 0) {
        fprintf(stderr, "accept error: %s\n", strerror(errno));
        return;
    }
    else {
        pfds_add(newFD, pfds, fd_count, fd_size);
        int status = getnameinfo(reinterpret_cast<sockaddr*>(&connectionQueue), connectionQueueLen, host, sizeof(host), serv, sizeof(serv), NI_NUMERICHOST | NI_NUMERICSERV);
        if (status != 0) {
            fprintf(stderr, "getnameinfo error: %s\n", gai_strerror(status));
            return;
        }
        string family = (connectionQueue.ss_family == AF_INET) ? "IPv4" : "IPv6";
        cout << "[Lobby] New " << family << " Connection established: from " << host << ": " << serv << ", fd = " << newFD << endl;
    }
}
void clean_up_lobby(int senderFD, int* fd_count, struct pollfd **pfds, int* whichPfd, const string& username, const string& object){
    string errMsg = "ERR UNKNOWN " + object + "\n";
    cout << errMsg;
    fflush(stdout);
    if(!send_msg(senderFD, errMsg)){
        fprintf(stderr, "clean_up_lobby: [player%s] ERROR SENDING ERR MESSAGE\n", username.c_str());
    }
    user_to_sock.erase(username);
    sock_to_user.erase(senderFD);
    close(senderFD);
    erase_fd(senderFD, pfds, fd_count);
    (*whichPfd)--;
}
void clean_up_lobby_nameless(int senderFD, int* fd_count, struct pollfd **pfds, int* whichPfd, const string& object){
    string errMsg = "ERR UNKNOWN " + object + "\n";
    cout << errMsg;
    fflush(stdout);
    if(!send_msg(senderFD, errMsg)){
        fprintf(stderr, "clean_up_lobby_nameless: ERROR SENDING ERR MESSAGE\n");
    }
    close(senderFD);
    erase_fd(senderFD, pfds, fd_count);
    (*whichPfd)--;
}
void client_connection(int listeningSocket, int* fd_count, int* fd_size, struct pollfd **pfds, int* whichPfd) {
    string msg;
    string arr[3];
    int senderFD = (*pfds)[*whichPfd].fd;
    if (!recv_line(senderFD, msg)) {
        if (auto it = sock_to_user.find(senderFD); it != sock_to_user.end()) {
            const string& uname = it->second;
            username_to_info[uname].online = false;
            user_to_sock.erase(uname);
            sock_to_user.erase(it);
        }
        if (errno) perror("recv"); else std::cerr << "peer closed\n";
        close(senderFD);
        erase_fd(senderFD, pfds, fd_count);
        (*whichPfd)--;
        return;
    }

    if (msg.empty()) {
        if (auto it = sock_to_user.find(senderFD); it != sock_to_user.end()) {
            const string& uname = it->second;
            username_to_info[uname].online = false;
            user_to_sock.erase(uname);
            sock_to_user.erase(it);
        }
        cout << "[Lobby] socket " << senderFD << " connection closed.\n";
        close(senderFD);
        pfds_del(*whichPfd, pfds, fd_count);
        (*whichPfd)--; //go back to the previous fd so that in the next iteration, we would not miss the original (*pfds[fd_count]).
        return;
    }
    else {
        parse_line(msg, arr);
        cout << "[Lobby] Received data from socket " << senderFD << ": " << msg << endl;
        if (arr[1] == "WIN") {
            auto it = sock_to_user.find(senderFD);
            if(it == sock_to_user.end()){
                clean_up_lobby_nameless(senderFD, fd_count, pfds, whichPfd, "SOCKET");
                return;
            }
            string winner = sock_to_user[senderFD];

            if (auto it = username_to_info.find(winner); it != username_to_info.end()) {
                it->second.wins++;
                string ret = winner + " WIN RECORDED\n";
                if(!send_msg(senderFD, ret)){
                    fprintf(stderr, "client_connection: Lobby Failure to send win message to [player%s]\n", winner.c_str());
                }
                if (auto match_it = active_match.find(winner); match_it != active_match.end()) {
                    string opponent = match_it->second;
                    active_match.erase(match_it);
                    if (!opponent.empty()) {
                        if (auto opp_it = active_match.find(opponent); opp_it != active_match.end()) {
                            active_match.erase(opp_it);
                        }
                    }
                }

                save_file_atomic("AccountInfo.txt", username_to_info);
            } else {
                clean_up_lobby(senderFD, fd_count, pfds, whichPfd, winner, "USER");
                return;
            }
        }
        else if (arr[1] == "LOSE") {
            auto it = sock_to_user.find(senderFD);
            if(it == sock_to_user.end()){
                clean_up_lobby_nameless(senderFD, fd_count, pfds, whichPfd, "SOCKET");
                return;
            }
            string loser = sock_to_user[senderFD];
            if (auto it = username_to_info.find(loser); it != username_to_info.end()) {
                it->second.losses++;
                string ret = loser + " LOSS RECORDED\n";
                if(!send_msg(senderFD, ret)){
                    fprintf(stderr, "client_connection: Lobby Failure to send loss message to [player%s]\n", loser.c_str());
                }
                if (auto match_it = active_match.find(loser); match_it != active_match.end()) {
                    string opponent = match_it->second;
                    active_match.erase(match_it);
                    if (!opponent.empty()) {
                        if (auto opp_it = active_match.find(opponent); opp_it != active_match.end()) {
                            active_match.erase(opp_it);
                        }
                    }
                }
                save_file_atomic("AccountInfo.txt", username_to_info);
            } else {
                clean_up_lobby(senderFD, fd_count, pfds, whichPfd, loser, "USER");
                return;
            }
        }
        else if (arr[1] == "connection") {
            if(arr[0] == "A" || arr[0] == "B"){
                if(!send_msg(senderFD, arr[0] + " connection ACK\n")){
                    fprintf(stderr, "client connection: Lobby Failure to send CONN_ACK to player.\n");
                }
                if(!send_msg(senderFD, arr[0] + " welcomeMsg " + WELCOME_MSG)){
                    fprintf(stderr, "client connection: Lobby Failure to send WELCOME_MSG to player.\n");
                }
            }
            else{
                clean_up_lobby_nameless(senderFD, fd_count, pfds, whichPfd, "CONNECTION");
                return;
            }
        }
        else if (arr[1] == "findUsername") {
            /*
             * <player> <findUsername> <username>
             */
            if(!arr[2].empty()){
                if (username_to_info.contains(arr[2])){
                    if(!send_msg(senderFD, arr[0] + " " + arr[1] + " EXIST\n")){
                        fprintf(stderr, "client_connection: Lobby Failure to send findUsername message to player.\n");
                    }
                }
                else{
                    if(!send_msg(senderFD, arr[0] + " " + arr[1] + " NOEXIST\n")){
                        fprintf(stderr, "client_connection: Lobby Failure to send findUsername message to player.\n");
                    }
                }
            }
            else{
                clean_up_lobby_nameless(senderFD, fd_count, pfds, whichPfd, "USER");
                return;
            }
        }
        else if (arr[1] == "registration") {
            user newUser;
            auto pos = arr[2].find(' ');
            if(pos == std::string::npos){
                clean_up_lobby_nameless(senderFD, fd_count, pfds, whichPfd, "MSG");
                return;
            }
            else{
                newUser.password = arr[2].substr(pos + 1);
                newUser.losses = 0;
                newUser.online = false;
                newUser.wins = 0;
                if (username_to_info.contains(arr[2].substr(0, pos))) {
                    if(!send_msg(senderFD, arr[0] + " " + arr[1] + " EXIST\n")){
                        fprintf(stderr, "client_connection: Lobby Failure to send registration message to player.\n");
                    }
                    return;
                }
                username_to_info[arr[2].substr(0, pos)] = newUser;
                save_file_atomic("AccountInfo.txt", username_to_info);
                if(!send_msg(senderFD, arr[0] + " " + arr[1] + " OK\n")){
                    fprintf(stderr, "client_connection: Lobby Failure to send registration confirmation message to player.\n");
                }
            }
        }
        else if (arr[1] == "login") {
            auto pos = arr[2].find(' ');
            if(pos == std::string::npos){
                clean_up_lobby_nameless(senderFD, fd_count, pfds, whichPfd, "MSG");
                return;
            }
            else{
                string username = arr[2].substr(0, pos);
                string password = arr[2].substr(pos + 1);
                auto it = username_to_info.find(username);
                if (it != username_to_info.end() && username_to_info[username].password == password) {
                    if (username_to_info[username].online) {
                        if(!send_msg(senderFD, arr[0] + " login ONLINE\n")){
                            fprintf(stderr, "client_connection: Lobby Failure to send duplicate login message to [player%s]\n", username.c_str());
                        }
                        return;
                    }
                    if(!send_msg(senderFD, arr[0] + " " + arr[1] + " OK\n")){
                        fprintf(stderr, "client_connection: Lobby Failure to send Login_ACK message to [player%s]\n", username.c_str());
                    }
                    username_to_info[username].online = true;
                    sock_to_user[senderFD] = username;
                    user_to_sock[username] = senderFD;
                }
                else {
                    if(!send_msg(senderFD, arr[0] + " " + arr[1] + " Invalid Username/Password.\n")){
                        fprintf(stderr, "client_connection: Lobby Failure to send Login Error Message to [player%s]\n", username.c_str());
                    }
                }
            }
        }
        else if (arr[1] == "STATS") {
            if(!username_to_info.contains(arr[0])){
                clean_up_lobby_nameless(senderFD, fd_count, pfds, whichPfd, "USER");
                return;
            }
            auto const& info = username_to_info[arr[0]];
            std::ostringstream oss;
            oss << arr[0] << " STATS " << info.wins << ' ' << info.losses << "\n";
            if(!send_msg(senderFD, oss.str())){
                fprintf(stderr, "client_connection: Lobby Failure to send stats to [%s]\n", arr[0].c_str());
            }
        }
        else if(arr[1] == "LOGOUT"){
            if(!sock_to_user.contains(senderFD)){
                clean_up_lobby_nameless(senderFD, fd_count, pfds, whichPfd, "SOCKET");
                return;
            }
            if(!user_to_sock.contains(arr[0])){
                clean_up_lobby_nameless(senderFD, fd_count, pfds, whichPfd, "USER");
                return;
            }
            if(!username_to_info.contains(arr[0])){
                clean_up_lobby_nameless(senderFD, fd_count, pfds, whichPfd, "USER");
                return;
            }
            int fd = user_to_sock[arr[0]];
            string opponent;
            int opponent_fd = -1;
            if (auto match_it = active_match.find(arr[0]); match_it != active_match.end()) {
                opponent = match_it->second;
                active_match.erase(match_it);
                if (!opponent.empty()) {
                    if (auto opp_it = active_match.find(opponent); opp_it != active_match.end()) {
                        active_match.erase(opp_it);
                    }
                    if (auto opp_fd_it = user_to_sock.find(opponent); opp_fd_it != user_to_sock.end()) {
                        opponent_fd = opp_fd_it->second;
                    }
                }
            }
            username_to_info[arr[0]].online = false;
            sock_to_user.erase(fd);
            user_to_sock.erase(arr[0]);
            /*differentiate MANUAL and INTERRUPT*/
            if(arr[2] == "INTERRUPT" && !opponent.empty() && opponent_fd != -1){
                if(!send_msg(opponent_fd, opponent + " " + arr[1] + " " + arr[2] + "\n")){
                    fprintf(stderr, "client_connection: Lobby Failure to send INTERRUPT LOGOUT Message to [player%s]\n", opponent.c_str());
                }
            }
        }
        else if(arr[1] == "MATCH"){
            if(!active_match.contains(arr[0]) && !active_match.contains(arr[2])){
                active_match[arr[0]] = arr[2];
                active_match[arr[2]] = arr[0];
            }
        }
        else{
            clean_up_lobby_nameless(senderFD, fd_count, pfds, whichPfd, "MSG");
            return;
        }
    }

}

void process_connections(int listeningSocket, int *fd_count, int *fd_size, pollfd **pfds) {
    for (int i = 0; i < *fd_count; i++) {
        if ((*pfds)[i].revents & (POLLIN | POLLHUP | POLLERR)) {
            if ((*pfds)[i].fd == listeningSocket) {
                new_connection(listeningSocket, fd_count, fd_size, pfds);
            }
            else {
                client_connection(listeningSocket, fd_count, fd_size, pfds, &i);
            }
        }
    }
}

void parse_file(ifstream &file) {
    string username, password;
    int wins, losses, online;
    while (file >> username >> password >> wins >> losses >> online) {
        user u = {password, wins, losses, false};
        username_to_info[username] = u;
    }
}



int main(int argc, char *argv[]) {
    std::signal(SIGINT, lobby_signal_handler);
    std::signal(SIGTERM, lobby_signal_handler);
    sock_to_user.clear();
    user_to_sock.clear();
    active_match.clear();
    ifstream read("AccountInfo.txt");
    if (!read.is_open()) {
        ofstream create("AccountInfo.txt", ios::app); // create if missing
        if (!create.is_open()) {
            cout << "Error creating AccountInfo.txt.\n";
            return 1;
        }
        // newly created file => empty DB
    } else {
        parse_file(read);
    }

    //get listening socket and begin listening
    int listeningSocket = getListeningSocket(LOBBY_IP, LOBBY_PORT, "TCP");
    if (listeningSocket == -1) {
        fprintf(stderr, "error getting listening socket.\n");
        return -1;
    }
    if(!lobby_running){
        close(listeningSocket);
        listeningSocket = -1;
        if(read.peek() != std::ifstream::traits_type::eof())save_file_atomic("AccountInfo.txt", username_to_info);
        return 1;
    }
    //begin polling for connections
    int fd_size = 5;
    int fd_count = 1;
    pollfd *pfds = (pollfd*)malloc(fd_size * sizeof(pollfd));
    pfds[0].fd = listeningSocket;
    pfds[0].events = POLLIN;
    cout << "Waiting for connections..." << endl;
    while (lobby_running.load(std::memory_order_relaxed)) {
        int poll_count = poll(pfds, fd_count, 1000);
        if (poll_count < 0) {
            if (errno == EINTR) continue;  // loop; lobby_running may now be false
            perror("poll");
            break;
        }
        process_connections(listeningSocket, &fd_count, &fd_size, &pfds);
    }
    free(pfds);
    save_file_atomic("AccountInfo.txt", username_to_info);
    return 0;
}





