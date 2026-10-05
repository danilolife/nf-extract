import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  Clipboard,
  ClipboardList,
  Copy,
  Download,
  FileSearch,
  Filter,
  LayoutGrid,
  List,
  ScanText,
  Moon,
  Pencil,
  RotateCcw,
  Search,
  ShieldCheck,
  Sparkles,
  Sun,
  Trash2,
  X,
} from 'lucide-react'
import { analyzeFiles, fetchRecipients } from './api'
import { EditInvoiceModal, type RecipientProfile } from './components/EditInvoiceModal'
import { ResultGroup } from './components/ResultGroup'
import { UploadZone } from './components/UploadZone'
import type { AnalysisGroup, AnalysisResponse, Invoice } from './types'

type ViewMode = 'groups' | 'table'
type ValidityFilter = 'all' | 'valid' | 'invalid'
type MethodFilter = 'all' | 'texto' | 'ocr'
type SourceKindFilter = 'all' | 'pdf' | 'imagem'
type SupplierStatusFilter = 'all' | 'recognized' | 'unknown'
type VolumeFilter = 'all' | 'with' | 'without'
type SortMode = 'nf-asc' | 'nf-desc' | 'carga-asc' | 'recipient-asc'

type Filters = {
  query: string
  carga: string
  cnpj: string
  issuer: string
  source: string
  date: string
  validity: ValidityFilter
  method: MethodFilter
  sourceKind: SourceKindFilter
  supplierStatus: SupplierStatusFilter
  volumes: VolumeFilter
}

const EMPTY_FILTERS: Filters = {
  query: '',
  carga: '',
  cnpj: '',
  issuer: '',
  source: '',
  date: '',
  validity: 'all',
  method: 'all',
  sourceKind: 'all',
  supplierStatus: 'all',
  volumes: 'all',
}

function normalize(value: string | null | undefined) {
  return (value || '').toLocaleLowerCase('pt-BR').normalize('NFD').replace(/[\u0300-\u036f]/g, '')
}

function moneyToNumber(value: string | null) {
  if (!value) return 0
  return Number(value.replace(/\./g, '').replace(',', '.')) || 0
}

function aggregateVolumeTotal(invoices: Invoice[]) {
  let total = 0
  const seenShared = new Set<string>()
  invoices.forEach((invoice) => {
    if (invoice.volume_count == null) return
    if (invoice.volume_mode === 'shared_document') {
      const token = [invoice.source_file || '', invoice.recipient_cnpj || '', invoice.issue_date || '', invoice.volume_count].join('|')
      if (seenShared.has(token)) return
      seenShared.add(token)
    }
    total += invoice.volume_count
  })
  return total
}

function digitsOnly(value: string | null | undefined) {
  return (value || '').replace(/\D/g, '')
}

