import re
import json
from datetime import datetime

log_file = "trades.log"
output_html = "trade_analysis.html"

def parse_log():
    trades = []
    pattern = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}),ACTION: (BOT|SLD), SYMBOL: ([A-Z]+), QTY: ([\d\.]+), PRICE: ([\d\.]+)")
    with open(log_file, "r") as f:
        for line in f:
            match = pattern.search(line)
            if match:
                dt_str = match.group(1)
                action = match.group(2)
                symbol = match.group(3)
                qty = float(match.group(4))
                price = float(match.group(5))
                
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S,%f")
                trades.append({
                    "timestamp": dt,
                    "action": action,
                    "symbol": symbol,
                    "qty": qty,
                    "price": price
                })
    return trades

def analyze_cycles(trades):
    cycles = []
    state = {}
    
    for t in trades:
        sym = t['symbol']
        if sym not in state:
            state[sym] = {"buys": [], "sells": [], "open_qty": 0}
            
        st = state[sym]
        
        if t['action'] == 'BOT':
            st["buys"].append(t)
            st["open_qty"] += t["qty"]
        elif t['action'] == 'SLD':
            if st["open_qty"] <= 0:
                continue
                
            actual_sell_qty = min(t["qty"], st["open_qty"])
            t_copy = dict(t)
            t_copy["qty"] = actual_sell_qty
            
            st["sells"].append(t_copy)
            st["open_qty"] -= actual_sell_qty
            
            if st["open_qty"] < 1e-5:
                total_buy_cost = sum(b["qty"] * b["price"] for b in st["buys"])
                total_buy_qty = sum(b["qty"] for b in st["buys"])
                avg_buy = total_buy_cost / total_buy_qty
                
                total_sell_revenue = sum(s["qty"] * s["price"] for s in st["sells"])
                total_sell_qty = sum(s["qty"] for s in st["sells"])
                avg_sell = total_sell_revenue / total_sell_qty
                
                pct_profit = (avg_sell - avg_buy) / avg_buy
                pnl = 4000 * pct_profit
                
                cycles.append({
                    "symbol": sym,
                    "start_time": st["buys"][0]["timestamp"].isoformat() + "Z",
                    "end_time": st["sells"][-1]["timestamp"].isoformat() + "Z",
                    "buy_qty": total_buy_qty,
                    "avg_buy_price": avg_buy,
                    "avg_sell_price": avg_sell,
                    "pct_profit": pct_profit,
                    "pnl": pnl
                })
                
                state[sym] = {"buys": [], "sells": [], "open_qty": 0}
                
    return cycles

def analyze_summary(trades):
    bot_qty = {}
    sld_qty = {}
    bot_vol = {}
    sld_vol = {}
    
    for t in trades:
        sym = t['symbol']
        qty = t['qty']
        vol = qty * t['price']
        if t['action'] == 'BOT':
            bot_qty[sym] = bot_qty.get(sym, 0) + qty
            bot_vol[sym] = bot_vol.get(sym, 0) + vol
        else:
            sld_qty[sym] = sld_qty.get(sym, 0) + qty
            sld_vol[sym] = sld_vol.get(sym, 0) + vol
            
    total_vol = {}
    all_syms = set(bot_qty.keys()) | set(sld_qty.keys())
    for s in all_syms:
        total_vol[s] = bot_vol.get(s, 0) + sld_vol.get(s, 0)
        
    top_symbols = sorted(total_vol.items(), key=lambda x: x[1], reverse=True)[:5]
    
    open_positions = []
    for s in sorted(bot_qty.keys()):
        net = bot_qty[s] - sld_qty.get(s, 0)
        if net > 1e-5:
            open_positions.append({"symbol": s, "qty": net})
            
    unmatched_sells = []
    for s in sorted(sld_qty.keys()):
        net = sld_qty[s] - bot_qty.get(s, 0)
        if net > 1e-5:
            unmatched_sells.append({"symbol": s, "qty": net})
            
    return {
        "top_symbols": [{"symbol": k, "volume": v} for k, v in top_symbols],
        "open_positions": open_positions,
        "unmatched_sells": unmatched_sells
    }

