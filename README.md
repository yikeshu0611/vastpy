# vastpy

**Author:** ZhangJing \<zj391120@163.com\>

Drive the macOS **Vast** large-file viewer from Python (same localhost JSON API as [vastR](https://github.com/yikeshu0611/vastR)).

Requires **Vast.app** at `/Applications/Vast.app`.

## Install

### From GitHub (recommended)

```bash
pip install "git+https://github.com/yikeshu0611/vastpy.git"
```

Or pin a tag:

```bash
pip install "git+https://github.com/yikeshu0611/vastpy.git@v0.6.34"
```

### From a Release asset

1. Open [Releases](https://github.com/yikeshu0611/vastpy/releases)
2. Download `vastpy-x.y.z.zip` or `vastpy-x.y.z-py3-none-any.whl` from Assets
3. Install:

```bash
pip install ~/Downloads/vastpy-0.6.34.zip
# or
pip install ~/Downloads/vastpy-0.6.34-py3-none-any.whl
```

Requires `pandas>=1.5` and Python ≥ 3.9.

## Quick start

```python
import vastpy as vast

# Open a large file (does not load the whole table into memory)
t = vast.open("~/data/huge.csv", delim=",", header=1)
print(t)

# Preview → pandas.DataFrame
df = t.head(20)

# Filter
df = t.filter("itemid", "==", "2257526")
df = t.filter("value", "contains", "kg")

# Sort (writes a new TSV, returns a new VastTbl)
t2 = t.sort("charttime", order="desc", max_rows=1000)

# Column index
idx = t.build_index("itemid", path="itemid.vidx")
t.attach_index("itemid", path=idx)
t.detach_index()

# Other
vast.status()
vast.goto(100_000)
vast.find("ERROR")
vast.is_running()

# Send a DataFrame to Vast
vast.view(df, title="preview")
```

R-style aliases are also available: `vast_open`, `vast_filter`, `vast_sort`, and so on.

## Mapping to vastR

| R (`vastR`) | Python (`vastpy`) |
|-------------|-------------------|
| `vast_open` | `vast.open` / `vast_open` |
| `filter(t, col == x)` | `t.filter("col", "==", x)` |
| `arrange` / `vast_sort` | `t.sort` / `vast_sort` |
| `vast_build_index` … | `t.build_index` … |
| returns `data.frame` | returns `pandas.DataFrame` |

## Notes

- API info file is the same as R: `~/Library/Application Support/com.zhangjing.Vast/api.json` (or the MAS container path).
- If Vast is not running, `open` / requests try to launch `/Applications/Vast.app --api`.

## License

MIT
