#include "autolink/http_link.hpp"

#include <arpa/inet.h>
#include <fcntl.h>
#include <netdb.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <cerrno>
#include <cstring>
#include <memory>
#include <sstream>

namespace autolink {
namespace {
constexpr size_t kMaxHeaderBytes = 16 * 1024;
constexpr size_t kMaxJsonBodyBytes = 1024 * 1024;
constexpr size_t kReadChunk = 16 * 1024;

class Socket {
 public:
  explicit Socket(int fd) : fd_(fd) {}
  ~Socket() {
    if (fd_ >= 0) ::close(fd_);
  }
  Socket(const Socket&) = delete;
  Socket& operator=(const Socket&) = delete;
  int fd() const { return fd_; }

 private:
  int fd_;
};

std::string lower(std::string s) {
  std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return std::tolower(c); });
  return s;
}

void send_all(int fd, const std::string& data) {
  size_t off = 0;
  while (off < data.size()) {
    ssize_t n = ::send(fd, data.data() + off, data.size() - off, MSG_NOSIGNAL);
    if (n < 0) {
      if (errno == EINTR) continue;
      throw TransportError(std::string("send failed: ") + std::strerror(errno));
    }
    off += static_cast<size_t>(n);
  }
}

ssize_t recv_some(int fd, char* buf, size_t len) {
  while (true) {
    ssize_t n = ::recv(fd, buf, len, 0);
    if (n < 0 && errno == EINTR) continue;
    if (n < 0) {
      if (errno == EAGAIN || errno == EWOULDBLOCK) throw TransportError("receive timeout");
      throw TransportError(std::string("recv failed: ") + std::strerror(errno));
    }
    return n;
  }
}

std::string build_request(const Url& u, const std::string& method, const std::string& path,
                          const std::map<std::string, std::string>& headers, const std::string& body) {
  std::ostringstream os;
  os << method << ' ' << u.base_path << path << " HTTP/1.1\r\n"
     << "Host: " << u.host << ':' << u.port << "\r\n"
     << "Connection: close\r\n"
     << "User-Agent: autolink-ecu/1.0\r\n";
  for (const auto& [k, v] : headers) {
    if (k.find_first_of("\r\n") != std::string::npos || v.find_first_of("\r\n") != std::string::npos)
      throw TransportError("header injection rejected");
    os << k << ": " << v << "\r\n";
  }
  if (!body.empty() || method == "POST") os << "Content-Length: " << body.size() << "\r\n";
  os << "\r\n" << body;
  return os.str();
}

// Reads status line + headers; returns any body bytes already received.
std::string read_head(int fd, HttpResponse& resp) {
  std::string buf;
  char tmp[kReadChunk];
  size_t end;
  while ((end = buf.find("\r\n\r\n")) == std::string::npos) {
    if (buf.size() > kMaxHeaderBytes) throw TransportError("response headers too large");
    ssize_t n = recv_some(fd, tmp, sizeof tmp);
    if (n == 0) throw TransportError("connection closed before headers");
    buf.append(tmp, static_cast<size_t>(n));
  }
  std::istringstream hs(buf.substr(0, end));
  std::string line;
  std::getline(hs, line);
  if (line.rfind("HTTP/1.", 0) != 0 || line.size() < 12) throw TransportError("bad status line");
  resp.status = std::atoi(line.c_str() + 9);
  while (std::getline(hs, line)) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    auto colon = line.find(':');
    if (colon == std::string::npos) continue;
    std::string v = line.substr(colon + 1);
    v.erase(0, v.find_first_not_of(' '));
    resp.headers[lower(line.substr(0, colon))] = v;
  }
  if (resp.headers.count("transfer-encoding")) throw TransportError("chunked encoding not supported");
  return buf.substr(end + 4);
}
}  // namespace

