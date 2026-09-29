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
  supplier_profile_id: string | null
  supplier_recognized: boolean
  issue_date: string | null
  total_amount: string | null
  volume_count: number | null
  volume_species: string | null
  volume_mode: 'per_invoice' | 'shared_document'
  pages: number[]
  source_file: string | null
  source_kind: 'pdf' | 'imagem'
  extraction_method: 'texto' | 'ocr'
  ocr_rotation: number
}

export type AnalysisGroup = {
  group_type: 'carga' | 'destinatario'
  carga: string | null
  recipient_cnpj: string
  recipient_name: string
  issuer_name: string
  issuer_cnpj: string
  key_count: number
  volume_total: number
  volume_records: number
  invoices: Invoice[]
}

export type AnalysisResponse = {
  summary: {
    files: number
    unique_keys: number
    groups: number
    cargas: number
    recipient_cnpjs: number
    issuers: number
    ocr_records: number
    image_records: number
    recognized_supplier_records: number
    unknown_supplier_records: number
    volume_records: number
    missing_volume_records: number
    total_volumes: number
  }
  files: { filename: string; size_bytes: number; unique_keys: number; kind: 'pdf' | 'imagem'; ocr_used: boolean; volume_records: number; total_volumes: number }[]
  groups: AnalysisGroup[]
  warnings: string[]
}
