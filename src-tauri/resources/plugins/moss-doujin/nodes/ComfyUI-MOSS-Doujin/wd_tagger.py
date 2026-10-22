# -*- coding: utf-8 -*-
"""WD eva02-large tagger v3 (SmilingWolf, Apache-2.0) in plain PyTorch - no onnxruntime / timm needed in the engine.
Re-implements timm's eva02_large_patch14_448 (as used by the tagger: avg pool + fc_norm, 2D rope, SwiGLU with inner norm) and
loads the repo's model.safetensors. Architecture after timm's Eva (Ross Wightman, Apache-2.0); checked against the official
model.onnx: same probabilities to 5 decimals, same tags (22 Oct).
Used by the "freeze the look" step: read the clothing of a drawn page as Danbooru tags."""
import csv

import torch
import torch.nn.functional as F
from torch import nn

DIM, DEPTH, HEADS, HIDDEN, PATCH, SIZE = 1024, 24, 16, 2730, 14, 448


def _rope(grid=SIZE // PATCH, head_dim=DIM // HEADS, temperature=10000.0):
    """timm RotaryEmbeddingCat(in_pixels=False, ref_feat_shape = feat_shape): sin / cos of shape (grid*grid, head_dim)"""
    nb = head_dim // 4
    bands = 1.0 / temperature ** (torch.arange(nb, dtype=torch.float32) / nb)
    t = torch.arange(grid, dtype=torch.float32)
    g = torch.stack(torch.meshgrid(t, t, indexing="ij"), -1).unsqueeze(-1) * bands   # (g, g, 2, nb)
    sin, cos = g.sin().reshape(grid * grid, -1), g.cos().reshape(grid * grid, -1)
    return sin.repeat_interleave(2, -1), cos.repeat_interleave(2, -1)


def _rot(x):
    return torch.stack([-x[..., 1::2], x[..., ::2]], -1).reshape(x.shape)


class Block(nn.Module):
    def __init__(self):
        super().__init__()
        self.norm1, self.norm2 = nn.LayerNorm(DIM, eps=1e-6), nn.LayerNorm(DIM, eps=1e-6)
        self.attn = nn.Module()
        self.attn.q_proj, self.attn.k_proj = nn.Linear(DIM, DIM), nn.Linear(DIM, DIM, bias=False)
        self.attn.v_proj, self.attn.proj = nn.Linear(DIM, DIM), nn.Linear(DIM, DIM)
        self.mlp = nn.Module()
        self.mlp.fc1_g, self.mlp.fc1_x = nn.Linear(DIM, HIDDEN), nn.Linear(DIM, HIDDEN)
        self.mlp.norm, self.mlp.fc2 = nn.LayerNorm(HIDDEN, eps=1e-6), nn.Linear(HIDDEN, DIM)

    def forward(self, x, sin, cos):
        B, N, _ = x.shape
        h = self.norm1(x); a = self.attn
        q, k, v = (p(h).reshape(B, N, HEADS, -1).transpose(1, 2) for p in (a.q_proj, a.k_proj, a.v_proj))
        q = torch.cat([q[:, :, :1], q[:, :, 1:] * cos + _rot(q[:, :, 1:]) * sin], 2).type_as(v)   # rope on the patch tokens only
        k = torch.cat([k[:, :, :1], k[:, :, 1:] * cos + _rot(k[:, :, 1:]) * sin], 2).type_as(v)
        x = x + a.proj(F.scaled_dot_product_attention(q, k, v).transpose(1, 2).reshape(B, N, DIM))
        h = self.norm2(x); m = self.mlp
        return x + m.fc2(m.norm(F.silu(m.fc1_g(h)) * m.fc1_x(h)))


class Eva02Tagger(nn.Module):
    def __init__(self, classes):
        super().__init__()
        self.patch_embed = nn.Module(); self.patch_embed.proj = nn.Conv2d(3, DIM, PATCH, PATCH)
        self.cls_token = nn.Parameter(torch.zeros(1, 1, DIM))
        self.pos_embed = nn.Parameter(torch.zeros(1, (SIZE // PATCH) ** 2 + 1, DIM))
        self.blocks = nn.ModuleList(Block() for _ in range(DEPTH))
        self.fc_norm = nn.LayerNorm(DIM, eps=1e-6)
        self.head = nn.Linear(DIM, classes)
        sin, cos = _rope()
        self.register_buffer("sin", sin, persistent=False); self.register_buffer("cos", cos, persistent=False)

    def forward(self, x):   # x: (B, 3, 448, 448) BGR, normalised to [-1, 1] (see prepare)
        x = self.patch_embed.proj(x).flatten(2).transpose(1, 2)
        x = torch.cat([self.cls_token.expand(x.shape[0], -1, -1), x], 1) + self.pos_embed
        sin, cos = self.sin.to(x.dtype), self.cos.to(x.dtype)
        for b in self.blocks:
            x = b(x, sin, cos)
        return torch.sigmoid(self.head(self.fc_norm(x[:, 1:].mean(1))).float())


def load(weights, tags_csv, device="cpu", dtype=torch.float32):
    """-> (model, tag names, tag categories). categories: 0 general, 4 character, 9 rating"""
    from safetensors.torch import load_file
    with open(tags_csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    m = Eva02Tagger(len(rows))
    missing, unexpected = m.load_state_dict(load_file(weights), strict=False)
    if [k for k in missing if k not in ("sin", "cos")] or unexpected:
        raise ValueError(f"WD tagger weights do not match: missing {missing[:5]}, unexpected {unexpected[:5]}")
    return m.to(device, dtype).eval(), [r["name"] for r in rows], [int(r["category"]) for r in rows]


def prepare(img):
    """PIL image -> (1, 3, 448, 448) tensor: white padding to a square, bicubic resize, BGR, [-1, 1] (the tagger's own preprocessing)"""
    from PIL import Image
    img = img.convert("RGBA")
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255)); bg.alpha_composite(img); img = bg.convert("RGB")
    s = max(img.size); sq = Image.new("RGB", (s, s), (255, 255, 255)); sq.paste(img, ((s - img.width) // 2, (s - img.height) // 2))
    sq = sq.resize((SIZE, SIZE), Image.BICUBIC)
    # channels in BGR order: the tagger was trained that way (the official ONNX takes BGR too); RGB turns blue hair brown
    t = torch.frombuffer(bytearray(sq.tobytes()), dtype=torch.uint8).reshape(SIZE, SIZE, 3).flip(-1).permute(2, 0, 1).float() / 255.0
    return ((t - 0.5) / 0.5).unsqueeze(0)


@torch.no_grad()
def tag(model, names, cats, img, threshold=0.35):
    """PIL image -> [(tag, score)] of the general tags above the threshold, best first (underscores -> spaces)"""
    p = model(prepare(img).to(next(model.parameters()).device, next(model.parameters()).dtype))[0].cpu()
    out = [(names[i].replace("_", " "), float(p[i])) for i in range(len(names)) if cats[i] == 0 and p[i] >= threshold]
    return sorted(out, key=lambda t: -t[1])
