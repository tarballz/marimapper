# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

Marimapper maps addressable LEDs into 2D/3D space using a webcam. It flashes each LED individually, detects its position in the camera image, and uses Structure from Motion (pycolmap) to reconstruct the 3D positions across multiple camera angles.

## Commands

```bash
# Install for development (UV recommended)
uv pip install .[develop]
# or: pip install .[develop]

# End-user installation
uv tool install git+https://github.com/TheMariday/marimapper

# Run all tests
pytest .

# Run a single test file
pytest test/test_led_functions.py

# Run a single test by name
pytest test/test_led_functions.py::test_fill_gaps

# Lint (errors only)
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics

# Lint (all warnings)
flake8 . --count --statistics

# Format check
black . --check

# Format in-place
black .
```

## Architecture

The main flow is orchestrated by `Scanner` (`marimapper/scanner.py`), which spins up four separate `multiprocessing.Process` workers connected via typed queues (`marimapper/queues.py`):

```
DetectorProcess ──→ SFM (sfm_process.py)       ──→ VisualiseProcess
               └──→ FileWriterProcess (2D CSVs)     FileWriterProcess (3D CSVs)
SFM ──────────────────────────────────────────────→ DetectorProcess (LED state info)
```

**DetectorProcess** (`detector_process.py`): Controls the camera and LED backend. Flashes each LED, captures the image, and calls `find_led_in_image()` from `detector.py` to locate the LED centroid. Emits `LED2D` objects (normalized u,v coordinates).

**SFM** (`sfm_process.py`): Receives `LED2D` detections, accumulates them across views, and runs `pycolmap.incremental_mapping` (via `sfm.py` + `database_populator.py`) to reconstruct `LED3D` positions. Post-processes with rescale, gap-fill (interpolation), recenter, and normal estimation.

**FileWriterProcess** (`file_writer_process.py`): Writes 2D scans as `<view>.csv` (columns: `index,u,v`) and 3D results. These CSVs are the persistent scan data — re-running marimapper in a directory with existing CSVs will load them automatically.

**VisualiseProcess** (`visualize_process.py`): Renders the 3D point cloud with open3d.

### Critical quirk: multiprocessing start method

`scanner.py` calls `set_start_method("spawn")` at module load time and imports `SFM` first. This is **required** — open3d's `estimate_normals` crashes under Linux's default fork start method. See issue #46. The `conftest.py` also forces spawn for tests.

### Data model

- `LED2D` (`led.py`): a detection — `led_id`, `view_id`, `Point2D` (normalized u,v where u,v ∈ [0,1], origin at top-left, aspect-ratio corrected to square)
- `LED3D` (`led.py`): a reconstructed LED — `led_id`, `Point3D` (position, normal, error), list of `View` (camera positions), list of `LED2D` detections
- `LEDInfo` enum tracks state: `NONE`, `DETECTED`, `RECONSTRUCTED`, `INTERPOLATED`, `MERGED`, `UNRECONSTRUCTABLE`

### Backends

Each backend lives in `marimapper/backends/<name>/` and must implement:

```python
class MyBackend:
    def get_led_count(self) -> int: ...
    def set_led(self, led_index: int, on: bool) -> None: ...
```

Plus two helper functions registered in `marimapper/backends/backend_utils.py`:

```python
def my_backend_set_args(parser): ...          # adds argparse arguments
def my_backend_factory(args) -> partial: ...  # returns partial(MyBackend, ...)
```

The `dummy` backend is used in tests and simulates LEDs without hardware. The `custom` backend lets users point to any Python file implementing the interface. See `docs/backends/backend_writing_guide.md` for full instructions.

### pycolmap version lock

