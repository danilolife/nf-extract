export type Invoice = {
  access_key: string
  nf_number: string
  series: string
  model: string
  valid_key: boolean
  carga: string | null
  recipient_name: string | null
  recipient_cnpj: string | null
  issuer_name: string | null
  issuer_cnpj: string | null
  issue_date: string | null
  total_amount: string | null
  pages: number[]
  source_file: string | null
}

export type AnalysisGroup = {
  group_type: 'carga' | 'destinatario'
  carga: string | null
  recipient_cnpj: string
  recipient_name: string
  issuer_name: string
  issuer_cnpj: string
  key_count: number
  invoices: Invoice[]
}

export type AnalysisResponse = {
  summary: {
    files: number
    unique_keys: number
    groups: number
    cargas: number
    recipient_cnpjs: number
  }
  files: { filename: string; size_bytes: number; unique_keys: number }[]
  groups: AnalysisGroup[]
  warnings: string[]
}