Url Url::parse(const std::string& url) {
  const std::string scheme = "http://";
  if (url.rfind(scheme, 0) != 0) throw std::invalid_argument("only http:// URLs are supported: " + url);
  std::string rest = url.substr(scheme.size());
  Url u;
  auto slash = rest.find('/');
  std::string hostport = rest.substr(0, slash);
  u.base_path = slash == std::string::npos ? "" : rest.substr(slash);
  if (!u.base_path.empty() && u.base_path.back() == '/') u.base_path.pop_back();
  auto colon = hostport.find(':');
  u.host = hostport.substr(0, colon);
  if (colon != std::string::npos) u.port = std::stoi(hostport.substr(colon + 1));
  if (u.host.empty() || u.port <= 0 || u.port > 65535) throw std::invalid_argument("bad URL " + url);
  return u;
}

int HttpClient::connect_socket() {
  addrinfo hints{};
  hints.ai_family = AF_UNSPEC;
  hints.ai_socktype = SOCK_STREAM;
  addrinfo* res = nullptr;
  if (::getaddrinfo(url_.host.c_str(), std::to_string(url_.port).c_str(), &hints, &res) != 0 || !res)
    throw TransportError("DNS resolution failed for " + url_.host);
  std::unique_ptr<addrinfo, decltype(&::freeaddrinfo)> guard(res, ::freeaddrinfo);
  int fd = ::socket(res->ai_family, res->ai_socktype | SOCK_CLOEXEC, res->ai_protocol);
  if (fd < 0) throw TransportError("socket() failed");
  int flags = ::fcntl(fd, F_GETFL, 0);
  ::fcntl(fd, F_SETFL, flags | O_NONBLOCK);
  int rc = ::connect(fd, res->ai_addr, res->ai_addrlen);
  if (rc != 0 && errno != EINPROGRESS) {
    ::close(fd);
    throw TransportError("connect failed: " + std::string(std::strerror(errno)));
  }
  if (rc != 0) {
    pollfd p{fd, POLLOUT, 0};
    int pr = ::poll(&p, 1, timeout_ms_);
    int err = 0;
    socklen_t len = sizeof err;
    ::getsockopt(fd, SOL_SOCKET, SO_ERROR, &err, &len);
    if (pr <= 0 || err != 0) {
      ::close(fd);
      throw TransportError(pr <= 0 ? "connect timeout" : "connect failed: " + std::string(std::strerror(err)));
    }
  }
  ::fcntl(fd, F_SETFL, flags);
  timeval tv{timeout_ms_ / 1000, (timeout_ms_ % 1000) * 1000};
  ::setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
  ::setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof tv);
  return fd;
}

HttpResponse HttpClient::request(const std::string& method, const std::string& path,
                                 const std::map<std::string, std::string>& headers,
                                 const std::string& body) {
  std::string out;
  HttpResponse head = stream(method, path, headers, body, [&](const char* d, size_t n) {
    if (out.size() + n > kMaxJsonBodyBytes) throw TransportError("response body too large");
    out.append(d, n);
    return true;
  });
  if (head.body.empty()) head.body = std::move(out);
  return head;
}

HttpResponse HttpClient::stream(const std::string& method, const std::string& path,
                                const std::map<std::string, std::string>& headers,
                                const std::string& body,
                                const std::function<bool(const char*, size_t)>& on_chunk) {
  Socket s(connect_socket());
  send_all(s.fd(), build_request(url_, method, path, headers, body));
  HttpResponse resp;
  std::string first = read_head(s.fd(), resp);
  int64_t remaining = -1;
  if (auto it = resp.headers.find("content-length"); it != resp.headers.end())
    remaining = std::stoll(it->second);
  const bool success = resp.status >= 200 && resp.status < 300;
  auto deliver = [&](const char* d, size_t n) {
    if (remaining >= 0) n = static_cast<size_t>(std::min<int64_t>(remaining, static_cast<int64_t>(n)));
    if (!success) {
      if (resp.body.size() + n <= kMaxHeaderBytes) resp.body.append(d, n);
    } else if (n > 0 && !on_chunk(d, n)) {
      throw TransportError("transfer aborted by client");
    }
    if (remaining >= 0) remaining -= static_cast<int64_t>(n);
  };
  deliver(first.data(), first.size());
  char buf[kReadChunk];
  while (remaining != 0) {
    ssize_t n = recv_some(s.fd(), buf, sizeof buf);
    if (n == 0) {
      if (remaining > 0) throw TransportError("connection closed mid-body (truncated transfer)");
      break;
    }
    deliver(buf, static_cast<size_t>(n));
  }
  return resp;
}

