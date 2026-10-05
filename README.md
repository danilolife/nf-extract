# NF Extract 2.9

Aplicação web full-stack para analisar DANFE/NF-e em PDF, foto ou imagem e transformar os documentos em dados prontos para filtrar, copiar e exportar.

A versão 2.0 foi preparada para **publicação online em um único serviço**, sem precisar instalar nada no computador do usuário. O mesmo container entrega o frontend React e a API FastAPI.

## Recursos

- Upload de vários PDFs, fotos e imagens ao mesmo tempo, com opção de usar a câmera do celular.
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
- Pré-visualização das fotos antes da análise.
- OCR com melhoria de contraste, redimensionamento inteligente e tentativa de rotação automática em 0°, 90°, 180° e 270°.
- Identificação visual de registros lidos por OCR ou pelo texto nativo do PDF.
- Filtros por origem (PDF/foto) e método de leitura (texto/OCR).
- Tema claro/escuro e layout responsivo.
- Processamento em memória: os arquivos não são persistidos nesta versão.

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
/api/analyze      análise de PDFs e imagens
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

Envie um ou mais arquivos no campo multipart `files` (PDF, PNG, JPG, JPEG, WEBP, BMP, TIF, TIFF).

A resposta contém resumo, arquivos processados, grupos por carga/CNPJ e notas individuais.

## OCR para fotos e PDFs escaneados

Esta versão usa OCR com Tesseract como fallback automático para PDFs escaneados e também para fotos/imagens de DANFE. O OCR melhora contraste, ajusta a resolução e testa rotações de 0°, 90°, 180° e 270° quando necessário. O sistema também consegue corrigir exclusivamente o dígito verificador final quando o OCR leu de forma plausível os 43 primeiros dígitos da chave. Para melhores resultados, envie fotos bem enquadradas, com boa iluminação e sem cortes na chave de acesso ou no bloco do destinatário.

## Segurança

- PDFs e imagens processados em memória.
- Sem armazenamento persistente dos documentos nesta versão.
- Limite padrão de 25 MB por arquivo.
- Limite padrão de 30 arquivos por análise.
- Em produção, o Render fornece HTTPS no endereço público do serviço.

## Próximas evoluções possíveis

- Login e histórico de análises com Supabase.
- Extração de peso bruto/líquido e pedido.
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


## Render: confirme que está usando a versão 2.7

No GitHub, abra `VERSION.txt`. Ele deve mostrar **NF Extract Online v2.7.0**.

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


## Novidades da versão 2.5

- Botão **Usar câmera** no celular.
- Pré-visualização das imagens selecionadas.
- OCR em fotos e PDFs escaneados.
- Correção automática de orientação em 90°, 180° e 270°.
- Otimização de imagens grandes de celular para reduzir tempo e memória no servidor.
- Badge **OCR** nas notas reconhecidas por imagem.
- Filtro **Origem**: PDF ou foto/imagem.
- Filtro **Leitura**: texto nativo ou OCR.
- CSV agora informa origem, método de leitura e rotação aplicada.
- Mantidas as regras: carga apenas para Nordil/Nordil Maré; Multigiro/G.R e outros agrupados por CNPJ do destinatário.


## Novidades da versão 2.6 — perfis de fornecedores

O reconhecimento de fornecedor deixou de depender de regras espalhadas no parser. Agora existe um cadastro central em:

```text
backend/app/suppliers.json
```

Cada fornecedor pode ter:

- identificador interno;
- nome oficial;
- um ou mais CNPJs;
- nomes/aliases alternativos;
- regra `uses_carga`;
- padrões próprios para localizar a carga.

A identificação prioriza o **CNPJ do emitente derivado diretamente da chave de acesso da NF-e**, que é mais confiável do que depender apenas do texto ou OCR do logotipo/nome. O nome/alias fica como fallback.

### Fornecedores cadastrados inicialmente

- Nordil — `03.775.813/0001-41` — usa carga operacional.
- Multigiro — `00.728.165/0001-84` — não usa carga operacional.
- G.R Distribuidora — `07.973.261/0001-37` — não usa carga operacional.
- Farpani — `24.171.697/0001-21` — não usa carga operacional na configuração atual.

### Farpani

A versão 2.6 corrige também um detalhe do layout da Farpani: antes da chave aparecem IE e CNPJ do emitente, o que podia fazer uma expressão genérica começar a montar a chave nos últimos dígitos do CNPJ. A leitura de chave agora tenta primeiro a linha completa, grupos de quatro dígitos e janelas de tokens, sempre validando o DV da NF-e.

No exemplo usado no desenvolvimento, a leitura retorna:

```text
Fornecedor: FARPANI DISTRIBUIDORA LTDA
CNPJ fornecedor: 24.171.697/0001-21
Destinatário: Farias Supermercado Ltda
CNPJ destinatário: 12.919.734/0003-10
NF: 73786
Valor: R$ 2.681,50
Chave: 25260924171697000121550010000737861242440800
```

O documento possui `Carga Nro.: 1662`, mas a Farpani está com `uses_carga: false` para preservar a regra operacional atual. Se a empresa passar a usar carga no seu processo, basta trocar esse campo para `true` no perfil da Farpani — sem alterar o parser.

### Como adicionar o próximo fornecedor

