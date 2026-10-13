#[derive(Default)]
pub struct ExitGuard {
    pub ready: bool,
    approved: bool,
    pending: Option<u64>,
    sequence: u64,
}

impl ExitGuard {
    pub fn intercept(&self) -> bool { self.ready && !self.approved }
    pub fn request(&mut self) -> Option<u64> {
        if self.pending.is_some() { return None; }
        self.sequence += 1;
        self.pending = Some(self.sequence);
        self.pending
    }
    pub fn answer(&mut self, ticket: u64, allow: bool) -> bool {
        if self.pending != Some(ticket) { return false; }
        self.pending = None;
        self.approved = allow;
        allow
    }
    pub fn reset(&mut self, ready: bool) {
        self.ready = ready; self.pending = None; self.approved = false;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn close_and_quit_share_one_pending_decision() {
        let mut guard = ExitGuard::default(); guard.reset(true);
        let ticket = guard.request().unwrap();
        assert!(guard.intercept()); assert_eq!(guard.request(), None);
        assert!(!guard.answer(ticket, false)); assert!(guard.intercept());
        let next = guard.request().unwrap();
        assert!(!guard.answer(ticket, true)); assert!(guard.intercept());
        assert!(guard.answer(next, true)); assert!(!guard.intercept());
    }
    #[test]
    fn reload_invalidates_old_approvals() {
        let mut guard = ExitGuard::default(); guard.reset(true);
        let ticket = guard.request().unwrap(); guard.reset(true);
        assert!(!guard.answer(ticket, true)); assert!(guard.intercept());
    }
}
