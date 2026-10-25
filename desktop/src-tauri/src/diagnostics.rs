//! Private bounded helper diagnostics. Never pass snapshots to frontend commands or ordinary logs.
//! The native verifier may persist a sanitized snapshot only to its explicit private audit directory.
use std::collections::VecDeque;
use std::io::Read;
use std::sync::{Arc, Mutex};

const CAPACITY: usize = 32 * 1024;
const MAX_FAILURE: usize = 4096;

#[derive(Clone)]
pub struct PrivateDiagnostics(Arc<Mutex<Buffer>>);
struct Buffer {
    bytes: VecDeque<u8>,
    received: u64,
    reader_done: bool,
    reader_failed: bool,
    secrets: Vec<String>,
    exit_code: Option<i32>,
    failure: Option<String>,
}

/// Sanitized evidence only. Deliberately has no Debug implementation to discourage incidental logging.
pub struct DiagnosticSnapshot {
    pub stderr: String,
    pub bytes_received: u64,
    pub truncated: bool,
    pub reader_done: bool,
    pub reader_failed: bool,
    pub exit_code: Option<i32>,
    pub failure: Option<String>,
}

impl PrivateDiagnostics {
    pub fn new() -> Self {
        Self(Arc::new(Mutex::new(Buffer {
            bytes: VecDeque::with_capacity(CAPACITY), received: 0, reader_done: false,
            reader_failed: false, secrets: Vec::new(), exit_code: None, failure: None,
        })))
    }

    /// Start draining immediately after stderr is taken from the owned child.
    /// The reader thread never waits on the child and retains at most CAPACITY stderr bytes.
    pub fn capture<R: Read + Send + 'static>(&self, mut reader: R) {
        let shared = self.clone();
        std::thread::spawn(move || {
            let mut chunk = [0_u8; 4096];
            loop {
                match reader.read(&mut chunk) {
                    Ok(0) => break,
                    Ok(count) => {
                        let mut b = shared.0.lock().unwrap_or_else(|e| e.into_inner());
                        b.received = b.received.saturating_add(count as u64);
                        for byte in &chunk[..count] {
                            if b.bytes.len() == CAPACITY { b.bytes.pop_front(); }
                            b.bytes.push_back(*byte);
                        }
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
                    Err(_) => {
                        shared.0.lock().unwrap_or_else(|e| e.into_inner()).reader_failed = true;
                        break;
                    }
                }
            }
            shared.0.lock().unwrap_or_else(|e| e.into_inner()).reader_done = true;
        });
    }

    /// Register descriptor capability/nonce as soon as they are parsed. Raw stdout is never captured here.
    pub fn register_secret(&self, value: &str) {
        if value.is_empty() { return; }
        let mut b = self.0.lock().unwrap_or_else(|e| e.into_inner());
        // Descriptor fields are bounded by their parser. A hostile unbounded registration is refused
        // by discarding diagnostics instead of allowing the secret to escape in an audit snapshot.
        if value.len() > CAPACITY || b.secrets.len() >= 16 {
            b.bytes.clear(); b.failure = Some("민감정보 등록 한도를 초과하여 진단을 생략했습니다.".into());
            b.secrets.clear(); b.secrets.push(String::new());
        } else if !b.secrets.iter().any(|s| s == value) {
            b.secrets.push(value.to_owned());
        }
    }

    pub fn record_exit(&self, code: Option<i32>) {
        self.0.lock().unwrap_or_else(|e| e.into_inner()).exit_code = code;
    }

    pub fn record_failure(&self, reason: &str) {
        let mut end = reason.len().min(MAX_FAILURE);
        while !reason.is_char_boundary(end) { end -= 1; }
        self.0.lock().unwrap_or_else(|e| e.into_inner()).failure = Some(reason[..end].to_owned());
    }

    /// Failure paths may briefly wait for EOF to avoid racing the stderr reader. Never wait unboundedly.
    pub fn snapshot_after_drain(&self, timeout: std::time::Duration) -> DiagnosticSnapshot {
        let deadline = std::time::Instant::now() + timeout.min(std::time::Duration::from_secs(1));
        loop {
            let value = self.snapshot_for_audit();
            if value.reader_done || std::time::Instant::now() >= deadline { return value; }
            std::thread::sleep(std::time::Duration::from_millis(5));
        }
    }

    pub fn snapshot_for_audit(&self) -> DiagnosticSnapshot {
        let b = self.0.lock().unwrap_or_else(|e| e.into_inner());
        let bytes: Vec<u8> = b.bytes.iter().copied().collect();
        let truncated = b.received > CAPACITY as u64;
        let text = String::from_utf8_lossy(&bytes);
        // A ring can start within a secret or UTF-8 scalar; discard that incomplete first line.
        let text = if truncated { text.split_once('\n').map_or("", |(_, tail)| tail) } else { &text };
        let suppressed = b.secrets.iter().any(|s| s.is_empty());
        DiagnosticSnapshot {
            stderr: if suppressed { "[진단 생략]".into() } else { sanitize(text, &b.secrets) },
            bytes_received: b.received, truncated, reader_done: b.reader_done,
            reader_failed: b.reader_failed, exit_code: b.exit_code,
            failure: b.failure.as_ref().map(|s| if suppressed { "[진단 생략]".into() } else { sanitize(s, &b.secrets) }),
        }
    }
}

