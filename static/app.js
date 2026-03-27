/* ═══════════════════════════════════════════════════════════════
   HARBOUR IAT FIA — Bloomberg Terminal JS
   ═══════════════════════════════════════════════════════════════ */

// ── Market hours (BRT = UTC-3, seg-sex 10:00–17:30) ─────────────
function isMarketOpen() {
  const brt  = new Date(Date.now() - 3 * 60 * 60 * 1000);
  const day  = brt.getUTCDay(); // 0=dom, 6=sab
  if (day === 0 || day === 6) return false;
  const mins = brt.getUTCHours() * 60 + brt.getUTCMinutes();
  return mins >= 10 * 60 && mins < 17 * 60 + 30;
}

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

// ── Inline stock chart state ──────────────────────────────────────
let expandedTicker      = null;
let _currentExpandRange = '1M';
const _inlineCharts     = new Map();
const _stockHistCache   = new Map();
const STOCK_HIST_CACHE_TTL = 5 * 60 * 1000;
const TABLE_COL_COUNT   = 22;

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
    if (q.mercado_fechado) {
      changeEl.textContent = 'MERCADO FECHADO';
      changeEl.className = 'bbg-cota-change neutral';
      refEl.textContent  = `FECH.: ${q.quota_fechamento?.toFixed(8) ?? '—'}`;
    } else {
      const pct   = q.variacao_pct ?? 0;
      const rCota = q.variacao_rs_por_cota ?? 0;
      const arrow = pct >= 0 ? '▲' : '▼';
      changeEl.textContent = `${arrow}${Math.abs(rCota).toFixed(8)}  ${sign(pct)}${fmt(pct,4)}%`;
      changeEl.className = 'bbg-cota-change ' + (pct >= 0 ? 'positive' : 'negative');
      refEl.textContent  = `FECH. ANT.: ${q.quota_fechamento?.toFixed(8) ?? '—'}`;
    }
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
      <td class="ticker-cell"><span class="ticker-click" data-ticker="${row.ticker}">${row.ticker}</span>${row.short_name?`<span class="name-sub">${row.short_name}</span>`:''}</td>
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
      <td class="num">${fmt(row.peg_ratio,2)}</td>
      <td class="num">${fmt(row.enterprise_to_ebitda,1)}</td>
      <td class="num ${colorCls(row.return_on_equity)}">${row.return_on_equity!=null?fmt(row.return_on_equity,1)+'%':'—'}</td>
      <td class="num">${fmt(row.beta,2)}</td>
      <td class="num">${fmt(row.price_to_book,1)}</td>
      <td class="num">${row.dividend_yield!=null?fmt(row.dividend_yield,2)+'%':'—'}</td>
      <td class="num">${row.market_cap_bi!=null?'R$'+fmt(row.market_cap_bi,1)+'B':'—'}</td>
      <td class="num">${row.lucro_mi_26!=null?fmtInt(row.lucro_mi_26):'—'}</td>
      <td class="num">${fmtBRL(row.preco_alvo)}</td>
      <td class="num ${upsideCls(row.upside_pct)}">${row.upside_pct!=null?sign(row.upside_pct)+fmt(row.upside_pct,2)+'%':'—'}</td>
      <td>${window.USER_ROLE === 'admin' ? '<button class="btn-edit" title="Editar">✎</button>' : ''}</td>
    `;
    const editBtn = tr.querySelector('.btn-edit');
    if (editBtn) editBtn.addEventListener('click', () => openEditModal(row));
    const tickerSpan = tr.querySelector('.ticker-click');
    if (tickerSpan) {
      tickerSpan.addEventListener('click', e => {
        e.stopPropagation();
        toggleStockExpand(row.ticker, row.yahoo_ticker, row.short_name, tr);
      });
    }
    tbody.appendChild(tr);
  });

  document.querySelectorAll('th[data-col]').forEach(th => {
    th.classList.remove('sorted-asc','sorted-desc');
    if (th.dataset.col === sortCol) th.classList.add(sortDir === 'asc' ? 'sorted-asc' : 'sorted-desc');
  });
  renderWeightedRow();
  // Re-inject expanded row if one was open before re-render
  if (expandedTicker) {
    const newDataRow = document.querySelector(`tr[data-ticker="${expandedTicker}"]`);
    if (newDataRow) {
      newDataRow.classList.add('row-expanded');
      if (!document.querySelector(`.stock-expand-row[data-for="${expandedTicker}"]`)) {
        const rowData = portfolioData.rows.find(r => r.ticker === expandedTicker);
        if (rowData) injectExpandRow(expandedTicker, rowData.yahoo_ticker, rowData.short_name, newDataRow, _currentExpandRange);
      }
    } else {
      collapseCurrentExpand();
    }
  }
}

function renderWeightedRow() {
  const tfoot = document.getElementById('portfolio-foot');
  if (!tfoot || !portfolioData?.weighted_stats) return;
  const ws = portfolioData.weighted_stats;
  tfoot.innerHTML = `
    <tr class="weighted-row">
      <td colspan="9" class="weighted-label">CARTEIRA (POND.)</td>
      <td class="num">${fmt(ws.w_trailing_pe,1)}</td>
      <td class="num">${fmt(ws.w_forward_pe,1)}</td>
      <td class="num">${fmt(ws.w_peg_ratio,2)}</td>
      <td class="num">${fmt(ws.w_enterprise_to_ebitda,1)}</td>
      <td class="num ${colorCls(ws.w_return_on_equity)}">${ws.w_return_on_equity!=null?fmt(ws.w_return_on_equity,1)+'%':'—'}</td>
      <td class="num">${fmt(ws.w_beta,2)}</td>
      <td class="num">${fmt(ws.w_price_to_book,1)}</td>
      <td class="num">${ws.w_dividend_yield!=null?fmt(ws.w_dividend_yield,2)+'%':'—'}</td>
      <td class="num">—</td>
      <td class="num">${ws.w_lucro_mi_26!=null?fmtInt(ws.w_lucro_mi_26):'—'}</td>
      <td class="num">—</td>
      <td class="num ${upsideCls(ws.w_upside_pct)}">${ws.w_upside_pct!=null?sign(ws.w_upside_pct)+fmt(ws.w_upside_pct,2)+'%':'—'}</td>
      <td></td>
    </tr>`;
}

// ── Inline stock chart functions ─────────────────────────────────

function toggleStockExpand(ticker, yahooTicker, shortName, dataRow) {
  const alreadyOpen = expandedTicker === ticker;
  collapseCurrentExpand();
  if (alreadyOpen) return;
  expandedTicker = ticker;
  injectExpandRow(ticker, yahooTicker, shortName, dataRow, _currentExpandRange);
}

function collapseCurrentExpand() {
  if (!expandedTicker) return;
  const chart = _inlineCharts.get(expandedTicker);
  if (chart) { chart.destroy(); _inlineCharts.delete(expandedTicker); }
  const existing = document.querySelector(`.stock-expand-row[data-for="${expandedTicker}"]`);
  if (existing) existing.remove();
  const dataRow = document.querySelector(`tr[data-ticker="${expandedTicker}"]`);
  if (dataRow) dataRow.classList.remove('row-expanded');
  expandedTicker = null;
}

function injectExpandRow(ticker, yahooTicker, shortName, dataRow, range) {
  document.querySelector(`.stock-expand-row[data-for="${ticker}"]`)?.remove();
  dataRow.classList.add('row-expanded');
  const expandRow = document.createElement('tr');
  expandRow.className   = 'stock-expand-row';
  expandRow.dataset.for = ticker;
  const ranges = ['1S','1M','3M','6M','YTD','1A'];
  expandRow.innerHTML = `
    <td colspan="${TABLE_COL_COUNT}" class="stock-expand-td">
      <div class="stock-expand-inner">
        <div class="stock-expand-header">
          <span class="stock-expand-title">${ticker}</span>
          ${shortName ? `<span class="stock-expand-name">${shortName}</span>` : ''}
          <div class="stock-range-selector">
            ${ranges.map(r => `<button class="range-btn stock-range-btn${r === range ? ' active' : ''}" data-range="${r}">${r}</button>`).join('')}
          </div>
          <button class="stock-expand-close" title="Fechar">✕</button>
        </div>
        <div class="stock-expand-body">
          <div class="stock-chart-wrap">
            <canvas class="stock-mini-chart" id="mini-chart-${ticker}"></canvas>
            <div class="stock-chart-loading" id="mini-loading-${ticker}">CARREGANDO...</div>
          </div>
          <div class="stock-stats-sidebar" id="mini-stats-${ticker}">
            <div class="sstat"><span class="sstat-lbl">PERÍODO</span><span class="sstat-val" id="ss-ret-${ticker}">—</span></div>
            <div class="sstat"><span class="sstat-lbl">VS IBOV</span><span class="sstat-val" id="ss-ibov-${ticker}">—</span></div>
            <div class="sstat"><span class="sstat-lbl">MÁX 52S</span><span class="sstat-val" id="ss-hi-${ticker}">—</span></div>
            <div class="sstat"><span class="sstat-lbl">MÍN 52S</span><span class="sstat-val" id="ss-lo-${ticker}">—</span></div>
            <div class="sstat"><span class="sstat-lbl">P. ATUAL</span><span class="sstat-val" id="ss-px-${ticker}">—</span></div>
          </div>
        </div>
      </div>
    </td>`;
  dataRow.after(expandRow);
  expandRow.querySelectorAll('.stock-range-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      expandRow.querySelectorAll('.stock-range-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      _currentExpandRange = btn.dataset.range;
      loadStockChart(ticker, yahooTicker, shortName, btn.dataset.range);
    });
  });
  expandRow.querySelector('.stock-expand-close').addEventListener('click', collapseCurrentExpand);
  loadStockChart(ticker, yahooTicker, shortName, range);
}

async function loadStockChart(ticker, yahooTicker, shortName, range) {
  const canvas  = document.getElementById(`mini-chart-${ticker}`);
  const loading = document.getElementById(`mini-loading-${ticker}`);
  if (!canvas || !loading) return;
  canvas.style.display  = 'none';
  loading.textContent   = 'CARREGANDO...';
  loading.style.display = '';
  try {
    const cacheKey = `${yahooTicker}__${range}`;
    let data;
    const cached = _stockHistCache.get(cacheKey);
    if (cached && (Date.now() - cached.ts) < STOCK_HIST_CACHE_TTL) {
      data = cached.data;
    } else {
      const res = await fetch(`/api/stock-history/${encodeURIComponent(yahooTicker)}?range=${range}`);
      data = await res.json();
      _stockHistCache.set(cacheKey, { data, ts: Date.now() });
    }
    if (!data.series?.length) {
      loading.textContent = 'SEM DADOS PARA O PERÍODO.';
      return;
    }
    // Update stats sidebar
    const pc  = v => v == null ? '—' : (v >= 0 ? '+' : '') + fmt(v, 2) + '%';
    const cls = v => v == null ? '' : v > 0 ? 'positive' : v < 0 ? 'negative' : '';
    const setS = (id, val, c) => {
      const el = document.getElementById(id);
      if (el) { el.textContent = val; el.className = 'sstat-val ' + c; }
    };
    setS(`ss-ret-${ticker}`,  pc(data.period_return), cls(data.period_return));
    setS(`ss-ibov-${ticker}`, pc(data.vs_ibov), cls(data.vs_ibov));
    setS(`ss-hi-${ticker}`,   data.w52_high ? fmtBRL(data.w52_high) : '—', '');
    setS(`ss-lo-${ticker}`,   data.w52_low  ? fmtBRL(data.w52_low)  : '—', '');
    setS(`ss-px-${ticker}`,   data.series.length ? fmtBRL(data.series.at(-1).price) : '—', '');
    // Destroy previous instance for this ticker
    const prev = _inlineCharts.get(ticker);
    if (prev) { prev.destroy(); _inlineCharts.delete(ticker); }
    const labels    = data.series.map(s => s.date);
    const stockData = data.series.map(s => s.indexed);
    const ibovData  = data.series.map(s => s.ibov);
    const n = labels.length;
    const tickStep = n <= 10 ? 1 : n <= 30 ? 5 : n <= 90 ? 10 : n <= 180 ? 20 : 30;
    loading.style.display = 'none';
    canvas.style.display  = '';
    const ctx  = canvas.getContext('2d');
    const grad = ctx.createLinearGradient(0, 0, 0, canvas.clientHeight || 160);
    grad.addColorStop(0,   'rgba(255,140,0,0.18)');
    grad.addColorStop(0.7, 'rgba(255,140,0,0.04)');
    grad.addColorStop(1,   'rgba(255,140,0,0)');
    const pr = data.period_return;
    const ir = data.ibov_return;
    const stockLabel = `${ticker}  ${pr != null ? (pr >= 0 ? '+' : '') + fmt(pr, 2) + '%' : ''}`;
    const ibovLabel  = `IBOV  ${ir != null ? (ir >= 0 ? '+' : '') + fmt(ir, 2) + '%' : ''}`;
    const chart = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: stockLabel,
            data:  stockData,
            borderColor: '#ff8c00',
            backgroundColor: grad,
            borderWidth: 2,
            pointRadius: 0,
            pointHoverRadius: 4,
            fill: true,
            tension: 0.15,
            order: 1,
          },
          {
            label: ibovLabel,
            data:  ibovData,
            borderColor: '#00aacc',
            backgroundColor: 'transparent',
            borderWidth: 1.5,
            pointRadius: 0,
            pointHoverRadius: 3,
            fill: false,
            tension: 0.15,
            borderDash: [5, 4],
            order: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 300 },
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: {
            position: 'top',
            align: 'end',
            labels: {
              color: '#888',
              usePointStyle: true,
              pointStyleWidth: 10,
              padding: 12,
              font: { size: 9, family: "'Cascadia Code','Courier New',monospace", weight: '700' },
            },
          },
          tooltip: {
            backgroundColor: 'rgba(10,10,10,0.95)',
            borderColor: '#333',
            borderWidth: 1,
            titleColor: '#ff8c00',
            titleFont:  { size: 9, weight: '700', family: "'Cascadia Code','Courier New',monospace" },
            bodyFont:   { size: 10, family: "'Cascadia Code','Courier New',monospace" },
            padding: 8,
            callbacks: {
              title: items => items[0]?.label ?? '',
              label: ctx => {
                const v = ctx.parsed.y;
                if (v == null) return null;
                const pct = (v - 100).toFixed(2);
                const name = ctx.dataset.label.split('  ')[0].padEnd(10);
                return `  ${name}  ${parseFloat(pct) >= 0 ? '+' : ''}${pct}%`;
              },
            },
          },
        },
        scales: {
          x: {
            grid:   { color: '#161616' },
            border: { color: '#2a2a2a' },
            ticks:  {
              color: '#444',
              maxRotation: 0,
              font: { size: 8, family: "'Cascadia Code','Courier New',monospace" },
              callback: (_, i) => i % tickStep !== 0 ? '' : (labels[i]?.slice(5) ?? ''),
            },
          },
          y: {
            position: 'right',
            grid:     { color: '#161616' },
            border:   { color: '#2a2a2a', dash: [3, 3] },
            ticks:    {
              color: '#444',
              font: { size: 8, family: "'Cascadia Code','Courier New',monospace" },
              callback: v => (v >= 100 ? '+' : '') + (v - 100).toFixed(0) + '%',
            },
          },
        },
      },
    });
    _inlineCharts.set(ticker, chart);
  } catch(e) {
    loading.textContent   = 'ERRO: ' + e.message;
    loading.style.display = '';
    canvas.style.display  = 'none';
  }
}

// ─────────────────────────────────────────────────────────────────

function recalcWeightedStats() {
  if (!portfolioData) return;
  const rows = portfolioData.rows;
  const total = portfolioData.total_value || 0;
  function wavg(field) {
    const valid = rows.filter(r => r[field] != null && r.valor_liquido);
    const wt = valid.reduce((s,r) => s + r.valor_liquido, 0);
    if (!valid.length || wt === 0) return null;
    return Math.round(valid.reduce((s,r) => s + r[field] * r.valor_liquido / wt, 0) * 100) / 100;
  }
  portfolioData.weighted_stats = {
    w_trailing_pe:          wavg('trailing_pe'),
    w_forward_pe:           wavg('forward_pe'),
    w_peg_ratio:            wavg('peg_ratio'),
    w_enterprise_to_ebitda: wavg('enterprise_to_ebitda'),
    w_return_on_equity:     wavg('return_on_equity'),
    w_beta:                 portfolioData.weighted_beta,
    w_price_to_book:        wavg('price_to_book'),
    w_dividend_yield:       wavg('dividend_yield'),
    w_var_dia_pct:          wavg('var_dia_pct'),
    w_upside_pct:           portfolioData.weighted_upside,
    w_lucro_mi_26:          rows.reduce((s,r) => s + (r.lucro_mi_26||0), 0) || null,
  };
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

    const fm = json.fundamentals || {};
    portfolioData.rows.forEach(row => {
      const p = pm[row.yahoo_ticker]; if (!p) return;
      const old = row.preco;
      row.preco = p.price; row.var_dia_pct = p.change_pct;
      if (row.preco && row.quantidade) row.valor_liquido = Math.round(row.preco * row.quantidade * 100) / 100;
      if (row.preco && row.preco_alvo)  row.upside_pct   = Math.round((row.preco_alvo / row.preco - 1) * 10000) / 100;
      // Update fundamentals from fresh cache
      const f = fm[row.yahoo_ticker];
      if (f) { row.trailing_pe = f.trailing_pe; row.forward_pe = f.forward_pe; row.peg_ratio = f.peg_ratio; }
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
      if (!isMarketOpen()) {
        // Mercado fechado: congela na cota de fechamento, zera variações
        const qFech = portfolioData.quota.quota_fechamento || 0;
        portfolioData.quota.mercado_fechado          = true;
        portfolioData.quota.cota_estimada            = qFech || null;
        portfolioData.quota.variacao_pct             = 0;
        portfolioData.quota.retorno_fundo_pct        = 0;
        portfolioData.quota.retorno_ibov_pct         = 0;
        portfolioData.quota.alpha_pct                = 0;
        portfolioData.quota.variacao_rs_por_cota     = 0;
        portfolioData.quota.provisao_performance_pct = 0;
        portfolioData.quota.provisao_performance_rs  = 0;
      } else {
        const valid = portfolioData.rows.filter(r => r.pct_total && r.var_dia_pct != null);
        const retCart = valid.reduce((s,r) => s + (r.var_dia_pct/100) * (r.pct_total/100), 0);
        const ibovRet = (portfolioData.quota.retorno_ibov_pct || 0) / 100;
        const feeRate = (portfolioData.quota.performance_fee_rate || 20) / 100;
        const qFech   = portfolioData.quota.quota_fechamento || 0;
        portfolioData.quota.mercado_fechado          = false;
        portfolioData.quota.retorno_fundo_pct        = Math.round(retCart * 10000) / 100;
        portfolioData.quota.variacao_pct             = portfolioData.quota.retorno_fundo_pct;
        portfolioData.quota.alpha_pct                = Math.round((retCart - ibovRet) * 10000) / 100;
        portfolioData.quota.cota_estimada            = qFech ? parseFloat((qFech * (1 + retCart)).toFixed(8)) : null;
        portfolioData.quota.variacao_rs_por_cota     = portfolioData.quota.cota_estimada ? parseFloat((portfolioData.quota.cota_estimada - qFech).toFixed(8)) : null;
        const alpha = retCart - ibovRet;
        portfolioData.quota.provisao_performance_pct = Math.round(Math.max(0, alpha * feeRate) * 10000) / 100;
        portfolioData.quota.provisao_performance_rs  = Math.round(Math.max(0, alpha * feeRate) * total * 100) / 100;
      }
    }

    recalcWeightedStats();
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
    if (btn.dataset.tab === 'tab-charts')    requestAnimationFrame(() => loadCharts(currentDays));
    if (btn.dataset.tab === 'tab-config')    loadConfig();
    if (btn.dataset.tab === 'tab-history')   loadHistoryTab();
    if (btn.dataset.tab === 'tab-macro')     loadMacroTab();
    if (btn.dataset.tab === 'tab-watchlist') loadWatchlistTab();
    if (btn.dataset.tab === 'tab-screener')  loadScreenerTab();
    if (btn.dataset.tab === 'tab-risk')        loadRiskTab();
    if (btn.dataset.tab === 'tab-financials')  loadFinancialsTab();
  });
});

function renderChartsIfVisible() {
  if (document.getElementById('tab-charts')?.classList.contains('active')) {
    requestAnimationFrame(() => loadCharts(currentDays));
  }
}

// ── Chart: Performance (cota history vs IBOV) ────────────────────
let _perfCache     = null;
let _perfCacheTime = 0;
const PERF_CACHE_TTL = 10 * 60 * 1000; // 10 min

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
    // Re-fetch if cache is missing, stale, or ibov data was empty on last attempt
    const ibovMissing = _perfCache && _perfCache.series?.every(s => s.ibov == null);
    if (!_perfCache || ibovMissing || Date.now() - _perfCacheTime > PERF_CACHE_TTL) {
      const res  = await fetch('/api/performance-chart');
      _perfCache     = await res.json();
      _perfCacheTime = Date.now();
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
  loadAttribution(_attribPeriod);
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
    renderConsistencyTable(_monthlyRetCache);
  } catch(e) {
    loading.textContent = 'ERRO: ' + e.message;
  }
}

// ── Consistência ─────────────────────────────────────────────────
function renderConsistencyTable(monthlyData) {
  const wrap    = document.getElementById('consistency-wrap');
  const loading = document.getElementById('consistency-loading');
  if (!wrap || !loading) return;

  const MNUMS = ['01','02','03','04','05','06','07','08','09','10','11','12'];
  const allMonths = [];
  (monthlyData.years || []).forEach(row => {
    MNUMS.forEach(mn => {
      const v = row.fund_months[mn];
      if (v != null) allMonths.push(v);
    });
  });

  if (!allMonths.length) { loading.textContent = 'SEM DADOS.'; return; }

  const positivos = allMonths.filter(v => v > 0).length;
  const negativos = allMonths.filter(v => v < 0).length;
  const total     = allMonths.length;
  const maior     = Math.max(...allMonths);
  const menor     = Math.min(...allMonths);
  const fmtPct    = v => (v >= 0 ? '+' : '') + fmt(v, 2) + '%';

  wrap.innerHTML = `
    <table class="consistency-table">
      <thead>
        <tr>
          <th>FUNDO</th>
          <th>MESES POSITIVOS</th>
          <th>MESES NEGATIVOS</th>
          <th>MAIOR RETORNO</th>
          <th>MENOR RETORNO</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td class="cons-name">HARBOUR IAT FIF AÇÕES RL</td>
          <td class="cons-val positive">
            ${positivos}
            <span class="cons-sub">${fmt(positivos / total * 100, 2)}%</span>
          </td>
          <td class="cons-val negative">
            ${negativos}
            <span class="cons-sub">${fmt(negativos / total * 100, 2)}%</span>
          </td>
          <td class="cons-val positive">${fmtPct(maior)}</td>
          <td class="cons-val negative">${fmtPct(menor)}</td>
        </tr>
      </tbody>
    </table>`;

  loading.classList.add('hidden');
  wrap.classList.remove('hidden');
}

// ── Export ───────────────────────────────────────────────────────
document.getElementById('btn-export-csv')?.addEventListener('click',   () => { window.location.href = '/api/export/csv'; });
document.getElementById('btn-export-excel')?.addEventListener('click', () => { window.location.href = '/api/export/excel'; });

document.getElementById('btn-export-pdf')?.addEventListener('click', async () => {
  const btn = document.getElementById('btn-export-pdf');
  const original = btn.textContent;
  btn.textContent = 'GERANDO...';
  btn.disabled = true;

  try {
    const el = document.getElementById('tab-charts');
    const canvas = await html2canvas(el, {
      backgroundColor: '#0a0a0a',
      scale: 1.5,
      useCORS: true,
      logging: false,
      ignoreElements: el => el.id === 'btn-export-pdf' || el.closest?.('#btn-export-pdf')
    });

    const { jsPDF } = window.jspdf;
    const imgW = canvas.width;
    const imgH = canvas.height;
    const ratio = imgH / imgW;
    const pageW = 297; // A4 landscape mm
    const pageH = 210;
    const contentW = pageW - 20;
    const contentH = contentW * ratio;

    const orientation = ratio > (pageH / pageW) ? 'portrait' : 'landscape';
    const pdf = new jsPDF({ orientation, unit: 'mm', format: 'a4' });
    const pW = pdf.internal.pageSize.getWidth() - 20;
    const pH = pW * ratio;
    const pagesNeeded = Math.ceil(pH / (pdf.internal.pageSize.getHeight() - 20));

    if (pagesNeeded <= 1) {
      pdf.addImage(canvas.toDataURL('image/jpeg', 0.9), 'JPEG', 10, 10, pW, pH);
    } else {
      // Slice into pages
      const pageHeightPx = canvas.width * ((pdf.internal.pageSize.getHeight() - 20) / pW);
      let yOffset = 0;
      let page = 0;
      while (yOffset < canvas.height) {
        if (page > 0) pdf.addPage();
        const sliceH = Math.min(pageHeightPx, canvas.height - yOffset);
        const sliceCanvas = document.createElement('canvas');
        sliceCanvas.width = canvas.width;
        sliceCanvas.height = sliceH;
        sliceCanvas.getContext('2d').drawImage(canvas, 0, yOffset, canvas.width, sliceH, 0, 0, canvas.width, sliceH);
        const slicePH = pW * (sliceH / canvas.width);
        pdf.addImage(sliceCanvas.toDataURL('image/jpeg', 0.9), 'JPEG', 10, 10, pW, slicePH);
        yOffset += sliceH;
        page++;
      }
    }

    const today = new Date().toISOString().slice(0, 10).replace(/-/g, '');
    pdf.save(`harbour-iat-graficos-${today}.pdf`);
  } catch (err) {
    console.error('PDF export error:', err);
    alert('Erro ao gerar PDF. Tente novamente.');
  } finally {
    btn.textContent = original;
    btn.disabled = false;
  }
});

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
  document.getElementById('edit-lucro').value       = row.lucro_mi_26 ?? '';
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
      lucro_mi_26: document.getElementById('edit-lucro').value,
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
  ['add-ticker','add-quantidade','add-liq','add-lucro','add-preco-alvo'].forEach(id => document.getElementById(id).value='');
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
      lucro_mi_26: document.getElementById('add-lucro').value,
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

// ── Atribuição de Retorno ────────────────────────────────────────
let attribChart = null;
let _attribPeriod = 'day';

document.querySelectorAll('.attrib-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.attrib-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    _attribPeriod = btn.dataset.period;
    loadAttribution(_attribPeriod);
  });
});

async function loadAttribution(period) {
  const loading  = document.getElementById('attrib-loading');
  const canvas   = document.getElementById('attrib-chart');
  const summary  = document.getElementById('attrib-summary');
  const tableWrap = document.getElementById('attrib-table-wrap');
  if (!loading) return;
  loading.classList.remove('hidden');
  loading.textContent = 'CARREGANDO ATRIBUIÇÃO...';
  if (canvas) canvas.style.display = 'none';
  if (summary) summary.classList.add('hidden');
  if (tableWrap) tableWrap.classList.add('hidden');

  try {
    const res  = await fetch(`/api/attribution?period=${period}`);
    const data = await res.json();
    if (data.error) { loading.textContent = 'ERRO: ' + data.error; return; }
    loading.classList.add('hidden');

    const rows   = data.rows || [];
    if (!rows.length) { loading.textContent = 'SEM DADOS.'; loading.classList.remove('hidden'); return; }

    const labels = rows.map(r => r.ticker);
    const values = rows.map(r => r.contribuicao_pct);
    const colors = values.map(v => v > 0 ? 'rgba(0,204,68,0.75)' : v < 0 ? 'rgba(255,51,51,0.75)' : 'rgba(136,136,136,0.5)');
    const borders = values.map(v => v > 0 ? '#00cc44' : v < 0 ? '#ff3333' : '#888');

    canvas.style.display = '';
    if (attribChart) attribChart.destroy();
    attribChart = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'Contribuição %',
          data: values,
          backgroundColor: colors,
          borderColor: borders,
          borderWidth: 1,
          borderRadius: 2,
        }],
      },
      options: {
        responsive: true,
        indexAxis: 'y',
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#0d0d0d', borderColor: '#2a2a2a', borderWidth: 1,
            callbacks: {
              label: ctx => {
                const r = rows[ctx.dataIndex];
                return [`  Contribuição: ${(ctx.parsed.x >= 0 ? '+' : '') + fmt(ctx.parsed.x, 3)}%`,
                        `  Retorno ativo: ${(r.retorno_pct >= 0 ? '+' : '') + fmt(r.retorno_pct, 2)}%`,
                        `  Peso: ${fmt(r.peso_pct, 2)}%`];
              },
            },
          },
        },
        scales: {
          x: { grid: { color: '#1c1c1c' }, ticks: { callback: v => (v >= 0 ? '+' : '') + fmt(v, 2) + '%' } },
          y: { grid: { display: false } },
        },
      },
    });

    // Summary
    const ptotal = data.total_fundo_pct;
    const pibov  = data.ibov_ret_pct;
    const alpha  = data.alpha_pct;
    const PERIOD_LABEL = { day: 'NO DIA', week: 'NA SEMANA', month: 'NO MÊS', ytd: 'NO ANO' };
    if (summary) {
      summary.innerHTML = `
        <span class="attrib-kpi">
          <span class="attrib-kpi-lbl">FUNDO ${PERIOD_LABEL[period] || ''}</span>
          <span class="attrib-kpi-val ${colorCls(ptotal)}">${ptotal != null ? (ptotal >= 0 ? '+' : '') + fmt(ptotal, 2) + '%' : '—'}</span>
        </span>
        <span class="attrib-sep">│</span>
        <span class="attrib-kpi">
          <span class="attrib-kpi-lbl">IBOV</span>
          <span class="attrib-kpi-val ${colorCls(pibov)}">${pibov != null ? (pibov >= 0 ? '+' : '') + fmt(pibov, 2) + '%' : '—'}</span>
        </span>
        <span class="attrib-sep">│</span>
        <span class="attrib-kpi">
          <span class="attrib-kpi-lbl">ALPHA</span>
          <span class="attrib-kpi-val ${colorCls(alpha)}">${alpha != null ? (alpha >= 0 ? '+' : '') + fmt(alpha, 2) + '%' : '—'}</span>
        </span>`;
      summary.classList.remove('hidden');
    }

    // Table
    if (tableWrap) {
      let th = `<table class="attrib-table"><thead><tr>
        <th>ATIVO</th><th class="num">RETORNO %</th><th class="num">PESO %</th>
        <th class="num">CONTRIB. %</th><th class="num">CONTRIB. BPS</th></tr></thead><tbody>`;
      rows.forEach(r => {
        th += `<tr>
          <td class="ticker-cell">${r.ticker}</td>
          <td class="num ${colorCls(r.retorno_pct)}">${(r.retorno_pct >= 0 ? '+' : '') + fmt(r.retorno_pct, 2)}%</td>
          <td class="num">${fmt(r.peso_pct, 2)}%</td>
          <td class="num ${colorCls(r.contribuicao_pct)}">${(r.contribuicao_pct >= 0 ? '+' : '') + fmt(r.contribuicao_pct, 3)}%</td>
          <td class="num ${colorCls(r.contribuicao_bps)}">${(r.contribuicao_bps >= 0 ? '+' : '') + fmt(r.contribuicao_bps, 1)}</td>
        </tr>`;
      });
      th += `<tr class="weighted-row"><td colspan="3" class="weighted-label">TOTAL FUNDO</td>
        <td class="num ${colorCls(ptotal)}">${ptotal != null ? (ptotal >= 0 ? '+' : '') + fmt(ptotal, 3) + '%' : '—'}</td>
        <td class="num ${colorCls(ptotal)}">${ptotal != null ? (ptotal >= 0 ? '+' : '') + fmt(ptotal * 100, 1) : '—'}</td></tr>`;
      th += '</tbody></table>';
      tableWrap.innerHTML = th;
      tableWrap.classList.remove('hidden');
    }
  } catch(e) {
    if (loading) { loading.textContent = 'ERRO: ' + e.message; loading.classList.remove('hidden'); }
  }
}

// ── Macro Dashboard ──────────────────────────────────────────────
let _macroCache = null;
const _macroSparklines = {};

async function loadMacroTab() {
  if (_macroCache) { renderMacro(_macroCache); return; }
  const loading = document.getElementById('macro-loading');
  if (loading) { loading.classList.remove('hidden'); loading.textContent = 'CARREGANDO DADOS MACRO...'; }
  try {
    const res  = await fetch('/api/macro');
    _macroCache = await res.json();
    renderMacro(_macroCache);
  } catch(e) {
    if (loading) loading.textContent = 'ERRO: ' + e.message;
  }
}

function renderMacro(data) {
  const grid    = document.getElementById('macro-cards-grid');
  const loading = document.getElementById('macro-loading');
  if (!grid) return;
  if (loading) loading.classList.add('hidden');

  const SECTIONS = [
    {
      title: 'POLÍTICA MONETÁRIA',
      cards: [
        { key: 'selic_meta',  label: 'SELIC META',  type: 'realized', suffix: '%', decimals: 2, color: '#ff8c00' },
        { key: 'selic_focus', label: 'SELIC FOCUS', type: 'focus',    suffix: '%', decimals: 2 },
        { key: 'cdi_ytd',     label: 'CDI ANO',     type: 'simple',   suffix: '%', decimals: 2 },
      ],
    },
    {
      title: 'INFLAÇÃO',
      cards: [
        { key: 'ipca_12m',      label: 'IPCA 12M',      type: 'realized', suffix: '%', decimals: 2, color: '#ffcc00' },
        { key: 'ipca_focus',    label: 'IPCA FOCUS',    type: 'focus',    suffix: '%', decimals: 2 },
        { key: 'ipca_servicos', label: 'IPCA SERVIÇOS', type: 'realized', suffix: '%', decimals: 2, color: '#ffaa44' },
      ],
    },
    {
      title: 'CÂMBIO & ATIVIDADE',
      cards: [
        { key: 'usdbrl',       label: 'USD/BRL',      type: 'realized', suffix: '',  decimals: 4, color: '#00aacc' },
        { key: 'usdbrl_focus', label: 'USD FOCUS',    type: 'focus',    suffix: '',  decimals: 2 },
        { key: 'pib_focus',    label: 'PIB FOCUS',    type: 'focus',    suffix: '%', decimals: 1 },
        { key: 'divida_bruta', label: 'DÍVIDA/PIB',   type: 'realized', suffix: '%', decimals: 1, color: '#cc4444' },
        { key: 'balanca',      label: 'BALANÇA COM.', type: 'realized', suffix: '',  decimals: 0, color: '#44cc88' },
      ],
    },
    {
      title: 'MERCADOS EXTERNOS',
      cards: [
        { key: 'brent', label: 'BRENT (USD)', type: 'realized', suffix: '', decimals: 2, color: '#888888' },
        { key: 'sp500', label: 'S&P 500',     type: 'realized', suffix: '', decimals: 0, color: '#ff4488' },
      ],
    },
  ];

  // Destroy existing sparklines
  Object.keys(_macroSparklines).forEach(id => {
    if (_macroSparklines[id]) { _macroSparklines[id].destroy(); delete _macroSparklines[id]; }
  });
  grid.innerHTML = '';

  // Helper: build a "realized" card (current value + var_pct + sparkline)
  function buildRealizedCard(card, d) {
    const div = document.createElement('div');
    div.className = 'macro-card';
    const canvasId = `macro-spark-${card.key}`;
    const val    = d.valor;
    const varPct = d.var_pct != null ? d.var_pct : null;
    div.innerHTML = `
      <div class="macro-card-label">${card.label}</div>
      <div class="macro-card-value">${val != null ? fmt(val, card.decimals) + card.suffix : '—'}</div>
      <div class="macro-card-change ${colorCls(varPct)}">
        ${varPct != null ? (varPct >= 0 ? '▲' : '▼') + ' ' + fmt(Math.abs(varPct), 2) + '%' : ''}
      </div>
      <canvas id="${canvasId}" class="macro-spark" height="40"></canvas>`;
    if (d.hist && d.hist.length) {
      requestAnimationFrame(() => {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;
        _macroSparklines[canvasId] = new Chart(canvas.getContext('2d'), {
          type: 'line',
          data: {
            labels: d.hist.map(h => h.data),
            datasets: [{ data: d.hist.map(h => h.valor), borderColor: card.color,
              borderWidth: 1.5, pointRadius: 0, tension: 0.2, fill: false }],
          },
          options: {
            responsive: false, animation: false,
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            scales: { x: { display: false }, y: { display: false } },
          },
        });
      });
    }
    return div;
  }

  // Helper: build a "focus" card (two rows: ano atual + próximo, mediana + faixa)
  function buildFocusCard(card, d) {
    const div = document.createElement('div');
    div.className = 'macro-card macro-card-focus';
    const anos = Object.keys(d).sort();
    let rowsHtml = '';
    anos.forEach(ano => {
      const f = d[ano];
      const med = f.mediana != null ? fmt(f.mediana, card.decimals) + card.suffix : '—';
      const range = (f.minimo != null && f.maximo != null)
        ? `${fmt(f.minimo, card.decimals)}–${fmt(f.maximo, card.decimals)}${card.suffix}`
        : '';
      rowsHtml += `<div class="macro-focus-row">
        <span class="macro-focus-year">${ano}</span>
        <span class="macro-focus-med">${med}</span>
        ${range ? `<span class="macro-focus-range"> (${range})</span>` : ''}
      </div>`;
    });
    div.innerHTML = `
      <div class="macro-card-label">${card.label}</div>
      <div class="macro-focus-body">${rowsHtml || '<span class="macro-focus-range">—</span>'}</div>`;
    return div;
  }

  // Helper: build a "simple" card (just value, no var_pct, no sparkline)
  function buildSimpleCard(card, d) {
    const div = document.createElement('div');
    div.className = 'macro-card';
    const val = d.valor;
    div.innerHTML = `
      <div class="macro-card-label">${card.label}</div>
      <div class="macro-card-value">${val != null ? fmt(val, card.decimals) + card.suffix : '—'}</div>`;
    return div;
  }

  SECTIONS.forEach(section => {
    // Filter to cards that have data
    const visibleCards = section.cards.filter(c => data[c.key] != null);
    if (!visibleCards.length) return;

    const sectionEl = document.createElement('div');
    sectionEl.className = 'macro-section';
    sectionEl.innerHTML = `<div class="macro-section-title">${section.title}</div>`;

    const sectionGrid = document.createElement('div');
    sectionGrid.className = 'macro-grid';

    visibleCards.forEach(card => {
      const d = data[card.key];
      let cardEl;
      if (card.type === 'focus')    cardEl = buildFocusCard(card, d);
      else if (card.type === 'simple') cardEl = buildSimpleCard(card, d);
      else                          cardEl = buildRealizedCard(card, d);
      sectionGrid.appendChild(cardEl);
    });

    sectionEl.appendChild(sectionGrid);
    grid.appendChild(sectionEl);
  });
}

// ── Watchlist ────────────────────────────────────────────────────
let _wlEditingTicker = null;

async function loadWatchlistTab() {
  await renderWatchlistTable();
}

async function renderWatchlistTable() {
  const tbody = document.getElementById('watchlist-body');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="18" class="empty-state">CARREGANDO...</td></tr>';
  try {
    const res  = await fetch('/api/watchlist');
    const data = await res.json();
    const rows = data.rows || [];
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="18" class="empty-state">WATCHLIST VAZIA — ADICIONE ATIVOS PARA ACOMPANHAR.</td></tr>';
      return;
    }
    tbody.innerHTML = '';
    rows.forEach(row => {
      const statusCls = row.status === 'Em análise' ? 'wl-status-analise'
                      : row.status === 'Monitorando' ? 'wl-status-monitor'
                      : 'wl-status-descartado';
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="ticker-cell">${row.ticker}${row.short_name ? `<span class="name-sub">${row.short_name}</span>` : ''}</td>
        <td>${row.categoria || '—'}</td>
        <td><span class="wl-status ${statusCls}">${row.status || '—'}</span></td>
        <td>${row.sector || '—'}</td>
        <td class="num">${fmtBRL(row.preco)}</td>
        <td class="num ${colorCls(row.var_dia_pct)}">${row.var_dia_pct != null ? sign(row.var_dia_pct) + fmt(row.var_dia_pct, 2) + '%' : '—'}</td>
        <td class="num">${fmt(row.trailing_pe, 1)}</td>
        <td class="num">${fmt(row.forward_pe, 1)}</td>
        <td class="num">${fmt(row.enterprise_to_ebitda, 1)}</td>
        <td class="num ${colorCls(row.return_on_equity)}">${row.return_on_equity != null ? fmt(row.return_on_equity, 1) + '%' : '—'}</td>
        <td class="num">${fmt(row.price_to_book, 1)}</td>
        <td class="num">${row.dividend_yield != null ? fmt(row.dividend_yield, 2) + '%' : '—'}</td>
        <td class="num">${row.market_cap_bi != null ? 'R$' + fmt(row.market_cap_bi, 1) + 'B' : '—'}</td>
        <td class="num">${fmtBRL(row.preco_alvo)}</td>
        <td class="num ${upsideCls(row.upside_pct)}">${row.upside_pct != null ? sign(row.upside_pct) + fmt(row.upside_pct, 2) + '%' : '—'}</td>
        <td class="wl-gatilho" title="${row.gatilho || ''}">${row.gatilho || '—'}</td>
        <td class="wl-tese" title="${row.tese || ''}">${row.tese ? row.tese.slice(0, 40) + (row.tese.length > 40 ? '...' : '') : '—'}</td>
        <td>${window.USER_ROLE === 'admin' ? '<button class="btn-edit wl-edit-btn" title="Editar">✎</button>' : ''}</td>`;
      const editBtn = tr.querySelector('.wl-edit-btn');
      if (editBtn) editBtn.addEventListener('click', () => openWlEditModal(row));
      tbody.appendChild(tr);
    });
  } catch(e) {
    tbody.innerHTML = `<tr><td colspan="18" class="empty-state">ERRO: ${e.message}</td></tr>`;
  }
}