html_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Quantum Trade Analytics</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #030305;
            --surface: #0a0a0f;
            --surface-hover: #12121a;
            --primary: #6366f1;
            --success: #10b981;
            --danger: #ef4444;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
        }
        body {
            background-color: var(--bg-color);
            color: var(--text-main);
            font-family: 'Outfit', sans-serif;
            background-image: radial-gradient(circle at 50% 0%, #1a1a2e 0%, transparent 50%);
            background-repeat: no-repeat;
        }
        .mono { font-family: 'JetBrains Mono', monospace; }
        
        .glass-panel {
            background: rgba(10, 10, 15, 0.6);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.05);
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.3);
        }
        
        .stat-card {
            transition: transform 0.3s ease, border-color 0.3s ease;
        }
        .stat-card:hover {
            transform: translateY(-2px);
            border-color: rgba(99, 102, 241, 0.4);
        }

        .gradient-text {
            background: linear-gradient(135deg, #e0e7ff 0%, #818cf8 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .profit-text { color: var(--success); text-shadow: 0 0 10px rgba(16, 185, 129, 0.2); }
        .loss-text { color: var(--danger); text-shadow: 0 0 10px rgba(239, 68, 68, 0.2); }
        
        table { border-collapse: separate; border-spacing: 0; }
        th { border-bottom: 1px solid rgba(255,255,255,0.1); }
        td { border-bottom: 1px solid rgba(255,255,255,0.03); transition: background 0.2s; }
        tr:hover td { background: var(--surface-hover); }
        
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: var(--bg-color); }
        ::-webkit-scrollbar-thumb { background: #1e1e2d; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #2d2d44; }

        .filter-btn {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            color: var(--text-muted);
            padding: 0.5rem 1rem;
            border-radius: 0.5rem;
            transition: all 0.2s;
            cursor: pointer;
        }
        .filter-btn:hover {
            background: rgba(255, 255, 255, 0.1);
            color: white;
        }
        .filter-btn.active {
            background: rgba(99, 102, 241, 0.2);
            border-color: var(--primary);
            color: white;
        }
    </style>
</head>
<body class="min-h-screen p-6 md:p-12">
    <div class="max-w-7xl mx-auto">
        <header class="mb-12 flex justify-between items-end flex-wrap gap-4">
            <div>
                <h1 class="text-4xl md:text-5xl font-extrabold tracking-tight mb-2 gradient-text">Trade Analytics</h1>
                <p class="text-muted text-lg">Power: <span class="text-white font-semibold">$4,000</span> per trade cycle</p>
            </div>
            <div class="text-right flex flex-col items-end gap-3">
                <div>
                    <p class="text-sm text-muted mb-1">Generated</p>
                    <p class="mono text-sm" id="gen-time"></p>
                </div>
                <div class="flex items-center gap-2">
                    <label class="text-sm text-muted mr-1">Global Filter:</label>
                    <button class="filter-btn active" id="filter-all-price" onclick="setPriceFilter('all')">All Prices</button>
                    <button class="filter-btn" id="filter-50-price" onclick="setPriceFilter('over50')">Only &gt; $50</button>
                </div>
            </div>
        </header>

        <!-- Stats Grid -->
        <div class="grid grid-cols-2 md:grid-cols-6 gap-4 mb-8">
            <div class="glass-panel rounded-2xl p-5 stat-card col-span-2 md:col-span-1">
                <h3 class="text-muted text-xs uppercase tracking-wider mb-2">Total Trades</h3>
                <div class="text-2xl font-bold mono text-white" id="total-trades">...</div>
            </div>
            <div class="glass-panel rounded-2xl p-5 stat-card col-span-2 md:col-span-1">
                <h3 class="text-muted text-xs uppercase tracking-wider mb-2">Win Rate</h3>
                <div class="text-2xl font-bold mono" id="win-rate">...</div>
            </div>
            <div class="glass-panel rounded-2xl p-5 stat-card col-span-2 md:col-span-2">
                <h3 class="text-muted text-xs uppercase tracking-wider mb-2">Total Net PnL</h3>
                <div class="text-3xl font-bold mono" id="total-pnl">...</div>
            </div>
            <div class="glass-panel rounded-2xl p-5 stat-card col-span-2 md:col-span-1">
                <h3 class="text-muted text-xs uppercase tracking-wider mb-2">Best Trade</h3>
                <div class="text-xl font-bold mono profit-text" id="best-trade">...</div>
            </div>
            <div class="glass-panel rounded-2xl p-5 stat-card col-span-2 md:col-span-1">
                <h3 class="text-muted text-xs uppercase tracking-wider mb-2">Worst Trade</h3>
                <div class="text-xl font-bold mono loss-text" id="worst-trade">...</div>
            </div>
        </div>

        <!-- Insights Grid -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-8 mb-12">
            <div class="glass-panel rounded-2xl p-6 flex flex-col">
                <h3 class="text-xl font-semibold mb-4 text-white">Top Symbols by Volume</h3>
                <div id="top-symbols-list" class="space-y-3 flex-1"></div>
            </div>
            <div class="glass-panel rounded-2xl p-6 flex flex-col">
                <h3 class="text-xl font-semibold mb-4 text-[var(--success)]">Open Positions (Long)</h3>
                <div id="open-positions-list" class="space-y-3 flex-1 overflow-y-auto max-h-[250px] pr-2"></div>
            </div>
            <div class="glass-panel rounded-2xl p-6 flex flex-col">
                <h3 class="text-xl font-semibold mb-4 text-[var(--danger)]">Unmatched Sells</h3>
                <div id="unmatched-sells-list" class="space-y-3 flex-1 overflow-y-auto max-h-[250px] pr-2"></div>
            </div>
        </div>

        <!-- Charts Grid -->
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-12">
            <div class="lg:col-span-2 glass-panel rounded-2xl p-6">
                <h3 class="text-xl font-semibold mb-6">Cumulative Equity Curve</h3>
                <div class="w-full h-[300px]">
                    <canvas id="equityChart"></canvas>
                </div>
            </div>
            <div class="glass-panel rounded-2xl p-6 flex flex-col justify-center items-center">
                 <h3 class="text-xl font-semibold mb-6 w-full text-left">Performance by Symbol</h3>
                 <div class="w-full h-[300px] relative">
                     <canvas id="symbolChart"></canvas>
                 </div>
            </div>
        </div>

        <!-- Table -->
        <div class="glass-panel rounded-2xl overflow-hidden">
            <div class="p-6 border-b border-[rgba(255,255,255,0.05)] flex justify-between items-center flex-wrap gap-4">
                <h3 class="text-xl font-semibold">Trade History</h3>
                <div class="flex gap-2 text-sm font-medium">
                    <button class="filter-btn tbl-filter active" onclick="setTableFilter('all', this)">All Results</button>
                    <button class="filter-btn tbl-filter" onclick="setTableFilter('wins', this)">Wins</button>
                    <button class="filter-btn tbl-filter" onclick="setTableFilter('losses', this)">Losses</button>
                </div>
            </div>
            <div class="overflow-x-auto">
                <table class="w-full text-left">
                    <thead>
                        <tr class="text-muted text-sm uppercase tracking-wider select-none">
                            <th class="p-4 font-medium cursor-pointer hover:text-white transition-colors" onclick="setSort('symbol')">Symbol <span id="sort-symbol"></span></th>
                            <th class="p-4 font-medium cursor-pointer hover:text-white transition-colors" onclick="setSort('start_time')">Open Time <span id="sort-start_time"></span></th>
                            <th class="p-4 font-medium cursor-pointer hover:text-white transition-colors" onclick="setSort('end_time')">Close Time <span id="sort-end_time"></span></th>
                            <th class="p-4 font-medium text-right cursor-pointer hover:text-white transition-colors" onclick="setSort('avg_buy_price')">Avg Buy <span id="sort-avg_buy_price"></span></th>
                            <th class="p-4 font-medium text-right cursor-pointer hover:text-white transition-colors" onclick="setSort('avg_sell_price')">Avg Sell <span id="sort-avg_sell_price"></span></th>
                            <th class="p-4 font-medium text-right cursor-pointer hover:text-white transition-colors" onclick="setSort('pct_profit')">% Return <span id="sort-pct_profit"></span></th>
                            <th class="p-4 font-medium text-right cursor-pointer hover:text-white transition-colors" onclick="setSort('pnl')">PnL ($) <span id="sort-pnl"></span></th>
                        </tr>
                    </thead>
                    <tbody id="trade-tbody" class="mono text-sm">
                        <!-- Populated by JS -->
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        const rawTradeData = {trade_data_json};
        const rawSummaryData = {summary_data_json};

        // State
        let currentPriceFilter = 'all'; // 'all' or 'over50'
        let currentTableFilter = 'all'; // 'all', 'wins', 'losses'
        let currentSortCol = 'end_time';
        let sortAsc = false;
        
        let activeTradeData = [];
        
        let equityChart = null;
        let symbolChart = null;

        // Utilities
        const formatMoney = (val) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(val);
        const formatPct = (val) => (val * 100).toFixed(2) + '%';
        const formatDate = (iso) => new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute:'2-digit', second:'2-digit' });

        document.getElementById('gen-time').textContent = new Date().toLocaleString();

        Chart.defaults.color = '#94a3b8';
        Chart.defaults.font.family = "'JetBrains Mono', monospace";

        function processDataAndRender() {
            // Apply Price Filter
            activeTradeData = rawTradeData.filter(t => {
                if (currentPriceFilter === 'over50') return t.avg_buy_price >= 50;
                return true;
            });

            // Calculate Stats
            let totalPnL = 0;
            let wins = 0;
            let equity = [0];
            let labels = ['Start'];
            let bestTrade = { pnl: -Infinity, symbol: '' };
            let worstTrade = { pnl: Infinity, symbol: '' };
            const symbolPnL = {};

            activeTradeData.forEach((t) => {
                totalPnL += t.pnl;
                equity.push(totalPnL);
                labels.push(new Date(t.end_time).toLocaleTimeString('en-US', {hour:'2-digit', minute:'2-digit'}));
                
                if (t.pnl >= 0) wins++;
                if (t.pnl > bestTrade.pnl) bestTrade = t;
                if (t.pnl < worstTrade.pnl) worstTrade = t;
                
                if (!symbolPnL[t.symbol]) symbolPnL[t.symbol] = 0;
                symbolPnL[t.symbol] += t.pnl;
            });

            // Update DOM Stats
            const totalTrades = activeTradeData.length;
            document.getElementById('total-trades').textContent = totalTrades;
            
            const winRate = totalTrades > 0 ? (wins / totalTrades * 100).toFixed(1) : 0;
            document.getElementById('win-rate').textContent = winRate + '%';
            
            const tPnlEl = document.getElementById('total-pnl');
            tPnlEl.textContent = (totalPnL >= 0 ? '+' : '') + formatMoney(totalPnL);
            tPnlEl.className = `text-3xl font-bold mono ${totalPnL >= 0 ? 'profit-text' : 'loss-text'}`;

            document.getElementById('best-trade').textContent = bestTrade.symbol ? `${bestTrade.symbol} +${formatMoney(bestTrade.pnl)}` : 'N/A';
            document.getElementById('worst-trade').textContent = worstTrade.symbol ? `${worstTrade.symbol} ${formatMoney(worstTrade.pnl)}` : 'N/A';

            // Render Charts
            renderCharts(labels, equity, symbolPnL);

            // Render Table
            renderTable();
            
            // Render Summary Data
            renderSummary();
        }

        function renderSummary() {
            const topList = document.getElementById('top-symbols-list');
            topList.innerHTML = rawSummaryData.top_symbols.map(s => 
                `<div class="flex justify-between border-b border-[rgba(255,255,255,0.05)] pb-2"><span class="font-bold text-white">${s.symbol}</span><span class="mono text-muted">${formatMoney(s.volume)}</span></div>`
            ).join('');
            
            const openList = document.getElementById('open-positions-list');
            openList.innerHTML = rawSummaryData.open_positions.length ? rawSummaryData.open_positions.map(s => 
                `<div class="flex justify-between border-b border-[rgba(255,255,255,0.05)] pb-2"><span class="font-bold text-white">${s.symbol}</span><span class="mono text-muted">${s.qty.toFixed(2)} sh</span></div>`
            ).join('') : '<p class="text-muted text-sm italic">No open positions.</p>';
            
            const unmatchList = document.getElementById('unmatched-sells-list');
            unmatchList.innerHTML = rawSummaryData.unmatched_sells.length ? rawSummaryData.unmatched_sells.map(s => 
                `<div class="flex justify-between border-b border-[rgba(255,255,255,0.05)] pb-2"><span class="font-bold text-white">${s.symbol}</span><span class="mono text-muted">${s.qty.toFixed(2)} sh</span></div>`
            ).join('') : '<p class="text-muted text-sm italic">No unmatched sells.</p>';
        }

        function renderCharts(labels, equity, symbolPnL) {
            if (equityChart) equityChart.destroy();
            if (symbolChart) symbolChart.destroy();

            equityChart = new Chart(document.getElementById('equityChart'), {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Cumulative PnL ($)',
                        data: equity,
                        borderColor: '#6366f1',
                        backgroundColor: 'rgba(99, 102, 241, 0.1)',
                        borderWidth: 2,
                        pointRadius: 0,
                        pointHitRadius: 10,
                        fill: true,
                        tension: 0.4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } },
                    scales: {
                        x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { maxTicksLimit: 10 } },
                        y: { grid: { color: 'rgba(255,255,255,0.05)' } }
                    }
                }
            });

            const sortedSymbols = Object.keys(symbolPnL).sort((a,b) => symbolPnL[b] - symbolPnL[a]).slice(0, 10);
            const symbolData = sortedSymbols.map(s => symbolPnL[s]);
            const symbolColors = symbolData.map(v => v >= 0 ? '#10b981' : '#ef4444');

            symbolChart = new Chart(document.getElementById('symbolChart'), {
                type: 'bar',
                data: {
                    labels: sortedSymbols,
                    datasets: [{
                        data: symbolData,
                        backgroundColor: symbolColors,
                        borderRadius: 4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { grid: { display: false } },
                        y: { grid: { color: 'rgba(255,255,255,0.05)' } }
                    }
                }
            });
        }

        function renderTable() {
            const tbody = document.getElementById('trade-tbody');
            tbody.innerHTML = '';
            
            document.querySelectorAll('th span').forEach(el => el.textContent = '');
            if (currentSortCol) {
                const icon = sortAsc ? '↑' : '↓';
                const el = document.getElementById('sort-' + currentSortCol);
                if (el) el.textContent = icon;
            }

            let filtered = activeTradeData.filter(t => {
                if (currentTableFilter === 'wins') return t.pnl >= 0;
                if (currentTableFilter === 'losses') return t.pnl < 0;
                return true;
            });

            if (currentSortCol) {
                filtered.sort((a, b) => {
                    let valA = a[currentSortCol];
                    let valB = b[currentSortCol];
                    if (typeof valA === 'string') {
                        return sortAsc ? valA.localeCompare(valB) : valB.localeCompare(valA);
                    }
                    return sortAsc ? valA - valB : valB - valA;
                });
            }

            filtered.forEach(t => {
                const isWin = t.pnl >= 0;
                const colorClass = isWin ? 'profit-text' : 'loss-text';
                const sign = isWin ? '+' : '';

                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td class="p-4 font-bold text-white">${t.symbol}</td>
                    <td class="p-4 text-muted">${formatDate(t.start_time)}</td>
                    <td class="p-4 text-muted">${formatDate(t.end_time)}</td>
                    <td class="p-4 text-right">$${t.avg_buy_price.toFixed(2)}</td>
                    <td class="p-4 text-right">$${t.avg_sell_price.toFixed(2)}</td>
                    <td class="p-4 text-right ${colorClass}">${sign}${formatPct(t.pct_profit)}</td>
                    <td class="p-4 text-right font-bold ${colorClass}">${sign}${formatMoney(t.pnl)}</td>
                `;
                tbody.appendChild(tr);
            });
        }

        window.setPriceFilter = function(mode) {
            currentPriceFilter = mode;
            document.getElementById('filter-all-price').classList.toggle('active', mode === 'all');
            document.getElementById('filter-50-price').classList.toggle('active', mode === 'over50');
            processDataAndRender();
        };

        window.setTableFilter = function(filter, btnElement) {
            currentTableFilter = filter;
            document.querySelectorAll('.tbl-filter').forEach(btn => btn.classList.remove('active'));
            btnElement.classList.add('active');
            renderTable(); // only re-renders table
        };

        window.setSort = function(col) {
            if (currentSortCol === col) {
                sortAsc = !sortAsc;
            } else {
                currentSortCol = col;
                sortAsc = col === 'symbol' || col === 'start_time' || col === 'end_time' ? true : false;
            }
            renderTable();
        };

        // Initial load
        processDataAndRender();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    trades = parse_log()
    cycles = analyze_cycles(trades)
    summary = analyze_summary(trades)
    
    cycles_json = json.dumps(cycles)
    summary_json = json.dumps(summary)
    html_out = html_template.replace("{trade_data_json}", cycles_json).replace("{summary_data_json}", summary_json)
    
    with open(output_html, "w") as f:
        f.write(html_out)
        
    print(f"Generated dashboard at {output_html} with {len(cycles)} completed trade cycles.")
