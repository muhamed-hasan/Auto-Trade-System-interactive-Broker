
// app.js - Advanced Dashboard Logic

const API_BASE = "/api";
const SYMBOL_CACHE = {};
let currentTab = 'dashboard';

async function updateDashboard() {
    // Only update dashboard elements if tab is active
    if (currentTab !== 'dashboard') return;

    try {
        const [account, pnl, positions, activity, status, openOrders] = await Promise.all([
            fetch(`${API_BASE}/account`).then(r => r.json()),
            fetch(`${API_BASE}/pnl`).then(r => r.json()),
            fetch(`${API_BASE}/positions`).then(r => r.json()),
            fetch(`${API_BASE}/activity`).then(r => r.json()),
            fetch(`${API_BASE}/status`).then(r => r.json()),
            fetch(`${API_BASE}/orders/open`).then(r => r.json())
        ]);

        updateHeader(status);
        updateAccountMetrics(account, pnl);
        renderPositionsList(positions);
        renderPendingOrders(openOrders);
        renderLogs(activity);

    } catch (e) {
        console.error("Dashboard Sync Error:", e);
    }
}

async function updateHistory() {
    try {
        const orders = await fetch(`${API_BASE}/history`).then(r => r.json());
        renderHistoryTable(orders);
    } catch (e) {
        console.error("History Fetch Error:", e);
    }
}

function switchTab(tabName) {
    currentTab = tabName;

    // UI Toggle
    document.querySelectorAll('.nav-tab').forEach(b => b.classList.remove('active'));
    event.target.classList.add('active');

    if (tabName === 'dashboard') {
        document.getElementById('tab-dashboard').style.display = 'block';
        document.getElementById('tab-history').style.display = 'none';
        updateDashboard();
    } else {
        document.getElementById('tab-dashboard').style.display = 'none';
        document.getElementById('tab-history').style.display = 'block';
        updateHistory();
    }
}

function updateHeader(status) {
    // Mode Badge
    const badge = document.getElementById("mode-badge");
    badge.innerText = (status.mode || "PAPER").toUpperCase();
    badge.className = status.mode === 'live' ? "mode-badge live" : "mode-badge";

    // Connection Status
    const dot = document.getElementById("ib-status-dot");
    const text = document.getElementById("ib-status-text");

    if (status.ib_connected) {
        dot.className = "status-dot active";
        text.innerText = "IB Connection: ACTIVE";
    } else {
        dot.className = "status-dot";
        text.innerText = "IB Connection: DISCONNECTED";
    }

    // Also update common metrics even if on history tab? 
    // Usually keep header live. But updateDashboard skips.
    // For simplicity, dashboard only updates when active.

    // Market Status
    const mktTitle = document.getElementById("market-status-title");
    const mktDot = document.getElementById("market-status-dot");
    const mktText = document.getElementById("market-status-text");
    const mktSub = document.getElementById("market-status-sub");

    if (status.market_status) {
        const isOpen = status.market_status.status === 'open';
        mktTitle.innerText = isOpen ? "MARKET OPEN" : "MARKET CLOSED";

        // Update dot class
        mktDot.className = isOpen ? "market-indicator status-dot active" : "market-indicator status-dot";
        // Optionally change title color
        mktTitle.className = isOpen ? "card-title text-green" : "card-title text-gray";

        // Truncate long reason text if needed
        let reason = status.market_status.reason || (isOpen ? "Trading Active" : "Trading Halted");
        if (reason.length > 50) reason = reason.substring(0, 47) + "...";
        mktText.innerText = reason;

        mktSub.innerText = "Source: " + (status.market_status.source || "Unknown");
    }

    // Market Indices
    const tickerDiv = document.getElementById("market-ticker");
    if (status.indices) {
        tickerDiv.style.display = "flex";

        const updateTicker = (id, data, isCurrency) => {
            const el = document.getElementById(id);
            if (!data || !data.value) {
                el.innerText = "---";
                return;
            }
            // User requested percentage change displayed
            const val = data.change;
            const sign = val >= 0 ? "+" : "";
            const colorClass = val >= 0 ? "text-green" : "text-red";

            // Format: "+0.52%"
            el.innerHTML = `<span class="${colorClass}">${sign}${val.toFixed(2)}%</span>`;
        };

        updateTicker("spy-val", status.indices.SPY, true);
        updateTicker("vix-val", status.indices.VIX, false);
    }
}

