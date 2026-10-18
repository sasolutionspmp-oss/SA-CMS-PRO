// Browser-only synthetic entry. Never imported by the normal application.
import '../src/local-ui5-fonts';
import '@ui5/webcomponents-react/dist/Assets.js';
import '@ui5/webcomponents-icons/dist/folder-blank.js';
import '@ui5/webcomponents-icons/dist/decline.js';
import { ThemeProvider, MessageStrip } from '@ui5/webcomponents-react';
import { setTheme } from '@ui5/webcomponents-base/dist/config/Theme.js';
import { createRoot } from 'react-dom/client';
import { useState } from 'react';
import FieldOffline from '../src/FieldOffline';
import { FieldOfflineVault, OFFLINE_VAULT_DATABASE } from '../src/field-offline-vault';
import { engineeringDigest } from '../src/api/engineering';
import type { Project } from '../src/api/types';
import '../src/styles.css';
void setTheme('sap_horizon');
(window as any).offlineTest = { FieldOfflineVault, OFFLINE_VAULT_DATABASE, engineeringDigest };
(window as any).testVaults = {};
function Harness() {
  const [context, setContext] = useState({ active: true, company: 'Fixture Company', project: 'FIELD-PROJECT', user: 'author@field.test', person: 'FIELD-AUTHOR', identityActive: true, capabilities: ['field.read', 'field.write'] });
  const [locked, setLocked] = useState(false);
  (window as any).setOfflineFixtureContext = (change: Partial<typeof context>) => setContext(previous => ({ ...previous, ...change }));
  return <ThemeProvider><MessageStrip hideCloseButton>Synthetic offline browser fixture. Actual IndexedDB and Web Crypto; mocked domain HTTP. Native integration remains separate.</MessageStrip><p className="caption">Fixture profile navigation: {locked ? 'Original request pending or busy' : 'Available'}</p><FieldOffline active={context.active} company={context.company} user={context.user} personId={context.person} identityActive={context.identityActive} project={{ id: context.project, company: context.company, name: 'Offline fixture project', status: 'Open', capabilities: context.capabilities } as Project} navigationLocked={false} onLockedChange={setLocked} navigate={path => { (window as any).fixtureNavigation = path; }} /></ThemeProvider>;
}
createRoot(document.getElementById('root')!).render(<Harness />);
