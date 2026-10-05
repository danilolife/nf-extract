import { useEffect, useMemo, useRef, useState } from 'react'
import { Camera, FileText, Image as ImageIcon, Plus, Trash2, UploadCloud } from 'lucide-react'

interface Props {
  files: File[]
  onFiles: (files: File[]) => void
  onRemove: (index: number) => void
  onClear: () => void
  disabled?: boolean
}

function isImage(file: File) {
  return file.type.startsWith('image/') || /\.(png|jpe?g|webp|bmp|tiff?)$/i.test(file.name)
}

export function UploadZone({ files, onFiles, onRemove, onClear, disabled }: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const cameraRef = useRef<HTMLInputElement | null>(null)
  const [dragging, setDragging] = useState(false)

  const previews = useMemo(() => files.map((file) => isImage(file) ? URL.createObjectURL(file) : null), [files])

  useEffect(() => () => {
    previews.forEach((url) => url && URL.revokeObjectURL(url))
  }, [previews])

  function addFromList(list: FileList | null) {
    if (!list) return
    const accepted = Array.from(list).filter((file) => {
      const name = file.name.toLowerCase()
      return file.type === 'application/pdf'
        || name.endsWith('.pdf')
        || file.type.startsWith('image/')
        || /\.(png|jpe?g|webp|bmp|tiff?)$/.test(name)
    })
    onFiles(accepted)
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
          accept="application/pdf,.pdf,image/png,image/jpeg,image/jpg,image/webp,image/bmp,image/tiff,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff"
          multiple
          hidden
          disabled={disabled}
          onChange={(event) => { addFromList(event.target.files); event.currentTarget.value = '' }}
        />
        <input
          ref={cameraRef}
          type="file"
          accept="image/*"
          capture="environment"
          hidden
          disabled={disabled}
          onChange={(event) => { addFromList(event.target.files); event.currentTarget.value = '' }}
        />

        <div className="upload-icon"><UploadCloud size={25} /></div>
        <h2>Solte PDFs ou fotos aqui</h2>
        <p>Envie DANFEs em PDF ou imagem. Para fotos e PDFs escaneados, o sistema aplica OCR e tenta corrigir automaticamente a orientação.</p>
        <div className="upload-actions">
          <button
            className="secondary-button"
            type="button"
            disabled={disabled}
            onClick={(event) => { event.stopPropagation(); inputRef.current?.click() }}
          >
            <Plus size={16} /> Escolher arquivos
          </button>
          <button
            className="ghost-button"
            type="button"
            disabled={disabled}
            onClick={(event) => { event.stopPropagation(); cameraRef.current?.click() }}
          >
            <Camera size={16} /> Usar câmera
          </button>
        </div>
        <span className="upload-hint">PDF, PNG, JPG, WEBP, BMP, TIFF • até 25 MB por arquivo</span>
      </div>

      {files.length > 0 && (
        <div className="file-list">
          <div className="file-list-head">
            <div className="file-list-title"><span>Arquivos selecionados</span><strong>{files.length}</strong></div>
            <button
              className="clear-files-button"
              type="button"
              disabled={disabled}
              onClick={(event) => { event.stopPropagation(); onClear() }}
            >
              <Trash2 size={14} /> Limpar anexos
            </button>
          </div>
          {files.map((file, index) => (
            <div className="file-row" key={`${file.name}-${file.size}-${index}`}>
              <div className="file-main">
                {previews[index] ? (
                  <img className="file-preview" src={previews[index] || ''} alt="Pré-visualização" />
                ) : (
                  <span className="file-icon"><FileText size={17} /></span>
                )}
                <div>
                  <strong>{file.name}</strong>
                  <small>{(file.size / 1024 / 1024).toFixed(2)} MB • {isImage(file) ? 'Imagem / OCR' : 'PDF'}</small>
                </div>
              </div>
              <div className="file-row-actions">
                {isImage(file) && <span className="image-badge"><ImageIcon size={12} /> foto</span>}
                <button className="icon-button" type="button" onClick={(event) => { event.stopPropagation(); onRemove(index) }} aria-label="Remover arquivo" disabled={disabled}><Trash2 size={16} /></button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