// Watchlist — Add modal
document.getElementById('btn-add-watchlist')?.addEventListener('click', () => {
  ['wl-ticker','wl-preco-alvo','wl-gatilho','wl-tese'].forEach(id => { const el = document.getElementById(id); if(el) el.value = ''; });
  document.getElementById('wl-add-error')?.classList.add('hidden');
  document.getElementById('wl-status').value = 'Em análise';
  document.getElementById('wl-add-modal')?.classList.remove('hidden');
});
const closeWlAddModal = () => document.getElementById('wl-add-modal')?.classList.add('hidden');
document.getElementById('wl-modal-close')?.addEventListener('click', closeWlAddModal);
document.getElementById('wl-modal-cancel')?.addEventListener('click', closeWlAddModal);
document.getElementById('wl-add-modal')?.addEventListener('click', e => { if(e.target === document.getElementById('wl-add-modal')) closeWlAddModal(); });

document.getElementById('wl-modal-save')?.addEventListener('click', async () => {
  const ticker = document.getElementById('wl-ticker')?.value.trim().toUpperCase();
  if (!ticker) { showWlAddError('TICKER OBRIGATÓRIO.'); return; }
  const btn = document.getElementById('wl-modal-save');
  btn.disabled = true; btn.textContent = 'VERIFICANDO...';
  const res = await fetch('/api/watchlist/add', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      ticker,
      categoria:    document.getElementById('wl-categoria')?.value,
      status:       document.getElementById('wl-status')?.value,
      preco_alvo:   document.getElementById('wl-preco-alvo')?.value,
      gatilho:      document.getElementById('wl-gatilho')?.value,
      tese:         document.getElementById('wl-tese')?.value,
    }),
  });
  btn.disabled = false; btn.textContent = 'ADICIONAR';
  if (res.ok) { closeWlAddModal(); await renderWatchlistTable(); }
  else { const err = await res.json(); showWlAddError(err.error || 'ERRO.'); }
});
function showWlAddError(msg) {
  const el = document.getElementById('wl-add-error');
  if (el) { el.textContent = msg; el.classList.remove('hidden'); }
}

