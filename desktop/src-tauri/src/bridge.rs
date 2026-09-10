//! 原生安全边界：固定操作、内存 Bearer、禁止重定向/代理/Cookie。
use reqwest::{header, redirect, Client, Method};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{sync::{Mutex, MutexGuard}, time::Duration};
use url::Url;
use uuid::Uuid;
use zeroize::Zeroizing;

const MAX_RESPONSE_BYTES: usize = 2 * 1024 * 1024;
const MAX_REQUEST_BYTES: usize = 32 * 1024;

#[derive(Debug, Serialize)]
pub struct BridgeError {
    pub code: &'static str,
    pub message: &'static str,
    pub retryable: bool,
    pub status: u16,
}

impl BridgeError {
    pub fn invalid() -> Self { Self::new("INVALID_REQUEST", "请求参数不符合桌面安全约束。", false, 0) }
    pub fn forbidden() -> Self { Self::new("FORBIDDEN", "当前窗口无权调用此操作。", false, 0) }
    fn new(code: &'static str, message: &'static str, retryable: bool, status: u16) -> Self {
        Self { code, message, retryable, status }
    }
    fn invalid_response() -> Self { Self::new("INVALID_RESPONSE", "服务返回了无法识别的数据。", false, 0) }
    fn internal() -> Self { Self::new("HOST_UNAVAILABLE", "桌面连接状态不可用，请重新启动。", false, 0) }
    fn stale() -> Self { Self::new("STALE_OPERATION", "连接已重置，旧请求结果已丢弃。", false, 0) }
    fn unpaired() -> Self { Self::new("PAIRING_REQUIRED", "请先使用电脑端配对码连接。", false, 401) }
    fn network() -> Self { Self::new("NETWORK_UNCONFIRMED", "连接未完成；请求可能已送达，请先查询或停止任务。", true, 0) }
    fn http(status: u16) -> Self {
        match status {
            300..=399 => Self::new("REDIRECT_BLOCKED", "服务发生跳转，请核对地址后重新配对。", false, status),
            401 => Self::unpaired(),
            403 => Self::new("ACCESS_DENIED", "服务拒绝访问，请核对配对状态。", false, status),
            404 => Self::new("NOT_FOUND", "会话或任务不存在，可能已过期。", false, status),
            409 => Self::new("CONFLICT", "请求与当前状态冲突，请刷新状态。", false, status),
            413 => Self::new("REQUEST_TOO_LARGE", "请求超过服务大小限制。", false, status),
            429 => Self::new("RATE_LIMITED", "服务繁忙，请稍后重试。", true, status),
            500..=599 => Self::new("SERVICE_UNAVAILABLE", "电脑服务暂时不可用，请稍后重试。", true, status),
            _ => Self::new("REQUEST_REJECTED", "服务拒绝了此请求，请检查输入。", false, status),
        }
    }
}

#[derive(Serialize)]
pub struct BackendStatus {
    pub origin: Option<String>,
    pub paired: bool,
    pub generation: u64,
    pub shortcut_available: bool,
}

#[derive(Serialize)]
pub struct ApiResponse { pub status: u16, pub body: Value }

