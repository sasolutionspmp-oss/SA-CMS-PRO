import { useSyncExternalStore, type MouseEvent, type ReactNode } from 'react';
import { Link } from '@fluentui/react-components';

export function navigate(href: string, replace = false) {
  if (replace) window.history.replaceState(null, '', href);
  else window.history.pushState(null, '', href);
  window.dispatchEvent(new Event('popstate'));
}
export function useLocation() {
  return useSyncExternalStore(
    callback => { window.addEventListener('popstate', callback); return () => window.removeEventListener('popstate', callback); },
    () => window.location.pathname + window.location.search,
  );
}
export function AppLink({ href, children, className, label }: { href: string; children: ReactNode; className?: string; label?: string }) {
  function follow(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); navigate(href);
  }
  return <Link href={href} onClick={follow} className={className} aria-label={label}>{children}</Link>;
}
