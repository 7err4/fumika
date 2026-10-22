import { app } from "../../scripts/app.js";
import { ComfyWidgets } from "../../scripts/widgets.js";

const DATASET_INFO = `=== Dataset Folder Structure (sd-scripts) ===

train_data_dir/
  <repeats>_<concept>/
      image1.png
      image1.txt    <- matching caption file
      image2.jpg
      image2.txt

Example:  10_ohwx/  (10 repeats, trigger "ohwx")

Caption file format (one line per .txt):
  ohwx, a woman with red hair, sitting, park

Tips:
  5-20 repeats for small datasets (10-30 imgs)
  1-5  repeats for large datasets (100+ imgs)
  Keep trigger word consistent across captions`;

const NODES_WITH_DATASET_INFO = [
    "AnimaTrainingWizard",
    "AnimaBasicParams",
];

app.registerExtension({
    name: "AnimaLoRA.DatasetInfo",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (!NODES_WITH_DATASET_INFO.includes(nodeData.name)) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);

            const w = ComfyWidgets["STRING"](this, "dataset_info", ["STRING", { multiline: true }], app);
            w.widget.value = DATASET_INFO;
            w.widget.inputEl.readOnly = true;
            w.widget.inputEl.style.opacity = 0.85;
            w.widget.inputEl.style.fontFamily = "monospace";
            w.widget.inputEl.style.fontSize = "11px";
            w.widget.inputEl.style.lineHeight = "1.4";
            w.widget.inputEl.style.background = "rgba(40, 60, 80, 0.35)";
            w.widget.inputEl.style.border = "1px solid rgba(100, 140, 180, 0.3)";
            w.widget.inputEl.style.borderRadius = "4px";
            w.widget.inputEl.style.color = "#c0d0e0";

            // Don't serialize this widget into workflow JSON
            w.widget.serializeValue = async () => undefined;

            // Force the node to be tall enough to show the full text
            const lineCount = DATASET_INFO.split("\n").length;
            const infoHeight = lineCount * 16 + 20;
            const currentWidgetsHeight = (this.widgets?.length || 0) * 28;
            const newHeight = currentWidgetsHeight + infoHeight + 60;
            this.size[1] = Math.max(this.size[1], newHeight);
            this.setDirtyCanvas(true, true);
        };
    },
});
