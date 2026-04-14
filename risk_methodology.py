# -*- coding: utf-8 -*-
"""
Metodologia das métricas da aba Risco — fonte única de verdade para tooltips
de auditoria / due diligence.

Cada entrada descreve UMA métrica (card ou sub-métrica) que o investidor vê
no dashboard. O conteúdo é consumido pelo frontend via Jinja
(window.RISK_METHODOLOGY) e renderizado nos tooltips expandidos ao passar o
mouse sobre o ícone ⓘ.

Como adicionar uma nova métrica:
    1. Adicionar uma nova entrada abaixo com as 5 seções (what / formula /
       window / source / interpretation).
    2. No template HTML, incluir
       <span class="col-info" data-tip-key="nova_chave">ⓘ</span>
    3. Nenhuma alteração em JS/CSS é necessária.

IMPORTANTE: manter os textos fielmente alinhados com as fórmulas em app.py.
Quando o cálculo mudar, ATUALIZAR AQUI — este arquivo é a fonte que o
compliance irá revisar.
"""

RISK_METHODOLOGY: dict = {

    # ───────────────────────── VaR / CVaR ─────────────────────────
    "card_var": {
        "title": "Value at Risk (VaR) & Conditional VaR (CVaR)",
        "what": (
            "VaR estima a perda máxima esperada do fundo, em R$ e em % do "
            "NAV, em um horizonte de 1 ou 10 dias úteis, para um dado nível "
            "de confiança (95% ou 99%). CVaR (Expected Shortfall) é a média "
            "das perdas que excedem o VaR — captura o 'tamanho' da cauda."
        ),
        "formula": (
            "Método histórico (não paramétrico):\n"
            "  • Ordena-se a série de retornos diários em ordem crescente.\n"
            "  • VaR_95 = |percentil 5%|  ;  VaR_99 = |percentil 1%|\n"
            "  • CVaR_95 = |média dos retornos ≤ percentil 5%|\n"
            "  • Escalonamento 10D: VaR_10d = VaR_1d × √10 "
            "(hipótese de i.i.d. via raiz do tempo)."
        ),
        "window": (
            "Janelas configuráveis no card: 63D, 126D, 252D (default). "
            "Horizonte: 1D (default) ou 10D."
        ),
        "source": (
            "Histórico de cotas do fundo (load_quota_history). "
            "NAV de referência = valor do portfólio + caixa + proventos "
            "a receber."
        ),
        "interpretation": (
            "VaR_95 1D = 2% significa que em 95 de 100 dias a perda não "
            "ultrapassará 2% do NAV. CVaR sendo muito maior que o VaR "
            "indica cauda gorda — perdas extremas são severas quando ocorrem."
        ),
    },
    "var_95": {
        "title": "VaR 95% (1D e 10D)",
        "what": (
            "Perda máxima esperada do fundo com 95% de confiança — isto é, "
            "em 95% dos dias a perda diária não deve ultrapassar esse valor."
        ),
        "formula": (
            "VaR_95_1d = |r_(idx_95)| onde idx_95 = floor(n × 0,05) na "
            "série ordenada de retornos.\n"
            "VaR_95_10d = VaR_95_1d × √10."
        ),
        "window": "Definida pelo seletor do card (63/126/252D).",
        "source": "Retornos diários derivados de cota_fechamento.",
        "interpretation": (
            "Nível padrão da indústria (ANBIMA/CVM) para comunicação de risco."
        ),
    },
    "var_99": {
        "title": "VaR 99% (1D e 10D)",
        "what": (
            "Perda máxima esperada do fundo com 99% de confiança — "
            "mede o risco em cenário mais extremo que o VaR 95%."
        ),
        "formula": (
            "VaR_99_1d = |r_(idx_99)| onde idx_99 = floor(n × 0,01) na "
            "série ordenada de retornos.\n"
            "VaR_99_10d = VaR_99_1d × √10."
        ),
        "window": "Definida pelo seletor do card (63/126/252D).",
        "source": "Retornos diários derivados de cota_fechamento.",
        "interpretation": (
            "Usado como métrica de estresse 'normal'. Perdas maiores que esse "
            "valor devem ocorrer em ~1% dos dias úteis — cerca de 2–3 vezes "
            "por ano considerando 252 dias úteis."
        ),
    },
    "cvar": {
        "title": "Conditional VaR (Expected Shortfall)",
        "what": (
            "Média das perdas que excedem o VaR. Responde à pergunta: "
            "'quando passamos do VaR, qual é a perda média esperada?'"
        ),
        "formula": (
            "CVaR_95 = média aritmética dos retornos ≤ percentil 5%.\n"
            "CVaR_99 = média aritmética dos retornos ≤ percentil 1%."
        ),
        "window": "Mesma janela do VaR selecionado no card.",
        "source": "Retornos diários derivados de cota_fechamento.",
        "interpretation": (
            "CVaR é coerente (subaditividade) — preferido por reguladores "
            "(Basileia III) sobre o VaR puro. Quanto maior a diferença "
            "CVaR − VaR, mais gorda é a cauda de perdas."
        ),
    },

    # ───────────────────────── Stress Test ─────────────────────────
    "card_stress": {
        "title": "Stress Test — Cenários Históricos",
        "what": (
            "Simula o impacto no portfólio atual caso o mercado repetisse "
            "um evento de estresse passado (COVID, Joesley Day, eleição "
            "Lula, impeachment Dilma) ou um cenário customizado definido "
            "pelo usuário."
        ),
        "formula": (
            "Para cada ativo i:\n"
            "  impacto_i = β_i × choque_IBOV + (choque_BRL se i for BDR)\n"
            "Portfolio: impacto_% = Σ w_i × impacto_i\n"
            "Portfolio: impacto_R$ = impacto_% × NAV"
        ),
        "window": (
            "Instantâneo (aplica choques sobre posições atuais). Cenários "
            "pré-configurados usam choques históricos de pico a vale."
        ),
        "source": (
            "Posições e NAV atuais; betas individuais calculados em "
            "fundamentals; categoria BDR identifica exposição cambial."
        ),
        "interpretation": (
            "Serve para questionar 'quanto o fundo perderia se um evento "
            "desses se repetisse hoje?'. Complementa o VaR (que olha só "
            "histórico recente próprio do fundo) com choques realmente "
            "severos já vividos no mercado brasileiro."
        ),
    },

    # ───────────────────────── Correlação ─────────────────────────
    "card_correlation": {
        "title": "Matriz de Correlação",
        "what": (
            "Correlação de Pearson entre os retornos diários de cada ativo "
            "do portfólio e o IBOV, dois a dois. Mede o grau de movimento "
            "conjunto."
        ),
        "formula": (
            "ρ(X,Y) = Cov(X,Y) / (σ_X × σ_Y)\n"
            "Range: −1 (movimento oposto) a +1 (movimento idêntico).\n"
            "Calculada sobre retornos pct_change() das cotações."
        ),
        "window": "60D (default) ou 252D.",
        "source": (
            "Cotações ajustadas via yfinance (auto_adjust=True). "
            "IBOV = ^BVSP."
        ),
        "interpretation": (
            "Correlação alta entre muitas posições reduz a diversificação "
            "real do fundo. Correlação com IBOV próxima de 1 indica que "
            "o ativo é essencialmente beta de mercado."
        ),
    },

    # ─────────────────── Risk Attribution ───────────────────
    "card_attribution": {
        "title": "Risk Attribution — Contribuição ao Risco",
        "what": (
            "Decompõe a volatilidade total do portfólio, atribuindo a cada "
            "ativo o percentual que ele efetivamente contribui para o risco."
        ),
        "formula": (
            "Contribuição_i = w_i × Cov(r_i, r_p) / Var(r_p) × 100%\n"
            "Onde r_p = retorno do portfólio (Σ w_i × r_i).\n"
            "Σ Contribuição_i = 100%.\n"
            "Volatilidade portfólio = σ(r_p) × √252."
        ),
        "window": "60D (default) ou 252D.",
        "source": (
            "Retornos diários via yfinance; pesos baseados em preços e "
            "quantidades atuais do portfólio."
        ),
        "interpretation": (
            "Ativos com contribuição muito maior que seu peso são os "
            "verdadeiros 'driver' de risco. Ajuda a identificar "
            "concentrações de risco ocultas (peso pequeno mas contribuição "
            "alta)."
        ),
    },

    # ─────────────────── Rolling Beta ───────────────────
    "card_rolling_beta": {
        "title": "Beta Rolante 60D vs. IBOV",
        "what": (
            "Beta do fundo contra o IBOV calculado em janela móvel de 60 "
            "dias úteis. Mede a sensibilidade dos retornos do fundo às "
            "oscilações do mercado, ao longo do tempo."
        ),
        "formula": (
            "β_t = Cov(r_fundo, r_IBOV) / Var(r_IBOV)\n"
            "Calculado na janela [t−60, t] com variância e covariância "
            "amostrais (denominador n−1).\n"
            "Série gerada dia a dia, rolando a janela."
        ),
        "window": "Janela móvel de 60 dias úteis.",
        "source": (
            "Retornos diários do fundo (cota) alinhados por data com "
            "retornos do IBOV (^BVSP, yfinance)."
        ),
        "interpretation": (
            "β > 1: fundo amplifica movimentos do IBOV. β < 1: defensivo. "
            "β instável no tempo indica mudança de postura (alavancagem, "
            "rotação para setores mais/menos cíclicos)."
        ),
    },
    "rolling_beta": {
        "title": "Beta Rolante (valor atual)",
        "what": "Valor mais recente da série de beta rolante.",
        "formula": "Cov(r_fundo, r_IBOV) / Var(r_IBOV) na janela [hoje−60, hoje].",
        "window": "60D.",
        "source": "Retornos diários do fundo e IBOV alinhados por data.",
        "interpretation": (
            "Compare com o beta médio histórico para avaliar se o fundo "
            "está mais ou menos exposto ao mercado que o usual."
        ),
    },

    # ─────────────────── Liquidez ───────────────────
    "card_liquidity": {
        "title": "Risco de Liquidez",
        "what": (
            "Estima a proporção do portfólio que pode ser liquidada em 1, "
            "5 e 10 dias úteis sem mover o mercado, baseada no volume "
            "médio negociado de cada posição."
        ),
        "formula": (
            "Para cada posição i:\n"
            "  days_i = dias necessários para liquidar (derivado do score "
            "de liquidez diária média mensal — liq_diaria_mm)\n"
            "  liq_1d_i = min(valor_i, valor_i × 1/days_i)\n"
            "  liq_5d_i = min(valor_i, valor_i × 5/days_i)\n"
            "  liq_10d_i = min(valor_i, valor_i × 10/days_i)\n"
            "Portfolio: soma ponderada dividida pelo valor total."
        ),
        "window": (
            "Snapshot das posições atuais; scores de liquidez baseados no "
            "volume médio mensal recente (dados fundamentais)."
        ),
        "source": (
            "Volume financeiro diário médio (função _liq_days_from_score "
            "em app.py). Hipótese: liquidar até 1/days do tamanho da "
            "posição por dia sem impactar preço."
        ),
        "interpretation": (
            "Liq_1d = 60% significa que 60% do portfólio poderia ser "
            "vendido em um dia útil. Quanto maior o valor, mais líquido — "
            "crítico para fundos abertos sujeitos a resgate."
        ),
    },

    # ──────────── Tracking Error & Information Ratio ────────────
    "card_tracking_error": {
        "title": "Tracking Error & Information Ratio",
        "what": (
            "Tracking Error (TE) mede a dispersão dos retornos do fundo "
            "em relação ao IBOV — quanto o fundo 'desvia' do benchmark. "
            "Information Ratio (IR) mede quanto retorno ativo é gerado "
            "por unidade de TE."
        ),
        "formula": (
            "excess_t = r_fundo_t − r_IBOV_t\n"
            "TE = √Var_amostral(excess) × √252       (anualizado)\n"
            "Retorno Ativo = média(excess) × 252     (anualizado)\n"
            "IR = Retorno Ativo / TE"
        ),
        "window": "252D (default), 126D ou 63D.",
        "source": (
            "Cotas do fundo alinhadas por data com IBOV (^BVSP, yfinance)."
        ),
        "interpretation": (
            "TE alto → portfólio muito ativo vs. benchmark. "
            "IR > 0,5 = bom; IR > 1,0 = excelente. "
            "IR alto indica que o gestor gera retorno acima do benchmark "
            "de forma eficiente em termos de risco ativo assumido."
        ),
    },
    "tracking_error": {
        "title": "Tracking Error (anualizado)",
        "what": (
            "Volatilidade anualizada da diferença de retornos entre o "
            "fundo e o IBOV."
        ),
        "formula": (
            "TE = √(Σ(excess − mean(excess))² / (n−1)) × √252\n"
            "com excess_t = r_fundo_t − r_IBOV_t."
        ),
        "window": "Janela do card (63/126/252D).",
        "source": "Retornos diários do fundo e IBOV alinhados por data.",
        "interpretation": (
            "TE alto = fundo muito distante do IBOV (sem compromisso "
            "com o benchmark). Um FIA 'benchmark-hugger' tem TE baixo "
            "(<3% a.a.); fundos ativos tipicamente 5–15% a.a."
        ),
    },
    "retorno_ativo": {
        "title": "Retorno Ativo (anualizado)",
        "what": (
            "Diferença entre o retorno anualizado do fundo e o retorno "
            "anualizado do IBOV no período — também chamado de 'alpha' "
            "simples (sem ajuste por beta)."
        ),
        "formula": (
            "Retorno Ativo = média(r_fundo_t − r_IBOV_t) × 252\n"
            "Retornos diários compostos podem ser usados de forma "
            "alternativa; aqui usamos média × 252 (consistente com a "
            "definição do Tracking Error)."
        ),
        "window": "Janela do card (63/126/252D).",
        "source": "Retornos diários do fundo e IBOV alinhados por data.",
        "interpretation": (
            "Retorno Ativo > 0 indica que o fundo bateu o IBOV no período. "
            "Sozinho é incompleto — combine com IR para avaliar se esse "
            "alpha foi gerado com risco ativo razoável."
        ),
    },
    "information_ratio": {
        "title": "Information Ratio (IR)",
        "what": (
            "Retorno ativo (acima do IBOV) por unidade de tracking error. "
            "Mede a 'qualidade' da gestão ativa."
        ),
        "formula": (
            "IR = (média(excess) × 252) / TE\n"
            "= Retorno Ativo anual / Tracking Error anual"
        ),
        "window": "Janela do card (63/126/252D).",
        "source": "Retornos diários do fundo e IBOV alinhados por data.",
        "interpretation": (
            "IR > 0 = fundo superou o benchmark no período. "
            "IR > 0,5: bom | IR > 1,0: excelente | IR > 1,5: raro. "
            "Interpretação preferida ao 'alpha bruto' por ajustar ao "
            "risco ativo incorrido."
        ),
    },

    # ─────────── Sortino & Calmar ───────────
    "card_sortino_calmar": {
        "title": "Sortino & Calmar Ratio",
        "what": (
            "Duas métricas de retorno ajustado ao risco que, ao contrário "
            "do Sharpe, penalizam apenas o risco 'ruim' (downside)."
        ),
        "formula": (
            "Sortino = (ret_ann − CDI_ann) / downside_vol_ann\n"
            "   downside_vol = √(Σ r_i² × [r_i<0] / n) × √252 "
            "(MAR = 0)\n"
            "\n"
            "Calmar = ret_ann / |max_drawdown|\n"
            "   max_drawdown = mín_t(cota_t / pico_até_t − 1)"
        ),
        "window": (
            "Múltiplos períodos: no mês, YTD, 3m, 6m, 12m, 24m, 36m, "
            "total. Anualização: (cota_fim/cota_início)^(252/n) − 1."
        ),
        "source": (
            "Cotas do fundo; taxa livre de risco = CDI composto no "
            "período (load_cdi_map)."
        ),
        "interpretation": (
            "Sortino > 1: muito bom — fundo gera prêmio significativo "
            "sobre CDI com pouco downside. Calmar > 1: retorno anual "
            "excede a maior perda pico-a-vale do período (regra comum "
            "em CTAs/hedge funds)."
        ),
    },
    "sortino": {
        "title": "Sortino Ratio",
        "what": (
            "Retorno anualizado acima do CDI, dividido pela volatilidade "
            "dos retornos NEGATIVOS apenas (downside deviation)."
        ),
        "formula": (
            "Sortino = (ret_ann − CDI_ann) / downside_vol_ann\n"
            "downside_vol = √(Σ r_i² onde r_i < 0 / n_total) × √252\n"
            "MAR (retorno mínimo aceitável) = 0."
        ),
        "window": (
            "Calculado em 8 janelas (no mês, YTD, 3m, 6m, 12m, 24m, 36m, "
            "total)."
        ),
        "source": "Cotas diárias do fundo e CDI composto no mesmo período.",
        "interpretation": (
            "Corrige o viés do Sharpe que penaliza também volatilidade "
            "'boa' (retornos positivos). Preferível quando a distribuição "
            "é assimétrica (caso comum em renda variável)."
        ),
    },
    "calmar": {
        "title": "Calmar Ratio",
        "what": (
            "Razão entre o retorno anualizado e o máximo drawdown "
            "(maior perda pico-a-vale) observado no período."
        ),
        "formula": (
            "Calmar = ret_ann / |max_drawdown|\n"
            "max_drawdown = mín_t(cota_t / pico_acumulado_até_t − 1)"
        ),
        "window": (
            "Calculado nas mesmas 8 janelas do Sortino."
        ),
        "source": "Série histórica de cotas do fundo.",
        "interpretation": (
            "Calmar = 1,5 significa que o retorno anual é 1,5× a maior "
            "queda histórica. Métrica muito usada por alocadores — "
            "captura a 'dor' real de passar pela pior fase do fundo."
        ),
    },

    # ─────────── Upside/Downside Capture ───────────
    "card_capture": {
        "title": "Upside / Downside Capture vs. IBOV",
        "what": (
            "Mede quanto do retorno acumulado do IBOV o fundo captura "
            "em dias de alta e em dias de baixa do benchmark, "
            "separadamente."
        ),
        "formula": (
            "Em dias com r_IBOV > 0 (up):\n"
            "  UP = ((1+r_fundo_up,1)×...×(1+r_fundo_up,n) − 1) /\n"
            "       ((1+r_IBOV_up,1)×...×(1+r_IBOV_up,n) − 1)\n"
            "Em dias com r_IBOV < 0 (down): idem com dias de queda.\n"
            "Resultado em % (100% = captura idêntica)."
        ),
        "window": "252D (default), 126D ou TOTAL.",
        "source": "Retornos diários alinhados: fundo (cota) e IBOV (^BVSP).",
        "interpretation": (
            "Padrão ouro: UP > 100% e DOWN < 100%. "
            "Ex: UP=110, DOWN=80 → o fundo captura 110% da alta e "
            "apenas 80% da queda do IBOV (gestão gera alpha assimétrico)."
        ),
    },
    "capture_up": {
        "title": "Upside Capture",
        "what": (
            "Percentual do retorno composto do IBOV em DIAS DE ALTA "
            "que o fundo capturou."
        ),
        "formula": (
            "Em dias t com r_IBOV_t > 0:\n"
            "UP = [Π(1+r_fundo_t) − 1] / [Π(1+r_IBOV_t) − 1] × 100%"
        ),
        "window": "Janela do card.",
        "source": "Retornos diários alinhados fundo × IBOV.",
        "interpretation": (
            "UP > 100% = fundo sobe mais que o IBOV nos dias de alta."
        ),
    },
    "capture_down": {
        "title": "Downside Capture",
        "what": (
            "Percentual do retorno composto do IBOV em DIAS DE BAIXA "
            "que o fundo capturou (sinal preservado — menor é melhor)."
        ),
        "formula": (
            "Em dias t com r_IBOV_t < 0:\n"
            "DOWN = [Π(1+r_fundo_t) − 1] / [Π(1+r_IBOV_t) − 1] × 100%"
        ),
        "window": "Janela do card.",
        "source": "Retornos diários alinhados fundo × IBOV.",
        "interpretation": (
            "DOWN < 100% = fundo cai MENOS que o IBOV em dias de queda. "
            "DOWN < 0% (raro) significa que o fundo subiu em dias em que "
            "o IBOV composto caiu — captura perfeita de proteção."
        ),
    },

    # ─────────── Concentração Setorial ───────────
    "card_concentration": {
        "title": "Concentração Setorial (HHI)",
        "what": (
            "Mede o grau de concentração do portfólio entre os setores "
            "econômicos, usando o Índice Herfindahl-Hirschman."
        ),
        "formula": (
            "HHI = Σ_s (peso_setor_s)² × 10.000\n"
            "Range: 0 (perfeitamente diversificado) a 10.000 (100% em 1 setor).\n"
            "Classificação:\n"
            "  • HHI < 1.000  → diversificado\n"
            "  • 1.000–2.500 → moderado\n"
            "  • HHI > 2.500 → concentrado"
        ),
        "window": (
            "Snapshot das posições e setores atuais do portfólio."
        ),
        "source": (
            "Pesos derivados do valor_liquido de cada posição; "
            "setor de cada ativo vem dos dados fundamentalistas."
        ),
        "interpretation": (
            "Faixas derivadas das diretrizes antitruste do DOJ (EUA) "
            "para mercados — adaptado como proxy de diversificação de "
            "portfólio. Mostra tb top-1, top-3, top-5 por ativo."
        ),
    },
    "hhi_concentration": {
        "title": "HHI Score",
        "what": "Valor numérico do Herfindahl-Hirschman Index setorial.",
        "formula": "HHI = Σ (peso_setor)² × 10.000",
        "window": "Posições atuais.",
        "source": "valor_liquido × setor de cada ativo.",
        "interpretation": (
            "< 1.000 diversificado | 1.000–2.500 moderado | > 2.500 "
            "concentrado. Dobra quando a alocação cai de 2 setores iguais "
            "para 1 setor dominante."
        ),
    },

    # ─────────── Exposição Cambial ───────────
    "card_fx": {
        "title": "Exposição Cambial (BDRs)",
        "what": (
            "Percentual do portfólio em BDRs, que geram exposição ao "
            "dólar (USD/BRL), e sensibilidade do portfólio a variações "
            "cambiais."
        ),
        "formula": (
            "FX% = Σ valor_BDR / valor_total_portfólio × 100%\n"
            "Sensibilidade a choque BRL de +Δ%:\n"
            "  impacto_portfolio% = FX% × Δ%\n"
            "(hipótese: beta cambial dos BDRs ≈ 1,0)"
        ),
        "window": (
            "Snapshot das posições atuais. Sensibilidade ±5% e ±10%."
        ),
        "source": (
            "Posições marcadas como 'BDR' na categoria dos ativos; "
            "NAV atual do fundo."
        ),
        "interpretation": (
            "FX% = 20% e choque BRL +10% → portfólio ganha ~2% (BDRs "
            "valorizam em reais quando o dólar sobe). Expõe risco/proteção "
            "cambial do fundo para fins de hedge ou análise de "
            "correlação com o real."
        ),
    },

    # ─────────── Rolling Sharpe / Sortino ───────────
    "card_rolling_ratios": {
        "title": "Rolling Sharpe / Sortino",
        "what": (
            "Sharpe e Sortino calculados em janela móvel, evidenciando "
            "como a qualidade do retorno ajustado ao risco evolui ao "
            "longo do tempo."
        ),
        "formula": (
            "Na janela [t−W, t]:\n"
            "  ret_ann = (1 + média_ret_diário)^252 − 1\n"
            "  vol_ann = √Var_amostral(ret_diário) × √252\n"
            "  rf_ann = (1 + CDI_diário_médio)^252 − 1\n"
            "Sharpe  = (ret_ann − rf_ann) / vol_ann\n"
            "Sortino = (ret_ann − rf_ann) / downside_vol_ann\n"
            "  downside_vol_ann = √(Σ r_i² × [r_i<0] / n) × √252"
        ),
        "window": (
            "Janela móvel W = 63D (default) ou 126D, deslizando dia a dia."
        ),
        "source": (
            "Cotas do fundo (retornos diários) e CDI (média diária dos "
            "últimos 252 dias úteis, composta)."
        ),
        "interpretation": (
            "Rolling Sharpe/Sortino estável > 1 ao longo do tempo é sinal "
            "de consistência. Quedas acentuadas marcam regimes de "
            "underperformance. Use junto com os retornos para distinguir "
            "'retornou bem' de 'retornou bem por unidade de risco'."
        ),
    },
    "rolling_sharpe": {
        "title": "Rolling Sharpe",
        "what": (
            "Sharpe Ratio calculado em janela móvel (63D ou 126D)."
        ),
        "formula": (
            "Sharpe_t = (ret_ann_[t−W,t] − rf_ann) / vol_ann_[t−W,t]\n"
            "rf = CDI diário médio últimos 252D, anualizado."
        ),
        "window": "63D (default) ou 126D, deslizante.",
        "source": "Retornos diários da cota; CDI histórico.",
        "interpretation": (
            "Mede prêmio por unidade de volatilidade TOTAL (up + down). "
            "Penaliza volatilidade mesmo 'boa' — por isso use junto com "
            "Sortino para visão completa."
        ),
    },
    "rolling_sortino": {
        "title": "Rolling Sortino",
        "what": (
            "Sortino Ratio calculado em janela móvel — penaliza apenas "
            "volatilidade de retornos negativos."
        ),
        "formula": (
            "Sortino_t = (ret_ann_[t−W,t] − rf_ann) / downside_vol_ann_[t−W,t]\n"
            "downside_vol = √(Σ r_i² × [r_i<0] / n) × √252."
        ),
        "window": "63D (default) ou 126D, deslizante.",
        "source": "Retornos diários da cota; CDI histórico.",
        "interpretation": (
            "Mais representativo que o Sharpe para estratégias com "
            "assimetria positiva (fundos de ações tendem a ter). "
            "Sortino alto + Sharpe mais baixo = fundo captura upside "
            "com volatilidade alta mas pouco downside."
        ),
    },

    # ─────────── Distribuição de Retornos ───────────
    "card_return_dist": {
        "title": "Distribuição de Retornos Diários",
        "what": (
            "Histograma dos retornos diários do fundo no período "
            "selecionado, com estatísticas descritivas (média, melhor "
            "dia, pior dia, % dias positivos)."
        ),
        "formula": (
            "Para cada dia t: r_t = cota_t / cota_{t−1} − 1\n"
            "Histograma: agrupamento em bins dos retornos da janela.\n"
            "Estatísticas: média, máx, mín, % r_t > 0."
        ),
        "window": "252D (default), 126D ou 63D.",
        "source": "Histórico de cota_fechamento do fundo.",
        "interpretation": (
            "Permite visualizar assimetria (skew) e caudas gordas "
            "(kurtosis). Distribuições com cauda esquerda longa indicam "
            "risco de perdas extremas acima do que a volatilidade "
            "isoladamente sugere."
        ),
    },
}
