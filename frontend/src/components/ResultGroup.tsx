import { Check, Copy, FileDown, Files, Hash, ListChecks, MapPin } from 'lucide-react'
import type { AnalysisGroup } from '../types'

interface Props {
  group: AnalysisGroup
  onCopy: (text: string, label?: string) => void
}

function downloadText(filename: string, content: string) {
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export function ResultGroup({ group, onCopy }: Props) {
  const keys = group.invoices.map((invoice) => invoice.access_key).join('\n')
  const nfs = group.invoices.map((invoice) => invoice.nf_number).join(', ')
  const formatted = `CARGA ${group.carga}\nDESTINATÁRIO: ${group.recipient_name}\nCNPJ: ${group.recipient_cnpj}\nNF: ${nfs}\n\n${keys}`

  return (
    <article className="result-card">
      <header className="result-header">
        <div className="result-title-block">
          <div className="eyebrow"><MapPin size={14} /> Grupo identificado</div>
          <div className="result-title-row">
            <h3>Carga {group.carga}</h3>
            <span className="count-badge">{group.key_count} chave{group.key_count === 1 ? '' : 's'}</span>
          </div>
          <p>{group.recipient_name}</p>
          <div className="meta-line">
            <span><Hash size={14} /> {group.recipient_cnpj}</span>
            <span><Files size={14} /> {group.invoices.length} nota{group.invoices.length === 1 ? '' : 's'}</span>
          </div>
        </div>
        <div className="header-actions">
          <button className="secondary-button compact" onClick={() => onCopy(keys, 'Chaves da carga copiadas')}><Copy size={15} /> Chaves</button>
          <button className="ghost-button compact" onClick={() => onCopy(nfs, 'Números das NFs copiados')}><ListChecks size={15} /> NFs</button>
          <button className="ghost-button compact" onClick={() => downloadText(`carga-${group.carga}.txt`, formatted)}><FileDown size={15} /> TXT</button>
        </div>
      </header>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>NF</th>
              <th>Chave de acesso</th>
              <th>Emissão</th>
              <th>Valor</th>
              <th>Origem</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {group.invoices.map((invoice) => (
              <tr key={invoice.access_key}>
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
                <td className="action-cell"><button className="icon-button" onClick={() => onCopy(invoice.access_key, `NF ${invoice.nf_number} copiada`)} aria-label="Copiar chave"><Copy size={14} /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <footer className="result-footer">
        <span>NF: <strong>{nfs}</strong></span>
        <button className="ghost-button" onClick={() => onCopy(formatted, 'Bloco completo copiado')}><Copy size={15} /> Copiar bloco completo</button>
      </footer>
    </article>
  )
}
