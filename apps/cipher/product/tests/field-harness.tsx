// Explicit browser fixture entry. The normal application never imports this file.
import '../src/local-ui5-fonts';
import '@ui5/webcomponents-react/dist/Assets.js';
import '@ui5/webcomponents-icons/dist/refresh.js';
import '@ui5/webcomponents-icons/dist/decline.js';
import '@ui5/webcomponents-icons/dist/folder-blank.js';
import '@ui5/webcomponents-icons/dist/navigation-left-arrow.js';
import '@ui5/webcomponents-icons/dist/navigation-right-arrow.js';
import { ThemeProvider, Button, MessageStrip } from '@ui5/webcomponents-react';
import { setTheme } from '@ui5/webcomponents-base/dist/config/Theme.js';
import { createRoot } from 'react-dom/client';
import { useCallback, useState } from 'react';
import FieldRecords from '../src/FieldRecords';
import { api } from '../src/api/client';
import { useResource } from '../src/hooks';
import '../src/styles.css';
void setTheme('sap_horizon');
function Harness() {
  const [route, setRoute] = useState(new URLSearchParams(location.search)), [locked, setLocked] = useState(false);
  const session = useResource('field-harness-session', signal => api.session(signal)), project = useResource('field-harness-project', signal => api.project('Fixture Company', 'FIELD-PROJECT', signal));
  const navigate = useCallback((path: string) => { const tail = path.split('/field/')[1]?.split('/') || ['daily']; const next = new URLSearchParams({ section: tail[0], ...(tail[1] ? { record: tail[1] } : {}) }); history.pushState({}, '', '/tests/field-harness.html?' + next); setRoute(next); window.scrollTo(0, 0); }, []);
  return <ThemeProvider><MessageStrip hideCloseButton>Synthetic Field browser contract fixtures. Native HTTP/database qualification remains separate.</MessageStrip><div className="field-inline-actions"><Button disabled={locked} onClick={() => { session.refresh(); project.refresh(); }}>Refresh fixture access</Button><span>Fixture Company · Field project</span></div><main id="main-content"><FieldRecords active company="Fixture Company" user={session.data?.user || ''} personId={session.data?.person.id || ''} project={project.data} contextLoading={session.loading || project.loading} contextError={session.error || project.error} section={route.get('section') || 'daily'} recordId={route.get('record') || undefined} navigationLocked={false} navigate={navigate} onLockedChange={setLocked} /></main></ThemeProvider>;
}
createRoot(document.getElementById('root')!).render(<Harness />);
