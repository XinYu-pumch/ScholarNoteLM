type Guard = () => boolean | Promise<boolean>;
const guards = new Set<Guard>();
let checking = false;

export function registerNavigationGuard(guard: Guard) {
  guards.add(guard);
  return () => { guards.delete(guard); };
}

// Keep the original destination while a decision or save is pending.
export async function canNavigate(): Promise<boolean> {
  if (checking) return false;
  checking = true;
  try {
    for (const guard of [...guards]) {
      if (guards.has(guard) && !await guard()) return false;
    }
    return true;
  } finally { checking = false; }
}

export function requestNavigation(action: () => void) {
  void canNavigate().then(allowed => { if (allowed) action(); });
}
