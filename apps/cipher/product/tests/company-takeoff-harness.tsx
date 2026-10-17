// Synthetic mounted-authority test entry; never imported by the product.
import '../src/local-ui5-fonts';
import '@ui5/webcomponents-react/dist/Assets.js';
import '@ui5/webcomponents-icons/dist/refresh.js';
import '@ui5/webcomponents-icons/dist/measure.js';
import '@ui5/webcomponents-icons/dist/add.js';
import '@ui5/webcomponents-icons/dist/locked.js';
import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ThemeProvider } from '@ui5/webcomponents-react';
import { setTheme } from '@ui5/webcomponents-base/dist/config/Theme.js';
import CompanyTakeoff from '../src/CompanyTakeoff';
import { api } from '../src/api/client';
import '../src/styles.css';
function Fixture() {
  const [scope, setScope] = useState({ active: true, company: 'TEST-AEC', user: 'test.pm@example.invalid', personId: 'TEST-PERSON-001', capabilities: ['company.read', 'estimate.read', 'estimate.write', 'document.read'], setId: '71000000-0000-4000-8000-000000000001', navigationLocked: false });
  const [locked, setLocked] = useState(false);
  useEffect(() => { const change = (e: Event) => setScope(v => ({ ...v, ...(e as CustomEvent).detail })); window.addEventListener('test:takeoff-context', change); return () => window.removeEventListener('test:takeoff-context', change); }, []);
  return <ThemeProvider><div data-testid="command-lock">{String(locked)}</div><CompanyTakeoff {...scope} onLockedChange={setLocked} navigate={() => { throw new Error('Mounted authority test cannot navigate.'); }} /></ThemeProvider>;
}
void Promise.all([setTheme('sap_horizon'), api.session()]).then(() => createRoot(document.getElementById('root')!).render(<Fixture />));