// Watchlist — Edit modal
function openWlEditModal(row) {
  _wlEditingTicker = row.ticker;
  document.getElementById('wl-edit-ticker-label').textContent = row.ticker;
  document.getElementById('wl-edit-status').value     = row.status || 'Em análise';
  document.getElementById('wl-edit-preco-alvo').value = row.preco_alvo ?? '';
  document.getElementById('wl-edit-gatilho').value    = row.gatilho || '';
  document.getElementById('wl-edit-tese').value       = row.tese || '';
  document.getElementById('wl-edit-modal')?.classList.remove('hidden');
}
const closeWlEditModal = () => { document.getElementById('wl-edit-modal')?.classList.add('hidden'); _wlEditingTicker = null; };
document.getElementById('wl-edit-close')?.addEventListener('click', closeWlEditModal);
document.getElementById('wl-edit-cancel')?.addEventListener('click', closeWlEditModal);
document.getElementById('wl-edit-modal')?.addEventListener('click', e => { if(e.target === document.getElementById('wl-edit-modal')) closeWlEditModal(); });

document.getElementById('wl-edit-save')?.addEventListener('click', async () => {
  if (!_wlEditingTicker) return;
  const res = await fetch('/api/watchlist/update', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      ticker:     _wlEditingTicker,
      status:     document.getElementById('wl-edit-status')?.value,
      preco_alvo: document.getElementById('wl-edit-preco-alvo')?.value,
      gatilho:    document.getElementById('wl-edit-gatilho')?.value,
      tese:       document.getElementById('wl-edit-tese')?.value,
    }),
  });
  if (res.ok) { closeWlEditModal(); await renderWatchlistTable(); }
  else alert('ERRO AO SALVAR.');
});
document.getElementById('wl-edit-delete')?.addEventListener('click', async () => {
  if (!_wlEditingTicker || !confirm(`REMOVER ${_wlEditingTicker} DA WATCHLIST?`)) return;
  const res = await fetch(`/api/watchlist/${_wlEditingTicker}`, { method: 'DELETE' });
  if (res.ok) { closeWlEditModal(); await renderWatchlistTable(); }
  else alert('ERRO AO REMOVER.');
});

