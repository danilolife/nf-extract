import { useMemo, useState } from 'react'
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
  Moon,
  RotateCcw,
  Search,
  ShieldCheck,
  Sparkles,
  Sun,
  X,
} from 'lucide-react'
import { analyzePdfs } from './api'
import { ResultGroup } from './components/ResultGroup'
import { UploadZone } from './components/UploadZone'
import type { AnalysisGroup, AnalysisResponse, Invoice } from './types'

type ViewMode = 'groups' | 'table'
type ValidityFilter = 'all' | 'valid' | 'invalid'
type SortMode = 'nf-asc' | 'nf-desc' | 'carga-asc' | 'recipient-asc'

type Filters = {
  query: string
  carga: string
  cnpj: string
  issuer: string
  source: string
  date: string
  validity: ValidityFilter
}

const EMPTY_FILTERS: Filters = {
  query: '',
  carga: '',
  cnpj: '',
  issuer: '',
  source: '',
  date: '',
  validity: 'all',
}

function normalize(value: string | null | undefined) {
  return (value || '').toLocaleLowerCase('pt-BR').normalize('NFD').replace(/[\u0300-\u036f]/g, '')
}

function moneyToNumber(value: string | null) {
  if (!value) return 0
  return Number(value.replace(/\./g, '').replace(',', '.')) || 0
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
  const header = ['Carga', 'Fornecedor', 'CNPJ fornecedor', 'Destinatário', 'CNPJ destinatário', 'NF', 'Série', 'Modelo', 'Chave de acesso', 'Emissão', 'Valor', 'Chave válida', 'Arquivo', 'Páginas']
  const rows = invoices.map((invoice) => [
    invoice.carga,
    invoice.issuer_name,
    invoice.issuer_cnpj,
    invoice.recipient_name,
    invoice.recipient_cnpj,
    invoice.nf_number,
    invoice.series,
    invoice.model,
    invoice.access_key,
    invoice.issue_date,
    invoice.total_amount,
    invoice.valid_key ? 'Sim' : 'Não',
    invoice.source_file,
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
        invoice.nf_number,
        invoice.series,
        invoice.access_key,
        invoice.issue_date,
        invoice.total_amount,
        invoice.source_file,
      ].join(' '))

      if (query && !searchable.includes(query)) return false
      if (filters.carga && invoice.carga !== filters.carga) return false
      if (filters.cnpj && invoice.recipient_cnpj !== filters.cnpj) return false
      if (filters.issuer && invoice.issuer_name !== filters.issuer) return false
      if (filters.source && invoice.source_file !== filters.source) return false
      if (filters.date && invoice.issue_date !== filters.date) return false
      if (filters.validity === 'valid' && !invoice.valid_key) return false
      if (filters.validity === 'invalid' && invoice.valid_key) return false
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
        return { ...group, invoices, key_count: invoices.length }
      })
      .filter((group) => group.invoices.length > 0)
  }, [result, filteredInvoices])

  const filteredTotals = useMemo(() => {
    const cargas = new Set(filteredInvoices.map((invoice) => invoice.carga).filter(Boolean)).size
    const cnpjs = new Set(filteredInvoices.map((invoice) => invoice.recipient_cnpj).filter(Boolean)).size
    const amount = filteredInvoices.reduce((sum, invoice) => sum + moneyToNumber(invoice.total_amount), 0)
    return { cargas, cnpjs, amount }
  }, [filteredInvoices])

  const hasFilters = Object.entries(filters).some(([key, value]) => key === 'validity' ? value !== 'all' : Boolean(value))

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

  async function handleAnalyze() {
    if (!canAnalyze) return
    setLoading(true)
    setError('')
    setResult(null)
    setFilters(EMPTY_FILTERS)
    try {
      const data = await analyzePdfs(files)
      setResult(data)
      window.setTimeout(() => document.getElementById('results')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro inesperado ao analisar os PDFs.')
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
          <div className="hero-badge"><Sparkles size={14} /> Leitura inteligente de DANFE</div>
          <h1>PDFs de NF-e viram dados organizados em segundos.</h1>
          <p>Envie seus documentos, extraia <strong>carga, CNPJ, destinatário, NF e chave de acesso</strong>, filtre o resultado e copie exatamente o que precisa.</p>
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
              disabled={loading}
            />

            <button className="primary-button analyze-button" disabled={!canAnalyze} onClick={handleAnalyze}>
              {loading ? <span className="spinner" /> : <FileSearch size={19} />}
              {loading ? 'Lendo e organizando os PDFs...' : 'Analisar notas fiscais'}
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
              <li><CheckCircle2 size={16} /> Vários PDFs por análise</li>
              <li><CheckCircle2 size={16} /> Carga só para Nordil / Nordil Maré</li>
              <li><CheckCircle2 size={16} /> Outros fornecedores por CNPJ</li>
              <li><CheckCircle2 size={16} /> Filtros em todas as informações</li>
              <li><CheckCircle2 size={16} /> Cópia individual ou em lote</li>
              <li><CheckCircle2 size={16} /> Exportação TXT e CSV</li>
              <li><CheckCircle2 size={16} /> Validação da chave de 44 dígitos</li>
            </ul>
            <p className="privacy-note">Nesta versão, os PDFs são processados em memória e não são armazenados pelo sistema.</p>
          </aside>
        </section>

        {result && (
          <section className="results-section" id="results">
            <div className="results-heading">
              <div>
                <span className="section-kicker"><CheckCircle2 size={14} /> Análise concluída</span>
                <h2>Central de resultados</h2>
                <p>{result.summary.unique_keys} chaves únicas extraídas de {result.summary.files} PDF{result.summary.files === 1 ? '' : 's'}.</p>
              </div>
              <div className="results-heading-actions">
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
              <div className="stat-card"><strong>{filteredTotals.cargas}</strong><span>cargas Nordil</span></div>
              <div className="stat-card"><strong>{filteredTotals.cnpjs}</strong><span>CNPJs</span></div>
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
                  <ResultGroup key={`${group.group_type}-${group.carga || 'sem-carga'}-${group.recipient_cnpj}`} group={group} onCopy={copy} />
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
                        <th>Origem</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredInvoices.map((invoice) => (
                        <tr key={invoice.access_key}>
                          <td><span className={invoice.carga ? 'load-badge' : 'no-load-badge'}>{invoice.carga || 'Sem carga'}</span></td>
                          <td><div className="supplier-cell"><span title={invoice.issuer_name || ''}>{invoice.issuer_name || '—'}</span><small>{invoice.issuer_cnpj || '—'}</small></div></td>
                          <td className="recipient-cell" title={invoice.recipient_name || ''}>{invoice.recipient_name || '—'}</td>
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
                          <td><div className="origin-cell"><span title={invoice.source_file || ''}>{invoice.source_file || '—'}</span><small>pág. {invoice.pages.join(', ')}</small></div></td>
                          <td className="action-cell"><button className="icon-button" onClick={() => copy(invoice.access_key, `NF ${invoice.nf_number} copiada`)} aria-label="Copiar chave"><Copy size={14} /></button></td>
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

      {toast && (
        <div className="toast">
          <CheckCircle2 size={17} /> {toast}
          <button onClick={() => setToast('')} aria-label="Fechar"><X size={15} /></button>
        </div>
      )}
    </div>
  )
}
