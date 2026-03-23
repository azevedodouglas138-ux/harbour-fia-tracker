/* ═══════════════════════════════════════════════════════════════
   HARBOUR IAT FIA — Bloomberg Terminal JS
   ═══════════════════════════════════════════════════════════════ */

// ── State ────────────────────────────────────────────────────────
let portfolioData = null;
let historyChart  = null;
let sectorChart   = null;
let upsideChart   = null;
let sortCol = 'pct_total', sortDir = 'desc';
let refreshTimer = null, countdownTimer = null;
let secondsLeft  = 30;
let editingTicker = null;
let currentDays   = '0';
const REFRESH_SEC = 30;

// ── Benchmark config ─────────────────────────────────────────────
const BENCH_CONFIG = {
  ibov:   { label: 'IBOV',      color: '#00aacc', dash: [5, 4] },
  smll:   { label: 'SMLL',      color: '#00cc88', dash: [4, 3] },
  idiv:   { label: 'IDIV',      color: '#ffcc00', dash: [4, 3] },
  cdi:    { label: 'CDI',       color: '#cc88ff', dash: [3, 3] },
  sp500:  { label: 'S&P500 $',  color: '#ff4488', dash: [4, 3] },
  nasdaq: { label: 'NASDAQ $',  color: '#66bbff', dash: [4, 3] },
};
// Maps UI key → backend key in _perfCache.benchmarks
const BENCH_BACKEND_KEY = {
  ibov:   null,       // special: comes from series[].ibov
  smll:   '^SMLL',
  idiv:   '^IDIV',
  cdi:    'cdi',
  sp500:  '^GSPC',
  nasdaq: '^IXIC',
};
let selectedBenchmarks = new Set(['ibov']);

// Chart.js dark/Bloomberg defaults
Chart.defaults.color       = '#888888';
Chart.defaults.borderColor = '#2a2a2a';
Chart.defaults.font.family = "'Cascadia Code','Courier New',monospace";
Chart.defaults.font.size   = 10;

// ── Format helpers ───────────────────────────────────────────────
const fmt    = (v, d=2, fb='—') => v == null || isNaN(v) ? fb : Number(v).toLocaleString('pt-BR',{minimumFractionDigits:d,maximumFractionDigits:d});
const fmtBRL = (v, fb='—')      => v == null || isNaN(v) ? fb : 'R$' + Number(v).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});
const fmtInt = (v, fb='—')      => v == null || isNaN(v) ? fb : Number(v).toLocaleString('pt-BR');
const sign   = v                 => v == null ? '' : v >= 0 ? '+' : '';
const colorCls = v => v == null ? '' : v > 0 ? 'positive' : v < 0 ? 'negative' : '';
const upsideCls = v => { if(v==null)return ''; if(v>=30)return 'upside-high'; if(v>=0)return 'upside-mid'; return 'upside-neg'; };

// ── Fetch portfolio ──────────────────────────────────────────────
async function fetchPortfolio() {
  try {
    const res = await fetch('/api/portfolio');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    portfolioData = await res.json();
    renderTable();
    renderTopBar();
    renderStatsBar();
    renderChartsIfVisible();
    hideLoading();
  } catch(e) { console.error('Erro:', e); }
}

// ── Top bar (cota) ───────────────────────────────────────────────
function renderTopBar() {
  if (!portfolioData) return;
  const q = portfolioData.quota || {};

  document.getElementById('ref-date').textContent =
    q.data_fechamento ? 'REF: ' + q.data_fechamento : 'REF: —';

  const cotaEl   = document.getElementById('cota-value');
  const changeEl = document.getElementById('cota-change');
  const refEl    = document.getElementById('cota-ref');

  if (q.cota_estimada) {
    cotaEl.textContent = q.cota_estimada.toFixed(8);
    const pct  = q.variacao_pct ?? 0;
    const rCota = q.variacao_rs_por_cota ?? 0;
    const arrow = pct >= 0 ? '▲' : '▼';
    changeEl.textContent = `${arrow}${Math.abs(rCota).toFixed(8)}  ${sign(pct)}${fmt(pct,4)}%`;
    changeEl.className = 'bbg-cota-change ' + (pct >= 0 ? 'positive' : 'negative');
    refEl.textContent  = `FECH. ANT.: ${q.quota_fechamento?.toFixed(8) ?? '—'}`;
  } else {
    cotaEl.textContent = '—';
    changeEl.textContent = '—';
    changeEl.className = 'bbg-cota-change';
  }
}

// ── Stats bar ────────────────────────────────────────────────────
function renderStatsBar() {
  if (!portfolioData) return;
  const q  = portfolioData.quota || {};
  const d  = portfolioData;

  const setVal = (id, val, cls) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = val;
    el.className = 'bbg-stat-val' + (cls ? ' ' + cls : '');
  };

  setVal('s-ret-fundo', q.retorno_fundo_pct != null ? sign(q.retorno_fundo_pct)+fmt(q.retorno_fundo_pct,2)+'%' : '—', colorCls(q.retorno_fundo_pct));
  setVal('s-ibov',      q.retorno_ibov_pct  != null ? sign(q.retorno_ibov_pct) +fmt(q.retorno_ibov_pct,2)+'%' : '—', colorCls(q.retorno_ibov_pct));
  setVal('s-alpha',     q.alpha_pct         != null ? sign(q.alpha_pct)+fmt(q.alpha_pct,2)+'%'                : '—', colorCls(q.alpha_pct));

  const provEl = document.getElementById('s-prov');
  if (provEl) {
    if (q.provisao_performance_rs != null && q.provisao_performance_rs > 0) {
      provEl.textContent = fmtBRL(q.provisao_performance_rs) + ' (' + fmt(q.provisao_performance_pct,3) + '% NAV)';
      provEl.className   = 'bbg-stat-val positive';
    } else {
      provEl.textContent = 'R$0 (sem alpha)';
      provEl.className   = 'bbg-stat-val neutral';
    }
  }

  setVal('s-nav',    fmtBRL(d.total_value));
  setVal('s-upside', d.weighted_upside != null ? sign(d.weighted_upside)+fmt(d.weighted_upside,2)+'%' : '—', colorCls(d.weighted_upside));
  setVal('s-beta',   d.weighted_beta   != null ? fmt(d.weighted_beta,2) : '—');

  const now = new Date();
  document.getElementById('s-update').textContent = now.toLocaleTimeString('pt-BR');
}

