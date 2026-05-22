# -*- coding: utf-8 -*-
"""
Metodologia das métricas da aba LIQUIDEZ — fonte única de verdade para
tooltips de auditoria CVM/ANBIMA.

Cada entrada descreve UMA métrica/card que o usuário vê. Mesmo formato do
RISK_METHODOLOGY (5 seções: what / formula / window / source / interpretation).

Como adicionar nova métrica:
    1. Adicionar entrada abaixo com as 5 seções.
    2. No template/JS, incluir <span class="col-info" data-tip-key="liq_NOVA">ⓘ</span>
    3. Nenhuma alteração em CSS/JS necessária — o handler de tooltip já existe.

IMPORTANTE: manter sincronizado com os cálculos em app.py (seção LIQUIDEZ).
Quando o cálculo mudar, ATUALIZAR AQUI — este arquivo é o que compliance
e auditoria irão revisar.
"""

LIQUIDITY_METHODOLOGY: dict = {

    # ───────────────────────── Cenários (filtro global) ─────────────────────
    "liq_cenarios": {
        "title": "Cenários de Stress de Liquidez",
        "what": (
            "Três cenários alteram simultaneamente: (a) o quanto do volume "
            "diário do mercado o fundo consegue executar sem impactar preço, "
            "e (b) qual percentil do histórico de resgates do fundo é usado "
            "como projeção de saída."
        ),
        "formula": (
            "Neutro:  100% do volume disponível  ×  P50 do histórico de resg.\n"
            "Stress:   50% do volume disponível  ×  P75 do histórico de resg.\n"
            "Crise:    30% do volume disponível  ×  P95 do histórico de resg.\n\n"
            "Cap padrão de participação no volume: 20% do ADV (Average Daily "
            "Volume) — teto de mercado para não impactar preço. O cenário "
            "multiplica esse cap (ex: Stress → 20% × 50% = 10% do ADV)."
        ),
        "window": "Snapshot atual da carteira × histórico CVM do fundo.",
        "source": "data/portfolio.json (posições) + data/cvm_daily.json (resg_dia/PL).",
        "interpretation": (
            "Use NEUTRO para acompanhamento dia-a-dia. STRESS / CRISE para "
            "testes regulatórios e relatório de due diligence. Cenário CRISE "
            "= 'pior caso histórico observado' (P95 = pior 5% dos casos)."
        ),
    },

    # ═════════════════════════ SUB-ABA FUNDO ═════════════════════════
    "liq_card_fundo": {
        "title": "Liquidez Fundo — Liquidez Ativos vs Resgate Projetado",
        "what": (
            "Compara cumulativamente, em cada bucket de dias úteis, quanto da "
            "carteira o fundo consegue liquidar (linha verde) vs quanto seria "
            "demandado em resgate (linha laranja). O Índice (linha azul) é a "
            "razão entre as duas — ≥ 1.0 significa folga, < 1.0 risco."
        ),
        "formula": (
            "Liquidez ativos(B) = Σ proporção_i × fração_liquidável_i(B)\n"
            "  onde fração_liquidável_i(B) =\n"
            "    0                                       se B < settlement_i\n"
            "    min((B-settlement_i+1) / días_market_i, 1)   caso contrário\n"
            "  e dias_market_i = valor_i / (vol_médio_i × 20% × cenário_mult)\n\n"
            "Resgate projetado(B) = percentil_p({Σ resg_pct rolante em B dias})\n"
            "  p = 50 (Neutro), 75 (Stress), 95 (Crise)\n\n"
            "Índice(B) = Liquidez ativos(B) / max(Resgate projetado(B), 0,01)"
        ),
        "window": (
            "Buckets de dias úteis: 1, 2, 3, 4, 5, 10, 21, 30, 42, 63, 84, "
            "105, 126, 180, 252, 360, 540."
        ),
        "source": (
            "Volume médio: yfinance (averageVolume ≈ 90d). "
            "Histórico de resgates: data/cvm_daily.json (campo resg_dia)."
        ),
        "interpretation": (
            "Índice no chart é capeado em 100 só para visualização — valores "
            "reais aparecem no tooltip. Pontos em que a linha verde está "
            "abaixo da laranja indicam buckets onde o fundo não conseguiria "
            "honrar o resgate projetado naquele horizonte."
        ),
    },

    "liq_card_ativos": {
        "title": "Liquidez Ativos — Heatmap Cumulativo por Ativo",
        "what": (
            "Para cada posição da carteira, mostra a fração do PL total que "
            "ESSE ativo contribui em liquidez acumulada até cada bucket. "
            "Soma das células de um bucket = % total da carteira liquidável "
            "até ali (= linha verde do chart acima)."
        ),
        "formula": (
            "célula(ativo_i, bucket_B) =\n"
            "    proporção_carteira_i × fração_liquidável_i(B)\n\n"
            "Fração liquidável usa modelo settlement-aware:\n"
            "  • Antes de D+settlement → 0% (caixa ainda não chegou)\n"
            "  • Depois → rampa linear conforme vendas vão settling, cada "
            "dia 1/dias_market da posição\n"
            "  • Capeado em 100% (proporção total do ativo)"
        ),
        "window": "Snapshot atual + buckets padrão (1 a 540 dias úteis).",
        "source": "portfolio.json + yfinance + override prazo_resgate_d.",
        "interpretation": (
            "Cor mais intensa = mais peso liquidado naquele bucket. Use a "
            "busca para filtrar por ticker. Ativos com prazo de liquidação "
            "longo aparecem com células mais à direita."
        ),
    },

    "liq_card_compliance": {
        "title": "Compliance CVM / ANBIMA",
        "what": (
            "Quatro regras de compliance de liquidez avaliadas em tempo real. "
            "Três são configuráveis em CONFIGURAÇÕES (card LIMITES DE LIQUIDEZ); "
            "a quarta é fixa: índice de liquidez D+5 em cenário Stress ≥ 1.0."
        ),
        "formula": (
            "Status por regra:\n"
            "  OK         : dentro do limite\n"
            "  ALERTA     : valor entre 85%-100% do limite\n"
            "  VIOLAÇÃO   : ultrapassou o limite\n\n"
            "Regras default:\n"
            "  • % liquidatável em 5d (Neutro) ≥ 80%\n"
            "  • % em ativos > 7 dias ≤ 10%\n"
            "  • Prazo médio ponderado ≤ 30 dias\n"
            "  • Índice Liquidez D+5 (Stress) ≥ 1.0  (não-configurável)"
        ),
        "window": "Atual (calculado a cada carregamento da aba).",
        "source": "fund_config.json (3 limites) + snapshot/market/stress do dia.",
        "interpretation": (
            "Verde em todas = pronto para entregar PDF de auditoria. "
            "Qualquer alerta/violação merece ação do gestor antes de aceitar "
            "novos resgates ou novas compras pouco líquidas."
        ),
    },

    # ═════════════════════════ SUB-ABA MERCADO — KPIs ═════════════════════════
    "liq_kpi_valor": {
        "title": "Valor em carteira",
        "what": (
            "Soma do valor de mercado de todas as posições do fundo (ativos), "
            "sem incluir caixa/proventos/custos. Mesma base usada para o NAV "
            "de ativos no chart de Liquidez Fundo."
        ),
        "formula": "Σ (quantidade_i × preço_i) para todas as posições.",
        "window": "Snapshot atual (preços via yfinance, posições via portfolio.json).",
        "source": "data/portfolio.json + preços yfinance (cache 30s).",
        "interpretation": (
            "Difere do NAV total da aba TABELA porque NÃO soma caixa/proventos/"
            "custos. Esse é o valor de ATIVOS — a parte que precisa ser "
            "liquidada em caso de resgate."
        ),
    },

    "liq_kpi_vol_ponderado": {
        "title": "Volume médio ponderado",
        "what": (
            "Volume financeiro diário médio do MERCADO dos ativos da carteira, "
            "ponderado pelo peso de cada posição. Indica quão líquido é o "
            "mercado dos ativos que o fundo detém."
        ),
        "formula": (
            "Vol médio ponderado = Σ (valor_i × volume_médio_i) / NAV_ativos\n"
            "  volume_médio_i = averageVolume (yfinance) × preço_i  (em R$)"
        ),
        "window": "Volume médio 3 meses (yfinance default).",
        "source": "yfinance fast_info / info, ponderado pelo peso na carteira.",
        "interpretation": (
            "Valores altos (>R$ 100M/dia) indicam carteira em ativos super "
            "líquidos. Volume muito acima do NAV do fundo = baixíssimo risco "
            "de impacto de preço em vendas urgentes."
        ),
    },

    "liq_kpi_alta": {
        "title": "% Carteira em Alta Liquidez",
        "what": (
            "Percentual do PL alocado em ativos classificados como 'Alta "
            "liquidez' (zeram em menos de 3 dias úteis). Métrica-chave para "
            "comprovação regulatória de capacidade de honrar resgates curtos."
        ),
        "formula": (
            "Soma da proporção das posições com dias_zerar < 3\n"
            "  onde dias_zerar = D+settlement + max(dias_market − 1, 0)"
        ),
        "window": "Snapshot atual.",
        "source": "Classificação derivada de dias_zerar por ativo.",
        "interpretation": (
            "Valores próximos de 100% indicam carteira altamente líquida. "
            "Para FIA típico aberto, manter ≥ 80% é boa prática ANBIMA."
        ),
    },

    "liq_kpi_prazo_medio": {
        "title": "Prazo Médio para Zerar (ponderado)",
        "what": (
            "Tempo médio (em dias úteis) que o fundo levaria para zerar 100% "
            "da carteira, ponderado pelo valor de cada posição. Inclui prazo "
            "de settlement + dias de execução em mercado."
        ),
        "formula": (
            "Prazo médio = Σ (valor_i × dias_zerar_i) / Σ valor_i\n"
            "  onde dias_zerar_i = settlement_i + max(dias_market_i − 1, 0)\n"
            "        dias_market_i = valor_i / (vol_médio_i × 20%)"
        ),
        "window": "Snapshot atual.",
        "source": "portfolio.json + yfinance.",
        "interpretation": (
            "Valor < 3 dias = carteira muito líquida. > 30 dias requer atenção "
            "regulatória. O histórico desse KPI aparece no chart 'Prazo médio "
            "ponderado' (alimentado pelo auto-close diário)."
        ),
    },

    "liq_card_faixas": {
        "title": "Faixas de Liquidez",
        "what": (
            "Distribuição do PL pelas 4 faixas de classificação de liquidez. "
            "Critério baseado em dias úteis até zerar a posição."
        ),
        "formula": (
            "Alta:        dias_zerar  < 3\n"
            "Média:       3 ≤ dias_zerar ≤ 7\n"
            "Baixa:       7 < dias_zerar ≤ 30\n"
            "Muito baixa: dias_zerar > 30\n\n"
            "% por faixa = Σ proporção das posições naquela faixa."
        ),
        "window": "Snapshot atual.",
        "source": "Classificação por ativo + soma ponderada de peso.",
        "interpretation": (
            "Distribuição padrão saudável para FIA: ≥ 80% em Alta, < 10% em "
            "Baixa+Muito baixa. Concentrações em Muito Baixa requerem "
            "documentação adicional para regulador."
        ),
    },

    "liq_card_prazo_historico": {
        "title": "Prazo Médio Ponderado — Histórico",
        "what": (
            "Evolução diária do prazo médio para zerar a carteira inteira. "
            "Cada ponto é o KPI 'Prazo médio para zerar' calculado no "
            "fechamento daquele dia."
        ),
        "formula": (
            "Mesma fórmula do KPI 'Prazo médio para zerar', aplicada à "
            "carteira de cada dia. Snapshot diário gerado pelo auto-close "
            "(17:35 BRT, dias úteis)."
        ),
        "window": "Toda a história desde a primeira execução do auto-close.",
        "source": "data/liquidity_history.json — populado por _record_liquidity_snapshot.",
        "interpretation": (
            "Tendência ascendente = carteira piorando em liquidez (mais ativos "
            "pouco líquidos ou concentração crescente). Spikes pontuais podem "
            "indicar dias de pouco volume no mercado."
        ),
    },

    "liq_card_matriz": {
        "title": "Métricas Liquidez por Ativo",
        "what": (
            "Tabela detalhada por posição com volume médio, % do volume "
            "diário que a posição representa, dias para zerar e classificação."
        ),
        "formula": (
            "% vol. diário = valor_carteira / vol_médio_diário × 100\n"
            "  (sem aplicar haircut — métrica bruta para referência)\n\n"
            "Dias p/ zerar = settlement + max(dias_market − 1, 0)\n"
            "Classificação: Alta / Média / Baixa / Muito baixa (mesmas faixas)"
        ),
        "window": "Snapshot atual.",
        "source": "portfolio.json × yfinance volumes.",
        "interpretation": (
            "Ativos com '% vol. diário' > 100% indicam que a posição é maior "
            "que 1 dia de volume — sinal de risco de execução. Ordenar pela "
            "coluna 'Dias p/ zerar' identifica rapidamente os mais ilíquidos."
        ),
    },
}
