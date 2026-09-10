use super::*;

fn translation() -> Value {
    json!({"text":"你好","target_language":"en","source_language":"auto","style":"standard","domain":"general","task_mode":"auto"})
}

#[test]
fn accepts_only_explicit_origins() {
    for input in ["https://translate.example", "https://translate.example:8443/", "http://localhost:8765", "http://127.0.0.1:8765/"] {
        assert!(validate_origin(input).is_ok());
    }
}

#[test]
fn rejects_credentials_and_non_origins() {
    let credential = ["https://", "user", ":", "example", "@translate.example"].concat();
    for input in [credential.as_str(), "https://translate.example/api/v1", "https://translate.example/a/..", "https://translate.example//", "https://translate.example?x=1", "https://translate.example#x", "https://translate.example/%2e", "https://translate.example\\x", " https://translate.example", "https://translate.example\n"] {
        assert_eq!(validate_origin(input).unwrap_err().code, "INVALID_ORIGIN");
    }
}

#[test]
fn rejects_remote_http_and_loopback_aliases() {
    for input in ["http://192.168.1.2:8765", "http://example.test:8765", "http://127.1:8765", "http://2130706433:8765", "http://localhost", "http://127.0.0.1:80", "http://localhost:0", "http://localhost:65536", "http://[::1]:8765", "file:///etc/passwd", "ftp://example.test/"] {
        assert!(validate_origin(input).is_err());
    }
}

#[test]
fn canonicalizes_https_default_port() {
    assert_eq!(validate_origin("https://translate.example:443/").unwrap().as_str(), "https://translate.example/");
}

#[test]
fn only_bundled_pages_may_navigate() {
    for input in ["tauri://localhost/index.html?view=pet", "http://tauri.localhost/index.html"] {
        assert!(local_navigation_allowed(&Url::parse(input).unwrap()));
    }
    for input in ["https://example.test", "http://localhost:8765/", "http://tauri.localhost:8765/", "file:///tmp/page.html", "javascript:alert(1)"] {
        assert!(!local_navigation_allowed(&Url::parse(input).unwrap()));
    }
}

#[test]
fn rejects_arbitrary_operations_methods_paths_and_headers() {
    for value in [json!({"operation":"fetch","url":"https://example.test"}), json!({"operation":"health","path":"/admin"}), json!({"operation":"health","method":"DELETE"}), json!({"operation":"auth","headers":{}}), json!({"operation":"shell","command":"echo"})] {
        assert!(serde_json::from_value::<ApiRequest>(value).is_err());
    }
}

#[test]
fn rejects_path_injection_in_job_and_session_ids() {
    for value in [json!({"operation":"job","job_id":"../../admin"}), json!({"operation":"delete_session","session_id":"x?y=z"})] {
        assert!(serde_json::from_value::<ApiRequest>(value).is_err());
    }
}

#[test]
fn pairing_forces_bearer_and_never_sends_authorization() {
    let request = ApiRequest::Pair { code: "A".repeat(12), device_name: "译境桌面".into() };
    let plan = request.plan().unwrap();
    assert_eq!(plan.method, Method::POST);
    assert_eq!(plan.path, "/api/v1/pair/exchange");
    assert!(!plan.auth);
    assert_eq!(plan.body.unwrap()["auth_mode"], "bearer");
    assert!(serde_json::from_value::<ApiRequest>(json!({"operation":"pair","code":"A".repeat(12),"device_name":"pet","auth_mode":"cookie"})).is_err());
}

#[test]
fn rejects_bad_pairing_inputs() {
    for code in ["A".repeat(11), "0".repeat(12), "A".repeat(13), "\n".repeat(12)] {
        assert!(ApiRequest::Pair { code, device_name: "pet".into() }.plan().is_err());
    }
    for name in [String::new(), " ".into(), "a".repeat(65), "a\nb".into()] {
        assert!(ApiRequest::Pair { code: "A".repeat(12), device_name: name }.plan().is_err());
    }
}