// ── Table ────────────────────────────────────────────────────────
function renderTable() {
  if (!portfolioData) return;
  if (!document.getElementById('portfolio-body')) return; // tab-table bloqueado para este viewer
  const rows = [...portfolioData.rows].sort((a, b) => {
    let av = a[sortCol], bv = b[sortCol];
    if (av == null) av = sortDir === 'asc' ?  Infinity : -Infinity;
    if (bv == null) bv = sortDir === 'asc' ?  Infinity : -Infinity;
    if (typeof av === 'string') return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
    return sortDir === 'asc' ? av - bv : bv - av;
  });

  const tbody = document.getElementById('portfolio-body');
  tbody.innerHTML = '';

  rows.forEach(row => {
    const tr = document.createElement('tr');
    tr.dataset.ticker = row.ticker;

    const liq = row.liq_diaria_mm;
    const liqHtml = liq == null ? '—'
      : `<span class="liq-badge ${liq>=0?'liq-buy':'liq-sell'}">${liq>=0?'+':''}${liq}</span>`;

    let rangeHtml = '—';
    if (row.week_high && row.week_low && row.preco) {
      const pct = Math.min(100, Math.max(0,
        (row.preco - row.week_low) / (row.week_high - row.week_low) * 100
      )).toFixed(0);
      rangeHtml = `<div class="range-bar">
        <span class="range-label">${fmt(row.week_low,0)}</span>
        <div class="range-track"><div class="range-fill" style="width:${pct}%"></div></div>
        <span class="range-label">${fmt(row.week_high,0)}</span>
      </div>`;
    }

    tr.innerHTML = `
      <td class="ticker-cell">${row.ticker}${row.short_name?`<span class="name-sub">${row.short_name}</span>`:''}</td>
      <td>${row.categoria||'—'}</td>
      <td>${row.sector||'—'}</td>
      <td class="num">${row.pct_total!=null?fmt(row.pct_total,2)+'%':'—'}</td>
      <td class="num">${fmtBRL(row.valor_liquido)}</td>
      <td class="num">${fmtBRL(row.preco)}</td>
      <td class="num ${colorCls(row.var_dia_pct)}">${row.var_dia_pct!=null?sign(row.var_dia_pct)+fmt(row.var_dia_pct,2)+'%':'—'}</td>
      <td class="num">${fmtInt(row.quantidade)}</td>
      <td class="num">${liqHtml}</td>
      <td class="num">${fmt(row.trailing_pe,1)}</td>
      <td class="num">${fmt(row.forward_pe,1)}</td>
      <td class="num">${fmt(row.enterprise_to_ebitda,1)}</td>
      <td class="num ${colorCls(row.return_on_equity)}">${row.return_on_equity!=null?fmt(row.return_on_equity,1)+'%':'—'}</td>
      <td class="num">${fmt(row.beta,2)}</td>
      <td class="num">${fmt(row.price_to_book,1)}</td>
      <td class="num">${row.dividend_yield!=null?fmt(row.dividend_yield,2)+'%':'—'}</td>
      <td class="num">${row.market_cap_bi!=null?'R$'+fmt(row.market_cap_bi,1)+'B':'—'}</td>
      <td class="num">${row.lucro_mi_25!=null?fmtInt(row.lucro_mi_25):'—'}</td>
      <td class="num">${fmt(row.pl_alvo_25,1)}</td>
      <td class="num">${fmtBRL(row.preco_alvo)}</td>
      <td class="num ${upsideCls(row.upside_pct)}">${row.upside_pct!=null?sign(row.upside_pct)+fmt(row.upside_pct,2)+'%':'—'}</td>
      <td>${window.USER_ROLE === 'admin' ? '<button class="btn-edit" title="Editar">✎</button>' : ''}</td>
    `;
    const editBtn = tr.querySelector('.btn-edit');
    if (editBtn) editBtn.addEventListener('click', () => openEditModal(row));
    tbody.appendChild(tr);
  });

  document.querySelectorAll('th[data-col]').forEach(th => {
    th.classList.remove('sorted-asc','sorted-desc');
    if (th.dataset.col === sortCol) th.classList.add(sortDir === 'asc' ? 'sorted-asc' : 'sorted-desc');
  });
}

document.querySelectorAll('th[data-col]').forEach(th => {
  th.addEventListener('click', () => {
    const col = th.dataset.col;
    if (sortCol === col) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
    else { sortCol = col; sortDir = ['ticker','categoria','sector'].includes(col) ? 'asc' : 'desc'; }
    renderTable();
  });
});

// ── Auto refresh ─────────────────────────────────────────────────
function startRefreshCycle() {
  clearInterval(refreshTimer); clearInterval(countdownTimer);
  secondsLeft  = REFRESH_SEC;
  refreshTimer = setInterval(refreshPricesOnly, REFRESH_SEC * 1000);
  countdownTimer = setInterval(() => {
    secondsLeft = Math.max(0, secondsLeft - 1);
    const el = document.getElementById('s-next');
    if (el) el.textContent = `PRÓX: ${secondsLeft}s`;
  }, 1000);
}

async function refreshPricesOnly() {
  try {
    const res  = await fetch('/api/prices');
    const json = await res.json();
    if (!portfolioData) return;

    const pm = json.prices;
    // Update IBOV in quota
    if (portfolioData.quota && pm['BVSP']) {
      portfolioData.quota.retorno_ibov_pct = pm['^BVSP']?.change_pct ?? portfolioData.quota.retorno_ibov_pct;
    }

    portfolioData.rows.forEach(row => {
      const p = pm[row.yahoo_ticker]; if (!p) return;
      const old = row.preco;
      row.preco = p.price; row.var_dia_pct = p.change_pct;
      if (row.preco && row.quantidade) row.valor_liquido = Math.round(row.preco * row.quantidade * 100) / 100;
      if (row.preco && row.preco_alvo)  row.upside_pct   = Math.round((row.preco_alvo / row.preco - 1) * 10000) / 100;
      if (old !== row.preco) {
        const tr = document.querySelector(`tr[data-ticker="${row.ticker}"]`);
        if (tr) { tr.classList.add(row.preco > old ? 'flash-up' : 'flash-down');
                  setTimeout(() => tr.classList.remove('flash-up','flash-down'), 800); }
      }
    });

    const total = portfolioData.rows.reduce((s,r) => s + (r.valor_liquido||0), 0);
    portfolioData.total_value = Math.round(total * 100) / 100;
    portfolioData.rows.forEach(r => {
      r.pct_total = total > 0 && r.valor_liquido ? Math.round(r.valor_liquido / total * 10000) / 100 : null;
    });
    const ws = portfolioData.rows.filter(r => r.upside_pct != null && r.pct_total)
                                  .reduce((s,r) => s + r.upside_pct * r.pct_total / 100, 0);
    portfolioData.weighted_upside = Math.round(ws * 100) / 100;

    // Recalculate quota
    if (portfolioData.quota) {
      const valid = portfolioData.rows.filter(r => r.pct_total && r.var_dia_pct != null);
      const retCart = valid.reduce((s,r) => s + (r.var_dia_pct/100) * (r.pct_total/100), 0);
      const ibovRet = (portfolioData.quota.retorno_ibov_pct || 0) / 100;
      const feeRate = (portfolioData.quota.performance_fee_rate || 20) / 100;
      const qFech   = portfolioData.quota.quota_fechamento || 0;
      portfolioData.quota.retorno_fundo_pct = Math.round(retCart * 10000) / 100;
      portfolioData.quota.variacao_pct      = portfolioData.quota.retorno_fundo_pct;
      portfolioData.quota.alpha_pct         = Math.round((retCart - ibovRet) * 10000) / 100;
      portfolioData.quota.cota_estimada     = qFech ? parseFloat((qFech * (1 + retCart)).toFixed(8)) : null;
      portfolioData.quota.variacao_rs_por_cota = portfolioData.quota.cota_estimada ? parseFloat((portfolioData.quota.cota_estimada - qFech).toFixed(8)) : null;
      const alpha = retCart - ibovRet;
      portfolioData.quota.provisao_performance_pct = Math.round(Math.max(0, alpha * feeRate) * 10000) / 100;
      portfolioData.quota.provisao_performance_rs  = Math.round(Math.max(0, alpha * feeRate) * total * 100) / 100;
    }

    renderTable(); renderTopBar(); renderStatsBar();
    secondsLeft = REFRESH_SEC;
  } catch(e) { console.error('Erro refresh:', e); }
}