function updateAccountMetrics(account, pnl) {
    const equity = account.NetLiquidation || 0;
    const bp = account.BuyingPower || 0;

    document.getElementById("equity-val").innerText = formatCurrency(equity);
    document.getElementById("bp-val").innerText = formatCurrency(bp);

    // BP Progress
    const util = 45; // Placeholder
    document.getElementById("bp-progress").style.width = "45%";
    document.getElementById("bp-util").innerText = "45";

    // PnL
    const r = pnl.realized || 0;
    const u = pnl.unrealized || 0;
    const total = r + u;

    setPnLValue("daily-pnl-total", total);
    setPnLValue("pnl-realized", r);
    setPnLValue("pnl-unrealized", u);
}

function setPnLValue(id, val) {
    const el = document.getElementById(id);
    el.innerText = (val >= 0 ? "+" : "") + formatCurrency(val);
    el.className = val >= 0 ? "value-number text-green" : "value-number text-red";
}

function renderPositionsList(positions) {
    const tbody = document.getElementById("positions-table-body");
    const noPosMsg = document.getElementById("no-positions-msg");
    const badge = document.getElementById("pos-count-badge");

    badge.innerText = `${positions.length} Active`;
    tbody.innerHTML = "";

    if (positions.length === 0) {
        noPosMsg.style.display = "block";
        tbody.closest("table").style.display = "none";
        return;
    }

    noPosMsg.style.display = "none";
    tbody.closest("table").style.display = "table";

    positions.forEach(pos => {
        const mktPrice = pos.market_price || pos.avg_cost; // Fallback
        const marketVal = pos.position * mktPrice;
        const costBasis = pos.position * pos.avg_cost;
        const pnl = marketVal - costBasis;
        const pnlPct = costBasis !== 0 ? (pnl / costBasis) * 100 : 0;

        const isLong = pos.position > 0;
        const colorClass = pnl >= 0 ? "text-green" : "text-red";

        const row = document.createElement("tr");
        row.innerHTML = `
            <td style="padding-left: 16px;">
                <div style="font-weight:600;">${pos.symbol}</div>
                <div style="font-size:0.7rem; color:var(--text-secondary);">${isLong ? 'LONG' : 'SHORT'}</div>
            </td>
            <td style="text-align:right">${pos.position}</td>
            <td style="text-align:right">${formatCurrency(pos.avg_cost)}</td>
            <td style="text-align:right">${formatCurrency(mktPrice)}</td>
            <td style="text-align:right">
                <div class="${colorClass}" style="font-weight:600;">${(pnl >= 0 ? "+" : "")}${formatCurrency(pnl)}</div>
                <div class="${colorClass}" style="font-size:0.7rem;">${pnlPct.toFixed(2)}%</div>
            </td>
            <td style="text-align:right; font-weight:600;">${formatCurrency(marketVal)}</td>
            <td style="text-align:right; padding-right: 16px;">
                <button onclick="closePosition('${pos.symbol}')" 
                    style="background:none; border:none; color:var(--accent-red); cursor:pointer; font-size:0.8rem; font-weight:600; padding:4px 8px; border-radius:4px;">
                    Close
                </button>
            </td>
        `;
        tbody.appendChild(row);
    });
}

async function closePosition(symbol) {
    if (!confirm(`Are you sure you want to CLOSE your ${symbol} position?`)) return;

    try {
        const response = await fetch('/api/positions/close', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol: symbol })
        });
        const result = await response.json();

        if (result.status === 'closed') {
            // Optimistically remove or reload
            alert(`Close order submitted for ${symbol}`);
            updateDashboard();
        } else {
            alert("Error: " + (result.error || "Unknown error"));
        }
    } catch (e) {
        console.error(e);
        alert("Failed to send close request");
    }
}