// ── Screener B3 ──────────────────────────────────────────────────
let _screenerUniverso = 'ibov';
let _screenerLoaded = false;

document.getElementById('btn-screener-filter')?.addEventListener('click', () => loadScreenerTab());
document.getElementById('btn-screener-clear')?.addEventListener('click', () => {
  ['flt-pl-max','flt-pl-min','flt-roe-min','flt-dy-min','flt-ev-max','flt-beta-min','flt-beta-max'].forEach(id => {
    const el = document.getElementById(id); if(el) el.value = '';
  });
  const sel = document.getElementById('flt-setor'); if(sel) sel.value = '';
  loadScreenerTab();
});

async function loadScreenerTab(isPoll = false) {
  const tbody  = document.getElementById('screener-body');
  const status = document.getElementById('screener-status');
  if (!tbody) return;

  // Preserve scroll position — chart destroy/recreate causes browser to jump to top
  const savedScroll = window.scrollY;

  if (!isPoll) {
    tbody.innerHTML = '<tr><td colspan="13" class="empty-state">CARREGANDO SCREENER...</td></tr>';
  }

  const params = new URLSearchParams({ universo: _screenerUniverso });
  const ids = [
    ['pl_max','flt-pl-max'],['pl_min','flt-pl-min'],['roe_min','flt-roe-min'],
    ['dy_min','flt-dy-min'],['evebitda_max','flt-ev-max'],
    ['beta_min','flt-beta-min'],['beta_max','flt-beta-max'],
  ];
  ids.forEach(([k, id]) => {
    const v = document.getElementById(id)?.value;
    if (v) params.set(k, v);
  });
  const setor = document.getElementById('flt-setor')?.value;
  if (setor) params.set('setor', setor);

  try {
    const res  = await fetch('/api/screener?' + params.toString());
    const data = await res.json();
    const rows = data.rows || [];

    // Update loading status
    if (status) {
      if (data.loading) {
        status.textContent = `⏳ CARREGANDO ${data.loaded}/${data.total} ATIVOS...`;
        // Only continue polling if the screener tab is still visible
        if (document.getElementById('tab-screener')?.classList.contains('active')) {
          setTimeout(() => loadScreenerTab(true), 3000);
        }
      } else {
        status.textContent = `${rows.length} ATIVOS ENCONTRADOS`;
        _screenerLoaded = true;
      }
    }

    // Populate sector filter dropdown
    const setores = [...new Set(rows.map(r => r.sector).filter(Boolean))].sort();
    const selSetor = document.getElementById('flt-setor');
    if (selSetor) {
      const cur = selSetor.value;
      selSetor.innerHTML = '<option value="">Todos</option>' + setores.map(s => `<option value="${s}">${s}</option>`).join('');
      if (cur) selSetor.value = cur;
    }

    // Render table
    if (!rows.length && !data.loading) {
      tbody.innerHTML = '<tr><td colspan="13" class="empty-state">NENHUM ATIVO ENCONTRADO COM OS FILTROS APLICADOS.</td></tr>';
      window.scrollTo(0, savedScroll);
      return;
    }
    if (!rows.length) {
      if (!isPoll) tbody.innerHTML = '<tr><td colspan="13" class="empty-state">AGUARDANDO DADOS DO SCREENER...</td></tr>';
      window.scrollTo(0, savedScroll);
      return;
    }

    tbody.innerHTML = '';
    rows.forEach(row => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="ticker-cell">${row.ticker}${row.short_name ? `<span class="name-sub">${row.short_name}</span>` : ''}</td>
        <td>${row.sector || '—'}</td>
        <td class="num">${fmtBRL(row.preco)}</td>
        <td class="num ${colorCls(row.var_dia_pct)}">${row.var_dia_pct != null ? sign(row.var_dia_pct) + fmt(row.var_dia_pct, 2) + '%' : '—'}</td>
        <td class="num">${fmt(row.trailing_pe, 1)}</td>
        <td class="num">${fmt(row.forward_pe, 1)}</td>
        <td class="num">${fmt(row.enterprise_to_ebitda, 1)}</td>
        <td class="num ${colorCls(row.return_on_equity)}">${row.return_on_equity != null ? fmt(row.return_on_equity, 1) + '%' : '—'}</td>
        <td class="num">${fmt(row.price_to_book, 1)}</td>
        <td class="num">${row.dividend_yield != null ? fmt(row.dividend_yield, 2) + '%' : '—'}</td>
        <td class="num">${fmt(row.beta, 2)}</td>
        <td class="num">${row.market_cap_bi != null ? 'R$' + fmt(row.market_cap_bi, 1) + 'B' : '—'}</td>
        <td>${window.USER_ROLE === 'admin' ? `<button class="btn-edit wl-quick-add" data-ticker="${row.ticker}" title="Add Watchlist">+WL</button>` : ''}</td>`;
      const wlBtn = tr.querySelector('.wl-quick-add');
      if (wlBtn) wlBtn.addEventListener('click', () => quickAddToWatchlist(row.ticker));
      tbody.appendChild(tr);
    });
    // Restore scroll after DOM updates to prevent page jumping to top
    requestAnimationFrame(() => window.scrollTo(0, savedScroll));
  } catch(e) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="13" class="empty-state">ERRO: ${e.message}</td></tr>`;
  }
}

async function quickAddToWatchlist(ticker) {
  const res = await fetch('/api/watchlist/add', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ticker, status: 'Em análise' }),
  });
  const btn = document.querySelector(`.wl-quick-add[data-ticker="${ticker}"]`);
  if (res.ok) { if(btn) { btn.textContent = '✔'; btn.disabled = true; btn.style.color = '#00cc44'; } }
  else { const err = await res.json(); alert(err.error || 'ERRO.'); }
}