HttpCloudLink::HttpCloudLink(const std::string& base_url, std::string vehicle_id,
                             std::string device_token, int timeout_ms)
    : http_(Url::parse(base_url), timeout_ms), vehicle_id_(std::move(vehicle_id)), token_(std::move(device_token)) {}

std::map<std::string, std::string> HttpCloudLink::auth_headers() const {
  return {{"Authorization", "Bearer " + token_}, {"X-Vehicle-Id", vehicle_id_}};
}

json::Value HttpCloudLink::json_call(const std::string& method, const std::string& path,
                                     const std::string& body) {
  auto hdrs = auth_headers();
  if (!body.empty()) hdrs["Content-Type"] = "application/json";
  HttpResponse r = http_.request(method, path, hdrs, body);
  if (r.status < 200 || r.status >= 300)
    throw TransportError(method + " " + path + " -> HTTP " + std::to_string(r.status));
  try {
    return json::parse(r.body);
  } catch (const json::ParseError& e) {
    throw TransportError(std::string("invalid JSON from backend: ") + e.what());
  }
}

std::vector<Command> HttpCloudLink::heartbeat(const json::Value& body) {
  json::Value r = json_call("POST", "/api/v1/device/heartbeat", body.dump());
  std::vector<Command> cmds;
  for (const auto& c : r.at("commands").as_array()) {
    try {
      cmds.push_back(Command::from_json(c));
    } catch (const std::exception&) {
      // Malformed command objects are dropped; they cannot be acted on safely.
    }
  }
  return cmds;
}

json::Value HttpCloudLink::fetch_manifest(const std::string& firmware_id) {
  if (!is_safe_identifier(firmware_id)) throw TransportError("unsafe firmware id");
  return json_call("GET", "/api/v1/device/firmware/" + firmware_id + "/manifest", "");
}

void HttpCloudLink::download(const std::string& firmware_id, const std::string& dest, int64_t offset,
                             int64_t max_total, const std::function<bool(int64_t)>& on_progress) {
  if (!is_safe_identifier(firmware_id)) throw TransportError("unsafe firmware id");
  auto hdrs = auth_headers();
  if (offset > 0) hdrs["Range"] = "bytes=" + std::to_string(offset) + "-";
  int fd = -1;
  int64_t total = offset;
  bool opened = false;
  auto open_dest = [&](bool truncate) {
    fd = ::open(dest.c_str(), O_WRONLY | O_CREAT | O_CLOEXEC | (truncate ? O_TRUNC : O_APPEND), 0600);
    if (fd < 0) throw TransportError("cannot open download file");
    opened = true;
  };
  HttpResponse head;
  try {
    head = http_.stream("GET", "/api/v1/device/firmware/" + firmware_id + "/image", hdrs, "",
                        [&](const char* d, size_t n) {
                          if (!opened) open_dest(false);
                          if (total + static_cast<int64_t>(n) > max_total)
                            throw TransportError("image larger than manifest size");
                          if (::write(fd, d, n) != static_cast<ssize_t>(n))
                            throw TransportError("write to download file failed");
                          total += static_cast<int64_t>(n);
                          return on_progress(total);
                        });
  } catch (...) {
    if (fd >= 0) {
      ::fsync(fd);
      ::close(fd);
    }
    throw;
  }
  if (fd >= 0) {
    ::fsync(fd);
    ::close(fd);
  }
  if (offset > 0 && head.status == 200) {
    // Server ignored Range: bytes were appended after a partial file; discard.
    ::unlink(dest.c_str());
    throw TransportError("server did not honour Range; restarting download");
  }
  if (head.status != 200 && head.status != 206)
    throw TransportError("image download -> HTTP " + std::to_string(head.status));
  if (total != max_total) throw TransportError("incomplete image transfer");
}

void HttpCloudLink::post_events(const std::vector<std::string>& events) {
  std::string body = "{\"events\":[";
  for (size_t i = 0; i < events.size(); ++i) body += (i ? "," : "") + events[i];
  body += "]}";
  json_call("POST", "/api/v1/device/events", body);
}

}  // namespace autolink
