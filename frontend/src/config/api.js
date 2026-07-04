const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export async function askQuestion(query, vaultPath = null, signal = null) {
  const response = await fetch(`${API_BASE_URL}/api/v1/ask`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      query,
      vault_path: vaultPath,
    }),
    signal,
  })

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null)
    const error = new Error(errorBody?.detail || `API Error: ${response.status}`)
    error.status = response.status
    throw error
  }

  return response.json()
}

export async function saveConcept(conceptName, content, category = null, vaultPath = null) {
  const response = await fetch(`${API_BASE_URL}/api/v1/obsidian/save_concept`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      concept_name: conceptName,
      content,
      category,
      vault_path: vaultPath,
    }),
  })

  if (!response.ok) {
    throw new Error(`API Error: ${response.status}`)
  }

  return response.json()
}

export async function saveReviewNote(question, answer, sourceFile = null, vaultPath = null) {
  const response = await fetch(`${API_BASE_URL}/api/v1/obsidian/save`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      question,
      answer,
      source_file: sourceFile,
      vault_path: vaultPath,
    }),
  })

  if (!response.ok) {
    throw new Error(`API Error: ${response.status}`)
  }

  return response.json()
}

export async function uploadDocument(file, vaultPath = null) {
  const formData = new FormData()
  formData.append('file', file)
  if (vaultPath) {
    formData.append('vault_path', vaultPath)
  }

  const response = await fetch(`${API_BASE_URL}/api/v1/obsidian/upload_concepts`, {
    method: 'POST',
    body: formData,
  })

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null)
    throw new Error(errorBody?.detail || `API Error: ${response.status}`)
  }

  return response.json()
}

export async function reindexVault(vaultPath = null) {
  const response = await fetch(`${API_BASE_URL}/api/v1/obsidian/reindex`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      vault_path: vaultPath,
    }),
  })

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null)
    throw new Error(errorBody?.detail || `API Error: ${response.status}`)
  }

  return response.json()
}

export async function getFolders(vaultPath = null) {
  const response = await fetch(`${API_BASE_URL}/api/v1/obsidian/folders`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      vault_path: vaultPath,
    }),
  })

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null)
    throw new Error(errorBody?.detail || `API Error: ${response.status}`)
  }

  return response.json()
}

export async function getConcepts(vaultPath = null) {
  const response = await fetch(`${API_BASE_URL}/api/v1/obsidian/concepts`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      vault_path: vaultPath,
    }),
  })

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null)
    throw new Error(errorBody?.detail || `API Error: ${response.status}`)
  }

  return response.json()
}

export async function searchPapers(query, signal = null) {
  const response = await fetch(`${API_BASE_URL}/api/v1/papers/search`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ query }),
    signal,
  })

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null)
    throw new Error(errorBody?.detail || `API Error: ${response.status}`)
  }

  return response.json()
}

export async function getSimilarDocs(query, vaultPath = null) {
  const response = await fetch(`${API_BASE_URL}/api/v1/obsidian/similar_docs`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      query,
      vault_path: vaultPath,
    }),
  })

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null)
    throw new Error(errorBody?.detail || `API Error: ${response.status}`)
  }

  const paths = await response.json()
  return paths.map(p => {
    const parts = p.split(/[/\\]/)
    const filename = parts[parts.length - 1]
    return filename.endsWith('.md') ? filename.slice(0, -3) : filename
  })
}

export async function checkServerHealth() {
  try {
    const response = await fetch(`${API_BASE_URL}/`, {
      method: 'GET',
    })
    return response.ok
  } catch (error) {
    return false
  }
}
