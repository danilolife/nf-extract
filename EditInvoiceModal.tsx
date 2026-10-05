import { AlertTriangle, CheckCircle2, Pencil, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import type { Invoice } from '../types'

type RecipientProfile = {
  cnpj: string
  display_name: string
  aliases: string[]
}

interface Props {
  invoice: Invoice | null
  recipients: RecipientProfile[]
  onClose: () => void
  onSave: (invoice: Invoice, changes: Partial<Invoice>) => void
}

function digitsOnly(value: string) {
  return value.replace(/\D/g, '')
}

function normalize(value: string | null | undefined) {
  return (value || '').toLocaleUpperCase('pt-BR').normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/\s+/g, ' ').trim()
}

function validCnpj(value: string) {
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

function formatCnpj(value: string) {
  const d = digitsOnly(value).slice(0, 14)
  if (d.length !== 14) return value
  return `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8, 12)}-${d.slice(12)}`
}

export function EditInvoiceModal({ invoice, recipients, onClose, onSave }: Props) {
  const [nf, setNf] = useState('')
  const [recipientName, setRecipientName] = useState('')
  const [recipientCnpj, setRecipientCnpj] = useState('')
  const [carga, setCarga] = useState('')
  const [volume, setVolume] = useState('')
  const [species, setSpecies] = useState('')

  useEffect(() => {
    if (!invoice) return
    setNf(invoice.nf_number || '')
    setRecipientName(invoice.recipient_name || '')
    setRecipientCnpj(invoice.recipient_cnpj || '')
    setCarga(invoice.carga || '')
    setVolume(invoice.volume_count == null ? '' : String(invoice.volume_count))
    setSpecies(invoice.volume_species || '')
  }, [invoice])

  const derivedNf = useMemo(() => {
    if (!invoice?.access_key || invoice.access_key.length !== 44) return ''
    return String(Number(invoice.access_key.slice(25, 34)))
  }, [invoice])

  const registryProfile = useMemo(() => {
    const target = digitsOnly(recipientCnpj)
    return recipients.find((item) => digitsOnly(item.cnpj) === target) || null
  }, [recipientCnpj, recipients])

  const cnpjOk = recipientCnpj ? validCnpj(recipientCnpj) : false
  const nfMatches = Boolean(derivedNf && nf === derivedNf)
  const nameMatches = useMemo(() => {
    if (!registryProfile) return null
    const name = normalize(recipientName)
    const candidates = [registryProfile.display_name, ...registryProfile.aliases].map(normalize)
    return Boolean(name) && candidates.some((candidate) => candidate && (candidate.includes(name) || name.includes(candidate)))
  }, [registryProfile, recipientName])

  if (!invoice) return null

  function save() {
    const parsedVolume = volume.trim() ? Number(volume.replace(/\D/g, '')) : null
    onSave(invoice, {
      nf_number: nf.trim(),
      recipient_name: recipientName.trim() || null,
      recipient_cnpj: recipientCnpj.trim() ? formatCnpj(recipientCnpj.trim()) : null,
      carga: carga.trim() || null,
      volume_count: parsedVolume && parsedVolume > 0 ? parsedVolume : null,
      volume_species: species.trim() || null,
      manual_edited: true,
    })
  }

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="edit-modal" onMouseDown={(event) => event.stopPropagation()}>
        <div className="edit-modal-head">
          <div>
            <span className="section-kicker"><Pencil size={14} /> Correção manual</span>
            <h3>Editar NF {invoice.nf_number}</h3>
            <p>A chave de acesso não é alterada. Mudanças que não batem com a chave ficam marcadas para revisão.</p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Fechar"><X size={17} /></button>
        </div>

        <div className="edit-grid">
          <label>
            <span>NF</span>
            <input value={nf} onChange={(event) => setNf(event.target.value.replace(/\D/g, ''))} />
            <small>NF derivada da chave: {derivedNf || '—'}</small>
          </label>
          <label>
            <span>Carga</span>
            <input value={carga} onChange={(event) => setCarga(event.target.value.replace(/\D/g, ''))} placeholder="Sem carga" />
          </label>
          <label className="edit-wide">
            <span>Destinatário</span>
            <input value={recipientName} onChange={(event) => setRecipientName(event.target.value)} />
          </label>
          <label>
            <span>CNPJ destinatário</span>
            <input value={recipientCnpj} onChange={(event) => setRecipientCnpj(event.target.value)} />
            <small>{cnpjOk ? 'CNPJ matematicamente válido' : 'CNPJ inválido ou incompleto'}</small>
          </label>
          <label>
            <span>Volumes</span>
            <input value={volume} onChange={(event) => setVolume(event.target.value.replace(/\D/g, ''))} placeholder="Não identificado" />
          </label>
          <label>
            <span>Espécie</span>
            <input value={species} onChange={(event) => setSpecies(event.target.value)} placeholder="VOLUMES, UNIDADE..." />
          </label>
        </div>

        <div className="edit-checks">
          <div className={nfMatches ? 'edit-check ok' : 'edit-check warning'}>
            {nfMatches ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
            <span>{nfMatches ? 'NF confere com a chave' : 'NF não confere com a chave'}</span>
          </div>
          <div className={cnpjOk ? 'edit-check ok' : 'edit-check warning'}>
            {cnpjOk ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
            <span>{cnpjOk ? 'CNPJ válido' : 'Revisar CNPJ'}</span>
          </div>
          {registryProfile && (
            <div className={nameMatches ? 'edit-check ok' : 'edit-check warning'}>
              {nameMatches ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
              <span>{nameMatches ? `CNPJ cadastrado: ${registryProfile.display_name}` : `Nome diverge do cadastro: ${registryProfile.display_name}`}</span>
            </div>
          )}
        </div>

        <div className="edit-modal-actions">
          <button className="ghost-button" onClick={onClose}>Cancelar</button>
          <button className="primary-button compact-primary" onClick={save}><Pencil size={15} /> Salvar correção</button>
        </div>
      </div>
    </div>
  )
}

export type { RecipientProfile }
