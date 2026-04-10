# RESEARCH (212) — Fase 3: Q&A + Sugestão Automática de Tese

**Data:** 2026-04-10  
**Escopo:** Fase 3 parcial — Features A (Q&A em linguagem natural) e B (Sugestão automática de atualização de tese). Features C–E (feed por setor, comparações cross-empresa, painel admin de audit log) ficam para planejamento posterior.

---

## Contexto

Fases 1 e 2 da aba RESEARCH estão em produção no Render. A base tem schema SQLite completo (`companies`, `theses`, `filings`, `news_items`, `notes`, `valuations`, `audit_log`, `research_fts` FTS5), pipeline de ingestão CVM/SEC/RSS funcionando com revisão humana, e ~35 rotas Flask ativas.

O passo natural é tornar a base de conhecimento acumulada **consultável em linguagem natural** e **proativa** — alertando a equipe quando novos dados sugerem revisão da tese de investimento.

---

## Decisões de Design

| Decisão | Escolha |
|---------|---------|
| Escopo do Q&A | Por empresa + global (cross-empresa) |
| Histórico de Q&A | Persistente no banco, visível na UI |
| Formato da resposta | Prosa com citações explícitas das fontes usadas |
| Modelo de conversação | Single-turn com RAG (cada pergunta é independente; threading multi-turn pode ser adicionado depois com migração simples) |
| UI do Q&A por empresa | Painel lateral deslizante (260px, sobre o conteúdo existente) |
| UI do Q&A global | Item fixo "✦ Q&A GLOBAL" no topo do sidebar esquerdo |
| Sugestão de tese | Claude gera rascunho automaticamente ao aprovar filing/notícia com `update_thesis=True`; admin vê banner na sub-aba TESE |

---

## Schema — Mudanças no Banco

### Nova tabela `qa_messages`

```sql
CREATE TABLE IF NOT EXISTS qa_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT,     -- NULL = pergunta global (cross-empresa)
    role        TEXT CHECK(role IN ('user','assistant')) NOT NULL,
    content     TEXT NOT NULL,
    sources     TEXT,     -- JSON array: [{type, id, ticker, snippet}]
    created_by  TEXT NOT NULL DEFAULT 'admin',
    created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);
```

### Novas colunas em `theses`

```sql
ALTER TABLE theses ADD COLUMN auto_generated INTEGER DEFAULT 0;
ALTER TABLE theses ADD COLUMN trigger_type TEXT;  -- 'filing' | 'news'
ALTER TABLE theses ADD COLUMN trigger_id   INTEGER;
```

A migração é segura (ADD COLUMN com DEFAULT não bloqueia leituras/escritas no SQLite WAL).

---

## Arquitetura

### Componentes novos

| Arquivo | Função |
|---------|--------|
| `research_claude.py` | + `answer_question(question, ticker, context_chunks) → {answer, sources}` |
| `research_claude.py` | + `suggest_thesis_update(current_thesis, trigger_summary, trigger_type) → str` |
| `research_db.py` | + `build_rag_context(question, ticker=None) → list[dict]` |
| `research_db.py` | + `get_qa_messages(ticker=None, limit=50) → list[dict]` |
| `research_db.py` | + `save_qa_message(ticker, role, content, sources, user) → int` |
| `app.py` | + `POST /api/research/qa` |
| `app.py` | + `GET /api/research/qa` (com `?ticker=` opcional) |
| `app.py` | Trigger em `review_filing` e `review_news`: ao aprovar item com `update_thesis=True`, chama `suggest_thesis_update` e salva RASCUNHO |

### Estratégia RAG (`build_rag_context`)

Para cada pergunta, o contexto enviado ao Claude é construído assim (em ordem de prioridade):

1. **FTS5 full-text search** com a pergunta → top 5 chunks (ticker-específico se `ticker` fornecido, global caso contrário)
2. **Tese ativa** da empresa (se `ticker` não for None)
3. **Último valuation aprovado** da empresa (se existir)

Cada chunk inclui metadados (`type`, `id`, `ticker`, `snippet`) para que o Claude possa citar com precisão.

### Fluxo do Q&A

```
1. Frontend POST /api/research/qa  {question, ticker?}
2. build_rag_context(question, ticker) → chunks
3. answer_question(question, ticker, chunks) → {answer, sources}
4. save_qa_message(ticker, 'user', question, None, user)
5. save_qa_message(ticker, 'assistant', answer, sources, 'claude')
6. Retorna {answer, sources} ao frontend
```

