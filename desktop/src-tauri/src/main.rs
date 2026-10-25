#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod diagnostics;
mod generated_icon;
#[cfg(feature = "native-qa")]
mod native_qa;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::HashSet,
    fs,
    io::{BufRead, BufReader, Read},
    path::{Path, PathBuf},
    process::{Child, ChildStdin, Command, Stdio},
    sync::Mutex,
    time::{Duration, Instant},
};
use tauri::{Emitter, Manager};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
// Never include a transport URL or user content in native errors.
#[derive(Clone, Deserialize, Serialize, Debug)]
#[serde(deny_unknown_fields)]
struct Config {
    version: u32,
    python: String,
    entrypoint: String,
    knowledge_home: Option<String>,
    vault_home: Option<String>,
    project_id: Option<String>,
    target_root: Option<String>,
    #[serde(default)]
    session_id: Option<String>,
    #[serde(default)]
    task_id: Option<String>,
    #[serde(default)]
    port: u16,
}
impl Config {
    fn validate(&self) -> Result<(), String> {
        if self.version != 1
            || ![&self.python, &self.entrypoint]
                .iter()
                .all(|p| Path::new(p).is_absolute())
            || [&self.knowledge_home, &self.vault_home, &self.target_root]
                .iter()
                .any(|p| p.as_ref().is_some_and(|v| !Path::new(v).is_absolute()))
        {
            return Err("앱 설정을 확인할 수 없습니다.".into());
        }
        Ok(())
    }
}
struct Backend {
    origin: String,
    token: String,
    child: Child,
    input: Option<ChildStdin>,
    diagnostics: diagnostics::PrivateDiagnostics,
}
#[derive(Clone, Copy)]
struct CloseTicket {
    id: u64,
    deadline: Instant,
}
fn consume_close(pending: &mut Option<CloseTicket>, id: u64, now: Instant) -> bool {
    if pending
        .as_ref()
        .is_some_and(|ticket| ticket.id == id && now < ticket.deadline)
    {
        *pending = None;
        true
    } else {
        false
    }
}
struct State {
    config: Config,
    diagnostics: diagnostics::PrivateDiagnostics,
    backend: Mutex<Option<Backend>>,
    error: Mutex<Option<String>>,
    close: Mutex<Option<CloseTicket>>,
    serial: std::sync::atomic::AtomicU64,
    rendered: std::sync::atomic::AtomicBool,
    confirming: std::sync::atomic::AtomicBool,
}
impl State {
    fn cleanup(&self) {
        if let Some(mut b) = self.backend.lock().unwrap().take() {
            b.input.take();
            std::thread::spawn(move || {
                for _ in 0..80 {
                    if b.child.try_wait().ok().flatten().is_some() {
                        b.diagnostics
                            .record_exit(b.child.try_wait().ok().flatten().and_then(|s| s.code()));
                        if b.diagnostics
                            .snapshot_for_audit()
                            .exit_code
                            .is_some_and(|code| code != 0)
                        {
                            print_diagnostics(&b.diagnostics);
                        }
                        return;
                    }
                    std::thread::sleep(Duration::from_millis(100));
                }
                let _ = b.child.kill();
                let status = b.child.wait().ok();
                b.diagnostics.record_exit(status.and_then(|s| s.code()));
                print_diagnostics(&b.diagnostics);
            });
        }
    }
}
fn read_config(path: &Path) -> Result<Config, String> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;
    let f = fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)
        .map_err(|_| "앱 설정을 읽을 수 없습니다.")?;
    let m = f.metadata().map_err(|_| "앱 설정을 확인할 수 없습니다.")?;
    if !m.is_file() || m.size() > 1024 * 1024 {
        return Err("앱 설정이 일반 파일이 아닙니다.".into());
    }
    let mut raw = String::new();
    f.take(1024 * 1024 + 1)
        .read_to_string(&mut raw)
        .map_err(|_| "앱 설정을 읽을 수 없습니다.")?;
    let value: Value =
        serde_json::from_str(&raw).map_err(|_| "앱 설정 형식이 올바르지 않습니다.")?;
    if ![
        "version",
        "python",
        "entrypoint",
        "knowledge_home",
        "vault_home",
        "project_id",
        "target_root",
    ]
    .iter()
    .all(|k| value.get(*k).is_some())
    {
        return Err("앱 설정의 필수 필드가 없습니다.".into());
    }
    let c: Config =
        serde_json::from_value(value).map_err(|_| "앱 설정 형식이 올바르지 않습니다.")?;
    c.validate()?;
    Ok(c)
}
fn config() -> Result<Config, String> {
    let exe = std::env::current_exe().map_err(|_| "앱 경로를 확인할 수 없습니다.")?;
    let base = read_config(
        &exe.parent()
            .unwrap()
            .parent()
            .unwrap()
            .join("Resources/desktop-config.json"),
    )?;
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() {
        return Ok(base);
    }
    if args.len() != 2 || args[0] != "--config" {
        return Err("지원하지 않는 앱 인자입니다.".into());
    }
    let p = PathBuf::from(&args[1]);
    use std::os::unix::fs::MetadataExt;
    let m = fs::symlink_metadata(&p).map_err(|_| "임시 설정을 확인할 수 없습니다.")?;
    let temp = std::env::temp_dir()
        .canonicalize()
        .map_err(|_| "임시 경로를 확인할 수 없습니다.")?;
    if p.parent().and_then(|x| x.canonicalize().ok()).as_ref() != Some(&temp)
        || !p
            .file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .starts_with("loop-work-desktop-")
        || !m.is_file()
        || m.mode() & 0o777 != 0o600
        || m.uid()
            != fs::metadata(&exe)
                .map_err(|_| "앱 소유자를 확인할 수 없습니다.")?
                .uid()
    {
        return Err("임시 설정의 소유권을 확인할 수 없습니다.".into());
    }
    let c = read_config(&p)?;
    if c.python != base.python
        || c.entrypoint != base.entrypoint
        || c.target_root != base.target_root
    {
        return Err("설치된 앱의 실행 범위를 바꿀 수 없습니다.".into());
    }
    fs::remove_file(p).map_err(|_| "임시 설정을 정리할 수 없습니다.")?;
    Ok(c)
}
fn launch(c: &Config, diagnostics: &diagnostics::PrivateDiagnostics) -> Result<Backend, String> {
    let mut cmd = Command::new(&c.python);
    cmd.arg(&c.entrypoint);
    if let Some(v) = &c.knowledge_home {
        cmd.args(["--knowledge-home", v]);
    }
    cmd.args(["board", "_desktop", "--port", &c.port.to_string()]);
    for (key, v) in [
        ("--vault", &c.vault_home),
        ("--project", &c.project_id),
        ("--session", &c.session_id),
        ("--task", &c.task_id),
        ("--target-root", &c.target_root),
    ] {
        if let Some(v) = v {
            cmd.args([key, v]);
        }
    }
    let mut child = cmd
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|_| "실행 도우미를 시작할 수 없습니다.")?;
    if let Some(stderr) = child.stderr.take() {
        diagnostics.capture(stderr);
    }
    let input = child.stdin.take();
    let out = child.stdout.take().unwrap();
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let mut raw = String::new();
        let result = BufReader::new(out)
            .take(65537)
            .read_line(&mut raw)
            .map(|_| raw);
        let _ = tx.send(result);
    });
    let value = match rx.recv_timeout(Duration::from_secs(25)) {
        Ok(Ok(raw)) => serde_json::from_str::<Value>(&raw).ok(),
        _ => None,
    };
    let parsed = (|| {
        let v = value?;
        if v.as_object()?.len() != 4
            || v["version"].as_u64() != Some(1)
            || !v["owned"].is_boolean()
            || v["instance_nonce"].as_str()?.len() < 32
        {
            return None;
        }
        let u = url::Url::parse(v["url"].as_str()?).ok()?;
        if u.scheme() != "http"
            || u.host_str() != Some("127.0.0.1")
            || u.port().is_none()
            || u.path() != "/"
            || u.query().is_some()
            || !u.username().is_empty()
            || u.password().is_some()
        {
            return None;
        }
        let token = u.fragment()?.to_string();
        if token.len() < 32
            || !token
                .bytes()
                .all(|x| x.is_ascii_alphanumeric() || b"-_".contains(&x))
        {
            return None;
        }
        diagnostics.register_secret(&token);
        diagnostics.register_secret(v["instance_nonce"].as_str()?);
        Some((format!("http://127.0.0.1:{}", u.port()?), token))
    })();
    if let Some((origin, token)) = parsed {
        Ok(Backend {
            origin,
            token,
            child,
            input,
            diagnostics: diagnostics.clone(),
        })
    } else {
        diagnostics.record_failure("도우미 연결 정보를 준비하지 못했습니다.");
        drop(input);
        let diagnostics = diagnostics.clone();
        std::thread::spawn(move || {
            let deadline = Instant::now() + Duration::from_secs(10);
            while child.try_wait().ok().flatten().is_none() && Instant::now() < deadline {
                std::thread::sleep(Duration::from_millis(20));
            }
            if child.try_wait().ok().flatten().is_none() {
                let _ = child.kill();
                let _ = child.wait();
            }
            diagnostics.record_exit(child.try_wait().ok().flatten().and_then(|s| s.code()));
            print_diagnostics(&diagnostics);
        });
        Err("앱 연결을 준비하지 못했습니다. 설치와 데이터 경로를 확인하세요.".into())
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    method: String,
    path: String,
    body: Option<Value>,
}
fn allowed(r: &Request, c: &Config) -> Result<(), String> {
    if !["GET", "POST"].contains(&r.method.as_str())
        || r.path.len() > 8192
        || !r.path.starts_with("/api/")
        || r.path.contains(['\\', '#'])
        || r.path.split('?').next().unwrap_or("").contains("..")
        || r.path.split('?').next().unwrap_or("").contains('%')
        || r.path.chars().any(|x| x.is_control())
    {
        return Err("허용하지 않는 API 요청입니다.".into());
    }
    let u = url::Url::parse(&format!("http://127.0.0.1{}", r.path))
        .map_err(|_| "API 경로가 올바르지 않습니다.")?;
    if u.path().contains('%') {
        return Err("인코딩된 API 경로는 허용하지 않습니다.".into());
    }
    let parts: Vec<_> = u.path().split('/').collect();
    let id = |s: &str| {
        !s.is_empty()
            && s.bytes()
                .all(|x| x.is_ascii_alphanumeric() || b"-_".contains(&x))
    };
    let get = matches!(
        u.path(),
        "/api/projects" | "/api/board" | "/api/requests" | "/api/document"
    ) || (parts.len() == 4 && ["tasks", "requests"].contains(&parts[2]) && id(parts[3]))
        || (parts.len() == 5
            && ["tasks", "projects"].contains(&parts[2])
            && id(parts[3])
            && parts[4] == "wiki");
    let post = parts.len() == 5
        && id(parts[3])
        && ((parts[2] == "requests" && ["respond", "execute"].contains(&parts[4]))
            || (parts[2] == "tasks" && parts[4] == "control")
            || (["tasks", "projects"].contains(&parts[2]) && parts[4] == "wiki"));
    if !(if r.method == "GET" {
        get && r.body.is_none()
    } else {
        post && r.body.as_ref().is_some_and(|v| v.is_object())
    }) {
        return Err("허용하지 않는 API 동작입니다.".into());
    }
    let mut seen = HashSet::new();
    for (k, v) in u.query_pairs() {
        if ![
            "project_id",
            "session_id",
            "task_id",
            "query",
            "sort",
            "include_closed",
            "status",
            "path",
        ]
        .contains(&k.as_ref())
            || !seen.insert(k.to_string())
        {
            return Err("API 조회 필드가 올바르지 않습니다.".into());
        }
        for (name, fixed) in [
            ("project_id", &c.project_id),
            ("session_id", &c.session_id),
            ("task_id", &c.task_id),
        ] {
            if k == name && fixed.as_ref().is_some_and(|x| x != &v) {
                return Err("고정된 작업 범위를 바꿀 수 없습니다.".into());
            }
        }
    }
    if r.body
        .as_ref()
        .is_some_and(|v| serde_json::to_vec(v).map_or(true, |v| v.len() > 1024 * 1024))
    {
        return Err("요청 본문이 너무 큽니다.".into());
    }
    Ok(())
}
#[tauri::command]
fn bootstrap(state: tauri::State<State>) -> Value {
    let error = state.error.lock().unwrap().clone();
    json!({"ready":state.backend.lock().unwrap().is_some(),"scope":{"project_id":state.config.project_id,"session_id":state.config.session_id,"task_id":state.config.task_id},"error":error})
}
#[tauri::command]
async fn board_request(
    request: Request,
    state: tauri::State<'_, State>,
    app: tauri::AppHandle,
) -> Result<Value, String> {
    allowed(&request, &state.config)?;
    let (origin, token) = {
        let b = state.backend.lock().unwrap();
        let b = b.as_ref().ok_or("앱 연결을 아직 준비하지 못했습니다.")?;
        (b.origin.clone(), b.token.clone())
    };
    let qa_path = request.path.clone();
    let qa_is_post = request.method == "POST";
    let result = tauri::async_runtime::spawn_blocking(move || {
        let agent = ureq::AgentBuilder::new()
            .timeout(Duration::from_secs(15))
            .redirects(0)
            .build();
        let req = agent
            .request(&request.method, &format!("{}{}", origin, request.path))
            .set("Origin", &origin)
            .set("X-Loop-Capability", &token);
        let response = if let Some(body) = request.body {
            req.send_json(body)
        } else {
            req.call()
        };
        let response = match response {
            Ok(v) => v,
            Err(ureq::Error::Status(_, v)) => v,
            Err(_) => {
                return Err(
                    "요청 응답을 확인하지 못했습니다. 초안을 보존하고 다시 확인하세요.".into(),
                )
            }
        };
        let status = response.status();
        let mut raw = String::new();
        response
            .into_reader()
            .take(8 * 1024 * 1024 + 1)
            .read_to_string(&mut raw)
            .map_err(|_| "응답을 읽을 수 없습니다.")?;
        if raw.len() > 8 * 1024 * 1024 {
            return Err("응답 크기 제한을 초과했습니다.".into());
        }
        let body: Value =
            serde_json::from_str(&raw).map_err(|_| "응답 형식이 올바르지 않습니다.")?;
        Ok(json!({"status":status,"body":body}))
    })
    .await
    .map_err(|_| "요청을 완료하지 못했습니다.".to_string())?;
    #[cfg(feature = "native-qa")]
    if let Ok(ref value) = result {
        match native_qa::fault(
            &app,
            &qa_path,
            value["status"].as_u64().unwrap_or(0) as u16,
            qa_is_post,
        ) {
            1 => return Err("QA: 실제 저장 후 응답 유실".into()),
            2 => {
                tauri::async_runtime::spawn_blocking(|| {
                    std::thread::sleep(Duration::from_secs(15))
                })
                .await
                .map_err(|_| "QA 지연 실패")?;
            }
            3 => {
                tauri::async_runtime::spawn_blocking(|| std::thread::sleep(Duration::from_secs(4)))
                    .await
                    .map_err(|_| "QA 보드 응답 전달 지연 실패")?;
                native_qa::board_released(&app);
            }
            _ => (),
        }
    }
    #[cfg(not(feature = "native-qa"))]
    let _ = (app, qa_path, qa_is_post);
    result
}
fn confirm(app: tauri::AppHandle, request_id: u64) {
    if app
        .state::<State>()
        .confirming
        .swap(true, std::sync::atomic::Ordering::SeqCst)
    {
        return;
    }
    let handle = app.clone();
    let dialog=app.dialog().message("저장하지 못한 초안이나 제출하지 않은 입력이 있을 수 있습니다. 종료하면 메모리의 입력을 잃습니다.").title("Loop Work 종료 확인").kind(MessageDialogKind::Warning).buttons(MessageDialogButtons::OkCancelCustom("종료하고 버리기".into(),"계속 편집".into()));
    let dialog = if let Some(window) = app.get_webview_window("main") {
        dialog.parent(&window)
    } else {
        dialog
    };
    dialog.show(move |yes| {
        #[cfg(feature = "native-qa")]
        native_qa::confirmation_callback(&handle, yes, request_id);
        handle
            .state::<State>()
            .confirming
            .store(false, std::sync::atomic::Ordering::SeqCst);
        if yes {
            handle.state::<State>().cleanup();
            handle.exit(0)
        } else {
            let _ = handle.emit(
                "loop-work-close-cancelled",
                json!({"request_id":request_id}),
            );
        }
    });
    #[cfg(feature = "native-qa")]
    native_qa::observe_dialog(&app);
}
fn request_close(app: &tauri::AppHandle) {
    use std::sync::atomic::Ordering;
    let state = app.state::<State>();
    let mut close = state.close.lock().unwrap();
    if close.is_some() || state.confirming.load(Ordering::SeqCst) {
        return;
    }
    let id = state.serial.fetch_add(1, Ordering::SeqCst) + 1;
    *close = Some(CloseTicket {
        id,
        deadline: Instant::now() + Duration::from_secs(6),
    });
    drop(close);
    #[cfg(feature = "native-qa")]
    native_qa::close_started(app, id);
    let _ = app.emit("loop-work-close-request", json!({"request_id":id}));
    let app = app.clone();
    std::thread::spawn(move || {
        std::thread::sleep(Duration::from_secs(6));
        let state = app.state::<State>();
        let mut pending = state.close.lock().unwrap();
        if pending.as_ref().is_some_and(|ticket| ticket.id == id) {
            *pending = None;
            drop(pending);
            let native = app.clone();
            let _ = app.run_on_main_thread(move || confirm(native, id));
        }
    });
}
#[tauri::command]
fn finish_close(
    request_id: u64,
    safe: bool,
    reason: Option<String>,
    app: tauri::AppHandle,
    state: tauri::State<State>,
) -> Result<(), String> {
    if reason.as_ref().is_some_and(|s| s.len() > 4096) {
        return Err("종료 응답이 너무 깁니다.".into());
    }
    let mut pending = state.close.lock().unwrap();
    if !consume_close(&mut pending, request_id, Instant::now()) {
        return Err("만료된 종료 요청입니다.".into());
    }
    drop(pending);
    if safe {
        state.cleanup();
        app.exit(0)
    } else {
        confirm(app, request_id)
    }
    Ok(())
}
#[tauri::command]
fn renderer_ready(app: tauri::AppHandle, state: tauri::State<State>) {
    if state
        .rendered
        .swap(true, std::sync::atomic::Ordering::SeqCst)
    {
        return;
    }
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.set_focus();
    }
    println!("{{\"event\":\"desktop_ready\"}}");
    #[cfg(feature = "native-qa")]
    native_qa::start(&app);
}
fn obsidian_uri(vault: &str, uri: Option<String>) -> Result<String, String> {
    let root = Path::new(vault)
        .canonicalize()
        .map_err(|_| "문서 보관함을 확인할 수 없습니다.")?;
    let u = match uri {
        Some(v) => url::Url::parse(&v).map_err(|_| "문서 링크가 올바르지 않습니다.")?,
        None => {
            let mut u = url::Url::parse("obsidian://open").unwrap();
            u.query_pairs_mut().append_pair("path", vault);
            u
        }
    };
    if u.scheme() != "obsidian"
        || u.host_str() != Some("open")
        || !u.path().is_empty()
        || u.fragment().is_some()
        || !u.username().is_empty()
        || u.password().is_some()
    {
        return Err("허용하지 않는 문서 링크입니다.".into());
    }
    let pairs: Vec<_> = u.query_pairs().collect();
    if pairs.len() != 1 || pairs[0].0 != "path" {
        return Err("선택한 보관함의 정확한 문서 경로만 열 수 있습니다.".into());
    }
    let selected = Path::new(pairs[0].1.as_ref());
    if !selected.is_absolute()
        || selected
            .components()
            .any(|x| matches!(x, std::path::Component::ParentDir))
        || selected
            .canonicalize()
            .ok()
            .is_none_or(|p| !p.starts_with(&root))
    {
        return Err("보관함 밖의 링크입니다.".into());
    }
    Ok(u.to_string())
}
#[tauri::command]
fn open_obsidian(uri: Option<String>, state: tauri::State<State>) -> Result<(), String> {
    let vault = state
        .config
        .vault_home
        .as_ref()
        .ok_or("문서 보관함이 설정되지 않았습니다.")?;
    let uri = obsidian_uri(vault, uri)?;
    Command::new("/usr/bin/open")
        .arg(uri)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|_| "Obsidian을 열 수 없습니다.")?;
    Ok(())
}

