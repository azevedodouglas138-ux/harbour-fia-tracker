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
    return 'R$ ' + new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 4, maximumFractionDigits: 6 }).format(v);
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
    const p = state.portfolio;
    const list = $('carteira-list');
    if (!p || !p.rows || !p.rows.length) {
      list.innerHTML = '<div class="m-empty">Sem posições.</div>';
      setVal('cart-count', '');
      return;
    }
    const rows = p.rows.slice().sort((a, b) => (b.pct_total || 0) - (a.pct_total || 0));
    const maxW = Math.max.apply(null, rows.map((r) => r.pct_total || 0)) || 1;
    setVal('cart-count', rows.length + ' ativos');
    list.innerHTML = rows.map((r) => {
      const v = r.var_dia_pct;
      const barW = Math.max(4, Math.round(((r.pct_total || 0) / maxW) * 100));
      const sub = r.upside_pct != null
        ? '<div class="m-pos-sub">upside ' + fmtPct(r.upside_pct, 0) + '</div>' : '';
      const name = r.short_name ? '<div class="m-pos-name">' + r.short_name + '</div>' : '';
      return (
        '<div class="m-pos">' +
          '<div class="m-pos-left">' +
            '<div class="m-pos-ticker">' + r.ticker + '</div>' + name +
            '<div class="m-pos-weight">' + fmtPctMag(r.pct_total, 1) + ' do fundo</div>' +
            '<div class="m-pos-bar" style="width:' + barW + '%"></div>' +
          '</div>' +
          '<div class="m-pos-right">' +
            '<div class="m-pos-var ' + sign(v) + '">' + (v == null ? '—' : fmtPct(v)) + '</div>' + sub +
          '</div>' +
        '</div>'
      );
    }).join('');
  }

  function themeColors() {
    const cs = getComputedStyle(document.documentElement);
    const g = (n) => cs.getPropertyValue(n).trim();
    return { orange: g('--orange'), cyan: g('--cyan'), yellow: g('--yellow'), muted: g('--text-muted'), border: g('--border') };
  }

  function cutoffDate(lastStr, kind) {
    if (kind === 'total') return null;
    const d = new Date(lastStr + 'T00:00:00');
    if (kind === '6m') d.setMonth(d.getMonth() - 6);
    else if (kind === '12m') d.setMonth(d.getMonth() - 12);
    return d.toISOString().slice(0, 10);
  }

  function renderRentChart() {
    const d = state.perfChart;
    const cv = $('rent-chart');
    if (!d || !d.series || !d.series.length || !cv) return;
    const co = themeColors();
    const last = d.series[d.series.length - 1].date;
    const cutoff = cutoffDate(last, chartRange);
    const series = cutoff ? d.series.filter((s) => s.date >= cutoff) : d.series;
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
