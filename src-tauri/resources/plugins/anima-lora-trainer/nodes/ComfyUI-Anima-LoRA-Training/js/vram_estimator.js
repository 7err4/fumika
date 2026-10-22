import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { ComfyWidgets } from "../../scripts/widgets.js";

// Node types the server-side chain evaluator understands. Anything else
// (Reroute, primitives, ...) is traversed through but not sent.
const PARAM_NODE_TYPES = new Set([
    "AnimaTrainingWizard",
    "AnimaBasicParams",
    "AnimaAdvancedParams",
    "AnimaMemoryOptimizer",
]);

const POLL_MS = 1200;

// Keep in sync with build_chart() component order in nodes/vram_estimator.py
const COMPONENT_COLORS = {
    "Model on GPU": "#4a90d9",
    "Working memory": "#e2903a",
    "LoRA + trainer": "#9b6dd6",
    "Text encoder": "#3fbfb0",
    "System overhead": "#8a8a8a",
};
const VERDICT_COLORS = { fits: "#5cb85c", tight: "#e2b93a", oom: "#d9534f", info: "#8a8a8a" };

const ROW_H = 16;
const CHART_PAD = 8;
// 5 component rows + gap + stacked total row + gap + scale/legend row
const CHART_H = CHART_PAD * 2 + 5 * ROW_H + 10 + ROW_H + 6 + 14;

function drawChart(ctx, node, widgetWidth, y, chart) {
    const margin = 12;
    const x0 = margin;
    const w = widgetWidth - margin * 2;
    ctx.save();

    // Panel background
    ctx.fillStyle = "#1b1b1b";
    ctx.beginPath();
    ctx.roundRect(x0, y, w, CHART_H, 4);
    ctx.fill();

    if (!chart) {
        ctx.fillStyle = "#777";
        ctx.font = "11px monospace";
        ctx.textAlign = "center";
        ctx.fillText("edit params or run to see the VRAM breakdown", x0 + w / 2, y + CHART_H / 2 + 4);
        ctx.restore();
        return;
    }

    const labelW = 100;
    const valueW = 52;
    const barX = x0 + CHART_PAD + labelW;
    const barW = w - CHART_PAD * 2 - labelW - valueW;
    // Scale bars against GPU size when known (so "how close am I to the
    // limit" is visually literal), else against the high estimate.
    const scaleMax = Math.max(chart.gpu > 0 ? chart.gpu : 0, chart.high, 0.1);

    ctx.font = "10px monospace";
    ctx.textBaseline = "middle";
    let ry = y + CHART_PAD + ROW_H / 2;

    // ── Per-component rows ──
    for (const [label, gb] of chart.components) {
        ctx.fillStyle = "#aaa";
        ctx.textAlign = "right";
        ctx.fillText(label, barX - 6, ry);
        // track
        ctx.fillStyle = "#2b2b2b";
        ctx.fillRect(barX, ry - 5, barW, 10);
        // fill
        const bw = Math.max(gb > 0 ? 2 : 0, (gb / scaleMax) * barW);
        ctx.fillStyle = COMPONENT_COLORS[label] ?? "#888";
        ctx.fillRect(barX, ry - 5, Math.min(bw, barW), 10);
        // value
        ctx.fillStyle = "#ccc";
        ctx.textAlign = "left";
        ctx.fillText(gb.toFixed(1) + " GB", barX + barW + 6, ry);
        ry += ROW_H;
    }

    // ── Stacked total row ──
    ry += 10;
    ctx.fillStyle = "#aaa";
    ctx.textAlign = "right";
    ctx.fillText("TOTAL", barX - 6, ry);
    ctx.fillStyle = "#2b2b2b";
    ctx.fillRect(barX, ry - 6, barW, 12);
    let sx = barX;
    for (const [label, gb] of chart.components) {
        const sw = (gb / scaleMax) * barW;
        ctx.fillStyle = COMPONENT_COLORS[label] ?? "#888";
        ctx.fillRect(sx, ry - 6, Math.max(sw, 0), 12);
        sx += sw;
    }
    // Uncertainty whisker (low..high)
    const lowX = barX + (chart.low / scaleMax) * barW;
    const highX = barX + Math.min(chart.high / scaleMax, 1) * barW;
    ctx.strokeStyle = "#eee";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(lowX, ry);
    ctx.lineTo(highX, ry);
    ctx.moveTo(lowX, ry - 4);
    ctx.lineTo(lowX, ry + 4);
    ctx.moveTo(highX, ry - 4);
    ctx.lineTo(highX, ry + 4);
    ctx.stroke();
    ctx.fillStyle = VERDICT_COLORS[chart.verdict] ?? "#ccc";
    ctx.textAlign = "left";
    ctx.fillText(chart.total.toFixed(1) + " GB", barX + barW + 6, ry);

    // GPU limit marker
    if (chart.gpu > 0) {
        const gx = barX + Math.min(chart.gpu / scaleMax, 1) * barW;
        ctx.strokeStyle = VERDICT_COLORS[chart.verdict] ?? "#fff";
        ctx.lineWidth = 2;
        ctx.setLineDash([3, 2]);
        ctx.beginPath();
        ctx.moveTo(gx, y + CHART_PAD - 2);
        ctx.lineTo(gx, ry + 8);
        ctx.stroke();
        ctx.setLineDash([]);
    }

    // ── Footer: GPU label ──
    ry += ROW_H + 2;
    ctx.font = "9px monospace";
    ctx.fillStyle = "#888";
    ctx.textAlign = "left";
    const gpuTxt = chart.gpu > 0
        ? `dashed line = your GPU (${chart.gpu} GB), whisker = ±20% band`
        : "set gpu_vram_gb for a fits/OOM verdict";
    ctx.fillText(gpuTxt, barX, ry);

    ctx.restore();
}

