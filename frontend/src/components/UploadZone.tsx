import { useRef, useState } from 'react'
import { FileText, Plus, Trash2, UploadCloud } from 'lucide-react'

interface Props {
  files: File[]
  onFiles: (files: File[]) => void
  onRemove: (index: number) => void
  disabled?: boolean
}

export function UploadZone({ files, onFiles, onRemove, disabled }: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [dragging, setDragging] = useState(false)

  function addFromList(list: FileList | null) {
    if (!list) return
    const pdfs = Array.from(list).filter((file) => file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf'))
    onFiles(pdfs)
  }

  return (
    <section className="upload-card">
      <div
        className={`dropzone ${dragging ? 'is-dragging' : ''}`}
        onDragEnter={(event) => { event.preventDefault(); setDragging(true) }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => { event.preventDefault(); setDragging(false); addFromList(event.dataTransfer.files) }}
        onClick={() => !disabled && inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          hidden
          disabled={disabled}
          onChange={(event) => { addFromList(event.target.files); event.currentTarget.value = '' }}
        />
        <div className="upload-icon"><UploadCloud size={25} /></div>
        <h2>Solte os PDFs aqui</h2>
        <p>Selecione um ou vários DANFEs. O sistema identifica as notas e remove repetições automaticamente.</p>
        <button className="secondary-button" type="button" disabled={disabled}><Plus size={16} /> Escolher arquivos</button>
        <span className="upload-hint">PDF • até 25 MB por arquivo</span>
      </div>

      {files.length > 0 && (
        <div className="file-list">
          <div className="file-list-head"><span>Arquivos selecionados</span><strong>{files.length}</strong></div>
          {files.map((file, index) => (
            <div className="file-row" key={`${file.name}-${file.size}-${index}`}>
              <div className="file-main">
                <span className="file-icon"><FileText size={17} /></span>
                <div><strong>{file.name}</strong><small>{(file.size / 1024 / 1024).toFixed(2)} MB</small></div>
              </div>
              <button className="icon-button" type="button" onClick={(event) => { event.stopPropagation(); onRemove(index) }} aria-label="Remover arquivo" disabled={disabled}><Trash2 size={16} /></button>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
