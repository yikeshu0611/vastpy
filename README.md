# vastpy

用 Python 驱动 macOS 大文件阅读器 **Vast**（与 R 包 [vastR](https://github.com/yikeshu0611/vastR) 共用同一套 localhost JSON API）。

需要已安装 **Vast.app** 到 `/Applications/Vast.app`。

## 安装

### 从 GitHub（推荐）

```bash
pip install "git+https://github.com/yikeshu0611/vastpy.git"
```

或指定版本标签：

```bash
pip install "git+https://github.com/yikeshu0611/vastpy.git@v0.6.34"
```

### 从 Release 资源包

1. 打开 [Releases](https://github.com/yikeshu0611/vastpy/releases)
2. 下载 Assets 中的 `vastpy-x.y.z.zip` 或 `vastpy-x.y.z-py3-none-any.whl`
3. 安装：

```bash
pip install ~/Downloads/vastpy-0.6.34.zip
# 或
pip install ~/Downloads/vastpy-0.6.34-py3-none-any.whl
```

依赖：`pandas>=1.5`，Python ≥ 3.9。

## 快速开始

```python
import vastpy as vast

# 打开大文件（不整表载入内存）
t = vast.open("~/data/huge.csv", delim=",", header=1)
print(t)

# 预览 → pandas.DataFrame
df = t.head(20)

# 筛选
df = t.filter("itemid", "==", "2257526")
df = t.filter("value", "contains", "kg")

# 排序（写出新 TSV，返回新 VastTbl）
t2 = t.sort("charttime", order="desc", max_rows=1000)

# 列索引
idx = t.build_index("itemid", path="itemid.vidx")
t.attach_index("itemid", path=idx)
t.detach_index()

# 其它
vast.status()
vast.goto(100_000)
vast.find("ERROR")
vast.is_running()

# 把 DataFrame 丢进 Vast
vast.view(df, title="preview")
```

也提供与 R 同名的别名：`vast_open`、`vast_filter`、`vast_sort` 等。

## 与 vastR 对照

| R (`vastR`) | Python (`vastpy`) |
|-------------|-------------------|
| `vast_open` | `vast.open` / `vast_open` |
| `filter(t, col == x)` | `t.filter("col", "==", x)` |
| `arrange` / `vast_sort` | `t.sort` / `vast_sort` |
| `vast_build_index` … | `t.build_index` … |
| 返回 `data.frame` | 返回 `pandas.DataFrame` |

## 说明

- API 信息文件与 R 相同：`~/Library/Application Support/com.qo.vast/api.json`（或 MAS Container 路径）。
- 若 Vast 未运行，`open` / 请求时会尝试启动 `/Applications/Vast.app --api`。

## 许可证

MIT
