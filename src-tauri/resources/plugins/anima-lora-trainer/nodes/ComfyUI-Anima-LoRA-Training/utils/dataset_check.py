"""
Dataset folder validation for sd-scripts LoRA training.

sd-scripts expects:

    train_data_dir/
      <repeats>_<concept>/     e.g. 10_mychar/
          image1.png
          image1.txt           <- matching caption file

The two mistakes that account for most "training found 0 images" reports:
  1. images placed directly in train_data_dir (not in a repeats subfolder)
  2. subfolders without the <number>_ prefix (sd-scripts silently skips them)

check_dataset() detects both, plus missing/orphan captions, and returns a
structured result. format_dataset_report() renders it in plain language.
Used by the Training Wizard / Basic Params summaries and as a launch gate
in the Training Launcher.
"""

import os
import re

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
_REPEATS_RE = re.compile(r"^(\d+)_(.+)$")


def check_dataset(train_data_dir: str, caption_extension: str = ".txt") -> dict:
    """Validate an sd-scripts dataset folder. Never raises.

    Returns a dict:
      ok:        True when training can find at least one image
      errors:    list[str] - problems that mean training WILL fail
      warnings:  list[str] - problems that mean worse results / surprises
      concepts:  list of dicts (folder, repeats, concept, images,
                 missing_captions, orphan_captions)
      total_images / total_steps_per_epoch: ints (0 when unknown)
    """
    result = {
        "ok": False, "errors": [], "warnings": [], "concepts": [],
        "total_images": 0, "total_steps_per_epoch": 0,
    }
    ext = caption_extension if caption_extension.startswith(".") else "." + caption_extension
    ext = ext.lower()

    path = (train_data_dir or "").strip()
    if not path:
        result["errors"].append("No training folder set yet (train_data_dir is empty).")
        return result
    if not os.path.exists(path):
        result["errors"].append(f"Folder not found: {path}")
        return result
    if not os.path.isdir(path):
        result["errors"].append(f"This is a file, not a folder: {path}")
        return result

    try:
        entries = list(os.scandir(path))
    except OSError as e:
        result["errors"].append(f"Cannot read the folder: {e}")
        return result

    # Mistake #1: images directly in the root
    root_images = [e.name for e in entries if e.is_file()
                   and e.name.lower().endswith(IMAGE_EXTENSIONS)]
    if root_images:
        result["errors"].append(
            f"{len(root_images)} image(s) sit directly in the folder (e.g. "
            f"'{root_images[0]}'). Training will IGNORE them - images must be "
            f"inside a subfolder named <repeats>_<name>, e.g. '10_mychar'. "
            f"Create that subfolder and move the images (and captions) into it."
        )

    subdirs = [e for e in entries if e.is_dir()]
    if not subdirs and not root_images:
        result["errors"].append(
            "The folder is empty. It needs a subfolder named <repeats>_<name> "
            "(e.g. '10_mychar') containing your images and caption files."
        )
        return result

    for d in sorted(subdirs, key=lambda e: e.name):
        m = _REPEATS_RE.match(d.name)
        if not m:
            # Mistake #2: no repeats prefix -> silently skipped by sd-scripts
            result["warnings"].append(
                f"Subfolder '{d.name}' has no repeats prefix - training will "
                f"SKIP it entirely. Rename it to e.g. '10_{d.name}'."
            )
            continue

        repeats = int(m.group(1))
        concept = m.group(2)
        try:
            files = list(os.scandir(d.path))
        except OSError as e:
            result["warnings"].append(f"Cannot read subfolder '{d.name}': {e}")
            continue

        images = sorted(f.name for f in files if f.is_file()
                        and f.name.lower().endswith(IMAGE_EXTENSIONS))
        captions = {os.path.splitext(f.name)[0] for f in files if f.is_file()
                    and f.name.lower().endswith(ext)}
        image_stems = {os.path.splitext(n)[0] for n in images}
        missing = sorted(image_stems - captions)
        orphans = sorted(captions - image_stems)

        info = {
            "folder": d.name, "repeats": repeats, "concept": concept,
            "images": len(images), "missing_captions": len(missing),
            "orphan_captions": len(orphans),
        }
        result["concepts"].append(info)
        result["total_images"] += len(images)
        result["total_steps_per_epoch"] += len(images) * repeats

        if not images:
            result["warnings"].append(
                f"'{d.name}' contains no images "
                f"(supported: {', '.join(IMAGE_EXTENSIONS)})."
            )
        if missing:
            shown = ", ".join(missing[:3]) + ("..." if len(missing) > 3 else "")
            result["warnings"].append(
                f"'{d.name}': {len(missing)} image(s) have no matching "
                f"'{ext}' caption file ({shown}). They train with an EMPTY "
                f"caption, which usually hurts results."
            )
        if orphans:
            result["warnings"].append(
                f"'{d.name}': {len(orphans)} caption file(s) have no matching "
                f"image - harmless, but probably a naming mismatch."
            )
        if repeats == 0:
            result["warnings"].append(
                f"'{d.name}': repeats is 0 - these images will never be seen. "
                f"Use at least 1."
            )
        elif repeats > 100:
            result["warnings"].append(
                f"'{d.name}': {repeats} repeats is unusually high - each image "
                f"is shown {repeats}x per epoch. Typical: 5-20 for small "
                f"datasets, 1-5 for large ones."
            )

    if not result["concepts"] and not result["errors"]:
        result["errors"].append(
            "No usable subfolder found. Training needs at least one folder "
            "named <repeats>_<name> (e.g. '10_mychar') with images inside."
        )
    if result["concepts"] and result["total_images"] == 0:
        result["errors"].append("Your concept folder(s) contain no images at all.")

    result["ok"] = not result["errors"] and result["total_images"] > 0
    return result


def format_dataset_report(result: dict, heading: str = "─── Dataset Check ───") -> list:
    """Render a check_dataset() result as plain-language summary lines."""
    lines = [heading, ""]

    for c in result["concepts"]:
        cap_note = ""
        if c["missing_captions"]:
            cap_note = f", {c['missing_captions']} caption(s) MISSING"
        lines.append(
            f"  {c['folder']}:  {c['images']} image(s) x {c['repeats']} "
            f"repeats = {c['images'] * c['repeats']} steps/epoch{cap_note}"
        )
    if result["concepts"]:
        lines.append(f"  Total: {result['total_images']} image(s), "
                     f"{result['total_steps_per_epoch']} steps per epoch (x batch size)")
        lines.append("")

    if result["ok"] and not result["warnings"]:
        lines.append("  Folder structure looks good.")
    for e in result["errors"]:
        lines.append(f"  PROBLEM: {e}")
    for w in result["warnings"]:
        lines.append(f"  Warning: {w}")
    lines.append("")
    return lines
