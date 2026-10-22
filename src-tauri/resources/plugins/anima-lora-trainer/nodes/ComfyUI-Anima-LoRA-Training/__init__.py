"""
ComfyUI-Anima-LoRA-Training
============================
A ComfyUI custom node pack for managing and triggering Anima LoRA training
via kohya-ss/sd-scripts.

Two workflow modes:

  AUTOMATIC (Wizard):
    [SD-Scripts Manager] -> [Model Selector] -> [Training Wizard] -> [Training Launcher]

  MANUAL (with optional override chain):
    [SD-Scripts Manager] -> [Model Selector] -> [Basic Params] -> [Advanced Params] -> [Memory Optimizer] -> [Training Launcher]

  HYBRID (Wizard + tweaks):
    [SD-Scripts Manager] -> [Model Selector] -> [Training Wizard] -> [Advanced Params] -> [Memory Optimizer] -> [Training Launcher]
"""

# Relative node imports — only resolvable when loaded as part of a package,
# which is what ComfyUI does. Wrapped in try/except so the module can also
# be imported standalone by tooling like pytest (which collects this file
# as a Package before reaching the tests/ subfolder); in that mode we
# simply expose empty mappings.
try:
    from .nodes.sdscripts_manager import AnimaSDScriptsManager
    from .nodes.model_selector import AnimaModelSelector
    from .nodes.training_wizard import AnimaTrainingWizard
    from .nodes.training_params import AnimaBasicParams, AnimaAdvancedParams, AnimaMemoryOptimizer
    from .nodes.training_launcher import AnimaTrainingLauncher
    from .nodes.config_preview import AnimaConfigPreview
    from .nodes.model_downloader import AnimaModelDownloader
    from .nodes.vram_estimator import AnimaVRAMEstimator

    NODE_CLASS_MAPPINGS = {
        "AnimaSDScriptsManager": AnimaSDScriptsManager,
        "AnimaModelSelector": AnimaModelSelector,
        "AnimaTrainingWizard": AnimaTrainingWizard,
        "AnimaBasicParams": AnimaBasicParams,
        "AnimaAdvancedParams": AnimaAdvancedParams,
        "AnimaMemoryOptimizer": AnimaMemoryOptimizer,
        "AnimaTrainingLauncher": AnimaTrainingLauncher,
        "AnimaConfigPreview": AnimaConfigPreview,
        "AnimaModelDownloader": AnimaModelDownloader,
        "AnimaVRAMEstimator": AnimaVRAMEstimator,
    }

    NODE_DISPLAY_NAME_MAPPINGS = {
        "AnimaSDScriptsManager": "SD-Scripts Manager (Anima)",
        "AnimaModelSelector": "Model Selector (Anima)",
        "AnimaTrainingWizard": "Training Wizard (Anima)",
        "AnimaBasicParams": "Basic Params (Anima)",
        "AnimaAdvancedParams": "Advanced Params (Anima)",
        "AnimaMemoryOptimizer": "Memory Optimizer (Anima)",
        "AnimaTrainingLauncher": "Training Launcher (Anima)",
        "AnimaConfigPreview": "Config Preview (Anima)",
        "AnimaModelDownloader": "Model Downloader (Anima)",
        "AnimaVRAMEstimator": "VRAM Estimator (Anima)",
    }
except ImportError:
    # Standalone import (pytest, repl). Node mappings remain empty,
    # which is fine — ComfyUI never enters this branch.
    NODE_CLASS_MAPPINGS = {}
    NODE_DISPLAY_NAME_MAPPINGS = {}

WEB_DIRECTORY = "./js"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