Adicione outro bloco ao `suppliers.json`. Exemplo:

```json
{
  "id": "novo-fornecedor",
  "display_name": "NOVO FORNECEDOR LTDA",
  "cnpjs": ["00.000.000/0001-00"],
  "aliases": ["NOVO FORNECEDOR"],
  "uses_carga": false,
  "carga_patterns": []
}
```

O frontend agora mostra se o fornecedor está **perfil cadastrado** ou **não cadastrado**, e inclui um filtro específico para localizar notas de fornecedores ainda sem perfil.

A API também disponibiliza:

```text
GET /api/suppliers
```

para listar os perfis atualmente configurados.


## Novidades da versão 2.7 — quantidade de volumes

A versão 2.7 adiciona leitura automática da **quantidade de volumes transportados** em PDFs nativos, PDFs escaneados e fotos/imagens.

A extração combina três estratégias:

1. leitura da tabela `TRANSPORTADOR / VOLUMES TRANSPORTADOS` por posição das células quando o PDF possui texto;
2. padrões específicos cadastrados no perfil do fornecedor;
3. OCR para fotos e páginas escaneadas.

Os resultados passam a incluir, por NF:

- `volume_count`: quantidade identificada;
- `volume_species`: espécie quando disponível, como `UNIDADE` ou `VOLUMES`;
- `volume_mode`: indica se o valor é por NF ou um total compartilhado no documento.

### Evitando soma duplicada de volumes

Alguns fornecedores repetem nos vários DANFEs o volume total de uma mesma entrega. O cadastro do fornecedor agora aceita `volume_mode`:

- `per_invoice`: soma a quantidade de cada NF, usado por Nordil e Farpani;
- `shared_document`: o mesmo total repetido no arquivo é contado apenas uma vez, usado por Multigiro e G.R.

Assim, no arquivo unificado de Multigiro/G.R usado no desenvolvimento, o valor `79 VOLUMES` repetido nas notas continua resultando em **79 volumes**, e não 79 multiplicado pela quantidade de NFs.

No exemplo Farpani, a tabela de transporte contém `QUANTIDADE 173 / ESPÉCIE UNIDADE`, portanto a aplicação retorna **173 volumes/unidades**.

A interface também ganhou:

- coluna **Volumes** na tabela geral e nos grupos;
- cartão com total de volumes identificados;
- filtro `Com volume identificado / Sem volume identificado`;
- volumes nas exportações CSV e TXT;
- volumes no bloco copiado de cada grupo.


## Novidades da versão 2.8 — integridade de chave e destinatário

Esta versão endurece a associação entre **chave de acesso, NF, carga e CNPJ do destinatário**, principalmente em lotes com vários PDFs da Nordil.

Principais mudanças:

- uma nova NF nunca herda automaticamente o destinatário/CNPJ da NF anterior;
- PDFs com texto usam extração **estrita** da chave, sem reconstrução automática;
- OCR continua disponível, mas uma chave só é aceita quando o DV oficial da NF-e confere;
- CNPJ do destinatário passa pela validação dos dígitos verificadores;
- se a mesma chave aparecer com CNPJs ou cargas divergentes, o sistema não escolhe silenciosamente: oculta o campo conflitante e gera aviso para revisão;
- cada registro recebe `binding_verified`, indicando que chave válida e CNPJ válido foram encontrados no próprio DANFE;
- a interface mostra **vínculo verificado** ou **revisar vínculo** e um contador de integridade.

### Teste de regressão com lote Nordil

A versão foi testada enviando simultaneamente 10 PDFs Nordil com destinatários diferentes. Resultado esperado e obtido: **69 chaves únicas, 10 cargas, 10 CNPJs de destinatário, 69 vínculos verificados e 0 conflitos**.


## Novidades da versão 2.9 — nova análise sem reiniciar

- Botão **Limpar anexos** no bloco de arquivos selecionados.
- Botão **Nova análise** na Central de resultados.
- A nova análise limpa anexos, resultados, filtros e ordenação sem recarregar a página.
- O backend não é reiniciado ao trocar os documentos, reduzindo a necessidade de esperar um novo cold start da hospedagem.


## v3.0 — validação cruzada e Maré

- **Maré Distribuição e Comércio Ltda** (CNPJ `21.610.221/0001-51`) possui perfil próprio e **usa carga operacional**, assim como a Nordil.
- Cadastro local de destinatários conhecidos em `backend/app/recipients.json`.
- Validação cruzada do CNPJ/nome do destinatário contra o cadastro quando o CNPJ é conhecido.
- Endpoint `GET /api/recipients` para listar destinatários cadastrados.
- Edição manual na interface para NF, destinatário, CNPJ, carga, volumes e espécie.
- A chave de acesso nunca é alterada pela edição manual. Se a NF digitada divergir da NF derivada da chave, o vínculo fica marcado para revisão.
- Correções manuais valem para a análise atual; para cadastro persistente de novos destinatários, adicione-os ao arquivo `recipients.json` ou migre esse cadastro para um banco como Supabase.

### Regra de carga

- Nordil (`03.775.813/0001-41`): usa carga.
- Maré Distribuição / Nordil Maré (`21.610.221/0001-51`): usa carga.
- Multigiro e G.R: não usam carga operacional no agrupamento.
- Farpani: não usa carga operacional no agrupamento.