// ── Init ─────────────────────────────────────────────────────────
(async () => {
  await fetchPortfolio();
  startRefreshCycle();
})();

// ══════════════════════════════════════════════════════════════════
// 207) RISCO
// ══════════════════════════════════════════════════════════════════

let _riskBetaChart         = null;
let _riskRollingRatiosChart = null;
let _riskDistChart          = null;
let _riskLoaded    = false;

// ── State for active selections ───────────────────────────────────
let _riskVarWindow  = 252;
let _riskVarHorizon = 1;
let _riskStress     = 'covid';
let _riskCorrWindow = 60;
let _riskAttrWindow = 60;
let _riskTeWindow   = 252;
let _riskCapWindow  = '252';
let _riskRollWindow = 63;
let _riskDistWindow = 252;

async function loadRiskTab() {
  if (_riskLoaded) return;
  _riskLoaded = true;
  _setupRiskControls();
  await Promise.all([
    _loadVaR(),
    _loadStress('covid'),
    _loadCorrelation(60),
    _loadAttribution(60),
    _loadRollingBeta(),
    _loadLiquidity(),
    _loadTrackingError(),
    _loadSortinoCal(),
    _loadCapture(),
    _loadConcentration(),
    _loadFxExposure(),
    _loadRollingRatios(),
    _loadReturnDist(),
  ]);
}

function _setupRiskControls() {
  // VaR window
  document.querySelectorAll('[data-var-window]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-var-window]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      _riskVarWindow = parseInt(btn.dataset.varWindow);
      _loadVaR();
    });
  });
  // VaR horizon
  document.querySelectorAll('[data-var-horizon]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-var-horizon]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      _riskVarHorizon = parseInt(btn.dataset.varHorizon);
      _renderVaRHorizon();
    });
  });
  // Stress scenario buttons
  document.querySelectorAll('[data-stress]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-stress]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const sc = btn.dataset.stress;
      const customBox = document.getElementById('risk-stress-custom');
      if (sc === 'custom') {
        customBox.style.display = 'flex';
      } else {
        customBox.style.display = 'none';
        _riskStress = sc;
        _loadStress(sc);
      }
    });
  });
  // Custom stress run
  document.getElementById('btn-stress-custom-run')?.addEventListener('click', () => {
    const ibov = document.getElementById('stress-ibov-input')?.value;
    const brl  = document.getElementById('stress-brl-input')?.value || 0;
    if (!ibov) return;
    _loadStress('custom', parseFloat(ibov), parseFloat(brl));
  });
  // Correlation window
  document.querySelectorAll('[data-corr-window]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-corr-window]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      _riskCorrWindow = parseInt(btn.dataset.corrWindow);
      _loadCorrelation(_riskCorrWindow);
    });
  });
  // Attribution window
  document.querySelectorAll('[data-attr-window]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-attr-window]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      _riskAttrWindow = parseInt(btn.dataset.attrWindow);
      _loadAttribution(_riskAttrWindow);
    });
  });
  // Tracking Error window
  document.querySelectorAll('[data-te-window]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-te-window]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      _riskTeWindow = parseInt(btn.dataset.teWindow);
      _loadTrackingError();
    });
  });
  // Capture window
  document.querySelectorAll('[data-cap-window]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-cap-window]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      _riskCapWindow = btn.dataset.capWindow;
      _loadCapture();
    });
  });
  // Rolling ratios window
  document.querySelectorAll('[data-roll-window]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-roll-window]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      _riskRollWindow = parseInt(btn.dataset.rollWindow);
      _loadRollingRatios();
    });
  });
  // Distribution window
  document.querySelectorAll('[data-dist-window]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-dist-window]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      _riskDistWindow = parseInt(btn.dataset.distWindow);
      _loadReturnDist();
    });
  });
}

// ── VaR ──────────────────────────────────────────────────────────
let _varCache = {};

async function _loadVaR() {
  const el = document.getElementById('risk-var-content');
  if (!el) return;
  const key = _riskVarWindow;
  if (!_varCache[key]) {
    el.innerHTML = '<div class="risk-loading">CARREGANDO VaR...</div>';
    try {
      const r = await fetch(`/api/risk/var?window=${_riskVarWindow}`);
      _varCache[key] = await r.json();
    } catch(e) {
      el.innerHTML = `<div class="risk-error">ERRO: ${e.message}</div>`;
      return;
    }
  }
  _renderVaR(_varCache[key], el);
}

function _renderVaRHorizon() {
  const el = document.getElementById('risk-var-content');
  const d  = _varCache[_riskVarWindow];
  if (el && d) _renderVaR(d, el);
}

function _renderVaR(d, el) {
  if (d.error) { el.innerHTML = `<div class="risk-error">${d.error}</div>`; return; }
  const h = _riskVarHorizon;
  const sfx = h === 10 ? '10d' : '1d';

  el.innerHTML = `
    <div class="risk-var-grid">
      <div class="risk-metric-block">
        <div class="risk-metric-label">VaR 95% ${h}D</div>
        <div class="risk-metric-val negative">-${fmt(d[`var_95_${sfx}_pct`],2)}%</div>
        <div class="risk-metric-sub">${fmtBRL(d[`var_95_${sfx}_rs`])}</div>
      </div>
      <div class="risk-metric-block">
        <div class="risk-metric-label">VaR 99% ${h}D</div>
        <div class="risk-metric-val negative">-${fmt(d[`var_99_${sfx}_pct`],2)}%</div>
        <div class="risk-metric-sub">${fmtBRL(d[`var_99_${sfx}_rs`])}</div>
      </div>
      <div class="risk-metric-block">
        <div class="risk-metric-label">CVaR 95% ${h}D</div>
        <div class="risk-metric-val negative">-${fmt(d[`cvar_95_${sfx}_pct`],2)}%</div>
        <div class="risk-metric-sub">${fmtBRL(d[`cvar_95_${sfx}_rs`])}</div>
      </div>
      <div class="risk-metric-block">
        <div class="risk-metric-label">CVaR 99% ${h}D</div>
        <div class="risk-metric-val negative">-${fmt(d[`cvar_99_${sfx}_pct`],2)}%</div>
        <div class="risk-metric-sub">${fmtBRL(d[`cvar_99_${sfx}_rs`])}</div>
      </div>
    </div>
    <div class="risk-dist-row">
      <span>MÉDIA/DIA: <b class="${colorCls(d.return_distribution?.mean_pct)}">${sign(d.return_distribution?.mean_pct)}${fmt(d.return_distribution?.mean_pct,3)}%</b></span>
      <span>MELHOR DIA: <b class="positive">+${fmt(d.return_distribution?.best_day,2)}%</b></span>
      <span>PIOR DIA: <b class="negative">${fmt(d.return_distribution?.worst_day,2)}%</b></span>
      <span>DIAS POSITIVOS: <b>${fmt(d.return_distribution?.positive_days_pct,1)}%</b></span>
      <span class="dim">BASE: ${d.n_obs} obs | NAV: ${fmtBRL(d.nav_ref)}</span>
    </div>
    ${_renderComponentVarTable(d.component_var)}
  `;
}

function _renderComponentVarTable(rows) {
  if (!rows || !rows.length) return '';
  return `
    <div class="risk-table-title">COMPONENT VaR POR ATIVO (approx. por beta)</div>
    <div class="table-wrapper" style="max-height:180px;overflow-y:auto">
    <table class="risk-table">
      <thead><tr><th>ATIVO</th><th class="num">PESO%</th><th class="num">BETA</th><th class="num">CONTRIB. RISCO%</th><th class="num">VaR 1D R$</th></tr></thead>
      <tbody>
        ${rows.map(r => `
          <tr>
            <td class="ticker-cell">${r.ticker}</td>
            <td class="num">${fmt(r.weight_pct,1)}%</td>
            <td class="num">${fmt(r.beta,2)}</td>
            <td class="num"><div class="risk-bar-cell"><div class="risk-bar" style="width:${Math.min(100,r.contrib_pct)}%"></div><span>${fmt(r.contrib_pct,1)}%</span></div></td>
            <td class="num negative">${fmtBRL(r.var_1d_rs)}</td>
          </tr>`).join('')}
      </tbody>
    </table>
    </div>
  `;
}

// ── Stress Test ───────────────────────────────────────────────────
let _stressCache = {};

async function _loadStress(scenario, ibovShock, brlShock) {
  const el = document.getElementById('risk-stress-content');
  if (!el) return;
  let url = `/api/risk/stress?scenario=${scenario}`;
  if (scenario === 'custom') {
    url = `/api/risk/stress?ibov_shock=${ibovShock}&brl_shock=${brlShock || 0}`;
  }
  const cacheKey = scenario === 'custom' ? `custom_${ibovShock}_${brlShock}` : scenario;
  if (!_stressCache[cacheKey]) {
    el.innerHTML = '<div class="risk-loading">SIMULANDO CENÁRIO...</div>';
    try {
      const r = await fetch(url);
      _stressCache[cacheKey] = await r.json();
    } catch(e) {
      el.innerHTML = `<div class="risk-error">ERRO: ${e.message}</div>`;
      return;
    }
  }
  _renderStress(_stressCache[cacheKey], el);
}