fn sanitize(text: &str, secrets: &[String]) -> String {
    let mut result = String::new();
    for line in text.lines() {
        let lower = line.to_ascii_lowercase();
        // Fail closed on structured credential/descriptor lines, including tokens not yet registered.
        let sensitive = ["capability", "nonce", "token", "authorization", "bearer ",
            "http://127.", "https://127.", "http://localhost", "https://localhost",
            "http://[::1]", "https://[::1]"].iter().any(|needle| lower.contains(needle));
        if sensitive { result.push_str("[민감정보 포함 진단 줄 생략]"); }
        else {
            let mut clean = line.to_owned();
            for secret in secrets { if !secret.is_empty() { clean = clean.replace(secret, "[비공개]"); } }
            result.push_str(&clean);
        }
        result.push('\n');
        if result.len() > CAPACITY {
            let mut end = CAPACITY;
            while !result.is_char_boundary(end) { end -= 1; }
            result.truncate(end); break;
        }
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;
    use std::time::{Duration, Instant};
    fn complete(d: &PrivateDiagnostics) -> DiagnosticSnapshot {
        let deadline = Instant::now() + Duration::from_secs(3);
        loop {
            let value = d.snapshot_for_audit();
            if value.reader_done { return value; }
            assert!(Instant::now() < deadline, "diagnostic reader failed to drain");
            std::thread::sleep(Duration::from_millis(5));
        }
    }
    #[test]
    fn unicode_failure_exit_and_secrets_are_retained_only_as_sanitized_evidence() {
        let d=PrivateDiagnostics::new();d.register_secret("known-private-value");
        d.capture(Cursor::new("대상 작업 연결 실패\nhttp://127.0.0.1:123/#unknown-private\nnonce=unknown-nonce\n오류: known-private-value\n".as_bytes().to_vec()));
        d.record_exit(Some(7));d.record_failure("실행 실패 known-private-value");
        let s=complete(&d);assert!(s.stderr.contains("대상 작업 연결 실패"));assert_eq!(s.exit_code,Some(7));
        assert!(!s.stderr.contains("unknown-private"));assert!(!s.stderr.contains("unknown-nonce"));assert!(!s.stderr.contains("known-private-value"));
        assert!(!s.failure.unwrap().contains("known-private-value"));
    }
    #[test]
    fn oversized_unicode_is_drained_but_retention_and_incomplete_prefix_are_bounded() {
        let d=PrivateDiagnostics::new();let payload=format!("{}\n마지막 실패 원인\n", "가".repeat(CAPACITY));
        let total=payload.len();d.capture(Cursor::new(payload.into_bytes()));let s=complete(&d);
        assert_eq!(s.bytes_received,total as u64);assert!(s.truncated);assert!(s.stderr.len()<=CAPACITY);
        assert_eq!(s.stderr,"마지막 실패 원인\n");assert!(!s.reader_failed);
    }
    #[test]
    fn late_secret_registration_redacts_already_captured_bytes() {
        let d=PrivateDiagnostics::new();d.capture(Cursor::new(b"failure private-value\n".to_vec()));complete(&d);
        d.register_secret("private-value");assert!(!d.snapshot_for_audit().stderr.contains("private-value"));
    }
    #[test]
    #[cfg(unix)]
    fn actual_failing_helper_pipe_retains_exit_and_unicode_without_capability() {
        use std::process::{Command, Stdio};
        let mut child=Command::new("/bin/sh").arg("-c")
            .arg("printf '대상 연결 실패\\ncapability=synthetic-private\\n' >&2; exit 9")
            .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::piped()).spawn().unwrap();
        let d=PrivateDiagnostics::new();d.register_secret("synthetic-private");
        d.capture(child.stderr.take().unwrap());d.record_exit(child.wait().unwrap().code());
        let s=d.snapshot_after_drain(Duration::from_secs(1));assert!(s.reader_done);
        assert_eq!(s.exit_code,Some(9));assert!(s.stderr.contains("대상 연결 실패"));
        assert!(!s.stderr.contains("synthetic-private"));
    }
    #[test]
    fn redaction_expansion_remains_bounded() {
        let d=PrivateDiagnostics::new();d.capture(Cursor::new("token=x\n".repeat(4000).into_bytes()));
        let s=d.snapshot_after_drain(Duration::from_secs(1));
        assert!(s.reader_done);assert!(s.stderr.len()<=CAPACITY);assert!(!s.stderr.contains("token=x"));
    }
    #[test]
    fn registration_overflow_fails_closed_for_later_drain() {
        let d=PrivateDiagnostics::new();d.register_secret(&"x".repeat(CAPACITY+1));
        d.capture(Cursor::new(b"unknown raw secret\n".to_vec()));let s=complete(&d);assert_eq!(s.stderr,"[진단 생략]");
    }
}
