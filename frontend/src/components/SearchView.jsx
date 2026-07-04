import React, { useState } from 'react'
import SearchPanel from './SearchPanel'
import SearchSidebar from './SearchSidebar'

export default function SearchView({ vaultPath, onSaveVaultPath }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)

  return (
    <div>
      <div className="panel-top">
        <p className="panel-label">개인 노트 검색과 RAG 결과</p>
        <button type="button" className="outline-button" onClick={() => setSidebarOpen(true)}>
          자료 설정
        </button>
      </div>
      <SearchPanel vaultPath={vaultPath} />
      <SearchSidebar
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        vaultPath={vaultPath}
        onSaveVaultPath={onSaveVaultPath}
      />
    </div>
  )
}


