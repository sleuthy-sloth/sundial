# The source artwork, and how much of it is actually original

These eight files are what the derivatives in `frontend/src/assets/` and
`frontend/public/brand/` are made from, and they are **the copies that arrived in the chat —
not the artist's masters.** That is worth knowing before anyone treats them as the archive.

The evidence is in the files themselves. Seven of the eight carry `Software: Picasa` in their
EXIF and XMP blocks, i.e. they were last written by a photo manager that re-encodes and resizes
on export. The dimensions agree: every empty-state pair is 1264×848, which is a resized size
rather than a working size. `ruler-banner-source.jpg` carries a Photoshop block instead and no
Picasa tag, so it may be closer to an export — still a JPEG, still not a master.

| file | dimensions | size | last written by | sha256 |
|---|---|---|---|---|
| `day-complete-dark.jpg` | 1264x848 | 46.3 KB | Picasa | `cd947079164ec4e5…` |
| `day-complete-light.jpg` | 1264x848 | 44.0 KB | Picasa | `affeb1197f09a38c…` |
| `inbox-tray-dark.jpg` | 1264x848 | 87.2 KB | Picasa | `7b79964f702d8d86…` |
| `inbox-tray-light.jpg` | 1264x848 | 82.3 KB | Picasa | `07bf314508ffda17…` |
| `planner-og-source.jpg` | 1424x752 | 65.9 KB | Picasa | `0adc7ea2a6469726…` |
| `ruler-banner-source.jpg` | 2048x246 | 61.9 KB | none recorded | `fd004b550e3df7e4…` |
| `sundial-dark.jpg` | 1264x848 | 50.6 KB | Picasa | `60b846e0416f9c5f…` |
| `sundial-light.jpg` | 1264x848 | 52.2 KB | Picasa | `ac9b2d7576c05ecc…` |

`scripts/make_art.py --check` holds the full hashes and fails if one of these files changes, so
a swap cannot happen quietly.

## If the real originals turn up

Replace the file here under the same name, then:

```bash
env -u PYTHONPATH backend/.venv/bin/python scripts/make_art.py          # regenerate
env -u PYTHONPATH backend/.venv/bin/python scripts/make_art.py --check  # then update the hashes
```

The check will fail first and tell you to update `SOURCES` in `scripts/make_art.py` with the new
hash — that is deliberate, so the recorded provenance always describes the bytes in the tree.

What improves with a better original, concretely:

- **The README banner is upscaled.** The as-received file is 2048px wide and the banner is
  exported at 2560, so those 512px are interpolated. A 2560px-or-wider original removes that.
- **The empty states are downscaled** from 1264 to 800, which is fine, but a master with cleaner
  edges would survive the alpha keying on the sundial better — that picture's ground is made
  transparent so the hour rules run underneath it, and a re-encoded edge is more expensive to
  key cleanly.
- **The social card** is cropped from 1424×752 to 1200×630, so a master with more room around
  the planner would allow a less tight crop.

None of these is a defect in what ships today; they are the ceiling the current copies set.
