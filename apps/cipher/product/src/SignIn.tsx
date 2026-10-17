import { useState } from 'react';
import { Button, Icon, Input, Label } from '@ui5/webcomponents-react';
import { api, ApiError } from './api/client';
import { Failure } from './components';

export default function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError>();
  const submit = async () => {
    if (!username.trim() || !password || busy) return;
    setBusy(true); setError(undefined);
    try { await api.signIn(username.trim(), password); setPassword(''); onSignedIn(); }
    catch (failure) { setError(failure as ApiError); }
    finally { setBusy(false); }
  };
  return <div className="sign-in-page"><section className="sign-in-card" aria-labelledby="sign-in-title"><div className="sign-in-brand"><img src="/cipher-mark.svg" alt="" /><span>Cipher</span></div><span className="eyebrow">THE AEC/CMS PRO</span><h1 id="sign-in-title">Sign in to your workspace</h1><p>Projects, source documents and the next step. Together in one place.</p>
    <form onSubmit={event => { event.preventDefault(); void submit(); }}>
      {error && <Failure error={error} />}
      <Label for="sign-in-user" required>Email or username</Label><Input id="sign-in-user" accessibleName="Email or username" name="username" value={username} disabled={busy} onInput={event => setUsername(event.currentTarget!.value)} />
      <Label for="sign-in-password" required>Password</Label><Input id="sign-in-password" accessibleName="Password" type="Password" name="password" value={password} disabled={busy} onInput={event => setPassword(event.currentTarget!.value)} />
      <Button design="Emphasized" type="Submit" disabled={busy || !username.trim() || !password}>{busy ? 'Signing in…' : 'Sign in'}</Button>
    </form><div className="sign-in-footnote"><Icon name="locked" /><span>Your account controls access to companies, projects and documents.</span></div>
  </section></div>;
}
