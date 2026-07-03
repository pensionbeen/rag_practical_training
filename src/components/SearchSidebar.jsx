import React, { useState, useRef, useEffect } from 'react'
import { X } from 'lucide-react'

export default function SearchSidebar({ open, onClose }) {
  const [vaultPath, setVaultPath] = useState('')
  const [uploads, setUploads] = useState([])
  const fileRef = useRef(null)

  useEffect(() => {
    if (!open) return
    // focus or other side-effects
  }, [open])

  const onFiles = e => {
    const files = Array.from(e.target.files || [])
    const list = files.map((f, i) => ({ id: Date.now() + i, name: f.name, status: 'queued' }))
    setUploads(prev => [...prev, ...list])
    // TODO: upload FormData POST to file upload API
  }

  const removeUpload = id => setUploads(prev => prev.filter(p => p.id !== id))

  return (
    <>
      {open && <div className="fixed inset-0 bg-black/30" onClick={onClose} />}
      <aside className={`fixed top-0 right-0 h-full w-96 transform ${open ? 'translate-x-0' : 'translate-x-full'} transition-transform duration-200`} style={{ background: 'white', borderLeft: '1px solid var(--border)' }}>
        <div className="p-4">
          <div className="flex justify-between items-center">
            <h3 className="font-medium">자료 설정</h3>
            <button onClick={onClose}><X /></button>
          </div>

          <div className="mt-4">
            <label className="block text-sm font-mono">옵시디언 볼트 경로</label>
            <div className="flex gap-2 mt-2">
              <input value={vaultPath} onChange={e => setVaultPath(e.target.value)} className="flex-1 p-2 rounded" style={{ border: '1px solid var(--border)' }} placeholder="C:\\Users\\...\\vault" />
              <button className="px-3" onClick={() => {/* TODO: save vault path API */}}>저장</button>
            </div>
          </div>

          <div className="mt-6">
            <label className="block text-sm font-mono">파일 업로드 (드래그앤드롭 지원)</label>
            <div className="mt-2 p-4 border border-dashed rounded" onClick={() => fileRef.current?.click()}>
              <input ref={fileRef} type="file" multiple className="hidden" onChange={onFiles} />
              <div className="text-sm text-[var(--text-2)]">파일을 클릭하거나 드래그하여 업로드하세요</div>
            </div>
            <ul className="mt-3 space-y-2">
              {uploads.map(u => (
                <li key={u.id} className="flex items-center justify-between p-2 border rounded">
                  <div>
                    <div className="text-sm">{u.name}</div>
                    <div className="text-xs font-mono text-[var(--text-3)]">{u.status}</div>
                  </div>
                  <div>
                    <button onClick={() => removeUpload(u.id)}>삭제</button>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </aside>
    </>
  )
}
