import React, { useState } from 'react'
import Header from './components/Header'
import Tabs from './components/Tabs'
import SearchView from './components/SearchView'
import PapersPanel from './components/PapersPanel'

export default function App() {
  const [activeTab, setActiveTab] = useState('search')

  return (
    <div className="min-h-screen p-6" style={{ background: 'var(--bg)', color: 'var(--text)' }}>
      <div className="max-w-6xl mx-auto">
        <Header />
        <Tabs active={activeTab} onChange={setActiveTab} />
        <main className="mt-6">
          {activeTab === 'search' ? <SearchView /> : <PapersPanel />}
        </main>
      </div>
    </div>
  )
}
