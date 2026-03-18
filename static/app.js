/* ===================================================================
   HARBOUR IAT FIA — Portfolio Tracker
   =================================================================== */

// ── State ────────────────────────────────────────────────────────────
let portfolioData  = null;
let historyChart   = null;
let sectorChart    = null;
let upsideChart    = null;
let sortCol        = 'pct_total';
let sortDir        = 'desc';
let refreshTimer   = null;
let countdownTimer = null;
let secondsLeft    = 30;
let editingTicker  = null;
let currentDays    = 90;
const REFRESH_SEC  = 30;

// Chart.js global defaults (dark theme)
Chart.defaults.color          = '#7b80a0';
Chart.defaults.borderColor    = '#2e3248';
Chart.defaults.font.family    = "'Segoe UI', system-ui, sans-serif";
Chart.defaults.font.size      = 11;

// ── Format helpers ────────────────────────────────────────────────────
const fmt = (v, d=2, fb='—') =>
  v == null || isNaN(v) ? fb
  : Number(v).toLocaleString('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d });

const fmtBRL = (v, fb='—') =>
  v == null || isNaN(v) ? fb
  : 'R$ ' + Number(v).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const fmtInt = (v, fb='—') =>
  v == null || isNaN(v) ? fb : Number(v).toLocaleString('pt-BR');

const sign = v => (v == null ? '' : v >= 0 ? '+' : '');

const colorCls = v => v == null ? 'neutral' : v > 0 ? 'positive' : v < 0 ? 'negative' : 'neutral';

const upsideCls = v => {
  if (v == null) return '';
  if (v >= 30) return 'upside-high';
  if (v >= 0)  return 'upside-mid';
  return 'upside-neg';
};

// ── Fetch portfolio ───────────────────────────────────────────────────
async function fetchPortfolio() {
  try {
    const res = await fetch('/api/portfolio');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    portfolioData = await res.json();
    renderTable();
    renderHeader();
    renderChartsIfVisible();
    hideLoading();
  } catch (e) {
    console.error('Erro ao buscar portfólio:', e);
  }
}

// ── Header ────────────────────────────────────────────────────────────
function renderHeader() {
  if (!portfolioData) return;

  document.getElementById('fund-name').textContent = portfolioData.fund_name;
  document.getElementById('total-value').textContent = fmtBRL(portfolioData.total_value);

  const wu = portfolioData.weighted_upside;
  const wuEl = document.getElementById('weighted-upside');
  wuEl.textContent = wu != null ? sign(wu) + fmt(wu) + '%' : '—';
  wuEl.className = 'stat-value ' + colorCls(wu);

  const wb = portfolioData.weighted_beta;
  document.getElementById('weighted-beta').textContent = wb != null ? fmt(wb, 2) : '—';

  const now = new Date();
  document.getElementById('header-date').textContent =
    'DATA: ' + now.toLocaleDateString('pt-BR') + ' ' + now.toLocaleTimeString('pt-BR', { hour:'2-digit', minute:'2-digit' });
  document.getElementById('last-update').textContent = now.toLocaleTimeString('pt-BR');
}

// ── Table ─────────────────────────────────────────────────────────────
function renderTable() {
  if (!portfolioData) return;
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

    // Liq badge
    const liq = row.liq_diaria_mm;
    const liqHtml = liq == null ? '—'
      : `<span class="liq-badge ${liq >= 0 ? 'liq-buy' : 'liq-sell'}">${liq >= 0 ? '+' : ''}${liq}</span>`;

    // 52-week range bar
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
      <td class="ticker-cell">
        ${row.ticker}
        ${row.short_name ? `<span class="name-sub">${row.short_name}</span>` : ''}
      </td>
      <td>${row.categoria || '—'}</td>
      <td>${row.sector || '—'}</td>
      <td class="num">${row.pct_total != null ? fmt(row.pct_total,2)+'%' : '—'}</td>
      <td class="num">${fmtBRL(row.valor_liquido)}</td>
      <td class="num">${fmtBRL(row.preco)}</td>
      <td class="num ${colorCls(row.var_dia_pct)}">${row.var_dia_pct != null ? sign(row.var_dia_pct)+fmt(row.var_dia_pct)+'%' : '—'}</td>
      <td class="num">${fmtInt(row.quantidade)}</td>
      <td class="num">${liqHtml}</td>
      <td class="num">${fmt(row.trailing_pe,1)}</td>
      <td class="num">${fmt(row.forward_pe,1)}</td>
      <td class="num">${fmt(row.enterprise_to_ebitda,1)}</td>
      <td class="num ${row.return_on_equity != null ? colorCls(row.return_on_equity) : ''}">${row.return_on_equity != null ? fmt(row.return_on_equity,1)+'%' : '—'}</td>
      <td class="num">${fmt(row.beta,2)}</td>
      <td class="num">${fmt(row.price_to_book,1)}</td>
      <td class="num">${row.dividend_yield != null ? fmt(row.dividend_yield,2)+'%' : '—'}</td>
      <td class="num">${row.market_cap_bi != null ? 'R$'+fmt(row.market_cap_bi,1)+'B' : '—'}</td>
      <td class="num">${row.lucro_mi_25 != null ? fmtInt(row.lucro_mi_25) : '—'}</td>
      <td class="num">${fmt(row.pl_alvo_25,1)}</td>
      <td class="num">${fmtBRL(row.preco_alvo)}</td>
      <td class="num ${upsideCls(row.upside_pct)}">${row.upside_pct != null ? sign(row.upside_pct)+fmt(row.upside_pct)+'%' : '—'}</td>
      <td><button class="btn-edit" title="Editar">✎</button></td>
    `;

    tr.querySelector('.btn-edit').addEventListener('click', () => openEditModal(row));
    tbody.appendChild(tr);
  });

  // Sort indicators
  document.querySelectorAll('th[data-col]').forEach(th => {
    th.classList.remove('sorted-asc', 'sorted-desc');
    if (th.dataset.col === sortCol) th.classList.add(sortDir === 'asc' ? 'sorted-asc' : 'sorted-desc');
  });
}

// Column sort
document.querySelectorAll('th[data-col]').forEach(th => {
  th.addEventListener('click', () => {
    const col = th.dataset.col;
    if (sortCol === col) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
    else { sortCol = col; sortDir = (col === 'ticker' || col === 'categoria' || col === 'sector') ? 'asc' : 'desc'; }
    renderTable();
  });
});

// ── Auto refresh (prices only) ────────────────────────────────────────
function startRefreshCycle() {
  clearInterval(refreshTimer);
  clearInterval(countdownTimer);
  secondsLeft = REFRESH_SEC;

  refreshTimer = setInterval(refreshPricesOnly, REFRESH_SEC * 1000);

  countdownTimer = setInterval(() => {
    secondsLeft = Math.max(0, secondsLeft - 1);
    document.getElementById('next-refresh').textContent = `Próx.: ${secondsLeft}s`;
  }, 1000);
}

async function refreshPricesOnly() {
  try {
    const res  = await fetch('/api/prices');
    const json = await res.json();
    if (!portfolioData) return;

    const priceMap = json.prices;
    portfolioData.rows.forEach(row => {
      const p = priceMap[row.yahoo_ticker];
      if (!p) return;
      const old = row.preco;
      row.preco      = p.price;
      row.var_dia_pct = p.change_pct;
      if (row.preco && row.quantidade) row.valor_liquido = Math.round(row.preco * row.quantidade * 100) / 100;
      if (row.preco && row.preco_alvo)  row.upside_pct = Math.round((row.preco_alvo / row.preco - 1) * 10000) / 100;

      if (old !== row.preco) {
        const tr = document.querySelector(`tr[data-ticker="${row.ticker}"]`);
        if (tr) {
          tr.classList.add(row.preco > old ? 'flash-up' : 'flash-down');
          setTimeout(() => tr.classList.remove('flash-up', 'flash-down'), 800);
        }
      }
    });

    const total = portfolioData.rows.reduce((s, r) => s + (r.valor_liquido || 0), 0);
    portfolioData.total_value = Math.round(total * 100) / 100;
    portfolioData.rows.forEach(r => {
      r.pct_total = total > 0 && r.valor_liquido ? Math.round(r.valor_liquido / total * 10000) / 100 : null;
    });

    const ws = portfolioData.rows
      .filter(r => r.upside_pct != null && r.pct_total != null)
      .reduce((s, r) => s + r.upside_pct * r.pct_total / 100, 0);
    portfolioData.weighted_upside = Math.round(ws * 100) / 100;

    renderTable();
    renderHeader();
    secondsLeft = REFRESH_SEC;
  } catch (e) {
    console.error('Erro ao atualizar preços:', e);
  }
}

document.getElementById('btn-refresh').addEventListener('click', async () => {
  const btn = document.getElementById('btn-refresh');
  btn.disabled = true;
  await refreshPricesOnly();
  btn.disabled = false;
});

// ── Tabs ──────────────────────────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');
    if (btn.dataset.tab === 'tab-charts') loadCharts(currentDays);
  });
});

function renderChartsIfVisible() {
  if (document.getElementById('tab-charts').classList.contains('active')) {
    loadCharts(currentDays);
  }
}

// ── CHART: History vs IBOV ────────────────────────────────────────────
async function loadHistoryChart(days) {
  const canvas  = document.getElementById('history-chart');
  const loading = document.getElementById('history-loading');
  canvas.style.display = 'none';
  loading.classList.remove('hidden');

  try {
    const res  = await fetch(`/api/history?days=${days}`);
    const data = await res.json();

    loading.classList.add('hidden');
    canvas.style.display = '';

    if (!data.series || data.series.length === 0) {
      loading.textContent = 'Sem dados históricos disponíveis.';
      loading.classList.remove('hidden');
      canvas.style.display = 'none';
      return;
    }

    const labels    = data.series.map(d => d.date);
    const portData  = data.series.map(d => d.portfolio);
    const ibovData  = data.series.map(d => d.ibov);

    const lastPort = portData[portData.length - 1];
    const lastIbov = ibovData[ibovData.length - 1];
    const portPerf = lastPort != null ? (lastPort - 100).toFixed(2) : null;
    const ibovPerf = lastIbov != null ? (lastIbov - 100).toFixed(2) : null;

    if (historyChart) historyChart.destroy();

    historyChart = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: `Portfólio ${portPerf != null ? (portPerf >= 0 ? '+' : '') + portPerf + '%' : ''}`,
            data: portData,
            borderColor: '#5865f2',
            backgroundColor: 'rgba(88,101,242,0.08)',
            borderWidth: 2,
            pointRadius: 0,
            pointHoverRadius: 4,
            fill: true,
            tension: 0.3,
          },
          {
            label: `IBOV ${ibovPerf != null ? (ibovPerf >= 0 ? '+' : '') + ibovPerf + '%' : ''}`,
            data: ibovData,
            borderColor: '#f39c12',
            backgroundColor: 'rgba(243,156,18,0.05)',
            borderWidth: 2,
            pointRadius: 0,
            pointHoverRadius: 4,
            fill: false,
            tension: 0.3,
          },
        ],
      },
      options: {
        responsive: true,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: {
            labels: { color: '#7b80a0', usePointStyle: true, pointStyleWidth: 10 },
          },
          tooltip: {
            backgroundColor: '#1a1d27',
            borderColor: '#2e3248',
            borderWidth: 1,
            callbacks: {
              label: ctx => ` ${ctx.dataset.label.split(' ')[0]}: ${fmt(ctx.parsed.y, 2)}`,
            },
          },
        },
        scales: {
          x: {
            grid: { color: '#2e3248' },
            ticks: {
              maxTicksLimit: 8,
              callback: (_, i) => {
                const d = labels[i];
                return d ? d.slice(5) : '';  // show MM-DD
              },
            },
          },
          y: {
            grid: { color: '#2e3248' },
            ticks: { callback: v => v.toFixed(0) },
          },
        },
      },
    });
  } catch (e) {
    loading.textContent = 'Erro ao carregar histórico: ' + e.message;
    loading.classList.remove('hidden');
    canvas.style.display = 'none';
  }
}

// ── CHART: Sector Doughnut ────────────────────────────────────────────
const SECTOR_COLORS = [
  '#5865f2','#2ecc71','#f39c12','#e74c3c','#3498db',
  '#9b59b6','#1abc9c','#e67e22','#34495e','#e91e63',
  '#00bcd4','#8bc34a',
];

function renderSectorChart() {
  if (!portfolioData) return;
  const canvas = document.getElementById('sector-chart');

  // Group by sector
  const sectorMap = {};
  portfolioData.rows.forEach(row => {
    const sector = row.sector || row.categoria || 'Outros';
    sectorMap[sector] = (sectorMap[sector] || 0) + (row.valor_liquido || 0);
  });

  const total = Object.values(sectorMap).reduce((a, b) => a + b, 0);
  const entries = Object.entries(sectorMap)
    .sort((a, b) => b[1] - a[1]);

  const labels = entries.map(([s]) => s);
  const values = entries.map(([, v]) => total > 0 ? Math.round(v / total * 1000) / 10 : 0);
  const colors = labels.map((_, i) => SECTOR_COLORS[i % SECTOR_COLORS.length]);

  if (sectorChart) sectorChart.destroy();

  sectorChart = new Chart(canvas, {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: colors,
        borderColor: '#1a1d27',
        borderWidth: 2,
        hoverOffset: 6,
      }],
    },
    options: {
      responsive: true,
      cutout: '62%',
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1a1d27',
          borderColor: '#2e3248',
          borderWidth: 1,
          callbacks: { label: ctx => ` ${ctx.label}: ${ctx.parsed.toFixed(1)}%` },
        },
      },
    },
  });

  // Custom legend
  const legend = document.getElementById('sector-legend');
  legend.innerHTML = entries.map(([sector, val], i) => {
    const pct = total > 0 ? (val / total * 100).toFixed(1) : '0.0';
    return `<div class="sector-legend-item">
      <div class="sector-legend-dot" style="background:${colors[i]}"></div>
      <span>${sector} <strong style="color:#e0e3f0">${pct}%</strong></span>
    </div>`;
  }).join('');
}

// ── CHART: Upside by stock ────────────────────────────────────────────
function renderUpsideChart() {
  if (!portfolioData) return;
  const canvas = document.getElementById('upside-chart');

  const rows = portfolioData.rows
    .filter(r => r.upside_pct != null)
    .sort((a, b) => b.upside_pct - a.upside_pct);

  const labels = rows.map(r => r.ticker);
  const values = rows.map(r => r.upside_pct);
  const colors = values.map(v => v >= 0 ? 'rgba(46,204,113,0.75)' : 'rgba(231,76,60,0.75)');
  const borders = values.map(v => v >= 0 ? '#2ecc71' : '#e74c3c');

  if (upsideChart) upsideChart.destroy();

  upsideChart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Upside %',
        data: values,
        backgroundColor: colors,
        borderColor: borders,
        borderWidth: 1,
        borderRadius: 4,
      }],
    },
    options: {
      responsive: true,
      indexAxis: 'y',
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1a1d27',
          borderColor: '#2e3248',
          borderWidth: 1,
          callbacks: { label: ctx => ` ${ctx.parsed.x >= 0 ? '+' : ''}${ctx.parsed.x.toFixed(2)}%` },
        },
      },
      scales: {
        x: {
          grid: { color: '#2e3248' },
          ticks: { callback: v => v + '%' },
        },
        y: { grid: { display: false } },
      },
    },
  });
}

async function loadCharts(days) {
  currentDays = days;
  renderSectorChart();
  renderUpsideChart();
  await loadHistoryChart(days);
}

// Range selector buttons
document.querySelectorAll('.range-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    loadHistoryChart(parseInt(btn.dataset.days));
  });
});

// ── Export ────────────────────────────────────────────────────────────
document.getElementById('btn-export-csv').addEventListener('click', () => {
  window.location.href = '/api/export/csv';
});

document.getElementById('btn-export-excel').addEventListener('click', () => {
  window.location.href = '/api/export/excel';
});

// ── Edit Modal ────────────────────────────────────────────────────────
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

const closeEditModal = () => {
  document.getElementById('edit-modal').classList.add('hidden');
  editingTicker = null;
};

document.getElementById('edit-modal-close').addEventListener('click', closeEditModal);
document.getElementById('edit-modal-cancel').addEventListener('click', closeEditModal);
document.getElementById('edit-modal').addEventListener('click', e => {
  if (e.target === document.getElementById('edit-modal')) closeEditModal();
});

document.getElementById('edit-modal-save').addEventListener('click', async () => {
  if (!editingTicker) return;
  const res = await fetch('/api/portfolio/update', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      ticker:      editingTicker,
      quantidade:  document.getElementById('edit-quantidade').value,
      liq_diaria_mm: document.getElementById('edit-liq').value,
      lucro_mi_25: document.getElementById('edit-lucro').value,
      pl_alvo_25:  document.getElementById('edit-pl-alvo').value,
      preco_alvo:  document.getElementById('edit-preco-alvo').value,
    }),
  });
  if (res.ok) { closeEditModal(); showLoading(); await fetchPortfolio(); }
  else alert('Erro ao salvar.');
});

document.getElementById('edit-modal-delete').addEventListener('click', async () => {
  if (!editingTicker || !confirm(`Remover ${editingTicker} da carteira?`)) return;
  const res = await fetch(`/api/portfolio/${editingTicker}`, { method: 'DELETE' });
  if (res.ok) { closeEditModal(); showLoading(); await fetchPortfolio(); }
  else alert('Erro ao remover ativo.');
});

// ── Add Modal ─────────────────────────────────────────────────────────
document.getElementById('btn-add-stock').addEventListener('click', () => {
  ['add-ticker','add-quantidade','add-liq','add-lucro','add-pl-alvo','add-preco-alvo']
    .forEach(id => document.getElementById(id).value = '');
  document.getElementById('add-error').classList.add('hidden');
  document.getElementById('add-modal').classList.remove('hidden');
});

const closeAddModal = () => document.getElementById('add-modal').classList.add('hidden');
document.getElementById('add-modal-close').addEventListener('click', closeAddModal);
document.getElementById('add-modal-cancel').addEventListener('click', closeAddModal);
document.getElementById('add-modal').addEventListener('click', e => {
  if (e.target === document.getElementById('add-modal')) closeAddModal();
});

document.getElementById('add-modal-save').addEventListener('click', async () => {
  const ticker   = document.getElementById('add-ticker').value.trim().toUpperCase();
  const quantidade = document.getElementById('add-quantidade').value;
  if (!ticker || !quantidade) { showAddError('Ticker e Quantidade são obrigatórios.'); return; }

  const btn = document.getElementById('add-modal-save');
  btn.disabled = true; btn.textContent = 'Verificando...';

  const res = await fetch('/api/portfolio/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      ticker, quantidade,
      categoria:    document.getElementById('add-categoria').value,
      liq_diaria_mm: document.getElementById('add-liq').value,
      lucro_mi_25:  document.getElementById('add-lucro').value,
      pl_alvo_25:   document.getElementById('add-pl-alvo').value,
      preco_alvo:   document.getElementById('add-preco-alvo').value,
    }),
  });

  btn.disabled = false; btn.textContent = 'Adicionar';

  if (res.ok) { closeAddModal(); showLoading(); await fetchPortfolio(); }
  else { const err = await res.json(); showAddError(err.error || 'Erro ao adicionar.'); }
});

function showAddError(msg) {
  const el = document.getElementById('add-error');
  el.textContent = msg; el.classList.remove('hidden');
}

// ── Loading overlay ───────────────────────────────────────────────────
const showLoading = () => document.getElementById('loading-overlay').classList.remove('hidden');
const hideLoading = () => document.getElementById('loading-overlay').classList.add('hidden');

// ── Init ──────────────────────────────────────────────────────────────
(async () => {
  await fetchPortfolio();
  startRefreshCycle();
})();
