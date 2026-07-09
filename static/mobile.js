/* ══════════════════════════════════════════════════════════════
   HARBOUR IAT FIA — App mobile (PWA) read-only
   Consome a mesma API REST do app desktop.
   ══════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);

  // ───────── Estado ─────────
  const state = { portfolio: null, indicators: null, perfChart: null, risk: {}, loaded: {} };
  let chart = null;
  let chartRange = 'total';
  let activeScreen = 'resumo';
  let busy = false;

  // ───────── Formatação (pt-BR) ─────────
  function fmtPct(v, dec) {
    dec = dec == null ? 2 : dec;
    if (v == null || isNaN(v)) return '—';
    return (v > 0 ? '+' : '') + Number(v).toFixed(dec).replace('.', ',') + '%';
  }
  function fmtPctMag(v, dec) {
    dec = dec == null ? 2 : dec;
    if (v == null || isNaN(v)) return '—';
    return Math.abs(Number(v)).toFixed(dec).replace('.', ',') + '%';
  }
  function fmtNum(v, dec) {
    if (v == null || isNaN(v)) return '—';
    return Number(v).toFixed(dec).replace('.', ',');
  }
  function fmtCota(v) {
    if (v == null || isNaN(v)) return '—';
    return new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 4, maximumFractionDigits: 6 }).format(v);
  }
  function fmtBRL(v, dec) {
    dec = dec == null ? 2 : dec;
    if (v == null || isNaN(v)) return '—';
    return 'R$ ' + new Intl.NumberFormat('pt-BR', { minimumFractionDigits: dec, maximumFractionDigits: dec }).format(v);
  }
  function fmtDate(s) {
    if (!s) return '';
    const p = String(s).split('-');
    return p.length === 3 ? p[2] + '/' + p[1] + '/' + p[0] : s;
  }
  const sign = (v) => (v > 0 ? 'up' : v < 0 ? 'down' : 'flat');

  function setVal(id, text, cls) {
    const el = $(id);
    if (!el) return;
    el.textContent = text;
    el.classList.remove('up', 'down', 'flat');
    if (cls) el.classList.add(cls);
  }

  let toastT;
  function toast(msg) {
    const el = $('m-toast');
    if (!el) return;
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toastT);
    toastT = setTimeout(() => { el.hidden = true; }, 2800);
  }

  function stampUpdated() {
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, '0');
    const mm = String(now.getMinutes()).padStart(2, '0');
    const el = $('m-updated');
    if (el) el.textContent = 'atualizado ' + hh + ':' + mm;
  }

  // ───────── API ─────────
  async function api(path) {
    const r = await fetch(path, { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
    if (!r.ok) throw new Error(path + ' → ' + r.status);
    return r.json();
  }

  // ───────── Telas: render ─────────
  function win(data, key) { return (data && data[key]) || {}; }

  function renderResumo() {
    const p = state.portfolio;
    if (p && p.quota) {
      const q = p.quota;
      const cota = q.cota_estimada != null ? q.cota_estimada : q.quota_fechamento;
      setVal('cota-value', fmtCota(cota));
      const chg = $('cota-change');
      chg.className = 'm-cota-change ' + sign(q.variacao_pct);
      chg.textContent = fmtPct(q.variacao_pct);
      const lbl = document.querySelector('#cota-card .m-cota-label');
      if (lbl) lbl.textContent = q.mercado_fechado ? 'COTA (FECHAMENTO)' : 'COTA ESTIMADA';
      const ref = [];
      if (q.quota_fechamento) ref.push('fech. ant. ' + fmtCota(q.quota_fechamento));
      if (q.data_fechamento) ref.push(fmtDate(q.data_fechamento));
      setVal('cota-ref', ref.join(' · '));
      setVal('i-ibov', fmtPct(q.retorno_ibov_pct), sign(q.retorno_ibov_pct));
      setVal('i-alpha', fmtPct(q.alpha_pct), sign(q.alpha_pct));
    }
    const d = state.indicators ? state.indicators.data : null;
    if (d) {
      const mes = win(d, 'no_mes'), ano = win(d, 'no_ano'), m12 = win(d, '12m'), tot = win(d, 'total');
      setVal('r-mes', fmtPct(mes.ret), sign(mes.ret));
      setVal('r-ano', fmtPct(ano.ret), sign(ano.ret));
      setVal('r-12m', fmtPct(m12.ret), sign(m12.ret));
      setVal('r-total', fmtPct(tot.ret), sign(tot.ret));
      setVal('i-sharpe', tot.sharpe != null ? fmtNum(tot.sharpe, 2) : '—');
      setVal('i-vol', fmtPctMag(tot.vol));
    }
  }

  function renderCarteira() {
    collapseExpand();
    const p = state.portfolio;
    const list = $('carteira-list');
    if (!p || !p.rows || !p.rows.length) {
      list.innerHTML = '<div class="m-empty">Sem posições.</div>';
      setVal('cart-count', '');
      return;
    }
    const q = p.quota || {};
    const caixa = q.caixa || 0;
    const prov = q.proventos_a_receber || 0;
    const custos = q.custos_provisionados || 0;
    const equity = p.total_value || 0;
    // PL do fundo = ativos + caixa + proventos a receber − custos provisionados (base dos percentuais).
    const base = (equity + caixa + prov - custos) || 1;
    const pctFund = (v) => (v != null ? (v / base) * 100 : null);

    const rows = p.rows.slice().sort((a, b) => (b.valor_liquido || 0) - (a.valor_liquido || 0));
    const maxW = Math.max.apply(null, rows.map((r) => pctFund(r.valor_liquido) || 0)
      .concat([(caixa / base) * 100, (prov / base) * 100])) || 1;
    setVal('cart-count', rows.length + ' ativos');

    const fundLine = (label, value) => {
      const w = (value / base) * 100;
      const barW = Math.max(4, Math.round((w / maxW) * 100));
      return (
        '<div class="m-fundline">' +
          '<div class="m-pos-left">' +
            '<div class="m-fundline-label">' + label + '</div>' +
            '<div class="m-pos-weight">' + fmtPctMag(w, 1) + ' do fundo</div>' +
            '<div class="m-pos-bar" style="width:' + barW + '%"></div>' +
          '</div>' +
          '<div class="m-pos-right"><div class="m-pos-price">' + fmtBRL(value) + '</div></div>' +
        '</div>'
      );
    };

    let html = fundLine('Caixa', caixa) + fundLine('Proventos a receber', prov);

    html += rows.map((r) => {
      const v = r.var_dia_pct;
      const w = pctFund(r.valor_liquido);
      const barW = Math.max(4, Math.round(((w || 0) / maxW) * 100));
      const weight = (w != null ? fmtPctMag(w, 1) : '—') + ' do fundo';
      const upside = r.upside_pct != null ? ' · upside ' + fmtPct(r.upside_pct, 0) : '';
      const name = r.short_name ? '<div class="m-pos-name">' + r.short_name + '</div>' : '';
      const price = r.preco != null ? '<div class="m-pos-price">' + fmtBRL(r.preco) + '</div>' : '';
      const qtyFmt = r.quantidade != null ? new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 }).format(r.quantidade) + ' ações' : null;
      const nomFmt = r.valor_liquido != null ? fmtBRL(r.valor_liquido, 0) : null;
      const posInfo = (qtyFmt || nomFmt) ? '<div class="m-pos-sub">' + [qtyFmt, nomFmt].filter(Boolean).join(' · ') + '</div>' : '';
      return (
        '<div class="m-pos" data-ticker="' + r.ticker + '" data-yahoo="' + (r.yahoo_ticker || '') + '">' +
          '<div class="m-pos-left">' +
            '<div class="m-pos-ticker">' + r.ticker + ' <span class="m-pos-caret">›</span></div>' + name +
            '<div class="m-pos-weight">' + weight + upside + '</div>' +
            posInfo +
            '<div class="m-pos-bar" style="width:' + barW + '%"></div>' +
          '</div>' +
          '<div class="m-pos-right">' + price +
            '<div class="m-pos-var ' + sign(v) + '">' + (v == null ? '—' : fmtPct(v)) + '</div>' +
          '</div>' +
        '</div>'
      );
    }).join('');

    list.innerHTML = html;
  }

  // ───────── Carteira: expandir ativo (mini gráfico vs IBOV) ─────────
  const expanded = { ticker: null, chart: null, range: '6M' };

  function collapseExpand() {
    if (expanded.chart) { expanded.chart.destroy(); expanded.chart = null; }
    const panel = document.querySelector('.m-pos-expand');
    if (panel) panel.remove();
    const open = document.querySelector('.m-pos.is-open');
    if (open) open.classList.remove('is-open');
    expanded.ticker = null;
  }

  function openExpand(card) {
    const ticker = card.dataset.ticker;
    const yahoo = card.dataset.yahoo;
    if (expanded.ticker === ticker) { collapseExpand(); return; }
    collapseExpand();
    if (!yahoo) return;
    expanded.ticker = ticker;
    card.classList.add('is-open');
    const ranges = ['1M', '3M', '6M', 'YTD', '1A'];
    const panel = document.createElement('div');
    panel.className = 'm-pos-expand';
    panel.innerHTML =
      '<div class="m-range m-range-stock">' +
        ranges.map((r) => '<button class="m-range-btn' + (r === expanded.range ? ' is-active' : '') + '" data-r="' + r + '">' + r + '</button>').join('') +
      '</div>' +
      '<div class="m-chart-wrap m-mini"><canvas></canvas><div class="m-mini-load">carregando…</div></div>' +
      '<div class="m-stats">' +
        '<div class="m-stat"><span>PERÍODO</span><b data-k="ret">—</b></div>' +
        '<div class="m-stat"><span>VS IBOV</span><b data-k="vsibov">—</b></div>' +
        '<div class="m-stat"><span>MÁX 52S</span><b data-k="hi">—</b></div>' +
        '<div class="m-stat"><span>MÍN 52S</span><b data-k="lo">—</b></div>' +
        '<div class="m-stat"><span>P. ATUAL</span><b data-k="px">—</b></div>' +
      '</div>';
    card.after(panel);
    panel.querySelectorAll('.m-range-btn').forEach((b) => {
      b.addEventListener('click', () => {
        panel.querySelectorAll('.m-range-btn').forEach((x) => x.classList.toggle('is-active', x === b));
        expanded.range = b.dataset.r;
        loadStock(yahoo, panel);
      });
    });
    loadStock(yahoo, panel);
  }

  async function loadStock(yahoo, panel) {
    const load = panel.querySelector('.m-mini-load');
    const canvas = panel.querySelector('canvas');
    load.style.display = ''; load.textContent = 'carregando…'; canvas.style.display = 'none';
    const set = (k, txt, cls) => {
      const el = panel.querySelector('[data-k="' + k + '"]');
      if (el) { el.textContent = txt; el.className = ''; if (cls) el.classList.add(cls); }
    };
    try {
      const d = await api('/api/stock-history/' + encodeURIComponent(yahoo) + '?range=' + expanded.range);
      if (!d.series || !d.series.length) { load.textContent = 'sem dados para o período.'; return; }
      const co = themeColors();
      set('ret', fmtPct(d.period_return), sign(d.period_return));
      set('vsibov', fmtPct(d.vs_ibov), sign(d.vs_ibov));
      set('hi', d.w52_high != null ? fmtBRL(d.w52_high) : '—');
      set('lo', d.w52_low != null ? fmtBRL(d.w52_low) : '—');
      set('px', d.series.length ? fmtBRL(d.series[d.series.length - 1].price) : '—');
      const labels = d.series.map((s) => s.date);
      if (expanded.chart) { expanded.chart.destroy(); expanded.chart = null; }
      load.style.display = 'none'; canvas.style.display = '';
      expanded.chart = new Chart(canvas, {
        type: 'line',
        data: {
          labels: labels,
          datasets: [
            { label: 'Ativo', data: d.series.map((s) => (s.indexed != null ? s.indexed - 100 : null)), borderColor: co.orange, borderWidth: 2, pointRadius: 0, tension: 0.15, fill: false },
            { label: 'IBOV', data: d.series.map((s) => (s.ibov != null ? s.ibov - 100 : null)), borderColor: co.cyan, borderWidth: 1.3, pointRadius: 0, tension: 0.15, fill: false, borderDash: [4, 3] },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { display: false },
            tooltip: { callbacks: { title: (it) => (it.length ? fmtDate(it[0].label) : ''), label: (it) => it.dataset.label + ': ' + fmtPct(it.parsed.y) } },
          },
          scales: {
            x: { grid: { display: false }, ticks: { color: co.muted, maxTicksLimit: 4, maxRotation: 0, callback: (v, i) => { const s = labels[i]; if (!s) return ''; const p = s.split('-'); return p[2] + '/' + p[1]; } } },
            y: { grid: { color: co.border }, ticks: { color: co.muted, callback: (v) => Number(v).toFixed(0) + '%' } },
          },
        },
      });
    } catch (e) {
      load.textContent = 'erro ao carregar.';
    }
  }

  function themeColors() {
    const cs = getComputedStyle(document.documentElement);
    const g = (n) => cs.getPropertyValue(n).trim();
    return { orange: g('--orange'), cyan: g('--cyan'), yellow: g('--yellow'), muted: g('--text-muted'), border: g('--border') };
  }

  function cutoffDate(lastStr, kind) {
    if (kind === 'total') return null;
    const d = new Date(lastStr + 'T00:00:00');
    if (kind === 'ytd') return d.getFullYear() + '-01-01';
    if (kind === '6m') d.setMonth(d.getMonth() - 6);
    else if (kind === '12m') d.setMonth(d.getMonth() - 12);
    else if (kind === '24m') d.setMonth(d.getMonth() - 24);
    else if (kind === '36m') d.setMonth(d.getMonth() - 36);
    else return null;
    return d.toISOString().slice(0, 10);
  }

  // Recorta a série na janela, incluindo o último ponto ANTES do corte como
  // base (mesma metodologia do desktop — ancora no fechamento anterior).
  function windowSeries(series, kind) {
    if (kind === 'total') return series;
    const last = series[series.length - 1].date;
    const cutoff = cutoffDate(last, kind);
    if (!cutoff) return series;
    let anchor = 0;
    for (let i = 0; i < series.length; i++) {
      if (series[i].date < cutoff) anchor = i;
      else break;
    }
    return series.slice(anchor);
  }

  function renderRentChart() {
    const d = state.perfChart;
    const cv = $('rent-chart');
    if (!d || !d.series || !d.series.length || !cv) return;
    const co = themeColors();
    const series = windowSeries(d.series, chartRange);
    if (!series.length) return;
    const labels = series.map((s) => s.date);

    const f0 = series[0].fund;
    const fund = series.map((s) => (f0 ? (s.fund / f0 - 1) * 100 : null));

    let ib0 = null;
    for (const s of series) { if (s.ibov != null) { ib0 = s.ibov; break; } }
    const ibov = series.map((s) => (ib0 && s.ibov != null ? (s.ibov / ib0 - 1) * 100 : null));

    const cdiMap = (d.benchmarks && d.benchmarks.cdi) || null;
    let cdi = null;
    if (cdiMap) {
      let c0 = null;
      for (const s of series) { if (cdiMap[s.date] != null) { c0 = cdiMap[s.date]; break; } }
      if (c0) cdi = series.map((s) => (cdiMap[s.date] != null ? (cdiMap[s.date] / c0 - 1) * 100 : null));
    }

    const base = { tension: 0.15, pointRadius: 0, spanGaps: true, fill: false };
    const datasets = [
      Object.assign({ label: 'Fundo', data: fund, borderColor: co.orange, borderWidth: 2.4 }, base),
      Object.assign({ label: 'IBOV', data: ibov, borderColor: co.cyan, borderWidth: 1.4 }, base),
    ];
    if (cdi) datasets.push(Object.assign({ label: 'CDI', data: cdi, borderColor: co.yellow, borderWidth: 1.4, borderDash: [4, 3] }, base));

    if (chart) chart.destroy();
    chart = new Chart(cv, {
      type: 'line',
      data: { labels: labels, datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (items) => (items.length ? fmtDate(items[0].label) : ''),
              label: (it) => it.dataset.label + ': ' + fmtPct(it.parsed.y),
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: {
              color: co.muted, maxTicksLimit: 5, autoSkip: true, maxRotation: 0,
              callback: function (val, idx) {
                const s = labels[idx];
                if (!s) return '';
                const p = s.split('-');
                return p[1] + '/' + p[0].slice(2);
              },
            },
          },
          y: {
            grid: { color: co.border },
            ticks: { color: co.muted, callback: (v) => Number(v).toFixed(0) + '%' },
          },
        },
      },
    });

    const leg = $('rent-legend');
    if (leg) {
      let html = '<span><i style="background:' + co.orange + '"></i>Fundo</span>' +
                 '<span><i style="background:' + co.cyan + '"></i>IBOV</span>';
      if (cdi) html += '<span><i style="background:' + co.yellow + '"></i>CDI</span>';
      leg.innerHTML = html;
    }
  }

  const RENT_WINS = [['6m', '6M'], ['ytd', 'YTD'], ['12m', '12M'], ['24m', '24M'], ['36m', '36M'], ['total', 'Total']];

  function windowReturns(d, kind) {
    const s = windowSeries(d.series, kind);
    if (!s.length) return { fund: null, ibov: null, cdi: null };
    const f0 = s[0].fund, f1 = s[s.length - 1].fund;
    const fund = f0 ? (f1 / f0 - 1) * 100 : null;
    let ib0 = null, ib1 = null;
    for (const x of s) { if (x.ibov != null) { ib0 = x.ibov; break; } }
    for (let i = s.length - 1; i >= 0; i--) { if (s[i].ibov != null) { ib1 = s[i].ibov; break; } }
    const ibov = (ib0 && ib1) ? (ib1 / ib0 - 1) * 100 : null;
    let cdi = null;
    const cm = d.benchmarks && d.benchmarks.cdi;
    if (cm) {
      let c0 = null, c1 = null;
      for (const x of s) { if (cm[x.date] != null) { c0 = cm[x.date]; break; } }
      for (let i = s.length - 1; i >= 0; i--) { if (cm[s[i].date] != null) { c1 = cm[s[i].date]; break; } }
      if (c0 && c1) cdi = (c1 / c0 - 1) * 100;
    }
    return { fund: fund, ibov: ibov, cdi: cdi };
  }

  function renderRentTable() {
    const d = state.perfChart;
    const el = $('rent-table');
    if (!d || !d.series || !d.series.length || !el) return;
    const body = RENT_WINS.map(([k, lbl]) => {
      const r = windowReturns(d, k);
      return '<tr><td class="m-rt-win">' + lbl + '</td>' +
        '<td class="' + sign(r.fund) + '">' + fmtPct(r.fund) + '</td>' +
        '<td class="' + sign(r.ibov) + '">' + fmtPct(r.ibov) + '</td>' +
        '<td class="' + sign(r.cdi) + '">' + fmtPct(r.cdi) + '</td></tr>';
    }).join('');
    el.innerHTML = '<table><thead><tr><th>Janela</th><th>Fundo</th><th>IBOV</th><th>CDI</th></tr></thead><tbody>' + body + '</tbody></table>';
  }

  function renderRisco() {
    const v = state.risk.var;
    if (v && !v.error) {
      setVal('k-var95', fmtPctMag(v.var_95_1d_pct));
      setVal('k-var99', fmtPctMag(v.var_99_1d_pct));
      if (v.return_distribution) setVal('k-worst', fmtPct(v.return_distribution.worst_day), 'down');
    } else {
      setVal('k-var95', '—'); setVal('k-var99', '—'); setVal('k-worst', '—');
    }
    const dv = state.risk.dd;
    if (dv && dv.series && dv.series.length) {
      const lastDd = [...dv.series].reverse().find((s) => s.drawdown != null);
      const lastVol = [...dv.series].reverse().find((s) => s.vol != null);
      if (lastDd) setVal('k-dd', fmtPct(lastDd.drawdown), sign(lastDd.drawdown));
      if (lastVol) setVal('k-vol', fmtPctMag(lastVol.vol));
    }
    const lq = state.risk.liq;
    const warn = $('risk-warn');
    if (lq) {
      setVal('l-1d', fmtPctMag(lq.portfolio_liq_1d_pct, 1), 'up');
      setVal('l-5d', fmtPctMag(lq.portfolio_liq_5d_pct, 1), 'up');
      setVal('l-10d', fmtPctMag(lq.portfolio_liq_10d_pct, 1), 'up');
      if (lq.warning) { warn.textContent = lq.warning; warn.hidden = false; }
      else { warn.hidden = true; }
    }
  }

  // ───────── Loaders ─────────
  async function loadCore() {
    const [p, ind] = await Promise.all([
      api('/api/portfolio').catch((e) => { throw e; }),
      api('/api/performance-indicators').catch(() => ({ data: {} })),
    ]);
    state.portfolio = p;
    state.indicators = ind;
    state.loaded.core = true;
    renderResumo();
    renderCarteira();
  }

  async function loadRent() {
    state.perfChart = await api('/api/performance-chart');
    state.loaded.rent = true;
    renderRentChart();
    renderRentTable();
  }

  async function loadRisk() {
    const [varR, ddR, liqR] = await Promise.allSettled([
      api('/api/risk/var'),
      api('/api/drawdown-volatility'),
      api('/api/risk/liquidity'),
    ]);
    state.risk.var = varR.status === 'fulfilled' ? varR.value : { error: true };
    state.risk.dd = ddR.status === 'fulfilled' ? ddR.value : null;
    state.risk.liq = liqR.status === 'fulfilled' ? liqR.value : null;
    state.loaded.risk = true;
    renderRisco();
  }

  // ───────── Navegação ─────────
  const SCREEN_IDS = { resumo: 'screen-resumo', carteira: 'screen-carteira', rent: 'screen-rent', risco: 'screen-risco' };

  async function ensureLoaded(name) {
    try {
      if ((name === 'resumo' || name === 'carteira') && !state.loaded.core) await loadCore();
      else if (name === 'rent' && !state.loaded.rent) await loadRent();
      else if (name === 'risco' && !state.loaded.risk) await loadRisk();
    } catch (e) {
      toast('Sem conexão — mostrando últimos dados');
    }
  }

  function showScreen(name) {
    if (!SCREEN_IDS[name]) return;
    activeScreen = name;
    Object.keys(SCREEN_IDS).forEach((k) => {
      const sec = $(SCREEN_IDS[k]);
      if (sec) sec.classList.toggle('is-active', k === name);
    });
    document.querySelectorAll('.m-tab').forEach((t) => {
      t.classList.toggle('is-active', t.dataset.target === name);
    });
    ensureLoaded(name);
    if (name === 'rent' && state.loaded.rent) renderRentChart();
  }

  // ───────── Refresh ─────────
  async function refreshActive() {
    if (busy) return;
    busy = true;
    const btn = $('m-refresh');
    if (btn) btn.style.opacity = '0.4';
    try {
      if (activeScreen === 'rent') await loadRent();
      else if (activeScreen === 'risco') await loadRisk();
      else await loadCore();
      stampUpdated();
    } catch (e) {
      toast('Sem conexão — mostrando últimos dados');
    } finally {
      busy = false;
      if (btn) btn.style.opacity = '';
    }
  }

  // ───────── Tema ─────────
  function applyTheme(t) {
    document.documentElement.setAttribute('data-theme', t);
    try { localStorage.setItem('harbour-theme', t); } catch (e) {}
    const mc = $('meta-theme-color');
    if (mc) mc.setAttribute('content', t === 'harbour' ? '#0a0f24' : '#000000');
    const fl = $('favicon-link');
    if (fl) fl.href = t === 'harbour' ? '/static/favicon-harbour.svg' : '/static/favicon.svg';
    if (state.perfChart) renderRentChart();
  }

  // ───────── Service worker ─────────
  function registerSW() {
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js').catch(() => {});
    }
  }

  // ───────── Init ─────────
  function init() {
    document.querySelectorAll('.m-tab').forEach((t) => {
      t.addEventListener('click', () => showScreen(t.dataset.target));
    });
    document.querySelectorAll('.m-range-btn').forEach((b) => {
      b.addEventListener('click', () => {
        chartRange = b.dataset.range;
        document.querySelectorAll('.m-range-btn').forEach((x) => x.classList.toggle('is-active', x === b));
        renderRentChart();
      });
    });
    $('carteira-list').addEventListener('click', (e) => {
      const card = e.target.closest('.m-pos');
      if (card) openExpand(card);
    });
    $('m-refresh').addEventListener('click', refreshActive);
    $('m-theme-toggle').addEventListener('click', () => {
      const cur = document.documentElement.getAttribute('data-theme') || 'dark';
      applyTheme(cur === 'dark' ? 'harbour' : 'dark');
    });

    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') refreshActive();
    });

    // Carga inicial
    loadCore().then(stampUpdated).catch(() => toast('Sem conexão — mostrando últimos dados'));
    registerSW();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
