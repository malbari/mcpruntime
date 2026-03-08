# Visual Assets for MCPRuntime / PTC-Bench

This directory contains visual assets for documentation, marketing, and the interactive dashboard.

## Generated Charts

### Benchmark Comparison Charts

| File | Description | Used In |
|------|-------------|---------|
| `ptc_vs_fc_comparison.png` | Side-by-side comparison of PTC vs FC across success rate, execution time, and cost | Main README, benchmark docs |
| `ptc_vs_fc_comparison.svg` | Vector version of above | Documentation, presentations |
| `backend_performance.png` | Backend comparison (Subprocess, OpenSandbox, Docker) | Main README |
| `backend_performance.svg` | Vector version | Documentation |
| `ptc_speedup.png` | PTC speedup factor visualization | Main README, marketing |
| `ptc_speedup.svg` | Vector version | Presentations |
| `multi_metric_radar.png` | Radar chart comparing PTC vs FC across 5 dimensions | Main README |
| `multi_metric_radar.svg` | Vector version | Documentation |
| `task_category_breakdown.png` | Pie chart + bar chart of task categories | Main README, methodology docs |
| `task_category_breakdown.svg` | Vector version | Documentation |

### Streaming Demo Assets

| File | Description | Used In |
|------|-------------|---------|
| `streaming_comparison.png` | Before/after comparison: traditional vs streaming execution | Main README (streaming section) |
| `streaming_comparison.svg` | Vector version | Documentation |
| `streaming_demo.gif` | **Animated** terminal streaming demo | Twitter, presentations, docs |
| `streaming_demo/frame_*.png` | Frame sequence for GIF animation | Marketing materials |

### Usage Demo GIFs

| File | Size | Description | Best For |
|------|------|-------------|----------|
| `install_demo.gif` | 37K | `pip install mcp-agent-runtime` in terminal | README quickstart, docs |
| `quickstart_demo.gif` | 48K | Running benchmark in 60 seconds | README hero section |
| `benchmark_demo.gif` | 66K | PTC vs FC comparison run | README benchmark section |

### Chart Animation GIFs

| File | Size | Description | Best For |
|------|------|-------------|----------|
| `streaming_demo.gif` | 76K | Terminal streaming animation | Twitter, demos, showing live execution |
| `benchmark_comparison.gif` | 632K | Building up the comparison chart | LinkedIn, blog posts |
| `speedup_animation.gif` | 79K | Animated speedup bars | Marketing "PTC is faster" message |
| `radar_animated.gif` | 110K | Pulsing radar chart | Presentations, engagement |

## Generating Assets

### Static Assets
```bash
cd /path/to/mcpruntime

# Generate benchmark charts
python assets/generate_charts.py

# Generate streaming demo frames
python assets/generate_streaming_demo.py

# Generate all static at once
python assets/generate_charts.py && python assets/generate_streaming_demo.py
```

### Animated GIFs
```bash
# Create animated GIFs from static assets (charts)
python assets/create_gifs.py

# Create terminal usage demos
python assets/generate_usage_gifs.py
```

## Requirements

```bash
pip install matplotlib numpy plotly Pillow
```

## Asset Specifications

- **Resolution**: 300 DPI for PNGs (print quality)
- **Formats**: PNG (raster), SVG (vector), GIF (animation)
- **Color Scheme**: 
  - PTC (Code-first): `#2ecc71` (Green)
  - FC (JSON-first): `#3498db` (Blue)
  - Accents: `#e74c3c` (Red), `#f39c12` (Orange)
- **Fonts**: System default (matplotlib)

## Usage Guidelines

### In README.md
```markdown
![Description](assets/chart_name.png)
```

### Animated GIFs in README
```markdown
![Description](assets/streaming_demo.gif)
```

### In Documentation
```markdown
![Description](../assets/chart_name.png)
```

### In Presentations
Use the SVG versions for infinite scalability.

### On Social Media
Use GIFs for engagement, but be mindful of file size limits (Twitter: 5MB, LinkedIn: 8MB).

## Regenerating After Data Updates

When benchmark results change:

1. Update the data in `assets/generate_charts.py`
2. Run the generation scripts
3. Commit new assets
4. Update any text in README that references specific numbers

## Customization

To customize colors or styling, edit the generation scripts:
- `assets/generate_charts.py` - Benchmark charts
- `assets/generate_streaming_demo.py` - Streaming demo frames
- `assets/create_gifs.py` - Chart animations
- `assets/generate_usage_gifs.py` - Terminal usage demos

## TODO

- [x] Create animated GIFs from streaming demo frames
- [ ] Add dark mode variants of charts
- [ ] Create social media optimized versions (Twitter: 1200×675, LinkedIn: 1200×627)
- [ ] Add interactive Plotly versions for web
- [ ] Create short video format (WebM) for browsers