function collectChain(node) {
    // Walk upstream from the estimator's training_params input,
    // gathering {type, widgets} for each known param node.
    const chain = [];
    let current = node;
    let guard = 0;
    while (current && guard++ < 32) {
        const input = current.inputs?.find((i) => i.name === "training_params" || i.type === "TRAINING_PARAMS");
        if (!input || input.link == null) break;
        const link = app.graph.links[input.link];
        if (!link) break;
        const upstream = app.graph.getNodeById(link.origin_id);
        if (!upstream) break;
        if (PARAM_NODE_TYPES.has(upstream.type)) {
            const widgets = {};
            for (const w of upstream.widgets ?? []) {
                if (w.name && w.type !== "button") widgets[w.name] = w.value;
            }
            chain.push({ type: upstream.type, widgets });
        }
        current = upstream; // keep walking (through Reroute etc. too)
    }
    return chain.reverse(); // upstream-first order for the server
}

app.registerExtension({
    name: "AnimaLoRA.VRAMEstimator",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "AnimaVRAMEstimator") {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                if (onNodeCreated) onNodeCreated.apply(this, arguments);

                // ── Bar-chart widget (canvas-drawn) ──
                const self = this;
                const chartWidget = {
                    name: "vram_chart",
                    type: "vram_chart",
                    value: null,
                    draw(ctx, node, w, y) {
                        drawChart(ctx, node, w, y, this.value);
                    },
                    computeSize(width) {
                        return [width ?? 200, CHART_H];
                    },
                    // Nothing to serialize — chart data is derived state.
                    serializeValue() { return null; },
                };
                this.addCustomWidget(chartWidget);
                this._vramChartWidget = chartWidget;

                // ── Text report widget ──
                const w = ComfyWidgets["STRING"](this, "vram_report", ["STRING", { multiline: true }], app);
                w.widget.inputEl.readOnly = true;
                w.widget.inputEl.style.opacity = 0.85;
                w.widget.inputEl.style.fontFamily = "monospace";
                w.widget.inputEl.style.fontSize = "11px";

                // ── Live estimation loop ──
                // Poll the upstream widget state; when it changes, ask the
                // server to re-derive params and re-estimate. The server
                // runs the same Python the queue would, so this number
                // matches an actual run — no logic duplicated in JS.
                this._vramLastHash = "";
                this._vramBusy = false;
                this._vramTimer = setInterval(async () => {
                    if (this._vramBusy || !this.graph) return;
                    try {
                        const chain = collectChain(this);
                        const gpu = this.widgets?.find((x) => x.name === "gpu_vram_gb")?.value ?? 0;
                        const payload = { chain, gpu_vram_gb: gpu };
                        const hash = JSON.stringify(payload);
                        if (hash === this._vramLastHash) return;
                        this._vramBusy = true;
                        const resp = await api.fetchApi("/anima_lora/estimate_vram", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: hash,
                        });
                        const data = await resp.json();
                        this._vramLastHash = hash;
                        const rw = this.widgets?.find((x) => x.name === "vram_report");
                        if (rw && data?.report) rw.value = data.report;
                        this._vramChartWidget.value = data?.chart ?? null;
                        app.graph.setDirtyCanvas(true);
                    } catch (e) {
                        // Endpoint missing (old server) or transient error —
                        // stay quiet; the post-run report still works.
                    } finally {
                        this._vramBusy = false;
                    }
                }, POLL_MS);
            };

            const onRemoved = nodeType.prototype.onRemoved;
            nodeType.prototype.onRemoved = function () {
                if (this._vramTimer) clearInterval(this._vramTimer);
                if (onRemoved) onRemoved.apply(this, arguments);
            };

            // Post-run report from the queue stays authoritative: it is
            // computed from the REAL params object (including anything a
            // custom/unknown node contributed) and overwrites the live text.
            const onExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function (message) {
                if (onExecuted) onExecuted.apply(this, arguments);
                if (message?.text) {
                    const text = Array.isArray(message.text) ? message.text.join("\n") : message.text;
                    const w = this.widgets?.find((x) => x.name === "vram_report");
                    if (w) {
                        w.value = text;
                        const lines = text.split("\n").length;
                        const newHeight = Math.max(360, Math.min(760, lines * 15 + 100 + CHART_H));
                        this.size[1] = newHeight;
                    }
                }
                if (message?.chart) {
                    try {
                        const raw = Array.isArray(message.chart) ? message.chart[0] : message.chart;
                        const chart = typeof raw === "string" ? JSON.parse(raw) : raw;
                        if (this._vramChartWidget) this._vramChartWidget.value = chart;
                    } catch (e) { /* malformed chart payload — keep old drawing */ }
                }
                app.graph.setDirtyCanvas(true);
            };
        }
    },
});
