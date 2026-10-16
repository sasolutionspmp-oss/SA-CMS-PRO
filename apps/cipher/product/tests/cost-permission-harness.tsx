// Test-only mounted-prop harness. It is never imported by the production entry.
import '@ui5/webcomponents-react/dist/Assets.js';
import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ThemeProvider } from '@ui5/webcomponents-react';
import { setTheme } from '@ui5/webcomponents-base/dist/config/Theme.js';
import { api } from '../src/api/client';
import CostMasters from '../src/CostMasters';
import '../src/styles.css';
function Fixture() {
  const [canWrite, setCanWrite] = useState(true);
  useEffect(() => { const revoke = () => setCanWrite(false); window.addEventListener('test:cost-write-loss', revoke); return () => window.removeEventListener('test:cost-write-loss', revoke); }, []);
  return <ThemeProvider><CostMasters company="TEST-AEC" kind="code" capabilities={['project.cost.read', ...(canWrite ? ['project.cost.write'] : [])]} navigate={() => { throw new Error('This recovery case must remain mounted.'); }} /></ThemeProvider>;
}
void Promise.all([setTheme('sap_horizon'), api.session()]).then(() => createRoot(document.getElementById('root')!).render(<Fixture />));