fn restore_main(app: &tauri::AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.set_focus();
    }
}
fn print_diagnostics(d: &diagnostics::PrivateDiagnostics) {
    let s = d.snapshot_after_drain(Duration::from_millis(500));
    eprintln!(
        "{}",
        json!({"event":"helper_failure","helper_exit":s.exit_code,"helper_stderr":s.stderr,"helper_failure":s.failure,"truncated":s.truncated,"bytes_received":s.bytes_received,"reader_done":s.reader_done,"reader_failed":s.reader_failed})
    );
}
fn main() {
    let c = match config() {
        Ok(c) => c,
        Err(_) => {
            eprintln!("앱 설정을 확인할 수 없습니다. 다시 설치하세요.");
            std::process::exit(2)
        }
    };
    let state = State {
        config: c,
        diagnostics: diagnostics::PrivateDiagnostics::new(),
        backend: Mutex::new(None),
        error: Mutex::new(None),
        close: Mutex::new(None),
        serial: std::sync::atomic::AtomicU64::new(0),
        rendered: std::sync::atomic::AtomicBool::new(false),
        confirming: std::sync::atomic::AtomicBool::new(false),
    };
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(state)
        .invoke_handler({
            #[cfg(feature = "native-qa")]
            {
                tauri::generate_handler![
                    bootstrap,
                    board_request,
                    finish_close,
                    renderer_ready,
                    open_obsidian,
                    native_qa::native_qa_action,
                    native_qa::native_qa_report
                ]
            }
            #[cfg(not(feature = "native-qa"))]
            {
                tauri::generate_handler![
                    bootstrap,
                    board_request,
                    finish_close,
                    renderer_ready,
                    open_obsidian
                ]
            }
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .setup(|app| {
            #[cfg(feature = "native-qa")]
            app.manage(native_qa::load().map_err(std::io::Error::other)?);
            let builder = tauri::WebviewWindowBuilder::new(
                app,
                "main",
                tauri::WebviewUrl::App("index.html".into()),
            )
            .title("Loop Work · 개발 자동화")
            .inner_size(1280.0, 840.0)
            .min_inner_size(760.0, 560.0)
            .visible(false)
            .incognito(true)
            .on_new_window(|_, _| tauri::webview::NewWindowResponse::Deny)
            .on_navigation(|u| {
                (u.scheme() == "tauri" && u.host_str() == Some("localhost"))
                    || (u.scheme() == "http" && u.host_str() == Some("tauri.localhost"))
            });
            #[cfg(feature = "native-qa")]
            let builder = builder.initialization_script(native_qa::initialization());
            builder.build()?;
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let result = launch(
                    &handle.state::<State>().config,
                    &handle.state::<State>().diagnostics,
                );
                match result {
                    Ok(b) => *handle.state::<State>().backend.lock().unwrap() = Some(b),
                    Err(e) => *handle.state::<State>().error.lock().unwrap() = Some(e),
                }
                let _ = handle.emit("loop-work-bootstrap-ready", ());
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("앱을 준비하지 못했습니다.");
    app.run(|app, event| match event {
        tauri::RunEvent::ExitRequested { api, code, .. } => {
            if code.is_none() {
                api.prevent_exit();
                request_close(app)
            }
        }
        tauri::RunEvent::Reopen { .. } => restore_main(app),
        tauri::RunEvent::Exit => app.state::<State>().cleanup(),
        _ => {}
    });
}
#[cfg(test)]
mod tests {
    use super::*;
    fn cfg() -> Config {
        Config {
            version: 1,
            python: "/usr/bin/python3".into(),
            entrypoint: "/tmp/loop.py".into(),
            knowledge_home: None,
            vault_home: None,
            project_id: Some("fixed".into()),
            target_root: None,
            session_id: None,
            task_id: None,
            port: 0,
        }
    }
    #[test]
    fn limits() {
        let c = cfg();
        for path in [
            "/api/_service",
            "/api/tasks/x/wiki/../control",
            "https://evil/api/board",
            "/api/tasks/%2e/wiki",
            "/api/board?project_id=other",
            "/api/board?sort=name&sort=name",
        ] {
            assert!(
                allowed(
                    &Request {
                        method: "GET".into(),
                        path: path.into(),
                        body: None
                    },
                    &c
                )
                .is_err(),
                "{path}"
            );
        }
        assert!(allowed(
            &Request {
                method: "GET".into(),
                path: "/api/board?project_id=fixed".into(),
                body: None
            },
            &c
        )
        .is_ok());
    }
    #[test]
    fn actual_config_file_and_obsidian_scope_guards() {
        let base = std::env::temp_dir().join(format!(
            "loop-native-test-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir(&base).unwrap();
        let p = base.join("config.json");
        let mut value = serde_json::to_value(cfg()).unwrap();
        fs::write(&p, serde_json::to_vec(&value).unwrap()).unwrap();
        assert!(read_config(&p).is_ok());
        value.as_object_mut().unwrap().remove("target_root");
        fs::write(&p, serde_json::to_vec(&value).unwrap()).unwrap();
        assert!(read_config(&p).is_err());
        fs::write(&p, b"null").unwrap();
        assert!(read_config(&p).is_err());
        fs::remove_file(&p).unwrap();
        std::os::unix::fs::symlink(base.join("absent"), &p).unwrap();
        assert!(read_config(&p).is_err());
        fs::remove_file(&p).unwrap();
        let vault = base.join("vault");
        fs::create_dir(&vault).unwrap();
        let note = vault.join("한글.md");
        fs::write(&note, "원문").unwrap();
        assert!(obsidian_uri(vault.to_str().unwrap(), None).is_ok());
        let mut u = url::Url::parse("obsidian://open").unwrap();
        u.query_pairs_mut()
            .append_pair("path", note.to_str().unwrap());
        assert!(obsidian_uri(vault.to_str().unwrap(), Some(u.to_string())).is_ok());
        std::os::unix::fs::symlink(&base, vault.join("outside")).unwrap();
        let mut u = url::Url::parse("obsidian://open").unwrap();
        u.query_pairs_mut()
            .append_pair("path", vault.join("outside/config.json").to_str().unwrap());
        assert!(obsidian_uri(vault.to_str().unwrap(), Some(u.to_string())).is_err());
        assert!(obsidian_uri(vault.to_str().unwrap(), Some("https://example.com".into())).is_err());
        fs::remove_dir_all(base).unwrap();
    }
    #[test]
    fn close_ticket_is_one_shot_deadline_bound_and_cannot_consume_new_request() {
        let now = Instant::now();
        let mut ticket = Some(CloseTicket {
            id: 7,
            deadline: now + Duration::from_secs(6),
        });
        assert!(!consume_close(&mut ticket, 6, now));
        assert!(ticket.is_some());
        assert!(!consume_close(&mut ticket, 7, now + Duration::from_secs(6)));
        assert!(ticket.is_some());
        assert!(consume_close(&mut ticket, 7, now + Duration::from_secs(5)));
        assert!(!consume_close(&mut ticket, 7, now));
        ticket = Some(CloseTicket {
            id: 8,
            deadline: now + Duration::from_secs(6),
        });
        assert!(!consume_close(&mut ticket, 7, now));
        assert!(consume_close(&mut ticket, 8, now));
    }
    #[test]
    fn generated_icon_preserves_modified_and_symlink_paths() {
        let root = std::env::temp_dir().join(format!(
            "loop-icon-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir(&root).unwrap();
        generated_icon::ensure_icon(&root, b"owned").unwrap();
        generated_icon::ensure_icon(&root, b"owned").unwrap();
        let icon = root.join("icons/icon.png");
        fs::write(&icon, b"user").unwrap();
        assert!(generated_icon::ensure_icon(&root, b"owned").is_err());
        assert_eq!(fs::read(&icon).unwrap(), b"user");
        fs::remove_file(&icon).unwrap();
        std::os::unix::fs::symlink(root.join("other"), &icon).unwrap();
        assert!(generated_icon::ensure_icon(&root, b"owned").is_err());
        assert!(fs::symlink_metadata(&icon)
            .unwrap()
            .file_type()
            .is_symlink());
        fs::remove_file(&icon).unwrap();
        fs::remove_dir(root.join("icons")).unwrap();
        std::os::unix::fs::symlink(&root, root.join("icons")).unwrap();
        assert!(generated_icon::ensure_icon(&root, b"owned").is_err());
        fs::remove_file(root.join("icons")).unwrap();
        fs::remove_dir(root).unwrap();
    }
    #[test]
    fn actual_native_launcher_keeps_failing_helper_diagnostics() {
        let path = std::env::temp_dir().join(format!(
            "loop-failing-helper-{}-{}.sh",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::write(&path,"printf '네이티브 도우미 실패 원인\n' >&2\nprintf 'capability=not-public\n' >&2\nprintf 'invalid descriptor\n'\nexit 7\n").unwrap();
        let mut c = cfg();
        c.python = "/bin/sh".into();
        c.entrypoint = path.to_str().unwrap().into();
        let d = diagnostics::PrivateDiagnostics::new();
        assert!(launch(&c, &d).is_err());
        let deadline = Instant::now() + Duration::from_secs(2);
        while d.snapshot_for_audit().exit_code.is_none() && Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(10));
        }
        let s = d.snapshot_after_drain(Duration::from_millis(500));
        assert_eq!(s.exit_code, Some(7));
        assert!(s.stderr.contains("네이티브 도우미 실패 원인"));
        assert!(!s.stderr.contains("not-public"));
        fs::remove_file(path).unwrap();
    }
    #[test]
    fn strict_config() {
        assert!(serde_json::from_value::<Config>(json!({"version":true,"python":"/x","entrypoint":"/y","knowledge_home":null,"vault_home":null,"project_id":null,"target_root":null})).is_err());
    }
}