document.getElementById('btn-refresh').addEventListener('click', async () => {
  const btn = document.getElementById('btn-refresh');
  btn.disabled = true;
  await refreshPricesOnly();
  btn.disabled = false;
});

// ── Tabs ─────────────────────────────────────────────────────────
document.querySelectorAll('.bbg-fn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.bbg-fn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');
    if (btn.dataset.tab === 'tab-charts')  requestAnimationFrame(() => loadCharts(currentDays));
    if (btn.dataset.tab === 'tab-config')  loadConfig();
    if (btn.dataset.tab === 'tab-history') loadHistoryTab();
  });
});

function renderChartsIfVisible() {
  if (document.getElementById('tab-charts')?.classList.contains('active')) {
    requestAnimationFrame(() => loadCharts(currentDays));
  }
}

// ── Chart: Performance (cota history vs IBOV) ────────────────────
let _perfCache = null;

// Filtra série por range usando datas de calendário, não contagem de entradas
function filterSeriesByRange(allSeries, range) {
  if (!range || range === '0' || range === 0) return allSeries;
  if (range && typeof range === 'object' && range.from) {
    return allSeries.filter(s =>
      (!range.from || s.date >= range.from) &&
      (!range.to   || s.date <= range.to)
    );
  }
  const lastDate = new Date(allSeries[allSeries.length - 1].date + 'T00:00:00');
  let cutoff;
  if (range === 'ytd') {
    cutoff = new Date(lastDate.getFullYear(), 0, 1);
  } else {
    cutoff = new Date(lastDate);
    cutoff.setDate(cutoff.getDate() - parseInt(range));
  }
  const cutoffStr = cutoff.toISOString().slice(0, 10);
  return allSeries.filter(s => s.date >= cutoffStr);
}

