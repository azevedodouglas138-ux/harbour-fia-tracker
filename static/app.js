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
let currentDays   = 90;
const REFRESH_SEC = 30;

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
      <td><button class="btn-edit" title="Editar">✎</button></td>
    `;
    tr.querySelector('.btn-edit').addEventListener('click', () => openEditModal(row));
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
    if (btn.dataset.tab === 'tab-charts')  loadCharts(currentDays);
    if (btn.dataset.tab === 'tab-config')  loadConfig();
    if (btn.dataset.tab === 'tab-history') loadHistoryTab();
  });
});

function renderChartsIfVisible() {
  if (document.getElementById('tab-charts')?.classList.contains('active')) loadCharts(currentDays);
}

// ── Chart: History ───────────────────────────────────────────────
async function loadHistoryChart(days) {
  const canvas  = document.getElementById('history-chart');
  const loading = document.getElementById('history-loading');
  canvas.style.display = 'none'; loading.classList.remove('hidden');
  try {
    const res  = await fetch(`/api/history?days=${days}`);
    const data = await res.json();
    loading.classList.add('hidden'); canvas.style.display = '';
    if (!data.series?.length) {
      loading.textContent = 'SEM DADOS HISTÓRICOS DISPONÍVEIS.';
      loading.classList.remove('hidden'); canvas.style.display = 'none'; return;
    }
    const labels   = data.series.map(d => d.date);
    const portData = data.series.map(d => d.portfolio);
    const ibovData = data.series.map(d => d.ibov);
    const lp = portData[portData.length-1], li = ibovData[ibovData.length-1];
    if (historyChart) historyChart.destroy();
    historyChart = new Chart(canvas, {
      type: 'line',
      data: { labels, datasets: [
        { label: `HARBOUR IAT ${lp!=null?(lp>=100?'+':'')+(lp-100).toFixed(2)+'%':''}`,
          data: portData, borderColor: '#ff8c00', backgroundColor: 'rgba(255,140,0,0.05)',
          borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, fill: true, tension: 0.2 },
        { label: `IBOV ${li!=null?(li>=100?'+':'')+(li-100).toFixed(2)+'%':''}`,
          data: ibovData, borderColor: '#00aacc', backgroundColor: 'transparent',
          borderWidth: 1.5, pointRadius: 0, pointHoverRadius: 4, fill: false, tension: 0.2,
          borderDash: [4,3] },
      ]},
      options: {
        responsive: true,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { labels: { color: '#888', usePointStyle: true, pointStyleWidth: 8 } },
          tooltip: { backgroundColor: '#0d0d0d', borderColor: '#2a2a2a', borderWidth: 1,
            callbacks: { label: ctx => ` ${ctx.dataset.label.split(' ')[0]}: ${fmt(ctx.parsed.y,2)}` } },
        },
        scales: {
          x: { grid: { color: '#1c1c1c' }, ticks: { maxTicksLimit: 8, callback: (_,i) => labels[i]?.slice(5)||'' } },
          y: { grid: { color: '#1c1c1c' }, ticks: { callback: v => v.toFixed(0) } },
        },
      },
    });
  } catch(e) {
    loading.textContent = 'ERRO: ' + e.message; loading.classList.remove('hidden'); canvas.style.display = 'none';
  }
}

// ── Chart: Sector ────────────────────────────────────────────────
const CHART_COLORS = ['#ff8c00','#00aacc','#00cc44','#ff3333','#ffcc00','#9b59b6','#1abc9c','#e67e22','#3498db','#e91e63'];

function renderSectorChart() {
  if (!portfolioData) return;
  const canvas = document.getElementById('sector-chart');
  const smap = {};
  portfolioData.rows.forEach(r => {
    const s = r.sector || r.categoria || 'Outros';
    smap[s] = (smap[s] || 0) + (r.valor_liquido || 0);
  });
  const total = Object.values(smap).reduce((a,b) => a+b, 0);
  const entries = Object.entries(smap).sort((a,b) => b[1]-a[1]);
  const labels = entries.map(([s]) => s);
  const values = entries.map(([,v]) => total > 0 ? Math.round(v/total*1000)/10 : 0);
  const colors = labels.map((_,i) => CHART_COLORS[i % CHART_COLORS.length]);
  if (sectorChart) sectorChart.destroy();
  sectorChart = new Chart(canvas, {
    type: 'doughnut',
    data: { labels, datasets: [{ data: values, backgroundColor: colors, borderColor: '#000', borderWidth: 2, hoverOffset: 5 }] },
    options: { responsive: true, cutout: '60%',
      plugins: { legend: { display: false },
        tooltip: { backgroundColor: '#0d0d0d', borderColor: '#2a2a2a', borderWidth: 1,
          callbacks: { label: ctx => ` ${ctx.label}: ${ctx.parsed.toFixed(1)}%` } } } },
  });
  document.getElementById('sector-legend').innerHTML = entries.map(([s,v],i) =>
    `<div class="sector-legend-item"><div class="sector-legend-dot" style="background:${colors[i]}"></div>
     <span>${s} <strong style="color:#e8e8e8">${(v/total*100).toFixed(1)}%</strong></span></div>`
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

async function loadCharts(days) {
  currentDays = days;
  renderSectorChart(); renderUpsideChart();
  await loadHistoryChart(days);
}

document.querySelectorAll('.range-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    loadHistoryChart(parseInt(btn.dataset.days));
  });
});

// ── Export ───────────────────────────────────────────────────────
document.getElementById('btn-export-csv').addEventListener('click',   () => { window.location.href = '/api/export/csv'; });
document.getElementById('btn-export-excel').addEventListener('click', () => { window.location.href = '/api/export/excel'; });

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

document.getElementById('cfg-save').addEventListener('click', async () => {
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
document.getElementById('btn-add-stock').addEventListener('click', () => {
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
  // Pre-fill date with today and cota with current estimated value
  const today = new Date().toISOString().slice(0, 10);
  document.getElementById('hist-reg-data').value = today;
  const cota = portfolioData?.quota?.cota_estimada;
  if (cota) document.getElementById('hist-reg-cota').value = cota.toFixed(8);

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
        <td><button class="btn-hist-delete" data-date="${entry.data}" title="Remover">✕</button></td>
      `;
      tr.querySelector('.btn-hist-delete').addEventListener('click', deleteQuotaEntry);
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

document.getElementById('hist-reg-save').addEventListener('click', async () => {
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

// ── Init ─────────────────────────────────────────────────────────
(async () => {
  await fetchPortfolio();
  startRefreshCycle();
})();