#[test]
fn all_protected_operations_require_token() {
    let id = Uuid::nil();
    for request in [ApiRequest::Auth, ApiRequest::Logout, ApiRequest::Capabilities, ApiRequest::CreateSession, ApiRequest::DeleteSession { session_id: id }, ApiRequest::Job { job_id: id }, ApiRequest::Cancel { job_id: id }, ApiRequest::Glossary] {
        assert!(request.plan().unwrap().auth);
    }
    assert!(!ApiRequest::Health.plan().unwrap().auth);
}

#[test]
fn translation_is_typed_bounded_and_forwarded_without_execution() {
    let input: TranslationInput = serde_json::from_value(translation()).unwrap();
    input.validate().unwrap();
    let request = ApiRequest::Translate { session_id: Uuid::nil(), client_request_id: Uuid::nil(), request: input };
    let plan = request.plan().unwrap();
    assert_eq!(plan.path, "/api/v1/translations");
    assert_eq!(plan.body.unwrap()["request"]["text"], "你好");
    for (key, value) in [("text", "a".repeat(4001)), ("text", "  ".into()), ("target_language", "unknown".into()), ("source_language", "unknown".into()), ("style", "execute".into()), ("domain", "shell".into()), ("task_mode", "command".into())] {
        let mut body = translation();
        body[key] = Value::String(value);
        assert!(serde_json::from_value::<TranslationInput>(body).unwrap().validate().is_err());
    }
}

#[test]
fn counts_unicode_characters_not_bytes() {
    let mut body = translation();
    body["text"] = Value::String("译".repeat(4000));
    assert!(serde_json::from_value::<TranslationInput>(body).unwrap().validate().is_ok());
}

#[test]
fn reconfigure_clears_token_and_invalidates_inflight_requests() {
    let bridge = Bridge::new().unwrap();
    bridge.configure("https://one.example", false).unwrap();
    bridge.lock().unwrap().token = Some(Zeroizing::new("x".repeat(43)));
    let old = bridge.status(false).unwrap();
    assert!(old.paired);
    let new = bridge.configure("https://two.example", false).unwrap();
    assert!(!new.paired);
    assert_eq!(bridge.lock().unwrap().check_generation(old.generation).unwrap_err().code, "STALE_OPERATION");
}

#[test]
fn same_origin_reconfigure_also_restarts_pairing() {
    let bridge = Bridge::new().unwrap();
    let old = bridge.configure("https://one.example", true).unwrap();
    bridge.lock().unwrap().token = Some(Zeroizing::new("x".repeat(43)));
    let new = bridge.configure("https://one.example", true).unwrap();
    assert!(!new.paired);
    assert_ne!(old.generation, new.generation);
    assert!(new.shortcut_available);
}

#[test]
fn invalid_configuration_does_not_mutate_previous_connection() {
    let bridge = Bridge::new().unwrap();
    let old = bridge.configure("https://one.example", false).unwrap();
    assert!(bridge.configure("http://remote.example", false).is_err());
    assert_eq!(bridge.status(false).unwrap().generation, old.generation);
}

#[test]
fn clear_leaves_origin_but_no_token() {
    let bridge = Bridge::new().unwrap();
    bridge.configure("http://127.0.0.1:8765", false).unwrap();
    bridge.lock().unwrap().token = Some(Zeroizing::new("x".repeat(43)));
    bridge.clear();
    assert!(!bridge.status(false).unwrap().paired);
    assert!(bridge.status(false).unwrap().origin.is_some());
}

#[test]
fn logout_failure_keeps_only_revocation_capability() {
    let mut state = SessionState::default();
    state.token = Some(Zeroizing::new("x".repeat(43)));
    let first = state.begin_logout().unwrap();
    assert!(state.token.is_none());
    assert!(!state.status(false).paired);
    let old_generation = state.generation;
    let retry = state.begin_logout().unwrap();
    assert_eq!(first.as_str(), retry.as_str());
    assert_ne!(old_generation, state.generation);
    assert!(state.pending_logout.is_some());
}

#[test]
fn reconfiguration_discards_pending_revocation_without_reusing_it() {
    let mut state = SessionState::default();
    state.token = Some(Zeroizing::new("x".repeat(43)));
    state.begin_logout();
    state.reset();
    assert!(state.pending_logout.is_none());
    assert!(state.begin_logout().is_none());
}

