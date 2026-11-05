// Minimal HTTP/1.1 client over POSIX sockets and the CloudLink built on it.
// Plain HTTP only: in the local stack TLS is out of scope (see
// docs/security/threat-model.md, T-11). The CloudLink interface isolates this
// so a libcurl/TLS transport can replace it without touching OTA logic.
#pragma once

#include <functional>
#include <map>
#include <string>

#include "autolink/ota_agent.hpp"

namespace autolink {

struct HttpResponse {
  int status = 0;
  std::map<std::string, std::string> headers;  // lower-cased names
  std::string body;
};

struct Url {
  std::string host;
  int port = 80;
  std::string base_path;
  static Url parse(const std::string& url);  // http://host[:port][/base]
};

class HttpClient {
 public:
  explicit HttpClient(Url url, int timeout_ms = 3000) : url_(std::move(url)), timeout_ms_(timeout_ms) {}
  HttpResponse request(const std::string& method, const std::string& path,
                       const std::map<std::string, std::string>& headers, const std::string& body);
  // Streams a 2xx response body to `on_chunk`; non-2xx bodies are captured
  // (bounded) in HttpResponse::body instead and never passed to on_chunk.
  HttpResponse stream(const std::string& method, const std::string& path,
                      const std::map<std::string, std::string>& headers, const std::string& body,
                      const std::function<bool(const char*, size_t)>& on_chunk);

 private:
  int connect_socket();
  Url url_;
  int timeout_ms_;
};

class HttpCloudLink : public CloudLink {
 public:
  HttpCloudLink(const std::string& base_url, std::string vehicle_id, std::string device_token,
                int timeout_ms = 3000);
  std::vector<Command> heartbeat(const json::Value& body) override;
  json::Value fetch_manifest(const std::string& firmware_id) override;
  void download(const std::string& firmware_id, const std::string& dest, int64_t offset,
                int64_t max_total, const std::function<bool(int64_t)>& on_progress) override;
  void post_events(const std::vector<std::string>& events) override;

 private:
  std::map<std::string, std::string> auth_headers() const;
  json::Value json_call(const std::string& method, const std::string& path, const std::string& body);
  HttpClient http_;
  std::string vehicle_id_;
  std::string token_;
};

}  // namespace autolink