async function loadHistoryChart(days) {
  const canvas  = document.getElementById('history-chart');
  const loading = document.getElementById('history-loading');
  const summary = document.getElementById('perf-summary');
  canvas.style.display = 'none';
  loading.classList.remove('hidden');
  loading.textContent  = 'CARREGANDO HISTÓRICO DE COTAS...';
  summary.classList.add('hidden');

  try {
    if (!_perfCache) {
      const res  = await fetch('/api/performance-chart');
      _perfCache = await res.json();
    }
    const allSeries = _perfCache.series || [];
    if (!allSeries.length) {
      loading.textContent = 'SEM DADOS DE HISTÓRICO.';
      loading.classList.remove('hidden'); return;
    }

    // ── Filter by range (calendar days, not entry count) ──
    const series = filterSeriesByRange(allSeries, days);

    // ── Helper: rebase a {date→value} map to the series window ──
    function getBenchmarkData(backendKey, seriesDates, cache) {
      const map = cache.benchmarks?.[backendKey];
      if (!map) return null;
      let baseVal = null;
      for (const date of seriesDates) {
        if (map[date] != null) { baseVal = map[date]; break; }
      }
      if (!baseVal) return null;
      return seriesDates.map(date => {
        const v = map[date];
        return v != null ? +((v / baseVal - 1) * 100).toFixed(2) : null;
      });
    }

    // ── Rebase to filtered window start ──
    const baseFund = series[0].fund;
    const baseIbov = series.find(s => s.ibov != null)?.ibov ?? null;

    const labels   = series.map(s => s.date);
    const fundData = series.map(s => s.fund != null ? +((s.fund / baseFund - 1) * 100).toFixed(2) : null);
    const ibovData = series.map(s => s.ibov != null && baseIbov ? +((s.ibov / baseIbov - 1) * 100).toFixed(2) : null);

    // ── Summary stats ──
    const lastFund = fundData[fundData.length - 1];
    const lastIbov = ibovData.filter(v => v != null).at(-1);
    const alpha    = lastFund != null && lastIbov != null && selectedBenchmarks.has('ibov')
      ? +(lastFund - lastIbov).toFixed(2) : null;

    const maxDD = (() => {
      let peak = -Infinity, dd = 0;
      fundData.forEach(v => { if (v == null) return; if (v > peak) peak = v; dd = Math.min(dd, v - peak); });
      return dd.toFixed(2);
    })();

    const dailyRets = [];
    for (let i = 1; i < series.length; i++) {
      if (series[i].fund && series[i-1].fund)
        dailyRets.push((series[i].fund / series[i-1].fund - 1) * 100);
    }
    const vol = dailyRets.length > 1
      ? +(Math.sqrt(dailyRets.reduce((s,r) => s + Math.pow(r - dailyRets.reduce((a,b)=>a+b,0)/dailyRets.length, 2), 0) / dailyRets.length) * Math.sqrt(252)).toFixed(2)
      : null;

    // ── Render summary bar ──
    const pc  = v => v == null ? '—' : (v >= 0 ? '+' : '') + fmt(v, 2) + '%';
    const cls = v => v == null ? 'neutral' : v > 0 ? 'positive' : v < 0 ? 'negative' : 'neutral';
    const summaryItems = [['HARBOUR IAT', pc(lastFund), cls(lastFund)]];
    for (const bk of selectedBenchmarks) {
      const cfg = BENCH_CONFIG[bk];
      if (!cfg) continue;
      const data = bk === 'ibov' ? ibovData : getBenchmarkData(BENCH_BACKEND_KEY[bk], labels, _perfCache);
      const lastV = data ? data.filter(v => v != null).at(-1) : null;
      summaryItems.push([cfg.label, pc(lastV), cls(lastV)]);
    }
    if (alpha != null) summaryItems.push(['ALPHA vs IBOV', pc(alpha), cls(alpha)]);
    summaryItems.push(
      ['MAX DRAWDOWN', pc(+maxDD), 'negative'],
      ['VOLATILIDADE A.A.', vol != null ? fmt(vol, 2) + '%' : '—', 'neutral'],
      ['PERÍODO', labels[0] + ' → ' + labels[labels.length-1], 'neutral'],
    );
    summary.innerHTML = summaryItems.map(([lbl, val, c]) =>
      `<div class="perf-item"><span class="perf-item-lbl">${lbl}</span><span class="perf-item-val ${c}">${val}</span></div>`
    ).join('');
    summary.classList.remove('hidden');

    // ── Build gradient fill ──
    loading.classList.add('hidden'); canvas.style.display = '';
    const ctx = canvas.getContext('2d');
    const grad = ctx.createLinearGradient(0, 0, 0, canvas.clientHeight || 300);
    grad.addColorStop(0,   'rgba(255,140,0,0.18)');
    grad.addColorStop(0.6, 'rgba(255,140,0,0.04)');
    grad.addColorStop(1,   'rgba(255,140,0,0)');

    const lf = lastFund != null ? (lastFund >= 0 ? '+' : '') + fmt(lastFund, 2) + '%' : '';

    // ── Smart x-axis ticks ──
    const n = labels.length;
    const tickStep = n <= 60 ? 7 : n <= 180 ? 20 : n <= 400 ? 45 : n <= 800 ? 90 : 180;

    // ── Build datasets: fund + selected benchmarks ──
    const datasets = [
      {
        label: `HARBOUR IAT  ${lf}`,
        data: fundData,
        borderColor: '#ff8c00',
        backgroundColor: grad,
        borderWidth: 2.5,
        pointRadius: 0,
        pointHoverRadius: 5,
        pointHoverBackgroundColor: '#ff8c00',
        pointHoverBorderColor: '#000',
        pointHoverBorderWidth: 2,
        fill: true,
        tension: 0.15,
        order: 1,
      },
    ];

    let dsOrder = 2;
    for (const bk of selectedBenchmarks) {
      const cfg = BENCH_CONFIG[bk];
      if (!cfg) continue;
      const data = bk === 'ibov'
        ? ibovData
        : getBenchmarkData(BENCH_BACKEND_KEY[bk], labels, _perfCache);
      if (!data) continue;
      const lastV = data.filter(v => v != null).at(-1);
      const lbl = lastV != null ? (lastV >= 0 ? '+' : '') + fmt(lastV, 2) + '%' : '';
      datasets.push({
        label: `${cfg.label}  ${lbl}`,
        data,
        borderColor: cfg.color,
        backgroundColor: 'transparent',
        borderWidth: 1.5,
        pointRadius: 0,
        pointHoverRadius: 4,
        pointHoverBackgroundColor: cfg.color,
        pointHoverBorderColor: '#000',
        pointHoverBorderWidth: 2,
        fill: false,
        tension: 0.15,
        borderDash: cfg.dash,
        order: dsOrder++,
      });
    }

    if (historyChart) { historyChart.destroy(); historyChart = null; }
    historyChart = new Chart(canvas, {
      type: 'line',
      data: { labels, datasets },
      options: {
        responsive: true,
        animation: { duration: 350 },
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: {
            position: 'top',
            align: 'end',
            labels: {
              color: '#aaa',
              usePointStyle: true,
              pointStyleWidth: 12,
              padding: 20,
              font: { size: 10, family: "'Cascadia Code','Courier New',monospace", weight: '700' },
            },
          },
          tooltip: {
            backgroundColor: 'rgba(10,10,10,0.95)',
            borderColor: '#333',
            borderWidth: 1,
            titleColor: '#ff8c00',
            titleFont: { size: 10, weight: '700', family: "'Cascadia Code','Courier New',monospace" },
            bodyFont:  { size: 11, family: "'Cascadia Code','Courier New',monospace" },
            padding: 10,
            callbacks: {
              title: items => items[0]?.label ?? '',
              label: ctx => {
                const v = ctx.parsed.y;
                const s = v >= 0 ? '+' : '';
                const name = ctx.dataset.label.split('  ')[0].padEnd(12);
                return `  ${name}  ${s}${fmt(v, 2)}%`;
              },
              afterBody: items => {
                const f = items.find(i => i.datasetIndex === 0)?.parsed.y;
                if (f == null || items.length < 2) return [];
                return items.filter(i => i.datasetIndex > 0).map(i => {
                  const v = i.parsed.y;
                  if (v == null) return null;
                  const a = +(f - v).toFixed(2);
                  const bName = ('α ' + i.dataset.label.split('  ')[0]).padEnd(14);
                  return `  ${bName}  ${a >= 0 ? '+' : ''}${fmt(a, 2)}%`;
                }).filter(Boolean);
              },
            },
          },
        },
        scales: {
          x: {
            grid: { color: '#161616', drawBorder: false },
            ticks: {
              color: '#555',
              maxRotation: 0,
              font: { size: 9, family: "'Cascadia Code','Courier New',monospace" },
              callback: (_, i) => {
                if (i % tickStep !== 0) return '';
                const d = labels[i];
                return d ? d.slice(0, 7) : '';
              },
            },
            border: { color: '#2a2a2a' },
          },
          y: {
            position: 'right',
            grid: { color: '#161616', drawBorder: false },
            ticks: {
              color: '#555',
              font: { size: 9, family: "'Cascadia Code','Courier New',monospace" },
              callback: v => (v >= 0 ? '+' : '') + v.toFixed(0) + '%',
            },
            border: { color: '#2a2a2a', dash: [3, 3] },
          },
        },
      },
    });
    requestAnimationFrame(() => historyChart?.resize());
  } catch (e) {
    loading.textContent = 'ERRO: ' + e.message;
    loading.classList.remove('hidden'); canvas.style.display = 'none';
  }
}

// ── Chart: Sector ────────────────────────────────────────────────
const CHART_COLORS = ['#ff8c00','#00aacc','#00cc44','#ff3333','#ffcc00','#9b59b6','#1abc9c','#e67e22','#3498db','#e91e63'];