function renderPendingOrders(orders) {
    const container = document.getElementById("pending-orders-list");
    const badge = document.getElementById("pending-orders-badge");

    if (!container || !badge) return;

    badge.innerText = orders ? orders.length : 0;
    container.innerHTML = "";

    if (!orders || orders.length === 0) {
        container.innerHTML = `<div style="text-align:center; padding: 20px; color: #64748b;">No pending orders</div>`;
        return;
    }

    orders.forEach(order => {
        const el = document.createElement("div");
        el.className = "strategy-item";
        el.style.borderLeftColor = "#f59e0b";

        el.innerHTML = `
            <div class="strat-info">
                <h4>${order.action.toUpperCase()} ${order.quantity} ${order.symbol}</h4>
                <p>${order.type} @ ${order.price > 0 ? formatCurrency(order.price) : 'MKT'} • ${order.status}</p>
            </div>
            <button onclick="cancelOrder(${order.orderId})" style="background:var(--accent-red); border:none; color:white; padding:6px 12px; border-radius:4px; cursor:pointer; font-size:0.75rem;">Cancel</button>
        `;
        container.appendChild(el);
    });
}

function renderHistoryTable(orders) {
    const tbody = document.getElementById("history-table-body");
    tbody.innerHTML = "";

    if (!orders || orders.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:20px; color:#64748b;">No trades today</td></tr>`;
        return;
    }

    orders.forEach(o => {
        const row = document.createElement("tr");
        const ts = new Date(o.created_at).toLocaleTimeString();
        const statusColor = o.status === 'Filled' ? 'text-green' : (o.status === 'Cancelled' ? 'text-red' : '');

        row.innerHTML = `
            <td>${ts}</td>
            <td style="font-weight:600; color:${o.action === 'buy' ? 'var(--accent-green)' : 'var(--accent-red)'}">${o.action.toUpperCase()}</td>
            <td><b>${o.ticker}</b></td>
            <td>${o.quantity}</td>
            <td>${o.fill_price ? formatCurrency(o.fill_price) : '-'}</td>
            <td class="${statusColor}">${o.status}</td>
        `;
        tbody.appendChild(row);
    });
}

async function cancelOrder(orderId) {
    if (!confirm("Are you sure you want to cancel this order?")) return;

    try {
        const res = await fetch(`${API_BASE}/orders/cancel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ order_id: orderId })
        });
        const data = await res.json();
        if (data.status === 'cancelled') {
            alert("Order Cancelled");
            updateDashboard();
        } else {
            alert("Failed to cancel: " + (data.error || "Unknown error"));
        }
    } catch (e) {
        alert("Error cancelling order: " + e);
    }
}



function renderLogs(activity) {
    const logsContainer = document.getElementById("logs-feed");
    const entries = [];

    if (activity.signals) {
        activity.signals.forEach(s => {
            entries.push({
                time: new Date(s.received_at),
                type: 'SIGNAL',
                msg: `Signal Received: ${s.action.toUpperCase()} ${s.ticker} (Qty: ${s.quantity})`,
                status: s.status
            });
        });
    }

    if (activity.orders) {
        activity.orders.forEach(o => {
            entries.push({
                time: new Date(o.created_at),
                type: 'ORDER',
                msg: `Order ${o.status}: ${o.action} ${o.ticker}`,
                status: o.status
            });
        });
    }

    entries.sort((a, b) => b.time - a.time);

    logsContainer.innerHTML = "";

    entries.forEach(log => {
        const div = document.createElement("div");
        div.className = "log-entry";
        const timeStr = log.time.toLocaleTimeString([], { hour12: false });

        let colorClass = "log-msg";
        if (log.status.includes('error') || log.status.includes('rejected')) colorClass = "log-error";
        else if (log.status === 'filled') colorClass = "log-success";
        else if (log.status === 'submitted') colorClass = "log-info";

        div.innerHTML = `
            <span class="log-time">[${timeStr}]</span>
            <span class="${colorClass}">${log.msg}</span>
        `;
        logsContainer.appendChild(div);
    });
}

function formatCurrency(num) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2
    }).format(num);
}

// Init
updateDashboard();
// Poll every 3 seconds for active content
setInterval(() => {
    if (currentTab === 'dashboard') {
        updateDashboard();
    }
}, 3000);
