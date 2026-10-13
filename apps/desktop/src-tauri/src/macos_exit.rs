//! AppKit's Quit menu, Cmd-Q and Dock Quit bypass Tauri's ExitRequested event.
//! Extend the existing delegate so all three use the same asynchronous guard.
use objc2::{class, msg_send, sel, runtime::{AnyObject, ClassBuilder, Sel}};
use std::sync::OnceLock;
use tauri::Manager;

static APP: OnceLock<tauri::AppHandle> = OnceLock::new();

extern "C-unwind" fn should_terminate(_: &AnyObject, _: Sel, _: *mut AnyObject) -> usize {
    let Some(app) = APP.get() else { return 1; }; // NSTerminateNow
    let intercept = app.state::<std::sync::Mutex<super::ExitGuard>>().lock().unwrap().intercept();
    if intercept {
        super::request_guarded_exit(app);
        0 // NSTerminateCancel; an approved answer later calls app.exit().
    } else { 1 }
}

pub fn install(app: &tauri::AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    // Called once in setup on AppKit's main thread. The subclass adds no ivars,
    // keeps Tao's delegate identity/state and inherits all its other callbacks.
    unsafe {
        let ns_app: *mut AnyObject = msg_send![class!(NSApplication), sharedApplication];
        let delegate: *mut AnyObject = msg_send![ns_app, delegate];
        let delegate = delegate.as_mut().ok_or("Missing AppKit delegate")?;
        let mut class = ClassBuilder::new(c"ScholarNoteLMExitDelegate", delegate.class())
            .ok_or("Exit delegate already installed")?;
        class.add_method(sel!(applicationShouldTerminate:), should_terminate as extern "C-unwind" fn(_, _, _) -> _);
        APP.set(app.clone()).map_err(|_| "Exit handle already installed")?;
        AnyObject::set_class(delegate, class.register());
        // AppKit caches optional delegate callbacks when the delegate is set.
        let _: () = msg_send![ns_app, setDelegate: std::ptr::null_mut::<AnyObject>()];
        let _: () = msg_send![ns_app, setDelegate: delegate as *mut AnyObject];
    }
    Ok(())
}