function renderSectorChart() {
  if (!portfolioData) return;
  const canvas = document.getElementById('sector-chart');
  const rows   = [...portfolioData.rows]
    .filter(r => r.valor_liquido)
    .sort((a, b) => b.valor_liquido - a.valor_liquido);
  const total  = rows.reduce((s, r) => s + r.valor_liquido, 0);
  const labels = rows.map(r => r.ticker);
  const values = rows.map(r => total > 0 ? Math.round(r.valor_liquido / total * 1000) / 10 : 0);
  const colors = labels.map((_, i) => CHART_COLORS[i % CHART_COLORS.length]);
  if (sectorChart) sectorChart.destroy();
  sectorChart = new Chart(canvas, {
    type: 'doughnut',
    data: { labels, datasets: [{ data: values, backgroundColor: colors, borderColor: '#000', borderWidth: 2, hoverOffset: 6 }] },
    options: {
      responsive: true,
      cutout: '62%',
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: 'rgba(10,10,10,0.95)',
          borderColor: '#333', borderWidth: 1,
          titleColor: '#ff8c00',
          titleFont: { size: 10, weight: '700', family: "'Cascadia Code','Courier New',monospace" },
          bodyFont:  { size: 11, family: "'Cascadia Code','Courier New',monospace" },
          padding: 10,
          callbacks: {
            label: ctx => {
              const row = rows[ctx.dataIndex];
              return [
                `  ${ctx.parsed.toFixed(1)}% do portfólio`,
                `  ${fmtBRL(row.valor_liquido)}`,
              ];
            },
          },
        },
      },
    },
  });
  document.getElementById('sector-legend').innerHTML = rows.map((r, i) =>
    `<div class="sector-legend-item">
       <div class="sector-legend-dot" style="background:${colors[i]}"></div>
       <span>${r.ticker} <strong style="color:#e8e8e8">${(r.valor_liquido / total * 100).toFixed(1)}%</strong></span>
     </div>`
  ).join('');
}

// ── Chart: Upside ────────────────────────────────────────────────
function renderUpsideChart() {
  if (!portfolioData) return;
  const canvas = document.getElementById('upside-chart');
  const rows = portfolioData.rows.filter(r => r.upside_pct != null).sort((a,b) => b.upside_pct - a.upside_pct);
  const colors = rows.map(r => r.upside_pct >= 0 ? 'rgba(0,204,68,0.7)' : 'rgba(255,51,51,0.7)');
  if (upsideChart) upsideChart.destroy();
  upsideChart = new Chart(canvas, {
    type: 'bar',
    data: { labels: rows.map(r => r.ticker),
      datasets: [{ label: 'Upside %', data: rows.map(r => r.upside_pct),
        backgroundColor: colors, borderColor: colors, borderWidth: 1, borderRadius: 2 }] },
    options: { responsive: true, indexAxis: 'y',
      plugins: { legend: { display: false },
        tooltip: { backgroundColor: '#0d0d0d', borderColor: '#2a2a2a', borderWidth: 1,
          callbacks: { label: ctx => ` ${ctx.parsed.x>=0?'+':''}${ctx.parsed.x.toFixed(2)}%` } } },
      scales: {
        x: { grid: { color: '#1c1c1c' }, ticks: { callback: v => v+'%' } },
        y: { grid: { display: false } },
      },
    },
  });
}

async function loadCharts(range) {
  currentDays = range;
  renderSectorChart(); renderUpsideChart();
  await loadHistoryChart(range);
  loadDrawdownVolatility(range);
  loadPerfIndicators();
  loadMonthlyReturnsTable();
}

document.querySelectorAll('.range-btn:not(#range-custom-btn)').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('range-custom-panel').classList.add('hidden');
    currentDays = btn.dataset.range;
    loadHistoryChart(btn.dataset.range);
    loadDrawdownVolatility(btn.dataset.range);
  });
});

// ── Custom date range ──
const _customBtn   = document.getElementById('range-custom-btn');
const _customPanel = document.getElementById('range-custom-panel');
const _customFrom  = document.getElementById('range-custom-from');
const _customTo    = document.getElementById('range-custom-to');
const _customApply = document.getElementById('range-custom-apply');

_customBtn?.addEventListener('click', () => {
  const isOpen = !_customPanel.classList.contains('hidden');
  _customPanel.classList.toggle('hidden', isOpen);
  if (!isOpen) {
    document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
    _customBtn.classList.add('active');
  }
});

_customApply?.addEventListener('click', () => {
  const from = _customFrom.value;
  const to   = _customTo.value;
  if (!from && !to) return;
  const range = { from, to: to || null };
  currentDays = range;
  loadHistoryChart(range);
  loadDrawdownVolatility(range);
});

document.querySelectorAll('.bench-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const bk = btn.dataset.bench;
    if (selectedBenchmarks.has(bk)) {
      selectedBenchmarks.delete(bk);
      btn.classList.remove('active');
    } else {
      selectedBenchmarks.add(bk);
      btn.classList.add('active');
    }
    const activeBtn = document.querySelector('.range-btn.active');
    const activeRange = activeBtn?.id === 'range-custom-btn'
      ? { from: _customFrom?.value || null, to: _customTo?.value || null }
      : (activeBtn?.dataset.range ?? '0');
    loadHistoryChart(activeRange);
  });
});

function invalidatePerfCache() { _perfCache = null; }

// ── Drawdown & Volatility Charts ─────────────────────────────────
let ddChart  = null;
let volChart = null;
let _ddVolCache = null;

async function loadDrawdownVolatility(range) {
  try {
    if (!_ddVolCache) {
      const res = await fetch('/api/drawdown-volatility');
      _ddVolCache = (await res.json()).series || [];
    }
    const series = filterSeriesByRange(_ddVolCache, range ?? currentDays ?? '0');
    renderDDVol(series);
  } catch(e) {
    ['dd-loading','vol-loading'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = 'ERRO: ' + e.message;
    });
  }
}