function _renderStress(d, el) {
  if (d.error) { el.innerHTML = `<div class="risk-error">${d.error}</div>`; return; }
  const impCls = d.portfolio_impact_pct < 0 ? 'negative' : 'positive';
  el.innerHTML = `
    <div class="risk-stress-header">
      <div class="risk-metric-block">
        <div class="risk-metric-label">${d.label}</div>
        <div class="risk-metric-sub dim">${d.description}</div>
      </div>
      <div class="risk-metric-block">
        <div class="risk-metric-label">IMPACTO PORTFÓLIO</div>
        <div class="risk-metric-val ${impCls}">${sign(d.portfolio_impact_pct)}${fmt(d.portfolio_impact_pct,2)}%</div>
        <div class="risk-metric-sub ${impCls}">${sign(d.portfolio_impact_rs)}${fmtBRL(d.portfolio_impact_rs)}</div>
      </div>
      <div class="risk-metric-block">
        <div class="risk-metric-label">CHOQUE IBOV</div>
        <div class="risk-metric-val negative">${sign(d.ibov_shock_pct)}${fmt(d.ibov_shock_pct,1)}%</div>
      </div>
      <div class="risk-metric-block">
        <div class="risk-metric-label">CHOQUE BRL</div>
        <div class="risk-metric-val ${d.brl_shock_pct >= 0 ? 'negative' : 'positive'}">${sign(d.brl_shock_pct)}${fmt(d.brl_shock_pct,1)}%</div>
      </div>
    </div>
    <div class="table-wrapper" style="max-height:200px;overflow-y:auto">
    <table class="risk-table">
      <thead><tr><th>ATIVO</th><th>CATEG.</th><th class="num">PESO%</th><th class="num">BETA</th><th class="num">IMPACTO%</th><th class="num">IMPACTO R$</th></tr></thead>
      <tbody>
        ${d.positions.map(r => {
          const cls = r.impact_pct < 0 ? 'negative' : 'positive';
          return `<tr>
            <td class="ticker-cell">${r.ticker}</td>
            <td>${r.categoria || '—'}</td>
            <td class="num">${fmt(r.weight_pct,1)}%</td>
            <td class="num">${fmt(r.beta,2)}</td>
            <td class="num ${cls}">${sign(r.impact_pct)}${fmt(r.impact_pct,2)}%</td>
            <td class="num ${cls}">${sign(r.impact_rs)}${fmtBRL(r.impact_rs)}</td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>
    </div>
  `;
}

// ── Correlation Matrix ────────────────────────────────────────────
let _corrCache = {};

async function _loadCorrelation(window) {
  const el = document.getElementById('risk-corr-content');
  if (!el) return;
  if (!_corrCache[window]) {
    el.innerHTML = '<div class="risk-loading">CARREGANDO CORRELAÇÕES...</div>';
    try {
      const r = await fetch(`/api/risk/correlation?window=${window}`);
      _corrCache[window] = await r.json();
    } catch(e) {
      el.innerHTML = `<div class="risk-error">ERRO: ${e.message}</div>`;
      return;
    }
  }
  _renderCorrelation(_corrCache[window], el);
}

function _renderCorrelation(d, el) {
  if (d.error) { el.innerHTML = `<div class="risk-error">${d.error}</div>`; return; }
  const { labels, matrix } = d;
  const n = labels.length;
  const cellSz = Math.max(32, Math.min(52, Math.floor(480 / n)));

  let html = `<div class="risk-corr-info dim">Janela: ${d.n_obs} observações</div>
    <div style="overflow-x:auto"><table class="risk-corr-table" style="border-spacing:2px">
    <thead><tr><th></th>${labels.map(l => `<th class="corr-lbl">${l}</th>`).join('')}</tr></thead><tbody>`;

  for (let i = 0; i < n; i++) {
    html += `<tr><td class="corr-lbl">${labels[i]}</td>`;
    for (let j = 0; j < n; j++) {
      const v = matrix[i][j];
      const bg = _corrColor(v);
      const text = v != null ? fmt(v, 2) : '—';
      const isDiag = i === j;
      html += `<td class="corr-cell${isDiag ? ' corr-diag' : ''}" style="background:${bg};width:${cellSz}px;height:${cellSz}px;font-size:${cellSz > 40 ? 10 : 9}px" title="${labels[i]} / ${labels[j]}: ${text}">${text}</td>`;
    }
    html += '</tr>';
  }
  html += '</tbody></table></div>';

  // Legend
  html += `<div class="corr-legend">
    <span>−1.0</span>
    <div class="corr-legend-bar"></div>
    <span>+1.0</span>
    <span class="dim" style="margin-left:12px">■ azul = negativo  ■ cinza = neutro  ■ laranja = positivo</span>
  </div>`;

  el.innerHTML = html;
}

function _corrColor(v) {
  if (v == null) return '#1c1c1c';
  if (v >= 0.999) return '#2a2a2a'; // diagonal
  if (v > 0) {
    const t = Math.min(v, 1);
    const r = Math.round(255 * 0.35 + 120 * t);
    const g = Math.round(100 + 40 * (1 - t));
    const b = Math.round(0);
    return `rgba(${r},${g},${b},0.85)`;
  } else {
    const t = Math.min(Math.abs(v), 1);
    const r = Math.round(0);
    const g = Math.round(100 + 100 * (1 - t));
    const b = Math.round(180 + 75 * t);
    return `rgba(${r},${g},${b},0.8)`;
  }
}

// ── Risk Attribution ──────────────────────────────────────────────
let _attrCache = {};

async function _loadAttribution(window) {
  const el = document.getElementById('risk-attr-content');
  if (!el) return;
  if (!_attrCache[window]) {
    el.innerHTML = '<div class="risk-loading">CARREGANDO ATTRIBUTION...</div>';
    try {
      const r = await fetch(`/api/risk/attribution?window=${window}`);
      _attrCache[window] = await r.json();
    } catch(e) {
      el.innerHTML = `<div class="risk-error">ERRO: ${e.message}</div>`;
      return;
    }
  }
  _renderAttribution(_attrCache[window], el);
}

function _renderAttribution(d, el) {
  if (d.error) { el.innerHTML = `<div class="risk-error">${d.error}</div>`; return; }
  el.innerHTML = `
    <div class="risk-dist-row">
      <span>VOL. ANUALIZADA PORTFÓLIO: <b class="bbg-orange">${fmt(d.portfolio_vol_pct,2)}%</b></span>
      <span class="dim">Janela: ${d.n_obs} obs</span>
    </div>
    <div class="table-wrapper" style="max-height:300px;overflow-y:auto">
    <table class="risk-table">
      <thead><tr>
        <th>ATIVO</th><th class="num">PESO%</th>
        <th class="num">VOL. IND. (ann)</th>
        <th class="num">CORR. PORTF.</th>
        <th class="num">CONTRIB. RISCO%</th>
        <th class="num">CONTRIB. VOL (pp)</th>
      </tr></thead>
      <tbody>
        ${d.rows.map(r => `
          <tr>
            <td class="ticker-cell">${r.ticker}</td>
            <td class="num">${fmt(r.weight_pct,1)}%</td>
            <td class="num">${fmt(r.vol_ind_pct,1)}%</td>
            <td class="num ${r.corr_port > 0.7 ? 'negative' : r.corr_port < 0.3 ? 'positive' : ''}">${fmt(r.corr_port,2)}</td>
            <td class="num">
              <div class="risk-bar-cell">
                <div class="risk-bar" style="width:${Math.min(100,Math.abs(r.contrib_risk_pct))}%"></div>
                <span>${fmt(r.contrib_risk_pct,1)}%</span>
              </div>
            </td>
            <td class="num dim">${fmt(r.contrib_vol_ppt,2)} pp</td>
          </tr>`).join('')}
      </tbody>
    </table>
    </div>
  `;
}

// ── Rolling Beta ──────────────────────────────────────────────────
async function _loadRollingBeta() {
  const canvas = document.getElementById('risk-beta-chart');
  const badges = document.getElementById('risk-beta-badges');
  if (!canvas) return;
  try {
    const r = await fetch('/api/risk/rolling-beta?roll_window=60');
    const d = await r.json();
    if (d.error) {
      canvas.parentElement.innerHTML += `<div class="risk-error">${d.error}</div>`;
      return;
    }
    const series = d.series.filter(p => p.beta != null);
    if (!series.length) return;
    const last  = series[series.length - 1].beta;
    const avg   = series.reduce((a, p) => a + p.beta, 0) / series.length;
    const min_v = Math.min(...series.map(p => p.beta));
    const max_v = Math.max(...series.map(p => p.beta));
    if (badges) badges.innerHTML = `
      <span class="risk-badge">ATUAL: <b class="${colorCls(last - 1)}">${fmt(last,2)}</b></span>
      <span class="risk-badge dim">MÉD: ${fmt(avg,2)}</span>
      <span class="risk-badge dim">MÍN: ${fmt(min_v,2)}</span>
      <span class="risk-badge dim">MÁX: ${fmt(max_v,2)}</span>
    `;
    if (_riskBetaChart) _riskBetaChart.destroy();
    _riskBetaChart = new Chart(canvas, {
      type: 'line',
      data: {
        labels: series.map(p => p.date),
        datasets: [{
          label: 'Beta 60D',
          data:  series.map(p => p.beta),
          borderColor: '#ff8c00',
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false,
          tension: 0.2,
        }, {
          label: 'Beta = 1',
          data: series.map(() => 1),
          borderColor: '#444',
          borderWidth: 1,
          borderDash: [4, 4],
          pointRadius: 0,
          fill: false,
        }],
      },
      options: {
        responsive: true,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: ctx => ctx.datasetIndex === 0 ? `Beta: ${fmt(ctx.parsed.y, 2)}` : null,
            }
          },
        },
        scales: {
          x: {
            ticks: {
              maxTicksLimit: 8,
              callback: (_, i, arr) => {
                const d = series[i];
                return d ? d.date.slice(0, 7) : '';
              },
              color: '#888',
            },
            grid: { color: '#1a1a1a' },
          },
          y: {
            ticks: { color: '#888', callback: v => fmt(v, 2) },
            grid: { color: '#1a1a1a' },
          },
        },
      },
    });
  } catch(e) {
    if (canvas.parentElement) canvas.insertAdjacentHTML('afterend', `<div class="risk-error">ERRO: ${e.message}</div>`);
  }
}

// ── Liquidity ─────────────────────────────────────────────────────
async function _loadLiquidity() {
  const el = document.getElementById('risk-liq-content');
  if (!el) return;
  try {
    const r = await fetch('/api/risk/liquidity');
    const d = await r.json();
    _renderLiquidity(d, el);
  } catch(e) {
    el.innerHTML = `<div class="risk-error">ERRO: ${e.message}</div>`;
  }
}

function _renderLiquidity(d, el) {
  const liqBar = pct => {
    const cls = pct >= 80 ? 'positive' : pct >= 40 ? 'bbg-orange' : 'negative';
    return `<div class="risk-liq-bar-wrap"><div class="risk-liq-bar ${cls}" style="width:${pct}%"></div><span>${fmt(pct,0)}%</span></div>`;
  };
  el.innerHTML = `
    <div class="risk-var-grid" style="margin-bottom:10px">
      <div class="risk-metric-block">
        <div class="risk-metric-label">LIQUIDÁVEL EM 1D</div>
        <div class="risk-metric-val ${d.portfolio_liq_1d_pct >= 80 ? 'positive' : 'negative'}">${fmt(d.portfolio_liq_1d_pct,1)}%</div>
        <div class="risk-metric-sub">${fmtBRL(d.portfolio_liq_1d_rs)}</div>
      </div>
      <div class="risk-metric-block">
        <div class="risk-metric-label">LIQUIDÁVEL EM 5D</div>
        <div class="risk-metric-val ${d.portfolio_liq_5d_pct >= 80 ? 'positive' : 'negative'}">${fmt(d.portfolio_liq_5d_pct,1)}%</div>
        <div class="risk-metric-sub">${fmtBRL(d.portfolio_liq_5d_rs)}</div>
      </div>
      <div class="risk-metric-block">
        <div class="risk-metric-label">LIQUIDÁVEL EM 10D</div>
        <div class="risk-metric-val ${d.portfolio_liq_10d_pct >= 80 ? 'positive' : 'negative'}">${fmt(d.portfolio_liq_10d_pct,1)}%</div>
        <div class="risk-metric-sub">${fmtBRL(d.portfolio_liq_10d_rs)}</div>
      </div>
    </div>
    <div class="table-wrapper" style="max-height:260px;overflow-y:auto">
    <table class="risk-table">
      <thead><tr>
        <th>ATIVO</th><th class="num">PESO%</th>
        <th class="num">SCORE LIQ.</th><th class="num">DIAS P/ LIQ.</th>
        <th>LIQ. 1D</th><th>LIQ. 5D</th><th>LIQ. 10D</th>
      </tr></thead>
      <tbody>
        ${d.rows.map(r => `
          <tr>
            <td class="ticker-cell">${r.ticker}</td>
            <td class="num">${fmt(r.weight_pct,1)}%</td>
            <td class="num ${r.liq_score >= 0 ? 'positive' : 'negative'}">${r.liq_score != null ? sign(r.liq_score) + r.liq_score : '—'}</td>
            <td class="num">${r.days_to_liq != null ? fmt(r.days_to_liq,1) + 'd' : '—'}</td>
            <td>${liqBar(r.liq_1d_pct)}</td>
            <td>${liqBar(r.liq_5d_pct)}</td>
            <td>${liqBar(r.liq_10d_pct)}</td>
          </tr>`).join('')}
      </tbody>
    </table>
    </div>
  `;
}

// ── Tracking Error & Information Ratio ────────────────────────────
const _teCache = {};
async function _loadTrackingError() {
  const el = document.getElementById('risk-te-content');
  if (!el) return;
  const key = _riskTeWindow;
  if (!_teCache[key]) {
    el.innerHTML = '<div class="risk-loading">CARREGANDO...</div>';
    try {
      const r = await fetch(`/api/risk/tracking-error?window=${key}`);
      const d = await r.json();
      if (d.error) { el.innerHTML = `<div class="risk-error">${d.error}</div>`; return; }
      _teCache[key] = d;
    } catch(e) { el.innerHTML = `<div class="risk-error">ERRO: ${e.message}</div>`; return; }
  }
  const d = _teCache[key];
  const irCls  = d.information_ratio == null ? '' : d.information_ratio >= 0 ? 'positive' : 'negative';
  const retCls = d.retorno_ativo_anual >= 0 ? 'positive' : 'negative';
  el.innerHTML = `
    <div class="risk-var-grid">
      <div class="risk-metric-block">
        <div class="risk-metric-label">TRACKING ERROR (a.a.)</div>
        <div class="risk-metric-val">${fmt(d.tracking_error,2)}%</div>
        <div class="risk-metric-sub">Janela: ${d.n_dias}d</div>
      </div>
      <div class="risk-metric-block">
        <div class="risk-metric-label">INFORMATION RATIO</div>
        <div class="risk-metric-val ${irCls}">${d.information_ratio != null ? fmt(d.information_ratio,2) : '—'}</div>
        <div class="risk-metric-sub">Retorno ativo / TE</div>
      </div>
      <div class="risk-metric-block">
        <div class="risk-metric-label">RETORNO ATIVO (a.a.)</div>
        <div class="risk-metric-val ${retCls}">${sign(d.retorno_ativo_anual)}${fmt(Math.abs(d.retorno_ativo_anual),2)}%</div>
        <div class="risk-metric-sub">vs. IBOV</div>
      </div>
    </div>
    <div style="padding:10px 12px 4px;font-size:9px;color:var(--text-muted)">
      IR &gt; 0.5 = bom &nbsp;·&nbsp; IR &gt; 1.0 = excelente &nbsp;·&nbsp; TE alto = portfólio muito ativo vs. benchmark
    </div>
  `;
}

// ── Sortino & Calmar ──────────────────────────────────────────────
let _sortinoData = null;
async function _loadSortinoCal() {
  const el = document.getElementById('risk-sortino-content');
  if (!el) return;
  if (!_sortinoData) {
    el.innerHTML = '<div class="risk-loading">CARREGANDO...</div>';
    try {
      const r = await fetch('/api/risk/sortino-calmar');
      const d = await r.json();
      if (d.error) { el.innerHTML = `<div class="risk-error">${d.error}</div>`; return; }
      _sortinoData = d;
    } catch(e) { el.innerHTML = `<div class="risk-error">ERRO: ${e.message}</div>`; return; }
  }
  const d = _sortinoData;
  const LABELS = { no_mes:'MÊS', no_ano:'ANO', '3m':'3M', '6m':'6M', '12m':'12M', '24m':'24M', '36m':'36M', total:'TOTAL' };
  const rows = Object.entries(d.windows).map(([k, v]) => {
    const srtCls = v.sortino == null ? '' : v.sortino >= 0 ? 'positive' : 'negative';
    const calCls = v.calmar  == null ? '' : v.calmar  >= 0 ? 'positive' : 'negative';
    return `<tr>
      <td>${LABELS[k] || k}</td>
      <td class="num ${srtCls}">${v.sortino != null ? fmt(v.sortino,2) : '—'}</td>
      <td class="num ${calCls}">${v.calmar  != null ? fmt(v.calmar,2)  : '—'}</td>
      <td class="num">${v.downside_vol != null ? fmt(v.downside_vol,2)+'%' : '—'}</td>
      <td class="num negative">${v.max_dd != null ? fmt(v.max_dd,2)+'%' : '—'}</td>
    </tr>`;
  }).join('');
  el.innerHTML = `
    <div class="table-wrapper" style="max-height:320px;overflow-y:auto">
    <table class="risk-table">
      <thead><tr>
        <th>JANELA</th>
        <th class="num">SORTINO</th>
        <th class="num">CALMAR</th>
        <th class="num">VOL. BAIXA</th>
        <th class="num">MAX DD</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
    </div>
    <div style="padding:6px 12px 0;font-size:9px;color:var(--text-muted)">
      Sortino penaliza só volatilidade negativa &nbsp;·&nbsp; Calmar = Retorno a.a. / Max Drawdown
    </div>
  `;
}

// ── Upside / Downside Capture ─────────────────────────────────────
const _captureCache = {};
async function _loadCapture() {
  const el = document.getElementById('risk-capture-content');
  if (!el) return;
  const key = _riskCapWindow;
  if (!_captureCache[key]) {
    el.innerHTML = '<div class="risk-loading">CARREGANDO...</div>';
    try {
      const r = await fetch(`/api/risk/capture?window=${key}`);
      const d = await r.json();
      if (d.error) { el.innerHTML = `<div class="risk-error">${d.error}</div>`; return; }
      _captureCache[key] = d;
    } catch(e) { el.innerHTML = `<div class="risk-error">ERRO: ${e.message}</div>`; return; }
  }
  const d = _captureCache[key];
  const upCls = d.upside_capture   == null ? '' : d.upside_capture   >= 100 ? 'positive' : 'bbg-orange';
  const dnCls = d.downside_capture == null ? '' : d.downside_capture <= 100 ? 'positive' : 'negative';
  const upIcon = d.upside_capture   != null && d.upside_capture   >= 100 ? '▲' : '▼';
  const dnIcon = d.downside_capture != null && d.downside_capture <= 100 ? '▲' : '▼';
  el.innerHTML = `
    <div class="risk-var-grid">
      <div class="risk-metric-block">
        <div class="risk-metric-label">UPSIDE CAPTURE</div>
        <div class="risk-metric-val ${upCls}">${d.upside_capture != null ? upIcon+' '+fmt(d.upside_capture,1)+'%' : '—'}</div>
        <div class="risk-metric-sub">${d.n_dias_up} dias de alta IBOV</div>
      </div>
      <div class="risk-metric-block">
        <div class="risk-metric-label">DOWNSIDE CAPTURE</div>
        <div class="risk-metric-val ${dnCls}">${d.downside_capture != null ? dnIcon+' '+fmt(d.downside_capture,1)+'%' : '—'}</div>
        <div class="risk-metric-sub">${d.n_dias_down} dias de baixa IBOV</div>
      </div>
      <div class="risk-metric-block">
        <div class="risk-metric-label">TOTAL DE DIAS</div>
        <div class="risk-metric-val">${d.n_total}</div>
        <div class="risk-metric-sub">Janela: ${key === 'total' ? 'completa' : key+'d'}</div>
      </div>
    </div>
    <div style="padding:8px 12px 4px;font-size:9px;color:var(--text-muted)">
      Ideal: Upside &gt; 100% e Downside &lt; 100% &nbsp;·&nbsp; Reflete a assimetria de retornos vs. IBOV
    </div>
  `;
}

// ── Concentração Setorial (HHI) ───────────────────────────────────
let _concentrationData = null;
async function _loadConcentration() {
  const el = document.getElementById('risk-concentration-content');
  if (!el) return;
  if (!_concentrationData) {
    el.innerHTML = '<div class="risk-loading">CARREGANDO...</div>';
    try {
      const r = await fetch('/api/risk/concentration');
      const d = await r.json();
      if (d.error) { el.innerHTML = `<div class="risk-error">${d.error}</div>`; return; }
      _concentrationData = d;
    } catch(e) { el.innerHTML = `<div class="risk-error">ERRO: ${e.message}</div>`; return; }
  }
  const d = _concentrationData;
  const hhiCls   = d.hhi < 1000 ? 'positive' : d.hhi < 2500 ? 'bbg-orange' : 'negative';
  const hhiLabel = d.hhi_label.toUpperCase();
  const barsHtml = d.setores.map(s => {
    const barW = Math.min(100, s.peso_pct);
    return `
      <div style="margin-bottom:5px">
        <div style="display:flex;justify-content:space-between;font-size:10px;margin-bottom:2px">
          <span>${s.setor} <span style="color:var(--text-muted);font-size:9px">(${s.tickers.join(', ')})</span></span>
          <span>${fmt(s.peso_pct,1)}%</span>
        </div>
        <div style="background:#1a1a1a;border-radius:2px;height:5px">
          <div style="background:#ff8c00;width:${barW}%;height:5px;border-radius:2px"></div>
        </div>
      </div>`;
  }).join('');
  el.innerHTML = `
    <div class="risk-var-grid" style="margin-bottom:10px">
      <div class="risk-metric-block">
        <div class="risk-metric-label">ÍNDICE HHI</div>
        <div class="risk-metric-val ${hhiCls}">${d.hhi}</div>
        <div class="risk-metric-sub">${hhiLabel}</div>
      </div>
      <div class="risk-metric-block">
        <div class="risk-metric-label">TOP 1 / TOP 3 / TOP 5</div>
        <div class="risk-metric-val">${fmt(d.top1_pct,1)}%</div>
        <div class="risk-metric-sub">${fmt(d.top3_pct,1)}% / ${fmt(d.top5_pct,1)}%</div>
      </div>
      <div class="risk-metric-block">
        <div class="risk-metric-label">SETORES / POSIÇÕES</div>
        <div class="risk-metric-val">${d.n_setores}</div>
        <div class="risk-metric-sub">${d.n_posicoes} ativos</div>
      </div>
    </div>
    <div style="padding:0 12px 8px">${barsHtml}</div>
    <div style="padding:0 12px 4px;font-size:9px;color:var(--text-muted)">
      HHI &lt; 1000 = diversificado &nbsp;·&nbsp; 1000–2500 = moderado &nbsp;·&nbsp; &gt; 2500 = concentrado
    </div>
  `;
}

// ── Exposição Cambial (BDRs) ──────────────────────────────────────
let _fxData = null;
async function _loadFxExposure() {
  const el = document.getElementById('risk-fx-content');
  if (!el) return;
  if (!_fxData) {
    el.innerHTML = '<div class="risk-loading">CARREGANDO...</div>';
    try {
      const r = await fetch('/api/risk/fx-exposure');
      const d = await r.json();
      if (d.error) { el.innerHTML = `<div class="risk-error">${d.error}</div>`; return; }
      _fxData = d;
    } catch(e) { el.innerHTML = `<div class="risk-error">ERRO: ${e.message}</div>`; return; }
  }
  const d = _fxData;
  const s = d.sensibilidade_pct || {};
  const bdrRows = (d.bdrs || []).map(r => `
    <tr>
      <td class="ticker-cell">${r.ticker}</td>
      <td>${r.sector}</td>
      <td class="num">${fmt(r.peso_pct,2)}%</td>
      <td class="num">${fmtBRL(r.valor_rs)}</td>
    </tr>`).join('');
  el.innerHTML = `
    <div class="risk-var-grid" style="margin-bottom:10px">
      <div class="risk-metric-block">
        <div class="risk-metric-label">EXPOSIÇÃO CAMBIAL</div>
        <div class="risk-metric-val">${fmt(d.total_fx_exposure_pct,1)}%</div>
        <div class="risk-metric-sub">${fmtBRL(d.total_fx_exposure_rs)}</div>
      </div>
      <div class="risk-metric-block">
        <div class="risk-metric-label">USD +5% / +10%</div>
        <div class="risk-metric-val positive">+${fmt(s.usd_plus5||0,2)}%</div>
        <div class="risk-metric-sub">+${fmt(s.usd_plus10||0,2)}% impacto no portfólio</div>
      </div>
      <div class="risk-metric-block">
        <div class="risk-metric-label">USD −5% / −10%</div>
        <div class="risk-metric-val negative">${fmt(s.usd_minus5||0,2)}%</div>
        <div class="risk-metric-sub">${fmt(s.usd_minus10||0,2)}% impacto no portfólio</div>
      </div>
    </div>
    ${d.bdrs && d.bdrs.length ? `
    <div class="table-wrapper" style="max-height:180px;overflow-y:auto">
    <table class="risk-table">
      <thead><tr><th>ATIVO</th><th>SETOR</th><th class="num">PESO%</th><th class="num">R$</th></tr></thead>
      <tbody>${bdrRows}</tbody>
    </table>
    </div>` : '<div style="padding:12px;font-size:11px;color:var(--text-muted)">Sem BDRs no portfólio atual</div>'}
  `;
}

// ── Rolling Sharpe / Rolling Sortino ─────────────────────────────
const _rollingRatiosCache = {};
async function _loadRollingRatios() {
  const canvas = document.getElementById('risk-rolling-ratios-chart');
  const badges = document.getElementById('risk-rolling-badges');
  if (!canvas) return;
  const key = _riskRollWindow;
  if (!_rollingRatiosCache[key]) {
    try {
      const r = await fetch(`/api/risk/rolling-ratios?roll_window=${key}`);
      const d = await r.json();
      if (d.error) {
        canvas.insertAdjacentHTML('afterend', `<div class="risk-error">${d.error}</div>`);
        return;
      }
      _rollingRatiosCache[key] = d;
    } catch(e) {
      canvas.insertAdjacentHTML('afterend', `<div class="risk-error">ERRO: ${e.message}</div>`);
      return;
    }
  }
  const d = _rollingRatiosCache[key];
  const series = d.series.filter(p => p.sharpe != null || p.sortino != null);
  if (!series.length) return;
  if (badges) {
    const sc = d.current_sharpe, so = d.current_sortino, as_ = d.avg_sharpe;
    badges.innerHTML = `
      <span class="risk-badge">SHARPE: <b class="${colorCls(sc)}">${sc != null ? fmt(sc,2) : '—'}</b></span>
      <span class="risk-badge">SORTINO: <b class="${colorCls(so)}">${so != null ? fmt(so,2) : '—'}</b></span>
      <span class="risk-badge dim">MÉD SHARPE: ${as_ != null ? fmt(as_,2) : '—'}</span>
    `;
  }
  if (_riskRollingRatiosChart) _riskRollingRatiosChart.destroy();
  _riskRollingRatiosChart = new Chart(canvas, {
    type: 'line',
    data: {
      labels: series.map(p => p.date),
      datasets: [{
        label: 'Sharpe',
        data:  series.map(p => p.sharpe),
        borderColor: '#ff8c00',
        borderWidth: 1.5,
        pointRadius: 0,
        fill: false,
        tension: 0.2,
      }, {
        label: 'Sortino',
        data:  series.map(p => p.sortino),
        borderColor: '#00bcd4',
        borderWidth: 1.5,
        pointRadius: 0,
        fill: false,
        tension: 0.2,
      }, {
        label: 'Zero',
        data: series.map(() => 0),
        borderColor: '#333',
        borderWidth: 1,
        borderDash: [4, 4],
        pointRadius: 0,
        fill: false,
      }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: {
          display: true,
          labels: { color: '#888', boxWidth: 12, font: { size: 10 } },
          filter: item => item.text !== 'Zero',
        },
        tooltip: {
          callbacks: {
            label: ctx => ctx.datasetIndex < 2 ? `${ctx.dataset.label}: ${fmt(ctx.parsed.y, 2)}` : null,
          }
        },
      },
      scales: {
        x: {
          ticks: {
            maxTicksLimit: 8,
            callback: (_, i) => { const p = series[i]; return p ? p.date.slice(0, 7) : ''; },
            color: '#888',
          },
          grid: { color: '#1a1a1a' },
        },
        y: {
          ticks: { color: '#888', callback: v => fmt(v, 2) },
          grid: { color: '#1a1a1a' },
        },
      },
    },
  });
}

// ── Distribuição de Retornos ──────────────────────────────────────
const _distCache = {};
async function _loadReturnDist() {
  const canvas  = document.getElementById('risk-dist-chart');
  const statsEl = document.getElementById('risk-dist-stats');
  if (!canvas) return;
  const key = _riskDistWindow;
  if (!_distCache[key]) {
    try {
      const r = await fetch(`/api/risk/return-distribution?window=${key}`);
      const d = await r.json();
      if (d.error) {
        canvas.insertAdjacentHTML('afterend', `<div class="risk-error">${d.error}</div>`);
        return;
      }
      _distCache[key] = d;
    } catch(e) {
      canvas.insertAdjacentHTML('afterend', `<div class="risk-error">ERRO: ${e.message}</div>`);
      return;
    }
  }
  const d = _distCache[key];
  if (statsEl) {
    const skewLabel = d.skewness < -0.5 ? 'assimetria negativa' : d.skewness > 0.5 ? 'assimetria positiva' : 'simétrico';
    const kurtLabel = d.kurtosis > 1 ? 'fat tails' : d.kurtosis < -1 ? 'thin tails' : 'normal';
    const skewCls   = d.skewness < -0.3 ? 'negative' : d.skewness > 0.3 ? 'positive' : '';
    statsEl.innerHTML = `
      <span class="risk-badge">MÉDIA: <b>${fmt(d.mean_pct,3)}%</b></span>
      <span class="risk-badge">VOL DIÁRIA: <b>${fmt(d.std_pct,3)}%</b></span>
      <span class="risk-badge">DIAS +: <b class="positive">${fmt(d.pct_positive,1)}%</b></span>
      <span class="risk-badge">MELHOR DIA: <b class="positive">+${fmt(d.best_day,2)}%</b></span>
      <span class="risk-badge">PIOR DIA: <b class="negative">${fmt(d.worst_day,2)}%</b></span>
      <span class="risk-badge">SKEW: <b class="${skewCls}">${fmt(d.skewness,2)} (${skewLabel})</b></span>
      <span class="risk-badge">KURTOSE: <b>${fmt(d.kurtosis,2)} (${kurtLabel})</b></span>
      <span class="risk-badge">P5/P95: <b>${fmt(d.p5,2)}% / +${fmt(d.p95,2)}%</b></span>
      ${d.ibov_mean_pct != null ? `<span class="risk-badge dim">IBOV MÉD: ${fmt(d.ibov_mean_pct,3)}% | VOL: ${fmt(d.ibov_std_pct,3)}%</span>` : ''}
    `;
  }
  if (_riskDistChart) _riskDistChart.destroy();
  const datasets = [{
    label: 'Fundo',
    data:  d.counts,
    backgroundColor: 'rgba(255,140,0,0.6)',
    borderColor: '#ff8c00',
    borderWidth: 1,
  }];
  if (d.ibov_counts) {
    datasets.push({
      label: 'IBOV',
      data:  d.ibov_counts,
      backgroundColor: 'rgba(100,180,255,0.3)',
      borderColor: '#64b4ff',
      borderWidth: 1,
    });
  }
  _riskDistChart = new Chart(canvas, {
    type: 'bar',
    data: { labels: d.bin_centers.map(v => fmt(v, 2) + '%'), datasets },
    options: {
      responsive: true,
      plugins: {
        legend: {
          display: true,
          labels: { color: '#888', boxWidth: 12, font: { size: 10 } },
        },
        tooltip: {
          callbacks: {
            label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y} dias`,
          }
        },
      },
      scales: {
        x: {
          ticks: { maxTicksLimit: 12, color: '#888', font: { size: 9 } },
          grid: { color: '#1a1a1a' },
        },
        y: {
          ticks: { color: '#888', callback: v => v + 'd' },
          grid: { color: '#1a1a1a' },
        },
      },
    },
  });
}