fn pairing_reply() -> Value {
    json!({"device_id":"example-device","device_name":"pet","expires_at":"2099-01-01T00:00:00Z","auth_mode":"bearer","csrf_token":null,"token_type":"Bearer","access_token":"x".repeat(43)})
}

#[test]
fn pairing_token_never_leaves_native_state() {
    let mut body = pairing_reply();
    body["extra"] = json!({"private":"anything"});
    let (token, public) = extract_pairing(&mut body).unwrap();
    assert_eq!(token.len(), 43);
    assert!(public.get("access_token").is_none());
    assert!(public.get("token_type").is_none());
    assert!(public.get("extra").is_none());
    assert!(body.get("access_token").is_none());
}

#[test]
fn rejects_cookie_and_malformed_pairing_responses() {
    for (key, value) in [("auth_mode", json!("cookie")), ("csrf_token", json!("not-null")), ("access_token", json!("short")), ("token_type", json!("Other")), ("device_name", Value::Null)] {
        let mut body = pairing_reply();
        body[key] = value;
        assert!(extract_pairing(&mut body).is_err());
    }
}

#[test]
fn public_status_contains_no_authentication_secret() {
    let mut state = SessionState::default();
    state.token = Some(Zeroizing::new("x".repeat(43)));
    let value = serde_json::to_value(state.status(false)).unwrap();
    assert_eq!(value.as_object().unwrap().len(), 4);
    assert_eq!(value["paired"], true);
    assert!(value.get("token").is_none());
}

#[test]
fn http_errors_are_fixed_and_redirects_are_rejected() {
    for status in [301, 302, 307, 308] { assert_eq!(BridgeError::http(status).code, "REDIRECT_BLOCKED"); }
    assert_eq!(BridgeError::http(401).code, "PAIRING_REQUIRED");
    assert!(!BridgeError::http(403).retryable);
    assert!(BridgeError::http(429).retryable);
    assert!(BridgeError::http(503).retryable);
}

// 仅本机合成 HTTP，不连接 Ollama，不持有真实配对码，也不写入用户内容。
fn serve(responses: Vec<Vec<u8>>) -> (String, std::thread::JoinHandle<Vec<String>>) {
    serve_with_delay(responses.into_iter().map(|response| (Duration::ZERO, response)).collect())
}

fn serve_with_delay(responses: Vec<(Duration, Vec<u8>)>) -> (String, std::thread::JoinHandle<Vec<String>>) {
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::time::Instant;
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let origin = format!("http://127.0.0.1:{}", listener.local_addr().unwrap().port());
    listener.set_nonblocking(true).unwrap();
    let handle = std::thread::spawn(move || {
        let mut requests = Vec::new();
        for (delay, response) in responses {
            let started = Instant::now();
            let mut stream = loop {
                match listener.accept() {
                    Ok((stream, _)) => break stream,
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        assert!(started.elapsed() < Duration::from_secs(5), "mock request deadline");
                        std::thread::sleep(Duration::from_millis(5));
                    }
                    Err(_) => panic!("mock accept failed"),
                }
            };
            stream.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
            let mut bytes = Vec::new();
            loop {
                let mut chunk = [0_u8; 4096];
                let count = stream.read(&mut chunk).unwrap();
                assert!(count > 0);
                bytes.extend_from_slice(&chunk[..count]);
                assert!(bytes.len() <= MAX_REQUEST_BYTES + 4096);
                if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                    let headers = String::from_utf8_lossy(&bytes[..end]).to_lowercase();
                    let length = headers.lines().find_map(|line| line.strip_prefix("content-length:"))
                        .map(|v| v.trim().parse::<usize>().unwrap()).unwrap_or(0);
                    if bytes.len() >= end + 4 + length { break; }
                }
            }
            requests.push(String::from_utf8(bytes).unwrap());
            if !delay.is_zero() { std::thread::sleep(delay); }
            let written = stream.write_all(&response);
            // 超时用例的客户端可能已经关闭套接字，这是预期结果而不是 mock 失败。
            if delay.is_zero() { written.unwrap(); }
        }
        requests
    });
    (origin, handle)
}

