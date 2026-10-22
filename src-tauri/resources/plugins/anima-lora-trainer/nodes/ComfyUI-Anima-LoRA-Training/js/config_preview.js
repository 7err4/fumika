import { app } from "../../scripts/app.js";
import { ComfyWidgets } from "../../scripts/widgets.js";

app.registerExtension({
    name: "AnimaLoRA.ConfigPreview",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "AnimaConfigPreview") {
            // When the node is created, add a text widget to show output
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                if (onNodeCreated) onNodeCreated.apply(this, arguments);
                const w = ComfyWidgets["STRING"](this, "config_preview", ["STRING", { multiline: true }], app);
                w.widget.inputEl.readOnly = true;
                w.widget.inputEl.style.opacity = 0.85;
                w.widget.inputEl.style.fontFamily = "monospace";
                w.widget.inputEl.style.fontSize = "11px";
            };

            // When execution result arrives, update the text widget
            const onExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function (message) {
                if (onExecuted) onExecuted.apply(this, arguments);
                if (message?.text) {
                    const text = Array.isArray(message.text) ? message.text.join("\n") : message.text;
                    // Find the text widget we created
                    const w = this.widgets?.find(w => w.name === "config_preview");
                    if (w) {
                        w.value = text;
                        // Resize node to fit content
                        const lines = text.split("\n").length;
                        const newHeight = Math.max(300, Math.min(800, lines * 15 + 100));
                        this.size[1] = newHeight;
                        app.graph.setDirtyCanvas(true);
                    }
                }
            };
        }
    },
});
