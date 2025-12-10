//
// Created by kurop on 21-Sep-25.
//

#ifndef CONFIG_H
#define CONFIG_H
#pragma once
#include <array>
#include <csignal>
#include <cstdint>
#include <string>
#include <vector>
#define LOBBY_IP "140.113.17.11"
#define LOBBY_PORT "15876"
#define PLAYERA_IP "0.0.0.0"
#define TIMEOUT 500

inline constexpr const char* PLAYERB_BIND_IP = "0.0.0.0";
inline constexpr std::uint16_t PLAYERB_DEFAULT_PORT = 10002;
inline constexpr std::uint16_t PLAYERB_PORT_MIN = 10000;
inline constexpr std::uint16_t PLAYERB_PORT_MAX = 10020;
inline constexpr int PLAYERB_SCAN_TOTAL_WINDOW_MS = 1500;
inline constexpr int PLAYERB_SCAN_SLICE_MS = 250;
inline const std::vector<std::string> PLAYERB_SCAN_HOSTS = {
        "127.0.0.1",
        "140.113.17.11",
        "140.113.17.12",
        "140.113.17.13",
        "140.113.17.14",
        "140.113.235.151",
        "140.113.235.152",
        "140.113.235.153",
        "140.113.235.154"
};
struct endpoint {
    sockaddr_storage addr;
    socklen_t addrlen;
    std::string label;
};
#include <unordered_map>
using namespace std;
struct user {
    string password;
    int wins;
    int losses;
    bool online;
};
struct IpPort {
    std::string ip;    // e.g. "203.0.113.7" or "2001:db8::1%en0"
    std::string port;  // e.g. "443"
};
extern volatile std::sig_atomic_t running;
void handle_signal(int);
IpPort ip_port_from_sockaddr(const sockaddr_storage& ss);
void install_signal_handlers();
inline unordered_map<string, int> user_to_sock;
inline unordered_map<int, string> sock_to_user;
inline unordered_map<string, user> username_to_info;
inline unordered_map<string, string> active_match;
#define BACKLOG 10
#define BUFFER_SIZE 1024
#define WELCOME_MSG "Welcome! Would you like to register for a new account, or log into an existing account? Please reply either \"register\" or \"login\", any other input will NOT be accepted. If you would like to exit this application, enter \"quit\".\n"
bool send_msg(int fd, const std::string& s);
bool udp_send_msg(int fd, const std::string& s, const sockaddr* to, socklen_t tolen);
bool recv_line(int fd, std::string& out);
void parse_line(const std::string& msg, std::string (&out)[3]);
int clientAccessAccountInfo(int fd, const std::string& player, const std::string& username, const std::string& password, const std::string& action);
int tcp_connect_to(const std::string &player, const std::string& to, const std::string& IP, const std::string& PORT);
int login(int fd, const std::string& player, std::string* user);
int reg(int fd, const std::string& player);
int welcome(int fd, const std::string& player, bool& isLoggedIn);
void erase_fd(int fd, struct pollfd **pfds, int *fd_count);
int clientRecvError(int fd, const std::string& player, const std::string& why);
bool recv_udp(int fd, std::string& out, sockaddr_storage* src = nullptr, socklen_t* srclen = nullptr);
int getListeningSocket(const std::string& IP, const std::string& PORT, const std::string& protocol);
int getUDPSocket();
bool construct_udp_addr(const char* ip, const char* port, sockaddr_storage& out, socklen_t& outlen);
int discover_waiting_players(int fd, const std::string& player, std::vector<endpoint>& opponents);
int bind_udp_port_range(const char* ip, std::uint16_t min_port, std::uint16_t max_port, std::uint16_t& out_port);
std::string visualise_sockaddr_storage(const sockaddr_storage& ss);
int start_tcp_server(std::string ip, uint16_t &out_port);
bool recv_udp_with_timeout(int fd, std::string& out, sockaddr_storage* src, socklen_t* srclen, int timeout_ms);
void clean_up(int& game_tcp_fd, int& invite_udp_fd, int& sockfd, const string& player, const string& reason);
bool check_opponent(int fd);
bool query_bound_port(int fd, std::uint16_t& out_port);
#define RULES "大老二是在台灣非常盛行的一種撲克牌遊戲，為什麼要叫大老二呢？因為這個遊戲規定最大的數字是２，所以就順口取名叫大老二。因為玩的速度比其它的快，而且規則不算太難，是台灣最流行的撲克牌遊戲。 \n最後的勝利者是第一個出完手上的牌的玩家。 \n顧名思義，點數2是最大的。其他大小順序是 2>A>K>Q>J>10>9>8>7>6>5>4>3\n要是數字相同，就得比花色。而花色普遍是黑桃>紅心>方塊>梅花 (台灣有些地方是玩方塊比紅心大的) \n所以一副牌中最大的牌就是「黑桃2」，而最小的牌則是「梅花3」。\n遊戲一開始每個玩家都會拿到１３張牌，拿到梅花３的人可以優先出牌，玩家可以選擇打5張(同花順.順子.鐵支.葫蘆)、2張(對子)、或1張(練單)等各式的牌形牌形。每一輪都在比大小，最大的玩家可以在下一輪先出。先出的人決定此一輪出的張數。 \n牌形介紹 \n要玩大老二要瞭解各式的牌形： \n1. 練單：出單張牌，先比數字，再比花色。 \n2. 對子：兩張數字相同的牌形。 \n比數字大小跟練單的方式一樣，但如果遇到兩個同數字。就得比花色，比的方式只比花色最大的一張。 \n黑桃３跟梅花３一對 ＞ 紅心３跟方塊３一對。 \n3. 順子：連續五張牌點相鄰的牌 \n如３４５６７、“910JQK”、“10JQKA”、Ａ２３４５等，順的張數必須是5張，A既可在順的最後，也可在順的最前，但不能在順的中間，如“JQKA2”不是順。 \n２３４５６最大 ＞ Ａ２３４５第二大 ＞ ３４５６７＞ ４５６７８ 以此類推。（也有人把在順子中的2當作小牌，在玩之前要說清楚） \n要是遇到相同的大小就得比最大的那一張牌的花色。例如３４５６７就比７看誰大，２３４５６就比誰的２大。 \n4. 同花：５張同樣花色的牌 \n相同的同花要比五張中最大一張的數字。數字相同就比第二大點數，依此類推。 \n5. 葫蘆：３張數子一樣的牌再加一個對子 \n要是遇到相同的葫蘆牌形，就得比三個中的最大一張的數字。 \n6. 鐵隻： ４張數字一樣的牌再加隨便一張牌 \n要是遇到相同的鐵隻牌形，要比４張的數字大小 \n7. 同花順：５張連續數字且花色相同的牌 \n同花順為大老二中最大的牌。顧名思義，就是同樣花色的順子。 \n出牌規則 \n1. 有梅花3的玩家先出牌，但不一定要出梅花3 \n2. 做下家的只能出跟上家同樣張數的牌，同時比首家所出的牌大 \n基本上當首家打單張時，你只能打比他所打還大的單張。 \n若首家是出兩張的對子.我們也只能出比他大的兩張的對子。 \n但是當首家打五張牌的牌型時，下家就可以打同樣是五張牌但同樣或比較大的牌型。 \n五張牌的牌型中，同花順最大，鐵隻第二，葫蘆第三，同花第四，順子最小。 \n3. 下家也可以Pass表示不出牌，由再下一家繼續出牌。 如果連續幾家都Pass，這時最後出牌的一家可以重新打出新的牌型。 \n4. 要是有一個玩家把手上的牌全部打完了，這場牌局就結束了，其他的玩家的輸贏則根據手中牌的大小扣分數。 \n此時只要手上還有幾張牌就得扣牌數乘１０的分數，要是你手上的牌超過１０張或手上的牌有老２的話，扣的分數就乘２。 \n其他的規則 \n當三人玩牌時，52張牌不能平分三個人，所以發到最後剩下的那張要蓋著，給有梅花3的人拿，因為梅花3是最先出的。\n另外.當四個人玩大老二時，每個人拿到的都是13張牌，如果有人拿到從A.2.3.4.5.......J.Q.K，13種數字都有時(不論花色).就叫做「一條龍」，此時他可以直接全出了，成為最大贏家 !"
#endif //CONFIG_H