// ═══════════════════════════════════════════════════════════════════
//  208) FINANCIAIS
// ═══════════════════════════════════════════════════════════════════

let _finCurrentTicker    = null;
let _finCurrentPeriod    = 'annual';
let _finCurrentStatement = 'income';
let _finInitialized      = false;

// Rows that should be visually highlighted (bold amber)
const FIN_HIGHLIGHT_ROWS = new Set([
  'Gross Profit', 'Operating Income', 'Net Income', 'EBITDA',
  'Total Assets', 'Total Liabilities Net Minority Interest', 'Stockholders Equity',
  'Free Cash Flow', 'Operating Cash Flow',
]);

// Rows that are inherently negative (no red colouring for them)
const FIN_NEUTRAL_NEGATIVE = new Set([
  'Cost Of Revenue', 'Tax Provision', 'Interest Expense Non Operating',
  'Total Other Finance Cost', 'Selling General Administrative',
  'General Administrative Expense', 'Selling Expense', 'Other Operating Expenses',
  'Capital Expenditure', 'Repayment Of Debt',
]);

function _finFmtNumber(val) {
  if (val === null || val === undefined) return '<span style="color:var(--text-muted)">—</span>';
  const thousands = Math.round(val / 1000);
  const abs = Math.abs(thousands);
  const formatted = abs.toLocaleString('en-US');
  return thousands < 0 ? `(${formatted})` : formatted;
}

