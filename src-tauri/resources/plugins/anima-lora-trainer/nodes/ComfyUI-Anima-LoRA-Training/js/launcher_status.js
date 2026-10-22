import { app } from "../../scripts/app.js";
import { ComfyWidgets } from "../../scripts/widgets.js";

// Shows the Training Launcher's status message directly on the node.
// Before this, errors (failed dependency check, blocked dataset, terminal
// spawn failure) went into the status_message OUTPUT, which the stock
// workflows don't display anywhere -> "training doesn't start, no error".
app.registerExtension({
    name: "AnimaLoRA.LauncherStatus",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "AnimaTrainingLauncher") {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                if (onNodeCreated) onNodeCreated.apply(this, arguments);
                const w = ComfyWidgets["STRING"](this, "launch_status", ["STRING", { multiline: true }], app);
                w.widget.value = "Status will appear here after you run the workflow.";
                w.widget.inputEl.readOnly = true;
                w.widget.inputEl.style.opacity = 0.85;
                w.widget.inputEl.style.fontFamily = "monospace";
                w.widget.inputEl.style.fontSize = "11px";
                w.widget.serializeValue = async () => undefined;
            };

            const onExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function (message) {
                if (onExecuted) onExecuted.apply(this, arguments);
                if (message?.text) {
                    const text = Array.isArray(message.text) ? message.text.join("\n") : message.text;
                    const w = this.widgets?.find(x => x.name === "launch_status");
                    if (w) {
                        w.value = text;
                        const lines = text.split("\n").length;
                        const newHeight = Math.max(this.size[1], Math.min(760, lines * 15 + 260));
                        this.size[1] = newHeight;
                        app.graph.setDirtyCanvas(true);
                    }
                }
            };
        }
    },
});