### Fluxo da sugestão de tese

```
1. Admin aprova filing ou notícia (review_filing / review_news)
2. Se item.update_thesis == True:
   a. get_active_thesis(ticker) → tese atual
   b. suggest_thesis_update(tese_atual, item.summary, tipo) → rascunho (str)
   c. create_thesis(ticker, rascunho, user='claude')  com auto_generated=1, trigger_type, trigger_id
3. Frontend detecta rascunho auto_generated pendente → exibe banner na sub-aba TESE
```

---

## Frontend — UI

### Q&A por empresa

- Botão **"✦ PERGUNTAR"** na header da empresa (ao lado de "↓EXPORTAR MD")
- Clique desliza painel de 260px da direita, sobre o conteúdo da sub-aba ativa
- Painel exibe histórico de Q&A do ticker (mensagens `user` e `assistant` em ordem cronológica)
- Citações na resposta aparecem como badges clicáveis em azul: `[ITR Q3/25]`, `[Nota call jan/26]`
- Fechamento: botão ✕ ou clique no overlay
- Histórico persiste entre sessões (carregado do banco via `GET /api/research/qa?ticker=X`)

### Q&A global

- Item **"✦ Q&A GLOBAL"** fixo no topo do sidebar esquerdo, acima da seção "PORTFÓLIO"
- Clique seleciona o item e exibe no painel principal uma interface de chat sem ticker
- Histórico global separado (`ticker = NULL`) — carregado via `GET /api/research/qa` (sem `?ticker=`)
- Citações incluem o ticker: `[PRIO3/ITR Q3]`, `[VALE3/Tese]`

### Banner de sugestão de tese

- Exibido no topo da sub-aba **TESE** quando existe `theses` com `status='RASCUNHO'` e `auto_generated=1` para o ticker
- Estilo: fundo âmbar, ícone ⚡, texto explica qual filing/notícia gerou a sugestão
- Botão **VER RASCUNHO**: expande editor lado a lado (tese ativa à esquerda, rascunho Claude à direita, editável)
- Botão **IGNORAR**: marca o rascunho como `ARQUIVADA` sem aprovação, registra no `audit_log`
- Fluxo de aprovação do rascunho: usa o mesmo `approve_thesis()` já existente

---

## Arquivos Modificados

| Arquivo | O que muda |
|---------|-----------|
| `research_db.py` | + tabela `qa_messages`, + colunas em `theses`, + funções `build_rag_context`, `get_qa_messages`, `save_qa_message`; atualizar `create_thesis()` para aceitar parâmetros opcionais `auto_generated=0`, `trigger_type=None`, `trigger_id=None` |
| `research_claude.py` | + `answer_question`, + `suggest_thesis_update` |
| `app.py` | + rotas `/api/research/qa`, trigger de sugestão em `review_filing`/`review_news` |
| `templates/index.html` | Botão "PERGUNTAR" na header de empresa, item "Q&A GLOBAL" no sidebar, banner de sugestão na sub-aba TESE |
| `static/app.js` | Lógica do painel lateral, Q&A global, renderização de citações, banner com diff de tese |
| `static/style.css` | Estilos do painel lateral, badges de citação, banner âmbar, editor lado a lado |

---

## Verificação (end-to-end)

1. Abrir PRIO3 → clicar "✦ PERGUNTAR" → painel lateral abre
2. Digitar "Qual o principal risco da PRIO3?" → resposta aparece com citações `[fonte]`
3. Recarregar página → histórico da pergunta persiste
4. Clicar "✦ Q&A GLOBAL" no sidebar → interface global carrega
5. Perguntar "Qual empresa do portfólio tem maior upside?" → resposta cita tickers específicos
6. Aprovar filing com `update_thesis=True` → banner ⚡ aparece na sub-aba TESE da empresa
7. Clicar "VER RASCUNHO" → editor lado a lado exibe tese atual vs sugerida
8. Editar rascunho e clicar "APROVAR" → tese ativa atualizada, audit_log registra `auto_generated=True`
9. Clicar "IGNORAR" no banner → rascunho arquivado, banner desaparece

---

## Fora de Escopo (Fase 3 Parcial)

- Feed por setor (C)
- Comparações cross-empresa P/L, EV/EBITDA, upside (D)
- Painel admin de audit log global com filtros (E)
- Q&A multi-turn com threads (decisão deliberada — migração futura simples via `thread_id` em `qa_messages`)
