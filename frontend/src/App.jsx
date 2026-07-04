import React, { useState } from 'react'
import Header from './components/Header'
import Tabs from './components/Tabs'
import SearchView from './components/SearchView'
import PapersPanel from './components/PapersPanel'

export default function App() {
  const [activeTab, setActiveTab] = useState('search')
  const [vaultPath, setVaultPath] = useState(() => localStorage.getItem('obsidian_vault_path') || '')

  const handleSaveVaultPath = (newPath) => {
    setVaultPath(newPath)
    localStorage.setItem('obsidian_vault_path', newPath)
  }

  return (
    <div className="page-shell">
      <Header />
      <Tabs active={activeTab} onChange={setActiveTab} />
      <main className="panel">
        {activeTab === 'search' ? (
          <SearchView vaultPath={vaultPath} onSaveVaultPath={handleSaveVaultPath} />
        ) : (
          <PapersPanel vaultPath={vaultPath} />
        )}
      </main>
    </div>
  )
}

