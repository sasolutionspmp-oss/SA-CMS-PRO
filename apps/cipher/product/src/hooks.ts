import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from './api/client';

export function useResource<T>(key: string | null, loader: (signal: AbortSignal) => Promise<T>) {
  const loadRef = useRef(loader);
  loadRef.current = loader;
  const [state, setState] = useState<{ key: string | null; data?: T; error?: ApiError; loading: boolean }>({ key, loading: Boolean(key) });
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision(value => value + 1), []);
  useEffect(() => {
    if (!key) { setState({ key, loading: false }); return; }
    const controller = new AbortController();
    setState(previous => ({ key, data: previous.key === key ? previous.data : undefined, loading: true }));
    loadRef.current(controller.signal).then(data => {
      if (!controller.signal.aborted) setState({ key, data, loading: false });
    }).catch(error => {
      if (!controller.signal.aborted) setState({ key, error: error instanceof ApiError ? error : new ApiError('The workspace response could not be read.', 'INVALID_RESPONSE', 0), loading: false });
    });
    return () => controller.abort();
  }, [key, revision]);
  // Never expose a previous company's/project's data during a scope change.
  return state.key === key ? { ...state, refresh } : { key, loading: Boolean(key), data: undefined, error: undefined, refresh };
}

export function useRoute() {
  const [path, setPath] = useState(window.location.pathname + window.location.search);
  useEffect(() => {
    const changed = () => setPath(window.location.pathname + window.location.search);
    window.addEventListener('popstate', changed);
    return () => window.removeEventListener('popstate', changed);
  }, []);
  const navigate = useCallback((next: string) => {
    window.history.pushState({}, '', next);
    setPath(next);
    document.getElementById('main-content')?.focus();
  }, []);
  return { path, navigate };
}

export function date(value?: string | null) {
  if (!value) return 'Not scheduled';
  const parsed = new Date(value.includes('T') ? value : `${value}T12:00:00`);
  return Number.isNaN(parsed.getTime()) ? 'Not scheduled' : new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' }).format(parsed);
}
export function human(value: string) { return value.replace(/[_.-]/g, ' ').replace(/^\w/, letter => letter.toUpperCase()); }