`pycolmap` is pinned to `==3.11.1`. Two-track reconstruction is broken above 3.12 (issue #79). Do not upgrade without verifying.

### Excluded from formatting and coverage

`marimapper/pycolmap_tools/` contains vendored colmap utilities — excluded from `black` formatting and pytest coverage.

## CLI entry points

| Command | Entry point |
|---|---|
| `marimapper` | `marimapper.scripts.scanner_cli:main` |
| `marimapper_check_camera` | `marimapper.scripts.check_camera_cli:main` |
| `marimapper_check_backend` | `marimapper.scripts.check_backend_cli:main` |
| `marimapper_upload_mapping_to_pixelblaze` | `marimapper.scripts.upload_map_to_pixelblaze_cli:main` |

## Pixelblaze pixel mapping reference

This project targets the Pixelblaze exclusively, so the reconstructed 3D coordinates must be in a form a Pixelblaze pattern can consume directly. Keep this model of Pixelblaze mapping fresh.

### What a Pixelblaze map is

A Pixelblaze "map" is a JSON array where each top-level element is one pixel and each inner array is that pixel's coordinates in arbitrary units. Element *i* of the top array is LED index *i* on the strip — order matters; there are no ID fields.

- 1D map: single render (no map needed); default `render(index)`.
- 2D map: `[[x,y], [x,y], ...]` → pattern exports `render2D(index, x, y)`.
- 3D map: `[[x,y,z], [x,y,z], ...]` → pattern exports `render3D(index, x, y, z)`.

Example (4-pixel square, 2D):
```json
[[0,0],[100,0],[100,100],[0,100]]
```

The map can also be produced by a JavaScript function in the mapper tab that takes `pixelCount` and returns the array. The JS runs in the browser (editor-side), so it uses standard JS (e.g., `Math.cos`), not the pattern-language expression dialect.

### Coordinate system and normalization

- Input units in the map are **arbitrary** (mm, inches, raw SfM units — doesn't matter). The Pixelblaze firmware rescales them.
- At runtime, the firmware **auto-scales the map into normalized "world units" in `[0.0, 1.0]` (exclusive)** before calling `render2D`/`render3D`. Patterns therefore assume each axis is in `[0,1]`.
- Two scaling modes, chosen in the mapper tab:
  - **Fill**: each axis stretched independently so the bbox fills `[0,1]^n` (aspect not preserved).
  - **Contain**: uniform scale by the largest axis extent (aspect preserved; shorter axes occupy a sub-range of `[0,1]`).
- Origin convention per the EGL tutorial: `(0,0,0)` top-left-front, `(1,1,1)` bottom-right-back. (In practice, orientation just depends on how your source coordinates are oriented — the firmware only rescales, it does not reorient.)
- Missing/unknown pixels still need an entry (commonly `[0,0,0]`). They will appear clustered at that point, which biases the bbox and therefore the normalization. Prefer to minimize unreconstructed pixels before upload; see `read_coordinates_from_csv` in `marimapper/backends/pixelblaze/upload_map_to_pixelblaze.py` which pads gaps with `[0,0,0]`.

### Axis orientation gotcha (project-specific)

Pixelblaze patterns treat **`y` as vertical** by convention (sky/ground effects, waterfalls, gravity, fire). Marimapper's SfM output is not gravity-aligned; the camera's up-axis may end up as `z`. The upload CLI's `--swap-yz` flag swaps y↔z at upload time so vertically-directional patterns look right. If a user complains that "rain falls sideways" or "fire burns horizontally", suspect axis orientation first.

### Render functions (pattern side)

Exported per-pixel functions, called once per pixel per frame:

```javascript
export function render(index)                 // 1D
export function render2D(index, x, y)         // 2D map present
export function render3D(index, x, y, z)      // 3D map present
```

- A pattern can export multiple variants; the firmware picks the one matching the loaded map.
- `x`, `y`, `z` are already normalized to `[0, 1)`.
- Set the pixel color by calling `hsv(h, s, v)` or `rgb(r, g, b)` inside the function; all channels are `[0, 1]`.
- A 3D-only pattern will not run correctly with a 2D map, and vice versa. Pixelblaze selects the best match but will fall back if the expected variant is missing.

### Per-frame setup: `beforeRender`

```javascript
export function beforeRender(delta) { t1 = time(.1) }
```

Runs once per frame. `delta` is ms since the last frame — use it for frame-rate-independent motion. Precompute globals here (wave phases, noise time, etc.) rather than per-pixel in `render*`.

### Useful built-ins for mapped patterns

- `time(interval)` → sawtooth `[0,1)` that wraps every `65.536 * interval` seconds (so `time(.015)` ≈ 1 Hz).
- `wave(t)` → sine `[0,1]` from a `[0,1]` input.
- `triangle(t)` → triangle `[0,1]` from a `[0,1]` input.
- `perlin(x, y, z, seed)` → 3D Perlin noise in `[-1, 1]`; to remap: `n = n*0.5 + 0.5`.
- `hypot(dx, dy)` / `hypot3(dx, dy, dz)` → radii; center on the unit cube with `hypot3(x-.5, y-.5, z-.5)`.
- Gamma is non-linear to the eye; contrast pops with `v*v` or `v*v*v` before `hsv(..., v)`.
- Globals: `pixelCount`, `index` (inside `render*`).

### Coordinate transforms (pattern side)

Patterns can push/pop up to 31 transforms applied before the firmware walks the map into `render*`:

- `translate(x, y)` / `translate3D(x, y, z)`
- `scale(x, y)` / `scale3D(x, y, z)`
- `rotate(theta)` / `rotateX(theta)` / `rotateY(theta)` / `rotateZ(theta)`

`mapPixels(fn)` iterates the map with `(index, x, y, z)` — handy when a pattern wants to pre-bucket pixels.

### Canonical tiny 3D pattern

```javascript
export function beforeRender(delta) {
  t1 = time(.1)
}
export function render3D(index, x, y, z) {
  r = 1 - hypot3(x - .5, y - .5, z - .5)  // bright at center
  h = (x + y + z) / 3 + t1                 // diagonal rainbow drift
  hsv(h, 1, r * r * r)                     // perceptual gamma
}
```

### Expression-language dialect (pattern code is NOT ordinary JS)

Patterns look like ES6 JS but run on a stripped-down interpreter. Do not assume JS semantics.

- **All numbers are 16.16 fixed-point**: range ≈ `[-32768, +32768]`, resolution `1/65536`. Overflow silently wraps. Bitwise ops act on all 32 bits — `~` zeroes the lower 16 fractional bits, not what JS does.
- **No `let` / `const`** — use `var` (function-local) or bare assignments (implicit globals).
- **Implicit globals**: any variable first assigned without `var` is global, even if assigned inside a function. This is a common footgun — a loop counter named `i` without `var` will stomp globals.
- **No closures**: nested functions cannot see the enclosing function's parameters or locals. Pass everything explicitly or promote to globals.
- **No objects / properties / classes / prototypes.** Arrays are the only dynamic allocation.
- **No `switch`/`case`** — use `else if` chains or a function lookup table.
- **No garbage collection.** Allocate arrays once at top-level, reuse every frame. Don't `array(n)` inside `render*` or `beforeRender`.
- **Arrays are typed-length** (no `push`); use `array(n)`, index directly, track your own length. Iteration helpers: `a.forEach(fn)`, `a.mutate(fn)`, `a.mapTo(dest, fn)`, `a.reduce(fn, init)`, `a.sum()`, `a.sort()`, `a.sortBy(fn)`.

### UI controls (export function names are magic)

The editor generates controls from specially-named exports. Both the initial saved value and every user change call the function.

| Export prefix | Control | Args |
|---|---|---|
| `sliderX(v)` | Slider | `v` in `[0,1]` |
| `hsvPickerX(h,s,v)` | HSV color picker | each `[0,1]` |
| `rgbPickerX(r,g,b)` | RGB color picker | each `[0,1]` |
| `toggleX(on)` | Toggle | boolean |
| `triggerX()` | Momentary button | none |
| `inputNumberX(v)` | Signed decimal input | number |
| `showNumberX()` | Read-back display | returns number |
| `gaugeX()` | Bar gauge | returns `[0,1]` |

### Audio / sensor-board globals

If an "expander / sensor board" is attached, these globals are auto-populated each frame:

```javascript
export var frequencyData        // 32-bin FFT, ~12.5 Hz – 10 kHz
export var energyAverage        // overall volume
export var maxFrequency, maxFrequencyMagnitude
export var accelerometer        // [x, y, z] ±16g
export var light                // ambient
export var analogInputs         // [A0..A4]
```

Touching any of these in a pattern silently does nothing on controllers without the sensor board — it's cheap to include as an optional effect modulator.

### Color / palette

- `hsv(h, s, v)` / `rgb(r, g, b)` — all channels `[0,1]`. `hsv` gets 5 bits of extra brightness headroom for dim scenes.
- `setPalette([pos, r, g, b, pos, r, g, b, ...])` then `paint(t, [brightness])` — idiomatic for cohesive gradients, beats hand-chosen hues.
- Perlin variants for textured color: `perlin`, `perlinFbm`, `perlinRidge`, `perlinTurbulence`, `setPerlinWrap(x,y,z)`. All return `[-1, 1]` — remap with `n*0.5 + 0.5`.

### Pattern idioms seen in real-world patterns

From reading `zranger1/PixelblazePatterns/2D_and_3D`:

1. **Centered radius** — the go-to move for "does this pixel belong to this shape": since axes are `[0,1)`, the center is always `(0.5, 0.5[, 0.5])`:
   ```javascript
   r = hypot(x - 0.5, y - 0.5) * 2        // 2D, scaled so corners≈√2
   r = hypot3(x-.5, y-.5, z-.5)           // 3D
   ```
2. **Unit-cube bouncing objects** — position, velocity, and radius all live in normalized space (`bouncer3D.js` uses `ballSize ≈ 0.06` for 2D, `ballSize3D = ballSize*4` for 3D because volumetric density falls off fast).
3. **Grid-indexed 2D patterns** convert normalized coords back to integer cells: `ix = floor(x * width); iy = floor(y * height)`. The pattern must know or be configured with `width`/`height`. These break on non-rectangular (e.g., SfM) maps — skip them when recommending patterns for scanned layouts.
4. **Polar coordinates** — `atan2(y-.5, x-.5)` then quantize: `angle = floor(((atan2(y,x)+PI)/4)*32) % 32` is common for audio-radial effects.
5. **Per-axis map-presence checks** — `has2DMap()`, `has3DMap()`, `pixelMapDimensions()` let a single pattern branch between `render`, `render2D`, and `render3D`. Preferred over shipping separate patterns.

### Uploading maps via `pixelblaze-client` (what we actually call)

The library is bundled in this project's venv as `pixelblaze` (see `upload_map_to_pixelblaze.py`). Key methods:

- `setMapCoordinates(list_of_lists)` — the one-shot entry point we use. Internally:
  1. Writes the list (stringified Python/JS) to `/pixelmap.txt` on the device (the editable Mapper-tab text).
  2. Compiles a binary blob via `createMapData(...)` and writes `/pixelmap.dat`.
  3. Sends a WebSocket `putPixelMap` binary frame, then `{"savePixelMap": true}` to persist to flash.
- `setMapFunction(jsText)` — same as above but runs the JS through an embedded MiniRacer first to produce the coordinate list. Useful if the source of truth is a generator function.
- `setMapData(bytes, saveToFlash=True)` — raw binary path, bypasses compilation.
- `getMapCoordinates()` — reads `/pixelmap.dat` back and returns coordinates already **normalized to `[0,1]`** (firmware stores them post-scale). So round-tripping through the Pixelblaze loses the original units — don't rely on it as ground truth.
- Other useful methods when scripting: `getPatternList()`, `setActivePattern(id)`, `setActivePatternByName(name)`, `getPixelCount()`, `setBrightnessSlider(v)`, `controlExists(name)`.

Implications:
- Our current upload sends a Python `list` whose `str()` representation happens to parse as valid JS array literal. If anyone refactors to numpy arrays or tuples, the `setMapFunction` path (via `str(coords)`) will break; prefer `json.dumps` + `setMapFunction` or keep using `setMapCoordinates` with plain nested lists.
- `setMapCoordinates` commits to flash automatically. That's a device-state change — fine for the CLI (user opts in) but keep the confirmation prompt in `upload_map_to_pixelblaze`.

### Community pattern references

- Official docs: https://electromage.com/docs (the electromage site is a SPA — `WebFetch` gets a blank "Loading…" page; fetch `README.mapper.md` / `README.expressions.md` from `raw.githubusercontent.com/simap/pixelblaze/master/` instead).
- EGL tutorials: https://www.evilgeniuslabs.org/tutorials/pixelblaze3d (part1 = coordinates + render3D; part2 = beforeRender, gamma, waves, perlin).
- Example patterns: https://github.com/zranger1/PixelblazePatterns — folders `1D`, `2D_and_3D`, `multisegment`, `toolkit`. Notably `bouncer3D.js`, `radial-rainbow-2d.js`, and `raindrops2d.js` are good references for different idioms (unit-cube primitives, polar, grid-indexed).
- Client library source: `.venv/lib/python3.10/site-packages/pixelblaze/pixelblaze.py` — the library we upload through. Docstrings are thorough; read them before guessing at API shape.

### Implications for marimapper

- 3D CSV columns are `index,x,y,z`; upload uses that ordering verbatim into the Pixelblaze map JSON. Do not re-sort — index position in the JSON **is** the LED index.
- Gap handling: missing LED indices must be filled with a placeholder coordinate so positional indexing stays correct. The current choice of `[0,0,0]` drags the bbox; an alternative is the centroid of known LEDs, but changing it alters the normalized output — coordinate with the user before switching.
- Normalization happens on the Pixelblaze side, so we can upload raw SfM units. No need to pre-scale into `[0,1]`, but do make sure units are consistent across axes when recommending "Contain" vs "Fill".
- When adding new export formats or map transformations, remember the invariant: *position in array = LED index*.