#[derive(Deserialize)]
#[serde(tag = "operation", rename_all = "snake_case", deny_unknown_fields)]
pub enum ApiRequest {
    Health,
    Pair { code: String, device_name: String },
    Auth,
    Logout,
    Capabilities,
    CreateSession,
    DeleteSession { session_id: Uuid },
    Translate { session_id: Uuid, client_request_id: Uuid, request: TranslationInput },
    Job { job_id: Uuid },
    Cancel { job_id: Uuid },
    Glossary,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TranslationInput {
    text: String,
    target_language: String,
    source_language: String,
    style: String,
    domain: String,
    task_mode: String,
}

impl TranslationInput {
    fn validate(&self) -> Result<(), BridgeError> {
        let languages = ["zh-Hans", "zh-Hant", "en", "ja", "ko", "fr", "de", "es", "ru", "pt-BR", "ar", "it"];
        if self.text.trim().is_empty() || self.text.chars().count() > 4000
            || !languages.contains(&self.target_language.as_str())
            || !(self.source_language == "auto" || languages.contains(&self.source_language.as_str()))
            || !["standard", "formal", "colloquial"].contains(&self.style.as_str())
            || !["general", "technology", "business", "finance", "legal", "medical", "academic"].contains(&self.domain.as_str())
            || !["auto", "translate", "annotate_code", "annotate_special"].contains(&self.task_mode.as_str())
        { return Err(BridgeError::invalid()); }
        Ok(())
    }
}

struct RequestPlan { method: Method, path: String, body: Option<Value>, auth: bool }

impl ApiRequest {
    fn plan(&self) -> Result<RequestPlan, BridgeError> {
        let (method, suffix, body, auth) = match self {
            Self::Health => (Method::GET, "health".into(), None, false),
            Self::Pair { code, device_name } => {
                if code.len() != 12 || !code.bytes().all(|b| b.is_ascii_alphabetic() || (b'2'..=b'7').contains(&b))
                    || device_name.trim().is_empty() || device_name.chars().count() > 64
                    || device_name.chars().any(char::is_control)
                { return Err(BridgeError::invalid()); }
                (Method::POST, "pair/exchange".into(), Some(json!({
                    "code": code, "device_name": device_name, "auth_mode": "bearer"
                })), false)
            }
            Self::Auth => (Method::GET, "auth/session".into(), None, true),
            Self::Logout => (Method::DELETE, "auth/session".into(), None, true),
            Self::Capabilities => (Method::GET, "capabilities".into(), None, true),
            Self::CreateSession => (Method::POST, "sessions".into(), Some(json!({})), true),
            Self::DeleteSession { session_id } => (Method::DELETE, format!("sessions/{session_id}"), None, true),
            Self::Translate { session_id, client_request_id, request } => {
                request.validate()?;
                (Method::POST, "translations".into(), Some(json!({
                    "session_id": session_id, "client_request_id": client_request_id, "request": request
                })), true)
            }
            Self::Job { job_id } => (Method::GET, format!("translations/{job_id}"), None, true),
            Self::Cancel { job_id } => (Method::POST, format!("translations/{job_id}/cancel"), Some(json!({})), true),
            Self::Glossary => (Method::GET, "glossary".into(), None, true),
        };
        Ok(RequestPlan { method, path: format!("/api/v1/{suffix}"), body, auth })
    }
}

pub fn validate_origin(raw: &str) -> Result<Url, BridgeError> {
    let invalid = || BridgeError::new("INVALID_ORIGIN", "仅支持 HTTPS 源地址，或带端口的本机 HTTP 地址；请勿包含路径或凭据。", false, 0);
    if raw.is_empty() || raw.len() > 1024 || raw.chars().any(|c| c.is_whitespace() || c.is_control())
        || raw.contains(['\\', '%', '@', '?', '#'])
    { return Err(invalid()); }
    let authority = raw.split_once("://").ok_or_else(invalid)?.1;
    if authority.split_once('/').is_some_and(|(_, tail)| !tail.is_empty()) {
        return Err(invalid());
    }
    let parsed = Url::parse(raw).map_err(|_| invalid())?;
    if parsed.host_str().is_none() || !parsed.username().is_empty() || parsed.password().is_some()
        || parsed.path() != "/" || parsed.query().is_some() || parsed.fragment().is_some()
    { return Err(invalid()); }
    match parsed.scheme() {
        "https" if raw.starts_with("https://") => {}
        "http" => {
            // 检查原始主机，拒绝 URL 库将 127.1/十进制地址规范化成回环地址。
            let authority = raw.strip_prefix("http://").ok_or_else(invalid)?.trim_end_matches('/');
            let (host, port) = authority.rsplit_once(':').ok_or_else(invalid)?;
            if !["127.0.0.1", "localhost"].contains(&host)
                || port.parse::<u16>().ok().filter(|p| *p >= 1024).is_none()
            { return Err(invalid()); }
        }
        _ => return Err(invalid()),
    }
    Url::parse(&parsed.origin().ascii_serialization()).map_err(|_| invalid())
}

pub fn local_navigation_allowed(url: &Url) -> bool {
    matches!(url.scheme(), "tauri" | "http" | "https")
        && matches!(url.host_str(), Some("tauri.localhost") | Some("localhost"))
        && (url.scheme() == "tauri" || url.host_str() == Some("tauri.localhost"))
        && url.port().is_none()
        && url.username().is_empty() && url.password().is_none()
}

#[derive(Default)]
struct SessionState {
    origin: Option<Url>,
    token: Option<Zeroizing<String>>,
    pending_logout: Option<Zeroizing<String>>,
    generation: u64,
}

impl SessionState {
    fn reset(&mut self) {
        self.token = None;
        self.pending_logout = None;
        self.generation = self.generation.wrapping_add(1);
    }
    fn begin_logout(&mut self) -> Option<Zeroizing<String>> {
        let token = self.token.take().or_else(|| self.pending_logout.take());
        self.generation = self.generation.wrapping_add(1);
        // 网络失败后只允许重试撤销，不允许继续用此令牌翻译。
        self.pending_logout = token.clone();
        token
    }
    fn check_generation(&self, generation: u64) -> Result<(), BridgeError> {
        if self.generation == generation { Ok(()) } else { Err(BridgeError::stale()) }
    }
    fn status(&self, shortcut_available: bool) -> BackendStatus {
        BackendStatus {
            origin: self.origin.as_ref().map(|u| u.origin().ascii_serialization()),
            paired: self.token.is_some(), generation: self.generation, shortcut_available,
        }
    }
}

pub struct Bridge { client: Client, state: Mutex<SessionState> }

impl Bridge {
    pub fn new() -> Result<Self, BridgeError> {
        let client = Client::builder()
            .no_proxy()
            .redirect(redirect::Policy::none())
            .retry(reqwest::retry::never())
            .connect_timeout(Duration::from_secs(5))
            .timeout(Duration::from_secs(15))
            .build().map_err(|_| BridgeError::internal())?;
        Ok(Self { client, state: Mutex::new(SessionState::default()) })
    }
    fn lock(&self) -> Result<MutexGuard<'_, SessionState>, BridgeError> {
        self.state.lock().map_err(|_| BridgeError::internal())
    }
    pub fn configure(&self, origin: &str, shortcut_available: bool) -> Result<BackendStatus, BridgeError> {
        let origin = validate_origin(origin)?;
        let mut state = self.lock()?;
        state.reset();
        state.origin = Some(origin);
        Ok(state.status(shortcut_available))
    }
    pub fn status(&self, shortcut_available: bool) -> Result<BackendStatus, BridgeError> {
        Ok(self.lock()?.status(shortcut_available))
    }
    pub fn clear(&self) {
        if let Ok(mut state) = self.state.lock() { state.reset(); }
    }

