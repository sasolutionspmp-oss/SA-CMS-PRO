// Test-only authority-change harness; never imported by the production entry.
import '../src/local-ui5-fonts';
import '@ui5/webcomponents-react/dist/Assets.js';
import '@ui5/webcomponents-icons/dist/refresh.js';
import '@ui5/webcomponents-icons/dist/history.js';
import '@ui5/webcomponents-icons/dist/locked.js';
import '@ui5/webcomponents-icons/dist/navigation-left-arrow.js';
import '@ui5/webcomponents-icons/dist/navigation-right-arrow.js';
import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ThemeProvider } from '@ui5/webcomponents-react';
import { setTheme } from '@ui5/webcomponents-base/dist/config/Theme.js';
import CompanyActivity from '../src/CompanyActivity';
import '../src/styles.css';
function Fixture() {
  const [scope, setScope] = useState({ company: 'TEST-AEC', user: 'original-user', personId: 'original-person', capabilities: ['company.read', 'commercial.read', 'estimate.read', 'document.read'], navigationLocked: false });
  useEffect(() => { const changed = (event: Event) => setScope(current => ({ ...current, ...(event as CustomEvent).detail })); window.addEventListener('test:activity-context', changed); return () => window.removeEventListener('test:activity-context', changed); }, []);
  return <ThemeProvider><CompanyActivity {...scope} navigate={() => { throw new Error('This authority test must remain mounted.'); }} /></ThemeProvider>;
}
void setTheme('sap_horizon').then(() => createRoot(document.getElementById('root')!).render(<Fixture />));
