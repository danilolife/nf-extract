import type { AnalysisResponse } from './types'
import type { RecipientProfile } from './components/EditInvoiceModal'

const API_URL = import.meta.env.VITE_API_URL || ''

export async function analyzeFiles(files: File[]): Promise<AnalysisResponse> {
  const form = new FormData()
  files.forEach((file) => form.append('files', file))

  const response = await fetch(`${API_URL}/api/analyze`, {
    method: 'POST',
    body: form
  })

  if (!response.ok) {
    let message = 'Não foi possível analisar os arquivos.'
    try {
      const payload = await response.json()
      message = payload.detail || message
    } catch {
      // keep fallback message
    }
    throw new Error(message)
  }

  return response.json()
}

export async function fetchRecipients(): Promise<RecipientProfile[]> {
  const response = await fetch(`${API_URL}/api/recipients`)
  if (!response.ok) return []
  const payload = await response.json()
  return payload.recipients || []
}