function renderDDVol(series) {
  if (!series.length) return;

  const labels = series.map(s => s.date);
  const ddData = series.map(s => s.drawdown);
  const vData  = series.map(s => s.vol);

  const n = labels.length;
  const tickStep = n <= 60 ? 7 : n <= 180 ? 20 : n <= 400 ? 45 : n <= 800 ? 90 : 180;
  const xTick = (_, i) => { if (i % tickStep !== 0) return ''; return labels[i]?.slice(0,7) ?? ''; };

  const baseOpts = (yFmt) => ({
    responsive: true,
    animation: { duration: 350 },
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: 'rgba(10,10,10,0.95)',
        borderColor: '#333', borderWidth: 1,
        titleColor: '#ff8c00',
        titleFont: { size: 10, weight: '700', family: "'Cascadia Code','Courier New',monospace" },
        bodyFont:  { size: 11, family: "'Cascadia Code','Courier New',monospace" },
        padding: 10,
      },
    },
    scales: {
      x: {
        grid: { color: '#161616' },
        ticks: { color: '#555', maxRotation: 0, font: { size: 9 }, callback: xTick },
        border: { color: '#2a2a2a' },
      },
      y: {
        position: 'right',
        grid: { color: '#161616' },
        ticks: { color: '#555', font: { size: 9 }, callback: yFmt },
        border: { color: '#2a2a2a', dash: [3,3] },
      },
    },
  });

  // ── Drawdown chart ──
  const ddCanvas  = document.getElementById('dd-chart');
  const ddLoading = document.getElementById('dd-loading');
  ddLoading.classList.add('hidden');
  ddCanvas.style.display = '';

  const ddCtx  = ddCanvas.getContext('2d');
  const ddGrad = ddCtx.createLinearGradient(0, 0, 0, ddCanvas.clientHeight || 200);
  ddGrad.addColorStop(0, 'rgba(0,204,68,0.0)');
  ddGrad.addColorStop(1, 'rgba(0,204,68,0.22)');

  if (ddChart) ddChart.destroy();
  const ddOpts = baseOpts(v => (v >= 0 ? '+' : '') + v.toFixed(1) + '%');
  ddOpts.plugins.tooltip.callbacks = {
    title: items => items[0]?.label ?? '',
    label: ctx => `  Drawdown  ${ctx.parsed.y >= 0 ? '+' : ''}${fmt(ctx.parsed.y, 2)}%`,
  };

  const curDD = ddData.filter(v => v != null).at(-1);
  const ddBadge = document.getElementById('dd-current');
  if (ddBadge && curDD != null) {
    ddBadge.textContent = `Atual  ${curDD >= 0 ? '+' : ''}${fmt(curDD, 2)}%`;
    ddBadge.className = 'chart-badge ' + (curDD < 0 ? 'negative' : 'positive');
  }

  ddChart = new Chart(ddCanvas, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data: ddData,
        borderColor: '#00cc44',
        backgroundColor: ddGrad,
        borderWidth: 1.5,
        pointRadius: 0,
        pointHoverRadius: 4,
        fill: { target: { value: 0 } },
        tension: 0.1,
      }],
    },
    options: ddOpts,
  });

  // ── Volatility chart ──
  const volCanvas  = document.getElementById('vol-chart');
  const volLoading = document.getElementById('vol-loading');
  volLoading.classList.add('hidden');
  volCanvas.style.display = '';

  const volCtx  = volCanvas.getContext('2d');
  const volGrad = volCtx.createLinearGradient(0, 0, 0, volCanvas.clientHeight || 200);
  volGrad.addColorStop(0, 'rgba(0,204,68,0.18)');
  volGrad.addColorStop(1, 'rgba(0,204,68,0.0)');

  if (volChart) volChart.destroy();
  const volOpts = baseOpts(v => v.toFixed(0) + '%');
  volOpts.plugins.tooltip.callbacks = {
    title: items => items[0]?.label ?? '',
    label: ctx => `  Volatilidade  ${fmt(ctx.parsed.y, 2)}%`,
  };

  const curVol = vData.filter(v => v != null).at(-1);
  const volBadge = document.getElementById('vol-current');
  if (volBadge && curVol != null) {
    volBadge.textContent = `Atual  ${fmt(curVol, 2)}%`;
    volBadge.className = 'chart-badge neutral';
  }

  volChart = new Chart(volCanvas, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data: vData,
        borderColor: '#00cc44',
        backgroundColor: volGrad,
        borderWidth: 1.5,
        pointRadius: 0,
        pointHoverRadius: 4,
        fill: true,
        tension: 0.2,
        spanGaps: true,
      }],
    },
    options: volOpts,
  });
}

// ── Performance Indicators Table ─────────────────────────────────
let _perfIndCache = null;

async function loadPerfIndicators() {
  const wrap    = document.getElementById('perf-ind-wrap');
  const loading = document.getElementById('perf-ind-loading');
  if (!wrap || !loading || _perfIndCache) return;

  loading.classList.remove('hidden');
  try {
    const res = await fetch('/api/performance-indicators');
    _perfIndCache = (await res.json()).data || {};

    const WINDOWS = ['no_mes','no_ano','3m','6m','12m','24m','36m','48m','60m','total'];
    const LABELS  = ['No Mês','No Ano','3 Meses','6 Meses','12 Meses','24 Meses','36 Meses','48 Meses','60 Meses','Total'];

    const fmtV = (v, isRet=false) => {
      if (v == null) return '<span class="pi-dash">-</span>';
      const cls = v > 0 ? 'positive' : v < 0 ? 'negative' : '';
      const txt = isRet
        ? (v >= 0 ? '+' : '') + fmt(v, 2) + '%'
        : fmt(Math.abs(v), 2) + (isRet === 'sharpe' ? '' : '%');
      return `<span class="${cls}">${txt}</span>`;
    };
    const fmtRet    = v => fmtV(v, true);
    const fmtVol    = v => v == null ? '<span class="pi-dash">-</span>' : `<span>${fmt(v,2)}%</span>`;
    const fmtSharpe = v => {
      if (v == null) return '<span class="pi-dash">-</span>';
      const cls = v > 0 ? 'positive' : v < 0 ? 'negative' : '';
      return `<span class="${cls}">${fmt(v, 2)}</span>`;
    };

    const th = LABELS.map((l, i) =>
      `<th class="pi-th${i === WINDOWS.length - 1 ? ' pi-th-total' : ''}">${l}</th>`
    ).join('');

    const makeRow = (label, key, fmtFn) =>
      `<tr><td class="pi-row-label">${label}</td>` +
      WINDOWS.map((w, i) =>
        `<td class="pi-td${i === WINDOWS.length - 1 ? ' pi-td-total' : ''}">${fmtFn(_perfIndCache[w]?.[key])}</td>`
      ).join('') + '</tr>';

    wrap.innerHTML = `<div class="perf-ind-scroll"><table class="perf-ind-table">
      <thead><tr><th class="pi-th-label"></th>${th}</tr></thead>
      <tbody>
        ${makeRow('Rentabilidade',   'ret',    fmtRet)}
        ${makeRow('Volatilidade',    'vol',    fmtVol)}
        ${makeRow('Índice de Sharpe','sharpe', fmtSharpe)}
      </tbody>
    </table></div>`;

    loading.classList.add('hidden');
    wrap.classList.remove('hidden');
  } catch(e) {
    loading.textContent = 'ERRO: ' + e.message;
  }
}

// ── Monthly Returns Table ─────────────────────────────────────────
let _monthlyRetCache = null;

