import React, { useState } from 'react'
import Header from './components/Header'
import Tabs from './components/Tabs'
import SearchView from './components/SearchView'
import PapersPanel from './components/PapersPanel'

export default function App() {
  const [activeTab, setActiveTab] = useState('search')

  return (
    <div className="page-shell">
      <Header />
      <Tabs active={activeTab} onChange={setActiveTab} />
      <main className="panel">
        {activeTab === 'search' ? <SearchView /> : <PapersPanel />}
      </main>
    </div>
  )
}