    pub async fn request(&self, request: ApiRequest) -> Result<ApiResponse, BridgeError> {
        let plan = request.plan()?;
        let pairing = matches!(&request, ApiRequest::Pair { .. });
        let logout = matches!(&request, ApiRequest::Logout);
        let (origin, token, generation) = {
            let mut state = self.lock()?;
            let origin = state.origin.clone().ok_or_else(|| BridgeError::new(
                "BACKEND_NOT_CONFIGURED", "请先明确配置电脑服务地址。", false, 0
            ))?;
            // 每次重新配对使更早的请求失效，不让迟到的配对结果恢复旧凭据。
            if pairing { state.reset(); }
            let token = if logout { state.begin_logout() } else { state.token.clone() };
            if plan.auth && token.is_none() {
                if logout { return Ok(ApiResponse { status: 204, body: Value::Null }); }
                return Err(BridgeError::unpaired());
            }
            (origin, token, state.generation)
        };
        let endpoint = origin.join(&plan.path).map_err(|_| BridgeError::internal())?;
        let mut outgoing = self.client.request(plan.method, endpoint).header(header::ACCEPT, "application/json");
        if logout { outgoing = outgoing.timeout(Duration::from_secs(3)); }
        if plan.auth {
            let token = token.as_ref().ok_or_else(BridgeError::unpaired)?;
            let value = Zeroizing::new(format!("Bearer {}", token.as_str()));
            let mut authorization = header::HeaderValue::from_str(&value).map_err(|_| BridgeError::invalid_response())?;
            authorization.set_sensitive(true);
            outgoing = outgoing.header(header::AUTHORIZATION, authorization);
        }
        if let Some(body) = plan.body {
            let bytes = serde_json::to_vec(&body).map_err(|_| BridgeError::invalid())?;
            if bytes.len() > MAX_REQUEST_BYTES { return Err(BridgeError::invalid()); }
            outgoing = outgoing.header(header::CONTENT_TYPE, "application/json").body(bytes);
        }
        let response = outgoing.send().await.map_err(|_| BridgeError::network())?;
        self.lock()?.check_generation(generation)?;
        let status = response.status().as_u16();
        if logout && (status == 204 || status == 401) {
            let mut state = self.lock()?;
            state.check_generation(generation)?;
            state.pending_logout = None;
            return Ok(ApiResponse { status: 204, body: Value::Null });
        }
        if !(200..=299).contains(&status) {
            if status == 401 && plan.auth && !logout {
                let mut state = self.lock()?;
                state.check_generation(generation)?;
                state.reset();
            }
            // 不向前端转发服务器错误正文，其中可能反射输入、地址或凭据。
            return Err(BridgeError::http(status));
        }
        if status == 204 {
            if matches!(&request, ApiRequest::DeleteSession { .. }) {
                return Ok(ApiResponse { status, body: Value::Null });
            }
            return Err(BridgeError::invalid_response());
        }
        if logout { return Err(BridgeError::invalid_response()); }
        let mut body = read_json(response).await?;
        let mut state = self.lock()?;
        state.check_generation(generation)?;
        if pairing {
            let (token, public) = extract_pairing(&mut body)?;
            state.token = Some(token);
            body = public;
        } else if matches!(&request, ApiRequest::Auth) {
            body = public_auth(&body)?;
        }
        Ok(ApiResponse { status, body })
    }
}

