//! Compile-time opt-in native integration driver. This entire module and its IPC
//! commands are absent from the default shipping binary. Never a production bridge.
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    fs,
    io::{Read, Write},
    path::PathBuf,
    sync::{
        atomic::{AtomicU8, Ordering},
        Mutex,
    },
    time::{Duration, Instant},
};
use tauri::{Emitter, Manager};
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Plan {
    script_path: PathBuf,
    report_path: PathBuf,
}
pub struct Audit {
    plan: Plan,
    events: Mutex<Vec<Value>>,
    started: Mutex<Option<Instant>>,
    fault: AtomicU8,
    board_hold: AtomicU8,
}
fn read(path: &std::path::Path, max: u64) -> Result<String, String> {
    use std::os::unix::fs::OpenOptionsExt;
    let f = fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)
        .map_err(|_| "QA 파일 열기 실패")?;
    if !f.metadata().map_err(|_| "QA 파일 확인 실패")?.is_file() {
        return Err("QA 일반 파일 필요".into());
    }
    let mut s = String::new();
    f.take(max + 1)
        .read_to_string(&mut s)
        .map_err(|_| "QA 파일 읽기 실패")?;
    if s.len() > max as usize {
        return Err("QA 파일 크기 초과".into());
    }
    Ok(s)
}
pub fn load() -> Result<Audit, String> {
    let p = std::env::var_os("LOOP_NATIVE_QA_PLAN").ok_or("native-qa 전용 계획이 필요합니다")?;
    let plan: Plan =
        serde_json::from_str(&read(&PathBuf::from(p), 65536)?).map_err(|_| "QA 계획 형식 오류")?;
    if !plan.script_path.is_absolute() || !plan.report_path.is_absolute() {
        return Err("QA 절대경로 필요".into());
    }
    Ok(Audit {
        plan,
        events: Mutex::new(vec![]),
        started: Mutex::new(None),
        fault: AtomicU8::new(0),
        board_hold: AtomicU8::new(0),
    })
}
pub fn initialization() -> &'static str {
    r#"(()=>{let reduced=false;const real=window.matchMedia.bind(window),q=real('(prefers-reduced-motion: reduce)');Object.defineProperty(q,'matches',{get:()=>reduced});window.matchMedia=s=>s==='(prefers-reduced-motion: reduce)'?q:real(s);Object.defineProperty(window,'__loopNativeQaReduced',{value:value=>{reduced=!!value;q.dispatchEvent(new Event('change'))}})})();"#
}
pub fn start(app: &tauri::AppHandle) {
    let audit = app.state::<Audit>();
    match read(&audit.plan.script_path, 256 * 1024) {
        Ok(script) => {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.eval(&script);
            }
        }
        Err(_) => {
            eprintln!("native-qa 계획을 읽지 못했습니다.");
            app.exit(3)
        }
    }
}
pub fn close_started(app: &tauri::AppHandle, id: u64) {
    let audit = app.state::<Audit>();
    *audit.started.lock().unwrap() = Some(Instant::now());
    audit
        .events
        .lock()
        .unwrap()
        .push(json!({"event":"close_requested","id":id}));
}
// QA observes and clicks the real AppKit alert. The shipping dialog and its
// callback remain unchanged; no simulated confirmation or early return.
pub fn confirmation_callback(app: &tauri::AppHandle, accepted: bool, request_id: u64) {
    let audit = app.state::<Audit>();
    let ms = audit
        .started
        .lock()
        .unwrap()
        .map(|t| t.elapsed().as_millis() as u64);
    audit.events.lock().unwrap().push(json!({"event":"confirmation_callback","request_id":request_id,"elapsed_ms":ms,"accepted":accepted,"physical_gui_input_verified":false}));
}
#[link(name = "objc")]
extern "C" {
    fn objc_getClass(name: *const std::ffi::c_char) -> *mut std::ffi::c_void;
    fn sel_registerName(name: *const std::ffi::c_char) -> *mut std::ffi::c_void;
    fn objc_msgSend();
}
unsafe fn message(receiver: *mut std::ffi::c_void, name: &str) -> *mut std::ffi::c_void {
    let selector = std::ffi::CString::new(name).unwrap();
    let f: unsafe extern "C" fn(
        *mut std::ffi::c_void,
        *mut std::ffi::c_void,
    ) -> *mut std::ffi::c_void = std::mem::transmute(objc_msgSend as *const ());
    f(receiver, sel_registerName(selector.as_ptr()))
}
// Apple's Objective-C BOOL is C++ bool on arm64 macOS, signed char on
// Intel macOS. Keep scalar-return calls separate from object-return messages.
#[cfg(target_arch = "aarch64")]
type ObjcBool = bool;
#[cfg(not(target_arch = "aarch64"))]
type ObjcBool = std::ffi::c_schar;
unsafe fn message_bool(receiver: *mut std::ffi::c_void, name: &str) -> bool {
    let selector = std::ffi::CString::new(name).unwrap();
    let f: unsafe extern "C" fn(*mut std::ffi::c_void, *mut std::ffi::c_void) -> ObjcBool =
        std::mem::transmute(objc_msgSend as *const ());
    let value = f(receiver, sel_registerName(selector.as_ptr()));
    #[cfg(target_arch = "aarch64")]
    {
        value
    }
    #[cfg(not(target_arch = "aarch64"))]
    {
        value != 0
    }
}
unsafe fn message_count(receiver: *mut std::ffi::c_void) -> usize {
    let f: unsafe extern "C" fn(*mut std::ffi::c_void, *mut std::ffi::c_void) -> usize =
        std::mem::transmute(objc_msgSend as *const ());
    f(receiver, sel_registerName(c"count".as_ptr()))
}
unsafe fn cancel_button(view: *mut std::ffi::c_void, depth: usize) -> bool {
    if view.is_null() || depth > 12 {
        return false;
    }
    let class = objc_getClass(c"NSButton".as_ptr());
    let f: unsafe extern "C" fn(
        *mut std::ffi::c_void,
        *mut std::ffi::c_void,
        *mut std::ffi::c_void,
    ) -> ObjcBool = std::mem::transmute(objc_msgSend as *const ());
    let kind = f(view, sel_registerName(c"isKindOfClass:".as_ptr()), class);
    #[cfg(target_arch = "aarch64")]
    let is_button = kind;
    #[cfg(not(target_arch = "aarch64"))]
    let is_button = kind != 0;
    if is_button {
        let title = message(view, "title");
        let utf = message(title, "UTF8String") as *const std::ffi::c_char;
        if !utf.is_null()
            && message_bool(view, "isEnabled")
            && std::ffi::CStr::from_ptr(utf).to_bytes() == "계속 편집".as_bytes()
        {
            let click: unsafe extern "C" fn(
                *mut std::ffi::c_void,
                *mut std::ffi::c_void,
                *mut std::ffi::c_void,
            ) = std::mem::transmute(objc_msgSend as *const ());
            click(
                view,
                sel_registerName(c"performClick:".as_ptr()),
                std::ptr::null_mut(),
            );
            return true;
        }
    }
    let children = message(view, "subviews");
    if children.is_null() {
        return false;
    }
    let n = message_count(children);
    let at: unsafe extern "C" fn(
        *mut std::ffi::c_void,
        *mut std::ffi::c_void,
        usize,
    ) -> *mut std::ffi::c_void = std::mem::transmute(objc_msgSend as *const ());
    for i in 0..n.min(100) {
        if cancel_button(
            at(children, sel_registerName(c"objectAtIndex:".as_ptr()), i),
            depth + 1,
        ) {
            return true;
        }
    }
    false
}
pub fn observe_dialog(app: &tauri::AppHandle) {
    let handle = app.clone();
    std::thread::spawn(move || {
        for _ in 0..60 {
            std::thread::sleep(Duration::from_millis(50));
            if !handle
                .state::<super::State>()
                .confirming
                .load(Ordering::SeqCst)
            {
                return;
            }
            let inner = handle.clone();
            let _=handle.run_on_main_thread(move||unsafe{
                if !inner.state::<super::State>().confirming.load(Ordering::SeqCst){return}
                let Some(window)=inner.get_webview_window("main") else{return};
                let Ok(parent)=window.ns_window() else{return};
                let sheet=message(parent as *mut std::ffi::c_void,"attachedSheet");
                if !sheet.is_null() && message(sheet,"isVisible") as usize != 0 && cancel_button(message(sheet,"contentView"),0){
                    inner.state::<Audit>().events.lock().unwrap().push(json!({"event":"actual_native_sheet_cancel_clicked","physical_gui_input_verified":false,"button":"계속 편집","actual_attached_sheet":true}));
                }
            });
        }
    });
}
fn fault_mode(value: u8, path: &str, status: u16) -> u8 {
    if status != 200 {
        return 0;
    }
    let path = path.split('?').next().unwrap_or("");
    match value {
        1 | 2 if path.ends_with("/wiki") => value,
        3 | 4 if path.ends_with("/execute") => value - 2,
        _ => 0,
    }
}
pub fn fault(app: &tauri::AppHandle, path: &str, status: u16, is_post: bool) -> u8 {
    let a = app.state::<Audit>();
    if !is_post {
        if status == 200
            && path.split('?').next() == Some("/api/board")
            && a.board_hold
                .compare_exchange(1, 2, Ordering::SeqCst, Ordering::SeqCst)
                .is_ok()
        {
            a.events
                .lock()
                .unwrap()
                .push(json!({"event":"actual_board_get_200_held","milliseconds":4000}));
            return 3;
        }
        return 0;
    }
    let value = a.fault.load(Ordering::SeqCst);
    let mode = fault_mode(value, path, status);
    if mode == 0
        || a.fault
            .compare_exchange(value, 0, Ordering::SeqCst, Ordering::SeqCst)
            .is_err()
    {
        return 0;
    }
    if value == 3 {
        a.board_hold.store(1, Ordering::SeqCst);
    }
    a.events.lock().unwrap().push(json!({"event":"actual_http_200_then_transport_fault","mode":mode,"target":if value>2{"execute"}else{"wiki"}}));
    mode
}
pub fn board_released(app: &tauri::AppHandle) {
    let a = app.state::<Audit>();
    a.board_hold.store(3, Ordering::SeqCst);
    a.events
        .lock()
        .unwrap()
        .push(json!({"event":"actual_board_get_200_released"}));
}
#[cfg(test)]
mod tests {
    #[test]
    fn transport_faults_require_exact_successful_operation() {
        for (value, suffix, mode) in [
            (1, "wiki", 1),
            (2, "wiki", 2),
            (3, "execute", 1),
            (4, "execute", 2),
        ] {
            assert_eq!(
                super::fault_mode(
                    value,
                    &format!("/api/requests/id/{suffix}?project_id=p"),
                    200
                ),
                mode
            );
            assert_eq!(super::fault_mode(value, "/api/requests/id/respond", 200), 0);
            assert_eq!(
                super::fault_mode(value, &format!("/api/requests/id/{suffix}"), 409),
                0
            );
        }
        assert_eq!(super::fault_mode(3, "/api/tasks/id/wiki", 200), 0);
        assert_eq!(super::fault_mode(1, "/api/requests/id/execute", 200), 0);
    }
}
#[tauri::command]
pub fn native_qa_action(action: String, app: tauri::AppHandle) -> Result<Value, String> {
    let w = app.get_webview_window("main").ok_or("QA 창 없음")?;
    match action.as_str() {
        "window_close" => {
            w.close().map_err(|_| "창 닫기 실패")?;
        }
        "window_reopen" => super::restore_main(&app),
        "request_quit" => super::request_close(&app),
        "unresponsive_then_quit" => {
            w.eval("{const until=Date.now()+7500;while(Date.now()<until){}}")
                .map_err(|_| "WebView 유한 응답정지 실패")?;
            super::request_close(&app)
        }
        "drop_next_wiki_response" => {
            app.state::<Audit>().fault.store(1, Ordering::SeqCst);
        }
        "delay_next_wiki_response" => {
            app.state::<Audit>().fault.store(2, Ordering::SeqCst);
        }
        "drop_next_execute_response" => {
            app.state::<Audit>().fault.store(3, Ordering::SeqCst);
        }
        "delay_next_execute_response" => {
            app.state::<Audit>().fault.store(4, Ordering::SeqCst);
        }
        label if label.starts_with("progress:") => {
            let parts: Vec<&str> = label.split(':').collect();
            if label.len() > 200
                || parts.len() != 3
                || !matches!(parts[2], "start" | "done")
                || parts[1].is_empty()
                || !label
                    .bytes()
                    .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_' || b == b':')
            {
                return Err("정해진 QA 진행 표식만 허용됩니다.".into());
            }
            let milliseconds = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_millis())
                .unwrap_or(0);
            eprintln!("native_qa_progress {} at_ms={}", label, milliseconds);
        }
        "status" => (),
        _ => return Err("지원하지 않는 QA 동작".into()),
    }
    let a = app.state::<Audit>();
    Ok(
        json!({"visible":w.is_visible().unwrap_or(false),"events":a.events.lock().unwrap().clone(),"feature":"native-qa","board_hold_state":a.board_hold.load(Ordering::SeqCst)}),
    )
}
#[tauri::command]
pub fn native_qa_report(report: Value, app: tauri::AppHandle) -> Result<(), String> {
    let a = app.state::<Audit>();
    let value = json!({"report":report,"native_events":a.events.lock().unwrap().clone(),"feature":"native-qa","shipping_binary":false,"physical_gui_input_verified":false});
    let raw = serde_json::to_vec_pretty(&value).map_err(|_| "QA 결과 직렬화 실패")?;
    if raw.len() > 512 * 1024 {
        return Err("QA 결과 크기 초과".into());
    }
    use std::os::unix::fs::OpenOptionsExt;
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(&a.plan.report_path)
        .map_err(|_| "QA 결과 보존 실패")?;
    file.write_all(&raw).map_err(|_| "QA 결과 쓰기 실패")?;
    file.sync_all().map_err(|_| "QA 결과 동기화 실패")?;
    let passed = value["report"]["passed"].as_bool().unwrap_or(false);
    println!("{}", json!({"event":"native_qa_complete","passed":passed}));
    app.state::<super::State>().cleanup();
    app.exit(if passed { 0 } else { 3 });
    Ok(())
}