async function loadMonthlyReturnsTable() {
  const wrap    = document.getElementById('monthly-ret-wrap');
  const loading = document.getElementById('monthly-ret-loading');
  if (!wrap || !loading) return;
  if (_monthlyRetCache) return; // already rendered

  loading.classList.remove('hidden');
  loading.textContent = 'CARREGANDO RENTABILIDADE HISTÓRICA...';

  try {
    const res = await fetch('/api/monthly-returns');
    _monthlyRetCache = await res.json();
    const years = _monthlyRetCache.years || [];

    if (!years.length) {
      loading.textContent = 'SEM DADOS DE HISTÓRICO.';
      return;
    }

    const MONTHS   = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];
    const MNUMS    = ['01','02','03','04','05','06','07','08','09','10','11','12'];
    const fmtPct   = v => v == null ? '-' : (v >= 0 ? '+' : '') + fmt(v, 2) + '%';
    const clsPct   = v => v == null ? '' : v > 0 ? 'positive' : v < 0 ? 'negative' : '';

    let html = `<table class="monthly-ret-table">
      <thead><tr>
        <th colspan="2" class="mrt-th-ano">ANO</th>
        ${MONTHS.map(m => `<th class="mrt-th-num">${m}</th>`).join('')}
        <th class="mrt-th-num mrt-th-year">No ano</th>
        <th class="mrt-th-num mrt-th-accum">Acumulado</th>
      </tr></thead><tbody>`;

    [...years].reverse().forEach(row => {
      html += `<tr class="mrt-fund-row">
        <td class="mrt-year-num" rowspan="2">${row.year}</td>
        <td class="mrt-fund-name">HARBOUR IAT FIF AÇÕES RL</td>
        ${MNUMS.map(mn => { const v = row.fund_months[mn]; return `<td class="mrt-num ${clsPct(v)}">${fmtPct(v)}</td>`; }).join('')}
        <td class="mrt-num mrt-year ${clsPct(row.fund_year)}">${fmtPct(row.fund_year)}</td>
        <td class="mrt-num mrt-accum ${clsPct(row.fund_accum)}">${fmtPct(row.fund_accum)}</td>
      </tr><tr class="mrt-ibov-row">
        <td class="mrt-ibov-name">IBOV</td>
        ${MNUMS.map(mn => { const v = row.ibov_months[mn]; return `<td class="mrt-num ${clsPct(v)}">${fmtPct(v)}</td>`; }).join('')}
        <td class="mrt-num mrt-year ${clsPct(row.ibov_year)}">${fmtPct(row.ibov_year)}</td>
        <td class="mrt-num mrt-accum ${clsPct(row.ibov_accum)}">${fmtPct(row.ibov_accum)}</td>
      </tr>`;
    });

    html += '</tbody></table>';
    wrap.innerHTML = html;
    loading.classList.add('hidden');
    wrap.classList.remove('hidden');
  } catch(e) {
    loading.textContent = 'ERRO: ' + e.message;
  }
}

// ── Export ───────────────────────────────────────────────────────
document.getElementById('btn-export-csv')?.addEventListener('click',   () => { window.location.href = '/api/export/csv'; });
document.getElementById('btn-export-excel')?.addEventListener('click', () => { window.location.href = '/api/export/excel'; });

// ── Config tab ───────────────────────────────────────────────────
async function loadConfig() {
  const res    = await fetch('/api/fund-config');
  const config = await res.json();
  document.getElementById('cfg-quota').value       = config.quota_fechamento ?? '';
  document.getElementById('cfg-data').value        = config.data_fechamento  ?? '';
  document.getElementById('cfg-num-cotas').value   = config.num_cotas        ?? '';
  document.getElementById('cfg-caixa').value       = config.caixa            ?? '';
  document.getElementById('cfg-proventos').value   = config.proventos_a_receber ?? '';
  document.getElementById('cfg-custos').value      = config.custos_provisionados ?? '';
  document.getElementById('cfg-fee-rate').value    = config.performance_fee_rate ?? 20;
  document.getElementById('cfg-prov-acum').value   = config.performance_fee_acumulada_rs ?? '';
}

document.getElementById('cfg-save')?.addEventListener('click', async () => {
  const payload = {
    quota_fechamento:          document.getElementById('cfg-quota').value,
    data_fechamento:           document.getElementById('cfg-data').value,
    num_cotas:                 document.getElementById('cfg-num-cotas').value,
    caixa:                     document.getElementById('cfg-caixa').value,
    proventos_a_receber:       document.getElementById('cfg-proventos').value,
    custos_provisionados:      document.getElementById('cfg-custos').value,
    performance_fee_rate:      document.getElementById('cfg-fee-rate').value,
    performance_fee_acumulada_rs: document.getElementById('cfg-prov-acum').value,
  };
  const res = await fetch('/api/fund-config', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  const status = document.getElementById('cfg-status');
  if (res.ok) {
    status.textContent = '✔ SALVO COM SUCESSO';
    status.style.color = '#00cc44';
    setTimeout(() => { status.textContent = ''; }, 3000);
    await fetchPortfolio(); // refresh with new config
  } else {
    status.textContent = '✖ ERRO AO SALVAR';
    status.style.color = '#ff3333';
  }
});

// ── Edit Modal ───────────────────────────────────────────────────
function openEditModal(row) {
  editingTicker = row.ticker;
  document.getElementById('edit-modal-ticker').textContent = row.ticker;
  document.getElementById('edit-quantidade').value  = row.quantidade ?? '';
  document.getElementById('edit-liq').value         = row.liq_diaria_mm ?? '';
  document.getElementById('edit-lucro').value       = row.lucro_mi_25 ?? '';
  document.getElementById('edit-pl-alvo').value     = row.pl_alvo_25 ?? '';
  document.getElementById('edit-preco-alvo').value  = row.preco_alvo ?? '';
  document.getElementById('edit-modal').classList.remove('hidden');
}
const closeEditModal = () => { document.getElementById('edit-modal').classList.add('hidden'); editingTicker = null; };
document.getElementById('edit-modal-close').addEventListener('click', closeEditModal);
document.getElementById('edit-modal-cancel').addEventListener('click', closeEditModal);
document.getElementById('edit-modal').addEventListener('click', e => { if(e.target===document.getElementById('edit-modal')) closeEditModal(); });
document.getElementById('edit-modal-save').addEventListener('click', async () => {
  if (!editingTicker) return;
  const res = await fetch('/api/portfolio/update', { method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ ticker: editingTicker,
      quantidade: document.getElementById('edit-quantidade').value,
      liq_diaria_mm: document.getElementById('edit-liq').value,
      lucro_mi_25: document.getElementById('edit-lucro').value,
      pl_alvo_25: document.getElementById('edit-pl-alvo').value,
      preco_alvo: document.getElementById('edit-preco-alvo').value }) });
  if (res.ok) { closeEditModal(); showLoading(); await fetchPortfolio(); }
  else alert('ERRO AO SALVAR.');
});
document.getElementById('edit-modal-delete').addEventListener('click', async () => {
  if (!editingTicker || !confirm(`REMOVER ${editingTicker} DA CARTEIRA?`)) return;
  const res = await fetch(`/api/portfolio/${editingTicker}`, { method: 'DELETE' });
  if (res.ok) { closeEditModal(); showLoading(); await fetchPortfolio(); }
  else alert('ERRO AO REMOVER.');
});

