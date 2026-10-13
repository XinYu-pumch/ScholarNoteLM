/** Drain older autosaves, then persist the newest state, including changes during I/O. */
export async function flushLatestState<T>(previous: Promise<unknown>, latest: () => T, write: (state: T) => Promise<void>): Promise<T> {
  await previous.catch(()=>{});
  let snapshot:T;
  do { snapshot=latest(); await write(snapshot); } while(snapshot!==latest());
  return snapshot;
}

/** Native approval is sent only after both draft decisions and local writes finish. */
export async function resolveCloseRequest(options: {
  canLeave: () => Promise<boolean>;
  flush: () => Promise<void>;
  answer: (allow: boolean) => Promise<void>;
  saving: (value: boolean) => void;
  error: (error: unknown) => void;
}) {
  let allow=false;
  try {
    if(await options.canLeave()) {
      options.saving(true);
      await options.flush();
      allow=true;
    }
  } catch(error) { options.error(error); }
  finally {
    options.saving(false);
    try { await options.answer(allow); } catch(error) { options.error(error); }
  }
}
