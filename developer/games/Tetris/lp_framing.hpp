#pragma once
#include <string>
#include <cstdint>
#include <arpa/inet.h>
#include <cerrno>
#include "common.hpp"

inline bool lp_send_frame(int fd, const std::string& body) {
    if (body.empty() || body.size() > 65536) {
        errno = EMSGSIZE;
        return false;
    }
    uint32_t len = htonl(static_cast<uint32_t>(body.size()));
    if (!send_all(fd, &len, 4)) return false;
    if (!send_all(fd, body.data(), body.size())) return false;
    return true;
}

inline bool lp_recv_frame(int fd, std::string& out) {
    uint32_t netlen = 0;
    if (!recv_all(fd, &netlen, 4)) return false;
    uint32_t len = ntohl(netlen);
    if (len == 0 || len > 65536) {
        errno = EINVAL;
        return false;
    }
    out.resize(len);
    if (!recv_all(fd, out.data(), len)) return false;
    return true;
}
