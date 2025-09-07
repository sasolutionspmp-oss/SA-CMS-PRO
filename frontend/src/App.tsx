import React from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Nav from './components/ui/Nav'
import Topbar from './components/ui/Topbar'
import Ingest from './pages/Ingest'
import Search from './pages/Search'
import Estimate from './pages/Estimate'
import Compliance from './pages/Compliance'
import PM from './pages/PM'
import Safety from './pages/Safety'
import Finance from './pages/Finance'
import Settings from './pages/Settings'
import History from './pages/History'

function App() {
  return (
    <BrowserRouter>
      <div className="flex h-screen">
        <Nav />
        <div className="flex-1 flex flex-col">
          <Topbar />
          <div className="p-4 flex-1 overflow-auto">
            <Routes>
              <Route path="/" element={<Ingest />} />
              <Route path="/search" element={<Search />} />
              <Route path="/estimate" element={<Estimate />} />
              <Route path="/compliance" element={<Compliance />} />
              <Route path="/pm" element={<PM />} />
              <Route path="/safety" element={<Safety />} />
              <Route path="/finance" element={<Finance />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/history" element={<History />} />
            </Routes>
          </div>
        </div>
      </div>
    </BrowserRouter>
  )
}

export default App