// ── Add Modal ────────────────────────────────────────────────────
document.getElementById('btn-add-stock')?.addEventListener('click', () => {
  ['add-ticker','add-quantidade','add-liq','add-lucro','add-pl-alvo','add-preco-alvo'].forEach(id => document.getElementById(id).value='');
  document.getElementById('add-error').classList.add('hidden');
  document.getElementById('add-modal').classList.remove('hidden');
});
const closeAddModal = () => document.getElementById('add-modal').classList.add('hidden');
document.getElementById('add-modal-close').addEventListener('click', closeAddModal);
document.getElementById('add-modal-cancel').addEventListener('click', closeAddModal);
document.getElementById('add-modal').addEventListener('click', e => { if(e.target===document.getElementById('add-modal')) closeAddModal(); });
document.getElementById('add-modal-save').addEventListener('click', async () => {
  const ticker   = document.getElementById('add-ticker').value.trim().toUpperCase();
  const quantidade = document.getElementById('add-quantidade').value;
  if (!ticker || !quantidade) { showAddError('TICKER E QUANTIDADE OBRIGATÓRIOS.'); return; }
  const btn = document.getElementById('add-modal-save');
  btn.disabled = true; btn.textContent = 'VERIFICANDO...';
  const res = await fetch('/api/portfolio/add', { method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ ticker, quantidade, categoria: document.getElementById('add-categoria').value,
      liq_diaria_mm: document.getElementById('add-liq').value,
      lucro_mi_25: document.getElementById('add-lucro').value,
      pl_alvo_25: document.getElementById('add-pl-alvo').value,
      preco_alvo: document.getElementById('add-preco-alvo').value }) });
  btn.disabled = false; btn.textContent = 'ADICIONAR';
  if (res.ok) { closeAddModal(); showLoading(); await fetchPortfolio(); }
  else { const err = await res.json(); showAddError(err.error || 'ERRO AO ADICIONAR.'); }
});
function showAddError(msg) {
  const el = document.getElementById('add-error'); el.textContent = msg; el.classList.remove('hidden');
}

// ── Loading ──────────────────────────────────────────────────────
const showLoading = () => document.getElementById('loading-overlay').classList.remove('hidden');
const hideLoading = () => document.getElementById('loading-overlay').classList.add('hidden');

// ── Histórico de Cotas ───────────────────────────────────────────
async function loadHistoryTab() {
  // Pre-fill date with today and cota with current estimated value (admin only)
  const regData = document.getElementById('hist-reg-data');
  if (regData) {
    regData.value = new Date().toISOString().slice(0, 10);
    const cota = portfolioData?.quota?.cota_estimada;
    const regCota = document.getElementById('hist-reg-cota');
    if (cota && regCota) regCota.value = cota.toFixed(8);
  }
  await renderQuotaHistoryTable();
}

async function renderQuotaHistoryTable() {
  const tbody = document.getElementById('history-body');
  tbody.innerHTML = '<tr><td colspan="5" class="empty-state">CARREGANDO...</td></tr>';
  try {
    const res     = await fetch('/api/quota-history');
    const history = await res.json();

    if (!history.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty-state">NENHUM FECHAMENTO REGISTRADO.</td></tr>';
      return;
    }

    const base = history[0].cota_fechamento;
    tbody.innerHTML = '';

    // Render newest first for better UX
    [...history].reverse().forEach((entry, idx, arr) => {
      const prev = arr[idx + 1];  // previous in reversed = next in original
      const varDia = prev
        ? (entry.cota_fechamento - prev.cota_fechamento) / prev.cota_fechamento * 100
        : null;
      const retAcum = (entry.cota_fechamento / base - 1) * 100;

      const varCls  = varDia  == null ? '' : varDia  >= 0 ? 'positive' : 'negative';
      const accumCls = retAcum >= 0 ? 'positive' : 'negative';

      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${entry.data}</td>
        <td class="num" style="color:var(--cyan);font-weight:700">${entry.cota_fechamento.toFixed(8)}</td>
        <td class="num ${varCls}">${varDia != null ? (varDia >= 0 ? '+' : '') + fmt(varDia, 4) + '%' : '—'}</td>
        <td class="num ${accumCls}">${(retAcum >= 0 ? '+' : '') + fmt(retAcum, 4)}%</td>
        <td>${window.USER_ROLE === 'admin' ? `<button class="btn-hist-delete" data-date="${entry.data}" title="Remover">✕</button>` : ''}</td>
      `;
      const delBtn = tr.querySelector('.btn-hist-delete');
      if (delBtn) delBtn.addEventListener('click', deleteQuotaEntry);
      tbody.appendChild(tr);
    });
  } catch(e) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty-state">ERRO: ${e.message}</td></tr>`;
  }
}

async function deleteQuotaEntry(e) {
  const date = e.currentTarget.dataset.date;
  if (!confirm(`REMOVER FECHAMENTO DE ${date}?`)) return;
  const res = await fetch(`/api/quota-history/${date}`, { method: 'DELETE' });
  if (res.ok) await renderQuotaHistoryTable();
  else alert('ERRO AO REMOVER.');
}

document.getElementById('hist-reg-save')?.addEventListener('click', async () => {
  const data = document.getElementById('hist-reg-data').value.trim();
  const cota = document.getElementById('hist-reg-cota').value.trim();
  if (!data || !cota) { alert('PREENCHA DATA E COTA.'); return; }
  const btn = document.getElementById('hist-reg-save');
  btn.disabled = true;
  const res = await fetch('/api/quota-history', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ data, cota_fechamento: parseFloat(cota) }),
  });
  btn.disabled = false;
  const status = document.getElementById('hist-reg-status');
  if (res.ok) {
    status.textContent = '✔ FECHAMENTO REGISTRADO';
    status.style.color = '#00cc44';
    setTimeout(() => { status.textContent = ''; }, 3000);
    await renderQuotaHistoryTable();
    // Refresh portfolio so cota base is updated
    await fetchPortfolio();
  } else {
    const err = await res.json();
    status.textContent = '✖ ' + (err.error || 'ERRO');
    status.style.color = '#ff3333';
  }
});

// ── Viewer Config (admin only) ───────────────────────────────────
if (window.USER_ROLE === 'admin') {
  document.querySelectorAll('.viewer-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
      const isOn = btn.classList.contains('viewer-toggle--on');
      btn.classList.toggle('viewer-toggle--on', !isOn);
      btn.classList.toggle('viewer-toggle--off', isOn);
      btn.textContent = isOn ? '○ BLOQUEADO' : '● LIBERADO';
    });
  });

  document.getElementById('viewer-config-save')?.addEventListener('click', async () => {
    const payload = {};
    document.querySelectorAll('.viewer-toggle').forEach(btn => {
      payload[btn.dataset.key] = btn.classList.contains('viewer-toggle--on');
    });
    const status = document.getElementById('viewer-config-status');
    const res = await fetch('/api/viewer-config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      status.textContent = '✔ ACESSO ATUALIZADO';
      status.style.color = '';
      setTimeout(() => { status.textContent = ''; }, 3000);
    } else {
      status.textContent = '✖ ERRO AO SALVAR';
      status.style.color = '#ff3333';
    }
  });
}

// ── Init ─────────────────────────────────────────────────────────
(async () => {
  await fetchPortfolio();
  startRefreshCycle();
})();
