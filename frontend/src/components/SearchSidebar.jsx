import React, { useState, useEffect, useRef } from 'react'
import { uploadDocument, reindexVault } from '../config/api'

export default function SearchSidebar({ open, onClose, vaultPath: initialVaultPath, onSaveVaultPath }) {
  const [vaultPath, setVaultPath] = useState(initialVaultPath)
  const [uploads, setUploads] = useState([])
  const fileRef = useRef(null)

  useEffect(() => {
    setVaultPath(initialVaultPath)
  }, [initialVaultPath])

  const updateUploadStatus = (id, status) => {
    setUploads(prev => prev.map(item => (item.id === id ? { ...item, status } : item)))
  }

  const processFile = async (id, file) => {
    try {
      updateUploadStatus(id, '청킹 및 개념 추출 중')
      const { saved_files: savedFiles } = await uploadDocument(file, vaultPath || null)

      updateUploadStatus(id, '벡터 임베딩 중')
      await reindexVault(vaultPath || null)

      updateUploadStatus(id, `완료 (노트 ${savedFiles.length}개 저장)`)
    } catch (err) {
      updateUploadStatus(id, `실패: ${err.message}`)
    }
  }

  const handleFiles = event => {
    const files = Array.from(event.target.files || event.dataTransfer?.files || [])
    const nextUploads = files.map((file, index) => ({ id: `${Date.now()}-${index}`, name: file.name, status: '대기 중' }))
    setUploads(prev => [...prev, ...nextUploads])
    nextUploads.forEach((item, index) => processFile(item.id, files[index]))
  }

  const removeUpload = id => setUploads(prev => prev.filter(item => item.id !== id))

  const handleSave = () => {
    onSaveVaultPath(vaultPath)
    alert('옵시디언 볼트 경로가 저장되었습니다.')
  }

  return (
    <>
      {open && <div className="drawer-backdrop" onClick={onClose} />}
      <aside className={`resource-drawer ${open ? 'drawer-open' : ''}`}>
        <div className="drawer-header">
          <div>
            <p className="drawer-title">자료 설정</p>
          </div>
          <button type="button" className="drawer-close" onClick={onClose}>닫기</button>
        </div>

        <div className="drawer-section">
          <label>옵시디언 볼트 경로</label>
          <div className="drawer-row">
            <input
              className="drawer-input"
              value={vaultPath}
              onChange={e => setVaultPath(e.target.value)}
              placeholder="C:\\Users\\...\\vault"
            />
            <button type="button" className="drawer-button" onClick={handleSave}
            >저장</button>
          </div>
        </div>


        <div className="drawer-section">
          <label>파일 업로드 (드래그앤드롭 지원)</label>
          <div
            className="upload-area"
            onClick={() => fileRef.current?.click()}
            onDragOver={e => e.preventDefault()}
            onDrop={e => {
              e.preventDefault()
              handleFiles(e)
            }}
          >
            <input ref={fileRef} type="file" multiple style={{ display: 'none' }} onChange={handleFiles} />
            파일을 클릭하거나 드래그하여 업로드하세요
          </div>

          <div className="upload-list">
            {uploads.map(item => (
              <div key={item.id} className="upload-item">
                <div>
                  <div>{item.name}</div>
                  <div className="card-meta">{item.status}</div>
                </div>
                <button type="button" onClick={() => removeUpload(item.id)}>삭제</button>
              </div>
            ))}
          </div>
        </div>
      </aside>
    </>
  )
}