fn json_response(status: u16, body: Value, extra_headers: &str) -> Vec<u8> {
    let body = body.to_string();
    format!("HTTP/1.1 {status} Result\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n{extra_headers}\r\n{body}", body.len()).into_bytes()
}

#[test]
fn interrupted_202_body_preserves_unconfirmed_task_semantics() {
    let (origin, server) = serve(vec![b"HTTP/1.1 202 Accepted\r\nContent-Type: application/json\r\nContent-Length: 100\r\nConnection: close\r\n\r\n{\"job_id\":".to_vec()]);
    let bridge = Bridge::new().unwrap();
    bridge.configure(&origin, false).unwrap();
    bridge.lock().unwrap().token = Some(Zeroizing::new("x".repeat(43)));
    let request = ApiRequest::Translate {
        session_id: Uuid::nil(), client_request_id: Uuid::nil(),
        request: serde_json::from_value(translation()).unwrap(),
    };
    let error = tauri::async_runtime::block_on(bridge.request(request)).err().unwrap();
    assert_eq!(error.code, "NETWORK_UNCONFIRMED");
    assert!(error.retryable);
    assert_eq!(server.join().unwrap().len(), 1);
}

#[test]
fn interrupted_chunked_body_is_a_network_failure_not_invalid_json() {
    let (origin, server) = serve(vec![b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n20\r\n{\"status\":".to_vec()]);
    let bridge = Bridge::new().unwrap();
    bridge.configure(&origin, false).unwrap();
    let error = tauri::async_runtime::block_on(bridge.request(ApiRequest::Health)).err().unwrap();
    assert_eq!(error.code, "NETWORK_UNCONFIRMED");
    assert_eq!(server.join().unwrap().len(), 1);
}

#[test]
fn complete_malformed_body_is_distinct_from_interrupted_transport() {
    let (origin, server) = serve(vec![b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 3\r\nConnection: close\r\n\r\n???".to_vec()]);
    let bridge = Bridge::new().unwrap();
    bridge.configure(&origin, false).unwrap();
    let error = tauri::async_runtime::block_on(bridge.request(ApiRequest::Health)).err().unwrap();
    assert_eq!(error.code, "INVALID_RESPONSE");
    assert_eq!(server.join().unwrap().len(), 1);
}

#[test]
fn http_redirect_is_not_followed() {
    let (origin, server) = serve(vec![b"HTTP/1.1 307 Temporary Redirect\r\nLocation: http://127.0.0.1:9/forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".to_vec()]);
    let bridge = Bridge::new().unwrap();
    bridge.configure(&origin, false).unwrap();
    let error = tauri::async_runtime::block_on(bridge.request(ApiRequest::Health)).err().unwrap();
    assert_eq!(error.code, "REDIRECT_BLOCKED");
    assert_eq!(server.join().unwrap().len(), 1);
}

#[test]
fn pairing_uses_native_bearer_without_cookies_or_frontend_token() {
    let auth = public_auth(&pairing_reply()).unwrap();
    let (origin, server) = serve(vec![
        json_response(201, pairing_reply(), "Set-Cookie: example-session=synthetic; Path=/\r\n"),
        json_response(200, auth, ""),
    ]);
    let bridge = Bridge::new().unwrap();
    bridge.configure(&origin, false).unwrap();
    let reply = tauri::async_runtime::block_on(bridge.request(ApiRequest::Pair {
        code: "A".repeat(12), device_name: "pet".into(),
    })).unwrap();
    assert!(reply.body.get("access_token").is_none());
    tauri::async_runtime::block_on(bridge.request(ApiRequest::Auth)).unwrap();
    let requests = server.join().unwrap();
    assert!(!requests[0].to_lowercase().contains("authorization:"));
    let headers = requests[1].to_lowercase();
    assert!(headers.contains("authorization: bearer "));
    assert!(!headers.contains("cookie:"));
}

#[test]
fn logout_can_retry_revocation_but_cannot_translate_after_failure() {
    let (origin, server) = serve(vec![json_response(503, json!({}), ""), b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n".to_vec()]);
    let bridge = Bridge::new().unwrap();
    bridge.configure(&origin, false).unwrap();
    bridge.lock().unwrap().token = Some(Zeroizing::new("x".repeat(43)));
    assert_eq!(tauri::async_runtime::block_on(bridge.request(ApiRequest::Logout)).err().unwrap().code, "SERVICE_UNAVAILABLE");
    assert!(!bridge.status(false).unwrap().paired);
    assert_eq!(tauri::async_runtime::block_on(bridge.request(ApiRequest::CreateSession)).err().unwrap().code, "PAIRING_REQUIRED");
    assert_eq!(tauri::async_runtime::block_on(bridge.request(ApiRequest::Logout)).unwrap().status, 204);
    assert!(bridge.lock().unwrap().pending_logout.is_none());
    assert_eq!(server.join().unwrap().len(), 2);
}

#[test]
fn logout_wrong_success_status_is_not_a_confirmed_revocation() {
    let (origin, server) = serve(vec![json_response(200, json!({}), ""), b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".to_vec()]);
    let bridge = Bridge::new().unwrap();
    bridge.configure(&origin, false).unwrap();
    bridge.lock().unwrap().token = Some(Zeroizing::new("x".repeat(43)));
    assert_eq!(tauri::async_runtime::block_on(bridge.request(ApiRequest::Logout)).err().unwrap().code, "INVALID_RESPONSE");
    assert!(!bridge.status(false).unwrap().paired);
    assert!(bridge.lock().unwrap().pending_logout.is_some());
    // 401 证明原凭据已不可用，可以完成本地撤销并丢弃仅用于重试的副本。
    assert_eq!(tauri::async_runtime::block_on(bridge.request(ApiRequest::Logout)).unwrap().status, 204);
    assert!(bridge.lock().unwrap().pending_logout.is_none());
    assert_eq!(server.join().unwrap().len(), 2);
}

#[test]
fn logout_disconnected_response_does_not_fabricate_success() {
    let (origin, server) = serve(vec![Vec::new(), b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n".to_vec()]);
    let bridge = Bridge::new().unwrap();
    bridge.configure(&origin, false).unwrap();
    bridge.lock().unwrap().token = Some(Zeroizing::new("x".repeat(43)));
    assert_eq!(tauri::async_runtime::block_on(bridge.request(ApiRequest::Logout)).err().unwrap().code, "NETWORK_UNCONFIRMED");
    assert!(bridge.lock().unwrap().pending_logout.is_some());
    assert_eq!(tauri::async_runtime::block_on(bridge.request(ApiRequest::Auth)).err().unwrap().code, "PAIRING_REQUIRED");
    assert_eq!(tauri::async_runtime::block_on(bridge.request(ApiRequest::Logout)).unwrap().status, 204);
    assert!(bridge.lock().unwrap().pending_logout.is_none());
    assert_eq!(server.join().unwrap().len(), 2);
}

#[test]
fn logout_has_a_short_deadline_and_retains_only_retry_capability() {
    let (origin, server) = serve_with_delay(vec![(
        Duration::from_secs(4),
        b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n".to_vec(),
    )]);
    let bridge = Bridge::new().unwrap();
    bridge.configure(&origin, false).unwrap();
    bridge.lock().unwrap().token = Some(Zeroizing::new("x".repeat(43)));
    let started = std::time::Instant::now();
    let error = tauri::async_runtime::block_on(bridge.request(ApiRequest::Logout)).err().unwrap();
    assert_eq!(error.code, "NETWORK_UNCONFIRMED");
    // 保留调度余量，但不能退回普通请求的 15 秒期限。
    assert!(started.elapsed() < Duration::from_secs(5));
    assert!(!bridge.status(false).unwrap().paired);
    assert!(bridge.lock().unwrap().pending_logout.is_some());
    bridge.clear();
    assert!(bridge.lock().unwrap().pending_logout.is_none());
    assert_eq!(server.join().unwrap().len(), 1);
}