async fn read_json(mut response: reqwest::Response) -> Result<Value, BridgeError> {
    if response.content_length().is_some_and(|n| n > MAX_RESPONSE_BYTES as u64) {
        return Err(BridgeError::invalid_response());
    }
    let mut bytes = Zeroizing::new(Vec::new());
    // 接收响应头不代表收到任务 ID。流中断仍可能已经创建了远端任务，
    // 不能当作普通 JSON 校验失败，更不能让前端自动重发一次翻译。
    while let Some(chunk) = response.chunk().await.map_err(|_| BridgeError::network())? {
        if bytes.len().saturating_add(chunk.len()) > MAX_RESPONSE_BYTES {
            return Err(BridgeError::invalid_response());
        }
        bytes.extend_from_slice(&chunk);
    }
    serde_json::from_slice(&bytes).map_err(|_| BridgeError::invalid_response())
}

fn public_auth(value: &Value) -> Result<Value, BridgeError> {
    if value["auth_mode"] != "bearer" || !value["csrf_token"].is_null() {
        return Err(BridgeError::invalid_response());
    }
    let mut public = json!({"auth_mode": "bearer", "csrf_token": null});
    for key in ["device_id", "device_name", "expires_at"] {
        let text = value[key].as_str().filter(|s| !s.is_empty() && s.len() <= 256)
            .ok_or_else(BridgeError::invalid_response)?;
        public[key] = Value::String(text.to_owned());
    }
    Ok(public)
}

fn extract_pairing(value: &mut Value) -> Result<(Zeroizing<String>, Value), BridgeError> {
    let public = public_auth(value)?;
    if value["token_type"] != "Bearer" { return Err(BridgeError::invalid_response()); }
    let secret = value.as_object_mut().and_then(|o| o.remove("access_token"))
        .ok_or_else(BridgeError::invalid_response)?;
    let Value::String(secret) = secret else { return Err(BridgeError::invalid_response()); };
    let secret = Zeroizing::new(secret);
    if !(32..=512).contains(&secret.len()) || !secret.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-') {
        return Err(BridgeError::invalid_response());
    }
    Ok((secret, public))
}

#[cfg(test)]
mod tests;
