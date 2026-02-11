
// app.js - Advanced Dashboard Logic

const API_BASE = "/api";
const SYMBOL_CACHE = {};

async function updateDashboard() {
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
        renderHoldingsTable(positions);
        renderLogs(activity);

    } catch (e) {
        console.error("Dashboard Sync Error:", e);
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
    const container = document.getElementById("positions-container");
    const badge = document.getElementById("pos-count-badge");

    badge.innerText = `${positions.length} Active`;
    container.innerHTML = "";

    if (positions.length === 0) {
        container.innerHTML = `<div style="text-align:center; padding: 40px; color: #64748b;">No active positions</div>`;
        return;
    }

    positions.forEach(pos => {
        const mktPrice = pos.market_price || pos.avg_cost; // Fallback
        const marketVal = pos.position * mktPrice;
        const costBasis = pos.position * pos.avg_cost;
        const pnl = marketVal - costBasis;
        const pnlPct = costBasis !== 0 ? (pnl / costBasis) * 100 : 0;

        const card = document.createElement("div");
        card.className = "card position-card";

        const isLong = pos.position > 0;
        const side = isLong ? "LONG" : "SHORT";
        const colorClass = pnl >= 0 ? "text-green" : "text-red";
        const bgClass = pnl >= 0 ? "bg-green-soft" : "bg-red-soft";
        const arrow = pnl >= 0 ? "▲" : "▼";

        card.innerHTML = `
            <div class="pos-header">
                <div class="pos-ticker-group">
                    <div class="ticker-box">${pos.symbol}</div>
                    <div>
                        <div class="pos-name">${pos.symbol} Inc.</div>
                        <div class="pos-side">${side} @ ${formatCurrency(pos.avg_cost)}</div>
                    </div>
                </div>
                <div class="pos-pnl">
                    <span class="pnl-amount ${colorClass}">${(pnl >= 0 ? "+" : "")}${formatCurrency(pnl)}</span>
                    <span class="pnl-percent ${bgClass}">${arrow} ${pnlPct.toFixed(2)}%</span>
                </div>
            </div>
            <div class="pos-stats">
                <div class="stat-box">
                    <span class="stat-label">Qty</span>
                    <span class="stat-val">${pos.position}</span>
                </div>
                <div class="stat-box">
                    <span class="stat-label">Last</span>
                    <span class="stat-val">${formatCurrency(mktPrice)}</span>
                </div>
                <div class="stat-box">
                    <span class="stat-label">Mkt Val</span>
                    <span class="stat-val">${formatCurrency(marketVal)}</span>
                </div>
            </div>
        `;
        container.appendChild(card);
    });
}

function renderPendingOrders(orders) {
    const container = document.getElementById("pending-orders-list");
    const badge = document.getElementById("pending-orders-badge");

    if (!container || !badge) return; // Guard clause if HTML updated slowly

    badge.innerText = orders ? orders.length : 0;
    container.innerHTML = "";

    if (!orders || orders.length === 0) {
        container.innerHTML = `<div style="text-align:center; padding: 20px; color: #64748b;">No pending orders</div>`;
        return;
    }

    orders.forEach(order => {
        const el = document.createElement("div");
        el.className = "strategy-item"; // Reuse style for now
        el.style.borderLeftColor = "#f59e0b"; // Orange/Yellow

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
            updateDashboard(); // Refresh immediately
        } else {
            alert("Failed to cancel: " + (data.error || "Unknown error"));
        }
    } catch (e) {
        alert("Error cancelling order: " + e);
    }
}

function renderHoldingsTable(positions) {
    const tbody = document.getElementById("holdings-table-body");
    tbody.innerHTML = "";

    positions.forEach(pos => {
        const val = pos.position * pos.avg_cost;
        const row = document.createElement("tr");
        row.innerHTML = `
            <td><b>${pos.symbol}</b></td>
            <td class="val-cell">${pos.position}</td>
            <td class="val-cell">${formatCurrency(pos.avg_cost)}</td>
            <td class="val-cell">${formatCurrency(val)}</td>
        `;
        tbody.appendChild(row);
    });
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
setInterval(updateDashboard, 3000);