function validateCnpj(value: string | null | undefined) {
  const digits = digitsOnly(value)
  if (digits.length !== 14 || new Set(digits).size === 1) return false
  const calc = (base: string, weights: number[]) => {
    const total = [...base].reduce((sum, digit, index) => sum + Number(digit) * weights[index], 0)
    const remainder = total % 11
    return String(remainder < 2 ? 0 : 11 - remainder)
  }
  const d1 = calc(digits.slice(0, 12), [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
  const d2 = calc(digits.slice(0, 12) + d1, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
  return digits.slice(-2) === d1 + d2
}

function keyDerivedNf(accessKey: string) {
  return accessKey.length === 44 ? String(Number(accessKey.slice(25, 34))) : ''
}

function regroupInvoices(invoices: Invoice[]): AnalysisGroup[] {
  const buckets = new Map<string, Invoice[]>()
  invoices.forEach((invoice) => {
    const cnpj = invoice.recipient_cnpj || 'CNPJ NÃO IDENTIFICADO'
    const name = invoice.recipient_name || 'DESTINATÁRIO NÃO IDENTIFICADO'
    const issuer = invoice.issuer_cnpj || 'CNPJ DO FORNECEDOR NÃO IDENTIFICADO'
    const key = invoice.carga
      ? ['carga', invoice.carga, cnpj, issuer, name].join('|')
      : ['destinatario', cnpj, name].join('|')
    buckets.set(key, [...(buckets.get(key) || []), invoice])
  })

  const groups: AnalysisGroup[] = []
  buckets.forEach((items) => {
    items.sort((a, b) => Number(a.nf_number) - Number(b.nf_number))
    const first = items[0]
    const issuerNames = [...new Set(items.map((item) => item.issuer_name).filter(Boolean) as string[])]
    const issuerCnpjs = [...new Set(items.map((item) => item.issuer_cnpj).filter(Boolean) as string[])]
    groups.push({
      group_type: first.carga ? 'carga' : 'destinatario',
      carga: first.carga || null,
      recipient_cnpj: first.recipient_cnpj || 'CNPJ NÃO IDENTIFICADO',
      recipient_name: first.recipient_name || 'DESTINATÁRIO NÃO IDENTIFICADO',
      issuer_name: issuerNames.length === 1 ? issuerNames[0] : 'VÁRIOS FORNECEDORES',
      issuer_cnpj: issuerCnpjs.length === 1 ? issuerCnpjs[0] : 'VÁRIOS CNPJS',
      key_count: items.length,
      volume_total: aggregateVolumeTotal(items),
      volume_records: items.filter((item) => item.volume_count != null).length,
      invoices: items,
    })
  })

  return groups.sort((a, b) => {
    if (Boolean(a.carga) !== Boolean(b.carga)) return a.carga ? -1 : 1
    return (a.carga || '').localeCompare(b.carga || '', 'pt-BR') || a.recipient_cnpj.localeCompare(b.recipient_cnpj, 'pt-BR')
  })
}

function downloadFile(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

function csvEscape(value: string | number | null | undefined) {
  const raw = String(value ?? '')
  return `"${raw.replace(/"/g, '""')}"`
}

function buildCsv(invoices: Invoice[]) {
  const header = ['Carga', 'Fornecedor', 'CNPJ fornecedor', 'Fornecedor cadastrado', 'Perfil fornecedor', 'Destinatário', 'CNPJ destinatário', 'NF', 'Série', 'Modelo', 'Chave de acesso', 'Emissão', 'Valor', 'Volumes', 'Espécie volume', 'Chave válida', 'Arquivo', 'Tipo de origem', 'Leitura', 'Rotação OCR', 'Páginas']
  const rows = invoices.map((invoice) => [
    invoice.carga,
    invoice.issuer_name,
    invoice.issuer_cnpj,
    invoice.supplier_recognized ? 'Sim' : 'Não',
    invoice.supplier_profile_id || '',
    invoice.recipient_name,
    invoice.recipient_cnpj,
    invoice.nf_number,
    invoice.series,
    invoice.model,
    invoice.access_key,
    invoice.issue_date,
    invoice.total_amount,
    invoice.volume_count,
    invoice.volume_species,
    invoice.valid_key ? 'Sim' : 'Não',
    invoice.binding_verified ? 'Verificado' : 'Revisar',
    invoice.source_file,
    invoice.source_kind,
    invoice.extraction_method,
    invoice.ocr_rotation ? `${invoice.ocr_rotation}°` : '',
    invoice.pages.join(', '),
  ])
  return '\uFEFF' + [header, ...rows].map((row) => row.map(csvEscape).join(';')).join('\n')
}

function buildTxt(groups: AnalysisGroup[]) {
  return groups
    .map((group) => {
      const nfs = group.invoices.map((invoice) => invoice.nf_number).join(', ')
      const keys = group.invoices.map((invoice) => invoice.access_key).join('\n')
      const issuers = [...new Set(group.invoices.map((invoice) => invoice.issuer_name).filter(Boolean) as string[])]
      const issuerCnpjs = [...new Set(group.invoices.map((invoice) => invoice.issuer_cnpj).filter(Boolean) as string[])]
      return [
        group.carga ? `CARGA: ${group.carga}` : null,
        `DESTINATÁRIO: ${group.recipient_name}`,
        `CNPJ DESTINATÁRIO: ${group.recipient_cnpj}`,
        issuers.length ? `FORNECEDOR: ${issuers.join(' | ')}` : null,
        issuerCnpjs.length ? `CNPJ FORNECEDOR: ${issuerCnpjs.join(' | ')}` : null,
        `NF: ${nfs}`,
        `VOLUMES: ${aggregateVolumeTotal(group.invoices)}`,
        '',
        keys,
      ].filter((line) => line !== null).join('\n')
    })
    .join('\n\n----------------------------------------\n\n')
}

export default function App() {
  const [files, setFiles] = useState<File[]>([])
  const [result, setResult] = useState<AnalysisResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [toast, setToast] = useState('')
  const [dark, setDark] = useState(false)
  const [viewMode, setViewMode] = useState<ViewMode>('groups')
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS)
  const [sortMode, setSortMode] = useState<SortMode>('nf-asc')
  const [editingInvoice, setEditingInvoice] = useState<Invoice | null>(null)
  const [recipients, setRecipients] = useState<RecipientProfile[]>([])

  useEffect(() => {
    fetchRecipients().then(setRecipients).catch(() => setRecipients([]))
  }, [])

  const canAnalyze = files.length > 0 && !loading

  const allInvoices = useMemo(
    () => result?.groups.flatMap((group) => group.invoices) || [],
    [result],
  )

  const filterOptions = useMemo(() => {
    const cargas = [...new Set(allInvoices.map((invoice) => invoice.carga).filter(Boolean) as string[])].sort()
    const cnpjs = [...new Set(allInvoices.map((invoice) => invoice.recipient_cnpj).filter(Boolean) as string[])].sort()
    const issuers = [...new Set(allInvoices.map((invoice) => invoice.issuer_name).filter(Boolean) as string[])].sort((a, b) => a.localeCompare(b, 'pt-BR'))
    const sources = [...new Set(allInvoices.map((invoice) => invoice.source_file).filter(Boolean) as string[])].sort()
    const dates = [...new Set(allInvoices.map((invoice) => invoice.issue_date).filter(Boolean) as string[])].sort()
    return { cargas, cnpjs, issuers, sources, dates }
  }, [allInvoices])

  const filteredInvoices = useMemo(() => {
    const query = normalize(filters.query.trim())
    const filtered = allInvoices.filter((invoice) => {
      const searchable = normalize([
        invoice.carga,
        invoice.recipient_name,
        invoice.recipient_cnpj,
        invoice.issuer_name,
        invoice.issuer_cnpj,
        invoice.supplier_profile_id,
        invoice.nf_number,
        invoice.series,
        invoice.access_key,
        invoice.issue_date,
        invoice.total_amount,
        invoice.volume_count?.toString(),
        invoice.volume_species,
        invoice.source_file,
        invoice.extraction_method,
        invoice.source_kind,
      ].join(' '))

      if (query && !searchable.includes(query)) return false
      if (filters.carga && invoice.carga !== filters.carga) return false
      if (filters.cnpj && invoice.recipient_cnpj !== filters.cnpj) return false
      if (filters.issuer && invoice.issuer_name !== filters.issuer) return false
      if (filters.source && invoice.source_file !== filters.source) return false
      if (filters.date && invoice.issue_date !== filters.date) return false
      if (filters.validity === 'valid' && !invoice.valid_key) return false
      if (filters.validity === 'invalid' && invoice.valid_key) return false
      if (filters.method !== 'all' && invoice.extraction_method !== filters.method) return false
      if (filters.sourceKind !== 'all' && invoice.source_kind !== filters.sourceKind) return false
      if (filters.supplierStatus === 'recognized' && !invoice.supplier_recognized) return false
      if (filters.supplierStatus === 'unknown' && invoice.supplier_recognized) return false
      if (filters.volumes === 'with' && invoice.volume_count == null) return false
      if (filters.volumes === 'without' && invoice.volume_count != null) return false
      return true
    })

    return [...filtered].sort((a, b) => {
      if (sortMode === 'nf-desc') return Number(b.nf_number) - Number(a.nf_number)
      if (sortMode === 'carga-asc') return (a.carga || '').localeCompare(b.carga || '', 'pt-BR') || Number(a.nf_number) - Number(b.nf_number)
      if (sortMode === 'recipient-asc') return (a.recipient_name || '').localeCompare(b.recipient_name || '', 'pt-BR') || Number(a.nf_number) - Number(b.nf_number)
      return Number(a.nf_number) - Number(b.nf_number)
    })
  }, [allInvoices, filters, sortMode])

  const filteredGroups = useMemo(() => {
    if (!result) return []
    const allowed = new Set(filteredInvoices.map((invoice) => invoice.access_key))
    return result.groups
      .map((group) => {
        const invoices = group.invoices.filter((invoice) => allowed.has(invoice.access_key))
        return { ...group, invoices, key_count: invoices.length, volume_total: aggregateVolumeTotal(invoices), volume_records: invoices.filter((invoice) => invoice.volume_count != null).length }
      })
      .filter((group) => group.invoices.length > 0)
  }, [result, filteredInvoices])

  const filteredTotals = useMemo(() => {
    const cargas = new Set(filteredInvoices.map((invoice) => invoice.carga).filter(Boolean)).size
    const cnpjs = new Set(filteredInvoices.map((invoice) => invoice.recipient_cnpj).filter(Boolean)).size
    const amount = filteredInvoices.reduce((sum, invoice) => sum + moneyToNumber(invoice.total_amount), 0)
    const volumes = aggregateVolumeTotal(filteredInvoices)
    const volumeRecords = filteredInvoices.filter((invoice) => invoice.volume_count != null).length
    return { cargas, cnpjs, amount, volumes, volumeRecords }
  }, [filteredInvoices])

  const hasFilters = Object.entries(filters).some(([key, value]) => ['validity', 'method', 'sourceKind', 'supplierStatus', 'volumes'].includes(key) ? value !== 'all' : Boolean(value))

  function addFiles(incoming: File[]) {
    setFiles((current) => {
      const map = new Map(current.map((file) => [`${file.name}-${file.size}`, file]))
      incoming.forEach((file) => map.set(`${file.name}-${file.size}`, file))
      return Array.from(map.values())
    })
    setResult(null)
    setFilters(EMPTY_FILTERS)
    setError('')
  }

  function clearAttachments() {
    setFiles([])
    setError('')
    setToast('Anexos removidos')
    window.setTimeout(() => setToast(''), 1800)
  }

  function startNewAnalysis() {
    setFiles([])
    setResult(null)
    setFilters(EMPTY_FILTERS)
    setSortMode('nf-asc')
    setViewMode('groups')
    setError('')
    setToast('Pronto para uma nova análise')
    window.scrollTo({ top: 0, behavior: 'smooth' })
    window.setTimeout(() => setToast(''), 1800)
  }

  async function handleAnalyze() {
    if (!canAnalyze) return
    setLoading(true)
    setError('')
    setResult(null)
    setFilters(EMPTY_FILTERS)
    try {
      const data = await analyzeFiles(files)
      setResult(data)
      window.setTimeout(() => document.getElementById('results')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro inesperado ao analisar os arquivos.')
    } finally {
      setLoading(false)
    }
  }

  async function copy(text: string, label = 'Copiado para a área de transferência') {
    try {
      await navigator.clipboard.writeText(text)
      setToast(label)
      window.setTimeout(() => setToast(''), 2200)
    } catch {
      setToast('Não foi possível copiar automaticamente')
      window.setTimeout(() => setToast(''), 2600)
    }
  }

  function setFilter<K extends keyof Filters>(key: K, value: Filters[K]) {
    setFilters((current) => ({ ...current, [key]: value }))
  }

  function applyManualEdit(invoice: Invoice, changes: Partial<Invoice>) {
    if (!result) return
    const cnpj = changes.recipient_cnpj ?? invoice.recipient_cnpj
    const name = changes.recipient_name ?? invoice.recipient_name
    const nfNumber = changes.nf_number ?? invoice.nf_number
    const cnpjValid = validateCnpj(cnpj)
    const profile = recipients.find((item) => digitsOnly(item.cnpj) === digitsOnly(cnpj)) || null
    const normalizedName = normalize(name)
    const nameMatchesRegistry = profile
      ? Boolean(normalizedName) && [profile.display_name, ...profile.aliases].map(normalize).some((candidate) => candidate && (candidate.includes(normalizedName) || normalizedName.includes(candidate)))
      : null
    const nfMatches = nfNumber === keyDerivedNf(invoice.access_key)

    const updated: Invoice = {
      ...invoice,
      ...changes,
      recipient_cnpj_valid: cnpjValid,
      recipient_registered: Boolean(profile),
      recipient_registry_name: profile?.display_name || null,
      recipient_name_matches_registry: nameMatchesRegistry,
      binding_verified: Boolean(invoice.valid_key && cnpjValid && nfMatches && (!profile || nameMatchesRegistry === true)),
      manual_edited: true,
    }

    const invoices = result.groups
      .flatMap((group) => group.invoices)
      .map((item) => item.access_key === invoice.access_key ? updated : item)
    const groups = regroupInvoices(invoices)
    const verified = invoices.filter((item) => item.binding_verified).length
    const registered = invoices.filter((item) => item.recipient_registered).length
    const mismatches = invoices.filter((item) => item.recipient_registered && item.recipient_name_matches_registry === false).length

    setResult({
      ...result,
      groups,
      summary: {
        ...result.summary,
        cargas: new Set(invoices.map((item) => item.carga).filter(Boolean)).size,
        recipient_cnpjs: new Set(invoices.map((item) => item.recipient_cnpj).filter(Boolean)).size,
        verified_bindings: verified,
        review_bindings: invoices.length - verified,
        registered_recipient_records: registered,
        recipient_registry_mismatches: mismatches,
      },
    })
    setEditingInvoice(null)
    setToast('Correção aplicada nesta análise')
    window.setTimeout(() => setToast(''), 2200)
  }

  const visibleKeys = filteredInvoices.map((invoice) => invoice.access_key).join('\n')

  return (
    <div className={dark ? 'app theme-dark' : 'app'}>
      <div className="ambient ambient-one" />
      <div className="ambient ambient-two" />
      <div className="ambient ambient-three" />

      <header className="topbar">
        <div className="brand">
          <span className="brand-mark"><ClipboardList size={19} /></span>
          <div>
            <strong>NF Extract</strong>
            <small>DANFE workspace</small>
          </div>
        </div>
        <div className="topbar-actions">
          <span className="status-pill"><span className="status-dot" /> Processamento privado</span>
          <button className="icon-button theme-button" onClick={() => setDark((value) => !value)} aria-label="Alternar tema">
            {dark ? <Sun size={17} /> : <Moon size={17} />}
          </button>
        </div>
      </header>

      <main className="shell">
        <section className="hero">
          <div className="hero-badge"><Sparkles size={14} /> Leitura inteligente por fornecedor</div>
          <h1>Cada fornecedor pode ter sua própria regra de leitura.</h1>
          <p>O sistema reconhece o fornecedor pelo <strong>CNPJ da chave de acesso</strong>, aplica o perfil correto e extrai carga, destinatário, NF, valores e chaves com regras próprias para cada layout.</p>
        </section>

        <section className="workspace">
          <div className="left-column">
            <UploadZone
              files={files}
              onFiles={addFiles}
              onRemove={(index) => {
                setFiles((current) => current.filter((_, currentIndex) => currentIndex !== index))
                setResult(null)
                setFilters(EMPTY_FILTERS)
              }}
              onClear={clearAttachments}
              disabled={loading}
            />

            <button className="primary-button analyze-button" disabled={!canAnalyze} onClick={handleAnalyze}>
              {loading ? <span className="spinner" /> : <FileSearch size={19} />}
              {loading ? 'Lendo e organizando os arquivos...' : 'Analisar notas fiscais'}
              {!loading && <ArrowRight size={18} />}
            </button>

            {error && (
              <div className="error-box">
                <AlertTriangle size={18} />
                <span>{error}</span>
              </div>
            )}
          </div>

          <aside className="side-card">
            <div className="side-card-head">
              <div className="side-icon"><ShieldCheck size={18} /></div>
              <span className="mini-badge">sem cadastro</span>
            </div>
            <h3>Pronto para sua rotina</h3>
            <ul>
              <li><CheckCircle2 size={16} /> Vários PDFs e fotos por análise</li>
              <li><CheckCircle2 size={16} /> OCR com rotação automática</li>
              <li><CheckCircle2 size={16} /> Câmera do celular e pré-visualização</li>
              <li><CheckCircle2 size={16} /> Perfis de fornecedor por CNPJ e nome</li>
              <li><CheckCircle2 size={16} /> Nordil e Maré usam carga operacional</li>
              <li><CheckCircle2 size={16} /> Outros fornecedores por CNPJ</li>
              <li><CheckCircle2 size={16} /> Quantidade de volumes por NF</li>
              <li><CheckCircle2 size={16} /> Filtros em todas as informações</li>
              <li><CheckCircle2 size={16} /> Cópia individual ou em lote</li>
              <li><CheckCircle2 size={16} /> Exportação TXT e CSV</li>
              <li><CheckCircle2 size={16} /> Validação da chave de 44 dígitos</li>
            </ul>
            <p className="privacy-note">Nesta versão, os arquivos são processados em memória e não são armazenados pelo sistema.</p>
          </aside>
        </section>

        {result && (
          <section className="results-section" id="results">
            <div className="results-heading">
              <div>
                <span className="section-kicker"><CheckCircle2 size={14} /> Análise concluída</span>
                <h2>Central de resultados</h2>
                <p>{result.summary.unique_keys} chaves únicas extraídas de {result.summary.files} arquivo{result.summary.files === 1 ? '' : 's'}{result.summary.ocr_records > 0 ? ` • ${result.summary.ocr_records} por OCR` : ''}.</p>
              </div>
              <div className="results-heading-actions">
                <button className="ghost-button new-analysis-button" type="button" onClick={startNewAnalysis}>
                  <Trash2 size={16} /> Nova análise
                </button>
                <button className="secondary-button" disabled={!filteredInvoices.length} onClick={() => copy(visibleKeys, 'Chaves filtradas copiadas')}>
                  <Copy size={16} /> Copiar visíveis
                </button>
                <button className="secondary-button" disabled={!filteredInvoices.length} onClick={() => downloadFile('nfe-filtrado.csv', buildCsv(filteredInvoices), 'text/csv;charset=utf-8')}>
                  <Download size={16} /> CSV
                </button>
                <button className="secondary-button" disabled={!filteredGroups.length} onClick={() => downloadFile('nfe-filtrado.txt', buildTxt(filteredGroups), 'text/plain;charset=utf-8')}>
                  <Download size={16} /> TXT
                </button>
              </div>
            </div>

            <div className="stats-grid">
              <div className="stat-card featured-stat">
                <span className="stat-icon"><Clipboard size={17} /></span>
                <div><strong>{filteredInvoices.length}</strong><span>chaves exibidas</span></div>
                {filteredInvoices.length !== result.summary.unique_keys && <small>de {result.summary.unique_keys}</small>}
              </div>
              <div className="stat-card"><strong>{filteredTotals.cargas}</strong><span>cargas operacionais</span></div>
              <div className="stat-card"><strong>{filteredTotals.cnpjs}</strong><span>CNPJs</span></div>
              <div className="stat-card"><strong>{filteredInvoices.filter((invoice) => invoice.binding_verified).length}</strong><span>vínculos verificados</span><small>{filteredInvoices.filter((invoice) => !invoice.binding_verified).length} para revisar</small></div>
              <div className="stat-card"><strong>{filteredTotals.volumes.toLocaleString('pt-BR')}</strong><span>volumes identificados</span><small>{filteredTotals.volumeRecords} NF{filteredTotals.volumeRecords === 1 ? '' : 's'} com volume</small></div>
              <div className="stat-card"><strong>{filteredInvoices.filter((invoice) => invoice.extraction_method === 'ocr').length}</strong><span>lidas por OCR</span></div>
              <div className="stat-card"><strong>{new Set(filteredInvoices.filter((invoice) => invoice.supplier_recognized).map((invoice) => invoice.issuer_cnpj)).size}</strong><span>fornecedores cadastrados</span></div>
              <div className="stat-card"><strong>{filteredTotals.amount.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })}</strong><span>valor das notas visíveis</span></div>
            </div>

            <div className="filters-card">
              <div className="filters-title">
                <div><Filter size={17} /><strong>Filtrar informações extraídas</strong></div>
                <span>{filteredInvoices.length} de {allInvoices.length} registros</span>
              </div>

              <div className="filters-grid">
                <label className="search-field">
                  <Search size={16} />
                  <input
                    value={filters.query}
                    onChange={(event) => setFilter('query', event.target.value)}
                    placeholder="Buscar NF, chave, carga, CNPJ, fornecedor, destinatário..."
                  />
                  {filters.query && <button onClick={() => setFilter('query', '')} aria-label="Limpar busca"><X size={14} /></button>}
                </label>

                <label className="select-field">
                  <span>Carga</span>
                  <select value={filters.carga} onChange={(event) => setFilter('carga', event.target.value)}>
                    <option value="">Todas</option>
                    {filterOptions.cargas.map((value) => <option key={value} value={value}>{value}</option>)}
                  </select>
                </label>

                <label className="select-field wide-select">
                  <span>CNPJ</span>
                  <select value={filters.cnpj} onChange={(event) => setFilter('cnpj', event.target.value)}>
                    <option value="">Todos</option>
                    {filterOptions.cnpjs.map((value) => <option key={value} value={value}>{value}</option>)}
                  </select>
                </label>

                <label className="select-field wide-select">
                  <span>Fornecedor</span>
                  <select value={filters.issuer} onChange={(event) => setFilter('issuer', event.target.value)}>
                    <option value="">Todos</option>
                    {filterOptions.issuers.map((value) => <option key={value} value={value}>{value}</option>)}
                  </select>
                </label>

                <label className="select-field">
                  <span>Emissão</span>
                  <select value={filters.date} onChange={(event) => setFilter('date', event.target.value)}>
                    <option value="">Todas</option>
                    {filterOptions.dates.map((value) => <option key={value} value={value}>{value}</option>)}
                  </select>
                </label>

                <label className="select-field wide-select">
                  <span>Arquivo</span>
                  <select value={filters.source} onChange={(event) => setFilter('source', event.target.value)}>
                    <option value="">Todos</option>
                    {filterOptions.sources.map((value) => <option key={value} value={value}>{value}</option>)}
                  </select>
                </label>

                <label className="select-field">
                  <span>Origem</span>
                  <select value={filters.sourceKind} onChange={(event) => setFilter('sourceKind', event.target.value as SourceKindFilter)}>
                    <option value="all">Todos</option>
                    <option value="pdf">PDF</option>
                    <option value="imagem">Foto / imagem</option>
                  </select>
                </label>

                <label className="select-field">
                  <span>Leitura</span>
                  <select value={filters.method} onChange={(event) => setFilter('method', event.target.value as MethodFilter)}>
                    <option value="all">Todas</option>
                    <option value="texto">Texto do PDF</option>
                    <option value="ocr">OCR</option>
                  </select>
                </label>

                <label className="select-field">
                  <span>Cadastro fornecedor</span>
                  <select value={filters.supplierStatus} onChange={(event) => setFilter('supplierStatus', event.target.value as SupplierStatusFilter)}>
                    <option value="all">Todos</option>
                    <option value="recognized">Cadastrados</option>
                    <option value="unknown">Não cadastrados</option>
                  </select>
                </label>

                <label className="select-field">
                  <span>Volumes</span>
                  <select value={filters.volumes} onChange={(event) => setFilter('volumes', event.target.value as VolumeFilter)}>
                    <option value="all">Todos</option>
                    <option value="with">Com volume identificado</option>
                    <option value="without">Sem volume identificado</option>
                  </select>
                </label>

                <label className="select-field">
                  <span>Validação</span>
                  <select value={filters.validity} onChange={(event) => setFilter('validity', event.target.value as ValidityFilter)}>
                    <option value="all">Todas</option>
                    <option value="valid">Somente válidas</option>
                    <option value="invalid">Somente inválidas</option>
                  </select>
                </label>

                <label className="select-field">
                  <span>Ordenar</span>
                  <select value={sortMode} onChange={(event) => setSortMode(event.target.value as SortMode)}>
                    <option value="nf-asc">NF crescente</option>
                    <option value="nf-desc">NF decrescente</option>
                    <option value="carga-asc">Carga</option>
                    <option value="recipient-asc">Destinatário</option>
                  </select>
                </label>
              </div>

              <div className="filter-footer">
                <div className="active-filter-summary">
                  {hasFilters ? <><span className="filter-dot" /> Filtros ativos</> : 'Nenhum filtro aplicado'}
                </div>
                <button className="ghost-button compact" disabled={!hasFilters} onClick={() => setFilters(EMPTY_FILTERS)}>
                  <RotateCcw size={14} /> Limpar filtros
                </button>
              </div>
            </div>

            {result.warnings.length > 0 && (
              <div className="warning-box">
                <AlertTriangle size={17} />
                <div>{result.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>
              </div>
            )}

            <div className="view-toolbar">
              <div className="segmented-control" role="group" aria-label="Modo de visualização">
                <button className={viewMode === 'groups' ? 'active' : ''} onClick={() => setViewMode('groups')}><LayoutGrid size={15} /> Agrupado</button>
                <button className={viewMode === 'table' ? 'active' : ''} onClick={() => setViewMode('table')}><List size={15} /> Tabela geral</button>
              </div>
              <span>Mostrando {filteredInvoices.length} registro{filteredInvoices.length === 1 ? '' : 's'}</span>
            </div>

            {filteredInvoices.length === 0 ? (
              <div className="empty-results">
                <Search size={26} />
                <h3>Nenhum resultado com esses filtros</h3>
                <p>Altere a busca ou limpe os filtros para voltar a exibir as notas.</p>
                <button className="secondary-button" onClick={() => setFilters(EMPTY_FILTERS)}><RotateCcw size={15} /> Limpar filtros</button>
              </div>
            ) : viewMode === 'groups' ? (
              <div className="groups-stack">
                {filteredGroups.map((group) => (
                  <ResultGroup key={`${group.group_type}-${group.carga || 'sem-carga'}-${group.recipient_cnpj}`} group={group} onCopy={copy} onEdit={setEditingInvoice} />
                ))}
              </div>
            ) : (
              <div className="master-table-card">
                <div className="table-wrap">
                  <table className="master-table">
                    <thead>
                      <tr>
                        <th>Carga</th>
                        <th>Fornecedor</th>
                        <th>Destinatário</th>
                        <th>CNPJ</th>
                        <th>NF</th>
                        <th>Chave de acesso</th>
                        <th>Emissão</th>
                        <th>Valor</th>
                        <th>Volumes</th>
                        <th>Origem</th>
                        <th>Leitura</th>
                        <th>Integridade</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredInvoices.map((invoice) => (
                        <tr key={invoice.access_key}>
                          <td><span className={invoice.carga ? 'load-badge' : 'no-load-badge'}>{invoice.carga || 'Sem carga'}</span></td>
                          <td><div className="supplier-cell"><span title={invoice.issuer_name || ''}>{invoice.issuer_name || '—'}</span><small>{invoice.issuer_cnpj || '—'}</small>{invoice.supplier_recognized ? <span className="supplier-profile-badge">perfil cadastrado</span> : <span className="supplier-unknown-badge">não cadastrado</span>}</div></td>
                          <td className="recipient-cell" title={invoice.recipient_name || ''}><div className="recipient-cell-stack"><span>{invoice.recipient_name || '—'}</span>{invoice.recipient_registered && invoice.recipient_name_matches_registry !== false && <span className="recipient-profile-badge">cadastrado</span>}{invoice.recipient_registered && invoice.recipient_name_matches_registry === false && <span className="supplier-unknown-badge">nome divergente</span>}{invoice.manual_edited && <span className="manual-badge">editado</span>}</div></td>
                          <td className="mono small-mono">{invoice.recipient_cnpj || '—'}</td>
                          <td className="mono nf-cell">{invoice.nf_number}</td>
                          <td>
                            <div className="key-line">
                              <span className="mono key-text">{invoice.access_key}</span>
                              {invoice.valid_key && <span className="valid-badge"><Check size={11} /> válida</span>}
                            </div>
                          </td>
                          <td>{invoice.issue_date || '—'}</td>
                          <td>{invoice.total_amount ? `R$ ${invoice.total_amount}` : '—'}</td>
                          <td><strong>{invoice.volume_count ?? '—'}</strong>{invoice.volume_species && <small className="volume-species"> {invoice.volume_species.toLowerCase()}</small>}</td>
                          <td><div className="origin-cell"><span title={invoice.source_file || ''}>{invoice.source_file || '—'}</span><small>{invoice.source_kind === 'imagem' ? 'foto/imagem' : `pág. ${invoice.pages.join(', ')}`}</small></div></td>
                          <td><span className={invoice.extraction_method === 'ocr' ? 'ocr-badge' : 'text-badge'}><ScanText size={11} /> {invoice.extraction_method === 'ocr' ? 'OCR' : 'texto'}</span></td>
                          <td>{invoice.binding_verified ? <span className="valid-badge"><Check size={11} /> verificado</span> : <span className="supplier-unknown-badge">revisar</span>}</td>
                          <td className="action-cell"><div className="row-actions"><button className="icon-button" onClick={() => setEditingInvoice(invoice)} aria-label="Editar dados"><Pencil size={14} /></button><button className="icon-button" onClick={() => copy(invoice.access_key, `NF ${invoice.nf_number} copiada`)} aria-label="Copiar chave"><Copy size={14} /></button></div></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </section>
        )}
      </main>

      <footer className="footer"><span>NF Extract</span> • extração de DANFE com interface de trabalho moderna.</footer>

      <EditInvoiceModal
        invoice={editingInvoice}
        recipients={recipients}
        onClose={() => setEditingInvoice(null)}
        onSave={applyManualEdit}
      />

      {toast && (
        <div className="toast">
          <CheckCircle2 size={17} /> {toast}
          <button onClick={() => setToast('')} aria-label="Fechar"><X size={15} /></button>
        </div>
      )}
    </div>
  )
}
