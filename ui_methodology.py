# -*- coding: utf-8 -*-
"""
Metodologia das métricas das abas PRÉ-TRADE, CVM OFICIAL, GRÁFICOS e
TABELA — fonte única de verdade para tooltips de auditoria.

Mesmo formato dos arquivos risk_methodology.py / liquidity_methodology.py
(5 seções: what / formula / window / source / interpretation).

Convenções de prefixo de chave:
    pt_*    : PRÉ-TRADE (cards de simulação, compliance, parâmetros)
    cvm_*   : CVM OFICIAL (KPIs e charts do informe diário)
    chart_* : GRÁFICOS (charts da aba 201)
    tab_*   : TABELA (colunas calculadas da aba 200)

Para adicionar nova: incluir entrada abaixo + <span class="col-info"
data-tip-key="<chave>">ⓘ</span> no template/JS. Sem alteração em CSS/JS.

Manter sincronizado com app.py — esta é a fonte que compliance e auditoria
revisam.
"""

UI_METHODOLOGY: dict = {

    # ═════════════════════════ PRÉ-TRADE ═════════════════════════

    "pt_card_impacto_cota": {
        "title": "Impacto na Cota e NAV",
        "what": (
            "Calcula o efeito do basket de operações sobre a cota estimada, "
            "NAV, caixa e métricas ponderadas da carteira. Mostra Antes vs "
            "Depois para cada métrica + Δ (variação)."
        ),
        "formula": (
            "Cota Estimada (antes/depois): calculate_quota com preços de\n"
            "  mercado atual; depois reflete o portfólio_sim mutado.\n"
            "NAV Total = NAV_carteira + caixa + proventos − custos.\n"
            "Caixa Resultante = caixa_atual − Σ(custos_basket) onde\n"
            "  compra: caixa − valor − corretagem\n"
            "  venda:  caixa + valor − corretagem\n"
            "  zerar:  caixa + qtd_atual × preço − corretagem\n"
            "Grupo I % = Σ(valor_i para categoria ∈ {Acao, BDR}) / NAV\n"
            "Beta/Upside ponderados: por valor de mercado.\n"
            "HHI Concentração = Σ(pct_setor²) × 10.000."
        ),
        "window": "Snapshot atual + preços do basket (preço informado).",
        "source": "portfolio.json + fund_config.json + yfinance (preços/fundamentals).",
        "interpretation": (
            "Δ na cota é o impacto esperado se o basket for executado AGORA. "
            "Δ Grupo I < 67% = violação CVM 175 (ver compliance abaixo). "
            "Caixa negativo após o basket = atenção, fundo não tem recurso."
        ),
    },

    "pt_card_compliance": {
        "title": "Compliance — Resolução CVM 175 + Limites Internos",
        "what": (
            "Valida o resultado do basket contra: (a) regra obrigatória da "
            "Res. CVM 175 (mín 67% em Ações/BDRs); (b) limites internos "
            "configuráveis de concentração por ativo e por setor."
        ),
        "formula": (
            "Status por regra:\n"
            "  OK         : dentro do limite\n"
            "  ALERTA     : valor entre 85%-100% do limite\n"
            "  VIOLAÇÃO   : ultrapassou o limite\n\n"
            "Regras:\n"
            "  • Grupo I mín 67%   (CVM 175, obrigatória)\n"
            "  • Conc. por ativo ≤ limite_concentracao_ativo_pct\n"
            "    (apenas se enable_concentracao_ativo = true)\n"
            "  • Conc. por setor ≤ limite_concentracao_setor_pct\n"
            "    (apenas se enable_concentracao_setor = true)\n"
            "  • Caixa Disponível (alerta se ficar negativo)"
        ),
        "window": "Pós-simulação.",
        "source": "fund_config.json (limites) + yfinance (setor por ticker).",
        "interpretation": (
            "Violação não impede SALVAR a simulação no histórico, mas o "
            "botão EXECUTAR abre modal de confirmação extra. O PDF de "
            "auditoria registra o status de cada regra na hora da execução."
        ),
    },

    "pt_card_carteira_antes_depois": {
        "title": "Carteira — Antes vs Depois",
        "what": (
            "Tabela com cada ativo da carteira mostrando o peso (% do PL) "
            "antes e depois do basket. Marcadores: [+NOVO] para tickers "
            "que não estavam na carteira; [-ZERADO] para posições removidas."
        ),
        "formula": (
            "Antes  % = valor_atual_i / NAV_atual × 100\n"
            "Depois % = valor_simulado_i / NAV_simulado × 100\n"
            "Δ pp     = Depois − Antes  (em pontos percentuais)\n\n"
            "Tickers tocados pelo basket aparecem destacados em laranja."
        ),
        "window": "Snapshot atual vs portfolio_sim (clone após aplicar basket).",
        "source": "portfolio.json + build_portfolio_response.",
        "interpretation": (
            "Use para confirmar visualmente que os pesos pós-trade ficaram "
            "alinhados com a tese. Acompanhe ativos que cruzam o limite de "
            "concentração interna (laranja → vermelho na regra de compliance)."
        ),
    },

    "pt_params_compliance": {
        "title": "Parâmetros de Compliance — Pré-Trade",
        "what": (
            "Limites internos de concentração por ativo e por setor, "
            "habilitáveis individualmente. Quando desabilitados, a regra "
            "fica visível mas não é avaliada (status: INATIVO)."
        ),
        "formula": (
            "Por Ativo: pct_ativo > limite → violação. Calculado por\n"
            "  pct = valor_ativo / NAV.\n"
            "Por Setor: somar valores por setor (de yfinance), dividir por\n"
            "  NAV. Acima do limite → violação.\n\n"
            "Limites default: 20% por ativo, 40% por setor."
        ),
        "window": "Alterações entram em vigor na próxima simulação.",
        "source": "fund_config.json (campos limite_concentracao_*).",
        "interpretation": (
            "Mantenha habilitado em produção para auditoria preventiva. "
            "Os limites são internos (não regulatórios) — ajuste conforme "
            "política do fundo."
        ),
    },

    # ═════════════════════════ CVM OFICIAL ═════════════════════════

    "cvm_kpi_cota": {
        "title": "Cota CVM (oficial)",
        "what": (
            "Valor da cota reportado pelo administrador (Banco Daycoval) à "
            "CVM no informe diário (FI-DOC INF_DIARIO). É a cota OFICIAL "
            "do fundo — usada para PL, captação e resgate junto aos cotistas."
        ),
        "formula": "Campo `vl_quota` do registro mais recente do informe.",
        "window": "Último dia útil reportado (T-1 em relação a hoje).",
        "source": "dados.cvm.gov.br/dataset/fi-doc-inf_diario — XLSX mensal.",
        "interpretation": (
            "Comparar com a Cota Calculada pelo terminal (Aba 200) para "
            "validar consistência. Diff esperado: ≤ 0.1% (proventos/custos)."
        ),
    },

    "cvm_kpi_diff": {
        "title": "Diff CVM vs Calculada",
        "what": (
            "Diferença percentual entre a cota oficial CVM e a cota "
            "calculada pelo terminal no mesmo dia. Métrica de validação — "
            "diferenças grandes indicam discrepância em proventos, custos, "
            "ou preços usados."
        ),
        "formula": (
            "diff_cota_pct = (cota_cvm − cota_calc) / cota_calc × 100\n\n"
            "Match-up: procura o dia mais recente em que ambos os valores "
            "existem (calculada via quota_history.json)."
        ),
        "window": "Dia mais recente com sobreposição (data exibida abaixo do KPI).",
        "source": "cvm_daily.json × quota_history.json.",
        "interpretation": (
            "± 0.05% = ótimo. ± 0.1-0.5% = aceitável (depende do regulamento). "
            "> 1% = investigar (preços de fechamento, proventos pendentes, "
            "custos provisionados não refletidos)."
        ),
    },

    "cvm_kpi_pl": {
        "title": "Patrimônio Líquido (PL)",
        "what": (
            "Valor total do patrimônio do fundo reportado à CVM. Inclui "
            "carteira + caixa + provisões − despesas, tudo apurado pelo "
            "administrador segundo regras CVM/CPC."
        ),
        "formula": "Campo `vl_patrim_liq` do informe diário mais recente.",
        "window": "Último dia útil reportado.",
        "source": "FI-DOC INF_DIARIO.",
        "interpretation": (
            "Crescente: captação líquida positiva ou retorno positivo da "
            "carteira. Quedas abruptas sem variação de cota = resgates."
        ),
    },

    "cvm_kpi_pl_medio_12m": {
        "title": "PL Médio 12M",
        "what": (
            "Patrimônio líquido médio diário do fundo nos últimos 12 meses. "
            "É a medida de porte exigida em informes, lâminas e materiais "
            "regulatórios (padrão CVM/ANBIMA)."
        ),
        "formula": (
            "Média aritmética simples do campo `vl_patrim_liq` de todos os "
            "dias reportados nos últimos 365 dias corridos:\n\n"
            "PL médio = Σ(vl_patrim_liq dos últimos 365d) ÷ nº de dias."
        ),
        "window": "Últimos 365 dias corridos (móvel).",
        "source": "FI-DOC INF_DIARIO.",
        "interpretation": (
            "Suaviza oscilações pontuais do PL, refletindo o porte médio do "
            "fundo ao longo do ano. Usado como base para comparações e "
            "divulgações regulatórias."
        ),
    },

    "cvm_kpi_cotst": {
        "title": "Nº de Cotistas",
        "what": (
            "Quantidade de cotistas (pessoas físicas/jurídicas) com posição "
            "no fundo na data de referência. Reportado oficialmente à CVM."
        ),
        "formula": (
            "Campo `nr_cotst` do informe diário.\n\n"
            "Variação Δ 30d = nr_cotst_atual − nr_cotst_30_dias_atrás\n"
            "Variação Δ YTD = nr_cotst_atual − nr_cotst_em_01-jan."
        ),
        "window": "Pontual (último dia) + variações 30d/YTD.",
        "source": "FI-DOC INF_DIARIO.",
        "interpretation": (
            "Crescimento estável = saúde comercial. Quedas grandes = atenção "
            "a movimentos de resgate. Δ YTD positivo significa entradas "
            "líquidas de cotistas no ano."
        ),
    },

    "cvm_kpi_captc_30d": {
        "title": "Captação Líquida (30 dias)",
        "what": (
            "Fluxo líquido de entradas (captação) − saídas (resgate) "
            "registrados oficialmente nos últimos 30 dias úteis."
        ),
        "formula": (
            "captc_liq_30d = Σ (captc_dia − resg_dia) para os últimos\n"
            "  ~30 dias do informe (cobre dias úteis e não-úteis).\n\n"
            "Positivo: entrou mais dinheiro do que saiu.\n"
            "Negativo: resgates superaram aplicações."
        ),
        "window": "30 dias corridos a partir do último registro.",
        "source": "FI-DOC INF_DIARIO (campos captc_dia, resg_dia).",
        "interpretation": (
            "Usar junto com a curva de Resgate Projetado na aba LIQUIDEZ "
            "(o histórico de resg_dia alimenta a curva de stress)."
        ),
    },

    "cvm_kpi_captc_12m": {
        "title": "Captação Líquida (12 meses)",
        "what": (
            "Mesma fórmula da Captação Líquida 30d, mas em janela de "
            "365 dias. Métrica útil para visão anual de fluxo."
        ),
        "formula": "captc_liq_12m = Σ (captc_dia − resg_dia) dos últimos 365 dias.",
        "window": "365 dias corridos a partir do último registro.",
        "source": "FI-DOC INF_DIARIO.",
        "interpretation": (
            "Métrica de captação reportada em relatórios anuais. Combine "
            "com a evolução do PL para entender se o crescimento veio de "
            "captação ou de performance."
        ),
    },

    "cvm_chart_pl": {
        "title": "Evolução do Patrimônio Líquido",
        "what": "Série temporal do PL oficial do fundo desde o início.",
        "formula": "Valores brutos de `vl_patrim_liq` ordenados por data.",
        "window": "Desde a data de início da cota (geralmente 2022-04-18).",
        "source": "FI-DOC INF_DIARIO.",
        "interpretation": (
            "Inclinação positiva = crescimento (captação ou retorno). "
            "Quedas abruptas correlacionadas com Cotistas em queda = "
            "movimentos de resgate."
        ),
    },

    "cvm_chart_cota_vs": {
        "title": "Cota CVM vs Cota Calculada",
        "what": (
            "Sobrepõe a cota oficial CVM (laranja) com a cota calculada "
            "pelo terminal (verde) ao longo do tempo. Mostra visualmente "
            "a aderência entre as duas séries."
        ),
        "formula": (
            "Cota CVM: vl_quota do informe.\n"
            "Cota Calc: cota_fechamento de quota_history.json (gerado pelo\n"
            "  auto-close a partir de calculate_quota)."
        ),
        "window": "Toda a sobreposição disponível.",
        "source": "cvm_daily.json + quota_history.json.",
        "interpretation": (
            "Linhas coladas = cálculo do terminal está consistente. "
            "Divergências sistemáticas indicam fórmula de cálculo precisa "
            "de ajuste (proventos, custos, etc)."
        ),
    },

    "cvm_chart_fluxo": {
        "title": "Fluxo Diário — Captação vs Resgate",
        "what": (
            "Barras diárias: verde = captação (entradas), vermelho = "
            "resgate (saídas). Mostra os movimentos brutos de cotistas."
        ),
        "formula": "captc_dia e resg_dia, plotados como barras separadas.",
        "window": "Toda a história do informe.",
        "source": "FI-DOC INF_DIARIO.",
        "interpretation": (
            "Histórico de pico de resgates alimenta a curva de Resgate "
            "Projetado da aba LIQUIDEZ (percentis P75/P95 nos cenários "
            "Stress/Crise)."
        ),
    },

    "cvm_chart_cotst": {
        "title": "Evolução do Nº de Cotistas",
        "what": "Quantidade de cotistas em cada data de reporte (step chart).",
        "formula": "Campo nr_cotst ordenado por data.",
        "window": "Desde o início do fundo.",
        "source": "FI-DOC INF_DIARIO.",
        "interpretation": (
            "Crescimento = saúde comercial. Estagnação ou queda sustentada "
            "merece investigação (taxa de saída de cotistas)."
        ),
    },

    # ═════════════════════════ GRÁFICOS (tab-charts) ═════════════════════════

    "chart_drawdown": {
        "title": "Drawdown",
        "what": (
            "Perda acumulada desde o último topo. Mede a maior queda da "
            "cota a partir do pico mais recente — métrica clássica de "
            "risco de perda em fundos."
        ),
        "formula": (
            "Para cada dia t:\n"
            "  pico(t) = max(cota(τ) para τ ≤ t)\n"
            "  DD(t)   = (cota(t) − pico(t)) / pico(t) × 100  (≤ 0)\n\n"
            "DD ATUAL: drawdown no último dia da série.\n"
            "DD MÁX:   menor valor de DD em toda a janela."
        ),
        "window": "Configurável pelo seletor (1S/1M/3M/6M/1A) sobre quota_history.",
        "source": "quota_history.json (cota_fechamento).",
        "interpretation": (
            "DD muito negativo = grande perda não recuperada. Tempo para "
            "voltar ao pico (recovery time) é tão importante quanto a "
            "profundidade. Use em conjunto com VaR/CVaR da aba RISCO."
        ),
    },

    "chart_volatilidade": {
        "title": "Volatilidade Anualizada (21 dias)",
        "what": (
            "Desvio-padrão dos retornos diários da cota, computado em "
            "janela rolante de 21 dias úteis e anualizado por √252 — "
            "padrão de indústria."
        ),
        "formula": (
            "Para cada dia t na janela:\n"
            "  σ_21(t) = stdev(r(t−20), ..., r(t))\n"
            "  σ_anual(t) = σ_21(t) × √252 × 100  (em %)"
        ),
        "window": "21 dias úteis rolantes (~1 mês).",
        "source": "quota_history.json → retornos diários.",
        "interpretation": (
            "Volatilidade típica de FIAs: 15-30% a.a. Picos súbitos em "
            "datas de stress (mercado em crise). Métrica essencial para "
            "comunicar risco ao cotista."
        ),
    },

    "chart_atribuicao": {
        "title": "Atribuição de Retorno por Ativo",
        "what": (
            "Decompõe o retorno do fundo no período por ativo (contribuição "
            "ponderada). Identifica o que puxou a performance pra cima e "
            "pra baixo."
        ),
        "formula": (
            "Para cada ativo i:\n"
            "  contrib_i = peso_médio_i × retorno_i\n"
            "  (peso_médio aproximado pela média geométrica de início e fim)"
        ),
        "window": "Mesmo range selecionado para os outros gráficos.",
        "source": "portfolio_history.json + preços históricos yfinance.",
        "interpretation": (
            "Soma de todas as contribuições ≈ retorno total do fundo no "
            "período. Identifique os 3 maiores contribuidores (positivos "
            "e negativos) para narrativa de performance ao cotista."
        ),
    },

    "chart_concentracao": {
        "title": "Concentração por Ativo",
        "what": (
            "Distribuição do PL entre as posições da carteira. Visualiza "
            "exposição e concentração de risco em poucos nomes."
        ),
        "formula": "pct_ativo_i = valor_liquido_i / NAV_total × 100.",
        "window": "Snapshot atual.",
        "source": "portfolio.json + preços atuais (yfinance).",
        "interpretation": (
            "Concentração elevada (top 3 > 60%) implica alta volatilidade "
            "idiossincrática. Cruzar com o HHI da aba RISCO para visão "
            "consolidada de concentração."
        ),
    },

    "chart_upside": {
        "title": "Upside por Ativo",
        "what": (
            "Potencial de valorização (em %) de cada posição até o preço-"
            "alvo definido pelo gestor."
        ),
        "formula": (
            "upside_i = (preço_alvo_i − preço_atual_i) / preço_atual_i × 100\n\n"
            "Preço-alvo é configurado manualmente no modal de edição da posição."
        ),
        "window": "Snapshot atual.",
        "source": "portfolio.json (campo preco_alvo) + yfinance (preco atual).",
        "interpretation": (
            "Upside ponderado pelo peso = retorno esperado da carteira se "
            "todos os ativos atingirem preço-alvo. Comparar com IBOV "
            "esperado para validar tese."
        ),
    },

    "chart_consistencia": {
        "title": "Consistência — Distribuição de Retornos",
        "what": (
            "Histograma dos retornos diários da cota. Visualiza assimetria, "
            "concentração em zero, e cauda gorda."
        ),
        "formula": (
            "Bins dos retornos diários da cota no range selecionado.\n"
            "Métricas associadas: skewness, kurtosis, % dias positivos."
        ),
        "window": "Range selecionado no card de range.",
        "source": "quota_history.json → retornos diários.",
        "interpretation": (
            "Distribuição simétrica em torno de zero = retornos 'normais'. "
            "Cauda esquerda gorda = risco de perdas extremas (típico em "
            "mercados de stress). Use junto com VaR da aba RISCO."
        ),
    },

    # ═════════════════════════ TABELA (colunas calculadas) ═════════════════════════

    "tab_upside": {
        "title": "Upside (%)",
        "what": "Potencial de valorização até o preço-alvo definido manualmente.",
        "formula": "(preço_alvo − preço_atual) / preço_atual × 100.",
        "window": "Pontual (preço atual de mercado).",
        "source": "portfolio.json (preco_alvo) + yfinance (preço atual).",
        "interpretation": (
            "Verde = potencial de alta; vermelho = preço acima do alvo "
            "(reavaliar tese). Mantenha o preço-alvo atualizado quando "
            "o fundamento do ativo mudar."
        ),
    },

    "tab_pl_fwd": {
        "title": "P/L Forward",
        "what": (
            "Razão preço/lucro estimado para o próximo ano fiscal — "
            "métrica de valuation forward-looking."
        ),
        "formula": "preço_atual / lucro_por_acao_estimado_próximo_ano.",
        "window": "Estimativas de analistas (consenso).",
        "source": "yfinance (campo forwardPE).",
        "interpretation": (
            "Menor que P/L Trailing = analistas esperam crescimento de "
            "lucro. Comparar com pares do setor. Acima de 30 em ações "
            "maduras = preço esticado."
        ),
    },

    "tab_beta": {
        "title": "Beta (vs S&P 500 — yfinance)",
        "what": (
            "Sensibilidade do ativo aos movimentos do mercado de "
            "referência. yfinance usa S&P 500 por default (mesmo para "
            "ações brasileiras — limitação)."
        ),
        "formula": "covariância(retornos_ativo, retornos_mkt) / variância(retornos_mkt).",
        "window": "Janela default do yfinance (~3 anos).",
        "source": "yfinance (campo beta).",
        "interpretation": (
            "β > 1 = mais volátil que o mercado; β < 1 = menos. Para análise "
            "vs IBOV use a aba RISCO (Beta Rolante 60d) que recalcula com "
            "IBOV como referência."
        ),
    },

    "tab_dy": {
        "title": "Dividend Yield",
        "what": (
            "Dividendos pagos nos últimos 12 meses como % do preço atual. "
            "Renda de dividendo se mantida a política atual."
        ),
        "formula": "dividendos_pagos_12m / preço_atual × 100.",
        "window": "Últimos 12 meses (trailing).",
        "source": "yfinance (campo dividendYield).",
        "interpretation": (
            "Alto DY (>8%) pode indicar preço deprimido OU política "
            "agressiva de payout. Para FIIs, métrica central. Para ações, "
            "avaliar payout ratio também."
        ),
    },

    "tab_mkt_cap": {
        "title": "Market Cap (R$ bilhões)",
        "what": "Valor de mercado total da empresa = preço × ações em circulação.",
        "formula": "preço_atual × shares_outstanding.",
        "window": "Snapshot.",
        "source": "yfinance (campo marketCap).",
        "interpretation": (
            "Classificação típica BR: < R$ 5B small cap, R$ 5-30B mid cap, "
            "> R$ 30B large cap. Para BDRs, valor da empresa US (não tem "
            "split brasileiro)."
        ),
    },

    # ═════════════════════════ HISTÓRICO DA CARTEIRA (aba 213) ═════════════════════════

    "ph_card_timeline": {
        "title": "Timeline de Snapshots da Carteira",
        "what": (
            "Lista todos os snapshots gravados de portfolio_history.json, "
            "agrupados por mês. Cada snapshot é a foto completa da carteira "
            "naquele momento (posições, preços, NAV, cota)."
        ),
        "formula": (
            "Snapshots gerados em 2 momentos:\n"
            "  • AUTO: auto-close diário 17:35 BRT (dias úteis), via\n"
            "    api_quota-history/auto-close → _build_portfolio_snapshot\n"
            "  • MANUAL: botão SALVAR SNAPSHOT na aba TABELA."
        ),
        "window": "Toda a história desde o primeiro snapshot.",
        "source": "data/portfolio_history.json.",
        "interpretation": (
            "Clique em qualquer snapshot para ver a carteira completa "
            "daquela data. Use o botão PDF para baixar relatório de "
            "auditoria do dia específico. Lacunas no histórico indicam "
            "dias em que o auto-close falhou (raro após o fix de "
            "persistência síncrona)."
        ),
    },

    "ph_card_comparar": {
        "title": "Diff entre 2 Datas da Carteira",
        "what": (
            "Compara duas snapshots da carteira e mostra tudo o que mudou "
            "entre elas: posições novas/removidas/alteradas, deltas de NAV, "
            "rotação setorial, mudança de concentração."
        ),
        "formula": (
            "Para cada ticker que aparece em pelo menos um dos snapshots:\n"
            "  Δ qtde  = qtde_to − qtde_from\n"
            "  Δ valor = valor_to − valor_from\n"
            "  Δ pp    = pct_to − pct_from\n\n"
            "Status:\n"
            "  novo      : entrou na carteira no período\n"
            "  removido  : saiu da carteira\n"
            "  aumentou  : aumento de quantidade\n"
            "  reduziu   : redução de quantidade\n"
            "  manteve   : sem alteração de quantidade\n\n"
            "Se a data exata não tiver snapshot, usa o mais recente em ou "
            "antes da data informada."
        ),
        "window": "Entre as duas datas selecionadas.",
        "source": "data/portfolio_history.json (helper _diff_snapshots).",
        "interpretation": (
            "Use para reporting mensal/trimestral, ou para responder \"o "
            "que mudou desde a última auditoria\". Posições ordenadas por "
            "|Δ valor| desc — primeiras são as mais impactantes."
        ),
    },

    "ph_chart_nav": {
        "title": "Evolução do NAV (R$)",
        "what": (
            "Valor de ativos da carteira (sem caixa/proventos) ao longo do "
            "tempo, calculado em cada snapshot."
        ),
        "formula": "NAV = Σ (quantidade_i × preço_i) no momento do snapshot.",
        "window": "Toda a história de snapshots.",
        "source": "summary.total_value em cada snapshot de portfolio_history.json.",
        "interpretation": (
            "Inclinação reflete combinação de retorno da carteira + entradas/"
            "saídas de capital. Para isolar o retorno puro, comparar com a "
            "Cota Estimada (mesma aba, sub-aba EVOLUÇÃO no futuro)."
        ),
    },

    "ph_chart_npos": {
        "title": "Nº de Posições",
        "what": (
            "Quantidade de tickers diferentes na carteira em cada snapshot. "
            "Indicador de diversificação por ativo."
        ),
        "formula": "len(snapshot.rows).",
        "window": "Toda a história.",
        "source": "Contagem de posições por snapshot.",
        "interpretation": (
            "Crescente = maior diversificação. Quedas indicam consolidação "
            "(removeu posições) ou stop em ativos. Cruzar com HHI para ver "
            "se a concentração também acompanhou."
        ),
    },

    "ph_chart_hhi": {
        "title": "HHI Concentração (por ativo)",
        "what": (
            "Índice de Herfindahl-Hirschman da concentração por ativo da "
            "carteira. Métrica clássica de concentração: menor = mais "
            "diversificado, maior = mais concentrado."
        ),
        "formula": (
            "HHI = Σ (pct_ativo_i)² × 10.000  (com pct em 0..1)\n\n"
            "Range típico: 500 (muito diversificado) a 3.000 (concentrado).\n"
            "Se 100% em 1 ativo → HHI = 10.000."
        ),
        "window": "Calculado em cada snapshot.",
        "source": "summary.rows + cálculo HHI em _ph_extract_metrics.",
        "interpretation": (
            "Subindo = carteira ficando mais concentrada (poucos ativos "
            "ganhando peso). Útil para auditar política de risco de "
            "concentração."
        ),
    },

    "ph_chart_grupo1": {
        "title": "% Grupo I (Ações + BDRs) — Res. CVM 175",
        "what": (
            "Percentual do NAV alocado em ativos do Grupo I (Ações + BDRs), "
            "exigência mínima de 67% para FIA conforme Res. CVM 175."
        ),
        "formula": (
            "Grupo I = {Acao, BDR, Acao BDR}\n"
            "pct_g1 = Σ valor_i (para categoria ∈ Grupo I) / NAV × 100"
        ),
        "window": "Calculado em cada snapshot.",
        "source": "categoria por posição em portfolio.json (snapshot rows).",
        "interpretation": (
            "Deve estar sempre ≥ 67% (linha implícita). Quedas abaixo "
            "indicam violação regulatória — investigar imediatamente. "
            "Mesma regra avaliada no pré-trade antes de cada execução."
        ),
    },

    "ph_chart_setor": {
        "title": "Rotação Setorial (% por Setor ao Longo do Tempo)",
        "what": (
            "Gráfico empilhado mostrando como o peso de cada setor da "
            "carteira evoluiu. Permite ver rotações setoriais explícitas "
            "ao longo do tempo."
        ),
        "formula": (
            "Para cada snapshot e setor:\n"
            "  pct_setor = Σ valor_ativos_do_setor / NAV × 100\n\n"
            "Setor vem do yfinance (campo sector), traduzido para PT."
        ),
        "window": "Toda a história.",
        "source": "rows[].sector em cada snapshot.",
        "interpretation": (
            "Mudanças bruscas em camadas = rebalanceamento setorial. "
            "Camadas dominantes consistentes = tese setorial forte. "
            "Usa categoria 'Outros' quando o yfinance não retornou setor."
        ),
    },

    "ph_card_operacoes": {
        "title": "Operações Inferidas + Cross-match com Pré-Trade",
        "what": (
            "Compara cada par de snapshots consecutivos no histórico e "
            "infere as operações que devem ter ocorrido (variações de "
            "quantidade). Cruza com pretrade_history.executed_at para "
            "identificar quais operações passaram pelo workflow oficial "
            "e quais foram mudanças manuais sem registro."
        ),
        "formula": (
            "Para cada par (snap_t-1, snap_t):\n"
            "  Para cada ticker com Δ qtde ≠ 0:\n"
            "    direção = 'compra' se Δ>0, 'venda' se reduziu, 'zerou' se 0\n"
            "    preço estimado = (preço_t-1 + preço_t) / 2\n"
            "    valor estimado = |Δ qtde| × preço estimado\n\n"
            "Cross-match: busca em pretrade_history os executed_at no "
            "intervalo da janela, match por ticker + direção + |Δ qtde| "
            "mais próximo."
        ),
        "window": "Configurável (DE/ATÉ). Default = toda a história.",
        "source": "portfolio_history + pretrade_history.",
        "interpretation": (
            "✓ RASTREADA = operação inferida bate com pré-trade executado. "
            "⚠ MANUAL = mudança da carteira sem registro de pré-trade "
            "(alteração direta de quantidade via modal). Para auditoria "
            "ANBIMA, todas as operações deveriam estar rastreadas."
        ),
    },

    "tab_var_dia": {
        "title": "Variação do Dia (%)",
        "what": "Retorno do ativo no pregão atual em relação ao fechamento de ontem.",
        "formula": "(preço_atual − preço_fechamento_anterior) / preço_fechamento_anterior × 100.",
        "window": "Intraday + close anterior.",
        "source": "yfinance fast_info (last_price + previous_close).",
        "interpretation": (
            "Ponderado pelo peso na carteira, alimenta a variação estimada "
            "da cota intraday (topbar do app)."
        ),
    },
}
