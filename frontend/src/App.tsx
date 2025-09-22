import React, { useState } from 'react'
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
  const [isNavOpen, setIsNavOpen] = useState(false)

  return (
    <BrowserRouter>
      <div className="relative min-h-screen bg-surface-base">
        <div
          className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(circle_at_top_right,_rgba(47,111,237,0.12),_transparent_55%)]"
          aria-hidden
        />
        <div className="flex min-h-screen">
          <Nav
            isOpen={isNavOpen}
            onClose={() => setIsNavOpen(false)}
            onNavigate={() => setIsNavOpen(false)}
          />
          <div className="flex flex-1 flex-col">
            <Topbar onMenuClick={() => setIsNavOpen((prev) => !prev)} />
            <main className="relative flex-1 overflow-y-auto px-4 pb-16 pt-8 sm:px-8 lg:px-12">
              <div className="mx-auto flex w-full max-w-7xl flex-col gap-12 pb-12">
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
            </main>
          </div>
        </div>
      </div>
    </BrowserRouter>
  )
}

export default App
