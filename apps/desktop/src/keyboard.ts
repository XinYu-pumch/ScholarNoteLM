import type {KeyboardEvent} from 'react';
export function isComposing(event: KeyboardEvent) { return event.nativeEvent.isComposing || event.nativeEvent.keyCode===229; }
export function isSendShortcut(event: KeyboardEvent) { return event.key==='Enter'&&(event.metaKey||event.ctrlKey)&&!isComposing(event); }