function _finRenderTable(data) {
  const wrap        = document.getElementById('fin-table-wrap');
  const unavailable = document.getElementById('fin-unavailable');
  const loading     = document.getElementById('fin-loading');

  loading.classList.add('hidden');

  if (!data.available) {
    wrap.classList.add('hidden');
    unavailable.classList.remove('hidden');
    return;
  }

  unavailable.classList.add('hidden');
  wrap.classList.remove('hidden');

  // Header row
  const thead = document.getElementById('fin-thead-row');
  thead.innerHTML = '<th class="fin-th-label">Breakdown</th>' +
    data.columns.map(c => `<th class="fin-th-val">${c}</th>`).join('');

  // Body rows
  const tbody = document.getElementById('fin-tbody');
  tbody.innerHTML = data.rows.map(row => {
    const isHighlight = FIN_HIGHLIGHT_ROWS.has(row.label);
    const isNeutral   = FIN_NEUTRAL_NEGATIVE.has(row.label);
    const cells = row.values.map(v => {
      let cls = '';
      if (v !== null && !isNeutral) {
        cls = v >= 0 ? 'fin-positive' : 'fin-negative';
      }
      return `<td class="fin-td-val ${cls}">${_finFmtNumber(v)}</td>`;
    }).join('');
    const rowCls = isHighlight ? 'fin-row-highlight' : '';
    return `<tr class="${rowCls}"><td class="fin-td-label">${row.label}</td>${cells}</tr>`;
  }).join('');
}

async function _finFetch(ticker, period, statement) {
  const loading     = document.getElementById('fin-loading');
  const wrap        = document.getElementById('fin-table-wrap');
  const unavailable = document.getElementById('fin-unavailable');

  loading.classList.remove('hidden');
  wrap.classList.add('hidden');
  unavailable.classList.add('hidden');

  try {
    const res  = await fetch(`/api/financials/${encodeURIComponent(ticker)}?period=${period}&statement=${statement}`);
    const data = await res.json();
    _finRenderTable(data);
  } catch (e) {
    loading.classList.add('hidden');
    unavailable.classList.remove('hidden');
    unavailable.textContent = 'Erro ao carregar dados financeiros.';
  }
}

function _finPopulateTickers() {
  const sel = document.getElementById('fin-ticker-select');
  if (!sel) return;
  sel.innerHTML = '';
  if (portfolioData && portfolioData.rows) {
    portfolioData.rows.forEach(r => {
      const opt = document.createElement('option');
      opt.value       = r.yahoo_ticker;
      opt.textContent = r.ticker;
      sel.appendChild(opt);
    });
  }
  _finCurrentTicker = sel.value || null;
}

function loadFinancialsTab() {
  if (!_finInitialized) {
    _finPopulateTickers();

    const sel = document.getElementById('fin-ticker-select');
    if (sel) {
      sel.addEventListener('change', () => {
        _finCurrentTicker = sel.value;
        _finFetch(_finCurrentTicker, _finCurrentPeriod, _finCurrentStatement);
      });
    }

    document.querySelectorAll('.fin-period-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.fin-period-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        _finCurrentPeriod = btn.dataset.period;
        if (_finCurrentTicker) _finFetch(_finCurrentTicker, _finCurrentPeriod, _finCurrentStatement);
      });
    });

    document.querySelectorAll('.fin-stmt-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.fin-stmt-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        _finCurrentStatement = btn.dataset.stmt;
        if (_finCurrentTicker) _finFetch(_finCurrentTicker, _finCurrentPeriod, _finCurrentStatement);
      });
    });

    _finInitialized = true;
  }

  if (_finCurrentTicker) {
    _finFetch(_finCurrentTicker, _finCurrentPeriod, _finCurrentStatement);
  }
}
