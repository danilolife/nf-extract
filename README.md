# NF Extract 2.3

Aplicação web full-stack para analisar DANFE/NF-e em PDF e transformar os documentos em dados prontos para filtrar, copiar e exportar.

A versão 2.0 foi preparada para **publicação online em um único serviço**, sem precisar instalar nada no computador do usuário. O mesmo container entrega o frontend React e a API FastAPI.

## Recursos

- Upload de vários PDFs ao mesmo tempo.
- Extração da chave de acesso NF-e/NFC-e de 44 dígitos.
- Validação do dígito verificador da chave.
- Extração do número da NF, série e modelo pela chave.
- Carga operacional do documento para **Nordil / Nordil Maré**.
- Para outros fornecedores (como Multigiro/G.R), ignora `NroCarga` de observações e agrupa por **CNPJ do destinatário**.
- Nome e CNPJ do destinatário, inclusive em layouts onde o CNPJ aparece longe do nome.
- Nome e CNPJ do fornecedor/emitente.
- Data de emissão, valor e página/arquivo de origem quando disponíveis no DANFE.
- Remoção automática de chaves repetidas em notas com mais de uma página.
- Agrupamento por carga + CNPJ.
- Busca global por NF, chave, carga, CNPJ, destinatário, valor ou arquivo.
- Filtros por carga, CNPJ do destinatário, **fornecedor**, data de emissão, arquivo e validade da chave.
- Ordenação por NF, carga ou destinatário.
- Duas visualizações: **Por carga** e **Tabela geral**.
- Botão de copiar uma chave, as chaves visíveis, as NFs da carga ou o bloco completo.
- Exportação dos resultados filtrados em **CSV** e **TXT**.
- Tema claro/escuro e layout responsivo.
- Processamento em memória: os PDFs não são persistidos nesta versão.

## Estrutura

```text
nfe-analyzer/
├─ Dockerfile                 # container único para produção
├─ render.yaml                # deploy no Render
├─ docker-compose.yml         # opcional para ambiente local
├─ backend/
│  ├─ app/
│  │  ├─ main.py
│  │  └─ parser.py
│  ├─ tests/
│  └─ requirements.txt
└─ frontend/
   ├─ src/
   ├─ package.json
   └─ vite.config.ts
```

# Publicar online sem CMD ou instalação

A forma mais simples é **GitHub + Render**, usando apenas o navegador.

## Etapa 1 — enviar o projeto para o GitHub

1. Entre em `github.com` e faça login.
2. Clique em **New repository**.
3. Escolha um nome, por exemplo `nf-extract`.
4. Crie o repositório.
5. Dentro dele, clique em **Add file → Upload files**.
6. Extraia este ZIP em uma pasta temporária usando o próprio recurso disponível no seu ambiente, se permitido, e envie o conteúdo da pasta `nfe-analyzer` para o repositório. É importante que `Dockerfile` e `render.yaml` fiquem na raiz do repositório.
7. Clique em **Commit changes**.

> Se a política do computador impedir até a extração de ZIP, você pode usar um ambiente online como GitHub Codespaces para importar o conteúdo do projeto, sem instalar nada localmente.

## Etapa 2 — publicar no Render

1. Entre em `render.com` e faça login.
2. Conecte sua conta do GitHub.
3. Escolha **New → Blueprint**.
4. Selecione o repositório `nf-extract`.
5. O Render lerá o arquivo `render.yaml`.
6. Confirme a criação do serviço.
7. Aguarde o build e o deploy.

Ao terminar, você receberá uma URL semelhante a:

```text
https://nf-extract.onrender.com
```

A API e o frontend usam o mesmo domínio:

```text
/                 interface web
/api/health       status da API
/api/analyze      análise dos PDFs
/docs             documentação interativa da API
```

## Como o Docker de produção funciona

O `Dockerfile` tem duas etapas:

1. Node compila o frontend React/Vite.
2. Python instala o backend FastAPI e recebe os arquivos compilados do frontend.

O FastAPI entrega o site e a API no mesmo container. Isso evita configurar dois serviços, duas URLs ou CORS em produção.

## Testar localmente com Docker, se algum dia precisar

```bash
docker compose up --build
```

Abra `http://localhost:8080`.

## API

### `POST /api/analyze`

Envie um ou mais PDFs no campo multipart `files`.

A resposta contém resumo, arquivos processados, grupos por carga/CNPJ e notas individuais.

## Limitação: PDF escaneado

Esta versão usa PyMuPDF e funciona com DANFEs que possuem texto embutido, como os documentos usados no desenvolvimento. Se o PDF for apenas uma imagem escaneada, será necessário adicionar OCR como fallback em uma evolução futura.

## Segurança

- PDFs processados em memória.
- Sem armazenamento persistente dos documentos nesta versão.
- Limite padrão de 25 MB por arquivo.
- Limite padrão de 30 arquivos por análise.
- Em produção, o Render fornece HTTPS no endereço público do serviço.

## Próximas evoluções possíveis

- Login e histórico de análises com Supabase.
- OCR automático para DANFEs escaneados.
- Extração de volume, peso e pedido.
- Exportação XLSX.
- Armazenamento opcional em bucket privado.

## Se o primeiro deploy no Render aparecer como “Failed deploy”

A versão 2.1 corrige a configuração de build do frontend para o ambiente do Render. Depois de substituir os arquivos no GitHub, abra o serviço `nf-extract` no Render e use **Manual Deploy → Deploy latest commit**.

O build esperado executa, em ordem:

1. `npm install --no-audit --no-fund`
2. `npm run build` (`vite build`)
3. instalação das dependências Python
4. inicialização do FastAPI na porta fornecida pelo Render
5. verificação de saúde em `/api/health`

Se ainda houver falha, abra **Logs** no serviço do Render e copie a primeira linha marcada como `error` ou `failed` para diagnóstico.


## Render: confirme que está usando a versão 2.2

No GitHub, abra `VERSION.txt`. Ele deve mostrar **NF Extract Online v2.2.0**.

No log do Render, a etapa do frontend deve mostrar:

```text
RUN npx vite build
```

Se aparecer `tsc -b && vite build`, o Render ainda está construindo uma versão antiga do repositório. Faça commit dos arquivos atualizados e use **Manual Deploy → Clear build cache & deploy** no Render.


## Regra de agrupamento da versão 2.3

- **Nordil / Nordil Maré:** o sistema lê e usa a carga operacional e agrupa por `carga + CNPJ do destinatário`.
- **Multigiro, G.R e demais fornecedores:** o sistema não usa números `Carga/NroCarga` presentes em observações, boletos ou roteirização. O agrupamento é feito pelo **CNPJ do destinatário**.
- O fornecedor continua identificado em cada nota e pode ser usado no filtro `Fornecedor`.

### Correção do DANFE Multigiro

No layout Multigiro/G.R, a ordem textual do PDF pode apresentar primeiro o CNPJ do emitente e somente depois o CNPJ do destinatário. A versão 2.3 deriva o CNPJ do emitente a partir da chave de acesso, ignora esse CNPJ ao analisar a seção `DESTINATÁRIO/REMETENTE` e captura o CNPJ seguinte como destinatário.
