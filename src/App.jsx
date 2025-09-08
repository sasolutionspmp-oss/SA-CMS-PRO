import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom';
import Ingest from './pages/Ingest';
import Search from './pages/Search';
import Estimator from './pages/Estimator';
import History from './pages/History';
import PM from './pages/PM';
import Compliance from './pages/Compliance';
import Safety from './pages/Safety';
import Finance from './pages/Finance';
import Settings from './pages/Settings';

export default function App() {
  return (
    <Router>
      <header aria-label="Top bar" className="top-bar">
        <h1>SA-CMS</h1>
      </header>
      <div className="container">
        <nav aria-label="Main navigation" className="side-nav">
          <ul>
            <li><Link to="/ingest">Ingest</Link></li>
            <li><Link to="/search">Search</Link></li>
            <li><Link to="/estimator">Estimator</Link></li>
            <li><Link to="/history">History</Link></li>
            <li><Link to="/pm">PM</Link></li>
            <li><Link to="/compliance">Compliance</Link></li>
            <li><Link to="/safety">Safety</Link></li>
            <li><Link to="/finance">Finance</Link></li>
            <li><Link to="/settings">Settings</Link></li>
          </ul>
        </nav>
        <main tabIndex="-1" className="content">
          <Routes>
            <Route path="/ingest" element={<Ingest />} />
            <Route path="/search" element={<Search />} />
            <Route path="/estimator" element={<Estimator />} />
            <Route path="/history" element={<History />} />
            <Route path="/pm" element={<PM />} />
            <Route path="/compliance" element={<Compliance />} />
            <Route path="/safety" element={<Safety />} />
            <Route path="/finance" element={<Finance />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/" element={<Search />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
}
