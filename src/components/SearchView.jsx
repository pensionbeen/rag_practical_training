import React, { useState } from 'react'
import SearchPanel from './SearchPanel'
import SearchSidebar from './SearchSidebar'

export default function SearchView() {
  const [sidebarOpen, setSidebarOpen] = useState(false)

  return (
    <div className="relative">
      <div className="flex justify-end mb-4">
        <button
          onClick={() => setSidebarOpen(true)}
          className="px-3 py-1 rounded" style={{ border: '1px solid var(--border)', background: 'white' }}>
          자료 설정
        </button>
      </div>
      <SearchPanel />
      <SearchSidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
    </div>
  )
}
